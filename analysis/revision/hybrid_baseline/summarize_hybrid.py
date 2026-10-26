"""Summary of the hybrid baseline: per task set and canonicalizer, the share of requests the parser read, the completion,
the mean score, and the paired comparison with VeriBIM-9B (grpo_v10b_c10) on the same tasks (completion difference with a
seeded bootstrap interval, exact McNemar p). Also the template parser alone on the same requests (0 recognised by construction
on the reworded set; the stored read on the practitioner set if present)."""
import json, math, random, sys
from pathlib import Path
H = Path('analysis/revision/hybrid_baseline'); P = Path('.')
MODEL = {'rw': P / 'analysis/revision/reworded_benchmark/reads/model/per_task_grpo_v10b_c10.jsonl',
         'prac': P / 'analysis/revision/colleague_packets/results/model/per_task_grpo_v10b_c10.jsonl'}
PARSER = {'rw': P / 'analysis/revision/reworded_benchmark/reads/parser/per_task_parser_rw.jsonl',
          'prac': P / 'analysis/revision/colleague_packets/results/parser/per_task_parser_colleague.jsonl'}
def rows(p): return {r['task_id']: r for r in (json.loads(l) for l in open(p) if l.strip())}
def comp(r):
    sc = r.get('score') or {}; return all((sc.get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology'))
def final(r): return float((r.get('score') or {}).get('final') or r.get('final') or 0.0)
def mcnemar(b, c):
    n = b + c; k = min(b, c)
    if n == 0: return 1.0
    return min(1.0, 2 * sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n)
def boot(diffs, seed=20261026, B=10000):
    rng = random.Random(seed); n = len(diffs); ms = []
    for _ in range(B):
        s = [diffs[rng.randrange(n)] for _ in range(n)]; ms.append(sum(s) / n)
    ms.sort(); return ms[int(0.025 * B)], ms[int(0.975 * B) - 1]
out = {}; lines = ['| set | canonicalizer | n | parser read | completed | completion | mean score | VeriBIM-9B completion | difference [95% CI] | McNemar p |', '|---|---|---|---|---|---|---|---|---|---|']
for s in ('rw', 'prac'):
    model = rows(MODEL[s]) if MODEL[s].exists() else {}
    for c in ('sonnet', 'local'):
        f = H / f'scoring/{s}_{c}/per_task_parser.jsonl'
        if not f.exists(): continue
        hb = rows(f); ids = sorted(hb); n = len(ids)
        rec = sum(1 for t in ids if hb[t].get('recognised')); done = sum(1 for t in ids if hb[t].get('completed') or comp(hb[t]))
        mean = sum(final(hb[t]) for t in ids) / n
        rec_in = {t: json.loads(l) for t, l in ((json.loads(l)['task_id'], l) for l in open(H / f'in/canon_{s}_{c}.jsonl'))}
        attempts = [len(rec_in[t].get('canon_attempts') or []) for t in ids if t in rec_in]
        e = {'n': n, 'recognised': rec, 'completed': done, 'completion': round(done / n, 3), 'mean': round(mean, 3),
             'attempts_mean': round(sum(attempts) / max(1, len(attempts)), 2), 'canon_errors': sum(1 for t in ids if rec_in.get(t, {}).get('canon_error'))}
        if model and all(t in model for t in ids):
            mdone = sum(1 for t in ids if comp(model[t])); diffs = [int(comp(hb[t])) - int(comp(model[t])) for t in ids]
            b = sum(1 for d in diffs if d > 0); cc = sum(1 for d in diffs if d < 0); lo, hi = boot(diffs)
            e.update({'model_completed': mdone, 'model_completion': round(mdone / n, 3), 'diff': round(done / n - mdone / n, 3), 'diff_lo': round(lo, 3), 'diff_hi': round(hi, 3),
                      'hybrid_only': b, 'model_only': cc, 'mcnemar_p': mcnemar(b, cc)})
            lines.append(f"| {s} | {c} | {n} | {rec} | {done} | {e['completion']} | {e['mean']} | {e['model_completion']} | {e['diff']} [{lo:.3f}, {hi:.3f}] | {e['mcnemar_p']:.2g} |")
        else:
            lines.append(f"| {s} | {c} | {n} | {rec} | {done} | {e['completion']} | {e['mean']} | - | - | - |")
        # failure classes among recognised-but-not-completed
        cls = {}
        for t in ids:
            r = hb[t]
            if r.get('completed') or comp(r): continue
            k = ('not recognised' if not r.get('recognised') else 'asked' if r.get('asked') else 'program error' if r.get('error') or r.get('codegen_error') else 'wrong edit')
            cls[k] = cls.get(k, 0) + 1
        e['failure_classes'] = cls; out[f'{s}_{c}'] = e
    if PARSER[s].exists():
        pr = rows(PARSER[s]); ids = sorted(pr); out[f'{s}_parser_alone'] = {'n': len(ids), 'recognised': sum(1 for t in ids if pr[t].get('recognised')), 'completed': sum(1 for t in ids if pr[t].get('completed') or comp(pr[t]))}
json.dump(out, open(H / 'summary_hybrid.json', 'w'), indent=1)
open(H / 'summary_hybrid.md', 'w').write('\n'.join(lines) + '\n\n' + json.dumps(out, indent=1))
print('\n'.join(lines)); print(json.dumps({k: v.get('failure_classes') for k, v in out.items() if 'failure_classes' in v}, indent=0)); print({k: v for k, v in out.items() if 'parser_alone' in k})
