"""Rescore one adapter's val-500 edits with the training verifier and with the
held-out verifier, and report the gap between the two rewards.

The held-out verifier (stage_c.reward.heldout_config) agrees with the training
verifier on every rule and differs only in the surface-sampling seed and
density.  A policy that had learned the training verifier's sampling rather
than the edit would score higher under the training verifier than under the
held-out one; a policy that learned the edit scores the same under both.

Run in the ``l2`` environment from the project root, pinned away from the
trainer's cores:

    OMP_NUM_THREADS=1 PYTHONPATH=code taskset -c 14-23 \\
        python -m stage_c.heldout_gap --name v2c100 --workers 6

Reads  runs_local/stage_c_val500/per_task_<name>.jsonl (the eval's edited
files) and writes runs_local/stage_c_val500/heldout_gap_<name>.json.

``--run-dir``, ``--tasks-file`` and ``--gold-cache`` default to the val-500
values above, so a call that names none of them is the val-500 measurement it
always was. The held-out-buildings test set (E2) passes its own three, and in
particular its own gold cache, because a cache directory is bounded and shared
by every worker that opens it.

Both verifiers read a task under the settings its own record asks for, and both
are handed the trajectory's closing assistant message, which is what the reward
path does. An under-specified task is decided by that message, so a row that
recorded none is scored under the published reading instead and counted in the
summary as ``read_without_the_reply``.
"""

from __future__ import annotations

import argparse
import json
import math
from multiprocessing import Pool
from pathlib import Path

from stage_a import paths

#: The val-500 defaults. Kept as module constants because other modules and
#: notes refer to them by name.
RUN_DIR = paths.PROJECT_ROOT / "runs_local/stage_c_val500"
TASKS = paths.PROJECT_ROOT / "data/veribim_tasks_canonical/tasks.jsonl"
GOLD_CACHE = paths.PROJECT_ROOT / "data/stage_c/_gold_val500"

#: The family whose reading needs the policy's last message. Named here because
#: it is the one family this tool has to treat as a special case.
UNDERSPECIFIED = "wording.underspecified"


def reply_of(row: dict) -> str:
    """The closing assistant message of one per-task row.

    The reward path scores a trajectory against the last assistant turn that
    carried content, which the harness returns as ``model_output`` and the
    rollout passes to the scorer as ``reply``. A row written by the evaluation
    driver carries that text under the same name, and a row that carries the
    transcript instead holds it as the last assistant message with content. A
    row with neither returns the empty string.
    """
    reply = row.get("reply")
    if isinstance(reply, str) and reply.strip():
        return reply
    for message in reversed(list(row.get("messages") or ())):
        if (message.get("role") == "assistant"
                and str(message.get("content") or "").strip()):
            return str(message["content"])
    return ""


def record_for(task: dict, reply: str) -> tuple[dict, bool]:
    """The record one row is scored against, and whether its reply was lost.

    The scorer settings are resolved from the record rather than from its
    operation, so a material association, a type assignment and an
    under-specified instruction are each read under the settings their edit is
    visible under. The under-specified reading is the one that needs the reply,
    because the answer there is to change nothing and ask for the missing
    value, and the file alone cannot separate that answer from a trajectory
    that did nothing. A row that recorded no reply cannot be read that way, so
    it is scored under the published reading, which is what this tool did
    before it passed the reply through, and it is counted in the summary.
    """
    from stage_c.reward import training_config

    if reply or not training_config(task).underspecified_mode:
        return task, False
    families = [f for f in (task.get("families") or ()) if f != UNDERSPECIFIED]
    return {**task, "families": families}, True


def build_jobs(records: list[dict], tasks: dict[str, dict]) -> tuple[list[dict], dict]:
    """One scoring job per per-task row, and what the replies came to."""
    jobs: list[dict] = []
    counts = {"rows_without_reply": 0, "read_without_the_reply": 0}
    for index, row in enumerate(records):
        reply = reply_of(row)
        task, fell_back = record_for(tasks[row["task_id"]], reply)
        counts["rows_without_reply"] += not reply
        counts["read_without_the_reply"] += fell_back
        jobs.append({"task": task, "index": index,
                     "predicted": row["edited_ifc"], "reply": reply})
    return jobs, counts


def _score_chunk(payload: tuple[list[dict], bool, str]) -> list[dict]:
    from stage_c.score_cli import score_jobs

    jobs, heldout, gold_cache = payload
    return score_jobs(jobs, Path(gold_cache), heldout=heldout)


def _chunks(items: list, n: int) -> list[list]:
    n = max(1, min(n, len(items)))
    return [items[i::n] for i in range(n)]


def _pearson(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 3:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    sa = math.sqrt(sum((x - ma) ** 2 for x in a))
    sb = math.sqrt(sum((y - mb) ** 2 for y in b))
    if sa == 0 or sb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / (sa * sb)


def _relative(path: Path) -> str:
    """A project-relative path where possible, the path itself otherwise."""
    try:
        return str(Path(path).relative_to(paths.PROJECT_ROOT))
    except ValueError:
        return str(path)


def build_parser() -> argparse.ArgumentParser:
    """The command line. Every default is the val-500 value it always was."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, help="adapter name, e.g. dpo_v1 or v2c100")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke test on the first N records (writes a _smokeN file)")
    ap.add_argument("--run-dir", default=str(RUN_DIR),
                    help="where per_task_<name>.jsonl is read and the gap file written")
    ap.add_argument("--tasks-file", default=str(TASKS),
                    help="the task records the edits are scored against")
    ap.add_argument("--gold-cache", default=str(GOLD_CACHE),
                    help="cache directory a missing gold model is rebuilt into")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    run_dir = Path(args.run_dir)
    tasks_file = Path(args.tasks_file)
    gold_cache = Path(args.gold_cache)

    per_task = run_dir / f"per_task_{args.name}.jsonl"
    suffix = f"_smoke{args.limit}" if args.limit else ""
    out_path = run_dir / f"heldout_gap_{args.name}{suffix}.json"
    if out_path.exists():
        raise SystemExit(f"{out_path} exists; refusing to overwrite")
    records = [json.loads(line) for line in per_task.read_text().splitlines() if line.strip()]
    if args.limit:
        records = records[:args.limit]
    wanted = {r["task_id"] for r in records}
    tasks: dict[str, dict] = {}
    with open(tasks_file) as f:
        for line in f:
            row = json.loads(line)
            if row["task_id"] in wanted:
                tasks[row["task_id"]] = row
    missing = wanted - tasks.keys()
    if missing:
        raise SystemExit(f"{len(missing)} task ids not in {tasks_file}: {sorted(missing)[:5]}")

    jobs, reply_counts = build_jobs(records, tasks)

    with Pool(args.workers) as pool:
        train = [x for part in pool.map(_score_chunk, [(c, False, str(gold_cache)) for c in _chunks(jobs, args.workers)]) for x in part]
        held = [x for part in pool.map(_score_chunk, [(c, True, str(gold_cache)) for c in _chunks(jobs, args.workers)]) for x in part]
    train.sort(key=lambda x: x["index"])
    held.sort(key=lambda x: x["index"])
    assert [t["task_id"] for t in train] == [h["task_id"] for h in held]

    rows = []
    for t, h in zip(train, held):
        rows.append({"task_id": t["task_id"], "operation": tasks[t["task_id"]]["operation"],
                     "reward_train": t["reward"], "reward_heldout": h["reward"],
                     "final_train": t.get("final"), "final_heldout": h.get("final"),
                     "readable": bool(t.get("readable")) and bool(h.get("readable")),
                     "gap": t["reward"] - h["reward"]})
    rt = [r["reward_train"] for r in rows]
    rh = [r["reward_heldout"] for r in rows]
    gaps = [r["gap"] for r in rows]
    n = len(rows)
    summary = {
        "name": args.name, "n": n,
        "mean_reward_train": sum(rt) / n, "mean_reward_heldout": sum(rh) / n,
        "mean_gap": sum(gaps) / n,
        "mean_abs_gap": sum(abs(g) for g in gaps) / n,
        "max_abs_gap": max(abs(g) for g in gaps),
        "share_abs_gap_gt_0.05": sum(abs(g) > 0.05 for g in gaps) / n,
        "pearson": _pearson(rt, rh),
        "unreadable_either": sum(not r["readable"] for r in rows),
        "scorer_reading": ("per record, stage_a.scoring.scorer_config_for, with "
                           "the held-out sampling seed and density on top"),
        "rows_without_reply": reply_counts["rows_without_reply"],
        "read_without_the_reply": reply_counts["read_without_the_reply"],
        "by_operation": {},
        "sources": {"per_task": _relative(per_task),
                    "tasks": _relative(tasks_file),
                    "gold_cache": _relative(gold_cache)},
    }
    for op in sorted({r["operation"] for r in rows}):
        sub = [r for r in rows if r["operation"] == op]
        summary["by_operation"][op] = {
            "n": len(sub),
            "mean_reward_train": sum(r["reward_train"] for r in sub) / len(sub),
            "mean_reward_heldout": sum(r["reward_heldout"] for r in sub) / len(sub),
            "mean_gap": sum(r["gap"] for r in sub) / len(sub),
        }
    out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
