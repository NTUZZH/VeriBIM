"""Every task the funnel accepted, for the imitation stage and nothing else.

The canonical set is the pool the reward and the evaluation draw on, so it
subsamples the eleven edit kinds an unedited model half-answers down to a tenth
of itself.  That subsample is what keeps its do-nothing floor at 0.08, and it
takes five of the ten operations 0.6.0 added with it, which is why the 0.6.0
share falls from 22 per cent of the wave to 15 per cent of the set.

Imitation data does not need that floor.  A trajectory is copied from a gold
script, so a task an unedited model would half-answer still teaches the model
to write the edit.  This file is therefore every task the funnel accepted, the
wave and all three top-up rounds, with its family tags and with the split the
canonical set uses, so Stage A can draw the thin operation families from it
while Stage B and Stage C draw from the canonical set.

It carries the raw floor, about 0.23, and must not be used to report difficulty
or to score anything.
"""

from __future__ import annotations

import argparse
import json
import statistics as st
from collections import Counter
from pathlib import Path

#: The eleven buildings the canonical set keeps for validation.
VALIDATION_BUILDINGS = ("BLD001", "BLD006", "BLD008", "BLD011", "BLD022",
                        "BLD024", "BLD033", "BLD034", "BLD037", "BLD041",
                        "BLD047")


def read(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wave", required=True)
    parser.add_argument("--topups", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--report", required=True)
    args = parser.parse_args(argv)

    validation = set(VALIDATION_BUILDINGS)
    rows = list(read(args.wave))
    n_wave = len(rows)
    if args.topups and Path(args.topups).exists():
        rows += list(read(args.topups))
    n_topup = len(rows) - n_wave

    ids = [r["task_id"] for r in rows]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"{len(ids) - len(set(ids))} repeated task ids")

    # The split is stamped by the generator from the building, so it is already
    # the canonical set's split.  It is asserted rather than trusted, and a
    # record the generator left unstamped is stamped here, so no validation
    # building can reach the training part.
    restamped = 0
    for record in rows:
        wanted = "validation" if record.get("building_id") in validation \
            else "train"
        if record.get("split") != wanted:
            record["split"] = wanted
            restamped += 1

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    families = Counter()
    kinds = Counter()
    splits = Counter()
    buildings = {"train": Counter(), "validation": Counter()}
    scored = []
    for record in rows:
        for tag in record.get("families") or ():
            families[tag] += 1
        kinds[record.get("edit_kind", "?")] += 1
        splits[record["split"]] += 1
        buildings[record["split"]][record.get("building_id")] += 1
        value = (record.get("verification") or {}).get("null_edit_score")
        if value is not None:
            scored.append(value)

    shared = sorted(set(buildings["train"]) & set(buildings["validation"]))
    report = {
        "out": str(out), "n": len(rows),
        "sources": {"wave": n_wave, "topups": n_topup,
                    "wave_file": args.wave, "topups_file": args.topups or None},
        "splits": dict(splits),
        "split_records_restamped": restamped,
        "train_buildings": len(buildings["train"]),
        "validation_buildings": len(buildings["validation"]),
        "buildings_in_both_splits": shared,
        "raw_null_edit_mean": round(st.mean(scored), 4) if scored else None,
        "raw_null_edit_share_gt_0.8": round(
            sum(1 for x in scored if x > 0.8) / len(scored), 4) if scored else None,
        "tasks_without_a_floor": len(rows) - len(scored),
        "families": dict(sorted(families.items(), key=lambda kv: -kv[1])),
        "edit_kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "purpose": ("imitation data only; the raw floor is what an unedited "
                    "model scores on it and no difficulty or score may be "
                    "reported from it"),
    }
    Path(args.report).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ("n", "sources", "splits", "split_records_restamped",
                       "train_buildings", "validation_buildings",
                       "buildings_in_both_splits", "raw_null_edit_mean",
                       "raw_null_edit_share_gt_0.8", "tasks_without_a_floor")},
                     indent=1))
    if shared:
        raise SystemExit(f"a building is in both splits: {shared}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
