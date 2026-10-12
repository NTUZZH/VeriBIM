#!/usr/bin/env python3
"""Documented commercial setting for every compared model: completion, specification split, strict
threshold, rounds, list cost, and paired differences against VeriBIM-9B and against the documented Sonnet 5.5
run, on the 108-task subset. Conventions of stats/common.py (completion = all axes >= 0.9; task-level percentile
bootstrap 10,000 x seed 20260929, indices [250]/[9749]; building-level cluster bootstrap, same rule).
    python analyze_informed4.py <model id> [...]   -> prints and writes informed4.json next to this script
"""
import json, os, re, ast, sys
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
import numpy as np
import common as C

HERE = os.path.dirname(os.path.abspath(__file__))
RES = f'{C.RES}/hosted108_informed_all'
T, S108, _ = C.load_tasks()
CL = {t: T[t]['building_id'] for t in T}
UNDER = [t for t in S108 if T[t]['clarification']]
FULL = [t for t in S108 if not T[t]['clarification']]
assert len(UNDER) == 11 and len(FULL) == 97
PR = ast.literal_eval(re.search(r'PRICE = (\{.*?\n\})', open(f'{C.BENCH}/hosted_cost.py').read(), re.S).group(1))
CACHE_READ = {'claude-opus-5-5': 0.05}     # fraction of the input price; 0.1 for every other model (hosted_cost.py)


def cost(r, m):
    pi, po = PR[m]
    ti, to = int(r.get('input_tokens') or 0), int(r.get('output_tokens') or 0)
    cr, cw = int(r.get('cache_read_tokens') or 0), int(r.get('cache_creation_tokens') or 0)
    return ((ti - cr - cw) * pi + cr * pi * CACHE_READ.get(m, 0.1) + cw * pi * 1.25 + to * po) / 1e6


def paired(a, b, ids):
    d = [a[t] - b[t] for t in ids]
    pt, lo, hi = C.boot(d)
    v = np.asarray(d); rng = np.random.default_rng(C.SEED)
    means = np.sort(np.array([v[rng.integers(0, len(v), len(v))].mean() for _ in range(C.R)]))
    lo90, hi90 = float(means[int(0.05 * C.R)]), float(means[int(0.95 * C.R) - 1])
    _, clo, chi, nb = C.cboot(d, ids, CL)
    return dict(point=pt, ci95=[lo, hi], ci90=[lo90, hi90], building95=[clo, chi], n_buildings=nb,
                wins=int(sum(x > 0 for x in d)), losses=int(sum(x < 0 for x in d)))


ours = C.read_rows(f'{C.RES}/local108_lib_all/per_task_{C.FINAL}.jsonl', S108)
son = C.read_rows(f'{RES}/per_task_claude-sonnet-5-5.jsonl', S108)
D_ours = {t: C.done(ours[t]) for t in S108}
D_son = {t: C.done(son[t]) for t in S108}
out = {}
for m in sys.argv[1:]:
    rows = C.read_rows(f'{RES}/per_task_{m}.jsonl', S108)
    D = {t: C.done(rows[t]) for t in S108}
    comp, lo, hi = C.boot([D[t] for t in S108])
    stops = {}
    for r in rows.values():
        stops[r['stop_reason']] = stops.get(r['stop_reason'], 0) + 1
    e = dict(
        completion=comp, ci95=[lo, hi], done=int(sum(D.values())),
        fully_specified=float(np.mean([D[t] for t in FULL])), under_specified_done=int(sum(D[t] for t in UNDER)),
        strict098=float(np.mean([C.done_at(rows[t], 0.98) for t in S108])),
        mean_score=float(np.mean([float(rows[t].get('final') or 0) for t in S108])),
        rounds=float(np.mean([rows[t]['tool_rounds'] for t in S108])),
        seconds=float(np.mean([float(rows[t].get('duration_seconds') or 0) for t in S108])),
        list_cost_usd=float(sum(cost(rows[t], m) for t in S108)),
        input_tokens_mean=float(np.mean([int(rows[t].get('input_tokens') or 0) for t in S108])),
        stops=stops, guard_blocked_tasks=int(sum(1 for t in S108 if rows[t].get('sandbox_blocked'))),
        ours_minus_this=paired(D_ours, D, S108), ours_minus_this_fully_specified=paired(D_ours, D, FULL),
        sonnet_documented_minus_this=paired(D_son, D, S108),
        per_version={v: float(np.mean([D[t] for t in S108 if T[t]['ifc_version'] == v])) for v in C.VERS},
    )
    out[m] = e
    pm = e['ours_minus_this']
    print(f"{m}: completion {comp:.3f} [{lo:.3f}, {hi:.3f}] ({e['done']}/108); fully specified {e['fully_specified']:.3f}; "
          f"under-specified {e['under_specified_done']}/11; strict 0.98 {e['strict098']:.3f}; mean score {e['mean_score']:.3f}; "
          f"rounds {e['rounds']:.2f}; {e['seconds']:.1f} s; list US${e['list_cost_usd']:.2f}; stops {stops}; guard-blocked tasks {e['guard_blocked_tasks']}")
    print(f"   VeriBIM-9B minus this: {pm['point']:+.3f} 95% [{pm['ci95'][0]:+.3f}, {pm['ci95'][1]:+.3f}] "
          f"buildings [{pm['building95'][0]:+.3f}, {pm['building95'][1]:+.3f}] (wins {pm['wins']}, losses {pm['losses']}); "
          f"Sonnet documented minus this: {e['sonnet_documented_minus_this']['point']:+.3f} "
          f"[{e['sonnet_documented_minus_this']['ci95'][0]:+.3f}, {e['sonnet_documented_minus_this']['ci95'][1]:+.3f}]")
json.dump(out, open(f'{HERE}/informed4.json', 'w'), indent=1)
