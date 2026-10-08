"""Survey the per-task record fields that the failure-end classes are derived from (read-only)."""
import json, glob
from collections import Counter
R = 'runs_local/bench_v4/results'
files = sorted(glob.glob(f'{R}/hosted108_lib_all/per_task_*.jsonl') + glob.glob(f'{R}/hosted108_alone_all/per_task_*.jsonl')
               + glob.glob(f'{R}/local108_*_all/per_task_*.jsonl') + [f'{R}/full_all/per_task_grpo_v10b_c10.jsonl'])
files = [f for f in files if f.count('.') == 2 or f.endswith('.jsonl') and '.pre_' not in f and '.unguarded' not in f and '.bak' not in f]
for f in files:
    if any(s in f for s in ('.pre_', '.unguarded', '.bak')):
        continue
    rows = [json.loads(l) for l in open(f) if l.strip()]
    keys = Counter(k for r in rows for k in r)
    sr = Counter(r.get('stop_reason') for r in rows)
    lastfin = Counter((r.get('finish_reasons') or ['<none>'])[-1] for r in rows)
    anyfin = Counter(x for r in rows for x in set(r.get('finish_reasons') or []))
    err = Counter(str(r.get('error'))[:60] for r in rows)
    serr = Counter(str((r.get('score') or {}).get('error'))[:50] for r in rows)
    print('==', f.replace(R + '/', ''), len(rows))
    print('  stop_reason', dict(sr))
    print('  last finish', dict(lastfin), ' any finish', dict(anyfin))
    print('  error', dict(err.most_common(8)))
    print('  score.error', dict(serr.most_common(6)))
    print('  rare keys', {k: v for k, v in keys.items() if v < len(rows)})
    print('  all keys', sorted(keys))
