"""Pre-specified equivalence test (written 2026-10-08 before the documented arm's 216-task rows existed).

Primary: on the 216 tasks of the 324-task subset outside the 108-task subset, the mean paired difference in completion,
VeriBIM-9B (local324_lib_all/per_task_grpo_v10b_c10.jsonl) minus Claude Sonnet 5.5 with the documented library
(hosted324rest_informed_all), with a 90 % percentile paired bootstrap over tasks (10,000 resamples, seed 20260929,
lower = sorted[500], upper = sorted[9499]); equivalence at margin 5 percentage points iff the 90 % interval lies inside
(-0.05, +0.05). Secondary: the same on all 324 tasks (the 108-task documented rows added), the building-level cluster
bootstrap, the fully specified / under-specified split and threshold 0.98. Read-only on every input.
"""
import json, sys
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
import numpy as np
import common as C

MARGIN = 0.05
E = 'analysis/revision/equivalence'
T, S108, S324 = C.load_tasks()
REST = sorted(set(S324) - set(S108))
assert REST == json.load(open(f'{C.BENCH}/subset_324_rest216.v4c.json')) and len(REST) == 216
ours = C.read_rows(f'{C.RES}/local324_lib_all/per_task_grpo_v10b_c10.jsonl', expect=S324)
inf = C.read_rows(f'{C.RES}/hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl', expect=REST)
inf.update(C.read_rows(f'{C.RES}/hosted108_informed_all/per_task_claude-sonnet-5-5.jsonl', expect=S108))
lib = C.read_rows(f'{C.RES}/hosted324_lib_all/per_task_claude-sonnet-5-5.jsonl', expect=S324)


def boot_ci(vals):
    v = np.asarray(vals, float)
    rng = np.random.default_rng(C.SEED)
    m = np.empty(C.R)
    for s in range(0, C.R, 250):
        ix = rng.integers(0, len(v), size=(min(250, C.R - s), len(v)))
        m[s:s + len(ix)] = v[ix].mean(1)
    m.sort()
    return {'point': float(v.mean()), 'ci90': [float(m[int(0.05 * C.R)]), float(m[int(0.95 * C.R) - 1])],
            'ci95': [float(m[int(0.025 * C.R)]), float(m[int(0.975 * C.R) - 1])]}


def cluster_ci(vals, ids):
    v = np.asarray(vals, float)
    c = [T[t]['building_id'] for t in ids]
    B = sorted(set(c)); bi = {b: i for i, b in enumerate(B)}
    s, n = np.zeros(len(B)), np.zeros(len(B))
    for x, cc in zip(v, c):
        s[bi[cc]] += x; n[bi[cc]] += 1
    rng = np.random.default_rng(C.SEED)
    idx = rng.integers(0, len(B), size=(C.R, len(B)))
    st = np.sort(s[idx].sum(1) / n[idx].sum(1))
    return {'point': float(v.mean()), 'ci90': [float(st[int(0.05 * C.R)]), float(st[int(0.95 * C.R) - 1])],
            'ci95': [float(st[int(0.025 * C.R)]), float(st[int(0.975 * C.R) - 1])], 'buildings': len(B)}


def block(ids, a, b, thr=0.9):
    d = [C.done_at(a[t], thr) - C.done_at(b[t], thr) for t in ids]
    out = {'n': len(ids), 'a_done': int(sum(C.done_at(a[t], thr) for t in ids)), 'b_done': int(sum(C.done_at(b[t], thr) for t in ids)),
           'a_only': int(sum(1 for x in d if x > 0)), 'b_only': int(sum(1 for x in d if x < 0)),
           'task': boot_ci(d), 'building': cluster_ci(d, ids)}
    out['a_comp'], out['b_comp'] = out['a_done'] / len(ids), out['b_done'] / len(ids)
    lo, hi = out['task']['ci90']
    out['equivalent_at_margin'] = bool(-MARGIN < lo and hi < MARGIN)
    return out


under = lambda ids: [t for t in ids if T[t]['clarification']]
full = lambda ids: [t for t in ids if not T[t]['clarification']]
R = {'margin': MARGIN, 'primary_216': block(REST, ours, inf)}
R['secondary'] = {
    '324_all': block(sorted(S324), ours, inf),
    '216_fully_specified': block(full(REST), ours, inf), '216_under_specified': block(under(REST), ours, inf),
    '324_fully_specified': block(full(sorted(S324)), ours, inf), '324_under_specified': block(under(sorted(S324)), ours, inf),
    '216_thr098': block(REST, ours, inf, 0.98), '324_thr098': block(sorted(S324), ours, inf, 0.98),
    'documented_minus_library_324': block(sorted(S324), inf, lib),
    'ours_minus_library_324': block(sorted(S324), ours, lib),
}
for v in ('IFC2X3', 'IFC4', 'IFC4X3'):
    R['secondary'][f'216_{v}'] = block([t for t in REST if T[t]['ifc_version'] == v], ours, inf)
rows = [inf[t] for t in REST]
R['documented_216_run'] = {'mean_rounds': float(np.mean([r.get('tool_rounds') or 0 for r in rows])),
                           'stops': {k: sum(1 for r in rows if r.get('stop_reason') == k) for k in sorted({r.get('stop_reason') for r in rows})},
                           'mean_final': float(np.mean([r.get('final') or 0 for r in rows]))}
json.dump(R, open(f'{E}/equiv_216.json', 'w'), indent=1)
p = R['primary_216']
print(f"PRIMARY 216: VeriBIM-9B {p['a_done']}/216 = {p['a_comp']:.3f}; documented {p['b_done']}/216 = {p['b_comp']:.3f}; "
      f"diff {p['task']['point']:+.3f}, 90% [{p['task']['ci90'][0]:+.3f}, {p['task']['ci90'][1]:+.3f}], "
      f"95% [{p['task']['ci95'][0]:+.3f}, {p['task']['ci95'][1]:+.3f}]; equivalent at 5 points: {p['equivalent_at_margin']}")
for k, b in R['secondary'].items():
    print(f"{k:30s} a {b['a_done']}/{b['n']} b {b['b_done']}/{b['n']} diff {b['task']['point']:+.3f} 90% [{b['task']['ci90'][0]:+.3f},{b['task']['ci90'][1]:+.3f}] "
          f"95% [{b['task']['ci95'][0]:+.3f},{b['task']['ci95'][1]:+.3f}] bld95 [{b['building']['ci95'][0]:+.3f},{b['building']['ci95'][1]:+.3f}] "
          f"a_only {b['a_only']} b_only {b['b_only']} eq {b['equivalent_at_margin']}")
print('documented run', R['documented_216_run'])
