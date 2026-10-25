"""Draw the verdict-audit cases (packet B, 60 model outputs) and the rewrite tasks (packet A, 200 tasks).

Seed 20261015. Writes draw.json next to this script.

Packet B: model outputs of three arms (case_pool.py) on fully specified tasks. 30 cases the checker
counts as completed (all three axes >= 0.90) and 30 it does not, at most one case per task.
  not completed: every near-threshold case (an axis in 0.85-0.95) and every case that failed on one
    axis only; 4 "reply only, no edit" cases (two per arm that has them); the rest filled by a greedy
    least-used rule over arm, (operation, category) and IFC version. The 108-task subset alone holds
    12 such cases, so the not-completed half also draws from the other 216 tasks of the 324 subset.
  completed: every near-threshold case and every completed case of the untrained base model; the rest
    from the 108-task subset by the same greedy rule, with arm quotas.
Packet A: single tier, fully specified, disjoint from packet B; 9 operation x category cells (22 or 23
each), spread over IFC version, building and edit kind (greedy least-used, every edit kind seeded once);
then dealt into 5 blocks of 40, each block holding 4 or 5 tasks of every cell.
Tasks listed in exclusions.json (task_id -> reason, e.g. a render that failed) are skipped.
Run: taskset -c 16-23 python sample_tasks.py
"""
import collections, json, os, random

import case_pool as CP

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 20261015
CELLS = [(o, c) for o in ('create', 'update', 'delete') for c in ('direct', 'spatial', 'topological')]
N_FAIL, N_PASS, N_REPLY = 30, 30, 4
PASS_QUOTA = {'veribim': 16, 'commercial': 11}          # base: all of its completed cases
N_BLOCKS, BLOCK = 5, 40


def k_of(r, k):
    if k == 'cell':
        return (r['operation'], r['category'])
    if k == 'cell_version':
        return (r['operation'], r['category'], r['ifc_version'])
    return r[k]


def greedy(pool, n, rng, cnt, keys):
    pool = list(pool)
    rng.shuffle(pool)
    out = []
    while len(out) < n and pool:
        best = min(pool, key=lambda r: tuple(cnt[k][k_of(r, k)] for k in keys))
        out.append(best)
        pool.remove(best)
        for k in keys:
            cnt[k][k_of(best, k)] += 1
    return out


def draw_audit(rng, tasks, excl):
    rows = [r for r in CP.candidates(tasks) if r['task_id'] not in excl]
    keys = ('arm', 'cell', 'version')
    cnt = {k: collections.Counter() for k in keys}

    def take(rs):
        for r in rs:
            for k in keys:
                cnt[k][k_of(r, k)] += 1
        return rs
    used = set()
    # ---- not completed
    fails = [r for r in rows if not r['completed'] and (r['committed'] or r['reply_only'])]
    fails.sort(key=lambda r: (r['pool'], r['arm'], r['task_id']))
    must = [r for r in fails if r['committed'] and (r['near_threshold'] or r['n_fail_axes'] == 1)]
    must = take(must)
    used |= {r['task_id'] for r in must}
    reply = []
    rep_pool = [r for r in fails if r['reply_only'] and r['task_id'] not in used]
    for arm in sorted({r['arm'] for r in rep_pool}):
        cand = sorted([r for r in rep_pool if r['arm'] == arm], key=lambda r: (not r['near_threshold'],
                                                                              r['tier'] != 'single', r['task_id']))
        first = cand[:1]
        rest = cand[1:]
        rng.shuffle(rest)
        reply += first + rest[:1]
    reply = take(reply[:N_REPLY])
    used |= {r['task_id'] for r in reply}
    rest = [r for r in fails if r['committed'] and r['task_id'] not in used]
    # one row per task (a task failed by two arms: the greedy picks one arm)
    fill = []
    while len(must) + len(reply) + len(fill) < N_FAIL:
        rest = [r for r in rest if r['task_id'] not in used]
        if not rest:
            break
        pick = greedy(rest, 1, rng, cnt, keys)[0]
        fill.append(pick)
        used.add(pick['task_id'])
    fail_set = must + reply + fill
    # ---- completed: spread counted within the completed half, so that every cell holds both verdicts
    cnt = {k: collections.Counter() for k in keys}
    passes = [r for r in rows if r['completed'] and r['task_id'] not in used and r['committed'] | True]
    pmust = [r for r in passes if r['near_threshold'] or r['arm'] == 'base']
    seen = set()
    pm = []
    for r in sorted(pmust, key=lambda r: (r['pool'], r['arm'], r['task_id'])):
        if r['task_id'] not in seen:
            pm.append(r)
            seen.add(r['task_id'])
    pm = take(pm)
    used |= seen
    pass_set = list(pm)
    for arm, q in PASS_QUOTA.items():
        have = sum(1 for r in pass_set if r['arm'] == arm)
        pool = [r for r in passes if r['arm'] == arm and r['pool'] == '108' and r['task_id'] not in used]
        got = []
        while have + len(got) < q:
            pool = [r for r in pool if r['task_id'] not in used]
            if not pool:
                break
            pick = greedy(pool, 1, rng, cnt, keys + ('edit_kind',) if False else keys)[0]
            got.append(pick)
            used.add(pick['task_id'])
        pass_set += got
    assert len(fail_set) == N_FAIL, len(fail_set)
    assert len(pass_set) == N_PASS, len(pass_set)
    cases = fail_set + pass_set
    assert len({r['task_id'] for r in cases}) == len(cases)
    rng.shuffle(cases)                      # page order mixes arms and verdicts
    for i, r in enumerate(cases):
        r['label'] = f'A{i + 1:02d}'
        r['why'] = ('near threshold' if r['near_threshold'] else '') or \
                   ('reply only, no edit' if r['reply_only'] and not r['completed'] else '') or \
                   ('one axis failed' if (not r['completed'] and r['n_fail_axes'] == 1) else '') or \
                   ('base model completed' if r['completed'] and r['arm'] == 'base' else '') or 'spread'
    return cases


def draw_rewrite(rng, tasks, excl, used):
    full = [r for r in tasks.values() if r['tier'] == 'single' and not r['clarification']
            and r['task_id'] not in excl and r['task_id'] not in used]
    big = sorted(rng.sample(CELLS, 2))
    n_cell = {c: (23 if c in big else 22) for c in CELLS}
    assert sum(n_cell.values()) == 200
    by_kind = collections.defaultdict(list)
    for r in sorted(full, key=lambda r: r['task_id']):
        by_kind[r['edit_kind']].append(r)
    seeds = collections.defaultdict(list)
    cnt = {k: collections.Counter() for k in ('cell_version', 'building_id', 'edit_kind')}
    for kind in sorted(by_kind, key=lambda k: (len(by_kind[k]), k)):
        pool = [r for r in by_kind[kind] if len(seeds[k_of(r, 'cell')]) < n_cell[k_of(r, 'cell')] - 12]
        if not pool:
            continue
        rng.shuffle(pool)
        best = min(pool, key=lambda r: (len(seeds[k_of(r, 'cell')]), cnt['building_id'][r['building_id']]))
        seeds[k_of(best, 'cell')].append(best)
        cnt['building_id'][best['building_id']] += 1
    cnt = {k: collections.Counter() for k in ('cell_version', 'building_id', 'edit_kind')}
    chosen = {}
    for c in CELLS:
        cands = sorted([r for r in full if k_of(r, 'cell') == c], key=lambda r: r['task_id'])
        first = seeds[c]
        for r in first:
            for k in cnt:
                cnt[k][k_of(r, k)] += 1
        rest = [r for r in cands if r not in first]
        chosen[c] = first + greedy(rest, n_cell[c] - len(first), rng, cnt, ('cell_version', 'building_id', 'edit_kind'))
    # ---- deal into blocks: every cell gives 4 tasks to every block and its extra tasks (2 or 3) go to the
    # blocks with the fewest extras so far; within a cell each task goes to the open block that holds the
    # fewest tasks of its IFC version, then of its edit kind, then of its building
    quota = {}
    n_extra = [0] * N_BLOCKS
    for c in CELLS:
        ex = n_cell[c] - 4 * N_BLOCKS
        order = sorted(range(N_BLOCKS), key=lambda b: (n_extra[b], rng.random()))
        for b in range(N_BLOCKS):
            quota[(c, b)] = 4 + (1 if b in order[:ex] else 0)
        for b in order[:ex]:
            n_extra[b] += 1
    blocks = [[] for _ in range(N_BLOCKS)]
    bc = {k: [collections.Counter() for _ in range(N_BLOCKS)] for k in ('ifc_version', 'edit_kind', 'building_id')}
    for c in CELLS:
        rs = list(chosen[c])
        rng.shuffle(rs)
        rs.sort(key=lambda r: sum(1 for x in chosen[c] if x['edit_kind'] == r['edit_kind']))   # rare kinds first
        for r in rs:
            open_b = [b for b in range(N_BLOCKS) if sum(1 for x in blocks[b] if k_of(x, 'cell') == c) < quota[(c, b)]]
            b = min(open_b, key=lambda b: (bc['ifc_version'][b][r['ifc_version']], bc['edit_kind'][b][r['edit_kind']],
                                           bc['building_id'][b][r['building_id']], len(blocks[b])))
            blocks[b].append(r)
            for k in bc:
                bc[k][b][r[k]] += 1
    for b in blocks:
        assert len(b) == BLOCK, [len(x) for x in blocks]
        rng.shuffle(b)
    return blocks, big


def summ(rs, ver='ifc_version'):
    return {'by_cell': {f'{o}/{c}': sum(1 for r in rs if (r['operation'], r['category']) == (o, c)) for o, c in CELLS},
            'by_version': dict(sorted(collections.Counter(r[ver] for r in rs).items())),
            'by_edit_kind': dict(sorted(collections.Counter(r['edit_kind'] for r in rs).items())),
            'n_buildings': len({r.get('building_id', r.get('building')) for r in rs})}


def main():
    tasks = CP.load_tasks()
    excl_path = os.path.join(HERE, 'exclusions.json')
    excl = json.load(open(excl_path)) if os.path.exists(excl_path) else {}
    rng = random.Random(SEED)
    cases = draw_audit(rng, tasks, excl)
    used = {r['task_id'] for r in cases}
    blocks, big = draw_rewrite(rng, tasks, excl, used)
    rw_ids = [r['task_id'] for b in blocks for r in b]
    assert len(set(rw_ids)) == 200 and not (set(rw_ids) & used)
    audit_tab = collections.Counter((r['arm'], 'completed' if r['completed'] else 'not completed') for r in cases)
    draw = {
        'seed': SEED, 'tasks_file': 'runs_local/bench_v4/tasks.v4c.jsonl', 'exclusions': excl,
        'audit_cases': cases,
        'audit_summary': {
            'by_arm_verdict': {f'{a}/{v}': n for (a, v), n in sorted(audit_tab.items())},
            'by_pool': dict(collections.Counter(r['pool'] for r in cases)),
            'by_why': dict(collections.Counter(r['why'] for r in cases)),
            'by_cell': {f'{o}/{c}': sum(1 for r in cases if (r['operation'], r['category']) == (o, c)) for o, c in CELLS},
            'by_version': dict(sorted(collections.Counter(r['version'] for r in cases).items())),
            'by_tier': dict(collections.Counter(r['tier'] for r in cases)),
            'reply_only': sum(r['reply_only'] for r in cases)},
        'rewrite_cells_with_23': [f'{o}/{c}' for o, c in big],
        'rewrite_blocks': [[r['task_id'] for r in b] for b in blocks],
        'rewrite_summary': summ([r for b in blocks for r in b]),
        'rewrite_block_summaries': [summ(b) for b in blocks],
    }
    json.dump(draw, open(os.path.join(HERE, 'draw.json'), 'w'), indent=1)
    print(json.dumps({k: draw[k] for k in ('audit_summary', 'rewrite_cells_with_23', 'rewrite_summary')}, indent=1))
    for i, s in enumerate(draw['rewrite_block_summaries']):
        print('block', i + 1, s['by_cell'], s['by_version'])


if __name__ == '__main__':
    main()
