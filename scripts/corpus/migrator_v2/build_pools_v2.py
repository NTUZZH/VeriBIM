"""Pools v2: copies of the v10 and benchmark pools whose migrated entries point at the migrator-v2 files
(relpath, sha256, bytes, n_products from the new file; key "migrator": "v2"). Native entries are unchanged.
Refuses to write when a migrated entry has no finished v2 file."""
import os, json, hashlib, copy, collections
ROOT = "."; C10 = f"{ROOT}/runs_local/corpus_v10"; HERE = f"{C10}/migrator_v2"
POOLS = ["pool_v10_IFC4.json", "pool_v10_IFC4X3.json", "pool_v10_IFC4_plus.json", "pool_v10_IFC4X3_plus.json",
         "pool_bench_v10_IFC4.json", "pool_bench_v10_IFC4X3.json", "pool_v10_IFC2X3.json", "pool_v10_all.json",
         "pool_bench_v10_all.json", "pool_bench_v10_IFC2X3.json"]


def sha256(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


mig = {}
for l in open(f"{HERE}/migrate_v2.jsonl"):
    r = json.loads(l); mig[r["old"]] = r
cache = {}
summary = collections.Counter()
for fn in POOLS:
    d = json.load(open(f"{C10}/{fn}")); out = copy.deepcopy(d)
    for m in out["models"]:
        if m.get("origin") != "migrated":
            summary[(fn, "native")] += 1
            continue
        r = mig.get(m["relpath"])
        assert r is not None, f"{fn}: no v2 file for {m['relpath']}"
        new = r["new"]; p = f"{ROOT}/{new}"
        assert os.path.exists(p) and os.path.basename(new) == os.path.basename(m["relpath"]), new
        if new not in cache:
            cache[new] = (sha256(p), os.path.getsize(p))
        m["relpath"] = new; m["sha256"], m["bytes"] = cache[new]
        m["n_products"] = r["counts"]["IfcProduct"]; m["migrator"] = "v2"
        summary[(fn, "migrated")] += 1
    json.dump(out, open(f"{HERE}/{fn}", "w"), indent=1)
for k, v in sorted(summary.items()):
    print(k, v)
