"""Corpus v8 on the generator's side: five references and one delete wording.

The references are asserted to be registered everywhere a reference has to be
registered, to resolve from the model alone, and to single an element out
before the generator will use them.  The delete wording is asserted to name
relationships the element really takes part in, to leave the reference phrase
in the sentence, and to leave the gold script exactly as the plain wording
leaves it, which is what makes it a wording family and not an operation.

Run with pytest.
"""

from __future__ import annotations

import random

import pytest

from modifc_gen import anchors as A
from modifc_gen import families, ops, script, templates
from modifc_gen.anchors import Anchor
from modifc_gen.scene import Scene

MODEL = "data/corpus/auckland/088_231110AC11-FZK-Haus-IFC.ifc"

NEW_KINDS = ("host_of", "joins", "bounds", "under", "without_relation")

BUILDERS = {"host_of": A.host_anchors, "joins": A.joins_anchors,
            "bounds": A.bounds_anchors, "under": A.under_anchors,
            "without_relation": A.without_relation_anchors}

FAMILIES_FOR = {"host_of": ("wall",), "joins": ("door", "window"),
                "bounds": ("wall", "door", "window", "slab"),
                "under": ("slab",),
                "without_relation": ("wall", "column", "slab")}


@pytest.fixture(scope="module")
def scene():
    return Scene(MODEL, MODEL, "")


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_the_kind_is_registered_everywhere(kind):
    assert kind in A.CHAIN_LENGTH
    assert kind in A.CATEGORY
    assert kind in A.RESOLVERS
    assert kind in A.KIND_FAMILY
    assert kind in A.NEW_KINDS
    tag = A.KIND_FAMILY[kind]
    entry = families.BY_TAG.get(tag)
    assert entry is not None, f"{tag} is not in the registry"
    assert families.build(entry) is not None, f"{tag} has no builder"


def unique_anchors(scene, kind, limit=6):
    """Anchors of one kind that single their own element out."""
    rng = random.Random(11)
    found = []
    for family in FAMILIES_FOR[kind]:
        for product in scene.elements(family):
            for anchor in BUILDERS[kind](scene, product, rng) or ():
                if anchor.resolve(scene) == [product.GlobalId]:
                    found.append((anchor, product))
                    if len(found) >= limit:
                        return found
    return found


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_the_reference_singles_an_element_out(scene, kind):
    found = unique_anchors(scene, kind)
    assert found, f"the fixture carries no usable {kind} reference"
    for anchor, product in found:
        assert anchor.kind == kind
        assert anchor.resolve(scene) == [product.GlobalId]


@pytest.mark.parametrize("kind", NEW_KINDS)
def test_the_phrase_reads_as_a_sentence_would(scene, kind):
    for anchor, _product in unique_anchors(scene, kind, limit=3):
        assert anchor.phrase.startswith("the ")
        assert "GlobalId" not in anchor.phrase
        assert anchor.phrase == anchor.phrase.strip()


def test_a_reference_that_names_nothing_resolves_to_nothing(scene):
    empty = Anchor(kind="host_of", family="wall", phrase="",
                   params={"element_guid": "0" * 22})
    assert empty.resolve(scene) == []


def test_the_outside_form_is_read_as_the_outside(scene):
    rng = random.Random(3)
    for family in ("door", "window"):
        for product in scene.elements(family):
            for anchor in A.joins_anchors(scene, product, rng) or ():
                if anchor.params.get("outside"):
                    assert "outside" in anchor.phrase
                    assert "space_b_guid" not in anchor.params
                    return
    pytest.skip("the fixture has no filling that opens to the outside")


# ------------------------------------------------ the delete wording family


def a_delete_plan(scene, rng):
    """One plain delete plan, with the element it removes."""
    for family in ("window", "door", "wall", "column", "slab"):
        for product in scene.elements(family):
            if len(ops._named_relation_clauses(scene, product)) < 2:
                continue
            plan = ops.plan_delete(scene, product, rng)
            if plan is not None and plan.params.get("scope") != "batch":
                plan.params.pop("named_relations", None)
                plan.params.pop("constraint", None)
                return plan, product
    return None, None


def test_the_sentence_names_relationships_the_element_takes_part_in(scene):
    rng = random.Random(7)
    plan, product = a_delete_plan(scene, rng)
    assert plan is not None
    clauses = ops._named_relation_clauses(scene, product)
    assert len(clauses) >= 2
    plan.params["named_relations"] = clauses[:2]
    plan.params["named_relations_form"] = 0
    anchor = A.guid_anchor(scene, product)
    sentence = templates.render(scene, plan, anchor, "direct")
    assert anchor.phrase in sentence
    for entry in clauses[:2]:
        assert entry["text"] in sentence


def test_every_form_of_the_sentence_keeps_the_reference(scene):
    rng = random.Random(7)
    plan, product = a_delete_plan(scene, rng)
    assert plan is not None
    anchor = A.guid_anchor(scene, product)
    plan.params["named_relations"] = ops._named_relation_clauses(scene, product)[:2]
    seen = set()
    for form in range(len(templates._NAMED_RELATION_FORMS)):
        plan.params["named_relations_form"] = form
        sentence = templates.render(scene, plan, anchor, "direct")
        assert anchor.phrase in sentence
        assert sentence.endswith(".")
        seen.add(sentence)
    assert len(seen) == len(templates._NAMED_RELATION_FORMS)


def test_the_wording_leaves_the_gold_script_alone(scene):
    rng = random.Random(7)
    plan, product = a_delete_plan(scene, rng)
    assert plan is not None
    plain = script.render_script("T-001", "plain", plan)
    plan.params["named_relations"] = ops._named_relation_clauses(scene, product)[:2]
    plan.params["named_relations_form"] = 1
    named = script.render_script("T-001", "plain", plan)
    assert plain == named


def test_the_sentence_names_no_element_the_edit_removes(scene):
    """A named relationship is a relationship, never a second target."""
    rng = random.Random(7)
    plan, product = a_delete_plan(scene, rng)
    assert plan is not None
    clauses = ops._named_relation_clauses(scene, product)
    assert plan.target_guids == (product.GlobalId,)
    for entry in clauses:
        assert entry["relation"] in ("connection", "containment",
                                     "space_boundary", "opening")


# ------------------------------------- deleting an element that holds others


def a_host(scene):
    """One wall of the fixture that holds a door or a window."""
    for wall in scene.elements("wall"):
        held = [scene.by_guid(g) for g in scene.hosted_by(wall)]
        held = [h for h in held if h is not None
                and scene.family_of(h) in ("door", "window")]
        if held:
            return wall, held
    return None, []


def test_a_host_is_now_a_delete_target(scene):
    wall, held = a_host(scene)
    assert wall is not None, "the fixture has a wall that holds a filling"
    plan = ops.plan_delete(scene, wall, random.Random(2))
    assert plan is not None
    assert plan.operation == "delete"
    assert plan.target_guids == (wall.GlobalId,)


def test_the_record_names_what_goes_with_the_host(scene):
    wall, held = a_host(scene)
    plan = ops.plan_delete(scene, wall, random.Random(2))
    removed = set(plan.removed_guids)
    assert wall.GlobalId in removed
    for filling in held:
        assert filling.GlobalId in removed
        opening = ops.own_opening(filling)
        if opening is not None:
            assert opening.GlobalId in removed
    listed = {entry["guid"] for entry in plan.params["hosted_removed"]}
    assert listed == {f.GlobalId for f in held}


def test_the_host_deletion_is_one_library_call(scene):
    wall, _held = a_host(scene)
    plan = ops.plan_delete(scene, wall, random.Random(2))
    assert [c.func for c in plan.calls] == ["delete_element"]
    assert plan.calls[0].args == (wall.GlobalId,)


def test_a_filling_still_takes_its_opening_and_nothing_else(scene):
    """Lifting the refusal must not change what a filling deletion removes."""
    for door in scene.elements("door"):
        opening = ops.own_opening(door)
        if opening is None:
            continue
        plan = ops.plan_delete(scene, door, random.Random(2))
        assert set(plan.removed_guids) == {door.GlobalId, opening.GlobalId}
        assert [c.func for c in plan.calls] == ["delete_filling_with_opening"]
        return
    pytest.skip("no door in the fixture fills an opening")
