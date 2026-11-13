#!/usr/bin/env python3
"""One generator for every number of the proposed model in the manuscript.

Reads the per-task result files named in a JSON config (see analysis/config.json) and writes
  --out-tex          one LaTeX file of \\newcommand lines, names starting with \\Pm, grouped in eight blocks, with a header
                     that lists every input file (rows, SHA-256)
  --out-json         the same values unformatted, plus the rows of every table fragment
  --fragments-prefix the table-row fragments: <prefix>frag_tab_main_full.tex, frag_tab_main_compact.tex,
                     frag_tab_324.tex, frag_tab_threshold.tex, frag_tab_per_building.tex, frag_tab5_failures.tex

Run from the repository root (a relative path in the config is read from there):
    python analysis/make_macros.py \\
        --config CONFIG.json --out-tex OUT.tex --out-json OUT.json --fragments-prefix PREFIX

The script stops with exit code 2 and a message on: a missing input, a per-task file whose ids are not exactly the
expected task set, duplicate ids, a row without a score object (geometry, semantics, topology), a placeholder left in
a config path, or an output path inside an input folder.

Every statistic is a copy of the function of the old chain that computed the same kind of quantity; the source of each
function is named in its docstring. No number is typed in this file or in the config: every value comes from a
per-task file named in the config (the config names files, models, labels and task-set sizes to check against).
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import re
import statistics
import sys

import numpy as np
from scipy import optimize, stats


class GenError(Exception):
    pass


def fail(msg):
    raise GenError(msg)


# ====================================================================== constants of the old chain
SEED, R = 20260929, 10000                       # make_results_exhibits.py SEED, R
SEED_CLEAN, NBOOT_CLEAN = 20261018, 10000       # gt_validity/summarize.py SEED, NBOOT
SEED_HYB, B_HYB = 20261026, 10000               # hybrid_baseline/summarize_hybrid.boot
Z_RW = 1.959963984540054                        # round4/reword_bench/summarize_rw.Z
Z_ARMS = 1.96                                   # local_arms/analysis/summarize_arms.wilson
Z95 = stats.norm.ppf(0.975)                     # stats/paired_methods.Z95
Z90 = stats.norm.ppf(0.95)                      # paired_methods.all_methods(alpha=0.10)
AX = ('geometry', 'semantics', 'topology')
VERS = ['IFC2X3', 'IFC4', 'IFC4X3']             # make_results_exhibits.VERS
ORIGS = ['native', 'migrated']                  # make_results_exhibits.ORIGS
OPS = ['create', 'update', 'delete']            # make_results_exhibits.OPS
CATS = ['direct', 'spatial', 'topological']     # make_results_exhibits.CATS
TH = [0.85, 0.90, 0.95, 0.98]                   # stats/subset_stats.TH
GTOK = {'IFC2X3': 'TwoXThree', 'IFC4': 'Four', 'IFC4X3': 'FourXThree', 'native': 'Native', 'migrated': 'Migrated'}
THTOK = {0.85: 'EightyFive', 0.90: 'Ninety', 0.95: 'NinetyFive', 0.98: 'NinetyEight'}
SETTOK = {'bench': 'Bench', 'sub108': 'HundredEight', 'sub324': 'ThreeTwentyFour', 'rest216': 'TwoSixteen',
          'rw': 'Rw', 'prac': 'Prac'}
STAGES = ['imitation', 'preference', 'reinforcement']
STAGETOK = {'imitation': 'Imitation', 'preference': 'Preference', 'reinforcement': 'Reinforcement'}
END_CLASSES = ['completed', 'wrong_commit', 'sandbox_crash', 'tool_timeout', 'turn_truncated', 'context_limit',
               'round_budget', 'provider_error', 'reply_no_commit', 'other']
ENDTOK = {'completed': 'Completed', 'wrong_commit': 'WrongCommit', 'sandbox_crash': 'Crash', 'tool_timeout': 'Timeout',
          'turn_truncated': 'Truncated', 'context_limit': 'Context', 'round_budget': 'Budget',
          'provider_error': 'ProviderError', 'reply_no_commit': 'Asked', 'other': 'Other'}
T5_CLASSES = ['committed_rejected', 'round_limit', 'context_limit', 'reply_only', 'other_stop']
T5TOK = {'committed_rejected': 'Committed', 'round_limit': 'Rounds', 'context_limit': 'Context', 'reply_only': 'Reply',
         'other_stop': 'Other'}
T5HEAD = {'committed_rejected': 'Committed, rejected', 'round_limit': 'Round limit', 'context_limit': 'Context limit',
          'reply_only': 'Reply, no edit', 'other_stop': 'Other stop'}


# ====================================================================== completion rule and outcome classes
def done(r):
    """make_results_exhibits.done: geometry, semantics and topology all >= 0.9 (None counts as 0)."""
    s = r.get('score') or {}
    return 1.0 if all((s.get(k) or 0) >= 0.9 for k in AX) else 0.0


def axes(r):
    """stats/common.axes."""
    s = r.get('score') or {}
    return tuple((s.get(k) or 0.0) for k in AX)


def done_at(r, t):
    """stats/common.done_at: every axis >= t."""
    return 1.0 if min(axes(r)) >= t else 0.0


def outcome_class(r):
    """make_results_exhibits.outcome_class (Table 5 classes)."""
    if done(r):
        return 'completed'
    if r.get('committed'):
        return 'committed_rejected'
    sr = r.get('stop_reason')
    if sr == 'budget_exhausted':
        return 'round_limit'
    if sr in ('context_overflow', 'output_truncated'):
        return 'context_limit'
    if sr == 'completed':
        return 'reply_only'
    return 'other_stop'


def end_class(r):
    """stats/failure_ends.end_class (how a run ended; Table S22 classes)."""
    if done(r):
        return 'completed'
    if r.get('committed'):
        return 'wrong_commit'
    sr = r.get('stop_reason')
    fin = r.get('finish_reasons') or []
    if sr == 'sandbox_crash':
        return 'sandbox_crash'
    if sr == 'tool_timeout':
        return 'tool_timeout'
    if sr == 'output_truncated' or (fin and fin[-1] == 'length'):
        return 'turn_truncated'
    if sr == 'context_overflow':
        return 'context_limit'
    if sr == 'budget_exhausted':
        return 'round_budget'
    if r.get('error'):
        return 'provider_error'
    if sr == 'completed':
        return 'reply_no_commit'
    return 'other'


# ====================================================================== intervals and tests (copied, bodies unchanged)
def boot(vals):
    """make_results_exhibits.boot: percentile bootstrap over tasks, 10,000 resamples drawn in batches
    of 250 from numpy default_rng(20260929), lower sorted[250], upper sorted[9749]. Depends on the task order."""
    v = np.asarray(vals, float)
    n = len(v)
    rng = np.random.default_rng(SEED)
    means = np.empty(R)
    for s in range(0, R, 250):
        idx = rng.integers(0, n, size=(min(250, R - s), n))
        means[s:s + len(idx)] = v[idx].mean(1)
    means.sort()
    return float(v.mean()), float(means[int(0.025 * R)]), float(means[int(0.975 * R) - 1])


def boot90(vals):
    """stats/run_stats.boot_exhibit90: the draws of boot(), sorted[500] / sorted[9499]."""
    v = np.asarray(vals, float)
    rng = np.random.default_rng(SEED)
    m = np.empty(R)
    for s in range(0, R, 250):
        ix = rng.integers(0, len(v), size=(min(250, R - s), len(v)))
        m[s:s + len(ix)] = v[ix].mean(1)
    m.sort()
    return float(v.mean()), float(m[int(0.05 * R)]), float(m[int(0.95 * R) - 1])


def _pct(st):
    """stats/common._pct."""
    st = np.sort(st)
    return float(st[int(0.025 * R)]), float(st[int(0.975 * R) - 1])


def cboot(vals, ids, clus):
    """stats/common.cboot: building-level cluster bootstrap of a mean over tasks
    (buildings drawn with replacement, ratio of summed values to summed task counts); returns (point, lo, hi, n_bld)."""
    v = np.asarray(vals, float)
    c = [clus[t] for t in ids]
    B = sorted(set(c))
    bi = {b: i for i, b in enumerate(B)}
    s, n = np.zeros(len(B)), np.zeros(len(B))
    for x, cc in zip(v, c):
        s[bi[cc]] += x
        n[bi[cc]] += 1
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(B), size=(R, len(B)))
    lo, hi = _pct(s[idx].sum(1) / n[idx].sum(1))
    return float(v.mean()), lo, hi, len(B)


def boot_clean(x):
    """gt_validity/summarize.boot_ci with a fresh default_rng(20261018): one
    (10,000 x n) draw, sorted[250] / sorted[9749]."""
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return (None, None)
    rng = np.random.default_rng(SEED_CLEAN)
    idx = rng.integers(0, n, size=(NBOOT_CLEAN, n))
    m = np.sort(x[idx].mean(axis=1))
    return (float(m[int(0.025 * NBOOT_CLEAN)]), float(m[int(0.975 * NBOOT_CLEAN) - 1]))


def boot_hybrid(diffs, seed=SEED_HYB, B=B_HYB):
    """hybrid_baseline/summarize_hybrid.boot: Python random.Random(20261026),
    10,000 resamples, ms[250] / ms[9749]."""
    rng = random.Random(seed)
    n = len(diffs)
    ms = []
    for _ in range(B):
        s = [diffs[rng.randrange(n)] for _ in range(n)]
        ms.append(sum(s) / n)
    ms.sort()
    return ms[int(0.025 * B)], ms[int(0.975 * B) - 1]


def mcnemar_exact(b, c):
    """stats/paired_methods.mcnemar_exact: min(1, 2 P(X <= min(b, c))), X ~ Bin(b+c, 1/2)."""
    n = b + c
    if n == 0:
        return 1.0
    return float(min(1.0, 2.0 * stats.binom.cdf(min(b, c), n, 0.5)))


def wilson_pm(x, n, z=Z95):
    """paired_methods.wilson (used by newcombe)."""
    if n == 0:
        return 0.0, 1.0
    p = x / n
    den = 1 + z * z / n
    mid = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, mid - half), min(1.0, mid + half)


def newcombe(n11, n12, n21, n22, z=Z95):
    """paired_methods.newcombe: Newcombe (1998) method 10 for a paired difference."""
    N = n11 + n12 + n21 + n22
    p1, p2 = (n11 + n12) / N, (n11 + n21) / N
    d = p1 - p2
    l1, u1 = wilson_pm(n11 + n12, N, z)
    l2, u2 = wilson_pm(n11 + n21, N, z)
    den = (n11 + n12) * (n21 + n22) * (n11 + n21) * (n12 + n22)
    phi = (n11 * n22 - n12 * n21) / math.sqrt(den) if den > 0 else 0.0
    lo = d - math.sqrt(max(0.0, (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2))
    hi = d + math.sqrt(max(0.0, (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2))
    return max(-1.0, lo), min(1.0, hi)


def tango_z(n12, n21, N, d0):
    """paired_methods.tango_z: score statistic of H0 delta = d0 (Tango 1998), closed-form constrained MLE."""
    A = 2.0 * N
    B = -n12 - n21 + (2.0 * N - n12 + n21) * d0
    C = -n21 * d0 * (1.0 - d0)
    p21 = (math.sqrt(max(0.0, B * B - 4 * A * C)) - B) / (2 * A)
    var = N * (2 * p21 + d0 * (1 - d0))
    if var <= 0:
        return math.copysign(math.inf, (n12 - n21 - N * d0)) if (n12 - n21 - N * d0) != 0 else 0.0
    return (n12 - n21 - N * d0) / math.sqrt(var)


def tango(n11, n12, n21, n22, z=Z95):
    """paired_methods.tango: Tango score interval for a paired difference."""
    N = n11 + n12 + n21 + n22
    d = (n12 - n21) / N
    eps = 1e-10
    f_lo = lambda d0: tango_z(n12, n21, N, d0) - z      # noqa: E731
    f_hi = lambda d0: tango_z(n12, n21, N, d0) + z      # noqa: E731
    lo = -1.0 if f_lo(-1 + eps) < 0 else optimize.brentq(f_lo, -1 + eps, d, xtol=1e-12)
    hi = 1.0 if f_hi(1 - eps) > 0 else optimize.brentq(f_hi, d, 1 - eps, xtol=1e-12)
    return lo, hi


def holm(ps):
    """macros/make_macros_rev2.holm (= stats/tables.holm): step-down, running max."""
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj


def wilson_rw(k, n):
    """round4/reword_bench/summarize_rw.wilson: z = 1.959963984540054, bounds rounded
    to four decimals and clamped to [0, 1] (the 172 reworded tasks)."""
    if n == 0:
        return None
    p = k / n
    d = 1 + Z_RW * Z_RW / n
    c = (p + Z_RW * Z_RW / (2 * n)) / d
    h = Z_RW * math.sqrt(p * (1 - p) / n + Z_RW * Z_RW / (4 * n * n)) / d
    return [round(max(0.0, c - h), 4), round(min(1.0, c + h), 4)]


def wilson_arms(k, n, z=Z_ARMS):
    """local_arms/analysis/summarize_arms.wilson: z = 1.96, no rounding (the 200
    practitioners' requests)."""
    if n == 0:
        return (0, 0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


# ====================================================================== number formats of the old macros
def num(x, d=3):
    """make_macros_rev2.num: fixed decimals, no plus sign, negative as $-$."""
    s = f'{abs(x):.{d}f}'
    return ('$-$' + s) if round(x, d) < 0 else s


def needs_four(lo, hi):
    """make_results_exhibits.needs_four: a nonzero bound that prints 0.000 at three decimals."""
    return any(x != 0 and f'{abs(x):.3f}' == '0.000' for x in (lo, hi))


def bounds(lo, hi):
    """Both bounds of an interval of a difference, with four decimals when needs_four (make_results_exhibits.txt4)."""
    d = 4 if needs_four(lo, hi) else 3
    return num(lo, d), num(hi, d)


def thou(n):
    """make_macros_rev2.thou: integer with thousands separators."""
    return f'{int(round(n)):,}'


def fmt_p(p):
    """make_macros_rev2.fmt_p: two significant digits down to 0.0001, below that the bound."""
    if p >= 0.995:
        return '1.00'
    if p < 1e-4:
        return '$<$0.0001'
    for lim, d in ((0.1, 2), (0.01, 3), (0.001, 4), (1e-4, 5)):
        if p >= lim:
            return f'{p:.{d}f}'


def fmt_p_sci(p):
    """make_macros_rev2.fmt_p_sci: fmt_p at 0.001 and above, scientific form below (Holm family macros)."""
    if p >= 1e-3:
        return fmt_p(p)
    m, e = f'{p:.1e}'.split('e')
    return f'${m}\\times10^{{{int(e)}}}$'


def f2(x):
    return f'{x:.2f}'


def kilo(x):
    """make_results_exhibits.write_macros TokensIn / TokensOut: mean tokens per task in thousands, one decimal."""
    return f'{x / 1e3:.1f}'


def pct1(k, n):
    """make_macros_rev RevUnderSharePct style: percent with one decimal."""
    return f'{100 * k / n:.1f}'


def bname(b):
    """stats/subset_stats.bname."""
    return b.replace('GNI-project_', 'GNI project ')


# ====================================================================== inputs
INPUTS = []          # (label, path, rows, sha256)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def check_path(path, label):
    if not isinstance(path, str) or not path:
        fail(f'{label}: no path given in the config')
    if '<' in path or '>' in path:
        fail(f'{label}: the config path still holds a placeholder: {path}')
    if not os.path.isfile(path):
        fail(f'{label}: input file missing: {path}')


def register(label, path, nrows):
    INPUTS.append((label, path, nrows, sha256(path)))


def read_jsonl_rows(path, label):
    check_path(path, label)
    rows, dup = {}, []
    with open(path, encoding='utf-8') as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                fail(f'{label}: line {i + 1} of {path} is not JSON ({e})')
            t = r.get('task_id')
            if not t:
                fail(f'{label}: line {i + 1} of {path} has no task_id')
            if t in rows:
                dup.append(t)
            rows[t] = r
    if dup:
        fail(f'{label}: {len(dup)} duplicate task ids in {path}, for example {dup[:3]}')
    register(label, path, len(rows))
    return rows


def read_per_task(paths, expect, label):
    """Per-task result rows of one arm. Fails unless the ids are exactly `expect` and every row has a score."""
    paths = [paths] if isinstance(paths, str) else list(paths or [])
    if not paths:
        fail(f'{label}: no per-task file given')
    rows = {}
    for p in paths:
        r = read_jsonl_rows(p, label)
        both = sorted(set(r) & set(rows))
        if both:
            fail(f'{label}: {len(both)} task ids occur in more than one file, for example {both[:3]}')
        rows.update(r)
    exp = set(expect)
    if set(rows) != exp:
        miss, extra = sorted(exp - set(rows)), sorted(set(rows) - exp)
        fail(f'{label}: the ids are not the expected set of {len(exp)} tasks: {len(miss)} missing (for example '
             f'{miss[:3]}), {len(extra)} not expected (for example {extra[:3]}); files {paths}')
    bad = sorted(t for t, r in rows.items()
                 if not isinstance(r.get('score'), dict) or any(k not in r['score'] for k in AX))
    if bad:
        fail(f'{label}: {len(bad)} rows without a score (no score object with geometry, semantics and topology), '
             f'for example {bad[:3]}')
    return rows


class Ctx:
    """Task sets and task attributes."""

    def __init__(self, cfg):
        tk = cfg['tasks']
        ex = cfg['expect']
        check_path(tk['benchmark'], 'benchmark task file')
        self.T = {}
        for line in open(tk['benchmark'], encoding='utf-8'):
            if line.strip():
                r = json.loads(line)
                if r['task_id'] in self.T:
                    fail(f'benchmark task file: duplicate id {r["task_id"]}')
                self.T[r['task_id']] = {k: r.get(k) for k in ('ifc_version', 'origin', 'operation', 'category', 'tier',
                                                               'building_id', 'families', 'clarification')}
        register('benchmark task file', tk['benchmark'], len(self.T))
        self.ALL = sorted(self.T)
        self.S108 = self._subset(tk['subset108'], 'subset 108')
        self.S324 = self._subset(tk['subset324'], 'subset 324')
        if (len(self.T), len(self.S108), len(self.S324)) != (ex['bench'], ex['sub108'], ex['sub324']):
            fail(f'task-set sizes {len(self.T)}, {len(self.S108)}, {len(self.S324)} differ from the config expect block')
        if not set(self.S108) <= set(self.S324):
            fail('the 108-task subset is not inside the 324-task subset')
        self.REST = sorted(set(self.S324) - set(self.S108))      # analyze_216.REST
        self.UNDER = {t for t in self.T if self.T[t]['clarification']}
        fam = {t for t in self.T if 'wording.underspecified' in (self.T[t]['families'] or [])}
        if fam != self.UNDER:
            fail('clarification flag and wording.underspecified family disagree (make_macros_rev2 assertion)')
        self.CL = {t: self.T[t]['building_id'] for t in self.T}
        self.BLD = sorted(set(self.CL.values()))
        self.sets = {'bench': self.ALL, 'sub108': sorted(self.S108), 'sub324': sorted(self.S324), 'rest216': self.REST}
        self.file_order = {'sub108': list(self.S108), 'sub324': list(self.S324)}
        # 172 reworded tasks
        rw = read_jsonl_rows(tk['reworded'], 'reworded task file')
        if len(rw) != ex['rw']:
            fail(f'reworded task file: {len(rw)} tasks, expected {ex["rw"]}')
        self.RW = sorted(rw)
        self.RWORIG = {t: rw[t]['original_task_id'] for t in self.RW}
        miss = [o for o in self.RWORIG.values() if o not in self.T]
        if miss or len(set(self.RWORIG.values())) != len(self.RW):
            fail(f'reworded task file: original ids not unique or not in the benchmark ({miss[:3]})')
        self.RWMETA = {t: {k: rw[t].get(k) for k in ('operation', 'category', 'building_id')} for t in self.RW}
        for t in self.RW:
            self.CL[t] = self.RWMETA[t]['building_id']
        # 200 practitioners' requests: the id set of a reference per-task file; operation from the benchmark task
        ref = read_jsonl_rows(tk['practitioner_ids_from'], 'practitioner id reference')
        if len(ref) != ex['prac']:
            fail(f'practitioner id reference: {len(ref)} rows, expected {ex["prac"]}')
        self.PRAC = sorted(ref)
        self.PRACBENCH = {}
        for t in self.PRAC:
            b = re.sub(r'-B\d+-S\d+$', '', t)
            if b == t or b not in self.T:
                fail(f'practitioner request id {t} does not map to a benchmark task')
            self.PRACBENCH[t] = b
        self.PRACOP = {t: self.T[self.PRACBENCH[t]]['operation'] for t in self.PRAC}
        # clean tasks: ground truth without an engineering error (gt_validity/summarize.clean_completion)
        cs = tk['clean_summary']
        check_path(cs, 'clean-task summary')
        field = tk.get('clean_field', 'true_error')
        rows = list(csv.DictReader(open(cs, encoding='utf-8')))
        register('clean-task summary', cs, len(rows))
        ids = [r['task_id'] for r in rows]
        if sorted(ids) != self.ALL:
            fail('clean-task summary: task ids differ from the benchmark task file')
        self.CLEAN = {r['task_id'] for r in rows if r[field] != '' and int(r[field]) == 0}

    def _subset(self, path, label):
        check_path(path, label)
        S = json.load(open(path, encoding='utf-8'))
        register(label, path, len(S))
        if len(set(S)) != len(S):
            fail(f'{label}: duplicate ids')
        out = [t for t in S if t not in self.T]
        if out:
            fail(f'{label}: {len(out)} ids are not benchmark tasks, for example {out[:3]}')
        return S


# ====================================================================== output
class Out:
    def __init__(self):
        self.lines, self.vals, self.block, self.skipped = [], {}, None, []

    def section(self, n, title):
        self.block = n
        self.lines += ['', f'% ======================================================== block {n}. {title}']

    def sub(self, title):
        self.lines.append(f'% ---- {title}')

    def skip(self, what, why):
        self.skipped.append({'block': self.block, 'what': what, 'why': why})
        self.lines.append(f'% not computed: {what} ({why})')

    def put(self, name, text, raw, src):
        if not re.fullmatch(r'Pm[A-Z][A-Za-z]*', name):
            fail(f'macro name {name!r} is not Pm followed by letters')
        if name in self.vals:
            fail(f'duplicate macro {name}')
        if re.search(r'(?<!\\)[_%&#]', str(text)) or str(text).count('{') != str(text).count('}'):
            fail(f'macro {name}: the text {text!r} is not safe LaTeX')
        self.vals[name] = {'text': str(text), 'value': jsonable(raw), 'block': self.block, 'source': src}
        self.lines.append(f'\\newcommand{{\\{name}}}{{{text}}}  % {src}')


def jsonable(x):
    if isinstance(x, (np.floating,)):
        return float(x)
    if isinstance(x, (np.integer,)):
        return int(x)
    if isinstance(x, (list, tuple)):
        return [jsonable(v) for v in x]
    if isinstance(x, dict):
        return {k: jsonable(v) for k, v in x.items()}
    return x


def check_key(k, label):
    if not re.fullmatch(r'[A-Z][A-Za-z]*', k or ''):
        fail(f'{label}: key {k!r} must be CamelCase letters only')
    return k


# ====================================================================== summaries
def summary(rows, ids, C, cluster=False, ci='boot', order=None):
    """Completion of one arm on a task set, with the interval rule of that set (task bootstrap in sorted id order as
    make_results_exhibits.summarize, building bootstrap as common.cboot, or the Wilson rule of the set). `order`
    gives another task order for the task bootstrap (the subset-file order of the documented-type arms)."""
    ids = sorted(ids)
    order = list(order) if order is not None else ids
    if sorted(order) != ids:
        fail('summary(): the task order is not a permutation of the task set')
    v = [done(rows[t]) for t in order]
    k, n = int(sum(v)), len(v)
    s = {'n': n, 'done': k, 'comp': k / n,
         'mean': float(np.mean([rows[t].get('final') or 0.0 for t in ids])),
         'rounds': float(np.mean([rows[t].get('tool_rounds') or 0 for t in ids])),
         'tin': float(np.mean([int(rows[t].get('input_tokens') or 0) for t in ids])),
         'tout': float(np.mean([int(rows[t].get('output_tokens') or 0) for t in ids]))}
    if ci == 'boot':
        _, s['lo'], s['hi'] = boot(v)
    elif ci == 'wilson_rw':
        s['lo'], s['hi'] = wilson_rw(k, n)
    elif ci == 'wilson_arms':
        s['lo'], s['hi'] = wilson_arms(k, n)
    if cluster:
        _, s['clo'], s['chi'], s['nb'] = cboot(v, order, C.CL)
    return s


def put_version(o, stem, rows, sel, g, src):
    """Completion on one IFC version with its interval: make_results_exhibits.summarize per-version rule (done() on
    the version's tasks in sorted id order, boot())."""
    sel = sorted(sel)
    c = [done(rows[t]) for t in sel]
    m, lo, hi = boot(c)
    k = int(sum(c))
    o.put(f'{stem}Comp{GTOK[g]}', num(m), m, src + f', completion on {g} tasks, {k}/{len(sel)}')
    o.put(f'{stem}Comp{GTOK[g]}Lo', num(lo), lo, src + f', {g} tasks, 95 % task-level bootstrap (sorted ids), lower')
    o.put(f'{stem}Comp{GTOK[g]}Hi', num(hi), hi, src + f', {g} tasks, 95 % task-level bootstrap (sorted ids), upper')
    o.put(f'{stem}Done{GTOK[g]}', thou(k), k, src + f', completed {g} tasks')
    o.put(f'{stem}N{GTOK[g]}', thou(len(sel)), len(sel), src + f', {g} tasks')


def put_versions(o, stem, rows, ids, C, src):
    for g in VERS:
        sel = [t for t in ids if C.T[t]['ifc_version'] == g]
        if sel:
            put_version(o, stem, rows, sel, g, src)


def paired(ra, rb, ids, C, order=None, cluster=True, interval='boot', at=0.9):
    """A minus B on the same tasks (make_macros_rev2.paired): point, task-level bootstrap in the given task order,
    building bootstrap (common.cboot), Tango 95 % score interval, b and c, exact McNemar p. interval='hybrid' takes
    the task-level interval from summarize_hybrid.boot (the parser-with-rewriting arms)."""
    ids = sorted(ids)
    order = list(order) if order is not None else ids
    if sorted(order) != ids:
        fail('paired(): the task order is not a permutation of the task set')
    v = [done_at(ra[t], at) - done_at(rb[t], at) for t in order]
    if interval == 'hybrid':
        m = float(np.mean(v))
        lo, hi = boot_hybrid([int(x) for x in v])
    else:
        m, lo, hi = boot(v)
    P = {'n': len(ids), 'diff': m, 'lo': lo, 'hi': hi}
    if cluster:
        _, P['clo'], P['chi'], P['nb'] = cboot(v, order, C.CL)
    ya = [int(done_at(ra[t], at)) for t in ids]
    yb = [int(done_at(rb[t], at)) for t in ids]
    n11 = sum(1 for a, b in zip(ya, yb) if a and b)
    n12 = sum(1 for a, b in zip(ya, yb) if a and not b)
    n21 = sum(1 for a, b in zip(ya, yb) if b and not a)
    n22 = len(ids) - n11 - n12 - n21
    P.update(b=n12, c=n21, n11=n11, n22=n22, p=mcnemar_exact(n12, n21), a_done=sum(ya), b_done=sum(yb))
    P['tlo'], P['thi'] = tango(n11, n12, n21, n22)
    return P


def put_summary(o, stem, s, src, interval_label):
    o.put(stem + 'N', thou(s['n']), s['n'], src + ', tasks')
    o.put(stem + 'Done', thou(s['done']), s['done'], src + ', tasks completed')
    o.put(stem + 'Comp', num(s['comp']), s['comp'], src + f', completion {s["done"]}/{s["n"]}')
    if 'lo' in s:
        o.put(stem + 'CompLo', num(s['lo']), s['lo'], src + f', {interval_label}, lower')
        o.put(stem + 'CompHi', num(s['hi']), s['hi'], src + f', {interval_label}, upper')
    if 'clo' in s:
        o.put(stem + 'CompCLo', num(s['clo']), s['clo'], src + f', 95 % building-level bootstrap ({s["nb"]} buildings), lower')
        o.put(stem + 'CompCHi', num(s['chi']), s['chi'], src + ', 95 % building-level bootstrap, upper')
    o.put(stem + 'Mean', num(s['mean']), s['mean'], src + ', mean score (final)')


def put_paired(o, stem, P, src, tango_=True, counts=True):
    o.put(stem, num(P['diff']), P['diff'], src + ', paired difference in completion')
    lab = 'parser-with-rewriting bootstrap (Python random, seed 20261026)' if P.get('hybrid') else 'task-level bootstrap'
    lo_, hi_ = bounds(P['lo'], P['hi'])
    o.put(stem + 'Lo', lo_, P['lo'], src + f', 95 % {lab}, lower')
    o.put(stem + 'Hi', hi_, P['hi'], src + f', 95 % {lab}, upper')
    if 'clo' in P:
        lo_, hi_ = bounds(P['clo'], P['chi'])
        o.put(stem + 'CLo', lo_, P['clo'], src + ', 95 % building-level bootstrap, lower')
        o.put(stem + 'CHi', hi_, P['chi'], src + ', 95 % building-level bootstrap, upper')
    if tango_:
        lo_, hi_ = bounds(P['tlo'], P['thi'])
        o.put(stem + 'TLo', lo_, P['tlo'], src + ', 95 % Tango score interval, lower')
        o.put(stem + 'THi', hi_, P['thi'], src + ', 95 % Tango score interval, upper')
    o.put(stem + 'Wins', thou(P['b']), P['b'], src + ', tasks only the first arm completes (b)')
    o.put(stem + 'Losses', thou(P['c']), P['c'], src + ', tasks only the second arm completes (c)')
    o.put(stem + 'P', fmt_p(P['p']), P['p'], src + ', exact two-sided McNemar p')
    if counts:
        o.put(stem + 'Both', thou(P['n11']), P['n11'], src + ', tasks both arms complete')
        o.put(stem + 'Neither', thou(P['n22']), P['n22'], src + ', tasks neither arm completes')


def groups_of(C, ids):
    """Task groups of make_results_exhibits.group_selectors plus single edits (tier not 'compositional')."""
    T = C.T
    g = {op: [t for t in ids if T[t]['operation'] == op] for op in OPS}
    g.update({c: [t for t in ids if T[t]['category'] == c] for c in CATS})
    g['chain'] = [t for t in ids if T[t]['tier'] == 'compositional']
    g['single'] = [t for t in ids if T[t]['tier'] != 'compositional']
    return g


def put_groups(o, stem, rows, ids, C, src, means=False, ver_ci=False):
    """Completion by IFC version, origin, the IFC4 native/migrated cells, operation, reference kind, chains.
    ver_ci: the IFC versions also with their interval (put_version)."""
    T = C.T
    for g in VERS + ORIGS:
        sel = [t for t in ids if (T[t]['ifc_version'] if g in VERS else T[t]['origin']) == g]
        if sel and ver_ci and g in VERS:
            put_version(o, stem, rows, sel, g, src)
        elif sel:
            k = int(sum(done(rows[t]) for t in sel))
            o.put(f'{stem}Comp{GTOK[g]}', num(k / len(sel)), k / len(sel), src + f', completion on {g} tasks, {k}/{len(sel)}')
            o.put(f'{stem}Done{GTOK[g]}', thou(k), k, src + f', completed {g} tasks')
            o.put(f'{stem}N{GTOK[g]}', thou(len(sel)), len(sel), src + f', {g} tasks')
    for o_ in ORIGS:
        sel = [t for t in ids if T[t]['ifc_version'] == 'IFC4' and T[t]['origin'] == o_]
        if sel:
            k = int(sum(done(rows[t]) for t in sel))
            o.put(f'{stem}CompFour{GTOK[o_]}', num(k / len(sel)), k / len(sel), src + f', completion on IFC4 {o_} tasks, {k}/{len(sel)}')
    for g, sel in groups_of(C, ids).items():
        if not sel:
            continue
        tok = g.capitalize()
        k = int(sum(done(rows[t]) for t in sel))
        o.put(f'{stem}Comp{tok}', num(k / len(sel)), k / len(sel), src + f', completion on {g} tasks, {k}/{len(sel)}')
        o.put(f'{stem}Done{tok}', thou(k), k, src + f', completed {g} tasks')
        o.put(f'{stem}N{tok}', thou(len(sel)), len(sel), src + f', {g} tasks')
        if means and g in OPS:
            m = float(np.mean([rows[t].get('final') or 0.0 for t in sel]))
            o.put(f'{stem}Mean{tok}', num(m), m, src + f', mean score on {g} tasks')


def put_specified(o, stem, rows, ids, C, src, end_classes=True):
    """Fully specified and under-specified tasks (subset_stats clarification split) with the end classes of
    failure_ends.end_class (wrong commit, no file split by how the run ended, question asked)."""
    full = [t for t in ids if t not in C.UNDER]
    under = [t for t in ids if t in C.UNDER]
    for part, sel in (('Full', full), ('Under', under)):
        if not sel:
            continue
        k = int(sum(done(rows[t]) for t in sel))
        o.put(f'{stem}{part}N', thou(len(sel)), len(sel), src + f', {part.lower()}-specified tasks')
        o.put(f'{stem}{part}Done', thou(k), k, src + f', {part.lower()}-specified tasks completed')
        o.put(f'{stem}{part}Comp', num(k / len(sel)), k / len(sel), src + f', completion on {part.lower()}-specified tasks')
        if not end_classes:
            continue
        cnt = {c: 0 for c in END_CLASSES}
        for t in sel:
            cnt[end_class(rows[t])] += 1
        for c in END_CLASSES[1:]:
            o.put(f'{stem}{part}End{ENDTOK[c]}', thou(cnt[c]), cnt[c], src + f', {part.lower()}-specified tasks ending as {c}')
        nofile = len(sel) - k - cnt['wrong_commit']
        o.put(f'{stem}{part}NoFile', thou(nofile), nofile, src + f', {part.lower()}-specified tasks not completed and with no committed file')
        if part == 'Full':
            o.put(f'{stem}FullWrongCommitPct', pct1(cnt['wrong_commit'], len(sel)), 100 * cnt['wrong_commit'] / len(sel),
                  src + ', fully specified tasks with a wrong committed file, percent')
            asked = cnt['reply_no_commit']
            o.put(f'{stem}FullAskedRate', num(asked / len(sel)), asked / len(sel),
                  src + ', fully specified tasks answered with a question and no file (t3_false_clarif rule), share')
            o.put(f'{stem}FullAskedPct', pct1(asked, len(sel)), 100 * asked / len(sel), src + ', the same in percent')
    return full, under


def put_effort(o, stem, s, src):
    """make_results_exhibits.write_macros Rounds (two decimals) and TokensIn / TokensOut (thousands, one decimal)."""
    o.put(stem + 'Rounds', f2(s['rounds']), s['rounds'], src + ', mean tool rounds per task')
    o.put(stem + 'TokensIn', kilo(s['tin']), s['tin'], src + ', mean prompt (input) tokens per task, thousands')
    o.put(stem + 'TokensOut', kilo(s['tout']), s['tout'], src + ', mean completion (output) tokens per task, thousands')


def put_thresholds(o, stem, rows, ids, C, src):
    full = [t for t in ids if t not in C.UNDER]
    for t in TH:
        c = float(np.mean([done_at(rows[x], t) for x in ids]))
        k = int(sum(done_at(rows[x], t) for x in ids))
        o.put(f'{stem}DoneAt{THTOK[t]}', thou(k), k, src + f', tasks with every axis >= {t:.2f}')
        o.put(f'{stem}CompAt{THTOK[t]}', num(c), c, src + f', completion when every axis >= {t:.2f}')
        cf = float(np.mean([done_at(rows[x], t) for x in full]))
        o.put(f'{stem}FullCompAt{THTOK[t]}', num(cf), cf, src + f', fully specified tasks, every axis >= {t:.2f}')
    one = sum(1 for x in ids if min(axes(rows[x])) >= 1.0)
    o.put(f'{stem}AllOne', thou(one), one, src + ', tasks with all three axes at 1.0 (checker completion_thresholds all_axes_1)')
    lost = sum(1 for x in ids if 0.9 <= min(axes(rows[x])) < 0.98)
    o.put(f'{stem}StrictLost', thou(lost), lost, src + ', tasks completed at 0.90 and not at 0.98 (subset_stats binding_axis rule)')


# ====================================================================== block helpers
def stage_name(cfg, st):
    return cfg['stages'].get(st)


def load_arm(arm, set_key, C, label):
    """Rows of a comparison arm on a task set. file_set 'bench' reads a 2,100-task file (checked against the whole
    benchmark) and slices it to the set."""
    ids = C.sets[set_key] if set_key in C.sets else None
    if arm.get('file_set') == 'bench':
        rows = read_per_task(arm['path'], C.ALL, label)
        return {t: rows[t] for t in ids}
    return read_per_task(arm['path'], ids, label)


def arm_order(arm, set_key, C):
    o = arm.get('order', 'sorted')
    if o == 'sorted':
        return C.sets[set_key]
    if o == 'subset_file':
        if set_key not in C.file_order:
            fail(f'arm {arm["key"]}: order subset_file is defined only for the 108 and 324 subsets')
        return C.file_order[set_key]
    fail(f'arm {arm["key"]}: unknown order {o!r}')


LABEL_TERMS = (('Note', 'library note'), ('Doc', 'documented library'))   # 04_protocol_v10.tex: the two arm terms


def arm_label(arm):
    """The normalised arm phrase that figures read (config field arm_label; the table phrase `arm` when absent)."""
    return arm.get('arm_label') or arm.get('arm') or arm.get('label') or arm['key']


def ours_label(cfg):
    r = cfg['ours_row']
    if r.get('arm_label'):
        return r['arm_label']
    if r['arm_sub108'] != r['arm_sub324']:
        fail('ours_row: arm_sub108 and arm_sub324 differ, so ours_row.arm_label must name the one phrase figures read')
    return r['arm_sub108']


def check_labels(cfg):
    """One arm, one phrase: an arm key on both subsets has one model name and one normalised phrase, and the
    library arms use the manuscript's two terms (keys ending in Note: 'library note'; in Doc: 'documented library')."""
    seen = {}
    for sk in ('sub108', 'sub324'):
        for a in cfg.get('arms', {}).get(sk, []):
            lab = arm_label(a)
            for suf, term in LABEL_TERMS:
                if a['key'].endswith(suf) and term not in lab.lower():
                    fail(f'arms.{sk} {a["key"]}: the arm phrase {lab!r} must contain {term!r} (set arm_label)')
            prev = seen.setdefault(a['key'], (a.get('model'), lab, sk))
            if prev[:2] != (a.get('model'), lab):
                fail(f'arm {a["key"]}: {prev[2]} has ({prev[0]!r}, {prev[1]!r}) and {sk} has ({a.get("model")!r}, '
                     f'{lab!r}); one arm must have one model name and one phrase on both subsets')


def table_row(rows, ids, C):
    ids = sorted(ids)
    full = [t for t in ids if t not in C.UNDER]
    under = [t for t in ids if t in C.UNDER]
    return {'all': sum(done(rows[t]) for t in ids) / len(ids), 'full': sum(done(rows[t]) for t in full) / len(full),
            'under': int(sum(done(rows[t]) for t in under)), 'n_under': len(under), 'n_full': len(full),
            'mean': statistics.mean((rows[t].get('final') or 0.0) for t in ids),
            'rounds': statistics.mean((rows[t].get('tool_rounds') or 0) for t in ids)}


# ====================================================================== the generator
def run(cfg, args):
    C = Ctx(cfg)
    o = Out()
    REP = cfg['reported']
    if REP not in STAGES or not cfg['stages'].get(REP):
        fail(f'reported stage {REP!r} is not one of the configured stages {cfg["stages"]}')
    reads = cfg['reads']
    rep_name = cfg['stages'][REP]
    check_labels(cfg)
    data = {'tables': {}, 'per_building': {}, 'threshold': {}, 'equivalence': {}, 'arms': {}}

    def stage_rows(kind, st, ids, label, required=False):
        p = (reads.get(kind) or {}).get(st)
        if p is None:
            if required:
                fail(f'reads.{kind}.{st} (the reported model) must be given')
            return None
        return read_per_task(p, ids, f'{label}, {st} stage ({cfg["stages"][st]})')

    # ---------------------------------------------------------------- reads of the proposed model
    bench = {st: stage_rows('bench', st, C.ALL, '2,100-task benchmark', st == REP) for st in STAGES if cfg['stages'].get(st)}
    ours = bench[REP]
    for kind in ('bench', 'sub108', 'sub324', 'rw', 'prac'):
        if (reads.get(kind) or {}).get(REP) is None:
            fail(f'reads.{kind}.{REP}: the read of the reported model ({rep_name}) must be given')
    sub = {'sub108': read_per_task(reads['sub108'][REP], C.S108, f'108-task subset, dedicated read of {rep_name}'),
           'sub324': read_per_task(reads['sub324'][REP], C.S324, f'324-task subset, dedicated read of {rep_name}')}
    rw = {st: stage_rows('rw', st, C.RW, '172 reworded tasks', st == REP) for st in STAGES if cfg['stages'].get(st)}
    prac = {st: stage_rows('prac', st, C.PRAC, '200 practitioners\' requests', st == REP) for st in STAGES if cfg['stages'].get(st)}
    rw_nl = stage_rows('rw_nolist', REP, C.RW, '172 reworded tasks without the candidate list')
    prac_nl = stage_rows('prac_nolist', REP, C.PRAC, '200 practitioners\' requests without the candidate list')
    for lab, rr in [('prac', prac.get(REP))] + [('prac_nolist', prac_nl)]:
        if rr is None:
            continue
        bad = [t for t in C.PRAC if rr[t].get('operation') not in (None, C.PRACOP[t])]
        if bad:
            fail(f'{lab}: the operation of {len(bad)} requests differs from their benchmark task, for example {bad[:3]}')
    src_b = f'benchmark read of {rep_name}'

    # ================================================================ block 1: the 2,100-task benchmark
    o.section(1, 'Level 1, the 2,100-task benchmark (reported model)')
    s = summary(ours, C.ALL, C, cluster=True)
    put_summary(o, 'PmBench', s, src_b, '95 % task-level bootstrap')
    o.put('PmBenchFailed', thou(s['n'] - s['done']), s['n'] - s['done'], src_b + ', tasks not completed')
    put_effort(o, 'PmBench', s, src_b)
    o.sub('by IFC version, origin, operation, reference kind, single edits and chains')
    put_groups(o, 'PmBench', ours, C.ALL, C, src_b, means=True)
    o.sub('fully specified and under-specified tasks, with how the runs ended (failure_ends.end_class)')
    put_specified(o, 'PmBench', ours, C.ALL, C, src_b)
    o.sub('Table 5 outcome classes, all tasks (make_results_exhibits.outcome_class)')
    cnt = {c: 0 for c in T5_CLASSES}
    for t in C.ALL:
        k = outcome_class(ours[t])
        if k != 'completed':
            cnt[k] += 1
    for c in T5_CLASSES:
        o.put(f'PmBenchFail{T5TOK[c]}', thou(cnt[c]), cnt[c], src_b + f', failed tasks of class {c}')
    o.sub('checker thresholds 0.85 to 0.98')
    put_thresholds(o, 'PmBench', ours, C.ALL, C, src_b)
    o.sub('per building (subset_stats per_building spread, make_macros_rev RevBld and RevSens rules)')
    pb = {}
    for b in C.BLD:
        ids = [t for t in C.ALL if C.CL[t] == b]
        pb[b] = (float(np.mean([done(ours[t]) for t in ids])), len(ids), b)
    vals = [x[0] for x in pb.values()]
    mn, mx = min(pb.values()), max(pb.values())
    o.put('PmBenchBldN', thou(len(pb)), len(pb), src_b + ', buildings of the benchmark')
    o.put('PmBenchBldMin', num(mn[0]), mn[0], src_b + ', lowest per-building completion')
    o.put('PmBenchBldMinName', bname(mn[2]), mn[2], src_b + ', building with the lowest completion')
    o.put('PmBenchBldMinN', thou(mn[1]), mn[1], src_b + ', tasks on that building')
    o.put('PmBenchBldMedian', num(float(np.median(vals))), float(np.median(vals)), src_b + ', median per-building completion')
    sd = round(float(np.std(vals, ddof=1)), 4)
    o.put('PmBenchBldSd', num(sd), sd, src_b + ', standard deviation between buildings (ddof 1)')
    o.put('PmBenchBldMax', num(mx[0]), mx[0], src_b + ', highest per-building completion')
    o.put('PmBenchBldMaxName', bname(mx[2]), mx[2], src_b + ', building with the highest completion')
    worst = mn[2]
    named = dict((cfg.get('per_building') or {}).get('named') or {})
    if 'Worst' in named:
        fail('per_building.named: the key Worst is reserved for the lowest building')
    for tok, b in list(named.items()) + [('Worst', worst)]:
        check_key(tok, 'per_building.named')
        if b not in pb:
            fail(f'per_building.named: building {b} is not in the benchmark')
        ids_b = [t for t in C.ALL if C.CL[t] == b]
        rest = [t for t in C.ALL if C.CL[t] != b]
        cb = float(np.mean([done(ours[t]) for t in ids_b]))
        cr = float(np.mean([done(ours[t]) for t in rest]))
        if tok != 'Worst':
            o.put(f'PmBenchBld{tok}Comp', num(cb), cb, src_b + f', completion on {b}')
            o.put(f'PmBenchBld{tok}N', thou(len(ids_b)), len(ids_b), src_b + f', tasks on {b}')
        o.put(f'PmBenchSensNo{tok}Comp', num(cr), cr, src_b + f', completion on the benchmark without {b}')
        o.put(f'PmBenchSensNo{tok}N', thou(len(rest)), len(rest), src_b + f', tasks outside {b}')
    wid = [t for t in C.ALL if C.CL[t] == worst]
    for cat, tok in (('direct', 'Direct'), ('spatial', 'Spatial'), ('topological', 'Topo')):
        sel = [t for t in wid if C.T[t]['category'] == cat]
        k = int(sum(done(ours[t]) for t in sel))
        o.put(f'PmBenchBldWorst{tok}K', thou(k), k, src_b + f', {worst}, {cat} tasks completed')
        o.put(f'PmBenchBldWorst{tok}N', thou(len(sel)), len(sel), src_b + f', {worst}, {cat} tasks')
        if sel:
            o.put(f'PmBenchBldWorst{tok}Rate', num(k / len(sel)), k / len(sel), src_b + f', {worst}, {cat} completion')
    wf = [t for t in wid if not done(ours[t])]
    ctx = sum(1 for t in wf if ours[t].get('stop_reason') == 'context_overflow')
    ctx_all = sum(1 for t in C.ALL if not done(ours[t]) and ours[t].get('stop_reason') == 'context_overflow')
    o.put('PmBenchBldWorstFailed', thou(len(wf)), len(wf), src_b + f', {worst}, failed tasks')
    o.put('PmBenchBldWorstContextStops', thou(ctx), ctx, src_b + f', {worst}, failed tasks with stop_reason context_overflow')
    o.put('PmBenchContextStops', thou(ctx_all), ctx_all, src_b + ', failed tasks with stop_reason context_overflow, all buildings')
    data['per_building']['bench'] = {b: {'comp': v[0], 'n': v[1]} for b, v in pb.items()}
    o.sub('comparison arms on the whole benchmark (parser alone)')
    for arm in cfg.get('arms', {}).get('bench', []):
        key = check_key(arm['key'], 'arms.bench')
        ra = load_arm(arm, 'bench', C, f'benchmark arm {key}')
        asrc = f'benchmark, {arm.get("label", key)}'
        sa = summary(ra, C.ALL, C, cluster=True, order=arm_order(arm, 'bench', C))
        put_summary(o, f'PmBench{key}', sa, asrc, f'95 % task-level bootstrap ({arm.get("order", "sorted")} task order)')
        P = paired(ours, ra, C.ALL, C, order=arm_order(arm, 'bench', C), cluster=True)
        put_paired(o, f'PmBenchMinus{key}', P, f'{src_b} minus {arm.get("label", key)}')

    # ================================================================ block 2: 108 and 324 subsets
    o.section(2, 'The 108-task and 324-task subsets (dedicated reads of the reported model)')
    for sk in ('sub108', 'sub324'):
        ST = SETTOK[sk]
        ids = C.sets[sk]
        ro = sub[sk]
        src = f'{ST} subset, dedicated read of {rep_name}'
        o.sub(f'{ST}: the reported model')
        s = summary(ro, ids, C, cluster=True)
        put_summary(o, f'Pm{ST}', s, src, '95 % task-level bootstrap')
        put_groups(o, f'Pm{ST}', ro, ids, C, src, ver_ci=True)
        put_specified(o, f'Pm{ST}', ro, ids, C, src)
        put_thresholds(o, f'Pm{ST}', ro, ids, C, src)
        o.sub(f'{ST}: the same tasks inside the 2,100-task read (second output, not the reported subset number)')
        k = int(sum(done(ours[t]) for t in ids))
        o.put(f'Pm{ST}SliceDone', thou(k), k, f'{src_b}, the {len(ids)} subset tasks, completed')
        o.put(f'Pm{ST}SliceComp', num(k / len(ids)), k / len(ids), f'{src_b}, the {len(ids)} subset tasks, completion')
        dd = sum(1 for t in ids if done(ro[t]) and not done(ours[t]))
        db = sum(1 for t in ids if done(ours[t]) and not done(ro[t]))
        o.put(f'Pm{ST}SliceVerdictDiffers', thou(dd + db), dd + db, f'tasks whose verdict differs between the dedicated read and the 2,100-task read')
        o.put(f'Pm{ST}SliceOnlyDedicated', thou(dd), dd, 'tasks completed only in the dedicated read')
        o.put(f'Pm{ST}SliceOnlyBench', thou(db), db, 'tasks completed only in the 2,100-task read')
        # comparison arms
        tab = [dict(key='@ours', model=cfg['ours_row']['model'], arm=cfg['ours_row'][f'arm_{sk}'],
                    arm_label=ours_label(cfg), group=0, **table_row(ro, ids, C), comp_lo=s['lo'], comp_hi=s['hi'],
                    comp_clo=s['clo'], comp_chi=s['chi'], macro_stem=f'Pm{ST}', diff_stem=None)]
        fams = {}
        armrows = {}
        for arm in cfg.get('arms', {}).get(sk, []):
            key = check_key(arm['key'], f'arms.{sk}')
            if arm.get('path') is None:
                o.skip(f'{ST} arm {key}', 'no per-task file in the config')
                continue
            ra = load_arm(arm, sk, C, f'{ST} arm {key} ({arm.get("model", "")}, {arm.get("arm", "")})')
            armrows[key] = ra
            order = arm_order(arm, sk, C)
            lab = f'{src} minus {arm.get("model", key)}, {arm.get("arm", "")}'
            o.sub(f'{ST}: {key} ({arm.get("model", "")}, {arm_label(arm)}; task order {arm.get("order", "sorted")})')
            asrc = f'{ST} subset, {arm.get("model", key)}, {arm_label(arm)}' + (' (trained model)' if arm.get('trained') else '')
            sa = summary(ra, ids, C, cluster=True, order=order)
            put_summary(o, f'Pm{ST}{key}', sa, asrc, f'95 % task-level bootstrap ({arm.get("order", "sorted")} task order)')
            if arm.get('trained'):
                put_effort(o, f'Pm{ST}{key}', sa, asrc)
                put_groups(o, f'Pm{ST}{key}', ra, ids, C, asrc, ver_ci=True)
                put_specified(o, f'Pm{ST}{key}', ra, ids, C, asrc, end_classes=False)
            else:
                put_versions(o, f'Pm{ST}{key}', ra, ids, C, asrc)
            P = paired(ro, ra, ids, C, order=order, cluster=True)
            put_paired(o, f'Pm{ST}Minus{key}', P, lab)
            full = sorted(t for t in ids if t not in C.UNDER)
            PF = paired(ro, ra, full, C, cluster=True)        # fully specified: sorted order (make_macros_rev2)
            put_paired(o, f'Pm{ST}FullMinus{key}', PF, lab + ', fully specified tasks')
            if arm.get('per_version'):
                for g in VERS + ORIGS:
                    sel = [t for t in ids if (C.T[t]['ifc_version'] if g in VERS else C.T[t]['origin']) == g]
                    if sel:
                        put_slice(o, f'Pm{ST}Minus{key}{GTOK[g]}', ro, ra, sel, C, lab + f', {g} tasks ({len(sel)})')
            if arm.get('holm'):
                fams.setdefault(arm['holm'], []).append((key, P['p']))
            row = dict(key=key, model=arm.get('model', key), arm=arm.get('arm', ''), arm_label=arm_label(arm),
                       group=arm.get('group', 1), **table_row(ra, ids, C), diff=P['diff'], lo=P['lo'], hi=P['hi'],
                       clo=P['clo'], chi=P['chi'], p=P['p'], b=P['b'], c=P['c'],
                       comp_lo=sa['lo'], comp_hi=sa['hi'], comp_clo=sa['clo'], comp_chi=sa['chi'],
                       macro_stem=f'Pm{ST}{key}', diff_stem=f'Pm{ST}Minus{key}')
            row['in_full'] = arm.get('full_table', True)
            tab.append(row)
        for fam, lst in fams.items():
            o.sub(f'{ST}: Holm family {fam} ({", ".join(k for k, _ in lst)})')
            adj = holm([p for _, p in lst])
            for (key, p), a in zip(lst, adj):
                o.put(f'Pm{ST}Minus{key}HolmRaw', fmt_p_sci(p), p, f'exact McNemar p, Holm family {fam}, raw')
                o.put(f'Pm{ST}Minus{key}HolmAdj', fmt_p_sci(a), a, f'exact McNemar p, Holm family {fam} of {len(lst)}, adjusted')
        data['tables'][sk] = tab
        data['arms'][sk] = [dict(key=r['key'], model=r['model'], arm_table=r['arm'], arm_label=r['arm_label'],
                                 n=len(ids), comp=r['all'], comp_lo=r['comp_lo'], comp_hi=r['comp_hi'],
                                 macro_stem=r['macro_stem'], diff_stem=r['diff_stem'],
                                 version_macros={g: f'{r["macro_stem"]}Comp{GTOK[g]}' for g in VERS}) for r in tab]
        data[f'armrows_{sk}'] = list(armrows)
        C.__dict__.setdefault('ARMROWS', {})[sk] = armrows
        # threshold-paired comparisons and per-building comparison
        thr = (cfg.get('threshold_paired') or {}).get(sk) or []
        for key in thr:
            if key not in armrows:
                fail(f'threshold_paired.{sk}: arm {key} has no rows')
            full = sorted(t for t in ids if t not in C.UNDER)
            for t_ in TH:
                for part, sel in (('', ids), ('Full', full)):
                    P = paired(ro, armrows[key], sel, C, cluster=True, at=t_)
                    stem = f'Pm{ST}{part}Minus{key}At{THTOK[t_]}'
                    o.put(stem, num(P['diff']), P['diff'], f'{src} minus {key}, every axis >= {t_:.2f}' + (', fully specified' if part else ''))
                    a_, b_ = bounds(P['lo'], P['hi'])
                    o.put(stem + 'Lo', a_, P['lo'], '95 % task-level bootstrap, lower')
                    o.put(stem + 'Hi', b_, P['hi'], '95 % task-level bootstrap, upper')
                    a_, b_ = bounds(P['clo'], P['chi'])
                    o.put(stem + 'CLo', a_, P['clo'], '95 % building-level bootstrap, lower')
                    o.put(stem + 'CHi', b_, P['chi'], '95 % building-level bootstrap, upper')
        pbk = ((cfg.get('per_building') or {}).get('not_below') or {}).get(sk)
        if pbk:
            if pbk not in armrows:
                fail(f'per_building.not_below.{sk}: arm {pbk} has no rows')
            hi_ = eq_ = lo_ = 0
            for b in C.BLD:
                bi = [t for t in ids if C.CL[t] == b]
                if not bi:
                    continue
                d = np.mean([done(ro[t]) for t in bi]) - np.mean([done(armrows[pbk][t]) for t in bi])
                hi_ += d > 0
                eq_ += d == 0
                lo_ += d < 0
            o.put(f'Pm{ST}BldNotBelow{pbk}', thou(hi_ + eq_), hi_ + eq_, f'{src}, buildings where the model is not below {pbk} (higher {hi_}, equal {eq_})')
            o.put(f'Pm{ST}BldN', thou(hi_ + eq_ + lo_), hi_ + eq_ + lo_, f'{src}, buildings with tasks in the subset')
    dd = cfg.get('lib_train_did')
    if dd:
        o.sub('library x training interaction (make_results_exhibits did block, cluster_boot.py building interval)')
        sk = dd['set']
        if any(k not in C.ARMROWS.get(sk, {}) for k in dd['arms']):
            o.skip('library x training interaction', f'one of the arms {dd["arms"]} has no rows')
        else:
            q = [C.ARMROWS[sk][k] for k in dd['arms']]
            ids = C.sets[sk]
            for sfx, f_ in (('', done), ('Mean', lambda r: float(r.get('final') or 0.0))):
                d_ = [(f_(q[0][t]) - f_(q[1][t])) - (f_(q[2][t]) - f_(q[3][t])) for t in ids]
                m_, lo_, hi_ = boot(d_)
                stem = f'Pm{SETTOK[sk]}LibTrainDiD{sfx}'
                src = f'({dd["arms"][0]} - {dd["arms"][1]}) - ({dd["arms"][2]} - {dd["arms"][3]}) per task, ' + \
                      ('completion' if not sfx else 'mean score')
                o.put(stem, num(m_), m_, src + ', paired difference-in-differences')
                a_, b_ = bounds(lo_, hi_)
                o.put(stem + 'Lo', a_, lo_, src + ', 95 % task-level bootstrap, lower')
                o.put(stem + 'Hi', b_, hi_, src + ', 95 % task-level bootstrap, upper')
                if not sfx:
                    _, clo_, chi_, _ = cboot(d_, ids, C.CL)
                    a_, b_ = bounds(clo_, chi_)
                    o.put(stem + 'CLo', a_, clo_, src + ', 95 % building-level bootstrap, lower')
                    o.put(stem + 'CHi', b_, chi_, src + ', 95 % building-level bootstrap, upper')
    o.sub('equivalence test against the documented Claude Sonnet arm (run_stats equivalence_margin_0.05 block)')
    margin = cfg['equivalence']['margin']
    for e in cfg['equivalence']['tests']:
        name = check_key(e['name'], 'equivalence.tests')
        sk = e['set']
        arm = next((a for a in cfg['arms'][sk] if a['key'] == e['arm']), None)
        if arm is None or e['arm'] not in C.ARMROWS[sk]:
            fail(f'equivalence {name}: arm {e["arm"]} not read on {sk}')
        ra = C.ARMROWS[sk][e['arm']]
        ro = sub[sk]
        if e.get('restrict') == 'rest216':
            ids, order = C.REST, C.REST
        else:
            ids, order = C.sets[sk], arm_order(arm, sk, C)
        P = paired(ro, ra, ids, C, order=order, cluster=True)
        v = [done(ro[t]) - done(ra[t]) for t in order]
        _, l90, h90 = boot90(v)
        n11, n12, n21, n22 = P['n11'], P['b'], P['c'], P['n22']
        t90 = tango(n11, n12, n21, n22, Z90)
        nc95, nc90 = newcombe(n11, n12, n21, n22), newcombe(n11, n12, n21, n22, Z90)
        N = len(ids)
        tost = float(max(stats.norm.sf(tango_z(n12, n21, N, -margin)), stats.norm.cdf(tango_z(n12, n21, N, margin))))
        inside = bool(-margin < l90 and h90 < margin)
        src = f'equivalence {name}: {rep_name} minus {e["arm"]} on {N} tasks, margin {margin}'
        stem = f'PmEquiv{name}'
        if e.get('restrict'):
            o.put(stem + 'N', thou(N), N, src + ', tasks')
            o.put(stem + 'OursComp', num(P['a_done'] / N), P['a_done'] / N, src + ', completion of the reported model')
            o.put(stem + 'ArmComp', num(P['b_done'] / N), P['b_done'] / N, src + ', completion of the comparison arm')
        else:      # one name per quantity: these three are Pm<Set>N, Pm<Set>Comp and Pm<Set><Arm>Comp
            o.lines.append(f'% {stem}: tasks, completion of the model and of the arm are Pm{SETTOK[sk]}N, '
                           f'Pm{SETTOK[sk]}Comp and Pm{SETTOK[sk]}{e["arm"]}Comp')
        put_paired(o, stem + 'Diff', P, src)
        for suf, (lo_, hi_), what in (('Ninety', (l90, h90), '90 % task-level bootstrap (run_stats.boot_exhibit90)'),
                                      ('TangoNinety', t90, '90 % Tango score interval'),
                                      ('Newcombe', nc95, '95 % Newcombe interval'),
                                      ('NewcombeNinety', nc90, '90 % Newcombe interval')):
            a_, b_ = bounds(lo_, hi_)
            o.put(stem + suf + 'Lo', a_, lo_, src + f', {what}, lower')
            o.put(stem + suf + 'Hi', b_, hi_, src + f', {what}, upper')
        o.put(stem + 'TostP', fmt_p(tost), tost, src + ', TOST p with the Tango score statistic')
        o.put(stem + 'Inside', 'yes' if inside else 'no', inside, src + ', 90 % bootstrap interval inside the margin')
        data['equivalence'][name] = jsonable(dict(P, ninety=[l90, h90], tango90=list(t90), newcombe95=list(nc95),
                                                  newcombe90=list(nc90), tost=tost, inside=inside))

    # ================================================================ block 3: 172 reworded tasks
    o.section(3, 'Level 2, the 172 reworded tasks')
    ro = rw[REP]
    ids = C.RW
    src = f'172 reworded tasks, read of {rep_name}'
    s = summary(ro, ids, C, ci='wilson_rw')
    put_summary(o, 'PmRw', s, src, '95 % Wilson interval (summarize_rw rule)')
    o.put('PmRwFailed', thou(s['n'] - s['done']), s['n'] - s['done'], src + ', tasks not completed')
    put_rw_slices(o, 'PmRw', ro, C, src, gen=False)
    gen = {t: ours[C.RWORIG[t]] for t in ids}
    g = summary(gen, ids, C, ci='wilson_rw')
    put_summary(o, 'PmRwGen', g, f'{src_b}, the 172 tasks in generator wording', '95 % Wilson interval (summarize_rw rule)')
    o.put('PmRwGenFailed', thou(g['n'] - g['done']), g['n'] - g['done'], f'{src_b}, generator wording, tasks not completed')
    put_rw_slices(o, 'PmRwGen', gen, C, f'{src_b}, generator wording', gen=True)
    P = paired(ro, gen, ids, C, cluster=False)
    put_paired(o, 'PmRwMinusGen', P, src + ' minus the same tasks in generator wording')
    for arm in cfg.get('arms', {}).get('rw', []):
        key = check_key(arm['key'], 'arms.rw')
        if arm.get('path') is None:
            o.skip(f'reworded arm {key}', 'no per-task file in the config')
            continue
        ra = read_per_task(arm['path'], ids, f'reworded arm {key}')
        o.sub(f'Rw: {key} ({arm.get("label", key)})')
        sa = summary(ra, ids, C, ci='wilson_rw')
        put_summary(o, f'PmRw{key}', sa, f'172 reworded tasks, {arm.get("label", key)}', '95 % Wilson interval (summarize_rw rule)')
        data['arms'].setdefault('rw', []).append(dict(key=key, label=arm.get('label', key), n=sa['n'], done=sa['done'],
                                                      comp=sa['comp'], comp_lo=sa['lo'], comp_hi=sa['hi'],
                                                      macro_stem=f'PmRw{key}', diff_stem=f'PmRwMinus{key}'))
        P = paired(ro, ra, ids, C, cluster=False, interval=arm.get('interval', 'boot'))
        P['hybrid'] = arm.get('interval') == 'hybrid'
        put_paired(o, f'PmRwMinus{key}', P, f'{src} minus {arm.get("label", key)}')

    # ================================================================ block 4: 200 practitioners' requests
    o.section(4, 'Level 3, the 200 practitioners\' requests')
    ro = prac[REP]
    ids = C.PRAC
    src = f'200 practitioners\' requests, read of {rep_name}'
    s = summary(ro, ids, C, ci='wilson_arms')
    put_summary(o, 'PmPrac', s, src, '95 % Wilson interval (summarize_arms rule)')
    put_prac_detail(o, 'PmPrac', ro, C, src)
    gen = {t: ours[C.PRACBENCH[t]] for t in ids}
    g = summary(gen, ids, C, ci='wilson_arms')
    put_summary(o, 'PmPracGen', g, f'{src_b}, the 200 requests in generator wording', '95 % Wilson interval (summarize_arms rule)')
    P = paired(ro, gen, ids, C, cluster=False)
    put_paired(o, 'PmPracMinusGen', P, src + ' minus the same edits in generator wording')
    for arm in cfg.get('arms', {}).get('prac', []):
        key = check_key(arm['key'], 'arms.prac')
        if arm.get('path') is None:
            o.skip(f'practitioner arm {key}', arm.get('missing_reason', 'no per-task file in the config'))
            continue
        ra = read_per_task(arm['path'], ids, f'practitioner arm {key}')
        o.sub(f'Prac: {key} ({arm.get("label", key)})')
        sa = summary(ra, ids, C, ci='wilson_arms')
        put_summary(o, f'PmPrac{key}', sa, f'200 requests, {arm.get("label", key)}', '95 % Wilson interval (summarize_arms rule)')
        data['arms'].setdefault('prac', []).append(dict(key=key, label=arm.get('label', key), n=sa['n'], done=sa['done'],
                                                        comp=sa['comp'], comp_lo=sa['lo'], comp_hi=sa['hi'],
                                                        macro_stem=f'PmPrac{key}', diff_stem=f'PmPracMinus{key}'))
        P = paired(ro, ra, ids, C, cluster=False, interval=arm.get('interval', 'boot'))
        P['hybrid'] = arm.get('interval') == 'hybrid'
        put_paired(o, f'PmPracMinus{key}', P, f'{src} minus {arm.get("label", key)}')

    # ================================================================ block 5: per stage
    o.section(5, 'Per stage (imitation, preference, reinforcement): benchmark, reworded tasks, requests')
    for kind, rows_by, ids, ci, cl in (('bench', bench, C.ALL, 'boot', True), ('rw', rw, C.RW, 'wilson_rw', False),
                                       ('prac', prac, C.PRAC, 'wilson_arms', False)):
        ST = SETTOK[kind]
        have = [st for st in STAGES if rows_by.get(st) is not None]
        for st in STAGES:
            if st not in have:
                o.skip(f'{ST} read of the {st} stage', 'no per-task file in the config')
                continue
            rr = rows_by[st]
            sname = cfg['stages'][st]
            src = f'{ST} read of {sname} ({st} stage)'
            stem = f'Pm{ST}{STAGETOK[st]}'
            o.sub(f'{ST}: {st} stage ({sname})')
            s = summary(rr, ids, C, cluster=cl, ci=ci)
            put_summary(o, stem, s, src, '95 % task-level bootstrap' if ci == 'boot' else '95 % Wilson interval')
            if kind == 'bench':
                o.put(stem + 'Failed', thou(s['n'] - s['done']), s['n'] - s['done'], src + ', tasks not completed')
                put_groups(o, stem, rr, ids, C, src, means=True)
                put_effort(o, stem, s, src)
                put_specified(o, stem, rr, ids, C, src, end_classes=False)
                put_thresholds(o, stem, rr, ids, C, src)
                cnt = {c: 0 for c in T5_CLASSES}
                for t in ids:
                    k = outcome_class(rr[t])
                    if k != 'completed':
                        cnt[k] += 1
                for c in T5_CLASSES:
                    o.put(f'{stem}Fail{T5TOK[c]}', thou(cnt[c]), cnt[c], src + f', failed tasks of class {c}')
            if kind == 'rw':
                gs = bench.get(st)
                if gs is None:
                    o.skip(f'{ST} {st} stage in generator wording', 'no benchmark read of this stage')
                else:
                    gen = {t: gs[C.RWORIG[t]] for t in ids}
                    k = int(sum(done(gen[t]) for t in ids))
                    o.put(stem + 'GenDone', thou(k), k, src + ', the 172 tasks in generator wording (benchmark read), completed')
                    o.put(stem + 'GenComp', num(k / len(ids)), k / len(ids), src + ', generator wording, completion')
                    P = paired(rr, gen, ids, C, cluster=False)
                    put_paired(o, stem + 'MinusGen', P, src + ' minus generator wording', tango_=False)
        pairs = [('preference', 'imitation'), ('reinforcement', 'preference'), ('reinforcement', 'imitation')]
        for a, b in pairs:
            if a not in have or b not in have:
                o.skip(f'{ST} {a} minus {b}', 'a stage read is missing')
                continue
            src = f'{ST}: {cfg["stages"][a]} ({a}) minus {cfg["stages"][b]} ({b})'
            P = paired(rows_by[a], rows_by[b], ids, C, cluster=cl)
            stem = f'Pm{ST}{STAGETOK[a]}Minus{STAGETOK[b]}'
            put_paired(o, stem, P, src)
            if kind == 'bench':
                for g_ in VERS + ORIGS:
                    sel = [t for t in ids if (C.T[t]['ifc_version'] if g_ in VERS else C.T[t]['origin']) == g_]
                    put_slice(o, f'{stem}{GTOK[g_]}', rows_by[a], rows_by[b], sel, C, src + f', {g_} tasks ({len(sel)})')

    # ================================================================ block 6: the candidate list
    o.section(6, 'The candidate list: reported model with and without the list')
    for kind, with_, without, ids, ci in (('prac', prac[REP], prac_nl, C.PRAC, 'wilson_arms'),
                                          ('rw', rw[REP], rw_nl, C.RW, 'wilson_rw')):
        ST = SETTOK[kind]
        if without is None:
            o.skip(f'{ST} read without the candidate list', 'no per-task file in the config')
            continue
        src = f'{ST}, {rep_name} without the candidate list'
        s = summary(without, ids, C, ci=ci)
        put_summary(o, f'Pm{ST}NoList', s, src, '95 % Wilson interval')
        P = paired(with_, without, ids, C, cluster=False)
        put_paired(o, f'Pm{ST}ListMinusNoList', P, f'{ST}, {rep_name} with minus without the candidate list')
        o.put(f'Pm{ST}ListNetGain', thou(P['b'] - P['c']), P['b'] - P['c'],
              f'{ST}: tasks completed with the list minus tasks completed without it (IdxHintGain rule)')

    # ================================================================ block 7: clean ground truths
    o.section(7, 'Ground-truth validity re-slice: tasks whose ground truth has no engineering error')
    sets7 = {'bench': (ours, C.ALL), 'sub108': (sub['sub108'], C.sets['sub108']),
             'sub324': (sub['sub324'], C.sets['sub324']), 'rest216': (sub['sub324'], C.REST)}
    for sk, (rr, ids) in sets7.items():
        ST = SETTOK[sk]
        cids = [t for t in ids if t in C.CLEAN]
        d = [done(rr[t]) for t in cids]
        lo, hi = boot_clean(d)
        src = f'{ST}, {rep_name}, clean tasks (gt_validity clean_completion rule)'
        o.put(f'Pm{ST}CleanN', thou(len(cids)), len(cids), src + ', clean tasks')
        o.put(f'Pm{ST}CleanDone', thou(int(sum(d))), int(sum(d)), src + ', completed')
        o.put(f'Pm{ST}CleanComp', num(float(np.mean(d))), float(np.mean(d)), src + ', completion')
        o.put(f'Pm{ST}CleanCompLo', num(lo), lo, src + ', 95 % bootstrap (seed 20261018), lower')
        o.put(f'Pm{ST}CleanCompHi', num(hi), hi, src + ', 95 % bootstrap (seed 20261018), upper')
    for st in STAGES:
        if st == REP or bench.get(st) is None:
            continue
        cids = [t for t in C.ALL if t in C.CLEAN]
        d = [done(bench[st][t]) for t in cids]
        lo, hi = boot_clean(d)
        stem = f'PmBench{STAGETOK[st]}Clean'
        src = f'benchmark, {cfg["stages"][st]} ({st} stage), clean tasks'
        o.put(stem + 'Done', thou(int(sum(d))), int(sum(d)), src + ', completed')
        o.put(stem + 'Comp', num(float(np.mean(d))), float(np.mean(d)), src + ', completion')
        o.put(stem + 'CompLo', num(lo), lo, src + ', 95 % bootstrap (seed 20261018), lower')
        o.put(stem + 'CompHi', num(hi), hi, src + ', 95 % bootstrap (seed 20261018), upper')
    for e in cfg.get('clean_pairs', []):
        sk, key = e['set'], e['arm']
        base = 'sub324' if sk == 'rest216' else sk
        if key not in C.ARMROWS.get(base, {}):
            fail(f'clean_pairs: arm {key} not read on {base}')
        rr, ids = sets7[sk]
        ra = C.ARMROWS[base][key]
        cids = [t for t in ids if t in C.CLEAN]
        dif = np.asarray([done(rr[t]) - done(ra[t]) for t in cids], float)
        lo, hi = boot_clean(dif)
        ST = SETTOK[sk]
        stem = f'Pm{ST}CleanMinus{key}'
        src = f'{ST}, clean tasks, {rep_name} minus {key}'
        o.put(stem, num(float(dif.mean())), float(dif.mean()), src + ', paired difference')
        a_, b_ = bounds(lo, hi)
        o.put(stem + 'Lo', a_, lo, src + ', 95 % bootstrap (seed 20261018), lower')
        o.put(stem + 'Hi', b_, hi, src + ', 95 % bootstrap (seed 20261018), upper')
        o.put(stem + 'Wins', thou(int((dif > 0).sum())), int((dif > 0).sum()), src + ', tasks only the reported model completes')
        o.put(stem + 'Losses', thou(int((dif < 0).sum())), int((dif < 0).sum()), src + ', tasks only the arm completes')

    # ================================================================ block 8: rounds and tokens
    o.section(8, 'Mean rounds and tokens per task (108-task subset, 200 requests)')
    for stem, rr, ids, src in (('PmHundredEight', sub['sub108'], C.sets['sub108'], f'108-task subset, dedicated read of {rep_name}'),
                               ('PmThreeTwentyFour', sub['sub324'], C.sets['sub324'], f'324-task subset, dedicated read of {rep_name}'),
                               ('PmPrac', prac[REP], C.PRAC, f'200 requests, read of {rep_name}')):
        put_effort(o, stem, summary(rr, ids, C, ci=None), src)

    # ================================================================ fragments
    frags = write_fragments(cfg, args, C, data, bench, sub, rep_name)
    return o, data, frags


def put_slice(o, stem, ra, rb, sel, C, src):
    """A minus B on one IFC version or origin (make_results_exhibits.paired: sorted ids, task bootstrap), with the
    building interval of cluster_boot.py for the same slice."""
    sel = sorted(sel)
    v = [done(ra[t]) - done(rb[t]) for t in sel]
    m_, lo_, hi_ = boot(v)
    _, clo_, chi_, _ = cboot(v, sel, C.CL)
    o.put(stem, num(m_), m_, src + ', paired difference')
    a, b = bounds(lo_, hi_)
    o.put(stem + 'Lo', a, lo_, src + ', 95 % task-level bootstrap, lower')
    o.put(stem + 'Hi', b, hi_, src + ', 95 % task-level bootstrap, upper')
    a, b = bounds(clo_, chi_)
    o.put(stem + 'CLo', a, clo_, src + ', 95 % building-level bootstrap, lower')
    o.put(stem + 'CHi', b, chi_, src + ', 95 % building-level bootstrap, upper')


def put_rw_slices(o, stem, rows, C, src, gen):
    """Completed counts by operation and reference kind on the 172 reworded tasks (summarize_rw by_slice)."""
    for key, vals in (('operation', OPS), ('category', CATS)):
        for v in vals:
            sel = [t for t in C.RW if C.RWMETA[t][key] == v]
            k = int(sum(done(rows[t]) for t in sel))
            tok = {'topological': 'Topo'}.get(v, v.capitalize())
            o.put(f'{stem}{tok}Done', thou(k), k, src + f', {v} tasks completed of {len(sel)}')
            o.put(f'{stem}{tok}N', thou(len(sel)), len(sel), src + f', {v} tasks')


def put_prac_detail(o, stem, rows, C, src):
    """By operation (summarize_arms by_operation) and how the runs ended (failure_ends.end_class)."""
    for op in OPS:
        sel = [t for t in C.PRAC if C.PRACOP[t] == op]
        k = int(sum(done(rows[t]) for t in sel))
        o.put(f'{stem}{op.capitalize()}Done', thou(k), k, src + f', {op} requests completed')
        o.put(f'{stem}{op.capitalize()}N', thou(len(sel)), len(sel), src + f', {op} requests')
        if sel:
            o.put(f'{stem}{op.capitalize()}Comp', num(k / len(sel)), k / len(sel), src + f', completion on {op} requests')
    cnt = {c: 0 for c in END_CLASSES}
    for t in C.PRAC:
        cnt[end_class(rows[t])] += 1
    for c in END_CLASSES[1:]:
        o.put(f'{stem}End{ENDTOK[c]}', thou(cnt[c]), cnt[c], src + f', requests ending as {c}')
    com = sum(1 for t in C.PRAC if rows[t].get('committed'))
    o.put(f'{stem}Committed', thou(com), com, src + ', requests with a committed file')


# ====================================================================== table fragments
def bold_if(s, cond):
    return f'\\textbf{{{s}}}' if cond else s


def write_fragments(cfg, args, C, data, bench, sub, rep_name):
    pre = args.fragments_prefix
    head = (f'% GENERATED by analysis/make_macros.py from {os.path.basename(args.config)} '
            f'(reported model {rep_name}); table rows only, do not edit by hand.')
    written = {}

    def write(name, lines):
        path = f'{pre}frag_{name}.tex'
        guard_output(path)
        open(path, 'w', encoding='utf-8').write('\n'.join([head] + lines) + '\n')
        written[name] = path

    # 108-task table, full (tab_main_full_supp layout; gated column is outside the contract) and compact
    tab = data['tables']['sub108']
    for name, keys in (('tab_main_full', [r['key'] for r in tab if r.get('in_full', True)]),
                       ('tab_main_compact', ['@ours'] + list(cfg.get('compact_rows_108') or []))):
        rows_ = []
        for k in keys:
            r = next((x for x in tab if x['key'] == k), None)
            if r is None:
                fail(f'{name}: row {k} has no data')
            rows_.append(r)
        best = {c: max(r[c] for r in rows_) for c in ('full', 'all', 'under', 'mean')}
        L, prev_m, prev_g = [], None, 0
        for r in rows_:
            if r['group'] != prev_g:                 # make_tab_main_rev2: a rule between groups of rows
                L.append(r'\midrule')
            cells = [r['model'] if r['model'] != prev_m else '', r['arm']]
            cells += [bold_if(num(r['full']), abs(r['full'] - best['full']) < 1e-12),
                      bold_if(num(r['all']), abs(r['all'] - best['all']) < 1e-12), r'\PmPending',
                      bold_if(f"{r['under']}/{r['n_under']}", r['under'] == best['under']),
                      bold_if(num(r['mean']), abs(r['mean'] - best['mean']) < 1e-12), f2(r['rounds'])]
            if r['key'] == '@ours':
                cells += ['', '', '', '']
            else:
                cells += [num(r['diff']), f"[{num(r['lo'])}, {num(r['hi'])}]", f"[{num(r['clo'])}, {num(r['chi'])}]",
                          fmt_p(r['p'])]
            L.append(' & '.join(cells) + r' \\')
            prev_m, prev_g = r['model'], r['group']
        write(name, L)
    # 324-task table (tab_324_rev layout)
    tab = [r for r in data['tables']['sub324'] if r.get('in_full', True)]
    best = {c: max(r[c] for r in tab) for c in ('all', 'full', 'mean', 'under')}
    L, prev_m = [], None
    for i, r in enumerate(tab):
        if i == 1:
            L.append(r'\midrule')
        cells = [r['model'] if r['model'] != prev_m else '', r['arm'],
                 bold_if(num(r['all']), abs(r['all'] - best['all']) < 1e-9),
                 bold_if(num(r['full']), abs(r['full'] - best['full']) < 1e-9),
                 bold_if(f"{r['under']}/{r['n_under']}", r['under'] == best['under']),
                 bold_if(num(r['mean']), abs(r['mean'] - best['mean']) < 1e-9), f2(r['rounds'])]
        cells += ['', '', ''] if r['key'] == '@ours' else \
            [num(r['diff']), f"[{num(r['lo'])}, {num(r['hi'])}]", f"[{num(r['clo'])}, {num(r['chi'])}]"]
        L.append(' & '.join(cells) + r' \\')
        prev_m = r['model']
    write('tab_324', L)
    # threshold table (make_tables_rev threshold block, without the earlier-corpus row)
    L = []

    def src_rows(spec, sk):
        if spec == '@ours':
            return bench[cfg['reported']] if sk == 'bench' else sub[sk]
        if spec.startswith('@'):
            st = spec[1:]
            if sk != 'bench' or bench.get(st) is None:
                fail(f'threshold table: {spec} needs a benchmark read of that stage')
            return bench[st]
        if spec not in C.ARMROWS.get(sk, {}):
            fail(f'threshold table: arm {spec} not read on {sk}')
        return C.ARMROWS[sk][spec]
    for i, blk in enumerate(cfg['threshold_table']):
        sk = blk['set']
        ids = C.sets[sk]
        if blk.get('part') == 'full':
            ids = [t for t in ids if t not in C.UNDER]
        vals = {}
        for spec, lab in blk['rows']:
            rr = src_rows(spec, sk)
            vals[spec] = [sum(done_at(rr[t], th) for t in ids) / len(ids) for th in TH]
        best = [max(v[j] for v in vals.values()) for j in range(len(TH))]
        if i:
            L.append(r'\addlinespace')
        L.append(f'\\multicolumn{{5}}{{@{{}}l}}{{\\textit{{{blk["title"]}}}}} \\\\')
        for spec, lab in blk['rows']:
            L.append(' & '.join([lab] + [bold_if(num(v), abs(v - best[j]) < 1e-9) for j, v in enumerate(vals[spec])]) + r' \\')
        data['threshold'][blk['title']] = {lab: vals[spec] for spec, lab in blk['rows']}
    write('tab_threshold', L)
    # per-building table (subset_stats tab_per_building_all layout)
    pbt = cfg['per_building_table']
    cols = [('sub108', ['@ours'] + pbt['sub108']), ('sub324', ['@ours'] + pbt['sub324']),
            ('bench', ['@ours'] + ['@' + s for s in pbt['bench_stages']])]
    L = []
    for b in C.BLD + ['ALL']:
        if b == 'ALL':
            L.append(r'\midrule')
        parts = ['All buildings' if b == 'ALL' else bname(b)]
        for sk, keys in cols:
            ids = [t for t in C.sets[sk] if b == 'ALL' or C.CL[t] == b]
            if not ids:
                parts += ['0'] + ['--'] * len(keys)
                continue
            v = [float(np.mean([done(src_rows(k, sk)[t]) for t in ids])) for k in keys]
            best = max(v)
            parts += [f'{len(ids):,}'] + [bold_if(num(x), abs(x - best) < 1e-12) for x in v]
            data['per_building'].setdefault(f'table_{sk}', {})[b] = dict(zip(keys, v), n=len(ids))
        L.append(' & '.join(parts) + r' \\')
    write('tab_per_building', L)
    # Table 5 rows (make_results_exhibits.write_tab5, without the column of the public benchmark)
    ours = bench[cfg['reported']]
    gsel = groups_of(C, C.ALL)
    groups = [('all', 'All tasks', C.ALL)] + [(g, g.capitalize(), gsel[g]) for g in OPS + CATS] + \
             [('chain', 'Chains of dependent edits', gsel['chain'])]
    tabc = {}
    for g, _, ids in groups:
        c = {k: 0 for k in ['completed'] + T5_CLASSES}
        for t in ids:
            c[outcome_class(ours[t])] += 1
        tabc[g] = (len(ids), c)
    used = [k for k in T5_CLASSES if any(tabc[g][1][k] for g in tabc)]
    L = ['% columns: Task group & Tasks & Completion & ' + ' & '.join(T5HEAD[k] for k in used)]
    for i, (g, lab, _) in enumerate(groups):
        if i in (1, 4, 7):
            L.append(r'\midrule')
        n, c = tabc[g]
        L.append(' & '.join([lab, f'{n:,}', num(c['completed'] / n)] + [f'{c[k]:,}' for k in used]) + r' \\')
    write('tab5_failures', L)
    return written


OUTPUTS = []


def guard_output(path):
    ap_ = os.path.abspath(path)
    for _, p, _, _ in INPUTS:
        if os.path.dirname(ap_) == os.path.dirname(os.path.abspath(p)):
            fail(f'output {path} would be written into the folder of the input {p}')
    OUTPUTS.append(ap_)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--config', required=True)
    ap.add_argument('--out-tex', required=True)
    ap.add_argument('--out-json', required=True)
    ap.add_argument('--fragments-prefix', required=True)
    args = ap.parse_args()
    try:
        check_path(os.path.abspath(args.config), 'config')
        cfg = json.load(open(args.config, encoding='utf-8'))
        o, data, frags = run(cfg, args)
        guard_output(args.out_tex)
        guard_output(args.out_json)
    except GenError as e:
        print(f'make_macros: ERROR: {e}', file=sys.stderr)
        sys.exit(2)
    rep = cfg['reported']
    H = ['% GENERATED by analysis/make_macros.py; do not edit by hand.',
         f'% config: {os.path.abspath(args.config)} ({cfg.get("label", "")})',
         f'% reported model: {cfg["stages"][rep]} ({rep} stage); stages: ' +
         ', '.join(f'{st} = {cfg["stages"].get(st)}' for st in STAGES),
         '% completion: geometry, semantics and topology all >= 0.9 (make_results_exhibits.done)',
         f'% {len(o.vals)} macros; inputs (label | rows | SHA-256 | path):']
    for lab, p, n, h in INPUTS:
        H.append(f'%   {lab} | {n} | {h} | {p}')
    if o.skipped:
        H.append(f'% not computed ({len(o.skipped)}): ' + '; '.join(f'block {s["block"]} {s["what"]}' for s in o.skipped))
    H.append(r'\providecommand{\PmPending}{\textbf{[pending]}}')
    open(args.out_tex, 'w', encoding='utf-8').write('\n'.join(H + o.lines) + '\n')
    J = {'generator': 'analysis/make_macros.py', 'config': os.path.abspath(args.config), 'label': cfg.get('label'),
         'reported': {'stage': rep, 'model': cfg['stages'][rep]}, 'stages': cfg['stages'],
         'inputs': [{'label': a, 'path': p, 'rows': n, 'sha256': h} for a, p, n, h in INPUTS],
         'skipped': o.skipped, 'macros': o.vals, 'fragments': frags,
         'data': jsonable({k: v for k, v in data.items() if not k.startswith('armrows')})}
    json.dump(J, open(args.out_json, 'w', encoding='utf-8'), indent=1)
    print(f'make_macros: {len(o.vals)} macros, {len(INPUTS)} inputs, {len(frags)} fragments, '
          f'{len(o.skipped)} parts not computed')


if __name__ == '__main__':
    main()
