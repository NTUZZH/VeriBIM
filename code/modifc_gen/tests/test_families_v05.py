"""The requirement families 0.5.0 adds, each checked on a model built for it.

One fixture carries everything the new families need: two storeys, a room with
four walls around it and a second room behind one of them, a gap between two
walls in line with each other, a run of columns, a door, and a slab overhead.
Each test then asks one anchor, one placement kind, one relation writer or one
coordinate form for its answer and checks it against the geometry.

Run with ``python -m modifc_gen.tests.test_families_v05``.
"""

from __future__ import annotations

import os
import random
import shutil
import tempfile

import numpy as np

import ifcopenshell

from .. import anchors as anchor_lib
from .. import families, goldlib, ops, settings, templates, verify
from ..scene import Scene
from .test_placement_rules import add_box, empty_model, rng_of

WORK = None


# ------------------------------------------------------------- the fixture


def two_storey_model():
    """A two-storey model with rooms, a wall gap, a column run and a door."""
    model, ground = empty_model()
    building = ground.ObjectPlacement.PlacementRelTo
    upper = model.create_entity(
        "IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(), Name="Level 1",
        Elevation=3.5,
        ObjectPlacement=model.create_entity(
            "IfcLocalPlacement", PlacementRelTo=building,
            RelativePlacement=model.create_entity(
                "IfcAxis2Placement3D",
                Location=model.create_entity("IfcCartesianPoint",
                                             Coordinates=(0.0, 0.0, 3.5)))))
    parent = building.PlacementRelTo
    for relation in model.by_type("IfcRelAggregates"):
        if relation.RelatingObject.is_a("IfcBuilding"):
            relation.RelatedObjects = tuple(relation.RelatedObjects) + (upper,)

    guids = {}
    guids["floor"] = add_box(model, ground, "IfcSlab", 0.0, 0.0, -0.2,
                             20.0, 12.0, 0.2, "Floor slab")
    # The room: four walls around a 5 by 5 space.
    guids["south"] = add_box(model, ground, "IfcWall", 0.0, 0.0, 0.0,
                             5.0, 0.2, 3.0, "Wall south")
    guids["north"] = add_box(model, ground, "IfcWall", 0.0, 5.0, 0.0,
                             5.0, 0.2, 3.0, "Wall north")
    guids["west"] = add_box(model, ground, "IfcWall", 0.0, 0.2, 0.0,
                            0.2, 4.8, 3.0, "Wall west")
    guids["east"] = add_box(model, ground, "IfcWall", 4.8, 0.2, 0.0,
                            0.2, 4.8, 3.0, "Wall east")
    guids["kitchen"] = add_box(model, ground, "IfcSpace", 0.25, 0.25, 0.0,
                               4.5, 4.7, 2.7, "K1")
    model.by_guid(guids["kitchen"]).LongName = "Kitchen"
    guids["hall"] = add_box(model, ground, "IfcSpace", 0.25, 5.3, 0.0,
                            4.5, 3.0, 2.7, "H1")
    model.by_guid(guids["hall"]).LongName = "Hall"
    # Two walls in line with each other, two metres apart.
    guids["gap_left"] = add_box(model, ground, "IfcWall", 8.0, 1.0, 0.0,
                                3.0, 0.2, 3.0, "Wall gap left")
    guids["gap_right"] = add_box(model, ground, "IfcWall", 13.0, 1.0, 0.0,
                                 3.0, 0.2, 3.0, "Wall gap right")
    # A run of three columns, the middle one between the outer two.
    guids["c_west"] = add_box(model, ground, "IfcColumn", 8.0, 8.0, 0.0,
                              0.4, 0.4, 3.0, "Column west")
    guids["c_mid"] = add_box(model, ground, "IfcColumn", 11.0, 8.0, 0.0,
                             0.4, 0.4, 3.0, "Column middle")
    guids["c_east"] = add_box(model, ground, "IfcColumn", 14.0, 8.0, 0.0,
                              0.4, 0.4, 3.0, "Column east")
    # A door in the south wall of the room, near its western end.
    guids["door"] = goldlib.add_filling(
        model, "IfcDoor", ifcopenshell.guid.new(), "Door one",
        guids["south"], ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        1.0, -0.05, 0.0, 0.9, 2.1, 0.3, None, 0.0, 0.2).GlobalId
    # The storey above: a ceiling slab and a column over the western one.
    guids["ceiling"] = add_box(model, upper, "IfcSlab", 6.0, 6.0, -0.2,
                               12.0, 6.0, 0.2, "Ceiling slab")
    guids["c_above"] = add_box(model, upper, "IfcColumn", 8.0, 8.0, 0.0,
                               0.4, 0.4, 3.0, "Column above")
    guids["door_above"] = goldlib.add_filling(
        model, "IfcWindow", ifcopenshell.guid.new(), "Window above",
        add_box(model, upper, "IfcWall", 0.0, 0.0, 0.0, 5.0, 0.2, 3.0,
                "Wall upper south"),
        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        3.5, -0.05, 0.9, 0.9, 1.2, 0.3, None, 0.0, 0.2).GlobalId
    # The room's boundaries, so the topological anchors have something to read.
    for role in ("south", "north", "west", "east", "door"):
        goldlib.add_space_boundary(model, ifcopenshell.guid.new(),
                                   guids["kitchen"], guids[role])
    goldlib.add_space_boundary(model, ifcopenshell.guid.new(), guids["hall"],
                               guids["north"])
    return model, ground, upper, guids


def scene_of(model, name):
    path = os.path.join(WORK, name)
    model.write(path)
    return Scene(path)


def fixture(name):
    model, ground, upper, guids = two_storey_model()
    scene = scene_of(model, name)
    return scene, scene.by_guid(ground.GlobalId), scene.by_guid(upper.GlobalId), guids


# ------------------------------------------------------- the new anchors


def test_nearest_names_the_closest_element_of_its_family():
    scene, _ground, _upper, guids = fixture("nearest.ifc")
    target = scene.by_guid(guids["c_mid"])
    found = [a for a in anchor_lib.nearest_anchors(scene, target, rng_of(4))
             if a.params["reference_guid"] == guids["c_west"]]
    assert found, "no anchor named the column nearest the western one"
    assert found[0].resolve(scene) == [guids["c_mid"]]
    assert "nearest to the column named 'Column west'" in found[0].phrase


def test_between_names_an_element_flanked_by_two_named_ones():
    scene, _ground, _upper, guids = fixture("between.ifc")
    target = scene.by_guid(guids["c_mid"])
    built = anchor_lib.between_anchors(scene, target, rng_of(5))
    assert built, "no between anchor for the middle column"
    anchor = built[0]
    assert anchor.resolve(scene) == [guids["c_mid"]]
    assert {anchor.params["a_guid"], anchor.params["b_guid"]} == \
        {guids["c_west"], guids["c_east"]}


def test_above_below_names_an_element_over_a_named_one():
    scene, _ground, _upper, guids = fixture("above.ifc")
    target = scene.by_guid(guids["c_above"])
    built = anchor_lib.above_below_anchors(scene, target, rng_of(6))
    assert built, "no storey-to-storey anchor for the upper column"
    anchor = built[0]
    assert anchor.params["direction"] == "above"
    assert anchor.resolve(scene) == [guids["c_above"]]
    # The same predicate must not answer for the column underneath.
    assert guids["c_west"] not in anchor.resolve(scene)


def test_separates_names_the_wall_between_two_rooms():
    scene, _ground, _upper, guids = fixture("separates.ifc")
    built = anchor_lib.separates_anchors(scene, scene.by_guid(guids["north"]),
                                         rng_of(9))
    assert built, "no separates anchor for the north wall"
    anchor = built[0]
    assert anchor.resolve(scene) == [guids["north"]]
    assert "separates" in anchor.phrase and "Kitchen" in anchor.phrase


def test_opposite_names_the_wall_facing_another_across_a_room():
    scene, _ground, _upper, guids = fixture("opposite.ifc")
    built = anchor_lib.opposite_anchors(scene, scene.by_guid(guids["north"]),
                                        rng_of(7))
    assert built, "no opposite anchor for the north wall"
    anchor = built[0]
    assert anchor.params["reference_guid"] == guids["south"]
    assert anchor.resolve(scene) == [guids["north"]]


def test_egocentric_names_the_wall_on_one_side_of_a_door():
    scene, _ground, _upper, guids = fixture("ego.ifc")
    built = anchor_lib.egocentric_anchors(scene, scene.by_guid(guids["west"]),
                                          rng_of(8))
    assert built, "no egocentric anchor for the west wall"
    anchor = built[0]
    assert anchor.params["door_guid"] == guids["door"]
    assert anchor.params["side"] == "left"
    assert anchor.resolve(scene) == [guids["west"]]
    # Looking the other way must name the other wall and not this one.
    mirrored = anchor_lib.Anchor(kind="egocentric", family="wall", phrase="",
                                 params=dict(anchor.params, side="right"))
    assert guids["west"] not in mirrored.resolve(scene)
    assert guids["east"] in mirrored.resolve(scene)


def test_the_new_anchor_kinds_all_carry_a_style_and_a_hop_count():
    for kind in anchor_lib.NEW_KINDS:
        assert kind in anchor_lib.CATEGORY
        assert kind in anchor_lib.CHAIN_LENGTH
        assert kind in anchor_lib.RESOLVERS
        # Each is a family of the taxonomy, drawn through the registry.
        tag = anchor_lib.KIND_FAMILY[kind]
        entry = families.BY_TAG[tag]
        assert entry.layer == "reference"
        assert entry.style == anchor_lib.CATEGORY[kind]
        assert families.build(entry) is not None


# --------------------------------------------------- the coordinate forms


def test_a_world_coordinate_lands_where_it_says_on_a_raised_storey():
    model, _ground, upper, _guids = two_storey_model()
    guid = ifcopenshell.guid.new()
    goldlib.add_box_element_world(model, "IfcColumn", guid, "World column",
                                  upper.GlobalId, ifcopenshell.guid.new(),
                                  9.0, 9.0, 3.5, 0.4, 0.4, 3.0)
    bounds = goldlib.world_extent(model, guid)
    assert bounds is not None
    assert np.allclose(bounds[0], [9.0, 9.0, 3.5], atol=1e-6), bounds[0]
    assert np.allclose(bounds[1], [9.4, 9.4, 6.5], atol=1e-6), bounds[1]
    # The storey sits 3.5 m up, so the element's own placement is at z zero.
    local = model.by_guid(guid).ObjectPlacement.RelativePlacement.Location
    assert abs(float(local.Coordinates[2])) < 1e-6


def test_a_wall_span_puts_the_thickness_on_the_side_it_names():
    model, ground, _upper, _guids = two_storey_model()
    for direction, expected_lo, expected_hi in (("-y", 5.8, 6.0),
                                                ("+y", 6.0, 6.2)):
        guid = ifcopenshell.guid.new()
        goldlib.add_wall_span(model, guid, f"Span {direction}",
                              ground.GlobalId, ifcopenshell.guid.new(),
                              2.0, 6.0, 0.0, 8.0, 6.0, 0.0, 0.2, direction, 3.0)
        bounds = goldlib.world_extent(model, guid)
        assert np.allclose(bounds[0], [2.0, expected_lo, 0.0], atol=1e-6)
        assert np.allclose(bounds[1], [8.0, expected_hi, 3.0], atol=1e-6)


def test_a_wall_span_refuses_a_line_that_is_not_on_one_axis():
    model, ground, _upper, _guids = two_storey_model()
    for bad in ((2.0, 6.0, 0.0, 8.0, 7.0, 0.0, "-y"),
                (2.0, 6.0, 0.0, 8.0, 6.0, 1.0, "-y"),
                (2.0, 6.0, 0.0, 8.0, 6.0, 0.0, "-x")):
        try:
            goldlib.add_wall_span(model, ifcopenshell.guid.new(), "Bad",
                                  ground.GlobalId, ifcopenshell.guid.new(),
                                  bad[0], bad[1], bad[2], bad[3], bad[4],
                                  bad[5], 0.2, bad[6], 3.0)
        except ValueError:
            continue
        raise AssertionError(f"a span of {bad} should have been refused")


def test_the_world_form_quotes_the_storey_elevation_not_zero():
    scene, _ground, upper, _guids = fixture("worldform.ifc")
    plan = ops.plan_create_box(scene, "column", upper, "TST-001", rng_of(11))
    assert plan is not None
    assert ops.use_world_coordinates(scene, plan, upper)
    assert plan.params["frame"] == "world"
    assert abs(float(plan.params["z"]) - 3.5) < 1e-6
    assert plan.calls[0].func == "add_box_element_world"
    assert "spec.world_frame" in plan.params["families"]


# ------------------------------------------------- the derived placements


def _created_box(scene, plan, storey, task_id="TST-002"):
    """Run the plan's calls on a fresh copy of the scene and read the result."""
    model = ifcopenshell.open(scene.path)
    for call in plan.calls:
        getattr(goldlib, call.func)(model, *call.args)
    return model, goldlib.world_extent(model, plan.created_guids[0])


def test_a_created_wall_fills_the_gap_between_two_named_walls():
    scene, ground, _upper, guids = fixture("gap.ifc")
    plan = ops.plan_create_box(scene, "wall", ground, "TST-003", rng_of(12))
    assert plan is not None
    drawn = ops._derive_fits_gap(scene, plan, ground, rng_of(12))
    assert drawn is not None, "the two walls in line were not found"
    assert {drawn["refs"][0], drawn["refs"][1]} == {guids["gap_left"],
                                                   guids["gap_right"]}
    ops._set_box_call(plan, drawn["lo"], drawn["size"], world=True)
    plan.params["placement"] = drawn
    _model, bounds = _created_box(scene, plan, ground)
    # The new wall starts where one wall ends and stops where the other begins.
    assert abs(float(bounds[0][0]) - 11.0) < 0.02, bounds[0]
    assert abs(float(bounds[1][0]) - 13.0) < 0.02, bounds[1]


def test_a_created_element_sits_on_the_top_face_of_a_named_one():
    scene, ground, _upper, guids = fixture("ontop.ifc")
    plan = ops.plan_create_box(scene, "column", ground, "TST-004", rng_of(13))
    assert plan is not None
    drawn = ops._derive_on_top_of(scene, plan, ground, rng_of(13))
    assert drawn is not None
    reference = scene.world_box(scene.by_guid(drawn["refs"][0]))
    assert abs(float(drawn["lo"][2]) - float(reference.hi[2])) < 1e-6
    ops._set_box_call(plan, drawn["lo"], drawn["size"], world=True)
    _model, bounds = _created_box(scene, plan, ground)
    assert abs(float(bounds[0][2]) - float(reference.hi[2])) < 0.02


def test_a_created_element_stands_against_a_room_s_boundary_wall():
    scene, ground, _upper, guids = fixture("adjacent.ifc")
    plan = ops.plan_create_box(scene, "column", ground, "TST-005", rng_of(14))
    assert plan is not None
    drawn = ops._derive_adjacent_to_space(scene, plan, ground, rng_of(14))
    assert drawn is not None, "no room with a nameable boundary wall was found"
    wall = scene.world_box(scene.by_guid(drawn["refs"][1]))
    lo = np.array(drawn["lo"], dtype=float)
    hi = lo + np.array(drawn["size"], dtype=float)
    touching = min(min(abs(float(lo[i]) - float(wall.hi[i])),
                       abs(float(hi[i]) - float(wall.lo[i]))) for i in (0, 1))
    assert touching < 1e-6, ("the new element does not touch the wall",
                             lo.tolist(), hi.tolist(), wall.lo.tolist(),
                             wall.hi.tolist())


def test_a_created_column_stops_at_the_underside_of_the_slab_above():
    scene, ground, _upper, guids = fixture("slabover.ifc")
    plan = ops.plan_create_box(scene, "column", ground, "TST-006", rng_of(15))
    assert plan is not None
    drawn = ops._derive_touching_slab_above(scene, plan, ground, rng_of(15))
    assert drawn is not None
    slab = scene.world_box(scene.by_guid(drawn["refs"][0]))
    top = float(drawn["lo"][2]) + float(drawn["size"][2])
    assert abs(top - float(slab.lo[2])) < 1e-6, (top, float(slab.lo[2]))


def test_a_created_leaf_may_be_placed_by_its_middle():
    scene, _ground, _upper, guids = fixture("centred.ifc")
    wall = scene.by_guid(guids["north"])
    plan = ops.plan_create_filling(scene, "door", wall, "TST-007", rng_of(16))
    assert plan is not None
    along = float(plan.params["along"])
    assert ops._derive_centred_on_wall(scene, plan, wall, rng_of(16))
    placement = plan.params["placement"]
    start = float(scene.local_extent(wall).lo[0])
    assert abs(placement["centre_from_start"]
               - (along + float(plan.params["width"]) / 2.0 - start)) < 0.01


def test_a_created_leaf_may_be_lined_up_with_one_on_the_storey_below():
    scene, _ground, _upper, guids = fixture("stack.ifc")
    upper_wall = scene.by_guid(scene.host_of(scene.by_guid(guids["door_above"])))
    plan = ops.plan_create_filling(scene, "window", upper_wall, "TST-008",
                                   rng_of(17))
    assert plan is not None
    assert ops._derive_above_below_filling(scene, plan, upper_wall, rng_of(17))
    placement = plan.params["placement"]
    assert placement["direction"] == "above"
    reference = scene.centre(scene.by_guid(placement["refs"][0]))
    frame = scene.matrix(upper_wall)
    middle = float(plan.params["along"]) + float(plan.params["width"]) / 2.0
    world = frame[:3, :3] @ np.array([middle, 0.0, 0.0]) + frame[:3, 3]
    assert abs(float(world[0]) - float(reference[0])) < 0.05


def test_every_derived_kind_reports_whether_it_could_be_built():
    scene, ground, _upper, _guids = fixture("counts.ifc")
    ops.reset_derived()
    plan = ops.plan_create_box(scene, "wall", ground, "TST-009", rng_of(18))
    assert ops.derive_box_placement(scene, plan, ground, rng_of(18))
    counts = ops.derived_counts()
    assert counts, "the derived placement counters recorded nothing"
    assert any(key.endswith(":ok") for key in counts)


# ---------------------------------------------------- the relation writers


def test_a_space_boundary_is_written_with_the_ends_it_was_given():
    model, _ground, _upper, guids = two_storey_model()
    guid = ifcopenshell.guid.new()
    goldlib.add_space_boundary(model, guid, guids["hall"], guids["east"],
                               "PHYSICAL", "EXTERNAL")
    relation = model.by_guid(guid)
    assert relation.is_a("IfcRelSpaceBoundary")
    assert relation.RelatingSpace.GlobalId == guids["hall"]
    assert relation.RelatedBuildingElement.GlobalId == guids["east"]
    assert relation.InternalOrExternalBoundary == "EXTERNAL"
    assert not verify.missing_relations(
        model, [["IfcRelSpaceBoundary", guids["hall"], guids["east"]]])


def test_a_connection_is_written_with_the_ends_it_was_given():
    model, _ground, _upper, guids = two_storey_model()
    guid = ifcopenshell.guid.new()
    goldlib.connect_elements(model, guid, guids["south"], guids["west"])
    relation = model.by_guid(guid)
    assert relation.is_a("IfcRelConnectsElements")
    assert relation.RelatingElement.GlobalId == guids["south"]
    assert relation.RelatedElement.GlobalId == guids["west"]
    assert not verify.missing_relations(
        model, [["IfcRelConnectsElements", guids["south"], guids["west"]]])


def test_the_funnel_notices_a_relationship_the_gold_does_not_hold():
    model, _ground, _upper, guids = two_storey_model()
    missing = verify.missing_relations(
        model, [["IfcRelConnectsElements", guids["south"], guids["east"]]])
    assert len(missing) == 1


def _put_box(plan, lo, size):
    """Stand the created box at one place, so the draw's own spot is not used."""
    ops._set_box_call(plan, np.asarray(lo, dtype=float),
                      np.asarray(size, dtype=float), world=False)


def test_a_create_task_states_a_relationship_and_writes_it():
    scene, ground, _upper, guids = fixture("relations.ifc")
    plan = ops.plan_create_box(scene, "wall", ground, "TST-010", rng_of(19))
    assert plan is not None
    # Against the room's north wall and inside the room's own footprint, so a
    # boundary and a connection are both true of the model.
    _put_box(plan, (1.0, 4.6, 0.0), (2.0, 0.4, 3.0))
    assert ops.attach_relations(scene, plan, ground, "TST-010", rng_of(19))
    edges = plan.params["relation_edges"]
    assert edges and plan.relation_guids
    model = ifcopenshell.open(scene.path)
    for call in plan.calls:
        getattr(goldlib, call.func)(model, *call.args)
    assert not verify.missing_relations(model, edges)
    assert plan.params["relation"]["ifc_class"] in ops.required_relations(plan)
    assert any(t.startswith("constraint.relation_on_create")
               for t in plan.params["families"])


def test_the_record_names_the_relation_classes_the_script_writes():
    scene, ground, _upper, guids = fixture("required.ifc")
    plan = ops.plan_create_filling(scene, "door", scene.by_guid(guids["north"]),
                                   "TST-011", rng_of(20))
    assert plan is not None
    required = ops.required_relations(plan)
    assert "IfcRelVoidsElement" in required
    assert "IfcRelFillsElement" in required
    assert "IfcRelContainedInSpatialStructure" in required


def test_a_created_space_is_aggregated_rather_than_contained():
    scene, ground, _upper, _guids = fixture("spacecreate.ifc")
    plan = ops.plan_create_box(scene, "space", ground, "TST-012", rng_of(21))
    assert plan is not None
    assert ops.required_relations(plan) == ["IfcRelAggregates"]


# ------------------------------------------------------ constraint clauses


def test_a_constraint_clause_is_only_added_where_the_gold_satisfies_it():
    plan = ops.EditPlan(kind="rename", operation="update", family="wall",
                        calls=[], params={})
    settings.configure(family_shares={"constraint.on_edit": 1.0})
    try:
        ops.attach_constraint(plan, rng_of(22))
        assert plan.params["constraint"] in (
            "constraint.invariant.keep_placement",
            "constraint.cascade.relations_preserved")
        moved = ops.EditPlan(kind="translate", operation="update", family="wall",
                             calls=[], params={"axis": 0})
        ops.attach_constraint(moved, rng_of(23))
        assert moved.params["constraint"] == "constraint.invariant.keep_z"
        removed = ops.EditPlan(kind="delete", operation="delete", family="wall",
                               calls=[], params={})
        ops.attach_constraint(removed, rng_of(24))
        assert removed.params["constraint"] == \
            "constraint.cascade.relations_consistent"
    finally:
        settings.configure(family_shares={})


def test_the_clause_reaches_the_instruction():
    plan = ops.EditPlan(kind="rename", operation="update", family="wall",
                        calls=[], params={
                            "old": "A", "new": "B",
                            "constraint": "constraint.invariant.keep_placement"})
    anchor = anchor_lib.Anchor(kind="name", family="wall",
                               phrase="the wall named 'A'", params={"name": "A"})
    sentence = templates.render(None, plan, anchor, "direct")
    assert sentence.endswith("keeping its placement fixed."), sentence


# ---------------------------------------------------- backward compatibility


def test_the_earlier_gold_calls_keep_their_signatures():
    """A record written by 0.4.1 still names every argument its script passes."""
    from ..script import _parameter_names

    assert _parameter_names("add_box_element")[:13] == [
        "ifc_class", "guid", "name", "storey_guid", "relation_guid", "x", "y",
        "z", "length", "width", "height", "predefined_type", "like_guid"]
    assert _parameter_names("add_filling")[:16] == [
        "ifc_class", "guid", "name", "host_guid", "opening_guid", "voids_guid",
        "fills_guid", "relation_guid", "along", "across", "sill", "width",
        "height", "thickness", "predefined_type", "filling_across"]


def test_an_old_record_carries_no_new_field_and_still_checks():
    """The new funnel stage is a no-op for a record that asks for nothing."""
    model, _ground, _upper, _guids = two_storey_model()
    path = os.path.join(WORK, "old.ifc")
    model.write(path)
    stage = verify.check_parse(path, [], [])
    assert stage.ok, stage.reason


def test_the_registry_names_every_family_after_the_taxonomy():
    """Every tag a task can carry belongs to a layer of the author's taxonomy."""
    for family in families.FAMILIES:
        assert family.layer in families.LAYERS
        assert family.tag.split(".")[0] in (
            "ref", "spec", "constraint", "wording", "op", "scope", "model")
        assert family.group in families.GROUP_SHARE
    for tag in families.OPERATION_TAG.values():
        assert families.layer_of(tag) == "operation"
    for tag in families.SCOPE_TAG.values():
        assert families.layer_of(tag) == "scope"


def test_a_family_is_switched_off_by_its_weight_alone():
    """Turning a family off needs no branch anywhere: its weight goes to zero."""
    settings.configure(family_weights={"ref.viewpoint.through_door": 0.0})
    try:
        tags = [f.tag for f in families.candidates("ref.new")]
        assert "ref.viewpoint.through_door" not in tags
        assert "ref.topological.separates" in tags
    finally:
        settings.configure(family_weights={})


def test_a_record_is_labelled_for_every_layer_the_generator_settles():
    plan = ops.EditPlan(kind="create_box", operation="create", family="wall",
                        calls=[], params={"families": ["spec.world_frame"]})
    tags = ops.family_tags(plan, "nearest", tier="single")
    assert "op.create" in tags
    assert "scope.single" in tags
    assert "ref.relative.nearest" in tags
    assert "spec.world_frame" in tags
    chain = ops.EditPlan(kind="delete_wall_with_fillings", operation="delete",
                         family="wall", calls=[], params={})
    assert "scope.chain" in ops.family_tags(chain, "", tier="compositional")


def test_the_axis_dimension_form_needs_the_world_frame_first():
    scene, ground, _upper, _guids = fixture("axisdims.ifc")
    plan = ops.plan_create_box(scene, "column", ground, "TST-013", rng_of(25))
    assert plan is not None
    assert not ops.use_axis_dimensions(scene, plan, ground, rng_of(25))
    assert ops.use_world_coordinates(scene, plan, ground)
    assert ops.use_axis_dimensions(scene, plan, ground, rng_of(25))
    assert plan.params["size_form"] == "axis"
    assert "spec.axis_dimensions" in plan.params["families"]


# ---------------------------------------------------------------- the runner


def test_a_relationship_is_only_stated_with_ends_the_new_element_touches():
    scene, ground, _upper, _guids = fixture("relationtouch.ifc")
    plan = ops.plan_create_box(scene, "wall", ground, "TST-020", rng_of(31))
    assert plan is not None
    _put_box(plan, (1.0, 4.6, 0.0), (2.0, 0.4, 3.0))
    assert ops.attach_relations(scene, plan, ground, "TST-020", rng_of(31))
    created = ops._created_world_box(scene, plan, ground)
    for _ifc_class, first, second in plan.params["relation_edges"]:
        other_guid = second if first == plan.created_guids[0] else first
        other = scene.world_box(scene.by_guid(other_guid))
        assert other is not None, other_guid
        gap = ops._box_gap(created, (other.lo, other.hi))
        assert gap <= ops.RELATION_TOUCH, (other_guid, gap)


def test_a_relationship_is_refused_when_every_candidate_stands_apart():
    scene, ground, _upper, _guids = fixture("relationapart.ifc")
    plan = ops.plan_create_box(scene, "wall", ground, "TST-021", rng_of(32))
    assert plan is not None
    # In the open, three metres from the nearest room and the nearest wall.
    _put_box(plan, (17.0, 9.0, 0.0), (2.0, 0.2, 3.0))
    assert not ops.attach_relations(scene, plan, ground, "TST-021", rng_of(32))
    assert not plan.params.get("relation_edges")
    assert "relation_partner_not_touching" in ops.rejection_counts()


def test_separates_is_refused_when_a_room_does_not_touch_the_element():
    model, _ground, _upper, guids = two_storey_model()
    # A wall the model says both rooms bound, three metres away from either.
    for space in ("kitchen", "hall"):
        goldlib.add_space_boundary(model, ifcopenshell.guid.new(),
                                   guids[space], guids["gap_left"])
    scene = scene_of(model, "separatesapart.ifc")
    wall = scene.by_guid(guids["gap_left"])
    assert anchor_lib.bounding_anchor(scene, wall) is not None
    assert anchor_lib.separates_anchors(scene, wall, rng_of(33)) == []


def main() -> int:
    global WORK
    WORK = tempfile.mkdtemp(prefix="modifc_gen_v05_tests_")
    os.environ["MODIFC_GEOM_CACHE"] = os.path.join(WORK, "geom_index")
    from . import test_placement_rules
    test_placement_rules.WORK = WORK
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
