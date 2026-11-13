"""Corpus v8: a complete deletion, and the five references it adds.

Three things are asserted here.  A removal through the library takes the
element, the openings cut into it and the doors and windows those openings
hold, leaves everything it did not hold alone, and leaves no relationship
object naming nothing.  The five new lookups answer the sentence they were
written for and say what they found when they cannot.  And the emitter writes
each of them as one library call, with no number the instruction does not
carry.

Run with pytest, or as ``python -m pytest stage_a/tests/test_delete_v8.py``.
"""

from __future__ import annotations

import ifcopenshell
import ifcopenshell.api.root
import pytest

from modifc_harness import veribim_geom as geom
from stage_a.inspection import resolve_round
from stage_a.goldcode import GoldCall, emit_edit
from stage_a.observed import numbers_in_code, numbers_in_text
from stage_a.style import Style

MODEL = ("data/corpus/bs_community_repo/"
         "IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc")

#: A second fixture, for the two sentences the first model cannot answer: it
#: has an external door and a floor slab the storey's walls stand on.
HOUSE = "data/corpus/auckland/088_231110AC11-FZK-Haus-IFC.ifc"


@pytest.fixture(scope="module")
def source():
    return ifcopenshell.open(MODEL)


def fresh():
    return ifcopenshell.open(MODEL)


def hosting_wall(model):
    """The wall of the fixture that holds the most doors and windows."""
    walls = [w for w in model.by_type("IfcWall") if geom.hosted_in(w)]
    assert walls, "the fixture model has a wall holding a filling"
    return max(walls, key=lambda w: len(geom.hosted_in(w)))


# ------------------------------------------------------------- the deletion


def test_delete_element_takes_the_fillings_with_the_host(source):
    model = fresh()
    wall = hosting_wall(model)
    held = [f.GlobalId for f in geom.hosted_in(wall)]
    wall_guid = wall.GlobalId
    assert len(held) >= 2
    geom.delete_element(wall)
    for guid in held + [wall_guid]:
        with pytest.raises(RuntimeError):
            model.by_guid(guid)


def test_delete_element_leaves_a_complete_model(source):
    model = fresh()
    wall = hosting_wall(model)
    guid = wall.GlobalId
    geom.delete_element(wall)
    assert geom.deletion_is_complete(model, guid, source=source)


def test_plain_removal_is_not_complete(source):
    """The census reads the orphans the plain API call leaves behind."""
    model = fresh()
    wall = hosting_wall(model)
    guid = wall.GlobalId
    ifcopenshell.api.root.remove_product(model, product=model.by_guid(guid))
    found = geom.deletion_is_complete(model, guid, source=source, report=True)
    assert not found["ok"]
    assert found["orphan_fillings"]


def test_delete_element_keeps_what_it_did_not_hold(source):
    model = fresh()
    wall = hosting_wall(model)
    storey_guid = geom.storey_of(wall).GlobalId
    neighbours = [r.RelatedElement.GlobalId
                  for r in model.by_type("IfcRelConnectsElements")
                  if r.RelatingElement is not None
                  and r.RelatedElement is not None
                  and r.RelatingElement.GlobalId == wall.GlobalId]
    walls_before = len(model.by_type("IfcWall"))
    geom.delete_element(wall)
    assert model.by_guid(storey_guid) is not None
    for guid in neighbours:
        assert model.by_guid(guid) is not None
    assert len(model.by_type("IfcWall")) == walls_before - 1


def test_a_storey_is_never_removed():
    model = fresh()
    storey = model.by_type("IfcBuildingStorey")[0]
    with pytest.raises(ValueError):
        geom.delete_element(storey)


def test_delete_filling_routes_a_non_filling_to_delete_element(source):
    model = fresh()
    wall = hosting_wall(model)
    guid = wall.GlobalId
    geom.delete_filling(wall)
    assert geom.deletion_is_complete(model, guid, source=source)


def test_delete_filling_leaves_the_host_standing(source):
    model = fresh()
    wall = hosting_wall(model)
    filling = geom.hosted_in(wall)[0]
    guid, host_guid = filling.GlobalId, wall.GlobalId
    openings_before = len(model.by_type("IfcOpeningElement"))
    geom.delete_filling(filling)
    assert model.by_guid(host_guid) is not None
    assert len(model.by_type("IfcOpeningElement")) == openings_before - 1
    assert geom.deletion_is_complete(model, guid, source=source)


def test_a_relation_already_empty_in_the_source_is_left_alone(source):
    """The fixture carries space boundaries that name nothing; they stay."""
    already = {r.id() for r in geom._empty_relations(source)}
    assert already, "the fixture model carries an empty relationship"
    model = fresh()
    wall = hosting_wall(model)
    geom.delete_element(wall)
    kept = {r.id() for r in geom._empty_relations(model)}
    assert already <= kept


# -------------------------------------------------------------- the lookups


def test_find_host_returns_the_wall_the_filling_sits_in():
    model = fresh()
    wall = hosting_wall(model)
    filling = geom.hosted_in(wall)[0]
    assert geom.find_host(filling).GlobalId == wall.GlobalId


def test_find_host_says_so_when_the_element_fills_nothing():
    model = fresh()
    wall = hosting_wall(model)
    with pytest.raises(LookupError):
        geom.find_host(wall)


def test_find_bounding_returns_the_one_element_of_the_class():
    model = fresh()
    for space in model.by_type("IfcSpace"):
        doors = geom.bounding_elements(space, "IfcDoor")
        if len(doors) == 1:
            assert geom.find_bounding(space, "IfcDoor").GlobalId == \
                doors[0].GlobalId
            return
    pytest.skip("no room in the fixture is bounded by exactly one door")


def test_find_bounding_names_the_candidates_when_several_bound():
    model = fresh()
    for space in model.by_type("IfcSpace"):
        walls = geom.bounding_elements(space, "IfcWall")
        if len(walls) > 1:
            with pytest.raises(LookupError) as raised:
                geom.find_bounding(space, "IfcWall")
            assert walls[0].GlobalId in str(raised.value)
            return
    pytest.skip("no room in the fixture is bounded by several walls")


def test_find_filling_between_reads_the_two_rooms():
    model = fresh()
    for door in model.by_type("IfcDoor"):
        host = geom.host_wall_of(door)
        if host is None:
            continue
        rooms = geom._bounded_spaces(host)
        if len(rooms) != 2:
            continue
        try:
            found = geom.find_filling_between(rooms[0], rooms[1], "IfcDoor")
        except LookupError:
            continue
        assert found.GlobalId == door.GlobalId or \
            geom.host_wall_of(found).GlobalId == host.GlobalId
        return
    pytest.skip("no door in the fixture joins exactly two rooms")


def test_find_filling_between_takes_the_words_for_the_outside():
    model = ifcopenshell.open(HOUSE)
    for door in model.by_type("IfcDoor"):
        host = geom.host_wall_of(door)
        if host is None:
            continue
        rooms = geom._bounded_spaces(host)
        if not rooms or (len(rooms) > 1 and not geom._is_external(host)):
            continue
        try:
            found = geom.find_filling_between(rooms[0], "the outside", "IfcDoor")
        except LookupError:
            continue
        assert found.is_a("IfcDoor")
        return
    pytest.skip("no door in the fixture leads from one room to the outside")


def test_find_under_answers_with_a_slab():
    model = ifcopenshell.open(HOUSE)
    for storey in model.by_type("IfcBuildingStorey"):
        try:
            found = geom.find_under(storey, "IfcSlab")
        except LookupError:
            continue
        assert found.is_a("IfcSlab")
        return
    pytest.skip("no storey in the fixture stands on one slab")


def test_find_without_takes_a_relationship_in_plain_words():
    model = fresh()
    storey = model.by_type("IfcBuildingStorey")[0]
    try:
        found = geom.find_without(storey, "IfcWall", "connection")
    except LookupError as exc:
        assert "connection" in str(exc)
        return
    assert not [r for r in model.by_type("IfcRelConnectsElements")
                if found in (r.RelatingElement, r.RelatedElement)]


def test_find_without_refuses_a_class_and_a_relationship_together():
    model = fresh()
    storey = model.by_type("IfcBuildingStorey")[0]
    with pytest.raises(ValueError):
        geom.find_without(storey, "IfcWall", ("IfcDoor", "connection"))


# -------------------------------------------------------------- the emitter


def _lookup_code(anchor: dict) -> str:
    return resolve_round(anchor, Style.for_seed(3, geom_lib=True)).code


NEW_ANCHORS = [
    ({"kind": "host_of", "family": "wall",
      "phrase": "the wall the door named 'D' sits in",
      "params": {"element_guid": "0" * 22}, "expected": []},
     "geom.find_host("),
    ({"kind": "joins", "family": "door",
      "phrase": "the door that connects the space 'A' to the space 'B'",
      "params": {"space_a_guid": "0" * 22, "space_b_guid": "1" * 22},
      "expected": []},
     "geom.find_filling_between("),
    ({"kind": "joins", "family": "door",
      "phrase": "the door that connects the space 'A' to the outside",
      "params": {"space_a_guid": "0" * 22, "outside": True}, "expected": []},
     "'the outside'"),
    ({"kind": "bounds", "family": "window",
      "phrase": "the window that bounds the space 'A'",
      "params": {"space_guid": "0" * 22}, "expected": []},
     "geom.find_bounding("),
    ({"kind": "under", "family": "slab",
      "phrase": "the slab below the walls of storey 'Level 1'",
      "params": {"storey_guid": "0" * 22}, "expected": []},
     "geom.find_under("),
    ({"kind": "without_relation", "family": "column",
      "phrase": "the only column on storey 'Level 1' that is connected to no "
                "other element",
      "params": {"storey_guid": "0" * 22, "relation": "connection"},
      "expected": []},
     "'connection'"),
]


@pytest.mark.parametrize("anchor,wanted", NEW_ANCHORS)
def test_each_new_lookup_is_one_library_call(anchor, wanted):
    code = _lookup_code(anchor)
    assert wanted in code
    assert "for relation in" not in code
    assert "IfcRelSpaceBoundary" not in code


@pytest.mark.parametrize("anchor,_wanted", NEW_ANCHORS)
def test_no_new_lookup_writes_a_number_the_sentence_lacks(anchor, _wanted):
    code = _lookup_code(anchor)
    stated = numbers_in_text(anchor["phrase"])
    unread = [value for value in numbers_in_code(code)
              if not any(abs(value - other) < 1e-9 for other in stated)]
    assert not unread, f"{anchor['kind']} writes {unread}"


def test_a_delete_edit_is_one_library_call():
    call = GoldCall(func="delete_element", kwargs={"guid": "0" * 22})
    code = emit_edit([call], Style.for_seed(3, geom_lib=True)).code
    assert "geom.delete_element(" in code
    assert "ifcopenshell.api.root" not in code


def test_a_batch_delete_loops_through_the_library():
    calls = [GoldCall(func="delete_element", kwargs={"guid": str(i) * 22})
             for i in range(4)]
    code = emit_edit(calls, Style.for_seed(3, geom_lib=True)).code
    assert "geom.delete_element(ifc.by_guid(target_guid))" in code
    assert "ifcopenshell.api.root" not in code


def test_the_hand_written_style_is_untouched():
    call = GoldCall(func="delete_element", kwargs={"guid": "0" * 22})
    code = emit_edit([call], Style.for_seed(3, geom_lib=False)).code
    assert "ifcopenshell.api.root.remove_product(" in code
    assert "geom." not in code


def test_no_new_lookup_quotes_a_word_the_sentence_lacks():
    """Every string a round matches on has to be in the sentence itself.

    The rounds run before anything has been printed, so the instruction is the
    only place their words can come from.  This is the check the synthesizer
    applies to every task; running it here on the anchors the fixture models
    carry catches a phrase and a call that drifted apart.
    """
    from modifc_gen import anchors as anchor_lib
    from modifc_gen.scene import Scene
    from stage_a.observed import names_in_code

    builders = {"host_of": anchor_lib.host_anchors,
                "joins": anchor_lib.joins_anchors,
                "bounds": anchor_lib.bounds_anchors,
                "under": anchor_lib.under_anchors,
                "without_relation": anchor_lib.without_relation_anchors}
    families = {"host_of": ("wall",), "joins": ("door", "window"),
                "bounds": ("wall", "door", "window", "slab"),
                "under": ("slab",),
                "without_relation": ("wall", "column", "slab")}
    import random

    checked: dict = {}
    for path in (MODEL, HOUSE):
        scene = Scene(path, path, "")
        rng = random.Random(5)
        for kind, builder in builders.items():
            for family in families[kind]:
                for product in scene.elements(family):
                    for anchor in builder(scene, product, rng) or ():
                        if anchor.resolve(scene) != [product.GlobalId]:
                            continue
                        record = dict(anchor.as_record(), expected=[])
                        code = resolve_round(record,
                                             Style.for_seed(3, geom_lib=True)).code
                        for name in names_in_code(code):
                            assert name in anchor.phrase, \
                                f"{kind}: {name!r} is not in {anchor.phrase!r}"
                        checked[kind] = checked.get(kind, 0) + 1
    assert set(checked) == set(builders), f"only checked {sorted(checked)}"


def test_delete_element_on_a_hosted_filling_removes_its_opening(tmp_path):
    """delete_element(window) and delete_filling(window) leave the same model:
    the window, its opening and the emptied relations are gone (2026-09-23 fix)."""
    import ifcopenshell, shutil, pathlib
    from modifc_harness import veribim_geom as geom
    src = pathlib.Path("runs_local/stage_a_v7/gates/v500/sft_v7/edited/WIN-DEL-TOP-B26-040/227_202103162102_cira.ifc")
    if not src.exists():
        import pytest; pytest.skip("sample model missing")
    a = ifcopenshell.open(str(src)); b = ifcopenshell.open(str(src))
    wa = next(w for w in a.by_type("IfcWindow") if w.FillsVoids); guid = wa.GlobalId; wb = b.by_guid(guid)
    opening = wa.FillsVoids[0].RelatingOpeningElement.GlobalId
    geom.delete_element(wa); geom.delete_filling(wb)
    del wa, wb  # removed entities must not be touched afterwards
    for f in (a, b):
        assert not any(o.GlobalId == opening for o in f.by_type("IfcOpeningElement"))
        assert not any(w.GlobalId == guid for w in f.by_type("IfcWindow"))
    assert len(a.by_type("IfcOpeningElement")) == len(b.by_type("IfcOpeningElement"))
    assert len(a.by_type("IfcRelVoidsElement")) == len(b.by_type("IfcRelVoidsElement"))
