"""Rejection sampling on the GPU: many trajectories at once, against one server.

The harness's own runner walks a task list one trajectory at a time, which is
right for an evaluation run and far too slow to build training data: the
bootstrap probe averaged 139 s per trajectory, so a k=8 harvest would cover two
dozen tasks in a shift. The Phase-0 concurrency spike measured the alternative
on the same protocol: trajectories run together against one server, which
batches them, and the cost per trajectory falls by more than an order of
magnitude.

This module is that measurement turned into a production sampler. Nothing about
the protocol changes: the same agent loop, the same system prompt, the same
single tool, the same sandbox worker per trajectory, the same stop rules. What
changes is that a pool of them is in flight at once, the work is ordered so that
stopping early still leaves broad coverage, and the run is bounded by a wall
clock rather than by a task count.

Three practical rules are built in.

*Breadth before depth.* Tasks are walked in a round robin over building, edit
kind and category, so a run that stops at its deadline has spread its samples
over the set rather than exhausted one building.

*A trajectory that never committed is deleted as it finishes.* Its file is still
byte-identical to the input model, and the highest score any unedited model
earns on this task set is 0.843, well under the keep floor. Keeping them would
cost tens of gigabytes to prove the same thing twice.

*The card is handed back.* The server is started, supervised and shut down here,
and the run stops on its own deadline rather than being killed.
"""

from __future__ import annotations

import json
import os
import random
import shutil
import signal
import threading
import time
from collections import Counter, OrderedDict, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import paths

paths.ensure_harness_on_path()

from modifc_harness.agent import run_task  # noqa: E402
from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.models import MODELS, build_serve_command  # noqa: E402
from modifc_harness.serve import (  # noqa: E402
    ServerSupervisor,
    plan_memory_utilization,
    read_gpu_memory,
)
from modifc_harness.tasks import Task, normalise_path  # noqa: E402


def load_pool(tasks_file: Path, split: str = "train",
              operations: Sequence[str] = ("update", "delete"),
              max_source_mb: float = 40.0,
              project_root: Path | None = None) -> list[dict]:
    """The task records this harvest may draw from.

    The source-size cap is a throughput and host-memory decision, not a quality
    one: a hundred-megabyte model is copied and parsed once per trajectory, and
    two dozen of those in flight would spend the budget on file handling and
    crowd the box. The cap is reported with the coverage it leaves.
    """
    project_root = project_root or paths.PROJECT_ROOT
    sizes: dict[str, float] = {}
    out: list[dict] = []
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("split") != split:
                continue
            if record["operation"] not in operations:
                continue
            relative = normalise_path(record["input_ifc"])
            if relative not in sizes:
                try:
                    sizes[relative] = (project_root / relative).stat().st_size / 1e6
                except OSError:
                    sizes[relative] = float("inf")
            if sizes[relative] > max_source_mb:
                continue
            record["_source_mb"] = round(sizes[relative], 2)
            out.append(record)
    return out


def breadth_first_order(records: Sequence[dict], seed: int = 20260825) -> list[dict]:
    """Round robin over building, edit kind and category.

    Whatever the deadline cuts off, what has been sampled is spread over the
    set: every cell contributes its first task before any cell contributes its
    second.

    The cells are visited in a seeded shuffle rather than sorted order, which
    matters more than it looks. Sorted order starts at the alphabetically first
    edit kind, and on this task set that is a compositional wall deletion: the
    first seven tasks of a run ordered that way were all the same kind, six of
    them pinned at the round cap. A shuffle spends the opening of a run on a
    mix of kinds, so a budget that runs out early still bought variety.
    """
    cells: dict[tuple, list[dict]] = {}
    for record in sorted(records, key=lambda r: r["task_id"]):
        key = (record.get("building_id", ""), record.get("edit_kind", ""),
               record.get("category", ""))
        cells.setdefault(key, []).append(record)
    keys = sorted(cells)
    random.Random(seed).shuffle(keys)
    ordered: list[dict] = []
    depth = 0
    while True:
        added = False
        for key in keys:
            bucket = cells[key]
            if depth < len(bucket):
                ordered.append(bucket[depth])
                added = True
        if not added:
            break
        depth += 1
    return ordered


def chunked_building_order(records: Sequence[dict], chunk: int = 64,
                           seed: int = 20260825) -> list[dict]:
    """Round robin over buildings, a chunk of tasks at a time.

    Pure breadth-first ordering spreads coverage perfectly and costs a factor of
    five in throughput, because a building is a source model: consecutive tasks
    on one building reuse a parsed model, and a walk that changes building every
    task re-parses one every time and re-runs the large-model gate besides. This
    order keeps both properties. Buildings are visited in a seeded round robin
    so a run that stops early has touched them all, and each visit takes a chunk
    of that building's tasks, spread over its edit kinds and categories, so the
    parsed model earns its keep before the walk moves on.
    """
    buildings: dict[str, list[dict]] = {}
    for record in sorted(records, key=lambda r: r["task_id"]):
        buildings.setdefault(record.get("building_id", ""), []).append(record)
    # Inside one building, interleave its cells so a chunk is not all one kind.
    for key, bucket in buildings.items():
        cells: dict[tuple, list[dict]] = {}
        for record in bucket:
            cells.setdefault((record.get("edit_kind", ""),
                              record.get("category", "")), []).append(record)
        order = sorted(cells)
        random.Random(seed ^ hash(key) & 0xFFFFFFFF).shuffle(order)
        spread: list[dict] = []
        depth = 0
        while True:
            added = False
            for cell in order:
                if depth < len(cells[cell]):
                    spread.append(cells[cell][depth])
                    added = True
            if not added:
                break
            depth += 1
        buildings[key] = spread

    keys = sorted(buildings)
    random.Random(seed).shuffle(keys)
    ordered: list[dict] = []
    offset = 0
    while True:
        added = False
        for key in keys:
            bucket = buildings[key]
            piece = bucket[offset:offset + chunk]
            if piece:
                ordered.extend(piece)
                added = True
        if not added:
            break
        offset += chunk
    return ordered


def as_task(record: dict, project_root: Path) -> Task:
    return Task(
        task_id=record["task_id"],
        operation=record["operation"],
        category=record["category"],
        prompt=record.get("instruction") or record["prompt"],
        input_ifc=project_root / normalise_path(record["input_ifc"]),
        ground_truth_ifc=project_root / normalise_path(record["ground_truth_ifc"]),
        target=record.get("target") or {},
        tags=[f"family:{record.get('family')}", f"tier:{record.get('tier')}",
              f"edit_kind:{record.get('edit_kind')}",
              f"element_type:{record.get('element_type')}"],
    )


class Sampler:
    """One served model, a pool of concurrent trajectories, a wall-clock budget."""

    def __init__(self, run_dir: Path, records: Sequence[dict], client: ChatClient,
                 agent: AgentConfig, k: int, concurrency: int,
                 project_root: Path, deadline: float,
                 supervisor: ServerSupervisor | None = None,
                 python_executable: str | None = None,
                 drop_uncommitted: bool = True) -> None:
        self.run_dir = Path(run_dir)
        self.records = list(records)
        self.client = client
        self.agent = agent
        self.k = k
        self.concurrency = concurrency
        self.project_root = Path(project_root)
        self.deadline = deadline
        self.supervisor = supervisor
        self.python_executable = python_executable
        self.drop_uncommitted = drop_uncommitted
        self.cache: dict[str, dict] = {}
        self.summary: list[dict] = []
        self.stops: Counter = Counter()
        self.lock = threading.Lock()
        self.trajectories = 0
        self.kept_files = 0
        self.dropped_files = 0
        self.edited = self.run_dir / "edited"
        self.logs = self.run_dir / "logs"

    # ------------------------------------------------------------- storage
    def _cache_file(self) -> Path:
        return self.run_dir / f"cache_{self.run_dir.name}.json"

    def _flush(self) -> None:
        tmp = self._cache_file().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.cache, indent=1), encoding="utf-8")
        tmp.replace(self._cache_file())
        (self.run_dir / "run_summary.json").write_text(
            json.dumps(self.summary, indent=1), encoding="utf-8")

    # -------------------------------------------------------------- rollout
    def _one(self, record: dict, sample: int) -> dict:
        task = as_task(record, self.project_root)
        working = (self.edited / record["task_id"] / f"sample_{sample}"
                   / f"{task.input_ifc.stem}.ifc")
        log_file = self.logs / f"{record['task_id']}_sample_{sample}.log"
        started = time.monotonic()
        result = run_task(task=task, working_ifc=working, client=self.client,
                          agent_config=self.agent, log_file=log_file,
                          python_executable=self.python_executable)
        # A run whose server died is worth one clean retry; nothing else is.
        if (self.supervisor is not None and result.stop_reason == "inference_error"
                and not self.supervisor.healthy()):
            if self.supervisor.restart(reason=f"inference_error on {task.task_id}"):
                result = run_task(task=task, working_ifc=working, client=self.client,
                                  agent_config=self.agent, log_file=log_file,
                                  python_executable=self.python_executable)
        dropped = False
        if self.drop_uncommitted and result.commits < 1:
            shutil.rmtree(working.parent, ignore_errors=True)
            dropped = True
        try:
            log_file.unlink()
        except OSError:
            pass
        with self.lock:
            self.trajectories += 1
            self.stops[result.stop_reason] += 1
            self.dropped_files += int(dropped)
            self.kept_files += int(not dropped)
        return {
            "model_output": result.model_output,
            "input_tokens": result.prompt_tokens,
            "output_tokens": result.completion_tokens,
            "tool_call_iterations": result.iterations,
            "duration_seconds": round(result.duration_seconds, 2),
            "error": result.error,
            "runtime_info": {
                "stop_reason": result.stop_reason,
                "error_type": result.error_type,
                "error_message": result.error,
                "duration_seconds": round(result.duration_seconds, 2),
                "tool_rounds": result.tool_rounds,
                "tool_calls": result.tool_calls,
                "llm_calls": result.llm_calls,
                "commits": result.commits,
                "finish_reasons": result.finish_reasons,
                "capped_tool_outputs": result.truncated_tool_outputs,
                "reasoning_chars": result.reasoning_chars,
            },
            "messages": result.messages,
            "sample": sample,
            "edited_ifc": "" if dropped else str(working.relative_to(self.run_dir)),
            "artifact_dropped": dropped,
        }

    def _task(self, record: dict, pool: ThreadPoolExecutor) -> None:
        started_at = datetime.now().isoformat(timespec="seconds")
        futures = [pool.submit(self._one, record, i) for i in range(1, self.k + 1)]
        results = [f.result() for f in futures]
        committed = sum(1 for r in results if r["runtime_info"]["commits"] > 0)
        with self.lock:
            self.cache[record["task_id"]] = {
                "task_id": record["task_id"],
                "prompt": record.get("instruction") or record["prompt"],
                "model": self.client.model,
                "input_ifc": str(self.project_root / normalise_path(record["input_ifc"])),
                "ground_truth_ifc": str(self.project_root
                                        / normalise_path(record["ground_truth_ifc"])),
                "operation": record["operation"],
                "category": record["category"],
                "tags": [f"edit_kind:{record.get('edit_kind')}",
                         f"building:{record.get('building_id')}"],
                "results": results,
                "benchmark_runtime": {
                    "status": "ok",
                    "samples_requested": self.k,
                    "samples_completed": len(results),
                    "started_at": started_at,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                },
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            self.summary.append({
                "task_id": record["task_id"],
                "building": record.get("building_id"),
                "operation": record["operation"],
                "category": record["category"],
                "edit_kind": record.get("edit_kind"),
                "source_mb": record.get("_source_mb"),
                "samples": len(results),
                "committed": committed,
                "mean_rounds": round(sum(r["runtime_info"]["tool_rounds"]
                                         for r in results) / len(results), 2),
                "seconds": round(sum(r["duration_seconds"] for r in results), 1),
            })

    def adopt(self) -> int:
        """Take over a run directory a previous process left behind."""
        path = self._cache_file()
        if not path.exists():
            return 0
        try:
            self.cache = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        summary_path = self.run_dir / "run_summary.json"
        if summary_path.exists():
            try:
                self.summary = json.loads(summary_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                self.summary = []
        done = set(self.cache)
        self.records = [r for r in self.records if r["task_id"] not in done]
        return len(done)

    def run(self, flush_every: int = 5, progress: bool = True) -> dict:
        self.edited.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        done = 0
        # One task's k samples are submitted together. More tasks are in flight
        # than the pool can serve at once, deliberately: a task's samples finish
        # at different times, and without a queue behind them the pool drains to
        # a trickle while the last sample of a task runs on.
        in_flight = max(2, 2 * (self.concurrency // max(1, self.k)))
        with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
            with ThreadPoolExecutor(max_workers=in_flight) as tasks:
                pending: list = []
                for record in self.records:
                    if time.monotonic() >= self.deadline:
                        break
                    pending.append(tasks.submit(self._task, record, pool))
                    while len(pending) >= in_flight:
                        pending.pop(0).result()
                        done += 1
                        if progress and done % flush_every == 0:
                            self._flush()
                            elapsed = time.monotonic() - started
                            print(f"  {done} tasks, {self.trajectories} trajectories, "
                                  f"{self.kept_files} artifacts kept, "
                                  f"{elapsed / 60:.1f} min, "
                                  f"{elapsed / max(1, self.trajectories):.1f} s/traj",
                                  flush=True)
                for future in pending:
                    future.result()
                    done += 1
        self._flush()
        elapsed = time.monotonic() - started
        return {
            "tasks_sampled": len(self.cache),
            "tasks_sampled_this_run": done,
            "trajectories": self.trajectories,
            "artifacts_kept": self.kept_files,
            "artifacts_dropped_no_commit": self.dropped_files,
            "stop_reasons": dict(self.stops),
            "seconds": round(elapsed, 1),
            "seconds_per_trajectory": round(elapsed / max(1, self.trajectories), 2),
            "deadline_reached": time.monotonic() >= self.deadline,
        }


def harvest_sampling_run(model_tag: str, tasks_file: Path, run_dir: Path,
                         hours: float = 8.0, k: int = 8, concurrency: int = 24,
                         temperature: float = 0.8, top_p: float = 0.95,
                         max_tool_rounds: int = 16, max_source_mb: float = 40.0,
                         split: str = "train",
                         operations: Sequence[str] = ("update", "delete"),
                         port: int = 8000, headroom_mib: int = 3072,
                         max_model_len: int = 65536,
                         sandbox_cores: str | Sequence[int] = (),
                         server_cores: str = "",
                         python_executable: str | None = None) -> dict:
    """Serve the pinned base, sample until the budget is spent, release the card."""
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    project_root = paths.PROJECT_ROOT

    if isinstance(sandbox_cores, str):
        sandbox_cores = parse_cores(sandbox_cores)
    records = load_pool(Path(tasks_file), split=split, operations=operations,
                        max_source_mb=max_source_mb, project_root=project_root)
    ordered = breadth_first_order(records)

    spec = MODELS[model_tag]
    utilization, before = plan_memory_utilization(headroom_mib=headroom_mib)
    command = build_serve_command(spec, gpu_memory_utilization=utilization,
                                  port=port, max_model_len=max_model_len)
    if server_cores:
        command = ["taskset", "-c", server_cores] + command
    base_url = f"http://127.0.0.1:{port}/v1"
    supervisor = ServerSupervisor(command=command, log_dir=run_dir,
                                  model_tag=run_dir.name, base_url=base_url,
                                  conda_env=spec.conda_env, max_restarts=3)

    agent = AgentConfig(max_tool_rounds=max_tool_rounds, temperature=temperature,
                        top_p=top_p, max_tokens=spec.max_tokens)
    client = ChatClient(base_url=base_url, model=spec.tag,
                        request_timeout=1800.0, max_attempts=2, retry_delay=30.0)

    resolved = {
        "run_dir": str(run_dir),
        "model": spec.tag,
        "model_path": spec.path,
        "tasks_file": str(tasks_file),
        "split": split,
        "operations": list(operations),
        "pool_size": len(records),
        "pool_buildings": len({r.get("building_id") for r in records}),
        "pool_edit_kinds": sorted({r.get("edit_kind") for r in records}),
        "max_source_mb": max_source_mb,
        "k": k,
        "concurrency": concurrency,
        "sampling": {"temperature": temperature, "top_p": top_p,
                     "max_tokens": spec.max_tokens},
        "max_tool_rounds": max_tool_rounds,
        "budget_hours": hours,
        "serve_command": command,
        "gpu_memory_utilization": utilization,
        "gpu_free_at_launch_mib": before.free_mib,
        "gpu_used_at_launch_mib": before.used_mib,
        "sandbox_cores": list(sandbox_cores),
        "server_cores": server_cores,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "config.json").write_text(json.dumps(resolved, indent=2),
                                         encoding="utf-8")
    print(json.dumps({k2: v for k2, v in resolved.items()
                      if k2 not in ("serve_command",)}, indent=2), flush=True)

    if sandbox_cores and hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(sandbox_cores))
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[name] = "1"

    # A stop signal has to reach the card, not just the driver: without this the
    # server outlives its client and holds 38 GB until something kills it by
    # hand. The flag turns the deadline into "now", so the pool drains and the
    # normal shutdown path runs.
    stopping = {"asked": False}

    def _stop(signum, frame):  # noqa: ANN001 - signal handler signature
        if not stopping["asked"]:
            stopping["asked"] = True
            print(f"signal {signum}: draining the pool and releasing the card",
                  flush=True)
            holder.get("sampler") and setattr(holder["sampler"], "deadline",
                                              time.monotonic())

    holder: dict[str, Any] = {}
    for signum in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(signum, _stop)
        except ValueError:
            pass

    supervisor.start()
    try:
        client.wait_until_ready(timeout=1800.0)
        sampler = Sampler(run_dir=run_dir, records=ordered, client=client,
                          agent=agent, k=k, concurrency=concurrency,
                          project_root=project_root,
                          deadline=time.monotonic() + hours * 3600.0,
                          supervisor=supervisor,
                          python_executable=python_executable)
        holder["sampler"] = sampler
        resumed = sampler.adopt()
        if resumed:
            print(f"resuming: {resumed} tasks already sampled", flush=True)
        outcome = sampler.run()
        outcome["resumed_from"] = resumed
    finally:
        supervisor.stop()

    after = read_gpu_memory()
    outcome.update({
        "run_dir": str(run_dir),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "gpu_free_after_mib": after.free_mib,
        "gpu_used_after_mib": after.used_mib,
        "coverage": _coverage(sampler.summary),
    })
    (run_dir / "sampling_report.json").write_text(json.dumps(outcome, indent=2),
                                                  encoding="utf-8")
    return outcome


def parse_cores(spec: str) -> list[int]:
    """``"0-5"`` or ``"0,1,4-6"`` as a list of core numbers."""
    cores: list[int] = []
    for piece in str(spec).split(","):
        piece = piece.strip()
        if not piece:
            continue
        if "-" in piece:
            first, last = piece.split("-", 1)
            cores.extend(range(int(first), int(last) + 1))
        else:
            cores.append(int(piece))
    return cores


def _coverage(summary: Sequence[dict]) -> dict:
    return {
        "buildings": len({r["building"] for r in summary}),
        "edit_kinds": len({r["edit_kind"] for r in summary}),
        "by_operation": dict(Counter(r["operation"] for r in summary)),
        "by_category": dict(Counter(r["category"] for r in summary)),
        "by_edit_kind": dict(Counter(r["edit_kind"] for r in summary)),
        "tasks_with_a_commit": sum(1 for r in summary if r["committed"] > 0),
    }
