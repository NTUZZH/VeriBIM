"""Task-level versus building-level cluster bootstrap for every completion interval the manuscript reports.

For each interval: (a) the published task-level percentile bootstrap, recomputed with the exhibit script's own
boot() over the same task order, to confirm the pipeline reproduces the macro; (b) a building-level cluster
bootstrap (resample the buildings of the task set with replacement, pool all tasks of each drawn building, 10,000
resamples, seed 20260929, percentile 2.5/97.5). Paired differences resample buildings and take the paired
difference over the drawn tasks. Also: discordant tasks and the sign of each paired difference per building.

    taskset -c 8-9 env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
        python analysis/revision/stats/cluster_boot.py
"""
import json, random, statistics, sys
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
import numpy as np
from common import *          # noqa: F401,F403
import common as C

T, S108, S324 = load_tasks()
rows, sets = load_all(T, S108, S324)
CL = {t: T[t]['building_id'] for t in T}
M = parse_macros(f'{ROOT}/writing/tables/macros_results_v10.tex', f'{ROOT}/writing/tables/macros_small_chain.tex')
SET_TOK = {108: 'HundredEight', 324: 'ThreeTwentyFour', 2100: 'Bench'}
ENTRIES = []


def pub(name):
    return [M.get(name), M.get(name + 'Lo'), M.get(name + 'Hi')]


def match(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


def entry(macro, setname, kind, desc, vals, ids, clus, task_iv, tol=0.0006, extra=None):
    p = pub(macro)
    cb = cboot(vals, ids, clus)
    wt, wc = task_iv[2] - task_iv[1], cb[2] - cb[1]
    e = {'macro': macro, 'set': setname, 'kind': kind, 'what': desc, 'n_tasks': len(ids), 'n_buildings': cb[3],
         'point': round(task_iv[0], 6), 'published': p,
         'task_level': [round(x, 6) for x in task_iv[1:3]],
         'reproduces_published': bool(p[1] is not None and match(task_iv[1], p[1], tol) and match(task_iv[2], p[2], tol)
                                      and match(task_iv[0], p[0], tol)),
         'cluster': [round(cb[1], 6), round(cb[2], 6)],
         'width_task': round(wt, 6), 'width_cluster': round(wc, 6),
         'width_ratio': round(wc / wt, 2) if wt > 0 else None,
         'cluster_wider_than_1_5x': bool(wt > 0 and wc / wt > 1.5),
         'cluster_excludes_zero': bool(cb[1] > 0 or cb[2] < 0) if kind != 'single' else None,
         'task_excludes_zero': bool(task_iv[1] > 0 or task_iv[2] < 0) if kind != 'single' else None}
    if extra:
        e.update(extra)
    ENTRIES.append(e)
    return e


def paired_extra(ra, rb, ids, clus):
    d = [done(ra[t]) - done(rb[t]) for t in ids]
    pcm = per_cluster_means(d, ids, clus)
    return {'a_only': sum(1 for x in d if x > 0), 'b_only': sum(1 for x in d if x < 0),
            'discordant': sum(1 for x in d if x != 0),
            'buildings_favour_a': sum(1 for v, _ in pcm.values() if v > 0),
            'buildings_favour_b': sum(1 for v, _ in pcm.values() if v < 0),
            'buildings_tie': sum(1 for v, _ in pcm.values() if v == 0),
            'per_building_diff': {b: [round(v, 6), n] for b, (v, n) in pcm.items()}}


def groups(ids):
    out = [('ALL', sorted(ids))]
    for g in VERS:
        out.append((g, sorted(t for t in ids if T[t]['ifc_version'] == g)))
    for g in ORIGS:
        s = sorted(t for t in ids if T[t]['origin'] == g)
        if s:
            out.append((g, s))
    return out


# ---- single-arm completion intervals and paired differences on the 108 and 324 subsets
single_tok = {108: [('Ours', (108, 'ours')), ('BaseAlone', (108, 'base', 'alone')), ('BaseNote', (108, 'base', 'libnote')),
                    ('SftLib', (108, 'sft', 'lib')), ('SftAlone', (108, 'sft', 'alone'))] +
                   [(tok + ('Alone' if a == 'alone' else 'Lib'), (108, mid, a)) for mid, _, tok in COMMERCIAL
                    for a in ('alone', 'lib')],
              324: [('Ours', (324, 'ours')), ('SftLib', (324, 'sft', 'lib')), ('SftAlone', (324, 'sft', 'alone')),
                    ('PrevLib', (324, 'prev', 'lib')), ('SonnetAlone', (324, 'claude-sonnet-5-5', 'alone')),
                    ('SonnetLib', (324, 'claude-sonnet-5-5', 'lib'))]}
for n in (108, 324):
    ids = sorted(sets[n])
    for tok, key in single_tok[n]:
        v = [done(rows[key][t]) for t in ids]
        entry(f'Res{SET_TOK[n]}{tok}Comp', n, 'single', f'completion, {arm_paths()[key][2]}', v, ids, CL, boot(v))
    for tok, key in single_tok[n][1:]:
        ra, rb = rows[(n, 'ours')], rows[key]
        for g, gids in groups(ids):
            v = [done(ra[t]) - done(rb[t]) for t in gids]
            entry(f'Res{SET_TOK[n]}OursMinus{tok}{GTOK[g]}', n, 'paired',
                  f'final model minus {arm_paths()[key][2]}, {g}', v, gids, CL, boot(v),
                  extra=paired_extra(ra, rb, gids, CL))

# ---- the 2,100-task benchmark: training chain
ALL = sorted(T)
for tok, k in (('Sft', 'sft'), ('Dpo', 'dpo'), ('Grpo', 'ours'), ('Prev', 'prev'), ('Ours', 'ours')):
    v = [done(rows[(2100, k)][t]) for t in ALL]
    entry(f'ResBench{tok}Comp', 2100, 'single', f'completion, {arm_paths()[(2100, k)][2]}', v, ALL, CL, boot(v))
for ta, a, tb, b in (('Ours', 'ours', 'Sft', 'sft'), ('Ours', 'ours', 'Dpo', 'dpo'), ('Dpo', 'dpo', 'Sft', 'sft'),
                     ('Grpo', 'ours', 'Dpo', 'dpo'), ('Dpo', 'dpo', 'Prev', 'prev')):
    ra, rb = rows[(2100, a)], rows[(2100, b)]
    for g, gids in groups(ALL):
        v = [done(ra[t]) - done(rb[t]) for t in gids]
        entry(f'ResBenchDelta{ta}Over{tb}{GTOK[g]}', 2100, 'paired', f'{ta} minus {tb}, {g}', v, gids, CL, boot(v),
              extra=paired_extra(ra, rb, gids, CL))

# ---- library x training interaction (difference in differences) on the 108-task subset
ids = sorted(S108)
q = [rows[(108, 'sft', 'lib')], rows[(108, 'sft', 'alone')], rows[(108, 'base', 'libnote')], rows[(108, 'base', 'alone')]]
v = [(done(q[0][t]) - done(q[1][t])) - (done(q[2][t]) - done(q[3][t])) for t in ids]
entry('ResHundredEightLibTrainDiD', 108, 'paired', 'library gain of the imitation model minus library gain of the '
      'untrained model (completion)', v, ids, CL, boot(v))

# ---- untrained base on the 2,100 tasks: a stopped read (982 tasks) plus the 108-task read with the library note
rows982 = read_rows(f'{RES}/full_note_all/per_task_{BASE}.jsonl', T, partial=True)
be = ex.base_estimate(rows982, rows[(108, 'base', 'libnote')], T)
per, _ = be['_per_rows']


def cluster_base(trained=None):
    """Cluster analogue of the base estimate (trained=None) or of the difference estimator of a trained model's
    gain: resample the 12 buildings; per version, the base rate over the measured tasks of the drawn buildings
    (and the trained rate over all tasks of that version in the drawn buildings); equal-weight mean of the three."""
    B = sorted({T[t]['building_id'] for t in T})
    bi = {b: i for i, b in enumerate(B)}
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(B), size=(R, len(B)))
    W = np.zeros((R, len(B)))
    for j in range(len(B)):
        W[:, j] = (idx == j).sum(1)
    acc = np.zeros(R)
    bad = np.zeros(R, bool)
    for vname in VERS:
        sb, nb, st, nt = (np.zeros(len(B)) for _ in range(4))
        for t, r in per[vname].items():
            sb[bi[T[t]['building_id']]] += done(r)
            nb[bi[T[t]['building_id']]] += 1
        for t in T:
            if T[t]['ifc_version'] == vname and trained is not None:
                st[bi[T[t]['building_id']]] += done(trained[t])
                nt[bi[T[t]['building_id']]] += 1
        den = W @ nb
        bad |= den == 0
        base_rate = np.where(den > 0, (W @ sb) / np.maximum(den, 1), np.nan)
        if trained is None:
            acc += base_rate
        else:
            acc += (W @ st) / np.maximum(W @ nt, 1) - base_rate
    acc = acc[~bad] / 3
    st_ = np.sort(acc)
    k = len(st_)
    return float(st_[int(0.025 * k)]), float(st_[int(0.975 * k) - 1]), int(bad.sum())


lo, hi, nbad = cluster_base()
e = be['est']
ENTRIES.append({'macro': 'ResBenchBaseNoteCompEst', 'set': 2100, 'kind': 'single (estimate)',
                'what': 'untrained model with the library note, completion estimated from 982 + 108-task reads',
                'n_tasks': be['n_read'], 'n_buildings': 12, 'point': round(e[0], 6),
                'published': pub('ResBenchBaseNoteCompEst'), 'task_level': [round(e[1], 6), round(e[2], 6)],
                'task_level_rule': 'MOVER combination of per-version Wilson intervals (published rule); stratified task '
                                   f'bootstrap cross-check {[round(x, 6) for x in be["est_boot"][1:]]}',
                'reproduces_published': match(e[1], pub('ResBenchBaseNoteCompEst')[1], 6e-4) and
                                        match(e[2], pub('ResBenchBaseNoteCompEst')[2], 6e-4),
                'cluster': [round(lo, 6), round(hi, 6)], 'cluster_draws_dropped_no_measured_task': nbad,
                'width_task': round(e[2] - e[1], 6), 'width_cluster': round(hi - lo, 6),
                'width_ratio': round((hi - lo) / (e[2] - e[1]), 2),
                'cluster_wider_than_1_5x': (hi - lo) / (e[2] - e[1]) > 1.5})
for tok, k in (('Sft', 'sft'), ('Dpo', 'dpo')):
    g = ex.base_gain(rows[(2100, k)], be, T)
    lo, hi, nbad = cluster_base(rows[(2100, k)])
    w = g['ALL'][2] - g['ALL'][1]
    ENTRIES.append({'macro': f'ResBenchDelta{tok}Over{"Base"}', 'set': 2100, 'kind': 'paired (estimate)',
                    'what': f'{tok} minus untrained model, difference estimator over the measured base tasks',
                    'n_tasks': 2100, 'n_buildings': 12, 'point': round(g['ALL'][0], 6),
                    'published': pub(f'ResBenchDelta{tok}OverBase'),
                    'task_level': [round(g['ALL'][1], 6), round(g['ALL'][2], 6)],
                    'task_level_rule': 'MOVER combination (published rule); paired task bootstrap cross-check '
                                       f'{[round(x, 6) for x in g["paired_boot"][1:]]}',
                    'reproduces_published': match(g['ALL'][1], pub(f'ResBenchDelta{tok}OverBase')[1], 6e-4) and
                                            match(g['ALL'][2], pub(f'ResBenchDelta{tok}OverBase')[2], 6e-4),
                    'cluster': [round(lo, 6), round(hi, 6)], 'cluster_draws_dropped_no_measured_task': nbad,
                    'width_task': round(w, 6), 'width_cluster': round(hi - lo, 6),
                    'width_ratio': round((hi - lo) / w, 2), 'cluster_wider_than_1_5x': (hi - lo) / w > 1.5})
    ids2 = be['per']['IFC2X3']['ids']
    v = [done(rows[(2100, k)][t]) - done(rows982[t]) for t in ids2]
    entry(f'ResBenchDelta{tok}OverBaseTwoXThree', 2100, 'paired', f'{tok} minus untrained model, IFC2X3 (measured)',
          v, ids2, CL, boot(v), extra=paired_extra(rows[(2100, k)], rows982, ids2, CL))

# ---- hard validation set (300 tasks, 71 buildings), file order of val_hard_ids.json as in the exhibit script
vh_ids = json.load(open(ex.VALHARD_IDS))
VH = {json.loads(l)['task_id']: json.loads(l)['building_id'] for l in open(f'{ROOT}/runs_local/stage_b_v10/val_hard/val_hard_tasks.jsonl')}
vrows = {SFT: read_rows(f'{ex.DPO_VALHARD_ROWS}/per_task_{SFT}.jsonl', vh_ids),
         DPO: read_rows(f'{ex.DPO_VALHARD_ROWS}/per_task_{DPO}.jsonl', vh_ids),
         FINAL: read_rows(f'{ROOT}/runs_local/stage_c_v10/gates/valhard_v10b/per_task_{FINAL}.jsonl', vh_ids)}
for tok, a, b in (('Dpo', DPO, SFT), ('Grpo', FINAL, DPO)):
    v = [done(vrows[a][t]) - done(vrows[b][t]) for t in vh_ids]
    entry(f'ResValHard{tok}Delta', 'hard validation (300)', 'paired', f'{a} minus {b} on the hard validation set', v,
          vh_ids, VH, boot(v), tol=6e-5, extra=paired_extra(vrows[a], vrows[b], vh_ids, VH))

# ---- ten-building chain (macros_small_chain.tex): published rule = Python random, 2,000 resamples, seed 20261005


def small_ci(d, n=2000, seed=20261005):
    rnd = random.Random(seed)
    m = statistics.mean(d)
    bs = sorted(statistics.mean([d[rnd.randrange(len(d))] for _ in d]) for _ in range(n))
    return m, bs[int(0.025 * n)], bs[int(0.975 * n)]


small = {'Sft': rows[(2100, 'sft_small')], 'Dpo': rows[(2100, 'dpo_small')], 'Grpo': rows[(2100, 'grpo_small')]}
main = {'Sft': rows[(2100, 'sft')], 'Dpo': rows[(2100, 'dpo')], 'Grpo': rows[(2100, 'ours')]}
for tag in ('Sft', 'Dpo', 'Grpo'):
    v = [done(main[tag][t]) - done(small[tag][t]) for t in ALL]
    entry(f'ResSmall{tag}GapToMain', 2100, 'paired', f'full-corpus chain minus ten-building chain after {tag}', v, ALL,
          CL, small_ci(v), extra={'task_level_rule': 'Python random, 2,000 resamples, seed 20261005',
                                  **paired_extra(main[tag], small[tag], ALL, CL)})
for a, b, lab in (('Sft', 'Dpo', 'DpoOverSft'), ('Dpo', 'Grpo', 'GrpoOverDpo'), ('Sft', 'Grpo', 'GrpoOverSft')):
    v = [done(small[b][t]) - done(small[a][t]) for t in ALL]
    entry(f'ResSmallDelta{lab}', 2100, 'paired', f'ten-building chain, {b} minus {a}', v, ALL, CL, small_ci(v),
          extra={'task_level_rule': 'Python random, 2,000 resamples, seed 20261005',
                 **paired_extra(small[b], small[a], ALL, CL)})

out = {'method': {'completion': 'geometry, semantics and topology all >= 0.9 (make_results_exhibits.done)',
                  'task_level': 'percentile bootstrap over tasks, 10,000 resamples, seed 20260929, sorted[250] and '
                                'sorted[9749] (make_results_exhibits.boot), same task order as the exhibit script',
                  'cluster': 'resample the buildings of the task set with replacement (12 on the 2,100 set and the '
                             'subsets; 8 for IFC2X3 groups; 71 on the hard validation set), pool all tasks of every '
                             'drawn building, statistic = summed values / summed task counts; 10,000 resamples, seed '
                             '20260929, same index rule',
                  'not_computed': 'BIM-Edit paired intervals (ResBimEdit...): they need the BIM-Edit per-task records, which '
                                  'are not redistributed'},
       'entries': ENTRIES}
json.dump(out, open(f'{OUT}/cluster_boot.json', 'w'), indent=1)
bad = [e['macro'] for e in ENTRIES if not e['reproduces_published']]
print(f'{len(ENTRIES)} intervals; not reproduced: {bad}')
print(f'cluster wider than 1.5x: {sum(e["cluster_wider_than_1_5x"] for e in ENTRIES)}')
