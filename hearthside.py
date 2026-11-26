"""hearthside: the chat terminal for hobkin, the seat by the fire where you talk to it.

hobkin itself is one stdlib-only file, and its own chat is deliberately plain: lines in, output printed as it comes.
Install hearthside beside it (`pip install hearthside`) and `hobkin chat` uses this instead:

- an input editor that's yours: Enter sends, Alt+Enter (or Shift+Enter, where the terminal tells them apart, or
  Ctrl+J) starts a new line, a paste lands as one block you can edit before sending, up arrow walks history;
- output appears above what you're typing and never through it;
- a status bar with what the agent's doing;
- the /commands complete as you type, each with what it does beside it, and so do their arguments where the
  program offers them (hobkin's /model: a menu of your models, with their services and any rate limit);
- F1 shows the help;
- code blocks in what the agent says are coloured by their language (Pygments);
- Tab completes file paths, from the folder you started in;
- PgUp opens the whole conversation to scroll back through, and Ctrl-F to search it (n and N for the next and
  the one before); Esc or q comes back to the chat, with what you were typing;
- tables the agent writes are lined up in columns, and list bullets tidied;
- a half-written message is kept: leave, or lose the connection, and it's there when you come back.

It isn't full-screen: your terminal's scrollback, search and copying all work as usual.

hearthside never imports hobkin. Anything that can hand it these callables can use it (see `chat`).
"""
from __future__ import annotations

import os
import re
import threading

from prompt_toolkit import PromptSession
from prompt_toolkit.application import run_in_terminal
from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import is_searching
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.page_navigation import load_page_navigation_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.patch_stdout import patch_stdout
from prompt_toolkit.search import SearchDirection, start_search
from prompt_toolkit.utils import get_cwidth
from prompt_toolkit.widgets import SearchToolbar

try:                                                     # code blocks in colour, when Pygments is there
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
except ImportError:                                      # pragma: no cover (it's a dependency)
    highlight = None

__version__ = "0.3.0"

# Shift+Enter, where the terminal sends it differently from Enter (kitty's and WezTerm's CSI u, xterm's
# modifyOtherKeys): read as Ctrl+J, which starts a new line
ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlJ)
ANSI_SEQUENCES.setdefault("\x1b[27;2;13~", Keys.ControlJ)

HELP = ("-- chatting with {name}: Enter sends, Alt+Enter (or Shift+Enter) for a new line; a paste stays one message; "
        "Tab completes /commands and paths{f1}; Ctrl-C clears, Ctrl-D leaves --")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
HEADER_RE = re.compile(r"^\d\d:\d\d(:\d\d)? \S+> ")          # a new message starts ("14:02:11 s1> ..."): any fence ends
TABLE_RE = re.compile(r"^\s*\|.*\|\s*$")                        # a Markdown table row
RULE_RE = re.compile(r"^\s*\|(\s*:?-{2,}:?\s*\|)+\s*$")          # its |---|---| line
BULLET_RE = re.compile(r"^(\s*)[-*] (?=\S)")                     # a list item
SCROLL, SEARCH = object(), object()                              # what PgUp and Ctrl-F hand the chat loop


class Completions(Completer):
    """At the start of a one-line message, the /commands (with what each does) and, after one, its arguments
    where the program offers them; anywhere, on Tab, the file path being typed."""

    def __init__(self, commands: dict, arguments: dict):
        self.commands, self.arguments = commands, arguments
        self.paths = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        typed = document.text_before_cursor
        if typed.startswith("/") and "\n" not in typed:
            cmd, space, rest = typed.partition(" ")
            if not space:
                for w in sorted(self.commands):
                    if w.startswith(cmd.lower()):
                        yield Completion(w, -len(cmd), display_meta=self.commands[w] or None)
            elif cmd.lower() in self.arguments and " " not in rest:
                try:
                    choices = list(self.arguments[cmd.lower()]())
                except Exception:                     # the program's list failing never breaks typing
                    choices = []
                low = rest.lower()
                for value, meta in choices:
                    if value.lower().startswith(low) or (low and low in value.lower()):
                        yield Completion(value, -len(rest), display_meta=meta or None)
                return
        if complete_event.completion_requested:      # paths only on Tab: no menu popping up mid-sentence
            word = re.split(r"[\s`'\"(<\[]", typed)[-1]
            if word and ("/" in word or word.startswith(("~", "."))):
                yield from self.paths.get_completions(Document(word, len(word)), complete_event)


class Painter:
    """Colours the code blocks in output lines by their fence's language; everything else passes as it is."""

    def __init__(self):
        self.lexer, self.fenced = None, False

    def __call__(self, line: str) -> str:
        if highlight is None:
            return line
        plain = ANSI_RE.sub("", line)
        head = HEADER_RE.match(plain)
        if head:                                       # a message starting with its fence: "14:02 s1> ```bash"
            self.fenced, plain = False, plain[head.end():]
        if plain.lstrip().startswith("```"):
            self.fenced = not self.fenced
            if self.fenced:
                lang = plain.strip()[3:].strip().split(" ")[0]
                try:
                    self.lexer = get_lexer_by_name(lang) if lang else None
                except ClassNotFound:
                    self.lexer = None
            return line
        if self.fenced:
            return highlight(plain, self.lexer, TerminalFormatter()).rstrip("\n") if self.lexer is not None else line
        return BULLET_RE.sub(lambda m: m.group(1) + "• ", line, count=1)

    def feed(self, lines: list[str], width: int = 100) -> list[str]:
        """Lines as they're shown: each painted, and a Markdown table (outside code) lined up in columns, when
        its rows came together and it fits `width`; otherwise as it was written."""
        out, table = [], []
        for line in lines + [None]:                  # None: the end, flushing a table still being collected
            plain = ANSI_RE.sub("", line) if line is not None else ""
            if line is not None and not self.fenced and TABLE_RE.match(plain) and not HEADER_RE.match(plain):
                table.append(plain)
                continue
            if table:
                out += table_lines(table, width)
                table = []
            if line is not None:
                out.append(self(line))
        return out


def table_lines(rows: list[str], width: int) -> list[str]:
    """A Markdown table, lined up: cells padded to their column's width (wide characters counted as two), the
    header bold, its rule drawn. As written if it's ragged or too wide for the terminal."""
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows if not RULE_RE.match(r)]
    ruled = any(RULE_RE.match(r) for r in rows)
    if len({len(r) for r in cells}) != 1:
        return rows
    widths = [max(get_cwidth(r[i]) for r in cells) for i in range(len(cells[0]))]
    if sum(widths) + 3 * len(widths) + 1 > width:
        return rows
    fmt = lambda r: "│ " + " │ ".join(c + " " * (w - get_cwidth(c)) for c, w in zip(r, widths)) + " │"
    out = []
    for i, r in enumerate(cells):
        out.append("\x1b[1m" + fmt(r) + "\x1b[0m" if i == 0 and ruled else fmt(r))
        if i == 0 and ruled:
            out.append("├" + "┼".join("─" * (w + 2) for w in widths) + "┤")
    return out


class Transcript(Lexer):
    """The scrollback view's colours: who's talking bold, code fences dim, search matches by prompt_toolkit."""

    def lex_document(self, document):
        def line(n):
            text = document.lines[n]
            head = HEADER_RE.match(text)
            if head:
                return [("bold", text[:head.end()]), ("", text[head.end():])]
            return [("#888888", text)] if text.lstrip().startswith("```") else [("", text)]
        return line


def scrollback(lines: list[str], search: bool = False, width: int = 100) -> None:
    """The conversation, full screen: PgUp/PgDn and the arrows scroll, Ctrl-F searches (Enter to stop there, n and
    N for the next and the one before), Esc or q goes back. Starts at the end, where you were."""
    text = "\n".join(ANSI_RE.sub("", ln) for ln in Painter().feed(list(lines), width))   # tables lined up here too
    toolbar = SearchToolbar(ignore_case=True)
    buf = Buffer(document=Document(text, len(text)), read_only=True)
    control = BufferControl(buffer=buf, search_buffer_control=toolbar.control, lexer=Transcript())
    kb = KeyBindings()

    @kb.add("escape", filter=~is_searching)
    @kb.add("q", filter=~is_searching)
    def _back(event):
        event.app.exit()

    @kb.add("c-f", filter=~is_searching)
    @kb.add("/", filter=~is_searching)
    def _search(event):
        start_search(control, direction=SearchDirection.BACKWARD)

    @kb.add("n", filter=~is_searching)
    def _next(event):
        buf.apply_search(event.app.current_search_state, include_current_position=False)

    @kb.add("N", filter=~is_searching)
    def _previous(event):
        buf.apply_search(~event.app.current_search_state, include_current_position=False)

    keys_line = FormattedTextControl(" PgUp/PgDn · Ctrl-F search, n/N · Esc or q: back to the chat")
    app = Application(layout=Layout(HSplit([Window(control, wrap_lines=True), toolbar,
                                            Window(keys_line, height=1, style="reverse")]), focused_element=control),
                      key_bindings=merge_key_bindings([load_page_navigation_bindings(), kb]), full_screen=True)
    app.ttimeoutlen, app.timeoutlen = 0.05, 0.25      # Esc answers at once (nothing here waits for an Alt+key)
    if search:
        app.pre_run_callables.append(lambda: start_search(control, direction=SearchDirection.BACKWARD))
    app.run()


def keys(local: dict) -> KeyBindings:
    kb = KeyBindings()

    @kb.add("f1")
    def _help(event):
        if "/help" in local:
            text = local["/help"]("")
            run_in_terminal(lambda: print(text, flush=True))

    @kb.add("pageup")
    def _scroll(event):
        event.app.erase_when_done = True             # what you're typing comes back after, not twice
        event.app.exit(result=SCROLL)

    @kb.add("c-f")
    def _find(event):
        event.app.erase_when_done = True
        event.app.exit(result=SEARCH)

    @kb.add("enter")
    def _send(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    @kb.add("c-j")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    return kb


def chat(name: str, recent: list[str], poll, send, *, status=None, history: str | None = None,
         commands=(), local: dict | None = None, arguments: dict | None = None, backlog=None,
         interval: float = 0.3) -> None:
    """Talk to an agent until Ctrl-D.

    name     who you're talking to (shown in the help line)
    recent   lines to show first (they may carry ANSI colour)
    poll()   new output lines since the last call (called from a background thread every `interval` seconds)
    send(t)  send a message; `t` may hold newlines (a multi-line message is one message)
    status() what the agent's busy with, or None when it's waiting for you (the status bar)
    history  a file for input history (hearthside's own format: don't share one with readline)
    commands words to complete (/stop, /pause...), or {word: what it does}, shown beside it
    local    {"/word": fn(rest) -> str}: commands answered here and never sent; what fn returns is printed.
             "/help" here is also F1.
    arguments {"/word": fn() -> [(value, what it is)]}: what can follow that command, offered as a menu
    backlog() the whole conversation so far, as lines, for scrolling back (PgUp): default, what this chat has shown
    A message you've half written is kept beside the history file (HISTORY.draft) until it's sent or cleared.
    """
    local = {k.lower(): v for k, v in (local or {}).items()}
    commands = dict(commands) if isinstance(commands, dict) else {c: "" for c in commands}
    commands.update({c: commands.get(c, "") for c in local})
    paint = Painter()
    hist = InMemoryHistory()
    if history:
        try:
            hist = FileHistory(history)
            if not os.path.exists(history):
                open(history, "a").close()
            os.chmod(history, 0o600)
        except OSError:
            hist = InMemoryHistory()
    session = PromptSession(
        history=hist, multiline=True, key_bindings=keys(local),
        completer=Completions({k.lower(): v for k, v in commands.items()},
                              {k.lower(): v for k, v in (arguments or {}).items()}),
        complete_while_typing=True, prompt_continuation=lambda width, n, soft: "  ",
        bottom_toolbar=(lambda: ANSI("\x1b[2m" + (status() or f"{name} is waiting for you") + "\x1b[0m"))
        if status else None,
        refresh_interval=0.5 if status else None)
    width = lambda: max(20, os.get_terminal_size().columns - 1) if os.isatty(1) else 100
    shown = list(recent)                             # what this chat has shown, for the scrollback view
    for line in paint.feed(list(recent), width()):
        print(line)
    print(HELP.format(name=name, f1="; F1 for help" if "/help" in local else "") +
          " (PgUp scrolls back, Ctrl-F searches)", flush=True)
    done, paging = threading.Event(), threading.Event()
    draft_file = history + ".draft" if history else None

    def draft(text=None):
        """The half-written message: read it (no text), keep it, or (empty) drop it."""
        if not draft_file:
            return ""
        try:
            if text is None:
                with open(draft_file, encoding="utf-8") as f:
                    return f.read()
            if text.strip():
                fd = os.open(draft_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(text)
            elif os.path.exists(draft_file):
                os.remove(draft_file)
        except OSError:
            pass
        return ""
    session.default_buffer.on_text_changed += lambda buf: draft(buf.text)

    def printer():
        held = []
        while not done.is_set():
            try:
                new = poll()
                shown.extend(new)
                held += new
                if held and not paging.is_set():     # while the scrollback view is open, output waits
                    for line in paint.feed(held, width()):
                        print(line, flush=True)
                    held = []
            except Exception:                        # a hiccup reading the agent's output never ends the chat
                pass
            done.wait(interval)

    with patch_stdout(raw=True):                     # output goes above the prompt, colours intact
        threading.Thread(target=printer, daemon=True).start()
        try:
            typed = draft()                          # what was half written last time
            while True:
                try:
                    text = session.prompt("> ", default=typed)
                except KeyboardInterrupt:            # Ctrl-C: what you typed is dropped, the chat stays
                    typed = draft("")
                    continue
                except EOFError:                     # Ctrl-D on an empty line: leave
                    break
                if text is SCROLL or text is SEARCH:   # PgUp, Ctrl-F: the scrollback view, then back where you were
                    session.app.erase_when_done = False
                    typed = session.default_buffer.text
                    paging.set()
                    try:
                        lines = backlog() if backlog else shown
                    except Exception:
                        lines = shown
                    try:
                        scrollback(lines, search=text is SEARCH, width=width())
                    finally:
                        paging.clear()
                    continue
                typed = draft("")
                word, _, rest = text.strip().partition(" ")
                if word.lower() in local:
                    answer = local[word.lower()](rest)
                    if answer:
                        print(answer, flush=True)
                elif text.strip():
                    send(text)
        finally:
            done.set()
