"""Batch generation: probe what each model can host, then fill the grid.

The run has three phases.  It first asks every candidate model which cells of
the design grid it can host, which is cheap because nothing is written or
scored.  It then spreads the task budget over the cells that have supporters,
preferring breadth of coverage and a spread of source models.  It finally
generates and verifies the assigned tasks, one worker per model, and writes the
task list, the funnel and the yield table.

Work is pinned to a fixed set of cores and every numerical library is capped to
one thread per worker, so a run cannot take the machine over.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import chains, corpus, generate
from .corpus import ModelRef
from .generate import CATEGORIES, FAMILIES, OPERATIONS
from .scene import Scene
from .version import GENERATOR_VERSION

CELLS = [(c, o, f) for c in CATEGORIES for o in OPERATIONS for f in FAMILIES]
CHAIN_CELLS = [(c, k) for c in CATEGORIES for k in chains.CHAIN_NAMES]

_WORKER: dict[str, Any] = {}


# ------------------------------------------------------------------- workers


def _init_worker(cores: Sequence[int]) -> None:
    """Keep one worker inside its share of the machine.

    Numerical libraries size their thread pools from the machine's core count
    rather than from the affinity mask, so both have to be set: the mask decides
    where the worker runs, the caps decide how many threads it starts.
    """
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass


def probe_model(payload: tuple) -> dict[str, Any]:
    """Which cells one model can host, and why it cannot host the others."""
    model_dict, root, seed = payload
    model = ModelRef(**model_dict)
    started = time.perf_counter()
    try:
        scene = Scene(str(Path(root) / model.relpath), model.relpath, model.sha256)
    except Exception as exc:
        return {"key": model.key, "relpath": model.relpath, "error": repr(exc)[:200],
                "cells": {}, "chains": {}, "seconds": time.perf_counter() - started}
    rng = random.Random(seed)
    cells: dict[str, Any] = {}
    for category, operation, family in CELLS:
        name = generate.cell_id(category, operation, family)
        task_id = generate.task_id_for(model.key, category, operation, family, 0)
        draw, reason = generate.draw_single(scene, category, operation, family,
                                            task_id, rng)
        cells[name] = {"ok": draw is not None, "reason": reason}
    chain_cells: dict[str, Any] = {}
    for category, kind in CHAIN_CELLS:
        name = f"{category}/{kind}"
        task_id = generate.chain_task_id(model.key, category, kind, 0)
        draw, reason = generate.draw_chain(scene, category, kind, task_id, rng)
        chain_cells[name] = {"ok": draw is not None, "reason": reason}
    return {
        "key": model.key, "relpath": model.relpath,
        "collection": model.collection, "schema": model.schema,
        "bytes": model.bytes, "n_products": scene.n_products,
        "n_relations": scene.n_relations, "counts": model.counts,
        "storeys": len(scene.storeys), "unit_scale": scene.unit_scale,
        "cells": cells, "chains": chain_cells, "error": None,
        "seconds": time.perf_counter() - started,
    }


def generate_model(payload: tuple) -> dict[str, Any]:
    """Generate and verify every task assigned to one model."""
    (model_dict, root, out_dir, scratch, assignments, seed, null_baseline,
     index_base) = payload
    model = ModelRef(**model_dict)
    root_path = Path(root)
    out_path = Path(out_dir)
    scratch_path = Path(scratch)
    scratch_path.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    from modifc_score.model_cache import MeshCache, ModelCache
    models_cache = ModelCache(capacity=3)
    meshes_cache = MeshCache()

    records: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    try:
        scene = Scene(str(root_path / model.relpath), model.relpath, model.sha256)
    except Exception as exc:
        return {"key": model.key, "records": [], "outcomes": [
            {"stage": "scene", "reason": "scene_build_failed",
             "detail": {"error": repr(exc)[:200]}}],
            "seconds": time.perf_counter() - started}

    index = index_base
    for assignment in assignments:
        wanted = assignment["count"]
        accepted = 0
        attempts = 0
        budget = wanted * 5 + 5
        while accepted < wanted and attempts < budget:
            attempts += 1
            index += 1
            task_seed = seed * 1000003 + index
            rng = random.Random(task_seed)
            if assignment["tier"] == "single":
                category, operation, family = assignment["cell"]
                task_id = generate.task_id_for(model.key, category, operation,
                                               family, index)
                draw, reason = generate.draw_single(scene, category, operation,
                                                    family, task_id, rng)
            else:
                category, kind = assignment["cell"]
                task_id = generate.chain_task_id(model.key, category, kind, index)
                draw, reason = generate.draw_chain(scene, category, kind,
                                                   task_id, rng)
            if draw is None:
                outcomes.append({"task_id": task_id, "stage": "draw",
                                 "reason": reason, "cell": assignment["name"]})
                continue
            outcome = generate.produce(scene, model, task_id, draw, root_path,
                                       out_path, scratch_path, models_cache,
                                       meshes_cache, task_seed, null_baseline)
            outcomes.append({"task_id": task_id, "stage": outcome.stage,
                             "reason": outcome.reason, "cell": assignment["name"],
                             "detail": outcome.detail})
            if outcome.stage == "accepted" and outcome.record is not None:
                records.append(outcome.record)
                accepted += 1
    return {"key": model.key, "records": records, "outcomes": outcomes,
            "seconds": time.perf_counter() - started}


# ---------------------------------------------------------------- allocation


def allocate(probes: Sequence[dict[str, Any]], n_single: int, n_chain: int,
             max_per_model: int,
             blocked: Optional[set] = None) -> dict[str, list[dict[str, Any]]]:
    """Spread the budget over the cells that have supporters.

    Coverage comes first: the loop walks the whole grid once before any cell is
    asked for a second task, and within a cell it picks the model that has been
    asked for least so far, so no one model carries the set.
    """
    supporters: dict[str, list[str]] = {}
    for category, operation, family in CELLS:
        name = generate.cell_id(category, operation, family)
        supporters[name] = [p["key"] for p in probes
                            if p["cells"].get(name, {}).get("ok")]
    chain_supporters: dict[str, list[str]] = {}
    for category, kind in CHAIN_CELLS:
        name = f"{category}/{kind}"
        chain_supporters[name] = [p["key"] for p in probes
                                  if p["chains"].get(name, {}).get("ok")]

    load: Counter = Counter()
    assignments: dict[tuple[str, str], dict[str, Any]] = {}

    blocked = blocked or set()

    def take(name: str, cell, tier: str, pool: list[str]) -> bool:
        pool = [k for k in pool
                if load[k] < max_per_model and (k, name) not in blocked]
        if not pool:
            return False
        key = min(pool, key=lambda k: (load[k], k))
        load[key] += 1
        slot = assignments.setdefault((key, name), {
            "name": name, "cell": cell, "tier": tier, "count": 0})
        slot["count"] += 1
        return True

    live = [(generate.cell_id(c, o, f), (c, o, f)) for c, o, f in CELLS
            if supporters[generate.cell_id(c, o, f)]]
    live_chains = [(f"{c}/{k}", (c, k)) for c, k in CHAIN_CELLS
                   if chain_supporters[f"{c}/{k}"]]

    placed = 0
    while placed < n_single and live:
        progressed = False
        for name, cell in live:
            if placed >= n_single:
                break
            if take(name, cell, "single", supporters[name]):
                placed += 1
                progressed = True
        if not progressed:
            break

    placed_chain = 0
    while placed_chain < n_chain and live_chains:
        progressed = False
        for name, cell in live_chains:
            if placed_chain >= n_chain:
                break
            if take(name, cell, "chain", chain_supporters[name]):
                placed_chain += 1
                progressed = True
        if not progressed:
            break

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (key, _name), slot in sorted(assignments.items()):
        by_model[key].append(slot)
    return by_model


# ---------------------------------------------------------------------- main


def _remove_gold(root: Path, record: dict[str, Any]) -> None:
    path = Path(record["gold_model"])
    if not path.is_absolute():
        path = root / path
    try:
        path.unlink()
    except OSError:
        pass


def parse_cores(text: str) -> list[int]:
    cores: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-")
            cores.extend(range(int(lo), int(hi) + 1))
        else:
            cores.append(int(part))
    return cores


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="data/modifc_tasks_smoke")
    parser.add_argument("--scratch", default=None)
    parser.add_argument("--n-tasks", type=int, default=200)
    parser.add_argument("--n-chain", type=int, default=24)
    parser.add_argument("--n-models", type=int, default=26)
    parser.add_argument("--max-per-model", type=int, default=14)
    parser.add_argument("--max-bytes", type=int, default=80_000_000)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cores", default="")
    parser.add_argument("--seed", type=int, default=20260823)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--no-null-baseline", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_dir = root / args.out if not os.path.isabs(args.out) else Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(args.scratch) if args.scratch else out_dir / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)

    cores = parse_cores(args.cores) if args.cores else []
    workers = max(1, args.workers)

    candidates = corpus.load_candidates(root, max_bytes=args.max_bytes)
    picked = corpus.select(candidates, args.n_models)
    print(f"{len(candidates)} candidate models, {len(picked)} selected", flush=True)

    import multiprocessing as mp
    context = mp.get_context("fork")

    started = time.perf_counter()
    with context.Pool(workers, initializer=_init_worker,
                      initargs=(cores,)) as pool:
        probes = pool.map(probe_model,
                          [(asdict(m), str(root), args.seed + i)
                           for i, m in enumerate(picked)])
    print(f"probe done in {time.perf_counter() - started:.1f}s", flush=True)
    (out_dir / "yield.json").write_text(json.dumps(
        {"generated": time.strftime("%Y-%m-%d"), "generator_version":
         GENERATOR_VERSION, "models": probes}, indent=1))
    if args.probe_only:
        return 0

    by_key = {m.key: m for m in picked}
    records: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    per_model_seconds: dict[str, float] = {}
    started = time.perf_counter()

    # Two passes at most.  The first fills the grid; the second tops up the
    # shortfall left by cells a model turned out not to be able to host after
    # all, which the probe cannot always foresee because it does not execute the
    # edit.
    remaining_single = args.n_tasks - args.n_chain
    remaining_chain = args.n_chain
    blocked: set[tuple[str, str]] = set()
    seen: set[tuple[str, str]] = set()
    n_duplicates = 0
    for attempt in range(args.passes):
        if remaining_single + remaining_chain <= 0:
            break
        cap = args.max_per_model if attempt == 0 else max(2, args.max_per_model // 4)
        plan = allocate(probes, remaining_single, remaining_chain, cap, blocked)
        if not plan:
            break
        payloads = [(asdict(by_key[key]), str(root), str(out_dir),
                     str(scratch / key), assignments, args.seed + 7919 * attempt,
                     not args.no_null_baseline, attempt * 1000)
                    for key, assignments in sorted(plan.items())]
        total = sum(a["count"] for a in sum(plan.values(), []))
        print(f"pass {attempt + 1}: {total} tasks assigned over {len(plan)} "
              f"models", flush=True)
        with context.Pool(workers, initializer=_init_worker,
                          initargs=(cores,)) as pool:
            results = pool.map(generate_model, payloads)
        for result in results:
            outcomes.extend(result["outcomes"])
            per_model_seconds[result["key"]] = (
                per_model_seconds.get(result["key"], 0.0)
                + round(result["seconds"], 1))
            for outcome in result["outcomes"]:
                if outcome["stage"] != "accepted":
                    blocked.add((result["key"], outcome["cell"]))
            # Two draws can land on the same target with the same parameters;
            # keep the first and count the rest as their own rejection class.
            for record in result["records"]:
                key = (record["input_ifc"], record["instruction"])
                if key in seen:
                    n_duplicates += 1
                    outcomes.append({"task_id": record["task_id"],
                                     "stage": "duplicate",
                                     "reason": "identical_instruction",
                                     "cell": record["category"] + "/"
                                     + record["operation"] + "/"
                                     + record["family"], "detail": {}})
                    _remove_gold(root, record)
                    continue
                seen.add(key)
                records.append(record)
        accepted_single = sum(1 for r in records if r["tier"] == "single")
        accepted_chain = sum(1 for r in records if r["tier"] == "compositional")
        remaining_single = args.n_tasks - args.n_chain - accepted_single
        remaining_chain = args.n_chain - accepted_chain
        print(f"pass {attempt + 1}: {len(records)} accepted so far", flush=True)
    elapsed = time.perf_counter() - started
    records.sort(key=lambda r: r["task_id"])
    with (out_dir / "tasks.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    funnel = Counter()
    reasons = Counter()
    for outcome in outcomes:
        funnel[outcome["stage"]] += 1
        if outcome["stage"] != "accepted":
            reasons[f"{outcome['stage']}:{outcome['reason']}"] += 1
    summary = {
        "generated": time.strftime("%Y-%m-%d"),
        "generator_version": GENERATOR_VERSION,
        "seed": args.seed,
        "n_models_selected": len(picked),
        "n_models_used": len({r["source_model"]["key"] for r in records}),
        # A duplicate is bookkeeping, not an attempt: the draw behind it was
        # already counted when the worker accepted it.
        "n_attempted": sum(1 for o in outcomes if o["stage"] != "duplicate"),
        "n_accepted": len(records),
        "n_duplicates_dropped": n_duplicates,
        "stages": dict(funnel),
        "rejections": dict(reasons.most_common()),
        "seconds": elapsed,
        "seconds_per_accepted": elapsed / max(1, len(records)),
        "per_model_seconds": per_model_seconds,
    }
    (out_dir / "funnel.json").write_text(json.dumps(summary, indent=1))
    with (out_dir / "outcomes.jsonl").open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(outcome, ensure_ascii=False) + "\n")
    print(json.dumps({k: summary[k] for k in
                      ("n_attempted", "n_accepted", "stages", "seconds")},
                     indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
