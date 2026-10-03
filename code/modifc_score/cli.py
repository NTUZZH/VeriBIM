"""Command line entry point: score one cached benchmark run."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pandas as pd

from .batch import score_tasks
from .config import ScorerConfig
from .tasks import load_tasks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Score a cached BIM-Edit run with ModIFC-Score")
    ap.add_argument("--tasks", required=True, help="path to tasks.jsonl")
    ap.add_argument("--scenes", required=True, help="directory holding simple/ and complex/")
    ap.add_argument("--edited", required=True, help="directory holding edited/<task_id>/")
    ap.add_argument("--out", required=True, help="output CSV")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--reserve-cores", type=int, default=4)
    ap.add_argument("--model-cache", type=int, default=3)
    ap.add_argument("--geometry-mode", default="per_pair")
    ap.add_argument("--scene", default=None, help="restrict to scene letter R or A")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)

    tasks = load_tasks(args.tasks)
    selected = [t for t in tasks.values()
                if args.scene is None or t.scene == args.scene]
    selected.sort(key=lambda t: t.task_id)
    if args.limit:
        selected = selected[: args.limit]

    rows = score_tasks(selected, args.scenes, args.edited, ScorerConfig(),
                       workers=args.workers, geometry_mode=args.geometry_mode,
                       reserve_cores=args.reserve_cores,
                       model_cache_size=args.model_cache)
    frame = pd.DataFrame(rows)
    for col in ("topology_breakdown", "semantics_breakdown", "geometry_breakdown"):
        if col in frame:
            frame[col] = frame[col].apply(json.dumps, default=str)
    frame = frame.sort_values("task_id")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(frame[["geometry", "semantics", "topology", "final_score"]].mean().to_string())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
