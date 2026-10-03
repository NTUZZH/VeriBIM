"""Running the synthesizer over a task set, and the funnel it reports.

Every task that is attempted is accounted for: it either produces a trajectory
or it names the stage it stopped at and why. The counts are what the report
quotes, so they are written to disk next to the trajectories rather than printed
and lost.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import paths
from .synthesize import Attempt, synthesize_one


def load_tasks(tasks_file: Path) -> list[dict]:
    records = []
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def stratified_sample(tasks: Sequence[dict], limit: int) -> list[dict]:
    """A sample that keeps every operation and category cell represented.

    Taking the head of a task file takes one building at a time, so the sample
    walks the cells in turn instead and takes one task from each until it has
    enough.
    """
    if limit <= 0 or limit >= len(tasks):
        return list(tasks)
    cells: dict[tuple[str, str], list[dict]] = {}
    for task in tasks:
        cells.setdefault((task["operation"], task["category"]), []).append(task)
    for bucket in cells.values():
        bucket.sort(key=lambda t: t["task_id"])
    picked: list[dict] = []
    keys = sorted(cells)
    index = 0
    while len(picked) < limit:
        progressed = False
        for key in keys:
            bucket = cells[key]
            if index < len(bucket):
                picked.append(bucket[index])
                progressed = True
                if len(picked) >= limit:
                    break
        if not progressed:
            break
        index += 1
    return picked


def build_chunks(tasks: Sequence[dict], chunk: int) -> list[list[dict]]:
    """Cut an ordered task list into runs of one building.

    A chunk is the unit of work a worker takes, and every task in it shares a
    source model. That is what makes the parse worth paying for, and it is also
    what keeps two workers out of the same large building at the same time:
    concurrency is across buildings, not inside one.
    """
    chunks: list[list[dict]] = []
    current: list[dict] = []
    building = None
    for task in tasks:
        key = task.get("building_id", "")
        if current and (key != building or len(current) >= chunk):
            chunks.append(current)
            current = []
        building = key
        current.append(task)
    if current:
        chunks.append(current)
    return chunks


_CONTEXT: dict[str, Any] = {}


#: A source model this size or larger goes through the gate below, because a
#: worker holding one parsed, plus its gold model and its prediction, is several
#: gigabytes wide. The threshold is not a memory cliff, it is a knob traded off
#: against the gate's width: on this task set 22% of the train split sits above
#: 25 MB, so a single permit there leaves most workers queueing rather than
#: working, which is what dropped the run to 106 tasks per hour.
LARGE_SOURCE_MB = float(os.environ.get("VERIBIM_LARGE_SOURCE_MB", "25"))

#: How many workers may be inside a large building at once. Sized against the
#: memory actually free, not against the worker count.
LARGE_PERMITS = int(os.environ.get("VERIBIM_LARGE_PERMITS", "3"))


def worker_slot(tag: str) -> str:
    """A cache directory name no two live workers can share.

    A slot named by a counter modulo the pool size, or by ``pid % N``, collides
    as soon as two pools number their workers from zero or the operating system
    reuses a pid, and two workers writing ``tmp*.ifc`` into one gold-cache
    directory delete each other's file. A multiprocessing pool numbers its
    workers on ``_identity``, which is unique among the workers that are alive
    and is reused by the worker that replaces one, so the cache stays bounded.
    The pool's own tag is prefixed because this run has two pools.
    """
    identity = getattr(mp.current_process(), "_identity", ()) or ()
    if identity:
        return f"{tag}-" + "-".join(str(part) for part in identity)
    return f"{tag}-pid{os.getpid()}"


def _init_worker(scratch: str, project_root: str, floor: float,
                 require_axes: bool, threads: int, gold_cache_root: str = "",
                 cores: Sequence[int] = (), large_gate=None, pool_tag: str = "pool",
                 name_index_root: str = "") -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = str(threads)
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    # The scorer's caches are sized for a benchmark run, where a handful of
    # scenes recur across every task. A synthesis pass over tens of thousands of
    # tasks sees a new gold model and a new prediction every time, so six
    # resident parsed models is six models' worth of memory per worker and, on a
    # box shared with the generator, that is what runs it out of RAM. Three is
    # the working set of one scored task; the mesh budget is cut with it.
    from modifc_score.model_cache import MESHES, MODELS

    MODELS.capacity = max(1, int(os.environ.get("VERIBIM_MODEL_CACHE", "3")))
    MESHES.capacity_vertices = int(os.environ.get("VERIBIM_MESH_VERTICES",
                                                  str(800_000)))
    # Workers are recycled to give their memory back, so a cache directory is
    # claimed by slot rather than by process id: a slot is reused by the worker
    # that replaces the one that had it, and the run's cache stays bounded
    # instead of leaving an orphaned directory per generation.
    cache = None
    if gold_cache_root:
        from .goldmodels import open_cache

        cache = open_cache(Path(gold_cache_root) / worker_slot(pool_tag))
    _CONTEXT.update(scratch=Path(scratch), project_root=Path(project_root),
                    floor=floor, require_axes=require_axes, gold_cache=cache,
                    since_clear=0, large_gate=large_gate,
                    name_index_root=name_index_root)


def _chunk_mb(chunk: Sequence[dict], project_root: Path) -> float:
    """Size of the source model a chunk shares, in megabytes."""
    if not chunk:
        return 0.0
    try:
        return (Path(project_root) / chunk[0]["input_ifc"]).stat().st_size / 1e6
    except OSError:
        return 0.0


def _source_mb(task: dict, project_root: Path) -> float:
    try:
        return (project_root / task["input_ifc"]).stat().st_size / 1e6
    except OSError:
        return 0.0


def _run_chunk(chunk: Sequence[dict]) -> list[dict]:
    """Every task of one building, in one worker.

    No gate. Bounding the number of workers inside a large building by making
    the others *wait* for a permit was the wrong shape: a blocked worker is not
    saving memory, it is simply not working, and four of seven sat in
    ``futex_do_wait`` while three worked. The bound is now the size of the pool
    a chunk is sent to, so a worker never blocks and the large buildings are
    limited by having fewer workers assigned to them.
    """
    return [_run_one_inner(task, time.monotonic()) for task in chunk]


def _run_one_inner(task: dict, started: float) -> dict:
    index = None
    root = _CONTEXT.get("name_index_root") or ""
    if root:
        from . import nameindex

        try:
            index = nameindex.load(Path(root), task, _CONTEXT["project_root"])
        except Exception:  # noqa: BLE001
            index = None
    attempt = synthesize_one(
        task,
        scratch=_CONTEXT["scratch"],
        project_root=_CONTEXT["project_root"],
        floor=_CONTEXT["floor"],
        require_axes=_CONTEXT["require_axes"],
        gold_cache=_CONTEXT.get("gold_cache"),
        name_index=index,
    )
    # Meshes belong to the task that was just scored and will never be asked for
    # again; the parsed models are dropped periodically so a worker's memory is
    # flat over a long run rather than sawtoothing up to the cache bound.
    from modifc_score.model_cache import MESHES, MODELS

    MESHES.clear()
    _CONTEXT["since_clear"] = _CONTEXT.get("since_clear", 0) + 1
    if _CONTEXT["since_clear"] >= 20:
        MODELS.clear()
        _CONTEXT["since_clear"] = 0
    return {
        "task_id": attempt.task_id,
        "building_id": task.get("building_id", ""),
        "operation": task["operation"],
        "category": task["category"],
        "edit_kind": task.get("edit_kind", ""),
        # The generator's own tags, so the funnel can be read family by family
        # rather than only cell by cell.
        "families": list(task.get("families") or ()),
        "anchor_kind": (task.get("anchor") or {}).get("kind", ""),
        "stage": attempt.stage,
        "ok": attempt.ok,
        "reason": attempt.reason,
        "tool_rounds": attempt.tool_rounds,
        "commits": attempt.commits,
        "score": attempt.score.as_dict() if attempt.score else None,
        "detail": attempt.detail,
        "seconds": round(time.monotonic() - started, 2),
        "record": attempt.record,
    }


def completed_ids(out_dir: Path) -> set[str]:
    """Task ids either output file already accounts for.

    Resumption counts a refusal as done as much as an acceptance, or a long run
    would spend its time re-deriving the same rejection. It reads both files
    rather than one because they are two streams: a kill lands between them, and
    keying off the outcomes file alone once let twenty-four tasks whose
    trajectory was already on disk be run a second time and appended twice. The
    writer now flushes the trajectory before the outcome, so the trajectory file
    is never behind, and the union of the two is what a task is judged by.
    """
    done: set[str] = set()
    for name in ("trajectories_gold.jsonl", "outcomes_gold.jsonl"):
        path = Path(out_dir) / name
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["task_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


def synthesize_set(tasks: Sequence[dict], out_dir: Path, scratch: Path,
                   project_root: Path, workers: int = 6, floor: float = 0.98,
                   require_axes: bool = True, threads_per_worker: int = 1,
                   progress: bool = True, resume: bool = True,
                   gold_cache_root: str = "", cores: Sequence[int] = (),
                   report_every: int = 200, recycle_after: int = 50,
                   chunk_size: int = 64,
                   large_permits: int = LARGE_PERMITS,
                   name_index_root: str = "") -> dict:
    """Synthesize a trajectory for every task, and write the funnel.

    Written for a set of tens of thousands: results are appended as they finish,
    the funnel is rewritten periodically rather than at the end, and a run that
    is interrupted is restarted with the same command and skips what it already
    accounted for.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Absolute, always. The sandbox worker is launched with its own working
    # directory, so a relative scratch path resolves somewhere else in the
    # child and the model it was told to open is not there; the path is also
    # what the trajectory shows the model, and that should not depend on where
    # the driver happened to be started.
    scratch = Path(scratch).resolve()
    scratch.mkdir(parents=True, exist_ok=True)

    trajectories = out_dir / "trajectories_gold.jsonl"
    outcomes_file = out_dir / "outcomes_gold.jsonl"
    started = time.monotonic()

    already = completed_ids(out_dir) if resume else set()
    pending = [t for t in tasks if t["task_id"] not in already]
    chunks = build_chunks(pending, chunk_size)
    big_chunks = [c for c in chunks
                  if _chunk_mb(c, project_root) >= LARGE_SOURCE_MB]
    small_chunks = [c for c in chunks
                    if _chunk_mb(c, project_root) < LARGE_SOURCE_MB]
    # Append whenever output already exists, whatever the resume setting says:
    # a targeted re-run of a handful of task ids must not truncate the file the
    # rest of the run wrote.
    mode = "a" if (trajectories.exists() or outcomes_file.exists()) else "w"

    stage_counts: Counter = Counter()
    reason_counts: Counter = Counter()
    cell_counts: Counter = Counter()
    kind_counts: Counter = Counter()
    building_counts: Counter = Counter()
    family_attempted: Counter = Counter()
    family_accepted: Counter = Counter()
    family_reasons: dict[str, Counter] = {}
    anchor_attempted: Counter = Counter()
    anchor_accepted: Counter = Counter()
    scores: list[float] = []
    rounds: list[int] = []

    def family_funnel() -> dict:
        """Attempted, kept and the leading refusal, one row per family."""
        out = {}
        for family in sorted(family_attempted):
            attempted = family_attempted[family]
            kept = family_accepted[family]
            reasons = family_reasons.get(family) or Counter()
            out[family] = {
                "attempted": attempted,
                "kept": kept,
                "kept_share": round(kept / attempted, 4) if attempted else 0.0,
                "reasons": dict(reasons.most_common(4)),
            }
        return out

    def funnel(finished: bool) -> dict:
        accepted = stage_counts["accepted"]
        return {
            "attempted": len(already) + sum(stage_counts.values()),
            "attempted_this_run": sum(stage_counts.values()),
            "resumed_from": len(already),
            "planned": sum(stage_counts.values()) - stage_counts["plan"],
            "replayed": stage_counts["scored"] + accepted,
            "accepted": accepted,
            "stage_counts": dict(stage_counts),
            "rejection_reasons": dict(reason_counts.most_common(25)),
            "accepted_by_cell": {f"{op}/{cat}": n
                                 for (op, cat), n in sorted(cell_counts.items())},
            "accepted_by_edit_kind": dict(sorted(kind_counts.items())),
            "by_family": family_funnel(),
            "by_anchor_kind": {kind: {"attempted": anchor_attempted[kind],
                                      "kept": anchor_accepted[kind]}
                               for kind in sorted(anchor_attempted)},
            "accepted_buildings": len(building_counts),
            "score_floor": floor,
            "require_all_axes": require_axes,
            "mean_final_score": round(sum(scores) / len(scores), 6) if scores else None,
            "min_final_score": round(min(scores), 6) if scores else None,
            "mean_tool_rounds": round(sum(rounds) / len(rounds), 3) if rounds else None,
            "duration_seconds": round(time.monotonic() - started, 1),
            "workers": workers,
            "name_index_root": name_index_root,
            "finished": finished,
            "trajectories": str(trajectories),
            "outcomes": str(outcomes_file),
        }

    context = mp.get_context("spawn")
    write_lock = threading.Lock()
    counter = {"n": 0}

    def make_pool(processes: int, tag: str):
        # ``maxtasksperchild`` is what keeps this run inside its memory budget.
        # A parsed model is released when the cache drops it, but the allocator
        # does not hand the pages back, so a worker that once scored a
        # two-hundred-megabyte building stays six gigabytes wide for the rest of
        # the run. Recycling the worker returns the memory.
        return context.Pool(
            processes=max(1, processes),
            maxtasksperchild=max(1, recycle_after),
            initializer=_init_worker,
            initargs=(str(scratch), str(project_root), floor, require_axes,
                      threads_per_worker, gold_cache_root, tuple(cores),
                      None, tag, name_index_root),
        )

    with trajectories.open(mode, encoding="utf-8") as traj_fh, \
            outcomes_file.open(mode, encoding="utf-8") as out_fh:

        def consume(pool, work) -> None:
            """Drain one pool, writing results as they arrive."""
            for batch in pool.imap_unordered(_run_chunk, work, chunksize=1):
                for result in batch:
                    record = result.pop("record")
                    with write_lock:
                        counter["n"] += 1
                        index = counter["n"]
                        stage_counts[result["stage"]] += 1
                        tags = list(result.get("families") or ()) or ["untagged"]
                        anchor_kind = result.get("anchor_kind", "") or "none"
                        anchor_attempted[anchor_kind] += 1
                        for tag in tags:
                            family_attempted[tag] += 1
                            if result["ok"]:
                                family_accepted[tag] += 1
                            else:
                                family_reasons.setdefault(tag, Counter())[
                                    result["reason"][:60] or "unknown"] += 1
                        if result["ok"]:
                            anchor_accepted[anchor_kind] += 1
                            traj_fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                            traj_fh.flush()
                            cell_counts[(result["operation"], result["category"])] += 1
                            kind_counts[result["edit_kind"]] += 1
                            building_counts[result.get("building_id", "")] += 1
                            scores.append(result["score"]["final"])
                            rounds.append(result["tool_rounds"])
                        else:
                            reason_counts[result["reason"][:80] or "unknown"] += 1
                        out_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
                        if index % report_every == 0:
                            out_fh.flush()
                            (out_dir / "funnel_gold.json").write_text(
                                json.dumps(funnel(False), indent=2), encoding="utf-8")
                            if progress:
                                rate = index / max(1e-9, time.monotonic() - started)
                                left = (len(pending) - index) / rate / 3600 if rate else 0
                                print(f"  {index}/{len(pending)} attempted, "
                                      f"{stage_counts['accepted']} accepted, "
                                      f"{rate * 3600:.0f} tasks/h, {left:.1f} h left",
                                      flush=True)

        # Two pools, sized separately. A large building costs several gigabytes
        # in the worker that holds it, so only a few workers are allowed to be
        # in one; the rest work the small buildings and never wait for them.
        large_workers = max(1, min(large_permits, workers - 1)) if big_chunks else 0
        small_workers = max(1, workers - large_workers)
        print(f"  {len(small_chunks)} small chunks on {small_workers} workers, "
              f"{len(big_chunks)} large chunks on {large_workers} workers",
              flush=True)

        pools, threads = [], []
        if small_chunks:
            pool = make_pool(small_workers, "small")
            pools.append(pool)
            threads.append(threading.Thread(target=consume, args=(pool, small_chunks),
                                            daemon=True))
        if big_chunks and large_workers:
            pool = make_pool(large_workers, "large")
            pools.append(pool)
            threads.append(threading.Thread(target=consume, args=(pool, big_chunks),
                                            daemon=True))
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for pool in pools:
            pool.close()
            pool.join()

    final = funnel(True)
    (out_dir / "funnel_gold.json").write_text(json.dumps(final, indent=2),
                                              encoding="utf-8")
    return final
