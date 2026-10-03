"""Hosted comparison on the 108-task subset: completion per model and arm, with the local model's projection on the
same tasks and paired bootstrap 95 % intervals (10,000 resamples over tasks, seed 20260929) of local minus hosted,
pooled and per IFC version.   python hosted_table.py <local_per_task.jsonl> <local name>"""
import json, random, sys, collections
B = 'runs_local/bench_v4/results'
T = {json.loads(l)['task_id']: json.loads(l) for l in open('runs_local/bench_v4/tasks.v4c.jsonl')}
sub = json.load(open('runs_local/bench_v4/subset_108_hosted.v4c.json'))
def done(r): return 1 if all(((r.get('score') or {}).get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology')) else 0
def load(p): return {json.loads(l)['task_id']: json.loads(l) for l in open(p) if l.strip()}
local_p, local_name = sys.argv[1], sys.argv[2]
local = load(local_p)
models = ['gpt-5.6-luna', 'deepseek-v4-pro', 'claude-sonnet-5-5', 'gemini-3.8-flash']
rng = random.Random(20260929); R = 10000
def ci(diffs):
    n = len(diffs); m = sum(diffs) / n
    bs = sorted(sum(diffs[rng.randrange(n)] for _ in range(n)) / n for _ in range(R))
    return m, bs[int(0.025 * R)], bs[int(0.975 * R) - 1]
vers = ['IFC2X3', 'IFC4', 'IFC4X3']
print(f"{'model':20} {'arm':6} {'ALL':>7} " + ' '.join(f'{v:>7}' for v in vers) + f"   | {local_name} minus model: mean [95% CI]  pooled; per version")
lp = {v: sum(done(local[t]) for t in sub if T[t]['ifc_version'] == v) / 36 for v in vers}
print(f"{local_name:20} {'lib':6} {sum(done(local[t]) for t in sub)/108:7.3f} " + ' '.join(f'{lp[v]:7.3f}' for v in vers))
for m in models:
    for arm in ['alone', 'lib']:
        h = load(f'{B}/hosted108_{arm}_all/per_task_{m}.jsonl')
        comp = {v: sum(done(h[t]) for t in sub if T[t]['ifc_version'] == v) / 36 for v in vers}
        d_all = [done(local[t]) - done(h[t]) for t in sub]
        parts = [f"{ci(d_all)[0]:+.3f} [{ci(d_all)[1]:+.3f},{ci(d_all)[2]:+.3f}]"]
        for v in vers:
            d = [done(local[t]) - done(h[t]) for t in sub if T[t]['ifc_version'] == v]
            mm, lo, hi = ci(d); parts.append(f"{v} {mm:+.3f} [{lo:+.3f},{hi:+.3f}]")
        print(f"{m:20} {arm:6} {sum(done(h[t]) for t in sub)/108:7.3f} " + ' '.join(f'{comp[v]:7.3f}' for v in vers) + '   | ' + '; '.join(parts))
