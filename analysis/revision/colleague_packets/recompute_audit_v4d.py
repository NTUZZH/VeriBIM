"""Recompute the verdict-audit agreement on the repaired ground truths (tasks.v4d.jsonl).

Every audit case is scored on the file the practitioners judged (packet_key.json 'edited_file'), never on a later
re-run of the same task:
  - task whose ground truth changed in v4d (verification.gold_sha256 differs between tasks.v4c and tasks.v4d): the
    rescored row of the judged file in gt_fix/rescored/<run>/per_task_<model>_fixed.jsonl, matched on task id
    AND on the edited file path; the script stops if no such row exists or if two matching rows disagree;
  - task whose ground truth is byte-identical in v4c and v4d: the judged file's original score in packet_key.json
    stands (same file, same ground truth, same checker).
Writes packet_key_v4d.json, then re-runs collect_answers.py against that key into results_v4d/. The practitioners'
answers are unchanged; only the checker side of the comparison moves.
"""
import glob, json, os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = '.'
AXES = ('geometry', 'semantics', 'topology')
RESCORED = os.path.join(ROOT, 'analysis/revision/ground_truth_repair/rescored')
key = json.load(open(os.path.join(HERE, 'packet_key.json')))


def gold_sha(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        out[r['task_id']] = (r.get('verification') or {}).get('gold_sha256')
    return out


sha_c = gold_sha(os.path.join(ROOT, 'runs_local/bench_v4/tasks.v4c.jsonl'))
sha_d = gold_sha(os.path.join(ROOT, 'runs_local/bench_v4/tasks.v4d.jsonl'))
want = {c['task_id'] for c in key['audit'].values()}
rescored = {}
for f in sorted(glob.glob(os.path.join(RESCORED, '*', '*_fixed.jsonl'))):
    for line in open(f):
        r = json.loads(line)
        if r['task_id'] in want:
            rescored.setdefault(r['task_id'], []).append((f, r))
changed = []
for lab, c in sorted(key['audit'].items()):
    t = c['task_id']
    judged = os.path.join(ROOT, c['edited_file'])
    if sha_c[t] is None or sha_d[t] is None:
        sys.exit(f'{lab}: no gold checksum for {t}')
    if sha_c[t] == sha_d[t]:
        scores, source = dict(c['scores']), 'packet_key.json (ground truth unchanged in v4d)'
    else:
        hits = [(f, r) for f, r in rescored.get(t, []) if r.get('edited_ifc') == judged]
        if not hits:
            sys.exit(f'{lab}: ground truth changed but no rescored row for the judged file {judged}')
        vals = {tuple(round(float(r['score'][k]), 4) for k in AXES) for _, r in hits}
        if len(vals) != 1:
            sys.exit(f'{lab}: rescored rows of the judged file disagree: {vals}')
        assert all(r['task_id'] == t and r['edited_ifc'] == judged for _, r in hits)
        scores = dict(zip(AXES, vals.pop()))
        source = os.path.relpath(hits[0][0], ROOT)
    completed = all(v >= 0.9 for v in scores.values())
    verdict = 'completed' if completed else 'not completed'
    if scores != c['scores'] or verdict != c['checker_verdict']:
        changed.append((lab, t, c['arm'], c['checker_verdict'], verdict, c['scores'], scores))
    c['scores'] = scores; c['completed'] = completed; c['checker_verdict'] = verdict
    c['n_fail_axes'] = sum(v < 0.9 for v in scores.values())
    c['near_threshold'] = any(0.85 <= v <= 0.95 for v in scores.values())
    c['score_source'] = source
key['tasks_file'] = os.path.join(ROOT, 'runs_local/bench_v4/tasks.v4d.jsonl')
out_key = os.path.join(HERE, 'packet_key_v4d.json')
json.dump(key, open(out_key, 'w'), indent=1)
print(f'audit cases whose checker side changed against packet_key.json: {len(changed)}')
for ch in changed: print(' ', ch)
out = os.path.join(HERE, 'results_v4d'); os.makedirs(out, exist_ok=True)
env = dict(os.environ, VERIBIM_PACKET_KEY=out_key)
rc = subprocess.call([sys.executable, os.path.join(HERE, 'collect_answers.py'), os.path.join(HERE, 'returned_clean'), '--out', out], env=env)
print('collect_answers rc', rc)
