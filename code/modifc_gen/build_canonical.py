"""Build the canonical VeriBIM-Tasks set from wave 1 + wave 2.

Selection, not regeneration: wave 2 is kept whole; from wave 1 the
translate tasks a no-op could pass (null-edit > 0.8) are dropped, and every
edit kind an unedited model half-answers is subsampled so that stratum is 10%
of the final set. Seeded, so the set is reproducible from the two wave files
alone.

Until 0.7.0 the stratum was three attribute-only kinds. Measured on the 0.6.0
pilot, eight further kinds sit above the same floor, and leaving them whole
left the wave at 0.2627 against the 0.162 the canonical set is measured at;
subsampling all eleven brings it to 0.0820. ``--stratum legacy`` rebuilds a
set made under the earlier list.

Task ids are unique in the output. The generator numbered wave 2 per
(family, building) from 001 again, so 8,739 wave-2 ids collide with wave-1
ids of different tasks; every wave-2 id therefore carries the suffix
``-w2`` here (its gold-model path follows, since the gold cache names files
by that path), and every row keeps its in-wave id as ``wave_task_id``.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics as st

#: The three attribute-only edit kinds the first two waves subsampled.  Kept
#: under a name of its own so a set built before 0.7.0 can be rebuilt exactly.
LEGACY_ATTR = ("rename", "retype", "resize_overall")

#: Every edit kind a system can half-answer by doing nothing.  An unedited
#: model scores above one half on each of them, measured on the 0.6.0 pilot
#: (``runs_local/gen_v06/null_edit_canonical_recipe.json``) and again on the
#: 0.7.0 pilot, so the wave has to subsample all of them and not only the three
#: the first two waves knew about.  Leaving the other eight in left the 0.6.0
#: wave at a floor of 0.2627 where the canonical set sits at 0.162; subsampling
#: all eleven brings it to 0.0820.
HIGH_FLOOR_ATTR = LEGACY_ATTR + (
    "assign_material", "assign_type", "move_space_with_bounding_walls",
    "move_to_storey", "resize_extrusion", "resize_profile", "rotate",
    "set_pset")

#: An edit kind whose median unedited score sits above this belongs in the list
#: above.  The threshold is stated so a later wave can re-derive the list from
#: its own measurement rather than inherit this one.
HIGH_FLOOR = 0.5

STRATA = {"high_floor": HIGH_FLOOR_ATTR, "legacy": LEGACY_ATTR}

ATTR = HIGH_FLOOR_ATTR
ATTR_TARGET = 0.10
NULL_CAP = 0.8
SEED = 20260830
WAVE2_SUFFIX = "-w2"


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--wave1", default="data/veribim_tasks_v1/tasks.jsonl")
    p.add_argument("--wave2", default="data/veribim_tasks_v2/tasks.jsonl")
    p.add_argument("--out", default="data/veribim_tasks_canonical/tasks.jsonl")
    p.add_argument("--report", default="data/veribim_tasks_canonical/build_report.json")
    p.add_argument("--wave1-label", default="v1",
                   help="what the first wave file is called in the record's "
                        "\"wave\" field; a later production wave is one file "
                        "and names itself")
    p.add_argument("--wave2-label", default="v2",
                   help="what the second wave file is called; pass an empty "
                        "second file to build from one wave alone")
    p.add_argument("--stratum", choices=sorted(STRATA), default="high_floor",
                   help="which edit kinds are subsampled to a tenth of the "
                        "set: every kind an unedited model half-answers "
                        "(default), or the three the first two waves named")
    args = p.parse_args(argv)
    attr_kinds = STRATA[args.stratum]

    def load(path, wave, suffix=""):
        rows = []
        for line in open(path):
            t = json.loads(line)
            t["wave"] = wave
            t["wave_task_id"] = t["task_id"]
            if suffix:
                old, new = t["task_id"], t["task_id"] + suffix
                t["task_id"] = new
                for key in ("gold_model", "ground_truth_ifc"):
                    if not t[key].endswith(f"/{old}.ifc"):
                        raise AssertionError(f"{key} of {old} is not named by its id: {t[key]}")
                    t[key] = t[key][: -len(f"{old}.ifc")] + f"{new}.ifc"
            rows.append(t)
        return rows

    w1 = load(args.wave1, args.wave1_label)
    w2 = load(args.wave2, args.wave2_label, suffix=WAVE2_SUFFIX) \
        if args.wave2 else []

    def kind(t):
        return t.get("edit_kind", "?")

    def nes(t):
        return (t.get("verification") or {}).get("null_edit_score")

    rng = random.Random(SEED)
    w1_keep = [t for t in w1 if not (kind(t) == "translate"
                                     and (nes(t) or 0.0) > NULL_CAP)]
    dropped_translate = len(w1) - len(w1_keep)

    attr_w1 = [t for t in w1_keep if kind(t) in attr_kinds]
    attr_w2 = [t for t in w2 if kind(t) in attr_kinds]
    non_attr = [t for t in w1_keep if kind(t) not in attr_kinds] + \
               [t for t in w2 if kind(t) not in attr_kinds]

    quota = int((ATTR_TARGET * len(non_attr) - (1 - ATTR_TARGET) * len(attr_w2))
                / (1 - ATTR_TARGET))
    quota = min(max(quota, 0), len(attr_w1))
    attr_w1_kept = rng.sample(attr_w1, quota)

    canon = non_attr + attr_w2 + attr_w1_kept
    canon.sort(key=lambda t: t["task_id"])
    ids = [t["task_id"] for t in canon]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"{len(ids) - len(set(ids))} duplicate task ids in the canonical set")

    import os
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w") as fh:
        for t in canon:
            fh.write(json.dumps(t) + "\n")

    # A task whose instruction leaves out a value it needs has no unedited
    # score: doing nothing is the edit its gold makes, so a floor read on it
    # would report one and mean nothing.  Those tasks are counted and left out
    # of the floor rather than scored as free marks.
    scored = [t for t in canon if nes(t) is not None]
    clarifying = len(canon) - len(scored)
    allv = [nes(t) for t in scored]
    tr = [nes(t) for t in scored if kind(t) == "translate"]
    by_kind = {}
    for t in scored:
        by_kind.setdefault(kind(t), []).append(nes(t))
    above = sorted(k for k, values in by_kind.items()
                   if st.median(values) > HIGH_FLOOR and k not in attr_kinds)
    report = {
        "seed": SEED,
        "n": len(canon),
        "wave2_id_suffix": WAVE2_SUFFIX,
        "wave2_ids_colliding_with_wave1": len({t["wave_task_id"] for t in w2}
                                              & {t["wave_task_id"] for t in w1}),
        "sources": {"wave1_in": len(w1), "wave2_in": len(w2),
                    "wave1_label": args.wave1_label,
                    "wave2_label": args.wave2_label if w2 else None,
                    "wave1_file": args.wave1,
                    "wave2_file": args.wave2 or None},
        "dropped_wave1_translate_null_gt_0.8": dropped_translate,
        "attr_wave1_kept": f"{quota}/{len(attr_w1)}",
        "attr_share": round(sum(1 for t in canon if kind(t) in ATTR) / len(canon), 4),
        "null_edit_mean": round(st.mean(allv), 4),
        "null_edit_share_gt_0.8": round(sum(1 for x in allv if x > 0.8) / len(allv), 4),
        "translate": {"n": len(tr), "null_mean": round(st.mean(tr), 4),
                      "share_gt_0.8": round(sum(1 for x in tr if x > 0.8) / len(tr), 4)},
        "splits": {s: sum(1 for t in canon if t.get("split") == s)
                   for s in {t.get("split") for t in canon}},
        "bimedit_reference": {"null_edit_mean": 0.173, "share_gt_0.8": 0.065},
        "stratum": args.stratum,
        "attribute_kinds": list(attr_kinds),
        "underspecified_tasks_excluded_from_the_floor": clarifying,
        "high_floor_kinds_not_subsampled": above,
    }
    with open(args.report, "w") as fh:
        json.dump(report, fh, indent=2)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
