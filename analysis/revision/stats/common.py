"""Shared loaders and bootstrap helpers for the 2026-10-07 revision statistics (read-only on every input).

Conventions are those of writing/tables/make_results_exhibits.py, imported unchanged (done(), boot(), SEED, R):
completion = geometry, semantics and topology all >= 0.9; task-level interval = percentile bootstrap over tasks,
10,000 resamples, seed 20260929, lower = sorted[250], upper = sorted[9749]. The building-level cluster bootstrap
uses the same seed, resample count and index rule, resampling buildings with replacement and pooling all tasks of
every drawn building (ratio of summed completions to summed task counts).
"""
import json, os, re, sys
sys.dont_write_bytecode = True
import numpy as np

ROOT = '.'
sys.path.insert(0, f'{ROOT}/writing/tables')
import make_results_exhibits as ex          # noqa: E402  (module import has no side effects; main() is guarded)

BENCH = f'{ROOT}/runs_local/bench_v4'
RES = f'{BENCH}/results'
OUT = f'{ROOT}/analysis/revision/stats'
SEED, R = ex.SEED, ex.R
VERS, ORIGS = ex.VERS, ex.ORIGS
done = ex.done
boot = ex.boot
FINAL, SFT, DPO, PREV, BASE = 'grpo_v10b_c10', 'sft_v10', 'dpo_v10_c6', 'dpo_v9_c10', 'Qwen3.5-9B'
COMMERCIAL = ex.COMMERCIAL       # (model id, printed name, macro token)
GTOK = {'ALL': '', 'IFC2X3': 'TwoXThree', 'IFC4': 'Four', 'IFC4X3': 'FourXThree', 'native': 'Native',
        'migrated': 'Migrated'}


def load_tasks():
    T = {}
    for line in open(f'{BENCH}/tasks.v4c.jsonl'):
        r = json.loads(line)
        T[r['task_id']] = {k: r.get(k) for k in ('ifc_version', 'bench_part', 'origin', 'operation', 'category', 'tier',
                                                 'edit_kind', 'building_id', 'families', 'family', 'clarification')}
    S108 = json.load(open(f'{BENCH}/subset_108_hosted.v4c.json'))
    S324 = json.load(open(f'{BENCH}/subset_324.v4c.json'))
    assert len(T) == 2100 and len(set(S108)) == 108 and len(set(S324)) == 324 and set(S108) <= set(S324) <= set(T)
    return T, S108, S324


def read_rows(path, expect=None, partial=False):
    rows, dup = {}, 0
    for line in open(path):
        if line.strip():
            r = json.loads(line)
            dup += r['task_id'] in rows
            rows[r['task_id']] = r
    assert not dup, f'{path}: {dup} duplicate ids'
    if expect is not None:
        if partial:
            assert set(rows) <= set(expect), f'{path}: ids outside the expected set'
        else:
            assert set(rows) == set(expect), f'{path}: {len(rows)} ids, expected {len(expect)}'
    return rows


def arm_paths():
    """Every per-task file this analysis reads: key -> (path, task set name, plain label)."""
    A = {}
    for n in (108, 324):
        A[(n, 'ours')] = (f'{RES}/local{n}_lib_all/per_task_{FINAL}.jsonl', n, 'Final model, with the library')
        A[(n, 'sft', 'lib')] = (f'{RES}/local{n}_lib_all/per_task_{SFT}.jsonl', n, 'Imitation, with the library')
        A[(n, 'sft', 'alone')] = (f'{RES}/local{n}_alone_all/per_task_{SFT}.jsonl', n, 'Imitation, alone')
        A[(n, 'dpo', 'lib')] = (f'{RES}/local{n}_lib_all/per_task_{DPO}.jsonl', n, 'Preference snapshot, with the library')
    A[(324, 'prev', 'lib')] = (f'{RES}/local324_lib_all/per_task_{PREV}.jsonl', 324,
                               'Imitation + preferences, earlier corpus, with the library')
    A[(108, 'base', 'alone')] = (f'{RES}/local108_alone_all/per_task_{BASE}.jsonl', 108, 'Untrained Qwen3.5-9B, alone')
    A[(108, 'base', 'libnote')] = (f'{RES}/local108_libnote_all/per_task_{BASE}.jsonl', 108,
                                   'Untrained Qwen3.5-9B, with the library note')
    for mid, name, _ in COMMERCIAL:
        for a, lab in (('alone', 'alone'), ('lib', 'with the library')):
            A[(108, mid, a)] = (f'{RES}/hosted108_{a}_all/per_task_{mid}.jsonl', 108, f'{name}, {lab}')
    for a, lab in (('alone', 'alone'), ('lib', 'with the library')):
        A[(324, 'claude-sonnet-5-5', a)] = (f'{RES}/hosted324_{a}_all/per_task_claude-sonnet-5-5.jsonl', 324,
                                           f'Claude Sonnet 5.5, {lab}')
    for k, name, lab in (('sft', SFT, 'Imitation'), ('dpo', DPO, 'Preference snapshot'), ('ours', FINAL, 'Final model'),
                         ('prev', PREV, 'Imitation + preferences, earlier corpus'),
                         ('sft_small', 'sft_small', 'Ten-building chain, imitation'),
                         ('dpo_small', 'dpo_small_c12', 'Ten-building chain, preferences'),
                         ('grpo_small', 'grpo_small_c10', 'Ten-building chain, reinforcement')):
        A[(2100, k)] = (f'{RES}/full_all/per_task_{name}.jsonl', 2100, lab)
    return A


def load_all(T, S108, S324):
    sets = {108: S108, 324: S324, 2100: sorted(T)}
    rows = {}
    for k, (p, n, _) in arm_paths().items():
        rows[k] = read_rows(p, sets[n])
    return rows, sets


def axes(r):
    s = r.get('score') or {}
    return tuple((s.get(k) or 0.0) for k in ('geometry', 'semantics', 'topology'))


def done_at(r, t):
    return 1.0 if min(axes(r)) >= t else 0.0


def _pct(st):
    st = np.sort(st)
    return float(st[int(0.025 * R)]), float(st[int(0.975 * R) - 1])


def cboot(vals, ids, clus):
    """Building-level cluster bootstrap of a mean over tasks; returns (point, lo, hi, n_clusters)."""
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


def per_cluster_means(vals, ids, clus):
    out = {}
    for x, t in zip(vals, ids):
        out.setdefault(clus[t], []).append(x)
    return {b: (float(np.mean(v)), len(v)) for b, v in sorted(out.items())}


def parse_macros(*paths):
    M = {}
    for p in paths:
        for line in open(p):
            m = re.match(r'\\newcommand\{\\(\w+)\}\{([^}]*)\}', line)
            if m:
                v = m.group(2).replace('$-$', '-').replace(',', '')
                try:
                    M[m.group(1)] = float(v)
                except ValueError:
                    M[m.group(1)] = m.group(2)
    return M


def f3(x):
    return f'{x:.3f}'
