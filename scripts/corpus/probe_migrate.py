"""Probe: migrate one corpus building to IFC4 and IFC4X3 with ifcopenshell's Migrator,
then ask the generator which cells it can host on the migrated files and produce a few
verified tasks (gold script, checks, self-score) on each. Nothing under data/ is written.

  python probe_migrate.py migrate B13            # writes probe/B13_IFC4.ifc, probe/B13_IFC4X3.ifc
  python probe_migrate.py probe B13 IFC4X3 --n 3 # generator probe + up to n tasks per live cell
"""
import argparse, json, os, random, sys, time, collections
from pathlib import Path
for k in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","NUMEXPR_NUM_THREADS"): os.environ[k]="1"
ROOT = Path("."); OUT = ROOT/"runs_local/corpus_v10/probe"
sys.path.insert(0, str(ROOT/"code"))
import ifcopenshell
from ifcopenshell.util.schema import Migrator as _Migrator

CLASS_4_TO_4X3 = {"IfcWindowStyle": "IfcWindowType", "IfcDoorStyle": "IfcDoorType",
                  "IfcWallStandardCase": "IfcWall"}
# IFC2X3 entities absent from IFC4 that ifcopenshell's class_2x3_to_4.json does not map (seen on Svaleveien).
CLASS_2X3_TO_4_EXTRA = {"IfcRelOccupiesSpaces": "IfcRelAssignsToActor"}

class Migrator(_Migrator):
    """ifcopenshell's Migrator plus the IFC4 -> IFC4X3 class renames it lacks and a tolerant
    attribute step (an attribute whose value has no IFC4X3 equivalent is left unset)."""
    dropped = None
    def migrate_class(self, element, new_file):
        ifc_class = element.is_a()
        if new_file.schema == "IFC4X3" and ifc_class in CLASS_4_TO_4X3:
            return new_file.create_entity(CLASS_4_TO_4X3[ifc_class])
        if new_file.schema == "IFC4" and ifc_class in CLASS_2X3_TO_4_EXTRA:
            return new_file.create_entity(CLASS_2X3_TO_4_EXTRA[ifc_class])
        return super().migrate_class(element, new_file)
    def migrate_attribute(self, attribute, element, new_file, new_element, new_element_schema):
        try:
            super().migrate_attribute(attribute, element, new_file, new_element, new_element_schema)
        except Exception as ex:
            if self.dropped is None: self.dropped = collections.Counter()
            self.dropped[f"{new_element.is_a()}.{attribute.name()}:{type(ex).__name__}"] += 1
            if attribute.optional():
                return
            if attribute.name() in ("PredefinedType", "PartitioningType", "OperationType"):
                idx = [a.name() for a in new_element_schema.all_attributes()].index(attribute.name())
                new_element[idx] = "NOTDEFINED"; return
            raise

def pool_model(key):
    p = json.load(open(ROOT/"data/veribim_tasks_v2/pool.json"))
    return next(m for m in p["models"] if m["key"]==key)

def migrate_one(src, target, dst):
    t=time.perf_counter()
    old = ifcopenshell.open(src)
    new = ifcopenshell.file(schema=target)
    mig = Migrator()
    mig.preprocess(old, new)
    n=0; errs=collections.Counter()
    for e in old:
        try: mig.migrate(e, new); n+=1
        except Exception as ex: errs[f"{e.is_a()}:{type(ex).__name__}:{str(ex)[:60]}"]+=1
    new.write(str(dst))
    chk = ifcopenshell.open(str(dst))
    fam = {c: len(chk.by_type(c)) for c in ("IfcWall","IfcWallStandardCase","IfcSlab","IfcSpace","IfcDoor","IfcWindow","IfcColumn","IfcBuildingStorey","IfcProduct")}
    return {"src":src,"target":target,"dst":str(dst),"seconds":round(time.perf_counter()-t,1),"migrated":n,
            "errors":dict(errs.most_common(10)),"dropped_attributes":dict((mig.dropped or collections.Counter()).most_common(12)),"n_errors":sum(errs.values()),"schema_out":chk.schema,"counts":fam,
            "bytes":os.path.getsize(dst)}

def cmd_migrate(a):
    m = pool_model(a.key); src = str(ROOT/m["relpath"]); rep=[]
    old = ifcopenshell.open(src)
    rep.append({"src":src,"schema":old.schema,"counts":{c: len(old.by_type(c)) for c in ("IfcWall","IfcWallStandardCase","IfcSlab","IfcSpace","IfcDoor","IfcWindow","IfcColumn","IfcBuildingStorey","IfcProduct")}})
    d4 = OUT/f"{a.key}_IFC4.ifc"; rep.append(migrate_one(src,"IFC4",d4))
    d43 = OUT/f"{a.key}_IFC4X3.ifc"; rep.append(migrate_one(str(d4),"IFC4X3",d43))
    json.dump(rep, open(OUT/f"{a.key}_migrate.json","w"), indent=1); print(json.dumps(rep, indent=1))

def cmd_probe(a):
    from modifc_gen import generate, chains, run as grun
    from modifc_gen.corpus import ModelRef
    from modifc_gen.scene import Scene
    from modifc_score.model_cache import MeshCache, ModelCache
    if getattr(a, "path", None):
        relpath = os.path.relpath(a.path, ROOT); path = ROOT/relpath
        a.key = Path(a.path).stem.replace(" ", "_"); a.schema = "FILE"
        m = {"collection": "file", "n_products": 0, "family_counts": {}}
    else:
        m = pool_model(a.key)
        relpath = f"runs_local/corpus_v10/probe/{a.key}_{a.schema}.ifc" if a.schema!="SRC" else m["relpath"]
        path = ROOT/relpath
    import hashlib; sha = hashlib.sha256(open(path,"rb").read()).hexdigest()
    ref = ModelRef(key=f"{a.key}{a.schema}", relpath=relpath, sha256=sha, collection=m["collection"],
                   schema=a.schema, bytes=os.path.getsize(path), n_products=m["n_products"], counts=m["family_counts"])
    t=time.perf_counter(); scene = Scene(str(path), relpath, sha); ts=time.perf_counter()-t
    print(f"scene ok schema={scene.schema} products={scene.n_products} storeys={len(scene.storeys)} rel={scene.n_relations} unit={scene.unit_scale} {ts:.1f}s")
    rng = random.Random(a.seed); live=[]; dead=collections.Counter()
    for c,o,f in grun.CELLS:
        name=generate.cell_id(c,o,f); tid=generate.task_id_for(ref.key,c,o,f,0)
        draw, reason = generate.draw_single(scene,c,o,f,tid,rng)
        (live.append((name,(c,o,f),"single")) if draw is not None else dead.update([f"{name}:{reason}"]))
    for c,k in grun.CHAIN_CELLS:
        name=f"{c}/{k}"; tid=generate.chain_task_id(ref.key,c,k,0)
        draw, reason = generate.draw_chain(scene,c,k,tid,rng)
        (live.append((name,(c,k),"chain")) if draw is not None else dead.update([f"{name}:{reason}"]))
    print(f"live cells {len(live)}/{len(grun.CELLS)+len(grun.CHAIN_CELLS)}")
    outdir = OUT/f"tasks_{a.key}_{a.schema}"; scratch = outdir/"_scratch"; scratch.mkdir(parents=True, exist_ok=True)
    models_cache = ModelCache(capacity=3); meshes_cache = MeshCache()
    outcomes=[]; idx=0; accepted=0
    for name, cell, tier in live:
        got=0; tries=0
        while got<a.n and tries<a.n*3:
            tries+=1; idx+=1; seed=a.seed*1000003+idx; rng=random.Random(seed)
            if tier=="single":
                c,o,f=cell; tid=generate.task_id_for(ref.key,c,o,f,idx); draw,reason=generate.draw_single(scene,c,o,f,tid,rng)
            else:
                c,k=cell; tid=generate.chain_task_id(ref.key,c,k,idx); draw,reason=generate.draw_chain(scene,c,k,tid,rng)
            if draw is None: outcomes.append({"cell":name,"stage":"draw","reason":reason}); continue
            oc = generate.produce(scene, ref, tid, draw, ROOT, outdir, scratch, models_cache, meshes_cache, seed, True)
            outcomes.append({"cell":name,"task_id":tid,"stage":oc.stage,"reason":oc.reason,"detail":str(oc.detail)[:300]})
            if oc.stage=="accepted": got+=1; accepted+=1
    stages=collections.Counter((o["stage"],o.get("reason")) for o in outcomes)
    rep={"key":ref.key,"schema":scene.schema,"scene_seconds":round(ts,1),"live_cells":[l[0] for l in live],"dead_cells":dict(dead),
         "attempts":len(outcomes),"accepted":accepted,"stages":{f"{s}|{r}":n for (s,r),n in stages.most_common()},"outcomes":outcomes,
         "seconds":round(time.perf_counter()-t,1)}
    json.dump(rep, open(OUT/f"{a.key}_{a.schema}_probe.json","w"), indent=1)
    print(json.dumps({k:v for k,v in rep.items() if k!="outcomes"}, indent=1))

ap=argparse.ArgumentParser(); sp=ap.add_subparsers(dest="cmd", required=True)
x=sp.add_parser("migrate"); x.add_argument("key"); x.set_defaults(fn=cmd_migrate)
x=sp.add_parser("probefile"); x.add_argument("path"); x.add_argument("--n",type=int,default=2); x.add_argument("--seed",type=int,default=20260926); x.set_defaults(fn=cmd_probe)
x=sp.add_parser("probe"); x.add_argument("key"); x.add_argument("schema"); x.add_argument("--n",type=int,default=2); x.add_argument("--seed",type=int,default=20260926); x.set_defaults(fn=cmd_probe)
a=ap.parse_args(); a.fn(a)
