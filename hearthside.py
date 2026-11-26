"""hearthside: the chat terminal for hobkin, the seat by the fire where you talk to it.

hobkin itself is one stdlib-only file, and its own chat is deliberately plain: lines in, output printed as it comes.
Install hearthside beside it (`pip install hearthside`) and `hobkin chat` uses this instead:

- an input editor that's yours: Enter sends, Alt+Enter (or Shift+Enter, where the terminal tells them apart, or
  Ctrl+J) starts a new line, a paste lands as one block you can edit before sending, up arrow walks history;
- output appears above what you're typing and never through it;
- a status bar with what the agent's doing;
- the /commands complete with Tab.

It isn't full-screen: your terminal's scrollback, search and copying all work as usual.

hearthside never imports hobkin. Anything that can hand it these callables can use it (see `chat`).
"""
from __future__ import annotations

import os
import threading

from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory, InMemoryHistory
from prompt_toolkit.input.ansi_escape_sequences import ANSI_SEQUENCES
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.patch_stdout import patch_stdout

__version__ = "0.1.0"

# Shift+Enter, where the terminal sends it differently from Enter (kitty's and WezTerm's CSI u, xterm's
# modifyOtherKeys): read as Ctrl+J, which starts a new line
ANSI_SEQUENCES.setdefault("\x1b[13;2u", Keys.ControlJ)
ANSI_SEQUENCES.setdefault("\x1b[27;2;13~", Keys.ControlJ)

HELP = ("-- chatting with {name}: Enter sends, Alt+Enter (or Shift+Enter) for a new line; a paste stays one message; "
        "Tab completes /commands; Ctrl-C clears, Ctrl-D leaves --")


class Commands(Completer):
    """The /commands, completed at the start of a one-line message."""

    def __init__(self, words):
        self.words = sorted(set(words))

    def get_completions(self, document, complete_event):
        typed = document.text_before_cursor
        if typed.startswith("/") and " " not in typed and "\n" not in typed:
            for w in self.words:
                if w.startswith(typed.lower()):
                    yield Completion(w, -len(typed))


def keys() -> KeyBindings:
    kb = KeyBindings()

    @kb.add("enter")
    def _send(event):
        event.current_buffer.validate_and_handle()

    @kb.add("escape", "enter")
    @kb.add("c-j")
    def _newline(event):
        event.current_buffer.insert_text("\n")

    return kb


def chat(name: str, recent: list[str], poll, send, *, status=None, history: str | None = None,
         commands=(), local: dict | None = None, interval: float = 0.3) -> None:
    """Talk to an agent until Ctrl-D.

    name     who you're talking to (shown in the help line)
    recent   lines to show first (they may carry ANSI colour)
    poll()   new output lines since the last call (called from a background thread every `interval` seconds)
    send(t)  send a message; `t` may hold newlines (a multi-line message is one message)
    status() what the agent's busy with, or None when it's waiting for you (the status bar)
    history  a file for input history (hearthside's own format: don't share one with readline)
    commands words to complete with Tab (/stop, /pause...)
    local    {"/word": fn(rest) -> str}: commands answered here and never sent; what fn returns is printed
    """
    local = {k.lower(): v for k, v in (local or {}).items()}
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
        history=hist, multiline=True, key_bindings=keys(), completer=Commands(list(commands) + list(local)),
        complete_while_typing=True, prompt_continuation=lambda width, n, soft: "  ",
        bottom_toolbar=(lambda: ANSI("\x1b[2m" + (status() or f"{name} is waiting for you") + "\x1b[0m"))
        if status else None,
        refresh_interval=0.5 if status else None)
    for line in recent:
        print(line)
    print(HELP.format(name=name), flush=True)
    done = threading.Event()

    def printer():
        while not done.is_set():
            try:
                for line in poll():
                    print(line, flush=True)
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
