"""Command line for Stage B."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from stage_a import paths

from .pool import (DEFAULT_CELL_KEYS, E2_HOLDOUT, OPERATION_WEIGHTS,
                   load_exclude_ids, load_train_tasks, parse_cell_keys,
                   parse_weights, select, strata)

paths.ensure_harness_on_path()


def cmd_pool(args: argparse.Namespace) -> int:
    weights = parse_weights(getattr(args, "weights", None))
    cell_keys = parse_cell_keys(getattr(args, "cell_keys", None))
    excluded = load_exclude_ids(getattr(args, "exclude_ids_file", None) or ())
    tasks = load_train_tasks(Path(args.tasks_file), split=args.split,
                             exclude_ids=excluded)
    picked = select(tasks, size=args.size, seed=args.seed, weights=weights,
                    cell_keys=cell_keys)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([t["task_id"] for t in picked], indent=1),
                   encoding="utf-8")
    report = {
        "tasks_file": str(args.tasks_file),
        "split": args.split,
        "size_requested": args.size,
        "seed": args.seed,
        "operation_weights": weights,
        "default_operation_weights": OPERATION_WEIGHTS,
        "cell_keys": list(cell_keys),
        "excluded_id_files": list(getattr(args, "exclude_ids_file", None) or ()),
        "excluded_ids": len(excluded),
        "tasks_available": len(tasks),
        "e2_holdout_excluded": sorted(E2_HOLDOUT),
        "strata": strata(picked, weights=weights, cell_keys=cell_keys),
        "subset_file": str(out),
        "written_at": datetime.now().isoformat(timespec="seconds"),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def cmd_sample(args: argparse.Namespace) -> int:
    from modifc_harness.client import ChatClient
    from modifc_harness.config import AgentConfig

    from .sample import run_sampling

    family_reading = args.scorer_reading == "family"
    wanted = set(json.loads(Path(args.subset).read_text(encoding="utf-8")))
    records = [t for t in load_train_tasks(Path(args.tasks_file), split=args.split)
               if t["task_id"] in wanted]
    if args.stride > 1:
        # Walk the subset evenly rather than taking its head: the subset is
        # sorted by task id, so its head is one edit kind on a couple of
        # buildings and tells you nothing about the yield of the whole.
        records = records[:: args.stride]
    if args.limit:
        records = records[: args.limit]
    agent = AgentConfig(max_tool_rounds=args.max_tool_rounds,
                        tool_timeout=args.tool_timeout,
                        temperature=args.temperature, top_p=args.top_p,
                        max_tokens=args.max_tokens,
                        max_tool_output_chars=args.max_tool_output_chars)
    client = ChatClient(base_url=args.base_url, model=args.adapter,
                        request_timeout=1800.0, max_attempts=2, retry_delay=30.0)
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    resolved = {
        "adapter": args.adapter, "k": args.k, "n_tasks": len(records),
        "sampling": {"temperature": args.temperature, "top_p": args.top_p,
                     "max_tokens": args.max_tokens},
        "max_tool_rounds": args.max_tool_rounds,
        "tool_timeout": args.tool_timeout,
        "max_tool_output_chars": args.max_tool_output_chars,
        "concurrency": args.concurrency, "score_workers": args.score_workers,
        "scorer_reading": args.scorer_reading,
        "order_seed": args.order_seed,
        "subset": str(args.subset), "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "config.json").write_text(json.dumps(resolved, indent=2),
                                         encoding="utf-8")
    print(json.dumps(resolved, indent=2), flush=True)
    outcome = run_sampling(
        records=records, run_dir=run_dir, client=client, agent=agent, k=args.k,
        concurrency=args.concurrency, score_workers=args.score_workers,
        project_root=paths.PROJECT_ROOT, gold_cache_root=Path(args.gold_cache),
        deadline=None if not args.hours else __import__("time").monotonic() + args.hours * 3600,
        resume=not args.no_resume, large_concurrency=args.large_concurrency,
        family_reading=family_reading, order_seed=args.order_seed)
    (run_dir / "sampling_report.json").write_text(json.dumps(outcome, indent=2),
                                                  encoding="utf-8")
    print(json.dumps(outcome, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stage-b")
    sub = parser.add_subparsers(dest="command", required=True)
    tasks_default = str(paths.PROJECT_ROOT / "data/veribim_tasks_v1/tasks.jsonl")

    p = sub.add_parser("pool", help="select and describe the sampling subset")
    p.add_argument("--tasks-file", default=tasks_default)
    p.add_argument("--split", default="train")
    p.add_argument("--size", type=int, default=6000)
    p.add_argument("--seed", type=int, default=20260826)
    p.add_argument("--weights", default="",
                   help="operation shares, e.g. create=0.45,delete=0.35,update=0.20; "
                        "empty keeps the pre-registered weights")
    p.add_argument("--cell-keys", default=",".join(DEFAULT_CELL_KEYS),
                   help="fields the round robin spreads over inside an operation")
    p.add_argument("--exclude-ids-file", action="append", default=[],
                   help="JSON list or JSONL of task ids to keep out; repeatable")
    p.add_argument("--out", default=str(paths.STAGE_A_DATA.parent / "stage_b/pool_v1.json"))
    p.add_argument("--report", default=str(paths.STAGE_A_DATA.parent / "stage_b/pool_report.json"))
    p.set_defaults(func=cmd_pool)

    s = sub.add_parser("sample", help="on-policy rollouts, scored and kept")
    s.add_argument("--subset", default=str(paths.STAGE_A_DATA.parent / "stage_b/pool_v1.json"))
    s.add_argument("--tasks-file", default=tasks_default)
    s.add_argument("--split", default="train")
    s.add_argument("--adapter", default="sft590")
    s.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    s.add_argument("--run-dir", default=str(paths.PROJECT_ROOT / "runs_local/stage_b_sample_v1"))
    s.add_argument("--gold-cache", default=str(paths.STAGE_A_DATA.parent / "stage_b/_gold"))
    s.add_argument("--k", type=int, default=6)
    s.add_argument("--concurrency", type=int, default=24)
    s.add_argument("--score-workers", type=int, default=6)
    s.add_argument("--large-concurrency", type=int, default=3,
                   help="rollouts in flight on sources above the size threshold")
    s.add_argument("--limit", type=int, default=0)
    s.add_argument("--stride", type=int, default=1,
                   help="take every Nth task of the subset, for a spread slice")
    s.add_argument("--hours", type=float, default=0.0)
    s.add_argument("--no-resume", action="store_true")
    # Spec §2 sampling settings.
    s.add_argument("--temperature", type=float, default=0.8)
    s.add_argument("--top-p", type=float, default=0.95)
    s.add_argument("--max-tool-rounds", type=int, default=12)
    s.add_argument("--tool-timeout", type=float, default=420.0)
    s.add_argument("--max-tokens", type=int, default=8192)
    s.add_argument("--max-tool-output-chars", type=int, default=16000)
    s.add_argument("--order-seed", type=int, default=None,
                   help="shuffle the pending tasks with this seed so a partial run is a uniform draw")
    s.add_argument("--scorer-reading", choices=("published", "family"),
                   default="published",
                   help="'family' reads each task under the settings its own "
                        "taxonomy tags ask for, which is what the v2 task set "
                        "needs; 'published' is the v1 reading and the default")
    s.set_defaults(func=cmd_sample)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
