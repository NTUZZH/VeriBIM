#!/usr/bin/env python3
"""Write the result tables from results/all_results.json (written by run_stats.py).

results/comparisons.csv   one row per comparison and method (interval or test), with significance at 0.05
results/agreement.csv     one row per comparison: significance by each method and the methods that disagree
results/holm.csv          raw and Holm-adjusted p-values, primary family and secondary (documented) family
results/mixed_effects.csv one row per comparison and mixed or marginal model
"""
import csv, json, math, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / 'results'
A = json.load(open(OUT / 'all_results.json'))
CMP = A['comparisons']

MODEL_KEYS = {
    'building random intercept (ML, quadrature)': 'glmm_building',
    'building and sampling-cell random intercepts (ML, Laplace)': 'glmm_building_cell',
    'building and task random intercepts (ML, quadrature)': 'glmm_building_task',
    'GEE, exchangeable within building, bias-reduced SE (Mancl-DeRouen)': 'gee_building_bias_reduced',
}
# methods that enter the agreement check (the conditional difference interval is dual to the exact test)
AGREE = ['bootstrap_task_95', 'bootstrap_building_95', 'mcnemar_exact', 'mcnemar_midp', 'mcnemar_asymptotic',
         'tango_score_95', 'newcombe_score_95', 'bonett_price_95', 'exact_conditional_odds_ratio_95',
         'midp_conditional_odds_ratio_95', 'glmm_building', 'glmm_building_cell', 'glmm_building_task',
         'gee_building_bias_reduced']


def excl(lo, hi, null=0.0):
    return bool(lo > null or hi < null)


def fit_by(e, name):
    for f in e.get('models', []):
        if f.get('model') == name:
            return f
    return None


def separated(f):
    b1, se = f.get('beta1'), f.get('se_beta1')
    return bool(f.get('separation') or b1 is None or se is None or not math.isfinite(se) or abs(b1) > 12 or se > 5)


def method_rows(e):
    m = e['methods95']
    R = []
    d = e['methods95']['diff']
    bt, bb = e['bootstrap_task'], e['bootstrap_building']
    R.append(('bootstrap_task_95', 'difference', d, bt[1], bt[2], None, excl(bt[1], bt[2]), e['bootstrap_rule'] + ' (published)'))
    R.append(('bootstrap_building_95', 'difference', d, bb[0], bb[1], None, excl(bb[0], bb[1]),
              'buildings resampled with replacement, all tasks of a drawn building kept (published)'))
    for k, lab in (('mcnemar_exact_p', 'mcnemar_exact'), ('mcnemar_midp_p', 'mcnemar_midp'), ('mcnemar_asymptotic_p', 'mcnemar_asymptotic')):
        R.append((lab, 'p-value', None, None, None, m[k], m[k] < 0.05, ''))
    for k, lab in (('tango', 'tango_score_95'), ('newcombe', 'newcombe_score_95'), ('bonett_price', 'bonett_price_95')):
        lo, hi = m[k]
        R.append((lab, 'difference', d, lo, hi, None, excl(lo, hi), ''))
    orr = m['odds_ratio']
    for k, lab in (('exact_conditional_or', 'exact_conditional_odds_ratio_95'), ('midp_conditional_or', 'midp_conditional_odds_ratio_95')):
        lo, hi = m[k]
        R.append((lab, 'paired odds ratio b/c', orr, lo, hi, None, excl(lo, hi, 1.0) if e['b'] + e['c'] > 0 else False, ''))
    lo, hi = m['exact_conditional_diff']
    R.append(('exact_conditional_difference_95', 'difference', d, lo, hi, None, excl(lo, hi),
              'Clopper-Pearson for b/(b+c) mapped to the difference with b+c held fixed; undercovers (see report)'))
    for name, lab in MODEL_KEYS.items():
        f = fit_by(e, name)
        if f is None or 'error' in f:
            R.append((lab, 'odds ratio', None, None, None, None, None, 'fit failed: ' + (f or {}).get('error', 'missing')))
            continue
        if separated(f):
            p = f.get('lr_p')
            R.append((lab, 'odds ratio', None, None, None, p, None,
                      'separation or near separation (|beta| > 12 or SE > 5): odds ratio not estimable and significance not '
                      'assessed' + (f'; likelihood-ratio p {p:.3g} shown for information only' if p is not None else '')))
        elif 'lr_p' in f:
            # mixed models: significance from the likelihood-ratio test (the Wald test is unreliable for large effects)
            R.append((lab, 'odds ratio', f['odds_ratio'], f['or_lo'], f['or_hi'], f['lr_p'], f['lr_p'] < 0.05,
                      f"likelihood-ratio p; Wald p {f['wald_p']:.3g} (95 % CI of the odds ratio is the Wald interval)"))
        else:
            R.append((lab, 'odds ratio', f['odds_ratio'], f['or_lo'], f['or_hi'], f['wald_p'], f['wald_p'] < 0.05,
                      f"Wald p with bias-reduced SE; working correlation {f.get('working_correlation', float('nan')):.3f}"))
    return R


def g(x, nd=6):
    if x is None:
        return ''
    if isinstance(x, float):
        if math.isinf(x):
            return 'inf'
        if math.isnan(x):
            return ''
        if x != 0 and abs(x) < 1e-4:
            return f'{x:.3e}'
        return f'{x:.{nd}f}'.rstrip('0').rstrip('.') if '.' in f'{x:.{nd}f}' else f'{x}'
    return str(x)


head = ['comparison_id', 'section', 'label', 'arm_A', 'arm_B', 'n_tasks', 'n_buildings', 'A_completed', 'B_completed',
        'both_completed', 'b_A_only', 'c_B_only', 'both_failed']
with open(OUT / 'comparisons.csv', 'w', newline='') as f, open(OUT / 'agreement.csv', 'w', newline='') as fa:
    w = csv.writer(f)
    w.writerow(head + ['method', 'statistic', 'estimate', 'ci_lo', 'ci_hi', 'p_value', 'significant_0.05', 'note'])
    wa = csv.writer(fa)
    wa.writerow(['comparison_id', 'label', 'n_tasks', 'b_A_only', 'c_B_only'] + AGREE + ['all_agree', 'methods_in_minority'])
    for cid, e in CMP.items():
        base = [cid, e['section'], e['label'], e['a_label'], e['b_label'], e['n'], e['n_buildings'], e['a_done'], e['b_done'],
                e['n11'], e['b'], e['c'], e['n22']]
        rows = method_rows(e)
        for r in rows:
            w.writerow(base + [r[0], r[1], g(r[2]), g(r[3]), g(r[4]), g(r[5]), '' if r[6] is None else r[6], r[7]])
        if 'equivalence_margin_0.05' in e:
            q = e['equivalence_margin_0.05']
            for k in ('bootstrap_90', 'tango_90', 'newcombe_90'):
                w.writerow(base + [f'{k}_equivalence', 'difference', g(e['methods95']['diff']), g(q[k][0]), g(q[k][1]), '',
                                   '', f"inside (-0.05, 0.05): {q['inside'][k]}"])
            w.writerow(base + ['tost_tango_score', 'p-value', '', '', '', g(q['tost_p_tango']), q['tost_p_tango'] < 0.05,
                               'two one-sided Tango score tests at -0.05 and +0.05; significant = equivalence shown'])
        sig = {r[0]: r[6] for r in rows}
        vals = [sig.get(k) for k in AGREE]
        known = [v for v in vals if v is not None]
        maj = sum(known) * 2 >= len(known)
        minority = [k for k, v in zip(AGREE, vals) if v is not None and v != maj]
        wa.writerow([cid, e['label'], e['n'], e['b'], e['c']] + ['' if v is None else v for v in vals] +
                    [not minority, ';'.join(minority)])

# ---------------------------------------------------------------- Holm
FAMS = [('primary', 'final model against the four commercial models with the library note, 108-task subset (the family of Section 4.6)'),
        ('documented', 'secondary: final model against the commercial models with the documented library (five models, and GPT-5.6 also with reasoning on), 108-task subset')]
PCOLS = [('exact McNemar', lambda e: e['methods95']['mcnemar_exact_p']),
         ('mid-p McNemar', lambda e: e['methods95']['mcnemar_midp_p']),
         ('GLMM building, Wald', lambda e: (fit_by(e, 'building random intercept (ML, quadrature)') or {}).get('wald_p')),
         ('GLMM building and task, likelihood ratio', lambda e: (fit_by(e, 'building and task random intercepts (ML, quadrature)') or {}).get('lr_p')),
         ('GLMM building, likelihood ratio', lambda e: (fit_by(e, 'building random intercept (ML, quadrature)') or {}).get('lr_p')),
         ('GEE bias-reduced', lambda e: (fit_by(e, 'GEE, exchangeable within building, bias-reduced SE (Mancl-DeRouen)') or {}).get('wald_p'))]


def holm(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj, order


with open(OUT / 'holm.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['family', 'family_description', 'comparison_id', 'label', 'b_A_only', 'c_B_only', 'difference',
                'test', 'raw_p', 'holm_rank', 'holm_multiplier', 'holm_adjusted_p', 'significant_after_holm_0.05'])
    for fam, desc in FAMS:
        es = [(cid, e) for cid, e in CMP.items() if e.get('family') == fam]
        for test, fn in PCOLS:
            ps = [fn(e) for _, e in es]
            if any(p is None or (isinstance(p, float) and math.isnan(p)) for p in ps):
                continue
            adj, order = holm(ps)
            for rank, i in enumerate(order):
                cid, e = es[i]
                w.writerow([fam, desc, cid, e['label'], e['b'], e['c'], g(e['methods95']['diff']), test, g(ps[i], 10),
                            rank + 1, len(ps) - rank, g(adj[i], 10), adj[i] < 0.05])

# ---------------------------------------------------------------- mixed models
cols = ['comparison_id', 'label', 'n_tasks', 'b_A_only', 'c_B_only', 'model', 'beta_arm', 'se_beta_arm', 'odds_ratio',
        'or_ci_lo', 'or_ci_hi', 'wald_p', 'likelihood_ratio_p', 'var_building', 'var_cell', 'var_task',
        'variance_at_boundary', 'separation_flag', 'n_obs', 'n_groups', 'working_correlation', 'note']
with open(OUT / 'mixed_effects.csv', 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(cols)
    for cid, e in CMP.items():
        for m in e.get('models', []):
            if 'error' in m:
                w.writerow([cid, e['label'], e['n'], e['b'], e['c'], m.get('model')] + [''] * 15 + [m['error']])
                continue
            w.writerow([cid, e['label'], e['n'], e['b'], e['c'], m['model'], g(m.get('beta1')), g(m.get('se_beta1')),
                        g(m.get('odds_ratio')), g(m.get('or_lo')), g(m.get('or_hi')), g(m.get('wald_p')), g(m.get('lr_p')),
                        g(m.get('var_building')), g(m.get('var_cell')), g(m.get('var_task')),
                        ';'.join(m.get('boundary_variance', [])), separated(m), m.get('n_obs', ''),
                        json.dumps(m.get('n_groups', '')), g(m.get('working_correlation')),
                        (m.get('prior', '') + ' ' + ';'.join(m.get('warnings', []))).strip()])
print('wrote comparisons.csv, agreement.csv, holm.csv, mixed_effects.csv')
