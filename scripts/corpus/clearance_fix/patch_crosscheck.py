"""Run the patched funnel stage on real records and compare with clearance_check.py."""
import json, os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import modifc_gen
assert 'clearance_fix/patch/b' in modifc_gen.__file__
from modifc_gen import verify, script
from modifc_gen.scene import Scene
import clearance_check as cc
ids = sys.argv[1].split(',')
rows = {}
for f in ('inscope_val500.jsonl', 'inscope_bench_v4.jsonl'):
    for l in open(f):
        r = json.loads(l)
        if r['task_id'] in ids: rows[r['task_id']] = r
work = tempfile.mkdtemp(dir=os.path.dirname(os.path.abspath(__file__)))
try:
    for tid in ids:
        r = rows[tid]
        src = cc.ROOT + r['input_ifc']
        gold = os.path.join(work, tid + '.ifc')
        script.execute_script(r['gold_script'], src, gold)
        sc = Scene(src)
        eg = r['edit_guids']
        st = verify.check_filling_clearance(sc, gold, eg.get('created') or (), tuple(eg.get('target') or ()) + tuple(eg.get('touched') or ()))
        mine = cc.check_task(r)
        print(tid, 'stage ok' if st.ok else 'stage REFUSED', st.reason, st.detail, '| checker flag', mine['flag'], mine['min_d'])
        os.remove(gold)
finally:
    shutil.rmtree(work)
