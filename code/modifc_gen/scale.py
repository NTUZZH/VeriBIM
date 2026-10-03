"""Generating a large task set: allocation, sharded execution, resume, merge.

The smoke driver in :mod:`modifc_gen.run` holds the whole run in one process
and writes its results at the end, which is right for two hundred tasks and
wrong for twenty thousand.  This driver differs in four ways.

*Sharding.*  A model's assignment is cut into shards of a few dozen tasks.  A
shard is the unit of work and the unit of resumption: it parses its source model
once, generates its tasks, and writes its own result file.  A run that is
interrupted is restarted with the same command and skips the shards already on
disk.

*Cost-aware caps.*  A source model is copied twice per task, so a 100 MB model
costs a minute of wall clock where a 3 MB model costs a second.  The per-model
task cap is scaled down with file size, which keeps the largest models in the
set for the diversity they bring without letting them dominate the run.

*Discarded gold models.*  The canonical artifact is the gold script; the gold
model is written into scratch, put through the full funnel, and deleted.  The
record keeps its checksum, so the materialisation utility can prove it rebuilt
the same file.

*Seeds from one run seed.*  Every task's seed is a keyed hash of the run seed,
the shard and the attempt index, so a shard regenerated after an interruption
draws exactly what it drew before.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import threading
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from typing import Any, Optional, Sequence

from . import chains, families as families_module, generate, pool as pool_lib
from .corpus import ModelRef
from .generate import CATEGORIES, FAMILIES, OPERATIONS
from .run import CELLS, CHAIN_CELLS, _init_worker, parse_cores, probe_model
from .scene import Scene
from .version import GENERATOR_VERSION


# Which family group each named flag writes into.  The flags are sugar over
# --family-share and the mapping is the only place a flag name meets a group.
_GROUP_OF_FLAG = {
    "share_spec_element_relative": "spec.element_relative",
    "share_constraint_relation_on_create": "constraint.relation_on_create",
    "share_ref_new": "ref.new",
    "share_spec_world_frame": "spec.world_frame",
    "share_constraint_on_edit": "constraint.on_edit",
    "share_wording_ifc_class": "wording.ifc_class",
    # 0.6.0
    "share_op_update_new": "op.update.new",
    "share_op_create_new": "op.create.new",
    "share_scope_batch": "scope.batch",
    "share_scope_conditional": "scope.conditional",
    # 0.7.0
    "share_wording_synonym": "wording.synonym",
    "share_wording_request_form": "wording.request_form",
    "share_wording_class_token": "wording.class_token",
    "share_wording_unit_spelling": "wording.unit_spelling",
    "share_wording_underspecified": "wording.underspecified",
}


def instruction_key(instruction: str) -> str:
    """A short stable key for one instruction, used to spot a repeated draw."""
    return hashlib.blake2b(instruction.encode("utf-8"), digest_size=12).hexdigest()


def task_seed(run_seed: int, shard_id: str, index: int) -> int:
    """One task's seed, derived from the run seed and where the task sits.

    A keyed hash rather than an arithmetic step, so that adding or removing a
    shard does not shift the seeds of the shards around it.
    """
    material = f"{run_seed}|{shard_id}|{index}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(),
                          "big") % (2 ** 31 - 1)


# --------------------------------------------------------------- allocation


def cost_weight(byte_count: int) -> float:
    """How large a share of the budget a model of this size should carry.

    A source model is opened and written out twice per task, so cost grows with
    file size while the variety a model can offer does not.  The three steps
    keep the largest models in the set for the diversity they bring without
    letting them consume the run.
    """
    if byte_count < 25_000_000:
        return 1.0
    if byte_count < 80_000_000:
        return 0.5
    return 0.15


def budget_weight(byte_count: int, n_cells: int) -> float:
    """One model's share of a budget, before it is turned into a cap.

    A model that can host most of the grid should carry more of the set than
    one that can host two cells of it, but not proportionally more: a
    structural model with nothing but columns is worth having in the training
    data, and the square root keeps its share small without erasing it.
    """
    return cost_weight(byte_count) * max(1.0, float(n_cells)) ** 0.5


def cost_ceiling(byte_count: int) -> int:
    """The most tasks one model is asked for, given what a task on it costs.

    Generating and verifying a task opens its source model four times and
    writes two copies of it, so the cost per task tracks file size closely.
    These ceilings keep the run's tail bounded: the largest files stay in the
    set, for the schemas, exporters and building types only they contribute,
    but they never carry a large share of it.
    """
    if byte_count < 25_000_000:
        return 1_000_000
    if byte_count < 60_000_000:
        return 700
    if byte_count < 100_000_000:
        return 250
    return 120


def caps_by_building(models: Sequence[Any], building_of: dict[str, str],
                     cells: dict[str, int], supply: dict[str, int], budget: int,
                     ceiling_fraction: float = 0.08, headroom: float = 1.7,
                     floor: int = 1) -> dict[str, int]:
    """Per-model caps that share the budget over BUILDINGS, not over files.

    A building is the unit a split is made on, so it is also the unit the
    budget is shared on: four exports of one building must not carry four
    times the weight of a building held once.  No building takes more than
    ``ceiling_fraction`` of the budget, no building is asked for more than its
    files can supply, and what a capped building cannot take flows to the
    others.  Within a building the share is divided between its files by the
    same weights, and each file is still bounded by its own supply and by what
    a task on a file that size costs.
    """
    groups: dict[str, list[Any]] = defaultdict(list)
    for model in models:
        groups[building_of[model.key]].append(model)
    weight = {b: cost_weight(min(m.bytes for m in ms))
                 * max(1.0, float(max(cells.get(m.key, 1) for m in ms))) ** 0.5
              for b, ms in groups.items()}
    ceiling = max(1, int(budget * ceiling_fraction))
    limit = {b: min(ceiling,
                    sum(min(supply.get(m.key, 0), cost_ceiling(m.bytes))
                        for m in ms))
             for b, ms in groups.items()}

    share: dict[str, float] = {b: 0.0 for b in groups}
    active = {b for b in groups if limit[b] > 0}
    for _round in range(64):
        remaining = budget - sum(share.values())
        if remaining <= 0.5 or not active:
            break
        total = sum(weight[b] for b in active) or 1.0
        moved = 0.0
        for b in sorted(active):
            take = min(remaining * weight[b] / total, limit[b] - share[b])
            if take > 0:
                share[b] += take
                moved += take
        active = {b for b in active if share[b] < limit[b] - 1e-9}
        if moved <= 1e-9:
            break

    caps: dict[str, int] = {}
    for b, ms in groups.items():
        target = min(float(limit[b]), share[b] * headroom)
        weights = {m.key: budget_weight(m.bytes, cells.get(m.key, 1)) for m in ms}
        total = sum(weights.values()) or 1.0
        for model in ms:
            wanted = int(round(target * weights[model.key] / total))
            caps[model.key] = max(floor, min(
                wanted, supply.get(model.key, wanted),
                cost_ceiling(model.bytes)))
    return caps


def caps_for(models: Sequence[Any], cells: dict[str, int], budget: int,
             headroom: float, floor: int = 20,
             supply: Optional[dict[str, int]] = None) -> dict[str, int]:
    """Per-model task caps that share ``budget`` in proportion to the weights.

    A cap is never larger than what the model can actually supply: a structural
    model with thirteen columns cannot yield three hundred distinct tasks, and
    asking it to would spend the run drawing edits the duplicate check throws
    away.
    """
    supply = supply or {}
    weights = {m.key: budget_weight(m.bytes, cells.get(m.key, 1)) for m in models}
    total = sum(weights.values()) or 1.0
    caps: dict[str, int] = {}
    for model in models:
        share = int(round(headroom * budget * weights[model.key] / total))
        caps[model.key] = max(1, min(max(floor, share),
                                     supply.get(model.key, share)))
    return caps


def supply_bound(probe: dict[str, Any], counts: dict[str, int]) -> int:
    """How many distinct tasks one model could plausibly carry.

    An update or a delete needs a distinct target, so the count of elements of
    the family bounds it; an update has more than one instruction per target,
    because the edit kind and its parameters vary.  A create is bounded by the
    variety of its free parameters rather than by the model's contents, so it
    gets a flat allowance per cell.  The bound is an upper one and is only used
    to stop a thin model being asked for more than it holds.
    """
    total = 0
    for name, outcome in probe.get("cells", {}).items():
        if not outcome.get("ok"):
            continue
        _category, operation, family = name.split("/")
        available = min(counts.get(family, 0), 250)
        if operation == "update":
            # One element carries several distinct edits: a move by any of many
            # offsets, a new name, a new predefined type, a new dimension.
            total += available * 4
        elif operation == "delete":
            total += available
        else:
            total += 120
    for name, outcome in probe.get("chains", {}).items():
        if not outcome.get("ok"):
            continue
        _category, kind = name.split("/", 1)
        if kind == "create_wall_with_door":
            total += 120
        else:
            family = "space" if kind.startswith("move_space") else "wall"
            total += min(counts.get(family, 0), 250) * 2
    return total


def allocate(probes: Sequence[dict[str, Any]], caps: dict[str, int],
             n_single: int, n_chain: int, blocked: Optional[set] = None,
             produced: Optional[dict[str, int]] = None,
             category_weight: Optional[dict[str, int]] = None
             ) -> dict[str, list[dict[str, Any]]]:
    """Spread the budget over the cells that have supporters.

    Coverage comes first: the loop walks the whole grid once before any cell is
    asked for a second task, and within a cell it picks the model that has been
    asked for least so far relative to its own cap, so no one model carries the
    set and a small model is not asked for more than it can supply.
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

    # A resumed run starts from what its earlier shards already produced, so a
    # model that has filled its cap is not asked for more.
    load: Counter = Counter(produced or {})
    assignments: dict[tuple[str, str], dict[str, Any]] = {}
    blocked = blocked or set()

    def take(name: str, cell, tier: str, candidates: list[str]) -> bool:
        available = [k for k in candidates
                     if load[k] < caps.get(k, 0) and (k, name) not in blocked]
        if not available:
            return False
        key = min(available, key=lambda k: (load[k] / max(1, caps.get(k, 1)),
                                            load[k], k))
        load[key] += 1
        slot = assignments.setdefault((key, name), {
            "name": name, "cell": cell, "tier": tier, "count": 0})
        slot["count"] += 1
        return True

    # A style may be asked for more often than the others by appearing more than
    # once in the round-robin, which is how the share of topological
    # instructions is raised without touching the operation library.
    weights = category_weight or {}
    live = []
    for c, o, f in CELLS:
        name = generate.cell_id(c, o, f)
        if supporters[name]:
            live.extend([(name, (c, o, f))] * max(1, int(weights.get(c, 1))))
    live_chains = []
    for c, k in CHAIN_CELLS:
        name = f"{c}/{k}"
        if chain_supporters[name]:
            live_chains.extend([(name, (c, k))] * max(1, int(weights.get(c, 1))))

    # Compositional tasks are placed first.  They are the scarce tier: only
    # nine of the twelve chain cells have any supporter at all, and a model's
    # cap is shared with the single-element tasks, which every model can host.
    # Filling the grid first leaves the tier short of the share it is meant to
    # have.
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

    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (key, _name), slot in sorted(assignments.items()):
        by_model[key].append(slot)
    return dict(by_model)


def shard_size_for(byte_count: int, ceiling: int,
                   seconds: float = 600.0) -> int:
    """How many tasks one unit of work holds, for a model of this size.

    A unit of work should take minutes rather than an hour: it is the unit that
    is lost if the run is interrupted, and the unit that decides how long the
    last worker keeps the others waiting at the end.  Cost per task tracks file
    size, so the count is chosen to keep a shard near a fixed wall-clock target.
    """
    per_task = max(0.5, 0.30 * byte_count / 1e6)
    return max(8, min(ceiling, int(seconds / per_task)))


def shard(plan: dict[str, list[dict[str, Any]]], shard_size: int, tag: str,
          sizes: Optional[dict[str, int]] = None,
          produced: Optional[dict[str, int]] = None) -> list[dict[str, Any]]:
    """Cut each model's assignment into units of work of a few dozen tasks.

    Each shard carries an ``index_base``, and a task's number inside its
    identifier counts up from there.  Two shards of the same model therefore
    never number a task the same way, which is what keeps task identifiers
    unique across a run and across a resumed one.
    """
    sizes = sizes or {}
    produced = produced or {}
    shards: list[dict[str, Any]] = []
    for key, slots in sorted(plan.items()):
        limit = shard_size_for(sizes.get(key, 0), shard_size)
        base = produced.get(key, 0) + 1
        current: list[dict[str, Any]] = []
        current_count = 0
        index = 0
        for slot in slots:
            remaining = slot["count"]
            while remaining > 0:
                room = limit - current_count
                take = min(room, remaining)
                current.append({**slot, "count": take})
                current_count += take
                remaining -= take
                if current_count >= limit:
                    shards.append({"shard_id": f"{tag}-{key}-{index:03d}",
                                   "key": key, "assignments": current,
                                   "index_base": base})
                    base += current_count * 8
                    index += 1
                    current, current_count = [], 0
        if current:
            shards.append({"shard_id": f"{tag}-{key}-{index:03d}",
                           "key": key, "assignments": current,
                           "index_base": base})
    return shards


# ------------------------------------------------------------------- worker


def run_shard(payload: tuple) -> dict[str, Any]:
    """Generate and verify every task in one shard."""
    (shard_spec, model_dict, root, out_dir, scratch, run_seed, null_baseline,
     keep_gold, already_seen, wave_settings) = payload
    from . import settings as settings_module

    settings_module.configure(**(wave_settings or {}))
    from . import ops as ops_module

    ops_module.reset_rejections()
    ops_module.reset_derived()
    shard_id = shard_spec["shard_id"]
    model = ModelRef(**model_dict)
    root_path = Path(root)
    out_path = Path(out_dir)
    scratch_path = Path(scratch) / shard_id
    scratch_path.mkdir(parents=True, exist_ok=True)
    result_path = out_path / "shards" / f"{shard_id}.json"
    started = time.perf_counter()

    from modifc_score.model_cache import MeshCache, ModelCache
    # Two entries: the source model, which every task in the shard reuses, and
    # the gold model of the task in hand.  A third would hold the previous
    # task's gold model, which is already deleted and will never be asked for
    # again, and on the largest sources that is gigabytes of resident memory
    # per worker for nothing.
    models_cache = ModelCache(capacity=2)
    meshes_cache = MeshCache(capacity_vertices=1_500_000)

    records: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    try:
        scene = Scene(str(root_path / model.relpath), model.relpath, model.sha256)
    except Exception as exc:
        outcomes.append({"stage": "scene", "reason": "scene_build_failed",
                         "cell": "", "detail": {"error": repr(exc)[:200]}})
        _write_shard(result_path, shard_id, model.key, records, outcomes,
                     time.perf_counter() - started)
        return {"shard_id": shard_id, "key": model.key, "n_accepted": 0,
                "n_outcomes": len(outcomes),
                "seconds": time.perf_counter() - started}

    # Instructions this model has already yielded, in this shard and in every
    # shard of an earlier pass, so a repeat costs a draw rather than a full
    # verification whose result the merge would then throw away.
    seen: set[str] = set(already_seen or ())
    index = int(shard_spec.get("index_base", 0))
    for assignment in shard_spec["assignments"]:
        wanted = assignment["count"]
        accepted = 0
        attempts = 0
        budget = wanted * 4 + 4
        while accepted < wanted and attempts < budget:
            attempts += 1
            index += 1
            seed = task_seed(run_seed, shard_id, index)
            rng = random.Random(seed)
            # A draw that raises costs one attempt rather than the shard.  The
            # planners refuse what a model cannot carry by returning None, so a
            # raised exception is a defect and is recorded as one.
            try:
                if assignment["tier"] == "single":
                    category, operation, family = assignment["cell"]
                    task_id = generate.task_id_for(model.key, category,
                                                   operation, family, index)
                    draw, reason = generate.draw_single(
                        scene, category, operation, family, task_id, rng)
                else:
                    category, kind = assignment["cell"]
                    task_id = generate.chain_task_id(model.key, category, kind,
                                                     index)
                    draw, reason = generate.draw_chain(scene, category, kind,
                                                       task_id, rng)
            except Exception as exc:
                outcomes.append({"task_id": f"{model.key}-{index}",
                                 "stage": "draw", "reason": "draw_failed",
                                 "cell": assignment["name"],
                                 "detail": {"error": repr(exc)[:200]}})
                continue
            if draw is None:
                outcomes.append({"task_id": task_id, "stage": "draw",
                                 "reason": reason, "cell": assignment["name"]})
                continue
            key = instruction_key(draw.instruction)
            if key in seen:
                outcomes.append({"task_id": task_id, "stage": "duplicate",
                                 "reason": "identical_instruction",
                                 "cell": assignment["name"], "detail": {}})
                continue
            outcome = generate.produce(scene, model, task_id, draw, root_path,
                                       out_path, scratch_path, models_cache,
                                       meshes_cache, seed, null_baseline,
                                       keep_gold)
            outcomes.append({"task_id": task_id, "stage": outcome.stage,
                             "reason": outcome.reason, "cell": assignment["name"],
                             "detail": outcome.detail})
            if outcome.stage == "accepted" and outcome.record is not None:
                outcome.record["shard_id"] = shard_id
                records.append(outcome.record)
                seen.add(key)
                accepted += 1

    seconds = time.perf_counter() - started
    _write_shard(result_path, shard_id, model.key, records, outcomes, seconds,
                 ops_module.rejection_counts(), ops_module.derived_counts())
    _clean(scratch_path)
    return {"shard_id": shard_id, "key": model.key, "n_accepted": len(records),
            "n_outcomes": len(outcomes), "seconds": seconds}


def _write_shard(path: Path, shard_id: str, key: str,
                 records: list[dict[str, Any]], outcomes: list[dict[str, Any]],
                 seconds: float,
                 placement_rejections: Optional[dict[str, int]] = None,
                 derived_placements: Optional[dict[str, int]] = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".partial")
    temporary.write_text(json.dumps(
        {"shard_id": shard_id, "key": key, "seconds": round(seconds, 2),
         "generator_version": GENERATOR_VERSION, "records": records,
         "outcomes": outcomes,
         "placement_rejections": placement_rejections or {},
         "derived_placements": derived_placements or {}}, ensure_ascii=False))
    temporary.replace(path)


def _clean(directory: Path) -> None:
    try:
        for child in sorted(directory.rglob("*"), reverse=True):
            if child.is_file():
                child.unlink()
            else:
                child.rmdir()
        directory.rmdir()
    except OSError:
        pass


# -------------------------------------------------------------------- merge


def relabel(records: list[dict[str, Any]]) -> int:
    """Number the tasks of one cell of one model consecutively, from one.

    A task's number used to count from the start of the shard that produced it,
    so two shards of the same model could number two different tasks the same
    way.  The merge therefore renumbers every task once the whole set is in
    hand, which makes the identifier unique and the numbering gap-free.  The
    identifier a task carried while it was generated is kept in the record as
    ``generation_task_id``, because the identifiers of the entities the edit
    creates were minted from it; those identifiers are literals in the gold
    script, so the gold model and its checksum are untouched.
    """
    counters: Counter = Counter()
    relabelled = 0
    for record in records:
        old_id = record["task_id"]
        prefix, _, _number = old_id.rpartition("-")
        counters[prefix] += 1
        new_id = f"{prefix}-{counters[prefix]:03d}"
        record["generation_task_id"] = old_id
        if new_id == old_id:
            continue
        relabelled += 1
        record["task_id"] = new_id
        for field in ("gold_model", "ground_truth_ifc"):
            value = record.get(field)
            if value:
                record[field] = value.replace(f"{old_id}.ifc", f"{new_id}.ifc")
        record["gold_script"] = record["gold_script"].replace(old_id, new_id)
    return relabelled


def merge(out_dir: Path, run_seed: int, elapsed: float,
          building_of: Optional[dict[str, str]] = None,
          validation: Sequence[str] = ()) -> dict[str, Any]:
    """Collect the shards into the task file, the funnel and the outcomes.

    Each record is stamped with the building it came from and with the split
    that building belongs to, so that a split is by building by construction
    and cannot be undone by re-shuffling the task file.
    """
    building_of = building_of or {}
    validation_set = set(validation)
    records: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    per_shard_seconds: dict[str, float] = {}
    placement_rejections: Counter = Counter()
    derived_placements: Counter = Counter()
    family_counts: Counter = Counter()
    relation_counts: Counter = Counter()
    seen: set[tuple[str, str]] = set()
    n_duplicates = 0
    for path in sorted((out_dir / "shards").glob("*.json")):
        payload = json.loads(path.read_text())
        per_shard_seconds[payload["shard_id"]] = payload["seconds"]
        placement_rejections.update(payload.get("placement_rejections") or {})
        derived_placements.update(payload.get("derived_placements") or {})
        outcomes.extend(payload["outcomes"])
        for record in payload["records"]:
            key = (record["input_ifc"], record["instruction"])
            if key in seen:
                n_duplicates += 1
                outcomes.append({"task_id": record["task_id"],
                                 "stage": "duplicate",
                                 "reason": "identical_instruction_across_shards",
                                 "cell": f"{record['category']}/"
                                         f"{record['operation']}/{record['family']}",
                                 "detail": {}})
                continue
            seen.add(key)
            record.setdefault("wave", "v1")
            building = building_of.get(record["source_model"]["key"], "")
            record["building_id"] = building
            record["split"] = ("validation" if building in validation_set
                               else "train")
            for name in record.get("families") or ():
                family_counts[name] += 1
            for name in record.get("requires_relations") or ():
                relation_counts[name] += 1
            records.append(record)
    records.sort(key=lambda r: (r["task_id"], r["input_ifc"], r["instruction"]))
    n_relabelled = relabel(records)
    with (out_dir / "tasks.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    with (out_dir / "outcomes.jsonl").open("w", encoding="utf-8") as handle:
        for outcome in outcomes:
            handle.write(json.dumps(outcome, ensure_ascii=False) + "\n")

    stages = Counter(o["stage"] for o in outcomes)
    reasons = Counter(f"{o['stage']}:{o['reason']}" for o in outcomes
                      if o["stage"] != "accepted")
    summary = {
        "generated": time.strftime("%Y-%m-%d"),
        "generator_version": GENERATOR_VERSION,
        "run_seed": run_seed,
        "n_shards": len(per_shard_seconds),
        "n_models_used": len({r["source_model"]["key"] for r in records}),
        "n_attempted": sum(1 for o in outcomes if o["stage"] != "duplicate"),
        "n_accepted": len(records),
        "n_train": sum(1 for r in records if r["split"] == "train"),
        "n_validation": sum(1 for r in records if r["split"] == "validation"),
        "n_buildings_used": len({r["building_id"] for r in records}),
        "n_relabelled": n_relabelled,
        "n_duplicates_dropped": n_duplicates
        + sum(1 for o in outcomes if o["stage"] == "duplicate"
              and o["reason"] == "identical_instruction"),
        "stages": dict(stages),
        "rejections": dict(reasons.most_common()),
        "placement_rejections": dict(sorted(placement_rejections.items())),
        "derived_placements": dict(sorted(derived_placements.items())),
        "family_counts": dict(sorted(family_counts.items())),
        "relation_counts": dict(sorted(relation_counts.items())),
        "seconds": round(elapsed, 1),
        "cpu_seconds": round(sum(per_shard_seconds.values()), 1),
        "seconds_per_accepted": round(elapsed / max(1, len(records)), 3),
    }
    (out_dir / "funnel.json").write_text(json.dumps(summary, indent=1))
    return summary


# --------------------------------------------------------------------- main


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="data/veribim_tasks_v1")
    parser.add_argument("--pool", default=None,
                        help="pool file (default <out>/pool.json)")
    parser.add_argument("--scratch", default=None)
    parser.add_argument("--n-tasks", type=int, default=20000)
    parser.add_argument("--chain-share", type=float, default=0.16)
    parser.add_argument("--shard-size", type=int, default=40)
    parser.add_argument("--workers", type=int, default=7)
    parser.add_argument("--cores", default="")
    parser.add_argument("--seed", type=int, default=20260825)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--cap-headroom", type=float, default=1.7,
                        help="spare per-model capacity over the weighted share, "
                             "so that a model that cannot fill its cells does "
                             "not strand part of the budget")
    parser.add_argument("--validation-buildings", default="",
                        help="comma-separated building ids whose tasks form the "
                             "validation split; they are generated to their own "
                             "smaller budget and never mixed with training")
    parser.add_argument("--n-validation", type=int, default=1000)
    parser.add_argument("--seed-instructions", default="",
                        help="an earlier wave's task file; its instructions are "
                             "treated as already produced, so this wave cannot "
                             "repeat one of them")
    parser.add_argument("--wave", default="v1",
                        help="tag written into every record of this run")
    parser.add_argument("--translate-relative", action="store_true",
                        help="draw a move from the element's own extent along "
                             "the axis it moves, not from the storey's size")
    parser.add_argument("--translate-extent-range", default="1,4")
    parser.add_argument("--attribute-weight", type=float, default=1.0,
                        help="relative weight of rename, retype and overall "
                             "resize among the update kinds")
    parser.add_argument("--delete-filling-removes-opening",
                        action=argparse.BooleanOptionalAction, default=None,
                        help="a deleted door or window takes its opening, the "
                             "IfcRelVoidsElement and the IfcRelFillsElement "
                             "with it; on unless the run says otherwise")
    parser.add_argument("--family-share", action="append", default=[],
                        metavar="GROUP=VALUE",
                        help="how often one requirement-family group is drawn, "
                             "by the group's name in modifc_gen.families; may "
                             "be given more than once")
    parser.add_argument("--family-weight", action="append", default=[],
                        metavar="TAG=VALUE",
                        help="the weight of one family inside its group, by "
                             "the family's tag; zero switches it off")
    # Names for the four groups a wave usually moves.  They write into the same
    # registry as --family-share, so a group or a family added later needs no
    # flag of its own.
    parser.add_argument("--derived-placement-prob", type=float, default=None,
                        dest="share_spec_element_relative",
                        help="share of spatial and topological create tasks "
                             "whose position is read off other elements")
    parser.add_argument("--relation-requirement-prob", type=float, default=None,
                        dest="share_constraint_relation_on_create",
                        help="share of create tasks that also state a "
                             "relationship the new element must carry")
    parser.add_argument("--new-anchor-prob", type=float, default=None,
                        dest="share_ref_new",
                        help="share of update and delete anchors drawn from "
                             "the relative and topological kinds")
    parser.add_argument("--world-coordinate-prob", type=float, default=None,
                        dest="share_spec_world_frame",
                        help="share of coordinate-bearing prompts stated in "
                             "world coordinates rather than storey ones")
    parser.add_argument("--constraint-clause-prob", type=float, default=None,
                        dest="share_constraint_on_edit",
                        help="share of update and delete prompts carrying a "
                             "constraint clause")
    parser.add_argument("--relation-class-name-prob", type=float, default=None,
                        dest="share_wording_ifc_class",
                        help="share of relationship clauses that name the IFC "
                             "class rather than saying it in plain words")
    parser.add_argument("--new-operation-prob", type=float, default=None,
                        dest="share_op_update_new",
                        help="share of update draws that ask for one of the "
                             "operations 0.6.0 adds before falling back")
    parser.add_argument("--new-create-prob", type=float, default=None,
                        dest="share_op_create_new",
                        help="share of create draws that copy, array or "
                             "replace an element already in the model")
    parser.add_argument("--batch-prob", type=float, default=None,
                        dest="share_scope_batch",
                        help="share of update and delete draws written over "
                             "every member of a set")
    parser.add_argument("--conditional-prob", type=float, default=None,
                        dest="share_scope_conditional",
                        help="share of those sets a measured condition narrows")
    parser.add_argument("--synonym-prob", type=float, default=None,
                        dest="share_wording_synonym",
                        help="share of instructions whose verb is swapped for "
                             "one that means the same thing")
    parser.add_argument("--request-form-prob", type=float, default=None,
                        dest="share_wording_request_form",
                        help="share of instructions written as a request, a "
                             "question or a briefed order rather than an order")
    parser.add_argument("--class-token-prob", type=float, default=None,
                        dest="share_wording_class_token",
                        help="share of instructions that name the element by "
                             "its IFC class rather than in plain words")
    parser.add_argument("--unit-spelling-prob", type=float, default=None,
                        dest="share_wording_unit_spelling",
                        help="share of instructions that state their lengths "
                             "in another unit or another spelling of one")
    parser.add_argument("--underspecified-prob", type=float, default=None,
                        dest="share_wording_underspecified",
                        help="share of draws whose instruction leaves out one "
                             "value the edit needs, with a gold that changes "
                             "nothing and an answer that asks for it")
    parser.add_argument("--two-hop-prob", type=float, default=0.0,
                        help="how often a topological instruction is required "
                             "to traverse two relationship hops")
    parser.add_argument("--topological-weight", type=int, default=1,
                        help="how many times a topological cell appears in the "
                             "allocation round-robin")
    parser.add_argument("--heavy-bytes", type=int, default=60_000_000,
                        help="a source model at least this large runs on the "
                             "smaller pool, which bounds peak memory")
    parser.add_argument("--heavy-workers", type=int, default=2)
    parser.add_argument("--building-ceiling", type=float, default=0.12,
                        help="the largest share of the budget any one building "
                             "may carry")
    parser.add_argument("--keep-gold", action="store_true",
                        help="keep every gold model on disk (off by default: "
                             "the gold script is the canonical artifact)")
    parser.add_argument("--no-null-baseline", action="store_true")
    parser.add_argument("--probe-only", action="store_true")
    parser.add_argument("--merge-only", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    out_dir = Path(args.out) if os.path.isabs(args.out) else root / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = Path(args.scratch) if args.scratch else out_dir / "_scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    cores = parse_cores(args.cores) if args.cores else []
    workers = max(1, args.workers)

    pool_path = Path(args.pool) if args.pool else out_dir / "pool.json"
    if not pool_path.is_absolute():
        pool_path = root / pool_path
    pool = pool_lib.load_pool(pool_path)
    models = pool_lib.model_refs(pool, only_in_run=True)
    by_key = {m.key: m for m in models}
    print(f"pool {pool_path.name}: {len(models)} models in run over "
          f"{pool['n_buildings_in_run']} buildings", flush=True)

    import multiprocessing as mp
    context = mp.get_context("fork")

    started_all = time.perf_counter()

    yield_path = out_dir / "yield.json"
    if yield_path.exists():
        probes = json.loads(yield_path.read_text())["models"]
        known = {p["key"] for p in probes}
        missing = [m for m in models if m.key not in known]
        if missing:
            print(f"probing {len(missing)} models missing from yield.json",
                  flush=True)
            with context.Pool(workers, initializer=_init_worker,
                              initargs=(cores,)) as worker_pool:
                probes.extend(worker_pool.map(
                    probe_model, [(asdict(m), str(root), args.seed + i)
                                  for i, m in enumerate(missing)]))
            yield_path.write_text(json.dumps(
                {"generated": time.strftime("%Y-%m-%d"),
                 "generator_version": GENERATOR_VERSION, "models": probes},
                indent=1))
    else:
        started = time.perf_counter()
        with context.Pool(workers, initializer=_init_worker,
                          initargs=(cores,)) as worker_pool:
            probes = worker_pool.map(
                probe_model, [(asdict(m), str(root), args.seed + i)
                              for i, m in enumerate(models)])
        print(f"probe done in {time.perf_counter() - started:.1f}s", flush=True)
        yield_path.write_text(json.dumps(
            {"generated": time.strftime("%Y-%m-%d"),
             "generator_version": GENERATOR_VERSION, "models": probes}, indent=1))
    probes = [p for p in probes if p["key"] in by_key]
    if args.probe_only:
        supported = sum(1 for p in probes
                        if any(c["ok"] for c in p["cells"].values()))
        print(f"{supported} of {len(probes)} models host at least one cell")
        return 0

    from . import settings as settings_module

    low, high = (float(x) for x in args.translate_extent_range.split(","))
    # The run records the value it actually used, whether it named it or took
    # the library's own default.
    delete_opening = (settings_module.GeneratorSettings()
                      .delete_filling_removes_opening
                      if args.delete_filling_removes_opening is None
                      else bool(args.delete_filling_removes_opening))
    wave_settings = {"wave": args.wave,
                     "translate_relative": bool(args.translate_relative),
                     "translate_extent_range": (low, high),
                     "attribute_weight": args.attribute_weight,
                     "two_hop_only_prob": args.two_hop_prob,
                     "delete_filling_removes_opening": delete_opening}
    # The 0.5.0 mixing knobs, as weights in the family registry.  The driver
    # only parses names and numbers; which families exist and what a name means
    # lives in modifc_gen.families, so a family added later needs no change
    # here.
    def _pairs(items):
        out = {}
        for item in items:
            name, _, value = str(item).partition("=")
            if not name or not value:
                raise SystemExit(f"expected NAME=VALUE, got {item!r}")
            out[name.strip()] = float(value)
        return out

    family_shares = _pairs(args.family_share)
    for name, value in vars(args).items():
        if name.startswith("share_") and value is not None:
            family_shares[_GROUP_OF_FLAG[name]] = float(value)
    family_weights = _pairs(args.family_weight)
    wave_settings["family_shares"] = family_shares
    wave_settings["family_weights"] = family_weights

    category_weight = {"topological": max(1, args.topological_weight)}

    building_of = {entry["key"]: entry["building_id"] for entry in pool["models"]}
    validation = [b.strip() for b in args.validation_buildings.split(",")
                  if b.strip()]
    validation_set = set(validation)
    unknown = validation_set - set(building_of.values())
    if unknown:
        raise SystemExit(f"validation buildings not in the pool: {sorted(unknown)}")
    held_out = {entry["building_id"] for entry in pool["models"]
                if not entry["in_run"]}
    if validation_set & held_out:
        raise SystemExit("a validation building is also held out for E2: "
                         f"{sorted(validation_set & held_out)}")

    cells_supported = {p["key"]: sum(1 for c in p["cells"].values() if c["ok"])
                       for p in probes}
    counts_of = {entry["key"]: entry["family_counts"] for entry in pool["models"]}
    supply = {p["key"]: supply_bound(p, counts_of.get(p["key"], {}))
              for p in probes}
    val_models = [m for m in models if building_of[m.key] in validation_set]
    train_models = [m for m in models if building_of[m.key] not in validation_set]
    n_validation = args.n_validation if val_models else 0
    n_training = args.n_tasks - n_validation
    caps = caps_by_building(train_models, building_of, cells_supported, supply,
                            n_training, args.building_ceiling, args.cap_headroom)
    caps.update(caps_by_building(val_models, building_of, cells_supported,
                                 supply, n_validation, 0.25, args.cap_headroom))
    print(f"capacity: {sum(caps[m.key] for m in train_models)} training / "
          f"{sum(caps[m.key] for m in val_models)} validation task slots",
          flush=True)
    print(f"budget: {n_training} training tasks over {len(train_models)} models, "
          f"{n_validation} validation tasks over {len(val_models)} models "
          f"({len(validation_set)} buildings)", flush=True)

    n_chain = int(round(args.n_tasks * args.chain_share))
    n_single = args.n_tasks - n_chain

    if args.merge_only:
        summary = merge(out_dir, args.seed, 0.0, building_of, validation)
        summary["validation_buildings"] = validation
        summary["wave_settings"] = wave_settings
        summary["category_weight"] = category_weight
        summary["family_registry"] = families_module.as_dict()
        summary["held_out_buildings"] = sorted(held_out)
        (out_dir / "funnel.json").write_text(json.dumps(summary, indent=1))
        print(json.dumps({k: summary[k] for k in
                          ("n_attempted", "n_accepted", "n_train",
                           "n_validation", "stages")}, indent=1))
        return 0

    shard_dir = out_dir / "shards"
    done = {path.stem for path in shard_dir.glob("*.json")} \
        if shard_dir.exists() else set()
    # Shard identifiers of an earlier invocation are never reused, so a resumed
    # run cannot mistake a shard it still owes for one already on disk.
    run_index = len({name.split("-", 1)[0] for name in done}) if done else 0
    if done:
        print(f"resuming: {len(done)} shards already on disk, "
              f"this invocation writes r{run_index}*", flush=True)

    def tally():
        """What the shards on disk hold, counted the way the merge counts it.

        A task that repeats an instruction another shard already produced is
        dropped by the merge, so counting the shard files naively would say the
        run had finished while the merged file was short.  The tally therefore
        deduplicates first, and returns the instructions each model has already
        yielded so the next pass does not draw them again.
        """
        single = chained = 0
        per_model: Counter = Counter()
        refused: set[tuple[str, str]] = set()
        instructions: dict[str, set[str]] = defaultdict(set)
        seen_global: set[tuple[str, str]] = set()
        for path in sorted(shard_dir.glob("*.json")):
            payload = json.loads(path.read_text())
            for record in payload["records"]:
                key = record["source_model"]["key"]
                marker = (record["input_ifc"], record["instruction"])
                if marker in seen_global:
                    continue
                seen_global.add(marker)
                instructions[key].add(instruction_key(record["instruction"]))
                per_model[key] += 1
                if record["tier"] == "single":
                    single += 1
                else:
                    chained += 1
            for outcome in payload["outcomes"]:
                if outcome["stage"] not in ("accepted", "duplicate"):
                    refused.add((payload["key"], outcome.get("cell", "")))
        return single, chained, dict(per_model), refused, dict(instructions)

    accepted_single, accepted_chain, produced, blocked, instructions = (
        tally() if done else (0, 0, {}, set(), {}))

    # An earlier wave's instructions are off limits, so that the two waves can
    # be mixed without the mixture holding the same task twice.
    if args.seed_instructions:
        earlier = Path(args.seed_instructions)
        if not earlier.is_absolute():
            earlier = root / earlier
        n_seeded = 0
        for line in earlier.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            instructions.setdefault(record["source_model"]["key"], set()).add(
                instruction_key(record["instruction"]))
            n_seeded += 1
        print(f"holding {n_seeded} earlier instructions off limits", flush=True)

    for attempt in range(args.passes):
        remaining_single = n_single - accepted_single
        remaining_chain = n_chain - accepted_chain
        if remaining_single + remaining_chain <= 0:
            break
        # The first pass places the bulk of the budget under the caps that
        # respect the per-building ceiling.  Later passes only top up what the
        # first could not fill, so they are allowed to reach further into a
        # model's supply rather than being held to the same ceiling.
        pass_caps = caps if attempt == 0 else {
            k: max(10, int(round(v * (1.0 + 0.35 * attempt))))
            for k, v in caps.items()}
        plan = allocate(probes, pass_caps, remaining_single, remaining_chain,
                        blocked, produced, category_weight)
        if not plan:
            break
        tag = f"r{run_index}p{attempt}"
        sizes = {m.key: m.bytes for m in models}
        shards = [s for s in shard(plan, args.shard_size, tag, sizes, produced)
                  if s["shard_id"] not in done]
        # Longest first, so the slowest source models are not left running
        # alone at the end while every other worker is idle.
        shards.sort(key=lambda s: -sizes.get(s["key"], 0))
        assigned = sum(a["count"] for s in shards for a in s["assignments"])
        print(f"pass {attempt + 1}: {assigned} tasks in {len(shards)} shards "
              f"over {len(plan)} models", flush=True)
        if not shards:
            break
        def payload_for(spec):
            return (spec, asdict(by_key[spec["key"]]), str(root), str(out_dir),
                    str(scratch), args.seed + 7919 * attempt,
                    not args.no_null_baseline, args.keep_gold,
                    sorted(instructions.get(spec["key"], ())), wave_settings)

        # A worker on a large source model holds gigabytes: the source, the
        # gold model of the task in hand, and the copy the gold script is
        # writing.  Those shards therefore run first and on their own smaller
        # pool, which bounds the memory the run can take at any moment; the
        # rest then run at full width.
        heavy = [s for s in shards if sizes.get(s["key"], 0) >= args.heavy_bytes]
        light = [s for s in shards if sizes.get(s["key"], 0) < args.heavy_bytes]
        lanes = [(heavy, min(args.heavy_workers, workers), "large"),
                 (light, max(1, workers - args.heavy_workers), "small")]
        state = {"finished": 0}
        guard = threading.Lock()

        def run_lane(batch, width, label):
            if not batch:
                return
            print(f"  lane {label}: {len(batch)} shards, {width} workers",
                  flush=True)
            with context.Pool(width, initializer=_init_worker,
                              initargs=(cores,)) as worker_pool:
                for result in worker_pool.imap_unordered(
                        run_shard, [payload_for(s) for s in batch]):
                    with guard:
                        state["finished"] += 1
                        done.add(result["shard_id"])
                        if state["finished"] % 10 == 0 \
                                or state["finished"] == len(shards):
                            print(f"  {state['finished']}/{len(shards)} shards, "
                                  f"last {result['shard_id']} "
                                  f"{result['n_accepted']} accepted in "
                                  f"{result['seconds']:.0f}s", flush=True)

        # The two lanes run at the same time.  Splitting them sequentially would
        # leave most of the machine idle while the large models were worked
        # through, and they carry more than half of the run's cost.
        threads = [threading.Thread(target=run_lane, args=lane, daemon=False)
                   for lane in lanes]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        accepted_single, accepted_chain, produced, blocked, instructions = tally()
        print(f"pass {attempt + 1}: {accepted_single} single + "
              f"{accepted_chain} compositional accepted", flush=True)

    summary = merge(out_dir, args.seed, time.perf_counter() - started_all,
                    building_of, validation)
    summary["validation_buildings"] = validation
    summary["wave_settings"] = wave_settings
    summary["category_weight"] = category_weight
    summary["family_registry"] = families_module.as_dict()
    summary["held_out_buildings"] = sorted(held_out)
    (out_dir / "funnel.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in
                      ("n_attempted", "n_accepted", "n_train", "n_validation",
                       "n_models_used", "n_buildings_used", "stages", "seconds")},
                     indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
