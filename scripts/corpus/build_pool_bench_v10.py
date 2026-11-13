"""Benchmark pools for the mixed-version benchmark: the ten E2 held-out corpus buildings and the two
held-out GNI projects, each in every version it exists in: the native file, and the migrated copies under
runs_local/corpus_v10/heldout_4x3 (corpus) or runs_local/corpus_v10/migrated (GNI). One pool per version,
all entries in_run (the benchmark generator draws only from them), origin native/migrated on each."""
import os, sys, json, hashlib, time, collections
from pathlib import Path
os.environ["OMP_NUM_THREADS"]="1"
import ifcopenshell
ROOT=Path("."); OUT=ROOT/"runs_local/corpus_v10"
sys.path.insert(0, str(ROOT/"code")); from modifc_gen.pool import size_tier
pool2=json.load(open(ROOT/"data/veribim_tasks_v2/pool.json")); v2={m["relpath"]:m for m in pool2["models"]}
E2={"BLD003","BLD018","BLD029","BLD031","BLD035","BLD038","BLD040","BLD042","BLD044","BLD045"}
cache_path=OUT/"pool_v10_scan_cache.json"; cache=json.load(open(cache_path)) if cache_path.exists() else {}
FAM={"wall":("IfcWall","IfcWallStandardCase"),"slab":("IfcSlab",),"space":("IfcSpace",),"door":("IfcDoor",),"window":("IfcWindow",),"column":("IfcColumn",)}
def scan(relpath):
    p=ROOT/relpath; key=f"{relpath}|{p.stat().st_size}"
    if key in cache: return cache[key]
    t=time.perf_counter(); f=ifcopenshell.open(str(p)); counts={}
    for fam,classes in FAM.items():
        n=0
        for c in classes:
            try: n+=len(f.by_type(c, include_subtypes=False))
            except Exception: pass
        counts[fam]=n
    apps=f.by_type("IfcApplication")
    rec={"sha256":hashlib.sha256(open(p,"rb").read()).hexdigest(),"schema":f.schema,"n_products":len(f.by_type("IfcProduct")),
         "family_counts":counts,"bytes":p.stat().st_size,"seconds":round(time.perf_counter()-t,1),"exporter":(apps[0].ApplicationFullName if apps else None)}
    del f; cache[key]=rec; json.dump(cache, open(cache_path,"w")); return rec
entries=[]
def add(key, relpath, bid, label, coll, origin, src):
    s=scan(relpath)
    entries.append({"key":key,"relpath":relpath,"sha256":s["sha256"],"building_id":bid,"building_label":label,"collection":coll,
        "schema":s["schema"],"bytes":s["bytes"],"size_tier":size_tier(s["bytes"]),"n_products":s["n_products"],"family_counts":s["family_counts"],
        "n_families":sum(1 for v in s["family_counts"].values() if v>0),"exporter":s["exporter"],"project_name":None,"in_run":True,"held_out":False,
        "origin":origin,"source_relpath":src}); print(key, s["schema"], s["n_products"], origin, flush=True)
# E2 corpus held-out buildings: native + migrated copies in heldout_4x3
e2_sources=[]
for l in open(ROOT/"runs_local/wave_v2/e2_v3/e2_tasks.jsonl"):
    t=json.loads(l); p=t["input_ifc"]
    if p not in e2_sources: e2_sources.append(p)
for src in e2_sources:
    m=v2.get(src); bid=m["building_id"] if m else "?"; label=m["building_label"] if m else Path(src).stem; coll=m["collection"] if m else "?"
    key=m["key"] if m else "X"+Path(src).stem[:6]
    add(key, src, bid, label, coll, "native", src)
    stem=Path(src).stem.replace(" ","_")
    for target in ("IFC4","IFC4X3"):
        rel=f"runs_local/corpus_v10/heldout_4x3/{stem}__{target}.ifc"
        if (ROOT/rel).exists(): add(f"{key}m{target[3:]}", rel, bid, label, coll, "migrated", src)
# GNI held-out projects 7 and 8: native + migrated copies
mig=[json.loads(l) for l in open(OUT/"migrated/manifest.jsonl")]
for r in mig:
    if r["collection"]!="gni" or not any(f"model_{n}_" in r["src"] for n in ("7","8")): continue
    bid="GNI-project_"+Path(r["src"]).stem.split("_")[1]; label=Path(r["src"]).stem
    add(r["key"], r["src"], bid, label, "gni", "native", r["src"])
    for step in r.get("steps",[]):
        rel=f"runs_local/corpus_v10/migrated/{r['key']}__{step['target']}.ifc"
        if (ROOT/rel).exists(): add(f"{r['key']}m{step['target'][3:]}", rel, bid, label, "gni", "migrated", r["src"])
def write(name, ents):
    by=collections.defaultdict(list)
    for e in ents: by[e["building_id"]].append(e["key"])
    pool={"pool_version":"pool-bench-v10","thresholds":pool2["thresholds"],"excluded_buildings":[],"n_models":len(ents),"n_buildings":len(by),
          "n_models_in_run":len(ents),"n_buildings_in_run":len(by),"buildings":{b:sorted(k) for b,k in sorted(by.items())},"models":ents}
    json.dump(pool, open(OUT/f"pool_bench_v10_{name}.json","w"), indent=1)
    print(name, len(ents), "models", len(by), "buildings", dict(collections.Counter((e["schema"],e["origin"]) for e in ents)), flush=True)
write("all", entries)
for s in ("IFC2X3","IFC4","IFC4X3"): write(s, [e for e in entries if e["schema"]==s])
