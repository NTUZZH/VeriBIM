"""On-policy sampling of sft590, every trajectory scored and kept.

This differs from the Stage A harvest in three ways that matter at this scale.

*Nothing is filtered.* The harvest kept only trajectories above a floor, because
it was building training targets. A preference pair needs the failures as much as
the successes, so every rollout is scored and recorded, committed or not.

*The artifact is scored and then deleted.* Thirty-six thousand edited models is
about 180 GB. Each task's samples are scored as soon as its rollouts finish and
the directory is dropped, so disk stays flat and only the numbers and the
transcript survive.

*Records stream to JSONL.* The harness's run cache is one JSON document rewritten
on every flush, which is fine for four hundred tasks and quadratic for six
thousand.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import shutil
import signal
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

from stage_a import paths

paths.ensure_harness_on_path()

from modifc_harness.agent import run_task  # noqa: E402
from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.tasks import Task, normalise_path  # noqa: E402

#: An IFC GlobalId is exactly 22 characters from this alphabet. The boundary
#: assertions matter: without them the pattern also matches the first 22
#: characters of any longer identifier, and `CoordinateSpaceDimension` in
#: ordinary code was being read as a fabricated id.
GUID = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")

#: In code, a GlobalId is always a quoted literal. Extracting only quoted
#: strings keeps a bare 22-character variable name from counting as an id.
GUID_LITERAL = re.compile(r"""['"]([0-9A-Za-z_$]{22})['"]""")

#: A real GlobalId always carries a digit, underscore or dollar: checked on
#: 5,441 identifiers drawn from the task set, 100% of them. Without this test a
#: 22-character IFC class name passes as an id, and `IfcRectangleProfileDef` is
#: exactly 22 characters, which accounted for three quarters of the first
#: version's fabrication flags.
GUID_MARK = re.compile(r"[0-9_$]")


def looks_like_guid(token: str) -> bool:
    return (len(token) == 22 and not token.startswith("Ifc")
            and bool(GUID_MARK.search(token)))


def guids_in_code(code: str) -> set[str]:
    """Identifiers a snippet uses as literals."""
    return {m.group(1) for m in GUID_LITERAL.finditer(code or "")
            if looks_like_guid(m.group(1))}


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


def call_status(iterations: Sequence[dict]) -> list[dict]:
    """Per turn, what the sandbox did with the code it was given.

    ``raised`` is the signal Stage B is built on, so it is recorded per call
    rather than aggregated: a pair is built from the turn that failed, not from
    a trajectory-level rate.
    """
    out: list[dict] = []
    for index, round_ in enumerate(iterations):
        for call in round_["tool_calls"]:
            code = (call.get("args") or {}).get("code")
            output = str(call.get("output") or "")
            raised = output.startswith("Traceback")
            out.append({
                "turn": index,
                "well_formed": bool(call.get("ok")),
                "raised": raised,
                "error_line": output.strip().split("\n")[-1][:200] if raised else "",
                "code_chars": len(code) if isinstance(code, str) else 0,
            })
    return out


def observed_guids(messages: Sequence[dict], upto: int) -> set[str]:
    """Every identifier a tool result printed before message ``upto``.

    This is the mechanical half of the fabricated-identifier check: an id the
    model uses that appears in no earlier tool output, and not in the
    instruction, was invented rather than read.
    """
    seen: set[str] = set()
    for message in messages[:upto]:
        if message.get("role") in ("tool", "user"):
            seen.update(g for g in GUID.findall(message.get("content") or "")
                        if looks_like_guid(g))
    return seen


def unobserved_guids_per_turn(messages: Sequence[dict]) -> list[dict]:
    """For each assistant turn, the identifiers it used that nothing had shown it."""
    out: list[dict] = []
    turn = 0
    for index, message in enumerate(messages):
        if message.get("role") != "assistant":
            continue
        codes = []
        for call in message.get("tool_calls") or []:
            arguments = call.get("function", {}).get("arguments")
            if isinstance(arguments, dict):
                codes.append(str(arguments.get("code") or ""))
            elif isinstance(arguments, str):
                try:
                    codes.append(str((json.loads(arguments) or {}).get("code") or ""))
                except json.JSONDecodeError:
                    codes.append(arguments)
        if not codes:
            continue
        used = set()
        for code in codes:
            used.update(guids_in_code(code))
        known = observed_guids(messages, index)
        out.append({"turn": turn, "used": sorted(used),
                    "unobserved": sorted(used - known)})
        turn += 1
    return out


# ------------------------------------------------------------------ scoring

_SC: dict[str, Any] = {}


def worker_slot() -> str:
    """A cache directory name no two workers of one pool can share.

    A slot named by ``pid % N`` collides as soon as the pool holds more than N
    live pids or the operating system reuses one, and two workers writing
    ``tmp*.ifc`` into one gold-cache directory delete each other's file. A
    multiprocessing Pool numbers its workers on ``_identity``, which is unique
    for the life of the pool; a process that is not a pool worker falls back to
    its pid, where there is nothing to collide with.
    """
    identity = getattr(mp.current_process(), "_identity", ()) or ()
    if identity:
        return "slot" + "-".join(str(part) for part in identity)
    return f"slotpid{os.getpid()}"


def _init_scorer(project_root: str, gold_cache_root: str,
                 family_reading: bool = False) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    from modifc_score.model_cache import MESHES, MODELS
    from stage_a.goldmodels import open_cache

    MODELS.capacity = 3
    MESHES.capacity_vertices = 800_000
    _SC.update(project_root=Path(project_root),
               family_reading=bool(family_reading),
               cache=open_cache(Path(gold_cache_root) / worker_slot()))


def _score_task(payload: tuple) -> list[dict]:
    """Score every sample of one task, then say nothing about which to keep.

    Under the family reading each task is graded with the settings its own
    taxonomy tags ask for, and the closing assistant message travels with the
    file, because a task whose instruction leaves out a value is decided by that
    message rather than by the model on disk. The published reading is the
    default, so a v1 run measures what it measured.
    """
    from modifc_score.model_cache import MESHES
    from stage_a.goldmodels import resolve_gold
    from stage_a.scoring import score_prediction, scorer_config_for

    record, predicted = payload[0], payload[1]
    replies = list(payload[2]) if len(payload) > 2 else [""] * len(predicted)
    config = scorer_config_for(record) if _SC.get("family_reading") else None
    gold = resolve_gold(record, _SC["cache"], _SC["project_root"])
    out: list[dict] = []
    for index, path in enumerate(predicted):
        entry: dict[str, Any] = {"score": None, "score_error": None}
        p = Path(path) if path else None
        if gold is None:
            entry["score_error"] = "gold model could not be rebuilt from its script"
        elif p is None or not (p.is_file() and p.stat().st_size > 0):
            entry["score_error"] = "prediction missing"
        else:
            reply = str(replies[index] if index < len(replies) else "")
            score = score_prediction(record, p, _SC["project_root"], gold_path=gold,
                                     config=config,
                                     reply=reply if config is not None else "")
            entry["score"] = score.as_dict()
            entry["score_error"] = score.error
        out.append(entry)
    MESHES.clear()
    return out


# ------------------------------------------------------------------- runner

#: A source model above this size is sampled with a much smaller pool. The
#: sampler holds one parsed model per in-flight rollout, and k samples of one
#: task are k independent copies of the same building; at 32 concurrent
#: rollouts over a pool whose p90 is 74 MB that reached 60 GB and the box ran
#: out. Concurrency is therefore sized against the model, not set once.
LARGE_SOURCE_MB = 25.0


def source_mb(record: dict, project_root: Path) -> float:
    try:
        return (project_root / normalise_path(record["input_ifc"])).stat().st_size / 1e6
    except OSError:
        return 0.0


def completed_task_ids(out_file: Path) -> set[str]:
    done: set[str] = set()
    if not Path(out_file).exists():
        return done
    with Path(out_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                done.add(json.loads(line)["task_id"])
            except (json.JSONDecodeError, KeyError):
                continue
    return done


def task_reading(record: dict) -> dict:
    """What one task is graded under, recorded beside its rollouts.

    Pair construction reads it rather than the task file: a rule that treats an
    under-specified task differently has to see, from the rollout line alone,
    that the task is one.
    """
    try:
        from stage_a.scoring import reading_for

        return reading_for(record)
    except Exception as exc:  # noqa: BLE001 - metadata must not end a run
        return {"error": f"{type(exc).__name__}: {exc}"[:200]}


def run_sampling(records: Sequence[dict], run_dir: Path, client: ChatClient,
                 agent: AgentConfig, k: int, concurrency: int, score_workers: int,
                 project_root: Path, gold_cache_root: Path,
                 deadline: float | None = None, resume: bool = True,
                 progress_every: int = 10, large_concurrency: int = 3,
                 family_reading: bool = False,
                 order_seed: int | None = None) -> dict:
    run_dir = paths.require_absolute(run_dir, "run_dir")
    run_dir.mkdir(parents=True, exist_ok=True)
    out_file = run_dir / "rollouts.jsonl"
    edited_root = run_dir / "edited"
    logs_root = run_dir / "logs"
    edited_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)

    already = completed_task_ids(out_file) if resume else set()
    pending = [r for r in records if r["task_id"] not in already]
    if order_seed is not None:
        # The task file is sorted by id, so a run stopped early would have seen
        # one building and a few edit kinds. A seeded shuffle makes any prefix
        # of the run a uniform draw from the pool, and the same seed gives the
        # same order on resume.
        import random

        random.Random(order_seed).shuffle(pending)
    write_lock = threading.Lock()
    counters = Counter()
    started = time.monotonic()
    handle = out_file.open("a" if already else "w", encoding="utf-8")

    context = mp.get_context("spawn")
    scorer = context.Pool(processes=max(1, score_workers), initializer=_init_scorer,
                          initargs=(str(project_root), str(gold_cache_root),
                                    bool(family_reading)))

    def finish(record: dict, rollouts: list[dict], scores: list[dict]) -> None:
        for roll, entry in zip(rollouts, scores):
            roll.update(entry)
            roll["final"] = (entry.get("score") or {}).get("final")
        shutil.rmtree(edited_root / record["task_id"], ignore_errors=True)
        line = {
            "task_id": record["task_id"],
            "operation": record["operation"],
            "category": record["category"],
            "edit_kind": record.get("edit_kind", ""),
            "building_id": record.get("building_id", ""),
            "schema": (record.get("source_model") or {}).get("schema", ""),
            "instruction": record.get("instruction") or record["prompt"],
            "input_ifc": record["input_ifc"],
            "ground_truth_ifc": record["ground_truth_ifc"],
            "target": record.get("target") or {},
            "families": list(record.get("families") or ()),
            "clarification": record.get("clarification"),
            "expected_reply": record.get("expected_reply"),
            "reading": task_reading(record),
            "samples": rollouts,
        }
        with write_lock:
            handle.write(json.dumps(line, ensure_ascii=False) + "\n")
            handle.flush()
            counters["tasks"] += 1
            counters["trajectories"] += len(rollouts)
            counters["scored"] += sum(1 for r in rollouts if r["final"] is not None)
            counters["committed"] += sum(1 for r in rollouts if r["commits"] > 0)
            counters["raised_calls"] += sum(
                sum(1 for c in r["calls"] if c["raised"]) for r in rollouts)
            counters["calls"] += sum(len(r["calls"]) for r in rollouts)
            if counters["tasks"] % progress_every == 0:
                elapsed = time.monotonic() - started
                rate = counters["trajectories"] / max(1e-9, elapsed)
                print(f"  {counters['tasks']}/{len(pending)} tasks, "
                      f"{counters['trajectories']} trajectories, "
                      f"{rate:.2f} traj/s, {elapsed / 60:.1f} min", flush=True)

    def one_sample(record: dict, index: int) -> dict:
        task = as_task(record, project_root)
        working = paths.require_absolute(
            edited_root / record["task_id"] / f"sample_{index}"
            / f"{task.input_ifc.stem}.ifc", "working_ifc")
        result = run_task(task=task, working_ifc=working, client=client,
                          agent_config=agent,
                          log_file=logs_root / f"{record['task_id']}_{index}.log")
        try:
            (logs_root / f"{record['task_id']}_{index}.log").unlink()
        except OSError:
            pass
        return {
            "sample": index,
            "stop_reason": result.stop_reason,
            "tool_rounds": result.tool_rounds,
            "commits": result.commits,
            "output_tokens": result.completion_tokens,
            "finish_reasons": result.finish_reasons,
            "duration_seconds": round(result.duration_seconds, 2),
            "error": result.error,
            "reply": result.model_output or "",
            "messages": result.messages,
            "calls": call_status(result.iterations),
            "guid_use": unobserved_guids_per_turn(result.messages),
            "edited_ifc": str(working),
        }

    def one_task(record: dict, pool: ThreadPoolExecutor) -> None:
        futures = [pool.submit(one_sample, record, i) for i in range(1, k + 1)]
        rollouts = [f.result() for f in futures]
        paths_ = [r["edited_ifc"] for r in rollouts]
        replies = [r.get("reply", "") for r in rollouts]
        scorer.apply_async(
            _score_task, ((record, paths_, replies),),
            callback=lambda scores, rec=record, rl=rollouts: finish(rec, rl, scores),
            error_callback=lambda exc, rec=record, rl=rollouts: finish(
                rec, rl, [{"score": None, "score_error": str(exc)[:200]}] * len(rl)))

    # Two pools, sized separately. Small buildings run wide; the heavy tail runs
    # narrow, in parallel with them, so the large models cost throughput only on
    # their own share of the work rather than forcing the whole run down.
    small = [r for r in pending if source_mb(r, project_root) < LARGE_SOURCE_MB]
    large = [r for r in pending if source_mb(r, project_root) >= LARGE_SOURCE_MB]
    print(f"  {len(small)} tasks on small sources ({concurrency} rollouts in flight), "
          f"{len(large)} on large ({large_concurrency})", flush=True)

    def settle(record: dict, future) -> None:
        # A task whose rollout raised (a failed copy of its source when the disk
        # was full, 2026-09-24) must not end the pool it ran in: the task is
        # reported, its working copies are dropped, and the next start of the
        # sampler picks it up again because it is absent from the rollout file.
        try:
            future.result()
        except Exception as exc:  # noqa: BLE001 - one task, not the pool
            shutil.rmtree(edited_root / record["task_id"], ignore_errors=True)
            with write_lock:
                counters["failed_tasks"] += 1
            print(f"  TASK FAILED {record['task_id']}: "
                  f"{type(exc).__name__}: {str(exc)[:160]}", flush=True)

    def drive(records: Sequence[dict], width: int) -> None:
        if not records:
            return
        in_flight = max(1, max(1, width // max(1, k)))
        with ThreadPoolExecutor(max_workers=width) as pool:
            with ThreadPoolExecutor(max_workers=in_flight) as tasks:
                queue: list = []
                for record in records:
                    if deadline is not None and time.monotonic() >= deadline:
                        break
                    queue.append((record, tasks.submit(one_task, record, pool)))
                    while len(queue) >= in_flight:
                        settle(*queue.pop(0))
                for record, future in queue:
                    settle(record, future)

    drivers = [threading.Thread(target=drive, args=(small, concurrency), daemon=True),
               threading.Thread(target=drive, args=(large, large_concurrency), daemon=True)]
    for thread in drivers:
        thread.start()
    for thread in drivers:
        thread.join()
    scorer.close()
    scorer.join()
    handle.close()

    elapsed = time.monotonic() - started
    return {
        "tasks_this_run": counters["tasks"],
        "failed_tasks": counters["failed_tasks"],
        "tasks_total": counters["tasks"] + len(already),
        "trajectories": counters["trajectories"],
        "scored": counters["scored"],
        "committed": counters["committed"],
        "tool_calls": counters["calls"],
        "raised_calls": counters["raised_calls"],
        "call_run_rate": round(1 - counters["raised_calls"] / counters["calls"], 4)
                         if counters["calls"] else None,
        "seconds": round(elapsed, 1),
        "trajectories_per_second": round(counters["trajectories"] / elapsed, 3)
                                   if elapsed else None,
        "rollouts_file": str(out_file),
    }
