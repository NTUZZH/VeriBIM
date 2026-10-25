"""Hand-verification aid: run the parser on one task and list what changed.

For each task id: parse the instruction, run the program in the harness
sandbox on a working copy under tmp/verify/<task_id>/, and print the products
added, removed, or changed (placement, name, predefined type, container,
materials, property values, type) between the source model and the edited
copy.  The task record is read for the instruction and the source model path
only.  Usage (PYTHONPATH=code):  python inspect_edit.py <task_id> [...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "code" / "harness"))


def snapshot(path: Path) -> dict:
    import ifcopenshell
    import ifcopenshell.util.element as ue
    import ifcopenshell.util.placement as up
    f = ifcopenshell.open(str(path))
    out = {}
    for p in f.by_type("IfcProduct"):
        if not getattr(p, "GlobalId", None) or p.is_a("IfcSpatialStructureElement") \
                and not p.is_a("IfcSpace"):
            continue
        m = up.get_local_placement(p.ObjectPlacement) if p.ObjectPlacement else np.eye(4)
        cont = ue.get_container(p)
        mats = []
        try:
            mat = ue.get_material(p)
            if mat is not None:
                mats = sorted({getattr(m_, "Name", None) or str(m_.is_a())
                               for m_ in ([mat] if not hasattr(mat, "__iter__") else mat)})
        except Exception:
            pass
        typ = ue.get_type(p)
        psets = {}
        try:
            for ps, props in ue.get_psets(p).items():
                for k, v in props.items():
                    if k != "id":
                        psets[f"{ps}.{k}"] = v
        except Exception:
            pass
        out[p.GlobalId] = {"cls": p.is_a(), "name": p.Name,
                           "pt": getattr(p, "PredefinedType", None),
                           "origin": [round(float(x), 3) for x in m[:3, 3]],
                           "xaxis": [round(float(x), 3) for x in m[:3, 0]],
                           "container": getattr(cont, "Name", None),
                           "materials": mats,
                           "type": getattr(typ, "Name", None), "psets": psets}
    return out


def diff(a: dict, b: dict) -> list[str]:
    lines = []
    for g in sorted(set(b) - set(a)):
        e = b[g]
        lines.append(f"ADDED   {e['cls']} {e['name']!r} on {e['container']!r} "
                     f"origin {e['origin']} xaxis {e['xaxis']} pt {e['pt']}")
    for g in sorted(set(a) - set(b)):
        e = a[g]
        lines.append(f"REMOVED {e['cls']} {e['name']!r} ({g})")
    for g in sorted(set(a) & set(b)):
        x, y = a[g], b[g]
        ch = []
        for k in ("name", "pt", "origin", "xaxis", "container", "materials", "type"):
            if x[k] != y[k]:
                ch.append(f"{k}: {x[k]} -> {y[k]}")
        for k in sorted(set(x["psets"]) | set(y["psets"])):
            if x["psets"].get(k) != y["psets"].get(k):
                ch.append(f"{k}: {x['psets'].get(k)!r} -> {y['psets'].get(k)!r}")
        if ch:
            lines.append(f"CHANGED {x['cls']} {x['name']!r} ({g}): " + "; ".join(ch))
    return lines


def main(ids: list[str]) -> None:
    import grammar
    import codegen
    from modifc_harness.sandbox import Sandbox
    recs = {}
    for line in (ROOT / "runs_local/bench_v4/tasks.v4c.jsonl").open(encoding="utf-8"):
        r = json.loads(line)
        if r["task_id"] in ids:
            recs[r["task_id"]] = r
    for tid in ids:
        r = recs[tid]
        src = ROOT / r["input_ifc"].replace("\\", "/")
        intent = grammar.parse(r["instruction"])
        print("=" * 100)
        print(tid, "|", r["instruction"])
        print("parsed:", intent.get("op"), json.dumps(intent.get("parse"), default=str)[:600])
        if intent.get("clarify") or not intent.get("recognised"):
            print("reply:", codegen.question(intent) if intent.get("clarify") else "unread")
            continue
        print(codegen.body(intent))
        work = HERE / "tmp" / "verify" / tid
        working = work / f"{src.stem}.ifc"
        sb = Sandbox(input_ifc=src, working_ifc=working, log_file=work / "sandbox.log")
        try:
            sb.start()
            res = sb.execute(codegen.program(intent), timeout=420.0)
            print("commits", res.commits, "error", (res.error or "")[-500:],
                  "stdout", (res.stdout or "")[-300:])
        finally:
            sb.close()
        for line in diff(snapshot(src), snapshot(working)):
            print("  ", line[:400])


if __name__ == "__main__":
    main(sys.argv[1:])
