"""Macros of the practitioner study: aggregates only, no request text, no respondent attribute per person.
Sources: results_v4d/audit_summary.json and audit_agreement.csv (verdict audit on the repaired ground truths),
results_v4d/rewrite_responses.csv (respondent years and tools, aggregated), results/model/per_task_grpo_v10b_c10.jsonl
(the proposed model on the 200 requests), results/model/forensics_classes.csv (post hoc classification of the failures),
results/parser/per_task_parser_colleague.jsonl (template parser), runs_local/bench_v4/results/full_all (same tasks,
generator wording). Output: writing/tables/macros_practitioner.tex.
"""
import json, csv, collections, statistics, math, os
from scipy.stats import binomtest
ROOT = '.'; C = f'{ROOT}/analysis/revision/colleague_packets'
AX = ('geometry', 'semantics', 'topology')
def comp(r): s = r.get('score') or {}; return all(s.get(k) is not None and s[k] >= 0.9 for k in AX)
def fmt(x, nd=3): return f'{x:.{nd}f}'
def pct(x): return f'{100*x:.1f}'
M = []
def mac(name, val, note=''): M.append((name, str(val), note))
# respondents
resp = list(csv.DictReader(open(f'{C}/results_v4d/rewrite_responses.csv')))
people = {}
for r in resp: people[r['respondent']] = (float(r['years_experience']) if r['years_experience'] else None, r['tool'])
years = [y for y, _ in people.values() if y is not None]
WORDS={2:'two',3:'three',4:'four',5:'five',6:'six',7:'seven',8:'eight',9:'nine'}
mac('PracN', WORDS.get(len(people), len(people)), 'practitioners, spelled out for prose'); mac('PracNNum', len(people), 'practitioners, numeral')
mac('PracYearsMin', int(min(years))); mac('PracYearsMax', int(max(years))); mac('PracYearsMedian', int(statistics.median(years)) if statistics.median(years) == int(statistics.median(years)) else fmt(statistics.median(years), 1))
tools = collections.Counter(t for _, t in people.values()); mac('PracToolsN', len(set(x.strip() for t in tools for x in t.replace('/', ',').split(','))), 'distinct modelling tools named')
mac('PracRequests', len(resp)); mac('PracRequestsPer', len(resp) // len(people))
# proposed model on the 200 requests
rows = [json.loads(l) for l in open(f'{C}/results/model/per_task_grpo_v10b_c10.jsonl')]
n = len(rows); c = sum(comp(r) for r in rows)
mac('PracOursComp', fmt(c / n)); mac('PracOursCompN', c); mac('PracTasks', n)
p = c / n; z = 1.96; d = 1 + z * z / n; ce = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
mac('PracOursCompLo', fmt(ce - h)); mac('PracOursCompHi', fmt(ce + h), 'Wilson 95 %')
full = {json.loads(l)['task_id']: json.loads(l) for l in open(f'{ROOT}/runs_local/bench_v4/results/full_all/per_task_grpo_v10b_c10.jsonl')}
pairs = collections.Counter()
for r in rows:
    base = r['task_id'].rsplit('-B', 1)[0]; pairs[(comp(full[base]), comp(r))] += 1
gen_c = pairs[(True, True)] + pairs[(True, False)]
mac('PracGenComp', fmt(gen_c / n)); mac('PracGenCompN', gen_c, 'same 200 tasks, generator wording, finalized full_all')
mac('PracOnlyGen', pairs[(True, False)]); mac('PracOnlyPrac', pairs[(False, True)]); mac('PracBoth', pairs[(True, True)]); mac('PracNeither', pairs[(False, False)])
pv = binomtest(min(pairs[(True, False)], pairs[(False, True)]), pairs[(True, False)] + pairs[(False, True)], 0.5).pvalue
mac('PracMcNemarP', '< 0.001' if pv < 0.001 else fmt(pv), 'exact McNemar')
stop = collections.Counter(r.get('stop_reason') for r in rows)
mac('PracBudget', stop.get('budget_exhausted', 0)); mac('PracTruncated', stop.get('output_truncated', 0))
mac('PracAsked', sum(1 for r in rows if not r.get('committed') and r.get('stop_reason') == 'completed'))
mac('PracWrongCommit', sum(1 for r in rows if r.get('committed') and not comp(r)), 'committed edits that do not complete')
byop = collections.defaultdict(lambda: [0, 0])
for r in rows: op = r['task_id'].split('-')[1]; byop[op][0] += comp(r); byop[op][1] += 1
for op, nm in (('CRE', 'Create'), ('UPD', 'Update'), ('DEL', 'Delete')): mac(f'PracOurs{nm}', f'{byop[op][0]}/{byop[op][1]}')
# commercial models on the same 200 requests: documented-library arm and alone
# list prices (USD per million tokens) read from the PRICE table of hosted_cost.py; no silent fallback (an earlier
# fallback priced gpt-5.6-luna at the gpt-5.5 rate, which overstated PracGptUSD)
import re as _re, ast as _ast
_hc = open(f'{ROOT}/runs_local/bench_v4/hosted_cost.py').read()
PRICES = _ast.literal_eval(_re.sub(r'#[^\n]*', '', _re.search(r'PRICE = (\{.*?\n\})', _hc, _re.S).group(1)))
assert PRICES['claude-sonnet-5-5'] == (2.0, 10.0) and PRICES['gpt-5.6-luna'] == (0.20, 1.20), PRICES
for mid, nm, arm in (('claude-sonnet-5-5', 'Sonnet', 'informed'), ('gpt-5.6-luna', 'Gpt', 'informed'), ('claude-sonnet-5-5', 'SonnetAlone', 'alone'), ('gpt-5.6-luna', 'GptAlone', 'alone')):
    hp = f'{C}/results/hosted_{arm}/per_task_{mid}.jsonl'
    if not os.path.exists(hp): continue
    hr = [json.loads(l) for l in open(hp)]
    hc_ = sum(comp(r) for r in hr); mac(f'Prac{nm}CompN', hc_); mac(f'Prac{nm}Comp', fmt(hc_ / len(hr)))
    pp = collections.Counter((comp(rows_by[r['task_id']]), comp(r)) for r in hr) if (rows_by := {r['task_id']: r for r in rows}) else None
    mac(f'Prac{nm}OnlyThis', pp[(False, True)]); mac(f'Prac{nm}OnlyOurs', pp[(True, False)]); mac(f'Prac{nm}Both', pp[(True, True)]); mac(f'Prac{nm}Neither', pp[(False, False)])
    pv2 = binomtest(min(pp[(False, True)], pp[(True, False)]), pp[(False, True)] + pp[(True, False)], 0.5).pvalue
    mac(f'Prac{nm}McNemarP', '< 0.001' if pv2 < 0.001 else fmt(pv2), 'exact McNemar, this model vs the proposed model on the 200 requests')
    mac(f'Prac{nm}MinusOurs', fmt((hc_ - c) / len(hr)), 'difference in completion')
    ti = sum(r.get('input_tokens') or 0 for r in hr); to = sum(r.get('output_tokens') or 0 for r in hr)
    mac(f'Prac{nm}USD', f'{(ti * PRICES[mid][0] + to * PRICES[mid][1]) / 1e6:.0f}', f'list price, 200 requests, {arm} arm'); mac(f'Prac{nm}USDTwo', f'{(ti * PRICES[mid][0] + to * PRICES[mid][1]) / 1e6:.2f}', f'same, two decimals')
    mac(f'Prac{nm}Rounds', fmt(sum(r.get('tool_rounds') or 0 for r in hr) / len(hr), 2))
mac('PracOursRounds', fmt(sum(r.get('tool_rounds') or 0 for r in rows) / len(rows), 2))
# forensic classes
cls = collections.Counter(r['class'] for r in csv.DictReader(open(f'{C}/results/model/forensics_classes.csv')))
for k, nm in (('A', 'Ambiguous'), ('B', 'NotFound'), ('C', 'WrongEdit'), ('D', 'Asked'), ('E', 'Other')): mac(f'PracFail{nm}', cls[k])
mac('PracFailTotal', sum(cls.values()))
ident = n - cls['A']; mac('PracIdentifiable', ident); mac('PracOursCompIdent', fmt(c / ident), 'completion among requests that identify the target')
failtarget = cls['A'] + cls['B']; mac('PracFailTarget', failtarget, 'failures whose cause is target identification (ambiguous request or target not found)')
found = n - failtarget; mac('PracTargetFound', found, 'requests whose target the model identified (all requests minus the ambiguous ones and the not-found ones)')
mac('PracOursCompFound', fmt(c / found), 'completion among requests whose target the model identified')
mac('PracOursCompFoundN', c, 'same numerator as PracOursCompN')
# template parser
par = [json.loads(l) for l in open(f'{C}/results/parser/per_task_parser_colleague.jsonl')]
mac('PracParserRecognised', sum(1 for r in par if r.get('recognised') or r.get('recognized')), 'template parser, requests recognised')
mac('PracParserComp', sum(comp(r) for r in par))
# verdict audit (v4d)
s = json.load(open(f'{C}/results_v4d/audit_summary.json'))
mac('AuditCases', 60); mac('AuditAnswers', s['n_rows'])
mac('AuditFleissQone', fmt(s['q1_fleiss_kappa'], 2)); mac('AuditFleissQthree', fmt(s['q3_fleiss_kappa'], 2))
m = s['q1_majority_vs_checker']
for arm, nm in (('all', 'All'), ('veribim', 'Ours'), ('commercial', 'Commercial'), ('base', 'Base')):
    t = m[arm]['table']; agree = t['human_correct_checker_completed'] + t['human_not_correct_checker_not_completed']
    mac(f'Audit{nm}N', m[arm]['n']); mac(f'Audit{nm}Agree', agree)
    mac(f'Audit{nm}Kappa', fmt(m[arm]['cohen_kappa'], 2)); lo, hi = m[arm]['cohen_kappa_bootstrap_95']; mac(f'Audit{nm}KappaLo', fmt(lo, 2)); mac(f'Audit{nm}KappaHi', fmt(hi, 2))
    mac(f'Audit{nm}Sens', fmt(m[arm]['sensitivity'], 2)); mac(f'Audit{nm}Spec', fmt(m[arm]['specificity'], 2))
    mac(f'Audit{nm}HumanYesCheckerNo', t['human_correct_checker_not_completed']); mac(f'Audit{nm}HumanNoCheckerYes', t['human_not_correct_checker_completed'])
agr = list(csv.DictReader(open(f'{C}/results_v4d/audit_agreement.csv')))
unan = sum(1 for r in agr if r['q1_majority_share'] in ('1.0', '1', '1.00'))
mac('AuditUnanimous', unan, 'cases with a unanimous Q1 majority')
out = f'{ROOT}/writing/tables/macros_practitioner.tex'
with open(out, 'w') as f:
    f.write('% Generated by analysis/revision/colleague_packets/make_macros_practitioner.py (aggregates only).\n')
    for name, val, note in M: f.write(f'\\newcommand{{\\{name}}}{{{val}}}' + (f'  % {note}' if note else '') + '\n')
print(len(M), 'macros ->', out)
for name, val, note in M: print(f'{name:28s} {val:10s} {note}')
