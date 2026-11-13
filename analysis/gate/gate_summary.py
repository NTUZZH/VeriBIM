"""Relation-gated and 1 cm-gated completion of one arm, from its per-task rows and its relation-gate rows.

The functions are those of the gate summary behind the paper's table of gated completion. Completed means all three
checker scores at least 0.9; relation-gated means completed and gate_pass; 1 cm means completed and every paired
target's centre error and largest dimension error at most 0.01 m. ARMS names the per-task file of each arm that the
generators in analysis/ gate. The gate rows in results/relation_gate/ were computed from the edited models, which are
not released.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOL = 0.01
ARMS = {   # arm -> per-task file, relative to the repository root
    "prac_200": "results/practitioner/stage_models/per_task_grpo_v14_c20.jsonl",
    "sub108_nolist": "results/subset108/veribim9b_without_list/per_task_grpo_v14_c20.jsonl",
}


def per_task_rows(arm: str) -> dict:
    return load_jsonl(ROOT / ARMS[arm])


def completed(row: dict) -> bool:
    """The paper's rule: every axis at least 0.9."""
    s = row.get("score") or {}
    return all((s.get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology"))


def load_jsonl(p):
    out = {}
    for l in open(p):
        if l.strip():
            r = json.loads(l)
            out[r["task_id"]] = r
    return out


def rows_of(path):
    return load_jsonl(path)


def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]


def classify(reason: str) -> str:
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
    return ";".join(sorted(set(re.findall(r"'(IfcRel\w+\.\w+)'", reason))))


def within(r, t=TOL):
    return all((a.get("pos_err_m", 0) <= t and a.get("dim_err_max_m", 0) <= t)
               for a in (r.get("abs") or []) if not a.get("mesh_missing"))


def summarize(arm, expected: dict, gate: dict):
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
                         "reason_class": " | ".join(sorted({classify(x) for x in rs})),
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
