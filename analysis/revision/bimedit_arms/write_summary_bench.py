#!/usr/bin/env python3
"""Write summary_bench_<model>.json for an arm directory (same format as the summary_bench files in results/bimedit/),
from its scores_bench csv and per_task jsonl.   python write_summary_bench.py <arm_dir> <model>"""
import sys, json, csv, statistics as st
arm, model = sys.argv[1], sys.argv[2]
rows = list(csv.DictReader(open(f'{arm}/scores_bench_{model}.csv')))
pt = {json.loads(l)['task_id']: json.loads(l) for l in open(f'{arm}/per_task_{model}.jsonl') if l.strip()}
assert len(rows) == 324 and set(pt) == {r['task_id'] for r in rows}, (len(rows), len(pt))
f = {r['task_id']: float(r['final_score'] or 0) for r in rows}
def mean(ts): return round(st.mean(f[t] for t in ts), 4)
summ = {'adapter': model, 'n': 324, 'mean_final': mean(f), 
        'full_solve_rate': round(sum(1 for r in rows if all(float(r[k] or 0) >= 0.98 for k in ('geometry','semantics','topology'))) / 324, 4),
        'by_category': {c: mean([t for t in f if pt[t]['category'] == c]) for c in ('direct','spatial','topological')},
        'by_operation': {o: mean([t for t in f if pt[t]['operation'] == o]) for o in ('create','delete','update')},
        'axes': {k: round(st.mean(float(r[k] or 0) for r in rows), 4) for k in ('geometry','semantics','topology')}}
json.dump(summ, open(f'{arm}/summary_bench_{model}.json', 'w'), indent=2)
print(json.dumps(summ))
