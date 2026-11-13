"""Sanity checks, manifest.json and REPORT.txt for VeriBIM-Bench v4 (after select_bench_v4.py and
materialize_bench_v4.py)."""
import hashlib, importlib.util, json, os, sys, time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
OUT = ROOT / "runs_local/bench_v4"
POOLS = ROOT / "runs_local/corpus_v10/migrator_v2"
VERSIONS = ("IFC2X3", "IFC4", "IFC4X3")
OPS = ("create", "delete", "update"); CATS = ("direct", "spatial", "topological")
sys.path.insert(0, str(ROOT / "code"))
spec = importlib.util.spec_from_file_location("build_e2_v3", ROOT / "scripts/benchmark/selection/build_e2_v3.py")
drv = importlib.util.module_from_spec(spec); spec.loader.exec_module(drv)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main():
    t0 = time.time()
    parts = {v: [json.loads(l) for l in open(OUT / f"tasks_{v}.jsonl") if l.strip()] for v in VERSIONS}
    alltasks = [json.loads(l) for l in open(OUT / "tasks.jsonl") if l.strip()]
    assert [t["task_id"] for t in alltasks] == [t["task_id"] for v in VERSIONS for t in parts[v]]
    subsets = {v: json.load(open(OUT / f"subset_108_{v}.json")) for v in VERSIONS}
    s324 = json.load(open(OUT / "subset_324.json"))
    assert s324 == subsets["IFC2X3"] + subsets["IFC4"] + subsets["IFC4X3"] and len(set(s324)) == 324
    insub = set(s324)
    sel_summary = json.load(open(OUT / "work/select_summary.json"))
    reports = {v: json.load(open(OUT / f"work/{v}/select_report.json")) for v in VERSIONS}
    checks = {}

    # 1. no task from a training building
    pool_all = json.load(open(POOLS / "pool_v10_all.json"))
    train_b = {m["building_id"] for m in pool_all["models"] if m.get("in_run")}
    bench_b = {t["building_id"] for t in alltasks}
    overlap = sorted(train_b & bench_b)
    assert not overlap, overlap
    # also against the merged v10 training file and the canonical v2 set (driver check)
    v10_train_b = set()
    for l in open(ROOT / "runs_local/corpus_v10/gen/tasks_v10_new.jsonl"):
        if '"train"' in l:
            t = json.loads(l)
            if t.get("split") == "train":
                v10_train_b.add(t["building_id"])
    overlap2 = sorted(v10_train_b & bench_b)
    assert not overlap2, overlap2
    checks["training_buildings"] = {"pool_v10_all_in_run_buildings": len(train_b), "overlap": overlap,
                                    "tasks_v10_new_train_buildings": len(v10_train_b), "overlap_v10_train": overlap2,
                                    "canonical_v2_shared": {v: reports[v]["canonical"]["buildings_shared_with_selection"] for v in VERSIONS},
                                    "bench_buildings": sorted(bench_b)}

    # 2. source files exist and sha256 matches the pool
    pool = {v: {m["key"]: m for m in json.load(open(POOLS / f"pool_bench_v10_{v}.json"))["models"]} for v in VERSIONS}
    file_sha = {}
    bad_src = []
    for t in alltasks:
        e = pool[t["ifc_version"]][t["source_model"]["key"]]
        p = t["input_ifc"]
        if p not in file_sha:
            file_sha[p] = sha(ROOT / p) if (ROOT / p).exists() else None
        ok = (p == e["relpath"] and file_sha[p] == e["sha256"] == t["source_model"]["sha256"]
              and t["source_relpath"] == e["source_relpath"] and t["origin"] == e["origin"]
              and t["building_id"] == e["building_id"])
        if not ok:
            bad_src.append(t["task_id"])
    assert not bad_src, bad_src[:10]
    checks["source_files"] = {"distinct_files": len(file_sha), "tasks_checked": len(alltasks), "mismatch": len(bad_src)}

    # 3. GNI project 8 in the IFC4 part
    g8 = Counter((t["origin"]) for t in parts["IFC4"] if t["building_id"] == "GNI-project_8")
    checks["gni_project_8_ifc4"] = dict(g8)
    checks["gni_project_8_ifc4_subset"] = sum(1 for t in parts["IFC4"] if t["building_id"] == "GNI-project_8" and t["task_id"] in insub)
    assert g8.get("native", 0) > 0

    # 4. materialisation
    mat = {}
    for l in open(OUT / "work/materialize.journal.jsonl"):
        d = json.loads(l); mat[d["task_id"]] = d
    missing = [t["task_id"] for t in alltasks if t["task_id"] not in mat or not mat[t["task_id"]].get("ok")]
    mism = [(t["task_id"], mat[t["task_id"]]["check"]) for t in alltasks if t["task_id"] in mat
            and mat[t["task_id"]].get("ok") and not mat[t["task_id"]].get("sha_match")]
    gz_missing = [t["task_id"] for t in alltasks if not (OUT / "models" / f"{t['task_id']}.ifc.gz").exists()]
    unstated = [(k, d["unstated_predefined_type"]) for k, d in mat.items() if d.get("unstated_predefined_type")]
    fill_checked = Counter()
    for d in mat.values():
        for cls, pt in d.get("created_fillings") or ():
            fill_checked[(d["ifc_version"], cls, "None" if pt is None else "set")] += 1
    checks["materialisation"] = {
        "rebuilt_ok": sum(1 for t in alltasks if mat.get(t["task_id"], {}).get("ok")),
        "failed": missing, "checks": dict(Counter(mat[t["task_id"]]["check"] for t in alltasks if t["task_id"] in mat)),
        "sha_mismatch": mism, "gz_missing": gz_missing,
        "gold_bytes_uncompressed": sum(mat[t["task_id"]].get("bytes", 0) for t in alltasks if t["task_id"] in mat),
        "gz_bytes": sum(mat[t["task_id"]].get("gz_bytes", 0) for t in alltasks if t["task_id"] in mat),
        "rebuild_seconds_sum": round(sum(mat[t["task_id"]].get("seconds", 0) for t in alltasks if t["task_id"] in mat), 1),
        "created_door_window_in_gold": {"/".join(k): c for k, c in sorted(fill_checked.items())},
        "unstated_predefined_type_in_gold": unstated}

    # manifest
    rows = []
    for t in alltasks:
        m = mat.get(t["task_id"], {})
        rows.append({"task_id": t["task_id"], "ifc_version": t["ifc_version"], "bench_part": t["bench_part"],
                     "origin": t["origin"], "building_id": t["building_id"], "source_key": t["source_model"]["key"],
                     "operation": t["operation"], "category": t["category"], "tier": t["tier"],
                     "edit_kind": t.get("edit_kind"), "families": t.get("families") or [],
                     "source_file": t["input_ifc"], "source_relpath": t["source_relpath"],
                     "source_sha256": t["source_model"]["sha256"],
                     "gold_sha256": (t.get("verification") or {}).get("gold_sha256"),
                     "gold_sha256_rebuilt": m.get("gold_sha256_rebuilt"),
                     "gold_check": m.get("check"), "gold_model_gz": f"models/{t['task_id']}.ifc.gz",
                     "null_edit_score": (t.get("verification") or {}).get("null_edit_score"),
                     "in_subset_108": t["task_id"] in insub})
    per_part = {}
    for v in VERSIONS:
        P = parts[v]
        floors = [drv.nes(t) for t in P if drv.nes(t) is not None]
        rep = reports[v]
        short = {}
        if rep.get("shortfall"):
            short["driver_cells"] = rep["shortfall"]
        if rep["families_short_of_quota"]:
            short["family_cells"] = {f: rep["family_cells"][f] for f in rep["families_short_of_quota"]}
        if sel_summary["parts"][v]["subset_short"]:
            short["subset_cells"] = sel_summary["parts"][v]["subset_short"]
        chain_cells = Counter(f"{t['operation']}/{t['category']}" for t in P if t["tier"] == "compositional")
        absent = [f"{o}/{c}" for o in OPS for c in CATS if chain_cells.get(f"{o}/{c}", 0) == 0]
        per_part[v] = {
            "n": len(P), "seed": sel_summary["parts"][v]["seed"],
            "by_cell_all_tiers": {f"{o}/{c}": sum(1 for t in P if t["operation"] == o and t["category"] == c) for o in OPS for c in CATS},
            "by_cell_single": {f"{o}/{c}": sum(1 for t in P if t["tier"] == "single" and t["operation"] == o and t["category"] == c) for o in OPS for c in CATS},
            "chains_by_cell": dict(sorted(chain_cells.items())), "chain_cells_absent": absent,
            "by_tier": dict(Counter(t["tier"] for t in P)),
            "core": rep["n_core"], "layer_cells": rep["n_layer_cells"], "size_top_up": rep["n_size_top_up"],
            "by_origin": dict(Counter(t["origin"] for t in P)),
            "by_building": dict(sorted(Counter(t["building_id"] for t in P).items())),
            "by_building_origin": {f"{b}/{o}": c for (b, o), c in sorted(Counter((t["building_id"], t["origin"]) for t in P).items())},
            "null_edit_floor_mean": round(sum(floors) / len(floors), 4), "tasks_without_a_floor": len(P) - len(floors),
            "null_edit_share_gt_0.8": rep["null_edit_share_gt_0.8"], "high_floor_share": rep["high_floor_share"],
            "shortfalls": short,
            "subset_108": {"n": len(subsets[v]),
                           "by_building": dict(sorted(Counter(t["building_id"] for t in P if t["task_id"] in insub).items())),
                           "by_origin": dict(Counter(t["origin"] for t in P if t["task_id"] in insub)),
                           "by_tier": dict(Counter(t["tier"] for t in P if t["task_id"] in insub))},
            "exclusions": {k: x for k, x in sel_summary["exclusions"][v].items() if k != "excluded_ids"},
        }
    manifest = {"name": "VeriBIM-Bench v4 (mixed-version: IFC2X3, IFC4, IFC4X3)",
                "tasks_file": str(OUT / "tasks.jsonl"), "tasks_sha256": sha(OUT / "tasks.jsonl"),
                "part_files": {v: {"path": str(OUT / f"tasks_{v}.jsonl"), "sha256": sha(OUT / f"tasks_{v}.jsonl")} for v in VERSIONS},
                "n_tasks": len(alltasks), "generator_version": sorted({t.get("generator_version") for t in alltasks}),
                "selection_driver": "scripts/benchmark/selection/build_e2_v3.py (unchanged), seeds 20260930/31/32",
                "subset": {"files": [f"subset_108_{v}.json" for v in VERSIONS] + ["subset_324.json"], "seed": 20260931,
                           "rule": "12 per operation x category cell (single and chains together), modifc_gen.build_e2.round_robin keyed on building_id"},
                "gold_models": "models/<task_id>.ifc.gz (gzip of the checksummed gold bytes)",
                "buildings": sorted(bench_b), "parts": per_part, "checks": checks, "tasks": rows}
    json.dump(manifest, open(OUT / "manifest.json", "w"), indent=1)
    json.dump({"checks": checks, "parts": per_part, "seconds": round(time.time() - t0, 1)},
              open(OUT / "work/finalize_summary.json", "w"), indent=1)
    print(json.dumps(checks, indent=1)[:4000])


if __name__ == "__main__":
    main()
