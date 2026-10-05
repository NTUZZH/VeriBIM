#!/usr/bin/env python3
"""Result exhibits of the VeriBIM paper, generated from the result files in one pass.

Writes Table 3 (108-task subset), Table 3b (324-task subset), Table 4 (training chain on the
2,100-task benchmark), Table 6 (cost of an edit), the results macro file, and the figure data
consumed by the figure scripts (Figs. 8, 9, 10 and the cost figure), then calls those scripts.

Completion rule: a task is completed when geometry, semantics and topology are all >= 0.9.
Mean score = mean of row['final']; rounds = row['tool_rounds']; seconds = row['duration_seconds'].
Intervals: percentile bootstrap over tasks, 10,000 resamples, seed 20260929, lower = sorted[250],
upper = sorted[9749]; a fresh generator
per comparison, so every interval is reproducible on its own.

A result file is accepted only when it holds exactly the expected task ids once each; a missing or
partially written file is pending. Local-model rows of Tables 3 and 3b come only from the
dedicated reads local108_* and local324_*, never from the 2,100-task read.

    python code/tables/make_results_exhibits.py [--strict]
        [--grpo NAME] [--preview DIR]
--strict   exit with status 2, writing nothing, if any required input is missing or provisional.
--grpo     name of the reinforcement-stage read in results/full_all (default grpo_v10).
--preview  also draw layout previews of the figures into DIR with the local-model slots filled
           from the 2,100-task read restricted to the subset tasks (layout check only; never
           used in the manuscript).
"""
import argparse, ast, json, os, re, subprocess, sys
from collections import Counter
import numpy as np

# Layout of the public repository. VERIBIM_ROOT overrides the repository root and VERIBIM_EXHIBITS_DIR
# the output directory (default <root>/exhibits).
ROOT = os.environ.get('VERIBIM_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.environ.get('VERIBIM_EXHIBITS_DIR') or f'{ROOT}/exhibits'
BENCH = f'{ROOT}/tasks/benchmark'
RES = f'{ROOT}/results/benchmark'
OUT_TAB = f'{OUT}/tables'
OUT_FIG = f'{ROOT}/code/tables/figures'
MACROS_V10 = os.environ.get('VERIBIM_MANUSCRIPT_MACROS', '')   # optional: macro names the manuscript defines
VALHARD = f'{ROOT}/results/val_hard/preference_stage/curve_dpo_v10_valhard.txt'
VALHARD_REPORT = f'{ROOT}/tasks/val_hard/val_hard_build_report.json'
CHOSEN_FILE = f'{ROOT}/results/val_hard/preference_stage/CHOSEN_DPO_V10'
VAL500 = f'{ROOT}/results/val_500/curve_dpo_v10_val500.txt'
HOSTED_COST = f'{ROOT}/code/tables/hosted_cost.py'
GATES_C = f'{ROOT}/results/val_hard/reinforcement_stage'
GRPO_PEAK = f'{GATES_C}/PEAK_GRPO_V10'                       # reinforcement snapshot reported in Table 4 (not adopted)
GRPO_CURVE = f'{GATES_C}/curve_grpo_v10_valhard.txt'
GRPO_VALHARD_ROWS = GATES_C                     # per_task_grpo_v10_cN.jsonl on the hard set
DPO_VALHARD_ROWS = f'{ROOT}/results/val_hard/preference_stage'   # per_task_{sft_v10,dpo_v10_cN}.jsonl
VALHARD_IDS = f'{ROOT}/tasks/val_hard/val_hard_ids.json'
POOL_REPORT = f'{ROOT}/results/training/pairs_trajectory_report.json'
CURVE_BOTH = f'{GATES_C}/CURVE_BOTH_LEGS.txt'               # both reinforcement runs: 'name\tstep N\tcompletion X\tmean Y', 'PEAK\tname'
GRPO_VALHARD_DIRS = [GATES_C]   # per_task_<grpo snapshot>.jsonl on the hard set
FLIP_PATTERN = f'{ROOT}/results/repeatability/flip_rate_{{}}.json'
# rewritten-wording validation set (val-100 v3b rewritten by gpt-5.6, ids in V100B_SUBSET): per_task_<name>.jsonl in gates/v100rw
V100B = f'{ROOT}/runs_local/stage_a_v10/gates/v100rw'
V100B_SUBSET = f'{ROOT}/runs_local/stage_a_v10/val100_rw/val_subset_100_v3b_rw.json'
FIG_OUTDIR = f'{OUT}/figures'          # figures and figure captions are written here
E1 = f'{ROOT}/results/bimedit'
os.makedirs(OUT_TAB, exist_ok=True)
# data separation (Appendix F): the training file, the decision set (val-100 v3b is a subset of val-500 v3b), the benchmark
SEP_TRAIN = os.environ.get('VERIBIM_TRAIN_TASKS', f'{ROOT}/tasks/train/tasks_stage_b_v10.jsonl')   # not released; regenerate with modifc_gen
SEP_VAL500 = f'{ROOT}/tasks/val_500/val_tasks_500_v3b.jsonl'
SEP_VAL100 = f'{ROOT}/tasks/val_500/val_tasks_100_v3b.jsonl'
SEP_CACHE = f'{OUT_TAB}/separation_cache.json'                                  # BIM-Edit reads: scores_bench_<adapter>.csv (final_score column)
# published BIM-Edit range of seven re-scored frontier models
BIMEDIT_FRONTIER = (0.375, 0.495)

SEED, R = 20260929, 10000
VERS = ['IFC2X3', 'IFC4', 'IFC4X3']
ORIGS = ['native', 'migrated']
VTOK = {'IFC2X3': 'TwoXThree', 'IFC4': 'Four', 'IFC4X3': 'FourXThree', 'native': 'Native', 'migrated': 'Migrated'}
# model id, product name printed in tables and figures, macro token
COMMERCIAL = [('gpt-5.6-luna', 'GPT-5.6', 'Gpt'), ('deepseek-v4-pro', 'DeepSeek V4', 'DeepSeek'),
              ('claude-sonnet-5-5', 'Claude Sonnet 5.5', 'Sonnet'), ('gemini-3.8-flash', 'Gemini 3.8 Flash', 'Gemini')]
BASE, SFT, PREV, PROVISIONAL_DPO = 'Qwen3.5-9B', 'sft_v10', 'dpo_v9_c10', 'dpo_v10_c3'
OURS_LABEL = 'VeriBIM-9B'
BASE_LABEL = 'Qwen3.5-9B, untrained'
BASE_EST_LABEL = 'Qwen3.5-9B, untrained (estimate)'
OPS = ['create', 'update', 'delete']
CATS = ['direct', 'spatial', 'topological']
GTOK = {'create': 'Create', 'update': 'Update', 'delete': 'Delete', 'direct': 'Direct', 'spatial': 'Spatial',
        'topological': 'Topological', 'chain': 'Chain'}
# per-round timing fields a dedicated read may carry (model time, tool time); none of the current reads has them
TIMING_KEYS = [('model_seconds', 'tool_seconds'), ('generation_seconds', 'tool_seconds'),
               ('llm_seconds', 'sandbox_seconds')]
ARM_LABEL = {'alone': 'Alone', 'lib': 'With the library', 'libnote': 'With the library note'}
ARM_TOK = {'alone': 'Alone', 'lib': 'Lib', 'libnote': 'Note'}
SET_TOK = {108: 'HundredEight', 324: 'ThreeTwentyFour', 2100: 'Bench'}
BASE_SETS = (108,)                     # subsets with dedicated untrained-base reads; 324 is not planned
SFT_LABEL = 'Imitation model'
WORKSTATION = 'one NVIDIA RTX PRO 5000 Blackwell GPU (48 GB)'   # macros_v10.tex \GpuMemGB comment (nvidia-smi)

PENDING, PROVISIONAL, INPUTS, WARN, FILESTATS = [], [], [], [], []


def log(msg):
    print(msg, file=sys.stderr)


# ---------------------------------------------------------------- loading
def _read_rows(path):
    rows, dup, nlines = {}, 0, 0
    with open(path) as f:
        for line in f:
            if line.strip():
                nlines += 1
                r = json.loads(line)
                dup += r['task_id'] in rows
                rows[r['task_id']] = r
    return rows, dup, nlines


def _file_stats(path, rows, dup, nlines, expect, accepted):
    """Per-file facts for the computed inconsistency section of REPORT.txt."""
    no_axes = sorted(t for t, r in rows.items() if not isinstance(r.get('score'), dict)
                     or any(r['score'].get(k) is None for k in ('geometry', 'semantics', 'topology')))
    err = sorted(t for t, r in rows.items() if (r.get('score') or {}).get('error') or r.get('score_error'))
    crash_stop = sorted(t for t, r in rows.items() if r.get('stop_reason') == 'sandbox_crash')
    crash_any = sum(1 for r in rows.values() if (r.get('sandbox_crashes') or 0) > 0 or r.get('stop_reason') == 'sandbox_crash')
    crash_done = sum(1 for t in crash_stop if done(rows[t]))
    extra = sorted(set(rows) - set(expect)) if expect is not None else []
    missing = len(set(expect) - set(rows)) if expect is not None else 0
    FILESTATS.append({'path': path, 'lines': nlines, 'ids': len(rows), 'dup': dup,
                      'expected': None if expect is None else len(expect), 'missing': missing, 'extra': len(extra),
                      'accepted': accepted, 'no_axes': no_axes, 'scorer_error': err, 'crash_stop': len(crash_stop),
                      'crash_stop_completed': crash_done, 'crash_any': crash_any})


def load_rows(path, expect, item, required=True):
    """Rows keyed by task id, or None (pending) unless the file holds exactly the expected ids once each."""
    if not os.path.exists(path):
        if required:
            PENDING.append((item, path, 'file absent'))
        return None
    rows, dup, nlines = _read_rows(path)
    ok = not dup and set(rows) == set(expect)
    _file_stats(path, rows, dup, nlines, expect, ok)
    if not ok:
        if required:
            PENDING.append((item, path, f'{len(rows)} rows, {dup} duplicates, expected {len(expect)} ids'))
        return None
    INPUTS.append((path, len(rows)))
    return rows


def load_rows_partial(path, universe, item):
    """Rows of a read that was stopped early (the untrained base model): every row is kept, the ids must
    lie inside the benchmark and occur once."""
    if not os.path.exists(path):
        PENDING.append((item, path, 'file absent'))
        return None
    rows, dup, nlines = _read_rows(path)
    ok = not dup and set(rows) <= set(universe)
    _file_stats(path, rows, dup, nlines, None, ok)
    if not ok:
        PENDING.append((item, path, f'{len(rows)} rows, {dup} duplicates, ids outside the benchmark'))
        return None
    INPUTS.append((path, len(rows)))
    return rows


def load_json(path, item, required=True):
    if not os.path.exists(path):
        if required:
            PENDING.append((item, path, 'file absent'))
        return None
    INPUTS.append((path, 1))
    return json.load(open(path))


def done(r):
    s = r.get('score') or {}
    return 1.0 if all((s.get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology')) else 0.0


def price_table():
    src = open(HOSTED_COST).read()
    m = re.search(r'PRICE = (\{.*?\n\})', src, re.S)
    body = re.sub(r'#[^\n]*', '', m.group(1))
    INPUTS.append((HOSTED_COST, 0))
    return ast.literal_eval(body)


def usd(r, pin, pout):
    """Cost of one task, the formula of hosted_cost.py (cache reads 0.1x, cache writes 1.25x input)."""
    tin, tout = int(r.get('input_tokens') or 0), int(r.get('output_tokens') or 0)
    cr, cw = int(r.get('cache_read_tokens') or 0), int(r.get('cache_creation_tokens') or 0)
    return (tin - cr - cw) / 1e6 * pin + cr / 1e6 * pin * 0.1 + cw / 1e6 * pin * 1.25 + tout / 1e6 * pout


# ---------------------------------------------------------------- statistics
def boot(vals):
    v = np.asarray(vals, float)
    n = len(v)
    rng = np.random.default_rng(SEED)
    means = np.empty(R)
    for s in range(0, R, 250):
        idx = rng.integers(0, n, size=(min(250, R - s), n))
        means[s:s + len(idx)] = v[idx].mean(1)
    means.sort()
    return float(v.mean()), float(means[int(0.025 * R)]), float(means[int(0.975 * R) - 1])


def group_selectors(T):
    sel = {op: (lambda t, op=op: T[t]['operation'] == op) for op in OPS}
    sel.update({c: (lambda t, c=c: T[t]['category'] == c) for c in CATS})
    sel['chain'] = lambda t: T[t]['tier'] == 'compositional'
    return sel


def summarize(rows, ids, T, price=None):
    ids = sorted(ids)
    c = np.array([done(rows[t]) for t in ids])
    out = {'n': len(ids), 'done': int(c.sum()), 'comp': boot(c),
           'mean': float(np.mean([rows[t].get('final') or 0.0 for t in ids])),
           'rounds': float(np.mean([rows[t].get('tool_rounds') or 0 for t in ids])),
           'secs': float(np.mean([rows[t].get('duration_seconds') or 0.0 for t in ids])),
           'tin': float(np.mean([int(rows[t].get('input_tokens') or 0) for t in ids])),
           'tout': float(np.mean([int(rows[t].get('output_tokens') or 0) for t in ids])),
           'crash': sum(1 for t in ids if rows[t].get('stop_reason') == 'sandbox_crash')}
    for g in VERS:
        cc = [done(rows[t]) for t in ids if T[t]['ifc_version'] == g]
        out[g] = boot(cc) + (len(cc),)
    for g in ORIGS:
        cc = [done(rows[t]) for t in ids if T[t]['origin'] == g]
        out[g] = boot(cc) + (len(cc),)
    # version x origin cells (IFC4 holds both origins), plain rates
    out['cells'] = {}
    for v in VERS:
        for o in ORIGS:
            cc = [done(rows[t]) for t in ids if T[t]['ifc_version'] == v and T[t]['origin'] == o]
            if cc:
                out['cells'][f'{v}|{o}'] = (float(np.mean(cc)), int(sum(cc)), len(cc))
    # task groups: operation, reference category, chains of dependent edits (tier 'compositional')
    out['groups'] = {}
    for gname, sel in group_selectors(T).items():
        cc = [done(rows[t]) for t in ids if sel(t)]
        if cc:
            out['groups'][gname] = (float(np.mean(cc)), int(sum(cc)), len(cc))
    # model time / tool time, only when the rows carry per-task timing fields
    for mk, tk in TIMING_KEYS:
        if all(rows[t].get(mk) is not None and rows[t].get(tk) is not None for t in ids):
            out['model_secs'] = float(np.mean([rows[t][mk] for t in ids]))
            out['tool_secs'] = float(np.mean([rows[t][tk] for t in ids]))
            out['timing_fields'] = (mk, tk)
            break
    if price is not None:
        tot = sum(usd(rows[t], *price) for t in ids)
        out['usd_task'] = tot / len(ids)
        out['usd_done'] = tot / max(1, out['done'])
    return out


def paired(ra, rb, ids, T):
    ids = sorted(ids)
    d = {'ALL': boot([done(ra[t]) - done(rb[t]) for t in ids])}
    for g in VERS:
        d[g] = boot([done(ra[t]) - done(rb[t]) for t in ids if T[t]['ifc_version'] == g])
    for g in ORIGS:
        sel = [t for t in ids if T[t]['origin'] == g]
        if sel:
            d[g] = boot([done(ra[t]) - done(rb[t]) for t in sel])
    d['wins'] = sum(1 for t in ids if done(ra[t]) > done(rb[t]))      # a completes, b fails
    d['losses'] = sum(1 for t in ids if done(ra[t]) < done(rb[t]))    # b completes, a fails
    return d


# ---------------------------------------------------------------- untrained base: estimate
def base_measured_sets(rows982, rows108, T):
    """Measured rows per IFC version. IFC2X3 and IFC4 come from the stopped 2,100-task read; the dedicated
    108-task read (36 tasks per version) adds its IFC4 tasks that the stopped read did not reach and supplies
    all IFC4X3 rows. A task read twice counts once, with its row from the stopped 2,100-task read."""
    per = {v: {} for v in VERS}
    for t, r in rows982.items():
        per[T[t]['ifc_version']][t] = r
    dup = 0
    if rows108 is not None:
        for t, r in rows108.items():
            v = T[t]['ifc_version']
            if v == 'IFC2X3':
                continue
            if t in per[v]:
                dup += 1
                continue
            per[v][t] = r
    return per, dup


def wilson(k, n, z=1.959964):
    p = k / n
    den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return c - h, c + h


def base_estimate(rows982, rows108, T):
    """Completion of the untrained model on the 2,100-task benchmark, estimated.

    Point estimate: the mean of the three per-version completion rates (each version holds 700 tasks, so equal
    weights), each rate measured on the rows available for that version. Reported interval: per-version Wilson
    intervals combined by the MOVER rule (robust to a version with 0 completions). Cross-check: percentile bootstrap,
    10,000 resamples, seed 20260929, resampling the measured tasks within each version (stratified) and averaging
    the three resampled rates. Cross-check: the average of the three per-version Wilson bounds.
    Origin cells are post-stratified: native = IFC2X3 (700) + IFC4 native (217); migrated = IFC4 migrated (483)
    + IFC4X3 (700), each stratum rate measured on its read tasks.
    Paired gain of a trained model (full 2,100-task read) over the base: difference estimator, per version
    (trained rate on all 700 tasks) - (base rate on the measured tasks); the interval resamples the paired
    differences on the measured tasks of each version and adds back each version's trained-rate correction."""
    per, dup = base_measured_sets(rows982, rows108, T)
    out = {'n_read': len(rows982), 'done_read': int(sum(done(r) for r in rows982.values())), 'dup108': dup,
           'per': {}, 'versions_complete': all(per[v] for v in VERS)}
    rng_v = {}
    for v in VERS:
        ids = sorted(per[v])
        if not ids:
            out['per'][v] = None
            continue
        c = np.array([done(per[v][t]) for t in ids])
        lo, hi = wilson(int(c.sum()), len(c))
        full = sum(1 for t in T if T[t]['ifc_version'] == v)
        out['per'][v] = {'rate': float(c.mean()), 'done': int(c.sum()), 'n': len(c), 'of': full,
                         'measured_all': len(c) == full, 'wilson': (float(lo), float(hi)),
                         'boot': boot(c), 'ids': ids}
        rng_v[v] = c
    # origin strata
    strata = {}
    for v in VERS:
        for o in ORIGS:
            pop = [t for t in T if T[t]['ifc_version'] == v and T[t]['origin'] == o]
            if not pop:
                continue
            m = [t for t in per[v] if T[t]['origin'] == o]
            strata[(v, o)] = (len(pop), float(np.mean([done(per[v][t]) for t in m])) if m else None, len(m))
    out['origin'] = {}
    for o in ORIGS:
        cells = [(N, p) for (v, oo), (N, p, _) in strata.items() if oo == o]
        out['origin'][o] = (None if any(p is None for _, p in cells)
                            else sum(N * p for N, p in cells) / sum(N for N, _ in cells))
    out['strata'] = {f'{v}|{o}': s for (v, o), s in strata.items()}
    if not out['versions_complete']:
        out['est'] = None
    else:
        rng = np.random.default_rng(SEED)
        acc = np.zeros(R)
        for v in VERS:
            c = rng_v[v]
            idx = rng.integers(0, len(c), size=(R, len(c)))
            acc += c[idx].mean(1)
        means = np.sort(acc / 3)
        est = float(np.mean([out['per'][v]['rate'] for v in VERS]))
        out['est_boot'] = (est, float(means[int(0.025 * R)]), float(means[int(0.975 * R) - 1]))
        # Reported interval: per-version Wilson intervals combined for the equal-weight mean by the MOVER rule
        # (Zou and Donner): a version with no completed task (0/36) keeps a nonzero upper bound, which the
        # stratified bootstrap cannot give (its resamples of 36 zeros are all zero).
        lo_, hi_ = 0.0, 0.0
        for v in VERS:
            pv = out['per'][v]
            lo_ += (pv['rate'] - pv['wilson'][0]) ** 2 / 9
            hi_ += (pv['wilson'][1] - pv['rate']) ** 2 / 9
        out['est'] = (est, max(0.0, est - float(np.sqrt(lo_))), est + float(np.sqrt(hi_)))
        out['wilson_avg'] = (float(np.mean([out['per'][v]['wilson'][0] for v in VERS])),
                             float(np.mean([out['per'][v]['wilson'][1] for v in VERS])))
    out['mean'] = float(np.mean([r.get('final') or 0.0 for r in rows982.values()]))
    out['rounds'] = float(np.mean([r.get('tool_rounds') or 0 for r in rows982.values()]))
    out['secs'] = float(np.mean([r.get('duration_seconds') or 0.0 for r in rows982.values()]))
    out['stops'] = dict(sorted(Counter(r.get('stop_reason') for r in rows982.values()).items()))
    out['committed'] = sum(1 for r in rows982.values() if r.get('committed'))
    out['_per_rows'] = (per, dup)
    return out


def base_gain(trained, be, T):
    """Paired gain of a trained model over the untrained base, by the difference estimator of base_estimate."""
    if not be['versions_complete']:
        return None
    per, _ = be['_per_rows']
    rng = np.random.default_rng(SEED)
    acc, point, byv = np.zeros(R), 0.0, {}
    for v in VERS:
        ids = be['per'][v]['ids']
        full = [t for t in T if T[t]['ifc_version'] == v]
        tr_full = float(np.mean([done(trained[t]) for t in full]))
        tr_meas = float(np.mean([done(trained[t]) for t in ids]))
        dv = np.array([done(trained[t]) - done(per[v][t]) for t in ids])
        pv = tr_full - be['per'][v]['rate']
        point += pv / 3
        idx = rng.integers(0, len(dv), size=(R, len(dv)))
        bs = dv[idx].mean(1) + (tr_full - tr_meas)
        acc += bs / 3
        bsv = np.sort(bs)
        byv[v] = (pv, float(bsv[int(0.025 * R)]), float(bsv[int(0.975 * R) - 1]), be['per'][v]['measured_all'])
    acc.sort()
    # Reported interval: MOVER combination of the trained model's bootstrap interval on all 2,100 tasks and the
    # base estimate's interval (conservative: ignores the pairing); the paired bootstrap is kept as a cross-check.
    tc = boot([done(trained[t]) for t in T])
    e = be['est']
    lo_ = point - float(np.sqrt((tc[0] - tc[1]) ** 2 + (e[2] - e[0]) ** 2))
    hi_ = point + float(np.sqrt((tc[2] - tc[0]) ** 2 + (e[0] - e[1]) ** 2))
    return {'ALL': (point, lo_, hi_), 'by_version': byv,
            'paired_boot': (point, float(acc[int(0.025 * R)]), float(acc[int(0.975 * R) - 1]))}


# ---------------------------------------------------------------- curve files
def parse_curve(path):
    """Lines 'name completion X mean Y n N', an optional 'CHOSEN name' (or 'PEAK name ...') line and
    'paired name vs sft_v10: completion delta D [lo, hi] ...' lines."""
    pts, chosen, pairs = {}, None, {}
    for line in open(path):
        tok = [t for t in line.split() if t != '(start)']
        if not tok:
            continue
        if tok[0] in ('CHOSEN', 'PEAK'):
            chosen = tok[1]
            continue
        if tok[0] == 'paired':
            m = re.search(r'paired\s+(\S+)\s+vs\s+(\S+?):\s*completion delta\s*([-+0-9.]+)\s*\[\s*([-+0-9.]+)\s*,\s*([-+0-9.]+)\s*\]', line)
            if m:
                pairs[m.group(1)] = (float(m.group(3)), float(m.group(4)), float(m.group(5)), m.group(2))
            continue
        if len(tok) >= 7 and tok[1] == 'completion' and tok[3] == 'mean':
            pts[tok[0]] = (float(tok[2]), float(tok[4]), int(tok[6]))
    return pts, chosen, pairs


def separation():
    """Appendix F: distinct buildings per version x origin, task counts, pairwise building overlap, and benchmark (and
    decision-set) instructions whose model-facing text (field 'prompt', stripped) also occurs verbatim in the training
    file. Cached on the input files' sizes and modification times, because the training file is large."""
    files = {'train': SEP_TRAIN, 'val500': SEP_VAL500, 'val100': SEP_VAL100, 'bench': f'{BENCH}/tasks.v4c.jsonl'}
    if not all(os.path.exists(f) for f in files.values()):
        PENDING.append(('data separation inputs', ', '.join(f for f in files.values() if not os.path.exists(f)), 'file absent'))
        return None
    sig = {k: [os.path.getsize(f), int(os.path.getmtime(f))] for k, f in files.items()}
    if os.path.exists(SEP_CACHE):
        c = json.load(open(SEP_CACHE))
        if c.get('sig') == sig:
            for f in files.values():
                INPUTS.append((f, c['rows'][[k for k, v in files.items() if v == f][0]]))
            return c
    R = {}
    for k, f in files.items():
        R[k] = []
        for l in open(f):
            if l.strip():
                r = json.loads(l)
                R[k].append({x: r.get(x) for x in ('task_id', 'building_id', 'ifc_version', 'origin', 'prompt', 'edit_kind', 'operation')})
        INPUTS.append((f, len(R[k])))
    out = {'sig': sig, 'rows': {k: len(v) for k, v in R.items()}, 'cells': {}, 'distinct': {}, 'overlap': {}, 'verbatim': {}}
    for k, rr in R.items():
        cc = {}
        for r in rr:
            cc.setdefault(f"{r['ifc_version']}|{r['origin']}", set()).add(r['building_id'])
        out['cells'][k] = {kk: len(v) for kk, v in cc.items()}
        out['distinct'][k] = len({r['building_id'] for r in rr})
    Bs = {k: {r['building_id'] for r in rr} for k, rr in R.items()}
    for a_, b_ in (('train', 'val500'), ('train', 'bench'), ('val500', 'bench'), ('train', 'val100')):
        out['overlap'][f'{a_}|{b_}'] = len(Bs[a_] & Bs[b_])
    tp = {}
    for r in R['train']:
        tp.setdefault((r['prompt'] or '').strip(), set()).add(r['building_id'])
    for k in ('bench', 'val500', 'val100'):
        hit = [r for r in R[k] if (r['prompt'] or '').strip() in tp]
        out['verbatim'][k] = {'n': len(hit), 'by_kind': dict(Counter(r['edit_kind'] for r in hit)),
                              'by_operation': dict(Counter(r['operation'] for r in hit)),
                              'same_building': sum(1 for r in hit if r['building_id'] in tp[(r['prompt'] or '').strip()]),
                              'ids': sorted(r['task_id'] for r in hit)}
    json.dump(out, open(SEP_CACHE, 'w'), indent=1)
    return out


def transcript_split(tdir, rows, ids):
    """Tool time = sum of the per-round duration_seconds in the transcript (each round's record is closed after its
    tool calls ran, and opened after the model's reply arrived); model time = the task's duration_seconds minus tool
    time, which also holds the sandbox start before round 1."""
    if not os.path.isdir(tdir):
        WARN.append(f'{tdir}: no transcripts; tool/model split not computed')
        return None
    tool, model, rounds, calls, missing = [], [], 0, 0, []
    for t in ids:
        f = f'{tdir}/{t}.json'
        if not os.path.exists(f):
            missing.append(t)
            continue
        it = json.load(open(f)).get('iterations') or []
        ts = sum(float(x.get('duration_seconds') or 0.0) for x in it)
        tool.append(ts)
        model.append(float(rows[t].get('duration_seconds') or 0.0) - ts)
        rounds += sum(1 for x in it if x.get('tool_calls'))
        calls += sum(len(x.get('tool_calls') or []) for x in it)
    if missing:
        WARN.append(f'{tdir}: {len(missing)} transcripts missing (e.g. {missing[0]}); tool/model split not computed')
        return None
    INPUTS.append((tdir, len(tool)))
    return {'tool': float(np.mean(tool)), 'model': float(np.mean(model)), 'tool_median': float(np.median(tool)),
            'rounds_with_calls': rounds, 'calls': calls, 'n': len(tool), 'neg_model': sum(1 for x in model if x < 0)}


def latency_sentence(data):
    if data.get('solo'):
        return "Its seconds are measured with one task at a time."
    if data.get('inflight'):
        return f"Its seconds are measured with {data['inflight']} tasks in flight on the same GPU."
    return ''


def write_cost_caption(data):
    cap = (r"\caption{Mean wall-clock time and price per task on the 108-task subset, with the mean number of tool rounds in "
           r"the right-hand column of (a). Prices are the providers' list prices, and VeriBIM-9B runs on "
           + WORKSTATION + r' with no provider fee per edit. ' + latency_sentence(data)).rstrip() + '}'
    out = os.path.join(FIG_OUTDIR or f'{OUT_FIG}', 'fig_cost', 'caption.tex')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write('% Caption of the cost figure (fig_cost.pdf). GENERATED by writing/tables/make_results_exhibits.py.\n'
                         + cap + '\n\\label{fig:cost}\n')


def write_curve_caption(data):
    g = data.get('grpo_curve') or {}
    if data['curve'].get('provisional') or not g.get('snaps'):
        return
    runs = len({x[5] for x in g['snaps']})
    two = ' in two runs' if runs > 1 else ''
    if data.get('final_is_grpo') and runs > 1:
        cap = (r'\caption{Completion on the hard validation set of 300 tasks along (a) the preference stage, which starts '
               r'from the imitation model at step 0, and (b) the reinforcement stage in two runs. The first run starts from '
               r"the preference-stage peak, and the second run continues from the first run's step-50 snapshot, "
               r'with steps counted along the path of the model. The circle marks the final model, the diamonds mark the '
               r'preference-stage peak, and the horizontal dashed line marks the imitation model.}')
    elif data.get('final_is_grpo'):
        cap = (r'\caption{Completion on the hard validation set of 300 tasks along (a) the preference stage, which starts '
               r'from the imitation model at step 0, and (b) the reinforcement stage' + two + r', which starts from the '
               r'preference-stage peak. The circle marks the final model, the diamonds mark the preference-stage peak, and '
               r'the dashed line marks the imitation model.}')
    else:
        cap = (r'\caption{Completion on the hard validation set of 300 tasks along (a) the preference stage, which starts '
               r'from the imitation model at step 0, and (b) the reinforcement stage' + two + r', which starts from the '
               r'chosen preference snapshot. Circles mark the chosen snapshot and squares the highest reinforcement '
               r'snapshot, and the dashed line marks the imitation model.}')
    out = os.path.join(FIG_OUTDIR or f'{OUT_FIG}', 'fig10_curve', 'caption.tex')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    open(out, 'w').write('% Caption of Fig. 10 (fig10_curve.pdf). GENERATED by writing/tables/make_results_exhibits.py.\n'
                         + cap + '\n\\label{fig:curve}\n')


def parse_curve_both(path):
    """CURVE_BOTH_LEGS.txt: 'name<TAB>step N<TAB>completion X<TAB>mean Y' per snapshot, and 'PEAK<TAB>name'."""
    rows, peak = {}, None
    for line in open(path):
        tok = line.split()
        if not tok:
            continue
        if tok[0] == 'PEAK' and len(tok) > 1:
            peak = tok[1]
            continue
        kv = {tok[i]: tok[i + 1] for i in range(1, len(tok) - 1) if tok[i] in ('step', 'completion', 'mean')}
        if {'step', 'completion'} <= set(kv):
            rows[tok[0]] = (int(kv['step']), float(kv['completion']), float(kv.get('mean', 'nan')))
    return rows, peak


# ---------------------------------------------------------------- formatting
def f3(x):
    return f'{x:.3f}'


def sgn(x):
    return f'+{x:.3f}' if x >= 0 else f'$-${abs(x):.3f}'


def txt_signed(x):     # for macros: no plus sign, typographic minus
    return f'{x:.3f}' if x >= 0 else f'$-${abs(x):.3f}'


def bold_cols(rows, keys, better):
    """Per column, the best value among rendered rows (ties all bold)."""
    best = {}
    for k in keys:
        vals = [r[k] for r in rows if r.get(k) is not None]
        if vals:
            best[k] = (max if better[k] == 'max' else min)(round(v, 3) for v in vals)
    return best


def cell(v, k, best, fmt=f3):
    if v is None:
        return r'\pending'
    s = fmt(v)
    return rf'\textbf{{{s}}}' if k in best and round(v, 3) == best[k] else s


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--strict', action='store_true')
    ap.add_argument('--grpo', default=None, help='default: first token of stage_c_v10/gates/PEAK_GRPO_V10, else grpo_v10')
    ap.add_argument('--preview', default=None)
    args = ap.parse_args()
    if args.grpo is None:
        args.grpo = (open(GRPO_PEAK).read().split() or ['grpo_v10'])[0] if os.path.exists(GRPO_PEAK) else 'grpo_v10'
        if os.path.exists(GRPO_PEAK):
            INPUTS.append((GRPO_PEAK, 0))

    T = {}
    for line in open(f'{BENCH}/tasks.v4c.jsonl'):
        r = json.loads(line)
        T[r['task_id']] = {k: r[k] for k in ('ifc_version', 'origin', 'operation', 'category', 'tier', 'edit_kind')}
    INPUTS.append((f'{BENCH}/tasks.v4c.jsonl', len(T)))
    S108 = json.load(open(f'{BENCH}/subset_108_hosted.v4c.json'))
    S324 = json.load(open(f'{BENCH}/subset_324.v4c.json'))
    INPUTS.extend([(f'{BENCH}/subset_108_hosted.v4c.json', len(S108)), (f'{BENCH}/subset_324.v4c.json', len(S324))])
    assert len(T) == 2100 and len(set(S108)) == 108 and len(set(S324)) == 324 and set(S108) <= set(S324) <= set(T)
    ALL = sorted(T)
    PRICE = price_table()

    # ---- the chosen preference-stage snapshot
    # order: the selection script's CHOSEN_DPO_V10 file, else the CHOSEN line of the hard-set curve, else
    # dpo_v10_c3 provisionally. Fig. 10 comes from the hard-set curve when it exists, else from val-500.
    chosen_file = None
    if os.path.exists(CHOSEN_FILE):
        tok = open(CHOSEN_FILE).read().split()
        chosen_file = tok[0] if tok else None
        INPUTS.append((CHOSEN_FILE, 0))
        if not chosen_file or not re.fullmatch(r'dpo_v10(_c\d+)?', chosen_file):
            WARN.append(f'{CHOSEN_FILE}: unexpected content {tok[:3]}; ignored')
            chosen_file = None
    else:
        PENDING.append(('chosen snapshot file', CHOSEN_FILE, 'file absent'))
    curve_path, curve_provisional, chosen_curve = VALHARD, False, None
    if os.path.exists(VALHARD):
        pts, chosen_curve, pairs = parse_curve(VALHARD)
        INPUTS.append((VALHARD, len(pts)))
    else:
        PENDING.append(('hard-validation curve (Fig. 10, hard-set scores)', VALHARD, 'file absent'))
        curve_path, curve_provisional = VAL500, True
        pts, _, pairs = parse_curve(VAL500)
        INPUTS.append((VAL500, len(pts)))
        PROVISIONAL.append('Fig. 10 drawn from the val-500 curve (saturated), marked provisional')
    if chosen_file and chosen_curve and chosen_file != chosen_curve:
        WARN.append(f'chosen snapshot disagrees: {os.path.basename(CHOSEN_FILE)} says {chosen_file}, '
                    f'the curve file says {chosen_curve}; the CHOSEN_DPO_V10 file is used')
    chosen = chosen_file or chosen_curve
    if chosen is None:
        chosen = PROVISIONAL_DPO
        PROVISIONAL.append(f'chosen snapshot: {PROVISIONAL_DPO} used provisionally (no CHOSEN_DPO_V10 file yet)')
    # ---- the final model: first token of results/FINAL_ARTIFACT; default the chosen preference snapshot
    final = chosen
    fpath = f'{RES}/FINAL_ARTIFACT'
    if os.path.exists(fpath):
        tok = open(fpath).read().split()
        INPUTS.append((fpath, 0))
        if tok and re.fullmatch(r'(dpo|grpo)_v10[a-z]?_c\d+', tok[0]):
            final = tok[0]
        else:
            WARN.append(f'{fpath}: unexpected content {tok[:2]}; the chosen preference snapshot is used')
    final_is_grpo = final != chosen and final.startswith('grpo')
    if final != chosen and not final_is_grpo:
        WARN.append(f'FINAL_ARTIFACT names {final}, neither the chosen preference snapshot {chosen} nor a reinforcement snapshot')
    if final_is_grpo:
        args.grpo = final            # Table 4's reinforcement row is then the final model
    val500 = parse_curve(VAL500)[0] if os.path.exists(VAL500) else {}
    if curve_path != VAL500 and val500:
        INPUTS.append((VAL500, len(val500)))
    valhard_build = load_json(VALHARD_REPORT, 'hard validation set build report')

    data = {'chosen': chosen, 'final': final, 'final_is_grpo': final_is_grpo, 'final_key': 'grpo' if final_is_grpo else 'dpo',
            'arms': {}, 'deltas': {}, 'offtarget': {}, 'curve': {}, 'val500': val500,
            'valhard_build': valhard_build, 'offdone': {}}

    def arm(key, rows, ids, label, armlabel, price=None, source=''):
        data['arms'][key] = None if rows is None else summarize(rows, ids, T, price)
        if data['arms'][key] is not None:
            data['arms'][key].update(label=label, arm=armlabel, source=source)
        return rows

    # ---- Table 3: the 108-task and 324-task subsets
    rows_store = {}
    for n, S in ((108, S108), (324, S324)):
        rows_store[(n, 'ours')] = arm((n, 'ours'), load_rows(f'{RES}/local{n}_lib_all/per_task_{final}.jsonl', S,
                                      f'VeriBIM-9B on the {n}-task subset (local{n}_lib, {final})'), S, OURS_LABEL,
                                      ARM_LABEL['lib'], source=f'local{n}_lib_all/{final}')
        for a in (('alone', 'libnote') if n in BASE_SETS else ()):     # 324-task base reads: not planned
            rows_store[(n, 'base', a)] = arm((n, 'base', a), load_rows(
                f'{RES}/local{n}_{a}_all/per_task_{BASE}.jsonl', S, f'{BASE} {a} on the {n}-task subset'),
                S, BASE_LABEL, ARM_LABEL[a], source=f'local{n}_{a}_all/{BASE}')
        # optional dedicated local reads of the other adapters (macros only)
        for name in (SFT, PREV):
            for a in ('lib', 'alone'):
                rows_store[(n, name, a)] = arm((n, name, a), load_rows(
                    f'{RES}/local{n}_{a}_all/per_task_{name}.jsonl', S, '', required=False), S, name, ARM_LABEL[a],
                    source=f'local{n}_{a}_all/{name}')
        models = COMMERCIAL if n == 108 else [c for c in COMMERCIAL if c[0] == 'claude-sonnet-5-5']
        for mid, mlabel, _ in models:
            for a in ('alone', 'lib'):
                rows_store[(n, mid, a)] = arm((n, mid, a), load_rows(
                    f'{RES}/hosted{n}_{a}_all/per_task_{mid}.jsonl', S, f'{mlabel} {a} on the {n}-task subset'),
                    S, mlabel, ARM_LABEL[a], price=PRICE[mid], source=f'hosted{n}_{a}_all/{mid}')
                if n == 108:
                    ot = load_json(f'{RES}/hosted108_{a}_all/offtarget_{mid}/offtarget_summary.json', '', required=False)
                    if ot:
                        net = ot['all_evaluated']['off_target_count_net']
                        data['offtarget'][(108, mid, a)] = (net['total_count'], net['n_with_off_target'], net['n'])
        ours = rows_store[(n, 'ours')]
        for key, rws in list(rows_store.items()):
            if key[0] != n or key[1] == 'ours' or rws is None or ours is None:
                continue
            data['deltas'][(n, 'ours') + key[1:]] = paired(ours, rws, S, T)

    # ---- library x training interaction on the 108-task subset: paired difference-in-differences per task
    data['did'] = None
    q = [rows_store.get(k) for k in ((108, SFT, 'lib'), (108, SFT, 'alone'), (108, 'base', 'libnote'), (108, 'base', 'alone'))]
    if all(x is not None for x in q):
        ids_ = sorted(S108)
        data['did'] = {}
        for nm, f_ in (('comp', done), ('mean', lambda r: float(r.get('final') or 0.0))):
            d_ = [(f_(q[0][t]) - f_(q[1][t])) - (f_(q[2][t]) - f_(q[3][t])) for t in ids_]
            data['did'][nm] = boot(d_)
    else:
        PENDING.append(('library x training interaction (four 108-task reads)', f'{RES}/local108_*_all', 'a read is missing'))
    data['separation'] = separation()

    # ---- latency of the local model: one-at-a-time read, and the tool/model split from the transcripts
    data['solo'], data['inflight'], data['inflight_split'] = None, None, None
    solo = load_rows(f'{RES}/local108_lib_solo/per_task_{final}.jsonl', S108,
                     f'one-at-a-time read of the final model on the 108-task subset (local108_lib_solo, {final})')
    if solo is not None:
        ss = summarize(solo, S108, T)
        data['solo'] = {'secs': ss['secs'], 'rounds': ss['rounds'], 'comp': ss['comp'][0], 'done': ss['done'],
                        'split': transcript_split(f'{RES}/local108_lib_solo/{final}/transcripts', solo, S108)}
    if rows_store.get((108, 'ours')) is not None:
        data['inflight_split'] = transcript_split(f'{RES}/local108_lib_all/{final}/transcripts', rows_store[(108, 'ours')], S108)
        lg = f'{RES}/local108_lib_all/{final}.log'
        if os.path.exists(lg):
            m_ = re.search(r'(\d+) in flight', open(lg).readline())
            data['inflight'] = int(m_.group(1)) if m_ else None

    # ---- Table 4: the training chain on the 2,100-task benchmark
    dpo_full = chosen if os.path.exists(f'{RES}/full_all/per_task_{chosen}.jsonl') else PROVISIONAL_DPO
    data['chosen_provisional'] = not (chosen_file or chosen_curve)
    data['dpo_full'] = dpo_full
    if dpo_full != chosen or data['chosen_provisional']:
        PROVISIONAL.append(f'Table 4 "+ preferences" row: {dpo_full} (provisional until the chosen snapshot is fixed and read)')
    chain = [('base', f'{RES}/full_note_all/per_task_{BASE}.jsonl', f'{RES}/full_note_all/offtarget_{BASE}/offtarget_summary.json',
              'Qwen3.5-9B, untrained, with the library note'),
             ('sft', f'{RES}/full_all/per_task_{SFT}.jsonl', f'{RES}/full_all/offtarget_{SFT}/offtarget_summary.json', 'Imitation'),
             ('dpo', f'{RES}/full_all/per_task_{dpo_full}.jsonl', f'{RES}/full_all/offtarget_{dpo_full}/offtarget_summary.json',
              '+ preferences (VeriBIM-9B)'),
             ('grpo', f'{RES}/full_all/per_task_{args.grpo}.jsonl', f'{RES}/full_all/offtarget_{args.grpo}/offtarget_summary.json',
              '+ reinforcement (VeriBIM-9B)' if final_is_grpo else '+ reinforcement (not adopted)'),
             ('prev', f'{RES}/full_all/per_task_{PREV}.jsonl', f'{RES}/full_all/offtarget_{PREV}/offtarget_summary.json',
              'Imitation + preferences, earlier corpus')]
    full_rows = {}
    for key, p, po, label in chain:
        if key == 'base':
            continue           # a stopped read: estimated below, never a full-benchmark arm
        full_rows[key] = arm((2100, key), load_rows(p, ALL, f'{label} on the 2,100-task benchmark'), ALL, label, '',
                             source=os.path.relpath(p, RES))
        ot = load_json(po, f'off-target summary, {label}')
        if ot:
            net = ot['all_evaluated']['off_target_count_net']
            if ot.get('n_rows') != 2100:
                WARN.append(f'{po}: n_rows {ot.get("n_rows")} != 2100')
            data['offtarget'][(2100, key)] = (net['total_count'], net['n_with_off_target'], net['n'])
        # off-target changes on tasks the checker counts as completed (per-task file of the off-target count)
        ptp = os.path.join(os.path.dirname(po), 'offtarget_per_task.jsonl')
        if full_rows[key] is not None and os.path.exists(ptp):
            pt = [json.loads(l) for l in open(ptp) if l.strip()]
            INPUTS.append((ptp, len(pt)))
            mism = sum(1 for r in pt if r['task_id'] in full_rows[key]
                       and bool(r.get('completed')) != bool(done(full_rows[key][r['task_id']])))
            if mism:
                WARN.append(f'{ptp}: {mism} rows whose "completed" flag differs from the completion rule on the per-task row')
            dn = [r for r in pt if r.get('status') == 'ok' and done(full_rows[key][r['task_id']])]
            data['offdone'][key] = (sum(int(r.get('off_target_count_net') or 0) for r in dn),
                                    sum(1 for r in dn if (r.get('off_target_count_net') or 0) > 0), len(dn))
    for a, b in (('dpo', 'sft'), ('grpo', 'dpo'), ('dpo', 'prev')):
        if full_rows[a] is not None and full_rows[b] is not None:
            data['deltas'][(2100, a, b)] = paired(full_rows[a], full_rows[b], ALL, T)
    # ---- the final model on the 2,100-task benchmark: \ResBenchOurs... aliases the final stage's values
    fk = data['final_key']
    full_rows['ours'] = full_rows.get(fk)
    if full_rows['ours'] is not None:
        data['arms'][(2100, 'ours')] = dict(data['arms'][(2100, fk)], label='final model', source=f'{fk} = {final}')
        if (2100, fk) in data['offtarget']:
            data['offtarget'][(2100, 'ours')] = data['offtarget'][(2100, fk)]
        if fk in data['offdone']:
            data['offdone']['ours'] = data['offdone'][fk]
        for b in (('sft', 'dpo') if final_is_grpo else ('sft',)):
            if full_rows.get(b) is not None:
                data['deltas'][(2100, 'ours', b)] = paired(full_rows['ours'], full_rows[b], ALL, T)
        # mean of the per-task 'final' score per operation (summarize's mean rule); kept out of the figure data
        data['ours_op_mean'] = {}
        for op in OPS:
            v = [full_rows['ours'][t].get('final') or 0.0 for t in ALL if T[t]['operation'] == op]
            if v:
                data['ours_op_mean'][op] = (float(np.mean(v)), len(v))

    # ---- stop classes of the preference-stage snapshot over the 2,100 tasks (Table 5 rule, outcome_class), for the
    # \ResBenchDpoFail... macros; kept out of the figure data
    data['dpo_stop'] = None if full_rows.get('dpo') is None else \
        (dpo_full, Counter(outcome_class(full_rows['dpo'][t]) for t in ALL))

    # ---- the untrained base on the 2,100-task benchmark: an estimate
    base_p = f'{RES}/full_note_all/per_task_{BASE}.jsonl'
    rows982 = load_rows_partial(base_p, ALL, 'untrained base, stopped 2,100-task read')
    data['base_est'] = None
    if rows982 is not None:
        be = base_estimate(rows982, rows_store.get((108, 'base', 'libnote')), T)
        if not be['versions_complete']:
            miss = [v for v in VERS if be['per'][v] is None]
            PENDING.append(('base estimate, versions without a measured task (needs the 108-task read with the '
                            'library note)', f'{RES}/local108_libnote_all/per_task_{BASE}.jsonl',
                            ', '.join(miss)))
        elif rows_store.get((108, 'base', 'libnote')) is None:
            PROVISIONAL.append('base estimate without the 108-task read')
        ot = load_json(f'{RES}/full_note_all/offtarget_{BASE}/offtarget_summary.json', 'off-target summary, untrained base')
        if ot:
            net = ot['all_evaluated']['off_target_count_net']
            if ot.get('n_rows') != len(rows982):
                WARN.append(f'base off-target summary: n_rows {ot.get("n_rows")} != {len(rows982)} read rows')
            be['off'] = (net['total_count'], net['n_with_off_target'], net['n'])
        bv = f'{RES}/full_note_all/by_version_{BASE}.txt'
        if os.path.exists(bv):
            for line in open(bv):
                m = re.match(r'ALL\s+(\d+)\s+completion\s+([0-9.]+)', line)
                if m:
                    be['by_version_all'] = (int(m.group(1)), float(m.group(2)))
        for k in ('sft', 'dpo'):
            if full_rows.get(k) is not None:
                g = base_gain(full_rows[k], be, T)
                if g:
                    data['deltas'][(2100, k, 'base')] = g
                # measured part: paired on the complete IFC2X3 part
                ids2 = be['per']['IFC2X3']['ids'] if be['per']['IFC2X3'] else []
                if ids2 and be['per']['IFC2X3']['measured_all']:
                    be.setdefault('gain2x3', {})[k] = boot([done(full_rows[k][t]) - done(rows982[t]) for t in ids2])
        data['base_est'] = be

    # ---- Fig. 10 curve
    snaps = []
    for name, (c, m, nn) in pts.items():
        mm = re.fullmatch(r'dpo_v10_c(\d+)', name)
        if mm:
            snaps.append((int(mm.group(1)), name, c, m, nn))
        elif name.startswith('dpo_v10'):
            WARN.append(f'curve {os.path.basename(curve_path)}: {name} has no step in its name; left out of Fig. 10')
    snaps.sort()
    data['curve'] = {'path': curve_path, 'provisional': curve_provisional, 'snaps': snaps,
                     'baseline': pts.get(SFT), 'chosen': chosen if chosen in pts else None, 'pairs': pairs}

    # ---- reinforcement stage on the hard validation set (Fig. 10 right panel, \ResValHardGrpo... macros)
    data['grpo_name'] = args.grpo
    data['grpo_curve'] = None
    leg_of = lambda k: k.rsplit('_c', 1)[0]
    if os.path.exists(CURVE_BOTH):
        # both reinforcement runs on one step axis: 'name\tstep N\tcompletion X\tmean Y' lines and 'PEAK\tname'
        rows_b, gpeak = parse_curve_both(CURVE_BOTH)
        INPUTS.append((CURVE_BOTH, len(rows_b)))
        gs = sorted((st, k, c_, m_, None, leg_of(k)) for k, (st, c_, m_) in rows_b.items()
                    if re.fullmatch(r'grpo_v10[a-z]?_c\d+', k))
        start = (rows_b[chosen][1], rows_b[chosen][2], None) if chosen in rows_b else pts.get(chosen)
        data['grpo_curve'] = {'snaps': gs, 'start': start, 'baseline': pts.get(SFT), 'peak': gpeak,
                              'source': CURVE_BOTH}
    elif os.path.exists(GRPO_CURVE):
        gpts, gpeak, _ = parse_curve(GRPO_CURVE)
        INPUTS.append((GRPO_CURVE, len(gpts)))
        gs = sorted((int(m_.group(1)), k, v[0], v[1], v[2], leg_of(k)) for k, v in gpts.items()
                    if (m_ := re.fullmatch(r'grpo_v10[a-z]?_c(\d+)', k)))
        data['grpo_curve'] = {'snaps': gs, 'start': gpts.get(chosen), 'baseline': gpts.get(SFT), 'peak': gpeak,
                              'source': GRPO_CURVE}
        if gpts.get(chosen) and chosen in pts and abs(gpts[chosen][0] - pts[chosen][0]) > 6e-4:
            WARN.append(f'{os.path.basename(GRPO_CURVE)}: start {chosen} {gpts[chosen][0]} differs from the preference curve {pts[chosen][0]}')
    else:
        PENDING.append(('reinforcement curve on the hard set', GRPO_CURVE, 'file absent'))
    gc_ = data['grpo_curve']
    if gc_ and final_is_grpo and final not in [x[1] for x in gc_['snaps']]:
        WARN.append(f'the final model {final} is not on the hard-set reinforcement curve ({os.path.basename(gc_["source"])})')
    data['vh_deltas'] = {}
    vh_ids = json.load(open(VALHARD_IDS)) if os.path.exists(VALHARD_IDS) else None
    if vh_ids:
        INPUTS.append((VALHARD_IDS, len(vh_ids)))
        vrows = {}
        gdir = next((d for d in GRPO_VALHARD_DIRS if os.path.exists(f'{d}/per_task_{args.grpo}.jsonl')), GRPO_VALHARD_DIRS[0])
        for name, d_ in ((SFT, DPO_VALHARD_ROWS), (chosen, DPO_VALHARD_ROWS), (args.grpo, gdir)):
            vrows[name] = load_rows(f'{d_}/per_task_{name}.jsonl', vh_ids, f'{name} on the hard validation set',
                                    required=False)
        for a_, b_ in ((chosen, SFT), (args.grpo, chosen)):
            if vrows.get(a_) is not None and vrows.get(b_) is not None:
                d_ = {'ALL': boot([done(vrows[a_][t]) - done(vrows[b_][t]) for t in vh_ids])}
                d_['wins'] = sum(1 for t in vh_ids if done(vrows[a_][t]) > done(vrows[b_][t]))
                d_['losses'] = sum(1 for t in vh_ids if done(vrows[a_][t]) < done(vrows[b_][t]))
                d_['a_comp'] = float(np.mean([done(vrows[a_][t]) for t in vh_ids]))
                data['vh_deltas'][(a_, b_)] = d_
    # ---- rewritten-wording validation set (val-100 v3b): final model, imitation model, chosen preference snapshot,
    # \ResValSmall... macros only (kept out of the figure data); a missing or partially written read stays pending
    data['v100b'], data['v100b_missing'], data['v100b_n'] = {}, {}, None
    v100_ids = json.load(open(V100B_SUBSET)) if os.path.exists(V100B_SUBSET) else None
    if v100_ids is not None:
        INPUTS.append((V100B_SUBSET, len(v100_ids)))
        v100_tasks = [json.loads(l)['task_id'] for l in open(SEP_VAL100) if l.strip()] if os.path.exists(SEP_VAL100) else []
        INPUTS.append((SEP_VAL100, len(v100_tasks)))
        if len(set(v100_ids)) != len(v100_ids) or set(v100_ids) != set(v100_tasks):
            WARN.append(f'{V100B_SUBSET}: {len(v100_ids)} ids ({len(set(v100_ids))} distinct) do not match the '
                        f'{len(v100_tasks)} tasks of {os.path.basename(SEP_VAL100)}; ResValSmall... left pending')
            v100_ids = None
    if v100_ids is not None:
        data['v100b_n'] = len(v100_ids)
    for name in dict.fromkeys((final, SFT, chosen)):
        pth = f'{V100B}/per_task_{name}.jsonl'
        rws = None if v100_ids is None else load_rows(pth, v100_ids, f'{name} on the rewritten-wording validation set',
                                                      required=False)
        if rws is None:
            data['v100b_missing'][name] = ('subset ids unavailable' if v100_ids is None else
                                           'file absent' if not os.path.exists(pth) else 'incomplete or duplicate task ids')
            continue
        c_ = [done(rws[t]) for t in sorted(v100_ids)]
        data['v100b'][name] = {'n': len(c_), 'done': int(sum(c_)), 'comp': float(np.mean(c_)),
                               'mean': float(np.mean([rws[t].get('final') or 0.0 for t in sorted(v100_ids)]))}
    data['pool'] = load_json(POOL_REPORT, 'preference pool report', required=False)
    # ---- BIM-Edit (E1) reads: final model, earlier corpus, imitation
    data['bimedit'] = {}
    for name in dict.fromkeys((final, chosen, PREV, SFT)):
        pth = f'{E1}/scores_bench_{name}.csv'
        if os.path.exists(pth):
            import csv
            rr = {r['task_id']: r for r in csv.DictReader(open(pth))}
            INPUTS.append((pth, len(rr)))
            if len(rr) != 324:
                WARN.append(f'{pth}: {len(rr)} rows, expected 324')
            err = [t for t, r in rr.items() if r.get('error')]
            if err:
                WARN.append(f'{pth}: {len(err)} rows with a scorer error')
            data['bimedit'][name] = rr
        elif name == final:
            PENDING.append(('BIM-Edit read of the final model', pth, 'file absent'))

    data['flip_file'] = FLIP_PATTERN.format(final)
    if not os.path.exists(data['flip_file']):
        PENDING.append(('flip rate of two identical reads of the final model', data['flip_file'], 'file absent'))
    if args.strict and (PENDING or PROVISIONAL):
        for p in PENDING:
            log(f'MISSING  {p[0]}: {p[1]} ({p[2]})')
        for p in PROVISIONAL:
            log(f'PROVISIONAL  {p}')
        sys.exit(2)

    write_tab3(data, 108)
    write_tab3(data, 324)
    write_tab4(data)
    write_tab5(data, full_rows, T)
    write_tabE1(data, full_rows, T)
    write_tab6(data)
    write_cost_caption(data)
    write_curve_caption(data)
    write_macros(data)
    fig_json = dump_fig_data(data, f'{OUT_TAB}/exhibit_data.json')
    py = sys.executable
    for script in ('fig08_main/make_fig08.py', 'fig09_ablation/make_fig09.py', 'fig10_curve/make_fig10.py',
                   'fig_cost/make_fig_cost.py'):
        extra = ['--outdir', os.path.join(FIG_OUTDIR, os.path.dirname(script))] if FIG_OUTDIR else []
        subprocess.run([py, f'{OUT_FIG}/{script}', fig_json] + extra, check=True)
    if args.preview:
        os.makedirs(args.preview, exist_ok=True)
        prev = preview_data(data, S108, S324, ALL, T, final if final_is_grpo else dpo_full)
        pj = dump_fig_data(prev, os.path.join(args.preview, 'exhibit_data_preview.json'))
        for script in ('fig08_main/make_fig08.py', 'fig_cost/make_fig_cost.py'):
            subprocess.run([py, f'{OUT_FIG}/{script}', pj, '--outdir', args.preview, '--preview'], check=True)
    for p in PENDING:
        log(f'PENDING  {p[0]}: {os.path.relpath(p[1], ROOT)} ({p[2]})')
    for p in PROVISIONAL:
        log(f'PROVISIONAL  {p}')
    for w in WARN:
        log(f'NOTE  {w}')
    json.dump({'pending': PENDING, 'provisional': PROVISIONAL, 'inputs': INPUTS, 'notes': WARN,
               'file_stats': FILESTATS}, open(f'{OUT_TAB}/exhibit_status.json', 'w'), indent=1)
    write_report(data, args)


def preview_data(data, S108, S324, ALL, T, dpo_full):
    """Layout preview only: the local slots filled from the 2,100-task read restricted to the subset."""
    import copy
    d = copy.deepcopy(data)
    rows = {}
    for line in open(f'{RES}/full_all/per_task_{dpo_full}.jsonl'):
        r = json.loads(line)
        rows[r['task_id']] = r
    for n, S in ((108, S108), (324, S324)):
        s = summarize(rows, S, T)
        s.update(label=OURS_LABEL, arm=ARM_LABEL['lib'], source='PREVIEW 2,100-task read restricted')
        d['arms'][(n, 'ours')] = s
    d['preview'] = True
    return d


def dump_fig_data(data, path):
    arms = {'|'.join(map(str, k)): v for k, v in data['arms'].items()}
    be = data.get('base_est')
    if be:
        fa = {'estimate': True, 'comp': be['est']}
        for v in VERS:
            pv = be['per'][v]
            fa[v] = None if pv is None else list(pv['boot']) + [pv['n']]
        arms['2100|base'] = fa
    if data.get('solo') and arms.get('108|ours'):           # cost figure: one-at-a-time latency for the local model
        arms['108|ours'] = dict(arms['108|ours'], secs=data['solo']['secs'], secs_inflight=arms['108|ours']['secs'])
    deltas = {'|'.join(map(str, k)): v for k, v in data['deltas'].items()}
    ot = {'|'.join(map(str, k)): v for k, v in data['offtarget'].items()}
    json.dump({'chosen': data['chosen'], 'arms': arms, 'deltas': deltas, 'offtarget': ot, 'curve': data['curve'],
               'preview': data.get('preview', False), 'commercial': COMMERCIAL, 'workstation': WORKSTATION,
               'ours_label': OURS_LABEL, 'base_label': BASE_LABEL, 'grpo_curve': data.get('grpo_curve'),
               'grpo_name': data.get('grpo_name'), 'final': data.get('final'), 'final_is_grpo': data.get('final_is_grpo'),
               'grpo_label': '+ reinforcement (VeriBIM-9B)' if data.get('final_is_grpo') else '+ reinforcement (not adopted)',
               'vh_deltas': {'|'.join(k): v for k, v in data.get('vh_deltas', {}).items()}}, open(path, 'w'), indent=1)
    return path


# ---------------------------------------------------------------- tables
HEADER_NOTE = '% GENERATED by writing/tables/make_results_exhibits.py; do not edit by hand. Needs macros_results_v10.tex (\\pending).\n'


def tab3_rows(data, n):
    A, D = data['arms'], data['deltas']
    out = []

    def row(key, label, armlabel, dkey, group='local'):
        a = A.get(key)
        r = {'label': label, 'arm': armlabel, 'group': group}
        if a:
            r.update(all=a['comp'][0], mean=a['mean'], rounds=a['rounds'], **{g: a[g][0] for g in VERS})
        dd = D.get(dkey)
        r['delta'] = dd['ALL'] if dd else None
        r['has'] = a is not None
        out.append(r)
    row((n, 'ours'), OURS_LABEL, ARM_LABEL['lib'], None)
    models = COMMERCIAL if n == 108 else [c for c in COMMERCIAL if c[0] == 'claude-sonnet-5-5']
    for mid, mlabel, _ in models:
        for a in ('alone', 'lib'):
            row((n, mid, a), mlabel, ARM_LABEL[a], (n, 'ours', mid, a), group='commercial')
    # local models: the library x training 2 x 2 (untrained base on the 108-task subset only)
    if n in BASE_SETS:
        for a in ('alone', 'libnote'):
            row((n, 'base', a), BASE_LABEL, ARM_LABEL[a], (n, 'ours', 'base', a))
    for a in ('alone', 'lib'):
        row((n, SFT, a), SFT_LABEL, ARM_LABEL[a], (n, 'ours', SFT, a))
    return out


def write_tab3(data, n):
    rows = tab3_rows(data, n)
    keys = ['all'] + VERS + ['mean', 'rounds']
    bkeys = ['all'] + VERS + ['mean']              # bold on completion and mean score only
    best = bold_cols(rows, bkeys, {k: 'max' for k in bkeys})
    per = 36 if n == 108 else 108
    lab = 'tab:main' if n == 108 else 'tab:main324'
    if n == 108:
        cap = (r'Results on the 108-task subset, with 36 tasks per IFC version. The last column is the paired difference '
               r'in completion between VeriBIM-9B and each row with its 95\,\% bootstrap interval. Bold marks the '
               r'highest completion and mean score per column.')
    else:
        cap = (r'Results on the 324-task subset, with 108 tasks per IFC version. Columns and bold marks as in '
               r'Table~\ref{tab:main}.')
    L = [HEADER_NOTE, r'\begin{table}[htbp]', r'\centering', rf'\caption{{{cap}}}', rf'\label{{{lab}}}', r'\footnotesize',
         r'\setlength{\tabcolsep}{4pt}',
         r'\begin{tabular}{@{}llcccccccc@{}}', r'\toprule',
         r' & & \multicolumn{4}{c}{Completion} & & & \multicolumn{2}{c}{VeriBIM-9B minus this row} \\',
         r'\cmidrule(lr){3-6}\cmidrule(l){9-10}',
         r'Model & Arm & All & IFC2X3 & IFC4 & IFC4X3 & Mean score & Rounds & Difference & 95\,\% interval \\', r'\midrule']
    prev_label = None
    for i, r in enumerate(rows):
        if i == 1 or (r['group'] == 'local' and i > 1 and rows[i - 1]['group'] == 'commercial'):
            L.append(r'\midrule')
        label = r['label'] if r['label'] != prev_label else ''
        prev_label = r['label']
        cells = [label, r['arm']] + [cell(r.get(k), k, best, (lambda v: f'{v:.2f}') if k == 'rounds' else f3) for k in keys]
        if i == 0:
            cells += ['', '']
        elif r['delta'] is None:
            cells += [r'\pending', r'\pending']
        else:
            m, lo, hi = r['delta']
            cells += [sgn(m), interval_txt(lo, hi)]
        L.append(' & '.join(cells) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
    name = 'tab3_main.tex' if n == 108 else 'tab3b_324.tex'
    open(f'{OUT_TAB}/{name}', 'w').write('\n'.join(L))


def write_tab4(data):
    A, D, O = data['arms'], data['deltas'], data['offtarget']
    be = data.get('base_est')
    order = ['base', 'sft', 'dpo', 'grpo', 'prev']
    fg = data.get('final_is_grpo')
    labels = {'base': BASE_EST_LABEL, 'sft': 'Imitation', 'dpo': '+ preferences' if fg else '+ preferences (VeriBIM-9B)',
              'grpo': '+ reinforcement (VeriBIM-9B)' if fg else '+ reinforcement (not adopted)',
              'prev': 'Imitation + preferences, earlier corpus'}
    keys = ['all'] + VERS + ORIGS + ['mean', 'rounds', 'off']
    rows = []
    for k in order:
        a = A.get((2100, k))
        r = {'label': labels[k]}
        if a:
            r.update(all=a['comp'][0], mean=a['mean'], rounds=a['rounds'], **{g: a[g][0] for g in VERS + ORIGS})
        o = O.get((2100, k))
        r['off'] = o[0] if o else None
        rows.append(r)
    if be:                                          # the base row takes part in the bold rule
        if be['est']:
            rows[0]['all'] = be['est'][0]
        rows[0].update({v: be['per'][v]['rate'] for v in VERS if be['per'][v]})
        rows[0].update({o: be['origin'][o] for o in ORIGS if be['origin'][o] is not None})
        rows[0]['mean'] = be['mean']
    bkeys = ['all'] + VERS + ORIGS + ['mean']       # bold on completion and mean score only; rounds, off-target none
    best = bold_cols(rows, bkeys, {k: 'max' for k in bkeys})
    L = [HEADER_NOTE, r'\begin{table}[htbp]', r'\centering',
         r'\caption{Completion, mean score, mean tool rounds and off-target changes along the training chain on the '
         r'2,100-task benchmark. Bold marks the highest completion and mean score per column.}',
         r'\label{tab:ablation}', r'\footnotesize', r'\setlength{\tabcolsep}{3.6pt}',
         r'\begin{tabular}{@{}lccccccccc@{}}', r'\toprule',
         r' & \multicolumn{6}{c}{Completion} & & & \\', r'\cmidrule(lr){2-7}',
         r' & & \multicolumn{3}{c}{By IFC version} & \multicolumn{2}{c}{By origin} & & & Off-target \\',
         r'\cmidrule(lr){3-5}\cmidrule(lr){6-7}',
         r'Stage & All & IFC2X3 & IFC4 & IFC4X3 & Native & Migrated & Mean score & Rounds & changes \\', r'\midrule']
    for i, r in enumerate(rows):
        if order[i] == 'prev':
            L.append(r'\midrule')
        if order[i] == 'base':
            L.append(' & '.join(base_row_cells(be, best)) + r' \\')
            continue
        cells = [r['label']]
        for k in keys:
            fmt = (lambda v: f'{v:.2f}') if k == 'rounds' else ((lambda v: f'{int(v):,}') if k == 'off' else f3)
            cells.append(cell(r.get(k), k, best, fmt))
        L.append(' & '.join(cells) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}']

    def dtxt(a, b):
        d = D.get((2100, a, b))
        if not d:
            return r'\pending{}'
        m, lo, hi = d['ALL']
        return (r'$\approx$' if b == 'base' else '') + f'{sgn(m)} {interval_txt(lo, hi)}' + (' (estimated)' if b == 'base' else '')
    nread = be['n_read'] if be else r'\pending{}'
    note = (r'\par\smallskip\parbox{\linewidth}{\footnotesize\itshape\textbf{Note:} The untrained row is estimated from '
            rf'{nread} evaluated tasks and the 108-task subset (see Section~\ref{{sec:protocol}}). Its IFC2X3 value is '
            r'measured on all 700 tasks, the values marked $\approx$ are estimates, and the bracket gives the 95\,\% '
            rf'interval of its pooled estimate. Its mean score, rounds and off-target changes are measured on the {nread} '
            r'evaluated tasks. Paired differences in completion over the 2,100 tasks, with 95\,\% bootstrap intervals, are '
            + dtxt('sft', 'base') + ' for imitation over the untrained model, ' + dtxt('dpo', 'sft') +
            ' for preferences over imitation, ' + dtxt('grpo', 'dpo') + ' for reinforcement over preferences and ' +
            dtxt('dpo', 'prev') + r' for the current corpus over the earlier corpus, both after the preference stage. ' + final_sentence(data) +
            r' Off-target changes are counted over the tasks that produced an edited model.}')
    L += [note, r'\end{table}', '']
    open(f'{OUT_TAB}/tab4_ablation.tex', 'w').write('\n'.join(L))


def snap_step(name):
    m = re.search(r'_c(\d+)$', name or '')
    return m.group(1) if m else '?'


def final_sentence(data):
    if data.get('final_is_grpo'):
        _fs = snap_step(data["final"]); _fstep = (f"path step {50 + int(_fs)} (step {_fs} of the second run)" if 'v10b' in data['final'] else f"step {_fs}")
        return (f"The final model is the reinforcement-stage snapshot at {_fstep}, and the "
                f"preference-stage snapshot is reported for comparison.")
    return 'The final model is the preference-stage snapshot, and the reinforcement row is reported for comparison.'


def stack(a, b, align='c'):
    return rf'\begin{{tabular}}[c]{{@{{}}{align}@{{}}}}{a}\\{{}}{b}\end{{tabular}}'   # {{}} keeps \\ from reading [..] as a length


def base_row_cells(be, best=None):
    """Table 4 row of the untrained model: IFC2X3 measured on all 700 tasks, the rest estimates."""
    label = stack('Qwen3.5-9B, untrained', '(estimate)', 'l')
    if be is None:
        return [label] + [r'\pending'] * 9
    AP = r'$\approx$'
    est = be['est']
    best = best or {}
    B = lambda k, v, txt: rf'\textbf{{{txt}}}' if k in best and round(v, 3) == best[k] else txt
    c_all = r'\pending' if est is None else stack(B('all', est[0], AP + f3(est[0])), f'[{f3(est[1])}, {f3(est[2])}]')
    cells = [label, c_all]
    for v in VERS:
        pv = be['per'][v]
        cells.append(r'\pending' if pv is None else B(v, pv['rate'], f3(pv['rate']) if pv['measured_all'] else AP + f3(pv['rate'])))
    for o in ORIGS:
        x = be['origin'][o]
        cells.append(r'\pending' if x is None else B(o, x, AP + f3(x)))
    cells += [B('mean', be['mean'], f3(be['mean'])), f'{be["rounds"]:.2f}', f'{be["off"][0]:,}' if be.get('off') else r'\pending']
    return cells


def interval_txt(lo, hi):
    """Signed bracket; four decimals when a nonzero bound would print as 0.000 at three."""
    four = any(x != 0 and f'{abs(x):.3f}' == '0.000' for x in (lo, hi))
    g = (lambda x: (f'+{x:.4f}' if x >= 0 else f'$-${abs(x):.4f}')) if four else sgn
    return f'[{g(lo)}, {g(hi)}]'


def write_tab5(data, full_rows, T):
    """Table 5: outcome of every benchmark task of the final local model, by task group, from per-task rows only."""
    key = data.get('final_key', 'dpo')
    rows = full_rows.get(key)
    groups = [('all', 'All tasks')] + [(g, g.capitalize()) for g in OPS] + [(g, g.capitalize()) for g in CATS] + \
             [('chain', 'Chains of dependent edits')]
    sel = group_selectors(T)
    sel['all'] = lambda t: True
    cls_names = ['committed_rejected', 'round_limit', 'context_limit', 'reply_only', 'other_stop']
    head = ['Committed, rejected', 'Round limit', 'Context limit', 'Reply, no edit', 'Other stop']
    tab = {}
    if rows is not None:
        for g, _ in groups:
            ids = [t for t in rows if sel[g](t)]
            c = Counter()
            for t in ids:
                c[outcome_class(rows[t])] += 1
            tab[g] = (len(ids), c)
    used = [k for k in cls_names if any(tab[g][1][k] for g in tab)] if tab else cls_names[:4]
    data['tab5'] = {g: {'n': n, **dict(c)} for g, (n, c) in tab.items()}
    data['tab5_classes'] = used
    who = f'the final model ({data["final"]})'
    L = [HEADER_NOTE, r'\begin{table}[htbp]', r'\centering',
         r'\caption{Outcome of each task of the 2,100-task benchmark for VeriBIM-9B, by task group, counted from '
         r'the per-task result rows. A failed task is counted once, under the way its run ended. The BIM-Edit column '
         r'gives the mean score of the same model on the public BIM-Edit benchmark, which has no chained tasks.}',
         r'\label{tab:failures}', r'\footnotesize', r'\setlength{\tabcolsep}{4pt}',
         r'\begin{tabular}{@{}l' + 'c' * (3 + len(used)) + r'@{}}', r'\toprule',
         r' & & & \multicolumn{' + str(len(used)) + r'}{c}{Failed tasks, by how the run ended} & \\',
         r'\cmidrule(lr){4-' + str(3 + len(used)) + '}',
         'Task group & Tasks & Completion & ' + ' & '.join(head[cls_names.index(k)] for k in used) +
         r' & BIM-Edit \\', r'\midrule']
    for i, (g, lab) in enumerate(groups):
        if i in (1, 4, 7):
            L.append(r'\midrule')
        if g not in tab:
            L.append(' & '.join([lab] + [r'\pending'] * (3 + len(used))) + r' \\')
            continue
        n, c = tab[g]
        comp = c['completed'] / n
        L.append(' & '.join([lab, f'{n:,}', f3(comp)] + [f'{c[k]:,}' for k in used] + [bim_cell(data, g)]) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}',
          r'\par\smallskip\parbox{\linewidth}{\footnotesize\itshape\textbf{Note:} ' + tab5_note(used) + '}',
          r'\end{table}', '']
    L.insert(1, f'% source: runs_local/bench_v4/results/full_all/per_task_{data["final"]}.jsonl ({who}); '
                f'BIM-Edit column: runs_local/e1/scores_bench_{data["final"]}.csv (mean final_score)')
    open(f'{OUT_TAB}/tab5_failures.tex', 'w').write('\n'.join(L))


def write_tabE1(data, full_rows, T):
    """Appendix Table E.1 (tab:cells): completion per version x operation x category for the untrained base, the
    imitation model and the final model, same layout as the appendix skeleton. Base cells: measured when every task of
    the cell was read, marked with an approximately sign when at least 10 of its tasks were read, otherwise a dash."""
    be = data.get('base_est')
    per = be['_per_rows'][0] if be else {v: {} for v in VERS}
    sft, fin = full_rows.get('sft'), full_rows.get(data.get('final_key', 'dpo'))
    AP = r'$\approx$'
    L = [HEADER_NOTE.rstrip('\n'),
         f'% Base: {BASE} with the library note (stopped read plus the 108-task read); imitation: {SFT}; final: '
         f'{data["final"]}; full_all/per_task_<arm>.jsonl joined with tasks.v4c.jsonl on task_id.',
         r'\begin{table}[pos=htbp]', r'\centering', r'\footnotesize',
         r'\caption{Completion per cell of \BenchName{} for the base model, the model after imitation, and the final model.}',
         r'\label{tab:cells}', r'\begin{tabular}{@{}llrrrr@{}}', r'\toprule',
         r'Operation & Category & Tasks & Base & Imitation & Final \\', r'\midrule']
    cells_used = {'measured': 0, 'approx': 0, 'dash': 0}
    for vi, v in enumerate(VERS):
        if vi:
            L.append(r'\midrule')
        L.append(rf'\multicolumn{{6}}{{@{{}}l}}{{\textit{{{v} part}}}} \\')
        for op in OPS + ['ALL']:
            for cat in (CATS if op != 'ALL' else ['']):
                ids = [t for t in T if T[t]['ifc_version'] == v and (op == 'ALL' or (T[t]['operation'] == op and T[t]['category'] == cat))]
                meas = [t for t in ids if t in per[v]]
                if len(meas) == len(ids) and ids:
                    b = f3(np.mean([done(per[v][t]) for t in meas])); cells_used['measured'] += 1
                elif len(meas) >= 10:
                    b = AP + f3(np.mean([done(per[v][t]) for t in meas])); cells_used['approx'] += 1
                else:
                    b = '--'; cells_used['dash'] += 1
                col = lambda rows: r'\pending' if rows is None else f3(np.mean([done(rows[t]) for t in ids]))
                lab = ('All', '') if op == 'ALL' else (op.capitalize(), cat.capitalize())
                L.append(f'{lab[0]:<6} & {lab[1]:<11} & {len(ids):,} & {b} & {col(sft)} & {col(fin)} \\\\')
    L += [r'\bottomrule', r'\end{tabular}',
          r'\par\smallskip\parbox{\linewidth}{\footnotesize\itshape\textbf{Note:} The base column is measured where '
          r'every task of the cell was evaluated, marked $\approx$ where at least 10 of its tasks were evaluated, and left as a '
          r'dash otherwise (see Table~\ref{tab:ablation}).}', r'\end{table}', '']
    data['tabE1_cells'] = cells_used
    open(f'{OUT_TAB}/tabE1_cells.tex', 'w').write('\n'.join(L))


def bim_cell(data, g):
    """BIM-Edit mean score of the final model for one task group; BIM-Edit has no chain tasks."""
    rr = data.get('bimedit', {}).get(data['final'])
    if rr is None:
        return r'\pending'
    if g == 'chain':
        return '--'
    sel = [r for r in rr.values() if g == 'all' or r['operation'] == g or r['category'] == g]
    return f3(float(np.mean([float(r['final_score'] or 0) for r in sel]))) if sel else '--'


def outcome_class(r):
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


def tab5_note(used):
    txt = {'committed_rejected': 'Committed, rejected: the model committed an edited file that the checker does not '
                                 'count as completed.',
           'round_limit': 'Round limit: the run used all its tool rounds without a commit.',
           'context_limit': 'Context limit: the conversation exceeded the context length without a commit.',
           'reply_only': 'Reply, no edit: the model ended with a reply and no commit, and the checker does not count '
                         'the task as completed.',
           'other_stop': 'Other stop: the run ended for another reason without a commit.'}
    return ' '.join(txt[k] for k in used)


def cost_rows(data):
    A = data['arms']
    rows = [('ours', A.get((108, 'ours')), OURS_LABEL, ARM_LABEL['lib'])]
    for mid, mlabel, _ in COMMERCIAL:
        for a in ('alone', 'lib'):
            rows.append((mid, A.get((108, mid, a)), mlabel, ARM_LABEL[a]))
    return rows


def write_tab6(data):
    rows = []
    for key, a, label, armlabel in cost_rows(data):
        r = {'label': label, 'arm': armlabel}
        if a:
            secs = data['solo']['secs'] if key == 'ours' and data.get('solo') else a['secs']
            r.update(rounds=a['rounds'], secs=secs, tin=a['tin'] / 1e3, tout=a['tout'] / 1e3,
                     cents=100 * a['usd_task'] if 'usd_task' in a else None,
                     cdone=100 * a['usd_done'] if 'usd_done' in a else None, noprice='usd_task' not in a)
        rows.append(r)
    keys = ['rounds', 'secs', 'tin', 'tout', 'cents', 'cdone']
    best = bold_cols(rows, keys, {k: 'min' for k in keys})
    fm = {'rounds': lambda v: f'{v:.2f}', 'secs': lambda v: f'{v:.1f}', 'tin': lambda v: f'{v:.1f}',
          'tout': lambda v: f'{v:.1f}', 'cents': lambda v: f'{v:.2f}', 'cdone': lambda v: f'{v:.2f}'}
    L = [HEADER_NOTE, r'\begin{table}[htbp]', r'\centering',
         r"\caption{Cost of an edit on the 108-task subset, as means per task. Prices are the providers' list prices, and "
         rf'VeriBIM-9B runs on {WORKSTATION} and has no provider fee per edit. ' + (latency_sentence(data) + ' ' if latency_sentence(data) else '')
         + r'Bold marks the lowest value in each column.}',
         r'\label{tab:cost}', r'\footnotesize', r'\setlength{\tabcolsep}{4pt}',
         r'\begin{tabular}{@{}llcccccc@{}}', r'\toprule',
         r' & & & & \multicolumn{2}{c}{Tokens (thousands)} & \multicolumn{2}{c}{Price (US cents)} \\',
         r'\cmidrule(lr){5-6}\cmidrule(l){7-8}',
         r'Model & Arm & Rounds & Seconds & Input & Output & Per task & Per completed edit \\', r'\midrule']
    prev = None
    for i, r in enumerate(rows):
        if i == 1:
            L.append(r'\midrule')
        label = r['label'] if r['label'] != prev else ''
        prev = r['label']
        L.append(' & '.join([label, r['arm']] + ['--' if r.get('noprice') and k in ('cents', 'cdone')
                                                 else cell(r.get(k), k, best, fm[k]) for k in keys]) + r' \\')
    L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
    open(f'{OUT_TAB}/tab6_cost.tex', 'w').write('\n'.join(L))


# ---------------------------------------------------------------- macros
def existing_macro_names():
    if not MACROS_V10 or not os.path.exists(MACROS_V10):
        return set()
    src = open(MACROS_V10).read()
    INPUTS.append((MACROS_V10, 0))
    return set(re.findall(r'\\(?:newcommand|renewcommand|providecommand|def)\s*\{?\\([A-Za-z]+)', src))


def txt4(x, four):
    if four:
        return f'{x:.4f}' if x >= 0 else f'$-${abs(x):.4f}'
    return txt_signed(x)


def needs_four(lo, hi):
    return any(x != 0 and f'{abs(x):.3f}' == '0.000' for x in (lo, hi))


ARM_SUFFIXES = (['Comp', 'CompLo', 'CompHi', 'Done'] + [f'Comp{VTOK[g]}' for g in VERS + ORIGS] +
                ['Mean', 'Rounds', 'Secs'])


def write_macros(data):
    taken = existing_macro_names()
    M, P = [], []          # defined macros; pending placeholders (\providecommand)

    def put(name, value, comment):
        assert re.fullmatch(r'Res[A-Za-z]+', name), name
        assert name not in taken, f'{name} already defined in macros_v10.tex'
        assert name not in [m[0] for m in M], f'duplicate {name}'
        M.append((name, value, comment))

    def pend(name, comment):
        assert re.fullmatch(r'Res[A-Za-z]+', name), name
        assert name not in taken, f'{name} already defined in macros_v10.tex'
        if name in [m[0] for m in M] or name in [p[0] for p in P]:
            return
        P.append((name, comment))

    A, D, O = data['arms'], data['deltas'], data['offtarget']
    arm_specs = []
    for n in (108, 324):
        arm_specs.append(((n, 'ours'), f'{SET_TOK[n]}Ours'))
        for a in (('alone', 'libnote') if n in BASE_SETS else ()):
            arm_specs.append(((n, 'base', a), f'{SET_TOK[n]}Base{ARM_TOK[a]}'))
        for name, tok in ((SFT, 'Sft'), (PREV, 'Prev')):
            for a in ('lib', 'alone'):
                if A.get((n, name, a)) or (name == SFT and n == 324):
                    arm_specs.append(((n, name, a), f'{SET_TOK[n]}{tok}{ARM_TOK[a]}'))
        for mid, _, tok in COMMERCIAL:
            if n == 108 or mid == 'claude-sonnet-5-5':
                for a in ('alone', 'lib'):
                    arm_specs.append(((n, mid, a), f'{SET_TOK[n]}{tok}{ARM_TOK[a]}'))
    for k, tok in (('sft', 'Sft'), ('dpo', 'Dpo'), ('grpo', 'Grpo'), ('prev', 'Prev'), ('ours', 'Ours')):
        arm_specs.append(((2100, k), f'{SET_TOK[2100]}{tok}'))
    for key, stem in arm_specs:
        a = A.get(key)
        src = (a or {}).get('source', 'pending')
        if a is None:
            for suf in ARM_SUFFIXES + (['Failed'] + [f'Comp{GTOK[g]}' for g in OPS + CATS + ['chain']]
                                       if key[0] == 2100 else []):
                pend(f'Res{stem}{suf}', f'PENDING read {key}')
            continue
        put(f'Res{stem}Comp', f3(a['comp'][0]), f"completion {a['done']}/{a['n']}; {src}")
        put(f'Res{stem}CompLo', f3(a['comp'][1]), '95 % bootstrap lower bound of completion')
        put(f'Res{stem}CompHi', f3(a['comp'][2]), '95 % bootstrap upper bound of completion')
        put(f'Res{stem}Done', f"{a['done']:,}", 'completed tasks')
        for g in VERS + ORIGS:
            put(f'Res{stem}Comp{VTOK[g]}', f3(a[g][0]), f'completion on {g} ({a[g][3]} tasks)')
        put(f'Res{stem}Mean', f3(a['mean']), 'mean score')
        put(f'Res{stem}Rounds', f'{a["rounds"]:.2f}', 'mean tool rounds per task')
        put(f'Res{stem}Secs', f'{a["secs"]:.1f}', 'mean wall-clock seconds per task')
        put(f'Res{stem}TokensIn', f'{a["tin"] / 1e3:.1f}', 'mean input tokens per task, thousands (per-task rows)')
        put(f'Res{stem}TokensOut', f'{a["tout"] / 1e3:.1f}', 'mean output tokens per task, thousands (per-task rows)')
        if 'usd_task' in a:
            put(f'Res{stem}CentsTask', f'{100 * a["usd_task"]:.2f}', 'US cents per task at list price (hosted_cost.py formula)')
            put(f'Res{stem}CentsDone', f'{100 * a["usd_done"]:.2f}', 'US cents per completed edit at list price')
        if key[0] == 2100:
            put(f'Res{stem}Failed', f"{a['n'] - a['done']:,}", f"tasks not completed ({a['n']} minus Done)")
            for cellkey, (m, k, nn) in a['cells'].items():
                v, o = cellkey.split('|')
                if v == 'IFC4':          # the only version that holds both origins
                    put(f'Res{stem}Comp{VTOK[v]}{VTOK[o]}', f3(m), f'completion on {v} {o} tasks, {k}/{nn}')
            for g in OPS + CATS + ['chain']:
                m, k, nn = a['groups'][g]
                what = "chains of dependent edits (tier 'compositional')" if g == 'chain' else f'{g} tasks'
                put(f'Res{stem}Comp{GTOK[g]}', f3(m), f'completion on {what}, {k}/{nn}')
    # paired differences
    toks = {'base': 'Base', SFT: 'Sft', PREV: 'Prev', 'sft': 'Sft', 'dpo': 'Dpo', 'grpo': 'Grpo', 'prev': 'Prev', 'ours': 'Ours'}
    toks.update({mid: tok for mid, _, tok in COMMERCIAL})
    expected_deltas = []
    for n in (108, 324):
        models = COMMERCIAL if n == 108 else [c for c in COMMERCIAL if c[0] == 'claude-sonnet-5-5']
        for mid, _, _ in models:
            for a in ('alone', 'lib'):
                expected_deltas.append((n, 'ours', mid, a))
        for a in (('alone', 'libnote') if n in BASE_SETS else ()):
            expected_deltas.append((n, 'ours', 'base', a))
    expected_deltas += [(2100, 'ours', 'sft')] + ([(2100, 'ours', 'dpo')] if data['final_is_grpo'] else [])
    expected_deltas += [(2100, 'dpo', 'sft'), (2100, 'grpo', 'dpo'), (2100, 'dpo', 'prev'), (2100, 'sft', 'base'),
                        (2100, 'dpo', 'base')]
    for key in expected_deltas + [k for k in D if k not in expected_deltas]:
        d = D.get(key)
        est = key[0] == 2100 and key[2] == 'base'
        if key[0] in (108, 324):
            stem = f'{SET_TOK[key[0]]}OursMinus{toks[key[2]]}{ARM_TOK.get(key[3], key[3])}'
            wl = (f'{SET_TOK[key[0]]}OursWins{toks[key[2]]}{ARM_TOK.get(key[3], key[3])}',
                  f'{SET_TOK[key[0]]}OursLosses{toks[key[2]]}{ARM_TOK.get(key[3], key[3])}')
        else:
            stem = f'BenchDelta{toks[key[1]]}Over{toks[key[2]]}'
            wl = (f'Bench{toks[key[1]]}Over{toks[key[2]]}Wins', f'Bench{toks[key[1]]}Over{toks[key[2]]}Losses')
        groups = ['ALL'] + ([] if est else VERS + ORIGS)
        if d is None:
            for g in groups:
                gt = '' if g == 'ALL' else VTOK[g]
                for suf in ('', 'Lo', 'Hi'):
                    pend(f'Res{stem}{gt}{suf}', f'PENDING paired difference {key}')
            if not est:
                pend(f'Res{wl[0]}', f'PENDING discordant count {key}')
                pend(f'Res{wl[1]}', f'PENDING discordant count {key}')
            continue
        for g in groups:
            if g not in d:
                continue
            gt = '' if g == 'ALL' else VTOK[g]
            m, lo, hi = d[g]
            four = needs_four(lo, hi)
            tag = ('ESTIMATE (base row estimated, difference estimator over the measured tasks, stratified by version); '
                   if est else '')
            put(f'Res{stem}{gt}', txt_signed(m), f'{tag}paired difference in completion, {g}')
            put(f'Res{stem}{gt}Lo', txt4(lo, four), '95 % bootstrap lower bound' + (' (four decimals: 0.000 at three)' if four else ''))
            put(f'Res{stem}{gt}Hi', txt4(hi, four), '95 % bootstrap upper bound' + (' (four decimals)' if four else ''))
        if 'wins' in d:
            put(f'Res{wl[0]}', f"{d['wins']:,}", f'tasks that {key[1]} completes and {" ".join(map(str, key[2:]))} fails')
            put(f'Res{wl[1]}', f"{d['losses']:,}", f'tasks that {" ".join(map(str, key[2:]))} completes and {key[1]} fails')
    for (k0, *rest), v in O.items():
        stem = (f'HundredEight{toks[rest[0]]}{ARM_TOK[rest[1]]}' if k0 == 108 else f'Bench{toks[rest[0]]}')
        put(f'Res{stem}OffNet', f'{v[0]:,}', 'off-target changes, net count, over tasks with an edited model')
        put(f'Res{stem}OffNetTasks', f'{v[1]:,}', 'tasks with at least one net off-target change')
        put(f'Res{stem}OffEvaluated', f'{v[2]:,}', 'tasks with an edited model (off-target evaluated)')
    for k, (tot, ntask, ndone) in data['offdone'].items():
        put(f'ResBench{toks[k]}OffCompletedTasks', f'{tot:,}',
            f'net off-target changes summed over the {ndone:,} completed tasks with an edited model')
        put(f'ResBench{toks[k]}OffCompletedTaskCount', f'{ntask:,}', 'completed tasks with at least one net off-target change')
    for k in ('dpo', 'grpo'):
        if k not in data['offdone']:
            pend(f'ResBench{toks[k]}OffCompletedTasks', 'PENDING off-target per-task file')
    # untrained base on the 2,100-task benchmark: estimate
    be = data.get('base_est')
    pend('ResBenchBaseNoteComp', 'SUPERSEDED: the base row is an estimate; use ResBenchBaseNoteCompEst and say so')
    if be is None:
        for suf in ('CompEst', 'CompEstLo', 'CompEstHi', 'CompTwoXThree', 'ReadTasks', 'Mean', 'Rounds', 'OffTarget'):
            pend(f'ResBenchBaseNote{suf}', 'PENDING base read')
    else:
        p2 = be['per']['IFC2X3']
        if be['est'] is None:
            for suf in ('CompEst', 'CompEstLo', 'CompEstHi'):
                pend(f'ResBenchBaseNote{suf}', 'PENDING: IFC4X3 needs the 108-task read with the library note')
        else:
            e = be['est']
            put('ResBenchBaseNoteCompEst', f3(e[0]), 'ESTIMATE, mean of the three per-version rates (700 tasks each): '
                + ', '.join(f"{v} {be['per'][v]['done']}/{be['per'][v]['n']}" for v in VERS))
            put('ResBenchBaseNoteCompEstLo', f3(e[1]), '95 % interval: per-version Wilson bounds combined by the MOVER rule')
            put('ResBenchBaseNoteCompEstHi', f3(e[2]), f"upper bound; stratified bootstrap {f3(be['est_boot'][1])}-{f3(be['est_boot'][2])} (cross-check, degenerate on 0/n versions)")
        if p2 and p2['measured_all']:
            put('ResBenchBaseNoteCompTwoXThree', f3(p2['rate']), f"MEASURED on all {p2['n']} IFC2X3 tasks, {p2['done']} completed")
        else:
            pend('ResBenchBaseNoteCompTwoXThree', 'PENDING: IFC2X3 part not fully read')
        for v in ('IFC4', 'IFC4X3'):
            pv = be['per'][v]
            if pv is None:
                pend(f'ResBenchBaseNoteComp{VTOK[v]}Est', f'PENDING: no measured {v} task yet')
            else:
                put(f'ResBenchBaseNoteComp{VTOK[v]}Est', f3(pv['rate']),
                    f"ESTIMATE for the {pv['of']} {v} tasks from {pv['done']}/{pv['n']} measured")
                put(f'ResBenchBaseNoteRead{VTOK[v]}', f"{pv['n']:,}", f'measured {v} tasks behind the estimate')
        for o in ORIGS:
            x = be['origin'][o]
            if x is None:
                pend(f'ResBenchBaseNoteComp{VTOK[o]}Est', 'PENDING stratum without a measured task')
            else:
                put(f'ResBenchBaseNoteComp{VTOK[o]}Est', f3(x), f'ESTIMATE, post-stratified by version x origin')
        put('ResBenchBaseNoteReadTasks', f"{be['n_read']:,}", 'tasks finished by the stopped 2,100-task read')
        put('ResBenchBaseNoteDoneRead', f"{be['done_read']:,}", 'completed among the read tasks (checker rule)')
        put('ResBenchBaseNoteMean', f3(be['mean']), f"mean score over the {be['n_read']} read tasks")
        put('ResBenchBaseNoteRounds', f"{be['rounds']:.2f}", f"mean tool rounds over the {be['n_read']} read tasks")
        put('ResBenchBaseNoteSecs', f"{be['secs']:.1f}", f"mean wall-clock seconds over the {be['n_read']} read tasks (contended read)")
        if be.get('off'):
            put('ResBenchBaseNoteOffTarget', f"{be['off'][0]:,}", f"net off-target changes over the {be['off'][2]} read tasks with an edited model")
            put('ResBenchBaseNoteOffEvaluated', f"{be['off'][2]:,}", 'read tasks with an edited model')
        else:
            pend('ResBenchBaseNoteOffTarget', 'PENDING base off-target summary')
        for k, dd in be.get('gain2x3', {}).items():
            four = needs_four(dd[1], dd[2])
            put(f'ResBenchDelta{toks[k]}OverBaseTwoXThree', txt_signed(dd[0]), 'MEASURED paired difference on the 700 IFC2X3 tasks')
            put(f'ResBenchDelta{toks[k]}OverBaseTwoXThreeLo', txt4(dd[1], four), '95 % bootstrap lower bound')
            put(f'ResBenchDelta{toks[k]}OverBaseTwoXThreeHi', txt4(dd[2], four), '95 % bootstrap upper bound')
    # best commercial arm per subset (for the text)
    for a in ('alone', 'lib'):
        c = [(A[(108, mid, a)]['comp'][0], label) for mid, label, _ in COMMERCIAL if A.get((108, mid, a))]
        if c:
            v, label = max(c)
            put(f'ResHundredEightBestCommercial{ARM_TOK[a]}Comp', f3(v), f'best commercial model {a}')
            put(f'ResHundredEightBestCommercial{ARM_TOK[a]}Name', label, f'its name')
    # latency of the local model: dedicated 108-task read (several tasks in flight) and the one-at-a-time read
    sp = data.get('inflight_split')
    if sp:
        put('ResHundredEightOursToolSecs', f"{sp['tool']:.1f}", f"mean tool seconds per task, in-flight read (transcript rounds; {sp['n']} tasks)")
        put('ResHundredEightOursModelSecs', f"{sp['model']:.1f}", 'mean remaining seconds per task (generation and sandbox start), in-flight read')
    else:
        pend('ResHundredEightOursToolSecs', 'PENDING transcripts of the dedicated 108-task read')
        pend('ResHundredEightOursModelSecs', 'PENDING transcripts of the dedicated 108-task read')
    if data.get('inflight'):
        put('ResHundredEightOursInFlight', str(data['inflight']), 'tasks in flight in the dedicated 108-task read (log first line)')
    so = data.get('solo')
    if so:
        put('ResHundredEightOursSoloSecs', f"{so['secs']:.1f}", f"mean seconds per task, one task at a time (local108_lib_solo, {data['final']})")
        put('ResHundredEightOursSoloRounds', f"{so['rounds']:.2f}", 'mean tool rounds per task, one-at-a-time read')
        put('ResHundredEightOursSoloComp', f3(so['comp']), f"completion of the one-at-a-time read, {so['done']}/108")
        if so['split']:
            put('ResHundredEightOursSoloToolSecs', f"{so['split']['tool']:.1f}", 'mean tool seconds per task, one-at-a-time read (transcript rounds)')
            put('ResHundredEightOursSoloModelSecs', f"{so['split']['model']:.1f}", 'mean remaining seconds per task (generation and sandbox start), one-at-a-time read')
        else:
            pend('ResHundredEightOursSoloToolSecs', 'PENDING transcripts of local108_lib_solo')
            pend('ResHundredEightOursSoloModelSecs', 'PENDING transcripts of local108_lib_solo')
    else:
        for nm in ('ResHundredEightOursSoloSecs', 'ResHundredEightOursSoloToolSecs', 'ResHundredEightOursSoloModelSecs'):
            pend(nm, f"PENDING runs_local/bench_v4/results/local108_lib_solo/per_task_{data['final']}.jsonl and its transcripts")
    # snapshot selection
    put('ResFinalStage', 'reinforcement' if data.get('final_is_grpo') else 'preference',
        f"stage of the final model {data['final']} (results/FINAL_ARTIFACT)")
    put('ResFinalSnapshotStep', snap_step(data['final']), f"training step of the final model {data['final']}")
    put('ResChosenSnapshotStep', re.sub(r'\D', '', data['chosen'].split('_c')[-1]) if '_c' in data['chosen'] else r'\pending',
        f"preference-stage snapshot {data['chosen']}" + (' (PROVISIONAL)' if data.get('chosen_provisional') else ''))
    v5 = {k: v for k, v in data['val500'].items() if k == SFT or re.fullmatch(r'dpo_v10(_c\d+)?', k)}
    if v5:
        lo_k, hi_k = min(v5, key=lambda k: v5[k][0]), max(v5, key=lambda k: v5[k][0])
        put('ResValLargeSnapMin', f3(v5[lo_k][0]), f'lowest val-500 completion over {SFT} and the {len(v5) - 1} dpo_v10 checkpoints ({lo_k})')
        put('ResValLargeSnapMax', f3(v5[hi_k][0]), f'highest ({hi_k}); {os.path.relpath(VAL500, ROOT)}')
    else:
        pend('ResValLargeSnapMin', 'PENDING val-500 curve'); pend('ResValLargeSnapMax', 'PENDING val-500 curve')
    # ---- rewritten-wording validation set (val-100 v3b): completion (all three axes >= 0.9), mean of 'final'
    vs_, vmiss_, vsrc_ = data.get('v100b', {}), data.get('v100b_missing', {}), os.path.relpath(V100B, ROOT)
    if data.get('v100b_n'):
        put('ResValSmallN', f"{data['v100b_n']:,}", f'tasks of the rewritten-wording validation set ({os.path.relpath(V100B_SUBSET, ROOT)})')
    else:
        pend('ResValSmallN', f'PENDING {os.path.relpath(V100B_SUBSET, ROOT)}')
    for name, stem, note in ((data['final'], 'Ours', 'final model'), (SFT, 'Sft', 'imitation model'),
                             (data['chosen'], 'Dpo', 'preference-stage snapshot')):
        v_ = vs_.get(name)
        if v_ is None:
            for suf in ('Comp', 'Mean', 'Done'):
                pend(f'ResValSmall{stem}{suf}', f'PENDING {vsrc_}/per_task_{name}.jsonl ({vmiss_.get(name, "not read")})')
            continue
        put(f'ResValSmall{stem}Comp', f3(v_['comp']), f"{note} ({name}) on the rewritten-wording validation set, "
            f"completion {v_['done']}/{v_['n']}; {vsrc_}/per_task_{name}.jsonl")
        put(f'ResValSmall{stem}Mean', f3(v_['mean']), f"mean score (per-task 'final'), {v_['n']} tasks")
        put(f'ResValSmall{stem}Done', f"{v_['done']:,}", 'completed tasks')
    vb = data.get('valhard_build')
    if vb:
        put('ResValHardN', f"{vb['val_hard_size']:,}", 'hard validation set size (val_hard_build_report.json)')
        put('ResValHardFailedSampleTasks', f"{vb['tasks_with_a_failed_sample']:,}", 'tasks with at least one failed sample')
        put('ResValHardFilledTasks', f"{vb['filled_with_lowest_scoring_completed']:,}", 'filled with the lowest-scoring completed tasks')
        put('ResValHardCandidates', f"{vb['candidates']:,}", 'candidate tasks')
        put('ResValHardSamplesPerTask', f"{vb['k']}", 'samples per candidate task')
    else:
        pend('ResValHardN', 'PENDING build report')
    c = data['curve']
    if not c['provisional'] and c['baseline']:
        put('ResValHardSftComp', f3(c['baseline'][0]), f'{SFT} on the hard validation set ({os.path.basename(c["path"])})')
    else:
        pend('ResValHardSftComp', f'PENDING {os.path.relpath(VALHARD, ROOT)}')
    pts = {s[1]: s for s in c['snaps']}
    if not c['provisional'] and data['chosen'] in pts:
        put('ResValHardChosenComp', f3(pts[data['chosen']][2]), f"{data['chosen']} on the hard validation set")
    else:
        pend('ResValHardChosenComp', f'PENDING {os.path.relpath(VALHARD, ROOT)}')
    # ---- hard validation set, preference stage (draft's local names included)
    if vb:
        put('ResValHardFailedTasks', f"{vb['tasks_with_a_failed_sample']:,}", 'same as ResValHardFailedSampleTasks (name used by Section 5)')
    dsn = [x for x in c['snaps']] if not c['provisional'] else []
    if dsn:
        put('ResValHardLastStep', str(dsn[-1][0]), f'last preference-stage snapshot ({dsn[-1][1]})')
        put('ResValHardLastComp', f3(dsn[-1][2]), f'{dsn[-1][1]} on the hard validation set')
        if len(dsn) > 1:
            put('ResValHardPenultStep', str(dsn[-2][0]), f'snapshot before the last one ({dsn[-2][1]})')
        put('ResValHardDpoMin', f3(min(x[2] for x in dsn)), 'lowest preference snapshot on the hard set')
        put('ResValHardDpoMax', f3(max(x[2] for x in dsn)), 'highest preference snapshot on the hard set')
    else:
        for nm in ('ResValHardLastStep', 'ResValHardLastComp', 'ResValHardPenultStep'):
            pend(nm, 'PENDING hard-set curve')
    vh = data.get('vh_deltas', {})

    def vh_put(stem, d_, what):
        m_, lo_, hi_ = d_['ALL']
        four = needs_four(lo_, hi_)
        put(f'Res{stem}', txt4(m_, True), f'paired difference in hard-set completion, {what} (four decimals: 1 task = 0.0033)')
        put(f'Res{stem}Lo', txt4(lo_, True), '95 % bootstrap lower bound, 300 tasks')
        put(f'Res{stem}Hi', txt4(hi_, True), '95 % bootstrap upper bound')
        put(f'Res{stem}Wins', f"{d_['wins']}", 'tasks the first model completes and the second fails')
        put(f'Res{stem}Losses', f"{d_['losses']}", 'tasks the second model completes and the first fails')
    if (data['chosen'], SFT) in vh:
        vh_put('ValHardDpoDelta', vh[(data['chosen'], SFT)], f"{data['chosen']} minus {SFT}")
    else:
        pend('ResValHardDpoDelta', 'PENDING hard-set per-task rows')
    # ---- hard validation set, reinforcement stage (not adopted)
    gc = data.get('grpo_curve')
    if gc and gc['snaps']:
        g = gc['snaps']
        pk = max(g, key=lambda x: (x[2], x[3], x[0]))   # completion, then mean, then the later step (the pre-written rule)
        if gc['peak'] and gc['peak'] in [x[1] for x in g] and gc['peak'] != pk[1]:
            WARN.append(f"{os.path.basename(gc['source'])}: PEAK {gc['peak']} differs from the highest snapshot {pk[1]}; the PEAK line is used")
            pk = [x for x in g if x[1] == gc['peak']][0]
        put('ResValHardGrpoName', data['grpo_name'].replace('_', r'\_'), 'reinforcement snapshot of Table 4 (final model or PEAK_GRPO_V10)')
        if data.get('final_is_grpo'):
            fx = [x for x in g if x[1] == data['final']]
            if fx:
                put('ResValHardFinalComp', f3(fx[0][2]), f"final model {data['final']} on the hard set (step {fx[0][0]})")
        if gc['start']:
            put('ResValHardGrpoStartComp', f3(gc['start'][0]), f"start of the reinforcement stage ({data['chosen']}) on the hard set")
        put('ResValHardGrpoFirstStep', str(g[0][0]), f'first reinforcement snapshot ({g[0][1]})')
        put('ResValHardGrpoFirstComp', f3(g[0][2]), f'{g[0][1]} on the hard set')
        put('ResValHardGrpoPeakStep', str(pk[0]), f'reinforcement snapshot with the highest hard-set completion ({pk[1]})')
        put('ResValHardGrpoPeakComp', f3(pk[2]), f'{pk[1]} on the hard set')
        put('ResValHardGrpoLastStep', str(g[-1][0]), f'last reinforcement snapshot ({g[-1][1]})')
        put('ResValHardGrpoLastComp', f3(g[-1][2]), f'{g[-1][1]} on the hard set')
        put('ResValHardGrpoMin', f3(min(x[2] for x in g)), 'lowest reinforcement snapshot on the hard set')
        put('ResValHardGrpoMax', f3(max(x[2] for x in g)), 'highest reinforcement snapshot on the hard set')
    else:
        pend('ResValHardGrpoPeakComp', 'PENDING reinforcement hard-set curve')
    if (data['grpo_name'], data['chosen']) in vh:
        vh_put('ValHardGrpoDelta', vh[(data['grpo_name'], data['chosen'])], f"{data['grpo_name']} minus {data['chosen']}")
    else:
        pend('ResValHardGrpoDelta', 'PENDING reinforcement hard-set per-task rows')
    # ---- stop counts over the 2,100 tasks: \ResBenchOursFail... = Table 5 "All tasks" row of the final model;
    # \ResBenchDpoFail... = the preference-stage snapshot's own per-task rows, same rule (outcome_class)
    t5 = data.get('tab5', {}).get('all')
    ds = data.get('dpo_stop')
    for nm, k in (('Committed', 'committed_rejected'), ('Rounds', 'round_limit'), ('Context', 'context_limit'),
                  ('Reply', 'reply_only')):
        if ds is not None:
            put(f'ResBenchDpoFail{nm}', f"{ds[1].get(k, 0):,}", f'{k} over the 2,100 tasks, preference-stage snapshot '
                f'({ds[0]}), full_all/per_task_{ds[0]}.jsonl, Table 5 rule')
        else:
            pend(f'ResBenchDpoFail{nm}', 'PENDING full_all per-task rows of the preference-stage snapshot')
        if t5:
            put(f'ResBenchOursFail{nm}', f"{t5.get(k, 0):,}", f'Table 5 "All tasks" row, {k} (final model {data["final"]})')
    # ---- preference pool (runs_local/stage_b_v10/pairs_trajectory_report.json)
    pool = data.get('pool')
    if pool:
        put('ResPoolTasks', f"{pool['tasks']:,}", 'tasks of the preference pool (= \\StageBPool)')
        put('ResPoolNoRejected', f"{pool['tasks_without_a_rejected']:,}", 'tasks with no attempt usable as the rejected side')
        put('ResPoolNoChosen', f"{pool['tasks_without_a_chosen']:,}", 'tasks with no attempt usable as the chosen side')
        put('ResPoolWithPairs', f"{pool['tasks_with_pairs']:,}", 'tasks that gave a trajectory pair')
        put('ResPoolTrajectoryPairs', f"{pool['pairs']:,}", 'trajectory pairs before exclusions')
    else:
        for nm in ('ResPoolNoRejected', 'ResPoolNoChosen', 'ResPoolWithPairs'):
            pend(nm, f'PENDING {os.path.relpath(POOL_REPORT, ROOT)}')
    # ---- library gain of the commercial models on the 108-task subset (Discussion)
    gains = [(100 * (A[(108, mid, 'lib')]['comp'][0] - A[(108, mid, 'alone')]['comp'][0]), lab)
             for mid, lab, _ in COMMERCIAL if A.get((108, mid, 'lib')) and A.get((108, mid, 'alone'))]
    if gains:
        lo_g, hi_g = min(gains), max(gains)
        put('ResLibGainMinPts', f'{lo_g[0]:.0f}', f'smallest library gain in completion points ({lo_g[1]}, {lo_g[0]:.1f})')
        put('ResLibGainMaxPts', f'{hi_g[0]:.0f}', f'largest library gain in completion points ({hi_g[1]}, {hi_g[0]:.1f})')
    # ---- library x training interaction (108-task subset)
    dd = data.get('did')
    if dd:
        for nm, sfx, what in (('comp', '', 'completion'), ('mean', 'Mean', 'mean score')):
            m_, lo_, hi_ = dd[nm]
            put(f'ResHundredEightLibTrainDiD{sfx}', txt_signed(m_), f'paired difference-in-differences in {what}: '
                f'(imitation with library - imitation alone) - (base with note - base alone), per task, 108 tasks')
            put(f'ResHundredEightLibTrainDiD{sfx}Lo', txt_signed(lo_), '95 % bootstrap lower bound (10,000 resamples of tasks)')
            put(f'ResHundredEightLibTrainDiD{sfx}Hi', txt_signed(hi_), '95 % bootstrap upper bound')
    else:
        for suf in ('', 'Lo', 'Hi'):
            pend(f'ResHundredEightLibTrainDiD{suf}', 'PENDING the four 108-task reads')
    # ---- data separation (Appendix F); same meaning as the \Sep... and \Verbatim... macros of macros_v10.tex
    sp_ = data.get('separation')
    if sp_:
        cellkeys = [('IFC2X3|native', 'TwoXThreeNative'), ('IFC4|native', 'FourNative'), ('IFC4|migrated', 'FourMigrated'),
                    ('IFC4X3|native', 'FourXThreeNative'), ('IFC4X3|migrated', 'FourXThreeMigrated')]
        for k, tok, what in (('train', 'Train', 'training file tasks_stage_b_v10.jsonl'),
                             ('val500', 'Val', 'decision set val_tasks_500_v3b.jsonl (val-100 v3b is a subset)'),
                             ('bench', 'Bench', 'benchmark tasks.v4c.jsonl')):
            for ck, ct in cellkeys:
                put(f'ResSep{tok}{ct}', f"{sp_['cells'][k].get(ck, 0):,}", f'distinct buildings, {ck}, {what}')
            put(f'ResSep{tok}Total', f"{sp_['distinct'][k]:,}", f'distinct buildings, {what}')
            put(f'ResSep{tok}Tasks', f"{sp_['rows'][k]:,}", f'instructions (rows), {what}')
        for ck, tok in (('train|val500', 'TrainVal'), ('train|bench', 'TrainBench'), ('val500|bench', 'ValBench')):
            put(f'ResSepOverlap{tok}', f"{sp_['overlap'][ck]:,}", 'buildings shared by the two files')
        WORDS = ['zero', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine']
        vb = sp_['verbatim']['bench']
        put('ResVerbatimOverlapBench', f"{vb['n']:,}", f"benchmark instructions whose prompt also occurs verbatim in the training file "
            f"(none on the same building: {vb['same_building']} same-building hits)")
        put('ResVerbatimOverlapClarify', f"{vb['by_kind'].get('clarify', 0):,}", 'of these, clarification prompts that name no target')
        nd = vb['n'] - vb['by_kind'].get('clarify', 0)
        put('ResVerbatimOverlapOther', f'{nd:,}', 'of these, other instructions: ' + ', '.join(f'{k} {v}' for k, v in vb['by_kind'].items() if k != 'clarify'))
        nde = vb['by_kind'].get('delete', 0)
        put('ResVerbatimOverlapDelete', f'{nde:,}', 'of these, deletion instructions (edit kind delete)')
        put('ResVerbatimOverlapDeleteWord', WORDS[nde] if nde < 10 else f'{nde:,}', 'the same in words (\\VerbatimOverlapDelete uses words)')
        for k, tok in (('val500', 'Val'), ('val100', 'ValHundred')):
            v_ = sp_['verbatim'][k]
            put(f'ResVerbatimOverlap{tok}', f"{v_['n']:,}", f"{k} instructions whose prompt also occurs verbatim in the training file "
                f"({', '.join(f'{a} {b}' for a, b in v_['by_kind'].items())})")
    # ---- not derivable from the files in scope
    # flip rate: two identical reads of the final model on the decision set (Section 4.5)
    FLIP_FILE = data['flip_file']
    if os.path.exists(FLIP_FILE):
        fr = json.load(open(FLIP_FILE))
        INPUTS.append((FLIP_FILE, 1))
        put('ResFlipRate', f3(float(fr['flip_rate'])), f"flip rate, {os.path.basename(FLIP_FILE)} (key flip_rate)")
        put('ResFlipRateN', f"{int(fr['n']):,}", 'tasks read twice')
        put('ResFlipRateFlips', f"{int(fr['flips_rep1_vs_rep2']):,}", 'tasks whose verdict differs between the two reads')
        if abs(float(fr['flip_rate']) - int(fr['flips_rep1_vs_rep2']) / int(fr['n'])) > 1e-6:
            WARN.append(f"{FLIP_FILE}: flip_rate {fr['flip_rate']} != flips/n {fr['flips_rep1_vs_rep2']}/{fr['n']}")
    else:
        for nm in ('ResFlipRate', 'ResFlipRateN', 'ResFlipRateFlips'):
            pend(nm, f'PENDING {os.path.relpath(FLIP_FILE, ROOT)}')
    # 324-task base reads are not planned: keep the two names the draft uses, marked for rewriting
    for a in ('alone', 'libnote'):
        pend(f'ResThreeTwentyFourBase{ARM_TOK[a]}Comp', 'NOT PLANNED: the 324-task base reads will not run; rewrite the sentence')
    # ---- BIM-Edit (E1): mean of final_score over the 324 tasks of runs_local/e1/scores_bench_<adapter>.csv
    bm = data.get('bimedit', {})

    def bmean(rr):
        return float(np.mean([float(r['final_score'] or 0) for r in rr.values()]))
    fin = data['final']
    extra = ((data['chosen'], 'Dpo', 'preference-stage snapshot'),) if data.get('final_is_grpo') else ()
    for name, stem, note in ((fin, 'Ours', 'final model'), (PREV, 'Prev', 'earlier corpus'), (SFT, 'Sft', 'imitation')) + extra:
        if name in bm:
            put(f'ResBimEdit{stem}', f3(bmean(bm[name])), f'{note} ({name}) on BIM-Edit, mean final_score over {len(bm[name])} tasks')
        else:
            pend(f'ResBimEdit{stem}', f'PENDING {os.path.relpath(E1, ROOT)}/scores_bench_{name}.csv')
    for other, tok in ((PREV, 'Prev'), (SFT, 'Sft')) + (((data['chosen'], 'Dpo'),) if data.get('final_is_grpo') else ()):
        if fin in bm and other in bm and set(bm[fin]) == set(bm[other]):
            ids_ = sorted(bm[fin])
            dif = [float(bm[fin][t]['final_score'] or 0) - float(bm[other][t]['final_score'] or 0) for t in ids_]
            d_ = boot(dif)
            what = f'paired over the {len(ids_)} BIM-Edit tasks, {fin} minus {other} (mean final_score)'
            put(f'ResBimEditDeltaOver{tok}', txt_signed(d_[0]), f'paired difference in BIM-Edit mean score, {what}')
            put(f'ResBimEditDeltaOver{tok}Lo', txt_signed(d_[1]), '95 % bootstrap lower bound')
            put(f'ResBimEditDeltaOver{tok}Hi', txt_signed(d_[2]), '95 % bootstrap upper bound')
            put(f'ResBimEditDeltaOver{tok}Wins', f'{sum(1 for x in dif if x > 0.05)}', 'tasks where the final model scores more than 0.05 higher')
            put(f'ResBimEditDeltaOver{tok}Losses', f'{sum(1 for x in dif if x < -0.05)}', 'tasks where it scores more than 0.05 lower')
            data.setdefault('bim_deltas', {})[tok] = (d_, len(ids_))
        else:
            for suf in ('', 'Lo', 'Hi'):
                pend(f'ResBimEditDeltaOver{tok}{suf}', f'PENDING {os.path.relpath(E1, ROOT)}/scores_bench_{fin}.csv and _{other}.csv with the same task ids')
    # preference-stage snapshot minus the earlier-corpus chain on BIM-Edit (conventions of \ResBimEditDeltaOverPrev)
    cho = data['chosen']
    if cho in bm and PREV in bm and set(bm[cho]) == set(bm[PREV]):
        ids_ = sorted(bm[cho])
        dif = [float(bm[cho][t]['final_score'] or 0) - float(bm[PREV][t]['final_score'] or 0) for t in ids_]
        d_ = boot(dif)
        what = f'paired over the {len(ids_)} BIM-Edit tasks, {cho} minus {PREV} (mean final_score)'
        put('ResBimEditDeltaDpoOverPrev', txt_signed(d_[0]), f'paired difference in BIM-Edit mean score, {what}')
        put('ResBimEditDeltaDpoOverPrevLo', txt_signed(d_[1]), '95 % bootstrap lower bound')
        put('ResBimEditDeltaDpoOverPrevHi', txt_signed(d_[2]), '95 % bootstrap upper bound')
        put('ResBimEditDeltaDpoOverPrevWins', f'{sum(1 for x in dif if x > 0.05)}', 'tasks where the preference-stage snapshot scores more than 0.05 higher')
        put('ResBimEditDeltaDpoOverPrevLosses', f'{sum(1 for x in dif if x < -0.05)}', 'tasks where it scores more than 0.05 lower')
    else:
        for suf in ('', 'Lo', 'Hi', 'Wins', 'Losses'):
            pend(f'ResBimEditDeltaDpoOverPrev{suf}', f'PENDING {os.path.relpath(E1, ROOT)}/scores_bench_{cho}.csv and _{PREV}.csv with the same task ids')
    put('ResBimEditFrontierLow', f3(BIMEDIT_FRONTIER[0]), 'published BIM-Edit range, lowest of seven re-scored frontier models (gemma4-31B)')
    put('ResBimEditFrontierHigh', f3(BIMEDIT_FRONTIER[1]), 'highest (gemini-flash-3.0), same source')
    # ---- BIM-Edit by task group: mean final_score per operation and per category, full-solve share
    # (final_score >= 0.999), from the same scores_bench_<adapter>.csv reads; empty final_score counts as 0 (bmean rule)
    for name, stem, note in ((fin, 'Ours', 'final model'), (PREV, 'Prev', 'earlier corpus'), (SFT, 'Sft', 'imitation')) + extra:
        src_ = f'{os.path.relpath(E1, ROOT)}/scores_bench_{name}.csv'
        rr = bm.get(name)
        if rr is None:
            for g in OPS + CATS:
                pend(f'ResBimEdit{stem}{GTOK[g]}', f'PENDING {src_}')
            pend(f'ResBimEdit{stem}FullSolve', f'PENDING {src_}')
            continue
        bad = [t for t, r in rr.items() if r.get('operation') not in OPS or r.get('category') not in CATS]
        if bad:
            WARN.append(f'{src_}: {len(bad)} rows with an operation or category outside {OPS} / {CATS}')
        for col, groups in (('operation', OPS), ('category', CATS)):
            for g in groups:
                v = [float(r['final_score'] or 0) for r in rr.values() if r.get(col) == g]
                if v:
                    put(f'ResBimEdit{stem}{GTOK[g]}', f3(float(np.mean(v))),
                        f'{note} ({name}) on BIM-Edit, mean final_score over the {len(v)} {g} tasks')
                else:
                    pend(f'ResBimEdit{stem}{GTOK[g]}', f'PENDING {src_}: no {g} rows')
        fs_ = [float(r['final_score'] or 0) for r in rr.values()]
        nfs = sum(1 for x in fs_ if x >= 0.999)
        put(f'ResBimEdit{stem}FullSolve', f3(nfs / len(fs_)),
            f'{note} ({name}) on BIM-Edit, share of tasks with final_score >= 0.999, {nfs}/{len(fs_)}')
    # task counts per operation, once: from the final model's read; every other read must agree
    cnt_src = next((n_ for n_ in (fin, PREV, SFT) if n_ in bm), None)
    if cnt_src is not None:
        cnt = Counter(r.get('operation') for r in bm[cnt_src].values())
        for n_ in dict.fromkeys((fin, PREV, SFT)):
            if n_ in bm and Counter(r.get('operation') for r in bm[n_].values()) != cnt:
                WARN.append(f'BIM-Edit reads disagree on the task count per operation: {n_} vs {cnt_src}')
        for g in OPS:
            put(f'ResBimEditN{GTOK[g]}', f'{cnt.get(g, 0):,}',
                f'BIM-Edit tasks with operation {g} (scores_bench_{cnt_src}.csv, {sum(cnt.values())} tasks)')
    else:
        for g in OPS:
            pend(f'ResBimEditN{GTOK[g]}', f'PENDING {os.path.relpath(E1, ROOT)}/scores_bench_{fin}.csv')
    # final model on the 2,100-task benchmark: mean score per operation (same rows and operation lookup as
    # \ResBenchOursComp<Op>), the like-for-like counterpart of the BIM-Edit mean per operation
    om = data.get('ours_op_mean') or {}
    for g in OPS:
        if g in om:
            put(f'ResBenchOursMean{GTOK[g]}', f3(om[g][0]),
                f"mean score on {g} tasks, {om[g][1]} tasks; final model {data['final']}")
        else:
            pend(f'ResBenchOursMean{GTOK[g]}', 'PENDING read (2100, ours)')
    data['macros'] = M
    data['macros_pending'] = P
    L = ['% macros_results_v10.tex: every result number the text quotes. GENERATED by',
         '% writing/tables/make_results_exhibits.py; re-run it, never edit by hand. Input after macros_v10.tex.',
         '% Completion: all three score axes >= 0.9. Intervals: paired percentile bootstrap, 10,000 resamples, seed 20260929.',
         r'\makeatletter',
         r'\providecommand{\pending}{{\setlength{\fboxsep}{1pt}\ifdefined\colorlet\fcolorbox{black!45}{black!12}{\vphantom{0}---}\else\fbox{\vphantom{0}---}\fi}}',
         r'\makeatother']
    for name, value, comment in M:
        L.append(f'\\newcommand{{\\{name}}}{{{value}}}  % {comment}')
    L.append('% ---- pending placeholders (\\providecommand; the real definition replaces them once the input exists)')
    for name, comment in P:
        L.append(f'\\providecommand{{\\{name}}}{{\\pending}}  % {comment}')
    open(f'{OUT_TAB}/macros_results_v10.tex', 'w').write('\n'.join(L) + '\n')


# ---------------------------------------------------------------- report
def by_version_all(path):
    if not os.path.exists(path):
        return None
    for line in open(path):
        m = re.match(r'ALL\s+(\d+)\s+completion\s+([0-9.]+)\s+mean\s+([0-9.]+)\s+rounds\s+([0-9.]+)', line)
        if m:
            return int(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4))
    return None


def figure_font_check():
    out = []
    for stem in ('fig08_main/fig08_main_A', 'fig08_main/fig08_main_B', 'fig09_ablation/fig09_ablation',
                 'fig10_curve/fig10_curve', 'fig10_curve/fig10_curve_provisional_val500', 'fig_cost/fig_cost'):
        pdf = f'{OUT_FIG}/{stem}.pdf'
        if not os.path.exists(pdf):
            continue
        try:
            fonts = subprocess.run(['pdffonts', pdf], capture_output=True, text=True).stdout.splitlines()[2:]
            fams = sorted({f.split()[0].split('+')[-1] for f in fonts if f.strip()})
            info = subprocess.run(['pdfinfo', pdf], capture_output=True, text=True).stdout
            cre = re.search(r'Creator:\s*(.*)', info)
            out.append(f'   {stem}.pdf  fonts: {", ".join(fams)}  creator: {cre.group(1).strip() if cre else "?"}  '
                       f'modified {__import__("time").strftime("%Y-%m-%d %H:%M", __import__("time").localtime(os.path.getmtime(pdf)))}')
        except FileNotFoundError:
            out.append('   pdffonts/pdfinfo not available')
            break
    return out


def write_report(data, args):
    A, be = data['arms'], data.get('base_est')
    rel = lambda p: os.path.relpath(p, ROOT)
    L = ['REPORT, result exhibits of the VeriBIM paper (written by make_results_exhibits.py on every run; '
         + ('strict' if args.strict else 'non-strict') + ' run)', '',
         'Re-run:  python '
         'code/tables/make_results_exhibits.py [--strict] [--grpo NAME] [--preview DIR]',
         '--strict exits with status 2 and writes nothing while any input below is pending or provisional.', '',
         '1. INPUTS USED (path, rows; 0 = a source read for constants or a marker file, 1 = a JSON summary)']
    seen = set()
    for p, n in INPUTS:
        if p not in seen:
            seen.add(p)
            L.append(f'   {rel(p):<100} {n}')
    L += ['', '2. PENDING (rendered as \\pending)']
    L += [f'   {p[0]}: {rel(p[1])} ({p[2]})' for p in PENDING] or ['   none']
    L.append('   Optional reads, picked up by name when present (macros only, Tables 3/3b unchanged):')
    for n in (108, 324):
        for name in (SFT, PREV):
            for a in ('lib', 'alone'):
                pth = f'{RES}/local{n}_{a}_all/per_task_{name}.jsonl'
                L.append(f"     {rel(pth):<80} {'present' if os.path.exists(pth) else 'absent'}")
    for name in dict.fromkeys((data['final'], data['chosen'], PREV, SFT)):
        pth = f'{E1}/scores_bench_{name}.csv'
        L.append(f"     {rel(pth):<80} {'present' if os.path.exists(pth) else 'absent'}  (BIM-Edit: task_id, operation, category, final_score)")
    L += ['', '3. PROVISIONAL']
    L += [f'   {p}' for p in PROVISIONAL] or ['   none']
    L += ['', '4. INCONSISTENCIES AND INPUT FACTS (computed from the current files on this run)']
    issues = 0
    for fs in FILESTATS:
        probs = []
        if fs['dup']:
            probs.append(f"{fs['dup']} duplicate task ids")
        if fs['expected'] is not None and (fs['missing'] or fs['extra']):
            probs.append(f"{fs['ids']} ids, {fs['missing']} expected ids missing, {fs['extra']} unexpected")
        if fs['no_axes']:
            probs.append(f"{len(fs['no_axes'])} rows without all three score axes: {', '.join(fs['no_axes'][:5])}")
        if fs['scorer_error']:
            probs.append(f"{len(fs['scorer_error'])} rows with a scorer error: {', '.join(fs['scorer_error'][:6])}")
        if fs['crash_stop']:
            probs.append(f"{fs['crash_stop']} rows stopped by a sandbox crash ({fs['crash_stop_completed']} of them still completed)")
        tag = 'ACCEPTED' if fs['accepted'] else 'NOT ACCEPTED'
        exp = '' if fs['expected'] is None else f"/{fs['expected']}"
        line = f"   {rel(fs['path'])}: {fs['ids']}{exp} ids, {tag}"
        if fs['crash_any'] and not fs['crash_stop']:
            line += f"; {fs['crash_any']} rows met a sandbox crash and recovered"
        if probs:
            issues += 1
            line += '; ' + '; '.join(probs)
        L.append(line)
    # summaries against row counts
    for w in WARN:
        L.append(f'   NOTE {w}')
        issues += 1
    # cross-check with the evaluation pipeline's by_version files
    L.append('   Cross-check against the evaluation pipeline\'s by_version files (ALL line; recount = this script):')
    checks = []
    for n, S_ in ((108, None), (324, None)):
        for mid, _, _ in COMMERCIAL:
            for a in ('alone', 'lib'):
                if A.get((n, mid, a)):
                    checks.append((f'{RES}/hosted{n}_{a}_all/by_version_{mid}.txt', A[(n, mid, a)]))
        if A.get((n, 'ours')):
            checks.append((f'{RES}/local{n}_lib_all/by_version_{data["final"]}.txt', A[(n, 'ours')]))
    for k in ('sft', 'dpo', 'grpo', 'prev'):
        a = A.get((2100, k))
        if a:
            checks.append((f"{RES}/{os.path.dirname(a['source'])}/by_version_{os.path.basename(a['source']).replace('per_task_', '').replace('.jsonl', '')}.txt", a))
    for path, a in checks:
        bv = by_version_all(path)
        if bv is None:
            L.append(f'     {rel(path):<75} no ALL line / file absent')
            continue
        ok = bv[0] == a['n'] and abs(bv[1] - a['comp'][0]) < 5e-4 and abs(bv[2] - a['mean']) < 5e-4
        issues += not ok
        L.append(f"     {rel(path):<75} file {bv[0]} {bv[1]:.3f} mean {bv[2]:.3f}   recount {a['n']} {a['comp'][0]:.3f} "
                 f"mean {a['mean']:.3f}  {'OK' if ok else 'MISMATCH'}")
    if be:
        bv = be.get('by_version_all')
        if bv:
            ok = bv[0] == be['n_read'] and abs(bv[1] - be['done_read'] / be['n_read']) < 5e-4
            issues += not ok
            L.append(f"     {'runs_local/bench_v4/results/full_note_all/by_version_Qwen3.5-9B.txt':<75} file {bv[0]} {bv[1]:.3f}   "
                     f"recount {be['n_read']} {be['done_read'] / be['n_read']:.3f}  {'OK' if ok else 'MISMATCH'}")
        nstop = be['stops'].get('completed', 0)
        L.append(f"   Base read: {be['n_read']} rows; {be['done_read']} completed by the checker rule; stop reasons "
                 f"{be['stops']}; {be['committed']} committed. The {nstop} rows with stop reason 'completed' are runs "
                 f"that ended by themselves, not checker completions.")
    L.append(f'   {issues} line(s) above carry a problem or a note.' if issues else '   no inconsistency found.')
    # base estimate
    L += ['', '5. UNTRAINED BASE ON THE 2,100-TASK BENCHMARK: ESTIMATE']
    if be is None:
        L.append('   pending (no base rows)')
    else:
        for v in VERS:
            pv = be['per'][v]
            if pv is None:
                L.append(f'   {v:<7} no measured task (pending: {rel(RES)}/local108_libnote_all/per_task_{BASE}.jsonl)')
            else:
                L.append(f"   {v:<7} {pv['done']}/{pv['n']} measured of {pv['of']} = {pv['rate']:.4f}   "
                         f"Wilson [{pv['wilson'][0]:.4f}, {pv['wilson'][1]:.4f}]   bootstrap [{pv['boot'][1]:.4f}, {pv['boot'][2]:.4f}]"
                         + ('   (complete part)' if pv['measured_all'] else ''))
        L.append(f"   108-task subset rows counted twice avoided: {be['dup108']} (a subset task already in the stopped read keeps that row)")
        if be['est']:
            e = be['est']
            eb = be['est_boot']
            L.append(f"   pooled estimate = mean of the three rates = {e[0]:.4f}; REPORTED 95 % interval [{e[1]:.4f}, {e[2]:.4f}] = "
                     f"per-version Wilson intervals combined by the MOVER rule. Cross-checks: stratified bootstrap "
                     f"[{eb[1]:.4f}, {eb[2]:.4f}] (degenerate when a version has 0 completions), average of the Wilson bounds "
                     f"[{be['wilson_avg'][0]:.4f}, {be['wilson_avg'][1]:.4f}]")
            for k in ('sft', 'dpo'):
                gg = data['deltas'].get((2100, k, 'base'))
                if gg:
                    L.append(f"   gain of {k} over the base: {gg['ALL'][0]:.4f}, REPORTED [{gg['ALL'][1]:.4f}, {gg['ALL'][2]:.4f}] (MOVER of the "
                             f"trained bootstrap and the base interval); paired stratified bootstrap [{gg['paired_boot'][1]:.4f}, {gg['paired_boot'][2]:.4f}]")
        else:
            L.append('   pooled estimate pending until every version has measured tasks')
        L.append(f"   origin cells (post-stratified): native {be['origin']['native']}, migrated {be['origin']['migrated']}; "
                 f"strata (population, measured rate, measured n): {be['strata']}")
        L.append(f"   measured on the {be['n_read']} read tasks: mean score {be['mean']:.4f}, rounds {be['rounds']:.2f}, "
                 f"seconds {be['secs']:.1f}, off-target net {be.get('off')}")
    # rendered tables
    L += ['', '6. RENDERED TABLES (verbatim rows)']
    for name in ('tab3_main.tex', 'tab3b_324.tex', 'tab4_ablation.tex', 'tab5_failures.tex', 'tab6_cost.tex'):
        L.append(f'--- {name}')
        for line in open(f'{OUT_TAB}/{name}'):
            if '&' in line or 'Note:' in line:
                L.append('   ' + line.rstrip())
    # macros
    L += ['', f"7. MACROS: {len(data['macros'])} defined, {len(data['macros_pending'])} pending placeholders (\\providecommand)"]
    fam = {}
    for name, comment in data['macros_pending']:
        if comment.startswith(('PENDING read', 'PENDING paired difference', 'PENDING discordant')):
            fam.setdefault(comment, []).append(name)
        else:
            L.append(f'   \\{name:<48} {comment}')
    for comment, names in fam.items():
        L.append(f'   {len(names):>3} placeholders, {comment}: \\{names[0]} ...')
    L += ['', '8. CHOICES TO CONFIRM (stated once)',
          '   - Bold (Tables 3, 3b, 4): highest completion and mean score per column, all rows; rounds and off-target unbolded.',
          '   - Table 4 untrained row: an estimate. IFC2X3 is measured on all 700 tasks; IFC4 pools the stopped read with the',
          '     108-task subset; IFC4X3 comes from the subset alone. It takes part in the bold rule.',
          '   - Base interval: per-version Wilson intervals combined by the MOVER rule (the stratified bootstrap collapses to',
          '     [0, 0] on a 0/36 version). Gain over the base: trained rate minus the estimate, MOVER of both intervals.',
          '   - Intervals whose nonzero bound prints as 0.000 at three decimals are printed with four (both bounds).',
          '   - Table 5: outcome classes from per-task rows only (committed flag, stop reason, checker rule); a task counts',
          '     once. Chains = tier "compositional" (367 tasks, the CHN family, the same set as the scope.chain family tag).',
          '   - Model time / tool time of the local model: the per-task rows carry only duration_seconds, so the split',
          '     is not derivable from them; ResHundredEightOursModelSecs / ToolSecs stay pending unless the dedicated read',
          '     writes one of the timing field pairs ' + ', '.join('/'.join(k) for k in TIMING_KEYS) + '.',
          '   - Labels: "VeriBIM-9B" for the final local model in every table and figure; no "hosted", no coined labels.',
          '   - Final model = CHOSEN_DPO_V10. Reinforcement row = PEAK_GRPO_V10 (default of --grpo), labelled "(not adopted)"; the',
          '     Table 4 note says the final model is the preference-stage snapshot. Bold stays mechanical, so the reinforcement',
          '     row can carry bold where it is highest.',
          '   - Fig. 10: two panels on one y axis (0.02 grid, wide band); (a) preference steps from the imitation model at 0,',
          '     (b) reinforcement steps from the chosen snapshot at 0. Hard-set paired deltas recomputed from per-task rows.',
          '   - Table E.1 is written to tabE1_cells.tex (the appendix skeleton has no macro names): swap the \\input.',
          '', '9. FIGURES (fonts and creator from pdffonts/pdfinfo)'] + figure_font_check()
    open(f'{OUT_TAB}/REPORT.txt', 'w').write('\n'.join(L) + '\n')


if __name__ == '__main__':
    main()
