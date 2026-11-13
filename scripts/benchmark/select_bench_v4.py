"""VeriBIM-Bench v4 selection.

Per version: exclusion rules, then the accepted E2 v3 driver
(scripts/benchmark/selection/build_e2_v3.py, imported unchanged) with seed 20260930 + 0/1/2, then the
bench fields (ifc_version, origin, bench_part) and the 108-task hosted subset (12 per
operation x category cell, round robin over buildings with modifc_gen.build_e2.round_robin, seed 20260931).
"""
import hashlib, importlib.util, json, os, re, shutil, sys, time
from collections import Counter
from pathlib import Path

ROOT = Path(".")
OUT = ROOT / "runs_local/bench_v4"
GEN = ROOT / "runs_local/corpus_v10/gen"
POOLS = ROOT / "runs_local/corpus_v10/migrator_v2"
VERSIONS = ("IFC2X3", "IFC4", "IFC4X3")
SEED0 = 20260930
SUBSET_SEED = 20260931
SUBSET_PER_CELL = 12
BAD_FAMILIES = {"spec.element_relative.touching_slab_above", "spec.element_relative.fits_gap"}
OPS = ("create", "delete", "update")
CATS = ("direct", "spatial", "topological")

sys.path.insert(0, str(ROOT / "code"))
spec = importlib.util.spec_from_file_location("build_e2_v3", ROOT / "scripts/benchmark/selection/build_e2_v3.py")
drv = importlib.util.module_from_spec(spec); spec.loader.exec_module(drv)
from modifc_gen.build_e2 import round_robin  # noqa: E402

PT_RE = re.compile(r"predefined_type\s*=\s*'([A-Za-z_]+)'")


def door_window_task(t):
    k = t.get("edit_kind", "")
    return (t.get("family") in ("door", "window") or "filling" in k or "door" in k or "window" in k)


def unstated_type(t):
    """The unstated-type rule widened to any door/window task: a predefined type drawn into the gold
    (edit_params or a literal in the gold script) whose token the instruction never states."""
    if not door_window_task(t):
        return None
    tokens = set(PT_RE.findall(t.get("gold_script") or ""))
    p = (t.get("edit_params") or {}).get("predefined_type")
    if p is not None:
        tokens.add(str(p))
    missing = sorted(x for x in tokens if x not in (t.get("instruction") or ""))
    return missing or None


def main():
    t0 = time.time()
    summary = {"exclusions": {}, "parts": {}}
    all_rows, subsets = [], {}
    for i, ver in enumerate(VERSIONS):
        pool = json.load(open(POOLS / f"pool_bench_v10_{ver}.json"))
        by_key = {m["key"]: m for m in pool["models"]}
        cand = [json.loads(l) for l in open(GEN / f"bench_candidates_v10_{ver}.jsonl") if l.strip()]
        ex_type, ex_fam, keep = [], [], []
        for t in cand:
            if unstated_type(t):
                ex_type.append(t["task_id"]); continue
            if t.get("edit_kind") == "create_box" and set(t.get("families") or ()) & BAD_FAMILIES:
                ex_fam.append(t["task_id"]); continue
            keep.append(t)
        # families of excluded create_box tasks, and any non-create_box task carrying the two families (kept, reported)
        fam_split = Counter(f for t in cand if t["task_id"] in set(ex_fam) for f in set(t["families"]) & BAD_FAMILIES)
        other_bad = Counter((t["edit_kind"], t["tier"]) for t in keep if set(t.get("families") or ()) & BAD_FAMILIES)
        assert not ex_type, f"{ver}: {len(ex_type)} candidates carry an unstated door/window PredefinedType"
        summary["exclusions"][ver] = {"candidates": len(cand), "unstated_filling_type": len(ex_type),
                                      "create_box_bad_family": len(ex_fam), "by_family": dict(fam_split),
                                      "kept_non_create_box_with_bad_family": {f"{a}/{b}": c for (a, b), c in other_bad.items()},
                                      "after_exclusion": len(keep), "excluded_ids": ex_type + ex_fam}
        wdir = OUT / "work" / ver
        wdir.mkdir(parents=True, exist_ok=True)
        shutil.copy(GEN / f"bench_{ver.lower()}" / "funnel.json", wdir / "funnel.json")
        with open(wdir / "candidates.jsonl", "w", encoding="utf-8") as h:
            for t in keep:
                h.write(json.dumps(t, ensure_ascii=False) + "\n")
        rc = drv.main(["--tasks", str(wdir / "candidates.jsonl"), "--out", str(wdir / "selected.jsonl"),
                       "--report", str(wdir / "select_report.json"), "--seed", str(SEED0 + i),
                       "--canonical", str(ROOT / "runs_local/wave_v2/canonical_v2/tasks.jsonl")])
        if rc != 0:
            raise SystemExit(f"{ver}: driver returned {rc} (cell shortfall); see {wdir/'select_report.json'}")
        sel = [json.loads(l) for l in open(wdir / "selected.jsonl") if l.strip()]
        for t in sel:
            e = by_key[t["source_model"]["key"]]
            assert e["building_id"] == t["building_id"] and e["schema"] == ver == t["ifc_version"]
            assert t.get("origin") == e["origin"], (t["task_id"], t.get("origin"), e["origin"])
            t["ifc_version"] = ver
            t["origin"] = e["origin"]
            t["bench_part"] = ver
        with open(OUT / f"tasks_{ver}.jsonl", "w", encoding="utf-8") as h:
            for t in sel:
                h.write(json.dumps(t, ensure_ascii=False) + "\n")
        all_rows += sel
        # hosted subset: 12 per operation x category cell (single and chains together, as e2_subset_108),
        # round robin over buildings
        sub = []
        short = {}
        for op in OPS:
            for cat in CATS:
                rows = sorted((t for t in sel if t["operation"] == op and t["category"] == cat),
                              key=lambda t: t["task_id"])
                pick = round_robin(rows, SUBSET_PER_CELL, lambda t: t["building_id"], SUBSET_SEED)
                if len(pick) < SUBSET_PER_CELL:
                    short[f"{op}/{cat}"] = len(pick)
                sub += [t["task_id"] for t in pick]
        subsets[ver] = sub
        json.dump(sub, open(OUT / f"subset_108_{ver}.json", "w"), indent=0)
        summary["parts"][ver] = {"selected": len(sel), "subset": len(sub), "subset_short": short,
                                 "seed": SEED0 + i}
        print(ver, "selected", len(sel), "subset", len(sub), flush=True)
    with open(OUT / "tasks.jsonl", "w", encoding="utf-8") as h:
        for t in all_rows:
            h.write(json.dumps(t, ensure_ascii=False) + "\n")
    ids = [t["task_id"] for t in all_rows]
    assert len(ids) == len(set(ids)), "duplicate task ids across parts"
    json.dump(subsets["IFC2X3"] + subsets["IFC4"] + subsets["IFC4X3"], open(OUT / "subset_324.json", "w"), indent=0)
    summary["seconds"] = round(time.time() - t0, 1)
    json.dump(summary, open(OUT / "work" / "select_summary.json", "w"), indent=1)
    print(json.dumps({v: {k: x for k, x in e.items() if k != "excluded_ids"} for v, e in summary["exclusions"].items()}, indent=1))
    print(json.dumps(summary["parts"], indent=1))


if __name__ == "__main__":
    main()
