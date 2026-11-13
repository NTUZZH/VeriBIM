"""Benchmark v4c: replace the rows of the 8 replaced tasks in a per-task file by the rows of their replacements.
    python merge_v4c.py <per_task.jsonl> <reread_per_task.jsonl> <changed_ids.json>
Rows of old ids present in the file are replaced in place by the new ids' rows (tagged v4c_replacement); an old id whose
replacement row is missing from the re-read file is an error. Backup once as <file>.pre_v4c.jsonl."""
import json, os, shutil, sys
orig, rerun, changed = sys.argv[1:4]
keep = orig.replace('.jsonl', '.pre_v4c.jsonl')
if not os.path.exists(keep): shutil.copy2(orig, keep)
old2new = json.load(open(changed))
base = [json.loads(l) for l in open(orig) if l.strip()]
new = {json.loads(l)['task_id']: json.loads(l) for l in open(rerun) if l.strip()}
def done(r): return all(((r.get('score') or {}).get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology'))
out = []; n = 0
for r in base:
    if r['task_id'] in old2new:
        nid = old2new[r['task_id']]; assert nid in new, f'replacement row missing: {nid}'
        row = dict(new[nid]); row['v4c_replacement'] = r['task_id']; out.append(row); n += 1
    else: out.append(r)
assert len({r['task_id'] for r in out}) == len(out)
with open(orig, 'w') as f:
    for r in out: f.write(json.dumps(r) + '\n')
print(f'{os.path.basename(orig)}: replaced {n} rows; completion {sum(map(done, base))}/{len(base)} -> {sum(map(done, out))}/{len(out)}')
