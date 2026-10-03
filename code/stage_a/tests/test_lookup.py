"""The lookup round: the instruction's phrase resolved through the library.

A phrase that places an element relative to another one used to be written out
as the generator's own predicate, tolerances and all, so the round asserted
numbers the reader of the instruction never had. Under the library style the
round makes one call into ``geom`` carrying the elements the sentence names,
the class, the storey, a direction word and the distance the sentence states.
Four claims carry the weight. The round holds the right call for its kind. It
writes no number the instruction does not carry. It defines no predicate of its
own. And turning the style off leaves the old body exactly as it was, so the
two are comparable arms of one experiment.

    python -m stage_a.tests.test_lookup
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from stage_a import paths
from stage_a.inspection import Ref, resolve_round
from stage_a.goldcode import GoldCall, emit_edit, parse_gold_script
from stage_a.observed import (names_in_code, names_observed_ok, number_observed,
                              numbers_in_code, numbers_in_text,
                              standard_property_names)
from stage_a.style import Style

VAL = paths.PROJECT_ROOT / "runs_local/stage_a_v2/val_tasks_500_v2.jsonl"
POOL = paths.PROJECT_ROOT / "runs_local/stage_a_v2/tasks_selected.jsonl"

GEOM = Style.for_seed(20260919, geom_lib=True)
PLAIN = Style.for_seed(20260919)

#: Anchor kinds the library now resolves, and the call each one has to make.
CALLS = {
    "offset": "geom.find_offset(",
    "extreme": "geom.find_extreme(",
    "nearest": "geom.find_nearest(",
    "between": "geom.find_between(",
    "ordinal": "geom.find_ordinal(",
    "opposite": "geom.find_opposite(",
    "egocentric": "geom.find_beside_door(",
    "above_below": "geom.find_above_below(",
}

#: Numbers the old bodies asserted and the instruction never states.
TOLERANCE_KEYS = ("tolerance", "lateral_tolerance", "margin", "inset",
                  "min_offset", "min_gap")

PASSED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{name} failed. {detail}")
    PASSED += 1
    print(f"ok  {name}")


def load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def refs_for(record: dict) -> dict:
    """The parameters the instruction gives by name, as the planner gives them.

    The test does not repeat the planner's name index; it binds every element
    the phrase names to a plain lookup by the class the anchor's family means,
    which is all the round's shape depends on.
    """
    family_class = {"wall": "IfcWall", "slab": "IfcSlab", "space": "IfcSpace",
                    "door": "IfcDoor", "window": "IfcWindow",
                    "column": "IfcColumn"}
    anchor = record["anchor"]
    out = {}
    for key in ("storey_guid",):
        if key in (anchor.get("params") or {}):
            out[key] = Ref("IfcBuildingStorey", "a storey")
    for key in ("reference_guid", "a_guid", "b_guid", "host_guid",
                "space_guid", "door_guid", "other_guid", "element_guid"):
        if key in (anchor.get("params") or {}):
            out[key] = Ref(family_class[anchor["family"]], "a neighbour")
    if "scope_guid" in (anchor.get("params") or {}):
        scope = (anchor["params"] or {}).get("scope")
        out["scope_guid"] = Ref({"storey": "IfcBuildingStorey",
                                 "host": "IfcWall",
                                 "space": "IfcSpace"}[scope], "a scope")
    return out


def one_per_kind(records: list[dict]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for record in records:
        kind = (record.get("anchor") or {}).get("kind")
        if kind in CALLS and kind not in found:
            found[kind] = record
    return found


# ------------------------------------------------------------------- tests


def test_each_kind_makes_its_call(examples: dict) -> None:
    print("\n== test_each_kind_makes_its_call")
    for kind, record in sorted(examples.items()):
        code = resolve_round(record["anchor"], GEOM, refs_for(record)).code
        check(f"{kind} is resolved with {CALLS[kind]}...)",
              CALLS[kind] in code, code)
        check(f"{kind} defines no predicate of its own",
              not any(isinstance(node, (ast.FunctionDef, ast.Lambda))
                      for node in ast.walk(ast.parse(code))
                      if getattr(node, "name", "") not in
                      ("by_name", "by_name_on_storey", "contained_elements",
                       "on_storey")), code)


def test_no_tolerance_reaches_the_round(examples: dict) -> None:
    print("\n== test_no_tolerance_reaches_the_round")
    for kind, record in sorted(examples.items()):
        params = record["anchor"].get("params") or {}
        code = resolve_round(record["anchor"], GEOM, refs_for(record)).code
        hidden = [float(params[key]) for key in TOLERANCE_KEYS if key in params]
        written = numbers_in_code(code)
        left = [value for value in hidden
                if any(abs(value - seen) < 1e-6 for seen in written)]
        check(f"{kind} writes none of its {len(hidden)} hidden tolerances",
              not left, f"{left} still in\n{code}")


def test_every_number_is_in_the_instruction(records: list[dict]) -> None:
    print("\n== test_every_number_is_in_the_instruction")
    checked = 0
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") not in CALLS:
            continue
        # A task whose sentence never carries the phrase gets no lookup round
        # at all: the generator drew the anchor but wrote a plain instruction,
        # and the planner refuses such a task. It is not one of the rounds this
        # walk is about.
        if not (record.get("wording") or {}).get("anchor_phrase"):
            continue
        code = resolve_round(anchor, GEOM, refs_for(record)).code
        known = numbers_in_text(record["instruction"])
        unread = [value for value in numbers_in_code(code)
                  if not number_observed(value, known)]
        if unread:
            raise AssertionError(
                f"{record['task_id']} writes {unread}, which its instruction "
                f"does not carry:\n{record['instruction']}\n{code}")
        checked += 1
    check(f"none of the {checked} library lookups of the validation split "
          "writes a number the instruction lacks", checked > 0)


#: Kinds whose hand-written body was retired: the plain style makes the
#: library call for them too, because the body it wrote read the phrase
#: differently from the library ("opposite").
RETIRED_BODIES = ("opposite",)


def test_the_old_body_is_unchanged(examples: dict) -> None:
    print("\n== test_the_old_body_is_unchanged")
    for kind, record in sorted(examples.items()):
        code = resolve_round(record["anchor"], PLAIN, refs_for(record)).code
        if kind in RETIRED_BODIES:
            params = record["anchor"].get("params") or {}
            hidden = [float(params[key]) for key in TOLERANCE_KEYS if key in params]
            written = numbers_in_code(code)
            check(f"{kind} without the style makes the library call too",
                  CALLS[kind] in code, code)
            check(f"{kind} without the style writes none of its hidden tolerances",
                  not [v for v in hidden if any(abs(v - w) < 1e-6 for w in written)], code)
            continue
        check(f"{kind} without the style writes the predicate out",
              CALLS[kind] not in code and "matches" in code or "hits" in code
              or "found" in code, code[:200])
        params = record["anchor"].get("params") or {}
        hidden = [float(params[key]) for key in TOLERANCE_KEYS if key in params]
        written = numbers_in_code(code)
        kept = [v for v in hidden if any(abs(v - w) < 1e-6 for w in written)]
        # ``ordinal`` is the one kind whose old body never wrote its own
        # tolerance: the generator uses ``min_gap`` to reject a row it cannot
        # count, and the round only sorts.
        if hidden and kind != "ordinal":
            check(f"{kind} without the style still carries its tolerance",
                  bool(kept), f"{hidden} not in {written}")


def test_the_offset_call_states_what_the_sentence_states(examples: dict) -> None:
    print("\n== test_the_offset_call_states_what_the_sentence_states")
    record = examples.get("offset")
    if record is None:
        return
    code = resolve_round(record["anchor"], GEOM, refs_for(record)).code
    phrase = record["anchor"]["phrase"]
    number = phrase.split("about ")[1].split(" m")[0]
    check("the distance the call carries is the one the phrase writes",
          number in code, f"{phrase}\n{code}")
    for word in ("east", "west", "north", "south"):
        if f" {word} (" in phrase:
            check("the direction the call carries is the phrase's own word",
                  f'"{word}"' in code or f"'{word}'" in code, code)
            break


def test_the_ordinal_counts_from_the_named_side(examples: dict) -> None:
    print("\n== test_the_ordinal_counts_from_the_named_side")
    record = examples.get("ordinal")
    if record is None:
        return
    phrase = record["anchor"]["phrase"]
    code = resolve_round(record["anchor"], GEOM, refs_for(record)).code
    side = phrase.split("from the ")[1].split(" ")[0]
    check("the side the call counts from is the one the phrase names",
          f'"{side}"' in code or f"'{side}'" in code, f"{phrase}\n{code}")
    place = int(record["anchor"]["params"]["index"]) + 1
    check("and the place it takes counts from one, as the sentence does",
          f", {place})" in code, code)


def test_the_set_measures_through_the_library(records: list[dict]) -> None:
    print("\n== test_the_set_measures_through_the_library")
    found = 0
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") != "set" or not (anchor.get("params") or {}).get("condition"):
            continue
        code = resolve_round(anchor, GEOM, refs_for(record)).code
        check(f"{record['task_id']} measures with geom.measure",
              "geom.measure(" in code, code)
        check("and brings no body-reading helper of its own",
              "def world_box(" not in code and "def body_centre(" not in code,
              code)
        found += 1
        if found >= 3:
            break
    check("at least one conditional set was checked", found > 0)


def test_a_counted_place_is_a_stated_number() -> None:
    print("\n== test_a_counted_place_is_a_stated_number")
    sentence = "Remove the fifth window from the east along the wall named 'W'."
    known = numbers_in_text(sentence)
    check("a place written as a word counts as a number the sentence states",
          number_observed(5.0, known), sorted(known))
    check("and a place the sentence does not name does not",
          not number_observed(7.0, known), sorted(known))
    check("a figure is still read as a figure",
          number_observed(2.1, numbers_in_text("2.1 m high")), "")


def test_a_move_states_only_the_distance(records: list[dict]) -> None:
    print("\n== test_a_move_states_only_the_distance")
    checked = 0
    for record in records:
        if record["edit_kind"] != "rehost_filling":
            continue
        calls = parse_gold_script(record["gold_script"])
        code = emit_edit(calls, GEOM, record.get("edit_params"),
                         record["instruction"]).code
        if checked == 0:
            check("a move is one geom.move_filling call",
                  "geom.move_filling(" in code, code)
            check("and it writes none of the placement the benchmark computed",
                  "rehost_into_wall(" not in code and "def replant_in_wall" not in code,
                  code)
            stated = record["edit_params"]["along"]
            check("and the distance it carries is the one the sentence states",
                  repr(float(stated)) in code, f"{stated}\n{code}")
        known = numbers_in_text(record["instruction"])
        unread = [v for v in numbers_in_code(code) if not number_observed(v, known)]
        if unread:
            raise AssertionError(
                f"{record['task_id']} writes {unread}:\n"
                f"{record['instruction']}\n{code}")
        checked += 1
    check(f"none of the {checked} moves writes a number the sentence lacks",
          checked > 0)


def test_a_turn_states_the_angle_and_names_the_point(records: list[dict]) -> None:
    print("\n== test_a_turn_states_the_angle_and_names_the_point")
    seen = set()
    checked = 0
    for record in records:
        if record["edit_kind"] != "rotate":
            continue
        calls = parse_gold_script(record["gold_script"])
        code = emit_edit(calls, GEOM, record.get("edit_params"),
                         record["instruction"]).code
        pivot = record["edit_params"]["pivot"]
        if pivot not in seen:
            seen.add(pivot)
            check(f"a turn about the {pivot} is one geom.turn_element call",
                  "geom.turn_element(" in code, code)
            word = {"origin": "own", "centre": "centre"}[pivot]
            check(f"and it names that point {word!r} rather than a coordinate",
                  f'"{word}"' in code or f"'{word}'" in code, code)
        known = numbers_in_text(record["instruction"])
        unread = [v for v in numbers_in_code(code) if not number_observed(v, known)]
        if unread:
            raise AssertionError(
                f"{record['task_id']} writes {unread}:\n"
                f"{record['instruction']}\n{code}")
        checked += 1
    check(f"none of the {checked} turns writes a number the sentence lacks",
          checked > 0)
    check("both pivot wordings were covered", seen == {"origin", "centre"}, seen)


#: What each negation wording says, as arguments to the library.
ABSENCE = {
    "wall_without_filling": ("IfcWall", "('IfcDoor', 'IfcWindow')"),
    "bounding_wall_without_filling": ("IfcWall", "'IfcDoor'"),
    "space_without_boundary": ("IfcSpace", "'IfcWindow'"),
}


def test_absence_is_one_call(records: list[dict]) -> None:
    print("\n== test_absence_is_one_call")
    seen: set = set()
    checked = 0
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") != "negation":
            continue
        if not (record.get("wording") or {}).get("anchor_phrase"):
            continue
        variant = anchor["params"]["variant"]
        code = resolve_round(anchor, GEOM, refs_for(record)).code
        if variant not in seen:
            seen.add(variant)
            check(f"{variant} is resolved with geom.find_without(...)",
                  "geom.find_without(" in code, code)
            check(f"{variant} brings no relationship index of its own",
                  "def relation_index(" not in code
                  and "SPACE_ELEMENTS" not in code and "HOSTED" not in code,
                  code)
            wanted = ABSENCE[variant][0]
            check(f"{variant} asks for a {wanted}",
                  f'"{wanted}"' in code or f"'{wanted}'" in code, code)
        known = numbers_in_text(record["instruction"])
        unread = [v for v in numbers_in_code(code) if not number_observed(v, known)]
        if unread:
            raise AssertionError(f"{record['task_id']} writes {unread}:\n{code}")
        checked += 1
    check(f"none of the {checked} absence lookups writes a number the "
          "sentence lacks", checked > 0)
    check("all three wordings were covered", len(seen) == 3, sorted(seen))


def test_the_old_absence_body_is_unchanged(records: list[dict]) -> None:
    print("\n== test_the_old_absence_body_is_unchanged")
    seen: set = set()
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") != "negation":
            continue
        variant = anchor["params"]["variant"]
        if variant in seen:
            continue
        seen.add(variant)
        code = resolve_round(anchor, PLAIN, refs_for(record)).code
        check(f"{variant} without the style still walks the relationships",
              "geom.find_without(" not in code
              and ("HOSTED" in code or "SPACE_ELEMENTS" in code), code[:200])


#: Which library call each scope of a set phrase reads its candidates with.
SCOPES = {"storey": "geom.on_storey(", "host": "geom.hosted_in(",
          "space": "geom.bounding_elements("}


def test_a_set_is_one_call(records: list[dict]) -> None:
    print("\n== test_a_set_is_one_call")
    seen: set = set()
    checked = 0
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") != "set":
            continue
        params = anchor["params"]
        shape = (params["scope"], bool(params.get("condition")))
        code = resolve_round(anchor, GEOM, refs_for(record)).code
        if shape not in seen:
            seen.add(shape)
            where = "a condition" if shape[1] else "no condition"
            check(f"a {shape[0]} set with {where} reads its candidates with "
                  f"{SCOPES[shape[0]]}...)",
                  SCOPES[shape[0]] in code, code)
            check(f"a {shape[0]} set with {where} brings no relationship "
                  "index of its own",
                  "def relation_index(" not in code and "HOSTED" not in code
                  and "SPACE_ELEMENTS" not in code
                  and "def world_box(" not in code, code)
            if shape[1]:
                check("and the condition is measured with geom.measure",
                      "geom.measure(" in code, code)
                stated = float(params["condition"]["threshold"])
                check("and the threshold it carries is the sentence's own",
                      number_observed(stated,
                                      numbers_in_text(record["instruction"])),
                      f"{stated}\n{record['instruction']}")
        known = numbers_in_text(record["instruction"])
        unread = [v for v in numbers_in_code(code) if not number_observed(v, known)]
        if unread:
            raise AssertionError(f"{record['task_id']} writes {unread}:\n{code}")
        checked += 1
    check(f"none of the {checked} set lookups writes a number the sentence "
          "lacks", checked > 0)
    check("all six scope and condition shapes were covered",
          len(seen) == 6, sorted(seen))


def test_the_old_set_body_is_unchanged(records: list[dict]) -> None:
    print("\n== test_the_old_set_body_is_unchanged")
    seen: set = set()
    for record in records:
        anchor = record.get("anchor") or {}
        if anchor.get("kind") != "set":
            continue
        scope = anchor["params"]["scope"]
        if scope in seen:
            continue
        seen.add(scope)
        code = resolve_round(anchor, PLAIN, refs_for(record)).code
        check(f"a {scope} set without the style still walks the model by hand",
              SCOPES[scope] not in code and "geom.measure(" not in code, code[:200])
    check("all three scopes were covered", len(seen) == 3, sorted(seen))


def test_a_material_is_one_call(records: list[dict]) -> None:
    print("\n== test_a_material_is_one_call")
    checked = 0
    for record in records:
        if record["edit_kind"] != "assign_material":
            continue
        calls = parse_gold_script(record["gold_script"])
        code = emit_edit(calls, GEOM, record.get("edit_params"),
                         record["instruction"]).code
        if checked == 0:
            check("a material assignment is one geom.assign_material call",
                  "geom.assign_material(" in code, code)
            check("and it builds no association entity of its own",
                  "IfcRelAssociatesMaterial" not in code
                  and "IfcMaterial" not in code, code)
            check("and it defines no helper of its own",
                  not any(isinstance(node, ast.FunctionDef)
                          for node in ast.walk(ast.parse(code))), code)
            name = record["edit_params"]["material"] \
                if "material" in (record["edit_params"] or {}) else None
            if name:
                check("and the name it carries is the sentence's own",
                      name in code, f"{name}\n{code}")
        unread = [n for n in names_in_code(code)
                  if n not in record["instruction"]]
        if unread:
            raise AssertionError(f"{record['task_id']} quotes {unread}")
        checked += 1
    check(f"none of the {checked} material assignments quotes a name the "
          "sentence lacks", checked > 0)


def test_a_type_is_one_call(records: list[dict]) -> None:
    print("\n== test_a_type_is_one_call")
    checked = 0
    for record in records:
        if record["edit_kind"] != "assign_type":
            continue
        calls = parse_gold_script(record["gold_script"])
        code = emit_edit(calls, GEOM, record.get("edit_params"),
                         record["instruction"]).code
        if checked == 0:
            check("a type assignment is one geom.assign_type call",
                  "geom.assign_type(" in code, code)
            check("and it builds no type relationship of its own",
                  "IfcRelDefinesByType" not in code, code)
            check("and the type object is one an earlier round found",
                  "ifc.by_guid(" in code, code)
            plain = emit_edit(calls, PLAIN, record.get("edit_params"),
                              record["instruction"]).code
            check("with the style off the type is still assigned by hand",
                  "attach_type(" in plain and "IfcRelDefinesByType" in plain,
                  plain[:200])
        checked += 1
    check(f"{checked} type assignments were written as one call", checked > 0)


def test_a_rename_is_left_alone(records: list[dict]) -> None:
    print("\n== test_a_rename_is_left_alone")
    for record in records:
        if record["edit_kind"] != "rename":
            continue
        code = emit_edit(parse_gold_script(record["gold_script"]), GEOM,
                         record.get("edit_params"), record["instruction"]).code
        body = [line for line in code.strip().splitlines()
                if line.strip() and not line.strip().startswith("#")]
        check("a rename is still one line of plain ifcopenshell",
              len(body) == 1 and ".Name = " in body[0], code)
        check("and no library call is made for it",
              "geom." not in code, code)
        return


def test_an_unknown_helper_name_gets_a_menu() -> None:
    print("\n== test_an_unknown_helper_name_gets_a_menu")
    import importlib

    geom = importlib.import_module("modifc_harness.veribim_geom")
    invented = ("wall_corner_world_coordinates", "move_into_storey",
                "find_below", "find_beside_space", "remove_from_storey")
    for name in invented:
        try:
            getattr(geom, name)
        except AttributeError as error:
            message = str(error)
        else:
            raise AssertionError(f"geom.{name} exists")
        check(f"{name} is refused with the list of what geom has",
              "find_offset" in message and "Available:" in message, message)
        check(f"and the message stays short for {name}",
              len(message) <= 600, len(message))
    try:
        getattr(geom, "move_into_storey")
    except AttributeError as error:
        check("a caller reaching for a move is shown move_filling",
              "move_filling" in str(error), str(error))
    for private in ("_secret", "__wrapped__", "__deepcopy__"):
        try:
            getattr(geom, private)
        except AttributeError as error:
            check(f"{private} raises the plain error, so introspection behaves",
                  "Available:" not in str(error), str(error))
        else:
            raise AssertionError(f"geom.{private} exists")
    check("every name the menu lists is really there",
          all(hasattr(geom, name) for name in geom.__all__), "")


def test_a_standard_property_name_is_knowable() -> None:
    print("\n== test_a_standard_property_name_is_knowable")
    standard = standard_property_names()
    check("the schema's own property names are read from its templates",
          len(standard) > 1000, len(standard))
    for name in ("LoadBearing", "FireRating", "IsExternal", "ThermalTransmittance"):
        check(f"{name} is one of them", name in standard)
    check("a name the generator chose is not",
          "Wand-008" not in standard and "Doorset 845" not in standard)
    rounds = [{"role": "assistant", "tool_calls": [{"function": {"arguments": json.dumps(
        {"code": "geom.set_property(ifc.by_guid('x'), 'Pset_ColumnCommon',"
                 " 'LoadBearing', False)"})}}]}]
    check("so a property write is not reported as quoting an unknown name",
          not names_observed_ok(rounds, "Update the load-bearing flag in "
                                        "Pset_ColumnCommon to false."), "")
    invented = [{"role": "assistant", "tool_calls": [{"function": {"arguments": json.dumps(
        {"code": "geom.set_property(ifc.by_guid('x'), 'Pset_ColumnCommon',"
                 " 'Wand-008', False)"})}}]}]
    check("while a name outside the schema still is",
          bool(names_observed_ok(invented, "Update something.")), "")


def test_the_property_write_is_one_call() -> None:
    print("\n== test_the_property_write_is_one_call")
    call = GoldCall("set_property_value",
                    {"guid": "2Gnb_Q_UrFd9l_whPeGH96",
                     "pset_name": "Pset_ColumnCommon",
                     "property_name": "FireRating", "value": "F60",
                     "value_type": "IfcLabel", "pset_guid": "a",
                     "relation_guid": "b"})
    code = emit_edit([call], GEOM).code
    check("a property write is one geom.set_property call",
          "geom.set_property(" in code, code)
    check("and the value type the instruction does not state is not written",
          "IfcLabel" not in code, code)
    check("and no property-set entity is built by hand",
          "IfcPropertySet" not in code and "IfcRelDefinesByProperties" not in code,
          code)
    check("and the round defines no helper of its own",
          not any(isinstance(node, ast.FunctionDef)
                  for node in ast.walk(ast.parse(code))), code)
    plain = emit_edit([call], PLAIN).code
    check("with the style off the property write is still done by hand",
          "write_pset_value(" in plain and "IfcPropertySet" in plain, plain[:200])


def test_the_filling_delete_removes_the_opening() -> None:
    print("\n== test_the_filling_delete_removes_the_opening")
    call = GoldCall("delete_filling_with_opening", {"guid": "1lBsEOVyuXokZvCKRLU6$V"})
    code = emit_edit([call], GEOM).code
    check("a filling delete is one geom.delete_filling call",
          "geom.delete_filling(" in code, code)
    check("and it writes no voids or fills relationship of its own",
          "IfcRelVoidsElement" not in code and "IfcRelFillsElement" not in code,
          code)


def main() -> int:
    val = load(VAL)
    pool = load(POOL)
    examples = one_per_kind(val)
    missing = sorted(set(CALLS) - set(examples))
    for kind in missing:
        for record in pool:
            if (record.get("anchor") or {}).get("kind") == kind:
                examples[kind] = record
                break
    test_each_kind_makes_its_call(examples)
    test_no_tolerance_reaches_the_round(examples)
    test_every_number_is_in_the_instruction(val)
    test_the_old_body_is_unchanged(examples)
    test_the_offset_call_states_what_the_sentence_states(examples)
    test_the_ordinal_counts_from_the_named_side(examples)
    test_the_set_measures_through_the_library(val + pool)
    test_a_counted_place_is_a_stated_number()
    test_a_move_states_only_the_distance(pool)
    test_a_turn_states_the_angle_and_names_the_point(pool)
    test_absence_is_one_call(val + pool)
    test_the_old_absence_body_is_unchanged(val + pool)
    test_a_set_is_one_call(val + pool)
    test_the_old_set_body_is_unchanged(val + pool)
    test_a_material_is_one_call(pool)
    test_a_type_is_one_call(pool)
    test_a_rename_is_left_alone(pool)
    test_an_unknown_helper_name_gets_a_menu()
    test_a_standard_property_name_is_knowable()
    test_the_property_write_is_one_call()
    test_the_filling_delete_removes_the_opening()
    print(f"\nall checks passed ({PASSED})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
