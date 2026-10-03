"""Calibration of the clearance c on the source buildings' own doors and windows."""
import json, sys, time, collections, resource
import numpy as np, ifcopenshell
sys.path.insert(0, 'scripts/corpus/clearance_fix')
import clearance_check as cc
R = cc.ROOT
BUILDINGS = [
    ('FZK-Haus (EliteCAD)', 'data/corpus/auckland/100_301110FZK-Haus-EliteCAD.ifc'),
    ('Smiley West (ArchiCAD 11)', 'data/corpus/auckland/090_231110AC-11-Smiley-West-04-07-2007.ifc'),
    ('Medical-Dental Clinic, architectural (Revit)', 'data/corpus/bs_community_repo/IFC 2.3.0.1 (IFC 2x3)/Medical-Dental Clinic/Clinic_Architectural.ifc'),
    ('Trapelo existing (Revit 2015)', 'data/corpus/auckland/161_20160125Trapelo - Existing-Trapelo_Design_Intent.ifc'),
    ('GNI model 191 (Revit 2025)', 'data/corpus/gni/IFC-models/2025_BIMfundamentals/model_191.ifc'),
]
rows = []
for label, rel in BUILDINGS:
    t = time.time()
    m = ifcopenshell.open(R + rel)
    idx = cc.source_index(R + rel, m)
    mc = {}
    n = 0
    for cl in cc.FILLING_CLASSES:
        for e in m.by_type(cl):
            r = cc.check_filling(m, e, idx, (), cc.C_DEFAULT, mc)
            r['building'] = label; r['file'] = rel
            rows.append(r); n += 1
    print(label, n, 'fillings', round(time.time() - t, 1), 's', 'index', idx['from'][-30:], flush=True)
    del m, mc
json.dump(rows, open('calibration_fillings.json', 'w'), indent=0, default=str)
ok = [r for r in rows if r['status'] == 'ok']
print('fillings', len(rows), 'measured', len(ok), collections.Counter(r['status'] for r in rows))
grid = [round(x, 2) for x in np.arange(0.05, 1.51, 0.05)]
tab = {}
for c in grid:
    k = sum(1 for r in ok if r['d'] is not None and r['d'] < c)
    tab[c] = (k, round(100 * k / len(ok), 2))
for c in grid:
    per = {}
    for label, _ in BUILDINGS:
        b = [r for r in ok if r['building'] == label]
        per[label[:12]] = f"{sum(1 for r in b if r['d'] is not None and r['d'] < c)}/{len(b)}"
    print(c, tab[c], per)
print('d==0 cases:')
for r in ok:
    if r['d'] is not None and r['d'] < 1.0:
        print(' ', r['building'][:14], r['class'], (r['name'] or '')[:30], r['d'], r['offending'], r['band'])
print('maxrss MB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
