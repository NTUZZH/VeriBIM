"""Score a list of edited files, one process, one environment.

The trainer runs in ``l2train``, which has no IfcOpenShell, so the mid-training
validation hook calls this module in ``l2``. Input and output are JSON files, so
the two environments share nothing but the file system.

Usage: ``python -m stage_a.score_cli --jobs jobs.json --out scores.json``
where ``jobs.json`` is a list of ``{"task": <task record>, "predicted": <path>}``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import paths
from .goldmodels import open_cache, resolve_gold
from .scoring import score_prediction


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage-a-score")
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gold-cache", default=str(paths.STAGE_A_DATA / "_gold_score"),
                        help="where a missing gold model is rebuilt from its script")
    args = parser.parse_args(argv)

    # The reference is rebuilt when it is not on disk. Without this a task whose
    # gold model was never materialised scores `input_parse_error`, which the
    # caller cannot tell from a genuine zero: that is what silently zeroed a
    # quarter of the first gate attempt.
    cache = open_cache(Path(args.gold_cache))

    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    results = []
    for job in jobs:
        predicted = job.get("predicted") or ""
        if not predicted or not Path(predicted).is_file():
            results.append({"task_id": job["task"]["task_id"], "score": None,
                            "error": "prediction missing"})
            continue
        gold = resolve_gold(job["task"], cache, paths.PROJECT_ROOT)
        if gold is None:
            results.append({"task_id": job["task"]["task_id"], "score": None,
                            "error": "gold model could not be rebuilt from its script"})
            continue
        score = score_prediction(job["task"], Path(predicted), paths.PROJECT_ROOT,
                                 gold_path=gold)
        results.append({"task_id": job["task"]["task_id"], "score": score.as_dict(),
                        "error": score.error})
    Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
