"""Corpus v9 on the emitter's side: an identifier is looked up as an identifier.

Three things are asserted.  A reference the instruction gives by identifier is
bound with one ``ifc.by_guid`` line, followed by a print of what it resolved
to, and never through a name lookup.  The first lookup round of every anchor
kind, compiled for references given by identifier and in both code styles,
passes no 22-character identifier to ``by_name``.  And the trajectories the
v9 trial synthesized hold the same rule, together with the identifier walk.

Run with pytest.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import pytest

from stage_a.inspection import GEOM_LOOKUPS, GuidRef, Ref, resolve_round
from stage_a.observed import (guids_in_code, identifier_passed_as_name,
                              observed_identifiers_ok,
                              trajectory_identifier_as_name)
from stage_a.style import Style
from stage_a.synthesize import _anchor_refs

DEV = Path("runs_local/stage_a_v9_dev")
TRIALS = [DEV / "trial600/trajectories_gold.jsonl",
          DEV / "gen_trial/trajectories_gold.jsonl"]

G = {"storey": "0OCkzK25HA0wxSqRSYLGvE", "a": "3VzPfRc0rBQgucB78rpFWR",
     "b": "3VzPfRc0rBQgucB78rpCA0", "space": "0Xx9gDujQRJ9wzMj5p9LxT",
     "space_b": "2_NBtRqv0xHPyZ3gqke_JN", "door": "1D3ZCPNC9uIwAHigXIdfHL",
     "target": "2aGbxcRfH7xwAj5lAAxyB$", "wall2": "08B$sTOJPDh8SD5wFIfdgP"}

#: The kinds 0.8.0 added are resolved by the library alone; the hand-written
#: style never had a round for them, before v9 or after.
LIBRARY_ONLY = ("host_of", "joins", "bounds", "under", "without_relation")

#: One anchor per kind, with every reference parameter an identifier.
ANCHORS = {
    "offset": ("window", {"reference_guid": G["a"], "storey_guid": G["storey"],
                          "axis": 0, "sign": 1, "distance": 2.0,
                          "tolerance": 0.25, "lateral_tolerance": 0.5},
               "the window on the storey with ID {storey} that stands about "
               "2.0 m east (+X) of wall {a}"),
    "extreme": ("window", {"storey_guid": G["storey"], "axis": 0, "sign": 1,
                           "margin": 0.05},
                "the window furthest east (+X) on storey {storey}"),
    "nearest": ("window", {"reference_guid": G["a"], "storey_guid": G["storey"],
                           "margin": 0.25},
                "the window nearest to wall ID {a} on storey ID {storey}"),
    "between": ("window", {"a_guid": G["a"], "b_guid": G["b"],
                           "storey_guid": G["storey"], "axis": 0,
                           "inset": 0.2, "lateral_tolerance": 2.0},
                "the window on the storey (ID: {storey}) that stands between "
                "the walls (IDs: {a} and {b})"),
    "above_below": ("window", {"reference_guid": G["a"],
                               "storey_guid": G["storey"],
                               "direction": "above", "tolerance": 0.5},
                    "the window on storey {storey} directly above window {a}"),
    "opposite": ("window", {"reference_guid": G["a"], "space_guid": G["space"],
                            "axis": 0, "min_offset": 0.25},
                 "the window opposite the window with GUID {a} across the "
                 "room with GUID {space}"),
    "egocentric": ("window", {"door_guid": G["door"], "space_guid": G["space"],
                              "side": "left", "tolerance": 0.5},
                   "the window on the left-hand side as seen from door {door} "
                   "looking into room {space}"),
    "ordinal": ("window", {"host_guid": G["a"], "axis": 0, "sign": 1,
                           "index": 1, "min_gap": 0.2},
                "the second window from the west along the wall identified as "
                "{a}"),
    "negation": ("wall", {"variant": "bounding_wall_without_filling",
                          "space_guid": G["space"], "missing": "door"},
                 "the wall bounding the room with ID {space} that hosts no "
                 "door"),
    "host_of": ("wall", {"element_guid": G["door"]},
                "the wall in which door ID {door} is located"),
    "joins": ("door", {"space_a_guid": G["space"], "space_b_guid": G["space_b"]},
              "the door between rooms {space} and {space_b}"),
    "bounds": ("window", {"space_guid": G["space"]},
               "the window that bounds the space with the ID {space}"),
    "under": ("slab", {"storey_guid": G["storey"]},
              "the slab below the walls of the storey whose GlobalId is "
              "{storey}"),
    "without_relation": ("slab", {"storey_guid": G["storey"],
                                  "relation": "connection"},
                         "the only slab on storey {storey} that has no "
                         "connection to another element"),
    "hosted": ("door", {"host_guid": G["a"]},
               "the door hosted in wall ID {a}"),
    "bounding": ("wall", {"space_a_guid": G["space"],
                          "space_b_guid": G["space_b"]},
                 "the wall that bounds both the spaces with IDs {space} and "
                 "{space_b}"),
    "separates": ("wall", {"space_a_guid": G["space"],
                           "space_b_guid": G["space_b"]},
                  "the wall that separates rooms {space} and {space_b}"),
    "space_of": ("space", {"element_guid": G["a"], "element_b_guid": G["wall2"]},
                 "the space bounded by the walls with IDs {a} and {wall2}"),
    "connects": ("wall", {"other_guid": G["a"]},
                 "the wall connected to the wall identified as {a}"),
    "in_storey": ("column", {"storey_guid": G["storey"]},
                  "the only column contained in the storey with ID {storey}"),
    "set": ("door", {"scope": "host", "scope_guid": G["a"],
                     "scope_label": "", "condition": None},
            "every door hosted in the wall with ID {a}"),
    "set_ids": ("door", {"scope": "ids", "member_guids": [G["door"], G["target"]],
                         "id_form": "id", "scope_label": "", "condition": None},
                "the doors with IDs {door} and {target}"),
}


def _record(kind: str) -> dict:
    family, params, phrase = ANCHORS[kind]
    return {"kind": "set" if kind == "set_ids" else kind, "family": family,
            "params": dict(params), "phrase": phrase.format(**G),
            "expected": [G["target"]]}


class _Index:
    """A name index that knows only the class of each identifier."""

    CLASSES = {G["storey"]: "IfcBuildingStorey", G["a"]: "IfcWall",
               G["b"]: "IfcWall", G["wall2"]: "IfcWall",
               G["space"]: "IfcSpace", G["space_b"]: "IfcSpace",
               G["door"]: "IfcDoor", G["target"]: "IfcWindow"}

    def labels(self, guid):
        return ["Name of " + guid[:4]]

    def ifc_class(self, guid):
        return self.CLASSES.get(guid, "")

    def resolve(self, ifc_class, name):
        return []

    def storey(self, guid):
        return G["storey"]


@pytest.mark.parametrize("kind", sorted(ANCHORS))
@pytest.mark.parametrize("geom_lib", (True, False))
def test_a_reference_given_by_identifier_is_looked_up_by_identifier(kind,
                                                                    geom_lib):
    if not geom_lib and kind in LIBRARY_ONLY:
        pytest.skip("the hand-written style has no round for the v8 kinds")
    anchor = _record(kind)
    task = {"instruction": f"Delete {anchor['phrase']} from the model."}
    refs, reason = _anchor_refs(task, anchor, _Index())
    assert refs is not None, reason
    assert all(isinstance(ref, GuidRef) for ref in refs.values())
    code = resolve_round(anchor, Style.for_seed(11, geom_lib=geom_lib),
                         refs).code
    assert identifier_passed_as_name(code) == []
    assert "by_name(" not in code
    for key, ref in refs.items():
        assert f"ifc.by_guid('{ref.guid}')" in code or \
            f'ifc.by_guid("{ref.guid}")' in code
    # Every identifier the round writes is one the sentence carries.
    messages = [{"role": "assistant", "tool_calls": [
        {"function": {"arguments": {"code": code}}}]}]
    assert observed_identifiers_ok(messages, task["instruction"]) == []


def test_the_lookup_prints_what_the_identifier_resolved_to():
    anchor = _record("nearest")
    task = {"instruction": f"Delete {anchor['phrase']}."}
    refs, _ = _anchor_refs(task, anchor, _Index())
    code = resolve_round(anchor, Style.for_seed(2, geom_lib=True), refs).code
    lines = code.splitlines()
    for var in ("storey", "reference"):
        at = next(i for i, line in enumerate(lines)
                  if line.startswith(f"{var} = ifc.by_guid("))
        assert lines[at + 1] == (f"print('given ->', {var}.GlobalId, "
                                 f"{var}.is_a(), {var}.Name)")


def test_a_name_the_sentence_quotes_still_uses_the_name_lookup():
    """The by-name path is untouched where the sentence gives a name."""
    anchor = _record("nearest")
    anchor["phrase"] = "the window nearest to the wall named 'W-1' on storey 'L1'"
    task = {"instruction": f"Delete {anchor['phrase']}."}

    class Named(_Index):
        def labels(self, guid):
            return {G["a"]: ["W-1"], G["storey"]: ["L1"]}.get(guid, [])

        def resolve(self, ifc_class, name):
            return [g for g, names in ((G["a"], ["W-1"]), (G["storey"], ["L1"]))
                    if name in names]

    refs, _ = _anchor_refs(task, anchor, Named())
    assert all(isinstance(ref, Ref) for ref in refs.values())
    code = resolve_round(anchor, Style.for_seed(2, geom_lib=True), refs).code
    assert "by_name('IfcWall', 'W-1')" in code or \
        'by_name("IfcWall", "W-1")' in code
    assert identifier_passed_as_name(code) == []


def test_the_scanner_catches_an_identifier_passed_as_a_name():
    bad = "column = by_name('IfcColumn', '16lgaIqan5BeMYyMkTHdSc')"
    assert identifier_passed_as_name(bad) == ["16lgaIqan5BeMYyMkTHdSc"]
    also = "x = by_name_on_storey(\"IfcWall\", \"1DyCabcdefghij0123456_\", storey)"
    assert identifier_passed_as_name(also) == ["1DyCabcdefghij0123456_"]
    fine = "x = by_name('IfcWall', 'Basic Wall:Generic 200')"
    assert identifier_passed_as_name(fine) == []


def _trial_rows():
    rows = []
    for path in TRIALS:
        if path.exists():
            rows.extend(json.loads(line) for line in path.open(encoding="utf-8")
                        if line.strip())
    return rows


def test_no_trial_trajectory_looks_an_identifier_up_by_name():
    rows = _trial_rows()
    if not rows:
        pytest.skip("the v9 trial has not been synthesized")
    hits = [(row["task_id"], found) for row in rows
            for found in [trajectory_identifier_as_name(row)] if found]
    assert hits == [], hits[:5]


def test_every_identifier_reference_of_the_trial_is_a_by_guid_line():
    rows = _trial_rows()
    if not rows:
        pytest.skip("the v9 trial has not been synthesized")
    checked = 0
    for row in rows:
        instruction = row.get("instruction") or ""
        codes = [json.loads(c["function"]["arguments"])["code"]
                 if isinstance(c["function"]["arguments"], str)
                 else c["function"]["arguments"]["code"]
                 for m in row["messages"] if m["role"] == "assistant"
                 for c in m.get("tool_calls") or ()]
        if not codes:
            continue
        first = codes[0]
        for guid in re.findall(r"ifc\.by_guid\(['\"]([0-9A-Za-z_$]{22})['\"]\)",
                               first):
            assert guid in instruction or guid in "".join(
                m.get("content") or "" for m in row["messages"]
                if m["role"] in ("tool", "user"))
            checked += 1
    assert checked > 0
