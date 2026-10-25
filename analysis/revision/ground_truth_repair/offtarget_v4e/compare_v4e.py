"""compare_v4e.py <run> <model>: recomputed control rows (rows_controls_s*) vs the stored off-target rows.
Fields that depend on the invocation (seconds, rss_mb, peak_rss_mb, gold_source) are left out; every other
field is compared (same rule as offtarget_v4d/compare.py)."""
import json, sys
from pathlib import Path
R = Path("runs_local/bench_v4/results")
F = Path("analysis/revision/ground_truth_repair/offtarget_v4e")
run, model = sys.argv[1:3]
VOLATILE = {"seconds", "rss_mb", "peak_rss_mb", "gold_source"}
old = {json.loads(l)["task_id"]: json.loads(l)
       for l in open(R / run / f"offtarget_{model}" / "offtarget_per_task.jsonl")}
new = [json.loads(l) for p in sorted((F / f"{run}__{model}").glob("rows_controls_s*/offtarget_per_task.jsonl"))
       for l in open(p)]
same = 0
for n in new:
    o = old[n["task_id"]]
    keys = (set(o) | set(n)) - VOLATILE
    diff = sorted(k for k in keys if o.get(k) != n.get(k))
    if diff:
        print(n["task_id"], "DIFF", {k: (o.get(k), n.get(k)) if k != "off_target" else "list differs" for k in diff})
    else:
        same += 1
print(f"{run}/{model} controls: {same}/{len(new)} rows identical outside {sorted(VOLATILE)}")
