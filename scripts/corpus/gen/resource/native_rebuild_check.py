"""Rebuild the gold of every filling-repaired task on a native source from its final script.

Native-source tasks are not re-sourced; their only change in this pass is the
canonical re-rendering of the repaired gold script (rerender.py).  This rebuilds
each one with ``materialize.rebuild(check=True)``, which compares the rebuilt file
with the recorded checksum, so it proves the re-rendered script builds the gold
the repair recorded.

    python native_rebuild_check.py --tasks IN.jsonl [...] --out OUT.json --workers 2
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(".")
for _path in (ROOT / "code", ROOT / "code" / "harness"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
SCRATCH = ROOT / "runs_local/corpus_v10/gen/resource/work_native_rebuild"
MIGRATED_DIRS = ("runs_local/corpus_v10/migrated/", "runs_local/corpus_v10/heldout_4x3/")


def one(record):
    from modifc_gen import materialize

    target = SCRATCH / f"{record['task_id']}.ifc"
    out = materialize.rebuild(record, ROOT, target, check=True)
    if target.exists():
        target.unlink()
    return {"task_id": record["task_id"], "ok": out.ok, "check": out.check,
            "reason": out.reason, "rerendered": bool(record["verification"].get("repair_rerendered")),
            "seconds": round(out.seconds, 2)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cores", default="20-23")
    args = parser.parse_args()
    cores = []
    for part in args.cores.split(","):
        lo, _, hi = part.partition("-")
        cores.extend(range(int(lo), int(hi or lo) + 1))
    os.sched_setaffinity(0, set(cores))
    SCRATCH.mkdir(parents=True, exist_ok=True)
    records = []
    for path in args.tasks:
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            if (r.get("verification") or {}).get("repair") and \
                    not r["input_ifc"].startswith(MIGRATED_DIRS):
                records.append(r)
    started = time.perf_counter()
    import multiprocessing as mp

    with mp.get_context("fork").Pool(args.workers, maxtasksperchild=20) as pool:
        results = list(pool.imap_unordered(one, records, 2))
    summary = {"n": len(results), "ok": sum(1 for r in results if r["ok"]),
               "checks": dict(Counter(r["check"] for r in results)),
               "rerendered": sum(1 for r in results if r["rerendered"]),
               "rerendered_ok": sum(1 for r in results if r["rerendered"] and r["ok"]),
               "failures": [r for r in results if not r["ok"]],
               "seconds": round(time.perf_counter() - started, 1)}
    Path(args.out).write_text(json.dumps(summary, indent=1))
    SCRATCH.rmdir() if SCRATCH.exists() and not any(SCRATCH.iterdir()) else None
    print(json.dumps({k: v for k, v in summary.items() if k != "failures"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
