"""The 0.7.0 task families, checked without running a sandbox or a scorer.

Everything here is about the code the planner writes and the reading the filter
applies, so it needs no IFC model and no GPU. Four claims carry the weight. A
task whose instruction leaves out a value must plan a trajectory that makes no
edit, calls no ``commit()`` and ends on the question the record expects, and
that reply must satisfy the check the scorer runs on it. Every anchor kind the
generator writes must produce a snippet that compiles, because a kind with no
lookup is a family the synthesizer refuses in full. An identifier that reaches
the edit through a storey, a type object or a wall a filling moves into must be
paid for by the round that looks that thing up. And a task carrying a material
or a type assignment must be graded under the settings that make the edit
visible, since the shipped reading scores an untouched model perfectly on both.

    python -m stage_a.tests.test_families
"""

from __future__ import annotations

import json
from pathlib import Path

from stage_a import paths
from stage_a.goldcode import GoldCall, emit_edit, parse_gold_script
from stage_a.inspection import (resolve_round, stated_lengths, type_objects_round,
                                units_round, materials_round, host_round,
                                rehost_candidates_round)
from stage_a.scoring import (FAMILY_READING, is_underspecified, reading_for,
                             scorer_config_for)
from stage_a.style import Style
from stage_a.synthesize import (_batch_check_lines, _batch_scope,
                                _discovery_rounds, plan, plan_clarification)

PILOT = paths.PROJECT_ROOT / "runs_local/gen_v07/pilot/tasks.jsonl"

STYLE = Style.for_seed(20260910)


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed. {detail}")
    print(f"ok  {name}")


def compiles(code: str, what: str) -> None:
    compile(code, f"<{what}>", "exec")


def load_pilot() -> list[dict]:
    """The pilot task file, or an empty list where it is not on this machine."""
    if not PILOT.exists():
        return []
    return [json.loads(line) for line in PILOT.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def first(records: list[dict], **fields) -> dict | None:
    for record in records:
        if all(record.get(key) == value for key, value in fields.items()):
            return record
    return None


def by_anchor(records: list[dict], kind: str) -> dict | None:
    for record in records:
        if (record.get("anchor") or {}).get("kind") == kind:
            return record
    return None


# --------------------------------------------------------------------------

def test_readings() -> None:
    material = {"operation": "update", "families": ["op.update.material"]}
    config = scorer_config_for(material)
    check("a material association is compared as a property",
          config.properties_include_material is True)
    check("and the association is an edge of the relation graph",
          "IfcRelAssociatesMaterial" in config.topology_relations_extra)

    type_object = {"operation": "update", "families": ["op.update.type_object"]}
    config = scorer_config_for(type_object)
    check("a type assignment is compared as a property",
          config.properties_include_type is True)
    check("and the assignment is an edge of the relation graph",
          "IfcRelDefinesByType" in config.topology_relations_extra)

    pset = {"operation": "update", "families": ["op.update.pset"]}
    check("a property-set write needs no setting the shipped reading lacks",
          scorer_config_for(pset).topology_modified_include_psets is True
          and reading_for(pset)["settings"] == {})

    plain = {"operation": "update", "families": ["op.update.geometry.translate"]}
    check("every other update is read exactly as the published runs read it",
          reading_for(plain)["settings"] == {})

    delete = {"operation": "delete", "families": ["op.delete"]}
    check("a deletion is read by removal",
          reading_for(delete)["settings"] == {"delete_semantics": "removal"})

    under = {"operation": "create", "families": ["wording.underspecified"],
             "clarification": {"slot": "storey"}, "expected_reply": "Which storey?"}
    check("an under-specified task is read by its file and its reply",
          scorer_config_for(under).underspecified_mode is True
          and reading_for(under)["axes"] == ["reply"])
    check("and it is recognised from the record alone", is_underspecified(under))
    check("every family with its own reading names the axis it moves",
          all(axis in ("geometry", "semantics", "topology", "reply")
              for axis, _note in FAMILY_READING.values()))


def test_anchor_kinds(records: list[dict]) -> None:
    """Every anchor kind the pilot writes resolves to a snippet that compiles."""
    kinds = sorted({(r.get("anchor") or {}).get("kind") for r in records} - {None})
    check("the pilot's anchor kinds were found", len(kinds) >= 15, str(kinds))
    for kind in kinds:
        record = by_anchor(records, kind)
        round_ = resolve_round(record["anchor"], STYLE)
        compiles(round_.code, f"anchor:{kind}")
        expected = tuple(record["anchor"].get("expected") or ())
        check(f"the {kind} anchor compiles and carries what it must find",
              round_.expect_guids == expected)


def test_clarification(records: list[dict]) -> None:
    from modifc_score.clarify import reply_asks

    clarify_tasks = [r for r in records if is_underspecified(r)]
    check("the pilot holds under-specified tasks", len(clarify_tasks) >= 10)
    for record in clarify_tasks[:12]:
        turns, rounds, edit = plan(dict(record), STYLE)
        check(f"{record['task_id']} plans no edit",
              edit.code == "" and all(t.purpose != "edit" for t in turns))
        check(f"{record['task_id']} calls no commit",
              all("commit()" not in (t.code or "") for t in turns))
        check(f"{record['task_id']} ends on the question the record expects",
              turns[-1].code is None and turns[-1].content == record["expected_reply"])
        ok, detail = reply_asks(turns[-1].content,
                                record["clarification"].get("keywords") or ())
        check(f"{record['task_id']}'s reply names the missing value", ok, str(detail))
        for round_ in rounds:
            compiles(round_.code, "clarify")


def test_discovery(records: list[dict]) -> None:
    """An identifier the instruction does not give is paid for by a lookup."""
    wanted = ("move_to_storey", "assign_type", "rehost_filling", "replace_filling")
    for edit_kind in wanted:
        record = first(records, edit_kind=edit_kind)
        if record is None:
            print(f"--  no {edit_kind} task in the pilot, skipped")
            continue
        task = dict(record)
        calls = parse_gold_script(task["gold_script"])
        task["_calls"] = calls
        edit = emit_edit(calls, STYLE)
        anchor = task["anchor"]
        known = set(anchor.get("expected") or ())
        missing = [g for g in edit.referenced_guids
                   if g not in known and g not in task["instruction"]]
        if not missing:
            print(f"--  {edit_kind} names every identifier it uses, skipped")
            continue
        rounds = _discovery_rounds(task, edit, anchor, missing, STYLE)
        check(f"{edit_kind} gets a lookup for what it was not told",
              rounds is not None and len(rounds) >= 1)
        for round_ in rounds:
            compiles(round_.code, edit_kind)


def test_batch(records: list[dict]) -> None:
    batch = [r for r in records if (r.get("edit_params") or {}).get("batch_members")]
    check("the pilot holds batch tasks", len(batch) >= 10)
    for record in batch[:8]:
        members, pool = _batch_scope(record)
        check(f"{record['task_id']} names its set and the pool it came from",
              len(members) >= 2 and set(members) <= set(pool))
        code = "\n".join(_batch_check_lines(record, STYLE))
        compiles(code, "batch")
        check(f"{record['task_id']}'s read-back names every member",
              all(guid in code for guid in members))


def test_units(records: list[dict]) -> None:
    calls = [GoldCall(func="add_box_element",
                      kwargs={"length": 4.0, "width": 0.2, "height": 2.9})]
    pairs = stated_lengths(calls, "mm")
    check("a length in metres is written as the millimetres the instruction quotes",
          (4000.0, 4.0) in pairs and (200.0, 0.2) in pairs, str(pairs))
    check("and a metre instruction quotes metres",
          stated_lengths(calls, "m")[0] == (4.0, 4.0))
    round_ = units_round(calls, "mm", "millimetres", STYLE)
    compiles(round_.code, "units")
    check("the unit round divides by the file's own scale rather than a constant",
          "calculate_unit_scale(ifc)" in round_.code and "file units" in round_.code)

    quoted = [r for r in records
              if (r.get("wording") or {}).get("unit") in ("mm", "cm")]
    check("the pilot quotes lengths in other units", len(quoted) >= 10)
    for record in quoted[:6]:
        task = dict(record)
        task["_calls"] = parse_gold_script(task["gold_script"])
        turns, _rounds, _edit = plan(task, STYLE)
        check(f"{record['task_id']} reads the file's unit before it edits",
              any("calculate_unit_scale" in (t.code or "") for t in turns))


def test_family_rounds() -> None:
    for name, round_ in (("types", type_objects_round("column", STYLE)),
                         ("materials", materials_round(STYLE)),
                         ("host", host_round("0" * 22, STYLE)),
                         ("rehost", rehost_candidates_round("0" * 22, STYLE))):
        compiles(round_.code, name)
        print(f"ok  the {name} round compiles")


def test_world_frame(records: list[dict]) -> None:
    """A world coordinate on a turned storey is converted in code, not by hand."""
    turned = [r for r in records
              if "spec.world_frame" in (r.get("families") or ())]
    check("the pilot holds world-frame creates", len(turned) >= 5)
    for record in turned[:5]:
        calls = parse_gold_script(record["gold_script"])
        code = emit_edit(calls, STYLE).code
        compiles(code, "world_frame")
        check(f"{record['task_id']} puts the point through the storey's own frame",
              "get_local_placement" in code and "np.linalg.inv" in code)


def main() -> int:
    records = load_pilot()
    if not records:
        print(f"the pilot task file is not on this machine ({PILOT}); "
              "only the checks that need no records run")
    print("\n== test_readings")
    test_readings()
    print("\n== test_family_rounds")
    test_family_rounds()
    if records:
        for test in (test_anchor_kinds, test_clarification, test_discovery,
                     test_batch, test_units, test_world_frame):
            print(f"\n== {test.__name__}")
            test(records)
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
