"""The do-nothing arm: score every task's unedited input file as if it were the answer.

Every results table needs the floor. A task's score is not zero when nothing is
done to it, because the verifier compares whole models and most of a building is
already correct before the edit; on the held-out set that floor is about 0.14 of
the final score. An arm that submits the input file unchanged measures that floor
under exactly the scorer, the gold models and the gold cache the model arms use,
so the two columns of the table are the same measurement and differ only in what
produced the file.

No model and no server are involved, so this runs on CPU alone in a few minutes.
The rows it writes carry the same fields as the evaluation driver's rows, with
the tool counters at zero and ``stop_reason`` set to ``null``, so the same
summariser, the same paired test and the same held-out gap script read them
without a special case.

Run in the ``l2`` environment from the project root, pinned away from the
trainer's cores:

    OMP_NUM_THREADS=1 PYTHONPATH=code taskset -c 14-23 \\
        python -m stage_c.null_arm \\
            --tasks-file data/veribim_tasks_e2/e2_tasks.jsonl \\
            --subset runs_local/e2/e2_subset_432.json \\
            --run-dir runs_local/e2 --gold-cache runs_local/e2/_gold_e2 \\
            --workers 6

Writes ``<run-dir>/per_task_<name>.jsonl`` and ``<run-dir>/summary_<name>.json``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from stage_a import paths
from stage_a.gate_eval import load_subset, score_rows, summarize

paths.ensure_harness_on_path()

from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.tasks import normalise_path  # noqa: E402


def null_rows(name: str, records: list[dict], project_root: Path) -> list[dict]:
    """One row per task, pointing at the task's own unedited input model."""
    rows = []
    for record in records:
        source = project_root / normalise_path(record["input_ifc"])
        rows.append({
            "adapter": name,
            "task_id": record["task_id"],
            "operation": record["operation"],
            "category": record["category"],
            "edit_kind": record.get("edit_kind", ""),
            "stop_reason": "null",
            "tool_rounds": 0,
            "tool_calls": 0,
            "well_formed_calls": 0,
            "compiling_calls": 0,
            "running_calls": 0,
            "commits": 1,
            "committed": True,
            "input_tokens": 0,
            "output_tokens": 0,
            "finish_reasons": [],
            "duration_seconds": 0.0,
            "error": None,
            # The arm says nothing, which is the floor an under-specified task
            # is measured against: its answer is to change nothing and ask.
            "reply": "",
            "edited_ifc": str(source),
            "edited_exists": source.is_file(),
        })
    return rows


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stage-c-null-arm")
    ap.add_argument("--tasks-file", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--gold-cache", required=True)
    ap.add_argument("--name", default="null_edit")
    # The floor has to be read the way the model arms are read, or the two
    # columns of the table are two different measurements. The default is the
    # published reading, which is what every earlier call used.
    ap.add_argument("--scorer-reading", choices=("published", "family"),
                    default="published")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0,
                    help="smoke test on the first N tasks of the subset")
    ap.add_argument("--label", default="", help="tag written into the summary")
    args = ap.parse_args(argv)

    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / f"per_task_{args.name}.jsonl"
    if out.exists():
        raise SystemExit(f"{out} exists; refusing to overwrite")

    records = load_subset(Path(args.subset), Path(args.tasks_file))
    if args.limit:
        records = records[: args.limit]
    rows = null_rows(args.name, records, paths.PROJECT_ROOT)
    missing = [r["task_id"] for r in rows if not r["edited_exists"]]
    if missing:
        raise SystemExit(f"{len(missing)} input models are not on disk: {missing[:5]}")

    print(f"  {args.name}: {len(rows)} tasks, {args.workers} scorer workers", flush=True)
    rows = score_rows(records, rows, args.workers, paths.PROJECT_ROOT,
                      Path(args.gold_cache),
                      family_reading=args.scorer_reading == "family")
    with out.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    summary = summarize(args.name, rows, AgentConfig())
    summary["per_task_file"] = str(out)
    summary["subset"] = str(args.subset)
    summary["tasks_file"] = str(args.tasks_file)
    summary["gold_cache"] = str(args.gold_cache)
    summary["scorer_reading"] = args.scorer_reading
    summary["label"] = args.label
    summary["arm"] = "null_edit"
    summary["note"] = ("no model and no server were involved: every row's file is the "
                       "task's own unedited input model, so the tool counters are zero "
                       "and the agent configuration is the default rather than a "
                       "resolved one")
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    (run_dir / f"summary_{args.name}.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("adapter", "n_tasks", "n_scored", "mean_final",
                       "by_category", "by_operation", "axis_means")}, indent=2),
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
