"""Summaries of analyses 1-2 from results/gate_<arm>.jsonl and results/mutation_gate.jsonl.

Writes results/gate_summary.json, results/lost_tasks_gated.csv,
results/abs_errors_<arm>.csv, results/abs_errors_summary.json,
results/mutation_gate_summary.json and results/mutation_gate_table.csv.
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


def load(arm):
    p = OUT / f"gate_{arm}.jsonl"
    if not p.exists():
        return None
    rows = {}
    for l in open(p):
        if l.strip():
            r = json.loads(l)
            rows[r["task_id"]] = r
    return rows


def dist(values):
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "median": float(np.median(v)), "p90": float(np.percentile(v, 90)),
            "p95": float(np.percentile(v, 95)), "p99": float(np.percentile(v, 99)),
            "max": float(v.max()),
            "share_le_1cm": float(np.mean(v <= 0.01)), "share_le_5cm": float(np.mean(v <= 0.05)),
            "share_le_10cm": float(np.mean(v <= 0.10)), "share_le_30cm": float(np.mean(v <= 0.30))}


def main():
    summary, lost_rows = {}, []
    abs_summary = {}
    for arm in C.ARMS:
        rows = load(arm)
        if rows is None:
            continue
        expected = C.per_task_rows(arm)
        n = len(expected)
        comp = [t for t, r in expected.items() if C.completed(r)]
        errors = [t for t, r in rows.items() if r.get("error")]
        missing = [t for t in expected if t not in rows]
        gated = [t for t in comp if t in rows and rows[t].get("gate_pass")]
        strict = [t for t in comp if t in rows and rows[t].get("gate_pass")
                  and rows[t].get("gate_strict_pass", True)]
        by_op = {}
        for op in ("create", "update", "delete"):
            ids = [t for t in expected if expected[t]["operation"] == op]
            c = [t for t in ids if t in comp]
            by_op[op] = {"n": len(ids), "completed": len(c),
                         "gated": sum(1 for t in c if t in gated),
                         "gated_strict": sum(1 for t in c if t in strict)}
        summary[arm] = {"run": "/".join(C.ARMS[arm]), "n_tasks": n,
                        "completed_paper_rule": len(comp), "completed_gated": len(gated),
                        "completed_gated_strict": len(strict),
                        "lost": sum(1 for t in comp if t in rows and not rows[t].get("gate_pass")),
                        "lost_strict": sum(1 for t in comp if t in rows and not (rows[t].get("gate_pass") and rows[t].get("gate_strict_pass", True))),
                        "completed_rows_missing": sum(1 for t in comp if t not in rows),
                        "rate_paper": len(comp) / n, "rate_gated": len(gated) / n,
                        "rate_gated_strict": len(strict) / n,
                        "by_operation": by_op, "rows_with_error": errors, "rows_missing": missing}
        for t in comp:
            r = rows.get(t)
            if r is None:
                continue
            if not r.get("gate_pass") or not r.get("gate_strict_pass", True):
                lost_rows.append({"arm": arm, "task_id": t, "operation": r.get("operation"),
                                  "edit_kind": r.get("edit_kind"),
                                  "lost_under": "gate" if not r.get("gate_pass") else "strict gate only",
                                  "reasons": " | ".join(r.get("gate_strict_reasons") or r.get("gate_reasons") or [r.get("error") or ""])})
        # analysis 2
        recs = []
        for t, r in rows.items():
            for a in r.get("abs") or []:
                if a.get("mesh_missing"):
                    continue
                recs.append({"arm": arm, "task_id": t, "operation": r["operation"],
                             "edit_kind": r["edit_kind"], "completed": r["completed"],
                             "class": a["class"], "pairing": a["pairing"],
                             "pos_err_m": a["pos_err_m"], "pos_err_xy_m": a["pos_err_xy_m"],
                             "pos_err_z_m": a["pos_err_z_m"],
                             "placement_err_m": a.get("placement_err_m"),
                             "dim_err_max_m": a["dim_err_max_m"],
                             **{f"dim_err_{k}_m": v for k, v in a["dim_err_m"].items()},
                             **{k: v for k, v in a.items() if k.startswith("gt_") and k.endswith("_m")},
                             "checker_geometry": a["checker_geometry"],
                             "checker_cd_m": a["checker_cd_m"], "checker_diag_m": a["checker_diag_m"]})
        if recs:
            keys = []
            for rec in recs:
                for k in rec:
                    if k not in keys:
                        keys.append(k)
            with open(OUT / f"abs_errors_{arm}.csv", "w", newline="") as fh:
                w = csv.DictWriter(fh, fieldnames=keys)
                w.writeheader()
                for rec in recs:
                    w.writerow(rec)
        block = {}
        for status, sel in (("completed", True), ("not_completed", False)):
            rr = [x for x in recs if bool(x["completed"]) == sel]
            blk = {"n_targets": len(rr), "n_tasks": len({x["task_id"] for x in rr}),
                   "position": dist([x["pos_err_m"] for x in rr]),
                   "dimension_max": dist([x["dim_err_max_m"] for x in rr]),
                   "placement": dist([x["placement_err_m"] for x in rr])}
            per_class = {}
            for cls in sorted({x["class"] for x in rr}):
                cr = [x for x in rr if x["class"] == cls]
                per_class[cls] = {"n_targets": len(cr),
                                  "position": dist([x["pos_err_m"] for x in cr]),
                                  "dimension_max": dist([x["dim_err_max_m"] for x in cr])}
            blk["per_class"] = per_class
            block[status] = blk
        abs_summary[arm] = block
    json.dump(summary, open(OUT / "gate_summary.json", "w"), indent=1)
    json.dump(abs_summary, open(OUT / "abs_errors_summary.json", "w"), indent=1)
    with open(OUT / "lost_tasks_gated.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["arm", "task_id", "operation", "edit_kind", "lost_under", "reasons"])
        w.writeheader()
        for r in lost_rows:
            w.writerow(r)
    # mutation
    mp = OUT / "mutation_gate.jsonl"
    if mp.exists():
        rows = [json.loads(l) for l in open(mp) if l.strip()]
        table = {}
        for pert in ("control", "containment", "filling", "wrong_host", "del_control", "del_naive"):
            rr = [r for r in rows if r.get("pert") == pert]
            ap = [r for r in rr if r.get("applied")]
            if not rr:
                continue
            table[pert] = {
                "n_rows": len(rr), "n_applied": len(ap),
                "n_not_applicable": sum(1 for r in rr if r.get("not_applicable")),
                "n_build_error": sum(1 for r in rr if r.get("build_error")),
                "accept_090": float(np.mean([r["accept_090"] for r in ap])) if ap else None,
                "accept_098": float(np.mean([r["accept_098"] for r in ap])) if ap else None,
                "gated_accept_090": float(np.mean([r["gated_accept_090"] for r in ap])) if ap else None,
                "gated_strict_accept_090": float(np.mean([r["gated_strict_accept_090"] for r in ap])) if ap else None,
                "n_accept_090": int(sum(r["accept_090"] for r in ap)),
                "n_gated_accept_090": int(sum(r["gated_accept_090"] for r in ap)),
                "gate_reasons": collections.Counter(
                    (r.get("gate_reasons") or ["passed"])[0].split(":")[0] if r.get("gate_reasons") else "passed"
                    for r in ap).most_common(),
            }
        json.dump({"n_tasks": len({r['task_id'] for r in rows}),
                   "errors": [r for r in rows if r.get("error")], "table": table},
                  open(OUT / "mutation_gate_summary.json", "w"), indent=1)
        with open(OUT / "mutation_gate_table.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["perturbation", "applied", "accepted_at_0.90_checker", "accepted_at_0.90_gated",
                        "accepted_at_0.90_gated_strict"])
            for k, v in table.items():
                w.writerow([k, v["n_applied"], v["accept_090"], v["gated_accept_090"],
                            v["gated_strict_accept_090"]])
    print(json.dumps({a: {k: s[k] for k in ("n_tasks", "completed_paper_rule", "completed_gated",
                                            "completed_gated_strict", "lost")} for a, s in summary.items()},
                     indent=1))


if __name__ == "__main__":
    main()
