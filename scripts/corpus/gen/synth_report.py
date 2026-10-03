"""Synthesis counts per batch and overall, from the files on disk.

accepted = unique task ids in trajectories_gold.jsonl; rejected = input ids with an outcome ok=false and no
trajectory.  Rejection classes: the IFC4+ filling defect (create_filling / replace_filling scored with
semantics 0.875) is counted apart; other reasons have their numbers replaced by N.
Every class above 2 % of the batch's input gets three examples.
usage: synth_report.py OUT_JSON DIR=INPUT [DIR=INPUT ...]
"""
import json, re, sys
from collections import Counter, defaultdict
from pathlib import Path

FILL = "filling_predefined_type_semantics_0.875 (create_filling/replace_filling)"


def cls(o):
    s = o.get("score") or {}
    if o.get("edit_kind") in ("create_filling", "replace_filling") and s.get("semantics") == 0.875:
        return FILL
    return f'{o.get("stage")}: ' + re.sub(r"-?\d+(\.\d+)?", "N", o.get("reason") or "?")


def batch(d, inp):
    d = Path(d)
    tasks = {}
    for l in open(inp):
        if l.strip():
            r = json.loads(l); tasks[r["task_id"]] = r
    acc = set()
    for l in open(d / "trajectories_gold.jsonl"):
        try: acc.add(json.loads(l)["task_id"])
        except Exception: pass
    out = {}
    for l in open(d / "outcomes_gold.jsonl"):
        try:
            o = json.loads(l); out[o["task_id"]] = o
        except Exception: pass
    rej = {t: o for t, o in out.items() if t in tasks and t not in acc and not o.get("ok")}
    missing = [t for t in tasks if t not in acc and t not in rej]
    classes = Counter(cls(o) for o in rej.values())
    examples = defaultdict(list)
    for t, o in rej.items():
        c = cls(o)
        if classes[c] > 0.02 * len(tasks) and len(examples[c]) < 3:
            examples[c].append({"task_id": t, "edit_kind": o.get("edit_kind"), "reason": o.get("reason"),
                                "score": {k: o["score"].get(k) for k in ("final", "geometry", "semantics", "topology")} if o.get("score") else None,
                                "prompt": (tasks[t].get("prompt") or "")[:300]})
    by_ver = Counter(tasks[t].get("ifc_version") for t in acc if t in tasks)
    return {"dir": str(d), "input": str(inp), "n_input": len(tasks), "accepted": len(acc & set(tasks)),
            "rejected": len(rej), "not_accounted": len(missing),
            "accept_share": round(len(acc & set(tasks)) / len(tasks), 4) if tasks else None,
            "rejection_classes": dict(classes.most_common()),
            "rejection_class_shares": {k: round(v / len(tasks), 4) for k, v in classes.most_common()},
            "examples_for_classes_over_2pct": dict(examples),
            "accepted_by_ifc_version": dict(by_ver)}


def main():
    res = [batch(*a.split("=", 1)) for a in sys.argv[2:]]
    tot = Counter()
    for r in res:
        for k in ("n_input", "accepted", "rejected", "not_accounted"): tot[k] += r[k]
        for k, v in r["rejection_classes"].items(): tot["class:" + k] += v
    rep = {"batches": res, "total": dict(tot)}
    Path(sys.argv[1]).write_text(json.dumps(rep, indent=1))
    for r in res:
        print(Path(r["dir"]).name, r["n_input"], r["accepted"], r["rejected"], r["not_accounted"])
        for k, v in list(r["rejection_classes"].items())[:6]: print("   ", v, k)


if __name__ == "__main__":
    main()
