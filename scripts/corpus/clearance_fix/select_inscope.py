"""Write the in-scope task subsets (tasks whose edit creates, copies, moves or replaces a door or window)."""
import json, os, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clearance_check as cc
R = cc.ROOT + 'runs_local/'
OUT = R + 'corpus_v10/clearance_fix/'
pool = set(json.load(open(R + 'stage_b_v10/pool_v10.json')))
sources = {'bench_v4': R + 'bench_v4/tasks.jsonl',
           'val500': R + 'stage_a_v10/val_tasks_500_v3.jsonl',
           'val100': R + 'stage_a_v10/val_tasks_100_v3.jsonl',
           'pool': R + 'stage_b_v10/tasks_stage_b_v10.jsonl'}
summary = {}
for name, path in sources.items():
    n = 0; keep = []
    for line in open(path):
        r = json.loads(line)
        if name == 'pool' and r['task_id'] not in pool:
            continue
        n += 1
        if cc.in_scope(r):
            keep.append(r)
    with open(OUT + f'inscope_{name}.jsonl', 'w') as f:
        for r in keep:
            f.write(json.dumps(r) + '\n')
    summary[name] = {'tasks': n, 'in_scope': len(keep),
                     'by_kind': dict(collections.Counter(f"{r['edit_kind']}/{r['family']}" for r in keep))}
    print(name, n, len(keep))
json.dump(summary, open(OUT + 'inscope_summary.json', 'w'), indent=1)
