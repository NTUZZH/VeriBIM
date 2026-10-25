"""Where the grammar stops on an instruction it does not recognise.

Loads grammar.py unchanged except that its two terminal parsers (lit, rx)
record how far into the normalised text any successful match reached.  The
furthest point any template path reached, and the text right after it, show
why an instruction is not recognised.  Parsing results are identical to
grammar.py (the check below asserts it).
Usage: python why_unread.py <tasks.jsonl> <out.jsonl>
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import grammar  # noqa: E402

SRC = (HERE / "grammar.py").read_text(encoding="utf-8")
OLD_LIT = """        if t.startswith(text):
            yield None, t[len(text):]"""
NEW_LIT = """        if t.startswith(text):
            _mark(t[len(text):])
            yield None, t[len(text):]"""
OLD_RX = """        if m:
            yield (conv(m) if conv else m.group(0)), t[m.end():]"""
NEW_RX = """        if m:
            _mark(t[m.end():])
            yield (conv(m) if conv else m.group(0)), t[m.end():]"""
assert SRC.count(OLD_LIT) == 1 and SRC.count(OLD_RX) == 1
traced = types.ModuleType("grammar_traced")
traced.__dict__["_STATE"] = {"min_rest": None}


def _mark(rest: str) -> None:
    st = traced.__dict__["_STATE"]
    if st["min_rest"] is None or len(rest) < st["min_rest"]:
        st["min_rest"] = len(rest)


traced.__dict__["_mark"] = _mark
exec(compile(SRC.replace(OLD_LIT, NEW_LIT).replace(OLD_RX, NEW_RX),
             "grammar_traced", "exec"), traced.__dict__)


def why(instruction: str) -> dict:
    text, _form = traced.normalise(instruction)
    traced._STATE["min_rest"] = None
    out = traced.parse(instruction)
    assert bool(out.get("recognised")) == bool(grammar.parse(instruction).get("recognised"))
    min_rest = traced._STATE["min_rest"]
    reached = 0 if min_rest is None else len(text) - min_rest
    return {"recognised": bool(out.get("recognised")), "normalised": text,
            "read_up_to": text[:reached], "stopped_at": text[reached:reached + 80]}


def main(tasks: str, out: str) -> None:
    with open(out, "w", encoding="utf-8") as fh:
        for line in open(tasks, encoding="utf-8"):
            r = json.loads(line)
            row = {"task_id": r["task_id"], **why(r["instruction"])}
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main(*sys.argv[1:])
