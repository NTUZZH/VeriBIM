"""Equivalence check of the restricted (fast) fingerprints.

The off-target diff computed from restricted fingerprints must equal the diff
computed from full fingerprints, on (a) ground-truth copies with injected
changes and (b) real completed edits whose edited file is on disk.
Writes fastpath_check.json."""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import offtarget_full as O
import validate_offtarget as V

WORK = O.SCRATCH / "fastcheck"


def compare(rec, gold, edited, label):
    fi = O.source_fp(rec)
    t0 = time.time()
    fg_full, fe_full = O.fp_file(gold), O.fp_file(edited)
    t1 = time.time()
    fg_fast, fe_fast, info = O.fast_fps(rec, gold, edited, fi)
    t2 = time.time()
    a = O.diff_task(fi, fg_full, fe_full, rec)
    b = O.diff_task(fi, fg_fast, fe_fast, rec)
    keys = [k for k in a if k not in ("n_excluded_objects",)]
    diff_keys = [k for k in keys if json.dumps(a[k], sort_keys=True, default=str) !=
                 json.dumps(b[k], sort_keys=True, default=str)]
    row = {"case": label, "task_id": rec["task_id"], "identical": not diff_keys, "differing_keys": diff_keys,
           "n_any_full": a["n_any"], "n_any_fast": b["n_any"],
           "classes_full": {k: a[k] for k in ("n_geometry", "n_relation", "n_property", "n_attribute", "n_other_objects")},
           "full_s": round(t1 - t0, 1), "fast_s": round(t2 - t1, 1), **info}
    print(row, flush=True)
    return row


def injected(tasks):
    import ifcopenshell, ifcopenshell.guid
    from modifc_gen import goldlib
    out = []
    for tid in V.CONTROL_TASKS:
        r = tasks[tid]
        g = O.unpack_gold(r, WORK)
        def variant(name, fn):
            m = ifcopenshell.open(str(g)); fn(m); p = WORK / f"{tid}.{name}.ifc"; m.write(str(p))
            out.append(compare(r, g, p, f"injected:{name}")); p.unlink()
        variant("round_trip", lambda m: None)
        variant("rename", lambda m: setattr(V._unrelated(m, r), "Name", "renamed"))
        variant("move", lambda m: goldlib.translate(m, V._unrelated(m, r).GlobalId, 0.5, 0, 0))
        variant("pset", lambda m: goldlib.set_property_value(m, V._unrelated(m, r).GlobalId, "Pset_X", "N", "v",
                                                             "IfcLabel", ifcopenshell.guid.new(), ifcopenshell.guid.new()))
        variant("material", lambda m: goldlib.assign_material(m, V._unrelated(m, r).GlobalId, "Mat X",
                                                              ifcopenshell.guid.new()))
        def restorey(m):
            w = V._unrelated(m, r); rel = w.ContainedInStructure[0]
            other = next(s for s in sorted(m.by_type("IfcBuildingStorey"), key=lambda s: s.GlobalId) if s != rel.RelatingStructure)
            goldlib.move_to_storey(m, w.GlobalId, other.GlobalId, ifcopenshell.guid.new(), keep_world=True)
        variant("restorey", restorey)
        variant("newguid", lambda m: setattr(V._unrelated(m, r), "GlobalId", ifcopenshell.guid.new()))
        def hdr(m):
            m.header.file_name.name = "x.ifc"; m.by_type("IfcOwnerHistory")[0].LastModifiedDate = 1999999999
        variant("header_owner", hdr)
        g.unlink()
    return out


def real(tasks, n_max):
    rows = []
    for arm in ("gpt-5.6-luna_108", "deepseek-v4-pro_108", "claude-sonnet-5-5_108", "gemini-3.8-flash_108"):
        for r in O.arm_todo(arm):
            if r.get("edited_ifc") and Path(r["edited_ifc"]).is_file():
                rows.append((arm, r))
    # keep the smaller models so the full path stays affordable
    rows.sort(key=lambda x: Path(x[1]["edited_ifc"]).stat().st_size)
    out = []
    for arm, r in rows[:n_max]:
        rec = tasks[r["task_id"]]
        g = O.unpack_gold(rec, WORK)
        out.append(compare(rec, g, Path(r["edited_ifc"]), f"real:{arm}"))
        g.unlink()
    return out


if __name__ == "__main__":
    O._init(); tasks = O._tasks()
    res = injected(tasks) + real(tasks, int(sys.argv[1]) if len(sys.argv) > 1 else 10)
    (O.OUT / "fastpath_check.json").write_text(json.dumps(res, indent=1, default=str))
    print("ALL IDENTICAL:", all(r["identical"] for r in res), len(res))
