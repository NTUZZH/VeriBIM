"""Replace recomputed rows in a results/*.jsonl file in place (v4d recompute, 2026-10-16).

usage: python replace_rows_v4d.py <results file> <new rows file> [--check]

Every row of the new-rows file names a task_id. In the results file, the rows of each such task
(one row per task for gate_/schema_clash_ files, several per task for mutation_gate.jsonl) are
replaced by the new rows of that task, in the new file's order, at the position of the task's first
old row. Every other line is written back byte-identical. Before writing, the results file is copied
to <name>.pre_v4d (refuses if that copy exists already). Checks: every new task had old rows; the
number of lines of other tasks and their bytes are unchanged.
"""
import json, shutil, sys
from collections import OrderedDict
from pathlib import Path

res, new = Path(sys.argv[1]), Path(sys.argv[2])
check = "--check" in sys.argv
new_rows = OrderedDict()
for line in open(new, "rb"):
    if line.strip():
        t = json.loads(line)["task_id"]
        new_rows.setdefault(t, []).append(line if line.endswith(b"\n") else line + b"\n")
old_lines = open(res, "rb").readlines()
old_tasks = [json.loads(l)["task_id"] if l.strip() else None for l in old_lines]
missing = [t for t in new_rows if t not in old_tasks]
if missing:
    sys.exit(f"tasks without old rows: {missing}")
out, placed, kept, replaced = [], set(), [], 0
for l, t in zip(old_lines, old_tasks):
    if t in new_rows:
        replaced += 1
        if t not in placed:
            out.extend(new_rows[t])
            placed.add(t)
        continue
    out.append(l)
    kept.append(l)
assert [l for l, t in zip(old_lines, old_tasks) if t not in new_rows] == kept
n_new = sum(len(v) for v in new_rows.values())
print(json.dumps({"file": res.name, "tasks": len(new_rows), "old_rows_replaced": replaced,
                  "new_rows": n_new, "rows_kept_byte_identical": len(kept), "lines_after": len(out)}))
if check:
    sys.exit(0)
bak = res.with_name(res.name + ".pre_v4d")
if bak.exists():
    sys.exit(f"{bak} exists; not overwriting the pre-v4d copy")
shutil.copy2(res, bak)
tmp = res.with_name(res.name + ".v4d_tmp")
with open(tmp, "wb") as f:
    f.writelines(out)
tmp.replace(res)
