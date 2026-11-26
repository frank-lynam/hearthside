"""Tests: hearthside.chat driven by typed keys (prompt_toolkit's pipe input), no terminal needed.

    python3 tests/test_hearthside.py
"""
import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import hearthside  # noqa: E402
from prompt_toolkit.application import create_app_session  # noqa: E402
from prompt_toolkit.input import create_pipe_input  # noqa: E402
from prompt_toolkit.output import DummyOutput  # noqa: E402

failed = False
HELPED = []


def check(name, cond, info=""):
    global failed
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {info!r}"))
    failed |= not cond


def run(keys: list[str], **kw):
    """Type each chunk of keys (a pause between them, as a person would), then Ctrl-D; what was sent,
    what local commands got, and whether polling ran."""
    sent, local_got, polled = [], [], []
    hist = os.path.join(tempfile.mkdtemp(), "history")

    def poll():
        polled.append(1)
        return ["\x1b[35ms1>\x1b[0m hello"] if len(polled) == 1 else []
    with create_pipe_input() as inp, create_app_session(input=inp, output=DummyOutput()):
        def typist():
            time.sleep(0.3)
            for k in keys + ["\x04"]:
                inp.send_text(k)
                time.sleep(0.15)
        threading.Thread(target=typist, daemon=True).start()
        hearthside.chat("s1", ["earlier"], poll, sent.append, status=lambda: "s1 is thinking", history=hist,
                        commands=["/stop", "/pause"], local={"/copy": lambda rest: local_got.append(rest) or "copied",
                               "/help": lambda rest: HELPED.append(rest) or "the help"},
                        interval=0.05, **kw)
    return sent, local_got, polled, hist


sent, local_got, polled, hist = run(["hello there\r"])
check("Enter sends the line", sent == ["hello there"], sent)
check("output is polled while you type", len(polled) >= 2, polled)
check("history is kept in its file", "hello there" in open(hist).read())

sent, *_ = run(["first line\x1b\rsecond line\r"])
check("Alt+Enter starts a new line: one message of two lines", sent == ["first line\nsecond line"], sent)

sent, *_ = run(["first\x1b[13;2usecond\r"])
check("Shift+Enter (CSI u) starts a new line too", sent == ["first\nsecond"], sent)

sent, *_ = run(["\x1b[200~pasted one\npasted two\npasted three\x1b[201~", " edited\r"])
check("a paste lands as one block you can edit, sent as one message",
      sent == ["pasted one\npasted two\npasted three edited"], sent)

sent, local_got, *_ = run(["/copy 2\r", "/stop\r"])
check("a local command is answered here and not sent; others are sent", local_got == ["2"] and sent == ["/stop"],
      (local_got, sent))

sent, *_ = run(["dropped", "\x03", "kept\r"])
check("Ctrl-C drops what was typed and the chat carries on", sent == ["kept"], sent)

sent, *_ = run(["   \r"])
check("an empty message isn't sent", sent == [], sent)

from prompt_toolkit.completion import CompleteEvent  # noqa: E402
from prompt_toolkit.document import Document  # noqa: E402
typing, tab = CompleteEvent(text_inserted=True), CompleteEvent(completion_requested=True)
c = hearthside.Completions({"/stop": "finish and exit", "/status": "", "/model": "switch models"},
                           {"/model": lambda: [("sonnet", "claude-sonnet at openrouter.ai · in use"),
                                               ("sonnet@anthropic", "claude-sonnet at api.anthropic.com · rate limited until 14:32"),
                                               ("local", "qwen at 127.0.0.1:5005")]})
got = list(c.get_completions(Document("/st"), typing))
check("/commands complete at the start of a message, with what they do, and only there",
      sorted(x.text for x in got) == ["/status", "/stop"] and any(x.display_meta_text == "finish and exit" for x in got)
      and not list(c.get_completions(Document("say /st"), typing)), [(x.text, x.display_meta_text) for x in got])
menu = list(c.get_completions(Document("/model "), typing))
check("after /model, a menu of the models, each with its service and state",
      [x.text for x in menu] == ["sonnet", "sonnet@anthropic", "local"] and "rate limited until 14:32" in menu[1].display_meta_text,
      [(x.text, x.display_meta_text) for x in menu])
check("typing narrows the menu", [x.text for x in c.get_completions(Document("/model anth"), typing)] == ["sonnet@anthropic"])
d = tempfile.mkdtemp(); os.makedirs(d + "/src/app"); open(d + "/src/app/main.py", "w").close()
paths = [x.text for x in c.get_completions(Document(f"look at {d}/src/ap"), tab)]
check("Tab completes a path in the middle of a message", paths == ["p/"] or paths == ["p"], paths)
check("paths aren't offered while typing, only on Tab", not list(c.get_completions(Document(f"look at {d}/src/ap"), typing)))
cwd = os.getcwd(); os.chdir(d)
rel = [x.text for x in c.get_completions(Document("see `./src/app/ma"), tab)]
os.chdir(cwd)
check("relative paths complete from the folder you started in, after a backtick too", rel == ["in.py"], rel)

paint = hearthside.Painter()
out = [paint(l) for l in ["10:00:07 s1> Run this:", "```python", "def f(x): return 1", "```", "after", "plain text",
                          "10:00:08 s1> ```bash", "echo hi", "10:00:09 s1> new message", "not code"]]
check("code in a fence is coloured by its language; the rest passes as it is",
      "\x1b[" in out[2] and out[4] == "after" and out[5] == "plain text" and out[1] == "```python", out)
check("a new message ends a fence left open", "\x1b[" in out[7] and out[9] == "not code", out[7:])
check("an unknown language is left alone", [hearthside.Painter()(l) for l in ["```nosuchlang", "x = 1"]][1] == "x = 1")

sent, *_ = run(["\x1bOP", "after help\r"])                    # F1 (xterm's code)
check("F1 is the help, and nothing is sent for it", HELPED == [""] and sent == ["after help"], (HELPED, sent))

print("FAILED" if failed else "ALL PASSED")
sys.exit(1 if failed else 0)
