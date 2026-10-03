"""Step 6 addition: the train trajectories and the validation tasks of the merge.

trajectories_v10_new_base.jsonl = every accepted trajectory of the synthesis batches whose task is in the train
split of tasks_v10_new.jsonl.  The synthesis inputs were written by merge_v10.py --one, so the trajectory ids
already carry the merge's suffix; the script checks that rather than rewriting (an id with no train task is a
hard failure).  val_tasks_v10.jsonl = the validation split of tasks_v10_new.jsonl.
"""
import json, sys
from collections import Counter
from pathlib import Path

G = Path("runs_local/corpus_v10/gen")
BATCHES = ["synth_train_ifc4x3_v2", "synth_train_ifc4_v2", "synth_train_ifc2x3_gni",
           "synth_topup_a_ifc4x3", "synth_topup_b_ifc4x3", "synth_topup_c_ifc4x3",
           "synth_topup_a_ifc4", "synth_topup_b_ifc4", "synth_topup_c_ifc4"]

#: the merge's suffix of each batch; a batch whose input was built outside merge_v10.py --one (synth_train_ifc4_v2,
#: launched separately on the unsuffixed train split) gets its ids rewritten exactly as the merge rewrites
#: them: task_id and the gold path named by it (ground_truth_ifc / gold_model).  The scratch path the trajectory
#: shows the model (a working directory named by the old id) is left as synthesized.
SUFFIX = {"synth_train_ifc4x3_v2": "x3", "synth_train_ifc4_v2": "x4", "synth_train_ifc2x3_gni": "x2g",
          "synth_topup_a_ifc4x3": "x3a", "synth_topup_b_ifc4x3": "x3b", "synth_topup_c_ifc4x3": "x3c",
          "synth_topup_a_ifc4": "x4a", "synth_topup_b_ifc4": "x4b", "synth_topup_c_ifc4": "x4c"}

tasks = [json.loads(l) for l in open(G / "tasks_v10_new.jsonl") if l.strip()]
train = {r["task_id"]: r for r in tasks if r["split"] == "train"}
val = [r for r in tasks if r["split"] == "validation"]
with open(G / "val_tasks_v10.jsonl", "w", encoding="utf-8") as h:
    for r in val:
        h.write(json.dumps(r, ensure_ascii=False) + "\n")

seen, per_batch, per_ver, orphans, dup = set(), {}, Counter(), [], 0
rewritten = Counter()
with open(G / "trajectories_v10_new_base.jsonl", "w", encoding="utf-8") as h:
    for b in BATCHES:
        n = 0
        for line in open(G / b / "trajectories_gold.jsonl", encoding="utf-8"):
            if not line.strip():
                continue
            rec = json.loads(line)
            tid = rec["task_id"]
            suf = "-" + SUFFIX[b]
            if not tid.endswith(suf):
                new = tid + suf
                for field in ("gold_model", "ground_truth_ifc"):
                    v = rec.get(field)
                    if v:
                        assert v.endswith(f"/{tid}.ifc"), (b, tid, field, v)
                        rec[field] = v[: -len(f"{tid}.ifc")] + f"{new}.ifc"
                rec["task_id"] = new
                tid = new
                line = json.dumps(rec, ensure_ascii=False) + "\n"
                rewritten[b] += 1
            if tid not in train:
                orphans.append((b, tid)); continue
            if tid in seen:
                dup += 1; continue
            seen.add(tid); n += 1
            per_ver[train[tid]["ifc_version"]] += 1
            h.write(line if line.endswith("\n") else line + "\n")
        per_batch[b] = n
no_traj = [t for t in train if t not in seen]
rep = {"train_tasks": len(train), "validation_tasks": len(val),
       "validation_by_version": dict(Counter(r["ifc_version"] for r in val)),
       "trajectories": len(seen), "per_batch": per_batch, "per_ifc_version": dict(per_ver),
       "train_tasks_without_accepted_trajectory": len(no_traj),
       "train_tasks_without_trajectory_by_version": dict(Counter(train[t]["ifc_version"] for t in no_traj)),
       "trajectories_without_a_train_task": len(orphans), "orphan_examples": orphans[:5],
       "duplicate_trajectory_ids_skipped": dup,
       "ids_rewritten_with_the_merge_suffix": dict(rewritten)}
(G / "finalize_v10_report.json").write_text(json.dumps(rep, indent=1))
print(json.dumps(rep, indent=1))
assert not orphans, "trajectories without a train task"
