#!/usr/bin/env python
"""Three-task plumbing check for one served model.

This checks that the server answers, that its tool calls parse, that the sandbox
executes code, that ``commit()`` writes a file, and that a transcript is saved.
It says nothing about how good the edits are.

Run it with the `l2` environment's Python while a server for the model is up:

    python scripts/smoke_test.py --model granite-4.1-8b --port 8000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HARNESS_DIR))

from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.config import AgentConfig, RetryConfig, RunConfig, ServerConfig  # noqa: E402
from modifc_harness.models import MODELS  # noqa: E402
from modifc_harness.runner import run_benchmark  # noqa: E402
from modifc_harness.sandbox import Sandbox  # noqa: E402
from modifc_harness.serve import read_gpu_memory, running_serve_command  # noqa: E402
from modifc_harness.tasks import load_tasks  # noqa: E402

PROJECT_ROOT = HARNESS_DIR.parents[1]

# One create, one update, one delete; two realistic scenes and one artificial.
SMOKE_TASKS = [
    "WIN-CRE-DIR-A-001",  # create, direct, artificial scene
    "COL-UPD-DIR-R-002",  # update, direct, realistic scene
    "WAL-DEL-TOP-R-003",  # delete, topological, realistic scene
]


def commit_probe(task_id: str, tasks_file: Path, scenes_dir: Path, scratch: Path) -> dict:
    """Prove the sandbox and ``commit()`` work on this machine for a real task.

    The model may or may not call ``commit()``; this check is about the harness,
    so it runs one snippet through the same sandbox and confirms the model on
    disk changes.
    """
    task = load_tasks(tasks_file, scenes_dir)[task_id]
    working = scratch / "commit_probe" / f"{task.input_ifc.stem}_0.ifc"
    sandbox = Sandbox(task.input_ifc, working, scratch / "commit_probe.log")
    sandbox.start()
    try:
        before = working.stat().st_size
        snippet = sandbox.execute(
            "before = len(ifc.by_type('IfcBuildingElementProxy'))\n"
            "ifc.create_entity('IfcBuildingElementProxy', GlobalId=guid.new())\n"
            "commit()\n"
            "result = {'proxies_before': before, "
            "'proxies_after': len(ifc.by_type('IfcBuildingElementProxy'))}",
            timeout=600,
        )
        after = working.stat().st_size
        return {
            "task_id": task_id,
            "ok": snippet.ok and snippet.commits == 1 and after != before,
            "commits": snippet.commits,
            "bytes_before": before,
            "bytes_after": after,
            "output": snippet.as_tool_output(400),
        }
    finally:
        sandbox.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True, choices=sorted(MODELS))
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--results-dir", default=str(PROJECT_ROOT / "runs_local"))
    parser.add_argument("--max-tool-rounds", type=int, default=22)
    parser.add_argument("--tool-timeout", type=float, default=420.0)
    parser.add_argument("--tasks", nargs="*", default=SMOKE_TASKS)
    parser.add_argument("--no-resume", action="store_true")
    args = parser.parse_args()

    spec = MODELS[args.model]
    base_url = f"http://127.0.0.1:{args.port}/v1"

    client = ChatClient(base_url, spec.tag, max_attempts=1)
    models = client.wait_until_ready(timeout=1800)
    print("server models:", [m["id"] for m in models.get("data", [])], flush=True)
    print("gpu before:", read_gpu_memory().__dict__, flush=True)

    config = RunConfig(
        model_tag=spec.tag,
        model_path=spec.path,
        results_dir=args.results_dir,
        tasks_file=str(PROJECT_ROOT / "data/bimedit/BIM-Edit-Tasks/tasks.jsonl"),
        scenes_dir=str(PROJECT_ROOT / "data/bimedit/BIM-Edit"),
        task_ids=list(args.tasks),
        agent=AgentConfig(max_tool_rounds=args.max_tool_rounds, tool_timeout=args.tool_timeout),
        retry=RetryConfig(),
        server=ServerConfig(base_url=base_url, served_model_name=spec.tag),
        serve_command=running_serve_command(spec.path),
        tool_call_parser=spec.tool_call_parser,
        notes="smoke test",
    )

    outcome = run_benchmark(config, task_ids=list(args.tasks), resume=not args.no_resume)
    print("gpu after:", read_gpu_memory().__dict__, flush=True)

    probe = commit_probe(
        args.tasks[0],
        Path(config.tasks_file),
        Path(config.scenes_dir),
        Path(outcome["run_dir"]) / "probe",
    )
    print("\ncommit probe:", json.dumps({k: v for k, v in probe.items() if k != "output"}))

    print("\nverdict per task (plumbing only; nothing here judges edit quality)")
    all_ok = probe["ok"]
    for entry in outcome["summary"]:
        checks = {
            "tool_calls_parsed": entry["tool_calls"] > 0,
            "code_executed": entry["tool_rounds"] > 0,
            "edited_file_on_disk": entry["edited_exists"] and entry["edited_bytes"] > 0,
            "stop_reason_recorded": bool(entry["stop_reason"]),
        }
        ok = all(checks.values())
        all_ok = all_ok and ok
        print(
            f"  {entry['task_id']:20s} {'PASS' if ok else 'FAIL'} "
            f"stop={entry['stop_reason']} rounds={entry['tool_rounds']} "
            f"calls={entry['tool_calls']} model_commits={entry['commits']} "
            f"out_tok={entry['output_tokens']} "
            f"{entry['output_tokens_per_second']} tok/s {entry['duration_seconds']} s"
        )
        if not ok:
            print("      failed checks:", [k for k, v in checks.items() if not v])

    print(json.dumps({"model": spec.tag, "all_pass": all_ok, "run_dir": outcome["run_dir"]}, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
