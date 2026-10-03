"""Command line for the Stage A gate measurement."""

from __future__ import annotations

import argparse
import os
import json
from datetime import datetime
from pathlib import Path

from . import paths
from .gate_eval import load_subset, rollout, score_rows, summarize

paths.ensure_harness_on_path()

from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stage-a-gate")
    ap.add_argument("--adapters", nargs="+", required=True)
    ap.add_argument("--subset", default=str(paths.STAGE_A_DATA / "v1/val_subset_100.json"))
    ap.add_argument("--tasks-file", default=str(paths.PROJECT_ROOT / "data/veribim_tasks_v1/tasks.jsonl"))
    ap.add_argument("--run-dir", default=str(paths.PROJECT_ROOT / "runs_local/stage_a_val_v1"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--score-workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--gold-cache", default=str(paths.STAGE_A_DATA / "_gold_gate"))
    # How each task's scorer settings are resolved. "published" is the reading
    # the published runs and every earlier gate used, and it stays the default.
    # "family" resolves them from the record through scoring.scorer_config_for,
    # which a task set carrying the 0.7.x families needs: a material
    # association and a type assignment leave no trace the published reading
    # sees, and an under-specified instruction is answered by changing nothing
    # and asking, which the published reading scores as a perfect answer for
    # anything that changed nothing at all.
    ap.add_argument("--scorer-reading", choices=("published", "family"),
                    default="published")
    # Protocol values. Exposed so the report can cite them and a
    # departure has to be typed rather than inherited.
    ap.add_argument("--max-tool-rounds", type=int, default=22)
    ap.add_argument("--tool-timeout", type=float, default=420.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-tool-output-chars", type=int, default=16000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--no-transcripts", action="store_true")
    ap.add_argument("--label", default="", help="tag written into the summary")
    args = ap.parse_args(argv)

    records = load_subset(Path(args.subset), Path(args.tasks_file))
    if args.limit:
        records = records[: args.limit]
    agent = AgentConfig(max_tool_rounds=args.max_tool_rounds,
                        tool_timeout=args.tool_timeout,
                        temperature=args.temperature, top_p=args.top_p,
                        max_tokens=args.max_tokens,
                        max_tool_output_chars=args.max_tool_output_chars)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    summaries = []
    for adapter in args.adapters:
        print(f"  {adapter}: {len(records)} tasks, {args.concurrency} in flight",
              flush=True)
        client = ChatClient(base_url=args.base_url, model=adapter,
                            api_key=os.environ.get("VERIBIM_API_KEY", "EMPTY"),
                            request_timeout=1800.0, max_attempts=2, retry_delay=30.0)
        rows = rollout(adapter, records, run_dir, client, agent,
                       args.concurrency, paths.PROJECT_ROOT,
                       keep_transcripts=not args.no_transcripts)
        rows = score_rows(records, rows, args.score_workers, paths.PROJECT_ROOT,
                          Path(args.gold_cache),
                          family_reading=args.scorer_reading == "family")
        out = run_dir / f"per_task_{adapter}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        summary = summarize(adapter, rows, agent)
        summary["per_task_file"] = str(out)
        summary["subset"] = str(args.subset)
        summary["scorer_reading"] = args.scorer_reading
        summary["label"] = args.label
        summary["protocol_conformant"] = (args.max_tool_rounds >= 22
                                          and args.max_tokens >= 8192
                                          and args.tool_timeout >= 420.0
                                          and args.temperature == 0.0)
        summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
        (run_dir / f"summary_{adapter}.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        summaries.append(summary)
        print(json.dumps({k: summary[k] for k in
                          ("adapter", "n_scored", "mean_final", "schema_validity",
                           "code_run", "commit_rate", "stop_reasons")}, indent=2),
              flush=True)

    (run_dir / "summaries.json").write_text(json.dumps(summaries, indent=2),
                                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
