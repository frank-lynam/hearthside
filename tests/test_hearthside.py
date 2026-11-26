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
                        commands=["/stop", "/pause"], local={"/copy": lambda rest: local_got.append(rest) or "copied"},
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

c = hearthside.Commands(["/stop", "/status", "/copy"])
from prompt_toolkit.document import Document  # noqa: E402
got = [x.text for x in c.get_completions(Document("/st"), None)]
check("/commands complete at the start of a message, and only there", sorted(got) == ["/status", "/stop"]
      and not list(c.get_completions(Document("say /st"), None)), got)

print("FAILED" if failed else "ALL PASSED")
sys.exit(1 if failed else 0)
