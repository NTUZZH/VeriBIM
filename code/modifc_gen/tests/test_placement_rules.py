"""The placement rules, each checked on a model built so that it must fire.

Every rule refuses a draw the generator used to accept, so each test builds a
small model where the refused situation exists, asks the rule, and then asks it
again in the situation it must let through.  The models are written to a
temporary directory because the rules read triangulated geometry, which comes
from a file rather than from an in-memory model.

Run with ``python -m modifc_gen.tests.test_placement_rules``.
"""

from __future__ import annotations

import os
import random
import shutil
import tempfile

import numpy as np

import ifcopenshell

from .. import chains, goldlib, ops, settings
from ..scene import Scene

WORK = None


# ------------------------------------------------------------ the fixtures


def empty_model():
    """A model with metres, one context, one building and one storey."""
    model = ifcopenshell.file(schema="IFC4")
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=[metre])
    context = model.create_entity(
        "IfcGeometricRepresentationContext", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5,
        WorldCoordinateSystem=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0))))
    project = model.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test",
        UnitsInContext=units, RepresentationContexts=[context])
    origin = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity("IfcCartesianPoint",
                                     Coordinates=(0.0, 0.0, 0.0)))
    building = model.create_entity(
        "IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Building",
        ObjectPlacement=model.create_entity("IfcLocalPlacement",
                                            RelativePlacement=origin))
    storey = model.create_entity(
        "IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Level 0",
        Elevation=0.0,
        ObjectPlacement=model.create_entity(
            "IfcLocalPlacement", PlacementRelTo=building.ObjectPlacement,
            RelativePlacement=origin))
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                        RelatingObject=project, RelatedObjects=[building])
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                        RelatingObject=building, RelatedObjects=[storey])
    return model, storey


def add_box(model, storey, ifc_class, x, y, z, length, width, height,
            name="Element"):
    guid = ifcopenshell.guid.new()
    goldlib.add_box_element(model, ifc_class, guid, name, storey.GlobalId,
                            ifcopenshell.guid.new(), x, y, z, length, width,
                            height)
    return guid


def furnished(n_columns=10):
    """A storey with a floor slab and enough columns to have a footprint.

    The floor runs from the origin to (20, 10) and the columns stand along its
    south edge, so a footprint exists, matter stands at known places, and the
    ground beyond (20, 10) is outside the storey.
    """
    model, storey = empty_model()
    guids = {"slab": add_box(model, storey, "IfcSlab", 0.0, 0.0, -0.2,
                             20.0, 10.0, 0.2, "Floor")}
    for i in range(n_columns):
        guids[f"column{i}"] = add_box(
            model, storey, "IfcColumn", 1.0 + 1.8 * i, 0.5, 0.0,
            0.4, 0.4, 3.0, f"Post {i}")
    return model, storey, guids


def add_wall(model, storey, x, y, z, length, thickness, height,
             base_offset=0.0, name="Wall"):
    """A wall, optionally with its extrusion starting above its own origin."""
    guid = add_box(model, storey, "IfcWall", x, y, z, length, thickness,
                   height, name)
    if base_offset:
        wall = model.by_guid(guid)
        solid = goldlib.sole_extrusion(model, wall)
        solid.Position.Location.Coordinates = (0.0, 0.0, base_offset)
    return guid


def save(model, name):
    path = os.path.join(WORK, name)
    model.write(path)
    return Scene(path)


def rng_of(seed=1):
    return random.Random(seed)


# ---------------------------------------------------------------- the rules


def test_created_box_that_occupies_matter_is_refused():
    model, storey, guids = furnished()
    scene = save(model, "collide.ifc")
    storey = scene.by_guid(storey.GlobalId)
    # A new column right where an existing one stands.
    fault = ops.spot_fault(scene, storey, 1.0, 0.5, 0.0, (0.4, 0.4, 3.0))
    assert fault == "created_element_collides", fault
    # The same column two metres north of it, where nothing stands.
    assert ops.spot_fault(scene, storey, 1.0, 4.0, 0.0, (0.4, 0.4, 3.0)) is None


def test_created_box_outside_the_storey_footprint_is_refused():
    model, storey, _guids = furnished()
    scene = save(model, "outside.ifc")
    storey = scene.by_guid(storey.GlobalId)
    fault = ops.spot_fault(scene, storey, 40.0, 4.0, 0.0, (0.4, 0.4, 3.0))
    assert fault == "created_outside_storey", fault
    footprint = scene.storey_local_footprint(storey)
    assert footprint is not None
    assert float(footprint.hi[0]) < 40.0


def test_free_spot_redraws_and_then_refuses():
    """A storey whose whole extent is filled yields no spot at all."""
    model, storey = empty_model()
    add_box(model, storey, "IfcSlab", 0.0, 0.0, -0.2, 20.0, 10.0, 0.2, "Floor")
    for i in range(9):
        add_box(model, storey, "IfcSlab", 2.0 * i, 1.0 * i, 0.0, 6.0, 10.0,
                6.0, f"Block {i}")
    scene = save(model, "full.ifc")
    storey = scene.by_guid(storey.GlobalId)
    ops.reset_rejections()
    spot = ops.free_spot(scene, storey, (4.0, 4.0), rng_of(3), 3.0, 0.0)
    assert spot is None
    assert ops.rejection_counts().get("created_element_collides", 0) >= 1


def test_a_wall_too_short_for_the_leaf_hosts_no_filling():
    model, storey, _guids = furnished()
    short = add_wall(model, storey, 2.0, 4.0, 0.0, 6.0, 0.2, 1.60, name="Low")
    tall = add_wall(model, storey, 2.0, 6.0, 0.0, 6.0, 0.2, 3.00, name="High")
    scene = save(model, "short.ifc")
    ops.reset_rejections()
    plan = ops.plan_create_filling(scene, "door", scene.by_guid(short), "T-1",
                                   rng_of(5))
    assert plan is None
    assert ops.rejection_counts().get("filling_taller_than_wall", 0) == 1
    assert ops.plan_create_filling(scene, "door", scene.by_guid(tall), "T-2",
                                   rng_of(5)) is not None


def test_the_sill_is_measured_from_the_base_of_the_wall_extrusion():
    model, storey, _guids = furnished()
    lifted = add_wall(model, storey, 2.0, 4.0, 0.0, 6.0, 0.2, 3.0,
                      base_offset=1.5, name="Lifted")
    scene = save(model, "lifted.ifc")
    wall = scene.by_guid(lifted)
    assert abs(float(scene.local_extent(wall).lo[2]) - 1.5) < 1e-6
    plan = ops.plan_create_filling(scene, "window", wall, "T-3", rng_of(5))
    assert plan is not None
    # The eleventh argument of add_filling is the base of the opening, given in
    # the wall's own axes.
    base = plan.calls[0].args[10]
    assert abs(base - (1.5 + ops.CREATE_FILLING["window"][2])) < 1e-6, base


def test_a_new_filling_clears_the_fillings_the_wall_already_carries():
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    # An existing door across the whole band the draw takes its position from.
    goldlib.add_filling(model, "IfcDoor", ifcopenshell.guid.new(), "Old door",
                        wall, ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        1.6, -0.05, 0.0, 4.0, 2.1, 0.3, None, 0.0, 0.2)
    scene = save(model, "occupied.ifc")
    ops.reset_rejections()
    slot = ops.wall_opening_slot(scene, scene.by_guid(wall), 0.9, 2.1, 0.0,
                                 rng_of(11))
    assert ops.rejection_counts().get("filling_overlaps_filling", 0) >= 1
    if slot is not None:
        along = slot[0]
        assert along >= 1.6 + 4.0 + ops.FILLING_CLEARANCE \
            or along + 0.9 <= 1.6 - ops.FILLING_CLEARANCE, along


def test_a_moved_door_takes_its_opening_with_it():
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    door = ifcopenshell.guid.new()
    opening = ifcopenshell.guid.new()
    goldlib.add_filling(model, "IfcDoor", door, "Door", wall, opening,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), 1.0, -0.05, 0.0, 0.9, 2.1,
                        0.3, None, 0.0, 0.2)
    scene = save(model, "carry.ifc")
    plan = ops.plan_translate(scene, scene.by_guid(door), rng_of(2))
    assert plan is not None
    assert [c.args[0] for c in plan.calls] == [door, opening]
    assert plan.calls[0].args[1:] == plan.calls[1].args[1:]


def _wall_with_a_door_near_its_end(model, storey, along=6.8):
    """An eight-metre wall whose door sits near the far end of it."""
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    door = ifcopenshell.guid.new()
    opening = ifcopenshell.guid.new()
    goldlib.add_filling(model, "IfcDoor", door, "Door", wall, opening,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), along, -0.05, 0.0, 0.9, 2.1,
                        0.3, None, 0.0, 0.2)
    return wall, door, opening


def test_a_resize_that_would_strand_a_filling_is_refused():
    """0.7.2: a wall that loses length or height leaves its door outside it.

    The physical audit of the v2 wave found seven gold models where a resize
    had done exactly that, so the rule is measured here on a wall built to
    show it: the door runs from 6.8 m to 7.7 m along an eight-metre wall and
    stands 2.1 m tall inside a wall 3 m tall.
    """
    model, storey, _guids = furnished()
    wall, _door, _opening = _wall_with_a_door_near_its_end(model, storey)
    scene = save(model, "resize_strand.ifc")
    product = scene.by_guid(wall)

    # Shortening the wall to four metres pulls both ends in to 2 m and 6 m.
    assert ops.resize_filling_fault(scene, product, 0, 2.0, 6.0) == \
        "filling_outside_resized_body"
    # Leaving the door inside is not refused.
    assert ops.resize_filling_fault(scene, product, 0, 0.0, 8.0) is None
    # Cutting the wall to a metre and a half leaves the door standing above it.
    assert ops.resize_filling_fault(scene, product, 2, 0.0, 1.5) == \
        "filling_outside_resized_body"
    assert ops.resize_filling_fault(scene, product, 2, 0.0, 3.0) is None

    # The two planners that rewrite a body now ask before they draw, and no
    # plan either of them returns leaves the door outside the new body.
    ops.reset_rejections()
    plans = 0
    for seed in range(60):
        for planner, axis, centred in (
                (ops.plan_resize_extrusion, 2, False),
                (ops.plan_resize_profile, None, True)):
            plan = planner(scene, product, rng_of(seed))
            if plan is None:
                continue
            plans += 1
            if axis is None:
                axis = 0 if plan.params["dimension"] == "length" else 1
            span = ops.resized_span(scene, product, axis,
                                    plan.params["new"], centred)
            assert ops.resize_filling_fault(
                scene, product, axis, span[0], span[1]) is None, plan.params
    assert plans > 0, "no resize was drawn at all, so nothing was tested"
    assert ops.rejection_counts().get("filling_outside_resized_body", 0) >= 1

    # A wall with nothing hosted in it is not touched by the rule.
    bare = add_wall(model, storey, 2.0, 8.0, 0.0, 8.0, 0.2, 3.0, name="Bare")
    scene = save(model, "resize_bare.ifc")
    assert ops.resize_filling_fault(scene, scene.by_guid(bare), 0,
                                    3.0, 4.0) is None


def test_a_move_and_a_reflection_read_the_storeys_a_create_reads():
    """0.7.2: a door's collision test reads its host wall's storey as well.

    A door and the wall that hosts it are not always filed on the same storey,
    and the test used to ask only about the door's own, so a neighbour filed
    with the wall was invisible to a move and to a reflection.  The create path
    that puts a door where a window stood already reads both storeys; a move
    and a reflection now read them too, so the three ask one question.

    This is not the cause of the three collisions the v2 wave's physical audit
    found.  Measured on all three, the wider reading adds no storey at all, and
    on the one that moves a door the narrow reading already scores the
    destination full: what those three have in common is a collision with an
    element the test skips, the moved element's own host or its own filling,
    which a reflection carries rigidly while it reflects the body.  That is
    recorded as an open item and not fixed here.
    """
    model, storey, _guids = furnished()
    wall, door, _opening = _wall_with_a_door_near_its_end(model, storey,
                                                          along=1.0)
    # A second storey at the same elevation, carrying the wall and a block of
    # matter three metres east of the door.  The door stays on the first.
    upper = model.create_entity(
        "IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Level 0b",
        Elevation=0.0,
        ObjectPlacement=model.by_guid(storey.GlobalId).ObjectPlacement)
    building = model.by_type("IfcBuilding")[0]
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                        RelatingObject=building, RelatedObjects=[upper])
    add_box(model, upper, "IfcSlab", 5.5, 3.5, 0.0, 1.5, 1.5, 3.0, "Block")
    for relation in model.by_type("IfcRelContainedInSpatialStructure"):
        if any(e.GlobalId == wall for e in relation.RelatedElements):
            relation.RelatedElements = tuple(
                e for e in relation.RelatedElements if e.GlobalId != wall)
    model.create_entity(
        "IfcRelContainedInSpatialStructure",
        GlobalId=ifcopenshell.guid.new(), RelatingStructure=upper,
        RelatedElements=[model.by_guid(wall)])
    scene = save(model, "storeys.ifc")
    leaf = scene.by_guid(door)

    # The door's own storey is not the only one its neighbours can be filed on.
    related = ops.related_storey_guids(scene, leaf)
    assert scene.storey_guid_of(leaf) in related
    assert upper.GlobalId in related, related

    # Moving the door three and a half metres east puts it inside the block,
    # which is filed with the wall and not with the door.
    offset = np.array([3.5, 0.0, 0.0], dtype=float)
    own = scene.storey_of(leaf)
    assert ops.destination_fault(scene, leaf, offset, own) == \
        "move_created_collision"
    # The old reading, which asked about the door's storey alone, saw nothing.
    matrix = np.array(scene.matrix(leaf), dtype=float)
    matrix[:3, 3] = matrix[:3, 3] + offset
    box = scene.box_in_frame(leaf, scene.matrix(leaf))
    assert ops.occupied_share(scene, matrix, box.lo, box.hi,
                              own.GlobalId) <= ops.COLLISION_SHARE
    # A move that lands on empty ground is still allowed.
    assert ops.destination_fault(scene, leaf, np.array([0.0, 2.5, 0.0]),
                                 own) != "move_created_collision"

    # A reflection asks the same question through the same storeys.
    reflected = np.array(scene.matrix(leaf), dtype=float)
    reflected[:3, 3] = reflected[:3, 3] + offset
    assert ops.transform_fault(scene, leaf, reflected, own, ()) == \
        "transformed_element_collides"


def test_a_move_that_would_strand_a_filling_is_refused():
    """A wall whose door hangs off the storey cannot be moved on its own."""
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    door = ifcopenshell.guid.new()
    opening = ifcopenshell.guid.new()
    goldlib.add_filling(model, "IfcDoor", door, "Door", wall, opening,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), 1.0, -0.05, 0.0, 0.9, 2.1,
                        0.3, None, 0.0, 0.2)
    # Re-hang the door and its opening on the storey, so moving the wall alone
    # would leave both of them standing where the wall used to be.
    for guid in (door, opening):
        model.by_guid(guid).ObjectPlacement.PlacementRelTo = \
            model.by_guid(storey.GlobalId).ObjectPlacement
    scene = save(model, "strand.ifc")
    ops.reset_rejections()
    assert ops.plan_translate(scene, scene.by_guid(wall), rng_of(2)) is None
    assert ops.rejection_counts().get("translate_leaves_dependant", 0) == 1


def test_a_move_is_bounded_by_the_storey_and_by_what_stands_there():
    model, storey, guids = furnished()
    free = add_box(model, storey, "IfcColumn", 6.0, 5.0, 0.0, 0.4, 0.4, 3.0,
                   "Mover")
    scene = save(model, "move.ifc")
    storey = scene.by_guid(storey.GlobalId)
    mover = scene.by_guid(free)
    assert ops.destination_fault(scene, mover, np.array([1.0, 0.0, 0.0]),
                                 storey, [free]) is None
    far = ops.destination_fault(scene, mover, np.array([60.0, 0.0, 0.0]),
                                storey, [free])
    assert far == "moved_outside_storey", far
    # Straight on to one of the columns along the south edge.
    onto = scene.by_guid(guids["column3"])
    offset = np.array(scene.point(onto) - scene.point(mover), dtype=float)
    hit = ops.destination_fault(scene, mover, offset, storey, [free])
    assert hit == "move_created_collision", hit


def test_deleting_a_leaf_takes_its_opening_and_leaves_the_wall():
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    door = ifcopenshell.guid.new()
    opening = ifcopenshell.guid.new()
    goldlib.add_filling(model, "IfcDoor", door, "Door", wall, opening,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), 1.0, -0.05, 0.0, 0.9, 2.1,
                        0.3, None, 0.0, 0.2)
    scene = save(model, "delete.ifc")
    # The default takes the opening with the leaf.
    plan = ops.plan_delete(scene, scene.by_guid(door), rng_of(1))
    assert plan.calls[0].func == "delete_filling_with_opening"
    assert set(plan.removed_guids) == {door, opening}

    # A run that asks for the first waves' convention still gets it.
    settings.configure(delete_filling_removes_opening=False)
    try:
        plan = ops.plan_delete(scene, scene.by_guid(door), rng_of(1))
    finally:
        settings.configure(delete_filling_removes_opening=True)
    assert plan.calls[0].func == "delete_element"
    assert plan.removed_guids == (door,)

    edited = ifcopenshell.open(scene.path)
    goldlib.delete_filling_with_opening(edited, door)
    for guid in (door, opening):
        try:
            edited.by_guid(guid)
            raise AssertionError(f"{guid} survived the deletion")
        except RuntimeError:
            pass
    assert not edited.by_type("IfcRelFillsElement")
    assert not edited.by_type("IfcRelVoidsElement")
    # The wall stays, with its own body untouched.
    host = edited.by_guid(wall)
    assert host is not None
    assert host.Representation is not None
    assert not (getattr(host, "HasOpenings", ()) or ())


def test_a_created_leaf_is_flush_with_both_wall_faces():
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.25, 3.0, name="Host")
    scene = save(model, "flush.ifc")
    plan = ops.plan_create_filling(scene, "door", scene.by_guid(wall), "T-9",
                                   rng_of(5))
    assert plan is not None
    edited = ifcopenshell.open(scene.path)
    call = plan.calls[0]
    getattr(goldlib, call.func)(edited, *call.args)
    path = os.path.join(WORK, "flush_edited.ifc")
    edited.write(path)
    after = Scene(path)
    host = after.by_guid(wall)
    leaf = after.by_guid(plan.created_guids[0])
    frame = after.matrix(host)
    wall_box = after.box_in_frame(host, frame)
    leaf_box = after.box_in_frame(leaf, frame)
    assert float(leaf_box.lo[1]) >= float(wall_box.lo[1]) - 1e-6
    assert float(leaf_box.hi[1]) <= float(wall_box.hi[1]) + 1e-6


def test_a_chain_removes_a_wall_s_fillings_under_the_same_convention():
    model, storey, _guids = furnished()
    wall = add_wall(model, storey, 2.0, 4.0, 0.0, 8.0, 0.2, 3.0, name="Host")
    door = ifcopenshell.guid.new()
    opening = ifcopenshell.guid.new()
    goldlib.add_filling(model, "IfcDoor", door, "Door", wall, opening,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), 1.0, -0.05, 0.0, 0.9, 2.1,
                        0.3, None, 0.0, 0.2)
    scene = save(model, "chain_delete.ifc")
    plan = chains.plan_delete_wall_with_fillings(scene, scene.by_guid(wall),
                                                 "T-4", rng_of(1))
    assert plan is not None
    assert [c.func for c in plan.calls] == ["delete_filling_with_opening",
                                            "delete_element"]
    assert opening in plan.removed_guids


def test_a_chain_move_checks_every_element_it_moves():
    """The rules the compositional tier runs are the ones the library holds."""
    assert chains.moves_with is ops.moves_with
    assert chains.placement_chain is ops.placement_chain


# ---------------------------------------------------------------- the runner


def main() -> int:
    global WORK
    WORK = tempfile.mkdtemp(prefix="modifc_gen_tests_")
    os.environ["MODIFC_GEOM_CACHE"] = os.path.join(WORK, "geom_index")
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    try:
        for test in tests:
            ops.reset_rejections()
            try:
                test()
            except Exception as exc:  # noqa: BLE001 - the report is the point
                failed += 1
                print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}",
                      flush=True)
            else:
                print(f"ok   {test.__name__}", flush=True)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
