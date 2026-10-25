"""What the 108-task / note arms' off-target summaries would read if the stale rows
(outputs re-read after the count) were also replaced. Writes <folder>/stale/report.json;
the result tree is not touched."""
import json, sys, glob
from pathlib import Path
sys.dont_write_bytecode = True
sys.path.insert(0, "code")
from stage_c.offtarget import summarize, completed_from
R = Path("runs_local/bench_v4/results")
D = Path("analysis/revision/ground_truth_repair/offtarget_v4d")
def head(s):
    return {"evaluated": s["all_evaluated"]["off_target_count"]["n"],
            "completed_edits": s["completed"]["off_target_count"]["n"],
            "completed_with_off_target": {k: s["completed"][k].get("n_with_off_target") for k in
                                          ("off_target_count", "off_target_count_net", "off_target_count_direct")}}
for f in sorted(D.glob("*__*/stale")):
    run, model = f.parent.name.split("__")
    od = R / run / f"offtarget_{model}"
    rows = [json.loads(l) for l in open(od / "offtarget_per_task.jsonl")]
    s_now = json.loads((od / "offtarget_summary.json").read_text())
    rp = f / "rows" / "offtarget_per_task.jsonl"
    new = {json.loads(l)["task_id"]: json.loads(l) for l in open(rp)} if rp.exists() else {}
    want = set((f / "only_tasks.txt").read_text().split())
    assert set(new) == want, (run, model, len(new), len(want))
    merged = [new.get(r["task_id"], r) for r in rows]
    s_new = json.loads(json.dumps(summarize(merged, {})))
    pt = {json.loads(l)["task_id"]: json.loads(l) for l in open(R / run / f"per_task_{model}.jsonl")}
    mm = [r["task_id"] for r in merged if r["completed"] != completed_from(pt[r["task_id"]])]
    rep = {"run": run, "model": model, "stale_rows": len(want),
           "status_errors": [t for t, r in new.items() if r["status"] not in ("ok", "no_edited_model")],
           "headline_now": head(s_now), "headline_if_stale_replaced": head(s_new),
           "completed_mismatch_if_replaced": mm}
    (f / "report.json").write_text(json.dumps(rep, indent=1))
    print(json.dumps(rep))
