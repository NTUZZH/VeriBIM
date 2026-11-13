"""Second pass of migrate_all.py: the sources it deferred for size (>100 MB). One file at a time, only when at
least 12 GB of host memory is available; records to migrated/manifest_large.jsonl with peak RSS per file."""
import os, sys, json, time, resource, subprocess
from pathlib import Path
os.environ["OMP_NUM_THREADS"]="1"
ROOT=Path("."); OUT=ROOT/"runs_local/corpus_v10/migrated"
src_code=open(ROOT/"scripts/corpus/probe_migrate.py").read().split("ap=argparse.ArgumentParser()")[0]
ns={}; exec(compile(src_code,"probe_migrate_lib","exec"), ns); migrate_one=ns["migrate_one"]
import ifcopenshell
def avail_gb():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"): return int(l.split()[1])/1e6
deferred=[json.loads(l) for l in open(OUT/"manifest.jsonl") if "deferred" in json.loads(l)["status"]]
done={json.loads(l)["src"] for l in open(OUT/"manifest_large.jsonl")} if (OUT/"manifest_large.jsonl").exists() else set()
deferred.sort(key=lambda r:r["bytes"])
for r in deferred:
    if r["src"] in done: continue
    while avail_gb()<12:
        print(time.strftime("%H:%M"), "waiting for memory", round(avail_gb(),1), flush=True); time.sleep(120)
    if time.strftime("%H:%M")>"20:15":
        print("past 20:15, stopping for the day", flush=True); break
    rec=dict(r); rec.pop("status"); t=time.perf_counter()
    try:
        f=ifcopenshell.open(str(ROOT/r["src"])); schema=f.schema; del f
        rec["schema"]=schema; cur=str(ROOT/r["src"]); reps=[]
        if schema=="IFC2X3":
            d4=OUT/f"{r['key']}__IFC4.ifc"; reps.append(migrate_one(cur,"IFC4",d4)); cur=str(d4)
        d43=OUT/f"{r['key']}__IFC4X3.ifc"; reps.append(migrate_one(cur,"IFC4X3",d43)); rec["status"]="ok"
        rec["steps"]=[{k:x[k] for k in ("target","seconds","n_errors","errors","dropped_attributes","bytes")} for x in reps]
        rec["products"]=[x["counts"]["IfcProduct"] for x in reps]
    except Exception as ex:
        rec["status"]="failed"; rec["error"]=repr(ex)[:300]
    rec["seconds"]=round(time.perf_counter()-t,1); rec["peak_rss_gb"]=round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e6,1)
    open(OUT/"manifest_large.jsonl","a").write(json.dumps(rec)+"\n")
    print(r["key"], rec["status"], rec["seconds"], rec.get("products"), "peak", rec["peak_rss_gb"], "GB", flush=True)
open(OUT/"MIGRATE_LARGE_DONE","w").close(); print("DONE", flush=True)
