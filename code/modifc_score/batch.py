"""Scoring many tasks at once, on several CPU cores.

Work is grouped by input model before it is handed out, so a worker scores every
task that shares a scene in one go and parses that scene once.  Each worker is
pinned to its own cores and its numerical libraries are capped to that many
threads, so the workers do not oversubscribe the machine.
"""

from __future__ import annotations

import multiprocessing as mp
import os
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

from .config import DEFAULT_CONFIG, ScorerConfig
from .paths import (reference_basename, resolve_prediction, resolve_reply,
                    resolve_scene)
from .tasks import Task

_WORKER: dict[str, Any] = {}


def _init_worker(cores: Sequence[int], scene_root: str, edited_root: str,
                 cfg: ScorerConfig, geometry_mode: str, model_cache_size: int) -> None:
    n = max(1, len(cores))
    for var in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[var] = str(n)
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    from .model_cache import MeshCache, ModelCache

    _WORKER["models"] = ModelCache(capacity=model_cache_size)
    _WORKER["meshes"] = MeshCache()
    _WORKER["scene_root"] = scene_root
    _WORKER["edited_root"] = edited_root
    _WORKER["cfg"] = cfg
    _WORKER["geometry_mode"] = geometry_mode


def _score_one(task: Task) -> dict[str, Any]:
    from .scorer import score_task

    scene_root = _WORKER["scene_root"]
    started = time.perf_counter()
    try:
        input_path = resolve_scene(task.input_ifc, scene_root)
        gt_path = resolve_scene(task.ground_truth_ifc, scene_root)
    except FileNotFoundError as exc:
        return {"task_id": task.task_id, "error": str(exc), "geometry": 0.0,
                "semantics": 0.0, "topology": 0.0, "final_score": 0.0,
                "seconds": time.perf_counter() - started}
    pred_path = resolve_prediction(task.task_id, _WORKER["edited_root"])
    reply = (resolve_reply(task.task_id, _WORKER["edited_root"])
             if _WORKER["cfg"].underspecified_mode and task.clarification
             else "")
    score = score_task(task, input_path, gt_path, pred_path, _WORKER["cfg"],
                       _WORKER["models"], _WORKER["meshes"],
                       geometry_mode=_WORKER["geometry_mode"], reply=reply)
    row = score.as_row()
    row["seconds"] = time.perf_counter() - started
    row["topology_breakdown"] = score.topology_breakdown
    row["semantics_breakdown"] = score.semantics_breakdown
    row["geometry_breakdown"] = score.geometry_breakdown
    row["input_mb"] = round(os.path.getsize(input_path) / 1e6, 2)
    return row


def group_by_scene(tasks: Iterable[Task]) -> list[Task]:
    """Order tasks so that tasks on the same input model sit together."""
    buckets: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        buckets[reference_basename(task.input_ifc)].append(task)
    ordered: list[Task] = []
    for name in sorted(buckets):
        ordered.extend(sorted(buckets[name], key=lambda t: t.task_id))
    return ordered


def core_blocks(n_workers: int, reserve: int = 4) -> list[list[int]]:
    """Split the machine's cores into one contiguous block per worker."""
    available = sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") \
        else list(range(os.cpu_count() or 1))
    usable = available[: max(1, len(available) - reserve)]
    if not usable:
        usable = available[:1]
    blocks: list[list[int]] = [[] for _ in range(n_workers)]
    for i, core in enumerate(usable):
        blocks[i % n_workers].append(core)
    return [b or [usable[0]] for b in blocks]


def score_tasks(tasks: Sequence[Task], scene_root: str | Path, edited_root: str | Path,
                cfg: ScorerConfig = DEFAULT_CONFIG, workers: int = 8,
                geometry_mode: str = "per_pair", reserve_cores: int = 4,
                model_cache_size: int = 3, progress: bool = True) -> list[dict[str, Any]]:
    ordered = group_by_scene(tasks)
    if workers <= 1:
        _init_worker(sorted(os.sched_getaffinity(0))[:4], str(scene_root), str(edited_root),
                     cfg, geometry_mode, model_cache_size)
        return [_score_one(t) for t in ordered]

    blocks = core_blocks(workers, reserve_cores)
    ctx = mp.get_context("spawn")
    # Each worker gets its own core block; a shared pool cannot hand a different
    # block to each process, so one single-process pool per block is used.
    chunk_size = (len(ordered) + workers - 1) // workers
    chunks = [ordered[i * chunk_size:(i + 1) * chunk_size] for i in range(workers)]
    results: list[dict[str, Any]] = []
    procs = []
    queue: Any = ctx.Queue()
    for w, chunk in enumerate(chunks):
        if not chunk:
            continue
        p = ctx.Process(target=_worker_main,
                        args=(queue, chunk, blocks[w], str(scene_root), str(edited_root),
                              cfg, geometry_mode, model_cache_size))
        p.start()
        procs.append(p)
    expected = sum(len(c) for c in chunks if c)
    done = 0
    while done < expected:
        row = queue.get()
        results.append(row)
        done += 1
        if progress and done % 25 == 0:
            print(f"  scored {done}/{expected}", flush=True)
    for p in procs:
        p.join()
    return results


def _worker_main(queue, chunk, cores, scene_root, edited_root, cfg, geometry_mode,
                 model_cache_size):
    _init_worker(cores, scene_root, edited_root, cfg, geometry_mode, model_cache_size)
    for task in chunk:
        try:
            queue.put(_score_one(task))
        except Exception as exc:  # a broken task must not stall the run
            queue.put({"task_id": task.task_id, "error": f"worker_error: {exc}",
                       "geometry": 0.0, "semantics": 0.0, "topology": 0.0,
                       "final_score": 0.0, "seconds": 0.0})
