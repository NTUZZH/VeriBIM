#!/usr/bin/env python3
"""Statistical robustness of every paired completion comparison the manuscript reports.

For each comparison (arm A minus arm B on the same tasks; a task is completed when geometry, semantics and
topology are all >= 0.9):
  1. the discordant counts b (A completes, B fails) and c (B completes, A fails);
  2. the exact McNemar p, its mid-p, and the asymptotic McNemar p;
  3. score-based 95 % intervals for the paired difference (Tango; Newcombe method 10), the Bonett-Price interval,
     and the exact conditional (Clopper-Pearson) and mid-p conditional intervals for the paired odds ratio b / c;
  4. the published percentile bootstraps (task level and building level), recomputed from the same per-task rows
     with the published code and seed and checked against the manuscript macros (the run stops on a mismatch);
  5. logistic mixed models of completion on arm with a random intercept per building, per building and sampling
     cell (IFC version x operation x reference category), and per building and task, plus a GEE with exchangeable
     correlation within building, and a variational-Bayes cross-check with statsmodels;
  6. Holm-adjusted p-values for the primary family (the final model against the four commercial models with the
     library note, 108-task subset) and, as a secondary family, against the five documented commercial arms.

Inputs (read-only): runs_local/bench_v4/tasks.v4c.jsonl and subsets; per-task rows under
runs_local/bench_v4/results/<run>/per_task_<model>.jsonl; runs_local/stage_b_v10, stage_c_v10 and stage_a_v10 gate
reads; analysis/revision/dpo_seeds/bench324; macros in writing/tables/ and manuscript/build_v10/.
Shared loaders and bootstrap code: analysis/revision/stats/common.py (imports
writing/tables/make_results_exhibits.py).

    taskset -c 16-23 env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONNOUSERSITE=1 \
        python analysis/revision/stats/run_stats.py [--workers 4] [--skip-models]
"""
import argparse, csv, json, math, os, random, re, statistics, sys, time, warnings
from multiprocessing import Pool
from pathlib import Path

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / 'analysis/revision/stats'))
import numpy as np
import common as C                       # noqa: E402
import paired_methods as PM              # noqa: E402
import glmm_ml as G                      # noqa: E402

OUT = HERE / 'results'
LOG = HERE / 'log.txt'
RES = Path(C.RES)
REV07 = ROOT / 'analysis/revision'
FINAL, SFT, DPO, PREV, BASE = C.FINAL, C.SFT, C.DPO, C.PREV, C.BASE


def log(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} run_stats: {msg}"
    print(line, flush=True)
    with open(LOG, 'a') as f:
        f.write(line + '\n')


# ---------------------------------------------------------------- macros, kept as printed strings
def read_macros():
    M = {}
    for p in (ROOT / 'writing/tables/macros_results_v10.tex', ROOT / 'writing/tables/macros_small_chain.tex',
              ROOT / 'manuscript/build_v10/macros_rev.tex', ROOT / 'manuscript/build_v10/macros_v10.tex'):
        for line in open(p):
            m = re.match(r'\\newcommand\{\\(\w+)\}\{([^}]*)\}', line)
            if m and m.group(1) not in M:
                M[m.group(1)] = m.group(2)
    return M


MAC = read_macros()


def fmt_like(x, printed):
    """Format x the way the manuscript printed the macro (same decimals, $-$ for negatives)."""
    s = printed.replace('$-$', '-')
    d = len(s.split('.')[1]) if '.' in s else 0
    v = f'{abs(x):.{d}f}'
    return ('-' + v) if round(x, d) < 0 and float(v) != 0 else v


# ---------------------------------------------------------------- bootstrap rules of the published numbers
def boot_exhibit(vals):
    return C.boot(vals)                                   # 10,000 resamples, seed 20260929, sorted[250]/[9749]


def boot_exhibit90(vals):
    v = np.asarray(vals, float)
    rng = np.random.default_rng(C.SEED)
    m = np.empty(C.R)
    for s in range(0, C.R, 250):
        ix = rng.integers(0, len(v), size=(min(250, C.R - s), len(v)))
        m[s:s + len(ix)] = v[ix].mean(1)
    m.sort()
    return float(v.mean()), float(m[int(0.05 * C.R)]), float(m[int(0.95 * C.R) - 1])


def boot_small(vals, n=2000, seed=20261005):
    rnd = random.Random(seed)
    m = statistics.mean(vals)
    bs = sorted(statistics.mean([vals[rnd.randrange(len(vals))] for _ in vals]) for _ in range(n))
    return m, bs[int(0.025 * n)], bs[int(0.975 * n)]


# ---------------------------------------------------------------- data
def load_data():
    T, S108, S324 = C.load_tasks()
    D = {'T': T, 'S108': S108, 'S324': S324}
    CL = {t: T[t]['building_id'] for t in T}
    CELL = {t: f"{T[t]['ifc_version']}|{T[t]['operation']}|{T[t]['category']}" for t in T}
    rd = C.read_rows
    R = {}
    R['ours108'] = rd(f'{RES}/local108_lib_all/per_task_{FINAL}.jsonl', S108)
    for mid, _, tok in C.COMMERCIAL:
        for arm in ('alone', 'lib', 'informed'):
            R[f'{tok}_{arm}_108'] = rd(f'{RES}/hosted108_{arm}_all/per_task_{mid}.jsonl', S108)
    R['Opus_informed_108'] = rd(f'{RES}/hosted108_informed_all/per_task_claude-opus-5-5.jsonl', S108)
    # round 4 (2026-10-19): GPT-5.6 with the documented library and reasoning on (responses endpoint, effort medium)
    R['GptReason_informed_108'] = rd(f'{RES}/hosted108_informed_reasoning_all/per_task_gpt-5.6-luna.jsonl', S108)
    for arm in ('alone', 'libnote', 'informed'):
        R[f'base_{arm}_108'] = rd(f'{RES}/local108_{arm}_all/per_task_{BASE}.jsonl', S108)
    R['sft_lib_108'] = rd(f'{RES}/local108_lib_all/per_task_{SFT}.jsonl', S108)
    R['sft_alone_108'] = rd(f'{RES}/local108_alone_all/per_task_{SFT}.jsonl', S108)
    R['ours324'] = rd(f'{RES}/local324_lib_all/per_task_{FINAL}.jsonl', S324)
    R['Sonnet_lib_324'] = rd(f'{RES}/hosted324_lib_all/per_task_claude-sonnet-5-5.jsonl', S324)
    R['Sonnet_alone_324'] = rd(f'{RES}/hosted324_alone_all/per_task_claude-sonnet-5-5.jsonl', S324)
    rest = sorted(set(S324) - set(S108))
    inf324 = rd(f'{RES}/hosted324rest_informed_all/per_task_claude-sonnet-5-5.jsonl', rest)
    inf324.update(R['Sonnet_informed_108'])
    R['Sonnet_informed_324'] = inf324
    R['sft324'] = rd(f'{RES}/local324_lib_all/per_task_{SFT}.jsonl', S324)
    R['dpo324_s1'] = rd(f'{RES}/local324_lib_all/per_task_{DPO}.jsonl', S324)
    R['dpo324_s2'] = rd(f'{REV07}/dpo_seeds/bench324/per_task_dpo_v10_s2_c6.jsonl', S324)
    R['dpo324_s3'] = rd(f'{REV07}/dpo_seeds/bench324/per_task_dpo_v10_s3_c6.jsonl', S324)
    ALL = sorted(T)
    for k, name in (('sft', SFT), ('dpo', DPO), ('ours', FINAL), ('prev', PREV), ('sft_small', 'sft_small'),
                    ('dpo_small', 'dpo_small_c12'), ('grpo_small', 'grpo_small_c10')):
        R[f'{k}_2100'] = rd(f'{RES}/full_all/per_task_{name}.jsonl', ALL)
    R['base982'] = rd(f'{RES}/full_note_all/per_task_{BASE}.jsonl', T, partial=True)
    be = C.ex.base_estimate(R['base982'], R['base_libnote_108'], T)
    D['base_2x3_ids'] = be['per']['IFC2X3']['ids']
    # hard validation set (300 tasks), order of val_hard_ids.json as in the exhibit script
    vh_ids = json.load(open(C.ex.VALHARD_IDS))
    VT = {json.loads(l)['task_id']: json.loads(l) for l in open(ROOT / 'runs_local/stage_b_v10/val_hard/val_hard_tasks.jsonl') if l.strip()}
    D['vh_ids'] = vh_ids
    R['vh_sft'] = rd(f'{C.ex.DPO_VALHARD_ROWS}/per_task_{SFT}.jsonl', vh_ids)
    R['vh_dpo'] = rd(f'{C.ex.DPO_VALHARD_ROWS}/per_task_{DPO}.jsonl', vh_ids)
    R['vh_ours'] = rd(f'{ROOT}/runs_local/stage_c_v10/gates/valhard_v10b/per_task_{FINAL}.jsonl', vh_ids)
    # rewritten-wording validation set (val-100 v3b): rewritten read and the generated-wording reads on the same ids
    v100 = json.load(open(C.ex.V100B_SUBSET))
    W = {json.loads(l)['task_id']: json.loads(l) for l in open(ROOT / 'runs_local/stage_a_v10/val100_rw/val_tasks_100_v3b_rw.jsonl') if l.strip()}
    assert set(W) == set(v100)
    D['v100'] = sorted(v100)
    D['v100_rw_only'] = sorted(t for t in v100 if W[t].get('wording_rewritten') is True)
    gates = ROOT / 'runs_local/stage_a_v10/gates'
    R['rw_ours'] = rd(f'{gates}/v100rw/per_task_{FINAL}.jsonl', v100)
    R['rw_sft'] = rd(f'{gates}/v100rw/per_task_{SFT}.jsonl', v100)
    o1 = rd(f'{gates}/v500b_grpo_v10b_c10_rep1/per_task_{FINAL}.jsonl')
    o2 = rd(f'{gates}/v500b_grpo_v10b_c10_rep2/per_task_{FINAL}.jsonl')
    s0 = rd(f'{gates}/v500b/per_task_{SFT}.jsonl')
    R['orig_ours'] = {t: o1[t] for t in v100}
    R['orig_ours_rep2'] = {t: o2[t] for t in v100}
    R['orig_sft'] = {t: s0[t] for t in v100}
    for t in VT:
        CL[t] = VT[t]['building_id']
        CELL[t] = f"{VT[t]['ifc_version']}|{VT[t]['operation']}|{VT[t]['category']}"
    for t in W:
        CL.setdefault(t, W[t]['building_id'])
        CELL.setdefault(t, f"{W[t]['ifc_version']}|{W[t]['operation']}|{W[t]['category']}")
        assert CL[t] == W[t]['building_id']
    D['CL'], D['CELL'], D['R'], D['ALL'], D['REST'] = CL, CELL, R, ALL, rest
    return D


# ---------------------------------------------------------------- the comparisons
def comparisons(D):
    T, S108, S324, R, ALL, REST = D['T'], D['S108'], D['S324'], D['R'], D['ALL'], D['REST']
    S108s, S324s = sorted(S108), sorted(S324)
    full = lambda ids: sorted(t for t in ids if not T[t]['clarification'])
    L = []

    def add(cid, section, label, a, b, ids, a_lab, b_lab, task=None, bld=None, order=None, rule='exhibit',
            wl=None, extra=None, equiv=False, family=None):
        L.append(dict(id=cid, section=section, label=label, a=a, b=b, ids=sorted(ids), order=order or sorted(ids),
                      a_label=a_lab, b_label=b_lab, task_macro=task, bld_macro=bld, rule=rule, wl=wl,
                      extra=extra or {}, equiv=equiv, family=family))

    names = {'Gpt': 'GPT-5.6', 'DeepSeek': 'DeepSeek V4', 'Sonnet': 'Claude Sonnet 5.5', 'Gemini': 'Gemini 3.8 Flash'}
    for tok in ('Gpt', 'DeepSeek', 'Sonnet', 'Gemini'):
        add(f'108_ours_vs_{tok}_note', '108-task subset, library note (primary Holm family)',
            f'VeriBIM-9B minus {names[tok]} with the library note', R['ours108'], R[f'{tok}_lib_108'], S108,
            'VeriBIM-9B', f'{names[tok]}, library and note', task=f'ResHundredEightOursMinus{tok}Lib',
            bld=f'RevHundredEightOursMinus{tok}Lib', family='primary')
    for tok in ('Gpt', 'DeepSeek', 'Sonnet', 'Gemini'):
        add(f'108_ours_vs_{tok}_alone', '108-task subset, commercial model alone',
            f'VeriBIM-9B minus {names[tok]} alone', R['ours108'], R[f'{tok}_alone_108'], S108,
            'VeriBIM-9B', f'{names[tok]}, alone', task=f'ResHundredEightOursMinus{tok}Alone',
            bld=f'RevHundredEightOursMinus{tok}Alone')
    for tok in ('Gpt', 'DeepSeek', 'Sonnet', 'Gemini', 'Opus'):
        nm = names.get(tok, 'Claude Opus 5.5')
        add(f'108_ours_vs_{tok}_documented', '108-task subset, documented library (secondary family)',
            f'VeriBIM-9B minus {nm} with the documented library', R['ours108'], R[f'{tok}_informed_108'], S108,
            'VeriBIM-9B', f'{nm}, documented library', task=f'RevOursMinusInf{tok}', bld=f'RevOursMinusInf{tok}',
            order=list(S108), wl=f'RevOursMinusInf{tok}', equiv=(tok == 'Sonnet'), family='documented')
    # round 4 (2026-10-19): the documented arm of GPT-5.6 with reasoning on joins the documented family (an arm designed
    # after the first evaluation, as the other documented arms); same task order (subset file) as the documented rows
    add('108_ours_vs_GptReason_documented', '108-task subset, documented library (secondary family)',
        'VeriBIM-9B minus GPT-5.6 with the documented library, reasoning on', R['ours108'], R['GptReason_informed_108'], S108,
        'VeriBIM-9B', 'GPT-5.6, documented library, reasoning on', task='RevOursMinusInfGptReason', bld='RevOursMinusInfGptReason',
        order=list(S108), wl='RevOursMinusInfGptReason', family='documented')
    add('108_ours_vs_base_alone', '108-task subset, untrained base', 'VeriBIM-9B minus untrained Qwen3.5-9B alone',
        R['ours108'], R['base_alone_108'], S108, 'VeriBIM-9B', 'Qwen3.5-9B, alone',
        task='ResHundredEightOursMinusBaseAlone', bld='RevHundredEightOursMinusBaseAlone')
    add('108_ours_vs_base_note', '108-task subset, untrained base', 'VeriBIM-9B minus untrained Qwen3.5-9B with the library note',
        R['ours108'], R['base_libnote_108'], S108, 'VeriBIM-9B', 'Qwen3.5-9B, library and note',
        task='ResHundredEightOursMinusBaseNote', bld='RevHundredEightOursMinusBaseNote')
    add('108_ours_vs_base_documented', '108-task subset, untrained base',
        'VeriBIM-9B minus untrained Qwen3.5-9B with the documented library', R['ours108'], R['base_informed_108'], S108,
        'VeriBIM-9B', 'Qwen3.5-9B, documented library', task='RevOursMinusBaseInf', bld='RevOursMinusBaseInf', order=list(S108))
    add('108_base_documented_vs_note', '108-task subset, untrained base',
        'Qwen3.5-9B documented minus Qwen3.5-9B with the library note', R['base_informed_108'], R['base_libnote_108'], S108,
        'Qwen3.5-9B, documented library', 'Qwen3.5-9B, library and note', task='RevBaseInfMinusNote', order=list(S108))
    add('108_sonnet_documented_vs_opus_documented', '108-task subset, documented library (secondary family)',
        'Claude Sonnet 5.5 documented minus Claude Opus 5.5 documented', R['Sonnet_informed_108'], R['Opus_informed_108'],
        S108, 'Claude Sonnet 5.5, documented library', 'Claude Opus 5.5, documented library',
        task='RevSonnetInfMinusOpus', order=list(S108))
    add('108_ours_vs_sft_lib', '108-task subset, training stages', 'VeriBIM-9B minus the imitation model with the library',
        R['ours108'], R['sft_lib_108'], S108, 'VeriBIM-9B', 'imitation model, library',
        task='ResHundredEightOursMinusSftLib', bld='RevHundredEightOursMinusSftLib')
    add('108_ours_vs_sft_alone', '108-task subset, training stages', 'VeriBIM-9B minus the imitation model without the library',
        R['ours108'], R['sft_alone_108'], S108, 'VeriBIM-9B', 'imitation model, alone',
        task='ResHundredEightOursMinusSftAlone', bld='RevHundredEightOursMinusSftAlone')
    for tok in ('Sonnet', 'DeepSeek', 'Gpt', 'Gemini'):
        add(f'108full_ours_vs_{tok}_note', '108-task subset, 97 fully specified tasks',
            f'VeriBIM-9B minus {names[tok]} with the library note, fully specified tasks', R['ours108'], R[f'{tok}_lib_108'],
            full(S108), 'VeriBIM-9B', f'{names[tok]}, library and note', task=f'RevFullHundredEightOursMinus{tok}Lib',
            bld=f'RevFullHundredEightOursMinus{tok}Lib', wl=f'RevFullHundredEightOursMinus{tok}Lib')
    # 324-task subset
    add('324_ours_vs_Sonnet_note', '324-task subset', 'VeriBIM-9B minus Claude Sonnet 5.5 with the library note',
        R['ours324'], R['Sonnet_lib_324'], S324, 'VeriBIM-9B', 'Claude Sonnet 5.5, library and note',
        task='ResThreeTwentyFourOursMinusSonnetLib', bld='RevThreeTwentyFourOursMinusSonnetLib')
    add('324_ours_vs_Sonnet_alone', '324-task subset', 'VeriBIM-9B minus Claude Sonnet 5.5 alone',
        R['ours324'], R['Sonnet_alone_324'], S324, 'VeriBIM-9B', 'Claude Sonnet 5.5, alone',
        task='ResThreeTwentyFourOursMinusSonnetAlone', bld='RevThreeTwentyFourOursMinusSonnetAlone')
    add('324_IFC4X3_ours_vs_Sonnet_note', '324-task subset', 'VeriBIM-9B minus Claude Sonnet 5.5 with the library note, IFC4X3 part',
        R['ours324'], R['Sonnet_lib_324'], [t for t in S324 if T[t]['ifc_version'] == 'IFC4X3'], 'VeriBIM-9B',
        'Claude Sonnet 5.5, library and note', task='ResThreeTwentyFourOursMinusSonnetLibFourXThree',
        bld='RevThreeTwentyFourOursMinusSonnetLibFourXThree')
    add('324full_ours_vs_Sonnet_note', '324-task subset', 'VeriBIM-9B minus Claude Sonnet 5.5 with the library note, 295 fully specified tasks',
        R['ours324'], R['Sonnet_lib_324'], full(S324), 'VeriBIM-9B', 'Claude Sonnet 5.5, library and note',
        task='RevFullThreeTwentyFourOursMinusSonnetLib', bld='RevFullThreeTwentyFourOursMinusSonnetLib',
        wl='RevFullThreeTwentyFourOursMinusSonnetLib')
    E = json.load(open(ROOT / 'analysis/revision/equivalence/equiv_216.json'))
    add('216_ours_vs_Sonnet_documented', '216 tasks outside the 108 (pre-specified equivalence test)',
        'VeriBIM-9B minus Claude Sonnet 5.5 documented, 216 tasks', R['ours324'], R['Sonnet_informed_324'], REST,
        'VeriBIM-9B', 'Claude Sonnet 5.5, documented library', task='RevRest', equiv=True,
        extra={'json_building': E['primary_216']['building']['ci95'], 'json_b': E['primary_216']['a_only'],
               'json_c': E['primary_216']['b_only'], 'ninety': ('RevRestNinetyLo', 'RevRestNinetyHi')})
    add('324_ours_vs_Sonnet_documented', '324-task subset', 'VeriBIM-9B minus Claude Sonnet 5.5 documented, all 324 tasks',
        R['ours324'], R['Sonnet_informed_324'], S324, 'VeriBIM-9B', 'Claude Sonnet 5.5, documented library',
        task='RevThreeOursMinusInf', equiv=True,
        extra={'json_building': E['secondary']['324_all']['building']['ci95'], 'json_b': E['secondary']['324_all']['a_only'],
               'json_c': E['secondary']['324_all']['b_only']})
    for k, tok in (('s1', 'CSix'), ('s2', 'Two'), ('s3', 'Three')):
        add(f'324_dpo_seed_{k}_vs_sft', '324-task subset, preference-stage seeds',
            f'preference snapshot seed {k[-1]} minus the imitation model', R[f'dpo324_{k}'], R['sft324'], S324,
            f'preference snapshot, seed {k[-1]}', 'imitation model', task=f'RevSeed{tok}MinusSft')
    # 2,100-task benchmark: training chain
    for cid, a, b, mac, lab in (('2100_dpo_vs_sft', 'dpo_2100', 'sft_2100', 'BenchDeltaDpoOverSft', 'preference stage minus imitation'),
                                ('2100_ours_vs_dpo', 'ours_2100', 'dpo_2100', 'BenchDeltaGrpoOverDpo', 'reinforcement stage (VeriBIM-9B) minus preference stage'),
                                ('2100_ours_vs_sft', 'ours_2100', 'sft_2100', 'BenchDeltaOursOverSft', 'VeriBIM-9B minus imitation'),
                                ('2100_dpo_vs_prev', 'dpo_2100', 'prev_2100', 'BenchDeltaDpoOverPrev', 'current corpus minus earlier corpus (after two stages)')):
        add(cid, '2,100-task benchmark, training chain', lab, R[a], R[b], ALL, a.split('_')[0], b.split('_')[0],
            task=f'Res{mac}', bld=f'Rev{mac}')
    add('2100_IFC2X3_sft_vs_base', '2,100-task benchmark, training chain', 'imitation minus untrained base with the library note, IFC2X3 part (measured)',
        R['sft_2100'], R['base982'], D['base_2x3_ids'], 'imitation model', 'Qwen3.5-9B, library and note',
        task='ResBenchDeltaSftOverBaseTwoXThree', bld='RevBenchDeltaSftOverBaseTwoXThree', order=list(D['base_2x3_ids']))
    for tag in ('Sft', 'Dpo', 'Grpo'):
        k = {'Sft': 'sft', 'Dpo': 'dpo', 'Grpo': 'ours'}[tag]
        add(f'2100_fullcorpus_vs_tenbuilding_{tag.lower()}', '2,100-task benchmark, ten-building chain',
            f'full-corpus chain minus ten-building chain after the {tag} stage', R[f'{k}_2100'],
            R[f'{k if k != "ours" else "grpo"}_small_2100'], ALL, 'full-corpus chain', 'ten-building chain',
            task=f'ResSmall{tag}GapToMain', bld=f'RevSmall{tag}GapToMain' if tag != 'Dpo' else None, rule='small')
    add('2100_tenbuilding_dpo_vs_sft', '2,100-task benchmark, ten-building chain', 'ten-building chain, preference minus imitation',
        R['dpo_small_2100'], R['sft_small_2100'], ALL, 'ten-building preference', 'ten-building imitation',
        task='ResSmallDeltaDpoOverSft', bld='RevSmallDeltaDpoOverSft', rule='small', wl='ResSmallDeltaDpoOverSft')
    # validation sets
    add('valhard_ours_vs_dpo', 'hard validation set (300 tasks, selection set)', 'reinforcement snapshot (VeriBIM-9B) minus preference snapshot',
        R['vh_ours'], R['vh_dpo'], D['vh_ids'], 'VeriBIM-9B', 'preference snapshot', task='ResValHardGrpoDelta',
        bld='RevValHardGrpoDelta', order=list(D['vh_ids']), wl='ResValHardGrpoDelta')
    add('valhard_dpo_vs_sft', 'hard validation set (300 tasks, selection set)', 'preference snapshot minus imitation',
        R['vh_dpo'], R['vh_sft'], D['vh_ids'], 'preference snapshot', 'imitation model', task='ResValHardDpoDelta',
        bld='RevValHardDpoDelta', order=list(D['vh_ids']), wl='ResValHardDpoDelta')
    add('v100_ours_rewritten_vs_generated', 'rewritten-wording validation set (100 tasks)',
        'VeriBIM-9B on rewritten wording minus the same model on the generated wording', R['rw_ours'], R['orig_ours'],
        D['v100'], 'VeriBIM-9B, rewritten wording', 'VeriBIM-9B, generated wording',
        extra={'done_macros': ('ResValSmallOursDone', 'ResValSmallOrigDone')})
    add('v85_ours_rewritten_vs_generated', 'rewritten-wording validation set (100 tasks)',
        'VeriBIM-9B on rewritten wording minus generated wording, the 85 rewritten instructions only', R['rw_ours'],
        R['orig_ours'], D['v100_rw_only'], 'VeriBIM-9B, rewritten wording', 'VeriBIM-9B, generated wording',
        extra={'comp_macros': ('RevRwOnlyOursComp',)})
    add('v100_sft_rewritten_vs_generated', 'rewritten-wording validation set (100 tasks)',
        'imitation model on rewritten wording minus generated wording', R['rw_sft'], R['orig_sft'], D['v100'],
        'imitation model, rewritten wording', 'imitation model, generated wording', extra={'done_macros': ('ResValSmallSftDone', 'ResValSmallOrigDone')})
    return L


# ---------------------------------------------------------------- reproduction of the published intervals
def reproduce(c, D):
    """Recompute the published intervals with the published rule and compare with the printed macros."""
    CL = D['CL']
    d_order = [C.done(c['a'][t]) - C.done(c['b'][t]) for t in c['order']]
    rep = {'id': c['id'], 'checks': []}

    def chk(what, value, macro):
        if macro not in MAC:
            rep['checks'].append({'what': what, 'macro': macro, 'printed': None, 'computed': value, 'ok': None})
            return
        printed = MAC[macro]
        ok = fmt_like(value, printed) == printed.replace('$-$', '-')
        rep['checks'].append({'what': what, 'macro': macro, 'printed': printed, 'computed': round(float(value), 6), 'ok': ok})

    tb = (boot_small if c['rule'] == 'small' else boot_exhibit)(d_order)
    cb = C.cboot(d_order, c['order'], CL)
    rep['task'] = list(tb)
    rep['building'] = [cb[1], cb[2]]
    if c['task_macro']:
        mt = c['task_macro']
        if c['id'] == '216_ours_vs_Sonnet_documented':
            chk('point', tb[0], 'RevRestDiff'); chk('task lo', tb[1], 'RevRestLo'); chk('task hi', tb[2], 'RevRestHi')
        else:
            chk('point', tb[0], mt); chk('task lo', tb[1], mt + 'Lo'); chk('task hi', tb[2], mt + 'Hi')
    if c['bld_macro']:
        chk('building lo', cb[1], c['bld_macro'] + 'CLo'); chk('building hi', cb[2], c['bld_macro'] + 'CHi')
    b = sum(1 for x in d_order if x > 0)
    cc = sum(1 for x in d_order if x < 0)
    if c['wl']:
        chk('b (A only)', b, c['wl'] + 'Wins'); chk('c (B only)', cc, c['wl'] + 'Losses')
    ex = c['extra']
    if 'ninety' in ex:
        t90 = boot_exhibit90(d_order)
        chk('task 90 lo', t90[1], ex['ninety'][0]); chk('task 90 hi', t90[2], ex['ninety'][1])
    if c['id'] == '108_ours_vs_Sonnet_documented':
        t90 = boot_exhibit90([C.done(c['a'][t]) - C.done(c['b'][t]) for t in sorted(c['ids'])])
        chk('task 90 lo (sorted order)', t90[1], 'RevOursMinusInfNinetyLo'); chk('task 90 hi (sorted order)', t90[2], 'RevOursMinusInfNinetyHi')
        ts = boot_exhibit([C.done(c['a'][t]) - C.done(c['b'][t]) for t in sorted(c['ids'])])
        chk('task lo (sorted order)', ts[1], 'RevOursMinusInfLo'); chk('task hi (sorted order)', ts[2], 'RevOursMinusInfHi')
        chk('building lo', cb[1], 'RevOursMinusInfCLo'); chk('building hi', cb[2], 'RevOursMinusInfCHi')
    if 'json_building' in ex:
        for k, (v, j) in enumerate(zip([cb[1], cb[2]], ex['json_building'])):
            rep['checks'].append({'what': f'building {"lo" if k == 0 else "hi"} (equiv_216.json)', 'macro': None,
                                  'printed': j, 'computed': v, 'ok': abs(v - j) < 1e-9})
        rep['checks'].append({'what': 'b, c (equiv_216.json)', 'macro': None, 'printed': [ex['json_b'], ex['json_c']],
                              'computed': [b, cc], 'ok': [b, cc] == [ex['json_b'], ex['json_c']]})
    for key in ('done_macros', 'comp_macros'):
        if key in ex:
            ya = sum(C.done(c['a'][t]) for t in c['ids']); yb = sum(C.done(c['b'][t]) for t in c['ids'])
            if key == 'done_macros':
                chk('A completed', ya, ex[key][0]); chk('B completed', yb, ex[key][1])
            else:
                chk('A completion', ya / len(c['ids']), ex[key][0])
    rep['ok'] = all(x['ok'] is not False for x in rep['checks'])
    rep['n_checked'] = sum(1 for x in rep['checks'] if x['ok'] is not None)
    return rep


# ---------------------------------------------------------------- mixed models (worker)
def model_job(args):
    cid, ya, yb, bl, cell = args
    warnings.simplefilter('ignore')
    out = {'id': cid, 'fits': []}
    t0 = time.time()
    ya, yb = np.asarray(ya, int), np.asarray(yb, int)
    for fn in (lambda: G.fit_building_quadrature(ya, yb, bl),
               lambda: G.fit_laplace(ya, yb, [bl, cell], ['building', 'cell'],
                                     'building and sampling-cell random intercepts (ML, Laplace)'),
               lambda: G.fit_building_task(ya, yb, bl),
               lambda: G.fit_laplace(ya, yb, [bl], ['building'], 'building random intercept (ML, Laplace; check of the quadrature fit)')):
        try:
            out['fits'].append(fn())
        except Exception as e:                      # recorded, never silent
            out['fits'].append({'model': 'failed', 'error': repr(e)})
    out['fits'].extend(statsmodels_fits(ya, yb, bl, cell))
    out['seconds'] = time.time() - t0
    return out


def statsmodels_fits(ya, yb, bl, cell):
    import pandas as pd
    import statsmodels.api as sm
    from statsmodels.genmod.bayes_mixed_glm import BinomialBayesMixedGLM
    from scipy import stats
    n = len(ya)
    df = pd.DataFrame({'y': np.concatenate([ya, yb]), 'arm': np.r_[np.ones(n), np.zeros(n)],
                       'building': list(bl) * 2, 'cell': list(cell) * 2})
    res = []
    X = sm.add_constant(df[['arm']])
    for cov_type, lab in (('robust', 'GEE, exchangeable within building, robust (sandwich) SE'),
                          ('bias_reduced', 'GEE, exchangeable within building, bias-reduced SE (Mancl-DeRouen)')):
        try:
            with warnings.catch_warnings(record=True) as w:
                warnings.simplefilter('always')
                m = sm.GEE(df['y'], X, groups=df['building'], family=sm.families.Binomial(),
                           cov_struct=sm.cov_struct.Exchangeable())
                r = m.fit(cov_type=cov_type, maxiter=200)
            b1, se = float(r.params['arm']), float(r.bse['arm'])
            ok = math.isfinite(se) and se > 0 and abs(b1) < 15 and se < 20
            res.append({'model': lab, 'beta1': b1, 'se_beta1': se, 'odds_ratio': math.exp(b1) if ok else math.nan,
                        'or_lo': math.exp(b1 - 1.959964 * se) if ok else math.nan,
                        'or_hi': math.exp(b1 + 1.959964 * se) if ok else math.nan,
                        'wald_p': float(2 * stats.norm.sf(abs(b1 / se))) if ok else math.nan,
                        'separation': not ok, 'working_correlation': float(r.cov_struct.dep_params),
                        'n_groups': {'building': int(df['building'].nunique())},
                        'warnings': sorted({str(x.category.__name__) for x in w})})
        except Exception as e:
            res.append({'model': lab, 'error': repr(e)})
    for vc, lab in (({'building': '0 + C(building)'}, 'variational Bayes, building random intercept (statsmodels, cross-check)'),
                    ({'building': '0 + C(building)', 'cell': '0 + C(cell)'}, 'variational Bayes, building and cell (statsmodels, cross-check)')):
        try:
            m = BinomialBayesMixedGLM.from_formula('y ~ arm', vc, df, vcp_p=1, fe_p=10)
            r = m.fit_vb()
            names = list(m.exog_names)
            i = names.index('arm')
            b1, sd = float(r.fe_mean[i]), float(r.fe_sd[i])
            d = {'model': lab, 'beta1': b1, 'se_beta1': sd, 'odds_ratio': math.exp(b1),
                 'or_lo': math.exp(b1 - 1.959964 * sd), 'or_hi': math.exp(b1 + 1.959964 * sd),
                 'wald_p': float(2 * stats.norm.sf(abs(b1 / sd))), 'prior': 'fixed effects N(0, 10^2); log SD N(0, 1)'}
            for k, nm in enumerate(m.vcp_names):
                d[f'var_{nm}'] = math.exp(2 * float(r.vcp_mean[k]))     # posterior mean of log SD, transformed
            res.append(d)
        except Exception as e:
            res.append({'model': lab, 'error': repr(e)})
    return res


# ---------------------------------------------------------------- Holm
def holm(ps):
    m = len(ps)
    order = sorted(range(m), key=lambda i: ps[i])
    adj, run = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        run = max(run, min(1.0, (m - rank) * ps[i]))
        adj[i] = run
    return adj, order


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workers', type=int, default=4)
    ap.add_argument('--skip-models', action='store_true')
    ap.add_argument('--regenerate', action='store_true',
                    help='the per-task rows changed on purpose (2026-10-16: repaired ground truths); a mismatch with the '
                         'printed macros is logged and the run continues, and the macros are regenerated from its output')
    args = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    log('start; loading per-task rows')
    D = load_data()
    comps = comparisons(D)
    log(f'{len(comps)} comparisons defined')
    # 1. reproduction gate
    reps = [reproduce(c, D) for c in comps]
    bad = [r for r in reps if not r['ok']]
    with open(OUT / 'reproduction.csv', 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['comparison_id', 'what', 'macro', 'printed_in_manuscript', 'recomputed', 'match'])
        for r in reps:
            for x in r['checks']:
                w.writerow([r['id'], x['what'], x['macro'] or '', x['printed'], x['computed'], x['ok']])
    log(f'reproduction: {sum(r["n_checked"] for r in reps)} printed values checked, {len(bad)} comparisons with a mismatch')
    if bad:
        for r in bad:
            log(f'MISMATCH {r["id"]}: ' + '; '.join(f'{x["what"]} printed {x["printed"]} recomputed {x["computed"]}'
                                                     for x in r['checks'] if x['ok'] is False))
        if not args.regenerate:
            log('stopping: a published interval was not reproduced from the per-task rows')
            sys.exit(3)
        log('--regenerate: continuing; the printed macros are regenerated from this run')
    # 2. exact and score-based statistics
    rows, results = [], {}
    for c, rp in zip(comps, reps):
        ids = c['ids']
        ya = np.array([int(C.done(c['a'][t])) for t in ids]); yb = np.array([int(C.done(c['b'][t])) for t in ids])
        n11, n12, n21, n22 = PM.table(ya, yb)
        m95 = PM.all_methods(n11, n12, n21, n22, 0.05)
        e = {'id': c['id'], 'section': c['section'], 'label': c['label'], 'a_label': c['a_label'], 'b_label': c['b_label'],
             'n': len(ids), 'a_done': int(ya.sum()), 'b_done': int(yb.sum()), 'n11': n11, 'b': n12, 'c': n21, 'n22': n22,
             'n_buildings': len({D['CL'][t] for t in ids}), 'family': c['family'],
             'methods95': m95, 'bootstrap_task': rp['task'], 'bootstrap_building': rp['building'],
             'bootstrap_rule': 'Python random, 2,000 resamples, seed 20261005' if c['rule'] == 'small' else
                               'numpy default_rng(20260929), 10,000 resamples, sorted[250] and sorted[9749]'}
        if c['equiv']:
            m90 = PM.all_methods(n11, n12, n21, n22, 0.10)
            d_sorted = [C.done(c['a'][t]) - C.done(c['b'][t]) for t in c['order']]
            b90 = boot_exhibit90(d_sorted)
            zl, zu = PM.tango_z(n12, n21, len(ids), -0.05), PM.tango_z(n12, n21, len(ids), 0.05)
            from scipy import stats
            e['equivalence_margin_0.05'] = {
                'bootstrap_90': [b90[1], b90[2]], 'tango_90': list(m90['tango']), 'newcombe_90': list(m90['newcombe']),
                'tost_p_tango': float(max(stats.norm.sf(zl), stats.norm.cdf(zu))),
                'inside': {k: bool(-0.05 < v[0] and v[1] < 0.05) for k, v in
                           (('bootstrap_90', (b90[1], b90[2])), ('tango_90', m90['tango']), ('newcombe_90', m90['newcombe']))}}
        results[c['id']] = e
        e['_model_input'] = (c['id'], ya.tolist(), yb.tolist(), [D['CL'][t] for t in ids], [D['CELL'][t] for t in ids])
    log('exact and score-based statistics done')
    # 3. mixed models
    if not args.skip_models:
        jobs = [results[c['id']]['_model_input'] for c in comps]
        jobs.sort(key=lambda j: -len(j[1]))
        with Pool(min(4, args.workers)) as pool:
            for k, out in enumerate(pool.imap_unordered(model_job, jobs)):
                results[out['id']]['models'] = out['fits']
                log(f'models {k + 1}/{len(jobs)} {out["id"]} ({out["seconds"]:.0f} s)')
    for e in results.values():
        e.pop('_model_input', None)
    json.dump({'comparisons': results, 'reproduction': reps, 'self_check': PM.self_check()},
              open(OUT / 'all_results.json', 'w'), indent=1, default=float)
    log('wrote results/all_results.json; tables are written by tables.py')


if __name__ == '__main__':
    main()
