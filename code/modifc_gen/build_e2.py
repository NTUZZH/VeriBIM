"""Select the E2 held-out-buildings test set from the E2 candidate pool.

Selection, not regeneration: the E2 wave generates far more tasks than the
test set needs, on buildings no training task ever saw, and this script cuts
that pool down to a fixed, balanced 432.  Nothing about a record changes
except its ``split`` field, which is set to ``e2`` so the materialisation and
audit utilities can address the set by name.

The single-element tier is balanced by construction: nine cells of category
by operation, thirty-six tasks each.  Inside a cell the tasks are taken by a
seeded round-robin over (building, element family) groups, one from each
group in turn, so no building and no family carries the cell.  The
compositional tier is drawn the same way over (building, edit kind) groups.
The translate tasks a no-op could pass (null-edit > 0.8) are dropped first,
under the cap the canonical set uses.

A cell that cannot fill its quota is a generation problem, not a selection
problem, so a short cell is never padded from its neighbours: the script
writes the report with the shortfall and exits without a task file.
"""

from __future__ import annotations

import argparse
import json
import os
import random
from collections import defaultdict

ATTR = ("rename", "retype", "resize_overall")
CATEGORIES = ("direct", "spatial", "topological")
OPERATIONS = ("create", "update", "delete")
CELL_QUOTA = 36
CHAIN_QUOTA = 108
NULL_CAP = 0.8
SEED = 20260903
SPLIT = "e2"

# Share of the whole set the attribute-only edits are meant to carry.  Renaming,
# retyping and setting a door's overall size are invisible to two of the score's
# three axes, so a task of that kind sits near the score a do-nothing answer
# earns whatever the set does; the canonical set therefore holds them to a
# tenth of the tasks by design rather than taking whatever the draw yields.
ATTR_TARGET_SHARE = 0.10


def load(path):
    rows = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            rows.append(json.loads(line))
    return rows


def kind(t):
    return t.get("edit_kind", "?")


def nes(t):
    return t["verification"]["null_edit_score"]


def round_robin(rows, quota, key_of, seed):
    """Take ``quota`` tasks, one from each group in turn, cycling.

    Groups are shuffled internally and then ordered by a shuffle of their
    keys, both from ``seed``, so the choice is reproducible from the
    candidate file alone.  Taking one member per group per turn spreads the
    quota over buildings and element families as evenly as the yield allows:
    a group only carries a second task once every other group has carried a
    first.
    """
    groups = defaultdict(list)
    for t in rows:
        groups[key_of(t)].append(t)
    rng = random.Random(seed)
    order = sorted(groups)
    for key in order:
        groups[key].sort(key=lambda t: t["task_id"])
        rng.shuffle(groups[key])
    rng.shuffle(order)

    picked = []
    cursor = {key: 0 for key in order}
    while len(picked) < quota:
        moved = False
        for key in order:
            if len(picked) >= quota:
                break
            index = cursor[key]
            if index < len(groups[key]):
                picked.append(groups[key][index])
                cursor[key] = index + 1
                moved = True
        if not moved:
            break
    return picked


def attr_quota(cells, quota, total, share=ATTR_TARGET_SHARE):
    """How many attribute-only tasks each cell carries, from the whole set's target.

    Only the update cells host such an edit, so the target for the whole set,
    chained tasks included, is spread over the cells that can supply one, in a
    fixed order, and a cell with fewer candidates than its share passes the
    remainder to the next.
    """
    hosts = [name for name in sorted(cells)
             if any(kind(t) in ATTR for t in cells[name])]
    wanted = int(round(share * total))
    out = {name: 0 for name in cells}
    left = wanted
    for position, name in enumerate(hosts):
        remaining_cells = len(hosts) - position
        available = sum(1 for t in cells[name] if kind(t) in ATTR)
        take = min(quota, available, -(-left // remaining_cells))
        out[name] = take
        left -= take
    return out, wanted


def select_cell(rows, quota, attribute_quota, key_of, seed):
    """Fill one cell, preferring edits a do-nothing answer cannot pass.

    Within the cell the candidates are split two ways: the attribute-only edits,
    which the set holds to a fixed share, and everything else.  Each side is
    taken low-score-first, so a task a no-op scores above the cap is drawn only
    when the side runs out.  Both sides are drawn by the same round-robin over
    (building, family) groups, so the spread the design asks for survives.
    """
    attribute = [t for t in rows if kind(t) in ATTR]
    other = [t for t in rows if kind(t) not in ATTR]

    def take(pool, count):
        if count <= 0:
            return []
        low = [t for t in pool if nes(t) <= NULL_CAP]
        picked = round_robin(low, count, key_of, seed)
        if len(picked) < count:
            chosen = {t["task_id"] for t in picked}
            high = [t for t in pool
                    if nes(t) > NULL_CAP and t["task_id"] not in chosen]
            picked += round_robin(high, count - len(picked), key_of, seed)
        return picked

    wanted_attribute = min(attribute_quota, len(attribute))
    picked = take(attribute, wanted_attribute)
    picked += take(other, quota - len(picked))
    if len(picked) < quota:
        # One side ran out, so the other carries the rest of the quota.
        chosen = {t["task_id"] for t in picked}
        rest = [t for t in rows if t["task_id"] not in chosen]
        picked += take(rest, quota - len(picked))
    return picked


def counts(rows, key_of):
    tally = defaultdict(int)
    for t in rows:
        tally[key_of(t)] += 1
    return dict(sorted(tally.items()))


def new_tally():
    """Running totals for one set of tasks.

    Kept as running totals rather than as a list of records, because the
    canonical set is read for comparison and it is a hundred megabytes of
    gold scripts that nothing here needs.
    """
    return {"n": 0, "null_sum": 0.0, "null_over": 0, "attr": 0,
            "difficulty_sum": defaultdict(float),
            "difficulty_n": defaultdict(int)}


def add(tally, t):
    tally["n"] += 1
    tally["null_sum"] += nes(t)
    if nes(t) > NULL_CAP:
        tally["null_over"] += 1
    if kind(t) in ATTR:
        tally["attr"] += 1
    for field, value in (t.get("difficulty") or {}).items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        tally["difficulty_sum"][field] += value
        tally["difficulty_n"][field] += 1


def summarize(tally):
    n = tally["n"]
    if not n:
        return {"n": 0, "null_edit_mean": None, "null_edit_share_gt_0.8": None,
                "attr_share": None, "difficulty_mean": {}}
    return {
        "n": n,
        "null_edit_mean": round(tally["null_sum"] / n, 4),
        "null_edit_share_gt_0.8": round(tally["null_over"] / n, 4),
        "attr_share": round(tally["attr"] / n, 4),
        "difficulty_mean": {f: round(tally["difficulty_sum"][f]
                                     / tally["difficulty_n"][f], 4)
                            for f in sorted(tally["difficulty_sum"])},
    }


def tally_rows(rows):
    tally = new_tally()
    for t in rows:
        add(tally, t)
    return tally


def scan_file(path):
    """Tally another task file by tier, and note the buildings it holds.

    The buildings are what makes the E2 set a held-out one, so the comparison
    file is asked for its own building list as well as its statistics.
    """
    tallies = {name: new_tally()
               for name in ("all", "single", "compositional")}
    buildings = set()
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        t = json.loads(line)
        buildings.add(t.get("building_id", ""))
        add(tallies["all"], t)
        if t.get("tier") in ("single", "compositional"):
            add(tallies[t["tier"]], t)
    return {name: summarize(tally) for name, tally in tallies.items()}, buildings


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tasks", default="data/veribim_tasks_e2/tasks.jsonl")
    p.add_argument("--out", default="data/veribim_tasks_e2/e2_tasks.jsonl")
    p.add_argument("--report", default="data/veribim_tasks_e2/e2_report.json")
    p.add_argument("--canonical", default="data/veribim_tasks_canonical/tasks.jsonl",
                   help="the canonical set, for the comparison statistics")
    p.add_argument("--canonical-report",
                   default="data/veribim_tasks_canonical/build_report.json")
    p.add_argument("--seed", type=int, default=SEED)
    args = p.parse_args(argv)

    pool = load(args.tasks)
    tiers = ("single", "compositional")
    candidates = [t for t in pool if t.get("tier") in tiers]
    keep = [t for t in candidates
            if not (t["tier"] == "single" and kind(t) == "translate"
                    and nes(t) > NULL_CAP)]
    dropped_translate = len(candidates) - len(keep)
    print(f"pool {len(pool)} rows, {len(candidates)} in the two tiers, "
          f"{dropped_translate} translate tasks dropped at null-edit > {NULL_CAP}")

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

    quotas, attribute_target = attr_quota(
        cells, CELL_QUOTA, 9 * CELL_QUOTA + CHAIN_QUOTA)
    selected = []
    for name, rows in sorted(cells.items()):
        selected.extend(select_cell(rows, CELL_QUOTA, quotas[name],
                                    lambda t: (t["building_id"], t["family"]),
                                    args.seed))
    selected.extend(round_robin(chains, CHAIN_QUOTA,
                                lambda t: (t["building_id"], kind(t)),
                                args.seed))
    for t in selected:
        t["split"] = SPLIT
    selected.sort(key=lambda t: t["task_id"])
    ids = [t["task_id"] for t in selected]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"{len(ids) - len(set(ids))} duplicate task ids "
                             "in the E2 set")

    single = [t for t in selected if t["tier"] == "single"]
    chosen_chains = [t for t in selected if t["tier"] == "compositional"]

    stats = {"all": summarize(tally_rows(selected)),
             "single": summarize(tally_rows(single)),
             "compositional": summarize(tally_rows(chosen_chains))}
    canonical, canonical_buildings = ({}, set())
    if os.path.exists(args.canonical):
        canonical, canonical_buildings = scan_file(args.canonical)
    shared = sorted({t["building_id"] for t in selected} & canonical_buildings)
    canonical_reference = {}
    if os.path.exists(args.canonical_report):
        with open(args.canonical_report) as fh:
            canonical_reference = json.load(fh).get("bimedit_reference", {})

    # The wave that produced the pool describes the set as much as the seed
    # does, so the report carries the generator's version and the settings the
    # generation ran with beside the selection's own numbers.
    funnel = {}
    funnel_path = os.path.join(os.path.dirname(args.tasks), "funnel.json")
    if os.path.exists(funnel_path):
        with open(funnel_path) as fh:
            funnel = json.load(fh)
    versions = sorted({t.get("generator_version", "") for t in selected})

    report = {
        "seed": args.seed,
        "split": SPLIT,
        "tasks": args.tasks,
        "generator_version": versions[0] if len(versions) == 1 else versions,
        "generation": {
            "generator_version": funnel.get("generator_version"),
            "run_seed": funnel.get("run_seed"),
            "wave_settings": funnel.get("wave_settings"),
            "category_weight": funnel.get("category_weight"),
            "placement_rejections": funnel.get("placement_rejections"),
            "funnel": funnel_path if funnel else None,
        },
        "n_candidates": {
            "single": sum(1 for t in candidates if t["tier"] == "single"),
            "compositional": sum(1 for t in candidates
                                 if t["tier"] == "compositional"),
            "after_null_cap": {"single": sum(1 for t in keep
                                             if t["tier"] == "single"),
                               "compositional": len(chains)},
        },
        "n_dropped_translate_null_gt_0.8": dropped_translate,
        "quotas": {"cell": CELL_QUOTA, "chain": CHAIN_QUOTA,
                   "total": 9 * CELL_QUOTA + CHAIN_QUOTA,
                   "attribute_share_target": ATTR_TARGET_SHARE,
                   "attribute_tasks_target": attribute_target,
                   "attribute_per_cell": {k: v for k, v in sorted(quotas.items())
                                          if v}},
        "n_selected": len(selected),
        "cells": {name: {
            "candidates": len(rows),
            "candidates_null_at_or_below_cap":
                sum(1 for t in rows if nes(t) <= NULL_CAP),
            "selected": sum(1 for t in single
                            if f"{t['category']}/{t['operation']}" == name),
            "selected_above_null_cap": sum(
                1 for t in single
                if f"{t['category']}/{t['operation']}" == name
                and nes(t) > NULL_CAP),
            "selected_attribute": sum(
                1 for t in single
                if f"{t['category']}/{t['operation']}" == name
                and kind(t) in ATTR),
            "null_edit_mean": round(sum(
                nes(t) for t in single
                if f"{t['category']}/{t['operation']}" == name)
                / max(1, sum(1 for t in single
                             if f"{t['category']}/{t['operation']}" == name)), 4),
        } for name, rows in sorted(cells.items())},
        "buildings": counts(selected, lambda t: t["building_id"]),
        "families": counts(selected, lambda t: t["family"]),
        "chain_edit_kinds": counts(chosen_chains, kind),
        "attr_share": stats["all"]["attr_share"],
        "null_edit_mean": stats["all"]["null_edit_mean"],
        "null_edit_share_gt_0.8": stats["all"]["null_edit_share_gt_0.8"],
        "difficulty_mean": stats["all"]["difficulty_mean"],
        "by_tier": {"single": stats["single"],
                    "compositional": stats["compositional"]},
        "canonical": {"path": args.canonical, "stats": canonical,
                      "buildings_shared_with_selection": shared},
        "bimedit_reference": canonical_reference,
    }
    if shortfall:
        report["shortfall"] = shortfall

    if os.path.dirname(args.report):
        os.makedirs(os.path.dirname(args.report), exist_ok=True)
    with open(args.report, "w") as fh:
        json.dump(report, fh, indent=2)

    if shortfall:
        for name, entry in sorted(shortfall.items()):
            print(f"SHORTFALL {name}: {entry['candidates']} candidates for a "
                  f"quota of {entry['quota']}")
        print(f"no task file written; report at {args.report}")
        return 2

    if len(selected) != 9 * CELL_QUOTA + CHAIN_QUOTA:
        raise AssertionError(f"selected {len(selected)} tasks, expected "
                             f"{9 * CELL_QUOTA + CHAIN_QUOTA}")
    if shared:
        print(f"WARNING: {len(shared)} of the selected buildings also appear "
              f"in {args.canonical}: {', '.join(shared)}")
    if os.path.dirname(args.out):
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        for t in selected:
            fh.write(json.dumps(t, ensure_ascii=False) + "\n")

    print(json.dumps({k: report[k] for k in
                      ("seed", "split", "n_candidates", "n_selected", "cells",
                       "buildings", "families", "chain_edit_kinds",
                       "attr_share", "null_edit_mean", "null_edit_share_gt_0.8",
                       "by_tier")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
