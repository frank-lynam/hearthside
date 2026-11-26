# Working on hearthside

- **One module, `hearthside.py`; one dependency, prompt_toolkit.** It's hobkin's optional chat terminal; hobkin's
  own plain chat is the fallback and must keep working without it.
- **It never imports hobkin.** The contract is `chat(name, recent, poll, send, status=, history=, commands=,
  local=)`; hobkin calls it from `chat_terminal`. Change the contract only with hobkin in step, and keep it
  backwards compatible: an older hobkin may call a newer hearthside.
- **Never full-screen:** scrollback and copying out of the terminal are why it's inline.
- **Tests:** `python3 tests/test_hearthside.py` (prompt_toolkit's pipe input; no terminal). Add a check for every
  behaviour you change.
- GitHub: `frank-lynam/hearthside` (remote `origin` uses the `github-hearthside` SSH alias). Commit and push
  finished work. PyPI `hearthside`: a GitHub release publishes it.
