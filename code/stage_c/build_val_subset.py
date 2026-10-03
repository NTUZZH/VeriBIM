"""Draw a fixed held-out subset from the canonical validation split.

val-100 (Stage A/B gate set) is too small to resolve Stage C differences:
88-92 of its 100 tasks tie between adapters. This draws a larger fixed set,
stratified in proportion to the operation x category cells of the
validation split, excluding every val-100 id so the two sets stay disjoint.
Seeded; the meta file records the draw so it can be reproduced and audited.

    python -m stage_c.build_val_subset --n 500 --out data/stage_c/val_subset_500.json
"""

from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path

from stage_a import paths

VAL100 = paths.PROJECT_ROOT / "data/stage_a/v1/val_subset_100.json"
CANONICAL = paths.PROJECT_ROOT / "data/veribim_tasks_canonical/tasks.jsonl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--seed", type=int, default=20260902)
    ap.add_argument("--tasks-file", default=str(CANONICAL))
    ap.add_argument("--exclude", default=str(VAL100))
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    exclude = set(json.loads(Path(args.exclude).read_text(encoding="utf-8")))
    pool = [json.loads(line) for line in Path(args.tasks_file).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    pool = [r for r in pool if r.get("split") == "validation" and r["task_id"] not in exclude]
    ids = [r["task_id"] for r in pool]
    if len(set(ids)) != len(ids):
        raise AssertionError("repeated task ids in the validation split")

    cells: dict[tuple[str, str], list[str]] = collections.defaultdict(list)
    for r in pool:
        cells[(r["operation"], r["category"])].append(r["task_id"])
    keys = sorted(cells)
    total = len(pool)
    # Proportional quota per cell, largest remainders absorbing the rounding.
    raw = {k: args.n * len(cells[k]) / total for k in keys}
    quota = {k: int(raw[k]) for k in keys}
    for k in sorted(keys, key=lambda k: raw[k] - quota[k], reverse=True)[: args.n - sum(quota.values())]:
        quota[k] += 1
    rng = random.Random(args.seed)
    chosen: list[str] = []
    for k in keys:
        chosen.extend(rng.sample(sorted(cells[k]), quota[k]))
    if len(chosen) != args.n or len(set(chosen)) != args.n:
        raise AssertionError((len(chosen), len(set(chosen))))
    rng.shuffle(chosen)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(chosen, indent=0), encoding="utf-8")
    by_wave = collections.Counter(r["wave"] for r in pool if r["task_id"] in set(chosen))
    meta = {
        "n": args.n, "seed": args.seed, "tasks_file": str(args.tasks_file),
        "excluded": str(args.exclude), "pool_size": total,
        "cells": {f"{op}/{cat}": {"pool": len(cells[(op, cat)]), "drawn": quota[(op, cat)]}
                  for op, cat in keys},
        "by_wave": dict(by_wave),
    }
    out.with_suffix(".meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()
