"""Parameterised copies of the old summary code of the engineering-validity analyses.

Each function below is the body of an old script with only its inputs and outputs turned into arguments (the old
scripts loop over hard-coded arms and write into their own results folders, so they cannot be imported for this
purpose). The source of each function is named in its docstring; the arithmetic is unchanged. The per-task analyses
themselves (relation gate, absolute errors, schema validation, clashes, whole-model diff) are not copied: vworker.py
imports and calls the old functions.
"""
from __future__ import annotations

import collections
import re

import numpy as np

AX = ("geometry", "semantics", "topology")


def completed(row: dict) -> bool:
    """checker_validity/common.completed: every axis at least 0.9 (None as 0)."""
    s = row.get("score") or {}
    return all((s.get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology"))


# ---------------------------------------------------------------- relation gate and absolute errors
def dist(values):
    """checker_validity/summarize_gate_abs.dist, unchanged."""
    v = np.asarray([x for x in values if x is not None], dtype=float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "median": float(np.median(v)), "p90": float(np.percentile(v, 90)),
            "p95": float(np.percentile(v, 95)), "p99": float(np.percentile(v, 99)),
            "max": float(v.max()),
            "share_le_1cm": float(np.mean(v <= 0.01)), "share_le_5cm": float(np.mean(v <= 0.05)),
            "share_le_10cm": float(np.mean(v <= 0.10)), "share_le_30cm": float(np.mean(v <= 0.30))}


def gate_summary(arm: str, run: str, expected: dict, rows: dict):
    """checker_validity/summarize_gate_abs.main, the body of the loop over C.ARMS for one arm (gate part).

    expected: the arm's per-task rows (task id -> row); rows: its gate rows (task id -> row of gate_abs.process).
    Returns (summary entry of gate_summary.json, rows of lost_tasks_gated.csv)."""
    n = len(expected)
    comp = [t for t, r in expected.items() if completed(r)]
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
    summary = {"run": run, "n_tasks": n,
               "completed_paper_rule": len(comp), "completed_gated": len(gated),
               "completed_gated_strict": len(strict),
               "lost": sum(1 for t in comp if t in rows and not rows[t].get("gate_pass")),
               "lost_strict": sum(1 for t in comp if t in rows and not (rows[t].get("gate_pass") and rows[t].get("gate_strict_pass", True))),
               "completed_rows_missing": sum(1 for t in comp if t not in rows),
               "rate_paper": len(comp) / n, "rate_gated": len(gated) / n,
               "rate_gated_strict": len(strict) / n,
               "by_operation": by_op, "rows_with_error": errors, "rows_missing": missing}
    lost_rows = []
    for t in comp:
        r = rows.get(t)
        if r is None:
            continue
        if not r.get("gate_pass") or not r.get("gate_strict_pass", True):
            lost_rows.append({"arm": arm, "task_id": t, "operation": r.get("operation"),
                              "edit_kind": r.get("edit_kind"),
                              "lost_under": "gate" if not r.get("gate_pass") else "strict gate only",
                              "reasons": " | ".join(r.get("gate_strict_reasons") or r.get("gate_reasons") or [r.get("error") or ""])})
    return summary, lost_rows


def abs_records(arm: str, rows: dict) -> list:
    """checker_validity/summarize_gate_abs.main, the 'analysis 2' records of one arm (rows of abs_errors_<arm>.csv)."""
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
    return recs


def abs_summary(recs: list) -> dict:
    """checker_validity/summarize_gate_abs.main, the abs_errors_summary.json block of one arm."""
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
    return block


def within_cm_share(recs: list) -> float | None:
    """macros/make_macros_rev2.py, RevAbs<arm>WithinCmPct: completed targets with
    centre error and largest dimension error both <= 1 cm, as a share (the old code read the same values back from
    abs_errors_<arm>.csv; float(r['dim_err_max_m'] or 0) there equals the float here)."""
    tg = [r for r in recs if r["completed"]]
    if not tg:
        return None
    return sum(1 for r in tg if float(r["pos_err_m"]) <= 0.01 and float(r["dim_err_max_m"] or 0) <= 0.01) / len(tg)


def abs_tolerance(rows: dict) -> dict:
    """checker_validity/abs_tolerance.py, the body of the loop over C.ARMS for one arm."""
    rows = list(rows.values())
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
    return res


# ---------------------------------------------------------------- gate_all (Table S19)
TOL = 0.01      # round4/gate_all/scripts/summarize_all.TOL


def classify_gate_reason(reason: str) -> str:
    """round4/gate_all/scripts/summarize_all.classify, unchanged."""
    if reason.startswith("new dangling relationship"):
        return "deletion leaves a relationship with an empty required end"
    if reason.startswith("orphan opening"):
        return "deletion leaves an opening that voids nothing"
    if "opening(s) the ground truth removed left in place" in reason:
        return "deletion keeps an opening the ground truth removed (strict variant only)"
    if "not contained in any spatial structure" in reason:
        return "element outside any spatial structure"
    if ": contained in " in reason:
        return "element in a different spatial container"
    if "fills no opening" in reason:
        return "door or window fills no opening"
    if "voids no element" in reason:
        return "opening of the door or window voids no element"
    if ": hosted in " in reason:
        return "door or window in a different host"
    if "no counterpart" in reason:
        return "target has no counterpart in the edited model"
    return "other: " + reason[:80]


def rel_classes(reason: str) -> str:
    """round4/gate_all/scripts/summarize_all.rel_classes, unchanged."""
    return ";".join(sorted(set(re.findall(r"'(IfcRel\w+\.\w+)'", reason))))


def within(r, t=TOL):
    """round4/gate_all/scripts/summarize_all.within, unchanged."""
    return all((a.get("pos_err_m", 0) <= t and a.get("dim_err_max_m", 0) <= t)
               for a in (r.get("abs") or []) if not a.get("mesh_missing"))


def gate_all_summary(arm, expected: dict, gate: dict):
    """round4/gate_all/scripts/summarize_all.summarize, unchanged except that C.completed is completed() above
    (the same rule). This module copies the function instead of importing summarize_all, because summarize_all
    imports common_all, whose readers point at a folder this task may not open."""
    comp = sorted(t for t, r in expected.items() if completed(r))
    missing = [t for t in comp if t not in gate]
    errors = [t for t in comp if t in gate and gate[t].get("error")]
    flag_mismatch = [t for t in comp if t in gate and gate[t].get("completed") is not True]
    gated = [t for t in comp if t in gate and gate[t].get("gate_pass")]
    strict = [t for t in gated if gate[t].get("gate_strict_pass", True)]
    cm = [t for t in comp if t in gate and not gate[t].get("error") and within(gate[t])]
    both = [t for t in gated if t in set(cm)]
    lost, lost_cm = [], []
    for t in comp:
        r = gate.get(t)
        if r is None or r.get("error"):
            continue
        if not r.get("gate_pass") or not r.get("gate_strict_pass", True):
            rs = r.get("gate_strict_reasons") or r.get("gate_reasons") or [r.get("gate") or ""]
            lost.append({"arm": arm, "task_id": t, "operation": r.get("operation"), "edit_kind": r.get("edit_kind"),
                         "lost_under": "gate" if not r.get("gate_pass") else "strict gate only",
                         "reason_class": " | ".join(sorted({classify_gate_reason(x) for x in rs})),
                         "relationships": ";".join(sorted({c for x in rs for c in rel_classes(x).split(";") if c})),
                         "reasons": " | ".join(rs)})
        if not within(r):
            bad = [a for a in (r.get("abs") or []) if not a.get("mesh_missing")
                   and not (a.get("pos_err_m", 0) <= TOL and a.get("dim_err_max_m", 0) <= TOL)]
            lost_cm.append({"arm": arm, "task_id": t, "operation": r.get("operation"), "edit_kind": r.get("edit_kind"),
                            "target_class": ";".join(sorted({a.get("class", "") for a in bad})),
                            "max_centre_err_m": round(max(a.get("pos_err_m", 0) for a in bad), 4),
                            "max_dim_err_m": round(max(a.get("dim_err_max_m", 0) for a in bad), 4),
                            "also_lost_under_gate": not r.get("gate_pass")})
    n = len(expected)
    by_class = {}
    for x in lost:
        if x["lost_under"] == "gate":
            by_class[x["reason_class"]] = by_class.get(x["reason_class"], 0) + 1
    return {"n_tasks": n, "completed": len(comp), "completed_gated": len(gated), "completed_gated_strict": len(strict),
            "completed_1cm": len(cm), "completed_gated_and_1cm": len(both),
            "removed_by_gate": len(comp) - len(gated) - len(missing) - len(errors),
            "removed_by_1cm": len(comp) - len(cm) - len(missing) - len(errors),
            "removed_by_gate_by_class": by_class,
            "rate": len(comp) / n, "rate_gated": len(gated) / n, "rate_1cm": len(cm) / n,
            "completed_rows_missing": missing, "rows_with_error": errors, "completed_flag_mismatch": flag_mismatch}, lost, lost_cm


def gate_all_cell(n, N):
    """round4/gate_all/scripts/summarize_all.main.cell, unchanged."""
    return f"{n / N:.3f} ({n:,})"


# ---------------------------------------------------------------- schema validation and clashes
def schema_summary(rows: list):
    """checker_validity/summarize_schema_clash.main, the body of the loop over C.ARMS for one arm.

    rows: the arm's rows of schema_clash.process. Returns (summary block, rows of schema_<arm>.csv,
    rows of clashes_<arm>.csv)."""
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
    return blk, srows, crows


def schema_draw(ids_sorted: list, sample: int, seed: int, take: int) -> list:
    """checker_validity/schema_clash.main, the draw of the 2,100-task sample, unchanged:
    ids = random.Random(seed).sample(sorted ids, sample); ids = ids[:take] (the first draws); sorted."""
    import random
    ids = random.Random(seed).sample(ids_sorted, sample)
    if take:
        ids = ids[:take]
    return sorted(ids)


# ---------------------------------------------------------------- relaxed reading of the under-specified tasks
def relaxed_rule(rows: dict, tasks: dict, ids: list) -> dict:
    """round4/prac_rescore/t4b_relaxed_rule.py, the per-arm body, unchanged:
    under-specified tasks of the set; completion under the published rule; and under the relaxed rule that drops the
    question-mark requirement (no commit and a missing-value word of the task's clarification keywords)."""
    def done(r):
        s = r.get('score') or {}
        return all((s.get(k) or 0) >= 0.9 for k in AX)
    U = [t for t in ids if tasks[t].get('clarification')]
    pub = sum(done(rows[t]) for t in U)
    rel, per = 0, []
    for t in U:
        r = rows[t]
        words = set(re.split(r'[^a-z0-9]+', (r.get('reply') or '').lower()))
        kw = tasks[t]['clarification'].get('keywords') or ()
        ok = bool(done(r) or (not r.get('committed') and any(k.lower() in words for k in kw)))
        rel += ok
        per.append({"task_id": t, "completed_published_rule": bool(done(r)),
                    "completed_without_question_mark_rule": ok})
    return {"n_underspecified": len(U), "completed_published_rule": pub,
            "completed_without_question_mark_rule": rel, "per_task": per}


# ---------------------------------------------------------------- totals over the stored arms, own model replaced
def gate_nine_arm_totals(other_summary: dict, other_lost: list, replace_key: str, ours_summary: dict, ours_lost: list,
                         arms108: list) -> dict:
    """make_macros_rev2.py section 10 (RevGateArms, RevGateLostTotal, RevGateLostArms, RevGateLostTasks,
    RevGateLostDeletions), with the entry `replace_key` of gate_summary.json and its rows of lost_tasks_gated.csv
    replaced by the proposed model's. arms108 is the old ARM108 list."""
    GS = dict(other_summary)
    GS[replace_key] = ours_summary
    LT = [r for r in other_lost if r["arm"] != replace_key] + [dict(r, arm=replace_key) for r in ours_lost]
    lost = sum(GS[a]['lost'] for a in arms108)
    la = [a for a in arms108 if GS[a]['lost']]
    return {"arms": len(arms108), "lost_total": lost, "lost_arms": len(la), "lost_arm_keys": la,
            "lost_tasks": len(LT), "lost_deletions": sum(1 for r in LT if r['operation'] == 'delete'),
            "lost_rows": LT}


def gate_ext_totals(table_rows: list, lost_rows: list, replace_key: str, ours_completed: int, ours_gated: int,
                    ours_lost: int, ours_lost_rows: list, local_keys: set) -> dict:
    """round4/reasoning_arm_chain/make_macros_gate_ext.py (RevGateExt*), with the
    table row and lost rows of `replace_key` replaced by the proposed model's. The old script's assertions that pin
    which arm lost what are left out (they describe the old numbers), the counts are the same expressions."""
    TR = [dict(t) for t in table_rows]
    hit = [t for t in TR if t['gate_arm'] == replace_key]
    if len(hit) != 1:
        raise ValueError(f'gate_summary_ext.json has {len(hit)} rows for {replace_key}')
    hit[0].update(completed=ours_completed, completed_gated=ours_gated, lost=ours_lost)
    L = [r for r in lost_rows if r['arm'] != replace_key] + [dict(r, arm=replace_key) for r in ours_lost_rows]
    Lg = [r for r in L if r['lost_under'] == 'gate']
    lost_total = sum(t['lost'] for t in TR)
    dele = [r for r in Lg if r['operation'] == 'delete']
    dele_comm = [r for r in dele if r['arm'] not in local_keys]
    other = [r for r in Lg if r['operation'] != 'delete']
    arms_lost = [t for t in TR if t['lost']]
    mx = max(t['lost'] for t in TR)
    return {"arms": len(TR), "lost_total": lost_total, "lost_rows_gate": len(Lg),
            "lost_deletions": len(dele), "lost_deletions_commercial": len(dele_comm),
            "lost_other": len(other), "lost_arms": len(arms_lost), "max_lost": mx,
            "max_lost_arms": [t['gate_arm'] for t in TR if t['lost'] == mx], "lost_rows": L}
