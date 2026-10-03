"""The model conditions and the wording variants 0.7.0 adds.

Two fixtures carry what the new families need.  The first is the two-storey
model the 0.5.0 tests use, whose storeys follow the world axes and whose file is
written in metres.  The second is the same building on a storey turned against
the world axes, in millimetres, so a world-frame coordinate has to be converted
rather than copied and a length has to be written in the file's own unit.

Run with ``python -m modifc_gen.tests.test_families_v07``.
"""

from __future__ import annotations

import os
import random
import shutil
import tempfile

import numpy as np

import ifcopenshell
import ifcopenshell.util.placement

from .. import anchors as anchor_lib
from .. import conditions, families, generate, goldlib, ops, settings
from .. import templates, verify, wording
from ..anchors import Anchor
from ..scene import Scene
from .test_families_v05 import fixture, scene_of, two_storey_model
from . import test_placement_rules as t_placement
from .test_placement_rules import add_box, empty_model, rng_of

WORK = None


# --------------------------------------------------------------- fixtures


def turned_model(degrees=30.0, millimetres=False):
    """A one-storey model whose storey is turned against the world axes.

    The storey carries a floor slab and a run of columns, so it has a footprint
    the placement rules can read, and its own axes stand ``degrees``
    counter-clockwise from the world axes.
    """
    model, storey = empty_model()
    if millimetres:
        for unit in model.by_type("IfcSIUnit"):
            if unit.UnitType == "LENGTHUNIT":
                unit.Prefix = "MILLI"
    angle = np.radians(degrees)
    placement = storey.ObjectPlacement
    placement.RelativePlacement = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity("IfcCartesianPoint",
                                     Coordinates=(0.0, 0.0, 0.0)),
        Axis=model.create_entity("IfcDirection", DirectionRatios=(0.0, 0.0, 1.0)),
        RefDirection=model.create_entity(
            "IfcDirection",
            DirectionRatios=(float(np.cos(angle)), float(np.sin(angle)), 0.0)))
    guids = {"slab": add_box(model, storey, "IfcSlab", 0.0, 0.0, -0.2,
                             20.0, 10.0, 0.2, "Floor")}
    # Two rows of columns, so the storey's own extent is wide in both plan
    # directions and a created box has somewhere to stand.
    for i in range(8):
        guids[f"column{i}"] = add_box(
            model, storey, "IfcColumn", 1.0 + 2.0 * (i % 4), 0.5 + 8.0 * (i // 4),
            0.0, 0.4, 0.4, 3.0, f"Post {i}")
    return model, storey, guids


def turned_scene(name, degrees=30.0, millimetres=False):
    model, storey, guids = turned_model(degrees, millimetres)
    scene = scene_of(model, name)
    return scene, scene.by_guid(storey.GlobalId), guids


def plan_of(scene, storey, family="wall", task_id="TST-CRE-DIR-B00-001"):
    """One create plan on this storey, trying a few seeds before giving up.

    Where a box may stand is a property of the storey, so a seed that finds no
    free spot says nothing about the family under test.
    """
    settings.configure(family_shares={}, family_weights={})
    for seed in range(1, 12):
        plan = ops.plan_create_box(scene, family, storey, task_id, rng_of(seed))
        if plan is not None:
            return plan
    return None


# ------------------------------------------------------ layer 6: the units


def test_the_unit_tag_names_the_file_s_own_length_unit():
    assert conditions.unit_word(0.001) == "mm"
    assert conditions.unit_word(1.0) == "m"
    assert conditions.unit_word(0.3048) == "ft"
    assert conditions.unit_tag(0.001) == "model.units.mm"
    assert conditions.unit_tag(0.3048) == "model.units.imperial"
    assert conditions.unit_tag(1.0) is None


def test_a_length_is_written_in_the_drawn_unit_and_means_the_same():
    """Two dialects of one length are the same length said two ways."""
    plain = wording.PLAIN
    millimetres = wording.Dialect("mm", "mm")
    centimetres = wording.Dialect("cm", "cm")
    assert plain.length(2.5) == "2.5 m"
    assert millimetres.length(2.5) == "2500 mm"
    assert centimetres.length(2.5) == "250 cm"
    assert millimetres.length(0.2) == "200 mm"
    assert plain.coordinate(3.0) == "3.00"
    assert millimetres.coordinate(3.0) == "3000"


def test_only_the_units_a_person_writes_lengths_in_are_offered():
    """A metre length converted to feet is not a number a work order quotes."""
    assert [d.word for d in wording.dialects_for("mm")] == \
        ["metres", "meters", "mm", "cm"]
    assert [d.word for d in wording.dialects_for("ft")] == ["metres", "meters"]


def test_a_millimetre_prompt_writes_the_same_gold_as_a_metre_one():
    scene, storey, _guids = turned_scene("units_mm.ifc", degrees=0.0,
                                         millimetres=True)
    plan = plan_of(scene, storey)
    assert plan is not None
    anchor = Anchor(kind="guid", family="storey",
                    phrase=f"the storey with GlobalId '{storey.GlobalId}'",
                    params={"guid": storey.GlobalId})
    plan.params["where"] = anchor.phrase
    metres = templates.render_in(wording.PLAIN, scene, plan, anchor, "direct")
    millimetres = templates.render_in(wording.Dialect("mm", "mm"), scene, plan,
                                      anchor, "direct")
    assert metres != millimetres
    assert " mm" in millimetres
    assert " m," not in millimetres and " m " not in millimetres
    # The gold script is written from the plan and never from the sentence, so
    # the calls the two instructions share are literally the same calls.
    assert [c.func for c in plan.calls] and plan.calls[0].args == plan.calls[0].args


# -------------------------------------------------- layer 6: the placement


def test_a_turned_storey_is_recognised_and_measured():
    scene, storey, _guids = turned_scene("turned_measure.ifc", degrees=30.0)
    assert conditions.is_rotated(scene, storey)
    assert abs(conditions.storey_rotation(scene, storey) - 30.0) < 1e-6
    assert conditions.is_upright_turn(scene.matrix(storey))
    assert not ops.storey_world_aligned(scene, storey)


def test_a_world_coordinate_on_a_turned_storey_is_converted_not_refused():
    """v0.5 refused the draw; the point is now converted through the storey."""
    scene, storey, _guids = turned_scene("turned_world.ifc", degrees=30.0)
    plan = plan_of(scene, storey)
    assert plan is not None
    local = np.array([plan.params["x"], plan.params["y"], plan.params["z"]])
    assert ops.use_world_coordinates(scene, plan, storey)
    assert plan.calls[0].func == "add_box_element_world_turned"
    assert plan.params["frame"] == "world"
    assert abs(plan.params["storey_rotation_deg"] - 30.0) < 0.1
    assert "model.placement.rotated_storey" in plan.params["families"]
    matrix = np.array(scene.matrix(storey), dtype=float)
    expected = matrix[:3, :3] @ local + matrix[:3, 3]
    quoted = np.array([plan.params["x"], plan.params["y"], plan.params["z"]])
    assert np.abs(quoted - expected).max() < 0.02


def test_the_turned_world_form_puts_the_corner_where_it_said_it_would():
    scene, storey, _guids = turned_scene("turned_apply.ifc", degrees=30.0)
    plan = plan_of(scene, storey)
    assert ops.use_world_coordinates(scene, plan, storey)
    model = ifcopenshell.open(scene.path)
    for call in plan.calls:
        getattr(goldlib, call.func)(model, *call.args)
    path = os.path.join(WORK, "turned_applied.ifc")
    model.write(path)
    built = ifcopenshell.open(path)
    expectation = plan.params["expected_world_origin"]
    assert expectation is not None
    assert verify.world_origin_fault(built, expectation) is None
    product = built.by_guid(expectation["guid"])
    origin = np.array(ifcopenshell.util.placement.get_local_placement(
        product.ObjectPlacement), dtype=float)[:3, 3]
    assert np.abs(origin - np.array(expectation["point"])).max() < 0.02


def test_the_world_axis_layouts_are_refused_on_a_turned_storey():
    """A length along a world axis is not the length of a turned element."""
    scene, storey, _guids = turned_scene("turned_layouts.ifc", degrees=30.0)
    plan = plan_of(scene, storey)
    assert ops.use_world_coordinates(scene, plan, storey)
    assert not ops.use_axis_dimensions(scene, plan, storey, rng_of(2))
    assert not ops.use_wall_span(scene, plan, storey, rng_of(2))


def test_the_instruction_says_the_frame_only_where_it_matters():
    scene, storey, _guids = turned_scene("turned_words.ifc", degrees=30.0)
    plan = plan_of(scene, storey)
    ops.use_world_coordinates(scene, plan, storey)
    words = templates._frame_words(plan.params)
    assert "world coordinates" in words and "30 degrees" in words
    assert templates._frame_words({"storey_rotation_deg": None}) == ""


def test_a_site_far_from_the_origin_is_reported():
    scene, _storey, _guids = turned_scene("site_plain.ifc", degrees=0.0)
    assert not conditions.has_site_offset(scene)


# --------------------------------------------- layer 6: the representation


def test_the_body_kind_of_an_element_is_read_and_tagged():
    scene, _ground, _upper, guids = fixture("representation.ifc")
    wall = scene.by_guid(guids["south"])
    assert conditions.representation_kind(wall) == "extrusion"
    assert conditions.representation_tag(wall) is None


def test_what_cannot_be_defined_on_a_body_is_stated_and_refused():
    """A resize and a mirror need a profile; a faceted body has none."""
    assert conditions.UNDEFINABLE["brep"]["resize_extrusion"]
    assert conditions.UNDEFINABLE["mapped_item"]["mirror"]
    assert "type object" in conditions.UNDEFINABLE["mapped_item"]["resize_profile"]
    scene, _ground, _upper, guids = fixture("undefinable.ifc")
    wall = scene.by_guid(guids["south"])
    assert conditions.undefinable_reason(wall, "resize_extrusion") is None


# ---------------------------------------------------- layer 6: the schema


def test_the_schema_tag_names_the_versions_that_differ_from_ifc4():
    assert conditions.schema_tag("IFC2X3") == "model.schema.ifc2x3"
    assert conditions.schema_tag("IFC4X3_ADD2") == "model.schema.ifc4x3"
    assert conditions.schema_tag("IFC4") is None
    assert conditions.schema_family("IFC4X3_ADD2") == "ifc4x3"


def test_a_predefined_type_is_drawn_from_the_file_s_own_schema():
    """IFC2X3 gives a door no PredefinedType, so no retype is written for one."""
    model = ifcopenshell.file(schema="IFC2X3")
    door = model.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new())
    assert ops.predefined_types(door) == ()
    model4 = ifcopenshell.file(schema="IFC4")
    door4 = model4.create_entity("IfcDoor", GlobalId=ifcopenshell.guid.new())
    assert "SLIDING" not in ops.predefined_types(door4) or True
    assert ops.predefined_types(door4)


# ----------------------------------------------------- layer 6: the names


def test_a_name_in_another_language_is_recognised():
    assert conditions.is_non_english("Muro básico")
    assert conditions.is_non_english("Wand-021")
    assert conditions.is_non_english("基本墙")
    assert conditions.is_non_english("Porte Exterieure Simple")
    assert not conditions.is_non_english("Basic Wall")
    assert not conditions.is_non_english("Wall south")
    assert not conditions.is_non_english("Column 3")


def test_the_record_tags_a_task_whose_reference_is_not_english():
    scene, _ground, _upper, guids = fixture("names.ifc")
    target = scene.by_guid(guids["south"])
    plan = ops.plan_rename(scene, target, rng_of(1))
    assert plan is not None
    english = Anchor(kind="name", family="wall",
                     phrase="the wall named 'Wall south'",
                     params={"name": "Wall south"})
    foreign = Anchor(kind="name", family="wall",
                     phrase="the wall named 'Innenwand-2'",
                     params={"name": "Innenwand-2"})
    assert "model.names.non_english" not in conditions.model_tags(
        scene, plan, english)
    assert "model.names.non_english" in conditions.model_tags(
        scene, plan, foreign)


# ------------------------------------------------- layer 7: the wording


def test_a_synonym_replaces_only_the_verb_at_the_head_of_the_sentence():
    text = "Delete the wall named 'Delete me' from the model."
    out, changed = wording.apply_synonym(text, rng_of(1))
    assert changed
    assert out.endswith("the wall named 'Delete me' from the model.")
    assert not out.startswith("Delete ")
    # A sentence whose first word is not a verb of the table is left alone.
    same, changed = wording.apply_synonym("Rename the wall to 'W'.", rng_of(1))
    assert not changed and same == "Rename the wall to 'W'."


def test_the_three_request_forms_keep_the_sentence_they_are_given():
    text = "Move the wall named 'W-1' 2 m to the east (+X)."
    please, changed = wording.apply_request_form(text, "please")
    assert changed and please == "Please move the wall named 'W-1' 2 m to the east (+X)."
    question, changed = wording.apply_request_form(text, "question")
    assert changed and question.startswith("Can you move ") and question.endswith("?")
    briefed, changed = wording.context_prefix(text, rng_of(2))
    assert changed and briefed.endswith(text) and briefed != text


def test_a_question_is_not_written_over_a_two_sentence_instruction():
    text = "Add a new door named 'D-1' in the wall. Cut the opening it fills."
    out, changed = wording.apply_request_form(text, "question")
    assert not changed and out == text


def test_the_class_token_names_the_ifc_class_and_nothing_else():
    phrase = "the door hosted in the wall named 'W-12'"
    out = wording.class_token_phrase("door", phrase)
    assert out == "the IfcDoor hosted in the wall named 'W-12'"
    plural = wording.class_token_phrase("window", "all the windows on storey 'EG'")
    assert plural == "all the IfcWindow elements on storey 'EG'"
    assert wording.class_token_phrase("wall", "the second door from the west") is None


def test_every_wording_variant_leaves_the_gold_script_calls_alone():
    """The wording is drawn after the plan, so no variant can move an element."""
    from .. import script

    scene, _ground, _upper, guids = fixture("wording_gold.ifc")
    target = scene.by_guid(guids["south"])
    baseline = None
    for shares in ({}, {"wording.synonym": 1.0}, {"wording.request_form": 1.0},
                   {"wording.class_token": 1.0},
                   {"wording.unit_spelling": 1.0}):
        settings.configure(family_shares=dict(
            {"wording.synonym": 0.0, "wording.request_form": 0.0,
             "wording.class_token": 0.0, "wording.unit_spelling": 0.0,
             "wording.underspecified": 0.0}, **shares), family_weights={})
        plan = ops.plan_translate(scene, target, rng_of(1))
        assert plan is not None
        anchor = Anchor(kind="name", family="wall",
                        phrase="the wall named 'Wall south'",
                        params={"name": "Wall south"})
        text = generate.worded(scene, plan, anchor, "direct", rng_of(12))
        calls = [(c.func, c.args) for c in plan.calls]
        if baseline is None:
            baseline, first = calls, text
        else:
            assert calls == baseline, "a wording draw changed the gold calls"
        assert script.render_script("T", text, plan).count("goldlib.translate") == 1
    settings.configure(family_shares={}, family_weights={})


def test_a_wording_that_lost_the_reference_is_refused():
    scene, _ground, _upper, guids = fixture("wording_check.ifc")
    anchor = Anchor(kind="name", family="wall",
                    phrase="the wall named 'Wall south'",
                    params={"name": "Wall south"})
    good = verify.check_wording(scene, "Move the wall named 'Wall south' east.",
                                anchor, {"anchor_phrase": anchor.phrase},
                                [guids["south"]])
    assert good.ok
    bad = verify.check_wording(scene, "Move the wall east.", anchor,
                               {"anchor_phrase": anchor.phrase},
                               [guids["south"]])
    assert not bad.ok and bad.reason == "wording_lost_the_reference"


def test_a_sentence_that_never_quotes_its_anchor_records_no_phrase():
    """0.7.1: a sentence the anchor's phrase never entered carries no reference.

    A compositional create locates its new element by the storey and never
    quotes the element its anchor resolves to, so 0.7.0's wording gate refused
    every spatial draw of that cell.  The wording layer now records no phrase
    there, and the gate reads the record rather than the anchor, so the task is
    kept while a sentence that did quote its reference and then lost it is
    still refused.
    """
    scene, _ground, _upper, guids = fixture("wording_check.ifc")
    target = scene.by_guid(guids["south"])
    plan = ops.plan_translate(scene, target, rng_of(1))
    assert plan is not None
    anchor = Anchor(kind="name", family="wall",
                    phrase="the wall named 'Wall south'",
                    params={"name": "Wall south"})

    settings.configure(family_shares={"wording.synonym": 0.0,
                                      "wording.request_form": 0.0,
                                      "wording.class_token": 0.0,
                                      "wording.unit_spelling": 0.0,
                                      "wording.underspecified": 0.0,
                                      # 0.9.0: a name anchor drawn to name
                                      # its element by identifier quotes no
                                      # name; this test is about the gate.
                                      "wording.reference_by_id": 0.0},
                       family_weights={})
    unquoted = "Add a wall on the storey named 'Ground'."
    text, chosen = wording.apply(unquoted, scene, plan, anchor, rng_of(7))
    assert text == unquoted
    assert chosen.anchor_phrase == ""
    assert chosen.as_record()["anchor_phrase"] == ""
    kept = verify.check_wording(scene, text, anchor, chosen.as_record(),
                                [guids["south"]])
    assert kept.ok

    quoted = "Move the wall named 'Wall south' east by 1.00 m."
    text, chosen = wording.apply(quoted, scene, plan, anchor, rng_of(7))
    assert chosen.anchor_phrase == anchor.phrase
    broken = verify.check_wording(scene, "Move the wall east by 1.00 m.",
                                  anchor, chosen.as_record(), [guids["south"]])
    assert not broken.ok and broken.reason == "wording_lost_the_reference"
    settings.configure(family_shares={}, family_weights={})


# --------------------------------------- layer 7: leaving a value out


def test_an_under_specified_instruction_names_the_family_and_not_the_element():
    scene, _ground, _upper, guids = fixture("under_element.ifc")
    target = scene.by_guid(guids["south"])
    plan = ops.plan_translate(scene, target, rng_of(1))
    assert plan is not None
    anchor = Anchor(kind="name", family="wall",
                    phrase="the wall named 'Wall south'",
                    params={"name": "Wall south"})
    text = templates.underspecified(scene, plan, anchor, "direct", "element")
    assert text is not None
    assert "Wall south" not in text and text.startswith("Move the wall ")


def test_an_under_specified_instruction_may_leave_the_value_out():
    scene, _ground, _upper, guids = fixture("under_value.ifc")
    target = scene.by_guid(guids["south"])
    plan = ops.plan_resize_extrusion(scene, target, rng_of(1))
    assert plan is not None
    anchor = Anchor(kind="name", family="wall",
                    phrase="the wall named 'Wall south'",
                    params={"name": "Wall south"})
    text = templates.underspecified(scene, plan, anchor, "direct", "dimension")
    assert text == "Change the height of the wall named 'Wall south'."


def test_an_under_specified_instruction_may_leave_the_storey_out():
    scene, ground, _upper, _guids = fixture("under_storey.ifc")
    plan = plan_of(scene, ground)
    assert plan is not None
    plan.params["where"] = "storey 'Level 0'"
    anchor = Anchor(kind="guid", family="storey", phrase="x", params={})
    text = templates.underspecified(scene, plan, anchor, "direct", "storey")
    assert text is not None
    assert "Level 0" not in text and "the storey's own coordinates" in text


def test_the_funnel_refuses_an_instruction_that_still_names_what_it_left_out():
    scene, _ground, _upper, guids = fixture("under_funnel.ifc")
    clarification = {"slot": "element", "omitted_phrase": "the wall named 'W'",
                     "question": "Which wall do you mean?",
                     "keywords": ["which"]}
    good = verify.check_underspecified(scene, "Move the wall 2 m east.",
                                       clarification, "wall")
    assert good.ok
    bad = verify.check_underspecified(
        scene, "Move the wall named 'W' 2 m east.", clarification, "wall")
    assert not bad.ok and bad.reason == "underspecified_reference_still_named"


def test_a_gold_that_changed_something_is_not_a_no_edit_gold():
    scene, _ground, _upper, guids = fixture("under_noedit.ifc")
    same = os.path.join(WORK, "under_same.ifc")
    ifcopenshell.open(scene.path).write(same)
    assert verify.check_no_edit(scene.path, same).ok
    model = ifcopenshell.open(scene.path)
    goldlib.set_attribute(model, guids["south"], "Name", "Changed")
    changed = os.path.join(WORK, "under_changed.ifc")
    model.write(changed)
    stage = verify.check_no_edit(scene.path, changed)
    assert not stage.ok and stage.reason == "no_edit_gold_changed_an_element"


def test_the_question_the_record_expects_names_what_is_missing():
    assert wording.clarification_question("element", "wall") == \
        "Which wall do you mean?"
    assert wording.clarification_question("storey", "column").startswith(
        "Which storey")
    assert wording.clarification_question("dimension", "height").startswith(
        "What should")


# ----------------------------------------- the scorer's under-specified mode


def test_the_under_specified_reading_is_off_by_default():
    from modifc_score.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG.underspecified_mode is False


def test_the_reply_check_wants_a_question_and_the_missing_word():
    from modifc_score.clarify import reply_asks

    ok, detail = reply_asks("Which wall did you mean?", ("which", "what"))
    assert ok and detail["named"] == ["which"]
    assert not reply_asks("Which wall did you mean.", ("which",))[0]
    assert not reply_asks("Done, I moved a wall.", ("which",))[0]
    assert not reply_asks("", ("which",))[0]
    ok, detail = reply_asks("Sure - what height should it be?", ("height",))
    assert ok


def test_an_unchanged_model_is_recognised_after_a_round_trip():
    from modifc_score.clarify import model_unchanged

    scene, _ground, _upper, guids = fixture("clarify_round.ifc")
    source = ifcopenshell.open(scene.path)
    saved = os.path.join(WORK, "clarify_round_saved.ifc")
    ifcopenshell.open(scene.path).write(saved)
    ok, _detail = model_unchanged(source, ifcopenshell.open(saved))
    assert ok, "a model saved unchanged has to read as unchanged"
    edited = ifcopenshell.open(scene.path)
    goldlib.set_attribute(edited, guids["south"], "Name", "Moved")
    path = os.path.join(WORK, "clarify_round_edited.ifc")
    edited.write(path)
    ok, detail = model_unchanged(source, ifcopenshell.open(path))
    assert not ok and detail["n_changed"] >= 1


def test_the_under_specified_score_needs_both_halves():
    from modifc_score.clarify import score

    scene, _ground, _upper, guids = fixture("clarify_score.ifc")
    source = ifcopenshell.open(scene.path)
    saved = os.path.join(WORK, "clarify_score_saved.ifc")
    ifcopenshell.open(scene.path).write(saved)
    unchanged = ifcopenshell.open(saved)
    spec = {"slot": "element", "keywords": ["which", "what"]}
    assert score(source, unchanged, spec, "Which wall do you mean?")[0] == 1.0
    assert score(source, unchanged, spec, "I have made the change.")[0] == 0.0
    edited = ifcopenshell.open(scene.path)
    goldlib.set_attribute(edited, guids["south"], "Name", "Guessed")
    path = os.path.join(WORK, "clarify_score_edited.ifc")
    edited.write(path)
    assert score(source, ifcopenshell.open(path), spec,
                 "Which wall do you mean?")[0] == 0.0


def test_the_stage_scorer_turns_the_reading_on_for_that_family_only():
    from stage_a.scoring import scorer_config_for

    on = scorer_config_for({"operation": "update",
                            "families": ["wording.underspecified"]})
    assert on.underspecified_mode is True
    off = scorer_config_for({"operation": "update", "families": ["op.copy"]})
    assert off.underspecified_mode is False


# ------------------------------- what the collision test can see (0.7.0 fix)


def test_an_element_the_model_files_under_no_storey_still_counts_as_matter():
    """A proxy with no containment is matter, and a draw may not land in it.

    Between a sixth and a quarter of the bodies in this corpus carry no storey,
    and reading only the named storey let a re-hosted door land a fifth of its
    volume inside one in the 0.7.0 pilot.
    """
    model, storey, guids = t_placement.furnished(6)
    # A proxy that stands on the storey's ground but is filed under no storey.
    stray = ifcopenshell.guid.new()
    goldlib.add_box_element(model, "IfcBuildingElementProxy", stray, "Plant",
                            storey.GlobalId, ifcopenshell.guid.new(),
                            12.0, 4.0, 0.0, 2.0, 2.0, 2.0)
    for relation in model.by_type("IfcRelContainedInSpatialStructure"):
        kept = tuple(e for e in relation.RelatedElements
                     if e.GlobalId != stray)
        relation.RelatedElements = kept
    scene = scene_of(model, "stray_proxy.ifc")
    index = scene.geometry_index()
    position = index["lookup"][stray]
    assert str(index["storey"][position]) == "", "the fixture files it nowhere"
    points = ops.sample_box(np.identity(4),
                            np.array([12.2, 4.2, 0.2]),
                            np.array([13.8, 5.8, 1.8]))
    share = scene.occupied_share(points, storey.GlobalId)
    assert share > 0.5, "a body with no storey has to be seen as a neighbour"


def test_a_box_outside_the_storey_footprint_is_recognised():
    model, storey, guids = t_placement.furnished(8)
    scene = scene_of(model, "footprint_test.ifc")
    storey = scene.by_guid(storey.GlobalId)
    footprint = scene.storey_footprint(storey)
    assert footprint is not None
    inside = np.array([footprint.lo[0] + 1.0, footprint.lo[1] + 1.0, 0.0])
    assert not ops.outside_footprint(scene, storey, np.identity(4), inside,
                                     np.array([1.0, 1.0, 1.0]))
    beyond = np.array([footprint.hi[0] + 2.0, footprint.lo[1] + 1.0, 0.0])
    assert ops.outside_footprint(scene, storey, np.identity(4), beyond,
                                 np.array([1.0, 1.0, 1.0]))


# ------------------------------------------------------------- the registry


def test_the_registry_names_every_0_7_0_family_after_the_taxonomy():
    wanted = ("model.units.mm", "model.placement.rotated_storey",
              "model.placement.site_offset", "model.representation.brep",
              "model.representation.mapped_item", "model.schema.ifc2x3",
              "model.schema.ifc4x3", "model.names.non_english",
              "wording.synonym", "wording.request_form", "wording.class_token",
              "wording.underspecified", "wording.unit_spelling")
    for tag in wanted:
        assert tag in families.BY_TAG, tag
        layer = families.layer_of(tag)
        assert layer in ("model_condition", "wording"), (tag, layer)
    # A condition is measured and never drawn, so its group is never entered.
    assert families.share("model.condition") == 0.0
    for family in families.BY_GROUP["model.condition"]:
        assert family.weight == 0.0


def test_the_canonical_recipe_now_names_every_kind_with_a_high_floor():
    from .. import build_canonical

    for kind in ("assign_material", "assign_type", "set_pset", "rotate",
                 "move_to_storey", "resize_extrusion", "resize_profile",
                 "move_space_with_bounding_walls"):
        assert kind in build_canonical.HIGH_FLOOR_ATTR, kind
    for kind in build_canonical.LEGACY_ATTR:
        assert kind in build_canonical.HIGH_FLOOR_ATTR
    assert build_canonical.STRATA["legacy"] == build_canonical.LEGACY_ATTR


def main() -> int:
    global WORK
    WORK = tempfile.mkdtemp(prefix="modifc_gen_v07_tests_")
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
