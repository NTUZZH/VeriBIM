"""Rank the hard-validation candidates and write the 300-task hard validation set.

    python rank_val_hard.py <rollouts.jsonl> <candidates.jsonl> <candidate ids.json> <target size> <output dir>

This is the ranking step of the selection run, unchanged. The stage-1 model was sampled six times per
candidate at temperature 0.8 (stage_b.cli sample, family reading, sandbox guard on), which wrote one line per
candidate with its six scored samples to <rollouts.jsonl>. A sample counts as failed unless its geometry,
semantics and topology scores are all at least 0.9. The candidates are ranked by failed samples (descending),
then by mean sampled score (ascending), then by their order in <candidate ids.json>. Every candidate with at
least one failed sample is kept, and the set is filled up to <target size> with the next candidates in the
ranking. The step writes val_hard_ids.json, val_hard_tasks.jsonl, val_hard_ranking.jsonl (every candidate in
ranking order, with its failed samples, mean sampled score and membership) and val_hard_build_report.json.

The released run used tasks/val_hard/val_hard_candidates.jsonl, tasks/val_hard/val_hard_candidate_ids.json and
a target size of 300. The sampled rollouts are not released; tasks/val_hard/val_hard_ranking.jsonl holds the two
numbers per candidate that the ranking reads.
"""
import json, sys, collections
roll, cand, ids_f, n_target, vh = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4]), sys.argv[5]
ids = json.load(open(ids_f)); order = {t: i for i, t in enumerate(ids)}
recs = {}
for l in open(cand):
    r = json.loads(l); recs[r['task_id']] = r
def completed(s):
    sc = s.get('score') or {}
    return all(sc.get(k) is not None and sc[k] >= 0.9 for k in ('geometry', 'semantics', 'topology'))
rows = []
for l in open(roll):
    r = json.loads(l)
    if r['task_id'] not in order: continue
    ss = r['samples']; nf = sum(1 for s in ss if not completed(s)); mean = sum(float(s.get('final') or 0) for s in ss) / max(1, len(ss))
    rows.append((r['task_id'], nf, mean, len(ss)))
assert len(rows) == len(ids), (len(rows), len(ids))
rows.sort(key=lambda x: (-x[1], x[2], order[x[0]]))
n_fail = sum(1 for x in rows if x[1] > 0)
keep = rows[:max(n_target, n_fail)]
keep_ids = sorted([x[0] for x in keep], key=lambda t: order[t])
json.dump(keep_ids, open(f'{vh}/val_hard_ids.json', 'w'), indent=0)
with open(f'{vh}/val_hard_tasks.jsonl', 'w') as fh:
    for t in keep_ids: fh.write(json.dumps(recs[t], ensure_ascii=False) + '\n')
with open(f'{vh}/val_hard_ranking.jsonl', 'w') as fh:
    for x in rows: fh.write(json.dumps({'task_id': x[0], 'failed_samples': x[1], 'mean_sampled_score': round(x[2], 4), 'k': x[3], 'in_val_hard': x[0] in set(keep_ids)}) + '\n')
ks = set(keep_ids)
rep = {'candidates': len(rows), 'k': rows[0][3] if rows else None, 'tasks_with_a_failed_sample': n_fail,
       'val_hard_size': len(keep_ids), 'filled_with_lowest_scoring_completed': max(0, len(keep_ids) - n_fail),
       'failed_samples_hist': dict(sorted(collections.Counter(x[1] for x in keep).items())),
       'by_version': dict(collections.Counter(recs[t]['ifc_version'] for t in keep_ids)),
       'by_operation': dict(collections.Counter(recs[t]['operation'] for t in keep_ids)),
       'by_category': dict(collections.Counter(recs[t]['category'] for t in keep_ids)),
       'by_family_top': dict(collections.Counter(recs[t].get('family') for t in keep_ids).most_common(12)),
       'candidate_completion_all_k': round(sum(1 for x in rows if x[1] == 0) / len(rows), 4)}
json.dump(rep, open(f'{vh}/val_hard_build_report.json', 'w'), indent=1); print(json.dumps(rep))
