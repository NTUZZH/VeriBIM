"""After the IFC2X3 resume: the IFC4X3 (-vh3) and IFC4 (-vh4) records of the new
candidates_v10.jsonl must equal those of candidates_v10.before_ifc2x3.jsonl, same id
set and same record content.  Exit 1 on any difference."""
import json, sys
from pathlib import Path
VH = Path("runs_local/stage_b_v10/val_hard")


def load(p):
    out = {}
    for l in open(p, encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            if r["task_id"].endswith(("-vh3", "-vh4")):
                out[r["task_id"]] = r
    return out


a = load(VH / "candidates_v10.before_ifc2x3.jsonl")
b = load(VH / "candidates_v10.jsonl")
diff = [t for t in a if t in b and a[t] != b[t]]
res = {"before": len(a), "after": len(b), "only_before": sorted(set(a) - set(b))[:5],
       "only_after": sorted(set(b) - set(a))[:5], "content_differs": diff[:5],
       "identical": set(a) == set(b) and not diff}
print(json.dumps(res))
sys.exit(0 if res["identical"] else 1)
