"""Print one compact line per comparison from results/comparisons.csv (used to write report.md)."""
import csv, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
rows = collections.OrderedDict()
for r in csv.DictReader(open(HERE / 'results/comparisons.csv')):
    rows.setdefault(r['comparison_id'], {'_': r})[r['method']] = r


def iv(r, d=3):
    if not r or r['ci_lo'] == '':
        return 'n.e.'
    return f"[{float(r['ci_lo']):.{d}f}, {float(r['ci_hi']):.{d}f}]"


def p(r):
    if not r or r['p_value'] == '':
        return 'n.e.'
    x = float(r['p_value'])
    s = f'{x:.2g}' if x < 0.001 else f'{x:.3f}'
    return s + ('' if r['significant_0.05'] != '' else '*')


def orr(r):
    if not r or r['estimate'] == '':
        return 'n.e.'
    return f"{float(r['estimate']):.2f} {iv(r, 2)}"


print('| id | n | b | c | diff | task boot | bldg boot | exact p | mid-p | Tango 95 | Newcombe 95 | exact cond. OR | GLMM bldg OR, LR p | GLMM bldg+cell LR p | GLMM bldg+task LR p | GEE p |')
print('|' + '---|' * 16)
for cid, m in rows.items():
    r0 = m['_']
    d = float(m['tango_score_95']['estimate'])
    print(f"| {cid} | {r0['n_tasks']} | {r0['b_A_only']} | {r0['c_B_only']} | {d:+.3f} | {iv(m['bootstrap_task_95'])} | "
          f"{iv(m['bootstrap_building_95'])} | {p(m['mcnemar_exact'])} | {p(m['mcnemar_midp'])} | {iv(m['tango_score_95'])} | "
          f"{iv(m['newcombe_score_95'])} | {orr(m['exact_conditional_odds_ratio_95'])} | {orr(m['glmm_building'])}, {p(m['glmm_building'])} | "
          f"{p(m['glmm_building_cell'])} | {p(m['glmm_building_task'])} | {p(m['gee_building_bias_reduced'])} |")
