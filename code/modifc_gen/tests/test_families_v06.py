"""The operations and scopes 0.6.0 adds, each checked on a model built for it.

The fixture is the two-storey model the 0.5.0 tests use: a room with four walls
and a door, a second room behind one of them, a run of columns, a slab overhead
and a storey above.  Each test then asks one operation, one reference or one
funnel check for its answer and checks it against the file the edit wrote.

Run with ``python -m modifc_gen.tests.test_families_v06``.
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
from .test_families_v05 import fixture, scene_of, two_storey_model
from .test_placement_rules import add_box, empty_model, rng_of

WORK = None


def _apply(scene, calls, name):
    """Run a plan's calls on a fresh copy of the fixture and reopen it."""
    model = ifcopenshell.open(scene.path)
    for call in calls:
        getattr(goldlib, call.func)(model, *call.args)
    path = os.path.join(WORK, name)
    model.write(path)
    return ifcopenshell.open(path)


def _world_box(model, guid):
    return goldlib.world_extent(model, guid)


# ------------------------------------------------------------------ rotate


def test_rotate_turns_the_body_about_the_stated_pivot():
    scene, ground, _upper, guids = fixture("rotate.ifc")
    target = scene.by_guid(guids["c_mid"])
    before = _world_box(scene.model, target.GlobalId)
    pivot = (before[0] + before[1]) / 2.0
    model = ifcopenshell.open(scene.path)
    goldlib.rotate(model, target.GlobalId, 90.0, float(pivot[0]),
                   float(pivot[1]))
    path = os.path.join(WORK, "rotate_out.ifc")
    model.write(path)
    after = _world_box(ifcopenshell.open(path), target.GlobalId)
    centre = (after[0] + after[1]) / 2.0
    assert np.abs(centre[:2] - pivot[:2]).max() < 1e-6, "the pivot moved"
    assert abs(float(after[1][2] - after[0][2])
               - float(before[1][2] - before[0][2])) < 1e-9, "the height changed"


def test_rotate_about_the_origin_is_not_rotation_about_the_plan_centre():
    scene, ground, _upper, guids = fixture("rotate2.ifc")
    guid = guids["south"]
    origin = np.array(scene.matrix(scene.by_guid(guid)), dtype=float)[:3, 3]
    box = _world_box(scene.model, guid)
    centre = (box[0] + box[1]) / 2.0
    boxes = []
    for index, pivot in enumerate((origin, centre)):
        model = ifcopenshell.open(scene.path)
        goldlib.rotate(model, guid, 45.0, float(pivot[0]), float(pivot[1]))
        path = os.path.join(WORK, f"rotate2_{index}.ifc")
        model.write(path)
        boxes.append(_world_box(ifcopenshell.open(path), guid))
    assert np.abs(boxes[0][0] - boxes[1][0]).max() > 0.1, \
        "the two pivots put the wall in the same place"


def test_rotate_is_planned_only_where_the_turned_body_still_fits():
    scene, ground, _upper, guids = fixture("rotate3.ifc")
    ops.reset_rejections()
    plan = ops.plan_rotate(scene, scene.by_guid(guids["c_mid"]), rng_of(3))
    assert plan is not None and plan.kind == "rotate"
    assert plan.params["pivot"] in ("origin", "centre")
    # A door is refused: a leaf turned out of its opening leaves the wall.
    assert ops.plan_rotate(scene, scene.by_guid(guids["door"]), rng_of(3)) is None


# ------------------------------------------------------------------ mirror


def test_mirror_reflects_the_body_exactly():
    scene, ground, _upper, guids = fixture("mirror.ifc")
    guid = guids["gap_left"]
    before = _world_box(scene.model, guid)
    plane = float(before[1][0]) + 3.0
    model = ifcopenshell.open(scene.path)
    goldlib.mirror(model, guid, plane, 0.0, 1.0, 0.0)
    path = os.path.join(WORK, "mirror_out.ifc")
    model.write(path)
    after = _world_box(ifcopenshell.open(path), guid)
    assert abs(float(after[0][0]) - (2 * plane - float(before[1][0]))) < 1e-6
    assert abs(float(after[1][0]) - (2 * plane - float(before[0][0]))) < 1e-6
    assert np.abs(after[0][1:] - before[0][1:]).max() < 1e-6, \
        "the reflection moved the wall across its own plane"


def test_mirror_refuses_a_body_it_cannot_flip():
    model, storey = empty_model()
    guid = add_box(model, storey, "IfcWall", 0.0, 0.0, 0.0, 4.0, 0.2, 3.0,
                   "Turned wall")
    solid = goldlib.sole_extrusion(model, model.by_guid(guid))
    solid.Position.RefDirection = model.create_entity(
        "IfcDirection", DirectionRatios=(0.0, 1.0, 0.0))
    assert goldlib.mirrorable_body(model, model.by_guid(guid)) is None
    try:
        goldlib.mirror(model, guid, 10.0, 0.0, 1.0, 0.0)
    except ValueError:
        return
    raise AssertionError("a body that cannot be flipped was mirrored anyway")


def test_mirror_plane_may_follow_a_named_wall():
    scene, ground, _upper, guids = fixture("mirror2.ifc")
    settings.configure(family_shares={"constraint.on_edit": 0.0})
    plan = ops.plan_mirror(scene, scene.by_guid(guids["c_mid"]), rng_of(11))
    settings.configure(family_shares={})
    assert plan is not None
    assert plan.params["plane_kind"] in ("wall_axis", "point")
    instruction = templates.render(scene, plan,
                                   anchor_lib.guid_anchor(scene, scene.by_guid(guids["c_mid"])),
                                   "direct")
    assert instruction.startswith("Mirror ")


# ---------------------------------------------------------- property values


def test_a_property_value_is_written_into_a_set_the_element_owns():
    scene, ground, _upper, guids = fixture("pset.ifc")
    guid = guids["south"]
    model = ifcopenshell.open(scene.path)
    goldlib.set_property_value(model, guid, "Pset_WallCommon", "FireRating",
                               "F90", "IfcLabel", ifcopenshell.guid.new(),
                               ifcopenshell.guid.new())
    path = os.path.join(WORK, "pset_out.ifc")
    model.write(path)
    import ifcopenshell.util.element as element_util
    psets = element_util.get_psets(ifcopenshell.open(path).by_guid(guid))
    assert psets["Pset_WallCommon"]["FireRating"] == "F90"


def test_a_shared_property_set_is_split_before_it_is_written():
    scene, ground, _upper, guids = fixture("pset_shared.ifc")
    model = ifcopenshell.open(scene.path)
    first, second = model.by_guid(guids["south"]), model.by_guid(guids["north"])
    pset = model.create_entity(
        "IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
        Name="Pset_WallCommon",
        HasProperties=[model.create_entity(
            "IfcPropertySingleValue", Name="FireRating",
            NominalValue=model.create_entity("IfcLabel", "F30"))])
    model.create_entity("IfcRelDefinesByProperties",
                        GlobalId=ifcopenshell.guid.new(),
                        RelatedObjects=[first, second],
                        RelatingPropertyDefinition=pset)
    goldlib.set_property_value(model, guids["south"], "Pset_WallCommon",
                               "FireRating", "F120", "IfcLabel",
                               ifcopenshell.guid.new(), ifcopenshell.guid.new())
    path = os.path.join(WORK, "pset_shared_out.ifc")
    model.write(path)
    import ifcopenshell.util.element as element_util
    done = ifcopenshell.open(path)
    assert element_util.get_psets(done.by_guid(guids["south"]))[
        "Pset_WallCommon"]["FireRating"] == "F120"
    assert element_util.get_psets(done.by_guid(guids["north"]))[
        "Pset_WallCommon"]["FireRating"] == "F30", \
        "writing one element's value changed another element's"


def test_the_property_planner_never_writes_the_value_already_there():
    scene, ground, _upper, guids = fixture("pset_plan.ifc")
    plan = ops.plan_set_pset(scene, scene.by_guid(guids["south"]), rng_of(5),
                             "T-1")
    assert plan is not None and plan.kind == "set_pset"
    current = ops.own_property_value(scene, scene.by_guid(guids["south"]),
                                     plan.params["pset"],
                                     plan.params["property"])
    assert ops._differs(current, plan.params["value"])


# ------------------------------------------------------- material and type


def test_a_material_association_replaces_the_one_the_element_had():
    scene, ground, _upper, guids = fixture("material.ifc")
    guid = guids["south"]
    model = ifcopenshell.open(scene.path)
    goldlib.assign_material(model, guid, "Brick masonry",
                            ifcopenshell.guid.new())
    goldlib.assign_material(model, guid, "Concrete C30/37",
                            ifcopenshell.guid.new())
    path = os.path.join(WORK, "material_out.ifc")
    model.write(path)
    import ifcopenshell.util.element as element_util
    done = ifcopenshell.open(path)
    assert element_util.get_material(done.by_guid(guid)).Name == "Concrete C30/37"
    holders = [r for r in done.by_type("IfcRelAssociatesMaterial")
               if done.by_guid(guid) in (r.RelatedObjects or ())]
    assert len(holders) == 1, "the element carries two material associations"


def test_the_default_reading_cannot_see_a_material_and_the_flag_can():
    import dataclasses

    from modifc_score.config import DEFAULT_CONFIG
    from modifc_score.properties import entity_properties, property_score

    scene, ground, _upper, guids = fixture("material_score.ifc")
    guid = guids["south"]
    model = ifcopenshell.open(scene.path)
    goldlib.assign_material(model, guid, "Brick masonry",
                            ifcopenshell.guid.new())
    path = os.path.join(WORK, "material_score_out.ifc")
    model.write(path)
    reference = ifcopenshell.open(path).by_guid(guid)
    candidate = ifcopenshell.open(scene.path).by_guid(guid)
    assert DEFAULT_CONFIG.properties_include_material is False
    assert property_score(reference, candidate, 0.05,
                          DEFAULT_CONFIG.properties_ignore)["score"] == 1.0
    with_flag = property_score(reference, candidate, 0.05,
                               DEFAULT_CONFIG.properties_ignore,
                               include_material=True)
    assert with_flag["score"] < 1.0, "the flag does not credit the material"
    assert "Material" in entity_properties(reference, (), True, False)


def test_a_type_assignment_replaces_the_type_the_element_had():
    scene, ground, _upper, guids = fixture("type.ifc")
    model = ifcopenshell.open(scene.path)
    first = model.create_entity("IfcWallType", GlobalId=ifcopenshell.guid.new(),
                                Name="Type A", PredefinedType="NOTDEFINED")
    second = model.create_entity("IfcWallType", GlobalId=ifcopenshell.guid.new(),
                                 Name="Type B", PredefinedType="NOTDEFINED")
    goldlib.assign_type(model, guids["south"], first.GlobalId,
                        ifcopenshell.guid.new())
    goldlib.assign_type(model, guids["south"], second.GlobalId,
                        ifcopenshell.guid.new())
    path = os.path.join(WORK, "type_out.ifc")
    model.write(path)
    import ifcopenshell.util.element as element_util
    done = ifcopenshell.open(path)
    assert element_util.get_type(done.by_guid(guids["south"])).Name == "Type B"
    holding = [r for r in done.by_type("IfcRelDefinesByType")
               if done.by_guid(guids["south"]) in (r.RelatedObjects or ())]
    assert len(holding) == 1


def test_the_topology_graph_reads_the_type_relation_only_when_asked():
    from modifc_score import topology as topo

    scene, ground, _upper, guids = fixture("type_topology.ifc")
    model = ifcopenshell.open(scene.path)
    wall_type = model.create_entity(
        "IfcWallType", GlobalId=ifcopenshell.guid.new(), Name="Type A",
        PredefinedType="NOTDEFINED")
    goldlib.assign_type(model, guids["south"], wall_type.GlobalId,
                        ifcopenshell.guid.new())
    path = os.path.join(WORK, "type_topology_out.ifc")
    model.write(path)
    edited = ifcopenshell.open(path)
    default = topo.graph_delta(scene.model, edited)
    with_flag = topo.graph_delta(
        scene.model, edited,
        relations=tuple(topo.TOPOLOGY_RELATIONS) + ("IfcRelDefinesByType",))
    assert not default.edges_added
    assert with_flag.edges_added, "the extra relation class was not read"


# ---------------------------------------------------------- another storey


def test_moving_to_another_storey_keeps_or_shifts_the_world_position():
    scene, ground, upper, guids = fixture("storey.ifc")
    guid = guids["c_mid"]
    before = _world_box(scene.model, guid)
    kept = _apply(scene, [ops.Call("move_to_storey",
                                   (guid, upper.GlobalId,
                                    ifcopenshell.guid.new(), True))],
                  "storey_keep.ifc")
    shifted = _apply(scene, [ops.Call("move_to_storey",
                                      (guid, upper.GlobalId,
                                       ifcopenshell.guid.new(), False))],
                     "storey_shift.ifc")
    assert np.abs(_world_box(kept, guid)[0] - before[0]).max() < 1e-6
    assert abs(float(_world_box(shifted, guid)[0][2] - before[0][2]) - 3.5) < 1e-6
    holder = [r for r in kept.by_type("IfcRelContainedInSpatialStructure")
              if kept.by_guid(guid) in (r.RelatedElements or ())]
    assert len(holder) == 1
    assert holder[0].RelatingStructure.GlobalId == upper.GlobalId


def test_a_wall_that_carries_a_door_is_not_moved_to_another_storey():
    scene, ground, upper, guids = fixture("storey_refuse.ifc")
    ops.reset_rejections()
    assert ops.plan_move_to_storey(scene, scene.by_guid(guids["south"]),
                                   rng_of(2), "T-1") is None
    assert ops.rejection_counts().get("restorey_leaves_fillings")


# -------------------------------------------------------------- re-hosting


def test_rehosting_moves_the_opening_and_heals_the_wall_it_left():
    scene, ground, _upper, guids = fixture("rehost.ifc")
    plan = ops.plan_rehost(scene, scene.by_guid(guids["door"]), rng_of(4), "T-1")
    assert plan is not None, "no wall could take the door"
    done = _apply(scene, plan.calls, "rehost_out.ifc")
    leaf = done.by_guid(guids["door"])
    opening = leaf.FillsVoids[0].RelatingOpeningElement
    host = opening.VoidsElements[0].RelatingBuildingElement
    assert host.GlobalId == plan.params["host_to_guid"]
    left = [v for v in done.by_guid(plan.params["host_from_guid"]).HasOpenings]
    assert not left, "the wall the element left is still cut"


def test_rehosting_refuses_a_place_where_something_already_stands():
    """A wall long enough for the leaf is not a wall the leaf can stand in."""
    model, ground, upper, guids = two_storey_model()
    # A slab standing on edge fills the whole of the wall the door would move
    # to, so every position along that wall is occupied.
    add_box(model, ground, "IfcSlab", 8.0, 0.9, 0.0, 3.0, 0.4, 3.0,
            "Blocking panel")
    scene = scene_of(model, "rehost_refuse.ifc")
    ops.reset_rejections()
    blocked = scene.by_guid(guids["gap_left"]).GlobalId
    for seed in range(6):
        plan = ops.plan_rehost(scene, scene.by_guid(guids["door"]),
                               rng_of(seed), "T-1")
        if plan is not None:
            assert plan.params["host_to_guid"] != blocked, \
                "the leaf was hung in the wall the panel fills"
    assert ops.rejection_counts().get("rehost_element_collides"), \
        "the collision rule never fired"


# ---------------------------------------------------------- copy and array


def test_a_copy_stands_at_the_stated_offset_with_the_same_size():
    scene, ground, _upper, guids = fixture("copy.ifc")
    plan = ops.plan_copy(scene, scene.by_guid(guids["c_mid"]), rng_of(6),
                         "COL-CRE-DIR-T-001")
    assert plan is not None
    done = _apply(scene, plan.calls, "copy_out.ifc")
    original = _world_box(scene.model, guids["c_mid"])
    copy = _world_box(done, plan.created_guids[0])
    size_before = original[1] - original[0]
    size_after = copy[1] - copy[0]
    assert np.abs(size_after - size_before).max() < 1e-6
    offset = copy[0] - original[0]
    assert abs(float(offset[plan.params["axis"]])
               - plan.params["sign"] * plan.params["distance"]) < 1e-6
    assert done.by_guid(plan.created_guids[0]).Name == plan.params["name"]


def test_an_array_writes_evenly_spaced_copies():
    scene, ground, _upper, guids = fixture("array.ifc")
    plan = ops.plan_array(scene, scene.by_guid(guids["c_mid"]), rng_of(8),
                          "COL-CRE-DIR-T-002")
    assert plan is not None
    done = _apply(scene, plan.calls, "array_out.ifc")
    origin = _world_box(scene.model, guids["c_mid"])[0]
    axis = plan.params["axis"]
    for step, guid in enumerate(plan.created_guids, start=1):
        here = _world_box(done, guid)[0]
        assert abs(float(here[axis] - origin[axis])
                   - step * plan.params["sign"] * plan.params["spacing"]) < 1e-6


def test_a_copy_is_refused_for_an_element_that_hosts_a_filling():
    scene, ground, _upper, guids = fixture("copy_refuse.ifc")
    assert ops.plan_copy(scene, scene.by_guid(guids["south"]), rng_of(9),
                         "T-1") is None


# ------------------------------------------------------------ replacement


def test_a_replacement_takes_the_old_opening_out_and_cuts_a_new_one():
    scene, ground, _upper, guids = fixture("replace.ifc")
    plan = ops.plan_replace(scene, scene.by_guid(guids["door"]), rng_of(10),
                            "WIN-CRE-DIR-T-001")
    assert plan is not None and plan.family == "window"
    done = _apply(scene, plan.calls, "replace_out.ifc")
    try:
        done.by_guid(guids["door"])
    except Exception:
        pass
    else:
        raise AssertionError("the replaced element is still in the model")
    new = done.by_guid(plan.created_guids[0])
    assert new.is_a("IfcWindow")
    host = new.FillsVoids[0].RelatingOpeningElement.VoidsElements[0]
    assert host.RelatingBuildingElement.GlobalId == plan.params["host_guid"]


# --------------------------------------------------------- sets and scopes


def test_a_set_phrase_resolves_to_every_member_and_to_nothing_else():
    scene, ground, _upper, guids = fixture("set.ifc")
    candidates = anchor_lib.set_anchors(scene, "column", rng_of(1))
    assert candidates, "no set phrase was offered for the columns"
    anchor = next(a for a in candidates if a.params["scope"] == "storey")
    resolved = anchor.resolve(scene)
    expected = sorted(e.GlobalId for e in
                      scene.on_storey("column", ground.GlobalId))
    assert resolved == expected
    assert "all the columns" in anchor.phrase


def test_a_conditional_set_keeps_only_the_members_over_the_threshold():
    scene, ground, _upper, guids = fixture("set_conditional.ifc")
    candidates = anchor_lib.set_anchors(scene, "wall", rng_of(1),
                                        conditional=True)
    assert candidates, "no conditional set phrase was offered"
    anchor = candidates[0]
    condition = anchor.params["condition"]
    resolved = set(anchor.resolve(scene))
    pool = anchor_lib._set_pool(anchor, scene)
    assert 0 < len(resolved) < len(pool)
    for element in pool:
        value = anchor_lib.measure(scene, element, condition["measure"])
        assert (element.GlobalId in resolved) == (value > condition["threshold"])
        assert abs(value - condition["threshold"]) >= anchor_lib.CONDITION_MARGIN
    # The threshold reads as a requirement rather than as a number off the data,
    # and it divides the set rather than shaving one member off an end.
    step = anchor_lib.CONDITION_STEP
    assert abs(condition["threshold"] / step
               - round(condition["threshold"] / step)) < 1e-9
    share = len(resolved) / len(pool)
    assert anchor_lib.CONDITION_KEEP[0] - 1e-9 <= share \
        <= anchor_lib.CONDITION_KEEP[1] + 1e-9, share


def test_a_batch_writes_the_edit_once_for_every_member():
    scene, ground, _upper, guids = fixture("batch.ifc")
    anchor = next(a for a in anchor_lib.set_anchors(scene, "column", rng_of(1))
                  if a.params["scope"] == "storey")
    members = [scene.by_guid(g) for g in anchor.resolve(scene)]
    plan = ops.plan_batch(scene, members, rng_of(12), "COL-UPD-TOP-T-001",
                          pool=[m.GlobalId for m in members])
    assert plan is not None
    assert plan.params["scope"] == "batch"
    assert len(plan.calls) == len(members)
    assert set(plan.target_guids) == {m.GlobalId for m in members}
    assert "scope.batch" in ops.family_tags(plan, anchor.kind)


def test_a_batch_resize_never_shortens_a_wall_below_its_door():
    """A wall shortened below its door's head would leave the door in the air."""
    scene, ground, _upper, guids = fixture("batch_resize.ifc")
    walls = [scene.by_guid(guids[name]) for name in ("south", "north")]
    ops.reset_rejections()
    floor = ops._lowest_safe_depth(scene, walls[0])
    assert floor > 2.1, "the wall's own door sets no floor"
    for seed in range(12):
        built = ops._batch_resize(scene, walls, rng_of(seed), "T-1")
        if built is None:
            continue
        assert built[2]["new"] >= floor, built[2]["new"]


def test_the_funnel_refuses_a_batch_that_missed_a_member():
    scene, ground, _upper, guids = fixture("batch_miss.ifc")
    members = [guids["c_west"], guids["c_mid"], guids["c_east"]]
    model = ifcopenshell.open(scene.path)
    for guid in members[:-1]:
        goldlib.set_property_value(model, guid, "Pset_ColumnCommon",
                                   "FireRating", "F60", "IfcLabel",
                                   ifcopenshell.guid.new(),
                                   ifcopenshell.guid.new())
    path = os.path.join(WORK, "batch_miss_out.ifc")
    model.write(path)
    outcome = verify.check_batch_scope(scene.path, path, members, members)
    assert not outcome.ok and outcome.reason == "batch_member_unchanged"


def test_the_funnel_refuses_a_batch_that_reached_outside_the_set():
    scene, ground, _upper, guids = fixture("batch_spill.ifc")
    members = [guids["c_west"], guids["c_mid"]]
    pool = members + [guids["c_east"]]
    model = ifcopenshell.open(scene.path)
    for guid in pool:
        goldlib.set_property_value(model, guid, "Pset_ColumnCommon",
                                   "FireRating", "F60", "IfcLabel",
                                   ifcopenshell.guid.new(),
                                   ifcopenshell.guid.new())
    path = os.path.join(WORK, "batch_spill_out.ifc")
    model.write(path)
    outcome = verify.check_batch_scope(scene.path, path, members, pool)
    assert not outcome.ok and outcome.reason == "batch_changed_outside_set"


def test_the_funnel_accepts_a_batch_that_changed_exactly_the_set():
    scene, ground, _upper, guids = fixture("batch_ok.ifc")
    members = [guids["c_west"], guids["c_mid"]]
    pool = members + [guids["c_east"]]
    model = ifcopenshell.open(scene.path)
    for guid in members:
        goldlib.set_property_value(model, guid, "Pset_ColumnCommon",
                                   "FireRating", "F60", "IfcLabel",
                                   ifcopenshell.guid.new(),
                                   ifcopenshell.guid.new())
    path = os.path.join(WORK, "batch_ok_out.ifc")
    model.write(path)
    outcome = verify.check_batch_scope(scene.path, path, members, pool)
    assert outcome.ok, outcome.reason


# ------------------------------------------------- ordinal and negation


def test_an_ordinal_phrase_counts_from_the_named_direction():
    model, ground, upper, guids = two_storey_model()
    wall = guids["south"]
    for index, along in enumerate((0.6, 2.2, 3.6)):
        goldlib.add_filling(
            model, "IfcWindow", ifcopenshell.guid.new(), f"W{index}", wall,
            ifcopenshell.guid.new(), ifcopenshell.guid.new(),
            ifcopenshell.guid.new(), ifcopenshell.guid.new(),
            along, -0.05, 0.9, 0.5, 1.0, 0.3, None, 0.0, 0.2)
    scene = scene_of(model, "ordinal.ifc")
    windows = sorted(
        (float(scene.centre(scene.by_guid(g))[0]), g)
        for g in scene.hosted_by(scene.by_guid(wall))
        if scene.family_of(scene.by_guid(g)) == "window")
    target = scene.by_guid(windows[1][1])
    anchors = anchor_lib.ordinal_anchors(scene, target, rng_of(1))
    assert anchors, "no ordinal phrase was offered"
    from_west = [a for a in anchors
                 if a.params["axis"] == 0 and a.params["sign"] == 1]
    assert from_west and from_west[0].params["index"] == 1
    assert "second window from the west" in from_west[0].phrase
    assert from_west[0].resolve(scene) == [target.GlobalId]


def test_an_ordinal_phrase_refuses_a_row_it_cannot_tell_apart():
    model, ground, upper, guids = two_storey_model()
    wall = guids["north"]
    for index, along in enumerate((1.0, 1.05)):
        goldlib.add_filling(
            model, "IfcWindow", ifcopenshell.guid.new(), f"N{index}", wall,
            ifcopenshell.guid.new(), ifcopenshell.guid.new(),
            ifcopenshell.guid.new(), ifcopenshell.guid.new(),
            along, -0.05, 0.9, 0.04, 1.0, 0.3, None, 0.0, 0.2)
    scene = scene_of(model, "ordinal_tie.ifc")
    target = scene.by_guid([g for g in scene.hosted_by(scene.by_guid(wall))
                            if scene.family_of(scene.by_guid(g)) == "window"][0])
    for anchor in anchor_lib.ordinal_anchors(scene, target, rng_of(1)):
        assert anchor.resolve(scene) == [], "a tied row was counted anyway"


def test_a_negation_phrase_names_the_room_no_window_bounds():
    model, ground, upper, guids = two_storey_model()
    # The hall gets a window in the wall that bounds it, so the kitchen is the
    # one room on the storey no window bounds and the phrase names it alone.
    window = goldlib.add_filling(
        model, "IfcWindow", ifcopenshell.guid.new(), "Hall window",
        guids["north"], ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
        3.0, -0.05, 0.9, 0.9, 1.2, 0.3, None, 0.0, 0.2)
    goldlib.add_space_boundary(model, ifcopenshell.guid.new(), guids["hall"],
                               window.GlobalId)
    scene = scene_of(model, "negation.ifc")
    kitchen = scene.by_guid(guids["kitchen"])
    anchors = anchor_lib.negation_anchors(scene, kitchen, rng_of(1))
    without_window = [a for a in anchors
                      if a.params.get("missing") == "window"]
    assert without_window, "no negation phrase was offered"
    assert without_window[0].resolve(scene) == [kitchen.GlobalId]
    assert "no window bounds" in without_window[0].phrase


# --------------------------------------------------------- the registry


def test_the_registry_names_every_0_6_0_family_after_the_taxonomy():
    wanted = ("op.update.rotate", "op.update.mirror", "op.update.pset",
              "op.update.material", "op.update.type_object",
              "op.update.restorey", "op.update.rehost", "op.copy", "op.array",
              "op.replace", "scope.batch", "scope.conditional", "ref.set",
              "ref.ordinal", "ref.negation")
    for tag in wanted:
        assert tag in families.BY_TAG, tag
        assert families.layer_of(tag) in families.LAYERS, tag
    for tag, (planner, allowed) in ops.NEW_UPDATE_PLANNERS.items():
        assert tag in families.BY_TAG and callable(planner) and allowed
    for tag, (planner, allowed) in ops.NEW_CREATE_PLANNERS.items():
        assert tag in families.BY_TAG and callable(planner) and allowed
    for _kind, tag in families.OPERATION_TAG.items():
        assert families.layer_of(tag) == "operation", tag


def test_the_0_6_0_gold_calls_have_the_signatures_the_scripts_carry():
    import inspect

    expected = {
        "rotate": ["guid", "degrees", "pivot_x", "pivot_y"],
        "mirror": ["guid", "point_x", "point_y", "normal_x", "normal_y"],
        "set_property_value": ["guid", "pset_name", "property_name", "value",
                               "value_type", "pset_guid", "relation_guid"],
        "assign_material": ["guid", "material_name", "relation_guid"],
        "assign_type": ["guid", "type_guid", "relation_guid"],
        "move_to_storey": ["guid", "storey_guid", "relation_guid",
                           "keep_world"],
        "rehost_filling": ["guid", "host_guid", "along", "across", "sill",
                           "leaf_along", "leaf_across", "leaf_sill",
                           "thickness", "leaf_depth"],
        "copy_element": ["guid", "new_guid", "dx", "dy", "dz", "name",
                         "relation_guid"],
        "array_elements": ["guid", "new_guids", "dx", "dy", "dz", "names",
                           "relation_guids"],
    }
    for name, arguments in expected.items():
        got = list(inspect.signature(getattr(goldlib, name)).parameters)[1:]
        assert got == arguments, f"{name}: {got}"


def test_the_published_scorer_reading_is_off_by_default():
    from modifc_score.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG.properties_include_material is False
    assert DEFAULT_CONFIG.properties_include_type is False
    assert tuple(DEFAULT_CONFIG.topology_relations_extra) == ()


def main() -> int:
    global WORK
    WORK = tempfile.mkdtemp(prefix="modifc_gen_v06_tests_")
    os.environ["MODIFC_GEOM_CACHE"] = os.path.join(WORK, "geom_index")
    from . import test_families_v05, test_placement_rules
    test_families_v05.WORK = WORK
    test_placement_rules.WORK = WORK
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    try:
        for test in tests:
            ops.reset_rejections()
            settings.configure(family_shares={}, family_weights={})
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
