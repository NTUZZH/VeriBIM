"""STALE-ROW variant (not merged): rows outside the v4d set whose committed flag,
score or edited model disagree with the final per-task row (outputs re-read
after the off-target count). Output under <folder>/stale/.

Prepare the v4d off-target recompute of one (run, model) folder.

Rows to recompute: the 69 tasks whose ground truth was regenerated
(gt_fix/affected_tasks.txt) plus the re-run tasks of this (run, model)
(gt_fix/rerun_list.csv), restricted to the tasks of the arm's per-task file.
The edited model of each committed row is the file the FINAL per-task row names
(edited_ifc); when that file is not on disk it is streamed out of the
edited.tar.gz of the arm folder that holds it (as gt_fix/scripts/rescore_arm.py
does) into gt_fix/offtarget_tmp/<run>__<model>/edited/<task>/. A committed row
whose model is neither on disk nor in an archive is not recomputed and keeps its
earlier off-target row (listed under "kept").

--controls N adds N unaffected committed tasks whose rows are recomputed into a
separate list (controls.txt) to check that the pipeline reproduces stored rows.

Writes <out>/only_tasks.txt, <out>/edited_map.json, <out>/plan.json.
"""
import argparse, csv, json, shutil, sys, tarfile, time
from pathlib import Path

ROOT = Path(".")
R = ROOT / "runs_local/bench_v4/results"
GT = ROOT / "analysis/revision/ground_truth_repair"
TMP = GT / "offtarget_tmp"

ap = argparse.ArgumentParser()
ap.add_argument("run"); ap.add_argument("model")
ap.add_argument("--controls", type=int, default=0)
args = ap.parse_args()
run, model = args.run, args.model
out = GT / "offtarget_v4d" / f"{run}__{model}" / "stale"
out.mkdir(parents=True, exist_ok=True)
stage = TMP / f"{run}__{model}__stale" / "edited"
stage.mkdir(parents=True, exist_ok=True)

aff = {l.strip() for l in open(GT / "affected_tasks.txt") if l.strip()}
reruns = {r["task"] for r in csv.DictReader(open(GT / "rerun_list.csv"))
          if r["run"] == run and r["model"] == model}
pt = [json.loads(l) for l in open(R / run / f"per_task_{model}.jsonl") if l.strip()]
ptd = {r["task_id"]: r for r in pt}
recs = {}
for l in open(ROOT / "runs_local/bench_v4/tasks.v4d.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["task_id"] in ptd:
        recs[r["task_id"]] = r
old = {json.loads(l)["task_id"]: json.loads(l)
       for l in open(R / run / f"offtarget_{model}" / "offtarget_per_task.jsonl")}

def _stale(t):
    p, o = ptd[t], old[t]
    sc = {k: (p.get("score") or {}).get(k) for k in ("geometry", "semantics", "topology", "final")}
    sys.path.insert(0, str(ROOT / "code")); sys.dont_write_bytecode = True
    from stage_c.offtarget import completed_from
    return (o["committed"] != bool(p.get("committed")) or o["completed"] != completed_from(p)
            or o["score"] != sc or (p.get("committed") and o["edited_ifc"] != p.get("edited_ifc")))
want = sorted(t for t in ptd if t not in (aff | reruns) and _stale(t))
controls = []
if args.controls:
    # unaffected committed tasks whose stored off-target row is ok and agrees
    # with the final per-task row (committed and score), cheapest first
    cand = [t for t in ptd if t not in aff and t not in reruns and ptd[t].get("committed")
            and old[t]["status"] == "ok" and old[t]["committed"]
            and old[t]["edited_ifc"] == ptd[t].get("edited_ifc")
            and old[t]["score"] == {k: (ptd[t].get("score") or {}).get(k)
                                    for k in ("geometry", "semantics", "topology", "final")}]
    cand.sort(key=lambda t: (old[t].get("seconds") or 0, t))
    picks = [c for c in cand if (old[c].get("off_target_count") or 0) > 0][:1]
    picks += [c for c in cand if c not in picks][: args.controls - len(picks)]
    controls = sorted(picks)

edited_map, plan = {}, {"run": run, "model": model, "recompute": [], "kept": [],
                        "not_committed": [], "controls": controls, "sources": {}}
need: dict[Path, dict[str, str]] = {}
for t in want + controls:
    row = ptd[t]
    stem = Path(recs[t]["input_ifc"]).stem
    if not row.get("committed"):
        plan["not_committed"].append(t)
        if t in want:
            plan["recompute"].append(t)
        continue
    rec_path = Path(row["edited_ifc"])
    assert rec_path.name == f"{stem}.ifc", (t, rec_path)
    if rec_path.is_file() and rec_path.stat().st_size > 0:
        edited_map[t] = {"read": str(rec_path), "record": str(rec_path)}
        plan["sources"][t] = "file"
        if t in want:
            plan["recompute"].append(t)
        continue
    archive = rec_path.parent.parent.parent / "edited.tar.gz"
    if not archive.is_file():
        if t in want:
            plan["kept"].append(t)
        else:
            controls.remove(t)
        plan["sources"][t] = f"missing archive {archive.relative_to(R)}"
        continue
    need.setdefault(archive, {})[f"edited/{t}/{rec_path.name}"] = t
    edited_map[t] = {"read": str(stage / t / rec_path.name), "record": str(rec_path)}
    plan["sources"][t] = f"archive {archive.relative_to(R)}"
    if t in want:
        plan["recompute"].append(t)

for archive, members in need.items():
    started = time.perf_counter()
    remaining = dict(members)
    todo = [m for m in members if not (stage / members[m] / Path(m).name).is_file()]
    if todo:
        remaining = {m: members[m] for m in todo}
        with tarfile.open(archive, mode="r|gz") as tar:
            for info in tar:
                if not remaining:
                    break
                t = remaining.pop(info.name, None)
                if t is None or not info.isfile():
                    continue
                target = stage / t / Path(info.name).name
                target.parent.mkdir(parents=True, exist_ok=True)
                part = target.with_suffix(".ifc.part")
                with tar.extractfile(info) as src, open(part, "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                part.rename(target)
    else:
        remaining = {}
    for m, t in remaining.items():
        # not in the archive: the row is kept, not recomputed
        edited_map.pop(t, None)
        plan["sources"][t] = f"not in archive {archive.relative_to(R)}"
        if t in plan["recompute"]:
            plan["recompute"].remove(t); plan["kept"].append(t)
        if t in controls:
            controls.remove(t)
    print(f"{archive.relative_to(R)}: {len(members) - len(remaining)}/{len(members)} "
          f"extracted in {time.perf_counter() - started:.0f}s", flush=True)

for t, m in edited_map.items():
    p = Path(m["read"])
    assert p.is_file() and p.stat().st_size > 0, t
(out / "only_tasks.txt").write_text("".join(t + "\n" for t in plan["recompute"]))
(out / "controls.txt").write_text("".join(t + "\n" for t in controls))
(out / "edited_map.json").write_text(json.dumps(edited_map, indent=1))
(out / "plan.json").write_text(json.dumps(plan, indent=1))
print(json.dumps({"run": run, "model": model, "recompute": len(plan["recompute"]),
                  "kept": len(plan["kept"]), "not_committed": len(plan["not_committed"]),
                  "controls": controls}), flush=True)
