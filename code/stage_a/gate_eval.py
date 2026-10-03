"""The Stage A gate, measured under the frozen protocol.

The point of this module is that the measurement is the evaluation harness, not
an approximation of it. The first attempt at the gate ran through the trainer's
in-process validation shim, whose defaults were eight tool rounds and 1,024
output tokens; a third of its turns were cut off mid-answer and a quarter of its
tasks ran out of budget, and the result read as a weak model rather than a
mis-set harness. So this driver holds the protocol values and
records the resolved configuration next to the numbers.

Three things differ from the harvest driver, all of them because this is a
measurement rather than a data source:

*One sample per task.* k=1, greedy, so the number is reproducible.

*Nothing is discarded.* Every task's finished file is scored whether or not the
model committed. A trajectory that never wrote is a zero on the record, not an
absence from it.

*Every reference is rebuilt if missing.* A quarter of the validation subset has
no materialised gold model, because the split was topped up after the
materialisation ran. Rebuilding from the gold script is what separates a real
zero from an unreadable file.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from . import paths

paths.ensure_harness_on_path()

from modifc_harness.agent import run_task  # noqa: E402
from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.tasks import Task, normalise_path  # noqa: E402


def load_subset(subset_file: Path, tasks_file: Path) -> list[dict]:
    """The fixed validation subset, in the order the file lists it."""
    wanted = json.loads(Path(subset_file).read_text(encoding="utf-8"))
    order = {task_id: i for i, task_id in enumerate(wanted)}
    found: dict[str, dict] = {}
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record["task_id"] in order:
                if record["task_id"] in found:
                    raise AssertionError(f"task id {record['task_id']} occurs twice in {tasks_file}")
                found[record["task_id"]] = record
    missing = [t for t in wanted if t not in found]
    if missing:
        raise KeyError(f"subset ids absent from the task file: {missing[:5]}")
    return [found[t] for t in wanted]


def as_task(record: dict, project_root: Path) -> Task:
    return Task(
        task_id=record["task_id"],
        operation=record["operation"],
        category=record["category"],
        prompt=record.get("instruction") or record["prompt"],
        input_ifc=project_root / normalise_path(record["input_ifc"]),
        ground_truth_ifc=project_root / normalise_path(record["ground_truth_ifc"]),
        target=record.get("target") or {},
        tags=[f"edit_kind:{record.get('edit_kind')}"],
    )


def _valid_python(code: str) -> bool:
    try:
        compile(code, "<tool_call>", "exec")
    except Exception:
        return False
    return True


def rollout(adapter: str, records: Sequence[dict], run_dir: Path,
            client: ChatClient, agent: AgentConfig, concurrency: int,
            project_root: Path, progress_every: int = 10,
            keep_transcripts: bool = True) -> list[dict]:
    """One adapter over the subset, k=1, trajectories in flight together.

    Transcripts are kept by default. The first gate attempt recorded only
    counts, and answering "what filled the turn that ran past the output cap"
    then needed the tasks run again; a transcript is a few hundred kilobytes and
    the question comes up every time a stop reason is interesting.
    """
    run_dir = paths.require_absolute(run_dir, "run_dir")
    edited_root = run_dir / adapter / "edited"
    logs_root = run_dir / adapter / "logs"
    transcript_root = run_dir / adapter / "transcripts"
    edited_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    if keep_transcripts:
        transcript_root.mkdir(parents=True, exist_ok=True)
    done = {"n": 0}
    lock = threading.Lock()
    started = time.monotonic()

    def one(record: dict) -> dict:
        task = as_task(record, project_root)
        working = edited_root / record["task_id"] / f"{task.input_ifc.stem}.ifc"
        result = run_task(task=task, working_ifc=working, client=client,
                          agent_config=agent,
                          log_file=logs_root / f"{record['task_id']}.log")
        if keep_transcripts:
            (transcript_root / f"{record['task_id']}.json").write_text(
                json.dumps({"task_id": record["task_id"], "adapter": adapter,
                            "stop_reason": result.stop_reason,
                            "sandbox_crashes": result.sandbox_crashes,
                            "finish_reasons": result.finish_reasons,
                            "messages": result.messages,
                            "iterations": result.iterations}, ensure_ascii=False),
                encoding="utf-8")
        calls = [c for r in result.iterations for c in r["tool_calls"]]
        well_formed = [c for c in calls if c.get("ok")]
        compiles = [c for c in well_formed if _valid_python(c["args"].get("code", ""))]
        ran = [c for c in well_formed
               if not str(c.get("output", "")).startswith("Traceback")]
        with lock:
            done["n"] += 1
            if done["n"] % progress_every == 0:
                elapsed = time.monotonic() - started
                print(f"    {adapter}: {done['n']}/{len(records)} "
                      f"({elapsed / 60:.1f} min)", flush=True)
        row = {
            "adapter": adapter,
            "task_id": record["task_id"],
            "operation": record["operation"],
            "category": record["category"],
            "edit_kind": record.get("edit_kind", ""),
            "stop_reason": result.stop_reason,
            # Worker crashes, recovered ones included (see agent.py); the
            # tool-call records in `iterations` carry each one.
            "sandbox_crashes": getattr(result, "sandbox_crashes", 0),
            "tool_rounds": result.tool_rounds,
            "tool_calls": len(calls),
            "well_formed_calls": len(well_formed),
            "compiling_calls": len(compiles),
            "running_calls": len(ran),
            "commits": result.commits,
            "committed": result.commits > 0,
            "input_tokens": result.prompt_tokens,
            "output_tokens": result.completion_tokens,
            "finish_reasons": result.finish_reasons,
            "duration_seconds": round(result.duration_seconds, 2),
            "error": result.error,
            # The closing assistant message. Only a task whose instruction
            # leaves out a value the edit needs is read against it, and that
            # reading cannot be applied to a row that did not keep it.
            "reply": result.model_output or "",
            "edited_ifc": str(working),
            "edited_exists": working.is_file(),
        }
        if os.environ.get("VERIBIM_REQUEST_STYLE", "") == "anthropic_native":
            # Part of input_tokens; kept apart so the cost can be priced.
            row["cache_read_tokens"] = getattr(result, "cache_read_tokens", 0)
            row["cache_creation_tokens"] = getattr(result, "cache_creation_tokens", 0)
        if os.environ.get("VERIBIM_SANDBOX_GUARD") == "1":
            # File, process and network attempts the sandbox refused; the
            # tool-call records in `iterations` name each one.
            row["sandbox_blocked"] = getattr(result, "sandbox_blocked", 0)
        return row

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        rows = list(pool.map(one, records))
    return rows


_CTX: dict[str, Any] = {}


def _worker_slot() -> str:
    """A cache directory name unique among the live workers of one pool."""
    identity = getattr(mp.current_process(), "_identity", ()) or ()
    if identity:
        return "slot" + "-".join(str(part) for part in identity)
    return f"slotpid{os.getpid()}"


def _init_scorer(project_root: str, gold_cache_root: str,
                 family_reading: bool = False) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    from modifc_score.model_cache import MESHES, MODELS

    MODELS.capacity = 3
    MESHES.capacity_vertices = 800_000
    from .goldmodels import open_cache

    _CTX.update(project_root=Path(project_root),
                family_reading=bool(family_reading),
                # One cache directory per live pool worker: a slot named by
                # pid modulo collides as soon as two workers share a residue,
                # and two workers rebuilding into one directory delete each
                # other's tmp*.ifc (the Stage A v2 gap of 2026-09-12).
                cache=open_cache(Path(gold_cache_root) / _worker_slot()))


def _score_one(payload: tuple[dict, dict]) -> dict:
    from .goldmodels import resolve_gold
    from .scoring import score_prediction, scorer_config_for

    record, row = payload
    out = {"task_id": row["task_id"], "score": None, "score_error": None}
    predicted = Path(row["edited_ifc"])
    if not (predicted.is_file() and predicted.stat().st_size > 0):
        out["score_error"] = "prediction missing"
        return out
    gold = resolve_gold(record, _CTX["cache"], _CTX["project_root"])
    if gold is None:
        out["score_error"] = "gold model could not be rebuilt from its script"
        return out
    # The published reading is the default, because the published numbers are
    # what this driver measures. A task set carrying the 0.7.x families is read
    # under the settings each family's edit is visible under, which is the
    # reading the reward uses, and the closing assistant message travels with
    # it because an under-specified task is decided by that message.
    config = scorer_config_for(record) if _CTX.get("family_reading") else None
    score = score_prediction(record, predicted, _CTX["project_root"], gold_path=gold,
                             config=config, reply=str(row.get("reply") or ""))
    from modifc_score.model_cache import MESHES

    MESHES.clear()
    out["score"] = score.as_dict()
    out["score_error"] = score.error
    return out


def score_rows(records: Sequence[dict], rows: Sequence[dict], workers: int,
               project_root: Path, gold_cache_root: Path,
               family_reading: bool = False) -> list[dict]:
    """Score every row, committed or not.

    ``family_reading`` resolves each task's scorer settings from its own record
    through ``scoring.scorer_config_for`` instead of from its operation alone.
    It is off by default, so every earlier call measures what it measured.
    """
    by_id = {r["task_id"]: r for r in records}
    payloads = [(by_id[row["task_id"]], row) for row in rows]
    context = mp.get_context("spawn")
    scored: dict[str, dict] = {}
    with context.Pool(processes=max(1, workers), initializer=_init_scorer,
                      initargs=(str(project_root), str(gold_cache_root),
                                bool(family_reading))) as pool:
        for out in pool.imap_unordered(_score_one, payloads, chunksize=1):
            scored[out["task_id"]] = out
    merged = []
    for row in rows:
        entry = scored.get(row["task_id"], {})
        row = dict(row)
        row["score"] = entry.get("score")
        row["score_error"] = entry.get("score_error")
        row["final"] = (entry.get("score") or {}).get("final")
        merged.append(row)
    return merged


def summarize(adapter: str, rows: Sequence[dict], agent: AgentConfig) -> dict:
    """The gate's numbers. A task that could not be scored is named, not hidden."""
    scorable = [r for r in rows if r["final"] is not None]
    unscorable = [r for r in rows if r["final"] is None]
    total_calls = sum(r["tool_calls"] for r in rows)
    by_op: dict[str, Any] = {}
    for operation in sorted({r["operation"] for r in rows}):
        values = [r["final"] for r in rows
                  if r["operation"] == operation and r["final"] is not None]
        by_op[operation] = {
            "n": sum(1 for r in rows if r["operation"] == operation),
            "n_scored": len(values),
            "mean": round(sum(values) / len(values), 6) if values else None,
        }
    by_cat: dict[str, Any] = {}
    for category in sorted({r["category"] for r in rows}):
        values = [r["final"] for r in rows
                  if r["category"] == category and r["final"] is not None]
        by_cat[category] = round(sum(values) / len(values), 6) if values else None
    axes = {}
    for axis in ("geometry", "semantics", "topology"):
        values = [(r["score"] or {}).get(axis) for r in scorable]
        values = [v for v in values if v is not None]
        axes[axis] = round(sum(values) / len(values), 6) if values else None
    return {
        "adapter": adapter,
        "n_tasks": len(rows),
        "n_scored": len(scorable),
        "n_unscorable": len(unscorable),
        "unscorable_ids": [r["task_id"] for r in unscorable],
        "mean_final": round(sum(r["final"] for r in scorable) / len(scorable), 6)
                      if scorable else None,
        "by_operation": by_op,
        "by_category": by_cat,
        "axis_means": axes,
        "schema_validity": round(sum(r["well_formed_calls"] for r in rows)
                                 / total_calls, 4) if total_calls else None,
        "code_valid": round(sum(r["compiling_calls"] for r in rows)
                            / total_calls, 4) if total_calls else None,
        "code_run": round(sum(r["running_calls"] for r in rows)
                          / total_calls, 4) if total_calls else None,
        "commit_rate": round(sum(1 for r in rows if r["committed"]) / len(rows), 4),
        "tasks_with_any_tool_call": sum(1 for r in rows if r["tool_calls"] > 0),
        "mean_tool_rounds": round(sum(r["tool_rounds"] for r in rows) / len(rows), 3),
        "total_tool_calls": total_calls,
        "stop_reasons": dict(Counter(r["stop_reason"] for r in rows)),
        "hit_output_cap": sum(1 for r in rows if "length" in (r["finish_reasons"] or [])),
        "mean_output_tokens": round(sum(r["output_tokens"] for r in rows) / len(rows), 1),
        "wall_seconds": round(sum(r["duration_seconds"] for r in rows), 1),
        "resolved_agent_config": asdict(agent),
    }
