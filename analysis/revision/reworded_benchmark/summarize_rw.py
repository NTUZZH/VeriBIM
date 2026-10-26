"""Pair the reads on the 172 reworded benchmark instructions with the same tasks in their generated wording.

Completion rule as every gate summary: geometry, semantics and topology all >= 0.90 (family reading).
  model rows, reworded: reads/model/per_task_<model>.jsonl  (read_model_rw.sh / read_model_rw_adapter.sh)
  model rows, generated wording: runs_local/bench_v4/results/full_all/per_task_<model>.jsonl (stored 2,100-task reads,
      v4d/v4e state), restricted to the 172 original ids
  parser, reworded: reads/parser/per_task_parser_rw.jsonl (172 tasks)
  parser, generated wording: reads/parser/per_task_parser_original.jsonl (the 200 drawn tasks, v4d ground truth)
Statistics: exact two-sided McNemar (binomial on the discordant pairs), Wilson 95% intervals.
Writes reads/pairing_summary.json (reads/summary_rw.json is the earlier grpo-only pairing; its script is reads/summarize_rw.py.v1_20261019).
A model whose reworded read has no DONE marker is reported as missing, never estimated.
"""
import collections, json, math, os, re
P = '.'; W = P + '/analysis/revision/reworded_benchmark'
FULL = P + '/runs_local/bench_v4/results/full_all'
MODELS = ['grpo_v10b_c10', 'dpo_v10_c6', 'sft_v10']
Z = 1.959963984540054


def completed(r):
    sc = r.get('score') or {}
    return all(sc.get(k) is not None and sc.get(k) >= 0.9 for k in ('geometry', 'semantics', 'topology'))


def rows(path, strip=False):
    out = {}
    for l in open(path):
        if l.strip():
            r = json.loads(l); t = r['task_id']
            out[t[:-3] if strip and t.endswith('-rw') else t] = r
    return out


def wilson(k, n):
    if n == 0:
        return None
    p = k / n; d = 1 + Z * Z / n
    c = (p + Z * Z / (2 * n)) / d; h = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def cell(k, n):
    return {'n': n, 'completed': k, 'rate': round(k / n, 4) if n else None, 'wilson95': wilson(k, n)}


M = [json.loads(l) for l in open(W + '/mapping_original_to_reworded.jsonl')]
ids = [m['original_task_id'] for m in M]
T = {t['original_task_id']: t for t in map(json.loads, open(W + '/tasks_bench_rw.jsonl'))}
draw = json.load(open(W + '/draw_ids_200.json'))
D4 = {}
for l in open(P + '/runs_local/bench_v4/tasks.v4d.jsonl'):
    t = json.loads(l)
    if t['task_id'] in set(draw):
        D4[t['task_id']] = t
SL = {'operation': lambda t: t['operation'], 'category': lambda t: t['category'],
      'ifc_version': lambda t: t['ifc_version'], 'family': lambda t: t['family']}


def pair(og, rw, label, files, extra=None):
    oc = {i: completed(og[i]) for i in ids}; rc = {i: completed(rw[i]) for i in ids}
    c = collections.Counter((oc[i], rc[i]) for i in ids)
    b, cc = c[(True, False)], c[(False, True)]
    res = {'label': label, 'files': files, 'n': len(ids),
           'reworded': cell(sum(rc.values()), len(ids)), 'generated_wording': cell(sum(oc.values()), len(ids)),
           'both': c[(True, True)], 'only_generated_wording': b, 'only_reworded': cc, 'neither': c[(False, False)],
           'mcnemar_exact_p': round(mcnemar_exact(b, cc), 4),
           'difference_reworded_minus_generated': round((sum(rc.values()) - sum(oc.values())) / len(ids), 4),
           'by_slice': {}}
    for name, f in SL.items():
        g = collections.defaultdict(list)
        for i in ids:
            g[f(T[i])].append(i)
        res['by_slice'][name] = {k: {'n': len(v), 'reworded': sum(rc[i] for i in v), 'generated_wording': sum(oc[i] for i in v),
                                     'reworded_wilson95': wilson(sum(rc[i] for i in v), len(v)),
                                     'generated_wilson95': wilson(sum(oc[i] for i in v), len(v)),
                                     'mcnemar_exact_p': round(mcnemar_exact(sum(oc[i] and not rc[i] for i in v),
                                                                            sum(rc[i] and not oc[i] for i in v)), 4)}
                                 for k, v in sorted(g.items())}
    if extra:
        res.update(extra)
    return res, oc, rc


out = {'completion_rule': 'geometry, semantics and topology all >= 0.90 (family reading)',
       'statistics': 'exact two-sided McNemar on discordant pairs; Wilson 95% score intervals',
       'task_set': {'reworded_tasks': W + '/tasks_bench_rw.jsonl', 'n': len(ids)}, 'models': {}, 'missing': []}
fails = {}
for m in MODELS:
    frw = W + '/reads/model/per_task_%s.jsonl' % m; fog = FULL + '/per_task_%s.jsonl' % m
    if not (os.path.exists(W + '/reads/model/DONE_%s' % m) and os.path.exists(frw) and os.path.exists(fog)):
        out['missing'].append(m); continue
    rw, og = rows(frw, strip=True), rows(fog)
    assert sorted(rw) == sorted(ids), m
    summ = json.load(open(W + '/reads/model/summary_%s.json' % m))
    stops = collections.Counter(r.get('stop_reason') for r in rw.values())
    res, oc, rc = pair(og, rw, m, {'reworded': frw, 'generated_wording': fog},
                       {'reworded_stop_reasons': dict(stops), 'reworded_inference_errors': stops.get('inference_error', 0),
                        'reworded_resolved_agent_config': summ.get('resolved_agent_config'),
                        'reworded_sum_task_seconds': summ.get('wall_seconds')})
    out['models'][m] = res
    fails[m] = {'reworded': [i for i in ids if not rc[i]], 'generated_wording': [i for i in ids if not oc[i]], 'rw': rw, 'og': og}

# parser
prw, pog = rows(W + '/reads/parser/per_task_parser_rw.jsonl', strip=True), rows(W + '/reads/parser/per_task_parser_original.jsonl')
assert sorted(prw) == sorted(ids) and sorted(pog) == sorted(draw)
res, _, _ = pair(pog, prw, 'template parser', {'reworded': W + '/reads/parser/per_task_parser_rw.jsonl',
                                                'generated_wording': W + '/reads/parser/per_task_parser_original.jsonl'},
                 {'reworded_recognised': sum(bool(prw[i].get('recognised')) for i in ids),
                  'generated_wording_all_200': cell(sum(completed(pog[i]) for i in draw), len(draw)),
                  'generated_wording_all_200_recognised': sum(bool(pog[i].get('recognised')) for i in draw)})
out['parser'] = res

# failure lists of the final model
if 'grpo_v10b_c10' in fails:
    f = fails['grpo_v10b_c10']

    def info(i, r):
        sc = r.get('score') or {}
        return {'task_id': i, 'family': T[i]['family'], 'operation': T[i]['operation'], 'category': T[i]['category'],
                'edit_kind': T[i]['edit_kind'], 'ifc_version': T[i]['ifc_version'], 'stop_reason': r.get('stop_reason'),
                'tool_rounds': r.get('tool_rounds'),
                'score': {k: sc.get(k) for k in ('geometry', 'semantics', 'topology', 'final')}, 'score_error': r.get('score_error')}
    a, b = set(f['reworded']), set(f['generated_wording'])
    out['final_model_failures'] = {
        'reworded': [dict(info(i, f['rw'][i]), also_fails_generated_wording=i in b) for i in f['reworded']],
        'generated_wording': [dict(info(i, f['og'][i]), also_fails_reworded=i in a) for i in f['generated_wording']],
        'overlap': sorted(a & b), 'only_reworded': sorted(a - b), 'only_generated_wording': sorted(b - a)}

# wall-clock and file-access audit
log = open(W + '/reads/read_model_rw.log').read()
wc = {}
for m in MODELS:
    s = re.search(r'(\S+ \S+) START %s on' % m, log); e = re.search(r'(\S+ \S+) END %s rc=(\d+)' % m, log)
    if s and e:
        import datetime as dt
        f = lambda x: dt.datetime.strptime(x, '%Y-%m-%d %H:%M:%S')
        wc[m] = {'start': s.group(1), 'end': e.group(1), 'rc': int(e.group(2)), 'elapsed_minutes': round((f(e.group(1)) - f(s.group(1))).total_seconds() / 60, 1)}
    a = W + '/reads/model/fs_audit_%s.json' % m
    if os.path.exists(a):
        aj = json.load(open(a)); wc.setdefault(m, {})['fs_audit_json'] = a
        wc[m]['fs_audit_log'] = open(W + '/reads/model/fs_audit_%s.log' % m).read().strip()
        wc[m]['fs_audit_flagged'] = sum(len(v) if isinstance(v, (list, dict)) else 0 for v in aj.values()) if isinstance(aj, dict) else None
out['reads'] = wc
json.dump(out, open(W + '/reads/pairing_summary.json', 'w'), indent=1, ensure_ascii=False)
tbl = [(m, out['models'][m]) for m in out['models']] + [('parser', out['parser'])]
for m, r in tbl:
    print('%-14s rw %3d/%d %s  gen %3d/%d %s  both %d onlyGen %d onlyRw %d neither %d  p=%.4f' % (
        m, r['reworded']['completed'], r['n'], r['reworded']['wilson95'], r['generated_wording']['completed'], r['n'],
        r['generated_wording']['wilson95'], r['both'], r['only_generated_wording'], r['only_reworded'], r['neither'], r['mcnemar_exact_p']))
print('missing', out['missing'])
