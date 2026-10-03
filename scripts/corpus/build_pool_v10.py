"""Build the v10 pools: one pool per IFC version, every entry carrying the building id its source
building has in pool v2 (migrated copies share it, so the building-level split holds across versions) and an
``origin`` field (native | migrated). GNI files get building ids GNI-<stem>; the 208 fundamentals variants are
one design brief, so they also carry ``family_group`` = "gni_fundamentals" for the split rule.

  python build_pool_v10.py            -> runs_local/corpus_v10/pool_v10_{IFC2X3,IFC4,IFC4X3}.json + pool_v10_all.json
Entries follow modifc_gen.pool.build_pool's schema so modifc_gen.scale --pool accepts them.
"""
import os, sys, json, hashlib, time, collections
from pathlib import Path
os.environ["OMP_NUM_THREADS"] = "1"
import ifcopenshell
ROOT = Path("."); OUT = ROOT/"runs_local/corpus_v10"; MIG = OUT/"migrated"
sys.path.insert(0, str(ROOT/"code"))
from modifc_gen.pool import size_tier

pool2 = json.load(open(ROOT/"data/veribim_tasks_v2/pool.json"))
v2 = {m["relpath"]: m for m in pool2["models"]}
held_out = set(pool2["excluded_buildings"])
gni_inv = {r["relpath"]: r for r in map(json.loads, open(ROOT/"data/corpus/gni/inventory.jsonl"))}
gni_con = {r["relpath"]: r for r in map(json.loads, open(ROOT/"data/corpus/gni/contamination.jsonl"))}
mig = [json.loads(l) for l in open(MIG/"manifest.jsonl")] if (MIG/"manifest.jsonl").exists() else []

FAM = {"wall": ("IfcWall", "IfcWallStandardCase"), "slab": ("IfcSlab",), "space": ("IfcSpace",),
       "door": ("IfcDoor",), "window": ("IfcWindow",), "column": ("IfcColumn",)}
cache_path = OUT/"pool_v10_scan_cache.json"
cache = json.load(open(cache_path)) if cache_path.exists() else {}

def scan(relpath):
    p = ROOT/relpath; key = f"{relpath}|{p.stat().st_size}"
    if key in cache: return cache[key]
    t = time.perf_counter()
    f = ifcopenshell.open(str(p))
    counts = {}
    for fam, classes in FAM.items():
        n = 0
        for c in classes:
            try: n += len(f.by_type(c, include_subtypes=False))
            except Exception: pass
        counts[fam] = n
    rec = {"sha256": hashlib.sha256(open(p, "rb").read()).hexdigest(), "schema": f.schema,
           "n_products": len(f.by_type("IfcProduct")), "family_counts": counts, "bytes": p.stat().st_size,
           "seconds": round(time.perf_counter()-t, 1)}
    apps = f.by_type("IfcApplication"); rec["exporter"] = (apps[0].ApplicationFullName if apps else None)
    del f; cache[key] = rec; json.dump(cache, open(cache_path, "w")); return rec

entries = []
def add(key, relpath, building_id, label, collection, origin, source_relpath, family_group=None):
    s = scan(relpath)
    entries.append({"key": key, "relpath": relpath, "sha256": s["sha256"], "building_id": building_id,
        "building_label": label, "collection": collection, "schema": s["schema"], "bytes": s["bytes"],
        "size_tier": size_tier(s["bytes"]), "n_products": s["n_products"], "family_counts": s["family_counts"],
        "n_families": sum(1 for v in s["family_counts"].values() if v > 0), "exporter": s["exporter"],
        "project_name": None, "in_run": building_id not in held_out, "held_out": building_id in held_out,
        "origin": origin, "source_relpath": source_relpath, "family_group": family_group})
    print(key, s["schema"], s["n_products"], origin, f'{s["seconds"]}s', flush=True)

# (1) corpus originals, in-run only (held-out buildings are the benchmark's; their migrated copies are built separately)
for m in pool2["models"]:
    if m["in_run"]:
        add(m["key"], m["relpath"], m["building_id"], m["building_label"], m["collection"], "native", m["relpath"])
# (2) migrated copies of corpus models and GNI files
for r in mig:
    if r.get("status") != "ok": continue
    src = r["src"]
    if src in v2:
        m = v2[src]; bid, label, coll = m["building_id"], m["building_label"], m["collection"]; fg = None
    else:
        rel = src.replace("data/corpus/gni/", ""); bid = r["building"]; label = Path(src).stem; coll = "gni"
        fg = "gni_fundamentals" if "2025_BIMfundamentals" in src else None
    for step in r["steps"]:
        target = step["target"]
        out_rel = f"runs_local/corpus_v10/migrated/{r['key']}__{target}.ifc"
        if (ROOT/out_rel).exists():
            add(f"{r['key']}m{target[3:]}", out_rel, bid, label, coll, "migrated", src, fg)
# (3) GNI originals (admitted files only)
for rel, c in sorted(gni_con.items()):
    if c.get("bimedit_shared", 1) != 0 or not gni_inv.get(rel, {}).get("parse_ok"): continue
    key = "G" + Path(rel).stem.replace("model_", "").replace("_", "")
    add(key, f"data/corpus/gni/{rel}", "GNI-" + Path(rel).stem, Path(rel).stem, "gni", "native", f"data/corpus/gni/{rel}",
        "gni_fundamentals" if "2025_BIMfundamentals" in rel else None)

def write(name, ents):
    by_b = collections.defaultdict(list)
    for e in ents: by_b[e["building_id"]].append(e["key"])
    pool = {"pool_version": "pool-v10", "thresholds": pool2["thresholds"], "excluded_buildings": sorted(held_out),
            "n_models": len(ents), "n_buildings": len(by_b), "n_models_in_run": sum(e["in_run"] for e in ents),
            "n_buildings_in_run": len({e["building_id"] for e in ents if e["in_run"]}),
            "buildings": {b: sorted(k) for b, k in sorted(by_b.items())}, "models": ents}
    json.dump(pool, open(OUT/f"pool_v10_{name}.json", "w"), indent=1)
    c = collections.Counter((e["schema"], e["origin"]) for e in ents)
    print(name, len(ents), "models", len(by_b), "buildings", dict(c), "products", sum(e["n_products"] for e in ents), flush=True)
write("all", entries)
for schema in ("IFC2X3", "IFC4", "IFC4X3"):
    write(schema, [e for e in entries if e["schema"] == schema])
