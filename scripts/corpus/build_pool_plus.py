"""pool_v10_{IFC4,IFC4X3}_plus.json = the main-run pools plus the migrated copies of the six large sources
(migrated/manifest_large.jsonl). Used by the top-up rounds only; the main runs keep their pools."""
import json, sys
from pathlib import Path
ROOT=Path("."); OUT=ROOT/"runs_local/corpus_v10"
code=open(ROOT/"scripts/corpus/build_pool_v10.py").read()
head=code.split("entries = []")[0]           # imports, pool v2, scan() and caches, no side effects beyond reading
ns={}; exec(compile(head,"build_pool_v10_head","exec"), ns)
scan=ns["scan"]; v2=ns["v2"]; size_tier=ns["size_tier"]
large=[json.loads(l) for l in open(OUT/"migrated/manifest_large.jsonl") if json.loads(l)["status"]=="ok"]
for target in ("IFC4","IFC4X3"):
    pool=json.load(open(OUT/f"pool_v10_{target}.json")); keys={m["key"] for m in pool["models"]}
    held=set(pool["excluded_buildings"])
    for r in large:
        rel=f"runs_local/corpus_v10/migrated/{r['key']}__{target}.ifc"
        if not (ROOT/rel).exists(): continue
        key=f"{r['key']}m{target[3:]}"
        if key in keys: continue
        if r["src"] in v2: m=v2[r["src"]]; bid,label,coll,fg=m["building_id"],m["building_label"],m["collection"],None
        else: n=Path(r["src"]).stem.split("_")[1]; bid,label,coll,fg=f"GNI-project_{n}",Path(r["src"]).stem,"gni",None
        s=scan(rel)
        pool["models"].append({"key":key,"relpath":rel,"sha256":s["sha256"],"building_id":bid,"building_label":label,"collection":coll,
            "schema":s["schema"],"bytes":s["bytes"],"size_tier":size_tier(s["bytes"]),"n_products":s["n_products"],"family_counts":s["family_counts"],
            "n_families":sum(1 for v in s["family_counts"].values() if v>0),"exporter":s["exporter"],"project_name":None,
            "in_run":bid not in held,"held_out":bid in held,"origin":"migrated","source_relpath":r["src"],"family_group":fg})
        print(target, key, bid, s["n_products"], "held" if bid in held else "in_run", flush=True)
    by={}
    for m in pool["models"]: by.setdefault(m["building_id"],[]).append(m["key"])
    pool["buildings"]={b:sorted(k) for b,k in sorted(by.items())}; pool["n_models"]=len(pool["models"]); pool["n_buildings"]=len(by)
    pool["n_models_in_run"]=sum(m["in_run"] for m in pool["models"]); pool["n_buildings_in_run"]=len({m["building_id"] for m in pool["models"] if m["in_run"]})
    json.dump(pool, open(OUT/f"pool_v10_{target}_plus.json","w"), indent=1)
    print(target, "plus:", pool["n_models_in_run"], "in-run models", pool["n_buildings_in_run"], "buildings", flush=True)
