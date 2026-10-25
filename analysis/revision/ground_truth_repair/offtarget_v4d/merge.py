"""merge.py <run> <model> [--apply]: merge the v4d-recomputed off-target rows.

Rows of the recomputed tasks replace the stored rows in place (same order);
every other line is kept byte-identical. The summary is rebuilt with
code/stage_c/offtarget.summarize over the full row set, with the stored
provenance fields carried over and the v4d fields added. Without --apply it
only checks and reports. Backups: *.pre_v4d (never overwritten).
"""
import json, shutil, sys
from collections import Counter
from pathlib import Path

ROOT = Path(".")
sys.path.insert(0, str(ROOT / "code"))
from stage_c.offtarget import summarize, completed_from  # noqa: E402  the original tool

R = ROOT / "runs_local/bench_v4/results"
GT = ROOT / "analysis/revision/ground_truth_repair"
D = GT / "offtarget_v4d"
run, model = sys.argv[1], sys.argv[2]
apply = "--apply" in sys.argv
od = R / run / f"offtarget_{model}"
F = D / f"{run}__{model}"
plan = json.loads((F / "plan.json").read_text())
GENERATED = {"definition", "completed_rule", "n_rows", "status", "n_no_edited_model",
             "n_edit_set_type_aliased", "edit_set_surplus", "n_underspecified",
             "gold_source", "all_evaluated", "completed", "not_completed", "timing"}

raw = (od / "offtarget_per_task.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
old_rows = [json.loads(l) for l in raw if l.strip()]
assert len(old_rows) == len(raw), "blank lines in the stored row file"
old_summary = json.loads((od / "offtarget_summary.json").read_text())
meta = {k: v for k, v in old_summary.items() if k not in GENERATED}
# the original summary logic reproduces the stored summary from the stored rows
re_old = json.loads(json.dumps(summarize(old_rows, meta)))
assert re_old == old_summary, "summarize() does not reproduce the stored summary"

new = {}
for l in open(F / "rows_only_tasks" / "offtarget_per_task.jsonl", encoding="utf-8"):
    r = json.loads(l)
    assert r["task_id"] not in new, r["task_id"]
    new[r["task_id"]] = r
assert set(new) == set(plan["recompute"]), (len(new), len(plan["recompute"]))
bad = {t: r["status"] for t, r in new.items() if r["status"] not in ("ok", "no_edited_model")}
assert not bad, bad

lines, replaced = [], 0
for line, row in zip(raw, old_rows):
    if row["task_id"] in new:
        lines.append(json.dumps(new[row["task_id"]]) + "\n"); replaced += 1
    else:
        lines.append(line)
assert replaced == len(new)
rows = [json.loads(l) for l in lines]

# verdict changes on the recomputed rows
def pos(r, k):
    return None if r["status"] != "ok" else int(r.get(k) or 0) > 0
changes = {"status": 0, "completed": 0, "off_target_count": 0,
           "off_target_count_net": 0, "off_target_count_direct": 0, "count_value": 0}
changed_tasks = []
for r in old_rows:
    t = r["task_id"]
    if t not in new:
        continue
    n = new[t]; c = []
    if r["status"] != n["status"]: changes["status"] += 1; c.append("status")
    if r["completed"] != n["completed"]: changes["completed"] += 1; c.append("completed")
    for k in ("off_target_count", "off_target_count_net", "off_target_count_direct"):
        if pos(r, k) != pos(n, k): changes[k] += 1; c.append(k + "_verdict")
    if any(r.get(k) != n.get(k) for k in ("off_target_count", "off_target_count_net",
                                          "off_target_count_direct")):
        changes["count_value"] += 1
    if c:
        changed_tasks.append({"task_id": t, "changed": c,
                              "old": {k: r.get(k) for k in ("status", "completed", "off_target_count", "off_target_count_net", "off_target_count_direct")},
                              "new": {k: n.get(k) for k in ("status", "completed", "off_target_count", "off_target_count_net", "off_target_count_direct")}})

# completed / committed flags against the final per-task file
pt = {json.loads(l)["task_id"]: json.loads(l) for l in open(R / run / f"per_task_{model}.jsonl")}
assert set(pt) == {r["task_id"] for r in rows}
def flag_mismatch(rs):
    return [r["task_id"] for r in rs if r["completed"] != completed_from(pt[r["task_id"]])]
def commit_mismatch(rs):
    return [r["task_id"] for r in rs if r["committed"] != bool(pt[r["task_id"]].get("committed"))]
mm_before, mm_after = flag_mismatch(old_rows), flag_mismatch(rows)
cm_after = commit_mismatch(rows)

def headline(s):
    out = {}
    for k in ("off_target_count", "off_target_count_net", "off_target_count_direct"):
        out[k] = s["completed"][k].get("n_with_off_target")
    return {"evaluated": s["all_evaluated"]["off_target_count"]["n"],
            "completed_edits": s["completed"]["off_target_count"]["n"],
            "completed_with_off_target": out}

meta.update({
    "v4d_recomputed_tasks": len(new),
    "v4d_recomputed_date": "2026-10-16",
    "v4d_update": {
        "note": ("Ground truths of 69 tasks regenerated (gt_fix/affected_tasks.txt) and "
                 "re-run model outputs (gt_fix/rerun_list.csv): rows of those tasks were "
                 "recomputed with gt_fix/offtarget_subset.py (code/stage_c/offtarget.py "
                 "restricted to the listed tasks) against tasks.v4d.jsonl and the final "
                 "per-task file; every other row is unchanged. This summary is "
                 "offtarget.summarize over the merged rows."),
        "tasks": str(ROOT / "runs_local/bench_v4/tasks.v4d.jsonl"),
        "per_task": str(R / run / f"per_task_{model}.jsonl"),
        "recomputed_task_ids": sorted(new),
        "kept_task_ids_no_stored_model": sorted(plan["kept"]),
        "edited_sources": dict(Counter(v.split(" ")[0] for t, v in plan["sources"].items()
                                       if t in new)),
        "earlier_count": {"directory": str(od),
                          "rows_backup": "offtarget_per_task.jsonl.pre_v4d",
                          "summary_backup": "offtarget_summary.json.pre_v4d"},
    },
})
summary = summarize(rows, meta)
report = {"run": run, "model": model, "rows": len(rows), "recomputed": len(new),
          "kept": len(plan["kept"]), "verdict_changes": changes,
          "completed_mismatch_before": len(mm_before), "completed_mismatch_after": mm_after,
          "committed_mismatch_after": cm_after,
          "mismatch_after_in_recomputed": [t for t in mm_after if t in new],
          "headline_before": headline(old_summary),
          "headline_after": headline(json.loads(json.dumps(summary))),
          "changed_tasks": changed_tasks}
if apply:
    for name in ("offtarget_per_task.jsonl", "offtarget_summary.json"):
        bak = od / (name + ".pre_v4d")
        assert not bak.exists(), f"{bak} exists"
        shutil.copy2(od / name, bak)
    tmp = od / "offtarget_per_task.jsonl.v4d_part"
    tmp.write_text("".join(lines), encoding="utf-8"); tmp.replace(od / "offtarget_per_task.jsonl")
    tmp = od / "offtarget_summary.json.v4d_part"
    tmp.write_text(json.dumps(summary, indent=1)); tmp.replace(od / "offtarget_summary.json")
    # read back: unchanged lines byte-identical, order kept, summary consistent
    back = (od / "offtarget_per_task.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
    bak = (od / "offtarget_per_task.jsonl.pre_v4d").read_text(encoding="utf-8").splitlines(keepends=True)
    assert len(back) == len(bak)
    for a, b in zip(back, bak):
        ta, tb = json.loads(a)["task_id"], json.loads(b)["task_id"]
        assert ta == tb
        assert (a == b) or (ta in new)
    rb = [json.loads(l) for l in back]
    assert json.loads((od / "offtarget_summary.json").read_text()) == json.loads(json.dumps(summarize(rb, meta)))
    report["applied"] = True
(F / "merge_report.json").write_text(json.dumps(report, indent=1))
print(json.dumps({k: v for k, v in report.items() if k != "changed_tasks"}))
