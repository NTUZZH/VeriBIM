#!/usr/bin/env python3
"""Untrained Qwen3.5-9B with the documented library on the 108-task subset: completion, specification
split, strict threshold, rounds, and paired differences against VeriBIM-9B, against the base with the short library
note, against the base alone, and against the documented Claude Sonnet 5.5 run. Conventions of stats/common.py
(completion = all axes >= 0.9; task-level percentile bootstrap 10,000 x seed 20260929; building-level cluster bootstrap).
    python analyze_base_informed.py   -> prints and writes base_informed.json next to this script
"""
import json, os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
import numpy as np
import common as C

HERE = os.path.dirname(os.path.abspath(__file__))
T, S108, _ = C.load_tasks()
CL = {t: T[t]['building_id'] for t in T}
UNDER = [t for t in S108 if T[t]['clarification']]
FULL = [t for t in S108 if not T[t]['clarification']]
assert len(UNDER) == 11 and len(FULL) == 97


def paired(a, b, ids):
    d = [a[t] - b[t] for t in ids]
    pt, lo, hi = C.boot(d)
    _, clo, chi, nb = C.cboot(d, ids, CL)
    return dict(point=pt, ci95=[lo, hi], building95=[clo, chi], n_buildings=nb,
                wins=int(sum(x > 0 for x in d)), losses=int(sum(x < 0 for x in d)))


def load(path):
    rows = C.read_rows(path, S108)
    return rows, {t: C.done(rows[t]) for t in S108}


ours, D_ours = load(f'{C.RES}/local108_lib_all/per_task_{C.FINAL}.jsonl')
note, D_note = load(f'{C.RES}/local108_libnote_all/per_task_{C.BASE}.jsonl')
alone, D_alone = load(f'{C.RES}/local108_alone_all/per_task_{C.BASE}.jsonl')
son, D_son = load(f'{C.RES}/hosted108_informed_all/per_task_claude-sonnet-5-5.jsonl')
rows, D = load(f'{C.RES}/local108_informed_all/per_task_{C.BASE}.jsonl')
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
    input_tokens_mean=float(np.mean([int(rows[t].get('input_tokens') or 0) for t in S108])),
    stops=stops, guard_blocked_tasks=int(sum(1 for t in S108 if rows[t].get('sandbox_blocked'))),
    committed=int(sum(1 for t in S108 if rows[t].get('committed'))),
    ours_minus_this=paired(D_ours, D, S108), ours_minus_this_fully_specified=paired(D_ours, D, FULL),
    this_minus_base_note=paired(D, D_note, S108), this_minus_base_alone=paired(D, D_alone, S108),
    sonnet_documented_minus_this=paired(D_son, D, S108),
    base_note_completion=float(np.mean([D_note[t] for t in S108])), base_alone_completion=float(np.mean([D_alone[t] for t in S108])),
    per_version={v: float(np.mean([D[t] for t in S108 if T[t]['ifc_version'] == v])) for v in C.VERS},
)
pm = e['ours_minus_this']
print(f"base documented: completion {comp:.3f} [{lo:.3f}, {hi:.3f}] ({e['done']}/108); fully specified {e['fully_specified']:.3f}; "
      f"under-specified {e['under_specified_done']}/11; strict 0.98 {e['strict098']:.3f}; mean score {e['mean_score']:.3f}; "
      f"rounds {e['rounds']:.2f}; {e['seconds']:.1f} s; committed {e['committed']}; stops {stops}; guard-blocked {e['guard_blocked_tasks']}")
print(f"   VeriBIM-9B minus this: {pm['point']:+.3f} [{pm['ci95'][0]:+.3f}, {pm['ci95'][1]:+.3f}] buildings [{pm['building95'][0]:+.3f}, {pm['building95'][1]:+.3f}]")
for k in ('this_minus_base_note', 'this_minus_base_alone', 'sonnet_documented_minus_this'):
    q = e[k]; print(f"   {k}: {q['point']:+.3f} [{q['ci95'][0]:+.3f}, {q['ci95'][1]:+.3f}] (wins {q['wins']}, losses {q['losses']})")
print(f"   base note {e['base_note_completion']:.3f}, base alone {e['base_alone_completion']:.3f}")
json.dump({C.BASE: e}, open(f'{HERE}/base_informed.json', 'w'), indent=1)
