"""For each flagged benchmark task: how many candidates of its cell and building pass the
clearance rule and the repair script's own candidate filters (rebench.py)."""
import importlib.util, json, os, sys, time, collections, resource
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, 'install_v2'))
import clearance_check as cc
from fixcommon import carries_opposite            # read-only helper of the opposite repair
R = cc.ROOT + 'runs_local/'
spec = importlib.util.spec_from_file_location('select_bench_v4', cc.ROOT + 'scripts/benchmark/select_bench_v4.py')
sel = importlib.util.module_from_spec(spec); spec.loader.exec_module(sel)
drv = sel.drv
from modifc_gen.build_e2 import NULL_CAP
VERSIONS = ('IFC2X3', 'IFC4', 'IFC4X3')

flag = {}
for l in open(HERE + '/flagged_bench_v4.jsonl'):
    r = json.loads(l); flag[r['task_id']] = r
bench = {json.loads(l)['task_id']: json.loads(l) for l in open(R + 'bench_v4/tasks.jsonl')}
plan = json.load(open(R + 'corpus_v10/opposite_fix/install/dry_run/bench_v4b/plan.json'))
taken = set(plan['replacements'].values())


def usable(t, v):
    """The candidate filters of rebench.py (the opposite-anchor filter included)."""
    if sel.unstated_type(t): return False
    if t.get('edit_kind') == 'create_box' and set(t.get('families') or ()) & sel.BAD_FAMILIES: return False
    if drv.floor_of(t) > NULL_CAP: return False
    if carries_opposite(t): return False
    if v == 'IFC4X3' and t.get('tier') == 'compositional' and t.get('operation') == 'create': return False
    return True


cands = {}
for v in VERSIONS:
    cands[v] = [t for t in map(json.loads, open(R + f'corpus_v10/gen/bench_candidates_v10_{v}.jsonl'))
                if t['task_id'] not in bench and usable(t, v)]
cache_path = HERE + '/candidate_checks.jsonl'
checked = {}
if os.path.exists(cache_path):
    for l in open(cache_path):
        r = json.loads(l); checked[r['task_id']] = r
out = []
with open(cache_path, 'a') as cf:
    for tid in sorted(flag, key=lambda i: (VERSIONS.index(bench[i]['ifc_version']), i)):
        d = bench[tid]; v = d['ifc_version']
        attr = drv.kind(d) in drv.ATTR
        cell = [t for t in cands[v] if t['tier'] == d['tier'] and t['operation'] == d['operation']
                and t['category'] == d['category'] and (drv.kind(t) in drv.ATTR) == attr]
        same_b = [t for t in cell if t['building_id'] == d['building_id']]
        passing, failing, same_kind_pass = [], [], []
        for t in same_b:
            if t['task_id'] in taken:
                continue
            if cc.in_scope(t):
                if t['task_id'] not in checked:
                    t0 = time.time()
                    try:
                        res = cc.check_task(t); res['status'] = 'ok'
                    except Exception as exc:
                        res = {'task_id': t['task_id'], 'status': 'error', 'error': repr(exc)[:200], 'flag': None}
                    res['seconds'] = round(time.time() - t0, 1)
                    checked[t['task_id']] = res
                    cf.write(json.dumps(res, default=str) + '\n'); cf.flush()
                ok = checked[t['task_id']]['flag'] is False
            else:
                ok = True
            (passing if ok else failing).append(t['task_id'])
            if ok and t.get('edit_kind') == d.get('edit_kind'):
                same_kind_pass.append(t['task_id'])
        row = {'task_id': tid, 'ifc_version': v, 'building_id': d['building_id'], 'edit_kind': d['edit_kind'],
               'cell': f"{v} {d['tier']} {d['operation']}/{d['category']}", 'cell_candidates': len(cell),
               'cell_same_building': len(same_b), 'same_building_taken_by_opposite_repair': sum(1 for t in same_b if t['task_id'] in taken),
               'same_building_passing': len(passing), 'same_building_failing_clearance': len(failing),
               'same_building_same_edit_kind_passing': len(same_kind_pass),
               'failing_ids': failing}
        out.append(row)
        print(tid, row['cell'], row['cell_candidates'], row['cell_same_building'], row['same_building_passing'],
              row['same_building_same_edit_kind_passing'], len(failing), flush=True)
json.dump(out, open(HERE + '/replacement_availability.json', 'w'), indent=1)
print('maxrss MB', resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
