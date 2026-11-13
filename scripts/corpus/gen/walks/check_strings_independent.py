"""Independent name walk: tokenizer-based, no project imports.

A name-like string literal (digit, colon or non-ASCII inside) in an assistant
code block, outside a print line, must appear in the instruction or an earlier
tool output. Exits non-zero when any trajectory quotes an unseen name.
"""

from __future__ import annotations

import argparse
import collections
import io
import json
import tokenize
from pathlib import Path

NOISE = ("(m)", "match(es)", "file unit", "metres", "committed", "in the model",
         "origin", "contained", "elevation", "the phrase", "still", "left in",
         "hosted in", "slot", "wall (", "corner", "footprint", "reference")


def codes(message):
    out = []
    for call in message.get("tool_calls") or []:
        function = call.get("function") or {}
        arguments = function.get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except Exception:
                arguments = {"code": arguments}
        out.append((arguments or {}).get("code", ""))
    return out


def strings(code):
    out = []
    try:
        for token in tokenize.generate_tokens(io.StringIO(code).readline):
            if token.type == tokenize.STRING:
                body = token.string.lstrip("rbRB")
                body = body[3:-3] if body[:3] in ('"""', "'''") else body[1:-1]
                out.append((body, token.start[0]))
    except Exception:
        pass
    return out


def namey(s):
    if len(s) < 3 or s.startswith("Ifc"):
        return False
    if not (any(ch.isdigit() for ch in s) or ":" in s or any(ord(ch) > 127 for ch in s)):
        return False
    return not any(word in s for word in NOISE)


def unseen_names(record):
    seen = record.get("instruction") or record.get("prompt") or ""
    found = []
    round_index = 0
    for message in record.get("messages") or ():
        role = message.get("role")
        if role in ("tool", "user"):
            seen += "\n" + (message.get("content") or "")
            continue
        if role != "assistant":
            continue
        blocks = codes(message)
        if not blocks:
            continue
        for code in blocks:
            lines = code.split("\n")
            for text, line_no in strings(code):
                if not namey(text) or text in seen:
                    continue
                line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
                if line.strip().startswith("print"):
                    continue
                found.append({"round": round_index, "unseen": text[:80]})
            seen += "\n" + code
        round_index += 1
    return found


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--report", default="")
    args = parser.parse_args()
    summary = {}
    total = 0
    for name in args.files:
        rows = bad = 0
        by_kind = collections.Counter()
        examples = []
        with Path(name).open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                rows += 1
                found = unseen_names(record)
                if not found:
                    continue
                bad += 1
                by_kind[f"{record.get('edit_kind')}/{record.get('category')}"] += 1
                if len(examples) < 8:
                    examples.append({"task_id": record["task_id"], "found": found[:2]})
        summary[name] = {"rows": rows, "trajectories_with_an_unseen_name": bad,
                         "by_kind": dict(by_kind), "examples": examples}
        total += bad
    print(json.dumps({k: {a: b for a, b in v.items() if a != "examples"} for k, v in summary.items()}, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 1 if total else 0


if __name__ == "__main__":
    raise SystemExit(main())
