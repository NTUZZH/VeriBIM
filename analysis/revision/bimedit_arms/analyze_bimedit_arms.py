#!/usr/bin/env python3
"""BIM-Edit arms for Table 9 / Section 5.3: the final model, the untrained base, and Claude Sonnet 5.5 alone
and with the library note, all in this paper's harness and scored by the published BIM-Edit rules (scores_bench csv).
Per arm: mean score, means by operation, full solves (every metric >= 0.98), create tasks committed and their mean,
create tasks stopped at the round budget or a tool timeout, rounds, seconds, guard-blocked tasks, list cost; paired
task-level bootstrap of each arm minus the final model (10,000 resamples, seed 20260929, percentile interval).
    python analyze_bimedit_arms.py  -> prints and writes bimedit_arms.json next to this script (arms whose files exist)
The per-task BIM-Edit records (per_task_*.jsonl) are not redistributed, so this script documents the computation, and
bimedit_arms.json in this folder holds its output. The per-task scores (scores_bench_*.csv) are released in results/bimedit/.
"""
import csv, json, os, sys
import numpy as np
sys.dont_write_bytecode = True
ROOT = os.environ.get('VERIBIM_ROOT') or os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
E1 = f'{ROOT}/results/bimedit'; HERE = os.path.dirname(os.path.abspath(__file__))
SEED, R = 20260929, 10000
ARMS = {'final': (f'{E1}/per_task_grpo_v10b_c10.jsonl', f'{E1}/scores_bench_grpo_v10b_c10.csv'),
        'base': (f'{E1}/per_task_Qwen3.5-9B.jsonl', f'{E1}/scores_bench_Qwen3.5-9B.csv'),
        'sonnet_alone': (f'{E1}/sonnet_alone/per_task_claude-sonnet-5-5.jsonl', f'{E1}/sonnet_alone/scores_bench_claude-sonnet-5-5.csv'),
        'sonnet_lib': (f'{E1}/sonnet_lib/per_task_claude-sonnet-5-5.jsonl', f'{E1}/sonnet_lib/scores_bench_claude-sonnet-5-5.csv')}
PRICE = {'claude-sonnet-5-5': (3.0, 15.0)}   # US$ per million tokens (code/tables/hosted_cost.py); cache read 0.1, cache write 1.25
# The 324 BIM-Edit task ids in the order of the reported run; the order fixes the bootstrap draws.
IDS = json.load(open(f'{HERE}/bimedit_ids_324.json')); assert len(IDS) == 324


def load(pt, sc):
    rows = {}
    for l in open(pt):
        if l.strip():
            r = json.loads(l); rows[r['task_id']] = r
    score = {}
    for r in csv.DictReader(open(sc)):
        score[r['task_id']] = r
    assert set(rows) == set(IDS) and set(IDS) <= set(score), (len(rows), len(score))
    return rows, {t: score[t] for t in IDS}


def fs(r):
    return float(r['final_score'] or 0)


def boot(d):
    v = np.asarray(d, float); rng = np.random.default_rng(SEED)
    m = np.sort(np.array([v[rng.integers(0, len(v), len(v))].mean() for _ in range(R)]))
    return float(v.mean()), float(m[int(0.025 * R)]), float(m[int(0.975 * R) - 1])


def tf(x):
    return str(x).lower() in ('true', '1')


out = {}
ref = None
FS = {}
for arm, (pt, sc) in ARMS.items():
    if not (os.path.exists(pt) and os.path.exists(sc)):
        print(f'{arm}: files missing, skipped'); continue
    rows, S = load(pt, sc)
    F = {t: fs(S[t]) for t in IDS}
    ops = {op: [t for t in IDS if rows[t]['operation'] == op] for op in ('create', 'update', 'delete')}
    cats = {c: [t for t in IDS if rows[t]['category'] == c] for c in ('direct', 'spatial', 'topological')}
    budget = lambda t: rows[t]['stop_reason'] in ('budget_exhausted', 'tool_timeout')
    cr = ops['create']; cc = [t for t in cr if tf(rows[t]['committed'])]; cb = [t for t in cr if budget(t)]
    cn = [t for t in cr if not budget(t) and not tf(rows[t]['committed'])]
    solve = [t for t in IDS if all(float(S[t][k] or 0) >= 0.98 for k in ('geometry', 'semantics', 'topology'))]
    e = dict(n=324, mean=float(np.mean(list(F.values()))), by_operation={op: float(np.mean([F[t] for t in ts])) for op, ts in ops.items()},
             by_category={c: float(np.mean([F[t] for t in ts])) for c, ts in cats.items()},
             axes={k: float(np.mean([float(S[t][k] or 0) for t in IDS])) for k in ('geometry', 'semantics', 'topology')},
             full_solves=len(solve), full_solves_by_operation={op: sum(1 for t in solve if t in ts) for op, ts in ops.items()},
             create_committed=len(cc), create_committed_mean=float(np.mean([F[t] for t in cc])) if cc else 0.0,
             create_budget_stops=len(cb), create_reply_only=len(cn),
             budget_stops=sum(1 for t in IDS if budget(t)), committed=sum(1 for t in IDS if tf(rows[t]['committed'])),
             stops={}, rounds=float(np.mean([int(rows[t]['tool_rounds']) for t in IDS])),
             seconds=float(np.mean([float(rows[t].get('duration_seconds') or 0) for t in IDS])),
             guard_blocked_tasks=sum(1 for t in IDS if int(rows[t].get('sandbox_blocked') or 0) > 0),
             score_errors=sum(1 for t in IDS if (S[t].get('error') or '') not in ('', 'None')))
    for t in IDS:
        e['stops'][rows[t]['stop_reason']] = e['stops'].get(rows[t]['stop_reason'], 0) + 1
    m = rows[IDS[0]]['adapter']
    if m in PRICE:
        pi, po = PRICE[m]; c = 0.0
        for t in IDS:
            r = rows[t]; ti, to = int(r.get('input_tokens') or 0), int(r.get('output_tokens') or 0)
            crd, cw = int(r.get('cache_read_tokens') or 0), int(r.get('cache_creation_tokens') or 0)
            c += ((ti - crd - cw) * pi + crd * pi * 0.1 + cw * pi * 1.25 + to * po) / 1e6
        e['list_cost_usd'] = c
    if arm == 'final':
        ref = F
    else:
        d = [F[t] - ref[t] for t in IDS]
        pt_, lo, hi = boot(d)
        e['this_minus_final'] = dict(point=pt_, ci95=[lo, hi], wins=int(sum(x > 0 for x in d)), losses=int(sum(x < 0 for x in d)),
                                     by_operation={op: list(boot([F[t] - ref[t] for t in ts])) for op, ts in ops.items()})
    out[arm] = e; FS[arm] = F
    print(f"{arm}: mean {e['mean']:.3f}; create/update/delete {e['by_operation']['create']:.3f}/{e['by_operation']['update']:.3f}/{e['by_operation']['delete']:.3f}; "
          f"full solves {e['full_solves']} {e['full_solves_by_operation']}; create committed {e['create_committed']} (mean {e['create_committed_mean']:.3f}), "
          f"budget {e['create_budget_stops']}, reply only {e['create_reply_only']}; budget stops all {e['budget_stops']}; rounds {e['rounds']:.2f}; "
          f"{e['seconds']:.1f} s; guard-blocked tasks {e['guard_blocked_tasks']}; stops {e['stops']}; score errors {e['score_errors']}"
          + (f"; list US${e['list_cost_usd']:.2f}" if 'list_cost_usd' in e else ''))
    if 'this_minus_final' in e:
        q = e['this_minus_final']; print(f"   this minus VeriBIM-9B: {q['point']:+.3f} [{q['ci95'][0]:+.3f}, {q['ci95'][1]:+.3f}] (wins {q['wins']}, losses {q['losses']}); by op "
                                        + ', '.join(f"{op} {v[0]:+.3f} [{v[1]:+.3f}, {v[2]:+.3f}]" for op, v in q['by_operation'].items()))
if 'sonnet_alone' in FS and 'sonnet_lib' in FS:
    d = [FS['sonnet_lib'][t] - FS['sonnet_alone'][t] for t in IDS]
    pt_, lo, hi = boot(d)
    out['sonnet_lib']['this_minus_alone'] = dict(point=pt_, ci95=[lo, hi], wins=int(sum(x > 0 for x in d)), losses=int(sum(x < 0 for x in d)))
    print(f"sonnet lib minus alone: {pt_:+.3f} [{lo:+.3f}, {hi:+.3f}]")
json.dump(out, open(f'{HERE}/bimedit_arms.json', 'w'), indent=1)
