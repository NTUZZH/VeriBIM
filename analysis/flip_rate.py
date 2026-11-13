#!/usr/bin/env python3
"""Run-to-run stability of one model: tasks whose completion verdict differs between two runs under identical settings.

  usage: flip_rate.py RUN_A.jsonl RUN_B.jsonl [--subset SUBSET.json] [--out OUT.json]

RUN_A and RUN_B are per-task files of the evaluation harness (one JSON row per task with task_id and score). Only tasks
present in both files are compared; with --subset (a JSON list of task ids, or an object with a "task_ids" list) the
comparison is limited to those tasks, and every one of them must be present in both files. A task is completed when
geometry, semantics and topology all reach 0.9. An unscored row in either file stops the script.
Output: number of compared tasks, completed in A, completed in B, flips (verdict differs), flip rate, and the ids that flip.
"""
import argparse
import json
import sys


def load(path):
    rows = {}
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        tid = r.get("task_id")
        if tid in rows:
            sys.exit(f"duplicate task_id {tid} in {path}")
        rows[tid] = r
    return rows


def done(r, path):
    sc = r.get("score")
    if sc is None:
        sys.exit(f"unscored row {r.get('task_id')} in {path}")
    return all((sc.get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run_a")
    ap.add_argument("run_b")
    ap.add_argument("--subset")
    ap.add_argument("--out")
    a = ap.parse_args()
    A, B = load(a.run_a), load(a.run_b)
    if a.subset:
        s = json.load(open(a.subset, encoding="utf-8"))
        ids = s["task_ids"] if isinstance(s, dict) else s
        ids = [i["task_id"] if isinstance(i, dict) else i for i in ids]
        missing = [i for i in ids if i not in A or i not in B]
        if missing:
            sys.exit(f"{len(missing)} subset tasks missing from a run, first {missing[:3]}")
    else:
        ids = sorted(set(A) & set(B))
    if not ids:
        sys.exit("no common task")
    da = {i: done(A[i], a.run_a) for i in ids}
    db = {i: done(B[i], a.run_b) for i in ids}
    flips = sorted(i for i in ids if da[i] != db[i])
    out = {
        "run_a": a.run_a, "run_b": a.run_b, "subset": a.subset, "n": len(ids),
        "completed_a": sum(da.values()), "completed_b": sum(db.values()),
        "flips": len(flips), "flip_rate": round(len(flips) / len(ids), 4),
        "a_only": sorted(i for i in flips if da[i]), "b_only": sorted(i for i in flips if db[i]),
    }
    print(json.dumps({k: v for k, v in out.items() if k not in ("a_only", "b_only")}, indent=1))
    print("completed only in A:", len(out["a_only"]), " completed only in B:", len(out["b_only"]))
    if a.out:
        json.dump(out, open(a.out, "w", encoding="utf-8"), indent=1)


if __name__ == "__main__":
    main()
