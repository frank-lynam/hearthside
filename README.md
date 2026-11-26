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
- **Help on F1** (and `/help`): every command, a line each; `/help model` for one in full.
- **F2 goes round how much the chat shows:** hobkin's `talk` (what's said), `chores` (and its housekeeping),
  `tools` (and what it runs) and `full` (everything, output too); `/show LEVEL` picks one.
- **Commands complete as you type,** with what each does beside it. **`/model` then Tab is a model picker:** your
  configured models, each with its service, the one in use, and any rate limit it's waiting out. Pick the same model
  on another service when one runs out of quota, and the switch happens at once.
- **Code blocks in colour,** by the language their fence names (Pygments).
- **Tab completes file paths** as you type them in a message, from the folder you started the chat in.
- **Scroll back and search:** PgUp opens the whole conversation full-screen (PgUp/PgDn and the arrows to move),
  Ctrl-F searches it (Enter to stop at a match, n and N for the next and the one before), and Esc or q brings you
  back to the chat with what you were typing. Ctrl-F from the chat opens it searching.
- **Tables lined up** in columns, and list bullets tidied, in the chat and in the scrollback.
- **Drafts kept:** a half-written message survives leaving the chat or a dropped connection, and is there to
  finish when you come back (beside the history file, as `HISTORY.draft`, until it's sent or cleared with Ctrl-C).
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
    commands={"/stop": "finish and exit"},   # or just a list of words
    local={"/copy": copy, "/help": help},     # answered here, never sent: fn(rest) -> text to print ("/help" is F1)
    arguments={"/model": models},             # models() -> [(value, what it is)]: the menu after "/model "
    backlog=whole_conversation,               # backlog() -> lines, for PgUp (default: what this chat has shown)
)
```

## Development

`python3 tests/test_hearthside.py` drives `chat` with typed keys (no terminal needed). Releases: publishing a GitHub
release `vX.Y.Z` matching `__version__` uploads to PyPI.
