#!/usr/bin/env python3
"""Numbers of the second set of practitioners' requests and of both sets together.

  usage: make_macros_set2.py --config CONFIG.json --props1 FIRST.csv --props2 SECOND.csv
                             --a2 PER_TASK --b2 PER_TASK --c2 PER_TASK --out-tex OUT.tex --out-json OUT.json
                             [--out-tables DIR]   (also writes tab_v11_pracsets.tex and tab_v11_pracwriters.tex)
         make_macros_set2.py --config CONFIG.json --props1 FIRST.csv --check-first MACRO_DIR

Three arms on each set, every request read once: A the reported model with the candidate list, B the reported model
without it, C the untrained base model with the documented library. The first set's per-task files come from the
config (reads.prac, reads.prac_nolist, arms.prac BaseDoc); the second set's are given on the command line. PROPS files
are written by analysis/inputs_not_released/request_properties.py (writer, operation, building, schema version, name group, list
coverage). No request text is read.

Stems: PmFirst (the first 200 requests, written only as a cross-check and into the JSON), PmSecond (the second set),
PmBoth (all requests). For each stem: completion of the three arms with the Wilson interval of the first set's rule
and the building-level bootstrap; the paired differences A minus C and A minus B (task bootstrap, building bootstrap,
Tango interval, exact McNemar test), all by analysis/make_macros.py (summary, paired); how the runs of A and B
ended; completion of A by list coverage, by name group, by operation and by schema version; per-writer completion of
A (minimum, maximum, mean and t-interval over writers) and the per-writer difference A minus C. For the second set
against the first: the difference in completion of each arm with the Newcombe interval for two independent
proportions and Fisher's exact test.

--check-first: computes the PmFirst block and compares every value whose name exists as PmPrac<suffix> in the macro
files of MACRO_DIR (macros_*.tex); exits 1 on any difference.
"""
import argparse, collections, csv, glob, json, math, os, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_macros as mm
import prac_failures as pf
from scipy import stats as st

VTOK = {'IFC2X3': 'TwoXThree', 'IFC4': 'Four', 'IFC4X3': 'FourXThree'}


class Clusters:
    """The part of make_macros.Ctx that summary() and paired() use: building of each task."""
    def __init__(self, cl):
        self.CL = cl


def read_props(path, n=None):
    rows = {r['task_id']: r for r in csv.DictReader(open(path, encoding='utf-8'))}
    if n is not None and len(rows) != n:
        mm.fail(f'{path}: {len(rows)} requests, expected {n}')
    for r in rows.values():
        r['holds'] = int(r['holds']); r['in_list'] = int(r['in_list'])
        if r['holds'] != r['in_list']:
            mm.fail(f"{path}: {r['task_id']}: among the first ten candidates but not in the written list, or the reverse")
    return rows


def newcombe_indep(k1, n1, k2, n2, z=mm.Z_ARMS):
    """Newcombe (1998) hybrid score interval for p1 - p2 of two independent proportions (method 10)."""
    def wil(k, n):
        p = k / n; d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return c - h, c + h
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wil(k1, n1); l2, u2 = wil(k2, n2)
    return (p1 - p2 - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), p1 - p2 + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2))


def t_interval(vals):
    m = statistics.mean(vals); se = statistics.stdev(vals) / len(vals) ** 0.5
    t = float(st.t.ppf(0.975, len(vals) - 1))
    return m, m - t * se, m + t * se


def block(o, stem, what, ids, A, B, C_, props, gen=None):
    ids = sorted(ids)
    ctx = Clusters({t: props[t]['building_id'] for t in ids})
    o.section(len([l for l in o.lines if l.startswith('% =====')]) + 1, f'{what} ({len(ids)} requests)')
    writers = sorted({props[t]['writer'] for t in ids})
    o.put(f'{stem}Writers', len(writers), len(writers), f'{what}, practitioners who wrote the requests')
    arms = (('', A, 'reported model with the candidate list'), ('NoList', B, 'reported model without the candidate list'),
            ('BaseDoc', C_, 'untrained base model with the documented library'))
    S = {}
    for key, rows, lab in arms:
        s = mm.summary(rows, ids, ctx, cluster=True, ci='wilson_arms')
        mm.put_summary(o, stem + key, s, f'{what}, {lab}', '95 % Wilson interval (summarize_arms rule)')
        S[key] = s
    for key, other, lab in (('MinusBaseDoc', C_, 'minus the untrained base model with the documented library'),
                            ('ListMinusNoList', B, 'with minus without the candidate list')):
        P = mm.paired(A, other, ids, ctx, cluster=True)
        mm.put_paired(o, stem + key, P, f'{what}, reported model {lab}')
    mm.put_paired(o, stem + 'NoListMinusBaseDoc', mm.paired(B, C_, ids, ctx, cluster=True),
                  f'{what}, reported model without the candidate list minus the untrained base model with the documented library')
    if gen is not None:
        g = mm.summary(gen, ids, ctx, cluster=False, ci='wilson_arms')
        mm.put_summary(o, stem + 'Gen', g, f'{what}, the same edits in generator wording (benchmark read of the reported model)',
                       '95 % Wilson interval (summarize_arms rule)')
        mm.put_paired(o, stem + 'MinusGen', mm.paired(A, gen, ids, ctx, cluster=False), f'{what}, practitioners\' wording minus generator wording')
    # how the runs ended (make_macros.end_class)
    for key, rows, lab in arms[:2]:
        w = sum(1 for t in ids if mm.end_class(rows[t]) == 'wrong_commit')
        o.put(f'{stem}{key}EndWrongCommit', mm.thou(w), w, f'{what}, {lab}: requests that end with a committed edit the checker rejects')
        o.put(f'{stem}{key}WrongCommitPct', f'{100 * w / len(ids):.1f}', 100 * w / len(ids), f'{what}, {lab}: the same as a percentage')
    cnt = collections.Counter(mm.end_class(A[t]) for t in ids)
    for c in mm.END_CLASSES[1:]:
        if c != 'wrong_commit':      # written above for both arms
            o.put(f'{stem}End{mm.ENDTOK[c]}', mm.thou(cnt[c]), cnt[c], f'{what}, reported model with the list: requests ending as {c}')
    if sum(cnt[c] for c in mm.END_CLASSES[1:]) != sum(1 for t in ids if not mm.done(A[t])):
        sys.exit(f'STOPPED: {what}: the run-end classes do not add up to the uncompleted requests')
    # outcome classes of the uncompleted requests of the reported model with the list (prac_failures.outcome)
    failed = [t for t in ids if not mm.done(A[t])]
    out = collections.Counter(pf.outcome(A[t]) for t in failed)
    src = f'{what}, reported model with the list, uncompleted requests'
    o.put(f'{stem}FailTotal', mm.thou(len(failed)), len(failed), src)
    o.put(f'{stem}FailNotMatched', mm.thou(out['NotMatched']), out['NotMatched'], src + ': committed edit that matches no target element')
    o.put(f'{stem}FailPartly', mm.thou(out['PartlyMatched']), out['PartlyMatched'], src + ': committed edit that matches part of the targets')
    o.put(f'{stem}FailWrongEdit', mm.thou(out['MatchedWrongEdit']), out['MatchedWrongEdit'], src + ': every target matched, edit wrong')
    nc = out['NoCommitBudget'] + out['NoCommitTruncated'] + out['NoCommitOther']
    o.put(f'{stem}FailNoCommit', mm.thou(nc), nc, src + ': no committed file')
    com = sum(1 for t in ids if A[t].get('committed'))
    o.put(f'{stem}Committed', mm.thou(com), com, f'{what}, reported model with the list: requests with a committed file')
    # list coverage (prac_failures rule) and name group (make_descriptor_split rule), reported model with the list
    for key, sel, lab in (('ListHolds', [t for t in ids if props[t]['holds']], 'the list holds every required element'),
                          ('ListMisses', [t for t in ids if not props[t]['holds']], 'the list misses a required element'),
                          ('Named', [t for t in ids if props[t]['group'] == 'identified'], 'a unique name or identifier for every element'),
                          ('Other', [t for t in ids if props[t]['group'] == 'described'], 'at least one element described without a unique name')):
        d = int(sum(mm.done(A[t]) for t in sel))
        src = f'{what}, reported model with the list, requests where {lab}'
        o.put(f'{stem}{key}N', mm.thou(len(sel)), len(sel), src)
        if key.startswith('List'):
            o.put(f'{stem}Done{key}', mm.thou(d), d, src + ', completed')
            if sel:
                o.put(f'{stem}Comp{key}', mm.num(d / len(sel)), d / len(sel), src + ', completion')
        else:
            o.put(f'{stem}{key}Done', mm.thou(d), d, src + ', completed')
            if sel:
                o.put(f'{stem}{key}Comp', mm.num(d / len(sel)), d / len(sel), src + ', completion')
            w = sum(1 for t in sel if mm.end_class(A[t]) == 'wrong_commit')
            o.put(f'{stem}{key}WrongCommit', mm.thou(w), w, src + ', committed edits the checker rejects')
    hp = 100 * sum(props[t]['holds'] for t in ids) / len(ids)
    o.put(f'{stem}ListHoldsPct', f'{hp:.1f}', hp, f'{what}: share of requests whose list holds every required element, percent')
    # by operation and by schema version, reported model with the list
    for op in mm.OPS:
        sel = [t for t in ids if props[t]['operation'] == op]
        d = int(sum(mm.done(A[t]) for t in sel)); src = f'{what}, reported model with the list, {op} requests'
        o.put(f'{stem}{op.capitalize()}Done', mm.thou(d), d, src + ' completed')
        o.put(f'{stem}{op.capitalize()}N', mm.thou(len(sel)), len(sel), src)
        if sel:
            o.put(f'{stem}{op.capitalize()}Comp', mm.num(d / len(sel)), d / len(sel), src + ', completion')
    for v in mm.VERS:
        sel = [t for t in ids if props[t]['ifc_version'] == v]
        if sel:
            d = int(sum(mm.done(A[t]) for t in sel)); src = f'{what}, reported model with the list, {v} requests'
            o.put(f'{stem}Ver{VTOK[v]}N', mm.thou(len(sel)), len(sel), src)
            o.put(f'{stem}Ver{VTOK[v]}Comp', mm.num(d / len(sel)), d / len(sel), src + ', completion')
    # writers: completion of the reported model per writer, and its difference to the untrained base model per writer
    per = collections.defaultdict(lambda: [0, 0, 0, 0])
    for t in ids:
        p = per[props[t]['writer']]
        p[0] += int(mm.done(A[t])); p[1] += 1; p[2] += int(mm.done(C_[t])); p[3] += int(mm.done(B[t]))
    rates = sorted(v[0] / v[1] for v in per.values())
    src = f'{what}, reported model with the list, by writer ({len(per)} writers)'
    o.put(f'{stem}WriterMin', mm.num(rates[0]), rates[0], src + ', lowest completion')
    o.put(f'{stem}WriterMax', mm.num(rates[-1]), rates[-1], src + ', highest completion')
    m, lo, hi = t_interval(rates)
    o.put(f'{stem}WriterMean', mm.num(m), m, src + ', mean of the writers\' rates')
    o.put(f'{stem}WriterTLo', mm.num(lo), lo, src + f', 95 % t-interval over the writers ({len(per) - 1} degrees of freedom), lower')
    o.put(f'{stem}WriterTHi', mm.num(hi), hi, src + ', 95 % t-interval over the writers, upper')
    gains = sorted((v[0] - v[2]) / v[1] for v in per.values())
    m, lo, hi = t_interval(gains)
    src = f'{what}, reported model minus untrained base model with the documented library, by writer'
    lo_, hi_ = mm.bounds(lo, hi)
    o.put(f'{stem}WriterGainMean', mm.num(m), m, src + ', mean of the writers\' differences')
    o.put(f'{stem}WriterGainTLo', lo_, lo, src + ', 95 % t-interval over the writers, lower')
    o.put(f'{stem}WriterGainTHi', hi_, hi, src + ', 95 % t-interval over the writers, upper')
    o.put(f'{stem}WritersGainPos', sum(g > 0 for g in gains), sum(g > 0 for g in gains), src + ', writers with more completed by the reported model')
    o.put(f'{stem}WritersGainNeg', sum(g < 0 for g in gains), sum(g < 0 for g in gains), src + ', writers with fewer')
    # writers' years of experience, when every writer gave a number
    yrs = {}
    for t in ids:
        m = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*(?:\+|years?|yrs?)?\s*', str(props[t].get('years_experience') or ''), re.I)
        yrs[props[t]['writer']] = float(m.group(1)) if m else None
    if yrs and all(v is not None for v in yrs.values()):
        fmt = lambda x: str(int(x)) if float(x).is_integer() else f'{x:g}'
        src = f'{what}: writers\' years of experience as each writer gave it'
        o.put(f'{stem}YearsMin', fmt(min(yrs.values())), min(yrs.values()), src + ', minimum')
        o.put(f'{stem}YearsMax', fmt(max(yrs.values())), max(yrs.values()), src + ', maximum')
    else:
        o.skip(f'{stem}YearsMin and {stem}YearsMax', 'a writer gave no number of years: ' + str(sum(v is None for v in yrs.values())) + ' writers')
    per_n = sorted({v[1] for v in per.values()})
    if len(per_n) == 1:
        o.put(f'{stem}RequestsPer', per_n[0], per_n[0], f'{what}: requests of each writer')
    return {'summaries': S, 'per_writer_done_sorted': sorted(v[0] for v in per.values()), 'per_writer_gain_sorted': gains,
            'per_writer': {w: {'n': v[1], 'list': v[0], 'nolist': v[3], 'base': v[2]} for w, v in sorted(per.items())}}


ARMS3 = (('', 'list', r'\ModelName{}'), ('NoList', 'nolist', r'\ModelName{} without the candidate list'),
         ('BaseDoc', 'base', 'Untrained Qwen3.5-9B, documented library'))


def write_tables(folder, o, J):
    """Two table fragments for the Supplementary Material, written from the values of this run: completion by request
    set and arm (tab:pracsets) and completed requests by practitioner (tab:pracwriters). Bold is set here, on the
    counts: the best completion among the three arms in each column of the first table and in each row of the second."""
    v = lambda name: o.vals[name]['text']
    sets = (('PmSecond', 'Second set'), ('PmFirst', 'First set'), ('PmBoth', 'Both sets'))
    L = ['% GENERATED by analysis/make_macros_set2.py; do not edit by hand.',
         r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
         r"\caption{Completion of the practitioners' requests by request set and arm, with \CiLevelPct{}\,\% Wilson score intervals. "
         r'Bold marks the best completion in each column. A difference is given with its \CiLevelPct{}\,\% interval from a bootstrap over tasks and the exact McNemar $p$.}',
         r'\label{tab:pracsets}', r'\setlength{\tabcolsep}{4pt}',
         r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{4.3cm}lll@{}}', r'\toprule',
         'Arm & ' + ' & '.join(f"{lab}, {v(st_ + 'N')} requests" for st_, lab in sets) + r' \\', r'\midrule']
    best = {st_: max(o.vals[st_ + k + 'Done']['value'] if (st_ + k + 'Done') in o.vals else -1 for k, _, _ in ARMS3) for st_, _ in sets}
    for k, _, lab in ARMS3:
        cells = []
        for st_, _ in sets:
            c = v(st_ + k + 'Comp'); c = r'\textbf{' + c + '}' if o.vals[st_ + k + 'Done']['value'] == best[st_] else c
            cells.append(f"{c} [{v(st_ + k + 'CompLo')}, {v(st_ + k + 'CompHi')}]")
        L.append(lab + ' & ' + ' & '.join(cells) + r' \\')
    L.append(r'\midrule')
    for stem, lab in (('MinusBaseDoc', r'\ModelName{} minus the untrained model'), ('ListMinusNoList', 'With minus without the candidate list'),
                      ('NoListMinusBaseDoc', r'\ModelName{} without the candidate list minus the untrained model')):
        cells = []
        for st_, _ in sets:
            pv = v(st_ + stem + 'P'); pv = ('$p$~' + pv) if '<' in pv else ('$p = ' + pv + '$')
            cells.append(f"{v(st_ + stem)} [{v(st_ + stem + 'Lo')}, {v(st_ + stem + 'Hi')}], {pv}")
        L.append(lab + ' & ' + ' & '.join(cells) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}', r'\end{table}']
    open(os.path.join(folder, 'tab_v11_pracsets.tex'), 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    W = ['% GENERATED by analysis/make_macros_set2.py; do not edit by hand.',
         r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
         r'\caption{Completed requests by practitioner. Each practitioner wrote for a different block of tasks. Bold marks the best arm in each row.}',
         r'\label{tab:pracwriters}', r'\setlength{\tabcolsep}{5pt}',
         r'\begin{tabular}{@{}llr>{\raggedleft\arraybackslash}p{2.2cm}>{\raggedleft\arraybackslash}p{3.0cm}>{\raggedleft\arraybackslash}p{3.2cm}@{}}', r'\toprule',
         r'Set & Practitioner & Requests & \ModelName{} & \ModelName{} without the candidate list & Untrained Qwen3.5-9B, documented library \\', r'\midrule']
    num = 0

    def row(first, second, d):
        m = max(d['list'], d['nolist'], d['base'])
        f = lambda x: (r'\textbf{%d}' % x if x == m else str(x)) + f' ({mm.num(x / d["n"])})'
        return f"{first} & {second} & {d['n']} & {f(d['list'])} & {f(d['nolist'])} & {f(d['base'])} " + r'\\'
    for key, lab in (('first', 'First'), ('second', 'Second')):
        for i, (w, d) in enumerate(J[key]['per_writer'].items()):
            num += 1
            W.append(row(lab if i == 0 else '', str(num), d))
        W.append(r'\midrule')
    tot = {k: sum(d[k] for key in ('first', 'second') for d in J[key]['per_writer'].values()) for k in ('n', 'list', 'nolist', 'base')}
    W.append(row('Both', f'all {num}', tot))
    W += [r'\bottomrule', r'\end{tabular}', r'\end{table}']
    open(os.path.join(folder, 'tab_v11_pracwriters.tex'), 'w', encoding='utf-8').write('\n'.join(W) + '\n')
    for key in ('list', 'nolist', 'base'):
        arm = {'list': '', 'nolist': 'NoList', 'base': 'BaseDoc'}[key]
        if tot[key] != o.vals['PmBoth' + arm + 'Done']['value'] or tot['n'] != o.vals['PmBothN']['value']:
            mm.fail('the per-writer table does not add up to the totals of both sets')
    print(f'wrote tab_v11_pracsets.tex and tab_v11_pracwriters.tex to {folder} ({num} practitioners)')


def main():
    ap = argparse.ArgumentParser()
    for a in ('--config', '--props1', '--props2', '--a2', '--b2', '--c2', '--out-tex', '--out-json', '--check-first', '--out-tables'):
        ap.add_argument(a)
    args = ap.parse_args()
    cfg = json.load(open(args.config, encoding='utf-8')); rep = cfg['reported']
    p1 = read_props(args.props1, 200)
    ids1 = sorted(p1)
    a1 = mm.read_per_task(cfg['reads']['prac'][rep], ids1, 'first set, reported model with the list')
    b1 = mm.read_per_task(cfg['reads']['prac_nolist'][rep], ids1, 'first set, reported model without the list')
    base = next(x for x in cfg['arms']['prac'] if x['key'] == 'BaseDoc')
    c1 = mm.read_per_task(base['path'], ids1, 'first set, untrained base model with the documented library')
    bench = mm.read_jsonl_rows(cfg['reads']['bench'][rep], 'benchmark read of the reported model (generator wording)')
    if len(bench) != 2100:
        mm.fail(f'benchmark read: {len(bench)} rows, expected 2,100')
    gen_of = lambda props, ids: {t: bench[props[t]['base_task_id']] for t in ids}
    o = mm.Out()
    J = {'first': block(o, 'PmFirst', "first set of practitioners' requests", ids1, a1, b1, c1, p1, gen_of(p1, ids1))}
    if args.check_first:
        stored = {}
        for f in sorted(glob.glob(os.path.join(args.check_first, 'macros_*.tex'))):
            for m in re.finditer(r'\\newcommand\{\\(PmPrac[A-Za-z]*)\}\{(.*?)\}\s*(?:%.*)?$', open(f, encoding='utf-8').read(), re.M):
                stored[m.group(1)] = m.group(2)
        same, diff = 0, []
        for name, v in o.vals.items():
            old = stored.get('PmPrac' + name[len('PmFirst'):])
            if old is None:
                continue
            if old == v['text']:
                same += 1
            else:
                diff.append((name, v['text'], old))
        print(f'first set: {len(o.vals)} values computed, {same} equal to stored PmPrac macros, {len(diff)} different')
        for d in diff:
            print('  DIFFERENT', d)
        sys.exit(1 if diff or same < 30 else 0)
    p2 = read_props(args.props2)
    ids2 = sorted(p2)
    if set(ids1) & set(ids2):
        mm.fail('the two sets share request ids')
    a2 = mm.read_per_task(args.a2, ids2, 'second set, reported model with the list')
    b2 = mm.read_per_task(args.b2, ids2, 'second set, reported model without the list')
    c2 = mm.read_per_task(args.c2, ids2, 'second set, untrained base model with the documented library')
    J['second'] = block(o, 'PmSecond', "second set of practitioners' requests", ids2, a2, b2, c2, p2, gen_of(p2, ids2))
    both = {**p1, **p2}
    J['both'] = block(o, 'PmBoth', "both sets of practitioners' requests", ids1 + ids2,
                      {**a1, **a2}, {**b1, **b2}, {**c1, **c2}, both, gen_of(both, ids1 + ids2))
    if set(p1[t]['writer'] for t in ids1) & set(p2[t]['writer'] for t in ids2):
        mm.fail('a writer label occurs in both sets')
    # the second set against the first (independent requests, tasks and writers)
    o.section(4, 'Second set against the first set (independent proportions)')
    for key, lab in (('', 'reported model with the candidate list'), ('NoList', 'reported model without the candidate list'),
                     ('BaseDoc', 'untrained base model with the documented library')):
        s1, s2 = J['first']['summaries'][key], J['second']['summaries'][key]
        d = s2['comp'] - s1['comp']
        lo, hi = newcombe_indep(s2['done'], s2['n'], s1['done'], s1['n'])
        p = float(st.fisher_exact([[s2['done'], s2['n'] - s2['done']], [s1['done'], s1['n'] - s1['done']]])[1])
        lo_, hi_ = mm.bounds(lo, hi)
        src = f'{lab}: completion on the second set minus the first set'
        o.put(f'PmSecondMinusFirst{key}', mm.num(d), d, src)
        o.put(f'PmSecondMinusFirst{key}Lo', lo_, lo, src + ', 95 % Newcombe interval for independent proportions, lower')
        o.put(f'PmSecondMinusFirst{key}Hi', hi_, hi, src + ', upper')
        o.put(f'PmSecondMinusFirst{key}P', mm.fmt_p(p), p, src + ', Fisher exact test, two-sided')
    for k in ('first', 'second', 'both'):
        J[k]['summaries'] = {a: {x: s[x] for x in ('n', 'done', 'comp')} for a, s in J[k]['summaries'].items()}
    if args.out_tables:
        mm.guard_output(os.path.join(args.out_tables, 'tab_v11_pracsets.tex'))
        os.makedirs(args.out_tables, exist_ok=True)
        write_tables(args.out_tables, o, J)
    head = ['% GENERATED by analysis/make_macros_set2.py; do not edit by hand.',
            f'% reported stage: {rep}; inputs (label, rows, sha256, path):'] + \
           [f'%   {lab}: {n} rows, {h[:16]}, {p}' for lab, p, n, h in mm.INPUTS]
    keep = [l for l in o.lines]
    mm.guard_output(args.out_tex); mm.guard_output(args.out_json)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_tex)), exist_ok=True)
    open(args.out_tex, 'w', encoding='utf-8').write('\n'.join(head + keep) + '\n')
    json.dump({'macros': o.vals, 'detail': J}, open(args.out_json, 'w', encoding='utf-8'), indent=1, default=mm.jsonable)
    print(f'wrote {len(o.vals)} macros to {args.out_tex}')
    for k in ('first', 'second', 'both'):
        print(k, {a or 'A': f"{s['done']}/{s['n']}" for a, s in J[k]['summaries'].items()})


if __name__ == '__main__':
    try:
        main()
    except mm.GenError as e:
        print('STOPPED:', e); sys.exit(2)
