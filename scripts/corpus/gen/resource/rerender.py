"""Re-render a filling-repaired gold script the way the fixed generator writes it.

The filling repair (gen/repair/repair_filling_type.py) replaced the literal
``predefined_type='<T>'`` by ``predefined_type=None`` in place.  The generator's
renderer (``modifc_gen.script.render_call``) wraps a call's named arguments at
78 columns, so the shorter literal lets the next argument move up one line when
the fixed generator writes the same call.  The two scripts are the same Python
(identical AST), but not the same text, and the redraw check compares text.

``canonical(script)`` reads the calls of ``apply_edit`` back out of the script,
renders them again with ``script.render_call`` and puts them between the
unchanged header and footer.  It asserts that the result parses to the same AST,
so executing it builds the same gold model byte for byte.

    python rerender.py --in IN.jsonl --out OUT.jsonl --report REPORT.json
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import sys
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(".")
for _path in (ROOT / "code", ROOT / "code" / "harness"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from modifc_gen import goldlib  # noqa: E402
from modifc_gen import script as script_lib  # noqa: E402
from modifc_gen.ops import Call  # noqa: E402

BODY_START = '    """Apply the task\'s edit to an open model, in place."""\n'
BODY_END = "\n    return model\n"
TAG = "generator_fix_rendering"


def canonical(source: str) -> str:
    start = source.index(BODY_START) + len(BODY_START)
    end = source.index(BODY_END, start)
    body = source[start:end]
    lines = body.split("\n")
    # Split the body into calls: an optional comment line, then the call lines.
    calls: list[Call] = []
    comment = ""
    chunk: list[str] = []

    def flush():
        nonlocal comment, chunk
        if not chunk:
            return
        node = ast.parse("\n".join(line[4:] for line in chunk)).body
        assert len(node) == 1 and isinstance(node[0], ast.Expr), chunk
        call = node[0].value
        assert isinstance(call.func, ast.Attribute) and call.func.value.id == "goldlib"
        assert len(call.args) == 1 and call.args[0].id == "model"
        func = call.func.attr
        names = list(inspect.signature(getattr(goldlib, func)).parameters)[1:]
        keys = [kw.arg for kw in call.keywords]
        assert keys == names[:len(keys)], (keys, names)
        calls.append(Call(func, tuple(ast.literal_eval(kw.value) for kw in call.keywords),
                          comment))
        comment, chunk = "", []

    for line in lines:
        if line == "" and not chunk:
            continue
        if line.startswith("    # "):
            flush()
            comment = line[len("    # "):]
        elif line.startswith("    goldlib."):
            flush()
            chunk = [line]
        else:
            chunk.append(line)
    flush()
    new_body = "\n".join(script_lib.render_call(call) for call in calls)
    result = source[:start] + new_body + source[end:]
    assert ast.dump(ast.parse(result)) == ast.dump(ast.parse(source))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--in", dest="inp", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    stats = Counter()
    changed_ids = []
    tmp = Path(args.out).with_suffix(".tmp")
    with open(args.inp, "rb") as fin, open(tmp, "wb") as fout:
        for raw in fin:
            record = json.loads(raw)
            ver = record.get("verification") or {}
            again = canonical(record["gold_script"])
            if not ver.get("repair"):
                # The renderer reproduces every script it wrote itself.
                if again == record["gold_script"]:
                    stats["unrepaired_identity"] += 1
                else:
                    stats["unrepaired_NOT_identity"] += 1
                fout.write(raw)
                continue
            if again == record["gold_script"]:
                stats["repaired_already_canonical"] += 1
                fout.write(raw)
                continue
            record["gold_script"] = again
            ver["repair_rerendered"] = TAG
            stats["repaired_rerendered"] += 1
            changed_ids.append(record["task_id"])
            fout.write((json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8"))
    os.replace(tmp, args.out)
    report = {"in": args.inp, "out": args.out, "counts": dict(stats),
              "rerendered_ids": changed_ids}
    Path(args.report).write_text(json.dumps(report, indent=1))
    print(json.dumps(report["counts"]))
    return 0 if not stats["unrepaired_NOT_identity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
