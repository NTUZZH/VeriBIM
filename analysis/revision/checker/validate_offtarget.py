"""Validation of the comprehensive off-target diff (offtarget_full.py).

1. Five ground-truth-versus-source pairs: the raw diff of G against I must list
   exactly the intended edit (checked against the task's edit_guids and read by
   hand in validation_pairs.txt); the off-target diff of E = G and of E = I
   (nothing done) must both be zero.
2. Injected controls: known changes written into a copy of a ground truth, each
   of which must be reported in exactly the expected class and count.

Writes validation_offtarget.json and validation_pairs.txt next to this file.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import offtarget_full as O  # noqa: E402

PAIRS = ["DOR-CRE-DIR-B16-004", "COL-UPD-DIR-B46m4-009", "DOR-UPD-SPA-B16m4X3-003",
         "COL-UPD-DIR-B46-004", "CHN-DWF-DIR-B16-004"]
CONTROL_TASKS = ["DOR-CRE-DIR-B16-004", "DOR-UPD-SPA-B16m4X3-003"]
WORK = O.SCRATCH / "val"


def counts(d: dict) -> dict:
    return {k: d[k] for k in ("n_geometry", "n_attribute", "n_relation", "n_property",
                              "n_other_objects", "n_any")}


def pairs(tasks: dict, lines: list[str]) -> list[dict]:
    out = []
    for tid in PAIRS:
        r = tasks[tid]
        g = O.unpack_gold(r, WORK)
        fi = O.fp_file(O.ROOT / r["input_ifc"])
        fg = O.fp_file(g)
        g.unlink()
        raw = O.raw_diff(fi, fg)
        eg = r.get("edit_guids") or {}
        created = {x[2] for x in raw["created"]}
        deleted = {x[2] for x in raw["deleted"]}
        modified = {x[2] for x in raw["modified"]}
        expect_created = set(eg.get("created") or ())
        expect_removed = set(eg.get("removed") or ())
        expect_touched = set(eg.get("touched") or ()) | set(eg.get("target") or ())
        prop_guids = {x[0] for x in raw["props_changed"]}
        check = {
            "created_equal_edit_guids": created == expect_created,
            "deleted_equal_edit_guids": deleted == expect_removed,
            "modified_within_touched": modified <= expect_touched,
            "property_changes_within_targets": prop_guids <= (expect_touched | expect_created | expect_removed),
            "edited_equals_gold_offtarget": counts(O.diff_task(fi, fg, fg, r))["n_any"],
            "nothing_done_offtarget": counts(O.diff_task(fi, fg, fi, r))["n_any"],
        }
        out.append({"task_id": tid, "edit_kind": r["edit_kind"], "ifc_version": r["ifc_version"],
                    "check": check, "n_created": len(created), "n_deleted": len(deleted),
                    "n_modified": len(modified), "n_edges_added": len(raw["edges_added"]),
                    "n_edges_removed": len(raw["edges_removed"]),
                    "n_props_changed": len(raw["props_changed"]),
                    "header_differs": raw["header_differs"],
                    "owner_history_differs": raw["owner_history_differs"]})
        lines.append(f"=== {tid} ({r['ifc_version']}, {r['edit_kind']})")
        lines.append(f"instruction: {r['instruction']}")
        lines.append(f"edit_guids: {json.dumps(eg)}")
        for k, v in raw.items():
            if isinstance(v, list):
                lines.append(f"  {k}: {len(v)}")
                for x in v:
                    lines.append(f"    {x}")
            else:
                lines.append(f"  {k}: {v}")
        lines.append(f"  checks: {json.dumps(check)}")
    return out


def _unrelated(model, record, cls="IfcWall"):
    """A deterministic element of the class that the task does not touch."""
    eg = record.get("edit_guids") or {}
    skip = set((record.get("target") or {}).get("guids") or ())
    for k in ("target", "touched", "created", "removed"):
        skip |= set(eg.get(k) or ())
    host = (record.get("edit_params") or {}).get("host_guid")
    if host:
        skip.add(host)
    cands = sorted((e for e in model.by_type(cls) if e.GlobalId not in skip and e.Representation),
                   key=lambda e: e.GlobalId)
    return cands[len(cands) // 2]


def controls(tasks: dict) -> list[dict]:
    import ifcopenshell
    import ifcopenshell.guid
    from modifc_gen import goldlib
    out = []
    for tid in CONTROL_TASKS:
        r = tasks[tid]
        g = O.unpack_gold(r, WORK)
        fi = O.fp_file(O.ROOT / r["input_ifc"])
        fg = O.fp_file(g)

        def run(name, expect, fn):
            m = ifcopenshell.open(str(g))
            note = fn(m)
            p = WORK / f"{tid}.{name}.ifc"
            m.write(str(p))
            fe = O.fp_file(p)
            p.unlink()
            d = O.diff_task(fi, fg, fe, r)
            got = counts(d)
            ok = all(got[k] == v for k, v in expect.items() if not k.startswith("_"))
            extra = {}
            if "_geo_min" in expect:
                ok = ok and got["n_geometry"] >= expect["_geo_min"]
            if "_rel_min" in expect:
                ok = ok and got["n_relation"] >= expect["_rel_min"] and got["n_any"] == got["n_relation"]
            if "_header" in expect:
                extra["header_differs"] = d["header_differs"]
                extra["owner_history_differs"] = d["owner_history_differs"]
                ok = ok and d["header_differs"] == expect["_header"] and \
                    d["owner_history_differs"] == expect["_owner"]
            if "_rel_ids" in expect:
                extra["relationship_ids_only"] = d["relationship_ids_only"]
                ok = ok and d["relationship_ids_only"]["in_ground_truth_not_edited"] >= 1
            out.append({"task_id": tid, "control": name, "note": note, "expected": expect,
                        "got": got, **extra, "pass": ok,
                        "items": {k: d[k][:4] for k in ("geometry", "attribute", "relation",
                                                        "property", "other_objects")}})

        run("round_trip", {"n_any": 0}, lambda m: "written unchanged")

        def rename(m):
            w = _unrelated(m, r)
            w.Name = (w.Name or "") + " renamed"
            return w.GlobalId
        run("unrelated_wall_renamed", {"n_attribute": 1, "n_any": 1}, rename)

        def tag(m):
            w = _unrelated(m, r)
            w.Tag = "X-999"
            return w.GlobalId
        run("unrelated_wall_tag", {"n_attribute": 1, "n_any": 1}, tag)

        def move(m):
            w = _unrelated(m, r)
            goldlib.translate(m, w.GlobalId, 0.5, 0.0, 0.0)
            return w.GlobalId
        # the wall plus whatever is placed relative to it
        run("unrelated_wall_moved_0.5m", {"n_relation": 0, "n_property": 0, "n_attribute": 0,
                                           "_geo_min": 1}, move)

        def prop(m):
            w = _unrelated(m, r)
            goldlib.set_property_value(m, w.GlobalId, "Pset_ValidationCheck", "Note", "check",
                                       "IfcLabel", ifcopenshell.guid.new(), ifcopenshell.guid.new())
            return f"{w.GlobalId} Pset_ValidationCheck.Note added"
        run("unrelated_property_value", {"n_property": 1, "n_any": 1}, prop)

        def restorey(m):
            w = _unrelated(m, r)
            storeys = sorted(m.by_type("IfcBuildingStorey"), key=lambda s: s.GlobalId)
            rel = w.ContainedInStructure[0]
            other = next(s for s in storeys if s != rel.RelatingStructure)
            rel.RelatedElements = tuple(x for x in rel.RelatedElements if x != w)
            m.create_entity("IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
                            OwnerHistory=rel.OwnerHistory, RelatedElements=[w], RelatingStructure=other)
            return f"{w.GlobalId} -> storey {other.Name}"
        run("unrelated_containment_changed", {"n_relation": 2, "n_any": 2}, restorey)

        def untype(m):
            for rel in sorted(m.by_type("IfcRelDefinesByType"), key=lambda x: x.GlobalId):
                for o in rel.RelatedObjects:
                    if o.GlobalId not in set(r["target"]["guids"]) and len(rel.RelatedObjects) > 1:
                        rel.RelatedObjects = tuple(x for x in rel.RelatedObjects if x != o)
                        return o.GlobalId
            return None
        run("unrelated_type_removed", {"n_relation": 1, "n_any": 1}, untype)

        def rematerial(m):
            w = _unrelated(m, r)
            had = [rel for rel in m.by_type("IfcRelAssociatesMaterial") if w in (rel.RelatedObjects or ())]
            goldlib.assign_material(m, w.GlobalId, "Validation material", ifcopenshell.guid.new())
            return f"{w.GlobalId} -> new material (had {len(had)} association)"
        run("unrelated_material_changed", {"n_attribute": 0, "n_property": 0, "_rel_min": 1}, rematerial)

        def header(m):
            m.header.file_name.name = "renamed.ifc"
            m.header.file_name.time_stamp = "2030-01-01T00:00:00"
            oh = m.by_type("IfcOwnerHistory")[0]
            oh.LastModifiedDate = 1999999999
            return "header name/time stamp and one owner history changed"
        run("header_and_owner_history", {"n_any": 0, "_header": True, "_owner": True}, header)

        def reid_rel(m):
            rel = sorted(m.by_type("IfcRelAggregates"), key=lambda x: x.GlobalId)[0]
            rel.GlobalId = ifcopenshell.guid.new()
            return "one IfcRelAggregates given a new GlobalId"
        run("relationship_new_globalid", {"n_any": 0, "_rel_ids": True}, reid_rel)

        def reid_el(m):
            w = _unrelated(m, r)
            old = w.GlobalId
            w.GlobalId = ifcopenshell.guid.new()
            return f"{old} -> {w.GlobalId}"
        run("unrelated_wall_new_globalid", {"n_geometry": 2, "n_relation": 0}, reid_el)

        def extra_wall(m):
            w = _unrelated(m, r)
            st = goldlib._containing_storey(w)
            goldlib.add_box_element(m, "IfcWall", ifcopenshell.guid.new(), "Extra", st.GlobalId,
                                    ifcopenshell.guid.new(), 0.0, 0.0, 0.0, 1.0, 0.2, 2.0)
            return "one extra wall created on a storey"
        run("extra_wall_created", {"n_geometry": 1, "n_relation": 0}, extra_wall)
        g.unlink()
    return out


def main() -> None:
    O._init()
    WORK.mkdir(parents=True, exist_ok=True)
    tasks = O.load_tasks()
    lines: list[str] = []
    res = {"pairs": pairs(tasks, lines), "controls": controls(tasks)}
    res["all_pairs_pass"] = all(all(v is True or v == 0 for v in p["check"].values()) for p in res["pairs"])
    res["all_controls_pass"] = all(c["pass"] for c in res["controls"])
    (O.OUT / "validation_offtarget.json").write_text(json.dumps(res, indent=1, default=str))
    (O.OUT / "validation_pairs.txt").write_text("\n".join(lines) + "\n")
    print(json.dumps({"pairs": [(p["task_id"], p["check"]) for p in res["pairs"]],
                      "controls": [(c["task_id"], c["control"], c["got"], c["pass"]) for c in res["controls"]],
                      "all_pairs_pass": res["all_pairs_pass"],
                      "all_controls_pass": res["all_controls_pass"]}, indent=1, default=str))


if __name__ == "__main__":
    main()
