"""Schema validation (ifcopenshell.validate, attribute types and cardinalities; EXPRESS where-rules off) of every
migrated file and every native source in the v10 and benchmark pools. One line per file in validate_schema.jsonl."""
import os, sys, json, glob, re, time, logging, collections
os.environ["OMP_NUM_THREADS"]="1"
import ifcopenshell, ifcopenshell.validate
ROOT="."; OUT=f"{ROOT}/runs_local/corpus_v10/validate_schema.jsonl"
class C(logging.Handler):
    def __init__(s): super().__init__(); s.recs=[]
    def emit(s, r): s.recs.append(r)
paths=set()
for p in glob.glob(f"{ROOT}/runs_local/corpus_v10/pool_v10_*.json")+glob.glob(f"{ROOT}/runs_local/corpus_v10/pool_bench_v10_*.json"):
    d=json.load(open(p))
    if "models" not in d: continue
    for m in d["models"]: paths.add(m["relpath"])
done=set()
if os.path.exists(OUT): done={json.loads(l)["relpath"] for l in open(OUT)}
def one(rel):
    t=time.time(); rec={"relpath":rel,"bytes":os.path.getsize(f"{ROOT}/{rel}")}
    try:
        f=ifcopenshell.open(f"{ROOT}/{rel}"); rec["schema"]=f.schema_identifier
        h=C(); lg=logging.getLogger("validate_one"); lg.handlers=[h]; lg.propagate=False; lg.setLevel(logging.DEBUG)
        ifcopenshell.validate.validate(f, lg, express_rules=False)
        kinds=collections.Counter()
        for r in h.recs:
            a=r.args if isinstance(r.args, tuple) else ()
            ent=re.search(r"=(Ifc\w+)\(", str(a[0])) if a else None
            att=re.search(r"attribute (\w+)", str(a[-1])) if a else None
            kinds[f"{ent.group(1) if ent else '?'}.{att.group(1) if att else '?'}:{r.msg.strip().splitlines()[-1][:40]}"]+=1
        rec["n_issues"]=len(h.recs); rec["kinds"]=dict(kinds.most_common(10))
    except Exception as ex:
        rec["error"]=repr(ex)[:200]
    rec["seconds"]=round(time.time()-t,1)
    return rec

def avail_gb():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"): return int(l.split()[1])/1e6

if __name__ == "__main__":
    import multiprocessing as mp
    ctx=mp.get_context("spawn")
    for rel in sorted(paths, key=lambda r: os.path.getsize(f"{ROOT}/{r}")):
        if rel in done: continue
        while avail_gb() < 12: time.sleep(60)
        with ctx.Pool(1, maxtasksperchild=1) as pool:   # one fresh process per file: nothing survives between files
            rec = pool.apply(one, (rel,))
        open(OUT,"a").write(json.dumps(rec)+"\n"); print(rel[-60:], rec.get("n_issues"), rec.get("seconds"), flush=True)
    open(f"{ROOT}/runs_local/corpus_v10/VALIDATE_SCHEMA_DONE","w").close()
