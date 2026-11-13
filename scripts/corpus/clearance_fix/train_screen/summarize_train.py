"""Share of the Stage B training tasks (all 51,956) whose door/window edit fails the clearance rule."""
import json, os, glob, collections, sys
HERE = os.path.dirname(os.path.abspath(__file__)); UP = os.path.dirname(HERE)
res = {}
for f in glob.glob(HERE + '/results_train_*.jsonl'):
    for l in open(f):
        r = json.loads(l); res[r['task_id']] = r
reused = 0
for f in ('results_big.jsonl', 'results_s0.jsonl', 'results_s1.jsonl'):
    for l in open(os.path.join(UP, f)):
        r = json.loads(l)
        if r['set'] == 'pool':
            res[r['task_id']] = r; reused += 1
sys.path.insert(0, UP)
import clearance_check as cc
recs = {}
n_all = 0
by_v_all = collections.Counter()
for l in open(cc.ROOT + 'runs_local/stage_b_v10/tasks_stage_b_v10.jsonl'):
    r = json.loads(l); n_all += 1; by_v_all[r['ifc_version']] += 1
    if cc.in_scope(r):
        recs[r['task_id']] = (r['ifc_version'], f"{r['edit_kind']}/{r['family']}", r['building_id'])
missing = [t for t in recs if t not in res]
err = [t for t in recs if t in res and res[t]['status'] != 'ok']
ok = {t: res[t] for t in recs if t in res and res[t]['status'] == 'ok'}
withf = {t: r for t, r in ok.items() if r['n_fillings'] > 0}
flag = {t for t, r in withf.items() if r['flag']}
def tab(key):
    s = collections.Counter(key(t) for t in withf); f = collections.Counter(key(t) for t in flag)
    return {k: {'screened': s[k], 'fail': f[k], 'share': round(f[k] / s[k], 4)} for k in sorted(s)}
out = {'tasks_all': n_all, 'tasks_by_version': dict(by_v_all), 'filling_tasks_in_scope': len(recs),
       'screened_ok': len(ok), 'errors': err, 'not_run': missing, 'reused_from_pool_screen': reused,
       'with_a_created_or_moved_filling': len(withf), 'fail': len(flag),
       'share_of_filling_tasks': round(len(flag) / len(withf), 4),
       'share_of_all_training_tasks': round(len(flag) / n_all, 4),
       'by_version': tab(lambda t: recs[t][0]), 'by_kind': tab(lambda t: recs[t][1]),
       'by_version_kind': tab(lambda t: recs[t][0] + ' ' + recs[t][1]),
       'buildings_worst': sorted(((b, v['fail'], v['screened']) for b, v in tab(lambda t: recs[t][2]).items()),
                                 key=lambda x: -x[1])[:15],
       'full_set': True}
json.dump(out, open(HERE + '/train_summary.json', 'w'), indent=1)
json.dump(sorted(flag), open(HERE + '/train_flagged_ids.json', 'w'), indent=0)
print(json.dumps({k: v for k, v in out.items() if k not in ('by_version_kind',)}, indent=1))
