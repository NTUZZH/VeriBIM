"""For every flagged task: where the offending element sits inside the band (z, a, n), and for
bench tasks a second check on the stored gold (gunzipped into tmp_gold/, deleted after)."""
import json, sys, os, gzip, shutil, numpy as np, ifcopenshell
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clearance_check as cc
k, n = map(int, sys.argv[1].split('/'))
recs = {}
for s in ['bench_v4', 'pool', 'val500', 'val100']:
    for l in open(f'{HERE}/inscope_{s}.jsonl'):
        r = json.loads(l); recs[(s, r['task_id'])] = r
items = [(s, json.loads(l)) for s in ['bench_v4', 'val500', 'val100', 'pool'] for l in open(f'{HERE}/flagged_{s}.jsonl')]
items = items[k::n]
tmp = f'{HERE}/tmp_gold'; os.makedirs(tmp, exist_ok=True)
def clipped(tl, A0, A1, Z0, Z1):
    out = []
    for tri in tl:
        poly = [tri[0], tri[1], tri[2]]
        for ax, v, g in ((0, A0, True), (0, A1, False), (2, Z0, True), (2, Z1, False)):
            poly = cc._clip(poly, ax, v, g)
            if len(poly) < 3: break
        if len(poly) >= 3: out += poly
    return np.array(out)
out = open(f'{HERE}/diag_flagged_{k}.jsonl', 'w')
for s, fr in items:
    rec = recs[(s, fr['task_id'])]
    m = ifcopenshell.open(cc.ROOT + rec['input_ifc'])
    ns = {}; exec(compile(rec['gold_script'], 'g', 'exec'), ns); ns['apply_edit'](m)
    row = {'set': s, 'task_id': fr['task_id']}
    for f in fr['fillings']:
        if not f['flag']: continue
        fe = m.by_guid(f['guid']); h, op = cc.host_of(fe); ht = cc.mesh(h); frm = cc.host_frame(m, h, ht)
        a0, a1 = f['band']['a']; z0, z1 = f['band']['z']
        o = m.by_guid(f['offending']['guid'])
        pts = clipped(cc.to_local(cc.mesh(o), frm), a0 + cc.TOL_A, a1 - cc.TOL_A, z0 + cc.TOL_Z_BOTTOM, z1 - cc.TOL_Z_TOP)
        row.update(filling=f['guid'], width=round(a1 - a0, 3), height=round(z1 - z0, 3),
                   part_z_above_bottom=[round(pts[:, 2].min() - z0, 3), round(pts[:, 2].max() - z0, 3)],
                   part_a_from_jamb=[round(pts[:, 0].min() - a0, 3), round(pts[:, 0].max() - a0, 3)],
                   part_n=[round(pts[:, 1].min(), 3), round(pts[:, 1].max(), 3)], host_n=f['band']['host_n'],
                   host_name=h.Name, storey_host_z=None)
        break
    del m
    if s == 'bench_v4':
        gz = cc.ROOT + 'runs_local/bench_v4/models/' + fr['task_id'] + '.ifc.gz'
        dst = f'{tmp}/{fr["task_id"]}.ifc'
        with gzip.open(gz, 'rb') as a, open(dst, 'wb') as b:
            shutil.copyfileobj(a, b)
        try:
            r2 = cc.check_task(rec, gold_path=dst)
            row['stored_gold_check'] = {'flag': r2['flag'], 'min_d': r2['min_d']}
        finally:
            os.remove(dst)
    out.write(json.dumps(row, default=str) + '\n'); out.flush()
print('done', k, len(items))
