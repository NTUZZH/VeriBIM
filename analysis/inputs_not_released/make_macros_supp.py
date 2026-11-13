#!/usr/bin/env python3
"""Supplementary Material values of the proposed model that make_macros.py does not compute.

  usage: make_macros_supp.py CONFIG.json OUT.tex OUT.json [--blocks 1,2,3,4,5] [--stats-rows A:B] [--cache DIR]

CONFIG (see config_supp_template.json) names the configuration of make_macros.py (base_config: task files, stage
reads and comparison arms), the value file that make_macros.py wrote from it (first_values), and the inputs that only
this script reads: transcripts, the per-row classes of the imitation data, the cost values of make_macros_cost.py,
and the rows of tab:stats. Outputs: OUT.tex (\\newcommand lines, names \\Pm..., a header listing every input with
row count and SHA-256), OUT.json (the unformatted values, per-row detail and the run time of each block), and the
rows of tab:stats in OUT_frag_tab_stats.tex next to OUT.tex.

Blocks (each with the method of the old script that produced the old macro; the source is named at each function):
  1  runs on the 108-task subset that repeat an identical tool call three or more times in a row
  2  p of a logistic mixed model with a building intercept only (the stage difference of the prose)
  3  tab:stats: odds ratio and likelihood-ratio p of the mixed model with building and task intercepts, GEE p
  4  completion by the form of the committed edit, by the training style of the edit kind, and the Fisher tests
  5  local cost per completed edit at the yearly volumes of the cost sentence

The mixed models take about 20 s per comparison. --stats-rows A:B fits only rows A to B-1 of tab:stats, stores the
fits in the cache folder (default: OUT.json without .json, plus _modelcache) and writes no output, so that the 31
rows can run as several commands of a few minutes; the full run then reads the stored fits. A stored fit is used
only when its key, the SHA-256 of the two outcome vectors, the building of every task, the model and the SHA-256 of
the model code, matches.

The script stops with exit code 2 and a message on: a missing input, a per-task file or transcript set whose ids
are not exactly the expected task set, duplicate ids, a row without a score (the checks of make_macros.py), a
transcript whose stop reason differs from its per-task row, a discordant count that differs from the value of
make_macros.py for the same comparison, or an output path inside an input folder. No number is typed in this file.
"""
import argparse
import glob
import hashlib
import json
import math
import os
import re
import sys
import time
import warnings

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import numpy as np                                    # noqa: E402
from scipy import stats                               # noqa: E402
import make_macros as mm                              # noqa: E402
import supp_gee                                       # noqa: E402

STATS_DIR = 'stats'                        # glmm_ml.py
CLASSIFY_DIR = 'round4/traj_accounting/scripts'  # classify.py
sys.path.insert(0, STATS_DIR)
sys.path.insert(0, CLASSIFY_DIR)
import glmm_ml as G                                   # noqa: E402
from classify import classify_codes, calls_with_outputs, COMMIT   # noqa: E402

fail = mm.fail
TRACEBACK = 'Traceback (most recent call last)'       # scan_bench.py: a call whose output holds this did not run


def sha256_file(path):
    return mm.sha256(path)


METHOD_FILES = {'glmm_ml.py': os.path.join(STATS_DIR, 'glmm_ml.py'), 'classify.py': os.path.join(CLASSIFY_DIR, 'classify.py'),
                'supp_gee.py': os.path.join(HERE, 'supp_gee.py'), 'make_macros.py': os.path.join(HERE, 'make_macros.py')}


# ====================================================================== formats of the old macros
def fmt_or(x):
    """make_macros_rev2.fmt_or (tab_stats_rev.tex): -- when not estimable, two decimals below 100, else integer."""
    if x is None:
        return '--'
    return f'{x:.2f}' if x < 100 else f'{x:,.0f}'


def fmt_p_or_dash(p):
    """tab_stats_rev.tex p cells: -- when not estimable, else make_macros_rev2.fmt_p."""
    return '--' if p is None else mm.fmt_p(p)


def getpath(d, dotted, label):
    cur = d
    for k in dotted.split('.'):
        if not isinstance(cur, dict) or k not in cur:
            fail(f'{label}: key {dotted} not found')
        cur = cur[k]
    if not isinstance(cur, (int, float)) or isinstance(cur, bool) or not math.isfinite(cur):
        fail(f'{label}: {dotted} is not a finite number ({cur!r})')
    return float(cur)


# ====================================================================== transcripts
def read_transcripts(dirs, expect, label):
    """One transcript per task (<task_id>.json in one of `dirs`), the ids exactly `expect`. Registers the folders as
    one input whose SHA-256 is that of the sorted list of (task id, file SHA-256)."""
    if isinstance(dirs, str):
        dirs = [dirs]
    if not dirs:
        fail(f'{label}: no transcript folder given')
    files = {}
    for d in dirs:
        if not isinstance(d, str) or '<' in d or '>' in d:
            fail(f'{label}: the config still holds a placeholder: {d}')
    dirs = [os.path.normpath(d) for d in dirs]
    if len(set(dirs)) != len(dirs):
        fail(f'{label}: a transcript folder is named twice')
    for d in dirs:
        if not os.path.isabs(d) or not os.path.isdir(d):
            fail(f'{label}: transcript folder missing: {d}')
        for f in sorted(glob.glob(os.path.join(d, '*.json'))):
            tid = os.path.basename(f)[:-len('.json')]
            if tid in files:
                fail(f'{label}: task {tid} has a transcript in two folders ({files[tid]}, {f})')
            files[tid] = f
    exp = set(expect)
    if set(files) != exp:
        miss, extra = sorted(exp - set(files)), sorted(set(files) - exp)
        fail(f'{label}: transcripts are not the expected set of {len(exp)} tasks: {len(miss)} missing (for example '
             f'{miss[:3]}), {len(extra)} not expected (for example {extra[:3]})')
    T, H = {}, {d: [hashlib.sha256(), 0] for d in dirs}
    for tid in sorted(files):
        raw = open(files[tid], 'rb').read()
        hd = H[os.path.dirname(files[tid])]
        hd[0].update(f'{tid}:{hashlib.sha256(raw).hexdigest()}\n'.encode())
        hd[1] += 1
        t = json.loads(raw)
        if t.get('task_id') != tid:
            fail(f'{label}: {files[tid]} holds task {t.get("task_id")!r}')
        if not isinstance(t.get('messages'), list):
            fail(f'{label}: {files[tid]} has no message list')
        T[tid] = t
    for i, d in enumerate(dirs):         # one input per folder; SHA-256 of its sorted (task id: file SHA-256) lines
        mm.INPUTS.append((f'{label}, folder {i + 1} of {len(dirs)}', d.rstrip('/') + '/', H[d][1], H[d][0].hexdigest()))
    return T


def check_stop_reasons(T, rows, label):
    """Transcripts and per-task rows must come from the same run: equal stop reason on every task."""
    bad = [t for t in T if T[t].get('stop_reason') != rows[t].get('stop_reason')]
    if bad:
        fail(f'{label}: {len(bad)} transcripts have another stop reason than their per-task row, for example {bad[:3]}')
    calls = sum(1 for t in T if len(tool_calls(T[t])) != rows[t].get('tool_calls'))
    return {'transcripts': len(T), 'stop_reason_mismatches': 0, 'tool_call_count_differs': calls}


def tool_calls(t):
    return [c for m in t['messages'] if m.get('role') == 'assistant' for c in (m.get('tool_calls') or [])]


def max_identical_run(t):
    """Longest run of consecutive tool calls with the same function name and the same argument string (the rule
    behind report_provenance.md section 12, 'runs with >= 3 identical consecutive calls')."""
    best, run, prev = 0, 0, None
    for c in tool_calls(t):
        k = (c['function'].get('name'), c['function'].get('arguments'))
        run = run + 1 if (prev is not None and k == prev) else 1
        prev = k
        best = max(best, run)
    return best


# ====================================================================== form of the committed edit
def committed_form(t):
    """round4/traj_accounting/scripts/scan_bench.py, primary rule: the code of the
    calls that ran without a Python traceback, up to and including the last such call that commits, classified by
    classify.classify_codes; 'no_commit' when no successful call commits."""
    cw = calls_with_outputs(t['messages'])
    ok = [(c, o) for c, o in cw if o is not None and TRACEBACK not in o]
    last = max([i for i, (c, o) in enumerate(ok) if COMMIT.search(c)] or [-1])
    return classify_codes([c for c, _ in ok[:last + 1]])['cls'] if last >= 0 else 'no_commit'


def training_kinds(path, label):
    """Edit kinds of the imitation data by how their rows write the edit (traj_accounting summarize.py and extra.py):
    raw kinds = every row is raw IfcOpenShell code; library kinds = no raw row and no row without an edit. extra.py
    defined the library kinds as 'no raw row and not clarify'; the two rules must give the same set."""
    mm.check_path(path, label)
    meta_p = path[:-len('.jsonl')] + '.meta.json'
    mm.check_path(meta_p, label + ' (meta file)')
    meta = json.load(open(meta_p, encoding='utf-8'))
    if meta.get('part'):
        fail(f'{label}: {path} is a part; join the parts with supp_classify_training.py --concat')
    kinds, n, rows_seen = {}, 0, set()
    for line in open(path, encoding='utf-8'):
        r = json.loads(line)
        if r['row'] in rows_seen:
            fail(f'{label}: row {r["row"]} occurs twice')
        rows_seen.add(r['row'])
        if not r.get('edit_kind'):
            fail(f'{label}: row {r["row"]} has no edit kind')
        c = kinds.setdefault(r['edit_kind'], {'n': 0, 'raw': 0, 'none': 0})
        c['n'] += 1
        c['raw'] += r['cls'] == 'raw'
        c['none'] += r['cls'] == 'none'
        n += 1
    if n != meta.get('rows') or rows_seen != set(range(n)):
        fail(f'{label}: {n} rows, the meta file states {meta.get("rows")} (rows 0 to n-1 expected)')
    mm.register(label, path, n)
    mm.register(label + ', meta file', meta_p, n)
    mm.INPUTS.append((label + ', the training file it classifies (SHA-256 as recorded in the meta file)',
                      str(meta.get('training_file')), n, meta.get('training_file_sha256') or 'not recorded'))
    raw = sorted(k for k, c in kinds.items() if c['raw'] == c['n'])
    lib = sorted(k for k, c in kinds.items() if c['raw'] == 0 and c['none'] == 0)
    lib_extra = sorted(k for k, c in kinds.items() if c['raw'] == 0 and k != 'clarify')
    if lib != lib_extra:
        fail(f'{label}: the library kinds of summarize.py {lib} and of extra.py {lib_extra} differ')
    return raw, lib, kinds, meta


def fisher(ka, na, kb, nb):
    """traj_accounting extra.fisher: two-sided Fisher exact test on [[ka, na - ka], [kb, nb - kb]]."""
    return float(stats.fisher_exact([[ka, na - ka], [kb, nb - kb]])[1])


# ====================================================================== mixed models and GEE (tab:stats)
def separated(f):
    """make_macros_rev2.separated (= stats/tables.separated)."""
    b1, se = f.get('beta1'), f.get('se_beta1')
    return bool(f.get('separation') or b1 is None or se is None or not math.isfinite(se) or abs(b1) > 12 or se > 5)


class ModelCache:
    def __init__(self, folder, engine):
        self.folder, self.engine = folder, engine
        self.code = {k: sha256_file(p) for k, p in METHOD_FILES.items()}
        self.hits, self.fits = 0, 0

    def key(self, kind, ya, yb, bl):
        code = self.code['glmm_ml.py'] if kind.startswith('glmm') else (self.code['supp_gee.py'] + self.engine)
        s = json.dumps([kind, code, [int(x) for x in ya], [int(x) for x in yb], list(bl)])
        return hashlib.sha256(s.encode()).hexdigest()

    def get(self, kind, ya, yb, bl, fn):
        k = self.key(kind, ya, yb, bl)
        p = os.path.join(self.folder, f'{kind}_{k}.json')
        if os.path.exists(p):
            d = json.load(open(p, encoding='utf-8'))
            if d.get('key') == k:
                self.hits += 1
                return d['fit'], d['seconds'], True
        t0 = time.time()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            try:
                fit = mm.jsonable(fn())
            except Exception as e:                       # recorded and printed as --, never silent
                fit = {'error': repr(e)}
        sec = time.time() - t0
        for _, ip, _, _ in mm.INPUTS:                    # never write into the folder of an input
            if os.path.abspath(self.folder) == os.path.dirname(os.path.abspath(ip)):
                fail(f'model cache {self.folder} is the folder of the input {ip}')
        os.makedirs(self.folder, exist_ok=True)
        json.dump({'key': k, 'kind': kind, 'fit': fit, 'seconds': sec}, open(p, 'w', encoding='utf-8'), indent=1,
                  default=float)
        self.fits += 1
        return fit, sec, False


def gee_fit(ya, yb, bl, engine):
    if engine == 'port':
        return supp_gee.gee_bias_reduced(ya, yb, bl)
    if engine == 'statsmodels':                          # make_macros_rev2.gee_bias_reduced, body unchanged
        import pandas as pd
        import statsmodels.api as sm
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
    fail(f'gee_engine {engine!r} is neither port nor statsmodels')


# ====================================================================== the generator
STAGES, STAGETOK, SETTOK = mm.STAGES, mm.STAGETOK, mm.SETTOK


class Data:
    """Task sets (make_macros.Ctx) and the per-task rows of the reported model, its stages and the arms."""

    def __init__(self, base):
        self.base = base
        self.C = mm.Ctx(base)
        self.REP = base['reported']
        if self.REP not in STAGES or not base['stages'].get(self.REP):
            fail(f'reported stage {self.REP!r} is not one of the configured stages {base["stages"]}')
        self.rep_name = base['stages'][self.REP]
        self._cache = {}

    def stage_bench(self, st):
        key = ('bench', st)
        if key not in self._cache:
            p = (self.base['reads'].get('bench') or {}).get(st)
            if p is None:
                fail(f'reads.bench.{st} is not given in the base config')
            self._cache[key] = mm.read_per_task(p, self.C.ALL, f'2,100-task benchmark, {st} stage ({self.base["stages"][st]})')
        return self._cache[key]

    def reported(self, set_key):
        if set_key == 'bench':
            return self.stage_bench(self.REP)
        base_set = 'sub324' if set_key == 'rest216' else set_key
        key = ('rep', base_set)
        if key not in self._cache:
            ids = self.C.S108 if base_set == 'sub108' else self.C.S324
            self._cache[key] = mm.read_per_task(self.base['reads'][base_set][self.REP], ids,
                                                f'{SETTOK[base_set]} subset, dedicated read of {self.rep_name}')
        return self._cache[key]

    def arm(self, set_key, arm_key):
        base_set = 'sub324' if set_key == 'rest216' else set_key
        key = ('arm', base_set, arm_key)
        if key not in self._cache:
            arm = next((a for a in self.base.get('arms', {}).get(base_set, []) if a.get('key') == arm_key), None)
            if arm is None or arm.get('path') is None:
                fail(f'arm {arm_key} has no per-task file on {base_set} in the base config')
            self._cache[key] = mm.load_arm(arm, base_set, self.C, f'{SETTOK[base_set]} arm {arm_key} ({arm.get("model", "")}, {arm.get("arm", arm.get("label", ""))})')
        return self._cache[key]

    def side(self, set_key, spec):
        if spec == '@reported':
            return self.reported(set_key)
        if spec.startswith('@'):
            st = spec[1:]
            if set_key != 'bench' or st not in STAGES:
                fail(f'side {spec}: a stage read exists only on the benchmark')
            return self.stage_bench(st)
        return self.arm(set_key, spec)


def row_stem(r):
    a, b, sk = r['a'], r['b'], r['set']
    if sk not in SETTOK:
        fail(f'stats row {r.get("label")}: unknown set {sk}')
    if a == '@reported' and not b.startswith('@'):
        return f'{SETTOK[sk]}Minus{mm.check_key(b, "stats row arm")}'
    if a.startswith('@') and b.startswith('@') and a[1:] in STAGES and b[1:] in STAGES and sk == 'bench':
        return f'{SETTOK[sk]}{STAGETOK[a[1:]]}Minus{STAGETOK[b[1:]]}'
    fail(f'stats row {r.get("label")}: sides {a}, {b} on {sk} are not a reported-model or a stage comparison')


def pair_vectors(D, r):
    sk = r['set']
    ids = D.C.sets[sk]
    ra, rb = D.side(sk, r['a']), D.side(sk, r['b'])
    ya = np.array([int(mm.done(ra[t])) for t in ids])
    yb = np.array([int(mm.done(rb[t])) for t in ids])
    bl = [D.C.CL[t] for t in ids]
    return ids, ya, yb, bl


def run(cfg, args):
    base_path = cfg['base_config']
    mm.check_path(base_path, 'base config')
    base = json.load(open(base_path, encoding='utf-8'))
    mm.register('base config (make_macros.py)', base_path, len(base.get('reads', {})))
    D = Data(base)
    C = D.C
    o = mm.Out()
    blocks = sorted({int(x) for x in args.blocks.split(',')})
    timing, detail = {}, {}
    first = None
    if cfg.get('first_values'):
        mm.check_path(cfg['first_values'], 'value file of make_macros.py')
        first = json.load(open(cfg['first_values'], encoding='utf-8'))
        mm.register('value file of make_macros.py', cfg['first_values'], len(first.get('macros', {})))
        if first.get('reported', {}).get('model') != D.rep_name:
            fail(f'first_values: written for {first.get("reported")}, the base config reports {D.rep_name}')
    for k, p in METHOD_FILES.items():
        mm.register(f'method code {k}', p, sum(1 for _ in open(p, encoding='utf-8')))
    cache = ModelCache(args.cache, cfg.get('gee_engine', 'port'))
    src_rep = f'reported model {D.rep_name}'

    # ---------------------------------------------------------------- block 1
    if 1 in blocks and args.stats_rows is None:
        t0 = time.time()
        o.section(1, 'Runs that repeat an identical tool call three or more times in a row')
        L = cfg['loops']
        sk = L['set']
        thr = int(L['min_in_a_row'])
        ids = C.sets[sk]
        T = read_transcripts(L['transcripts'], ids, f'transcripts, {SETTOK[sk]} subset, {D.rep_name}')
        info = check_stop_reasons(T, D.reported(sk), f'transcripts, {SETTOK[sk]} subset')
        runs = {t: max_identical_run(T[t]) for t in ids}
        k = sum(1 for t in ids if runs[t] >= thr)
        o.put(f'Pm{SETTOK[sk]}LoopRuns', mm.thou(k), k, f'{SETTOK[sk]} subset, {src_rep}: runs with {thr} or more '
              'consecutive identical tool calls (same function, same arguments), report_provenance.md section 12 rule')
        o.put(f'Pm{SETTOK[sk]}LoopRunsN', mm.thou(len(ids)), len(ids), f'{SETTOK[sk]} subset, transcripts read')
        detail['loops'] = dict(info, threshold=thr, runs=k, n=len(ids), longest=max(runs.values()),
                               tasks=sorted(t for t in ids if runs[t] >= thr))
        timing['block1'] = time.time() - t0

    # ---------------------------------------------------------------- blocks 2 and 3 (models)
    rows_spec = []
    for g in cfg.get('stats_table', []):
        for r in g['rows']:
            rows_spec.append((g, r))
    engine = cfg.get('gee_engine', 'port')
    if engine == 'statsmodels':
        try:
            import statsmodels.api  # noqa: F401
        except ImportError:
            fail('gee_engine statsmodels: statsmodels is not installed in this Python; use gee_engine port')
    if 2 in blocks and args.stats_rows is None:
        t0 = time.time()
        o.section(2, 'Logistic mixed model with a building intercept only (prose of the tests paragraph)')
        for r in cfg.get('building_only', []):
            stem = row_stem(r)
            ids, ya, yb, bl = pair_vectors(D, r)
            f, sec, hit = cache.get('glmm_building', ya, yb, bl, lambda: G.fit_building_quadrature(ya, yb, bl))
            p = None if 'error' in f else f['lr_p']
            o.put(f'PmStat{stem}MixBuildingP', fmt_p_or_dash(p), p,
                  f'{r["set"]}, {r["a"]} minus {r["b"]}: likelihood-ratio p, logistic mixed model with a building '
                  'random intercept only (glmm_ml.fit_building_quadrature)')
            detail.setdefault('building_only', []).append(dict(stem=stem, fit=f, seconds=sec, from_cache=hit))
        timing['block2'] = time.time() - t0
    if 3 in blocks or args.stats_rows is not None:
        if not rows_spec:
            fail('stats_table: the config lists no rows')
        else:
            t0 = time.time()
            if args.stats_rows is None:
                o.section(3, 'tab:stats: mixed model with building and task intercepts, and GEE')
            lo, hi = 0, len(rows_spec)
            if args.stats_rows is not None:
                a_, b_ = args.stats_rows.split(':')
                lo, hi = int(a_), int(b_)
                if not 0 <= lo < hi <= len(rows_spec):
                    fail(f'--stats-rows {args.stats_rows}: the table has rows 0 to {len(rows_spec) - 1}')
            seen, out_rows, frag = set(), [], []
            for i, (g, r) in enumerate(rows_spec):
                stem = row_stem(r)
                if stem in seen:
                    fail(f'stats table: the comparison {stem} occurs twice')
                seen.add(stem)
                if not lo <= i < hi:
                    continue
                ids, ya, yb, bl = pair_vectors(D, r)
                n = len(ids)
                n11 = int(((ya == 1) & (yb == 1)).sum()); b = int(((ya == 1) & (yb == 0)).sum())
                c = int(((ya == 0) & (yb == 1)).sum()); n22 = n - n11 - b - c
                p_ex = mm.mcnemar_exact(b, c)
                cells = r['cells']
                if first is not None:
                    M = first['macros']
                    for suf, v in (('Wins', b), ('Losses', c)):
                        if f'{cells}{suf}' not in M:
                            fail(f'stats row {stem}: make_macros.py wrote no {cells}{suf}')
                        if M[f'{cells}{suf}']['value'] != v:
                            fail(f'stats row {stem}: {cells}{suf} is {M[cells + suf]["value"]} in the value file of '
                                 f'make_macros.py and {v} here (different per-task rows)')
                    if abs(M[f'{cells}P']['value'] - p_ex) > 1e-12 * max(1.0, p_ex):
                        fail(f'stats row {stem}: exact p differs from {cells}P')
                full_arm = int(ya.sum()) == n or int(yb.sum()) == n
                rec = dict(index=i, stem=stem, cells=cells, label=r['label'], set=r['set'], a=r['a'], b=r['b'], n=n,
                           a_done=int(ya.sum()), b_done=int(yb.sum()), n11=n11, b_count=b, c_count=c, n22=n22, exact_p=p_ex,
                           full_arm=full_arm, buildings=len(set(bl)))
                if full_arm:          # make_macros_rev2: one arm completes every task, so no model is fitted
                    rec.update(or_=None, lr_p=None, gee_p=None, note='one arm completes every task')
                else:
                    bt, sbt, hit1 = cache.get('glmm_building_task', ya, yb, bl, lambda: G.fit_building_task(ya, yb, bl))
                    ge, sge, hit2 = cache.get(f'gee_{engine}', ya, yb, bl, lambda: gee_fit(ya, yb, bl, engine))
                    rec['glmm'] = bt
                    rec['gee'] = ge
                    rec['seconds'] = {'glmm_building_task': sbt, 'gee': sge, 'from_cache': [hit1, hit2]}
                    if 'error' in bt:
                        rec.update(or_=None, lr_p=None, note_glmm='fit failed: ' + bt['error'])
                    else:
                        rec.update(or_=None if separated(bt) else bt['odds_ratio'], lr_p=bt['lr_p'])
                    if 'error' in ge:
                        rec.update(gee_p=None, note_gee='fit failed: ' + ge['error'])
                    else:
                        rec.update(gee_p=None if separated(ge) else ge['wald_p'])
                out_rows.append(rec)
                if args.stats_rows is not None:
                    print(f'make_macros_supp: row {i} {stem} fitted ({rec.get("seconds", {})})', flush=True)
                    continue
                src = f'{r["label"]} ({r["set"]}, {r["a"]} minus {r["b"]}, b = {b}, c = {c})'
                o.put(f'PmStat{stem}Or', fmt_or(rec['or_']), rec['or_'],
                      src + ', odds ratio, logistic mixed model with building and task intercepts (glmm_ml.fit_building_task)')
                o.put(f'PmStat{stem}MixP', fmt_p_or_dash(rec['lr_p']), rec['lr_p'], src + ', likelihood-ratio p of that model')
                o.put(f'PmStat{stem}GeeP', fmt_p_or_dash(rec['gee_p']), rec['gee_p'],
                      src + f', GEE p, exchangeable within building, bias-reduced covariance ({engine})')
            if args.stats_rows is not None:
                print(f'make_macros_supp: rows {lo} to {hi - 1} done, {cache.fits} fitted, {cache.hits} from the cache '
                      f'{args.cache}', flush=True)
                return None
            detail['stats_rows'] = out_rows
            # fragment rows
            for gi, g in enumerate(cfg.get('stats_table', [])):
                if gi:
                    frag.append(r'\midrule')
                frag.append(f'\\multicolumn{{9}}{{@{{}}l}}{{{g["header"]}}} \\\\')
                for r in g['rows']:
                    s, c_ = row_stem(r), r['cells']
                    frag.append(f'\\quad {r["label"]} & \\{c_}Wins{{}} & \\{c_}Losses{{}} & \\{c_}P{{}} & '
                                f'[\\{c_}TLo{{}}, \\{c_}THi{{}}] & [\\{c_}CLo{{}}, \\{c_}CHi{{}}] & '
                                f'\\PmStat{s}Or{{}} & \\PmStat{s}MixP{{}} & \\PmStat{s}GeeP{{}} \\\\')
            detail['stats_fragment'] = frag
            o.sub('prose values of the tests paragraph that are cells of tab:stats (one macro per quantity)')
            for al in cfg.get('prose_aliases', []):
                if al['macro'] not in o.vals:
                    fail(f'prose_aliases: {al["macro"]} (for {al["old"]}) is not a cell of the table')
                o.lines.append(f'% {al["old"]} (prose) is \\{al["macro"]}, value {o.vals[al["macro"]]["text"]}')
            timing['block3'] = time.time() - t0
            timing['block3_fits'] = {'fitted': cache.fits, 'from_cache': cache.hits}

    # ---------------------------------------------------------------- block 4
    if 4 in blocks and args.stats_rows is None:
        t0 = time.time()
        o.section(4, 'Completion by the form of the committed edit (2,100-task benchmark, reported model)')
        F = cfg['form_of_edit']
        rows = D.reported('bench')
        T = read_transcripts(F['transcripts'], C.ALL, f'transcripts, 2,100-task benchmark, {D.rep_name}')
        info = check_stop_reasons(T, rows, 'transcripts, 2,100-task benchmark')
        kind = {}
        for line in open(base['tasks']['benchmark'], encoding='utf-8'):
            if line.strip():
                r = json.loads(line)
                kind[r['task_id']] = r.get('edit_kind')
        if set(kind) != set(C.ALL) or any(not v for v in kind.values()):
            fail('benchmark task file: every task needs an edit_kind')
        raw_k, lib_k, kinds_train, meta = training_kinds(F['training_rows_class'], 'imitation data, rows by form of edit')
        mirror = F['mirror_kind']
        if mirror not in raw_k:
            fail(f'form_of_edit.mirror_kind {mirror!r} is not one of the raw-trained kinds {raw_k}')
        cls = {t: committed_form(T[t]) for t in C.ALL}
        dn = {t: int(mm.done(rows[t])) for t in C.ALL}
        src = f'2,100-task benchmark, {src_rep}'

        def put_group(stem, sel, what):
            k = sum(dn[t] for t in sel)
            o.put(stem + 'N', mm.thou(len(sel)), len(sel), src + f', {what}, tasks')
            o.put(stem + 'Done', mm.thou(k), k, src + f', {what}, completed')
            if sel:
                o.put(stem + 'Comp', mm.num(k / len(sel)), k / len(sel), src + f', {what}, completion {k}/{len(sel)}')
            return k, len(sel)

        o.sub('committed edit by form (scan_bench.py primary rule, classify.classify_codes)')
        form = {}
        for c_, tok, what in (('one_lib', 'OneCall', 'committed edit with one library edit call'),
                              ('multi_lib', 'MultiCall', 'committed edit with two or more library edit calls'),
                              ('raw', 'RawCode', 'committed edit in IfcOpenShell code without a library edit call'),
                              ('mixed', 'Mixed', 'committed edit with library edit calls and IfcOpenShell writes'),
                              ('none', 'NoEdit', 'committed with no detectable edit'),
                              ('no_commit', 'NoCommit', 'no successful commit')):
            form[c_] = put_group(f'PmBenchForm{tok}', [t for t in C.ALL if cls[t] == c_], what)
        o.sub('edit kinds by how the imitation data write them (summarize.py bench_by_training_style, extra.py fisher)')
        o.put('PmImitRawKinds', mm.thou(len(raw_k)), len(raw_k), 'edit kinds whose imitation rows all write raw IfcOpenShell code: ' + ', '.join(raw_k))
        o.put('PmImitLibKinds', mm.thou(len(lib_k)), len(lib_k), 'edit kinds whose imitation rows all use library edit calls: ' + ', '.join(lib_k))
        sel_raw = [t for t in C.ALL if kind[t] in raw_k]
        sel_lib = [t for t in C.ALL if kind[t] in lib_k]
        sel_mir = [t for t in C.ALL if kind[t] == mirror]
        sel_rnm = [t for t in sel_raw if kind[t] != mirror]
        kr = put_group('PmBenchRawKinds', sel_raw, 'tasks of the raw-trained kinds')
        kl = put_group('PmBenchLibKinds', sel_lib, 'tasks of the library-trained kinds')
        km = put_group('PmBenchMirror', sel_mir, f'tasks of the kind {mirror}')
        kn = put_group('PmBenchRawKindsNoMirror', sel_rnm, f'tasks of the raw-trained kinds without {mirror}')
        p1 = fisher(kr[0], kr[1], kl[0], kl[1])
        p2 = fisher(kn[0], kn[1], kl[0], kl[1])
        o.put('PmBenchRawKindsVsLibKindsP', mm.fmt_p(p1), p1, src + ', Fisher exact p, raw-trained against library-trained kinds')
        o.put('PmBenchRawKindsNoMirrorVsLibKindsP', mm.fmt_p(p2), p2,
              src + f', Fisher exact p, raw-trained kinds without {mirror} against library-trained kinds')
        detail['form_of_edit'] = dict(info, classes={c_: {'completed': v[0], 'n': v[1]} for c_, v in form.items()},
                                      raw_kinds=raw_k, library_kinds=lib_k, training_rows=meta.get('rows'),
                                      training_file=meta.get('training_file'),
                                      training_kind_counts=kinds_train,
                                      raw_kinds_tasks=kr, library_kinds_tasks=kl, mirror_tasks=km, raw_no_mirror_tasks=kn,
                                      fisher_raw_vs_lib=p1, fisher_raw_no_mirror_vs_lib=p2,
                                      committed_flag=sum(bool(rows[t].get('committed')) for t in C.ALL),
                                      successful_commit=sum(1 for t in C.ALL if cls[t] != 'no_commit'),
                                      kinds_of_committed={'raw-trained kind written as raw code': sum(1 for t in sel_raw if cls[t] == 'raw'),
                                                          'raw-trained kind written with the library': sum(1 for t in sel_raw if cls[t] in ('one_lib', 'multi_lib')),
                                                          'library-trained kind written with the library': sum(1 for t in sel_lib if cls[t] in ('one_lib', 'multi_lib')),
                                                          'library-trained kind written as raw code': sum(1 for t in sel_lib if cls[t] == 'raw')})
        timing['block4'] = time.time() - t0

    # ---------------------------------------------------------------- block 5
    if 5 in blocks and args.stats_rows is None:
        t0 = time.time()
        o.section(5, 'Local cost per completed edit at three yearly volumes (Singapore)')
        K = cfg['cost']
        mm.check_path(K['values_json'], 'cost values (make_macros_cost.py)')
        V = json.load(open(K['values_json'], encoding='utf-8'))
        mm.register('cost values (make_macros_cost.py)', K['values_json'], len(V))
        annual = getpath(V, K['annual_key'], 'cost values')
        elec = getpath(V, K['elec_key'], 'cost values')
        for v in K['volumes']:
            name = mm.check_key(v['key'], 'cost.volumes')
            n_ed = v['edits']
            if not isinstance(n_ed, int) or n_ed <= 0:
                fail(f'cost.volumes {name}: edits must be a positive integer')
            cents = annual * 100.0 / n_ed + elec            # make_macros_rev.py RevSgLocal* rule
            if v['unit'] == 'dollars':
                o.put(f'PmSgLocal{name}', f'{cents / 100.0:.2f}', cents / 100.0,
                      f'(S$ {annual:,.0f} a year / {n_ed:,} completed edits + {elec:.5f} Singapore cents of electricity), S$ per completed edit')
            elif v['unit'] == 'cents':
                o.put(f'PmSgLocal{name}', f'{cents:.1f}', cents,
                      f'(S$ {annual:,.0f} a year / {n_ed:,} completed edits + {elec:.5f} Singapore cents of electricity), Singapore cents per completed edit')
            else:
                fail(f'cost.volumes {name}: unit must be dollars or cents')
        detail['cost'] = {'annual_sgd': annual, 'electricity_sg_cents_per_edit': elec}
        timing['block5'] = time.time() - t0
    return o, detail, timing, cache


def precheck_outputs(cfg, args):
    """Before any work: no output (OUT.tex, OUT.json, the cache folder) goes into the folder of a file the configs
    name. The full check against every registered input runs again before writing."""
    paths = [os.path.abspath(args.config)]

    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and x.startswith('/') and os.path.exists(x):
            paths.append(os.path.abspath(x))
    walk(cfg)
    if os.path.exists(cfg.get('base_config', '')):
        walk(json.load(open(cfg['base_config'], encoding='utf-8')))
    outs = [os.path.abspath(args.out_tex), os.path.abspath(args.out_json), os.path.abspath(args.cache) + '/x']
    for o_ in outs:
        for p in paths:
            if os.path.dirname(o_) == os.path.dirname(p):
                fail(f'output {o_} would be written into the folder of the input {p}')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('config')
    ap.add_argument('out_tex')
    ap.add_argument('out_json')
    ap.add_argument('--blocks', default='1,2,3,4,5')
    ap.add_argument('--stats-rows', default=None, help='A:B, fit rows A to B-1 of tab:stats into the cache and stop')
    ap.add_argument('--cache', default=None)
    args = ap.parse_args()
    if not args.out_tex.endswith('.tex') or not args.out_json.endswith('.json'):
        print('make_macros_supp: ERROR: OUT.tex must end in .tex and OUT.json in .json', file=sys.stderr)
        sys.exit(2)
    if args.cache is None:
        args.cache = args.out_json[:-len('.json')] + '_modelcache'
    t_all = time.time()
    try:
        mm.check_path(os.path.abspath(args.config), 'config')
        cfg = json.load(open(args.config, encoding='utf-8'))
        precheck_outputs(cfg, args)
        mm.register('config of this script', os.path.abspath(args.config), len(cfg))
        res = run(cfg, args)
        if res is None:
            return
        o, detail, timing, cache = res
        frag_path = args.out_tex[:-len('.tex')] + '_frag_tab_stats.tex'
        mm.guard_output(args.cache + '/x')
        mm.guard_output(args.out_tex)
        mm.guard_output(args.out_json)
        if 'stats_fragment' in detail:
            mm.guard_output(frag_path)
    except mm.GenError as e:
        print(f'make_macros_supp: ERROR: {e}', file=sys.stderr)
        sys.exit(2)
    base = json.load(open(cfg['base_config'], encoding='utf-8'))
    rep = base['reported']
    H = ['% GENERATED by analysis/make_macros_supp.py; do not edit by hand.',
         f'% config: {os.path.abspath(args.config)} ({cfg.get("label", "")})',
         f'% base config: {cfg["base_config"]} ({base.get("label", "")})',
         f'% reported model: {base["stages"][rep]} ({rep} stage); GEE engine: {cfg.get("gee_engine", "port")}',
         '% completion: geometry, semantics and topology all >= 0.9 (make_results_exhibits.done)',
         f'% {len(o.vals)} macros; inputs (label | rows | SHA-256 | path):']
    for lab, p, n, h in mm.INPUTS:
        H.append(f'%   {lab} | {n} | {h} | {p}')
    open(args.out_tex, 'w', encoding='utf-8').write('\n'.join(H + o.lines) + '\n')
    if 'stats_fragment' in detail:
        fh = [f'% GENERATED by analysis/make_macros_supp.py from {os.path.basename(args.config)} (reported model '
              f'{base["stages"][rep]}); the rows of tab:stats between the column header and \\bottomrule; do not edit by hand.']
        open(frag_path, 'w', encoding='utf-8').write('\n'.join(fh + detail['stats_fragment']) + '\n')
    timing['total'] = time.time() - t_all
    J = {'generator': 'analysis/make_macros_supp.py', 'config': os.path.abspath(args.config), 'label': cfg.get('label'),
         'base_config': cfg['base_config'], 'reported': {'stage': rep, 'model': base['stages'][rep]},
         'gee_engine': cfg.get('gee_engine', 'port'), 'blocks': args.blocks,
         'inputs': [{'label': a, 'path': p, 'rows': n, 'sha256': h} for a, p, n, h in mm.INPUTS],
         'macros': o.vals, 'timing_seconds': timing, 'detail': mm.jsonable(detail),
         'fragment': frag_path if 'stats_fragment' in detail else None, 'model_cache': args.cache}
    json.dump(J, open(args.out_json, 'w', encoding='utf-8'), indent=1, default=float)
    print(f'make_macros_supp: {len(o.vals)} macros, {len(mm.INPUTS)} inputs; seconds per block ' +
          ', '.join(f'{k} {v:.1f}' for k, v in timing.items() if isinstance(v, float)))


if __name__ == '__main__':
    main()
