"""Summaries of analysis 3 from results/schema_clash_<arm>.jsonl.

Writes results/schema_<arm>.csv (one row per task: error counts in source,
ground truth and output, and the new ones by rule class), results/clashes_<arm>.csv
(one row per new hard clash), and results/schema_clash_summary.json.
"""
from __future__ import annotations

import collections
import csv
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

OUT = C.OUT


def main(tags=("",)):
    summary = {}
    for arm in C.ARMS:
        for tag in tags:
            p = OUT / f"schema_clash_{arm}{tag}.jsonl"
            if not p.exists():
                continue
            rows = [json.loads(l) for l in open(p) if l.strip()]
            key = arm + tag
            srows, crows = [], []
            for r in rows:
                if r.get("error"):
                    srows.append({"task_id": r["task_id"], "error": r["error"]})
                    continue
                ng = r.get("val_new_gt") or []
                npd = r.get("val_new_pred")
                def k2(i):
                    return (i["type"], i["rule"], i["what"], i["cls"])
                cg = collections.Counter(k2(i) for i in ng)
                excess = []
                for i in (npd or []):
                    if cg[k2(i)] > 0:
                        cg[k2(i)] -= 1
                    else:
                        excess.append(i)
                s = {"task_id": r["task_id"], "operation": r["operation"], "edit_kind": r["edit_kind"],
                     "completed": r["completed"], "has_output": r["has_output"],
                     "errors_source": r.get("val_src_n"), "errors_gt": r.get("val_gt_n"),
                     "errors_output": r.get("val_pred_n"),
                     "new_errors_gt": len(ng), "new_errors_output": (len(npd) if npd is not None else None),
                     "output_errors_beyond_gt": (len(excess) if npd is not None else None),
                     "beyond_gt_rules": "; ".join(sorted({f"{i['type']}:{i['rule']}:{i['what'][:60]}" for i in excess})),
                     "new_gt_rules": "; ".join(sorted({f"{i['type']}:{i['rule']}:{i['what'][:60]}" for i in ng})),
                     "new_output_rules": "; ".join(sorted({f"{i['type']}:{i['rule']}:{i['what'][:60]}" for i in (npd or [])})),
                     "validation_error_output": r.get("val_pred_error")}
                cl = r.get("clash")
                if cl:
                    s["new_clashes_gt"] = len(cl["new_gt"])
                    s["new_clashes_output"] = len(cl["new_pred"])
                    gt_pairs = collections.Counter((x["target_class"], x["other"]) for x in cl["new_gt"])
                    beyond = 0
                    for x in cl["new_pred"]:
                        k = (x["target_class"], x["other"])
                        if gt_pairs[k] > 0:
                            gt_pairs[k] -= 1
                        else:
                            beyond += 1
                            x["beyond_gt"] = True
                    s["output_clashes_beyond_gt"] = beyond
                    s["clashes_source_targets"] = sum(1 for x in cl["source"] if not x["excluded"])
                    s["excluded_pairs_output"] = sum(1 for x in cl["pred"] if x["excluded"])
                    for side in ("gt", "pred"):
                        for x in cl[f"new_{side}"]:
                            crows.append({"task_id": r["task_id"], "operation": r["operation"],
                                          "edit_kind": r["edit_kind"], "completed": r["completed"],
                                          "model": "ground truth" if side == "gt" else "output",
                                          "element": x["target"], "element_class": x["target_class"],
                                          "other": x["other"], "other_class": x["other_class"],
                                          "other_name": x.get("other_name"),
                                          "volume_m3": x["volume_m3"],
                                          "not_in_gt": bool(x.get("beyond_gt")) if side == "pred" else None,
                                          "overlap_box_m": "x".join(str(v) for v in x["overlap_box_m"])})
                srows.append(s)
            if srows:
                keys = []
                for s in srows:
                    for k in s:
                        if k not in keys:
                            keys.append(k)
                with open(OUT / f"schema_{key}.csv", "w", newline="") as fh:
                    w = csv.DictWriter(fh, fieldnames=keys)
                    w.writeheader()
                    w.writerows(srows)
            with open(OUT / f"clashes_{key}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=["task_id", "operation", "edit_kind", "completed", "model",
                                                   "element", "element_class", "other", "other_class",
                                                   "other_name", "volume_m3", "not_in_gt", "overlap_box_m"])
                w.writeheader()
                w.writerows(crows)
            ok = [s for s in srows if "error" not in s]
            blk = {"n_tasks": len(rows), "n_errors": len(rows) - len(ok)}
            for sub, sel in (("all", lambda s: True), ("completed", lambda s: s["completed"])):
                ss = [s for s in ok if sel(s)]
                wo = [s for s in ss if s.get("errors_output") is not None]
                b = {"n": len(ss),
                     "tasks_with_new_errors_gt": sum(1 for s in ss if s.get("new_errors_gt")),
                     "tasks_with_new_errors_output": sum(1 for s in wo if s.get("new_errors_output")),
                     "n_with_output_validated": len(wo),
                     "new_errors_gt_total": sum(s.get("new_errors_gt") or 0 for s in ss),
                     "new_errors_output_total": sum(s.get("new_errors_output") or 0 for s in wo),
                     "tasks_output_errors_beyond_gt": sum(1 for s in wo if s.get("output_errors_beyond_gt")),
                     "output_errors_beyond_gt_total": sum(s.get("output_errors_beyond_gt") or 0 for s in wo)}
                wc = [s for s in ss if "new_clashes_output" in s]
                b.update({"n_with_clash_check": len(wc),
                          "tasks_with_new_clash_gt": sum(1 for s in wc if s["new_clashes_gt"]),
                          "tasks_with_new_clash_output": sum(1 for s in wc if s["new_clashes_output"]),
                          "new_clashes_gt_total": sum(s["new_clashes_gt"] for s in wc),
                          "new_clashes_output_total": sum(s["new_clashes_output"] for s in wc),
                          "tasks_output_clash_beyond_gt": sum(1 for s in wc if s["output_clashes_beyond_gt"]),
                          "output_clashes_beyond_gt_total": sum(s["output_clashes_beyond_gt"] for s in wc),
                          "tasks_output_more_new_clashes_than_gt": sum(1 for s in wc if s["new_clashes_output"] > s["new_clashes_gt"])})
                per_op = {}
                for op in ("create", "update", "delete"):
                    oo = [s for s in wc if s["operation"] == op]
                    per_op[op] = {"n": len(oo),
                                  "tasks_with_new_clash_gt": sum(1 for s in oo if s["new_clashes_gt"]),
                                  "tasks_with_new_clash_output": sum(1 for s in oo if s["new_clashes_output"]),
                                  "new_clashes_gt": sum(s["new_clashes_gt"] for s in oo),
                                  "new_clashes_output": sum(s["new_clashes_output"] for s in oo),
                                  "tasks_output_clash_beyond_gt": sum(1 for s in oo if s["output_clashes_beyond_gt"]),
                                  "tasks_output_errors_beyond_gt": sum(1 for s in wo if s["operation"] == op and s.get("output_errors_beyond_gt")),
                                  "tasks_with_new_errors_gt": sum(1 for s in ss if s["operation"] == op and s.get("new_errors_gt")),
                                  "tasks_with_new_errors_output": sum(1 for s in wo if s["operation"] == op and s.get("new_errors_output"))}
                b["per_operation"] = per_op
                rules_gt = collections.Counter()
                rules_out = collections.Counter()
                for r in rows:
                    if r.get("error") or (sub == "completed" and not r["completed"]):
                        continue
                    for i in r.get("val_new_gt") or []:
                        rules_gt[f"{i['type']}|{i['rule']}|{i['what'][:80]}"] += 1
                    for i in r.get("val_new_pred") or []:
                        rules_out[f"{i['type']}|{i['rule']}|{i['what'][:80]}"] += 1
                b["new_error_kinds_gt"] = rules_gt.most_common(15)
                b["new_error_kinds_output"] = rules_out.most_common(15)
                blk[sub] = b
            summary[key] = blk
    json.dump(summary, open(OUT / "schema_clash_summary.json", "w"), indent=1)
    print(json.dumps({k: {s: {kk: v[s][kk] for kk in ("n", "tasks_with_new_errors_gt", "tasks_with_new_errors_output",
                                                       "tasks_with_new_clash_gt", "tasks_with_new_clash_output", "tasks_output_errors_beyond_gt", "tasks_output_clash_beyond_gt")}
                          for s in ("all", "completed") if s in v} for k, v in summary.items()}, indent=1))


if __name__ == "__main__":
    main(tuple(sys.argv[1:]) or ("",))
