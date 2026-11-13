#!/usr/bin/env python3
"""Breakdowns of the practitioners' requests for the proposed model (Supplementary Material).

  usage: make_macros_pracsplit.py CONFIG.json OUT.tex OUT.json

Reads config.json for the reported stage and its two runs on the 200 requests (with and without the candidate
list). The split of the requests by whether the text gives a unique name for every element (136 named, 64 other) is the
stored one of practitioner_requests/make_descriptor_split.py (results/descriptor_split.csv,
a property of the request, not of a model). The writer of each request and its operation come from the request file;
no request text is read into any output.

Methods: completion and wrong commit as in analysis/make_macros.py (done, end_class), which copy
make_results_exhibits.done and stats/failure_ends.end_class; per-writer completion as in
make_descriptor_split.py (rate over the requests of one writer, minimum and maximum over writers); the writer-level
interval is the mean of the five rates with the 95 % t-interval on 4 degrees of freedom.
"""
import collections, csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_macros as mm

PK = 'practitioner_requests/results'
SPLIT = f'{PK}/descriptor_split.csv'
REQ = f'{PK}/rewrite_tasks.jsonl'

cfg = json.load(open(sys.argv[1], encoding='utf-8')); out_tex, out_json = sys.argv[2], sys.argv[3]
rep = cfg['reported']
split = {r['task_id']: r['group'] for r in csv.DictReader(open(SPLIT, encoding='utf-8'))}
req = {}
for l in open(REQ, encoding='utf-8'):
    if l.strip():
        t = json.loads(l); req[t['task_id']] = (t['human_request']['respondent'], t['operation'])
ids = sorted(req)
if len(ids) != 200 or set(split) != set(ids):
    mm.fail(f'request file {len(ids)} requests, split file {len(split)}: wanted the same 200')
grp = collections.Counter(split.values())
if set(grp) != {'identified', 'described'}:
    mm.fail(f'groups of the split file: {dict(grp)}')
writers = collections.Counter(w for w, _ in req.values())
if len(writers) != 5 or set(writers.values()) != {40}:
    mm.fail(f'writers: {dict(writers)}, wanted 5 with 40 requests each')


def load(path, label):
    rows = mm.read_jsonl_rows(path, label)
    if set(rows) != set(ids):
        mm.fail(f'{label}: {len(rows)} rows, {len(set(rows) ^ set(ids))} ids differ from the 200 requests')
    bad = [t for t in ids if not isinstance(rows[t].get('score'), dict) or any(k not in rows[t]['score'] for k in mm.AX)]
    if bad:
        mm.fail(f'{label}: {len(bad)} rows without a score')
    return rows


with_list = load(cfg['reads']['prac'][rep], 'proposed model, 200 requests, with the candidate list')
no_list = load(cfg['reads']['prac_nolist'][rep], 'proposed model, 200 requests, without the candidate list')
V, M = {}, []


def put(name, val, shown, src):
    V[name] = val; M.append(f'\\newcommand{{\\{name}}}{{{shown}}}  % {src}')


src = f'{os.path.basename(cfg["reads"]["prac"][rep])}, split of descriptor_split.csv'
for g, key in (('identified', 'Named'), ('described', 'Other')):
    sub = [t for t in ids if split[t] == g]
    d = sum(int(mm.done(with_list[t])) for t in sub)
    w = sum(1 for t in sub if mm.end_class(with_list[t]) == 'wrong_commit')
    put(f'PmPrac{key}N', len(sub), len(sub), 'requests of the group')
    put(f'PmPrac{key}Done', d, d, src)
    put(f'PmPrac{key}Comp', d / len(sub), f'{d / len(sub):.3f}', src)
    put(f'PmPrac{key}WrongCommit', w, w, src)
per = collections.defaultdict(lambda: [0, 0])
for t in ids:
    per[req[t][0]][0] += int(mm.done(with_list[t])); per[req[t][0]][1] += 1
rates = {w: v[0] / v[1] for w, v in per.items()}
src = f'{os.path.basename(cfg["reads"]["prac"][rep])}, by writer (5 writers, 40 requests each)'
put('PmPracWriterMin', min(rates.values()), f'{min(rates.values()):.3f}', src)
put('PmPracWriterMax', max(rates.values()), f'{max(rates.values()):.3f}', src)
put('PmPracWriterMinDone', min(v[0] for v in per.values()), min(v[0] for v in per.values()), src)
put('PmPracWriterMaxDone', max(v[0] for v in per.values()), max(v[0] for v in per.values()), src)
V['per_writer_done_sorted'] = sorted(v[0] for v in per.values())      # counts only, no writer identity
# writer-level interval: the five writers are the units; mean of their rates and the 95 % t-interval with 4 degrees of freedom
import statistics
from scipy import stats as _st
_r = sorted(rates.values()); _m = statistics.mean(_r); _se = statistics.stdev(_r) / len(_r) ** 0.5
_t = float(_st.t.ppf(0.975, len(_r) - 1))
put('PmPracWriterMean', _m, f'{_m:.3f}', src + ', mean of the five writers\' rates')
put('PmPracWriterTLo', _m - _t * _se, f'{_m - _t * _se:.3f}', src + ', 95 % t-interval over the five writers, lower')
put('PmPracWriterTHi', _m + _t * _se, f'{_m + _t * _se:.3f}', src + ', 95 % t-interval over the five writers, upper')
src = f'{os.path.basename(cfg["reads"]["prac_nolist"][rep])} (run without the candidate list)'
w = sum(1 for t in ids if mm.end_class(no_list[t]) == 'wrong_commit')
put('PmPracNoListEndWrongCommit', w, w, src)
for op, key in (('create', 'Create'), ('update', 'Update'), ('delete', 'Delete')):
    sub = [t for t in ids if req[t][1] == op]
    d = sum(int(mm.done(no_list[t])) for t in sub)
    put(f'PmPracNoList{key}Done', d, d, src); V[f'PmPracNoList{key}N'] = len(sub)
# cross-checks against the values the main generator wrote
V['check_total_done_with_list'] = sum(int(mm.done(with_list[t])) for t in ids)
V['check_total_done_no_list'] = sum(int(mm.done(no_list[t])) for t in ids)
V['check_wrong_commit_with_list'] = sum(1 for t in ids if mm.end_class(with_list[t]) == 'wrong_commit')
V['check_done_by_operation_with_list'] = {op: sum(int(mm.done(with_list[t])) for t in ids if req[t][1] == op) for op in ('create', 'update', 'delete')}
head = ['% GENERATED by analysis/make_macros_pracsplit.py; do not edit by hand.',
        f'% reported stage: {rep}; inputs: {cfg["reads"]["prac"][rep]} and {cfg["reads"]["prac_nolist"][rep]}',
        '% split of the requests: practitioner_requests/results/descriptor_split.csv']
open(out_tex, 'w', encoding='utf-8').write('\n'.join(head + M) + '\n')
json.dump(V, open(out_json, 'w', encoding='utf-8'), indent=1)
print(f'wrote {len(M)} macros to {out_tex}')
print(json.dumps({k: v for k, v in V.items() if k.startswith('check_')}))
