"""Layer 7 of the requirement taxonomy: how the same requirement is worded.

Two people asking for the same edit do not write the same sentence.  One writes
"delete", another "take out"; one gives an order, another asks a question; one
says 2.5 m and another 2500 mm; one names the element in plain words and another
quotes its IFC class.  A model that only ever sees one of those forms learns the
form rather than the requirement, so a run draws a wording for every instruction
from the task's own seed.

Every variant here changes the words and not the meaning.  The gold script is
written before the wording is chosen and is not passed through this module at
all, so a wording draw cannot move an element; a unit test per variant asserts
that the gold script text is the same under every wording, and the funnel
re-reads the rendered instruction and resolves the anchor from it again.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from . import conditions, families, idspell

# ------------------------------------------------------------------- units


@dataclass(frozen=True)
class Dialect:
    """The unit one instruction states its lengths in, and how it spells it."""

    unit: str = "m"
    word: str = "m"

    #: Metres per unit of ``unit``.
    @property
    def scale(self) -> float:
        return {"m": 1.0, "mm": 0.001, "cm": 0.01}[self.unit]

    def number(self, metres: float) -> str:
        """One length, in this dialect's unit, written the way a person writes it."""
        value = float(metres) / self.scale
        if self.unit == "m":
            text = f"{value:.2f}".rstrip("0").rstrip(".")
            return text or "0"
        # A length the generator quotes is rounded to the centimetre, so the
        # millimetre and centimetre forms are whole numbers and are written as
        # whole numbers rather than with a trailing zero decimal.
        rounded = round(value, 3)
        if abs(rounded - round(rounded)) < 1e-6:
            return str(int(round(rounded)))
        return f"{rounded:g}"

    def length(self, metres: float) -> str:
        return f"{self.number(metres)} {self.word}"

    def coordinate(self, value: float) -> str:
        """One coordinate of a point, without the unit, which the point carries.

        A metre coordinate keeps both decimals, which is how a setting-out
        point is written and how every earlier wave wrote one.  A millimetre or
        centimetre coordinate is a whole number and is written as one.
        """
        if self.unit == "m":
            return f"{float(value):.2f}"
        return self.number(value)


#: The dialect every earlier version wrote in, and the one a task keeps unless
#: the wording layer draws another.
PLAIN = Dialect("m", "m")


def dialects_for(unit_word: str) -> list[Dialect]:
    """The dialects an instruction on a model in this unit may be written in.

    Metres are always available, because a person states a building dimension in
    metres whatever the file holds.  The file's own unit is offered as well when
    it is one a person writes lengths in, which millimetres and centimetres are
    and feet and inches, in this corpus, are not: a metre length converted to
    feet is not a number a work order would quote.
    """
    out = [Dialect("m", "metres"), Dialect("m", "meters")]
    if unit_word in ("mm", "cm"):
        out.append(Dialect(unit_word, unit_word))
        if unit_word == "mm":
            out.append(Dialect("cm", "cm"))
    return out


# ---------------------------------------------------------------- synonyms

#: Verbs one instruction may open with, and the verbs that mean the same thing
#: in the same sentence.  Only drop-in replacements are listed: a synonym that
#: would need the rest of the sentence rewritten is not one.
SYNONYMS = {
    "Move": ("Shift", "Relocate"),
    "Delete": ("Remove", "Take out"),
    "Remove": ("Delete", "Take out"),
    "Add": ("Create", "Insert"),
    "Set": ("Change", "Update"),
    "Change": ("Set", "Update"),
    "Rotate": ("Turn",),
    "Mirror": ("Reflect",),
    "Copy": ("Duplicate",),
}


def apply_synonym(instruction: str, rng) -> tuple[str, bool]:
    """Swap the verb the instruction opens with for one that means the same."""
    for verb, alternatives in sorted(SYNONYMS.items()):
        if not instruction.startswith(verb + " "):
            continue
        choice = str(rng.choice(sorted(alternatives)))
        return choice + instruction[len(verb):], True
    return instruction, False


# ----------------------------------------------------------- request forms

#: A prefix that says who asked for the edit and nothing else.  It carries no
#: requirement, so the gold model is the same sentence's gold model.
CONTEXT_PREFIXES = (
    "The client wants one change made to this model.",
    "The design team has agreed on one change to this model.",
    "The client has asked for the following change.",
)

REQUEST_FORMS = ("imperative", "please", "question", "context")


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text


def apply_request_form(instruction: str, form: str) -> tuple[str, bool]:
    """Write the same order as a request, a question or a briefed instruction."""
    if form == "imperative" or not instruction:
        return instruction, False
    if form == "please":
        return "Please " + _lower_first(instruction), True
    if form == "question":
        # A question mark belongs at the end of a question, so the form is only
        # written where the whole instruction is one sentence.  A full stop
        # inside a number does not end a sentence, so the test is for a stop
        # followed by a space rather than for a stop.
        stem = instruction.rstrip()
        if not stem.endswith(".") or ". " in stem:
            return instruction, False
        return "Can you " + _lower_first(stem[:-1]) + "?", True
    if form == "context":
        return instruction, False
    return instruction, False


def context_prefix(instruction: str, rng) -> tuple[str, bool]:
    prefix = str(rng.choice(sorted(CONTEXT_PREFIXES)))
    return f"{prefix} {instruction}", True


# ------------------------------------------------------------ class tokens

#: The IFC class each element family is written as when an instruction names the
#: class instead of saying it in plain words.
CLASS_OF_FAMILY = {"wall": "IfcWall", "slab": "IfcSlab", "space": "IfcSpace",
                   "door": "IfcDoor", "window": "IfcWindow",
                   "column": "IfcColumn"}


def class_token_phrase(family: str, phrase: str) -> Optional[str]:
    """The same reference phrase with the IFC class in place of the plain word.

    Only the first plain word is replaced, so "the door hosted in the wall named
    'W-12'" becomes "the IfcDoor hosted in the wall named 'W-12'" and the wall
    the phrase points through keeps the word a reader needs to follow it.
    """
    ifc_class = CLASS_OF_FAMILY.get(family or "")
    if not ifc_class or not phrase:
        return None
    plural = re.compile(rf"\b{family}s\b")
    match = plural.search(phrase)
    if match:
        return phrase[:match.start()] + f"{ifc_class} elements" + \
            phrase[match.end():]
    singular = re.compile(rf"\b{family}\b")
    match = singular.search(phrase)
    if not match:
        return None
    return phrase[:match.start()] + ifc_class + phrase[match.end():]


# ------------------------------------------------------------- the wording


@dataclass
class Wording:
    """The wording one instruction was rendered in."""

    dialect: Dialect = PLAIN
    request_form: str = "imperative"
    tags: tuple[str, ...] = ()
    anchor_phrase: str = ""
    #: How the sentence spells its identifiers and which references it names
    #: by identifier (0.9.0); empty for a sentence that carries none.
    identifiers: Optional[dict] = None
    #: The anchor the record carries when the rewrite changed it: its phrase,
    #: and for a ``name`` anchor that now quotes an identifier, its kind and
    #: parameters as well.
    anchor_rewrite: Optional[dict] = None

    def as_record(self) -> dict[str, Any]:
        out = {"unit": self.dialect.unit, "unit_word": self.dialect.word,
               "request_form": self.request_form,
               "anchor_phrase": self.anchor_phrase,
               "tags": list(self.tags)}
        if self.identifiers is not None:
            out["identifiers"] = dict(self.identifiers)
        if self.anchor_rewrite is not None:
            out["anchor_rewrite"] = dict(self.anchor_rewrite)
        return out


def draw_dialect(scene, rng) -> tuple[Dialect, bool]:
    """The unit an instruction states its lengths in."""
    if not families.draw("wording.unit_spelling", rng):
        return PLAIN, False
    options = dialects_for(conditions.unit_word(scene.unit_scale))
    if not options:
        return PLAIN, False
    return options[int(rng.random() * len(options)) % len(options)], True


def draw_request_form(rng) -> str:
    if not families.draw("wording.request_form", rng):
        return "imperative"
    forms = [f for f in REQUEST_FORMS if f != "imperative"]
    return forms[int(rng.random() * len(forms)) % len(forms)]


def apply(instruction: str, scene, plan, anchor, rng,
          dialect: Dialect = PLAIN, dialect_drawn: bool = False) -> Wording:
    """Word one rendered instruction, and say which variants it carries.

    The instruction comes in already written in the drawn dialect, because the
    unit a length is quoted in has to be chosen before the sentence is built.
    Everything else is a substitution on the finished sentence, and each one is
    exact: a verb only at the head of the sentence, and a reference phrase only
    where the anchor's own phrase stands.
    """
    tags: list[str] = []
    phrase = getattr(anchor, "phrase", "") or ""
    if phrase and phrase not in (instruction or ""):
        # Some sentences never quote the phrase their anchor carries: a
        # compositional create names the storey the new element goes on and
        # nothing about the element the anchor resolves to.  There is no
        # reference in the words for a wording draw to break, so the record
        # says the sentence carries none rather than claiming one the reader
        # cannot see, and the funnel's wording check has nothing to read back.
        phrase = ""
    if dialect_drawn and dialect.word != PLAIN.word:
        tags.append("wording.unit_spelling")

    identifiers, anchor_rewrite = None, None
    if phrase and phrase in instruction:
        instruction, phrase, identifiers, anchor_rewrite, id_tags = \
            _identifiers(instruction, phrase, scene, plan, anchor, rng)
        tags.extend(id_tags)

    if phrase and phrase in instruction and \
            families.draw("wording.class_token", rng):
        replacement = class_token_phrase(getattr(anchor, "family", ""), phrase)
        if replacement and replacement != phrase:
            instruction = instruction.replace(phrase, replacement, 1)
            phrase = replacement
            tags.append("wording.class_token")

    if families.draw("wording.synonym", rng):
        instruction, changed = apply_synonym(instruction, rng)
        if changed:
            tags.append("wording.synonym")

    form = draw_request_form(rng)
    if form == "context":
        instruction, changed = context_prefix(instruction, rng)
    else:
        instruction, changed = apply_request_form(instruction, form)
    if changed:
        tags.append("wording.request_form")
    else:
        form = "imperative"

    wording = Wording(dialect=dialect, request_form=form,
                      tags=tuple(dict.fromkeys(tags)), anchor_phrase=phrase,
                      identifiers=identifiers, anchor_rewrite=anchor_rewrite)
    return instruction, wording


def _identifiers(instruction: str, phrase: str, scene, plan, anchor, rng):
    """Spell the sentence's identifiers and name its references by identifier.

    Runs before the class-token draw, so a class token replaces the plain word
    of the rewritten phrase the way it replaced the word of the old one.  The
    relationships a delete instruction names are rewritten with the same draws,
    so one sentence spells every identifier it carries one way.
    """
    params = dict(getattr(anchor, "params", {}) or {})
    kind = getattr(anchor, "kind", "")
    expected: list[str] = []
    if kind == "guid" and params.get("guid"):
        expected = [params["guid"]]
    elif kind == "name":
        try:
            expected = list(anchor.resolve(scene))
        except Exception:
            expected = []
    if params.get("scope") == "ids":
        # An identifier list is spelled when the set phrase is built.
        record = {"identifier_spelling": params.get("id_form", ""),
                  "references_by_id": ["member_guids"],
                  "identifier_lists": 1, "room_noun": False, "changed": True}
        return instruction, phrase, record, None, \
            ["wording.identifier_list"] + (
                ["wording.identifier_spelling"]
                if params.get("id_form") not in ("", idspell.CURRENT_FORM)
                else [])
    choice = idspell.draw_choice_with(rng, idspell.shares_from_registry())
    lookup = idspell.scene_lookup(scene)
    clauses = [entry.get("text", "") for entry in
               (plan.params.get("named_relations") or ())]
    # The element the edit is about, which is what a relationship clause
    # describes: the anchor's own answer for a direct or a named anchor, and
    # the plan's single target otherwise.
    targets = list(getattr(plan, "target_guids", ()) or ())
    target_guid = expected[0] if expected else (
        targets[0] if len(targets) == 1 else "")
    target = scene.by_guid(target_guid) if target_guid else None
    near: list[str] = []
    storey_guid = ""
    if target is not None:
        near = list(scene.connected(target)) + list(scene.bounded_spaces(target))
        host = scene.host_of(target)
        if host:
            near.append(host)
        storey = scene.storey_of(target)
        storey_guid = storey.GlobalId if storey is not None else ""
    done = idspell.reword(instruction, phrase, anchor.phrase, kind, params,
                          expected, lookup, choice, clauses, storey_guid, near)
    if not done.record.get("mentions") and not done.changed:
        # A phrase with no identifier and no reference it could switch.
        return instruction, phrase, None, None, []
    for entry, text in zip(plan.params.get("named_relations") or (),
                           done.clauses):
        entry["text"] = text
    rewrite = None
    if done.changed:
        rewrite = {"phrase": done.base_phrase}
        if done.anchor_kind != kind:
            rewrite.update(kind=done.anchor_kind, params=done.anchor_params)
    return done.instruction, done.phrase, done.record, rewrite, done.tags


# --------------------------------------------------- under-specified asking

#: What an instruction may leave out, the word the reply has to name, and the
#: other words a reply may use for the same thing.  The check the scorer runs is
#: a question mark plus one of these words, so the list is short and fixed.
MISSING_SLOTS = {
    "element": {
        "question": "which element the change is meant for",
        "keywords": ("which", "what"),
    },
    "storey": {
        "question": "which storey the new element goes on",
        "keywords": ("storey", "story", "floor", "level"),
    },
    "dimension": {
        "question": "what the new value should be",
        "keywords": ("value", "dimension", "how", "what", "size", "height",
                     "width", "length", "thickness", "distance"),
    },
}


def clarification_question(slot: str, subject: str) -> str:
    """The one question a correct reply asks, as the record records it."""
    if slot == "element":
        return f"Which {subject} do you mean?"
    if slot == "storey":
        return f"Which storey should the {subject} go on?"
    return f"What should the new {subject} be?"
