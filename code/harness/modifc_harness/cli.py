"""Command line entry points for the harness.

Three subcommands:

``serve-command``  print the vLLM invocation for one model, sized against the
                   memory that is free on the card right now
``gpu``            print the current GPU memory state
``run``            run a set of tasks against an already-running server
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .bakeoff import run_model
from .config import AgentConfig, RetryConfig, RunConfig, ServerConfig
from .models import MODELS, build_serve_command
from .runner import run_benchmark
from .serve import (
    DEFAULT_HEADROOM_MIB,
    plan_memory_utilization,
    read_gpu_memory,
    running_serve_command,
)
from .tasks import load_slice_ids

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--port", type=int, default=8000)


def cmd_gpu(args: argparse.Namespace) -> int:
    memory = read_gpu_memory()
    print(json.dumps(memory.__dict__, indent=2))
    return 0


def cmd_serve_command(args: argparse.Namespace) -> int:
    spec = MODELS[args.model]
    utilization, memory = plan_memory_utilization(headroom_mib=args.headroom_mib)
    command = build_serve_command(
        spec,
        gpu_memory_utilization=utilization,
        port=args.port,
        max_model_len=args.max_model_len,
    )
    print(json.dumps({"gpu": memory.__dict__, "utilization": utilization}, indent=2), file=sys.stderr)
    print(" ".join(command))
    return 0


def cmd_serve_env(args: argparse.Namespace) -> int:
    print(MODELS[args.model].conda_env)
    return 0


def cmd_bakeoff(args: argparse.Namespace) -> int:
    ids = load_slice_ids(args.slice_file)
    if args.limit:
        ids = ids[: args.limit]
    report = run_model(
        spec=MODELS[args.model],
        task_ids=ids,
        results_dir=Path(args.results_dir),
        tasks_file=Path(args.tasks_file),
        scenes_dir=Path(args.scenes_dir),
        port=args.port,
        headroom_mib=args.headroom_mib,
        max_model_len=args.max_model_len,
        max_restarts=args.max_restarts,
        agent=AgentConfig(
            max_tool_rounds=args.max_tool_rounds,
            tool_timeout=args.tool_timeout,
            max_tokens=args.max_tokens,
            max_tool_output_chars=args.max_tool_output_chars,
        ),
        resume=not args.no_resume,
        notes=args.notes,
    )
    print(json.dumps(report, indent=2))
    return 0


PROBE_TASKS = [
    "COL-UPD-DIR-B37-002", "WAL-UPD-SPA-B25-005", "SLB-UPD-TOP-B36-005",
    "SPC-UPD-DIR-B25-003", "WIN-CRE-DIR-B23-001", "DOR-CRE-SPA-B16-003",
    "WAL-CRE-TOP-B23-006", "SLB-DEL-DIR-B37-001", "WAL-DEL-SPA-B23-004",
    "SPC-DEL-TOP-B23-007",
]


def cmd_probe(args: argparse.Namespace) -> int:
    """Sample several trajectories per task, to see what the base model can do."""
    spec = MODELS[args.model]
    report = run_model(
        spec=spec,
        task_ids=list(args.task_ids) if args.task_ids else PROBE_TASKS,
        results_dir=Path(args.results_dir),
        tasks_file=Path(args.tasks_file),
        scenes_dir=Path(args.scenes_dir),
        port=args.port,
        headroom_mib=args.headroom_mib,
        max_model_len=args.max_model_len,
        max_restarts=args.max_restarts,
        agent=AgentConfig(
            max_tool_rounds=args.max_tool_rounds,
            tool_timeout=args.tool_timeout,
            temperature=args.temperature,
            top_p=args.top_p,
            max_tokens=args.max_tokens,
            max_tool_output_chars=args.max_tool_output_chars,
        ),
        resume=not args.no_resume,
        notes=args.notes,
        run_tag=f"probe_{spec.tag}",
        task_source="corpus",
        num_samples=args.k,
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    spec = MODELS[args.model]
    if args.task_ids:
        ids = list(args.task_ids)
    elif args.slice_file:
        ids = load_slice_ids(args.slice_file)
    else:
        ids = []

    config = RunConfig(
        model_tag=spec.tag,
        model_path=spec.path,
        results_dir=str(args.results_dir),
        tasks_file=str(args.tasks_file),
        scenes_dir=str(args.scenes_dir),
        task_ids=ids,
        agent=AgentConfig(
            max_tool_rounds=args.max_tool_rounds,
            tool_timeout=args.tool_timeout,
            max_tokens=args.max_tokens,
            max_tool_output_chars=args.max_tool_output_chars,
        ),
        retry=RetryConfig(),
        server=ServerConfig(
            base_url=f"http://127.0.0.1:{args.port}/v1",
            served_model_name=spec.tag,
        ),
        serve_command=running_serve_command(spec.path),
        tool_call_parser=spec.tool_call_parser,
        notes=args.notes,
    )
    outcome = run_benchmark(config, task_ids=ids or None, resume=not args.no_resume)
    print(json.dumps({k: v for k, v in outcome.items() if k != "summary"}, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="modifc-harness")
    sub = parser.add_subparsers(dest="command", required=True)

    p_gpu = sub.add_parser("gpu", help="print GPU memory state")
    p_gpu.set_defaults(func=cmd_gpu)

    p_serve = sub.add_parser("serve-command", help="print the vLLM serve invocation")
    _add_common(p_serve)
    p_serve.add_argument("--headroom-mib", type=int, default=DEFAULT_HEADROOM_MIB)
    p_serve.add_argument("--max-model-len", type=int, default=None)
    p_serve.set_defaults(func=cmd_serve_command)

    p_env = sub.add_parser("serve-env", help="print the conda environment for a model")
    p_env.add_argument("--model", required=True, choices=sorted(MODELS))
    p_env.set_defaults(func=cmd_serve_env)

    p_bake = sub.add_parser("bakeoff", help="serve a model, run a slice, shut down")
    _add_common(p_bake)
    p_bake.add_argument("--slice-file", default=str(PROJECT_ROOT / "phase0/bakeoff_slice_v1.json"))
    p_bake.add_argument("--limit", type=int, default=0, help="use only the first N task ids")
    p_bake.add_argument("--results-dir", default=str(PROJECT_ROOT / "runs_local"))
    p_bake.add_argument("--tasks-file", default=str(PROJECT_ROOT / "data/bimedit/BIM-Edit-Tasks/tasks.jsonl"))
    p_bake.add_argument("--scenes-dir", default=str(PROJECT_ROOT / "data/bimedit/BIM-Edit"))
    p_bake.add_argument("--headroom-mib", type=int, default=DEFAULT_HEADROOM_MIB)
    p_bake.add_argument("--max-model-len", type=int, default=None)
    p_bake.add_argument("--max-restarts", type=int, default=3)
    p_bake.add_argument("--max-tool-rounds", type=int, default=22)
    p_bake.add_argument("--tool-timeout", type=float, default=420.0)
    p_bake.add_argument("--max-tokens", type=int, default=8192)
    p_bake.add_argument("--max-tool-output-chars", type=int, default=16000)
    p_bake.add_argument("--no-resume", action="store_true")
    p_bake.add_argument("--notes", default="")
    p_bake.set_defaults(func=cmd_bakeoff)

    p_probe = sub.add_parser("probe", help="sample k trajectories per task")
    _add_common(p_probe)
    p_probe.add_argument("--task-ids", nargs="*", default=[])
    p_probe.add_argument("--k", type=int, default=8)
    p_probe.add_argument("--temperature", type=float, default=0.8)
    p_probe.add_argument("--top-p", type=float, default=0.95)
    p_probe.add_argument("--results-dir", default=str(PROJECT_ROOT / "runs_local"))
    p_probe.add_argument("--tasks-file", default=str(PROJECT_ROOT / "data/modifc_tasks_smoke/tasks.jsonl"))
    p_probe.add_argument("--scenes-dir", default=str(PROJECT_ROOT))
    p_probe.add_argument("--headroom-mib", type=int, default=DEFAULT_HEADROOM_MIB)
    p_probe.add_argument("--max-model-len", type=int, default=65536)
    p_probe.add_argument("--max-restarts", type=int, default=3)
    p_probe.add_argument("--max-tool-rounds", type=int, default=22)
    p_probe.add_argument("--tool-timeout", type=float, default=420.0)
    p_probe.add_argument("--max-tokens", type=int, default=8192)
    p_probe.add_argument("--max-tool-output-chars", type=int, default=16000)
    p_probe.add_argument("--no-resume", action="store_true")
    p_probe.add_argument("--notes", default="")
    p_probe.set_defaults(func=cmd_probe)

    p_run = sub.add_parser("run", help="run tasks against a running server")
    _add_common(p_run)
    p_run.add_argument("--task-ids", nargs="*", default=[])
    p_run.add_argument("--slice-file", default=None)
    p_run.add_argument("--results-dir", default=PROJECT_ROOT / "runs_local")
    p_run.add_argument("--tasks-file", default=PROJECT_ROOT / "data/bimedit/BIM-Edit-Tasks/tasks.jsonl")
    p_run.add_argument("--scenes-dir", default=PROJECT_ROOT / "data/bimedit/BIM-Edit")
    p_run.add_argument("--max-tool-rounds", type=int, default=22)
    p_run.add_argument("--tool-timeout", type=float, default=420.0)
    p_run.add_argument("--max-tokens", type=int, default=8192)
    p_run.add_argument("--max-tool-output-chars", type=int, default=16000)
    p_run.add_argument("--no-resume", action="store_true")
    p_run.add_argument("--notes", default="")
    p_run.set_defaults(func=cmd_run)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
