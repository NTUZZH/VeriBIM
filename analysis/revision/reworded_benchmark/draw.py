"""Draw 200 fully specified benchmark tasks for the reworded-instruction test on the benchmark buildings.

Pool: runs_local/bench_v4/tasks.v4d.jsonl, tasks whose `clarification` field is null (the under-specified tasks,
edit_kind 'clarify', carry a clarification record and are excluded). Strata: family x operation. Quotas: largest-
remainder allocation of 200 in proportion to the pool's stratum sizes (ties in the fractional part broken by the
stratum name). Within each stratum, in sorted stratum order, one random.Random(SEED) draws the quota from the
stratum's task ids in sorted order. The draw must cover all 12 benchmark buildings; the script asserts it.
Writes draw_200.json (ids, seed, quotas, building and version counts, input checksum).
"""
import collections, hashlib, json, random, os
SEED = 20261019
N_DRAW = 200
P = '.'
TASKS = P + '/runs_local/bench_v4/tasks.v4d.jsonl'
HERE = os.path.dirname(os.path.abspath(__file__))

T = [json.loads(l) for l in open(TASKS)]
assert len(T) == 2100
pool = [t for t in T if t.get('clarification') is None]
assert all(t['edit_kind'] != 'clarify' for t in pool) and len(T) - len(pool) == sum(t['edit_kind'] == 'clarify' for t in T)
strata = collections.defaultdict(list)
for t in pool:
    strata[(t['family'], t['operation'])].append(t['task_id'])
N = len(pool)
exact = {s: N_DRAW * len(v) / N for s, v in strata.items()}
quota = {s: int(x) for s, x in exact.items()}
left = N_DRAW - sum(quota.values())
for s in sorted(exact, key=lambda s: (-(exact[s] - quota[s]), s))[:left]:
    quota[s] += 1
assert sum(quota.values()) == N_DRAW
rng = random.Random(SEED)
ids = []
for s in sorted(strata):
    ids += rng.sample(sorted(strata[s]), quota[s])
by = {t['task_id']: t for t in pool}
bld = collections.Counter(by[i]['building_id'] for i in ids)
all_bld = {t['building_id'] for t in T}
assert set(bld) == all_bld and len(all_bld) == 12, (sorted(all_bld - set(bld)))
out = {
    'seed': SEED, 'n': N_DRAW, 'tasks_file': TASKS,
    'tasks_file_sha256': hashlib.sha256(open(TASKS, 'rb').read()).hexdigest(),
    'pool': 'fully specified tasks (clarification is null): %d of %d; %d under-specified excluded' % (N, len(T), len(T) - N),
    'allocation': 'largest remainder over family x operation, proportional to the pool; within-stratum random.Random(seed).sample over sorted ids, strata in sorted order',
    'quotas': {'%s|%s' % s: {'pool': len(strata[s]), 'exact': round(exact[s], 3), 'drawn': quota[s]} for s in sorted(strata)},
    'buildings': dict(sorted(bld.items())),
    'ifc_version': dict(sorted(collections.Counter(by[i]['ifc_version'] for i in ids).items())),
    'operation': dict(sorted(collections.Counter(by[i]['operation'] for i in ids).items())),
    'category': dict(sorted(collections.Counter(by[i]['category'] for i in ids).items())),
    'tier': dict(sorted(collections.Counter(by[i]['tier'] for i in ids).items())),
    'task_ids': ids,
}
json.dump(out, open(os.path.join(HERE, 'draw_200.json'), 'w'), indent=1)
print(json.dumps({k: v for k, v in out.items() if k != 'task_ids'}, indent=1))
