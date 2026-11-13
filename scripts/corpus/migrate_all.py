"""Migrate every in-run corpus model (pool v2) and every admitted GNI file (bimedit_shared == 0) to IFC4X3,
IFC2X3 sources through IFC4 (the IFC4 intermediate is kept as a training file too). One file at a time, files over
100 MB deferred to a later pass. Writes runs_local/corpus_v10/migrated/<key>__IFC4.ifc / __IFC4X3.ifc and a
manifest line per source in migrated/manifest.jsonl. Resumable."""
import os, sys, json, time, hashlib
from pathlib import Path
os.environ["OMP_NUM_THREADS"]="1"
sys.path.insert(0, "scripts/corpus")
src_code = open("scripts/corpus/probe_migrate.py").read().split("ap=argparse.ArgumentParser()")[0]
ns = {}; exec(compile(src_code, "probe_migrate_lib", "exec"), ns); migrate_one = ns["migrate_one"]
import ifcopenshell
ROOT = Path("."); OUT = ROOT/"runs_local/corpus_v10/migrated"; OUT.mkdir(parents=True, exist_ok=True)
MAN = OUT/"manifest.jsonl"
done = set()
if MAN.exists():
    for l in open(MAN): done.add(json.loads(l)["src"])
jobs = []
pool = json.load(open(ROOT/"data/veribim_tasks_v2/pool.json"))
for m in pool["models"]:
    if m["in_run"]: jobs.append((m["key"], m["relpath"], m["building_id"], "corpus"))
con = {json.loads(l)["relpath"]: json.loads(l) for l in open(ROOT/"data/corpus/gni/contamination.jsonl")}
inv = {json.loads(l)["relpath"]: json.loads(l) for l in open(ROOT/"data/corpus/gni/inventory.jsonl")}
for rel, c in sorted(con.items()):
    if c.get("bimedit_shared", 1) == 0 and inv.get(rel, {}).get("parse_ok"):
        key = "G" + Path(rel).stem.replace("model_", "").replace("_", "")
        jobs.append((key, f"data/corpus/gni/{rel}", "GNI-" + Path(rel).stem, "gni"))
print("jobs", len(jobs), flush=True)
for key, rel, bld, coll in jobs:
    if rel in done: continue
    src = ROOT/rel; size = src.stat().st_size
    rec = {"key": key, "src": rel, "building": bld, "collection": coll, "bytes": size}
    if size > 100_000_000:
        rec["status"] = "deferred_over_100MB"; open(MAN, "a").write(json.dumps(rec)+"\n"); print(key, "deferred", flush=True); continue
    t = time.perf_counter()
    try:
        f = ifcopenshell.open(str(src)); schema = f.schema; del f
        rec["schema"] = schema; cur = str(src); reps = []
        if schema == "IFC2X3":
            d4 = OUT/f"{key}__IFC4.ifc"; reps.append(migrate_one(cur, "IFC4", d4)); cur = str(d4)
        elif not schema.startswith("IFC4"):
            rec["status"] = f"unsupported_{schema}"; open(MAN, "a").write(json.dumps(rec)+"\n"); continue
        if schema == "IFC4X3":
            rec["status"] = "already_ifc4x3"
        else:
            d43 = OUT/f"{key}__IFC4X3.ifc"; reps.append(migrate_one(cur, "IFC4X3", d43)); rec["status"] = "ok"
        rec["steps"] = [{k: r[k] for k in ("target", "seconds", "n_errors", "errors", "dropped_attributes", "bytes")} for r in reps]
        rec["products"] = [r["counts"]["IfcProduct"] for r in reps]
    except Exception as ex:
        rec["status"] = "failed"; rec["error"] = repr(ex)[:300]
    rec["seconds"] = round(time.perf_counter()-t, 1)
    open(MAN, "a").write(json.dumps(rec)+"\n"); print(key, rec["status"], rec.get("seconds"), rec.get("products"), flush=True)
open(OUT/"MIGRATE_ALL_DONE", "w").close(); print("DONE", flush=True)
