"""The Revit-export creation functions of the helper library.

Every test builds on the Duplex apartment, the smallest source model of the
training pool that carries walls, slabs, rooms, doors and windows, in its
IFC2X3 export and in its IFC4X3 migration.  A test opens a fresh copy, calls one
function, and checks what a Revit export would hold: the typed element with its
name, tag and property sets, the type's material, and the relationships.  The
last three tests check the gold side: the same task built twice gives the same
file byte for byte, the file the library writes with fresh identifiers scores
1.0 on every axis against it under the family's reading, and the reading sees
the type and the material, so an untyped box of the same size does not.

Run with ``python -m modifc_gen.tests.test_revit_library``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import shutil
import tempfile
from pathlib import Path

import numpy as np

import ifcopenshell
import ifcopenshell.util.element as element_util

from .. import goldlib

ROOT = Path(__file__).resolve().parents[3]
IFC2X3 = ROOT / ("data/corpus/bs_community_repo/IFC 2.3.0.1 (IFC 2x3)/"
                 "Duplex Apartment/Duplex_A_20110907.ifc")
IFC4X3 = ROOT / "runs_local/corpus_v10/migrator_v2/files/B28__IFC4X3.ifc"

LEVEL_1 = "1xS3BCk291UvhgP2dvNMKI"
LEVEL_2 = "1xS3BCk291UvhgP2dvNMQJ"
DOOR_0762 = "1hOSvn6df7F8_7GcBWlS8Z"     # 762 x 2032 door, mapped body
WINDOW_0750 = "1hOSvn6df7F8_7GcBWlRLx"   # 750 x 2200 window

_MODELS: dict = {}


def lib():
    from modifc_harness import veribim_geom

    return veribim_geom


def fresh(path: Path = IFC2X3):
    """A fresh copy of a source model, parsed once and copied in memory."""
    key = str(path)
    if key not in _MODELS:
        _MODELS[key] = ifcopenshell.open(key)
    return ifcopenshell.file.from_string(_MODELS[key].to_string())


def storey(model, guid: str = LEVEL_1):
    return model.by_guid(guid)


def facing_pair(model, level):
    """Two parallel walls of a storey facing each other across 1.5 to 8 m."""
    g = lib()
    walls = sorted(g.on_storey(level, "IfcWall"), key=lambda w: w.GlobalId)
    for index, first in enumerate(walls):
        for second in walls[index + 1:]:
            try:
                run, gap, stretch, _base, _top = g._facing(first, second, level)
            except ValueError:
                continue
            if 1.5 <= gap[1] - gap[0] <= 8.0 and stretch[1] - stretch[0] > 1.0:
                return first, second
    raise AssertionError("no facing pair on the storey")


def psets(element):
    return element_util.get_psets(element, should_inherit=False)


def relations(model, ifc_class: str, element):
    return [r for r in model.by_type(ifc_class)
            if element in [getattr(r, a, None) for a in
                           ("RelatingElement", "RelatedElement",
                            "RelatedBuildingElement", "RelatingSpace",
                            "RelatedOpeningElement", "RelatingOpeningElement",
                            "RelatingBuildingElement")]
            or element in (getattr(r, "RelatedElements", None) or ())
            or element in (getattr(r, "RelatedObjects", None) or ())]


# ---------------------------------------------------------------- numbering


def test_next_tag_and_room_number():
    g = lib()
    model = fresh()
    tag = g.next_tag(model)
    assert len(tag) == 7 and tag.isdigit()
    level = storey(model)
    wall = g.add_wall_box(level, (100.0, 100.0, 0.0), (4.0, 0.2, 3.0))
    assert wall.Tag == tag
    assert g.next_tag(model) == str(int(tag) + 1)
    number = g.next_room_number(model)
    room = g.add_space_box(level, (100.0, 90.0, 0.0), (3.0, 3.0, 2.5))
    assert room.Name == number and g.next_room_number(model) != number


# ---------------------------------------------------------------- type objects


def test_revit_type_creates_then_reuses():
    g = lib()
    model = fresh(IFC4X3)
    made = g.revit_type(model, "wall", thickness=0.137)
    assert made.is_a("IfcWallType") and made.Name == "Basic Wall:Generic - 137mm"
    assert made.PredefinedType == "STANDARD"
    assert abs(g.layer_thickness(made) - 0.137) < 1e-9
    assert g.revit_type(model, "wall", thickness=0.1374) == made
    assert g.revit_type(model, "wall", thickness=0.139) != made
    slab = g.revit_type(model, "slab", thickness=0.25)
    assert slab.Name == "Floor:Generic 250mm" and slab.PredefinedType == "FLOOR"
    door = g.revit_type(model, "door", width=0.9, height=2.1)
    assert door.is_a("IfcDoorType") and door.PredefinedType == "DOOR"
    assert door.Name == "M_Door-Passage-Single-Flush:0900 x 2100mm"
    window = g.revit_type(model, "window", width=1.2, height=1.5)
    assert window.is_a("IfcWindowType") and window.Name == "M_Window-Fixed:1200 x 1500mm"


def test_revit_type_reuses_the_files_door_style():
    g = lib()
    model = fresh(IFC2X3)
    door = model.by_guid(DOOR_0762)
    style = element_util.get_type(door)
    assert g.revit_type(model, "door", width=0.765, height=2.03) == style
    created = g.revit_type(model, "door", width=0.9, height=2.1)
    assert created.is_a("IfcDoorStyle") and created.OperationType == "SINGLE_SWING_LEFT"


def test_revit_type_column_by_section():
    g = lib()
    model = fresh()
    level = storey(model)
    column = g.add_column_box(level, (100.0, 100.0, 0.0), (0.3, 0.45, 3.0))
    assert g.rectangular_section(column) == (0.3, 0.45)
    kind = element_util.get_type(column)
    assert kind.Name == "M_Concrete-Rectangular-Column:300 x 450mm"
    assert g.revit_type(model, "column", width=0.45, depth=0.3) == kind


# ---------------------------------------------------------------- property sets


def test_add_revit_psets_per_kind():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    proxy = model.create_entity("IfcWall", GlobalId=ifcopenshell.guid.new(),
                                Name="Basic Wall:Interior - 138mm:1234567")
    g.add_revit_psets(proxy, "wall", is_external=True)
    read = psets(proxy)
    assert read["Pset_WallCommon"]["Reference"] == "Interior - 138mm:1234567"
    assert read["Pset_WallCommon"]["IsExternal"] is True
    assert read["Pset_WallCommon"]["LoadBearing"] is False
    assert read["Pset_WallCommon"]["ExtendToStructure"] is False
    assert set(read) == {"Pset_WallCommon", "Pset_EnvironmentalImpactIndicators",
                         "Pset_ReinforcementBarPitchOfWall"}
    window = model.create_entity("IfcWindow", GlobalId=ifcopenshell.guid.new())
    g.add_revit_psets(window, "window", reference="1200 x 1500mm",
                      is_external=False, fire_rating="EI30")
    read = psets(window)
    assert read["Pset_WindowCommon"] == {"id": read["Pset_WindowCommon"]["id"],
                                         "IsExternal": False,
                                         "Reference": "1200 x 1500mm",
                                         "FireRating": "EI30"}
    slab = model.create_entity("IfcSlab", GlobalId=ifcopenshell.guid.new())
    g.add_revit_psets(slab, "slab", reference="Generic 200mm")
    common = psets(slab)["Pset_SlabCommon"]
    assert common["LoadBearing"] is True and common["IsExternal"] is False
    assert common["PitchAngle"] == 0.0
    assert level is not None


# ---------------------------------------------------------------- the creators


def test_add_wall_box_writes_a_revit_wall():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    first, second = facing_pair(model, level)
    spot = g.wall_between(first, second, level, 0.2)
    rooms = [r for r in g.on_storey(level, "IfcSpace")
             if g.box_in_frame(r, level) is not None][:1]
    wall = g.add_wall_box(level, spot["origin"], spot["extents"],
                          connect_to=[first, second], bounds=rooms)
    kind = element_util.get_type(wall)
    assert kind.Name == "Basic Wall:Generic - 200mm"
    assert wall.Name == "%s:%s" % (kind.Name, wall.Tag)
    assert wall.ObjectType == kind.Name and wall.PredefinedType == "STANDARD"
    identifiers = [r.RepresentationIdentifier
                   for r in wall.Representation.Representations]
    assert identifiers == ["Axis", "Body"]
    usage = element_util.get_material(wall)
    assert usage.is_a("IfcMaterialLayerSetUsage") and usage.LayerSetDirection == "AXIS2"
    assert g.storey_of(wall) == level
    paths = relations(model, "IfcRelConnectsPathElements", wall)
    assert len(paths) == 2
    assert all(p.RelatingElement == wall and p.RelatingConnectionType == "ATPATH"
               and p.RelatedConnectionType in ("ATSTART", "ATEND") for p in paths)
    boundaries = relations(model, "IfcRelSpaceBoundary", wall)
    assert [b.RelatingSpace for b in boundaries] == rooms
    assert boundaries[0].PhysicalOrVirtualBoundary == "PHYSICAL"
    lo, hi = g._storey_box(wall, level)
    assert np.allclose(lo, spot["origin"], atol=1e-6)
    assert np.allclose(hi - lo, spot["extents"], atol=1e-6)
    assert psets(wall)["Pset_WallCommon"]["Reference"] == "Generic - 200mm"


def test_wall_external_follows_the_rooms_on_its_sides():
    g = lib()
    model = fresh()
    level = storey(model)
    room = g.add_space_box(level, (100.0, 100.0, 0.0), (6.0, 4.0, 2.5))
    inside = g.add_wall_box(level, (102.9, 100.0, 0.0), (0.2, 4.0, 2.5),
                            bounds=[room])
    edge = g.add_wall_box(level, (99.8, 100.0, 0.0), (0.2, 4.0, 2.5),
                          bounds=[room])
    assert psets(inside)["Pset_WallCommon"]["IsExternal"] is False
    assert psets(edge)["Pset_WallCommon"]["IsExternal"] is True
    kinds = {b.RelatedBuildingElement.GlobalId: b.InternalOrExternalBoundary
             for b in relations(model, "IfcRelSpaceBoundary", room)}
    assert kinds == {inside.GlobalId: "INTERNAL", edge.GlobalId: "EXTERNAL"}


def test_add_slab_box():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    room = g.add_space_box(level, (100.0, 100.0, 0.0), (4.0, 4.0, 2.8))
    slab = g.add_slab_box(level, (100.0, 100.0, 2.8), (4.0, 4.0, 0.25),
                          bounds=[room])
    kind = element_util.get_type(slab)
    assert kind.Name == "Floor:Generic 250mm" and slab.PredefinedType == "FLOOR"
    assert element_util.get_material(slab).LayerSetDirection == "AXIS3"
    assert set(psets(slab)) == {"Pset_SlabCommon", "Pset_EnvironmentalImpactIndicators",
                                "Pset_ReinforcementBarPitchOfSlab"}
    boundary = relations(model, "IfcRelSpaceBoundary", slab)[0]
    assert boundary.RelatingSpace == room
    assert boundary.InternalOrExternalBoundary == "INTERNAL"
    assert g.storey_of(slab) == level


def test_add_column_box_and_column_on_top():
    g = lib()
    model = fresh(IFC4X3)
    lower, upper = storey(model), storey(model, LEVEL_2)
    below = g.add_column_box(lower, (100.0, 100.0, 0.0), (0.4, 0.4, 3.1))
    spot = g.column_on_top(below, upper, 2.9)
    assert np.allclose(spot["origin"], (100.0, 100.0, 0.0), atol=1e-6)
    assert np.allclose(spot["extents"], (0.4, 0.4, 2.9), atol=1e-6)
    above = g.add_column_box(upper, spot["origin"], spot["extents"], stands_on=below)
    assert element_util.get_type(above) == element_util.get_type(below)
    link = relations(model, "IfcRelConnectsElements", above)
    assert len(link) == 1 and link[0].RelatingElement == above \
        and link[0].RelatedElement == below and not link[0].is_a(
            "IfcRelConnectsPathElements")
    assert above.PredefinedType == "COLUMN"
    assert set(psets(above)) == {"Pset_ColumnCommon", "Pset_EnvironmentalImpactIndicators"}


def test_add_space_box_is_aggregated_not_contained():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    walls = [g.add_wall_box(level, origin, size) for origin, size in (
        ((100.0, 100.0, 0.0), (5.0, 0.2, 2.7)), ((100.0, 104.8, 0.0), (5.0, 0.2, 2.7)),
        ((100.0, 100.2, 0.0), (0.2, 4.6, 2.7)), ((104.8, 100.2, 0.0), (0.2, 4.6, 2.7)))]
    spot = g.room_inside_walls(walls, level)
    assert np.allclose(spot["origin"], (100.2, 100.2, 0.0), atol=1e-6)
    assert np.allclose(spot["extents"], (4.6, 4.6, 2.7), atol=1e-6)
    room = g.add_space_box(level, spot["origin"], spot["extents"], bounded_by=walls)
    assert not (getattr(room, "ContainedInStructure", None) or ())
    assert [r.RelatingObject for r in room.Decomposes] == [level]
    assert psets(room)["Pset_SpaceCommon"]["IsExternal"] is False
    assert len(relations(model, "IfcRelSpaceBoundary", room)) == 4
    cover = g.slab_over_walls(walls, level, 0.2)
    top = (float(storey(model, LEVEL_2).Elevation) - float(level.Elevation)) \
        * g.unit_scale(model)
    assert np.allclose(cover["origin"], (100.0, 100.0, top - 0.2), atol=1e-6)
    assert np.allclose(cover["extents"], (5.0, 5.0, 0.2), atol=1e-6)


def test_add_opening_filling_door_reuses_the_type():
    g = lib()
    model = fresh(IFC2X3)
    level = storey(model)
    reference = model.by_guid(DOOR_0762)
    host = g.filling_slot(reference)["host"]
    first, second = facing_pair(model, level)
    spot = g.opening_centred(first, reference, level)
    door = g.add_opening_filling(first, "IfcDoor", spot["origin"], spot["extents"])
    assert element_util.get_type(door) == element_util.get_type(reference)
    opening = g.opening_of(door)
    assert opening is not None and g.host_wall_of(door) == first
    assert door.ObjectPlacement.PlacementRelTo == opening.ObjectPlacement
    assert opening.ObjectPlacement.PlacementRelTo == first.ObjectPlacement
    assert not (opening.ContainedInStructure or ())
    assert g.storey_of(door) == level
    assert door.Representation.Representations[0].RepresentationType in (
        "MappedRepresentation", "SweptSolid")
    lo, hi = g._storey_box(opening, level)
    assert np.allclose(lo, spot["origin"], atol=1e-6)
    assert abs(door.OverallWidth * g.unit_scale(model) - 0.762) < 0.002
    assert set(psets(door)) == {"Pset_DoorCommon", "Pset_EnvironmentalImpactIndicators"}
    assert host is not None


def test_add_opening_filling_window_box_and_corner_from():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    reference = model.by_guid(WINDOW_0750)
    host = g.filling_slot(reference)["host"]
    beside = g.opening_beside(reference, level, 1.5, _along_word(g, host, level))
    corner = g.corner_from(host, level, (0.0, 0.0, 0.0))
    room = g.on_storey(level, "IfcSpace")[0]
    window = g.add_opening_filling(host, "IfcWindow", beside["origin"],
                                   beside["extents"], bounds=[room])
    kind = element_util.get_type(window)
    assert kind.is_a("IfcWindowType") and window.PredefinedType == "WINDOW"
    assert relations(model, "IfcRelSpaceBoundary", window)[0].RelatingSpace == room
    lo, _hi = g._storey_box(host, level)
    assert np.allclose(corner, lo, atol=1e-9)


def _along_word(g, wall, level) -> str:
    lo, hi = g._storey_box(wall, level)
    return "+x" if g._run_of(lo, hi) == 0 else "+y"


# ---------------------------------------------------------------- the placers


def test_wall_from_jamb_and_column_in_gap():
    g = lib()
    model = fresh()
    level = storey(model)
    south = g.add_wall_box(level, (100.0, 100.0, 0.0), (8.0, 0.2, 2.7))
    north = g.add_wall_box(level, (100.0, 104.0, 0.0), (8.0, 0.2, 2.7))
    door = g.add_opening_filling(south, "IfcDoor", (101.0, 100.0, 0.0),
                                 (0.9, 0.2, 2.1))
    spot = g.wall_from_jamb(door, south, north, level, 0.5, "+x", 0.15)
    assert np.allclose(spot["origin"], (102.4, 100.2, 0.0), atol=1e-6)
    assert np.allclose(spot["extents"], (0.15, 3.8, 2.7), atol=1e-6)
    east = g.add_wall_box(level, (108.6, 100.0, 0.0), (3.0, 0.2, 2.7))
    gap = g.column_in_gap(south, east, level)
    assert np.allclose(gap["origin"], (108.0, 100.0, 0.0), atol=1e-6)
    assert np.allclose(gap["extents"], (0.6, 0.2, 2.7), atol=1e-6)
    slab = g.add_slab_box(level, (100.0, 100.0, -0.2), (8.0, 4.2, 0.2))
    above = g.slab_above(slab, level, 1.0, 0.15)
    assert np.allclose(above["origin"], (100.0, 100.0, 1.0), atol=1e-6)
    assert np.allclose(above["extents"], (8.0, 4.2, 0.15), atol=1e-6)


def test_room_placers_and_the_wall_between_two_rooms():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    west = g.add_space_box(level, (100.0, 100.0, 0.0), (4.0, 5.0, 2.6))
    east = g.add_space_box(level, (104.2, 100.0, 0.0), (4.0, 5.0, 2.6))
    between = g.add_wall_box(level, (104.0, 100.0, 0.0), (0.2, 5.0, 2.6),
                             bounds=[west, east])
    assert g.find_wall_between_rooms(west, east) == between
    slab = g.slab_on_room(west, level, 0.2)
    assert np.allclose(slab["origin"], (100.0, 100.0, 2.6), atol=1e-6)
    assert np.allclose(slab["extents"], (4.0, 5.0, 0.2), atol=1e-6)
    column = g.column_in_room(west, level, 0.3, 0.4)
    assert np.allclose(column["origin"], (101.85, 102.3, 0.0), atol=1e-6)
    assert np.allclose(column["extents"], (0.3, 0.4, 2.6), atol=1e-6)
    try:
        g.find_wall_between_rooms(west, west)
    except LookupError:
        pass
    else:
        raise AssertionError("a room is not separated from itself")


def test_assign_type_takes_a_specification_and_connect_path_reads_the_end():
    g = lib()
    model = fresh(IFC4X3)
    level = storey(model)
    long_wall = g.add_wall_box(level, (100.0, 100.0, 0.0), (6.0, 0.2, 2.7))
    stub = g.add_box_element(level, "IfcWall", None, 100.2, 100.2, 0.0, 0.2, 2.0, 2.7)
    g.assign_type(stub, {"kind": "wall", "thickness": 0.2})
    assert element_util.get_type(stub) == element_util.get_type(long_wall)
    near_start = g.connect_path(stub, long_wall)
    assert near_start.RelatedConnectionType == "ATSTART"
    far = g.add_box_element(level, "IfcWall", None, 105.6, 100.2, 0.0, 0.2, 2.0, 2.7)
    assert g.connect_path(far, long_wall).RelatedConnectionType == "ATEND"


# ---------------------------------------------------------------- the gold side


def _task_build(path: Path, gold: bool):
    g = lib()
    model = fresh(path)
    level = storey(model)
    first, second = facing_pair(model, level)
    spot = g.wall_between(first, second, level, 0.2)
    if gold:
        seed = "RVW-CRE-TOP-TEST-001"
        guid = goldlib.first_free_minted(seed, lambda q: _has(model, q))
        goldlib.revit_wall(model, guid, seed, LEVEL_1, *spot["origin"],
                           *spot["extents"], [first.GlobalId, second.GlobalId], [])
    else:
        g.add_wall_box(level, spot["origin"], spot["extents"],
                       connect_to=[first, second])
    return model


def _has(model, guid: str) -> bool:
    try:
        model.by_guid(guid)
        return True
    except Exception:
        return False


def _write(model, directory: str, name: str) -> str:
    path = os.path.join(directory, name)
    model.write(path)
    return path


def test_gold_rebuilds_byte_for_byte():
    directory = tempfile.mkdtemp(prefix="revit_gold_")
    try:
        one = _write(_task_build(IFC4X3, True), directory, "a.ifc")
        two = _write(_task_build(IFC4X3, True), directory, "b.ifc")
        digest = [hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in (one, two)]
        assert digest[0] == digest[1]
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def _score(source: Path, gold: str, predicted: str, config):
    from modifc_score.model_cache import MeshCache, ModelCache
    from modifc_score.scorer import score_task
    from modifc_score.tasks import Task

    task = Task(task_id="RVW-CRE-TOP-TEST-001", operation="create",
                category="topological", input_ifc=str(source),
                ground_truth_ifc=gold, prompt="", entity_type="IfcWall",
                guids=(), tags=())
    return score_task(task, str(source), gold, predicted, config, ModelCache(4),
                      MeshCache(), geometry_mode="per_pair")


def _family_config():
    from modifc_score.config import DEFAULT_CONFIG
    from modifc_gen.revit import SCORER_SETTINGS

    return dataclasses.replace(DEFAULT_CONFIG, **SCORER_SETTINGS)


def test_library_output_scores_one_against_the_gold():
    directory = tempfile.mkdtemp(prefix="revit_score_")
    try:
        for path in (IFC2X3, IFC4X3):
            gold = _write(_task_build(path, True), directory, "gold.ifc")
            predicted = _write(_task_build(path, False), directory, "pred.ifc")
            score = _score(path, gold, predicted, _family_config())
            assert score.error is None
            assert min(score.geometry, score.semantics, score.topology) >= 0.999, score
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def test_family_reading_sees_the_type_and_material():
    g = lib()
    directory = tempfile.mkdtemp(prefix="revit_reading_")
    try:
        gold = _write(_task_build(IFC4X3, True), directory, "gold.ifc")
        model = fresh(IFC4X3)
        level = storey(model)
        first, second = facing_pair(model, level)
        spot = g.wall_between(first, second, level, 0.2)
        plain = g.add_box_element(level, "IfcWall", None, *spot["origin"],
                                  *spot["extents"])
        g.connect_path(plain, first)
        g.connect_path(plain, second)
        predicted = _write(model, directory, "plain.ifc")
        score = _score(IFC4X3, gold, predicted, _family_config())
        assert score.semantics < 0.9, score
    finally:
        shutil.rmtree(directory, ignore_errors=True)


def main() -> int:
    tests = [(name, value) for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for name, test in tests:
        try:
            test()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
