"""Score a group of finished rollouts, in the environment that owns the scorer.

The trainer runs in ``l2train``, which has neither IfcOpenShell nor the scorer's
dependencies, so rewards are computed by this module under ``l2``. One call
scores a whole group, because a per-trajectory subprocess would pay the
interpreter and IfcOpenShell import cost sixteen times per optimizer step.

Usage: ``python -m stage_c.score_cli --jobs jobs.json --out rewards.json``
with ``jobs.json`` a list of ``{"task": <record>, "predicted": <path>}``. A job
may also carry ``"reply"``, the last thing the policy said, which only an
under-specified task is read against.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage_a import paths
from stage_a.goldmodels import open_cache, resolve_gold

from .reward import UNREADABLE_FILE_REWARD, Reward, null_edit_score, score_trajectory


def score_jobs(jobs: list[dict], gold_cache_dir: Path, heldout: bool = False) -> list[dict]:
    cache = open_cache(Path(gold_cache_dir))
    out: list[dict] = []
    for job in jobs:
        task = job["task"]
        record = {"task_id": task["task_id"], "index": job.get("index")}
        try:
            null = null_edit_score(task)
        except KeyError as exc:
            out.append({**record, **Reward(UNREADABLE_FILE_REWARD, readable=False,
                                           error=str(exc)[:160]).as_dict()})
            continue
        gold = resolve_gold(task, cache, paths.PROJECT_ROOT)
        if gold is None:
            # Not a modelling failure: the reference could not be rebuilt. It is
            # floored rather than dropped so the group keeps its size, and the
            # error travels with it so the run log shows why.
            out.append({**record, **Reward(UNREADABLE_FILE_REWARD, null=null,
                                           readable=False,
                                           error="gold model could not be rebuilt "
                                                 "from its script").as_dict()})
            continue
        reward = score_trajectory(task, Path(job["predicted"]), paths.PROJECT_ROOT,
                                  gold, heldout=heldout,
                                  reply=str(job.get("reply") or ""))
        out.append({**record, **reward.as_dict()})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage-c-score")
    parser.add_argument("--jobs", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--gold-cache",
                        default=str(paths.PROJECT_ROOT / "data/stage_c/_gold"))
    parser.add_argument("--heldout", action="store_true",
                        help="score with the held-out verifier variant")
    args = parser.parse_args(argv)
    jobs = json.loads(Path(args.jobs).read_text(encoding="utf-8"))
    results = score_jobs(jobs, Path(args.gold_cache), heldout=args.heldout)
    Path(args.out).write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
