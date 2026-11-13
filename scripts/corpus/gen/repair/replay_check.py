"""Replay check for repaired filling tasks.

Picks repaired ``create_filling`` and ``replace_filling`` tasks from the train
split of a repaired task file, spread round robin over buildings, and runs
``stage_a.synthesize.synthesize_one`` on each exactly as ``stage_a.pipeline``
calls it: the pipeline's own worker initialiser (thread caps, core pinning, model
and mesh cache sizes, a gold cache opened through ``goldmodels.open_cache`` in a
per-worker slot, the name-index root) and its own per-task wrapper
``_run_one_inner`` (name index loaded with ``nameindex.load``, then
``synthesize_one`` with floor 0.98 and every axis held to it, as
``stage_a.cli synthesize`` passes by default).  One worker, in this process, so
the only other process is the harness sandbox the replay starts.

The gold model is rebuilt from the repaired gold script by the gold cache, which
checks the repaired checksum, so an accepted task also proves the recorded
checksum reproduces.

    python replay_check.py --tasks REPAIRED.jsonl --journal REPORT.journal.jsonl \
        --out-dir DIR --name-index DIR --gold-cache DIR [--per-kind 30]
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"
# stage_a.cli synthesize sets this before the pipeline loads the synthesizer;
# the v10 synthesis runs (run_synth.sh) do not pass --no-geom-lib.
os.environ["VERIBIM_STAGE_A_GEOM"] = "1"

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
for _path in (ROOT / "code", ROOT / "code" / "harness"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from stage_a import paths, pipeline  # noqa: E402

KINDS = ("create_filling", "replace_filling")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def choose(records, per_kind: int, max_mb: float) -> list[dict]:
    chosen = []
    for kind in KINDS:
        by_building = defaultdict(list)
        for r in records:
            if r["edit_kind"] != kind:
                continue
            try:
                size = (ROOT / r["input_ifc"]).stat().st_size / 1e6
            except OSError:
                continue
            if size > max_mb:
                continue
            by_building[r.get("building_id") or r["input_ifc"]].append(r)
        for group in by_building.values():
            group.sort(key=lambda r: _h("replay|" + r["task_id"]))
        order = sorted(by_building, key=lambda b: _h("replay|" + b))
        picked, depth = [], 0
        while len(picked) < per_kind and any(len(by_building[b]) > depth for b in order):
            for building in order:
                if len(picked) >= per_kind:
                    break
                if len(by_building[building]) > depth:
                    picked.append(by_building[building][depth])
            depth += 1
        chosen.extend(picked)
    return chosen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--journal", required=True)
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--name-index", required=True)
    parser.add_argument("--gold-cache", required=True)
    parser.add_argument("--per-kind", type=int, default=30)
    parser.add_argument("--max-mb", type=float, default=25.0)
    parser.add_argument("--cores", default="8-9")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    repaired_ok = set()
    with open(args.journal, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                entry = json.loads(line)
                if entry.get("ok"):
                    repaired_ok.add(entry["task_id"])
    records = []
    with open(args.tasks, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if (r["task_id"] in repaired_ok and r.get("split") == "train"
                    and r["edit_kind"] in KINDS):
                assert (r.get("verification") or {}).get("repair"), r["task_id"]
                records.append(r)
    tasks = choose(records, args.per_kind, args.max_mb)
    (out_dir / "chosen_ids.json").write_text(json.dumps(
        [t["task_id"] for t in tasks], indent=0))

    outcomes_path = out_dir / "outcomes.jsonl"
    done = set()
    if outcomes_path.exists():
        for line in outcomes_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["task_id"])
    pending = [t for t in tasks if t["task_id"] not in done]
    print(f"{len(records)} repaired train tasks; {len(tasks)} chosen over "
          f"{len({t.get('building_id') for t in tasks})} buildings; "
          f"{len(pending)} to run", flush=True)

    cores = [int(c) for part in args.cores.split(",") for c in
             (range(int(part.split("-")[0]), int(part.split("-")[1]) + 1)
              if "-" in part else [int(part)])]
    # The pipeline's own worker initialiser, in this process: one worker.
    pipeline._init_worker(str((out_dir / "_work").resolve()), str(paths.PROJECT_ROOT),
                          0.98, True, 1, str(Path(args.gold_cache).resolve()),
                          tuple(cores), None, "repair",
                          str(Path(args.name_index).resolve()))
    started = time.monotonic()
    with outcomes_path.open("a", encoding="utf-8") as out_fh, \
            (out_dir / "trajectories.jsonl").open("a", encoding="utf-8") as traj_fh:
        for index, task in enumerate(pending, 1):
            result = pipeline._run_one_inner(task, time.monotonic())
            record = result.pop("record")
            if result["ok"] and record is not None:
                traj_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                traj_fh.flush()
            result["input_ifc"] = task["input_ifc"]
            out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_fh.flush()
            print(f"  {index}/{len(pending)} {task['task_id']} "
                  f"{'accepted' if result['ok'] else 'rejected: ' + result['reason'][:90]}"
                  f" ({result['seconds']}s)", flush=True)

    outcomes = [json.loads(l) for l in outcomes_path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
    chosen = {t["task_id"] for t in tasks}
    outcomes = [o for o in outcomes if o["task_id"] in chosen]
    summary = {
        "n": len(outcomes),
        "accepted": sum(1 for o in outcomes if o["ok"]),
        "by_kind": {k: {"n": sum(1 for o in outcomes if o["edit_kind"] == k),
                        "accepted": sum(1 for o in outcomes
                                        if o["edit_kind"] == k and o["ok"])}
                    for k in KINDS},
        "buildings": len({o["building_id"] for o in outcomes}),
        "rejections": dict(Counter(f"{o['stage']}: {o['reason'][:100]}"
                                   for o in outcomes if not o["ok"])),
        "rejected": [{k: o.get(k) for k in ("task_id", "edit_kind", "building_id",
                                           "stage", "reason", "score", "detail")}
                     for o in outcomes if not o["ok"]],
        "mean_final_score_accepted": (
            round(sum(o["score"]["final"] for o in outcomes if o["ok"])
                  / max(1, sum(1 for o in outcomes if o["ok"])), 6)),
        "seconds_this_run": round(time.monotonic() - started, 1),
    }
    summary["accepted_share"] = round(summary["accepted"] / max(1, summary["n"]), 4)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1,
                                                     ensure_ascii=False))
    print(json.dumps({k: summary[k] for k in ("n", "accepted", "accepted_share",
                                              "by_kind", "buildings", "rejections")},
                     indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
