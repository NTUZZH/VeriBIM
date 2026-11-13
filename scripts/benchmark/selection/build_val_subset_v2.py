"""Draw the val-500 and val-100 gate sets from the canonical v2 validation split.

The Stage C set of 2026-09-02 was stratified by operation and category alone.
A wave whose tasks are weighted by taxonomy layer needs a gate set weighted the
same way, or the gate reads a mixture the training set does not have, so the
stratum here is the layer a task draws from crossed with the cell it sits in.
Quotas are proportional to the validation split, largest remainders absorb the
rounding, and a stratum with fewer tasks than its quota passes the remainder to
the others.  val-100 is drawn from the 500 by the same rule, so the smaller set
is a subset of the larger one and the two gates read one distribution.

    python scripts/benchmark/selection/build_val_subset_v2.py \
        --tasks data/.../tasks.jsonl --n 500 --n-small 100 --seed 20260910
"""

from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from partition import layer_of  # noqa: E402


def cell_of(record: dict) -> str:
    if record.get("tier") == "single":
        return f"{record.get('operation')}/{record.get('category')}"
    return "compositional"


def stratum_of(record: dict) -> str:
    return f"{layer_of(set(record.get('families') or ()))}|{cell_of(record)}"


def allocate(strata: dict[str, list[str]], n: int) -> dict[str, int]:
    """Proportional quotas, capped by supply, with the shortfall redistributed."""
    keys = sorted(strata)
    quota = {k: 0 for k in keys}
    left = n
    for _round in range(32):
        active = [k for k in keys if len(strata[k]) > quota[k]]
        if not active or left <= 0:
            break
        total = sum(len(strata[k]) for k in active)
        raw = {k: left * len(strata[k]) / total for k in active}
        take = {k: min(int(raw[k]), len(strata[k]) - quota[k]) for k in active}
        for k in sorted(active, key=lambda k: raw[k] - int(raw[k]), reverse=True):
            if sum(take.values()) >= left:
                break
            if take[k] < len(strata[k]) - quota[k]:
                take[k] += 1
        moved = 0
        for k in active:
            quota[k] += take[k]
            moved += take[k]
        left -= moved
        if moved == 0:
            break
    return quota


def draw(records: list[dict], n: int, seed: int) -> tuple[list[str], dict]:
    strata: dict[str, list[str]] = collections.defaultdict(list)
    for record in records:
        strata[stratum_of(record)].append(record["task_id"])
    for key in strata:
        strata[key].sort()
    quota = allocate(strata, n)
    rng = random.Random(seed)
    chosen: list[str] = []
    for key in sorted(strata):
        if quota[key]:
            chosen.extend(rng.sample(strata[key], quota[key]))
    if len(chosen) != n or len(set(chosen)) != n:
        raise AssertionError(f"drew {len(chosen)} ids, {len(set(chosen))} distinct, "
                             f"wanted {n}")
    rng.shuffle(chosen)
    meta = {key: {"pool": len(strata[key]), "drawn": quota[key]}
            for key in sorted(strata)}
    return chosen, meta


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--n-small", type=int, default=100)
    parser.add_argument("--seed", type=int, default=20260910)
    parser.add_argument("--out-500", required=True)
    parser.add_argument("--out-100", required=True)
    args = parser.parse_args(argv)

    pool = [json.loads(line) for line in
            Path(args.tasks).read_text(encoding="utf-8").splitlines()
            if line.strip()]
    pool = [r for r in pool if r.get("split") == "validation"]
    ids = [r["task_id"] for r in pool]
    if len(set(ids)) != len(ids):
        raise AssertionError("repeated task ids in the validation split")

    five, meta500 = draw(pool, args.n, args.seed)
    by_id = {r["task_id"]: r for r in pool}
    one, meta100 = draw([by_id[i] for i in five], args.n_small, args.seed)
    if not set(one) <= set(five):
        raise AssertionError("val-100 is not a subset of val-500")

    for path, chosen, meta, size in ((args.out_500, five, meta500, args.n),
                                     (args.out_100, one, meta100, args.n_small)):
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(chosen, indent=0), encoding="utf-8")
        picked = {r["task_id"] for r in pool} & set(chosen)
        report = {
            "n": size, "seed": args.seed, "tasks_file": args.tasks,
            "pool_size": len(pool),
            "strata": meta,
            "layers": dict(collections.Counter(
                layer_of(set(by_id[i].get("families") or ())) for i in chosen)),
            "cells": dict(collections.Counter(cell_of(by_id[i]) for i in chosen)),
            "buildings": dict(collections.Counter(
                by_id[i].get("building_id") for i in chosen)),
            "n_ids_in_pool": len(picked),
        }
        out.with_suffix(".meta.json").write_text(json.dumps(report, indent=1),
                                                 encoding="utf-8")
        print(f"{size} ids -> {out}")
        print(json.dumps({k: report[k] for k in ("layers", "cells")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
