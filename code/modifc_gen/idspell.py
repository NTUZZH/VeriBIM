"""Layer 7: how an instruction writes an element identifier.

People write a GlobalId in many ways.  One writes "the wall with GlobalId
'X'", another "wall ID X", "the door (ID: X)", "column X" or "the slab with
GUID X".  A person who knows the identifiers also tends to name every element
of the sentence by identifier, the reference elements included: "the window
nearest to column X", "the door between rooms A and B".  Every earlier version
wrote one spelling, quoted and after the word GlobalId, and named a reference
element by its name, so a model trained on it read an unquoted identifier after
the word ID as a name.

This module rewrites the reference phrase of a finished instruction.  It
changes how an identifier is spelled and, in a drawn share of instructions,
names the reference elements by identifier instead of by name.  The anchor's
parameters are not touched, so the predicate the phrase stands for and the
element it resolves to stay the same, and the gold script is not affected.

The rewrite runs on a phrase and a table of what the phrase's identifiers
belong to.  The table is read from the scene while a task is generated and
from the source model's name index when an existing task is reworded, so one
function serves both.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Sequence

#: An IFC GlobalId: exactly 22 characters of this alphabet.
GUID_CHARS = r"[0-9A-Za-z_$]{22}"

#: How one identifier is written, singular and for a list of several.  ``{n}``
#: is the noun (wall, IfcWall, room, storey), ``{p}`` its plural and ``{g}``
#: the identifier; ``{l}`` is a list "A and B" or "A, B and C" and ``{q}`` the
#: same list with each identifier quoted.  The first form is the one every
#: earlier corpus version wrote.
FORMS: dict[str, tuple[str, str]] = {
    "globalid_quoted": ("the {n} with GlobalId '{g}'", "the {p} with GlobalIds {q}"),
    "globalid": ("the {n} with GlobalId {g}", "the {p} with GlobalIds {l}"),
    "id": ("the {n} with ID {g}", "the {p} with IDs {l}"),
    "id_quoted": ("the {n} with ID '{g}'", "the {p} with IDs {q}"),
    "the_id": ("the {n} with the ID {g}", "the {p} with the IDs {l}"),
    "id_colon": ("the {n} (ID: {g})", "the {p} (IDs: {l})"),
    "noun_id": ("{n} ID {g}", "{p} with IDs {l}"),
    "guid": ("the {n} with GUID {g}", "the {p} with GUIDs {l}"),
    "identified_as": ("the {n} identified as {g}", "the {p} identified as {l}"),
    "bare": ("{n} {g}", "{p} {l}"),
    "the_bare": ("the {n} {g}", "the {p} {l}"),
    "whose_globalid": ("the {n} whose GlobalId is {g}",
                       "the {p} whose GlobalIds are {l}"),
}

#: How often each form is drawn.  The form the corpus already carries keeps
#: 0.40, so what the model has learned is not lost, and the rest is shared out
#: with the plain word ID ahead of the rarer spellings.
WEIGHTS: dict[str, float] = {
    "globalid_quoted": 0.40,
    "id": 0.10,
    "bare": 0.08,
    "noun_id": 0.06,
    "globalid": 0.06,
    "id_colon": 0.05,
    "guid": 0.05,
    "id_quoted": 0.04,
    "the_id": 0.04,
    "identified_as": 0.04,
    "the_bare": 0.04,
    "whose_globalid": 0.04,
}

CURRENT_FORM = "globalid_quoted"

#: The share of instructions whose reference elements are named by identifier.
REFERENCE_SHARE = 0.40

#: The share of those in which a storey the phrase names is given by identifier
#: as well.  A storey is usually named by its level name in a work order, so the
#: share is lower than for elements; an anchor whose only reference is a storey
#: uses ``REFERENCE_SHARE`` instead, so that such anchors get the pattern too.
STOREY_SHARE = 0.50

#: How often a room is called a room rather than a space once it is named by
#: identifier.
ROOM_SHARE = 0.35

#: How often two identifiers of one noun that stand side by side ("the space A
#: and the space B") are written as one list ("the spaces with IDs A and B").
MERGE_SHARE = 0.70

PLURAL = {"wall": "walls", "slab": "slabs", "space": "spaces", "room": "rooms",
          "door": "doors", "window": "windows", "column": "columns",
          "storey": "storeys"}

FAMILY_NOUNS = ("wall", "slab", "space", "door", "window", "column")

#: The anchor parameters that name an element other than the target, in the
#: order a phrase names them.
REFERENCE_KEYS = ("reference_guid", "a_guid", "b_guid", "host_guid",
                  "other_guid", "door_guid", "element_guid", "element_b_guid",
                  "space_guid", "space_a_guid", "space_b_guid", "scope_guid",
                  "storey_guid")


def plural(noun: str) -> str:
    if noun.startswith("Ifc"):
        return f"{noun} elements"
    return PLURAL.get(noun, noun + "s")


def _join(items: Sequence[str]) -> str:
    items = list(items)
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def spell(form: str, noun: str, guid: str) -> str:
    """One identifier, written in one form."""
    return FORMS[form][0].format(n=noun, g=guid)


def spell_list(form: str, noun: str, guids: Sequence[str]) -> str:
    """Several identifiers of one noun, written as one list."""
    return FORMS[form][1].format(p=plural(noun), l=_join(guids),
                                 q=_join([f"'{g}'" for g in guids]))


def draw_form(rng) -> str:
    """One spelling, in proportion to the weights."""
    point = rng.random() * sum(WEIGHTS.values())
    for form in sorted(WEIGHTS):
        point -= WEIGHTS[form]
        if point <= 0:
            return form
    return CURRENT_FORM


# ------------------------------------------------------------ the lookup side


@dataclass
class Lookup:
    """What the rewrite needs to know about the elements a phrase names.

    ``family`` gives an identifier's family (wall, door, space, storey, ...),
    ``labels`` the names and long names it carries, and ``resolve`` the
    identifiers of one family carrying one name.  A scene and a name index both
    supply these, which is what lets one rewrite serve generation and
    rewording.
    """

    family: Callable[[str], Optional[str]]
    labels: Callable[[str], Sequence[str]]
    resolve: Callable[[str, str], Sequence[str]]


def scene_lookup(scene) -> Lookup:
    def family(guid: str) -> Optional[str]:
        element = scene.by_guid(guid)
        return scene.family_of(element) if element is not None else None

    def labels(guid: str) -> list[str]:
        element = scene.by_guid(guid)
        if element is None:
            return []
        out = [(element.Name or "").strip(),
               (getattr(element, "LongName", None) or "").strip()]
        return [label for label in out if label]

    def resolve(family_name: str, label: str) -> list[str]:
        out = []
        for element in scene.elements(family_name):
            names = ((element.Name or "").strip(),
                     (getattr(element, "LongName", None) or "").strip())
            if label in names:
                out.append(element.GlobalId)
        return out

    return Lookup(family=family, labels=labels, resolve=resolve)


CLASS_FAMILY = {"IfcWall": "wall", "IfcSlab": "slab", "IfcSpace": "space",
                "IfcDoor": "door", "IfcWindow": "window",
                "IfcColumn": "column", "IfcBuildingStorey": "storey"}
FAMILY_CLASS = {family: cls for cls, family in CLASS_FAMILY.items()}


def index_lookup(index) -> Lookup:
    """The same table read from a source model's name index."""
    def family(guid: str) -> Optional[str]:
        return CLASS_FAMILY.get(index.ifc_class(guid) or "")

    def labels(guid: str) -> list[str]:
        return [label for label in index.labels(guid) if label]

    def resolve(family_name: str, label: str) -> list[str]:
        cls = FAMILY_CLASS.get(family_name)
        return list(index.resolve(cls, label)) if cls else []

    return Lookup(family=family, labels=labels, resolve=resolve)


# ------------------------------------------------------------- the mentions


@dataclass
class Mention:
    """One place in a phrase that names an element."""

    start: int
    end: int
    guid: str
    noun: str
    #: ``target`` for the element the phrase is about, ``identifier`` for a
    #: reference the phrase already gives by identifier, ``name`` for one it
    #: gives by name, ``storey`` for a storey given by its label.
    how: str
    key: str = ""


_NOUN = r"(wall|slab|space|door|window|column|storey|Ifc[A-Za-z]+)"
R_GLOBALID = re.compile(rf"the {_NOUN} with GlobalId '({GUID_CHARS})'")
R_NAMED = re.compile(rf"the {_NOUN} named '([^']+)'")
R_SPACE = re.compile(r"the space '([^']+)'")
R_STOREY = re.compile(r"(?:the )?storey '([^']+)'|the storey at elevation "
                      r"-?[0-9]+(?:\.[0-9]+)? m")


def _overlaps(mentions: Sequence[Mention], start: int, end: int) -> bool:
    return any(m.start < end and start < m.end for m in mentions)


def find_mentions(phrase: str, params: dict, lookup: Lookup,
                  target_guid: str = "") -> list[Mention]:
    """Every element the phrase names, with the identifier it belongs to.

    A name is tied to an identifier only when exactly one of the anchor's
    reference parameters carries that name and that family; a name the table
    cannot tie is left as it stands, so the rewrite never guesses.
    """
    mentions: list[Mention] = []
    for match in R_GLOBALID.finditer(phrase):
        guid = match.group(2)
        how = "target" if guid == target_guid else "identifier"
        mentions.append(Mention(match.start(), match.end(), guid,
                                match.group(1), how))
    refs = [(key, params[key]) for key in REFERENCE_KEYS
            if isinstance(params.get(key), str) and len(params[key]) == 22]
    families = {guid: lookup.family(guid) for _key, guid in refs}

    def tie(family_names: Sequence[str], label: str) -> Optional[tuple[str, str]]:
        hits = [(key, guid) for key, guid in refs
                if families.get(guid) in family_names
                and label in lookup.labels(guid)]
        unique = {guid for _key, guid in hits}
        return hits[0] if len(unique) == 1 else None

    for match in R_NAMED.finditer(phrase):
        if _overlaps(mentions, match.start(), match.end()):
            continue
        noun = match.group(1)
        family = CLASS_FAMILY.get(noun, noun)
        tied = tie((family,), match.group(2))
        if tied is None:
            continue
        mentions.append(Mention(match.start(), match.end(), tied[1], noun,
                                "name", tied[0]))
    for match in R_SPACE.finditer(phrase):
        if _overlaps(mentions, match.start(), match.end()):
            continue
        tied = tie(("space",), match.group(1))
        if tied is None:
            continue
        mentions.append(Mention(match.start(), match.end(), tied[1], "space",
                                "name", tied[0]))
    storey_guid = params.get("storey_guid") or (
        params.get("scope_guid") if params.get("scope") == "storey" else None)
    if isinstance(storey_guid, str) and len(storey_guid) == 22:
        for match in R_STOREY.finditer(phrase):
            if _overlaps(mentions, match.start(), match.end()):
                continue
            label = match.group(1)
            if label is not None and label not in lookup.labels(storey_guid):
                continue
            key = "storey_guid" if params.get("storey_guid") else "scope_guid"
            mentions.append(Mention(match.start(), match.end(), storey_guid,
                                    "storey", "storey", key))
            break
    mentions.sort(key=lambda m: m.start)
    return mentions


# --------------------------------------------------------------- the rewrite


@dataclass
class Rewrite:
    """What one rewrite did, as the task record carries it."""

    phrase: str
    form: str
    by_id: list[str] = field(default_factory=list)
    respelled: int = 0
    merged: int = 0
    room: bool = False
    storeys_switched: bool = False

    @property
    def changed(self) -> bool:
        return self.form != CURRENT_FORM or bool(self.by_id)

    def tags(self) -> list[str]:
        out = []
        if self.respelled and self.form != CURRENT_FORM:
            out.append("wording.identifier_spelling")
        if self.by_id:
            out.append("wording.reference_by_id")
        if self.merged:
            out.append("wording.identifier_list")
        return out

    def as_record(self) -> dict[str, Any]:
        return {"identifier_spelling": self.form,
                "references_by_id": list(self.by_id),
                "identifier_lists": self.merged,
                "identifiers_written": self.respelled,
                "room_noun": self.room}


@dataclass
class Choice:
    """The draws one instruction's rewrite is made with."""

    form: str
    by_id: bool
    storey: bool
    storey_only: bool
    room: bool
    merge: bool


def draw_choice(rng) -> Choice:
    """The draws for one instruction, made in a fixed order."""
    form = draw_form(rng)
    by_id = rng.random() < REFERENCE_SHARE
    storey = rng.random() < STOREY_SHARE
    storey_only = rng.random() < REFERENCE_SHARE
    room = rng.random() < ROOM_SHARE
    merge = rng.random() < MERGE_SHARE
    return Choice(form, by_id, storey, storey_only, room, merge)


_SEPARATORS = (" and ", " to ", " from ")


def rewrite(phrase: str, mentions: Sequence[Mention], choice: Choice,
            storeys_follow: bool = False, storey_given: bool = False
            ) -> Rewrite:
    """The phrase with every identifier respelled and the drawn references switched.

    A storey is switched on its own draw when it is the only reference the
    phrase names, and together with the element references otherwise.  With
    ``storeys_follow`` it is always switched together with them, which is what
    a relationship clause does.
    """
    element_refs = [m for m in mentions if m.how == "name"]
    storeys = [m for m in mentions if m.how == "storey"]
    switch: list[Mention] = []
    if choice.by_id:
        switch.extend(element_refs)
    if storeys:
        only_storey = not element_refs and not any(
            m.how == "identifier" for m in mentions)
        if storeys_follow:
            # A clause names its storey the way the sentence already named it.
            if storey_given or (choice.by_id and choice.storey):
                switch.extend(storeys)
        elif (only_storey and choice.storey_only) or \
                (not only_storey and choice.by_id and choice.storey):
            switch.extend(storeys)
    written: list[tuple[Mention, str]] = []
    for mention in mentions:
        if mention.how in ("target", "identifier") or mention in switch:
            noun = mention.noun
            if noun == "space" and choice.room and mention in switch:
                noun = "room"
            written.append((mention, noun))
    result = Rewrite(phrase=phrase, form=choice.form,
                     by_id=[m.key for m in switch if m.key],
                     respelled=len(written),
                     room=any(noun == "room" for _m, noun in written),
                     storeys_switched=any(m.how == "storey" for m in switch))
    if not written:
        return result
    # Two switched references of one noun that stand side by side are written
    # as one list, which is how a person writes "between rooms A and B".
    pieces: list[tuple[int, int, str]] = []
    index = 0
    while index < len(written):
        mention, noun = written[index]
        if choice.merge and index + 1 < len(written):
            following, following_noun = written[index + 1]
            between = phrase[mention.end:following.start]
            if (mention in switch and following in switch
                    and noun == following_noun and between in _SEPARATORS):
                pieces.append((mention.start, following.end,
                               spell_list(choice.form, noun,
                                          [mention.guid, following.guid])))
                result.merged += 1
                index += 2
                continue
        pieces.append((mention.start, mention.end,
                       spell(choice.form, noun, mention.guid)))
        index += 1
    out = phrase
    for start, end, text in sorted(pieces, reverse=True):
        out = out[:start] + text + out[end:]
    result.phrase = out
    return result


def rewrite_phrase(phrase: str, params: dict, lookup: Lookup, choice: Choice,
                   target_guid: str = "") -> Rewrite:
    return rewrite(phrase, find_mentions(phrase, params, lookup, target_guid),
                   choice)


# -------------------------------------------- the named relationships clause


R_CLAUSE_NAMED = re.compile(r"the (wall|slab|door|window|column) named '([^']+)'")
R_CLAUSE_SPACE = re.compile(r"the space '([^']+)'")
R_CLAUSE_STOREY = re.compile(r"storey '([^']+)'")


def clause_mentions(text: str, lookup: Lookup, storey_guid: str = "",
                    near: Sequence[str] = ()) -> list[Mention]:
    """The elements one "named relationship" clause names.

    The clause names the element on the far side of a connection, the rooms
    the target bounds, the wall it sits in and its storey, each by name.  A
    name is tied to an identifier when the model carries exactly one element of
    that family under it, or when exactly one of ``near`` does.
    """
    mentions: list[Mention] = []

    def tie(family: str, label: str) -> Optional[str]:
        found = list(dict.fromkeys(lookup.resolve(family, label)))
        if len(found) == 1:
            return found[0]
        close = [g for g in found if g in near]
        return close[0] if len(close) == 1 else None

    for match in R_CLAUSE_NAMED.finditer(text):
        guid = tie(match.group(1), match.group(2))
        if guid:
            mentions.append(Mention(match.start(), match.end(), guid,
                                    match.group(1), "name", "relation"))
    for match in R_CLAUSE_SPACE.finditer(text):
        guid = tie("space", match.group(1))
        if guid:
            mentions.append(Mention(match.start(), match.end(), guid, "space",
                                    "name", "relation"))
    if storey_guid:
        for match in R_CLAUSE_STOREY.finditer(text):
            if match.group(1) in lookup.labels(storey_guid):
                mentions.append(Mention(match.start(), match.end(),
                                        storey_guid, "storey", "storey",
                                        "relation_storey"))
    mentions.sort(key=lambda m: m.start)
    return mentions


def rewrite_clause(text: str, mentions: Sequence[Mention], choice: Choice,
                   storey_given: bool = False) -> Rewrite:
    """A relationship clause, with its elements named by identifier.

    The clause follows the reference draw of its sentence, so a sentence that
    names its references by identifier names the related elements the same
    way, and its storey follows the sentence's storey draw.
    """
    return rewrite(text, mentions, choice, storeys_follow=True,
                   storey_given=storey_given)


# ------------------------------------------------ one instruction, end to end


@dataclass
class Reworded:
    """An instruction after the rewrite, with what the record has to carry."""

    instruction: str
    phrase: str
    base_phrase: str
    anchor_kind: str
    anchor_params: dict
    clauses: list[str]
    record: dict
    tags: list[str]

    @property
    def changed(self) -> bool:
        return bool(self.record.get("changed"))


def shares_from_registry() -> dict[str, float]:
    """The run's shares for the draws, where the registry overrides them."""
    try:
        from . import families
    except ImportError:
        return {}
    return {"spelling": families.share("wording.identifier_spelling"),
            "reference": families.share("wording.reference_by_id"),
            "merge": families.share("wording.identifier_list")}


def draw_choice_with(rng, shares: Optional[dict] = None) -> Choice:
    """``draw_choice`` with the registry's shares, when a run sets them."""
    shares = shares or {}
    form = draw_form(rng)
    if rng.random() >= shares.get("spelling", 1.0):
        # A run that switches the family off keeps the spelling every earlier
        # version wrote.
        form = CURRENT_FORM
    by_id = rng.random() < shares.get("reference", REFERENCE_SHARE)
    storey = rng.random() < STOREY_SHARE
    storey_only = rng.random() < shares.get("reference", REFERENCE_SHARE)
    room = rng.random() < ROOM_SHARE
    merge = rng.random() < shares.get("merge", MERGE_SHARE)
    return Choice(form, by_id, storey, storey_only, room, merge)


def reword(instruction: str, phrase: str, base_phrase: str, kind: str,
           params: dict, expected: Sequence[str], lookup: Lookup,
           choice: Choice, clauses: Sequence[str] = (),
           clause_storey: str = "", near: Sequence[str] = ()) -> Reworded:
    """Rewrite one instruction's reference phrase and relationship clauses.

    ``phrase`` is the reference phrase as the sentence carries it (after any
    class-token substitution) and ``base_phrase`` the anchor's own phrase; both
    are rewritten with the same draws, so they stay one phrase in two forms.
    A ``name`` anchor, which names the element the sentence is about by its
    name, becomes a ``guid`` anchor when the draw names elements by
    identifier, since the phrase then carries the identifier and no name.
    """
    params = dict(params or {})
    target = params.get("guid") if kind == "guid" else ""
    new_kind, new_params = kind, params
    if kind == "name" and choice.by_id and len(expected or ()) == 1:
        guid = expected[0]
        full = R_NAMED.fullmatch(phrase)
        base_full = R_NAMED.fullmatch(base_phrase)
        if full and base_full and full.group(2) in lookup.labels(guid):
            new_phrase = spell(choice.form, full.group(1), guid)
            new_base = spell(choice.form, base_full.group(1), guid)
            out_instruction = instruction.replace(phrase, new_phrase, 1)
            record = Rewrite(new_phrase, choice.form, by_id=["name"],
                             respelled=1).as_record()
            record["changed"] = True
            record["mentions"] = 1
            return Reworded(out_instruction, new_phrase, new_base, "guid",
                            {"guid": guid}, list(clauses), record,
                            ["wording.reference_by_id"]
                            + (["wording.identifier_spelling"]
                               if choice.form != CURRENT_FORM else []))
    mentions = find_mentions(phrase, params, lookup, target)
    done = rewrite(phrase, mentions, choice)
    done_base = rewrite_phrase(base_phrase, params, lookup, choice, target)
    out_instruction = instruction
    if phrase and done.phrase != phrase and phrase in out_instruction:
        out_instruction = out_instruction.replace(phrase, done.phrase, 1)
    tags = done.tags()
    by_id = list(done.by_id)
    new_clauses = []
    for text in clauses:
        found = clause_mentions(text, lookup, clause_storey, near)
        rewritten = rewrite_clause(text, found, choice,
                                   storey_given=done.storeys_switched)
        if rewritten.phrase != text and text in out_instruction:
            out_instruction = out_instruction.replace(text, rewritten.phrase, 1)
            by_id.extend(rewritten.by_id)
            for tag in rewritten.tags():
                if tag not in tags:
                    tags.append(tag)
            done.merged += rewritten.merged
        new_clauses.append(rewritten.phrase)
    record = done.as_record()
    record["references_by_id"] = by_id
    record["identifier_lists"] = done.merged
    record["changed"] = out_instruction != instruction
    record["mentions"] = len(mentions)
    record["identifiers_written"] = done.respelled + sum(
        1 for text, new in zip(clauses, new_clauses) if new != text)
    return Reworded(out_instruction, done.phrase, done_base.phrase, new_kind,
                    new_params, new_clauses, record, tags)
