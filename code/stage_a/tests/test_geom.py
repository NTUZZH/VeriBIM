"""The library style: a create edit written as calls into the sandbox's ``geom``.

The sandbox binds a geometry helper under the name ``geom``. A create-type gold
call is emitted as one call into it carrying only what the instruction states,
and the helper cuts the opening, places the element, converts the frame and
writes the relationships. Four claims carry the weight here. The emitted edit
holds a ``geom`` call and none of the entity literals the helper builds inside.
The arguments are the instruction's own numbers, which is what
``along_is_centre`` and the storey-or-world frame turn on. A create edit whose
position is described against another element gets a round that measures that
element before the edit uses it. And turning the style off leaves the
hand-written emitter byte for byte as it was, since the two styles have to be
comparable arms of the same experiment.

    python -m stage_a.tests.test_geom
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from stage_a import paths
from stage_a.goldcode import (GoldCall, emit_edit, parse_gold_script,
                              referenced_guids)
from stage_a.style import Style
from stage_a.observed import (number_observed, numbers_in_code,
                              numbers_in_text)
from stage_a.synthesize import _measure_rounds, _units_round, plan

PILOT = paths.PROJECT_ROOT / "runs_local/gen_v07/pilot/tasks.jsonl"

#: Entities the helper builds inside. None of them may appear in an edit the
#: library style wrote, which is the whole point of the style.
BY_HAND = ("IfcRectangleProfileDef", "IfcExtrudedAreaSolid", "IfcLocalPlacement",
           "IfcRelVoidsElement", "IfcRelFillsElement", "IfcAxis2Placement3D",
           "IfcRelContainedInSpatialStructure", "IfcRelSpaceBoundary",
           "IfcRelConnectsElements", "IfcRelAggregates")

GEOM = Style.for_seed(20260919, geom_lib=True)
PLAIN = Style.for_seed(20260919)

PASSED = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if not condition:
        raise AssertionError(f"{name} failed. {detail}")
    PASSED += 1
    print(f"ok  {name}")


def load_pilot() -> list[dict]:
    if not PILOT.exists():
        return []
    return [json.loads(line) for line in PILOT.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def kinds_of(record: dict) -> set[str]:
    """What the task is, for picking one example of each shape."""
    params = record.get("edit_params") or {}
    out = {record.get("edit_kind", "")}
    placement = (params.get("placement") or {}).get("kind")
    if placement:
        out.add(placement)
    if params.get("offset"):
        out.add("offset")
    for call in parse_gold_script(record["gold_script"]):
        out.add(call.func)
    return out


def one_per_kind(records: list[dict], wanted: tuple[str, ...]) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for record in records:
        if record["operation"] != "create":
            continue
        for kind in kinds_of(record) & set(wanted):
            found.setdefault(kind, record)
    return found


# ------------------------------------------------------------------ emitters

def test_emitters() -> None:
    """Every create call becomes a ``geom`` call and no entity literal."""
    print("\n== test_emitters")
    calls = {
        "add_filling": GoldCall("add_filling", {
            "ifc_class": "IfcDoor", "guid": "aaaaaaaaaaaaaaaaaaaaaa",
            "name": "Doorset 1", "host_guid": "hhhhhhhhhhhhhhhhhhhhh1",
            "along": 2.3, "across": -0.14, "sill": 0.0, "width": 0.9,
            "height": 2.1, "thickness": 0.27, "predefined_type": "DOOR"}),
        "replace_filling": GoldCall("replace_filling", {
            "guid": "oooooooooooooooooooo11", "ifc_class": "IfcDoor",
            "new_guid": "nnnnnnnnnnnnnnnnnnnn11", "name": "Doorset 2",
            "host_guid": "hhhhhhhhhhhhhhhhhhhhh2", "along": 13.76,
            "across": -0.1, "sill": 0.0, "width": 0.9, "height": 2.1,
            "thickness": 0.2, "predefined_type": None}),
        "add_box_element": GoldCall("add_box_element", {
            "ifc_class": "IfcWall", "guid": "bbbbbbbbbbbbbbbbbbbb11",
            "name": "Partition 1", "storey_guid": "ssssssssssssssssssss11",
            "x": 1.0, "y": 2.0, "z": 0.0, "length": 4.0, "width": 0.2,
            "height": 2.3, "predefined_type": None, "long_name": None}),
        "add_box_element_world": GoldCall("add_box_element_world", {
            "ifc_class": "IfcSlab", "guid": "bbbbbbbbbbbbbbbbbbbb22",
            "name": "Deck 1", "storey_guid": "ssssssssssssssssssss11",
            "x": 1.0, "y": 2.0, "z": 3.0, "length": 4.0, "width": 4.0,
            "height": 0.2, "predefined_type": "ROOF", "long_name": None}),
        "add_box_element_world_turned": GoldCall("add_box_element_world_turned", {
            "ifc_class": "IfcColumn", "guid": "bbbbbbbbbbbbbbbbbbbb33",
            "name": "Post 1", "storey_guid": "ssssssssssssssssssss11",
            "x": 1.0, "y": 2.0, "z": 0.0, "length": 0.4, "width": 0.4,
            "height": 2.3, "predefined_type": None, "long_name": None}),
        "add_wall_span": GoldCall("add_wall_span", {
            "guid": "bbbbbbbbbbbbbbbbbbbb44", "name": "Partition 2",
            "storey_guid": "ssssssssssssssssssss11", "x1": 0.0, "y1": 0.0,
            "x2": 5.0, "y2": 0.0, "z1": 0.0, "height": 3.0, "thickness": 0.2,
            "thickness_direction": "+y", "predefined_type": None}),
        "copy_element": GoldCall("copy_element", {
            "guid": "cccccccccccccccccccc11", "new_guid": "dddddddddddddddddddd11",
            "dx": 0.6, "dy": 0.0, "dz": 0.0, "name": "Post 2"}),
        "array_elements": GoldCall("array_elements", {
            "guid": "cccccccccccccccccccc22",
            "new_guids": ["dddddddddddddddddddd22", "dddddddddddddddddddd33"],
            "dx": 0.0, "dy": -0.75, "dz": 0.0, "names": ["Post 3", "Post 4"]}),
        "add_space_boundary": GoldCall("add_space_boundary", {
            "guid": "eeeeeeeeeeeeeeeeeeee11", "space_guid": "pppppppppppppppppppp11",
            "element_guid": "qqqqqqqqqqqqqqqqqqqq11",
            "physical_or_virtual": "PHYSICAL", "internal_or_external": "INTERNAL",
            "name": None}),
        "connect_elements": GoldCall("connect_elements", {
            "guid": "eeeeeeeeeeeeeeeeeeee22", "relating_guid": "rrrrrrrrrrrrrrrrrrrr11",
            "related_guid": "rrrrrrrrrrrrrrrrrrrr22", "name": None}),
        "delete_filling_with_opening": GoldCall("delete_filling_with_opening", {
            "guid": "ffffffffffffffffffff11"}),
    }
    wanted = {
        "add_filling": "geom.add_filling(",
        "replace_filling": "geom.replace_filling(",
        "add_box_element": "geom.add_box_element(",
        "add_box_element_world": "geom.add_box_element(",
        "add_box_element_world_turned": "geom.add_box_element(",
        "add_wall_span": "geom.add_box_element(",
        "copy_element": "geom.copy_element(",
        "array_elements": "geom.array_elements(",
        "add_space_boundary": "geom.add_space_boundary(",
        "connect_elements": "geom.connect_elements(",
        "delete_filling_with_opening": "geom.delete_filling(",
    }
    for func, call in calls.items():
        code = emit_edit([call], GEOM).code
        compile(code, f"<{func}>", "exec")
        check(f"{func} is written as {wanted[func]}...)", wanted[func] in code,
              code)
        leaked = [name for name in BY_HAND if name in code]
        check(f"{func} writes none of the helper's own entities", not leaked,
              f"{leaked} in\n{code}")
        check(f"{func} defines no helper function", "\ndef " not in code, code)

    # the same calls under the plain style still build everything by hand
    plain = emit_edit([calls["add_filling"]], PLAIN).code
    check("with the style off the filling is still built by hand",
          "IfcRelVoidsElement" in plain and "geom." not in plain, plain)


def test_frames_and_wording() -> None:
    """The frame and the ``along`` the call carries are the instruction's own."""
    print("\n== test_frames_and_wording")
    storey = GoldCall("add_box_element", {
        "ifc_class": "IfcWall", "guid": "bbbbbbbbbbbbbbbbbbbb11", "name": "W",
        "storey_guid": "ssssssssssssssssssss11", "x": 1.0, "y": 2.0, "z": 0.0,
        "length": 4.0, "width": 0.2, "height": 2.3, "predefined_type": None,
        "long_name": None})
    world = GoldCall("add_box_element_world", dict(storey.kwargs))
    check("a storey-frame corner is written frame='storey'",
          "frame='storey'" in emit_edit([storey], GEOM).code.replace('"', "'"))
    check("a world-frame corner is written frame='world'",
          "frame='world'" in emit_edit([world], GEOM).code.replace('"', "'"))

    centred = GoldCall("add_filling", {
        "ifc_class": "IfcWindow", "guid": "aaaaaaaaaaaaaaaaaaaaaa", "name": "G",
        "host_guid": "hhhhhhhhhhhhhhhhhhhhh1", "along": 1.93, "across": -0.2,
        "sill": 0.0, "width": 0.9, "height": 2.1, "thickness": 0.3,
        "predefined_type": None})
    params = {"placement": {"kind": "centred_on_wall", "centre_from_start": 2.38}}
    code = emit_edit([centred], GEOM, params).code
    check("the middle-of-the-leaf wording is written along_is_centre=True",
          "along_is_centre=True" in code, code)
    check("and the number it carries is the instruction's centre, measured"
          " from the wall's own start",
          "+ 2.38" in code and "geom.wall_box(" in code and "1.93" not in code,
          code)
    plain_centre = emit_edit([centred], GEOM).code
    check("without that wording the call carries the near edge",
          "along=1.93" in plain_centre and "along_is_centre" not in plain_centre,
          plain_centre)

    offset = {"offset": {"reference_guid": "ffffffffffffffffffff99", "dx": 3.0,
                         "dy": 8.0, "x_axis": "+X", "y_axis": "-Y"}}
    code = emit_edit([storey], GEOM, offset).code
    check("an offset corner is measured with origin_in_frame",
          "geom.origin_in_frame(" in code, code)
    check("and the stated offset is added to what it returns",
          "+ 3.0" in code and "- 8.0" in code, code)
    check("the element the offset is measured from has to be found first",
          "ffffffffffffffffffff99" in emit_edit([storey], GEOM, offset).referenced_guids)

    top = {"placement": {"kind": "on_top_of", "anchor_guid": "ffffffffffffffffffff98"}}
    code = emit_edit([world], GEOM, top).code
    check("sitting on top of an element is measured with spot_on_top_of",
          "geom.spot_on_top_of(" in code, code)

    beside = {"placement": {"kind": "adjacent_to_space",
                            "anchor_guid": "ffffffffffffffffffff97",
                            "refs": ["ffffffffffffffffffff96",
                                     "ffffffffffffffffffff97"]}}
    code = emit_edit([world], GEOM, beside).code
    check("standing against a wall in a room is measured with spot_beside",
          "geom.spot_beside(" in code, code)
    check("and the long name of that placer is not written out",
          "geom.spot_beside_wall_in_space(" not in code, code)
    check("and the room it stands in has to be found first",
          "ffffffffffffffffffff96" in emit_edit([world], GEOM, beside).referenced_guids)


def test_replace_needs_no_host() -> None:
    """The library reads the wall off the element it replaces."""
    print("\n== test_replace_needs_no_host")
    call = GoldCall("replace_filling", {
        "guid": "oooooooooooooooooooo11", "ifc_class": "IfcDoor",
        "new_guid": "nnnnnnnnnnnnnnnnnnnn11", "name": "D",
        "host_guid": "hhhhhhhhhhhhhhhhhhhhh2", "along": 13.76, "across": -0.1,
        "sill": 0.0, "width": 0.9, "height": 2.1, "thickness": 0.2,
        "predefined_type": None})
    check("the hand-written edit has to find the wall",
          "hhhhhhhhhhhhhhhhhhhhh2" in referenced_guids([call]))
    check("the library edit does not",
          "hhhhhhhhhhhhhhhhhhhhh2" not in referenced_guids([call], geom=True))


# ------------------------------------------------------------ measuring rounds

def test_measure_rounds(records: list[dict]) -> None:
    """A create edit reads what it places its element against."""
    print("\n== test_measure_rounds")
    if not records:
        print("skip  the pilot task file is not on this machine")
        return
    wanted = ("create_filling", "replace_filling", "offset", "on_top_of",
              "adjacent_to_space", "create_wall_with_door")
    found = one_per_kind(records, wanted)
    check("the pilot holds an example of each create wording",
          set(found) == set(wanted), f"missing {sorted(set(wanted) - set(found))}")
    expected = {
        "create_filling": "geom.wall_box(",
        "replace_filling": "geom.filling_slot(",
        "offset": "geom.origin_in_frame(",
        "on_top_of": "geom.spot_on_top_of(",
        "adjacent_to_space": "geom.spot_beside_wall_in_space(",
    }
    for kind, marker in expected.items():
        record = found[kind]
        record["_calls"] = parse_gold_script(record["gold_script"])
        rounds = _measure_rounds(record, GEOM)
        code = "\n".join(r.code for r in rounds)
        for r in rounds:
            compile(r.code, f"<{kind}>", "exec")
        check(f"{kind} measures with {marker}...)", marker in code,
              f"{record['task_id']}\n{code}")

    # the round can be the first of a trajectory, so it names its own element
    record = found["replace_filling"]
    code = "\n".join(r.code for r in _measure_rounds(record, GEOM))
    check("the replacement's measuring round prints the element it read",
          ".GlobalId" in code, code)

    # a wall the edit is about to create cannot be measured before it exists
    record = found["create_wall_with_door"]
    record["_calls"] = parse_gold_script(record["gold_script"])
    check("a wall the edit creates itself is not measured first",
          not _measure_rounds(record, GEOM), record["task_id"])
    check("and the plain style measures nothing at all",
          not _measure_rounds(record, PLAIN), record["task_id"])


def test_plan_order(records: list[dict]) -> None:
    """The measuring round stands between the lookups and the edit."""
    print("\n== test_plan_order")
    if not records:
        print("skip  the pilot task file is not on this machine")
        return
    found = one_per_kind(records, ("create_filling", "replace_filling"))
    for kind, record in sorted(found.items()):
        turns, _rounds, edit = plan(dict(record), Style.for_seed(3, geom_lib=True))
        purposes = [t.purpose for t in turns]
        check(f"{kind} plans a round that measures the wall",
              any("measure" in p or "sits in its wall" in p for p in purposes),
              str(purposes))
        edit_at = next(i for i, t in enumerate(turns) if t.purpose == "edit")
        measured = [i for i, p in enumerate(purposes)
                    if "measure" in p or "sits in its wall" in p]
        check(f"{kind} measures before it edits", all(i < edit_at for i in measured),
              str(purposes))
        check(f"{kind}'s edit calls geom", "geom." in edit.code, edit.code)
        compile(edit.code, f"<{kind}>", "exec")


def test_no_long_name() -> None:
    """A created space carries no long name the instruction never gave."""
    print("\n== test_no_long_name")
    space = GoldCall("add_box_element_world", {
        "ifc_class": "IfcSpace", "guid": "bbbbbbbbbbbbbbbbbbbb55", "name": "Room 1",
        "storey_guid": "ssssssssssssssssssss11", "x": 1.0, "y": 2.0, "z": 0.0,
        "length": 4.0, "width": 3.0, "height": 3.1, "predefined_type": None,
        "long_name": "New space"})
    code = emit_edit([space], GEOM).code
    check("the library call writes no long_name", "long_name" not in code, code)
    check("and the string the generator uses is not in the edit",
          "New space" not in code, code)
    check("while the hand-written edit still writes it",
          "New space" in emit_edit([space], PLAIN).code)


def test_units_round_quotes_the_instruction(records: list[dict]) -> None:
    """The unit round lists what the instruction states, not what was derived."""
    print("\n== test_units_round_quotes_the_instruction")
    if not records:
        print("skip  the pilot task file is not on this machine")
        return
    seen = 0
    leaked: list[str] = []
    for record in records:
        if record["operation"] != "create" or record.get("edit_kind") == "clarify":
            continue
        task = dict(record)
        task["_calls"] = parse_gold_script(task["gold_script"])
        edit = emit_edit(task["_calls"], GEOM, task.get("edit_params"))
        found = _units_round(task, GEOM, edit)
        if found is None:
            continue
        seen += 1
        quoted = numbers_in_text(task.get("instruction") or task.get("prompt", ""))
        # The listed pairs are (the number the instruction wrote, the same
        # number in metres). Only the first of each pair is a claim about what
        # the instruction says, so only that one is checked here.
        for line in found.code.splitlines():
            if not line.startswith("for stated, metres in"):
                continue
            for pair in re.finditer(r"\((-?[\d.]+), (-?[\d.]+)\)", line):
                value = float(pair.group(1))
                if not any(abs(value - number) <= 1e-6 for number in quoted):
                    leaked.append(f"{task['task_id']}: {value}")
    check(f"{seen} pilot tasks get a unit round", seen > 0)
    check("and none of them lists a number the instruction does not quote",
          not leaked, f"{leaked[:6]}")


def test_predefined_type_is_stated() -> None:
    """A type reaches the edit only when the instruction names it."""
    print("\n== test_predefined_type_is_stated")
    call = GoldCall("add_filling", {
        "ifc_class": "IfcDoor", "guid": "aaaaaaaaaaaaaaaaaaaaaa", "name": "D",
        "host_guid": "hhhhhhhhhhhhhhhhhhhhh1", "along": 2.3, "across": -0.1,
        "sill": 0.0, "width": 0.9, "height": 2.1, "thickness": 0.2,
        "predefined_type": "TRAPDOOR"})
    silent = emit_edit([call], GEOM, None, "Add a new door named 'D'.").code
    check("a type the instruction never states is left out",
          "TRAPDOOR" not in silent, silent)
    spoken = emit_edit([call], GEOM, None,
                       "Add a new door named 'D'. Give it the predefined type"
                       " TRAPDOOR.").code
    check("and one the instruction states is written",
          "predefined_type='TRAPDOOR'" in spoken.replace('"', "'"), spoken)
    box = GoldCall("add_box_element_world", {
        "ifc_class": "IfcSlab", "guid": "bbbbbbbbbbbbbbbbbbbb11", "name": "S",
        "storey_guid": "ssssssssssssssssssss11", "x": 1.0, "y": 2.0, "z": 3.0,
        "length": 4.0, "width": 4.0, "height": 0.2, "predefined_type": "ROOF",
        "long_name": None})
    check("the same rule holds for a box",
          "ROOF" not in emit_edit([box], GEOM, None, "Add a slab named 'S'.").code)
    check("and the hand-written style is left as it was",
          "TRAPDOOR" in emit_edit([call], PLAIN, None, "Add a door.").code)


def _literals_are_quoted(record: dict) -> list[float]:
    """Numbers the emitted edit writes that the task's instruction does not."""
    calls = parse_gold_script(record["gold_script"])
    instruction = record.get("instruction") or record.get("prompt", "")
    code = emit_edit(calls, GEOM, record.get("edit_params"), instruction).code
    compile(code, record["task_id"], "exec")
    quoted = numbers_in_text(instruction)
    return [value for value in numbers_in_code(code)
            if not number_observed(value, quoted)]


def test_span_and_centre_write_no_derived_number(records: list[dict]) -> None:
    """The two wordings whose numbers the generator works out."""
    print("\n== test_span_and_centre_write_no_derived_number")
    if not records:
        print("skip  the pilot task file is not on this machine")
        return
    spans = [r for r in records if r["operation"] == "create"
             and any(c.func == "add_wall_span"
                     for c in parse_gold_script(r["gold_script"]))]
    centred = [r for r in records if r["operation"] == "create"
               and ((r.get("edit_params") or {}).get("placement") or {}
                    ).get("kind") == "centred_on_wall"]
    check(f"the pilot holds {len(spans)} span tasks", bool(spans))
    check(f"and {len(centred)} centred-leaf tasks", bool(centred))

    example = emit_edit(parse_gold_script(spans[0]["gold_script"]), GEOM,
                        spans[0].get("edit_params"), spans[0]["instruction"]).code
    check("a span's length is computed in the edit rather than quoted",
          "abs(x2 - x1)" in example or "abs(y2 - y1)" in example, example)
    check("and its lowest corner too", "min(x1, x2)" in example, example)

    first = emit_edit(parse_gold_script(centred[0]["gold_script"]), GEOM,
                      centred[0].get("edit_params"),
                      centred[0]["instruction"]).code
    check("a centred leaf is placed off the wall's own start",
          "geom.wall_box(" in first and "along_is_centre=True" in first, first)

    bad = [(r["task_id"], _literals_are_quoted(r)) for r in spans + centred]
    bad = [(task_id, left) for task_id, left in bad if left]
    check(f"none of the {len(spans) + len(centred)} writes a number the"
          f" instruction does not state", not bad, f"{bad[:4]}")


def test_every_create_compiles(records: list[dict]) -> None:
    """Every create task of the pilot emits a snippet that compiles."""
    print("\n== test_every_create_compiles")
    if not records:
        print("skip  the pilot task file is not on this machine")
        return
    seen = 0
    leaked: list[str] = []
    for record in records:
        if record["operation"] != "create" or record.get("edit_kind") == "clarify":
            continue
        calls = parse_gold_script(record["gold_script"])
        if not calls:
            continue
        code = emit_edit(calls, GEOM, record.get("edit_params"),
                         record.get("instruction") or "").code
        compile(code, record["task_id"], "exec")
        seen += 1
        if any(name in code for name in BY_HAND):
            leaked.append(record["task_id"])
    check(f"all {seen} create edits of the pilot compile", seen > 0)
    check("and none of them builds an entity the library builds",
          not leaked, f"{leaked[:5]}")


def main() -> int:
    records = load_pilot()
    test_emitters()
    test_frames_and_wording()
    test_replace_needs_no_host()
    test_no_long_name()
    test_measure_rounds(records)
    test_plan_order(records)
    test_units_round_quotes_the_instruction(records)
    test_predefined_type_is_stated()
    test_span_and_centre_write_no_derived_number(records)
    test_every_create_compiles(records)
    print(f"\nall checks passed ({PASSED})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
