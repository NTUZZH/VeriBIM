#!/usr/bin/env python3
"""Generate macros_rev2.tex and the tables of the 2026-10-15 revision results into out/.

Every macro is computed from a result file (per-task rows, JSON, CSV) or, where no file holds the number, from a
pinned sentence of a task report that the script matches with a regular expression. Each output line carries a
comment naming its source, and out/CHECKS.md lists every macro with the raw value, the file and the key.

Conventions (as in writing/tables/make_results_exhibits.py and manuscript/build_v10/make_macros_rev.py):
  completion   geometry, semantics and topology all >= 0.9 (make_results_exhibits.done)
  task-level   percentile bootstrap over tasks, 10,000 resamples, seed 20260929, sorted[250] / sorted[9749]
               (make_results_exhibits.boot); tasks in sorted id order unless stated
  building     cluster bootstrap over buildings (analysis/revision/stats/common.cboot)
  Tango        score interval for a paired difference (analysis/revision/stats/paired_methods.tango)
  exact p      two-sided exact McNemar test (paired_methods.mcnemar_exact)
  list price   input tokens x input price + output tokens x output price, prices of runs_local/bench_v4/hosted_cost.py,
               no prompt-cache discount (the rule of this revision for every commercial cost)
  numbers      three decimals for proportions, negative values as $-$0.119, thousands separators

Inputs are read-only. Outputs: out/macros_rev2.tex, out/macros_cost_listprice.tex, out/tab_*_rev.tex,
out/tab6_cost.tex, out/CHECKS.md, out/values.json.

Run (from the project root):
    taskset -c 16-23 env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
        python analysis/revision/macros/make_macros_rev2.py
"""
import ast, csv, glob, json, math, os, re, statistics, sys, warnings
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'out'
OUT.mkdir(exist_ok=True)
REV = ROOT / 'analysis/revision'
REV07 = ROOT / 'analysis/revision'
RES = ROOT / 'runs_local/bench_v4/results'
sys.path.insert(0, str(ROOT / 'writing/tables'))
sys.path.insert(0, str(REV07 / 'stats'))
sys.path.insert(0, str(REV / 'stats'))
import numpy as np                            # noqa: E402
import make_results_exhibits as ex            # noqa: E402  (import has no side effects; main() is guarded)
import common as C                            # noqa: E402
import paired_methods as PM                   # noqa: E402
import glmm_ml as G                           # noqa: E402

assert ex.SEED == 20260929 and ex.R == 10000
done = ex.done


def rel(p):
    return str(Path(p).resolve().relative_to(ROOT))


# ---------------------------------------------------------------- output helpers
LINES, CHECKS, VALUES = [], [], {}
DROPIN = []          # \renewcommand lines of macros_cost_listprice.tex
DROPCHK = []


def num(x, d=3):
    """Manuscript convention: no plus sign, negative as $-$, fixed decimals."""
    s = f'{abs(x):.{d}f}'
    return ('$-$' + s) if round(x, d) < 0 else s


def pct(k, n):
    """Integer percent of k out of n, rounded half up on the exact fraction."""
    return str((200 * k + n) // (2 * n))


def thou(n):
    return f'{int(round(n)):,}'


def fmt_p(p):
    """Fixed notation with two significant digits (two decimals at 0.1 and above) down to 0.0001; below that the bound."""
    if p >= 0.995:
        return '1.00'
    if p < 1e-4:
        return '$<$0.0001'
    for lim, d in ((0.1, 2), (0.01, 3), (0.001, 4), (1e-4, 5)):
        if p >= lim:
            return f'{p:.{d}f}'


def fmt_p_sci(p):
    """Two significant digits; scientific form below 0.001."""
    if p >= 1e-3:
        return fmt_p(p)
    m, e = f'{p:.1e}'.split('e')
    return f'${m}\\times10^{{{int(e)}}}$'


def put(name, value, src, raw=None):
    assert re.fullmatch(r'[A-Za-z]+', name), name
    assert name not in VALUES, f'duplicate macro {name}'
    VALUES[name] = str(value)
    LINES.append(f'\\newcommand{{\\{name}}}{{{value}}}  % {src}')
    CHECKS.append((name, str(value), '' if raw is None else repr(raw) if not isinstance(raw, float) else f'{raw:.6g}', src))


def section(title):
    LINES.append(f'% ---------------------------------------------------------------- {title}')
    CHECKS.append(('##', title, '', ''))


def grab(pattern, text, src, group=1, flags=0):
    m = re.search(pattern, text, flags)
    assert m, f'pattern not found in {src}: {pattern}'
    return m.group(group)


# ---------------------------------------------------------------- existing macros (read-only), for reproduction and collisions
def read_macros(paths):
    M = {}
    for p in paths:
        for line in open(p, encoding='utf-8'):
            m = re.match(r'\\(?:newcommand|providecommand)\{\\(\w+)\}\{(.*?)\}\s*(?:%.*)?$', line.rstrip('\n'))
            if m and m.group(1) not in M:
                M[m.group(1)] = m.group(2)
    return M


MACRO_FILES = [ROOT / 'writing/tables/macros_results_v10.tex', ROOT / 'writing/tables/macros_small_chain.tex',
               ROOT / 'manuscript/build_v10/macros_rev.tex', ROOT / 'manuscript/build_v10/macros_v10.tex']
OLD = read_macros(MACRO_FILES)
REPRO = []        # (what, macro, printed, recomputed, ok)


def repro(what, macro, recomputed):
    printed = OLD[macro]
    ok = printed == recomputed
    REPRO.append((what, macro, printed, recomputed, ok))
    assert ok, f'reproduction failed for {macro}: printed {printed}, recomputed {recomputed}'


# ---------------------------------------------------------------- data
T, S108, S324 = C.load_tasks()
S108s, S324s = sorted(S108), sorted(S324)
UNDER = {t for t in T if T[t]['clarification']}
FULL108 = [t for t in S108s if t not in UNDER]
UNDER108 = [t for t in S108s if t in UNDER]
assert len(FULL108) == 97 and len(UNDER108) == 11
assert UNDER == {t for t in T if 'wording.underspecified' in (T[t]['families'] or [])}, 'clarification flag vs family'
CL = {t: T[t]['building_id'] for t in T}


def rows(path, expect):
    return C.read_rows(str(path), expect)


OURS108 = rows(RES / 'local108_lib_all/per_task_grpo_v10b_c10.jsonl', S108)
OURS324 = rows(RES / 'local324_lib_all/per_task_grpo_v10b_c10.jsonl', S324)
OURS2100 = rows(RES / 'full_all/per_task_grpo_v10b_c10.jsonl', sorted(T))
BASEINF = rows(RES / 'local108_informed_all/per_task_Qwen3.5-9B.jsonl', S108)
COMM = [('gpt-5.6-luna', 'GPT-5.6', 'Gpt'), ('deepseek-v4-pro', 'DeepSeek V4', 'DeepSeek'),
        ('claude-sonnet-5-5', 'Claude Sonnet 5.5', 'Sonnet'), ('gemini-3.8-flash', 'Gemini 3.8 Flash', 'Gemini')]
assert [(a, b, c) for a, b, c in ex.COMMERCIAL] == COMM


def comp(r, ids):
    return sum(done(r[t]) for t in ids) / len(ids)


def ndone(r, ids):
    return int(sum(done(r[t]) for t in ids))


def paired(ra, rb, ids, order=None):
    """A minus B on the same tasks: point, task-level bootstrap, building bootstrap, Tango, b, c, exact p."""
    ids = sorted(ids)
    order = order or ids
    v = [done(ra[t]) - done(rb[t]) for t in order]
    m, lo, hi = ex.boot(v)
    _, clo, chi, _ = C.cboot(v, order, CL)
    ya = np.array([int(done(ra[t])) for t in ids]); yb = np.array([int(done(rb[t])) for t in ids])
    n11, n12, n21, n22 = PM.table(ya, yb)
    tlo, thi = PM.tango(n11, n12, n21, n22)
    return dict(diff=m, lo=lo, hi=hi, clo=clo, chi=chi, tlo=tlo, thi=thi, b=n12, c=n21, n11=n11, n22=n22,
                p=PM.mcnemar_exact(n12, n21), n=len(ids), ya=ya, yb=yb, ids=ids)


def put_paired(stem, P, src, building=True):
    put(stem, num(P['diff']), src + ', paired difference in completion', P['diff'])
    put(stem + 'Lo', num(P['lo']), src + ', 95 % task-level bootstrap, lower', P['lo'])
    put(stem + 'Hi', num(P['hi']), src + ', 95 % task-level bootstrap, upper', P['hi'])
    if building:
        put(stem + 'CLo', num(P['clo']), src + ', 95 % building-level bootstrap, lower', P['clo'])
        put(stem + 'CHi', num(P['chi']), src + ', 95 % building-level bootstrap, upper', P['chi'])
    put(stem + 'TLo', num(P['tlo']), src + ', 95 % Tango score interval, lower', P['tlo'])
    put(stem + 'THi', num(P['thi']), src + ', 95 % Tango score interval, upper', P['thi'])
    put(stem + 'Wins', P['b'], src + ', tasks only the first arm completes (b)', P['b'])
    put(stem + 'Losses', P['c'], src + ', tasks only the second arm completes (c)', P['c'])
    put(stem + 'P', fmt_p(P['p']), src + ', exact two-sided McNemar p', P['p'])


# ---------------------------------------------------------------- prices and cost
HC = (ROOT / 'runs_local/bench_v4/hosted_cost.py').read_text()
PRICE = ast.literal_eval(re.sub(r'#[^\n]*', '', re.search(r'PRICE = (\{.*?\n\})', HC, re.S).group(1)))
CACHE_READ = ast.literal_eval(re.search(r'CACHE_READ = (\{[^}]*\})', HC).group(1))
LIST_PRICES = {'gpt-5.6-luna': (0.20, 1.20), 'claude-sonnet-5-5': (2.00, 10.00), 'claude-opus-5-5': (4.00, 20.00),
                'gemini-3.8-flash': (0.75, 3.75), 'deepseek-v4-pro': (1.32, 3.96)}
for m_, p_ in LIST_PRICES.items():
    assert PRICE[m_] == p_, (m_, PRICE[m_], p_)


def usd_list(r, model):
    pi, po = PRICE[model]
    return int(r.get('input_tokens') or 0) / 1e6 * pi + int(r.get('output_tokens') or 0) / 1e6 * po


def usd_cached(r, model):
    """The earlier formula of hosted_cost.py (cache reads 0.1x or 0.05x, cache writes 1.25x input); reproduction only."""
    pi, po = PRICE[model]
    tin, tout = int(r.get('input_tokens') or 0), int(r.get('output_tokens') or 0)
    cr, cw = int(r.get('cache_read_tokens') or 0), int(r.get('cache_creation_tokens') or 0)
    return (tin - cr - cw) / 1e6 * pi + cr / 1e6 * pi * CACHE_READ.get(model, 0.1) + cw / 1e6 * pi * 1.25 + tout / 1e6 * po


def cost(rws, model, rule='list'):
    f = usd_list if rule == 'list' else usd_cached
    tot = sum(f(r, model) for r in rws.values())
    nd = sum(done(r) for r in rws.values())
    return tot, 100 * tot / len(rws), 100 * tot / nd, nd


def arm_summary(r, ids):
    ids = sorted(ids)
    full = [t for t in ids if t not in UNDER]
    und = [t for t in ids if t in UNDER]
    return dict(comp=comp(r, ids), done=ndone(r, ids), full=comp(r, full) if full else math.nan, nfull=len(full),
                under=ndone(r, und), nunder=len(und),
                mean=statistics.mean((r[t].get('final') or 0.0) for t in ids),
                rounds=statistics.mean((r[t].get('tool_rounds') or 0) for t in ids),
                tin=statistics.mean(int(r[t].get('input_tokens') or 0) for t in ids),
                tout=statistics.mean(int(r[t].get('output_tokens') or 0) for t in ids),
                committed=sum(1 for t in ids if r[t].get('committed')),
                stops={k: sum(1 for t in ids if r[t].get('stop_reason') == k) for k in sorted({r[t].get('stop_reason') for t in ids})})


# ================================================================ reproduction of existing macros before any new number
src_o = 'bench_v4/results/local108_lib_all/per_task_grpo_v10b_c10.jsonl'
repro('completion, VeriBIM-9B, 108 subset', 'ResHundredEightOursComp', num(comp(OURS108, S108s)))
NOTE = {tok: rows(RES / f'hosted108_lib_all/per_task_{mid}.jsonl', S108) for mid, _, tok in COMM}
ALONE = {tok: rows(RES / f'hosted108_alone_all/per_task_{mid}.jsonl', S108) for mid, _, tok in COMM}
repro('completion, Claude Sonnet 5.5 with the library note, 108', 'ResHundredEightSonnetLibComp', num(comp(NOTE['Sonnet'], S108s)))
repro('completion, VeriBIM-9B, 2,100 benchmark', 'ResBenchOursComp', num(comp(OURS2100, sorted(T))))
_P = paired(OURS108, NOTE['Sonnet'], S108s)
repro('task-level bootstrap, VeriBIM-9B minus Sonnet note, point', 'ResHundredEightOursMinusSonnetLib', num(_P['diff']))
repro('task-level bootstrap, lower', 'ResHundredEightOursMinusSonnetLibLo', num(_P['lo']))
repro('task-level bootstrap, upper', 'ResHundredEightOursMinusSonnetLibHi', num(_P['hi']))
repro('building-level bootstrap, lower', 'RevHundredEightOursMinusSonnetLibCLo', num(_P['clo']))
repro('building-level bootstrap, upper', 'RevHundredEightOursMinusSonnetLibCHi', num(_P['chi']))
_PG = paired(OURS108, NOTE['Gpt'], S108s)
repro('task-level bootstrap, VeriBIM-9B minus GPT-5.6 note, lower', 'ResHundredEightOursMinusGptLibLo', num(_PG['lo']))
repro('task-level bootstrap, VeriBIM-9B minus GPT-5.6 note, upper', 'ResHundredEightOursMinusGptLibHi', num(_PG['hi']))
_PF = paired(OURS108, NOTE['Sonnet'], FULL108)
repro('fully specified wins (count), VeriBIM-9B vs Sonnet note', 'RevFullHundredEightOursMinusSonnetLibWins', str(_PF['b']))
repro('fully specified losses (count)', 'RevFullHundredEightOursMinusSonnetLibLosses', str(_PF['c']))
repro('under-specified tasks in the 108 subset (count)', 'RevUnderHundredEight', str(len(UNDER108)))
# documented-arm intervals: analyze_informed4 / analyze_base_informed resampled in the subset-file order
_PB = paired(OURS108, BASEINF, S108s, order=list(S108))
repro('task-level bootstrap in subset-file order, VeriBIM-9B minus base documented, lower', 'RevOursMinusBaseInfLo', num(_PB['lo']))
repro('task-level bootstrap in subset-file order, upper', 'RevOursMinusBaseInfHi', num(_PB['hi']))
repro('building-level bootstrap, VeriBIM-9B minus base documented, lower', 'RevOursMinusBaseInfCLo', num(_PB['clo']))
_PBs = paired(OURS108, BASEINF, S108s)
ORDER_NOTE = (f'VeriBIM-9B minus base documented with sorted order: [{num(_PBs["lo"])}, {num(_PBs["hi"])}] vs subset-file '
              f'order [{num(_PB["lo"])}, {num(_PB["hi"])}] (printed [{OLD["RevOursMinusBaseInfLo"]}, {OLD["RevOursMinusBaseInfHi"]}])')
# Tango interval against the statistics task's CSV
CMP = list(csv.DictReader(open(REV / 'stats/results/comparisons.csv')))


def cmp_row(cid, method):
    r = [x for x in CMP if x['comparison_id'] == cid and x['method'] == method]
    assert len(r) == 1, (cid, method, len(r))
    return r[0]


_t = cmp_row('108_ours_vs_Sonnet_note', 'tango_score_95')
assert abs(float(_t['ci_lo']) - _P['tlo']) < 1e-5 and abs(float(_t['ci_hi']) - _P['thi']) < 1e-5, (_t, _P['tlo'], _P['thi'])
REPRO.append(('Tango 95 %, VeriBIM-9B minus Sonnet note (stats/results/comparisons.csv)', '(csv)',
              f"[{_t['ci_lo']}, {_t['ci_hi']}]", f"[{_P['tlo']:.6f}, {_P['thi']:.6f}]", True))
# cost reproduction: the results macros (make_results_exhibits.py) are at the uncached list price since 2026-10-16;
# the informed-arm macros of make_macros_rev.py still carry the earlier cached-billing formula and are renewed below
INF = {}
for mid in ('claude-sonnet-5-5', 'claude-opus-5-5', 'gemini-3.8-flash', 'gpt-5.6-luna', 'deepseek-v4-pro'):
    INF[mid] = rows(RES / f'hosted108_informed_all/per_task_{mid}.jsonl', S108)
_c = cost(NOTE['Sonnet'], 'claude-sonnet-5-5', 'list')
repro('cost per task, uncached list price, Sonnet note', 'ResHundredEightSonnetLibCentsTask', f'{_c[1]:.2f}')
repro('cost per completed edit, uncached list price, Sonnet note', 'ResHundredEightSonnetLibCentsDone', f'{_c[2]:.2f}')
_c = cost(INF['claude-sonnet-5-5'], 'claude-sonnet-5-5', 'cached')
repro('cost per task, cached formula, Sonnet documented', 'RevInfSonnetCentsTask', f'{_c[1]:.2f}')
_c = cost(INF['claude-opus-5-5'], 'claude-opus-5-5', 'cached')
repro('cost per task, cached formula (cache reads 0.05x), Opus documented', 'RevInfOpusCentsTask', f'{_c[1]:.2f}')


# ================================================================ 1. commercial arms with the ask sentence
section('1. commercial models with the library note and the sentence telling them to ask (hosted108_asknote_all)')
ASK = {tok: rows(RES / f'hosted108_asknote_all/per_task_{mid}.jsonl', S108) for mid, _, tok in COMM}
ASKP = {}
for mid, name, tok in COMM:
    s = arm_summary(ASK[tok], S108s)
    src = f'bench_v4/results/hosted108_asknote_all/per_task_{mid}.jsonl'
    put(f'RevAsk{tok}Comp', num(s['comp']), src + f', completion {s["done"]}/108', s['comp'])
    put(f'RevAsk{tok}Done', s['done'], src + ', tasks completed', s['done'])
    put(f'RevAsk{tok}FullComp', num(s['full']), src + f', completion on the {s["nfull"]} fully specified tasks', s['full'])
    put(f'RevAsk{tok}UnderDone', s['under'], src + f', under-specified tasks completed of {s["nunder"]}', s['under'])
    put(f'RevAsk{tok}Mean', num(s['mean']), src + ', mean score (final)', s['mean'])
    put(f'RevAsk{tok}Rounds', f"{s['rounds']:.2f}", src + ', mean tool_rounds', s['rounds'])
    put(f'RevAsk{tok}TokensIn', f"{s['tin'] / 1000:.1f}", src + ', mean input_tokens / 1000', s['tin'])
    put(f'RevAsk{tok}TokensOut', f"{s['tout'] / 1000:.1f}", src + ', mean output_tokens / 1000', s['tout'])
    tot, ct, cd, nd = cost(ASK[tok], mid)
    put(f'RevAsk{tok}CentsTask', f'{ct:.2f}', src + ', US cents per task at the uncached list price', ct)
    put(f'RevAsk{tok}CentsDone', f'{cd:.2f}', src + ', US cents per completed task at the uncached list price', cd)
    P = paired(OURS108, ASK[tok], S108s)
    ASKP[tok] = P
    put_paired(f'RevOursMinusAsk{tok}', P, f'VeriBIM-9B ({src_o}) minus {name} with the note and the ask sentence, 108 tasks')
    PF = paired(OURS108, ASK[tok], FULL108)
    put_paired(f'RevFullOursMinusAsk{tok}', PF, f'same, the 97 fully specified tasks', building=False)
    PN = paired(ASK[tok], NOTE[tok], S108s)
    put(f'RevAsk{tok}MinusNote', num(PN['diff']), f'{name}: ask-sentence arm minus note arm (hosted108_lib_all), 108 tasks', PN['diff'])
    put(f'RevAsk{tok}MinusNoteLo', num(PN['lo']), 'same, 95 % task-level bootstrap, lower', PN['lo'])
    put(f'RevAsk{tok}MinusNoteHi', num(PN['hi']), 'same, 95 % task-level bootstrap, upper', PN['hi'])
    put(f'RevAsk{tok}MinusNoteWins', PN['b'], 'same, tasks only the ask-sentence arm completes', PN['b'])
    put(f'RevAsk{tok}MinusNoteLosses', PN['c'], 'same, tasks only the note arm completes', PN['c'])
    put(f'RevAsk{tok}MinusNoteP', fmt_p(PN['p']), 'same, exact two-sided McNemar p', PN['p'])


def holm(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


_toks = [tok for _, _, tok in COMM]
_adj = holm([ASKP[t]['p'] for t in _toks])
for tok, a in zip(_toks, _adj):
    put(f'RevHolmAsk{tok}Adj', fmt_p_sci(a), f'Holm-adjusted exact McNemar p over the four ask-sentence comparisons, {tok}', a)
    put(f'RevHolmAsk{tok}Raw', fmt_p_sci(ASKP[tok]['p']), f'raw exact McNemar p, {tok} (ask-sentence arm)', ASKP[tok]['p'])
put('RevAskSigBelow', sum(1 for t in _toks if _adj[_toks.index(t)] < 0.05),
    'ask-sentence arms below VeriBIM-9B after Holm at 0.05: ' + ', '.join(t for t, a in zip(_toks, _adj) if a < 0.05))

# ================================================================ 2. Sonnet documented repeats
section('2. Claude Sonnet 5.5 documented, three runs (hosted108_informed_all, _rep2_all, _rep3_all)')
REP = [('One', 'hosted108_informed_all'), ('Two', 'hosted108_informed_rep2_all'), ('Three', 'hosted108_informed_rep3_all')]
RR = {k: rows(RES / f'{d}/per_task_claude-sonnet-5-5.jsonl', S108) for k, d in REP}
for k, d in REP:
    s = arm_summary(RR[k], S108s)
    tot, ct, cd, _ = cost(RR[k], 'claude-sonnet-5-5')
    src = f'bench_v4/results/{d}/per_task_claude-sonnet-5-5.jsonl'
    put(f'RevRep{k}Comp', num(s['comp']), src + f', completion {s["done"]}/108', s['comp'])
    put(f'RevRep{k}Done', s['done'], src + ', tasks completed', s['done'])
    put(f'RevRep{k}USD', f'{tot:.2f}', src + ', US$ for the 108 tasks at the uncached list price', tot)
    put(f'RevRep{k}CentsTask', f'{ct:.2f}', src + ', US cents per task at the uncached list price', ct)
    put(f'RevRep{k}TokensInM', f"{sum(int(r.get('input_tokens') or 0) for r in RR[k].values()) / 1e6:.2f}",
        src + ', input tokens over the 108 tasks, millions', sum(int(r.get('input_tokens') or 0) for r in RR[k].values()))
_v = {t: tuple(done(RR[k][t]) for k, _ in REP) for t in S108s}
_flip = sorted(t for t, v in _v.items() if len(set(v)) > 1)
put('RevRepFlips', len(_flip), 'tasks whose verdict differs across the three runs: ' + ', '.join(_flip), _flip)
put('RevRepFailAll', sum(1 for v in _v.values() if max(v) == 0), 'tasks failed in all three runs')
put('RevRepFailAny', sum(1 for v in _v.values() if min(v) == 0), 'tasks failed in at least one of the three runs')
put('RevRepUSDTotal', f"{sum(cost(RR[k], 'claude-sonnet-5-5')[0] for k, _ in REP):.0f}", 'US$ for the three runs at the uncached list price')

# ================================================================ 3. Gemma 4 31B documented
section('3. Gemma 4 31B (4-bit AWQ) with the documented library (local108_informed_all)')
GEM = rows(RES / 'local108_informed_all/per_task_gemma-4-31b-it-awq.jsonl', S108)
DOC_ORDER = list(S108)   # documented-type arms: tasks resampled in the subset-file order, as the documented rows of the main table


def local_arm(stem, r, src, label):
    s = arm_summary(r, S108s)
    put(f'{stem}Comp', num(s['comp']), src + f', completion {s["done"]}/108', s['comp'])
    put(f'{stem}Done', s['done'], src + ', tasks completed', s['done'])
    put(f'{stem}FullComp', num(s['full']), src + f', completion on the {s["nfull"]} fully specified tasks', s['full'])
    put(f'{stem}UnderDone', s['under'], src + f', under-specified tasks completed of {s["nunder"]}', s['under'])
    put(f'{stem}Mean', num(s['mean']), src + ', mean score (final)', s['mean'])
    for g in ex.OPS + ex.CATS:
        key = 'operation' if g in ex.OPS else 'category'
        ids = [t for t in S108s if T[t][key] == g]
        put(f'{stem}Comp{g.capitalize()}', num(comp(r, ids)), src + f', completion on {g} tasks, {ndone(r, ids)}/{len(ids)}', comp(r, ids))
    put(f'{stem}Committed', s['committed'], src + ', tasks with a committed file', s['committed'])
    STOPTOK = {'completed': 'Completed', 'budget_exhausted': 'Budget', 'sandbox_crash': 'Crash', 'output_truncated': 'Truncated',
               'context_overflow': 'Context', 'inference_error': 'InferenceError', 'tool_timeout': 'Timeout'}
    for k in ('completed', 'budget_exhausted', 'sandbox_crash', 'output_truncated', 'context_overflow'):
        put(f'{stem}Stop{STOPTOK[k]}', s['stops'].get(k, 0), src + f', stop_reason {k}', s['stops'].get(k, 0))
    assert set(s['stops']) <= set(STOPTOK), s['stops']
    put(f'{stem}Rounds', f"{s['rounds']:.2f}", src + ', mean tool_rounds', s['rounds'])
    put(f'{stem}TokensIn', f"{s['tin'] / 1000:.1f}", src + ', mean input_tokens / 1000', s['tin'])
    put(f'{stem}TokensOut', f"{s['tout'] / 1000:.2f}", src + ', mean output_tokens / 1000', s['tout'])
    return s


local_arm('RevGemma', GEM, 'bench_v4/results/local108_informed_all/per_task_gemma-4-31b-it-awq.jsonl', 'Gemma 4 31B')
PGEM = paired(OURS108, GEM, S108s, order=DOC_ORDER)
put_paired('RevOursMinusGemma', PGEM, 'VeriBIM-9B minus Gemma 4 31B documented, 108 tasks')
PGB = paired(GEM, BASEINF, S108s, order=DOC_ORDER)
put_paired('RevGemmaMinusBaseInf', PGB, 'Gemma 4 31B documented minus untrained Qwen3.5-9B documented (local108_informed_all), 108 tasks')
PGS = paired(INF['claude-sonnet-5-5'], GEM, S108s, order=DOC_ORDER)
put('RevSonnetInfMinusGemma', num(PGS['diff']), 'Claude Sonnet 5.5 documented minus Gemma 4 31B documented, 108 tasks', PGS['diff'])
put('RevSonnetInfMinusGemmaP', fmt_p(PGS['p']), 'same, exact two-sided McNemar p', PGS['p'])

# ================================================================ 4. retrieval arms
section('4. untrained Qwen3.5-9B with three retrieved training trajectories (local108_retrieval_all, local108_retrievalshort_all)')
RET = {'RevRetr': rows(RES / 'local108_retrieval_all/per_task_Qwen3.5-9B.jsonl', S108),
       'RevRetrShort': rows(RES / 'local108_retrievalshort_all/per_task_Qwen3.5-9B.jsonl', S108)}
RETP = {}
for stem, d in (('RevRetr', 'local108_retrieval_all'), ('RevRetrShort', 'local108_retrievalshort_all')):
    local_arm(stem, RET[stem], f'bench_v4/results/{d}/per_task_Qwen3.5-9B.jsonl', stem)
    P = paired(OURS108, RET[stem], S108s, order=DOC_ORDER)
    RETP[stem] = P
    put_paired(f'RevOursMinus{stem[3:]}', P, f'VeriBIM-9B minus the {d} arm, 108 tasks')
    PB = paired(RET[stem], BASEINF, S108s, order=DOC_ORDER)
    put_paired(f'Rev{stem[3:]}MinusBaseInf', PB, f'the {d} arm minus untrained Qwen3.5-9B documented, 108 tasks')
PRS = paired(RET['RevRetr'], RET['RevRetrShort'], S108s, order=DOC_ORDER)
put('RevRetrMinusRetrShort', num(PRS['diff']), 'documented note + retrieved minus short note + retrieved, 108 tasks', PRS['diff'])
put('RevRetrMinusRetrShortP', fmt_p(PRS['p']), 'same, exact two-sided McNemar p', PRS['p'])
TAB = list(csv.DictReader(open(REV / 'retrieval_fewshot/results/retrieval_table.csv')))
assert len(TAB) == 108 and {r['task_id'] for r in TAB} == set(S108)
for stem, col in (('RevRetr', 'prompt_tokens_notes'), ('RevRetrShort', 'prompt_tokens_notes_short')):
    v = [int(r[col]) for r in TAB]
    src = f'retrieval_fewshot/results/retrieval_table.csv {col} (first-request prompt tokens)'
    put(f'{stem}PromptMean', thou(statistics.mean(v)), src + ', mean', statistics.mean(v))
    put(f'{stem}PromptMedian', thou(statistics.median(v)), src + ', median', statistics.median(v))
    put(f'{stem}PromptMin', thou(min(v)), src + ', min', min(v))
    put(f'{stem}PromptMax', thou(max(v)), src + ', max', max(v))
RREP = (REV / 'retrieval_fewshot/report.md').read_text()
mm = re.search(r'documented arm ([\d,]+)/([\d,]+)/([\d,]+)', RREP)
assert mm
put('RevInfPromptMedian', mm.group(2), 'retrieval_fewshot/report.md, documented arm first-request prompt tokens min/median/max (no result file holds it)',
    mm.group(2))
RJ = json.load(open(REV / 'retrieval_fewshot/results/retrieval.json'))
assert len(RJ) == 108
ex_ = [(t, x) for t in RJ for x in t['retrieved']]
sims = [x['similarity'] for _, x in ex_]
put('RevRetrExamples', len(ex_), 'retrieval_fewshot/results/retrieval.json, retrieved examples (3 per task)', len(ex_))
put('RevRetrTrainTasks', len({x['task_id'] for _, x in ex_}), 'retrieval.json, distinct training tasks among them')
put('RevRetrBuildings', len({x['building_id'] for _, x in ex_}), 'retrieval.json, distinct training buildings among them')
put('RevRetrSimMedian', num(statistics.median(sims)), 'retrieval.json, median TF-IDF cosine similarity of the retrieved examples', statistics.median(sims))
put('RevRetrSimMin', num(min(sims)), 'retrieval.json, lowest similarity', min(sims))
put('RevRetrSimOne', sum(1 for s in sims if s >= 1 - 1e-9), 'retrieval.json, examples at similarity 1.0 (same masked request)')
put('RevRetrSameKind', sum(1 for t, x in ex_ if x['edit_kind'] == t['edit_kind']), 'retrieval.json, examples with the same edit kind as their task')
put('RevRetrSameCell', sum(1 for t, x in ex_ if x['cell'] == t['cell']), 'retrieval.json, examples with the same operation-category cell')
_pre = lambda tid: tid.split('-')[0]
_st = sum(1 for t in RJ if any(_pre(x['task_id']) == _pre(t['task_id']) and x['edit_kind'] == t['edit_kind'] for x in t['retrieved']))
put('RevRetrTasksSameTypeKind', _st, 'retrieval.json, tasks with an example of the same element type (task-id prefix) and edit kind')
_uq = sum(1 for t in RJ if t['clarification'] and any(x['answer'] == 'clarify' for x in t['retrieved']))
put('RevRetrUnderWithQuestion', _uq, 'retrieval.json, under-specified tasks with an example that ends in a question')
assert (len(ex_), statistics.median(sims) > 0.93, sum(1 for t, x in ex_ if x['edit_kind'] == t['edit_kind'])) == (324, True, 311)

# ================================================================ 5. rule-based parser
section('5. rule-based parser baseline (parser_baseline/results)')
PS = json.load(open(REV / 'parser_baseline/results/summary.json'))
PR = rows(REV / 'parser_baseline/results/per_task_parser.jsonl', sorted(T))
ALL = sorted(T)


def tri(a, b, ids):
    both = sum(1 for t in ids if done(a[t]) and done(b[t]))
    po = sum(1 for t in ids if done(a[t]) and not done(b[t]))
    mo = sum(1 for t in ids if not done(a[t]) and done(b[t]))
    return dict(n=len(ids), pc=comp(a, ids), mc=comp(b, ids), pd=ndone(a, ids), md=ndone(b, ids), both=both, po=po, mo=mo,
                ne=len(ids) - both - po - mo)


PARSER_ROWS = []
for key, label, ids, model, msrc in (('Bench', 'Generated tasks', ALL, OURS2100, 'full_all'),
                                     ('HundredEight', '108-task subset', S108s, OURS108, 'local108_lib_all'),
                                     ('ThreeTwentyFour', '324-task subset', S324s, OURS324, 'local324_lib_all')):
    q = tri(PR, model, ids)
    PARSER_ROWS.append((label, q))
    src = f'parser_baseline/results/per_task_parser.jsonl vs bench_v4/results/{msrc}/per_task_grpo_v10b_c10.jsonl, {len(ids)} tasks'
    put(f'RevParser{key}Comp', num(q['pc']), src + f', parser completion {q["pd"]}/{q["n"]}', q['pc'])
    put(f'RevParser{key}Done', thou(q['pd']), src + ', parser completed', q['pd'])
    put(f'RevParser{key}Both', thou(q['both']), src + ', both complete', q['both'])
    put(f'RevParser{key}ParserOnly', q['po'], src + ', parser only', q['po'])
    put(f'RevParser{key}ModelOnly', q['mo'], src + ', VeriBIM-9B only', q['mo'])
    put(f'RevParser{key}Neither', q['ne'], src + ', neither', q['ne'])
assert PARSER_ROWS[0][1]['pd'] == PS['overall']['completed'] and PARSER_ROWS[1][1]['pd'] == PS['subset_108']['completed']
assert PARSER_ROWS[2][1]['pd'] == PS['subset_324']['completed']
_out = [t for t in ALL if t not in set(S108)]
put('RevParserOutsideDevComp', num(comp(PR, _out)), f'per_task_parser.jsonl, the {len(_out)} tasks outside the 108-task development subset, {ndone(PR, _out)}', comp(PR, _out))
assert ndone(PR, _out) == PS['outside_108_development_subset']['completed']
for key, fld, vals in (('operation', 'by_operation', ex.OPS), ('category', 'by_category', ex.CATS),
                       ('ifc_version', 'by_ifc_version', ex.VERS)):
    for g in vals:
        ids = [t for t in ALL if T[t][key] == g]
        assert ndone(PR, ids) == PS[fld][g]['completed'], (g, ndone(PR, ids), PS[fld][g])
        tok = ex.VTOK.get(g, g.capitalize())
        put(f'RevParserComp{tok}', num(comp(PR, ids)), f'per_task_parser.jsonl, {g} tasks, {ndone(PR, ids)}/{len(ids)}', comp(PR, ids))
_fs = [t for t in ALL if t not in UNDER]
put('RevParserFullComp', num(comp(PR, _fs)), f'per_task_parser.jsonl, fully specified tasks, {ndone(PR, _fs)}/{len(_fs)}', comp(PR, _fs))
put('RevParserUnderDone', ndone(PR, sorted(UNDER)), f'per_task_parser.jsonl, under-specified tasks completed of {len(UNDER)}')
_asked = sum(1 for t in ALL if PR[t].get('asked'))
_asked_full = sum(1 for t in _fs if PR[t].get('asked'))
put('RevParserAskedFull', _asked_full, 'per_task_parser.jsonl, fully specified tasks on which the parser asked a question')
assert _asked == len(UNDER) and _asked_full == 0
# rewritten wording (85 rewritten, 15 kept) and the generated wording of the same 100 tasks
RW = json.load(open(REV / 'parser_baseline/results/rewritten/summary_rewritten.json'))
v100 = json.load(open(ex.V100B_SUBSET))
VT = {json.loads(l)['task_id']: json.loads(l) for l in open(ROOT / 'runs_local/stage_a_v10/val100_rw/val_tasks_100_v3b_rw.jsonl') if l.strip()}
rw_ids = sorted(t for t in v100 if VT[t].get('wording_rewritten') is True)
kept_ids = sorted(t for t in v100 if VT[t].get('wording_rewritten') is not True)
P_rw = C.read_rows(str(REV / 'parser_baseline/results/rewritten/per_task_parser_rw.jsonl'), v100)
P_or = C.read_rows(str(REV / 'parser_baseline/results/rewritten/per_task_parser_original.jsonl'), v100)
M_rw = C.read_rows(str(ROOT / 'runs_local/stage_a_v10/gates/v100rw/per_task_grpo_v10b_c10.jsonl'), v100)
_o1 = C.read_rows(str(ROOT / 'runs_local/stage_a_v10/gates/v500b_grpo_v10b_c10_rep1/per_task_grpo_v10b_c10.jsonl'))
M_or = {t: _o1[t] for t in v100}
for label, ids, a, b, key in (('Rewritten wording', rw_ids, P_rw, M_rw, 'rewritten_85'),
                              ('Kept wording', kept_ids, P_rw, M_rw, 'kept_15'),
                              ('Generated wording of the same tasks', sorted(v100), P_or, M_or, None)):
    q = tri(a, b, ids)
    if key:
        e = RW['rewritten_wording'][key]
        assert (q['n'], q['pd'], q['md'], q['both'], q['po'], q['mo'], q['ne']) == (
            e['n'], e['parser_completed'], e['model_completed'], e['both'], e['parser_only'], e['model_only'], e['neither']), (key, q, e)
    else:
        e = RW['original_wording']['all_100']
        assert (q['pd'], q['md']) == (e['parser_completed'], e['model_completed'])
    PARSER_ROWS.append((label, q))
src = 'parser_baseline/results/rewritten (per_task_parser_rw.jsonl, per_task_parser_original.jsonl) vs stage_a_v10/gates v100rw and v500b_grpo_v10b_c10_rep1'
q = PARSER_ROWS[3][1]
put('RevParserRwN', q['n'], src + ', rewritten instructions')
put('RevParserRwDone', q['pd'], src + ', parser completed on the rewritten instructions', q['pd'])
put('RevParserRwModelDone', q['md'], src + ', VeriBIM-9B completed on the rewritten instructions', q['md'])
put('RevParserRwNeither', q['ne'], src + ', neither completed on the rewritten instructions', q['ne'])
_rec = sum(1 for t in rw_ids if P_rw[t].get('recognised'))
assert _rec == RW['parser_counts']['rw_recognised'] - sum(1 for t in kept_ids if P_rw[t].get('recognised')), _rec
put('RevParserRwRecognised', _rec, src + ', rewritten instructions the parser recognised', _rec)
q = PARSER_ROWS[4][1]
put('RevParserKeptN', q['n'], src + ', kept instructions')
put('RevParserKeptDone', q['pd'], src + ', parser completed on the kept instructions', q['pd'])
put('RevParserKeptModelDone', q['md'], src + ', VeriBIM-9B completed on the kept instructions', q['md'])
q = PARSER_ROWS[5][1]
put('RevParserGenN', q['n'], src + ', the same tasks in the generated wording')
put('RevParserGenDone', q['pd'], src + ', parser completed, generated wording', q['pd'])
put('RevParserGenModelDone', q['md'], src + ', VeriBIM-9B completed, generated wording', q['md'])
PREP = (REV / 'parser_baseline/report.md').read_text()
mm = re.search(r'Why unread: (\d+)/85 the sentence opens unlike any template.*?; (\d+)/85 a template verb opens but the frame differs.*?; (\d+)/85 read through', PREP, re.S)
assert mm and sum(int(x) for x in mm.groups()) == 85
put('RevParserRwOpenUnlike', mm.group(1), 'parser_baseline/report.md, rewritten instructions that open unlike any template (hand classification)')
put('RevParserRwFrameDiffers', mm.group(2), 'parser_baseline/report.md, rewritten instructions with a template verb and a different frame')
put('RevParserRwOrderDiffers', mm.group(3), 'parser_baseline/report.md, rewritten instructions read through the target, then a clause in a different order')

# ================================================================ 6. cost at the uncached list price
section('6. cost of every commercial arm at the uncached list price')
COSTS = {}


def put_cost(old_task, old_done, rws, model, src, new_task=None, new_done=None):
    tot, ct, cd, nd = cost(rws, model)
    ot, oct_, ocd, _ = cost(rws, model, 'cached')
    nt = new_task or old_task + 'List'
    ndn = new_done or old_done + 'List'
    put(nt, f'{ct:.2f}', src + f', US cents per task at the uncached list price ({len(rws)} tasks)', ct)
    put(ndn, f'{cd:.2f}', src + f', US cents per completed task at the uncached list price ({nd} completed)', cd)
    for old, new, val, oval in ((old_task, nt, ct, oct_), (old_done, ndn, cd, ocd)):
        if old and old in OLD and OLD[old] == f'{val:.2f}':
            DROPCHK.append((old, OLD[old], f'{val:.2f}', new + ' (already at the list price)'))
            continue
        if old and old in OLD:
            assert OLD[old] == f'{oval:.2f}', (old, OLD[old], oval)      # the printed value is the cached-formula value
            DROPIN.append(f'\\renewcommand{{\\{old}}}{{{val:.2f}}}  % {src}, uncached list price (was {OLD[old]})')
            DROPCHK.append((old, OLD[old], f'{val:.2f}', new))
    COSTS[nt] = (tot, ct, cd, nd, ot)
    return tot


for mid, name, tok in COMM:
    for arm, rw in (('Alone', ALONE[tok]), ('Lib', NOTE[tok])):
        put_cost(f'ResHundredEight{tok}{arm}CentsTask', f'ResHundredEight{tok}{arm}CentsDone', rw, mid,
                 f'bench_v4/results/hosted108_{arm.lower()}_all/per_task_{mid}.jsonl')
for arm in ('Alone', 'Lib'):
    rw = rows(RES / f'hosted324_{arm.lower()}_all/per_task_claude-sonnet-5-5.jsonl', S324)
    put_cost(f'ResThreeTwentyFourSonnet{arm}CentsTask', f'ResThreeTwentyFourSonnet{arm}CentsDone', rw, 'claude-sonnet-5-5',
             f'bench_v4/results/hosted324_{arm.lower()}_all/per_task_claude-sonnet-5-5.jsonl')
I4TOK = {'claude-sonnet-5-5': 'Sonnet', 'claude-opus-5-5': 'Opus', 'gemini-3.8-flash': 'Gemini', 'gpt-5.6-luna': 'Gpt', 'deepseek-v4-pro': 'DeepSeek'}
for mid, tok in I4TOK.items():
    put_cost(f'RevInf{tok}CentsTask', f'RevInf{tok}CentsDone', INF[mid], mid, f'bench_v4/results/hosted108_informed_all/per_task_{mid}.jsonl')
put_cost('RevInfCentsTask', 'RevInfCentsDone', INF['claude-sonnet-5-5'], 'claude-sonnet-5-5',
         'bench_v4/results/hosted108_informed_all/per_task_claude-sonnet-5-5.jsonl (same as RevInfSonnet)')
REST = sorted(set(S324) - set(S108))
INFREST = rows(RES / 'hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl', REST)
put_cost(None, None, INFREST, 'claude-sonnet-5-5', 'bench_v4/results/hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl',
         new_task='RevRestInfCentsTaskList', new_done='RevRestInfCentsDoneList')
_inf324 = dict(INFREST); _inf324.update(INF['claude-sonnet-5-5'])
put_cost(None, None, _inf324, 'claude-sonnet-5-5', 'hosted324rest_informed_all + hosted108_informed_all (Sonnet documented, all 324)',
         new_task='RevThreeInfCentsTaskList', new_done='RevThreeInfCentsDoneList')
_i4 = sum(cost(INF[m], m)[0] for m in I4TOK)
assert OLD['RevInfSpendUSD'] == f"{sum(cost(INF[m], m, 'cached')[0] for m in I4TOK):.0f}"
put('RevInfSpendUSDList', f'{_i4:.0f}', 'the five documented runs on the 108 tasks, US$ at the uncached list price', _i4)
DROPIN.append(f'\\renewcommand{{\\RevInfSpendUSD}}{{{_i4:.0f}}}  % five documented runs, uncached list price (was {OLD["RevInfSpendUSD"]})')
DROPCHK.append(('RevInfSpendUSD', OLD['RevInfSpendUSD'], f'{_i4:.0f}', 'RevInfSpendUSDList'))

# reported runs: the file set of make_macros_rev.py (RevSpendRuns / RevSpendUSD)
SPEND_FILES = [RES / f'hosted108_{a}_all/per_task_{m}.jsonl' for a in ('alone', 'lib')
               for m in ('claude-sonnet-5-5', 'deepseek-v4-pro', 'gemini-3.8-flash', 'gpt-5.6-luna')]
SPEND_FILES += [RES / f'hosted216_{a}_all/per_task_claude-sonnet-5-5.jsonl' for a in ('alone', 'lib')]
SPEND_FILES += [RES / 'hosted108_informed_all/per_task_claude-sonnet-5-5.jsonl', RES / 'hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl']
SPEND_FILES += [RES / f'hosted108_informed_all/per_task_{m}.jsonl' for m in ('gpt-5.6-luna', 'deepseek-v4-pro', 'gemini-3.8-flash', 'claude-opus-5-5')]
NEW_FILES = [RES / f'hosted108_asknote_all/per_task_{m}.jsonl' for m, _, _ in COMM]
NEW_FILES += [RES / f'hosted108_informed_{r}_all/per_task_claude-sonnet-5-5.jsonl' for r in ('rep2', 'rep3')]


def model_of(path):
    b = os.path.basename(str(path))[len('per_task_'):]
    hits = [m for m in PRICE if b.startswith(m + '.')]
    assert hits, path
    return max(hits, key=len)


def spend(files, rule):
    tot, n = 0.0, 0
    for f in files:
        m = model_of(f)
        fn = usd_list if rule == 'list' else usd_cached
        for l in open(f):
            if l.strip():
                tot += fn(json.loads(l), m); n += 1
    return tot, n


_cs, _n = spend(SPEND_FILES, 'cached')
assert thou(_n) == OLD['RevSpendRuns'] and f'{_cs:.0f}' == OLD['RevSpendUSD'], (_n, _cs)
REPRO.append(('reported commercial runs and their cost, cached formula', 'RevSpendRuns / RevSpendUSD',
              f"{OLD['RevSpendRuns']} / {OLD['RevSpendUSD']}", f'{thou(_n)} / {_cs:.0f}', True))
_ls, _ = spend(SPEND_FILES, 'list')
put('RevSpendUSDList', f'{_ls:.0f}', f'the {thou(_n)} reported runs of RevSpendRuns (same file set as before), US$ at the uncached list price', _ls)
DROPIN.append(f'\\renewcommand{{\\RevSpendUSD}}{{{_ls:.0f}}}  % same {thou(_n)} runs, uncached list price (was {OLD["RevSpendUSD"]})')
DROPCHK.append(('RevSpendUSD', OLD['RevSpendUSD'], f'{_ls:.0f}', 'RevSpendUSDList'))
_rv, _rn = spend(NEW_FILES, 'list')
assert _rn == 6 * 108
put('RevSpendRevisionRuns', _rn, 'runs added in this revision: four models with the note and the ask sentence, two Sonnet documented repeats')
put('RevSpendRevisionUSD', f'{_rv:.0f}', 'those runs, US$ at the uncached list price', _rv)
put('RevSpendTotalRuns', thou(_n + _rn), 'reported runs including this revision')
put('RevSpendTotalUSD', f'{_ls + _rv:.0f}', 'reported runs including this revision, US$ at the uncached list price', _ls + _rv)

# every commercial-model call: the glob of make_macros_rev.py minus the BIM-Edit folder (not readable here)
_allf = sorted(glob.glob(str(RES / 'hosted*/per_task_*.jsonl*')))
_allf += [str(ROOT / p) for p in ('runs_local/e2_v3/subset108/per_task_claude-sonnet-5.jsonl',
                                  'runs_local/rescore_run/val_claude/per_task_claude-sonnet-5-5.jsonl',
                                  'runs_local/rescore_run/val_gpt/per_task_gpt-5.6-luna.jsonl')]
_seen = {}
for f in _allf:
    m = model_of(f)
    for l in open(f):
        if not l.strip():
            continue
        r = json.loads(l)
        k = (m, r['task_id'], r.get('input_tokens'), r.get('output_tokens'), r.get('duration_seconds'), r.get('tool_rounds'))
        if k not in _seen:
            _seen[k] = (usd_list(r, m), usd_cached(r, m))
_u = json.load(open(ROOT / 'runs_local/stage_a_v10/val100_rw/rewrite_report.json'))['usage']
_rwc = _u['prompt_tokens'] / 1e6 * PRICE['gpt-5.6-sol'][0] + _u['completion_tokens'] / 1e6 * PRICE['gpt-5.6-sol'][1]
SPEND_ALL_PARTIAL = (len(_seen), sum(v[0] for v in _seen.values()) + _rwc, sum(v[1] for v in _seen.values()) + _rwc)

# Singapore cost example: inputs and formulas of make_macros_rev.py
SG = (REV07 / 'literature/singapore_cost.md').read_text()
rate = float(grab(r'\*\*1 USD = ([\d.]+) SGD\*\*', SG, 'singapore_cost.md'))
watts = int(grab(r'\*\*Board power:\*\* \*\*(\d+) W total board power\*\*, confirmed directly from the NVIDIA datasheet PDF\s*\n\s*\("Power Consumption', SG, 'singapore_cost.md 1'))
ws = float(grab(r'\*\*Total with RTX PRO 5000 Blackwell\*\* \| \| \*\*\u2248 S\$([\d,]+)', SG, 'singapore_cost.md 2b').replace(',', ''))
tariff = float(grab(r'(\d+\.\d+) cents/kWh with 9% GST\*\*', SG, 'singapore_cost.md 3'))
M1 = (ROOT / 'writing/tables/macros_results_v10.tex').read_text()   # current results macros, same file as make_macros_rev.py
solo = float(grab(r'\\newcommand\{\\ResHundredEightOursSoloSecs\}\{([\d.]+)\}', M1, 'macros_results_v10.tex'))
scomp = float(grab(r'\\newcommand\{\\ResHundredEightOursSoloComp\}\{([\d.]+)\}', M1, 'macros_results_v10.tex'))
assert f'{rate:.4f}' == OLD['RevSgRate'] and f'{ws:,.0f}' == OLD['RevSgWorkstation']
annual = ws / 3
elec = watts * solo / 3600 / 1000 * tariff / scomp
assert f'{elec:.2f}' == OLD['RevSgElecCents'] and f'{annual:,.0f}' == OLD['RevSgAnnual']
fee_old = float(OLD['ResHundredEightSonnetLibCentsDone'])
inf_old = cost(INF['claude-sonnet-5-5'], 'claude-sonnet-5-5', 'cached')[2]
repro('Singapore fee from the printed note-arm cents', 'RevSgFeeSonnet', f'{fee_old * rate:.2f}')
repro('Singapore fee of the documented arm, cached formula', 'RevSgFeeInf', f'{inf_old * rate:.2f}')
repro('break-even from the printed note-arm cents', 'RevSgBreakEven', f'{round(annual * 100 / (fee_old * rate - elec), -3):,.0f}')
repro('break-even of the documented arm, cached formula', 'RevSgBreakEvenInf', f'{round(annual * 100 / (inf_old * rate - elec), -3):,.0f}')
fee_new = cost(NOTE['Sonnet'], 'claude-sonnet-5-5')[2]          # unrounded, as the earlier generator used inf_us unrounded
inf_new = cost(INF['claude-sonnet-5-5'], 'claude-sonnet-5-5')[2]
ask_new = cost(ASK['Sonnet'], 'claude-sonnet-5-5')[2]
for nm, us, lab in (('RevSgFeeSonnet', fee_new, 'note arm'), ('RevSgFeeInf', inf_new, 'documented arm'), ('RevSgFeeAskSonnet', ask_new, 'ask-sentence arm')):
    v = f'{us * rate:.2f}'
    put(nm + 'List' if nm != 'RevSgFeeAskSonnet' else nm, v, f'Claude Sonnet 5.5 {lab}: US cents per completed edit at the uncached list price x {rate:.4f}, Singapore cents', us * rate)
    if nm in OLD and OLD[nm] == v:
        DROPCHK.append((nm, OLD[nm], v, nm + 'List (already at the list price)'))
    elif nm in OLD:
        DROPIN.append(f'\\renewcommand{{\\{nm}}}{{{v}}}  % {lab}, uncached list price (was {OLD[nm]})')
        DROPCHK.append((nm, OLD[nm], v, nm + 'List'))
for nm, us, lab in (('RevSgBreakEven', fee_new, 'note arm'), ('RevSgBreakEvenInf', inf_new, 'documented arm'), ('RevSgBreakEvenAsk', ask_new, 'ask-sentence arm')):
    be = round(annual * 100 / (us * rate - elec), -3)
    v = f'{be:,.0f}'
    put(nm + 'List' if nm != 'RevSgBreakEvenAsk' else nm, v,
        f'annual workstation cost / (Claude Sonnet 5.5 {lab} fee - electricity), completed edits a year, to thousands', annual * 100 / (us * rate - elec))
    if nm in OLD and OLD[nm] == v:
        DROPCHK.append((nm, OLD[nm], v, nm + 'List (already at the list price)'))
    elif nm in OLD:
        DROPIN.append(f'\\renewcommand{{\\{nm}}}{{{v}}}  % {lab}, uncached list price (was {OLD[nm]})')
        DROPCHK.append((nm, OLD[nm], v, nm + 'List'))

# ================================================================ 7. statistics table and Holm / equivalence macros
section('7. Holm family and equivalence intervals (stats/results/holm.csv, comparisons.csv)')
HO = [r for r in csv.DictReader(open(REV / 'stats/results/holm.csv')) if r['family'] == 'primary' and r['test'] == 'exact McNemar']
assert len(HO) == 4
for r in HO:
    tok = re.search(r'108_ours_vs_(\w+)_note', r['comparison_id']).group(1)
    put(f'RevHolm{tok}Raw', fmt_p_sci(float(r['raw_p'])), f"stats/results/holm.csv primary exact McNemar {r['comparison_id']} raw_p", float(r['raw_p']))
    put(f'RevHolm{tok}Adj', fmt_p_sci(float(r['holm_adjusted_p'])), f"stats/results/holm.csv primary exact McNemar {r['comparison_id']} holm_adjusted_p", float(r['holm_adjusted_p']))
    assert (int(r['b_A_only']), int(r['c_B_only'])) == (paired(OURS108, NOTE[tok], S108s)['b'], paired(OURS108, NOTE[tok], S108s)['c'])
HD = [r for r in csv.DictReader(open(REV / 'stats/results/holm.csv')) if r['family'] == 'documented' and r['test'] == 'exact McNemar']
r = [x for x in HD if x['comparison_id'] == '108_ours_vs_DeepSeek_documented'][0]
put('RevHolmInfDeepSeekRaw', fmt_p(float(r['raw_p'])), 'holm.csv documented family, exact McNemar, DeepSeek V4 raw_p', float(r['raw_p']))
put('RevHolmInfDeepSeekAdj', fmt_p(float(r['holm_adjusted_p'])), 'holm.csv documented family, exact McNemar, DeepSeek V4 holm_adjusted_p', float(r['holm_adjusted_p']))
r = [x for x in HD if x['comparison_id'] == '108_ours_vs_GptReason_documented'][0]
put('RevHolmInfGptReasonRaw', fmt_p(float(r['raw_p'])), 'holm.csv documented family, exact McNemar, GPT-5.6 documented with reasoning on raw_p', float(r['raw_p']))
put('RevHolmInfGptReasonAdj', fmt_p(float(r['holm_adjusted_p'])), 'holm.csv documented family, exact McNemar, GPT-5.6 documented with reasoning on holm_adjusted_p', float(r['holm_adjusted_p']))
for cid, stem in (('108_ours_vs_Sonnet_documented', 'RevEquivTangoHundredEight'), ('216_ours_vs_Sonnet_documented', 'RevEquivTangoRest'),
                  ('324_ours_vs_Sonnet_documented', 'RevEquivTangoThree')):
    e = cmp_row(cid, 'tango_90_equivalence')
    put(stem + 'Lo', num(float(e['ci_lo'])), f'stats/results/comparisons.csv {cid} tango_90_equivalence ci_lo', float(e['ci_lo']))
    put(stem + 'Hi', num(float(e['ci_hi'])), f'stats/results/comparisons.csv {cid} tango_90_equivalence ci_hi', float(e['ci_hi']))
    tp = float(cmp_row(cid, 'tost_tango_score')['p_value'])
    put(stem + 'TostP', f'{tp:.3f}', f'stats/results/comparisons.csv {cid} tost_tango_score p_value', tp)
_e = cmp_row('108_ours_vs_Sonnet_documented', 'bootstrap_90_equivalence')
assert (num(float(_e['ci_lo'])), num(float(_e['ci_hi']))) == (OLD['RevOursMinusInfNinetyLo'], OLD['RevOursMinusInfNinetyHi'])


# --- mixed model (building + task) and GEE for the comparisons that the statistics run did not cover
def gee_bias_reduced(ya, yb, bl):
    import pandas as pd
    import statsmodels.api as sm
    from scipy import stats
    n = len(ya)
    df = pd.DataFrame({'y': np.concatenate([ya, yb]), 'arm': np.r_[np.ones(n), np.zeros(n)], 'building': list(bl) * 2})
    X = sm.add_constant(df[['arm']])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        r = sm.GEE(df['y'], X, groups=df['building'], family=sm.families.Binomial(),
                   cov_struct=sm.cov_struct.Exchangeable()).fit(cov_type='bias_reduced', maxiter=200)
    b1, se = float(r.params['arm']), float(r.bse['arm'])
    ok = math.isfinite(se) and se > 0 and abs(b1) < 15 and se < 20
    return {'beta1': b1, 'se_beta1': se, 'separation': not ok, 'odds_ratio': math.exp(b1) if ok else math.nan,
            'wald_p': float(2 * stats.norm.sf(abs(b1 / se))) if ok else math.nan}


def separated(f):
    b1, se = f.get('beta1'), f.get('se_beta1')
    return bool(f.get('separation') or b1 is None or se is None or not math.isfinite(se) or abs(b1) > 12 or se > 5)


def models(P):
    bl = [CL[t] for t in P['ids']]
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        bt = G.fit_building_task(P['ya'], P['yb'], bl)
    ge = gee_bias_reduced(P['ya'], P['yb'], bl)
    return dict(or_=None if separated(bt) else bt['odds_ratio'], lr_p=bt['lr_p'],
                gee_p=None if separated(ge) else ge['wald_p'])


# check the copy of the model code on one comparison of the statistics run
_m = models(_P)
_r1, _r2 = cmp_row('108_ours_vs_Sonnet_note', 'glmm_building_task'), cmp_row('108_ours_vs_Sonnet_note', 'gee_building_bias_reduced')
assert abs(_m['or_'] - float(_r1['estimate'])) / float(_r1['estimate']) < 2e-3 and abs(_m['lr_p'] - float(_r1['p_value'])) / float(_r1['p_value']) < 5e-3, (_m, _r1)
assert abs(_m['gee_p'] - float(_r2['p_value'])) / float(_r2['p_value']) < 5e-3, (_m, _r2)
REPRO.append(('mixed model (building + task) OR and LR p, GEE p, VeriBIM-9B minus Sonnet note (comparisons.csv)', '(csv)',
              f"{_r1['estimate']} / {_r1['p_value']} / {_r2['p_value']}", f"{_m['or_']:.6f} / {_m['lr_p']:.6g} / {_m['gee_p']:.6g}", True))


def csv_stats(cid):
    """b, c, exact p, Tango 95, building bootstrap 95, GLMM building+task OR and LR p, GEE p, from comparisons.csv."""
    ex_ = cmp_row(cid, 'mcnemar_exact')
    ta = cmp_row(cid, 'tango_score_95')
    bb = cmp_row(cid, 'bootstrap_building_95')
    gm = cmp_row(cid, 'glmm_building_task')
    ge = cmp_row(cid, 'gee_building_bias_reduced')
    b_, c_ = int(ex_['b_A_only']), int(ex_['c_B_only'])
    assert abs(PM.mcnemar_exact(b_, c_) - float(ex_['p_value'])) <= 5e-7 + 1e-3 * float(ex_['p_value'])
    return dict(b=b_, c=c_, p=PM.mcnemar_exact(b_, c_), tlo=float(ta['ci_lo']), thi=float(ta['ci_hi']),
                clo=float(bb['ci_lo']), chi=float(bb['ci_hi']), or_=float(gm['estimate']) if gm['estimate'] not in ('', 'inf') else None,
                lr_p=float(gm['p_value']) if gm['p_value'] else None, gee_p=float(ge['p_value']) if ge['p_value'] and ge['estimate'] else None,
                diff=float(ex_['estimate'] or cmp_row(cid, 'bootstrap_task_95')['estimate']), n=int(ex_['n_tasks']),
                full_arm=int(ex_['A_completed']) == int(ex_['n_tasks']) or int(ex_['B_completed']) == int(ex_['n_tasks']))


def new_stats(P):
    m = models(P)
    return dict(b=P['b'], c=P['c'], p=P['p'], tlo=P['tlo'], thi=P['thi'], clo=P['clo'], chi=P['chi'], or_=m['or_'], lr_p=m['lr_p'],
                gee_p=m['gee_p'], diff=P['diff'], n=P['n'], full_arm=int(P['ya'].sum()) == P['n'] or int(P['yb'].sum()) == P['n'])


REPRO_REP = list(csv.DictReader(open(REV / 'stats/results/reproduction.csv')))
assert all(r['match'] in ('True', '') for r in REPRO_REP), 'stats reproduction has a mismatch'
STAT_GROUPS = [
    ('108-task subset: VeriBIM-9B minus each model with the library note',
     [(nm, csv_stats(f'108_ours_vs_{tok}_note')) for _, nm, tok in COMM]),
    ('108-task subset: VeriBIM-9B minus each model with the library note and the instruction to ask',
     [(nm, new_stats(ASKP[tok])) for _, nm, tok in COMM]),
    ('108-task subset: VeriBIM-9B minus each model alone',
     [(nm, csv_stats(f'108_ours_vs_{tok}_alone')) for _, nm, tok in COMM]),
    ('108-task subset: VeriBIM-9B minus each model with the documented library',
     # round 4 (2026-10-19): GPT-5.6 with reasoning on directly after the published GPT-5.6 documented row
     [(nm, csv_stats(f'108_ours_vs_{tok}_documented')) for _, nm, tok in COMM[:1]] +
     [('GPT-5.6, reasoning on', csv_stats('108_ours_vs_GptReason_documented'))] +
     [(nm, csv_stats(f'108_ours_vs_{tok}_documented')) for _, nm, tok in COMM[1:]] +
     [('Claude Opus 5.5', csv_stats('108_ours_vs_Opus_documented')), ('Gemma 4 31B', new_stats(PGEM))]),
    ('108-task subset: VeriBIM-9B minus the untrained Qwen3.5-9B',
     [('Alone', csv_stats('108_ours_vs_base_alone')), ('With the library note', csv_stats('108_ours_vs_base_note')),
      ('With the documented library', csv_stats('108_ours_vs_base_documented')),
      ('Documented library, retrieved examples', new_stats(RETP['RevRetr'])),
      ('Library note, retrieved examples', new_stats(RETP['RevRetrShort']))]),
    ('324-task subset: VeriBIM-9B minus Claude Sonnet 5.5',
     [('With the library note', csv_stats('324_ours_vs_Sonnet_note')), ('Alone', csv_stats('324_ours_vs_Sonnet_alone')),
      ('Documented library, 216 further tasks', csv_stats('216_ours_vs_Sonnet_documented'))]),
    ('2,100 generated tasks: training stages',
     [('Preference minus imitation', csv_stats('2100_dpo_vs_sft')),
      ('Reinforcement minus preference', csv_stats('2100_ours_vs_dpo')),
      ('VeriBIM-9B minus imitation', csv_stats('2100_ours_vs_sft'))]),
    ('Rewritten wording: VeriBIM-9B, rewritten minus generated wording',
     [('85 rewritten instructions', csv_stats('v85_ours_rewritten_vs_generated'))]),
]
# the building-level column of the CSV rows equals the printed macros (reproduction.csv); spot check two
assert (num(csv_stats('108_ours_vs_Sonnet_note')['clo']), num(csv_stats('108_ours_vs_Sonnet_note')['chi'])) == (
    OLD['RevHundredEightOursMinusSonnetLibCLo'], OLD['RevHundredEightOursMinusSonnetLibCHi'])
assert (num(csv_stats('324_ours_vs_Sonnet_note')['clo']), num(csv_stats('324_ours_vs_Sonnet_note')['chi'])) == (
    OLD['RevThreeTwentyFourOursMinusSonnetLibCLo'], OLD['RevThreeTwentyFourOursMinusSonnetLibCHi'])

# ================================================================ 9. BIM-Edit similarity strata (summary file of the strata analysis)
section('9. BIM-Edit tasks by similarity of the scene to a training file (bimedit_strata/strata.json)')
SJ = json.load(open(REV / 'bimedit_strata/strata.json'))
for key, stem in (('realistic, similar (>= 0.80)', 'RevStratSimilar'), ('realistic, not similar (< 0.80)', 'RevStratOther'),
                  ('simple (all < 0.80)', 'RevStratSimple')):
    e = SJ[key]
    src = f"bimedit_strata/strata.json['{key}']"
    put(stem + 'N', e['n'], src + '.n')
    put(stem + 'Scenes', e['n_scenes'], src + '.n_scenes')
    put(stem + 'Ours', num(e['final']), src + '.final (VeriBIM-9B mean score)', e['final'])
    put(stem + 'Base', num(e['base']), src + '.base (untrained base mean score)', e['base'])
    put(stem + 'SonnetAlone', num(e['sonnet_alone']), src + '.sonnet_alone', e['sonnet_alone'])
    put(stem + 'SonnetLib', num(e['sonnet_lib']), src + '.sonnet_lib', e['sonnet_lib'])
    d = e['final_minus_base']
    put(stem + 'OursMinusBase', num(d[0]), src + '.final_minus_base[0]', d[0])
    put(stem + 'OursMinusBaseLo', num(d[1]), src + '.final_minus_base[1]', d[1])
    put(stem + 'OursMinusBaseHi', num(d[2]), src + '.final_minus_base[2]', d[2])
    d = e['sonnet_alone_minus_final']
    put(stem + 'SonnetAloneMinusOurs', num(d[0]), src + '.sonnet_alone_minus_final[0]', d[0])
put('RevStratSimThreshold', '0.80', 'bimedit_strata/strata.json stratum boundary (structural similarity to the nearest training file)')
put('RevStratSpearmanGain', num(SJ['scene_level_realistic']['spearman_sim_vs_ours_minus_base']),
    "strata.json scene_level_realistic.spearman_sim_vs_ours_minus_base (38 realistic scenes)")
put('RevStratSpearmanOurs', num(SJ['scene_level_realistic']['spearman_sim_vs_ours']), 'strata.json scene_level_realistic.spearman_sim_vs_ours')


# ================================================================ 10. checker validity: relation gate, absolute errors, schema and clashes
section('10. checker validity: relation-gated verdict, absolute errors, schema validation and clashes (checker_validity/results)')
CV = REV / 'checker_validity/results'
CVREP = (REV / 'checker_validity/report.md').read_text()
GS = json.load(open(CV / 'gate_summary.json'))
ARM108 = ['veribim9b_108', 'base9b_libnote_108', 'sonnet_alone_108', 'sonnet_lib_108', 'sonnet_documented_108',
          'opus_documented_108', 'gpt_documented_108', 'gemini_documented_108', 'deepseek_documented_108']
assert set(GS) == set(ARM108) | {'veribim9b_2100'}
for key, stem, n in (('veribim9b_2100', 'RevGateBench', 2100), ('veribim9b_108', 'RevGateHundredEight', 108)):
    e = GS[key]
    assert e['n_tasks'] == n and not e['rows_with_error'] and not e['rows_missing']
    put(stem + 'Before', thou(e['completed_paper_rule']), f'checker_validity/results/gate_summary.json {key}.completed_paper_rule', e['completed_paper_rule'])
    put(stem + 'After', thou(e['completed_gated']), f'gate_summary.json {key}.completed_gated (relation checks added)', e['completed_gated'])
    put(stem + 'AfterStrict', thou(e['completed_gated_strict']), f'gate_summary.json {key}.completed_gated_strict', e['completed_gated_strict'])
assert GS['veribim9b_2100']['completed_paper_rule'] == ndone(OURS2100, ALL) and GS['veribim9b_108']['completed_paper_rule'] == ndone(OURS108, S108s)
put('RevGateArms', len(ARM108), 'gate_summary.json, arms read on the 108-task subset')
_lost = sum(GS[a]['lost'] for a in ARM108)
put('RevGateLostTotal', _lost, 'gate_summary.json, completions lost to the relation checks summed over the 108-task arms', _lost)
_la = [a for a in ARM108 if GS[a]['lost']]
# v4e (2026-10-16): after the deletion re-run the gate removes completions in several commercial arms (deletions that
# leave an empty IfcRelAssociatesClassification or IfcRelCoversBldgElements relation); one macro per arm, none for ours
assert GS['veribim9b_2100']['lost'] == 0 and GS['veribim9b_108']['lost'] == 0, 'the gate removes a completion of the proposed model; the 6.2 sentence must change'
put('RevGateLostArms', len(_la), 'gate_summary.json, 108-task arms with at least one completion lost to the relation checks', len(_la))
_DIG = {d: w for d, w in zip('0123456789', ('Zero', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine'))}
for a in _la:        # one macro per arm that loses at least one completion (macro names are letters only)
    stem = 'RevGateLost' + ''.join(_DIG.get(ch, ch) for ch in ''.join(w.capitalize() for w in a.replace('_108', '').split('_')))
    put(stem, GS[a]['lost'], f'gate_summary.json {a}.lost', GS[a]['lost'])
put('RevGateLostArmBefore', GS['sonnet_alone_108']['completed_paper_rule'], 'gate_summary.json sonnet_alone_108.completed_paper_rule (Claude Sonnet 5.5 alone)')
put('RevGateLostArmAfter', GS['sonnet_alone_108']['completed_gated'], 'gate_summary.json sonnet_alone_108.completed_gated')
LT = list(csv.DictReader(open(CV / 'lost_tasks_gated.csv')))
assert len(LT) == _lost, (len(LT), _lost)
put('RevGateLostTasks', len(LT), 'checker_validity/results/lost_tasks_gated.csv rows (one per lost completion)', len(LT))
_dele = sum(1 for r in LT if r['operation'] == 'delete')
put('RevGateLostDeletions', _dele, 'lost_tasks_gated.csv rows with operation delete', _dele)
# topology of an output that misses one of three reference edges (report, Analysis 1): mean of seven numbers
_er, _ef = 2 / 3, 2 * 1 * (2 / 3) / (1 + 2 / 3)
_comb = 0.3 * 1 + 0.7 * _ef
_mean7 = (1 + 1 + 1 + 1 + _er + _ef + _comb) / 7
_topo = _mean7        # topology score of an output that misses one of three reference edges (v4e: no longer tied to one lost task)
put('RevTopoEdgeRecall', num(_er), 'edge recall with two of three reference edges', _er)
put('RevTopoEdgeF', num(_ef), 'edge F1 at precision 1 and recall 2/3', _ef)
put('RevTopoCombined', num(_comb), '0.3 x node F1 + 0.7 x edge F1', _comb)
put('RevTopoMean', num(_mean7), '(node P + node R + node F1 + edge P + edge R + edge F1 + combined) / 7', _mean7)
MG = json.load(open(CV / 'mutation_gate_summary.json'))['table']
MJ = [json.loads(l) for l in open(CV / 'mutation_gate.jsonl') if l.strip()]
for key, stem in (('control', 'Control'), ('containment', 'Contain'), ('filling', 'Filling'), ('wrong_host', 'WrongHost'),
                  ('del_control', 'DelControl'), ('del_naive', 'DelBare')):
    e = MG[key]
    src = f'checker_validity/results/mutation_gate_summary.json table.{key}'
    _rows = [r for r in MJ if r['pert'] == key and r['applied']]
    assert len(_rows) == e['n_applied'] and sum(r['accept_090'] for r in _rows) == e['n_accept_090']
    assert sum(r['gated_accept_090'] for r in _rows) == e['n_gated_accept_090']
    put(f'RevMutGate{stem}N', e['n_applied'], src + '.n_applied')
    put(f'RevMutGate{stem}Acc', e['n_accept_090'], src + '.n_accept_090 (accepted at 0.90 by the checker)')
    ks = sum(r['accept_098'] for r in _rows)
    assert abs(ks / e['n_applied'] - e['accept_098']) < 1e-9
    MG[key]['_strict_n'] = ks
    put(f'RevMutGate{stem}AccPct', pct(e['n_accept_090'], e['n_applied']), src + '.n_accept_090 / n_applied, percent rounded half up', e['accept_090'])
    put(f'RevMutGate{stem}AccStrictPct', pct(ks, e['n_applied']), 'mutation_gate.jsonl accept_098 count / n_applied, percent', e['accept_098'])
    put(f'RevMutGate{stem}Gated', e['n_gated_accept_090'], src + '.n_gated_accept_090 (accepted at 0.90 with the relation checks)')
    put(f'RevMutGate{stem}GatedPct', pct(e['n_gated_accept_090'], e['n_applied']), src + '.n_gated_accept_090 / n_applied, percent', e['gated_accept_090'])
repro('mutation study, containment removed accepted at 0.90 (%)', 'RevMutContainAcc', VALUES['RevMutGateContainAccPct'])
repro('mutation study, filling removed accepted at 0.90 (%)', 'RevMutFillingAcc', VALUES['RevMutGateFillingAccPct'])
for key, stem in (('containment', 'Contain'), ('filling', 'Filling')):
    k = sum(1 for r in MJ if r['pert'] == key and r['applied'] and r['accept_090'] and abs(r['score']['topology'] - _topo) < 5e-4)
    put(f'RevMutGate{stem}AtTopo', k, f'mutation_gate.jsonl, accepted {key} removals whose topology is {num(_topo)}', k)
# absolute errors: the checker's geometry formula and the measured errors
_ratio = math.log(10 / 9) / 5
put('RevAbsScale', '5', 'geometry score g = exp(-5 d / D) (checker_validity/report.md Analysis 2, chamfer_scale 5)')
put('RevAbsRatioMax', f'{_ratio:.4f}', 'largest d / D that passes 0.9: ln(10/9) / 5', _ratio)
for stem, dims, lab in (('Door', (0.9, 0.2, 2.1), '0.9 x 0.2 x 2.1 m door'), ('Wall', (4.0, 0.2, 3.0), '4 x 0.2 x 3 m wall'),
                        ('Space', (4.0, 3.0, 4.9), '4 x 3 x 4.9 m space')):
    Dg = math.sqrt(sum(x * x for x in dims))
    put(f'RevAbs{stem}AllowCm', f'{100 * _ratio * Dg:.1f}', f'allowed median distance d for a {lab}: ratio x box diagonal {Dg:.2f} m, cm', 100 * _ratio * Dg)
AE = json.load(open(CV / 'abs_errors_summary.json'))
AT = json.load(open(CV / 'abs_tolerance_completion.json'))
ABS_ARMS = [('veribim9b_2100', r'\ModelName{}, all 2,100 tasks', 'OursBench'), ('veribim9b_108', r'\ModelName{}', 'Ours'),
            ('sonnet_alone_108', 'Claude Sonnet 5.5, alone', 'SonnetAlone'), ('sonnet_lib_108', 'Claude Sonnet 5.5, with the library note', 'SonnetLib'),
            ('sonnet_documented_108', 'Claude Sonnet 5.5, documented library', 'SonnetInf'), ('opus_documented_108', 'Claude Opus 5.5, documented library', 'OpusInf'),
            ('gpt_documented_108', 'GPT-5.6, documented library', 'GptInf'), ('gemini_documented_108', 'Gemini 3.8 Flash, documented library', 'GeminiInf'),
            ('deepseek_documented_108', 'DeepSeek V4, documented library', 'DeepSeekInf')]
ABSROWS = []
for key, label, tok in ABS_ARMS:
    c = AE[key]['completed']; p = c['position']; dm = c['dimension_max']; t = AT[key]
    assert t['completed'] == GS[key]['completed_paper_rule']
    src = f'checker_validity/results/abs_errors_summary.json {key}.completed'
    put(f'RevAbs{tok}Targets', thou(c['n_targets']), src + '.n_targets (targets of completed edits)', c['n_targets'])
    put(f'RevAbs{tok}Tasks', thou(c['n_tasks']), src + '.n_tasks', c['n_tasks'])
    for q, qt in (('median', 'Median'), ('p95', 'NinetyFive'), ('p99', 'NinetyNine'), ('max', 'Max')):
        put(f'RevAbs{tok}Pos{qt}', f'{1000 * p[q]:.1f}', src + f'.position.{q} x 1000 (centre error, mm)', p[q])
    put(f'RevAbs{tok}DimMax', f'{1000 * dm["max"]:.1f}', src + '.dimension_max.max x 1000 (largest dimension error, mm)', dm['max'])
    _tg = [r for r in csv.DictReader(open(CV / f'abs_errors_{key}.csv')) if r['completed'] == 'True']
    assert len(_tg) == c['n_targets']
    _w = sum(1 for r in _tg if float(r['pos_err_m']) <= 0.01 and float(r['dim_err_max_m'] or 0) <= 0.01) / len(_tg)
    c['_within'] = _w
    put(f'RevAbs{tok}WithinCmPct', f"{100 * _w:.1f}", f'checker_validity/results/abs_errors_{key}.csv, completed targets with centre error and largest dimension error both <= 1 cm, percent', _w)
    put(f'RevAbs{tok}Done', thou(t['completed']), f'checker_validity/results/abs_tolerance_completion.json {key}.completed')
    put(f'RevAbs{tok}DoneCm', thou(t['completed_within_1cm']), f'abs_tolerance_completion.json {key}.completed_within_1cm')
    ABSROWS.append((label, c, t))
# a target is within 1 cm when its centre and every dimension are; check on the per-target file of VeriBIM-9B
_ae = list(csv.DictReader(open(CV / 'abs_errors_veribim9b_2100.csv')))
_aec = [r for r in _ae if r['completed'] == 'True']
assert len(_aec) == AE['veribim9b_2100']['completed']['n_targets']
assert max(float(r['pos_err_m']) for r in _aec) <= 0.01 and max(float(r['dim_err_max_m']) for r in _aec) <= 0.01
# the commercial cases with errors above 5 cm
_hi = []
for key, _, _ in ABS_ARMS[2:]:
    for r in csv.DictReader(open(CV / f'abs_errors_{key}.csv')):
        if r['completed'] == 'True' and r['task_id'] in ('WIN-UPD-DIR-B16m4X3-003', 'DOR-UPD-TOP-B24m4X3-060'):
            _hi.append((key, r['task_id'], float(r['dim_err_height_m']), float(r['checker_geometry'])))
_arms_hi = sorted({k for k, *_ in _hi})
assert _arms_hi == sorted(['sonnet_alone_108', 'sonnet_lib_108', 'sonnet_documented_108', 'opus_documented_108', 'deepseek_documented_108']), _arms_hi
put('RevAbsHeightTasks', len({t for _, t, *_ in _hi}), 'abs_errors_<arm>.csv, completed overall-height tasks with a height error above 5 cm (WIN-UPD-DIR-B16m4X3-003, DOR-UPD-TOP-B24m4X3-060)')
put('RevAbsHeightArms', len(_arms_hi), 'abs_errors_<arm>.csv, arms with those errors: ' + ', '.join(_arms_hi))
put('RevAbsHeightErrLo', f'{min(h for *_, h, _ in _hi):.2f}', 'abs_errors_<arm>.csv dim_err_height_m, smallest of those cases (m)', min(h for *_, h, _ in _hi))
put('RevAbsHeightErrHi', f'{max(h for *_, h, _ in _hi):.2f}', 'abs_errors_<arm>.csv dim_err_height_m, largest of those cases (m)', max(h for *_, h, _ in _hi))
put('RevAbsHeightGeomLo', num(min(g for *_, g in _hi)), 'abs_errors_<arm>.csv checker_geometry, lowest of those cases', min(g for *_, g in _hi))
put('RevAbsHeightGeomHi', num(max(g for *_, g in _hi)), 'abs_errors_<arm>.csv checker_geometry, highest of those cases', max(g for *_, g in _hi))
_sp = [r for r in csv.DictReader(open(CV / 'abs_errors_gpt_documented_108.csv')) if r['task_id'] == 'SPC-CRE-TOP-B04-004']
assert len(_sp) == 1 and _sp[0]['completed'] == 'True'
put('RevAbsGptSpaceErr', f"{float(_sp[0]['pos_err_m']):.2f}", 'abs_errors_gpt_documented_108.csv SPC-CRE-TOP-B04-004 pos_err_m (space placed too low, m)', float(_sp[0]['pos_err_m']))
put('RevAbsGptSpaceGeom', num(float(_sp[0]['checker_geometry'])), 'same row, checker_geometry', float(_sp[0]['checker_geometry']))
# schema validation and clashes
SC = json.load(open(CV / 'schema_clash_summary.json'))
mm = re.search(r'IfcOpenShell (\d+\.\d+\.\d+), ifcopenshell\.validate', CVREP); assert mm
put('RevSchemaIfcosVersion', mm.group(1), 'checker_validity/report.md Analysis 3, validator version')
mm = re.search(r'Tasks whose source model is larger than (\d+) MB were left out \((\d+) of the 108 tasks', CVREP); assert mm
put('RevSchemaSizeLimitMB', mm.group(1), 'checker_validity/report.md Analysis 3 scope, source-size limit (MB)')
put('RevSchemaExcluded', mm.group(2), 'checker_validity/report.md Analysis 3 scope, 108-subset tasks left out')
assert all(SC[a]['n_tasks'] == 108 - int(mm.group(2)) for a in ARM108)
put('RevSchemaScopeN', SC['veribim9b_108']['n_tasks'], 'schema_clash_summary.json veribim9b_108.n_tasks (same for every 108-task arm)')
mm = re.search(r'the first (\d+) draws of random\.Random\((\d+)\)\.sample\(task_ids, \d+\) were taken, of which (\d+) have a source above', CVREP); assert mm
put('RevSchemaDrawN', mm.group(1), 'checker_validity/report.md, tasks drawn from the 2,100 benchmark')
put('RevSchemaDrawSeed', mm.group(2), 'checker_validity/report.md, seed of the draw')
assert SC['veribim9b_2100']['n_tasks'] == int(mm.group(1)) - int(mm.group(3))
put('RevSchemaDrawScopeN', SC['veribim9b_2100']['n_tasks'], 'schema_clash_summary.json veribim9b_2100.n_tasks (draw minus large sources)')
SCHROWS = []
for key, label, tok in ABS_ARMS:
    c = SC[key]['completed']
    src = f'checker_validity/results/schema_clash_summary.json {key}.completed'
    put(f'RevSchema{tok}N', c['n'], src + '.n (completed edits validated)')
    put(f'RevSchema{tok}GtTasks', c['tasks_with_new_errors_gt'], src + '.tasks_with_new_errors_gt')
    put(f'RevSchema{tok}OutTasks', c['tasks_with_new_errors_output'], src + '.tasks_with_new_errors_output')
    put(f'RevSchema{tok}BeyondTasks', c['tasks_output_errors_beyond_gt'], src + '.tasks_output_errors_beyond_gt')
    put(f'RevSchema{tok}BeyondErrors', c['output_errors_beyond_gt_total'], src + '.output_errors_beyond_gt_total')
    put(f'RevClash{tok}N', c['n_with_clash_check'], src + '.n_with_clash_check')
    put(f'RevClash{tok}GtTasks', c['tasks_with_new_clash_gt'], src + '.tasks_with_new_clash_gt')
    put(f'RevClash{tok}OutTasks', c['tasks_with_new_clash_output'], src + '.tasks_with_new_clash_output')
    put(f'RevClash{tok}BeyondTasks', c['tasks_output_clash_beyond_gt'], src + '.tasks_output_clash_beyond_gt')
    put(f'RevClash{tok}BeyondClashes', c['output_clashes_beyond_gt_total'], src + '.output_clashes_beyond_gt_total')
    SCHROWS.append((label, c))
for key in ('veribim9b_2100', 'veribim9b_108'):
    c = SC[key]['completed']
    assert c['tasks_output_errors_beyond_gt'] == 0 and c['tasks_output_clash_beyond_gt'] == 0 and c['output_clashes_beyond_gt_total'] == 0
_a = SC['veribim9b_2100']['all']
put('RevClashOursBenchAllBeyond', _a['tasks_output_clash_beyond_gt'], 'schema_clash_summary.json veribim9b_2100.all.tasks_output_clash_beyond_gt (all edits, completed or not)')
GJ = [json.loads(l) for l in open(CV / 'gate_veribim9b_2100.jsonl') if l.strip()]
assert len(GJ) == 2100
_gd = [r for r in GJ if (r.get('dangling') or {}).get('new_dangling_gt')]
put('RevGtDanglingTasks', len(_gd), 'checker_validity/results/gate_veribim9b_2100.jsonl, tasks whose ground truth leaves a relationship with an empty required end (dangling.new_dangling_gt)')
put('RevGtDanglingDelete', sum(1 for r in _gd if r['operation'] == 'delete'), 'same, of which deletions')

# ================================================================ 11. GPT-5.6 documented with reasoning on (round 4, 2026-10-19)
section('11. GPT-5.6 with the documented library and reasoning on (hosted108_informed_reasoning_all, responses endpoint, effort medium)')
GRS_FILE = 'bench_v4/results/hosted108_informed_reasoning_all/per_task_gpt-5.6-luna.jsonl'
GRS = rows(RES / 'hosted108_informed_reasoning_all/per_task_gpt-5.6-luna.jsonl', S108)
GRSUM = json.load(open(REV / 'round4/gpt_reasoning/result_summary.json'))
_s = arm_summary(GRS, S108s)
put('RevInfGptReasonComp', num(_s['comp']), GRS_FILE + f', completion {_s["done"]}/108', _s['comp'])
put('RevInfGptReasonDone', _s['done'], GRS_FILE + ', tasks completed', _s['done'])
put('RevInfGptReasonFullComp', num(_s['full']), GRS_FILE + f', completion on the {_s["nfull"]} fully specified tasks', _s['full'])
put('RevInfGptReasonFullDone', ndone(GRS, FULL108), GRS_FILE + ', fully specified tasks completed of 97', ndone(GRS, FULL108))
put('RevInfGptReasonUnderDone', _s['under'], GRS_FILE + f', under-specified tasks completed of {_s["nunder"]}', _s['under'])
put('RevInfGptReasonMean', num(_s['mean']), GRS_FILE + ', mean score (final)', _s['mean'])
put('RevInfGptReasonRounds', f"{_s['rounds']:.2f}", GRS_FILE + ', mean tool_rounds', _s['rounds'])
_tin = sum(int(GRS[t].get('input_tokens') or 0) for t in S108s)
_tout = sum(int(GRS[t].get('output_tokens') or 0) for t in S108s)
_treas = sum(int(GRS[t].get('reasoning_tokens') or 0) for t in S108s)
_tcach = sum(int(GRS[t].get('cached_input_tokens') or 0) for t in S108s)
put('RevInfGptReasonTokensIn', f'{_tin / 108 / 1000:.1f}', GRS_FILE + ', mean input_tokens / 1000', _tin / 108)
put('RevInfGptReasonTokensOut', f'{_tout / 108 / 1000:.2f}', GRS_FILE + ', mean output_tokens / 1000 (reasoning tokens included)', _tout / 108)
put('RevInfGptReasonTokensReason', f'{_treas / 108 / 1000:.2f}', GRS_FILE + ', mean reasoning_tokens / 1000 (part of the output tokens)', _treas / 108)
put('RevInfGptReasonTokensInM', f'{_tin / 1e6:.2f}', GRS_FILE + ', input tokens over the 108 tasks, millions', _tin)
put('RevInfGptReasonTokensCachedM', f'{_tcach / 1e6:.2f}', GRS_FILE + ', of the input tokens cached by the provider (cached_input_tokens), millions; not discounted in the cost', _tcach)
put('RevInfGptReasonTokensOutTotal', thou(_tout), GRS_FILE + ', output tokens over the 108 tasks (reasoning included)', _tout)
put('RevInfGptReasonTokensReasonTotal', thou(_treas), GRS_FILE + ', reasoning tokens over the 108 tasks', _treas)
_tot, _ct, _cd, _nd = cost(GRS, 'gpt-5.6-luna')
put('RevInfGptReasonUSD', f'{_tot:.2f}', GRS_FILE + ', US$ for the 108 tasks at the uncached list price (0.20 / 1.20 per M tokens)', _tot)
put('RevInfGptReasonCentsTask', f'{_ct:.2f}', GRS_FILE + ', US cents per task at the uncached list price (108 tasks)', _ct)
put('RevInfGptReasonCentsDone', f'{_cd:.2f}', GRS_FILE + f', US cents per completed task at the uncached list price ({_nd} completed)', _cd)
_stops = _s['stops']
put('RevInfGptReasonStopCompleted', _stops.get('completed', 0), GRS_FILE + ', stop_reason completed', _stops.get('completed', 0))
PGR = paired(OURS108, GRS, S108s, order=DOC_ORDER)
put_paired('RevOursMinusInfGptReason', PGR, f'VeriBIM-9B ({src_o}) minus GPT-5.6 documented with reasoning on ({GRS_FILE}), 108 tasks, subset-file order')
PGRF = paired(OURS108, GRS, FULL108)
put_paired('RevFullOursMinusInfGptReason', PGRF, 'same, the 97 fully specified tasks (sorted order)', building=False)
PGRP = paired(GRS, INF['gpt-5.6-luna'], S108s, order=DOC_ORDER)
put_paired('RevInfGptReasonMinusInfGpt', PGRP, f'GPT-5.6 documented with reasoning on minus the published GPT-5.6 documented arm (hosted108_informed_all, reasoning none), 108 tasks, subset-file order')
PGRPF = paired(GRS, INF['gpt-5.6-luna'], FULL108)
put_paired('RevFullInfGptReasonMinusInfGpt', PGRPF, 'same, the 97 fully specified tasks (sorted order)', building=False)
# the statistics run (stats/results/comparisons.csv) carries the same comparison; its b, c, p and building interval must agree
_cs = csv_stats('108_ours_vs_GptReason_documented')
assert (_cs['b'], _cs['c']) == (PGR['b'], PGR['c']) and abs(_cs['p'] - PGR['p']) < 1e-12, (_cs, PGR['b'], PGR['c'])
assert (num(_cs['clo']), num(_cs['chi'])) == (num(PGR['clo']), num(PGR['chi'])), (_cs['clo'], _cs['chi'], PGR['clo'], PGR['chi'])
assert (num(_cs['tlo']), num(_cs['thi'])) == (num(PGR['tlo']), num(PGR['thi']))
_bt = cmp_row('108_ours_vs_GptReason_documented', 'bootstrap_task_95')
assert (num(float(_bt['ci_lo'])), num(float(_bt['ci_hi']))) == (num(PGR['lo']), num(PGR['hi'])), (_bt, PGR['lo'], PGR['hi'])
# EXPECTED: the values of round4/gpt_reasoning/result.md (analyze_result.py); the run stops on any difference
_n, _v = GRSUM['new'], GRSUM['veribim9b_minus_new']['all_108']
_np = GRSUM['new_minus_published']['all_108']
EXPECTED = {'RevInfGptReasonComp': '0.880', 'RevInfGptReasonDone': '95', 'RevInfGptReasonFullComp': '0.918',
            'RevInfGptReasonFullDone': '89', 'RevInfGptReasonUnderDone': '6', 'RevInfGptReasonMean': '0.911',
            'RevInfGptReasonRounds': '3.30', 'RevInfGptReasonUSD': '1.73', 'RevInfGptReasonCentsTask': '1.60',
            'RevInfGptReasonTokensOutTotal': '154,077', 'RevInfGptReasonTokensReasonTotal': '48,683',
            'RevOursMinusInfGptReason': '0.093', 'RevOursMinusInfGptReasonLo': '0.028', 'RevOursMinusInfGptReasonHi': '0.157',
            'RevOursMinusInfGptReasonCLo': '0.035', 'RevOursMinusInfGptReasonCHi': '0.148', 'RevOursMinusInfGptReasonP': '0.013',
            'RevOursMinusInfGptReasonWins': '12', 'RevOursMinusInfGptReasonLosses': '2',
            'RevFullOursMinusInfGptReasonWins': '7', 'RevFullOursMinusInfGptReasonLosses': '2',
            'RevInfGptReasonMinusInfGpt': '0.241', 'RevInfGptReasonMinusInfGptLo': '0.157', 'RevInfGptReasonMinusInfGptHi': '0.333',
            'RevInfGptReasonMinusInfGptCLo': '0.170', 'RevInfGptReasonMinusInfGptCHi': '0.312',   # exact value 0.3125; num() prints 0.312 (result.md rounded it up to 0.313)
           
            'RevInfGptReasonMinusInfGptWins': '28', 'RevInfGptReasonMinusInfGptLosses': '2', 'RevInfGptReasonMinusInfGptP': '$<$0.0001'}
for _k, _e in EXPECTED.items():
    assert VALUES[_k] == _e, f'EXPECTED {_k}: generated {VALUES[_k]}, expected {_e}'
assert (_s['done'], ndone(GRS, FULL108), _s['under']) == (_n['completed_108'], _n['completed_full_97'], _n['completed_under_11'])
assert abs(_s['mean'] - _n['mean_score']) < 1e-12 and abs(_s['rounds'] - _n['mean_rounds']) < 1e-12
assert (_tin, _tout, _treas, _tcach) == (_n['input_tokens'], _n['output_tokens'], _n['reasoning_tokens'], _n['cached_input_tokens'])
assert abs(_tot - _n['list_price_usd']) < 1e-9 and abs(_ct / 100 - _n['usd_per_task']) < 1e-12
assert (PGR['b'], PGR['c']) == (_v['a_only'], _v['b_only']) and abs(PGR['p'] - _v['mcnemar_exact_p']) < 1e-15
assert all(abs(x - y) < 1e-12 for x, y in zip((PGR['lo'], PGR['hi'], PGR['clo'], PGR['chi']), _v['task_ci95'] + _v['building_ci95']))
assert (PGRP['b'], PGRP['c']) == (_np['a_only'], _np['b_only']) and abs(PGRP['p'] - _np['mcnemar_exact_p']) < 1e-15
assert all(abs(x - y) < 1e-12 for x, y in zip((PGRP['lo'], PGRP['hi'], PGRP['clo'], PGRP['chi']), _np['task_ci95'] + _np['building_ci95']))
REPRO.append(('GPT-5.6 documented with reasoning on, every EXPECTED value (round4/gpt_reasoning/result_summary.json)',
              f'{len(EXPECTED)} macros', 'result.md', 'reproduced', True))


# ================================================================ tables
def write(name, text):
    (OUT / name).write_text(text)
    print(f'---------------- {name}\n{text}')


def bold(s):
    return f'\\textbf{{{s}}}'


# --- tab_parser_rev.tex
L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py from parser_baseline/results and the VeriBIM-9B reads; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering',
     r'\caption{Completion of the template parser and of \ModelName{} on the same tasks, with the counts of tasks completed by both, by one of them, or by neither. Bold marks the higher completion in each row.}',
     r'\label{tab:parser}', r'\footnotesize', r'\setlength{\tabcolsep}{4pt}',
     r'\begin{tabular}{@{}lrcccccc@{}}', r'\toprule',
     r' & & \multicolumn{2}{c}{Completion} & \multicolumn{4}{c}{Tasks completed by} \\',
     r'\cmidrule(lr){3-4}\cmidrule(l){5-8}',
     r'Task set & Tasks & Parser & \ModelName{} & Both & Parser only & \ModelName{} only & Neither \\', r'\midrule']
for label, q in PARSER_ROWS[:5]:
    pc, mc = num(q['pc']), num(q['mc'])
    best = max(q['pc'], q['mc'])
    pcs = bold(pc) if abs(q['pc'] - best) < 1e-12 else pc
    mcs = bold(mc) if abs(q['mc'] - best) < 1e-12 else mc
    if label == 'Rewritten wording':
        L.append(r'\midrule')
        label = 'Reworded instructions'
    L.append(f"{label} & {thou(q['n'])} & {pcs} & {mcs} & {thou(q['both'])} & {q['po']} & {q['mo']} & {q['ne']} \\\\")
# reworded benchmark tasks (round 4): the parser recognizes none, so the pairing follows from the two completion counts
_rw = json.load(open('analysis/revision/round4/reword_bench/reads/pairing_summary.json'))
_rw_n = _rw['models']['grpo_v10b_c10']['reworded']['n']; _rw_m = _rw['models']['grpo_v10b_c10']['reworded']['completed']
_rw_p = _rw['parser']['reworded']['completed']; assert _rw_p == 0 and _rw['parser']['reworded_recognised'] == 0, (_rw_p, _rw['parser']['reworded_recognised'])
L.append(r'\midrule')
L.append(f"Reworded benchmark tasks & {thou(_rw_n)} & {num(_rw_p / _rw_n)} & {bold(num(_rw_m / _rw_n))} & 0 & 0 & {_rw_m} & {_rw_n - _rw_m} \\\\")
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_parser_rev.tex', '\n'.join(L))


# --- tab_stats_rev.tex
def fmt_iv(lo, hi):
    return f'[{num(lo)}, {num(hi)}]'


def fmt_or(x):
    if x is None:
        return '--'
    return f'{x:.2f}' if x < 100 else f'{x:,.0f}'


L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py from stats/results/comparisons.csv and, for the comparisons added in this revision, the same methods applied to the per-task rows; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering',
     r'\caption{Paired comparisons of completion by five methods. $b$ counts the tasks that only the first arm completes and $c$ those that only the second arm completes. The mixed model is a logistic model with random intercepts for building and task, and GEE is a generalized estimating equation clustered by building. A double dash marks a value that cannot be estimated because one arm completes every discordant task or every task.}',
     r'\label{tab:stats}', r'\footnotesize', r'\setlength{\tabcolsep}{2.4pt}',
     # first column 4.8cm (2026-10-23): every comparison name fits on one line
     r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{4.8cm}rrcccrcc@{}}', r'\toprule',
     r' & & & Exact & \multicolumn{2}{c}{95\,\% interval of the difference} & \multicolumn{2}{c}{Mixed model} & GEE \\',
     r'\cmidrule(lr){5-6}\cmidrule(lr){7-8}',
     r'Comparison & $b$ & $c$ & McNemar $p$ & Tango score & Building bootstrap & Odds ratio & $p$ & $p$ \\']
STATROWS = []
for gi, (glabel, items) in enumerate(STAT_GROUPS):
    L.append(r'\midrule')
    L.append(f'\\multicolumn{{9}}{{@{{}}l}}{{{glabel}}} \\\\')
    for nm, s in items:
        if s['full_arm']:          # one arm completes every task: the mixed model and the GEE are not fitted
            s = dict(s, or_=None, lr_p=None, gee_p=None)
        STATROWS.append((glabel, nm, s))
        L.append(f"\\quad {nm} & {s['b']} & {s['c']} & {fmt_p(s['p'])} & {fmt_iv(s['tlo'], s['thi'])} & {fmt_iv(s['clo'], s['chi'])} & "
                 f"{fmt_or(s['or_'])} & {'--' if s['lr_p'] is None else fmt_p(s['lr_p'])} & {'--' if s['gee_p'] is None else fmt_p(s['gee_p'])} \\\\")
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_stats_rev.tex', '\n'.join(L))

# --- tab_arms_rev.tex (glossary of arms)
ARMS = [
    ('Alone', 'IfcOpenShell only, with no library and no note',
     'GPT-5.6, DeepSeek V4, Claude Sonnet 5.5, Gemini 3.8 Flash, untrained Qwen3.5-9B, imitation model',
     '108 tasks, and for Claude Sonnet 5.5 also 324 tasks and BIM-Edit', r'Tables~\ref{tab:main}, \ref{tab:main324} and~\ref{tab:bimedit}'),
    ('With the library', 'Helper library in the sandbox, no note',
     r'\ModelName{} and the training-stage models, and the untrained Qwen3.5-9B on BIM-Edit',
     '108, 324 and 2,100 tasks, and BIM-Edit', r'Tables~\ref{tab:main}, \ref{tab:main324}, \ref{tab:ablation} and~\ref{tab:bimedit}'),
    ('With the library note', 'Helper library and, after the instruction, a note that lists its functions',
     'GPT-5.6, DeepSeek V4, Claude Sonnet 5.5, Gemini 3.8 Flash, untrained Qwen3.5-9B',
     '108 tasks, and for Claude Sonnet 5.5 also 324 tasks and BIM-Edit', r'Tables~\ref{tab:main}, \ref{tab:main324} and~\ref{tab:bimedit}'),
    ('With the library note and the instruction to ask', 'As the library note, plus one sentence that tells the model to ask for a missing value and to leave the file unchanged',
     'GPT-5.6, DeepSeek V4, Claude Sonnet 5.5, Gemini 3.8 Flash', '108 tasks', r'Table~\ref{tab:stats}'),
    ('With the documented library', r'Helper library, documentation of every function, \RevInfConventions{} statements of the task conventions (one tells the model to ask) and \RevInfExamples{} worked examples',
     'GPT-5.6, DeepSeek V4, Claude Sonnet 5.5, Claude Opus 5.5, Gemini 3.8 Flash, untrained Qwen3.5-9B, Gemma 4 31B',
     '108 tasks, and for Claude Sonnet 5.5 also the other 216 tasks of the 324-task subset and two repeats on the 108', r'Tables~\ref{tab:main} and~\ref{tab:stats}'),
    ('Documented library with retrieved examples', 'As the documented library, with its worked examples replaced by the three most similar training trajectories',
     'Untrained Qwen3.5-9B', '108 tasks', r'Table~\ref{tab:stats}'),
    ('Library note with retrieved examples', 'Library note and the three most similar training trajectories',
     'Untrained Qwen3.5-9B', '108 tasks', r'Table~\ref{tab:stats}'),
    ('Template parser', "No language model, only the sentence patterns of the task generator and the generator's edit code",
     'None', '2,100 tasks and the 100 tasks of the rewritten-wording set', r'Table~\ref{tab:parser}'),
]
L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py; arm contents as in the protocol section and the run notes; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering',
     r'\caption{Evaluation arms. Each row states what the model receives besides the system prompt, the instruction and the code tool, which models run the arm, on which tasks, and where the results appear.}',
     r'\label{tab:arms}', r'\footnotesize', r'\setlength{\tabcolsep}{3pt}',
     r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{2.6cm}>{\raggedright\arraybackslash}p{4.0cm}>{\raggedright\arraybackslash}p{3.6cm}>{\raggedright\arraybackslash}p{2.6cm}>{\raggedright\arraybackslash}p{2.2cm}@{}}',
     r'\toprule', r'Arm & What the model receives & Models & Tasks & Results \\', r'\midrule']
for i, a in enumerate(ARMS):
    L.append(' & '.join(a) + r' \\')
    if i < len(ARMS) - 1:
        L.append(r'\addlinespace')
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_arms_rev.tex', '\n'.join(L))

# --- tab_gate_rev.tex (appendix): relation and deletion rows of the error study under the relation checks
L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py from checker_validity/results/mutation_gate_summary.json; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
     r'\caption{Share of controlled relation and deletion errors that the completion verdict accepts at 0.90 and at 0.98, and at 0.90 once the checks of storey containment, opening filling and empty relationships are added.}',
     r'\label{tab:gate}', r'\setlength{\tabcolsep}{4pt}', r'\begin{tabular}{lrrrr}', r'\toprule',
     r'Error written into the ground truth & Tasks & \multicolumn{3}{c}{Accepted (\%)} \\', r'\cmidrule(l){3-5}',
     r' & & at 0.90 & at 0.98 & at 0.90 with the relation checks \\', r'\midrule']
for key, lab in (('control', 'Correct edit (ground truth written again)'), ('containment', 'Storey containment removed'),
                 ('filling', 'Opening filling relation removed'), ('wrong_host', 'Door or window in the nearest other wall'),
                 ('del_control', 'Delete: correct deletion re-run on the source'),
                 ('del_naive', 'Delete: target removed, relationships to it left empty')):
    e = MG[key]
    if key == 'del_control':
        L.append(r'\addlinespace')
    L.append(f"{lab} & {e['n_applied']} & {pct(e['n_accept_090'], e['n_applied'])} & {pct(e['_strict_n'], e['n_applied'])} & {pct(e['n_gated_accept_090'], e['n_applied'])} \\\\")
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_gate_rev.tex', '\n'.join(L))

# --- tab_abserr_rev.tex: absolute errors of completed edits
L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py from checker_validity/results/abs_errors_summary.json and abs_tolerance_completion.json; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
     r'\caption{Absolute errors of the completed edits against the ground truth on the 108-task subset, and on all 2,100 tasks for \ModelName{}. The columns give the distance between element centers, the largest error over the three dimensions, share of targets within 1\,cm in both, and completions when every target must also lie within 1\,cm.}',
     r'\label{tab:abserr}', r'\setlength{\tabcolsep}{3pt}',
     r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{5.4cm}rrrrrcrrr@{}}', r'\toprule',
     r' & & \multicolumn{4}{c}{Center error (mm)} & Largest dimension & Within & \multicolumn{2}{c}{Completed} \\',
     r'\cmidrule(lr){3-6}\cmidrule(l){9-10}',
     r'Arm & Targets & Median & P95 & P99 & Max & error (mm) & 1\,cm (\%) & Rule & With 1\,cm \\', r'\midrule']
for i, (label, c, t) in enumerate(ABSROWS):
    p, dm = c['position'], c['dimension_max']
    if i == 2:
        L.append(r'\midrule')
    L.append(f"{label} & {thou(c['n_targets'])} & {1000 * p['median']:.1f} & {1000 * p['p95']:.1f} & {1000 * p['p99']:.1f} & {1000 * p['max']:.1f} & "
             f"{1000 * dm['max']:.1f} & {100 * c['_within']:.1f} & {thou(t['completed'])} & {thou(t['completed_within_1cm'])} \\\\")
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_abserr_rev.tex', '\n'.join(L))

# --- tab_schema_rev.tex: schema validation and clashes of completed edits
L = ['% GENERATED by analysis/revision/macros/make_macros_rev2.py from checker_validity/results/schema_clash_summary.json; do not edit by hand.',
     r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
     r'\caption{Schema errors and hard clashes that completed edits add to the source model, against those that the ground truth adds. Tasks: the \RevSchemaScopeN{} tasks of the 108-task subset whose source file is below \RevSchemaSizeLimitMB{}\,MB, and for \ModelName{} also \RevSchemaDrawScopeN{} of \RevSchemaDrawN{} tasks drawn from all 2,100. A cell gives the edits with at least one new error or clash and, in parentheses, their number. Output only counts those that the ground truth does not have.}',
     r'\label{tab:schema}', r'\setlength{\tabcolsep}{3pt}',
     r'\begin{tabular}{@{}>{\raggedright\arraybackslash}p{5.2cm}rccc rccc@{}}', r'\toprule',
     r' & \multicolumn{4}{c}{New schema errors} & \multicolumn{4}{c}{New clashes} \\',
     r'\cmidrule(lr){2-5}\cmidrule(l){6-9}',
     r'Arm & Edits & Ground truth & Output & Output only & Edits & Ground truth & Output & Output only \\', r'\midrule']


def _tc(a, b):
    return f'{a} ({b})'


for i, (label, c) in enumerate(SCHROWS):
    if i == 2:
        L.append(r'\midrule')
    lab = label.replace('all 2,100 tasks', 'sample of the 2,100 tasks')
    L.append(f"{lab} & {c['n']} & {_tc(c['tasks_with_new_errors_gt'], c['new_errors_gt_total'])} & {_tc(c['tasks_with_new_errors_output'], c['new_errors_output_total'])} & "
             f"{_tc(c['tasks_output_errors_beyond_gt'], c['output_errors_beyond_gt_total'])} & {c['n_with_clash_check']} & "
             f"{_tc(c['tasks_with_new_clash_gt'], c['new_clashes_gt_total'])} & {_tc(c['tasks_with_new_clash_output'], c['new_clashes_output_total'])} & "
             f"{_tc(c['tasks_output_clash_beyond_gt'], c['output_clashes_beyond_gt_total'])} \\\\")
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
write('tab_schema_rev.tex', '\n'.join(L))

# --- tab6_cost.tex: the current table with the Claude Sonnet 5.5 prices at the uncached list price
T6 = (ROOT / 'writing/tables/tab6_cost.tex').read_text()
lines6 = T6.split('\n')
model = None
NEWCELL = {}
for mid, name, tok in COMM:
    for arm, lab in (('Alone', 'Alone'), ('Lib', 'With the library')):
        c = COSTS[f'ResHundredEight{tok}{arm}CentsTaskList']
        NEWCELL[(name, lab)] = (f'{c[1]:.2f}', f'{c[2]:.2f}')
out6, cells = [], []
for ln in lines6:
    s = ln.strip()
    if s.endswith('\\\\') and '&' in s:
        c = [x.strip() for x in s[:-2].split('&')]
        if len(c) == 8 and c[1] in ('Alone', 'With the library'):
            model = c[0] or model
            cells.append([model, c])
            out6.append(None)
            continue
    out6.append(ln)
assert len(cells) == 9, len(cells)
unb = lambda x: re.sub(r'\\textbf\{(.*?)\}', r'\1', x)
for mdl, c in cells:
    if (mdl, c[1]) in NEWCELL:
        nt, nd = NEWCELL[(mdl, c[1])]
        if mdl != 'Claude Sonnet 5.5':
            assert (unb(c[6]), unb(c[7])) == (nt, nd), (mdl, c, nt, nd)    # unchanged: no cached tokens for these providers
        c[6], c[7] = nt, nd
for col in (6, 7):                                                          # bold the lowest price in each price column
    vals = [(float(unb(c[col])), i) for i, (_, c) in enumerate(cells) if unb(c[col]) != '--']
    lo = min(v for v, _ in vals)
    for i, (_, c) in enumerate(cells):
        u = unb(c[col])
        c[col] = bold(u) if u != '--' and float(u) == lo else u
it = iter(cells)
final6 = []
for ln in out6:
    if ln is None:
        mdl, c = next(it)
        final6.append(' & '.join(c) + r' \\')
    else:
        final6.append(ln)
txt6 = '\n'.join(final6)
txt6 = txt6.replace('% GENERATED by writing/tables/make_results_exhibits.py; do not edit by hand.',
                    '% GENERATED by analysis/revision/macros/make_macros_rev2.py from writing/tables/tab6_cost.tex, prices at the uncached list price; do not edit by hand.')
write('tab6_cost.tex', txt6)

# ================================================================ write macro files
hdr = ('% GENERATED by analysis/revision/macros/make_macros_rev2.py (revision of 2026-10-15); do not edit by hand.\n'
       '% Load after macros_rev.tex. Cost macros are at the uncached list price (input tokens x input price + output tokens x output price).\n')
clash = sorted(n for n in VALUES if n in OLD)
assert not clash, f'new macro names already defined: {clash}'
(OUT / 'macros_rev2.tex').write_text(hdr + '\n'.join(LINES) + '\n')
(OUT / 'macros_cost_listprice.tex').write_text(
    '% GENERATED by analysis/revision/macros/make_macros_rev2.py; do not edit by hand.\n'
    '% Drop-in alternative: redefines the earlier cost macros with the uncached list price. Load after macros_rev.tex and\n'
    '% writing/tables/macros_results_v10.tex. RevSpendAllUSD and the BIM-Edit cost macros are not here (see CHECKS.md).\n'
    + '\n'.join(DROPIN) + '\n')
json.dump({k: v for k, v in VALUES.items()}, open(OUT / 'values.json', 'w'), indent=1)

# ================================================================ CHECKS.md
C_ = ['# CHECKS for macros_rev2.tex and the revision tables of 2026-10-15', '',
      'Generated by make_macros_rev2.py. Completion = all three axes >= 0.9. Task-level intervals: exhibit boot() (10,000 resamples, seed 20260929, sorted[250]/[9749]); task order: see the order note below. Building-level: common.cboot. Tango: paired_methods.tango. Cost: uncached list price.', '',
      '## Reproduction of existing macros (run stops on any mismatch)', '', '| what | macro | printed | recomputed | match |', '|---|---|---|---|---|']
for w, m, p, r, ok in REPRO:
    C_.append(f'| {w} | {m} | {p} | {r} | {ok} |')
C_ += ['', f'Order note: {ORDER_NOTE}. The documented-arm macros of the manuscript (informed4.json, base_informed.json) resampled tasks in the order of subset_108_hosted.v4c.json; the new documented-type arms (Gemma 4 31B, the two retrieval arms) use the same subset-file order so that they sit consistently beside those rows; every other new interval uses sorted id order, the order of make_results_exhibits.paired() (note arms, ask-sentence arms).', '',
       '## Every macro of macros_rev2.tex', '', '| macro | value | raw | source and key |', '|---|---|---|---|']
for n, v, r, s in CHECKS:
    if n == '##':
        C_ += ['', f'### {v}', '', '| macro | value | raw | source and key |', '|---|---|---|---|']
    else:
        C_.append(f'| {n} | {v} | {r} | {s} |')
C_ += ['', '## Drop-in file macros_cost_listprice.tex (old names, new values)', '', '| old macro | printed (cached formula) | uncached list price | same value under the new name |', '|---|---|---|---|']
for o, p, n, nn in DROPCHK:
    C_.append(f'| {o} | {p} | {n} | {nn} |')
(OUT / 'CHECKS.md').write_text('\n'.join(C_) + '\n')
print(f'{len(LINES)} lines -> out/macros_rev2.tex; {len(DROPIN)} -> out/macros_cost_listprice.tex; CHECKS.md written')
