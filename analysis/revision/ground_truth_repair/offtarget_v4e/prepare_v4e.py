"""Plan the v4e off-target recompute of one (run, model) folder (2026-10-16).

Rows to recompute: the deletion tasks of this (run, model) whose outputs were re-run with the
repaired library (gt_fix/rerun_list_delete_v2.csv, geom_call_ran_clean=1), restricted to the tasks
of the arm's per-task file. The edited model of each committed row is the file the FINAL per-task
row names (edited_ifc = <run>/<model>/edited/<task>/<file>); it is read from
<run>/<model>/edited_v4e.tar.gz (member edited/<task>/<file>), never from edited.tar.gz, which still
holds the superseded output under the same name. --controls N adds N committed tasks outside the
69 repaired tasks and outside both re-run lists, read from the archive their edited_ifc names
(as offtarget_v4d/prepare.py chose them), to check that the pipeline reproduces stored rows.

Nothing is extracted here: run_v4e.py extracts one task at a time. Writes
offtarget_v4e/<run>__<model>/plan.json.
"""
import argparse, csv, json
from pathlib import Path

ROOT = Path(".")
R = ROOT / "runs_local/bench_v4/results"
GT = ROOT / "analysis/revision/ground_truth_repair"

ap = argparse.ArgumentParser()
ap.add_argument("run"); ap.add_argument("model")
ap.add_argument("--controls", type=int, default=0)
args = ap.parse_args()
run, model = args.run, args.model
out = GT / "offtarget_v4e" / f"{run}__{model}"
out.mkdir(parents=True, exist_ok=True)

aff = {l.strip() for l in open(GT / "affected_tasks.txt") if l.strip()}
reruns_v4d = {r["task"] for r in csv.DictReader(open(GT / "rerun_list.csv"))}
v4e = {r["task"] for r in csv.DictReader(open(GT / "rerun_list_delete_v2.csv"))
       if r["run"] == run and r["model"] == model and r["geom_call_ran_clean"] == "1"}
pt = [json.loads(l) for l in open(R / run / f"per_task_{model}.jsonl") if l.strip()]
ptd = {r["task_id"]: r for r in pt}
recs = {}
for l in open(ROOT / "runs_local/bench_v4/tasks.v4d.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["task_id"] in ptd:
        recs[r["task_id"]] = r
old = {json.loads(l)["task_id"]: json.loads(l)
       for l in open(R / run / f"offtarget_{model}" / "offtarget_per_task.jsonl")}

want = sorted(v4e & set(ptd))
controls = []
if args.controls:
    cand = [t for t in ptd if t not in aff and t not in reruns_v4d and ptd[t].get("committed")
            and old[t]["status"] == "ok" and old[t]["committed"]
            and old[t]["edited_ifc"] == ptd[t].get("edited_ifc")
            and old[t]["score"] == {k: (ptd[t].get("score") or {}).get(k)
                                    for k in ("geometry", "semantics", "topology", "final")}
            and (Path(ptd[t]["edited_ifc"]).parent.parent.parent / "edited.tar.gz").is_file()]
    cand.sort(key=lambda t: (old[t].get("seconds") or 0, t))
    picks = [c for c in cand if (old[c].get("off_target_count") or 0) > 0][:1]
    picks += [c for c in cand if c not in picks][: args.controls - len(picks)]
    controls = sorted(picks)

def gold_name(rec):
    return Path(rec.get("gold_model") or rec["ground_truth_ifc"]).name

plan = {"run": run, "model": model, "recompute": [], "not_committed": [], "controls": controls,
        "items": {}}
for t in want + controls:
    row = ptd[t]
    stem = Path(recs[t]["input_ifc"]).stem
    item = {"list": "only_tasks" if t in want else "controls", "gold_name": gold_name(recs[t]),
            "repaired_gold": t in aff}
    if t in want:
        plan["recompute"].append(t)
    if not row.get("committed"):
        plan["not_committed"].append(t)
        item["source"] = "not committed"
        plan["items"][t] = item
        continue
    rec_path = Path(row["edited_ifc"])
    assert rec_path.name == f"{stem}.ifc", (t, rec_path)
    if t in want:
        assert str(rec_path).startswith(str(R / run / model / "edited" / t) + "/"), (t, rec_path)
        archive = R / run / model / "edited_v4e.tar.gz"
    else:
        archive = rec_path.parent.parent.parent / "edited.tar.gz"
    assert archive.is_file(), archive
    item.update(source=f"archive {archive.relative_to(R)}", archive=str(archive),
                member=f"edited/{t}/{rec_path.name}", record=str(rec_path))
    plan["items"][t] = item
(out / "plan.json").write_text(json.dumps(plan, indent=1))
print(json.dumps({"run": run, "model": model, "recompute": len(plan["recompute"]),
                  "not_committed": len(plan["not_committed"]), "controls": controls}), flush=True)
