#!/usr/bin/env python3
"""Name the reported model among the three stage models by their completion on the hard validation set.

    python analysis/validation/name_reported_model.py VAL_HARD_DIR GATES_DIR PREFERENCE_MODEL REINFORCEMENT_MODEL OUT.txt

The candidates are the imitation model (VAL_HARD_DIR/per_task_sft_v14.jsonl), the kept preference snapshot
(VAL_HARD_DIR/per_task_<PREFERENCE_MODEL>.jsonl) and the kept reinforcement snapshot
(GATES_DIR/per_task_<REINFORCEMENT_MODEL>.jsonl). The candidate with the highest completion (geometry, semantics and
topology all at least 0.9) is reported; a tie goes to the higher mean final score, then to the earlier stage. The rule
decides only when every candidate has a read of all 300 tasks. OUT.txt lists the candidates in rank order and the
reported model. The code below is the rule as it ran, with the input folder of the reinforcement read and the output
path given as arguments.
"""
import json, sys, glob, os
vhd, gates, dpeak, fn, out_path = sys.argv[1:6]
def stats(p):
    rows = [json.loads(l) for l in open(p) if l.strip()]
    comp = sum(all(((r.get('score') or {}).get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology')) for r in rows) / len(rows)
    return round(comp, 6), round(sum(float(r.get('final') or 0) for r in rows) / len(rows), 6), len(rows)
cands = [('sft_v14', 0, os.path.join(vhd, 'per_task_sft_v14.jsonl'))]   # (name, stage order, file)
if dpeak: cands.append((dpeak, 1, os.path.join(vhd, f'per_task_{dpeak}.jsonl')))
if fn:
    hit = glob.glob(os.path.join(gates, f'per_task_{fn}.jsonl'))
    cands.append((fn, 2, hit[0] if hit else ''))
res = []
for name, order, f in cands:
    if f and os.path.exists(f):
        c, m, n = stats(f); res.append((c, m, -order, name, n))
res.sort(reverse=True)
with open(out_path, 'w') as out:
    for c, m, o, name, n in res: out.write(f'{name}\tstage {-o}\tval-hard completion {c:.4f}\tmean {m:.4f}\tn {n}\n')
    done = len(res) == len(cands) and all(r[4] == 300 for r in res)
    out.write(f'REPORTED\t{res[0][3]}\n' if done else f'UNDECIDED\t{len(res)} of {len(cands)} val-hard reads found, rows {[r[4] for r in res]}\n')
print(res[0][3] if done else '')
