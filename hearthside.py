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
- Tab completes file paths, from the folder you started in.

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
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout

try:                                                     # code blocks in colour, when Pygments is there
    from pygments import highlight
    from pygments.formatters import TerminalFormatter
    from pygments.lexers import get_lexer_by_name
    from pygments.util import ClassNotFound
except ImportError:                                      # pragma: no cover (it's a dependency)
    highlight = None

__version__ = "0.2.0"

# Shift+Enter, where the terminal sends it differently from Enter (kitty's and WezTerm's CSI u, xterm's
# modifyOtherKeys): read as Ctrl+J, which starts a new line
ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlJ)
ANSI_SEQUENCES.setdefault("\x1b[27;2;13~", Keys.ControlJ)

HELP = ("-- chatting with {name}: Enter sends, Alt+Enter (or Shift+Enter) for a new line; a paste stays one message; "
        "Tab completes /commands and paths{f1}; Ctrl-C clears, Ctrl-D leaves --")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
HEADER_RE = re.compile(r"^\d\d:\d\d(:\d\d)? \S+> ")          # a new message starts ("14:02:11 s1> ..."): any fence ends


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
        if self.fenced and self.lexer is not None:
            return highlight(plain, self.lexer, TerminalFormatter()).rstrip("\n")
        return line


def keys(local: dict) -> KeyBindings:
    kb = KeyBindings()

    @kb.add("f1")
    def _help(event):
        if "/help" in local:
            text = local["/help"]("")
            run_in_terminal(lambda: print(text, flush=True))

    @kb.add("enter")
    def _send(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    @kb.add("c-j")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    return kb


def chat(name: str, recent: list[str], poll, send, *, status=None, history: str | None = None,
         commands=(), local: dict | None = None, arguments: dict | None = None, interval: float = 0.3) -> None:
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
    for line in recent:
        print(paint(line))
    print(HELP.format(name=name, f1="; F1 for help" if "/help" in local else ""), flush=True)
    done = threading.Event()

    def printer():
        while not done.is_set():
            try:
                for line in poll():
                    print(paint(line), flush=True)
            except Exception:                        # a hiccup reading the agent's output never ends the chat
                pass
            done.wait(interval)

    with patch_stdout(raw=True):                     # output goes above the prompt, colours intact
        threading.Thread(target=printer, daemon=True).start()
        try:
            while True:
                try:
                    text = session.prompt("> ")
                except KeyboardInterrupt:            # Ctrl-C: what you typed is dropped, the chat stays
                    continue
                except EOFError:                     # Ctrl-D on an empty line: leave
                    break
                word, _, rest = text.strip().partition(" ")
                if word.lower() in local:
                    answer = local[word.lower()](rest)
                    if answer:
                        print(answer, flush=True)
                elif text.strip():
                    send(text)
        finally:
            done.set()
