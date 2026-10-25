"""merge_stale.py <run> <model>: merge the stale-row recompute (<folder>/stale/rows)
into the off-target rows, same rules as merge.py: replaced rows in place, every
other line byte-identical, summary = code/stage_c/offtarget.summarize over all
rows with the stored provenance carried over plus a stale_refresh block.
Backups: *.pre_stale (never overwritten)."""
import json, shutil, sys
from pathlib import Path
sys.dont_write_bytecode = True
ROOT = Path(".")
sys.path.insert(0, str(ROOT / "code"))
from stage_c.offtarget import summarize, completed_from  # noqa: E402
R = ROOT / "runs_local/bench_v4/results"
D = ROOT / "analysis/revision/ground_truth_repair/offtarget_v4d"
GENERATED = {"definition", "completed_rule", "n_rows", "status", "n_no_edited_model",
             "n_edit_set_type_aliased", "edit_set_surplus", "n_underspecified",
             "gold_source", "all_evaluated", "completed", "not_completed", "timing"}
run, model = sys.argv[1:3]
od = R / run / f"offtarget_{model}"
F = D / f"{run}__{model}" / "stale"
plan = json.loads((F / "plan.json").read_text())
raw = (od / "offtarget_per_task.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
old_rows = [json.loads(l) for l in raw]
old_summary = json.loads((od / "offtarget_summary.json").read_text())
meta = {k: v for k, v in old_summary.items() if k not in GENERATED}
assert json.loads(json.dumps(summarize(old_rows, meta))) == old_summary
new = {json.loads(l)["task_id"]: json.loads(l) for l in open(F / "rows" / "offtarget_per_task.jsonl")}
assert set(new) == set(plan["recompute"]) and not plan["kept"]
assert all(r["status"] in ("ok", "no_edited_model") for r in new.values())
lines = [json.dumps(new[r["task_id"]]) + "\n" if r["task_id"] in new else l
         for l, r in zip(raw, old_rows)]
rows = [json.loads(l) for l in lines]
meta["stale_refresh"] = {
    "date": "2026-10-16",
    "note": ("Rows whose stored committed flag, score or edited model disagreed with the "
             "final per-task row (outputs re-read after the off-target count) were "
             "recomputed with gt_fix/offtarget_subset.py against tasks.v4d.jsonl and the "
             "edited model the final per-task row names; every other row is unchanged. "
             "This summary is offtarget.summarize over the merged rows."),
    "n_rows_recomputed": len(new),
    "recomputed_task_ids": sorted(new),
    "rows_backup": "offtarget_per_task.jsonl.pre_stale",
    "summary_backup": "offtarget_summary.json.pre_stale",
}
summary = summarize(rows, meta)
for name in ("offtarget_per_task.jsonl", "offtarget_summary.json"):
    bak = od / (name + ".pre_stale")
    assert not bak.exists(), bak
    shutil.copy2(od / name, bak)
tmp = od / "offtarget_per_task.jsonl.stale_part"; tmp.write_text("".join(lines), encoding="utf-8")
tmp.replace(od / "offtarget_per_task.jsonl")
tmp = od / "offtarget_summary.json.stale_part"; tmp.write_text(json.dumps(summary, indent=1))
tmp.replace(od / "offtarget_summary.json")
# read back
back = (od / "offtarget_per_task.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
bak = (od / "offtarget_per_task.jsonl.pre_stale").read_text(encoding="utf-8").splitlines(keepends=True)
assert len(back) == len(bak)
for a, b in zip(back, bak):
    ta = json.loads(a)["task_id"]
    assert ta == json.loads(b)["task_id"] and (a == b or ta in new)
rb = [json.loads(l) for l in back]
s2 = json.loads((od / "offtarget_summary.json").read_text())
assert s2 == json.loads(json.dumps(summarize(rb, meta)))
pt = {json.loads(l)["task_id"]: json.loads(l) for l in open(R / run / f"per_task_{model}.jsonl")}
mm = [r["task_id"] for r in rb if r["completed"] != completed_from(pt[r["task_id"]])]
cm = [r["task_id"] for r in rb if r["committed"] != bool(pt[r["task_id"]].get("committed"))]
def head(s):
    return [s["completed"]["off_target_count"]["n"]] + [s["completed"][k].get("n_with_off_target") for k in
            ("off_target_count", "off_target_count_net", "off_target_count_direct")]
rep = {"run": run, "model": model, "rows": len(rb), "replaced": len(new),
       "evaluated": [old_summary["all_evaluated"]["off_target_count"]["n"], s2["all_evaluated"]["off_target_count"]["n"]],
       "before_completed_raw_net_direct": head(old_summary), "after_completed_raw_net_direct": head(s2),
       "completed_mismatch_after": mm, "committed_mismatch_after": cm}
(F / "merge_report.json").write_text(json.dumps(rep, indent=1))
print(json.dumps(rep))
