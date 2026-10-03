"""Step 6 of the v10 generation: merge the v10 training runs into one task file.

The suffix rule of scripts/benchmark/selection/concat_topups.py is applied to every run
(one suffix per run: -x3, -x3a, -x3b, -x3c, -x4, -x4a, -x4b, -x4c, -x2g), so
identifiers stay unique across versions, across rounds and against the v9
corpus; the task id, the two gold-model paths named by it, and a
``topup_round``/``v10_run`` tag change, the gold script never does.  The split
check of scripts/benchmark/selection/build_wave_all.py is applied (validation iff the
building is one of the eleven validation buildings) and, additionally,
no held-out building (``in_run`` false in the pool) may sit in the train split.
Each record gains ``ifc_version`` (pool entry ``schema``), ``origin`` and
``source_relpath`` from its ``source_model.key``.
"""
import json, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
C10 = ROOT / "runs_local/corpus_v10"
G = C10 / "gen"
VALIDATION = {"BLD001", "BLD006", "BLD008", "BLD011", "BLD022", "BLD024",
              "BLD033", "BLD034", "BLD037", "BLD041", "BLD047"}
#: task file and funnel directory of a run whose tasks were re-sourced after generation
TASKS_OF = {"train_ifc4x3_v2": ("resource/train_ifc4x3_v2.jsonl", "train_ifc4x3"),
            "train_ifc4_v2": ("resource/train_ifc4_v2.jsonl", "train_ifc4")}


def tasks_path(run):
    return G / TASKS_OF[run][0] if run in TASKS_OF else G / run / "tasks.jsonl"


def funnel_dir(run):
    return G / TASKS_OF[run][1] if run in TASKS_OF else G / run


RUNS = [  # (run, suffix, round tag, pool)
    # main runs: the re-sourced files of gen/resource/, on the migrator_v2 pools
    ("train_ifc4x3_v2", "x3", "main", "migrator_v2/pool_v10_IFC4X3_plus.json"),
    ("topup_a_ifc4x3", "x3a", "a", "migrator_v2/pool_v10_IFC4X3_plus.json"),
    ("topup_b_ifc4x3", "x3b", "b", "migrator_v2/pool_v10_IFC4X3_plus.json"),
    ("topup_c_ifc4x3", "x3c", "c", "migrator_v2/pool_v10_IFC4X3_plus.json"),
    ("train_ifc4_v2", "x4", "main", "migrator_v2/pool_v10_IFC4_plus.json"),
    ("topup_a_ifc4", "x4a", "a", "migrator_v2/pool_v10_IFC4_plus.json"),
    ("topup_b_ifc4", "x4b", "b", "migrator_v2/pool_v10_IFC4_plus.json"),
    ("topup_c_ifc4", "x4c", "c", "migrator_v2/pool_v10_IFC4_plus.json"),
    ("train_ifc2x3_gni", "x2g", "main", "gen/pool_v10_IFC2X3_gni.json"),
]


def read(path):
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield json.loads(line)


def transform_run(run, suffix, rnd, pool_name):
    """The records of one run with the merge's suffix and added fields (split untouched)."""
    pool = json.load(open(C10 / pool_name))
    by_key = {m["key"]: m for m in pool["models"]}
    out = []
    for r in read(tasks_path(run)):
        old = r["task_id"]; new = f"{old}-{suffix}"
        r["task_id"] = new; r["topup_round"] = rnd; r["v10_run"] = run
        r["v10_task_file"] = str(tasks_path(run).relative_to(ROOT))
        for field in ("gold_model", "ground_truth_ifc"):
            v = r.get(field)
            if v:
                assert v.endswith(f"/{old}.ifc"), (field, old, v)
                r[field] = v[: -len(f"{old}.ifc")] + f"{new}.ifc"
        entry = by_key[r["source_model"]["key"]]
        assert entry["building_id"] == r["building_id"], (new, entry["building_id"])
        r["ifc_version"] = entry["schema"]
        r["origin"] = entry["origin"]
        r["source_relpath"] = entry["source_relpath"]
        out.append(r)
    return out


def one(run):
    """Train-split records of one finished run, for synthesis ahead of the merge."""
    spec = next(x for x in RUNS if x[0] == run)
    rows = [r for r in transform_run(*spec)
            if r.get("split") == "train" and r["building_id"] not in VALIDATION]
    d = G / "synth_inputs"; d.mkdir(exist_ok=True)
    path = d / f"{run}_train.jsonl"
    with path.open("w", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(path, len(rows))


def main():
    rows, seen, missing_runs = [], set(), []
    funnels, rejections = {}, {}
    held_out = set()
    for run, suffix, rnd, pool_name in RUNS:
        tasks = tasks_path(run)
        if not tasks.exists():
            missing_runs.append(run)
            continue
        pool = json.load(open(C10 / pool_name))
        by_key = {m["key"]: m for m in pool["models"]}
        held_out |= {m["building_id"] for m in pool["models"] if not m["in_run"]}
        f = json.load(open(funnel_dir(run) / "funnel.json"))
        funnels[run] = {k: f.get(k) for k in ("n_attempted", "n_accepted", "n_train",
                        "n_validation", "n_duplicates_dropped", "seconds", "cpu_seconds",
                        "stages")}
        rejections[run] = dict(Counter(f.get("rejections") or {}).most_common(10))
        for r in transform_run(run, suffix, rnd, pool_name):
            new = r["task_id"]
            assert new not in seen, new
            seen.add(new)
            rows.append(r)

    restamped = 0
    for r in rows:
        want = "validation" if r.get("building_id") in VALIDATION else "train"
        if r.get("split") != want:
            r["split"] = want; restamped += 1
    bad_held = [r["task_id"] for r in rows if r["split"] == "train" and r["building_id"] in held_out]
    missing_fields = [r["task_id"] for r in rows
                      if any(r.get(k) in (None, "") for k in
                             ("ifc_version", "origin", "source_relpath", "building_id", "split"))]

    v9 = {json.loads(l)["task_id"] for l in open(ROOT / "runs_local/stage_a_v9_dev/out/corpus_tasks_v9.jsonl")}
    collide_v9 = sorted(seen & v9)
    # also the ids before suffixing, for information
    raw_collide = sum(1 for r in rows if r["task_id"].rsplit("-", 1)[0] in v9)

    out = G / "tasks_v10_new.jsonl"
    with out.open("w", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")

    ver = Counter(r["ifc_version"] for r in rows)
    ver_split = Counter(f'{r["ifc_version"]}|{r["split"]}' for r in rows)
    cells = Counter("|".join([r["ifc_version"], r["origin"], r["split"],
                              r.get("operation", "?"), r.get("category", "?")]) for r in rows)
    train = [r for r in rows if r["split"] == "train"]
    tver = Counter(r["ifc_version"] for r in train)
    buildings = defaultdict(set)
    for r in rows:
        buildings[r["split"]].add(r["building_id"])
    report = {
        "out": str(out), "n": len(rows), "missing_runs": missing_runs,
        "per_run": dict(Counter(r["v10_run"] for r in rows)),
        "version_counts": dict(ver),
        "version_shares": {k: round(v / len(rows), 4) for k, v in ver.items()} if rows else {},
        "train_version_counts": dict(tver),
        "train_version_shares": {k: round(v / len(train), 4) for k, v in tver.items()} if train else {},
        "version_split": dict(ver_split),
        "origin_counts": dict(Counter(f'{r["ifc_version"]}|{r["origin"]}' for r in rows)),
        "split_records_restamped": restamped,
        "train_buildings": len(buildings["train"]), "validation_buildings": len(buildings["validation"]),
        "buildings_in_both_splits": sorted(buildings["train"] & buildings["validation"]),
        "held_out_buildings": sorted(held_out),
        "train_tasks_from_held_out_buildings": len(bad_held),
        "records_missing_required_fields": len(missing_fields),
        "task_id_collisions_with_corpus_tasks_v9": len(collide_v9),
        "unsuffixed_ids_that_would_collide_with_v9": raw_collide,
        "cells_version_origin_split_operation_category": dict(sorted(cells.items())),
        "funnel_per_run": funnels,
        "rejections_top10_per_run": rejections,
    }
    (G / "tasks_v10_new_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: report[k] for k in list(report)[:18]}, indent=1))
    if bad_held or missing_fields or collide_v9 or report["buildings_in_both_splits"]:
        sys.exit("merge check failed")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--one":
        one(sys.argv[2])
    else:
        main()
