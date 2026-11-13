#!/usr/bin/env python3
"""Write the rows of one per-task result file that belong to a task subset.

  usage: slice_subset.py RUN.jsonl SUBSET.json OUT.jsonl

RUN is a per-task file of the evaluation harness (one JSON row per task). SUBSET is a JSON list of task ids or an
object with a "task_ids" list. Every subset task must be present in RUN exactly once and must carry a score; the
script stops otherwise. The rows are copied unchanged, in the order of the subset file.
"""
import json
import sys


def main():
    run, subset, out = sys.argv[1:4]
    ids = json.load(open(subset, encoding="utf-8"))
    if isinstance(ids, dict):
        ids = ids.get("task_ids") or ids.get("ids") or ids.get("tasks")
    ids = [t["task_id"] if isinstance(t, dict) else t for t in ids]
    if len(ids) != len(set(ids)):
        sys.exit("subset holds a repeated task id")
    rows = {}
    for line in open(run, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["task_id"] in rows:
            sys.exit(f"task {r['task_id']} occurs twice in {run}")
        rows[r["task_id"]] = line if line.endswith("\n") else line + "\n"
    missing = [t for t in ids if t not in rows]
    if missing:
        sys.exit(f"{len(missing)} subset tasks are not in {run}, e.g. {missing[:3]}")
    unscored = [t for t in ids if json.loads(rows[t]).get("score") is None]
    if unscored:
        sys.exit(f"{len(unscored)} subset tasks have no score, e.g. {unscored[:3]}")
    with open(out, "w", encoding="utf-8") as fh:
        for t in ids:
            fh.write(rows[t])
    print(f"{len(ids)} rows -> {out}")


if __name__ == "__main__":
    main()
