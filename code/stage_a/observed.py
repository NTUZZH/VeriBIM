"""The identifier invariant: a trajectory may only use an identifier it has seen.

The protocol the model is trained on gives it one way to learn a GlobalId: read
it in the instruction, or read it in the output of a tool call it already made.
A trajectory that writes a GlobalId literal it never obtained teaches the model
to invent identifiers, which is what it then does at evaluation time.

The check walks the messages in order. Before each assistant turn the known set
holds every identifier the instruction carries plus every identifier an earlier
tool or user message printed; the turn's code may use only those. It is the same
extraction Stage B's sampler uses on a model's own transcripts, so a trajectory
and a rollout are judged by one rule.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable, Sequence

#: An IFC GlobalId is exactly 22 characters from this alphabet. The boundary
#: assertions matter: without them the pattern also matches the first 22
#: characters of any longer identifier, and ``CoordinateSpaceDimension`` in
#: ordinary code was being read as a fabricated id.
GUID = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")

#: In code, a GlobalId is always a quoted literal. Extracting only quoted
#: strings keeps a bare 22-character variable name from counting as an id.
GUID_LITERAL = re.compile(r"""['"]([0-9A-Za-z_$]{22})['"]""")

#: A real GlobalId always carries a digit, underscore or dollar. Without this
#: test a 22-character IFC class name passes as an id, and
#: ``IfcRectangleProfileDef`` is exactly 22 characters.
GUID_MARK = re.compile(r"[0-9_$]")


def looks_like_guid(token: str) -> bool:
    return (len(token) == 22 and not token.startswith("Ifc")
            and bool(GUID_MARK.search(token)))


def guids_in_code(code: str) -> set[str]:
    """Identifiers a snippet uses as literals."""
    return {m.group(1) for m in GUID_LITERAL.finditer(code or "")
            if looks_like_guid(m.group(1))}


def guids_in_text(text: str) -> set[str]:
    """Identifiers a piece of prose or tool output carries."""
    return {g for g in GUID.findall(text or "") if looks_like_guid(g)}


def _codes_of(message: dict) -> list[str]:
    """The snippets one assistant message asks the sandbox to run."""
    codes: list[str] = []
    for call in message.get("tool_calls") or []:
        arguments = (call.get("function") or {}).get("arguments")
        if isinstance(arguments, dict):
            codes.append(str(arguments.get("code") or ""))
        elif isinstance(arguments, str):
            try:
                codes.append(str((json.loads(arguments) or {}).get("code") or ""))
            except json.JSONDecodeError:
                codes.append(arguments)
    return codes


def observed_identifiers_ok(messages: Sequence[dict],
                            instruction: str = "") -> list[dict]:
    """Every assistant turn that used an identifier nothing had shown it.

    An empty list means the trajectory holds the invariant. Each entry names the
    round, counted over assistant turns that carry code, and the identifiers
    that turn used without having read them.
    """
    known = guids_in_text(instruction)
    violations: list[dict] = []
    round_index = 0
    for message in messages:
        role = message.get("role")
        if role in ("tool", "user"):
            known |= guids_in_text(message.get("content") or "")
            continue
        if role != "assistant":
            continue
        codes = _codes_of(message)
        if not codes:
            continue
        used: set[str] = set()
        for code in codes:
            used |= guids_in_code(code)
        unknown = sorted(used - known)
        if unknown:
            violations.append({"round": round_index, "unresolved": unknown})
        round_index += 1
    return violations


def trajectory_violations(record: dict) -> list[dict]:
    """The invariant run over one line of a trajectory file."""
    instruction = record.get("instruction") or record.get("prompt") or ""
    return observed_identifiers_ok(record.get("messages") or (), instruction)


def iter_violations(records: Iterable[dict]) -> Iterable[tuple[dict, list[dict]]]:
    for record in records:
        found = trajectory_violations(record)
        if found:
            yield record, found


# ------------------------------------------- choosing one candidate out of many

#: Names an instruction quotes. A quote mark between two letters is a
#: possessive rather than the end of a name.
QUOTED = re.compile(r"(?<![A-Za-z])['\"]([^'\"]{1,200}?)['\"](?![A-Za-z])")

#: Phrases a tool output uses when it prints a link rather than a list. A line
#: carrying one of them says which element the identifier beside it belongs to,
#: which is what makes the choice of that identifier readable.
LINK_WORDS = ("contained in", "belongs to", "is cut in", "in opening",
              "hosted in", "bounds", "->", "named", "on storey")


def _guid_class(line: str) -> dict[str, str]:
    """Per identifier on one line, the class token printed after it.

    ``print(e.GlobalId, e.is_a(), e.Name)`` is the shape every listing round
    uses, so the class of an identifier is the first ``Ifc`` token to its right.
    A listing that prints no class at all, as the storey listing does, leaves
    every identifier in one unnamed group, which is the behaviour wanted: those
    entries are candidates for one another.
    """
    marks: list[tuple[int, str, bool]] = []
    for match in GUID.finditer(line):
        if looks_like_guid(match.group(0)):
            marks.append((match.start(), match.group(0), True))
    for match in re.finditer(r"\bIfc[A-Za-z]+\b", line):
        marks.append((match.start(), match.group(0), False))
    marks.sort()
    out: dict[str, str] = {}
    for index, (_pos, token, is_guid) in enumerate(marks):
        if not is_guid:
            continue
        ifc_class = ""
        for _pos2, later, later_is_guid in marks[index + 1:]:
            if later_is_guid:
                break
            ifc_class = later
            break
        out[token] = ifc_class
    return out


def _groups(output: str) -> tuple[dict[str, str], dict[str, set[str]]]:
    """The identifiers one tool output printed, and the groups they fall into.

    A line that says what the identifier beside it is tied to, such as the echo
    of a lookup by name or the wall an opening is cut in, is not a list of
    interchangeable options, so its identifiers form no group. What is left is
    the real listings: every storey of the building, every space, every type
    object, where picking one of them is a choice that has to be readable.
    """
    of_guid: dict[str, str] = {}
    members: dict[str, set[str]] = {}
    for line in (output or "").splitlines():
        if any(word in line for word in LINK_WORDS):
            continue
        for guid, ifc_class in _guid_class(line).items():
            if guid in of_guid:
                continue
            of_guid[guid] = ifc_class
            members.setdefault(ifc_class, set()).add(guid)
    return of_guid, members


def _line_of(output: str, guid: str) -> str:
    for line in (output or "").splitlines():
        if guid in line:
            return line
    return ""


def listing_choice_justified(messages: Sequence[dict],
                             instruction: str = "") -> list[dict]:
    """Rounds that pick one identifier out of a list without saying why.

    The identifier check asks only whether a round had seen an identifier. A
    round can pass it and still teach nothing: a listing of every storey in the
    building prints them all, and the edit then takes one of them, so a model
    imitating the trajectory has no rule for which one. Here a choice counts as
    readable when the instruction quotes that element's name, when the output
    printed only one candidate of its class, when the round uses every candidate
    the listing offered, or when the line the identifier sits on also carries the
    element it was reached through.
    """
    # The user turn repeats the instruction, so an assembled row that carries no
    # instruction field is judged by the same names as a raw trajectory.
    quoted = [name for name in QUOTED.findall(instruction or "") if name.strip()]
    known_in_instruction = guids_in_text(instruction)
    # Per identifier: the output that first showed it, and its group there.
    first_output: dict[str, str] = {}
    first_group: dict[str, tuple[str, set[str]]] = {}
    justified: set[str] = set(known_in_instruction)
    violations: list[dict] = []
    round_index = 0

    for message in messages:
        role = message.get("role")
        if role in ("tool", "user"):
            content = message.get("content") or ""
            if role == "user":
                justified |= guids_in_text(content)
                quoted.extend(name for name in QUOTED.findall(content)
                              if name.strip() and name not in quoted)
                continue
            of_guid, members = _groups(content)
            for guid, ifc_class in of_guid.items():
                if guid in first_output:
                    continue
                first_output[guid] = content
                first_group[guid] = (ifc_class, members[ifc_class])
            continue
        if role != "assistant":
            continue
        codes = _codes_of(message)
        if not codes:
            continue
        used: set[str] = set()
        for code in codes:
            used |= guids_in_code(code)
        # The round is counted whether or not it writes an identifier, so both
        # checks number the rounds of one trajectory the same way.
        this_round = round_index
        round_index += 1
        unjustified: list[str] = []
        for guid in sorted(used):
            if guid in justified:
                continue
            output = first_output.get(guid)
            if output is None:
                # The identifier check owns this case.
                continue
            _ifc_class, group = first_group[guid]
            line = _line_of(output, guid)
            if len(group) < 2 or group <= used:
                justified.add(guid)
                continue
            if any(name and name in line for name in quoted):
                justified.add(guid)
                continue
            others = {g for g in guids_in_text(line) if g != guid}
            if others & justified and any(word in line for word in LINK_WORDS):
                justified.add(guid)
                continue
            unjustified.append(guid)
        if unjustified:
            violations.append({"round": this_round, "unjustified": unjustified})
    return violations


def trajectory_unjustified(record: dict) -> list[dict]:
    """The listing check run over one line of a trajectory file."""
    instruction = record.get("instruction") or record.get("prompt") or ""
    return listing_choice_justified(record.get("messages") or (), instruction)


# ------------------------------------------- numbers a round writes and has read

#: A number as it appears in prose or in a tool's output. The boundaries keep
#: the digits inside an identifier, a name or a class token out: a GlobalId
#: carries digits next to letters, and a run of digits reached over a letter is
#: part of that token rather than a quantity.
NUMBER = re.compile(r"(?<![0-9A-Za-z_$.])-?\d+(?:\.\d+)?(?![0-9A-Za-z_$])")

#: Unit conversions a round may apply between the instruction and the file. A
#: literal that is an instruction number times one of these has been read.
UNIT_SCALES = (1.0, 0.001, 0.01, 0.1, 10.0, 100.0, 1000.0)

#: How close two numbers have to be to count as the same one.
NUMBER_TOLERANCE = 1e-6


#: Counting words an instruction writes out instead of as a figure. A phrase
#: that asks for "the fifth window from the east" states the number five, and a
#: round that writes 5 is quoting the sentence.
COUNTING_WORDS = {
    "first": 1.0, "second": 2.0, "third": 3.0, "fourth": 4.0, "fifth": 5.0,
    "sixth": 6.0, "seventh": 7.0, "eighth": 8.0, "ninth": 9.0, "tenth": 10.0,
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
}

WORD = re.compile(r"[a-z]+")


def numbers_in_text(text: str) -> set[float]:
    """Quantities a piece of prose or tool output carries.

    A number the sentence writes as a word counts as stated: "the fifth window"
    gives five, so a lookup that asks the library for the fifth is quoting the
    sentence rather than inventing an index.
    """
    found: set[float] = set()
    for match in NUMBER.finditer(text or ""):
        try:
            found.add(float(match.group(0)))
        except ValueError:
            continue
    for match in WORD.finditer((text or "").lower()):
        value = COUNTING_WORDS.get(match.group(0))
        if value is not None:
            found.add(value)
    return found


def _skipped_constants(tree: "ast.AST") -> set[int]:
    """Integer literals that index, count or round rather than measure.

    A slice bound, a subscript index, the second argument of ``round`` and the
    arguments of ``range``, ``enumerate`` and ``zip`` are part of how the code
    is written, not values the round claims to know. A constant inside a
    function the round defines is skipped for the same reason: the helper is
    code the round brings with it, and its shapes and divisors are not claims
    about this model. They are identified by their node rather than by their
    value, so a 3 that indexes is skipped while a 3 that is a length is not.
    """
    import ast

    skip: set[int] = set()

    def mark(node, ints_only: bool = True) -> None:
        for child in ast.walk(node):
            if not isinstance(child, ast.Constant):
                continue
            if ints_only and not isinstance(child.value, int):
                continue
            if isinstance(child.value, (int, float)):
                skip.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            mark(node, ints_only=False)
        elif isinstance(node, (ast.Subscript, ast.Slice)):
            mark(node.slice if isinstance(node, ast.Subscript) else node)
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name == "round":
                for argument in node.args[1:]:
                    mark(argument)
            elif name in ("range", "enumerate", "zip"):
                for argument in node.args:
                    mark(argument)
            for keyword in node.keywords:
                if keyword.arg == "start":
                    mark(keyword.value)
    return skip


def numbers_in_code(code: str, floats_only: bool = False) -> list[float]:
    """Quantities a snippet writes out as literals.

    Numbers inside a string are not counted, since a name or a message is not a
    measurement. Zero and one are not counted either: they are how a loop, an
    axis or an empty offset is written. What is left is every value the round
    asserts, and each of those has to have been read somewhere.
    ``floats_only`` drops the integer literals, which is what a caller asking
    for lengths wants: a count of copies is written as an integer and a length
    is not.
    """
    import ast

    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []
    skip = _skipped_constants(tree)
    out: list[float] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant):
            continue
        value = node.value
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        if id(node) in skip:
            continue
        # A small integer counts, indexes or names an axis. A float of exactly
        # one is a sign or a unit factor. Neither is a measurement.
        if isinstance(value, int) and abs(value) <= 3:
            continue
        if isinstance(value, float) and abs(abs(value) - 1.0) <= 1e-9:
            continue
        if isinstance(value, float) and abs(value) <= 1e-9:
            continue
        if floats_only and not isinstance(value, float):
            continue
        out.append(float(value))
    return out


def number_observed(value: float, known: Iterable[float]) -> bool:
    """Whether a literal is one the trajectory has read.

    A number counts as read when it equals one that was written down, when it
    equals that number with the sign turned round, when it equals it converted
    between millimetres, centimetres and metres, or when rounding it to
    millimetres gives a number a tool printed, since every round prints its
    measurements rounded.
    """
    rounded = round(value, 3)
    for number in known:
        for scale in UNIT_SCALES:
            for candidate in (number * scale, -number * scale):
                if abs(value - candidate) <= NUMBER_TOLERANCE:
                    return True
                if abs(rounded - candidate) <= NUMBER_TOLERANCE:
                    return True
    return False


def numbers_observed_ok(messages: Sequence[dict],
                        instruction: str = "") -> list[dict]:
    """Every assistant turn that wrote a number nothing had shown it.

    This is the identifier walk applied to quantities. A trajectory that writes
    a coordinate it worked out off the record teaches the model to invent
    numbers, which is the failure the geometry axis then shows. An empty list
    means every literal the trajectory wrote was in the instruction or in an
    earlier tool output.
    """
    known = numbers_in_text(instruction)
    violations: list[dict] = []
    round_index = 0
    for message in messages:
        role = message.get("role")
        if role in ("tool", "user"):
            known |= numbers_in_text(message.get("content") or "")
            continue
        if role != "assistant":
            continue
        codes = _codes_of(message)
        if not codes:
            continue
        unknown: list[float] = []
        for code in codes:
            for value in numbers_in_code(code):
                if not number_observed(value, known) and value not in unknown:
                    unknown.append(value)
        if unknown:
            violations.append({"round": round_index, "unobserved": unknown})
        round_index += 1
    return violations


def trajectory_number_violations(record: dict) -> list[dict]:
    """The number walk run over one line of a trajectory file."""
    instruction = record.get("instruction") or record.get("prompt") or ""
    return numbers_observed_ok(record.get("messages") or (), instruction)


# ------------------------------------------ names a round matches elements on

#: Calls whose string arguments are not names of anything in the model: a
#: message, an attribute, a class token or an entity being built.
_NOT_A_NAME = ("print", "getattr", "hasattr", "setattr", "is_a", "by_type",
               "create_entity", "format", "join", "startswith", "endswith",
               "ValueError", "round", "repr", "len",
               # container and settings calls: their string argument is a key
               # or a switch, never the name of an element in the model
               "set", "get", "setdefault", "add", "append", "update", "pop",
               "split", "strip", "replace", "sorted", "sort",
               # ``measure`` is one of the helpers a lookup round defines, and
               # its string argument names a measurement, not an element
               "measure")

#: A class token. The instruction names a class in words, not in this form, so
#: a lookup that filters on one is not quoting a name it was given.
_CLASS_TOKEN = re.compile(r"^Ifc[A-Za-z]*$")

#: Keyword arguments whose value is one of the library's own words rather than
#: anything in the model: which frame a coordinate is written in, and what kind
#: of boundary a relationship records. The model learns these from the call it
#: makes, not from the sentence it was given.
_API_KEYWORDS = ("frame", "physical_or_virtual", "internal_or_external",
                 "pivot")

#: The IFC standard's own property names, read once from the schema templates.
_STANDARD_PROPERTY_NAMES = None


def names_in_code(code: str) -> list[str]:
    """The names a snippet matches elements on.

    A lookup round finds an element by comparing its ``Name`` or ``LongName``
    with a string, and that string has to be one the instruction gave. What is
    left out is everything a string is used for besides naming an element: a
    message, an attribute name, a class token, a dictionary key, an identifier,
    and anything inside a helper the round defines, which is code the round
    brings with it rather than a claim about this model.
    """
    import ast

    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return []
    skip: set[int] = set()

    def mark(node) -> None:
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                skip.add(id(child))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            mark(node)
        elif isinstance(node, ast.Subscript):
            mark(node.slice)
        elif isinstance(node, ast.JoinedStr):
            mark(node)
        elif isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in _NOT_A_NAME:
                for argument in node.args:
                    mark(argument)
                for keyword in node.keywords:
                    mark(keyword.value)
            for keyword in node.keywords:
                if keyword.arg in _API_KEYWORDS:
                    mark(keyword.value)
        elif isinstance(node, ast.Raise):
            mark(node)

    out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            continue
        if id(node) in skip:
            continue
        value = node.value
        if len(value) < 2 or not any(ch.isalnum() for ch in value):
            continue
        if _CLASS_TOKEN.match(value) or looks_like_guid(value):
            continue
        if value not in out:
            out.append(value)
    return out


def standard_property_names() -> frozenset:
    """Every property name the IFC standard property sets define.

    A property name such as ``LoadBearing`` is part of the schema, the way an
    ``Ifc`` class token is: an instruction that asks for "the load-bearing flag
    in Pset_ColumnCommon" names the set, and the name of the property inside it
    follows from the standard rather than from anything the generator chose.
    The list is read from IfcOpenShell's own property-set templates for both
    schemas the corpus uses, so it is the standard's list and not a hand-kept
    one. An unreadable template library leaves the set empty, which reports
    more rather than less.
    """
    global _STANDARD_PROPERTY_NAMES
    if _STANDARD_PROPERTY_NAMES is not None:
        return _STANDARD_PROPERTY_NAMES
    names: set[str] = set()
    try:
        import ifcopenshell.util.pset

        for schema in ("IFC2X3", "IFC4"):
            template = ifcopenshell.util.pset.get_template(schema)
            for library in template.templates:
                for definition in library.by_type("IfcPropertySetTemplate"):
                    for entry in definition.HasPropertyTemplates or ():
                        if entry.Name:
                            names.add(str(entry.Name))
    except Exception:  # noqa: BLE001 - an absent template library reports more
        names = set()
    _STANDARD_PROPERTY_NAMES = frozenset(names)
    return _STANDARD_PROPERTY_NAMES


def names_observed_ok(messages: Sequence[dict],
                      instruction: str = "") -> list[dict]:
    """Every assistant turn that matched on a name nothing had shown it.

    The generator knows an element by a name it picked when it built the task,
    and a lookup written from that name teaches the model a string it cannot
    read anywhere. A name counts as given when the instruction carries it, when
    an earlier tool output printed it, or when it is a property name the IFC
    standard defines, which a reader of the schema has without being told.
    """
    standard = standard_property_names()
    known = instruction or ""
    violations: list[dict] = []
    round_index = 0
    for message in messages:
        role = message.get("role")
        if role in ("tool", "user"):
            known += "\n" + (message.get("content") or "")
            continue
        if role != "assistant":
            continue
        codes = _codes_of(message)
        if not codes:
            continue
        unknown: list[str] = []
        for code in codes:
            for value in names_in_code(code):
                if value in standard:
                    continue
                if value not in known and value not in unknown:
                    unknown.append(value)
        if unknown:
            violations.append({"round": round_index, "unnamed": unknown})
        round_index += 1
    return violations


def trajectory_name_violations(record: dict) -> list[dict]:
    """The name walk run over one line of a trajectory file."""
    instruction = record.get("instruction") or record.get("prompt") or ""
    return names_observed_ok(record.get("messages") or (), instruction)


# --------------------------------------- an identifier looked up as a name

#: A call to one of the name lookups a round defines.  The arguments are read
#: as far as the closing parenthesis, which the lookups' own arguments (a class
#: token, a quoted name, a storey variable) never contain.
BY_NAME_CALL = re.compile(r"\bby_name(?:_on_storey)?\(([^)]*)\)")


def identifier_passed_as_name(code: str) -> list[str]:
    """Identifiers a snippet hands to a name lookup (0.9.0).

    An instruction that writes an identifier out is answered with
    ``ifc.by_guid``; a round that passes the same 22 characters to
    ``by_name`` looks the element up as a name, finds nothing, and teaches
    the model the failure the corpus exists to remove.  An empty list means
    the snippet holds the rule.
    """
    found: list[str] = []
    for match in BY_NAME_CALL.finditer(code or ""):
        for literal in GUID_LITERAL.findall(match.group(1)):
            if looks_like_guid(literal) and literal not in found:
                found.append(literal)
    return found


def trajectory_identifier_as_name(record: dict) -> list[dict]:
    """Every assistant round of one trajectory that looks an identifier up by name."""
    out: list[dict] = []
    round_index = 0
    for message in record.get("messages") or ():
        if message.get("role") != "assistant":
            continue
        codes = _codes_of(message)
        if not codes:
            continue
        for code in codes:
            hits = identifier_passed_as_name(code)
            if hits:
                out.append({"round": round_index, "identifiers": hits})
        round_index += 1
    return out
