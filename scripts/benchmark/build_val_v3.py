"""val-500 v3 and val-100 v3: a third per IFC version, stratified within a version by
(operation, category, tier) with proportional quotas and largest remainders; val-100 is drawn from val-500 by the
same rule, so it is a subset. IFC2X3 tasks come from the canonical v2 validation split (IFC2X3 sources only);
IFC4 and IFC4X3 tasks from the v10 validation split (gen/val_tasks_v10.jsonl, filling repair and migrator v2 applied).
No task with an unstated door/window type is admitted."""
import json, random, collections, math
R="."; O=f"{R}/runs_local/stage_a_v10"
SEED=20260927
def affected(t):
    if t.get('edit_kind') not in ('create_filling','replace_filling'): return False
    p=(t.get('edit_params') or {}).get('predefined_type'); return p is not None and p not in (t.get('instruction') or '')
pools={"IFC2X3":[], "IFC4":[], "IFC4X3":[]}
for l in open(f"{R}/runs_local/wave_v2/canonical_v2/tasks_validation.jsonl"):
    t=json.loads(l)
    if (t.get('source_model') or {}).get('schema')=='IFC2X3' and not affected(t):
        t['ifc_version']='IFC2X3'; t['origin']='native'; pools['IFC2X3'].append(t)
for l in open(f"{R}/runs_local/corpus_v10/gen/val_tasks_v10.jsonl"):
    t=json.loads(l)
    if t['ifc_version'] in ('IFC4','IFC4X3') and not affected(t): pools[t['ifc_version']].append(t)
def stratum(t): return (t['operation'], t['category'], t.get('tier','single'))
def draw(items, n, rng):
    by=collections.defaultdict(list)
    for t in items: by[stratum(t)].append(t)
    for k in by: rng.shuffle(by[k])
    total=len(items); raw={k: n*len(v)/total for k,v in by.items()}
    q={k:int(math.floor(x)) for k,x in raw.items()}
    for k in sorted(raw, key=lambda k:-(raw[k]-q[k]))[:n-sum(q.values())]: q[k]+=1
    out=[]
    for k,v in by.items(): out+=v[:q[k]]
    return out
rng=random.Random(SEED)
v500=[]; v100=[]
for ver,n5,n1 in (("IFC2X3",167,34),("IFC4",167,33),("IFC4X3",166,33)):
    a=draw(pools[ver], n5, rng); b=draw(a, n1, rng); v500+=a; v100+=b
    print(ver, "pool", len(pools[ver]), "val500", len(a), "val100", len(b), "origin", dict(collections.Counter(t['origin'] for t in a)))
for name,S in (("500",v500),("100",v100)):
    json.dump([t['task_id'] for t in S], open(f"{O}/val_subset_{name}_v3.json","w"), indent=1)
    with open(f"{O}/val_tasks_{name}_v3.jsonl","w") as f:
        for t in S: f.write(json.dumps(t, ensure_ascii=False)+"\n")
    c=collections.Counter((t['ifc_version'], t['operation']) for t in S); print(name, len(S), dict(sorted(c.items())))
    print(name, "buildings", len({t['building_id'] for t in S}), "cells", len({(t['operation'],t['category']) for t in S}))
ids5={t['task_id'] for t in v500}; assert all(t['task_id'] in ids5 for t in v100); assert len(ids5)==500
