"""One model, one server, one pass over a task list.

This is the unattended path: it sizes the memory pool against the card as it is
right now, starts the server, runs the tasks, restarts the server a bounded
number of times if it dies, then shuts down and waits for the memory to come
back before returning. Running two models is a matter of calling it twice.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from .config import AgentConfig, RetryConfig, RunConfig, ServerConfig
from .models import MODELS, ModelSpec, build_serve_command
from .runner import RunDirectory, run_benchmark
from .serve import (
    DEFAULT_HEADROOM_MIB,
    ServerSupervisor,
    plan_memory_utilization,
    read_gpu_memory,
)


def run_model(
    spec: ModelSpec,
    task_ids: list[str],
    results_dir: Path,
    tasks_file: Path,
    scenes_dir: Path,
    port: int = 8000,
    headroom_mib: int = DEFAULT_HEADROOM_MIB,
    max_model_len: int | None = None,
    max_restarts: int = 3,
    agent: AgentConfig | None = None,
    resume: bool = True,
    notes: str = "",
    run_tag: str | None = None,
    task_source: str = "bimedit",
    num_samples: int = 1,
) -> dict:
    run_tag = run_tag or spec.tag
    run_dir = RunDirectory(Path(results_dir), run_tag)
    run_dir.prepare()

    utilization, before = plan_memory_utilization(headroom_mib=headroom_mib)
    command = build_serve_command(
        spec, gpu_memory_utilization=utilization, port=port, max_model_len=max_model_len
    )
    base_url = f"http://127.0.0.1:{port}/v1"

    supervisor = ServerSupervisor(
        command=command,
        log_dir=run_dir.root,
        model_tag=run_tag,
        base_url=base_url,
        conda_env=spec.conda_env,
        max_restarts=max_restarts,
    )

    agent_config = agent or AgentConfig()
    if agent_config.max_tokens == AgentConfig().max_tokens:
        agent_config.max_tokens = spec.max_tokens

    config = RunConfig(
        model_tag=run_tag,
        model_path=spec.path,
        results_dir=str(results_dir),
        tasks_file=str(tasks_file),
        scenes_dir=str(scenes_dir),
        task_ids=list(task_ids),
        task_source=task_source,
        num_samples=num_samples,
        agent=agent_config,
        retry=RetryConfig(),
        server=ServerConfig(base_url=base_url, served_model_name=spec.tag),
        serve_command=command,
        tool_call_parser=spec.tool_call_parser,
        notes=notes,
    )

    started = datetime.now().isoformat(timespec="seconds")
    supervisor.start()
    during = read_gpu_memory()
    try:
        outcome = run_benchmark(
            config, task_ids=list(task_ids), resume=resume, supervisor=supervisor
        )
    finally:
        supervisor.stop()
    after = read_gpu_memory()

    report = summarise(outcome["summary"])
    report.update(
        {
            "model_tag": run_tag,
            "served_model": spec.tag,
            "num_samples": num_samples,
            "conda_env": spec.conda_env,
            "tool_call_parser": spec.tool_call_parser,
            "reasoning_parser": spec.reasoning_parser or None,
            "serve_command": " ".join(command),
            "gpu_memory_utilization": utilization,
            "gpu_before": before.__dict__,
            "gpu_serving": during.__dict__,
            "gpu_after": after.__dict__,
            "server_launches": supervisor.launches,
            "server_restarts": supervisor.restarts,
            "started_at": started,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "wall_clock_seconds": outcome["duration_seconds"],
            "run_dir": outcome["run_dir"],
        }
    )
    (run_dir.root / "bakeoff_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


def summarise(summary: list[dict]) -> dict:
    """Aggregate a run's per-task rows into the numbers the report needs."""
    n = len(summary)
    stops = Counter(row["stop_reason"] for row in summary)
    rounds = [row["tool_rounds"] for row in summary]
    out_tokens = [row["output_tokens"] for row in summary]
    durations = [row["duration_seconds"] for row in summary]
    return {
        "n_trajectories": n,
        "n_tasks": len({row["task_id"] for row in summary}),
        "trajectories_modifying_the_file": sum(1 for row in summary if row.get("file_modified")),
        "trajectories_with_commit": sum(1 for row in summary if row["commits"] > 0),
        "stop_reasons": dict(stops),
        "edited_files_written": sum(1 for row in summary if row["edited_exists"]),
        "tasks_with_commit": sum(1 for row in summary if row["commits"] > 0),
        "total_commits": sum(row["commits"] for row in summary),
        "rounds_mean": round(sum(rounds) / n, 2) if n else 0.0,
        "rounds_max": max(rounds) if n else 0,
        "output_tokens_total": sum(out_tokens),
        "output_tokens_mean": round(sum(out_tokens) / n, 1) if n else 0.0,
        "tokens_per_second_mean": (
            round(sum(row["output_tokens_per_second"] for row in summary) / n, 2) if n else 0.0
        ),
        "wall_clock_total_seconds": round(sum(durations), 1),
        "wall_clock_mean_seconds": round(sum(durations) / n, 1) if n else 0.0,
        "tasks_hitting_output_token_cap": sum(
            1 for row in summary if row.get("hit_output_token_cap")
        ),
        "tasks_with_capped_tool_output": sum(
            1 for row in summary if row.get("capped_tool_outputs", 0) > 0
        ),
        "capped_tool_outputs_total": sum(row.get("capped_tool_outputs", 0) for row in summary),
        "context_overflows": stops.get("context_overflow", 0),
    }


def resolve_spec(tag: str) -> ModelSpec:
    return MODELS[tag]
