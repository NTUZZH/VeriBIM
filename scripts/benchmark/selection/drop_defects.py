"""Take the tasks a physical audit found a defect in out of the shipped files.

A task whose gold model carries a defect the edit caused is not a task: the
answer it asks for puts a filling outside its host wall or an element inside
another one, so a model that copied it would be copying the fault.  The audit
names them, this takes them out of the canonical set, its two splits and the
imitation pool, and it repairs the two gate subsets if a dropped task was in
one, drawing the replacement from the same stratum so the stratification holds.

The statistics of the build report are recomputed from the file that is left
rather than by building the set again, because a rebuild would re-run the
seeded subsample and move several thousand tasks instead of ten.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, "code")

from modifc_gen.build_canonical import HIGH_FLOOR_ATTR, NULL_CAP  # noqa: E402
from build_val_subset_v2 import stratum_of  # noqa: E402


def read(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def defective_ids(audit_path) -> list[str]:
    out = []
    for record in read(audit_path):
        if record.get("defects"):
            out.append(record["task_id"])
    return sorted(out)


def filter_file(path, drop: set) -> int:
    path = Path(path)
    if not path.exists():
        return 0
    kept, removed = [], 0
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        if json.loads(line)["task_id"] in drop:
            removed += 1
        else:
            kept.append(line)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return removed


def repair_subset(path, drop: set, pool, taken_elsewhere: set, seed: int):
    """Replace a dropped id with another task of the same stratum."""
    path = Path(path)
    chosen = json.loads(path.read_text(encoding="utf-8"))
    hit = [i for i in chosen if i in drop]
    if not hit:
        return {"hit": [], "replaced": {}}
    by_id = {t["task_id"]: t for t in pool}
    used = set(chosen) | taken_elsewhere
    rng = random.Random(seed)
    replaced = {}
    for task_id in hit:
        want = stratum_of(by_id[task_id]) if task_id in by_id else None
        options = sorted(t["task_id"] for t in pool
                         if t["task_id"] not in used and t["task_id"] not in drop
                         and stratum_of(t) == want)
        if not options:
            raise SystemExit(f"no replacement of stratum {want} for {task_id}")
        new = rng.choice(options)
        chosen[chosen.index(task_id)] = new
        used.add(new)
        replaced[task_id] = new
    path.write_text(json.dumps(chosen, indent=0), encoding="utf-8")
    return {"hit": hit, "replaced": replaced}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", required=True)
    parser.add_argument("--canonical-dir", required=True)
    parser.add_argument("--wave-all", default="")
    parser.add_argument("--report", required=True)
    parser.add_argument("--seed", type=int, default=20260912)
    args = parser.parse_args(argv)

    canon_dir = Path(args.canonical_dir)
    tasks_path = canon_dir / "tasks.jsonl"
    drop = set(defective_ids(args.audit))
    if not drop:
        print("no defective task in the audit; nothing to drop")
        return 0

    rows = list(read(tasks_path))
    dropped = [t for t in rows if t["task_id"] in drop]
    if len(dropped) != len(drop):
        missing = sorted(drop - {t["task_id"] for t in dropped})
        raise SystemExit(f"not in the canonical set: {missing}")
    wave_ids = {t.get("wave_task_id") or t["task_id"] for t in dropped}
    detail = [{"task_id": t["task_id"], "wave_task_id": t.get("wave_task_id"),
               "edit_kind": t.get("edit_kind"), "split": t.get("split"),
               "building_id": t.get("building_id"),
               "families": t.get("families")} for t in sorted(
                   dropped, key=lambda t: t["task_id"])]

    # The gate subsets are repaired against the validation split as it stands
    # before the drop, so a replacement is a task that survives it.
    validation_pool = [t for t in rows
                       if t.get("split") == "validation" and t["task_id"] not in drop]
    five = repair_subset(canon_dir / "val_subset_500_v2.json", drop,
                         validation_pool, set(), args.seed)
    five_now = set(json.loads((canon_dir / "val_subset_500_v2.json")
                              .read_text(encoding="utf-8")))
    one = repair_subset(canon_dir / "val_subset_100_v2.json", drop,
                        [t for t in validation_pool if t["task_id"] in five_now],
                        set(), args.seed + 1)
    one_now = set(json.loads((canon_dir / "val_subset_100_v2.json")
                             .read_text(encoding="utf-8")))
    if not one_now <= five_now:
        raise SystemExit("val-100 is no longer a subset of val-500")

    removed = {name: filter_file(canon_dir / name, drop) for name in
               ("tasks.jsonl", "tasks_train.jsonl", "tasks_validation.jsonl")}
    if args.wave_all:
        removed["wave_all_accepted.jsonl"] = filter_file(args.wave_all, wave_ids)

    # The build report's statistics are recomputed from what is left.
    rows = list(read(tasks_path))
    def kind(t):
        return t.get("edit_kind", "?")
    def nes(t):
        return (t.get("verification") or {}).get("null_edit_score")
    scored = [nes(t) for t in rows if nes(t) is not None]
    translate = [nes(t) for t in rows
                 if kind(t) == "translate" and nes(t) is not None]
    splits = Counter(t.get("split") for t in rows)
    buildings = {s: {t["building_id"] for t in rows if t.get("split") == s}
                 for s in ("train", "validation")}
    report_path = canon_dir / "build_report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    before = {k: report.get(k) for k in
              ("n", "attr_share", "null_edit_mean", "null_edit_share_gt_0.8",
               "translate", "splits")}
    report.update({
        "n": len(rows),
        "attr_share": round(sum(1 for t in rows if kind(t) in HIGH_FLOOR_ATTR)
                            / len(rows), 4),
        "null_edit_mean": round(st.mean(scored), 4),
        "null_edit_share_gt_0.8": round(
            sum(1 for x in scored if x > NULL_CAP) / len(scored), 4),
        "translate": {"n": len(translate),
                      "null_mean": round(st.mean(translate), 4),
                      "share_gt_0.8": round(
                          sum(1 for x in translate if x > NULL_CAP)
                          / len(translate), 4)},
        "splits": dict(splits),
        "underspecified_tasks_excluded_from_the_floor": len(rows) - len(scored),
        "dropped_for_physical_defects": {
            "n": len(drop), "audit": args.audit, "tasks": detail,
            "statistics_before_the_drop": before,
            "note": ("a gold model whose own edit left a filling outside its "
                     "host wall or an element inside another one; the audit "
                     "counts every other task of the set clean"),
        },
    })
    report_path.write_text(json.dumps(report, indent=1), encoding="utf-8")

    splits_path = canon_dir / "splits.json"
    splits_report = json.loads(splits_path.read_text(encoding="utf-8"))
    splits_report.update({
        "counts": dict(splits),
        "train_buildings": len(buildings["train"]),
        "validation_buildings": len(buildings["validation"]),
        "buildings_in_both_splits": sorted(buildings["train"]
                                           & buildings["validation"]),
        "validation_building_counts": dict(sorted(Counter(
            t["building_id"] for t in rows
            if t.get("split") == "validation").items())),
        "dropped_for_physical_defects": len(drop),
    })
    splits_path.write_text(json.dumps(splits_report, indent=1), encoding="utf-8")

    out = {"dropped": detail, "removed_rows": removed,
           "val_500": five, "val_100": one,
           "canonical_n": len(rows), "splits": dict(splits),
           "attr_share": report["attr_share"],
           "null_edit_mean": report["null_edit_mean"],
           "null_edit_share_gt_0.8": report["null_edit_share_gt_0.8"],
           "translate": report["translate"]}
    Path(args.report).write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: out[k] for k in
                      ("removed_rows", "val_500", "val_100", "canonical_n",
                       "splits", "attr_share", "null_edit_mean",
                       "null_edit_share_gt_0.8", "translate")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
