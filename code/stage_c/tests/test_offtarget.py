"""The off-target count on a synthetic building small enough to check by eye.

The input model holds one storey with a wall and a door. The ground truth
deletes the door. Three edited models are scored against it:

* the ground truth itself, which has no off-target change;
* the ground truth with the wall moved 1 m along x, which has exactly one
  off-target change, an IfcWall modified in its placement;
* the ground truth rewritten with every OwnerHistory timestamp changed, which
  must still count zero, because a write that touches only history is not a
  change to any element.

A second case adds a window placed relative to the wall. Moving the wall moves
the window with it, so both count (the window as ``placement_carried``), while
giving the wall a new but equal placement entity moves nothing and counts zero.

The full command line is also run once over the three tasks, to check the row
fields, the summary and that no input file is modified.

Run in the ``l2`` environment from the project root:

    PYTHONPATH=code:code/harness python -m pytest -q code/stage_c/tests/test_offtarget.py
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np

import ifcopenshell
import ifcopenshell.api

from stage_c import offtarget


def _building(path: Path) -> dict[str, str]:
    model = ifcopenshell.api.run("project.create_file", version="IFC4")
    project = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcProject",
                                   name="P")
    ifcopenshell.api.run("unit.assign_unit", model)
    context = ifcopenshell.api.run("context.add_context", model, context_type="Model")
    body = ifcopenshell.api.run("context.add_context", model, context_type="Model",
                                context_identifier="Body", target_view="MODEL_VIEW",
                                parent=context)
    site = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcSite", name="S")
    building = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcBuilding",
                                    name="B")
    storey = ifcopenshell.api.run("root.create_entity", model,
                                  ifc_class="IfcBuildingStorey", name="L0")
    ifcopenshell.api.run("aggregate.assign_object", model, products=[site],
                         relating_object=project)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[building],
                         relating_object=site)
    ifcopenshell.api.run("aggregate.assign_object", model, products=[storey],
                         relating_object=building)
    for product in (site, building, storey):
        ifcopenshell.api.run("geometry.edit_object_placement", model, product=product)

    wall = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWall",
                                name="W1")
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=wall,
                         matrix=np.eye(4))
    shape = ifcopenshell.api.run("geometry.add_wall_representation", model,
                                 context=body, length=5.0, height=3.0, thickness=0.2)
    ifcopenshell.api.run("geometry.assign_representation", model, product=wall,
                         representation=shape)
    ifcopenshell.api.run("spatial.assign_container", model, products=[wall],
                         relating_structure=storey)

    door = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcDoor",
                                name="D1")
    matrix = np.eye(4)
    matrix[0, 3] = 2.0
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=door,
                         matrix=matrix)
    ifcopenshell.api.run("spatial.assign_container", model, products=[door],
                         relating_structure=storey)
    person = model.createIfcPerson(FamilyName="A")
    organisation = model.createIfcOrganization(Name="O")
    user = model.createIfcPersonAndOrganization(person, organisation)
    application = model.createIfcApplication(organisation, "1", "App", "App")
    history = model.createIfcOwnerHistory(user, application, None, "ADDED", 100,
                                          user, application, 100)
    for product in model.by_type("IfcRoot"):
        product.OwnerHistory = history
    model.write(str(path))
    return {"wall": wall.GlobalId, "door": door.GlobalId}


def _delete(src: Path, dst: Path, guid: str) -> None:
    model = ifcopenshell.open(str(src))
    ifcopenshell.api.run("root.remove_product", model, product=model.by_guid(guid))
    model.write(str(dst))


def _move(src: Path, dst: Path, guid: str, dx: float) -> None:
    model = ifcopenshell.open(str(src))
    wall = model.by_guid(guid)
    matrix = np.eye(4)
    matrix[0, 3] = dx
    ifcopenshell.api.run("geometry.edit_object_placement", model, product=wall,
                         matrix=matrix)
    model.write(str(dst))


def _touch_history(src: Path, dst: Path) -> None:
    model = ifcopenshell.open(str(src))
    for history in model.by_type("IfcOwnerHistory"):
        history.LastModifiedDate = 1234567890
        history.CreationDate = 1234567
    # Renumber by rewriting into a fresh file: entity ids must not matter.
    fresh = ifcopenshell.file(schema=model.schema)
    for entity in model.by_type("IfcProject"):
        fresh.add(entity)
    for entity in model:
        fresh.add(entity)
    assert model.by_type("IfcOwnerHistory")
    fresh.write(str(dst))


def _sigs(path: Path):
    model = ifcopenshell.open(str(path))
    return model, offtarget.ProductHasher(model).signatures()[0]


def _count(inp: Path, gold: Path, edited: Path, guid: str) -> dict:
    from modifc_score.editset import build_edit_set

    model_i, sig_i = _sigs(inp)
    _, sig_g = _sigs(gold)
    model_e, sig_e = _sigs(edited)
    edit = build_edit_set(model_i, model_e, "delete", "IfcDoor", (guid,))
    return offtarget.off_target(sig_i, sig_g, sig_e, edit.guids, (guid,))


def _fixture(tmp: Path) -> dict:
    inp, gold = tmp / "input.ifc", tmp / "gold.ifc"
    guids = _building(inp)
    _delete(inp, gold, guids["door"])
    moved, same, history = tmp / "moved.ifc", tmp / "same.ifc", tmp / "history.ifc"
    _move(gold, moved, guids["wall"], 1.0)
    _delete(inp, same, guids["door"])
    _touch_history(gold, history)
    return {"input": inp, "gold": gold, "moved": moved, "same": same,
            "history": history, **guids}


def test_counts() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        f = _fixture(Path(tmp))
        moved = _count(f["input"], f["gold"], f["moved"], f["door"])
        assert moved["off_target_count"] == 1, moved
        assert moved["off_target_types"] == {"IfcWall": 1}, moved
        assert moved["off_target"][0]["guid"] == f["wall"]
        assert moved["off_target"][0]["kind"] == "modified"
        assert moved["off_target"][0]["parts"] == ["placement"], moved
        assert moved["n_covered_by_edit_set"] == 1          # the deleted door
        assert moved["off_target_count_net"] == 1

        same = _count(f["input"], f["gold"], f["same"], f["door"])
        assert same["off_target_count"] == 0, same
        assert same["n_changed_edited"] == same["n_changed_gold"] >= 1

        history = _count(f["input"], f["gold"], f["history"], f["door"])
        assert history["off_target_count"] == 0, history
        # the gold itself against the input: only the door changes
        assert history["n_changed_gold"] == 1, history


def test_door_not_deleted_is_not_off_target() -> None:
    """A model that does nothing changes nothing outside the edit."""
    with tempfile.TemporaryDirectory() as tmp:
        f = _fixture(Path(tmp))
        nothing = _count(f["input"], f["gold"], f["input"], f["door"])
        assert nothing["off_target_count"] == 0, nothing
        assert nothing["n_changed_edited"] == 0


def _with_hosted_window(src: Path, dst: Path, wall_guid: str) -> str:
    """Add a window placed relative to the wall's own placement."""
    model = ifcopenshell.open(str(src))
    wall = model.by_guid(wall_guid)
    point = model.createIfcCartesianPoint((1.0, 0.0, 0.9))
    local = model.createIfcAxis2Placement3D(point, None, None)
    placement = model.createIfcLocalPlacement(wall.ObjectPlacement, local)
    window = ifcopenshell.api.run("root.create_entity", model, ifc_class="IfcWindow",
                                  name="WIN1")
    window.ObjectPlacement = placement
    model.write(str(dst))
    return window.GlobalId


def _shift_in_place(src: Path, dst: Path, guid: str, dx: float) -> None:
    """Move an element by rewriting the location of its own placement."""
    model = ifcopenshell.open(str(src))
    relative = model.by_guid(guid).ObjectPlacement.RelativePlacement
    x, y, z = relative.Location.Coordinates
    relative.Location = model.createIfcCartesianPoint((x + dx, y, z))
    model.write(str(dst))


def _rebuild_placement(src: Path, dst: Path, guid: str) -> None:
    """Give an element a new but equal placement, orphaning its old one."""
    model = ifcopenshell.open(str(src))
    element = model.by_guid(guid)
    old = element.ObjectPlacement
    relative = old.RelativePlacement
    copy = model.createIfcAxis2Placement3D(
        model.createIfcCartesianPoint(relative.Location.Coordinates), None, None)
    element.ObjectPlacement = model.createIfcLocalPlacement(old.PlacementRelTo, copy)
    model.write(str(dst))


def test_carried_and_rebuilt_placement() -> None:
    """A hosted element moved by its host counts, a re-made placement does not."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        f = _fixture(tmp)
        inp, gold = tmp / "input2.ifc", tmp / "gold2.ifc"
        window = _with_hosted_window(f["input"], inp, f["wall"])
        _delete(inp, gold, f["door"])

        moved = tmp / "moved2.ifc"
        _shift_in_place(gold, moved, f["wall"], 0.5)
        result = _count(inp, gold, moved, f["door"])
        kinds = {o["guid"]: o["parts"] for o in result["off_target"]}
        assert result["off_target_count"] == 2, result
        assert kinds == {f["wall"]: ["placement"], window: ["placement_carried"]}, kinds
        assert result["off_target_carried"] == 1
        assert result["off_target_count_direct"] == 1

        rebuilt = tmp / "rebuilt2.ifc"
        _rebuild_placement(gold, rebuilt, f["wall"])
        result = _count(inp, gold, rebuilt, f["door"])
        assert result["off_target_count"] == 0, result


def test_cli_end_to_end() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        f = _fixture(tmp)
        tasks, rows = [], []
        for name, edited in (("T-MOVED", f["moved"]), ("T-SAME", f["same"]),
                             ("T-HISTORY", f["history"]), ("T-NOCOMMIT", f["input"])):
            tasks.append({"task_id": name, "operation": "delete", "category": "direct",
                          "edit_kind": "delete_door", "ifc_version": "IFC4",
                          "input_ifc": str(f["input"]),
                          "ground_truth_ifc": str(f["gold"]),
                          "gold_model": str(f["gold"]),
                          "target": {"entity_type": "IfcDoor", "guids": [f["door"]]}})
            (tmp / "edited" / name).mkdir(parents=True)
            copy = tmp / "edited" / name / "input.ifc"
            copy.write_bytes(Path(edited).read_bytes())
            rows.append({"task_id": name, "committed": name != "T-NOCOMMIT",
                         "score": {"geometry": 1.0, "semantics": 1.0,
                                   "topology": 0.95 if name != "T-MOVED" else 0.5,
                                   "final": 1.0}})
        (tmp / "tasks.jsonl").write_text("\n".join(json.dumps(t) for t in tasks))
        (tmp / "rows.jsonl").write_text("\n".join(json.dumps(r) for r in rows))
        stamp = {p: os.stat(p).st_mtime_ns for p in
                 [f["input"], f["gold"], tmp / "tasks.jsonl", tmp / "rows.jsonl"]}
        argv = ["--per-task", str(tmp / "rows.jsonl"), "--tasks", str(tmp / "tasks.jsonl"),
                "--edited-dir", str(tmp / "edited"), "--out-dir", str(tmp / "out"),
                "--workers", "1", "--gold-cache", str(tmp / "cache"),
                "--gold-lookup", str(tmp / "nowhere")]
        assert offtarget.main(argv) == 0
        out = {json.loads(l)["task_id"]: json.loads(l) for l in
               (tmp / "out" / "offtarget_per_task.jsonl").read_text().splitlines()}
        assert out["T-MOVED"]["off_target_count"] == 1
        assert out["T-MOVED"]["completed"] is False
        assert out["T-SAME"]["off_target_count"] == 0
        assert out["T-SAME"]["completed"] is True
        assert out["T-HISTORY"]["off_target_count"] == 0
        assert out["T-NOCOMMIT"]["status"] == "no_edited_model"
        summary = json.loads((tmp / "out" / "offtarget_summary.json").read_text())
        block = summary["all_evaluated"]["off_target_count"]
        assert block["n"] == 3 and block["n_with_off_target"] == 1
        assert summary["completed"]["off_target_count"]["n_with_off_target"] == 0
        assert summary["n_no_edited_model"] == 1
        assert summary["inputs_modified"] == []
        assert all(os.stat(p).st_mtime_ns == t for p, t in stamp.items())
        # resumable: a second invocation evaluates nothing new
        assert offtarget.main(argv) == 0
        assert len((tmp / "out" / "offtarget_per_task.jsonl").read_text().splitlines()) == 4


if __name__ == "__main__":
    test_counts()
    test_door_not_deleted_is_not_off_target()
    test_carried_and_rebuilt_placement()
    test_cli_end_to_end()
    print("ok")
