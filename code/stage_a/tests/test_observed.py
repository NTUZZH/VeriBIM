"""The two checks on a trajectory, and the lookups that let one hold them.

Three claims. First, the walk over a conversation accepts an identifier the
instruction wrote or an earlier tool result printed and refuses every other one,
which is the rule the model works under at evaluation time. Second, for every
anchor kind the generator writes, the planner's first tool call carries no
identifier the instruction did not carry: the elements the phrase refers to are
found by the names the instruction quotes. Third, an identifier that came out of
a listing of several candidates is accepted only when the transcript says which
candidate the instruction meant, and the planner reads the containment link
whenever the instruction gives the storey through an element rather than by
name.

    python -m stage_a.tests.test_observed
"""

from __future__ import annotations

import json
from pathlib import Path

from stage_a import nameindex, paths
from stage_a.nameindex import NameIndex
from stage_a.observed import (guids_in_code, guids_in_text,
                              listing_choice_justified, looks_like_guid,
                              names_in_code, names_observed_ok,
                              numbers_in_code, numbers_in_text,
                              numbers_observed_ok, observed_identifiers_ok)
from stage_a.style import Style
from stage_a.synthesize import ANCHOR_GUID_KEYS, plan

TASKS = paths.PROJECT_ROOT / "runs_local/stage_a_v2/tasks_selected.jsonl"
INDEX_ROOT = paths.PROJECT_ROOT / "runs_local/stage_a_v3/name_index"

A = "0ELnodLOr8mQ4vsWfSrVC9"
B = "3$f9rYNXRt6nBcyBanb7Ua"
C = "1JzwEp1_mQDupWlAuQRqBS"


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed. {detail}")
    print(f"ok  {name}")


def call(code: str) -> dict:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": "call_1", "type": "function",
                            "function": {"name": "run_python",
                                         "arguments": {"code": code}}}]}


def result(text: str) -> dict:
    return {"role": "tool", "tool_call_id": "call_1", "name": "run_python",
            "content": text}


def user(text: str) -> dict:
    return {"role": "user", "content": text}


def test_tokens() -> None:
    check("a GlobalId is recognised", looks_like_guid(A) and looks_like_guid(B))
    check("an IFC class name of the same length is not",
          not looks_like_guid("IfcRectangleProfileDef"))
    check("a word with no digit, underscore or dollar is not",
          not looks_like_guid("abcdefghijklmnopqrstuv"))
    check("a literal in code is found",
          guids_in_code(f"target = ifc.by_guid('{A}')") == {A})
    check("a bare name of the same length in code is not",
          guids_in_code("CoordinateSpaceDimensions = 3") == set())
    check("an identifier inside a longer token is not read as one",
          guids_in_text(f"{A}XYZ") == set())


def test_walk() -> None:
    instruction = f"Delete the wall with GlobalId '{A}'."

    good = [user(instruction), call(f"ifc.by_guid('{A}')"), result(f"IfcWall {B}"),
            call(f"ifc.by_guid('{B}')"), result("ok")]
    check("a trajectory that uses only what it was given passes",
          observed_identifiers_ok(good, instruction) == [])

    check("the instruction alone pays for an identifier",
          observed_identifiers_ok([user(instruction), call(f"ifc.by_guid('{A}')")],
                                  instruction) == [])

    printed = [user("Delete the wall on storey 'Level 1'."),
               call("for s in ifc.by_type('IfcBuildingStorey'): print(s.GlobalId)"),
               result(f"{B} 'Level 1'"), call(f"on_storey('{B}', 'IfcWall')")]
    check("an identifier an earlier tool result printed pays for itself",
          observed_identifiers_ok(printed, "Delete the wall on storey 'Level 1'.")
          == [])

    invented = [user("Delete the wall on storey 'Level 1'."),
                call(f"on_storey('{C}', 'IfcWall')")]
    found = observed_identifiers_ok(invented, "Delete the wall on storey 'Level 1'.")
    check("an identifier nothing showed the model is refused",
          found == [{"round": 0, "unresolved": [C]}], str(found))

    early = [user("Delete the wall on storey 'Level 1'."),
             call(f"on_storey('{B}', 'IfcWall')"),
             result(f"{B} 'Level 1'"),
             call(f"ifc.by_guid('{B}')")]
    found = observed_identifiers_ok(early, "Delete the wall on storey 'Level 1'.")
    check("an identifier used one round before it is printed is refused",
          found == [{"round": 0, "unresolved": [B]}], str(found))

    check("the user turn carries the instruction on its own",
          observed_identifiers_ok([user(instruction), call(f"ifc.by_guid('{A}')")])
          == [])

    closing = [user(instruction), call(f"ifc.by_guid('{A}')"), result("ok"),
               {"role": "assistant", "content": f"Removed {C}."}]
    check("a closing message is not code and is not judged",
          observed_identifiers_ok(closing, instruction) == [])


STOREYS = ("2WSdUCQgLA19aleUi6sdSw 'Ground Floor' 0.0\n"
           "39uTNFPctKJfAqNQwZbq2a 'Level 1' 3200.0\n"
           "0o8nNAbaT5OQLV8C9mNFXU 'Level 2' 6400.0")
S1 = "2WSdUCQgLA19aleUi6sdSw"
S2 = "39uTNFPctKJfAqNQwZbq2a"
S3 = "0o8nNAbaT5OQLV8C9mNFXU"


def test_listing() -> None:
    named = "Add a column on the storey that contains the column named 'X'."
    picked = [user(named), call("for s in ifc.by_type('IfcBuildingStorey'): print(s)"),
              result(STOREYS), call(f"storey = ifc.by_guid('{S2}')")]
    found = listing_choice_justified(picked, named)
    check("taking one storey out of a listing with no reason is refused",
          found == [{"round": 1, "unjustified": [S2]}], str(found))

    quoted = "Add a column on storey 'Level 1'."
    named_pick = [user(quoted), call("for s in ifc.by_type('IfcBuildingStorey'): print(s)"),
                  result(STOREYS), call(f"storey = ifc.by_guid('{S2}')")]
    check("the same listing is enough when the instruction names the storey",
          listing_choice_justified(named_pick, quoted) == [])

    linked = [user(named),
              call("print(reference.GlobalId, 'is contained in', storey.GlobalId)"),
              result(f"1hOSvn6df7F8_7GcBWlS_W IfcColumn X is contained in {S2}"
                     " IfcBuildingStorey 'Level 1' elevation 3200.0"),
              call(f"storey = ifc.by_guid('{S2}')")]
    check("a line that ties the storey to the named element is enough",
          listing_choice_justified(linked, named) == [])

    every = [user("Delete every storey."),
             call("for s in ifc.by_type('IfcBuildingStorey'): print(s)"),
             result(STOREYS),
             call(f"for g in ('{S1}', '{S2}', '{S3}'): ifc.by_guid(g)")]
    check("a round that uses every candidate the listing offered is not a choice",
          listing_choice_justified(every, "Delete every storey.") == [])

    alone = [user(named), call("print(matches)"),
             result(f"{S2} IfcBuildingStorey Level 1"),
             call(f"storey = ifc.by_guid('{S2}')")]
    check("an output that printed one candidate leaves nothing to choose",
          listing_choice_justified(alone, named) == [])

    instruction = f"Delete the wall with GlobalId '{A}'."
    check("an identifier the instruction writes is never a listing choice",
          listing_choice_justified(
              [user(instruction), call("for s in ifc.by_type('IfcWall'): print(s)"),
               result(f"{A} IfcWall one\n{B} IfcWall two"),
               call(f"ifc.by_guid('{A}')")], instruction) == [])


def load_one_per_kind() -> dict[str, dict]:
    """One task of every anchor kind, skipping the ones that ask a question."""
    per: dict[str, dict] = {}
    with TASKS.open(encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            if record.get("clarification") and record.get("expected_reply"):
                continue
            kind = (record.get("anchor") or {}).get("kind")
            if kind and kind not in per:
                per[kind] = record
    return per


def test_lookups() -> None:
    if not TASKS.exists() or not INDEX_ROOT.exists():
        print("--  the v2 task file or the name index is not on this machine,"
              " skipped")
        return
    per = load_one_per_kind()
    check("the task file holds every anchor kind", len(per) >= 18, str(sorted(per)))
    cache: dict[str, NameIndex] = {}
    for kind, record in sorted(per.items()):
        key = nameindex.index_key(record)
        if key not in cache:
            path = INDEX_ROOT / f"{key}.json"
            cache[key] = NameIndex(json.loads(path.read_text(encoding="utf-8")))
        index = cache[key]
        style = Style.for_seed(int((record.get("seeds") or {}).get("task_seed", 0)))
        notes: dict[str, str] = {}
        turns, _rounds, _edit = plan(dict(record), style, index, notes)
        check(f"the {kind} anchor plans a trajectory",
              bool(turns), notes.get("reason", ""))
        first = next(turn for turn in turns if turn.code)
        compile(first.code, f"<{kind}>", "exec")
        instruction = record.get("instruction") or record["prompt"]
        params = (record.get("anchor") or {}).get("params") or {}
        literals = guids_in_code(first.code)
        written = {params[key] for key in ANCHOR_GUID_KEYS
                   if isinstance(params.get(key), str)
                   and params[key] in instruction}
        check(f"the {kind} anchor's first call writes no identifier it was"
              f" not given",
              literals <= written,
              f"{record['task_id']}: {sorted(literals - written)}")
        looked_up = {params[key] for key in ANCHOR_GUID_KEYS
                     if isinstance(params.get(key), str) and len(params[key]) == 22}
        if looked_up - written:
            check(f"the {kind} anchor looks its reference up by name",
                  "by_name(" in first.code or "by_name_on_storey(" in first.code,
                  record["task_id"])


def find_task(predicate) -> dict | None:
    with TASKS.open(encoding="utf-8") as fh:
        for line in fh:
            record = json.loads(line)
            if predicate(record):
                return record
    return None


def test_storey_of_round() -> None:
    """A storey given through an element is read off that element."""
    if not TASKS.exists() or not INDEX_ROOT.exists():
        print("--  the v2 task file or the name index is not on this machine,"
              " skipped")
        return
    derived = find_task(lambda r: r["task_id"] == "CHN-CWD-TOP-B20-001")
    listed = find_task(lambda r: r["task_id"] == "CHN-CWD-SPA-B01-001")
    check("the two create tasks the check needs are in the task file",
          derived is not None and listed is not None)

    for record, wants_link in ((derived, True), (listed, False)):
        key = nameindex.index_key(record)
        index = NameIndex(json.loads(
            (INDEX_ROOT / f"{key}.json").read_text(encoding="utf-8")))
        style = Style.for_seed(int((record.get("seeds") or {}).get("task_seed", 0)))
        turns, _rounds, _edit = plan(dict(record), style, index, {})
        purposes = [turn.purpose for turn in turns]
        link = "read the storey the named element is contained in"
        listing = "identify the storey by name"
        if wants_link:
            check(f"{record['task_id']} reads the containment link",
                  link in purposes and listing not in purposes, str(purposes))
            code = next(t.code for t in turns if t.purpose == link)
            check(f"{record['task_id']} follows containment and decomposition",
                  "ContainedInStructure" in code and "Decomposes" in code)
            check(f"{record['task_id']} prints the storey it resolved to",
                  "is contained in" in code and "elevation" in code)
        else:
            check(f"{record['task_id']} keeps the storey listing,"
                  f" since the instruction names the storey",
                  listing in purposes and link not in purposes, str(purposes))
        for turn in turns:
            if turn.code:
                compile(turn.code, f"<{record['task_id']}>", "exec")


def test_number_tokens() -> None:
    """Which literals count as a quantity, in prose and in code."""
    text = ("Add a door 0.9 m wide and 2.1 m high, 2.3 m along the wall, in the"
            " wall with GlobalId '3MD$kLhGDEEOBkCo$6woEa' named 'Wall - 033'.")
    found = numbers_in_text(text)
    check("a quantity in prose is read", {0.9, 2.1, 2.3} <= found, str(found))
    check("and an identifier on its own carries no quantity",
          not numbers_in_text("3MD$kLhGDEEOBkCo$6woEa 0e$SWHp1zE7vA9ZmBiPLLK"),
          str(numbers_in_text("3MD$kLhGDEEOBkCo$6woEa")))
    check("a name's own number is read as a number", 33.0 in found, str(found))

    code = ("import numpy as np\n"
            "def helper(x):\n"
            "    return np.array(x).reshape(-1, 3) / 2.0\n"
            "values = [1, 2, 3]\n"
            "print(round(values[0], 3), values[:20])\n"
            "leaf = geom.add_filling(host, 'IfcDoor', 'Doorset 826',\n"
            "                        width=0.9, height=2.1, along=2.3, sill=0.0)\n")
    numbers = numbers_in_code(code)
    check("a length the code writes is a quantity",
          {0.9, 2.1, 2.3} <= set(numbers), str(numbers))
    check("a rounding digit, a slice bound and a shape are not",
          not ({20.0} & set(numbers)), str(numbers))
    check("a constant inside a helper the round defines is not",
          2.0 not in numbers, str(numbers))
    check("a number inside a string is not", 826.0 not in numbers, str(numbers))
    check("zero is not a measurement", 0.0 not in numbers, str(numbers))
    check("only the floats come back when the caller asks for lengths",
          all(isinstance(v, float) for v in numbers_in_code(code, floats_only=True))
          and 2.0 not in numbers_in_code(code, floats_only=True), str(numbers))


def test_number_walk() -> None:
    """A round may write a number it read, and no other."""
    instruction = ("Add a new column 0.4 m by 0.4 m in section and 3.7 m high,"
                   " 3 m to the east (+X) of the column named 'C1'.")
    good = [user(instruction),
            call("reference = ifc.by_guid('16m7AeRcv3Tvvy74g$saxk')\n"
                 "corner = geom.origin_in_frame(reference, storey)\n"),
            result("reference origin in the storey frame (m): [12.5, 4.25, 0.0]"),
            call("added = geom.add_box_element(storey, 'IfcColumn', 'C2',\n"
                 "                             corner[0] + 3.0, corner[1], 0.0,\n"
                 "                             0.4, 0.4, 3.7, frame='world')\n")]
    check("a round that writes what the instruction states holds",
          not numbers_observed_ok(good, instruction),
          str(numbers_observed_ok(good, instruction)))

    bad = list(good)
    bad[-1] = call("added = geom.add_box_element(storey, 'IfcColumn', 'C2',\n"
                   "                             15.5, 4.25, 0.0,\n"
                   "                             0.4, 0.4, 3.7, frame='world')\n")
    found = numbers_observed_ok(bad, instruction)
    check("a coordinate nothing printed is caught", bool(found), str(found))
    check("and the one the earlier round printed is not", 
          15.5 in found[0]["unobserved"] and 4.25 not in found[0]["unobserved"],
          str(found))

    millimetres = ("Add a new column 400 mm by 400 mm in section and 3700 mm"
                   " high, at (1000, 2000, 0) mm.")
    metres = [user(millimetres),
              call("geom.add_box_element(storey, 'IfcColumn', 'C3', 1.0, 2.0, 0.0,\n"
                   "                     0.4, 0.4, 3.7, frame='world')\n")]
    check("a stated length converted into metres counts as read",
          not numbers_observed_ok(metres, millimetres),
          str(numbers_observed_ok(metres, millimetres)))

    flipped = [user("Copy the column 0.6 m to the south (-Y)."),
               call("geom.copy_element(product, 0.0, -0.6, 0.0, 'Post 1')\n")]
    check("a stated distance written with the sign the direction gives counts",
          not numbers_observed_ok(flipped, "Copy the column 0.6 m to the south (-Y)."),
          "sign flip")


def test_name_tokens() -> None:
    """Which strings in a snippet are names of something in the model."""
    code = ("def by_name(ifc_class, wanted):\n"
            "    print('named', repr(wanted))\n"
            "    raise ValueError('%d are named %r')\n"
            "storey = by_name('IfcBuildingStorey', 'Level 1')\n"
            "matches = [e for e in ifc.by_type('IfcColumn')\n"
            "           if (e.Name or '').strip() == 'Concrete-Column:24x24']\n"
            "print('model length unit in metres:', scale)\n"
            "start = wall['start']\n")
    found = names_in_code(code)
    check("a name a lookup matches on is a name",
          "Level 1" in found and "Concrete-Column:24x24" in found, str(found))
    check("a class token is not", not any(n.startswith("Ifc") for n in found),
          str(found))
    check("a message a round prints is not",
          "model length unit in metres:" not in found, str(found))
    check("a string inside a helper the round defines is not",
          "named" not in found, str(found))
    check("and a dictionary key is not", "start" not in found, str(found))


def test_name_walk() -> None:
    """A round may match on a name it was given, and no other."""
    instruction = ("Add a new wall named 'Partition 968' on storey"
                   " 'Basement (Parking)', 4 m long.")
    good = [user(instruction),
            call("storey = by_name('IfcBuildingStorey', 'Basement (Parking)')\n"),
            result("named 'Basement (Parking)' -> " + A + " IfcBuildingStorey"),
            call("added = geom.add_box_element(storey, 'IfcWall',"
                 " 'Partition 968', 1.0, 2.0, 0.0, 4.0, 0.2, 2.9)\n")]
    check("a lookup on a name the instruction gives holds",
          not names_observed_ok(good, instruction),
          str(names_observed_ok(good, instruction)))

    hidden = [user(instruction),
              call("matches = [e for e in ifc.by_type('IfcColumn')\n"
                   "           if (e.Name or '').strip()"
                   " == 'Concrete-Rectangular-Column:24 x 24:258517']\n")]
    found = names_observed_ok(hidden, instruction)
    check("a lookup on a name the instruction withholds is caught", bool(found),
          str(found))
    check("and the name it quotes is the one reported",
          found and found[0]["unnamed"] == ["Concrete-Rectangular-Column:24 x 24:258517"],
          str(found))

    printed = [user(instruction),
               call("for s in ifc.by_type('IfcBuildingStorey'):\n"
                    "    print(s.GlobalId, repr(s.Name))\n"),
               result("%s 'Mezzanine'" % A),
               call("level = by_name('IfcBuildingStorey', 'Mezzanine')\n")]
    check("a name an earlier round printed counts as given",
          not names_observed_ok(printed, instruction),
          str(names_observed_ok(printed, instruction)))


def test_unnamed_anchor_is_dropped() -> None:
    """A task whose anchor the instruction never names plans no lookup for it."""
    records = [json.loads(line) for line in
               Path(TASKS).read_text(encoding="utf-8").splitlines()[:4000]
               if line.strip()] if Path(TASKS).exists() else []
    hidden = None
    for record in records:
        anchor = record.get("anchor") or {}
        name = (anchor.get("params") or {}).get("name")
        instruction = record.get("instruction") or record.get("prompt", "")
        if (record.get("edit_kind") == "create_wall_with_door" and name
                and f"'{name}'" not in instruction):
            hidden = record
            break
    if hidden is None:
        print("skip  no task with an unnamed anchor in the sample read")
        return
    index = nameindex.load(Path(INDEX_ROOT), hidden,
                           paths.PROJECT_ROOT, build_if_missing=False)
    notes: dict = {}
    turns, rounds, _edit = plan(dict(hidden), Style.for_seed(11, geom_lib=True),
                                index, notes)
    check(f"{hidden['task_id']} plans without resolving the anchor",
          bool(turns) and notes.get("anchor_dropped"), str(notes))
    name = (hidden["anchor"]["params"] or {})["name"]
    for turn in turns:
        if turn.code:
            check(f"and no round of it quotes {name[:24]!r}",
                  name not in turn.code, turn.code[:200])
            break


def main() -> int:
    for name, test in (("test_tokens", test_tokens), ("test_walk", test_walk),
                       ("test_listing", test_listing),
                       ("test_lookups", test_lookups),
                       ("test_storey_of_round", test_storey_of_round),
                       ("test_number_tokens", test_number_tokens),
                       ("test_number_walk", test_number_walk),
                       ("test_name_tokens", test_name_tokens),
                       ("test_name_walk", test_name_walk),
                       ("test_unnamed_anchor_is_dropped",
                        test_unnamed_anchor_is_dropped)):
        print(f"\n== {name}")
        test()
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
