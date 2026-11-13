"""Select VeriBIM-Bench v3 from the E2 candidate pool on the ten held-out buildings.

Selection, not regeneration.  The nine category-by-operation cells and the
compositional tier are filled exactly as the accepted 0.4.1 driver filled them:
thirty-six tasks a cell, a hundred and eight chains, taken low-null-first by a
round robin over (building, element family) so no building and no family
carries a cell.  What v3 adds is a second tier of cells, one per requirement
family of the taxonomy's layers 2 to 7, each asked for twelve tasks, so a
reader can report a model's score per family and not only per style and
operation.  A family the ten buildings cannot supply twelve of keeps what they
hold and the shortfall is reported.

Two rules keep the set from drifting.  The edit kinds an unedited model
half-answers are held to a tenth of the whole set, counted over every such kind
rather than over the three the first waves knew about, because the layer cells
ask for rotations, property values, materials and type objects, which are the
kinds a do-nothing answer scores highest on.  And every draw inside a cell is
low-null-first, so a task an unedited model passes is taken only once the cell
has nothing better.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "code")

from modifc_gen import families as families_module  # noqa: E402
from modifc_gen.build_canonical import HIGH_FLOOR_ATTR  # noqa: E402
from modifc_gen.build_e2 import (  # noqa: E402
    CATEGORIES, CELL_QUOTA, CHAIN_QUOTA, NULL_CAP, OPERATIONS, SPLIT,
    counts, kind, load, round_robin)

#: Every requirement family the taxonomy's layers 2 to 7 name.  The registry
#: holds exactly the families 0.5.0 and later added; the operation and scope
#: tags of the earlier versions are not in it and are covered by the nine cells.
TARGET_FAMILIES = tuple(f.tag for f in families_module.FAMILIES)

#: How many tasks a family cell asks for.
LAYER_QUOTA = 12

#: The whole set stays inside this, so the benchmark is one a reader can run.
TOTAL_MAX = 720

#: And it reaches at least this, so every cell carries enough to read a score
#: off and the do-nothing floor is diluted by the tasks that have none.
TOTAL_MIN = 700

#: The edit kinds an unedited model half-answers, held to this share of the set.
ATTR = HIGH_FLOOR_ATTR
ATTR_TARGET_SHARE = 0.10

SEED = 20260903


def families_of(task) -> set:
    return set(task.get("families") or ())


def nes(task):
    """What an unedited model scores on a task, or nothing where it has no floor.

    An instruction that leaves a value out has no floor at all: doing nothing is
    the edit its gold makes, so the score an unedited model earns says nothing
    about the task.  The 0.4.1 driver read the field directly because the family
    did not exist yet; every reader here goes through this.
    """
    return (task.get("verification") or {}).get("null_edit_score")


def floor_of(task) -> float:
    """Where a task sits in a low-floor-first draw.

    A task with no floor sits with the ones a do-nothing answer cannot pass,
    because a system that changes nothing and says nothing scores zero on it
    under the reading that family is graded with.
    """
    value = nes(task)
    return 0.0 if value is None else float(value)


def new_tally() -> dict:
    return {"n": 0, "null_sum": 0.0, "null_n": 0, "null_over": 0, "attr": 0,
            "no_floor": 0, "difficulty_sum": defaultdict(float),
            "difficulty_n": defaultdict(int)}


def add(tally, task) -> None:
    tally["n"] += 1
    value = nes(task)
    if value is None:
        tally["no_floor"] += 1
    else:
        tally["null_sum"] += value
        tally["null_n"] += 1
        if value > NULL_CAP:
            tally["null_over"] += 1
    if kind(task) in ATTR:
        tally["attr"] += 1
    for field, value in (task.get("difficulty") or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        tally["difficulty_sum"][field] += value
        tally["difficulty_n"][field] += 1


def summarize(tally) -> dict:
    n = tally["n"]
    if not n:
        return {"n": 0, "null_edit_mean": None, "null_edit_share_gt_0.8": None,
                "attr_share": None, "tasks_without_a_floor": 0,
                "difficulty_mean": {}}
    scored = max(1, tally["null_n"])
    return {
        "n": n,
        "null_edit_mean": round(tally["null_sum"] / scored, 4),
        "null_edit_share_gt_0.8": round(tally["null_over"] / scored, 4),
        "attr_share": round(tally["attr"] / n, 4),
        "tasks_without_a_floor": tally["no_floor"],
        "difficulty_mean": {f: round(tally["difficulty_sum"][f]
                                     / tally["difficulty_n"][f], 4)
                            for f in sorted(tally["difficulty_sum"])},
    }


def tally_rows(rows) -> dict:
    tally = new_tally()
    for task in rows:
        add(tally, task)
    return tally


def scan_file(path):
    """Tally another task file by tier, and note the buildings it holds."""
    tallies = {name: new_tally()
               for name in ("all", "single", "compositional")}
    buildings = set()
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        task = json.loads(line)
        buildings.add(task.get("building_id", ""))
        add(tallies["all"], task)
        if task.get("tier") in ("single", "compositional"):
            add(tallies[task["tier"]], task)
    return {name: summarize(tally) for name, tally in tallies.items()}, buildings


def attr_quota(cells, quota, total, share=ATTR_TARGET_SHARE):
    """How many high-floor tasks each of the nine cells carries."""
    hosts = [name for name in sorted(cells)
             if any(kind(t) in ATTR for t in cells[name])]
    wanted = int(round(share * total))
    out = {name: 0 for name in cells}
    left = wanted
    for position, name in enumerate(hosts):
        remaining = len(hosts) - position
        available = sum(1 for t in cells[name] if kind(t) in ATTR)
        take = min(quota, available, -(-left // remaining))
        out[name] = take
        left -= take
    return out, wanted


def select_cell(rows, quota, attribute_quota, key_of, seed):
    """Fill one cell, preferring the edits a do-nothing answer cannot pass."""
    attribute = [t for t in rows if kind(t) in ATTR]
    other = [t for t in rows if kind(t) not in ATTR]

    def take(pool, count):
        if count <= 0:
            return []
        low = [t for t in pool if floor_of(t) <= NULL_CAP]
        picked = round_robin(low, count, key_of, seed)
        if len(picked) < count:
            chosen = {t["task_id"] for t in picked}
            high = [t for t in pool
                    if floor_of(t) > NULL_CAP and t["task_id"] not in chosen]
            picked += round_robin(high, count - len(picked), key_of, seed)
        return picked

    picked = take(attribute, min(attribute_quota, len(attribute)))
    picked += take(other, quota - len(picked))
    if len(picked) < quota:
        chosen = {t["task_id"] for t in picked}
        rest = [t for t in rows if t["task_id"] not in chosen]
        picked += take(rest, quota - len(picked))
    return picked


def fill_layers(pool, chosen, attr_budget, total_max):
    """Bring every requirement family up to its quota, cheapest task first.

    One task carries several families, so the tasks are taken greedily: the one
    that lifts the most families still short of their quota goes first, and a
    tie is settled by the score an unedited model earns on it and then by the
    identifier, so the choice is reproducible from the candidate file alone.
    A family cell outranks the high-floor budget.  Three of the families a
    reader most wants reported per family - a material, a property value, a
    type object - are themselves edits an unedited model half-answers, so a
    budget that outranked them left the set with none of the first and half of
    the third.  The budget therefore bounds nothing here and the set's floor is
    held down by the top-up below instead, which is made of tasks a do-nothing
    answer scores zero on.  What the budget would have allowed is still
    reported, beside the share the set actually carries.
    """
    targets = frozenset(TARGET_FAMILIES)
    tags_of = {id(t): frozenset(families_of(t) & targets) for t in pool}
    have = Counter()
    for task in chosen:
        for tag in families_of(task) & targets:
            have[tag] += 1
    taken_ids = {t["task_id"] for t in chosen}
    attr_taken = sum(1 for t in chosen if kind(t) in ATTR)

    by_family = defaultdict(list)
    for task in pool:
        if task["task_id"] in taken_ids:
            continue
        for tag in tags_of[id(task)]:
            by_family[tag].append(task)
    for tag in by_family:
        by_family[tag].sort(key=lambda t: (floor_of(t), t["task_id"]))

    added = []
    while len(chosen) + len(added) < total_max:
        short = {tag for tag in TARGET_FAMILIES if have[tag] < LAYER_QUOTA}
        if not short:
            break
        best = None
        for tag in sorted(short):
            # The candidates of one family are already in the order the set
            # wants them, so only the head of each list has to be weighed.
            for task in by_family.get(tag, ()):
                if task["task_id"] in taken_ids:
                    continue
                gain = len(tags_of[id(task)] & short)
                key = (-gain, floor_of(task), task["task_id"])
                if best is None or key < best[0]:
                    best = (key, task)
                break
        if best is None:
            break
        task = best[1]
        taken_ids.add(task["task_id"])
        added.append(task)
        if kind(task) in ATTR:
            attr_taken += 1
        for tag in tags_of[id(task)]:
            have[tag] += 1
    return added, have


def top_up(pool, chosen, total_min: int, seed: int) -> list:
    """Bring the set up to its size target on the tasks that cost it least.

    Every family has its quota by the time this runs, so what the set still
    needs is size, and the cheapest size is a task an unedited model scores
    zero on: it raises no floor and it fills the nine cells the design is built
    on.  The draw is the same round robin over building and element family the
    cells use, so the spread survives.
    """
    need = total_min - len(chosen)
    if need <= 0:
        return []
    taken = {t["task_id"] for t in chosen}
    free = [t for t in pool
            if t["task_id"] not in taken and t["tier"] == "single"]
    zero = [t for t in free if floor_of(t) <= 0.0]
    picked = round_robin(zero, need,
                         lambda t: (t["building_id"], t["family"]), seed)
    if len(picked) < need:
        chosen_ids = {t["task_id"] for t in picked}
        rest = [t for t in free
                if t["task_id"] not in chosen_ids and floor_of(t) <= NULL_CAP]
        picked += round_robin(rest, need - len(picked),
                              lambda t: (t["building_id"], t["family"]), seed)
    return picked


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--canonical",
                        default="runs_local/wave_v2/canonical_v2/tasks.jsonl")
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--total-max", type=int, default=TOTAL_MAX)
    parser.add_argument("--total-min", type=int, default=TOTAL_MIN)
    args = parser.parse_args(argv)

    pool = load(args.tasks)
    tiers = ("single", "compositional")
    candidates = [t for t in pool if t.get("tier") in tiers]
    keep = [t for t in candidates
            if not (t["tier"] == "single" and kind(t) == "translate"
                    and floor_of(t) > NULL_CAP)]
    dropped = len(candidates) - len(keep)

    cells = {}
    for category in CATEGORIES:
        for operation in OPERATIONS:
            cells[f"{category}/{operation}"] = [
                t for t in keep if t["tier"] == "single"
                and t["category"] == category and t["operation"] == operation]
    chains = [t for t in keep if t["tier"] == "compositional"]

    shortfall = {name: {"quota": CELL_QUOTA, "candidates": len(rows)}
                 for name, rows in sorted(cells.items())
                 if len(rows) < CELL_QUOTA}
    if len(chains) < CHAIN_QUOTA:
        shortfall["compositional"] = {"quota": CHAIN_QUOTA,
                                      "candidates": len(chains)}

    core_total = 9 * CELL_QUOTA + CHAIN_QUOTA
    quotas, core_attr_target = attr_quota(cells, CELL_QUOTA, core_total)
    core = []
    for name, rows in sorted(cells.items()):
        core.extend(select_cell(rows, CELL_QUOTA, quotas[name],
                                lambda t: (t["building_id"], t["family"]),
                                args.seed))
    core.extend(round_robin(chains, CHAIN_QUOTA,
                            lambda t: (t["building_id"], kind(t)), args.seed))

    # The whole set may carry this many high-floor tasks; the nine cells have
    # already taken some of them, and the rest is what the layer cells may use.
    attr_budget = int(round(ATTR_TARGET_SHARE * args.total_max))
    layers, have = fill_layers(keep, core, attr_budget, args.total_max)
    filler = top_up(keep, core + layers, args.total_min, args.seed)

    selected = core + layers + filler
    for task in selected:
        task["split"] = SPLIT
    selected.sort(key=lambda t: t["task_id"])
    ids = [t["task_id"] for t in selected]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"{len(ids) - len(set(ids))} duplicate task ids")

    single = [t for t in selected if t["tier"] == "single"]
    chosen_chains = [t for t in selected if t["tier"] == "compositional"]
    stats = {"all": summarize(tally_rows(selected)),
             "single": summarize(tally_rows(single)),
             "compositional": summarize(tally_rows(chosen_chains))}

    canonical, canonical_buildings = ({}, set())
    if os.path.exists(args.canonical):
        canonical, canonical_buildings = scan_file(args.canonical)
    shared = sorted({t["building_id"] for t in selected} & canonical_buildings)

    funnel = {}
    funnel_path = os.path.join(os.path.dirname(args.tasks), "funnel.json")
    if os.path.exists(funnel_path):
        with open(funnel_path) as handle:
            funnel = json.load(handle)
    versions = sorted({t.get("generator_version", "") for t in selected})

    family_table = {}
    for tag in TARGET_FAMILIES:
        in_pool = sum(1 for t in keep if tag in families_of(t))
        family_table[tag] = {
            "in_set": have.get(tag, 0), "quota": LAYER_QUOTA,
            "candidates": in_pool,
            "reached": have.get(tag, 0) >= min(LAYER_QUOTA, in_pool)}

    high_floor = sum(1 for t in selected if kind(t) in ATTR)
    report = {
        "seed": args.seed, "split": SPLIT, "tasks": args.tasks,
        "generator_version": versions[0] if len(versions) == 1 else versions,
        "generation": {
            "generator_version": funnel.get("generator_version"),
            "run_seed": funnel.get("run_seed"),
            "wave_settings": funnel.get("wave_settings"),
            "category_weight": funnel.get("category_weight"),
            "funnel": funnel_path if funnel else None,
        },
        "n_candidates": {
            "single": sum(1 for t in candidates if t["tier"] == "single"),
            "compositional": sum(1 for t in candidates
                                 if t["tier"] == "compositional"),
            "after_null_cap": {
                "single": sum(1 for t in keep if t["tier"] == "single"),
                "compositional": len(chains)}},
        "n_dropped_translate_null_gt_0.8": dropped,
        "quotas": {"cell": CELL_QUOTA, "chain": CHAIN_QUOTA,
                   "layer_cell": LAYER_QUOTA, "core_total": core_total,
                   "total_max": args.total_max,
                   "total_min": args.total_min,
                   "high_floor_share_target": ATTR_TARGET_SHARE,
                   "high_floor_budget": attr_budget,
                   "core_attribute_target": core_attr_target,
                   "core_attribute_per_cell": {k: v for k, v in
                                               sorted(quotas.items()) if v}},
        "n_selected": len(selected),
        "n_core": len(core), "n_layer_cells": len(layers),
        "n_size_top_up": len(filler),
        "cells": {name: {
            "candidates": len(rows),
            "candidates_null_at_or_below_cap":
                sum(1 for t in rows if floor_of(t) <= NULL_CAP),
            "selected": sum(1 for t in single
                            if f"{t['category']}/{t['operation']}" == name),
            # The mean is over the tasks that have a floor at all; a task
            # whose instruction leaves a value out has none and is counted
            # beside it rather than scored as a free mark.
            "null_edit_mean": round(
                sum(nes(t) for t in single
                    if f"{t['category']}/{t['operation']}" == name
                    and nes(t) is not None)
                / max(1, sum(1 for t in single
                             if f"{t['category']}/{t['operation']}" == name
                             and nes(t) is not None)), 4),
            "selected_without_a_floor": sum(
                1 for t in single
                if f"{t['category']}/{t['operation']}" == name
                and nes(t) is None),
        } for name, rows in sorted(cells.items())},
        "family_cells": family_table,
        "families_short_of_quota": sorted(
            tag for tag, row in family_table.items() if not row["reached"]),
        "buildings": counts(selected, lambda t: t["building_id"]),
        "element_families": counts(selected, lambda t: t["family"]),
        "chain_edit_kinds": counts(chosen_chains, kind),
        "edit_kinds": counts(selected, kind),
        "high_floor_tasks": high_floor,
        "high_floor_share": round(high_floor / max(1, len(selected)), 4),
        "attr_share": stats["all"]["attr_share"],
        "null_edit_mean": stats["all"]["null_edit_mean"],
        "null_edit_share_gt_0.8": stats["all"]["null_edit_share_gt_0.8"],
        "difficulty_mean": stats["all"]["difficulty_mean"],
        "by_tier": {"single": stats["single"],
                    "compositional": stats["compositional"]},
        "canonical": {"path": args.canonical, "stats": canonical,
                      "buildings_shared_with_selection": shared},
    }
    if shortfall:
        report["shortfall"] = shortfall

    os.makedirs(os.path.dirname(args.report) or ".", exist_ok=True)
    with open(args.report, "w") as handle:
        json.dump(report, handle, indent=1)

    if shortfall:
        for name, entry in sorted(shortfall.items()):
            print(f"SHORTFALL {name}: {entry['candidates']} candidates for a "
                  f"quota of {entry['quota']}")
        print(f"no task file written; report at {args.report}")
        return 2
    if shared:
        raise SystemExit(f"buildings shared with the training set: {shared}")

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        for task in selected:
            handle.write(json.dumps(task, ensure_ascii=False) + "\n")
    print(json.dumps({k: report[k] for k in
                      ("n_selected", "n_core", "n_layer_cells", "cells",
                       "buildings", "element_families", "high_floor_share",
                       "null_edit_mean", "null_edit_share_gt_0.8",
                       "families_short_of_quota", "by_tier")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
