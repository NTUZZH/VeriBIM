"""The manifest VeriBIM-Bench v3 is frozen on.

It names the generator version, the seed, the ten buildings and their source
files with checksums, the checksum of every gold model on disk and of the task
file itself, and the command that rebuilds the set from the corpus alone.  It
also states that no building of the set appears in the training or validation
splits, which is the property that makes the set a held-out one.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

REGENERATION = (
    "PYTHONPATH=code MODIFC_GEOM_CACHE=runs_local/wave_v2/geom_index_e2 "
    "OMP_NUM_THREADS=1 taskset -c 0-9 python -m modifc_gen.scale "
    "--root . --out runs_local/wave_v2/e2_wave "
    "--pool runs_local/wave_v2/pool_e2.json --n-tasks 6000 --chain-share 0.12 "
    "--n-validation 0 --shard-size 30 --passes 4 --workers 4 "
    "--heavy-workers 2 --cores 0-9 --seed 20260903 --wave e2v3 "
    "<the family shares and weights recorded in e2_wave/funnel.json>; "
    "then PYTHONPATH=code python scripts/benchmark/selection/build_e2_v3.py "
    "--tasks runs_local/wave_v2/e2_wave/tasks.jsonl "
    "--out e2_tasks.jsonl --report e2_report.json --seed 20260903; "
    "then PYTHONPATH=code python -m modifc_gen.materialize --root . "
    "--tasks e2_tasks.jsonl --split e2 --out models --workers 4 --cores 0-9"
)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--canonical", default="")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    tasks_path = Path(args.tasks)
    rows = [json.loads(line) for line in
            tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    models_dir = Path(args.models)
    gold = {}
    missing, mismatched = [], []
    for record in rows:
        path = models_dir / f"{record['task_id']}.ifc"
        recorded = (record.get("verification") or {}).get("gold_sha256")
        if not path.exists():
            missing.append(record["task_id"])
            continue
        digest = sha256_of(path)
        gold[record["task_id"]] = {"sha256": digest, "bytes": path.stat().st_size}
        if recorded and recorded != digest:
            mismatched.append(record["task_id"])

    sources = {}
    for record in rows:
        source = record["source_model"]
        sources[source["relpath"]] = {
            "sha256": source["sha256"], "key": source["key"],
            "schema": source.get("schema"),
            "collection": source.get("collection"),
            "building_id": record["building_id"]}

    training = set()
    if args.canonical and Path(args.canonical).exists():
        for line in Path(args.canonical).read_text(encoding="utf-8").splitlines():
            if line.strip():
                training.add(json.loads(line).get("building_id"))
    buildings = sorted({r["building_id"] for r in rows})

    manifest = {
        "name": "VeriBIM-Bench v3",
        "tasks_file": str(tasks_path),
        "tasks_sha256": sha256_of(tasks_path),
        "n_tasks": len(rows),
        "generator_version": sorted({r.get("generator_version") for r in rows}),
        "seed": 20260903,
        "buildings": buildings,
        "tasks_per_building": dict(sorted(Counter(
            r["building_id"] for r in rows).items())),
        "source_models": sources,
        "n_source_models": len(sources),
        "gold_models": gold,
        "gold_models_missing": missing,
        "gold_models_whose_checksum_moved": mismatched,
        "buildings_shared_with_the_training_and_validation_splits":
            sorted(set(buildings) & training),
        "regeneration_command": REGENERATION,
    }
    Path(args.out).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in
                      ("n_tasks", "n_source_models", "buildings",
                       "gold_models_missing",
                       "gold_models_whose_checksum_moved",
                       "buildings_shared_with_the_training_and_validation_splits")},
                     indent=1))
    if missing or mismatched:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
