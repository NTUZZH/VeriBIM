"""Corpus v9 on the generator's side: how an identifier is written.

The spelling family is asserted to write every form it lists, to keep the form
the corpus already carries at 40 %, and to leave every identifier findable by
the identifier walk.  The reference rewrite is asserted to switch only names it
can tie to one of the anchor's own parameters, to write two identifiers of one
noun side by side as one list, and to leave the anchor's predicate, and so the
element it resolves to and the gold script, untouched.  The two anchors 0.9.0
adds, a room named through two of its bounding elements and a set named by its
members' identifiers, are asserted to resolve from the model alone.

Run with pytest.
"""

from __future__ import annotations

import random
from collections import Counter

import pytest

from modifc_gen import anchors as A
from modifc_gen import families, idspell, ops, script, settings, verify, wording
from modifc_gen.anchors import Anchor
from modifc_gen.scene import Scene
from stage_a.observed import guids_in_text

MODEL = "data/corpus/auckland/088_231110AC11-FZK-Haus-IFC.ifc"
DUPLEX = ("data/corpus/bs_community_repo/"
          "IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc")

G1 = "2UsXbL$3P0sOaD4Qg7rH1a"
G2 = "0okaGdY4n1xulccRQajpx9"


@pytest.fixture(scope="module")
def scene():
    return Scene(MODEL, MODEL, "")


@pytest.fixture(scope="module")
def duplex():
    return Scene(DUPLEX, DUPLEX, "")


@pytest.fixture(autouse=True)
def plain_settings():
    settings.configure(family_shares={}, family_weights={})
    yield
    settings.configure(family_shares={}, family_weights={})


# ------------------------------------------------------------ the spellings


@pytest.mark.parametrize("form", sorted(idspell.FORMS))
def test_every_form_leaves_the_identifier_findable(form):
    single = idspell.spell(form, "wall", G1)
    listed = idspell.spell_list(form, "door", [G1, G2])
    assert G1 in guids_in_text(f"Delete {single} from the model.")
    assert {G1, G2} <= guids_in_text(f"Delete {listed} from the model.")
    assert "wall" in single and "doors" in listed


def test_the_current_form_keeps_forty_percent():
    assert idspell.WEIGHTS[idspell.CURRENT_FORM] == pytest.approx(0.40)
    assert sum(idspell.WEIGHTS.values()) == pytest.approx(1.0)
    assert set(idspell.WEIGHTS) == set(idspell.FORMS)
    rng = random.Random(3)
    drawn = Counter(idspell.draw_form(rng) for _ in range(20000))
    assert abs(drawn[idspell.CURRENT_FORM] / 20000 - 0.40) < 0.015
    assert set(drawn) == set(idspell.FORMS)


def test_the_word_id_and_the_bare_form_are_written():
    assert idspell.spell("id", "column", G1) == f"the column with ID {G1}"
    assert idspell.spell("bare", "door", G1) == f"door {G1}"
    assert idspell.spell("id_colon", "wall", G1) == f"the wall (ID: {G1})"
    assert idspell.spell_list("bare", "room", [G1, G2]) == f"rooms {G1} and {G2}"


# ---------------------------------------------------------- the rewrite


def _lookup():
    table = {G1: ("column", ["C-1"]), G2: ("column", ["C-2"]),
             "1s1s1s1s1s1s1s1s1s1s1s": ("space", ["A103"]),
             "2s2s2s2s2s2s2s2s2s2s2s": ("space", ["A102"]),
             "5storey5storey5storey5": ("storey", ["Level 1"])}
    return idspell.Lookup(
        family=lambda g: table.get(g, (None, []))[0],
        labels=lambda g: table.get(g, (None, []))[1],
        resolve=lambda f, label: [g for g, (fam, names) in table.items()
                                  if fam == f and label in names])


def _choice(form="id", by_id=True, storey=True, merge=True, room=False):
    return idspell.Choice(form, by_id, storey, storey, room, merge)


def test_two_references_of_one_noun_become_one_list():
    phrase = ("the window on storey 'Level 1' that stands between the column "
              "named 'C-1' and the column named 'C-2'")
    params = {"a_guid": G1, "b_guid": G2,
              "storey_guid": "5storey5storey5storey5"}
    done = idspell.rewrite_phrase(phrase, params, _lookup(), _choice())
    assert done.phrase == ("the window on the storey with ID "
                           "5storey5storey5storey5 that stands between the "
                           f"columns with IDs {G1} and {G2}")
    assert done.merged == 1
    assert sorted(done.by_id) == ["a_guid", "b_guid", "storey_guid"]


def test_the_rooms_a_door_joins_read_as_a_person_writes_them():
    phrase = "the door that connects the space 'A103' to the space 'A102'"
    params = {"space_a_guid": "1s1s1s1s1s1s1s1s1s1s1s",
              "space_b_guid": "2s2s2s2s2s2s2s2s2s2s2s"}
    done = idspell.rewrite_phrase(phrase, params, _lookup(),
                                  _choice(form="bare", room=True))
    assert done.phrase == ("the door that connects rooms 1s1s1s1s1s1s1s1s1s1s1s"
                           " and 2s2s2s2s2s2s2s2s2s2s2s")


def test_a_name_the_table_cannot_tie_is_left_alone():
    phrase = "the window nearest to the column named 'C-9' on storey 'Level 1'"
    params = {"reference_guid": G1, "storey_guid": "5storey5storey5storey5"}
    done = idspell.rewrite_phrase(phrase, params, _lookup(), _choice())
    assert "the column named 'C-9'" in done.phrase


def test_without_the_reference_draw_only_the_spelling_changes():
    phrase = f"the door hosted in the wall with GlobalId '{G1}'"
    done = idspell.rewrite_phrase(phrase, {"host_guid": G1}, _lookup(),
                                  _choice(form="noun_id", by_id=False))
    assert done.phrase == f"the door hosted in wall ID {G1}"
    assert done.by_id == []


def test_a_storey_only_reference_uses_its_own_draw():
    phrase = "the column furthest east (+X) on storey 'Level 1'"
    params = {"storey_guid": "5storey5storey5storey5"}
    kept = idspell.rewrite_phrase(phrase, params, _lookup(),
                                  idspell.Choice("id", True, True, False,
                                                 False, True))
    assert kept.phrase == phrase
    switched = idspell.rewrite_phrase(phrase, params, _lookup(),
                                      idspell.Choice("id", False, False, True,
                                                     False, True))
    assert switched.phrase.endswith("on the storey with ID "
                                    "5storey5storey5storey5")


def test_a_relationship_clause_follows_the_sentence():
    text = "its connection to the column named 'C-2'"
    found = idspell.clause_mentions(text, _lookup())
    done = idspell.rewrite_clause(text, found, _choice(form="bare"))
    assert done.phrase == f"its connection to column {G2}"


# ------------------------------------------ the generator, end to end


def _named_anchor(scene, rng):
    """A relational anchor on the fixture that names a reference by name."""
    for family in ("window", "door", "wall", "slab"):
        for product in scene.elements(family):
            for builder in (A.nearest_anchors, A.between_anchors):
                for anchor in builder(scene, product, rng) or ():
                    if anchor.resolve(scene) == [product.GlobalId]:
                        return anchor, product
    return None, None


def test_the_generator_names_references_by_identifier(scene):
    rng = random.Random(7)
    anchor, product = _named_anchor(scene, rng)
    assert anchor is not None, "the fixture carries no relational reference"
    plan = ops.plan_delete(scene, product, random.Random(1))
    assert plan is not None
    plan.params.pop("named_relations", None)
    settings.configure(family_shares={"wording.reference_by_id": 1.0,
                                      "wording.class_token": 0.0,
                                      "wording.synonym": 0.0,
                                      "wording.request_form": 0.0},
                       family_weights={})
    sentence = f"Delete {anchor.phrase} from the model."
    seen_named = 0
    for seed in range(12):
        text, chosen = wording.apply(sentence, scene, plan, anchor,
                                     random.Random(seed))
        record = chosen.as_record()
        assert record["anchor_phrase"] in text
        refs = record["identifiers"]["references_by_id"]
        assert refs, text
        for key in refs:
            assert anchor.params[key] in guids_in_text(text), (key, text)
        assert " named '" not in record["anchor_phrase"], text
        seen_named += 1
        kept = verify.check_wording(scene, text, anchor, record,
                                    [product.GlobalId])
        assert kept.ok, kept.reason
    assert seen_named == 12


def test_the_gold_script_does_not_depend_on_the_spelling(scene):
    rng = random.Random(7)
    anchor, product = _named_anchor(scene, rng)
    plan = ops.plan_delete(scene, product, random.Random(1))
    bodies = set()
    for share in (0.0, 1.0):
        settings.configure(family_shares={"wording.reference_by_id": share},
                           family_weights={})
        text, _chosen = wording.apply(f"Delete {anchor.phrase}.", scene, plan,
                                      anchor, random.Random(2))
        source = script.render_script("T-1", text, plan)
        bodies.add(source.split('"""', 2)[2])
    assert len(bodies) == 1


def test_a_room_named_through_two_walls_resolves_to_it(duplex):
    checked = 0
    for space in duplex.elements("space"):
        anchor = A.space_of_pair_anchor(duplex, space)
        if anchor is None:
            continue
        assert anchor.params["element_b_guid"] != anchor.params["element_guid"]
        assert anchor.resolve(duplex) == [space.GlobalId]
        assert " and the " in anchor.phrase
        checked += 1
    assert checked >= 3, "the fixture carries too few rooms with two named walls"


def test_a_set_named_by_identifiers_covers_exactly_them(scene):
    rng = random.Random(5)
    found = A.id_list_anchors(scene, "wall", rng)
    assert found
    for anchor in found:
        members = anchor.params["member_guids"]
        assert 2 <= len(members) <= 4
        assert anchor.resolve(scene) == sorted(members)
        assert set(members) <= guids_in_text(f"Delete {anchor.phrase}.")


def test_the_new_families_are_registered():
    for tag in ("wording.identifier_spelling", "wording.reference_by_id",
                "wording.identifier_list", "scope.id_list"):
        assert tag in families.BY_TAG
        assert families.layer_of(tag) in ("wording", "scope")
    assert families.share("wording.reference_by_id") == pytest.approx(0.40)


def test_a_clause_names_its_storey_the_way_the_anchor_does(scene):
    """A sentence that gives its storey by identifier gives it so throughout."""
    checked = 0
    for product in scene.elements("column") + scene.elements("wall"):
        anchor = A.in_storey_anchor(scene, product)
        if anchor is None or anchor.resolve(scene) != [product.GlobalId]:
            continue
        plan = ops.plan_delete(scene, product, random.Random(1))
        clauses = ops._named_relation_clauses(scene, product)
        if plan is None or not any(c["relation"] == "containment"
                                   for c in clauses):
            continue
        plan.params.pop("constraint", None)
        plan.params["named_relations"] = [dict(c) for c in clauses[:2]]
        plan.params["named_relations_form"] = 1
        label = scene.storey_label(scene.storey_of(product))
        for seed in range(40):
            for entry, original in zip(plan.params["named_relations"],
                                       clauses[:2]):
                entry["text"] = original["text"]
            sentence = templates_sentence(plan, anchor)
            text, chosen = wording.apply(sentence, scene, plan, anchor,
                                         random.Random(seed))
            record = chosen.as_record().get("identifiers") or {}
            if "storey_guid" not in record.get("references_by_id", ()):
                continue
            assert label not in text, text
            checked += 1
        if checked:
            break
    assert checked, "no draw on the fixture switched a storey"


def templates_sentence(plan, anchor):
    from modifc_gen import templates
    return templates._delete_sentence(plan, anchor.phrase)


def test_a_delete_that_leaves_the_element_out_names_no_relationship(scene):
    """The host wall, the rooms and the storey a delete names would identify
    the element, so the sentence that asks "which one?" does not carry them."""
    from modifc_gen import templates
    for product in scene.elements("window") + scene.elements("door"):
        clauses = ops._named_relation_clauses(scene, product)
        if len(clauses) < 2:
            continue
        plan = ops.plan_delete(scene, product, random.Random(1))
        plan.params["named_relations"] = clauses[:2]
        plan.params["named_relations_form"] = 2
        anchor = A.guid_anchor(scene, product)
        text = templates.underspecified(scene, plan, anchor, "direct", "element")
        assert text is not None
        for clause in clauses[:2]:
            assert clause["text"] not in text
        assert plan.params["named_relations"] == clauses[:2]
        return
    pytest.skip("no door or window of the fixture takes part in two relationships")
