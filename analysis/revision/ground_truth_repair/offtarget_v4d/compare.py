"""compare.py <run> <model> <list>: recomputed rows vs the stored off-target rows.
Fields that depend on the invocation (seconds, rss_mb, peak_rss_mb, gold_source)
are left out; every other field is compared."""
import json, sys
from pathlib import Path
R = Path("runs_local/bench_v4/results")
F = Path("analysis/revision/ground_truth_repair/offtarget_v4d")
run, model, lst = sys.argv[1:4]
VOLATILE = {"seconds", "rss_mb", "peak_rss_mb", "gold_source"}
old = {json.loads(l)["task_id"]: json.loads(l)
       for l in open(R / run / f"offtarget_{model}" / "offtarget_per_task.jsonl")}
new = [json.loads(l) for l in open(F / f"{run}__{model}" / f"rows_{lst}" / "offtarget_per_task.jsonl")]
same = 0
for n in new:
    o = old[n["task_id"]]
    keys = (set(o) | set(n)) - VOLATILE
    diff = sorted(k for k in keys if o.get(k) != n.get(k))
    if diff:
        print(n["task_id"], "DIFF", {k: (o.get(k), n.get(k)) if k != "off_target" else "list differs" for k in diff})
    else:
        same += 1
print(f"{run}/{model} {lst}: {same}/{len(new)} rows identical outside {sorted(VOLATILE)}")
