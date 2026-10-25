"""Completion if an absolute tolerance were added on top of the paper's rule.

Reads results/gate_<arm>.jsonl; a completed task keeps its completion under a
tolerance t when every paired target has centre error <= t and every dimension
error <= t (deletions and clarification tasks have no geometric target and keep it).
Writes results/abs_tolerance_completion.json.
"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C

out = {}
for arm in C.ARMS:
    p = C.OUT / f"gate_{arm}.jsonl"
    if not p.exists():
        continue
    rows = [json.loads(l) for l in open(p) if l.strip()]
    comp = [r for r in rows if r.get("completed")]
    res = {"n_tasks": len(rows), "completed": len(comp)}
    for t in (0.01, 0.02, 0.05, 0.10):
        keep, lost = 0, []
        for r in comp:
            ok = all((a.get("pos_err_m", 0) <= t and a.get("dim_err_max_m", 0) <= t)
                     for a in (r.get("abs") or []) if not a.get("mesh_missing"))
            keep += ok
            if not ok:
                lost.append(r["task_id"])
        res[f"completed_within_{int(t*100)}cm"] = keep
        res[f"lost_at_{int(t*100)}cm"] = lost
    out[arm] = res
json.dump(out, open(C.OUT / "abs_tolerance_completion.json", "w"), indent=1)
for a, r in out.items():
    print(a, r["n_tasks"], r["completed"], [r[f"completed_within_{c}cm"] for c in (1, 2, 5, 10)], r["lost_at_5cm"])
