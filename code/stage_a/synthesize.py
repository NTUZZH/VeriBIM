"""Gold-backed trajectories: plan, execute, verify, keep.

For one task the synthesizer plans a short conversation, runs every planned
snippet in the harness sandbox against a fresh copy of the source model, and
keeps the result only if four things hold:

1. every snippet ran without raising, and the sandbox stayed alive;
2. every identifier any round writes was either given in the instruction or
   printed by an earlier round, and where it came out of a listing of several
   candidates the trajectory shows which one it is, so the trajectory never uses
   knowledge it did not obtain and never makes a choice it cannot explain;
3. the trajectory called ``commit()``;
4. the file left on disk scores at or above the floor against the task's gold
   model, under the delete reading Stage A trains on.

The third and fourth are the behaviours the base models were shown to lack. The
second is what keeps the inspection rounds honest: a round that prints nothing
useful cannot pay for the identifier a later round then uses. It also decides
how the anchor itself is resolved. An instruction says "the wall nearest to the
column named 'X' on storey 'Y'", so the resolve round finds the storey and the
column by those names and prints what it found, instead of writing identifiers
only the generator knew. The name a parameter is looked up by comes from the
source model's name index, which is exact; a name two elements of one class
share is narrowed by the storey the instruction names, and a task whose
reference still cannot be told apart is refused.

Two task families answer to a different rule. An instruction that leaves out a
value the edit needs is answered by changing nothing and asking for it, so its
trajectory inspects, finds that the sentence could mean more than one thing,
calls no ``commit()`` and ends on the question; it is kept only when the file
comes back unchanged and the reply names the missing value. An instruction that
covers a whole set of elements is kept only when every member of the set changed
and nothing outside it did, which is the check the generator's own funnel runs
on the gold model.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from . import paths
from .goldcode import EmittedEdit, emit_edit, parse_gold_script
from .goldmodels import resolve_gold
from .inspection import (
    FAMILY_CLASS,
    KEY_VAR,
    GuidRef,
    Ref,
    Round,
    beside_wall_round,
    bounding_round,
    detail_round,
    filling_slot_round,
    host_round,
    hosted_round,
    materials_round,
    named_round,
    on_top_round,
    origin_offset_round,
    rehost_candidates_round,
    resolve_round,
    spaces_round,
    stated_lengths,
    storeys_round,
    storey_of_round,
    storey_round,
    type_objects_round,
    units_round,
    wall_box_round,
)
from .observed import (listing_choice_justified, names_in_code,
                       observed_identifiers_ok)
from .scoring import (
    Score,
    accepted,
    is_underspecified,
    reading_for,
    score_prediction,
    scorer_config_for,
)
from .style import Style
from .trajectory import Turn, replay, trajectory_record

GUID_IN_TEXT = re.compile(r"[0-9A-Za-z_$]{22}")

#: Short sentences an assistant turn may open with, by what the turn is doing.
LEAD_INS: dict[str, tuple[str, ...]] = {
    "resolve": (
        "First I need to find the element the instruction describes.",
        "Let me locate that element in the model.",
        "I will resolve the description to a single element.",
    ),
    "discover": (
        "Next I need the elements that go with it.",
        "Let me read the related elements before editing.",
        "I will list what depends on it first.",
    ),
    "detail": (
        "Let me read the target before changing it.",
        "I will check the element's class and position first.",
        "Reading the current state of the target.",
    ),
    "edit": (
        "Now I can apply the edit.",
        "Applying the change.",
        "This makes the change the instruction asks for.",
    ),
    "commit": (
        "Checking the result and saving the model.",
        "Now I verify the edit and commit.",
        "Confirming the change, then persisting it.",
    ),
    "list": (
        "Let me see what the model already holds.",
        "I will read the existing entries first.",
        "Checking what is already there.",
    ),
    "measure": (
        "Before I place anything I need the numbers off the model.",
        "Let me measure what the instruction refers to.",
        "I will read the sizes the placement depends on first.",
    ),
    "units": (
        "The file may not be written in the unit the instruction uses.",
        "Let me read the file's own length unit before I size anything.",
        "I will convert the stated sizes into the file's unit first.",
    ),
}

#: How the closing message describes the edit. ``{thing}`` is the element family
#: the task is about, so the sentence names what changed rather than "the element".
WHAT: dict[str, tuple[str, ...]] = {
    "create": ("the new {thing} is in the model",
               "the {thing} has been created and placed on its storey"),
    "update": ("the {thing} has been updated",
               "the {thing} now carries the values the instruction asked for"),
    "delete": ("the {thing} has been removed",
               "the {thing} and the relationships that depended on it are gone"),
}


def _what(task: dict, style: Style) -> str:
    thing = task.get("family") or "element"
    options = WHAT.get(task["operation"], ("the edit is done",))
    return style.choice(options).format(thing=thing)


@dataclass
class Attempt:
    """What happened to one task."""

    task_id: str
    stage: str = "planned"
    ok: bool = False
    reason: str = ""
    score: Optional[Score] = None
    record: Optional[dict] = None
    tool_rounds: int = 0
    commits: int = 0
    detail: dict[str, Any] = field(default_factory=dict)


def _lead_in(style: Style, key: str) -> str:
    if not style.chance(0.65):
        return ""
    return style.choice(LEAD_INS[key])


def _commit_snippet(task: dict, edit: EmittedEdit, style: Style) -> str:
    """A short check of the edit, then ``commit()``."""
    s = style
    lines: list[str] = []
    comment = s.comment("check")
    if comment:
        lines.append(comment.rstrip("\n"))
    operation = task["operation"]
    members, _pool = _batch_scope(task)
    if members:
        lines.extend(_batch_check_lines(task, s))
    elif operation == "delete" and edit.removed_guids:
        listed = ", ".join(s.string(g) for g in edit.removed_guids)
        lines.append(f"present = {{e.GlobalId for e in ifc.by_type('IfcProduct')}}")
        lines.append(
            f"print('still present:', [g for g in ({listed},) if g in present])"
            if len(edit.removed_guids) == 1
            else f"print('still present:', [g for g in ({listed}) if g in present])"
        )
    elif edit.created_vars:
        for variable in edit.created_vars:
            lines.append(
                f"print({variable}.GlobalId, {variable}.is_a(), {variable}.Name)"
            )
    elif edit.referenced_guids:
        guid = edit.referenced_guids[0]
        lines.append(f"{s.name('product')} = ifc.by_guid({s.string(guid)})")
        lines.append(
            f"print({s.name('product')}.is_a(), {s.name('product')}.GlobalId,"
            f" {s.name('product')}.Name)"
        )
    lines.append("")
    commit_comment = s.comment("commit")
    if commit_comment:
        lines.append(commit_comment.rstrip("\n"))
    lines.append("commit()")
    lines.append(f"print({s.string('model committed')})")
    return "\n".join(lines) + "\n"


def _anchor_is_named(anchor: dict, instruction: str) -> bool:
    """Whether the phrase the anchor stands for quotes a name the reader has.

    An anchor of kind ``name`` is resolved by matching that name in the model,
    so the name has to be one the instruction gives. The generator sometimes
    draws an anchor it never writes into the sentence, which leaves a lookup
    quoting a string no reader could produce.
    """
    name = (anchor.get("params") or {}).get("name")
    if not name:
        return True
    return _quoted_in(str(name), instruction)


def _unnamed_lookups(rounds: Sequence[Round], instruction: str) -> list[str]:
    """Names the planned lookup rounds match on that the instruction never gives.

    The rounds run before anything has been printed, so the instruction is the
    only place their names can come from. A round that matches on any other
    string is a round the model could not have written.
    """
    unknown: list[str] = []
    for item in rounds:
        for name in names_in_code(item.code):
            if name not in instruction and name not in unknown:
                unknown.append(name)
    return unknown


def _needs_discovery(task: dict, edit: EmittedEdit, anchor: dict) -> list[str]:
    """Identifiers the edit uses that neither the instruction nor the anchor gives."""
    known = set(anchor.get("expected") or [])
    known.update(GUID_IN_TEXT.findall(task.get("instruction") or task.get("prompt", "")))
    return [g for g in edit.referenced_guids if g not in known]


#: The anchor parameters that carry an identifier. Each of them points at an
#: element the instruction describes in words, so unless the instruction writes
#: the identifier itself the trajectory has to find the element by that name.
#: The storey comes first, because it is what tells two elements of one class
#: sharing a name apart.
ANCHOR_GUID_KEYS = ("storey_guid", "scope_guid", "guid", "space_guid",
                    "space_a_guid", "space_b_guid", "reference_guid",
                    "a_guid", "b_guid", "host_guid", "other_guid",
                    "door_guid", "element_guid", "element_b_guid")


def _quoted_in(name: str, instruction: str) -> bool:
    """Whether the instruction quotes this name.

    The quotes matter. A space called ``320`` appears inside any number that
    contains those digits, and only the quoted form is the instruction naming
    the element.
    """
    return f"'{name}'" in instruction or f'"{name}"' in instruction


def _anchor_refs(task: dict, anchor: dict,
                 index) -> tuple[Optional[dict], str]:
    """Per anchor parameter, the name lookup that pays for its identifier.

    An identifier the instruction writes out is used as it stands. Every other
    one is turned back into the name the instruction quotes, so the resolve
    round finds the element the way a reader has to. A name two elements of the
    class share is narrowed to the storey the instruction names; where that
    still leaves more than one, the task is refused rather than given a lookup
    that could land on the wrong element.
    """
    if index is None:
        return {}, ""
    instruction = task.get("instruction") or task.get("prompt", "")
    params = anchor.get("params") or {}
    refs: dict[str, Ref] = {}
    for key in ANCHOR_GUID_KEYS:
        guid = params.get(key)
        if not isinstance(guid, str) or len(guid) != 22:
            continue
        if guid in instruction:
            # An identifier the instruction writes out is looked up as one,
            # never by name: the target through the anchor's own round, and a
            # reference element through one ``ifc.by_guid`` line (0.9.0).
            if key != "guid":
                refs[key] = GuidRef(guid)
            continue
        label = next((name for name in index.labels(guid)
                      if _quoted_in(name, instruction)), None)
        if label is None:
            return None, "reference not named in the instruction"
        ifc_class = index.ifc_class(guid)
        if not ifc_class:
            return None, "reference not named in the instruction"
        if len(index.resolve(ifc_class, label)) == 1:
            refs[key] = Ref(ifc_class=ifc_class, name=label)
            continue
        storey = index.storey(guid)
        if ("storey_guid" in refs and storey
                and params.get("storey_guid") == storey
                and len(index.resolve_on_storey(ifc_class, label, storey)) == 1):
            refs[key] = Ref(ifc_class=ifc_class, name=label,
                            on_storey=KEY_VAR["storey_guid"])
            continue
        return None, "reference name not unique"
    return refs, ""


#: Which gold-call keyword an identifier came in through, which is what decides
#: the lookup that pays for it. A storey and a type object are named in the
#: instruction and have to be found in the model by that name; a wall a filling
#: moves into is one of the walls of the storey the filling already stands on.
_LOOKUP_BY_KEYWORD = ("storey_guid", "type_guid", "host_guid", "space_guid",
                      "related_guid", "relating_guid")

#: Names an instruction quotes, which is how a connection or a boundary reaches
#: the element at its other end. A quote mark between two letters is a
#: possessive rather than the end of a name, and reading it as one pairs the
#: apostrophe in "that storey's own coordinates" with the next name's opening
#: quote and loses that name.
QUOTED_NAME = re.compile(r"(?<![A-Za-z])'([^']{2,}?)'(?![A-Za-z])")


def _keyword_of(calls: Sequence[Any], guid: str) -> Optional[tuple[str, str, dict]]:
    """The call and the keyword one identifier reaches the edit through."""
    for call in calls:
        for key in _LOOKUP_BY_KEYWORD:
            if call.kwargs.get(key) == guid:
                return call.func, key, call.kwargs
    return None


def _storey_referent(task: dict, anchor: dict, storey_guid: str,
                     index) -> Optional[str]:
    """The element an instruction gives the target storey through, if it does.

    "on storey 'Level 2'" names the storey, and a listing of the storeys is
    enough to find it. "on the storey that contains the column named 'X'" names
    no storey at all, so a listing shows the reader every storey and nothing
    about which one is meant; the storey has to be read off the column instead.
    The two are told apart by whether the storey's own name is quoted in the
    instruction, and the element is accepted only when the model puts it on that
    storey and the instruction names it.
    """
    if index is None or not storey_guid:
        return None
    instruction = task.get("instruction") or task.get("prompt", "")
    if any(_quoted_in(name, instruction) for name in index.labels(storey_guid)):
        return None
    target = (anchor.get("expected") or [None])[0]
    if not target or index.storey(target) != storey_guid:
        return None
    if target not in instruction and not any(
            _quoted_in(name, instruction) for name in index.labels(target)):
        return None
    return target


#: Classes a wall carries through the openings cut in it. One listing of those
#: openings pays for every identifier of that kind the edit then uses.
CARRIED_CLASSES = {"IfcDoor", "IfcWindow", "IfcOpeningElement"}


def _group_round(task: dict, anchor: dict, unexplained: Sequence[str],
                 index, style: Style) -> Optional[list[Round]]:
    """The round that pays for identifiers the edit reaches through its target.

    Three shapes account for all of them. A wall that is deleted takes its
    doors and windows with it, and one listing of what the wall hosts names
    them. A door or a window that is moved is moved by its opening, which is
    read off the element itself. A space that is moved takes the walls that
    bound it, and one listing of its boundaries names those.
    """
    target = (anchor.get("expected") or [None])[0]
    if target is None:
        return None
    if index is None:
        # Without an index the old reading stands: a deletion carries what the
        # target hosts, and anything else carries what bounds it.
        return [hosted_round(target, style) if task["operation"] == "delete"
                else bounding_round(target, style)]
    classes = {index.ifc_class(guid) for guid in unexplained}
    family = anchor.get("family") or task.get("family") or ""
    if classes and classes <= CARRIED_CLASSES:
        if classes == {"IfcOpeningElement"} and family in ("door", "window"):
            return [host_round(target, style)]
        return [hosted_round(target, style)]
    instruction = task.get("instruction") or task.get("prompt", "")
    labels: list[str] = []
    for guid in unexplained:
        label = next((name for name in index.labels(guid)
                      if _quoted_in(name, instruction)), None)
        if label is None:
            labels = []
            break
        if label not in labels:
            labels.append(label)
    if labels:
        return [named_round(labels, style)]
    return [bounding_round(target, style)]


def _discovery_rounds(task: dict, edit: EmittedEdit, anchor: dict,
                      missing: Sequence[str], style: Style,
                      index=None) -> Optional[list[Round]]:
    """The rounds that produce the identifiers the edit still needs.

    One round per lookup, not per identifier: a create and a move both name a
    storey in words and one listing of the storeys pays for both. A lookup that
    no round can supply returns ``None``, and the task is refused rather than
    given an edit that uses an identifier it never read.
    """
    calls = task["_calls"]
    rounds: list[Round] = []
    seen: set[str] = set()
    unexplained: list[str] = []

    for guid in missing:
        found = _keyword_of(calls, guid)
        if found is None:
            unexplained.append(guid)
            continue
        func, key, kwargs = found
        if key == "storey_guid":
            referent = _storey_referent(task, anchor, guid, index)
            if referent is None:
                name = "storeys"
                builder = lambda: storeys_round(style)
            else:
                name = f"storey_of:{referent}"
                builder = lambda referent=referent: storey_of_round(referent, style)
        elif key == "type_guid":
            name = "types"
            builder = lambda: type_objects_round(task.get("family", ""), style)
        elif func == "rehost_filling":
            name = f"rehost:{kwargs['guid']}"
            builder = lambda: rehost_candidates_round(kwargs["guid"], style)
        elif func == "replace_filling":
            # The wall is the one the element being replaced already stands in,
            # so it is read off that element rather than named.
            name = f"host:{kwargs['guid']}"
            builder = lambda: host_round(kwargs["guid"], style)
        elif key == "space_guid":
            name = "spaces"
            builder = lambda: spaces_round(style)
        elif func == "connect_elements":
            quoted = QUOTED_NAME.findall(
                task.get("instruction") or task.get("prompt", ""))
            if not quoted:
                unexplained.append(guid)
                continue
            name = "named"
            builder = lambda: named_round(quoted, style)
        else:
            unexplained.append(guid)
            continue
        if name not in seen:
            seen.add(name)
            rounds.append(builder())

    if unexplained:
        extra = _group_round(task, anchor, unexplained, index, style)
        if extra is None:
            return None
        rounds.extend(extra)
    return rounds or None


def _batch_scope(task: dict) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """The elements the instruction's set phrase covers, and the pool it was drawn from."""
    params = task.get("edit_params") or {}
    members = tuple(params.get("batch_members") or ())
    pool = tuple(dict.fromkeys(tuple(params.get("batch_pool") or ()) + members))
    return members, pool


def _batch_check_lines(task: dict, style: Style) -> list[str]:
    """Read back that the whole set changed, and how much of its class is left.

    The set is named by its members, which the resolve round printed. The
    elements outside it are counted rather than listed: the instruction never
    named them, so writing their identifiers would be knowledge the trajectory
    did not obtain, and the count of the class still in the model is what a
    reader can check. Whether anything outside the set moved is settled against
    the gold model by the scope check the synthesizer runs on the file.
    """
    s = style
    members, _pool = _batch_scope(task)
    family = (task.get("anchor") or {}).get("family") or task.get("family") or ""
    ifc_class = FAMILY_CLASS.get(family, "IfcProduct")
    lines: list[str] = []
    if s.comments:
        lines.append("# every element the phrase covers, and what is left of its class")
    lines.append(f"{s.name('members')} = ({', '.join(s.string(g) for g in members)},)")
    lines.append("present = {e.GlobalId for e in ifc.by_type('IfcProduct')}")
    lines.append(f"print('the phrase covers', len({s.name('members')}), 'element(s)')")
    if task["operation"] == "delete":
        lines.append(f"print('members still in the model:',"
                     f" [g for g in {s.name('members')} if g in present])")
        lines.append(f"print({s.string(ifc_class)}, 'left in the model:',"
                     f" len(ifc.by_type({s.string(ifc_class)})))")
    else:
        lines.append(f"for target_guid in {s.name('members')}:")
        lines.append(f"    {s.name('product')} = ifc.by_guid(target_guid)")
        lines.append(f"    print(' edited', target_guid, {s.name('product')}.is_a(),"
                     f" {s.name('product')}.Name)")
        lines.append(f"print({s.string(ifc_class)}, 'in the model:',"
                     f" len(ifc.by_type({s.string(ifc_class)})))")
    return lines


#: The extra reading one family's edit asks for before it is written: a material
#: is named rather than identified, so the names already in the model are what
#: tell the reader whether the instruction names a new one.
def _family_round(task: dict, style: Style) -> Optional[Round]:
    """A lookup one edit kind needs beyond resolving its target."""
    if task.get("edit_kind") == "assign_material":
        return materials_round(style)
    return None


#: The geometry helper is bound in the sandbox as ``geom``. A create-type edit
#: is written as calls into it unless this is turned off, which is what the
#: ``--no-geom-lib`` flag does.
GEOM_LIB_DEFAULT = os.environ.get("VERIBIM_STAGE_A_GEOM", "1").lower() not in (
    "0", "false", "no", "off")


def _measure_rounds(task: dict, style: Style) -> list[Round]:
    """The rounds that read the numbers a create edit places its element by.

    A filling is cut into a wall, so the wall is measured first and its length,
    thickness, height and base go into the transcript. A replacement reads the
    slot the old element already holds. A box whose corner the instruction gives
    relative to another element has that element read as well, in the frame the
    corner is written in. Every round names an element the instruction named or
    an earlier round printed, and none of them changes the model.
    """
    if not style.geom_lib:
        return []
    params = task.get("edit_params") or {}
    placement = params.get("placement") or {}
    kind = placement.get("kind")
    offset = params.get("offset") or {}
    created: set[str] = set()
    rounds: list[Round] = []
    for call in task["_calls"]:
        kw = call.kwargs
        if call.func == "add_filling":
            host = kw.get("host_guid")
            if host and host not in created:
                rounds.append(wall_box_round(host, style))
        elif call.func == "replace_filling":
            rounds.append(filling_slot_round(kw["guid"], style))
        elif call.func == "add_box_element" and offset.get("reference_guid"):
            reference = offset["reference_guid"]
            if reference not in created:
                rounds.append(origin_offset_round(reference, kw["storey_guid"],
                                                  style))
        elif call.func == "add_box_element_world" and kind == "on_top_of":
            reference = (placement.get("anchor_guid")
                         or (placement.get("refs") or [None])[0])
            if reference and reference not in created:
                rounds.append(on_top_round(reference, style))
        elif call.func == "add_box_element_world" and kind == "adjacent_to_space":
            wall = placement.get("anchor_guid")
            others = [g for g in (placement.get("refs") or ()) if g != wall]
            if wall and others and wall not in created:
                rounds.append(beside_wall_round(wall, others[0], kw["length"],
                                                kw["width"], style))
        key = _CREATED_KEY.get(call.func)
        if key == "new_guids":
            created.update(kw.get(key) or ())
        elif key is not None and kw.get(key):
            created.add(kw[key])
    return rounds


#: Which keyword of a gold call names an entity the edit itself creates. A
#: measuring round is written only for an element that is already in the model,
#: since one the edit is about to create cannot be read yet.
_CREATED_KEY = {
    "add_box_element": "guid", "add_box_element_world": "guid",
    "add_box_element_world_turned": "guid", "add_wall_span": "guid",
    "add_filling": "guid", "copy_element": "new_guid",
    "replace_filling": "new_guid", "array_elements": "new_guids",
}


def _units_round(task: dict, style: Style,
                 edit: Optional[EmittedEdit] = None) -> Optional[Round]:
    """Read the file's own length unit when the instruction quotes another one.

    An instruction on a file written in millimetres may state its lengths in
    metres, and one on a file written in metres may state them in millimetres,
    so the conversion is done against the unit the file declares. Under the
    library style the round lists the lengths the edit writes and the
    instruction quotes; the numbers the generator derived from the sentence are
    left to the round that measures them.
    """
    wording = task.get("wording") or {}
    conditions = task.get("model_conditions") or {}
    unit = wording.get("unit") or "m"
    file_unit = conditions.get("length_unit") or "m"
    if unit == file_unit and unit == "m":
        return None
    if not stated_lengths(task["_calls"], unit):
        # The edit states no length, so there is nothing to convert.
        return None
    code = edit.code if (style.geom_lib and edit is not None) else ""
    return units_round(task["_calls"], unit, wording.get("unit_word") or unit,
                       style, code=code,
                       instruction=task.get("instruction") or task.get("prompt", ""))


def plan_clarification(task: dict, style: Style) -> tuple[list[Turn], list[Round],
                                                          EmittedEdit]:
    """The trajectory for an instruction that leaves out a value the edit needs.

    The right answer changes nothing, so the plan holds inspection rounds and a
    closing message and no edit at all. The rounds show what makes the sentence
    ambiguous: the model holds several elements of the family the instruction
    names, or several storeys, so the reader cannot tell which one is meant and
    asks instead of guessing.
    """
    clarification = task.get("clarification") or {}
    slot = clarification.get("slot")
    family = (task.get("anchor") or {}).get("family") or task.get("family") or "wall"
    ifc_class = FAMILY_CLASS.get(family, "IfcBuildingElement")
    s = style

    if slot == "storey":
        rounds = [storeys_round(s)]
    else:
        lines: list[str] = []
        if s.comments:
            lines.append("# which element the instruction means is not stated")
        lines.append(f"{s.name('candidates')} = ifc.by_type({s.string(ifc_class)})")
        lines.append(f"print(len({s.name('candidates')}),"
                     f" {s.string(ifc_class)}, 'in the model')")
        lines.append(f"for {s.name('product')} in {s.name('candidates')}[:20]:")
        lines.append(f"    print(' ', {s.name('product')}.GlobalId,"
                     f" {s.name('product')}.Name)")
        rounds = [Round(code="\n".join(lines) + "\n",
                        purpose="count the elements the instruction could mean")]

    turns = [Turn(code=r.code, content=_lead_in(s, "resolve"), purpose=r.purpose)
             for r in rounds]
    turns.append(Turn(code=None, content=task["expected_reply"], purpose="ask"))
    return turns, rounds, EmittedEdit(code="")


def plan(task: dict, style: Style, index=None,
         notes: Optional[dict] = None) -> tuple[list[Turn], list[Round], EmittedEdit]:
    """The turns of one trajectory, before any of them has been executed.

    ``index`` is the source model's name index, which is what turns an anchor
    parameter the instruction gives in words back into that name. Without one
    the planner falls back to writing the identifier as a literal, and the
    check after execution is what then refuses the trajectory. ``notes`` takes
    the reason a plan was refused, since an empty plan on its own does not say
    which lookup was missing.
    """
    calls = parse_gold_script(task["gold_script"])
    task["_calls"] = calls
    if is_underspecified(task):
        return plan_clarification(task, style)
    instruction = task.get("instruction") or task.get("prompt", "")
    edit = emit_edit(calls, style, task.get("edit_params"), instruction)
    anchor = task.get("anchor") or {"kind": "guid", "family": "wall",
                                    "params": {}, "expected": []}
    refs, reason = _anchor_refs(task, anchor, index)
    if refs is None:
        if notes is not None:
            notes["reason"] = reason
        return [], [], edit
    missing = _needs_discovery(task, edit, anchor)
    # An anchor the instruction never names cannot be resolved by a reader. Where
    # the edit needs the element it stands for, the task is refused; where it
    # does not, as in a wall raised on a storey the instruction names, the
    # resolve round is dropped and the rounds that find what the edit does need
    # stand on their own.
    drop_anchor = not _anchor_is_named(anchor, instruction)
    if drop_anchor:
        expected = set(anchor.get("expected") or ())
        if expected & set(edit.referenced_guids) or not missing:
            if notes is not None:
                notes["reason"] = "the anchor's name is not in the instruction"
            return [], [], edit
        if notes is not None:
            notes["anchor_dropped"] = True
    category = task.get("category", "direct")
    budget = 1 if category == "direct" else 2
    # A target the instruction does not write out has to be resolved in the
    # model before any later round can name it, whatever the round budget says.
    must_resolve = (not drop_anchor) and (bool(refs) or not all(
        guid in instruction for guid in (anchor.get("expected") or ())))

    rounds: list[Round] = []
    keys: list[str] = []
    if missing:
        discovery = _discovery_rounds(task, edit, anchor, missing, style, index)
        if discovery is None:
            if notes is not None:
                notes["reason"] = ("no inspection round can supply the edit's"
                                   " identifiers")
            return [], [], edit
        if (budget >= 2 or must_resolve) and not drop_anchor:
            rounds.append(resolve_round(anchor, style, refs))
            keys.append("resolve")
        rounds.extend(discovery)
        keys.extend(["discover"] * len(discovery))
    else:
        wanted = budget if style.chance(0.6 if budget == 2 else 0.7) else budget - 1
        wanted = max(1 if must_resolve else 0, min(budget, wanted))
        if wanted >= 1 and not drop_anchor:
            rounds.append(resolve_round(anchor, style, refs))
            keys.append("resolve")
        if wanted >= 2:
            target = tuple(anchor.get("expected") or ())
            if task["operation"] == "create":
                storey = next((c.kwargs.get("storey_guid") for c in calls
                               if c.func in ("add_box_element",
                                             "add_box_element_world",
                                             "add_wall_span")), None)
                rounds.append(storey_round(task, storey, style) if storey
                              else detail_round(task, target, style))
            else:
                rounds.append(detail_round(task, target, style))
            keys.append("detail")

    extra = _family_round(task, style)
    if extra is not None:
        rounds.append(extra)
        keys.append("list")
    unit_check = _units_round(task, style, edit)
    if unit_check is not None:
        rounds.append(unit_check)
        keys.append("units")
    for measured in _measure_rounds(task, style):
        rounds.append(measured)
        keys.append("measure")

    # Nothing a lookup matches on may be a string the instruction withholds,
    # whichever round wrote it.
    unnamed = _unnamed_lookups(rounds, instruction)
    if unnamed:
        if notes is not None:
            notes["reason"] = ("a lookup quotes a name the instruction does not"
                               f" give: {unnamed[0]!r}")
        return [], [], edit

    turns = [Turn(code=r.code, content=_lead_in(style, k), purpose=r.purpose)
             for r, k in zip(rounds, keys)]
    turns.append(Turn(code=edit.code, content=_lead_in(style, "edit"), purpose="edit"))
    turns.append(Turn(code=_commit_snippet(task, edit, style),
                      content=_lead_in(style, "commit"), purpose="commit"))
    turns.append(Turn(code=None, content=style.closing(_what(task, style)),
                      purpose="close"))
    return turns, rounds, edit


def _batch_scope_check(task: dict, source: Path, predicted: Path) -> dict:
    """The generator's fifth funnel check, run on the trajectory's own output.

    Every element the set was drawn from is compared between the source model
    and the file the trajectory left behind. A member has to differ and a
    non-member has to be identical, which is what makes the instruction's word
    "all" true of the file rather than of the plan.
    """
    from modifc_gen.verify import check_batch_scope

    members, pool = _batch_scope(task)
    result = check_batch_scope(str(source), str(predicted), members, pool)
    return {"ok": bool(result.ok), "reason": result.reason or "",
            "detail": result.detail, "n_members": len(members),
            "n_pool": len(pool)}


def synthesize_one(task: dict, scratch: Path, project_root: Path,
                   floor: float = 0.98, require_axes: bool = True,
                   keep_model: Optional[Path] = None,
                   style_salt: int = 0, gold_cache=None,
                   name_index=None, geom_lib: Optional[bool] = None) -> Attempt:
    """Plan, replay, score and judge one task."""
    task_id = task["task_id"]
    seed = int((task.get("seeds") or {}).get("task_seed", 0)) + style_salt
    style = Style.for_seed(seed, geom_lib=GEOM_LIB_DEFAULT if geom_lib is None
                           else geom_lib)
    attempt = Attempt(task_id=task_id)
    clarify_task = is_underspecified(task)
    reading = reading_for(task)
    attempt.detail["reading"] = reading

    notes: dict[str, str] = {}
    try:
        turns, rounds, edit = plan(task, style, name_index, notes)
    except Exception as exc:  # noqa: BLE001
        attempt.stage, attempt.reason = "plan", f"{type(exc).__name__}: {exc}"[:200]
        return attempt
    if not turns:
        attempt.stage = "plan"
        attempt.reason = notes.get(
            "reason", "no inspection round can supply the edit's identifiers")
        return attempt

    attempt.stage = "replayed"
    # A deterministic working directory, not a temporary one: the path is shown
    # to the model in the user turn exactly as the evaluation harness shows it,
    # so a random suffix would put an unreproducible string in the training data.
    work_dir = Path(scratch) / task_id
    shutil.rmtree(work_dir, ignore_errors=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    working = work_dir / f"{Path(task['input_ifc']).stem}.ifc"
    log_file = work_dir / "sandbox.log"
    try:
        result = replay(
            turns=turns,
            input_ifc=project_root / task["input_ifc"],
            working_ifc=working,
            log_file=log_file,
            instruction=task.get("instruction") or task["prompt"],
        )
        attempt.tool_rounds = result.tool_rounds
        attempt.commits = result.commits
        if not result.ok:
            attempt.reason = result.failure
            if result.failure == "snippet_raised" and result.outputs:
                attempt.detail["traceback_tail"] = result.outputs[-1][-600:]
            return attempt
        if clarify_task:
            # The answer to an instruction that leaves a value out is to change
            # nothing, so a commit here is the failure rather than the proof.
            if result.commits:
                attempt.reason = "committed an edit to an under-specified task"
                return attempt
        elif result.commits < 1:
            attempt.reason = "no commit"
            return attempt

        seen = "\n".join(result.outputs)
        instruction = task.get("instruction") or task["prompt"]
        # The whole conversation, not the edit alone. Every round's code may use
        # only the identifiers the instruction carried and the earlier rounds
        # printed, which is the rule the model has to work under at evaluation
        # time; a resolve round that writes one it was never shown teaches the
        # model to invent identifiers.
        unresolved = observed_identifiers_ok(result.messages, instruction)
        if unresolved:
            attempt.reason = "identifier never observed"
            attempt.detail["unresolved"] = unresolved[:3]
            return attempt
        # Having seen an identifier is not the same as having a reason for it.
        # A round that lists every storey in the building and an edit that then
        # takes one of them leaves the choice unexplained, and a model copying
        # the trajectory picks a storey at random.
        unreadable = listing_choice_justified(result.messages, instruction)
        if unreadable:
            attempt.reason = "listing choice not justified"
            attempt.detail["unjustified"] = unreadable[:3]
            return attempt
        anchor_expected = tuple((task.get("anchor") or {}).get("expected") or ())
        if (not clarify_task and rounds and rounds[0].expect_guids
                and not notes.get("anchor_dropped")):
            missing_anchor = [g for g in anchor_expected if g not in seen]
            if missing_anchor:
                attempt.reason = "anchor round did not resolve the anchor"
                attempt.detail["missing_anchor"] = missing_anchor[:5]
                return attempt

        attempt.stage = "scored"
        gold = resolve_gold(task, gold_cache, project_root)
        if gold is None:
            attempt.reason = "gold model could not be rebuilt from its script"
            return attempt
        # The reply is the trajectory's closing message, which is half the answer
        # for an under-specified task and is ignored for every other one.
        reply = next((m.get("content", "") for m in reversed(result.messages)
                      if m.get("role") == "assistant" and not m.get("tool_calls")), "")
        score = score_prediction(task, working, project_root, gold_path=gold,
                                 config=scorer_config_for(task), reply=reply)
        attempt.score = score
        if not accepted(score, floor=floor, require_axes=require_axes):
            attempt.reason = (score.error or
                              ("the file changed or the reply did not ask for the"
                               " missing value" if clarify_task else
                               f"score below floor (final {score.final:.4f},"
                               f" min axis {score.min_axis:.4f})"))
            return attempt

        members, _pool = _batch_scope(task)
        batch = None
        if members:
            batch = _batch_scope_check(task, project_root / task["input_ifc"],
                                       working)
            attempt.detail["batch"] = batch
            if not batch["ok"]:
                attempt.reason = f"batch scope: {batch['reason']}"
                return attempt

        attempt.stage = "accepted"
        attempt.ok = True
        attempt.record = trajectory_record(
            task=task,
            messages=result.messages,
            loss_on=result.loss_on,
            source="gold",
            score=score,
            extra={
                "style_seed": seed,
                "style": {"quote": style.quote, "report": style.report,
                          "comments": style.comments,
                          "geom_lib": style.geom_lib},
                "purposes": [t.purpose for t in turns],
                "commits": result.commits,
                "target": task.get("target") or {},
                "scorer_reading": reading,
                "batch_scope": batch,
                "answer": "clarify" if clarify_task else "edit",
                "generator": ("stage-a-synth/0.3.0" if style.geom_lib
                              else "stage-a-synth/0.2.0"),
            },
        )
        if keep_model is not None:
            keep_model.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(working, keep_model)
        return attempt
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
