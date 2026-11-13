"""Run the fixed generator rule and the fixed library rule on every audited task.

Usage: run_fixed.py <audit.jsonl> <out.jsonl>
One output row per audit row: the generator's GUID list, the library's GUID or
its LookupError, and the directions the rule read.
"""
import gc, json, resource, sys, time
import fixload
from fixload import geom, anchors, Scene, FAMILY_CLASS
import numpy as np

ROOT = './'
rows = [json.loads(l) for l in open(sys.argv[1])]
order = sorted(range(len(rows)), key=lambda i: rows[i]['input_ifc'])
out = open(sys.argv[2], 'w')
cur, sc, t0 = None, None, time.time()
results = {}
for i in order:
    r = rows[i]
    src = ROOT + r['input_ifc']
    if src != cur:
        geom._READ.clear(); sc = None; gc.collect()
        sc = Scene(src); cur = src
    ref = sc.by_guid(r['reference'][0]); sp = sc.by_guid(r['space'][0])
    params = {'reference_guid': r['reference'][0], 'space_guid': r['space'][0],
              'axis': r['axis'], 'min_offset': 0.25}
    A = anchors.Anchor(kind='opposite', family=r['family'], phrase=r['phrase'], params=params)
    rec = {'file': r['file'], 'task_id': r['task_id'], 'class': r['class']}
    rec['gen'] = A.resolve(sc)
    try:
        e = geom.find_opposite(ref, FAMILY_CLASS[r['family']], sp)
        rec['lib'] = e.GlobalId
    except LookupError as ex:
        rec['lib'] = None; rec['lib_error'] = str(ex)[:400]
    d = geom.plan_direction(ref)
    rec['ref_dir'] = None if d is None else [round(float(x), 4) for x in d]
    rec['ref_axis_dir'] = (lambda a: None if a is None else [round(float(x), 4) for x in a])(
        geom._axis_direction(geom.host_wall_of(ref) or ref) if (ref.is_a('IfcDoor') or ref.is_a('IfcWindow')) else geom._axis_direction(ref) if ref.is_a('IfcWall') else None)
    b = geom._body_direction(geom.host_wall_of(ref) or ref if (ref.is_a('IfcDoor') or ref.is_a('IfcWindow')) else ref)
    rec['ref_body_dir'] = None if b is None else [round(float(x), 4) for x in b]
    # full ranking, for the report
    mem = [sc.by_guid(g) for g in sc.space_elements(sp)]
    mem = [m for m in mem if m is not None and sc.family_of(m) == r['family']]
    mid = sc.centre(sp); o = sc.centre(ref)
    if d is not None and mid is not None and o is not None:
        n = np.array([-d[1], d[0]]); s = float(np.dot((o - mid)[:2], n))
        if s < 0: n = -n
        rec['ref_side'] = round(abs(s), 3)
        cand = []
        for m in mem:
            if m.GlobalId == ref.GlobalId: continue
            p = sc.centre(m); dm = anchors._plan_direction(sc, m)
            if p is None or dm is None: continue
            cand.append([m.GlobalId, round(abs(float(np.dot(dm, d))), 3), round(float(np.dot((p - mid)[:2], n)), 3)])
        rec['candidates'] = sorted(cand, key=lambda c: c[2])
    out.write(json.dumps(rec) + '\n'); out.flush()
print(len(rows), 'rows', round(time.time() - t0, 1), 's; maxrss MB',
      resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
