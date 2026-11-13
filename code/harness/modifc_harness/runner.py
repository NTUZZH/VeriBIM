"""Run a list of tasks against one served model and write the run directory.

The output layout mirrors the published BIM-Edit run folders so that the
scoring code can read local runs and published runs through the same loader:

``<results_dir>/<model_tag>/``
    ``config.json``               resolved configuration for the run
    ``edited/<task_id>/<file>``   the edited IFC model, the only scored artifact
    ``cache_<model_tag>.json``    one full transcript per task
    ``errors.jsonl``              one line per task that ended on an error
    ``run_summary.json``          per-task status, timing and budget use
    ``logs/``                     sandbox worker logs, one file per task
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

from .agent import STOP_BUDGET, STOP_COMPLETED, STOP_INFERENCE_ERROR, run_task
from .client import ChatClient
from .config import RunConfig
from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_SHA256, TOOL_DESCRIPTION
from .tasks import Task, load_corpus_tasks, load_tasks


class RunDirectory:
    def __init__(self, root: Path, model_tag: str) -> None:
        self.root = Path(root) / model_tag
        self.model_tag = model_tag
        self.edited = self.root / "edited"
        self.logs = self.root / "logs"
        self.cache_file = self.root / f"cache_{model_tag}.json"
        self.errors_file = self.root / "errors.jsonl"
        self.config_file = self.root / "config.json"
        self.summary_file = self.root / "run_summary.json"

    def prepare(self) -> None:
        self.edited.mkdir(parents=True, exist_ok=True)
        self.logs.mkdir(parents=True, exist_ok=True)
        # Always present, so an empty file means "no errors" rather than
        # "the run never got that far".
        self.errors_file.touch(exist_ok=True)

    def working_path(self, task: Task, sample: int = 1, num_samples: int = 1) -> Path:
        """Where one trajectory's model is written.

        A single-sample run keeps the published naming,
        ``edited/<task_id>/<input stem>_0.ifc``. A run that samples several
        trajectories per task gives each its own directory underneath, so the
        eight copies of one task never collide and the scorer can walk them.
        """
        if num_samples > 1:
            return (self.edited / task.task_id / f"sample_{sample}"
                    / f"{task.input_ifc.stem}.ifc")
        return self.edited / task.task_id / f"{task.input_ifc.stem}_{sample - 1}.ifc"

    def load_cache(self) -> dict:
        if self.cache_file.exists():
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        return {}

    def save_cache(self, cache: dict) -> None:
        tmp = self.cache_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(cache, indent=1), encoding="utf-8")
        tmp.replace(self.cache_file)

    def append_error(self, record: dict) -> None:
        with self.errors_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _differs(edited: Path, source: Path) -> bool:
    """True if the edited model is not byte-identical to the model it started from."""
    if not (edited.is_file() and source.is_file()):
        return False
    if edited.stat().st_size != source.stat().st_size:
        return True
    return _sha256(edited) != _sha256(source)


def _is_complete(record: dict, run_dir: "RunDirectory", num_samples: int = 1) -> bool:
    """A cached task counts as done only if it left a usable artifact.

    A transcript alone is not enough: the run is resumable precisely because
    the edited model on disk is the thing the scorer reads, so a record whose
    file is missing, or that never reached a stop reason, is re-run.
    """
    results = record.get("results") or []
    if len(results) < num_samples:
        return False
    for result in results:
        if not (result.get("runtime_info") or {}).get("stop_reason"):
            return False
        edited = run_dir.root / str(result.get("edited_ifc", ""))
        if not (edited.is_file() and edited.stat().st_size > 0):
            return False
    return True


def _summary_from_cache(record: dict, task: Task, run_dir: RunDirectory) -> list[dict]:
    """Rebuild the summary rows for a task that was already in the cache."""
    rows = []
    for result in record["results"]:
        info = result.get("runtime_info", {})
        edited = run_dir.root / result["edited_ifc"]
        duration = float(result.get("duration_seconds") or 0.0)
        completion = int(result.get("output_tokens") or 0)
        source = Path(record["input_ifc"])
        rows.append(_cache_row(record, task, result, info, edited, duration, completion, source))
    return rows


def _cache_row(record, task, result, info, edited, duration, completion, source) -> dict:
    return {
        "task_id": record["task_id"],
        "sample": result.get("sample", 1),
        "operation": task.operation,
        "category": task.category,
        "scene": task.scene,
        "tags": task.tags,
        "stop_reason": info.get("stop_reason", ""),
        "tool_rounds": info.get("tool_rounds", len(result.get("tool_call_iterations") or [])),
        "tool_calls": info.get("tool_calls", 0),
        "llm_calls": info.get("llm_calls", 0),
        "commits": info.get("commits", 0),
        "hit_output_token_cap": "length" in (info.get("finish_reasons") or []),
        "capped_tool_outputs": info.get("capped_tool_outputs", 0),
        "reasoning_chars": info.get("reasoning_chars", 0),
        "sandbox_crashes": info.get("sandbox_crashes", 0),
        "input_tokens": int(result.get("input_tokens") or 0),
        "output_tokens": completion,
        "duration_seconds": round(duration, 2),
        "output_tokens_per_second": round(completion / duration, 2) if duration else 0.0,
        "edited_ifc": str(edited),
        "edited_exists": edited.exists(),
        "edited_bytes": edited.stat().st_size if edited.exists() else 0,
        "file_modified": _differs(edited, source),
        "error": result.get("error"),
        "from_cache": True,
    }


def run_benchmark(
    config: RunConfig,
    task_ids: list[str] | None = None,
    resume: bool = True,
    python_executable: str | None = None,
    progress: bool = True,
    supervisor=None,
) -> dict:
    if config.task_source == "corpus":
        tasks = load_corpus_tasks(config.tasks_file, config.scenes_dir)
    else:
        tasks = load_tasks(config.tasks_file, config.scenes_dir)
    k = max(1, config.num_samples)
    ids = task_ids or config.task_ids or sorted(tasks)
    missing = [t for t in ids if t not in tasks]
    if missing:
        raise KeyError(f"unknown task ids: {missing}")

    run_dir = RunDirectory(Path(config.results_dir), config.model_tag)
    run_dir.prepare()

    client = ChatClient(
        base_url=config.server.base_url,
        model=config.server.served_model_name or config.model_tag,
        api_key=config.server.api_key,
        request_timeout=config.server.request_timeout,
        max_attempts=config.retry.max_attempts,
        retry_delay=config.retry.delay_seconds,
    )

    resolved = config.to_dict()
    resolved["system_prompt"] = SYSTEM_PROMPT
    resolved["system_prompt_sha256"] = SYSTEM_PROMPT_SHA256
    resolved["tool_description"] = TOOL_DESCRIPTION
    resolved["task_ids"] = ids
    resolved["started_at"] = datetime.now().isoformat(timespec="seconds")
    run_dir.config_file.write_text(json.dumps(resolved, indent=2), encoding="utf-8")

    cache = run_dir.load_cache() if resume else {}
    summary: list[dict] = []
    run_started = time.monotonic()

    for position, task_id in enumerate(ids, start=1):
        task = tasks[task_id]
        if resume and task_id in cache and _is_complete(cache[task_id], run_dir, k):
            summary.extend(_summary_from_cache(cache[task_id], tasks[task_id], run_dir))
            if progress:
                print(f"[{position}/{len(ids)}] {task_id}: cached, skipped", flush=True)
            continue
        started_at = datetime.now().isoformat(timespec="seconds")
        sample_results: list[dict] = []
        sample_entries: list[dict] = []

        for sample in range(1, k + 1):
            working = run_dir.working_path(task, sample=sample, num_samples=k)
            log_file = run_dir.logs / (
                f"{task_id}_sample_{sample}.log" if k > 1 else f"{task_id}.log"
            )

            def _attempt():
                return run_task(
                    task=task,
                    working_ifc=working,
                    client=client,
                    agent_config=config.agent,
                    log_file=log_file,
                    python_executable=python_executable,
                )

            result = _attempt()
            # A dead server is not the trajectory's fault. Bring it back once and
            # give it a clean run; the budget is per attempt, so nothing is
            # doubled for a trajectory that was progressing normally.
            if (
                supervisor is not None
                and result.stop_reason == STOP_INFERENCE_ERROR
                and not supervisor.healthy()
            ):
                if progress:
                    print(f"    server unreachable after {task_id} sample {sample};"
                          " restarting", flush=True)
                if supervisor.restart(reason=f"inference_error on {task_id}#{sample}"):
                    result = _attempt()

            sample_results.append({
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
                    "sandbox_crashes": result.sandbox_crashes,
                    "ifc_copy_seconds": round(result.copy_seconds, 2),
                },
                "messages": result.messages,
                "sample": sample,
                "edited_ifc": str(working.relative_to(run_dir.root)),
            })

            if result.error:
                run_dir.append_error({
                    "task_id": task_id,
                    "sample": sample,
                    "stage": result.stop_reason,
                    "error": result.error,
                    "when": datetime.now().isoformat(timespec="seconds"),
                })

            tokens_per_second = (
                result.completion_tokens / result.duration_seconds
                if result.duration_seconds else 0.0
            )
            # Whether the trajectory changed the model at all is the probe's
            # headline, so it is recorded per trajectory rather than derived
            # later, and by content rather than by size: an edit that happens to
            # preserve the byte count would otherwise be missed.
            modified = _differs(working, task.input_ifc)
            sample_entries.append({
                "task_id": task_id,
                "sample": sample,
                "operation": task.operation,
                "category": task.category,
                "scene": task.scene,
                "tags": task.tags,
                "stop_reason": result.stop_reason,
                "tool_rounds": result.tool_rounds,
                "tool_calls": result.tool_calls,
                "llm_calls": result.llm_calls,
                "commits": result.commits,
                "input_tokens": result.prompt_tokens,
                "output_tokens": result.completion_tokens,
                "duration_seconds": round(result.duration_seconds, 2),
                "output_tokens_per_second": round(tokens_per_second, 2),
                "hit_output_token_cap": "length" in result.finish_reasons,
                "capped_tool_outputs": result.truncated_tool_outputs,
                "reasoning_chars": result.reasoning_chars,
                # Worker crashes, recovered ones included (see agent.py).
                "sandbox_crashes": result.sandbox_crashes,
                "edited_ifc": str(working),
                "edited_exists": working.exists(),
                "edited_bytes": working.stat().st_size if working.exists() else 0,
                "file_modified": modified,
                "error": result.error,
            })
            if os.environ.get("VERIBIM_SANDBOX_GUARD") == "1":
                # Attempts the sandbox refused; see the tool-call records.
                sample_entries[-1]["sandbox_blocked"] = result.sandbox_blocked

            if progress:
                print(f"[{position}/{len(ids)}] {task_id} sample {sample}/{k}: "
                      f"{result.stop_reason} rounds={result.tool_rounds} "
                      f"commits={result.commits} modified={modified} "
                      f"out_tok={result.completion_tokens} "
                      f"{round(tokens_per_second, 1)} tok/s "
                      f"{round(result.duration_seconds, 1)} s", flush=True)

        errors = [r for r in sample_results if r["error"]]
        record = {
            "task_id": task_id,
            "prompt": task.prompt,
            "model": config.model_tag,
            "input_ifc": str(task.input_ifc),
            "ground_truth_ifc": str(task.ground_truth_ifc),
            "operation": task.operation,
            "category": task.category,
            "tags": task.tags,
            "results": sample_results,
            "benchmark_runtime": {
                "status": "ok" if not errors else "error",
                "pending_pos": position - 1,
                "samples_requested": k,
                "samples_completed": len(sample_results),
                "sample_errors": len(errors),
                "started_at": started_at,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "duration_seconds": round(
                    sum(r["duration_seconds"] for r in sample_results), 2),
                "last_error": errors[-1]["error"] if errors else "",
            },
            "timestamp": datetime.now().isoformat(timespec="seconds"),
        }
        cache[task_id] = record
        run_dir.save_cache(cache)
        summary.extend(sample_entries)
        run_dir.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    total = time.monotonic() - run_started
    run_dir.summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return {
        "model_tag": config.model_tag,
        "n_tasks": len(ids),
        "duration_seconds": round(total, 2),
        "run_dir": str(run_dir.root),
        "summary": summary,
    }
