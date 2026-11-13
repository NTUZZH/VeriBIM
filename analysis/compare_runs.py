#!/usr/bin/env python3
"""Paired comparison of two runs of one model on the same tasks.

  usage: compare_runs.py LABEL_A RUN_A.jsonl LABEL_B RUN_B.jsonl [--out OUT.json]

A task is completed when geometry, semantics and topology all reach 0.9. Prints the completions, the tasks only
one run completes, the exact two-sided McNemar p (binomial on the discordant pairs) and the difference B minus A
with a 95 % paired bootstrap interval (10,000 resamples, seed 20261111). Stops on a different task set, a duplicate
or an unscored row.
"""
import argparse, json, math, random, sys


def load(path):
    rows = {}
    for line in open(path, encoding='utf-8'):
        if line.strip():
            r = json.loads(line)
            if r['task_id'] in rows:
                sys.exit(f'duplicate task {r["task_id"]} in {path}')
            if r.get('score') is None:
                sys.exit(f'unscored task {r["task_id"]} in {path}')
            rows[r['task_id']] = r
    return rows


def done(r):
    sc = r['score']
    return all(sc.get(k) is not None and float(sc[k]) >= 0.9 for k in ('geometry', 'semantics', 'topology'))


def mcnemar_exact(b, c):
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, p)


ap = argparse.ArgumentParser()
ap.add_argument('label_a'); ap.add_argument('run_a'); ap.add_argument('label_b'); ap.add_argument('run_b')
ap.add_argument('--out', default='')
a = ap.parse_args()
A, B = load(a.run_a), load(a.run_b)
if sorted(A) != sorted(B):
    sys.exit(f'task sets differ: {len(A)} against {len(B)}')
ids = sorted(A)
da = [done(A[t]) for t in ids]; db = [done(B[t]) for t in ids]
n = len(ids); only_a = sum(x and not y for x, y in zip(da, db)); only_b = sum(y and not x for x, y in zip(da, db))
rng = random.Random(20261111); diffs = []
pairs = list(zip(da, db))
for _ in range(10000):
    s = [pairs[rng.randrange(n)] for _ in range(n)]
    diffs.append(sum(y - x for x, y in s) / n)
diffs.sort()
out = {'n': n, a.label_a: sum(da), a.label_b: sum(db), 'only_' + a.label_a: only_a, 'only_' + a.label_b: only_b,
       'verdict_changes': only_a + only_b, 'difference_b_minus_a': (sum(db) - sum(da)) / n,
       'interval95': [diffs[249], diffs[9749]], 'mcnemar_exact_p': mcnemar_exact(only_a, only_b),
       'mean_score_a': sum(float(A[t].get('final') or 0) for t in ids) / n,
       'mean_score_b': sum(float(B[t].get('final') or 0) for t in ids) / n,
       'mean_rounds_a': sum(float(A[t].get('tool_rounds') or 0) for t in ids) / n,
       'mean_rounds_b': sum(float(B[t].get('tool_rounds') or 0) for t in ids) / n}
print(json.dumps(out, indent=1))
if a.out:
    json.dump(out, open(a.out, 'w', encoding='utf-8'), indent=1)
