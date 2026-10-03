"""In-scope filling tasks of all 51,956 Stage B training tasks; the 1,252 pool tasks screened
before are reused (same records, same checker), the rest are written for screening."""
import json, os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, os.path.dirname(HERE))
import clearance_check as cc
done = set()
for f in ('results_big.jsonl', 'results_s0.jsonl', 'results_s1.jsonl'):
    for l in open(os.path.join(os.path.dirname(HERE), f)):
        r = json.loads(l)
        if r['set'] == 'pool': done.add(r['task_id'])
n = k = 0
with open(HERE + '/inscope_train_todo.jsonl', 'w') as h:
    for l in open(cc.ROOT + 'runs_local/stage_b_v10/tasks_stage_b_v10.jsonl'):
        r = json.loads(l); n += 1
        if cc.in_scope(r):
            k += 1
            if r['task_id'] not in done:
                h.write(l if l.endswith('\n') else l + '\n')
print(n, 'tasks;', k, 'in scope;', len(done), 'reused from the pool screen')
