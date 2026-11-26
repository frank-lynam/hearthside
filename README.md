# hearthside

The chat terminal for [hobkin](https://github.com/frank-lynam/hobkin): the seat by the fire where you talk to it.

hobkin is one standard-library file, and its own `hobkin chat` is deliberately plain, for when nothing else can
be installed: lines in, output printed as it comes. Install hearthside beside it and `hobkin chat` uses it instead:

```bash
pip install hearthside        # or: pip install "hobkin[chat]"
hobkin chat
```

- **Input that's yours.** Enter sends. Alt+Enter starts a new line (so does Shift+Enter, in terminals that tell
  it apart from Enter: kitty, WezTerm, recent iTerm2 and Windows Terminal; Ctrl+J works everywhere). A paste
  lands as one block you can edit before sending, however many lines it has. Up arrow walks your history.
- **Output above, never through.** What the agent says appears above your prompt while you type.
- **A status bar** with what the agent's doing right now.
- **Tab completes the /commands.**
- **Not full-screen,** on purpose: your terminal's scrollback, search and copying work as they always do. To copy
  a code block the agent wrote, `/copy` (hobkin's) puts it on your clipboard; `/copy 2` the one before.

Ctrl-C clears what you've typed, Ctrl-D leaves. `HOBKIN_CHAT=plain hobkin chat` gives you hobkin's plain chat even
with hearthside installed.

## For other programs

hearthside never imports hobkin. Anything that can hand it a few callables can use it:

```python
import hearthside

hearthside.chat(
    "s1",                       # who you're talking to
    recent_lines,               # shown first (ANSI colour is fine)
    poll,                       # poll() -> new output lines; called from a thread
    send,                       # send(text): a message, newlines and all
    status=status,              # status() -> what it's doing, or None when it's waiting for you
    history="~/.my_history",    # input history (hearthside's own format)
    commands=["/stop", "/pause"],
    local={"/copy": copy},      # answered here, never sent: fn(rest) -> text to print
)
```

## Development

`python3 tests/test_hearthside.py` drives `chat` with typed keys (no terminal needed). Releases: publishing a GitHub
release `vX.Y.Z` matching `__version__` uploads to PyPI.
