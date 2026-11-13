#!/usr/bin/env python3
"""Completion of the reported model and of every arm without the deletion tasks that the orphan rule flags.

  usage: make_macros_orphans.py CONFIG.json OUT.tex OUT.json

The rule and its flagged tasks are those of the orphan analysis (results/benchmark/orphan_rule/orphans_summary.json,
key orphaning_task_ids); the tasks whose ground truth carries an error under the strict rule set come from the
summary file named in the configuration (tasks.clean_summary). The method is that of the orphan analysis: completion with and without the excluded tasks, a percentile bootstrap over tasks (10,000 resamples,
seed 20261018) for the interval, the shift per arm, and a count of arm pairs whose order changes. Arms: the three
stages of the reported run and the template parser on the benchmark, and every arm of the 108-task subset.
"""
import csv, json, os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_macros as mm

ROOT = ''
ORPH = ROOT + 'results/benchmark/orphan_rule/orphans_summary.json'
SEED, NBOOT = 20261018, 10000


def boot(x):
    x = np.asarray(x, float)
    rng = np.random.default_rng(SEED)
    m = np.sort(x[rng.integers(0, len(x), size=(NBOOT, len(x)))].mean(axis=1))
    return float(m[int(0.025 * NBOOT)]), float(m[int(0.975 * NBOOT) - 1])


def load(paths, ids, label):
    """Rows of one arm on the tasks `ids`; a file may hold more tasks (the parser file holds the whole benchmark)."""
    rows = {}
    for q in ([paths] if isinstance(paths, str) else list(paths)):
        r = mm.read_jsonl_rows(q, label)
        if set(r) & set(rows):
            mm.fail(f'{label}: a task occurs in more than one file')
        rows.update(r)
    miss = [t for t in ids if t not in rows]
    if miss:
        mm.fail(f'{label}: {len(miss)} of the {len(ids)} tasks are missing, for example {miss[:3]}')
    bad = [t for t in ids if not isinstance(rows[t].get('score'), dict) or any(k not in rows[t]['score'] for k in mm.AX)]
    if bad:
        mm.fail(f'{label}: {len(bad)} rows without a score, for example {bad[:3]}')
    return {t: rows[t] for t in ids}


cfg = json.load(open(sys.argv[1], encoding='utf-8')); out_tex, out_json = sys.argv[2], sys.argv[3]
S = json.load(open(ORPH, encoding='utf-8'))
orph = set(S['orphaning_task_ids'])
if len(orph) != S['orphaning_tasks']:
    mm.fail('the list of flagged tasks does not match its count')
strict = {r['task_id'] for r in csv.DictReader(open(cfg['tasks']['clean_summary'], encoding='utf-8')) if r[cfg['tasks']['clean_field']] == '1'}
bench = [json.loads(l)['task_id'] for l in open(cfg['tasks']['benchmark'], encoding='utf-8') if l.strip()]
sub108 = json.load(open(cfg['tasks']['subset108'], encoding='utf-8'))
if len(bench) != 2100 or len(set(bench)) != 2100 or len(sub108) != 108 or not orph <= set(bench) or not strict <= set(bench):
    mm.fail('task lists are not the expected ones')
rep = cfg['reported']
arms = []                                   # (set, label, ids, rows)
for st, path in cfg['reads']['bench'].items():
    arms.append(('2100', '@ours' if st == rep else f'stage {st}', bench, load(path, bench, f'benchmark, {st}')))
for a in cfg['arms']['bench']:
    arms.append(('2100', a['key'], bench, load(a['path'], bench, f"benchmark, {a['key']}")))
arms.append(('108', '@ours', sub108, load(cfg['reads']['sub108'][rep], sub108, '108-task subset, reported model')))
for a in cfg['arms']['sub108']:
    if a.get('path'):
        arms.append(('108', a['key'], sub108, load(a['path'], sub108, f"108-task subset, {a['key']}")))
excl = {'orphaning': orph, 'strict_or_orphaning': strict | orph}
recs = []
for sset, label, ids, rows in arms:
    d_all = [1 if mm.done(rows[t]) else 0 for t in ids]
    rec = {'set': sset, 'label': label, 'tasks': len(ids), 'completed': sum(d_all), 'completion': float(np.mean(d_all))}
    for name, ex in excl.items():
        keep = [t for t in ids if t not in ex]
        d = [1 if mm.done(rows[t]) else 0 for t in keep]
        rec[name] = {'tasks': len(keep), 'completed': sum(d), 'completion': float(np.mean(d)), 'ci95': boot(d),
                     'shift': float(np.mean(d)) - rec['completion']}
    flagged = [t for t in ids if t in orph]
    rec['on_flagged'] = {'tasks': len(flagged), 'completed': sum(1 for t in flagged if mm.done(rows[t]))}
    recs.append(rec)
changes = {}
for sset in ('2100', '108'):
    A = [r for r in recs if r['set'] == sset]; ch = []
    for i in range(len(A)):
        for j in range(i + 1, len(A)):
            s0 = np.sign(round(A[i]['completion'] - A[j]['completion'], 12))
            s1 = np.sign(round(A[i]['orphaning']['completion'] - A[j]['orphaning']['completion'], 12))
            if s0 != s1:
                ch.append({'a': A[i]['label'], 'b': A[j]['label'], 'kind': 'swap' if s0 * s1 < 0 else ('tie becomes order' if s0 == 0 else 'order becomes tie')})
    changes[sset] = {'arms': len(A), 'pairs': len(A) * (len(A) - 1) // 2, 'changed': ch, 'swaps': sum(1 for c in ch if c['kind'] == 'swap')}
ours = next(r for r in recs if r['set'] == '2100' and r['label'] == '@ours')
maxmove = max(abs(r['orphaning']['shift']) for r in recs)
who = [f"{r['set']}:{r['label']}" for r in recs if abs(r['orphaning']['shift']) == maxmove]
o = mm.Out(); o.section(9, 'Completion without the deletion tasks that the orphan rule flags')
src = 'reported model on the 2,100 benchmark tasks'
o.put('PmOrphTasks', mm.thou(len(orph)), len(orph), 'deletion tasks that the orphan rule flags (must equal the count in the Supplementary Material)')
o.put('PmOrphOursN', mm.thou(ours['orphaning']['tasks']), ours['orphaning']['tasks'], src + ', tasks without the flagged ones')
o.put('PmOrphOursDone', mm.thou(ours['orphaning']['completed']), ours['orphaning']['completed'], src + ', completed without the flagged ones')
o.put('PmOrphOursComp', mm.num(ours['orphaning']['completion']), ours['orphaning']['completion'], src + ', completion without the flagged ones')
o.put('PmOrphOursCompLo', mm.num(ours['orphaning']['ci95'][0]), ours['orphaning']['ci95'][0], 'lower bound, percentile bootstrap over tasks')
o.put('PmOrphOursCompHi', mm.num(ours['orphaning']['ci95'][1]), ours['orphaning']['ci95'][1], 'upper bound')
u = ours['strict_or_orphaning']
o.put('PmOrphUnionN', mm.thou(u['tasks']), u['tasks'], src + ', tasks without the flagged ones and without those with a strict-rule error')
o.put('PmOrphUnionDone', mm.thou(u['completed']), u['completed'], 'completed among them')
o.put('PmOrphUnionComp', mm.num(u['completion']), u['completion'], 'completion among them')
o.put('PmOrphOursFlaggedDone', mm.thou(ours['on_flagged']['completed']), ours['on_flagged']['completed'], 'flagged tasks that the reported model completes')
o.put('PmOrphMaxMove', mm.num(maxmove), maxmove, 'largest absolute change of completion of any arm when the flagged tasks are left out (benchmark arms and arms of the 108-task subset): ' + ', '.join(who))
o.put('PmOrphArms', str(len(recs)), len(recs), 'arms in this comparison')
o.put('PmOrphSwaps', str(changes['2100']['swaps'] + changes['108']['swaps']), changes['2100']['swaps'] + changes['108']['swaps'], 'pairs of arms whose order reverses')
lines = ['% Generated by analysis/make_macros_orphans.py (completion without the tasks that the orphan rule flags).']
lines += [l.split('  % ')[0] for l in o.lines if l.startswith('\\newcommand')]
open(out_tex, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
json.dump({'macros': o.vals, 'arms': recs, 'ordering': changes, 'flagged': len(orph), 'strict': len(strict), 'union': len(strict | orph)}, open(out_json, 'w', encoding='utf-8'), indent=1)
print('\n'.join(lines[1:]))
print(f"flagged {len(orph)}, strict {len(strict)}, union {len(strict | orph)}; ours all {ours['completed']}/{ours['tasks']}; on flagged {ours['on_flagged']}; largest move {maxmove:.4f} by {who}")
for k, v in changes.items():
    print(k, 'arms', v['arms'], 'pairs', v['pairs'], 'changed', len(v['changed']), 'swaps', v['swaps'], v['changed'][:4])
