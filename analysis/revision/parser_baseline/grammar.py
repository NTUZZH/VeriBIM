"""Template-inversion grammar for benchmark instructions.

The grammar is the inverse of the instruction renderer in code/modifc_gen
(templates.py, anchors.py, idspell.py, wording.py and the storey phrases of
generate.py).  It reads one instruction and returns the edit it asks for as a
plain dictionary (the "intent"): the operation, the reference that names the
target, and the parameters.  It reads nothing but the instruction text.

The parsers are small generator combinators.  Each takes the remaining text
and yields every way it can read a prefix of it, as (value, rest) pairs, so a
quoted name that itself contains an apostrophe is split wherever the rest of
the sentence still parses.
"""

from __future__ import annotations

import re
from typing import Any, Callable, Iterator

Parser = Callable[[str], Iterator[tuple[Any, str]]]

FAMILIES = ("wall", "slab", "space", "door", "window", "column")
CLASS_OF = {"wall": "IfcWall", "slab": "IfcSlab", "space": "IfcSpace",
            "door": "IfcDoor", "window": "IfcWindow", "column": "IfcColumn"}
FAMILY_OF_CLASS = {v: k for k, v in CLASS_OF.items()}
PLURALS = {"walls": "wall", "slabs": "slab", "spaces": "space",
           "doors": "door", "windows": "window", "columns": "column",
           "rooms": "space"}
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
DIR_AXIS = {"east": "+X", "west": "-X", "north": "+Y", "south": "-Y",
            "up": "+Z", "down": "-Z"}
UNIT_SCALE = {"m": 1.0, "metres": 1.0, "meters": 1.0, "mm": 0.001,
              "cm": 0.01}


# ------------------------------------------------------------ combinators


def lit(text: str) -> Parser:
    def p(t: str):
        if t.startswith(text):
            yield None, t[len(text):]
    return p


def rx(pattern: str, conv=None, flags=0) -> Parser:
    compiled = re.compile(pattern, flags)

    def p(t: str):
        m = compiled.match(t)
        if m:
            yield (conv(m) if conv else m.group(0)), t[m.end():]
    return p


def alt(*parsers: Parser) -> Parser:
    def p(t: str):
        for sub in parsers:
            yield from sub(t)
    return p


def seq(*parts) -> Parser:
    """Parts are literal strings, (name, parser) pairs, or bare parsers.

    Yields a dict of the named values.  A part named "*" merges the dict its
    parser yields into the result.
    """
    norm = []
    for part in parts:
        if isinstance(part, str):
            norm.append((None, lit(part)))
        elif isinstance(part, tuple):
            norm.append(part)
        else:
            norm.append((None, part))

    def p(t: str):
        def rec(i, t, acc):
            if i == len(norm):
                yield dict(acc), t
                return
            name, sub = norm[i]
            for value, rest in sub(t):
                nxt = acc
                if name == "*":
                    nxt = dict(acc)
                    nxt.update(value or {})
                elif name:
                    nxt = dict(acc)
                    nxt[name] = value
                yield from rec(i + 1, rest, nxt)
        yield from rec(0, t, {})
    return p


def mapv(parser: Parser, fn) -> Parser:
    def p(t: str):
        for value, rest in parser(t):
            yield fn(value), rest
    return p


def opt(parser: Parser, default=None) -> Parser:
    def p(t: str):
        yield from parser(t)
        yield default, t
    return p


def lazy(fn) -> Parser:
    def p(t: str):
        yield from fn()(t)
    return p


def quoted(allow_empty: bool = False) -> Parser:
    """A single-quoted name, split at every closing quote that may end it."""
    def p(t: str):
        if not t.startswith("'"):
            return
        start = 1
        while True:
            end = t.find("'", start)
            if end < 0:
                return
            if end > 1 or allow_empty:
                yield t[1:end], t[end + 1:]
            start = end + 1
    return p


# ------------------------------------------------------------- tokens

NUM_RE = r"-?\d+(?:\.\d+)?"
GUID_RE = r"[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])"

NUM = rx(NUM_RE, lambda m: float(m.group(0)))
GUID = rx(GUID_RE)
QGUID = alt(seq("'", ("g", GUID), "'"), seq(("g", GUID)))
QGUID = mapv(QGUID, lambda d: d["g"])
UNIT = rx(r"(metres|meters|mm|cm|m)(?![A-Za-z])",
          lambda m: m.group(1))


def length() -> Parser:
    """A length with its unit, returned in metres."""
    return mapv(seq(("v", NUM), " ", ("u", UNIT)),
                lambda d: round(d["v"] * UNIT_SCALE[d["u"]], 6))


LEN = length()


def _family_word(word: str) -> str:
    if word in FAMILY_OF_CLASS:
        return FAMILY_OF_CLASS[word]
    if word == "room":
        return "space"
    return word


NOUN = rx(r"(wall|slab|space|door|window|column|IfcWall|IfcSlab|IfcSpace|"
          r"IfcDoor|IfcWindow|IfcColumn)(?![A-Za-z])",
          lambda m: _family_word(m.group(1)))
# A reference element may also be a room (a space spelled as a room).
RNOUN = rx(r"(wall|slab|space|door|window|column|room|IfcWall|IfcSlab|"
           r"IfcSpace|IfcDoor|IfcWindow|IfcColumn)(?![A-Za-z])",
           lambda m: _family_word(m.group(1)))
PNOUN = rx(r"(walls|slabs|spaces|doors|windows|columns|rooms|"
           r"(IfcWall|IfcSlab|IfcSpace|IfcDoor|IfcWindow|IfcColumn) elements)"
           r"(?![A-Za-z])",
           lambda m: (FAMILY_OF_CLASS[m.group(2)] if m.group(2)
                      else PLURALS[m.group(1)]))
DIRW = rx(r"(east|west|north|south|up|down)", lambda m: m.group(1))
AXW = rx(r"([+-][XYZ])", lambda m: m.group(1))


def id_forms(noun: Parser) -> Parser:
    """One element written by its identifier, in every spelling idspell uses."""
    return alt(
        seq("the ", ("fam", noun), " with GlobalId ", ("g", QGUID)),
        seq("the ", ("fam", noun), " with ID ", ("g", QGUID)),
        seq("the ", ("fam", noun), " with the ID ", ("g", GUID)),
        seq("the ", ("fam", noun), " (ID: ", ("g", GUID), ")"),
        seq("the ", ("fam", noun), " with GUID ", ("g", GUID)),
        seq("the ", ("fam", noun), " identified as ", ("g", GUID)),
        seq("the ", ("fam", noun), " whose GlobalId is ", ("g", GUID)),
        seq("the ", ("fam", noun), " ", ("g", GUID)),
        seq(("fam", noun), " ID ", ("g", GUID)),
        seq(("fam", noun), " ", ("g", GUID)),
    )


def guid_list() -> Parser:
    """'A', 'B' and 'C' or A, B and C (two or more)."""
    def p(t: str):
        out = []
        rest = t
        while True:
            got = list(QGUID(rest))
            if not got:
                return
            g, rest = got[0]
            out.append(g)
            if rest.startswith(", "):
                rest = rest[2:]
                continue
            if rest.startswith(" and "):
                got = list(QGUID(rest[5:]))
                if not got:
                    return
                g, rest = got[0]
                out.append(g)
                yield list(out), rest
                return
            return
    return p


GLIST = guid_list()


def list_forms(pnoun: Parser) -> Parser:
    """Several elements of one noun written as one identifier list."""
    return alt(
        seq(opt(lit("the ")), ("fam", pnoun), " with GlobalIds ", ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " with IDs ", ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " with the IDs ", ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " (IDs: ", ("gs", GLIST), ")"),
        seq(opt(lit("the ")), ("fam", pnoun), " with GUIDs ", ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " identified as ", ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " whose GlobalIds are ",
            ("gs", GLIST)),
        seq(opt(lit("the ")), ("fam", pnoun), " ", ("gs", GLIST)),
    )


# ---------------------------------------------------------- references


def _guid_ref(d):
    return {"k": "guid", "fam": d["fam"], "g": d["g"]}


STOREY_NOUN = rx(r"storey(?![A-Za-z])", lambda m: "storey")

STOREY = alt(
    mapv(seq("storey ", ("n", quoted())), lambda d: {"k": "storey_name",
                                                     "name": d["n"]}),
    mapv(seq("the storey at elevation ", ("e", NUM), " m"),
         lambda d: {"k": "storey_elev", "e": d["e"]}),
    mapv(id_forms(STOREY_NOUN), lambda d: {"k": "guid", "fam": "storey",
                                           "g": d["g"]}),
)

SPACEREF = alt(
    mapv(seq("the space ", ("n", quoted())),
         lambda d: {"k": "spacelabel", "fam": "space", "name": d["n"]}),
    mapv(id_forms(rx(r"(space|room|IfcSpace)(?![A-Za-z])",
                     lambda m: "space")), _guid_ref),
)

REFEL = alt(
    mapv(seq("the ", ("fam", RNOUN), " named ", ("n", quoted())),
         lambda d: {"k": "name", "fam": d["fam"], "name": d["n"]}),
    mapv(id_forms(RNOUN), _guid_ref),
    SPACEREF,
)


def pair(ref: Parser, sep: str, plural: Parser) -> Parser:
    """Two references joined by ``sep``, or merged into one identifier list."""
    return alt(
        mapv(seq(("a", ref), sep, ("b", ref)), lambda d: [d["a"], d["b"]]),
        mapv(list_forms(plural),
             lambda d: [{"k": "guid", "fam": d["fam"], "g": g}
                        for g in d["gs"]] if len(d["gs"]) == 2 else None),
    )


def _not_none(parser: Parser) -> Parser:
    def p(t):
        for v, r in parser(t):
            if v is not None:
                yield v, r
    return p


ANYPLURAL = PNOUN
SPACEPLURAL = rx(r"(spaces|rooms|IfcSpace elements)(?![A-Za-z])",
                 lambda m: "space")
REFPAIR_AND = _not_none(pair(REFEL, " and ", ANYPLURAL))
SPACEPAIR_AND = _not_none(pair(SPACEREF, " and ", SPACEPLURAL))
SPACEPAIR_FROM = _not_none(pair(SPACEREF, " from ", SPACEPLURAL))
SPACEPAIR_TO = _not_none(pair(SPACEREF, " to ", SPACEPLURAL))


def target() -> Parser:
    """One element, named by any anchor kind the generator writes."""
    N = ("fam", NOUN)
    return alt(
        mapv(seq("the ", N, " named ", ("n", quoted())),
             lambda d: {"k": "name", "fam": d["fam"], "name": d["n"]}),
        mapv(id_forms(NOUN), _guid_ref),
        mapv(seq("the ", N, " on ", ("st", STOREY), " that stands about ",
                 ("d", NUM), " m ", ("dir", DIRW), " (", AXW, ") of ",
                 ("ref", REFEL)),
             lambda d: dict(d, k="offset")),
        mapv(seq("the ", N, " furthest ", ("dir", DIRW), " (", AXW, ") on ",
                 ("st", STOREY)), lambda d: dict(d, k="extreme")),
        mapv(seq("the only ", N, " contained in ", ("st", STOREY)),
             lambda d: dict(d, k="in_storey")),
        mapv(seq("the ", N, " hosted in ", ("host", lazy(target_or_refel))),
             lambda d: dict(d, k="hosted")),
        mapv(seq("the ", N, " that bounds both ", ("pair", SPACEPAIR_AND)),
             lambda d: dict(d, k="bounding")),
        mapv(seq("the ", N, " bounded by ", ("pair", REFPAIR_AND)),
             lambda d: dict(d, k="space_of")),
        mapv(seq("the ", N, " bounded by ", ("el", REFEL)),
             lambda d: dict(d, k="space_of")),
        mapv(seq("the ", N, " connected to ", ("other", REFEL)),
             lambda d: dict(d, k="connects")),
        mapv(seq("the ", N, " nearest to ", ("ref", REFEL), " on ",
                 ("st", STOREY)), lambda d: dict(d, k="nearest")),
        mapv(seq("the ", N, " on ", ("st", STOREY), " that stands between ",
                 ("pair", REFPAIR_AND)), lambda d: dict(d, k="between")),
        mapv(seq("the ", N, " on ", ("st", STOREY), " directly ",
                 ("dir", rx(r"(above|below)", lambda m: m.group(1))), " ",
                 ("ref", REFEL)), lambda d: dict(d, k="above_below")),
        mapv(seq("the ", N, " that separates ", ("pair", SPACEPAIR_FROM)),
             lambda d: dict(d, k="bounding")),
        mapv(seq("the ", N, " opposite ", ("ref", REFEL), " across ",
                 ("space", SPACEREF)), lambda d: dict(d, k="opposite")),
        mapv(seq("the ", N, " on the ",
                 ("side", rx(r"(left|right)", lambda m: m.group(1))),
                 "-hand side as seen from ", ("door", REFEL),
                 " looking into ", ("space", SPACEREF)),
             lambda d: dict(d, k="egocentric")),
        mapv(seq("the ", ("ord", rx(r"(first|second|third|fourth|fifth)",
                                    lambda m: ORDINALS[m.group(1)])),
                 " ", N, " from the ", ("dir", DIRW), " along ",
                 ("host", REFEL)), lambda d: dict(d, k="ordinal")),
        mapv(seq("the ", N, " on ", ("st", STOREY), " that no ",
                 ("missing", rx(r"(window|door)", lambda m: m.group(1))),
                 " bounds"), lambda d: dict(d, k="space_without")),
        mapv(seq("the ", N, " on ", ("st", STOREY),
                 " that hosts no door and no window"),
             lambda d: dict(d, k="wall_without_filling")),
        mapv(seq("the ", N, " bounding ", ("space", SPACEREF),
                 " that hosts no ",
                 ("missing", rx(r"(window|door)", lambda m: m.group(1)))),
             lambda d: dict(d, k="bounding_wall_without")),
        mapv(seq("the ", N, " in which ", ("el", REFEL), " is located"),
             lambda d: dict(d, k="host_of")),
        mapv(seq("the ", N, " that holds ", ("el", REFEL)),
             lambda d: dict(d, k="host_of")),
        mapv(seq("the ", N, " ", ("el", REFEL), " sits in"),
             lambda d: dict(d, k="host_of")),
        mapv(seq("the ", N, " that connects ", ("a", SPACEREF),
                 " to the outside"), lambda d: dict(d, k="joins_out")),
        mapv(seq("the ", N, " that leads from ", ("a", SPACEREF),
                 " to the outside"), lambda d: dict(d, k="joins_out")),
        mapv(seq("the ", N, " that connects ", ("pair", SPACEPAIR_TO)),
             lambda d: dict(d, k="joins")),
        mapv(seq("the ", N, " between ", ("pair", SPACEPAIR_AND)),
             lambda d: dict(d, k="joins")),
        mapv(seq("the ", N, " joining ", ("pair", SPACEPAIR_AND)),
             lambda d: dict(d, k="joins")),
        mapv(seq("the ", N, " that bounds ", ("space", SPACEREF)),
             lambda d: dict(d, k="bounds")),
        mapv(seq("the ", N, " bounding ", ("space", SPACEREF)),
             lambda d: dict(d, k="bounds")),
        mapv(seq("the ", N, " below the walls of ", ("st", STOREY)),
             lambda d: dict(d, k="under")),
        mapv(seq("the ", N, " the walls of ", ("st", STOREY), " stand on"),
             lambda d: dict(d, k="under")),
        mapv(seq("the only ", N, " on ", ("st", STOREY),
                 " that has no connection to another element"),
             lambda d: dict(d, k="without_relation", rel="connection")),
        mapv(seq("the ", N, " on ", ("st", STOREY),
                 " with no connection to any other element"),
             lambda d: dict(d, k="without_relation", rel="connection")),
        mapv(seq("the only ", N, " on ", ("st", STOREY),
                 " that has no space boundary"),
             lambda d: dict(d, k="without_relation", rel="space boundary")),
        mapv(seq("the ", N, " on ", ("st", STOREY),
                 " recorded with no space boundary"),
             lambda d: dict(d, k="without_relation", rel="space boundary")),
    )


def target_or_refel():
    return REFEL


TARGET = target()
BARE = mapv(seq("the ", ("fam", rx(r"(wall|slab|space|door|window|column)"
                                    r"(?![A-Za-z])", lambda m: m.group(1)))),
            lambda d: {"k": "bare", "fam": d["fam"]})

COND = rx(r"(wider|taller|longer) than (\d+(?:\.\d+)?) m",
          lambda m: {"measure": {"wider": "overall_width",
                                 "taller": "height",
                                 "longer": "plan_length"}[m.group(1)],
                     "threshold": float(m.group(2))})


def set_ref() -> Parser:
    """A set of elements: by storey, host, room, condition or identifier list."""
    return alt(
        mapv(seq("all the ", ("fam", PNOUN), " on ", ("st", STOREY)),
             lambda d: dict(d, k="set", scope="storey")),
        mapv(seq("every ", ("fam", NOUN), " hosted in ", ("host", REFEL)),
             lambda d: dict(d, k="set", scope="host")),
        mapv(seq("the ", ("fam", PNOUN), " that bound ", ("space", SPACEREF)),
             lambda d: dict(d, k="set", scope="space")),
        mapv(seq("only the ", ("fam", PNOUN), " on ", ("st", STOREY), " ",
                 ("cond", COND)),
             lambda d: dict(d, k="set", scope="storey")),
        mapv(seq("only the ", ("fam", PNOUN), " hosted in ", ("host", REFEL),
                 " ", ("cond", COND)),
             lambda d: dict(d, k="set", scope="host")),
        mapv(seq("only the ", ("fam", PNOUN), " bounding ", ("space", SPACEREF),
                 " ", ("cond", COND)),
             lambda d: dict(d, k="set", scope="space")),
        mapv(list_forms(PNOUN),
             lambda d: {"k": "set", "scope": "ids", "fam": d["fam"],
                        "gs": d["gs"]}),
    )


SET = set_ref()
TARGET_OR_BARE = alt(TARGET, BARE)
TARGET_SET_BARE = alt(TARGET, SET, BARE)


# ------------------------------------------------------------- sentences

DEL = rx(r"(Delete|Remove|Take out)(?= )", lambda m: m.group(1))
SETV = rx(r"(Set|Change|Update)(?= )", lambda m: m.group(1))
MOVE = rx(r"(Move|Shift|Relocate)(?= )")
ADD = rx(r"(Add|Create|Insert)(?= )")

CONSTRAINT = opt(rx(r", (keeping its placement fixed|keeping its z value fixed|"
                    r"preserving all of its relationships|and make sure the "
                    r"other relationships stay consistent)",
                    lambda m: m.group(1)))
END = rx(r"\.$", lambda m: True)
REST = rx(r".+$", lambda m: m.group(0))
MOVEDIR = alt(
    mapv(seq(("d", LEN), " to the ", ("dir", DIRW), " (", AXW, ")"),
         lambda d: {"dist": d["d"], "dir": d["dir"]}),
    mapv(seq("by ", ("d", LEN), " in the ",
             ("ax", rx(r"([+-][xyz])", lambda m: m.group(1))), " direction"),
         lambda d: {"dist": d["d"], "dir": {"+x": "east", "-x": "west",
                                             "+y": "north", "-y": "south",
                                             "+z": "up", "-z": "down"}[d["ax"]]}),
)
POINT = mapv(seq("(", ("x", NUM), ", ", ("y", NUM), ", ", ("z", NUM), ") ",
                 ("u", UNIT)),
             lambda d: [round(d[c] * UNIT_SCALE[d["u"]], 6) for c in "xyz"])

VALUE = alt(
    mapv(rx(r"(true|false)(?![A-Za-z])", lambda m: m.group(1) == "true"),
         lambda v: {"v": v, "t": "IfcBoolean"}),
    mapv(rx(r"(-?\d+\.\d+) W/m2K", lambda m: float(m.group(1))),
         lambda v: {"v": v, "t": "IfcThermalTransmittanceMeasure"}),
    mapv(rx(r"-?\d+\.\d+(?![\d ])", lambda m: float(m.group(0))),
         lambda v: {"v": v, "t": "IfcReal"}),
    mapv(quoted(allow_empty=True), lambda v: {"v": v, "t": "IfcLabel"}),
)
PROPWORD = rx(r"(fire rating|external flag|load-bearing flag|thermal "
              r"transmittance)", lambda m: m.group(1))
PSET = rx(r"(Pset_\w+)", lambda m: m.group(1))
DIMWORD = rx(r"(overall height|overall width|height|thickness|length|width)",
             lambda m: m.group(1))


def _names_list() -> Parser:
    """'a', 'b' and 'c'"""
    def p(t):
        out = []
        rest = t
        # names are quoted; split greedily with backtracking over quote ends
        def rec(rest, acc):
            for name, r in quoted()(rest):
                if r.startswith(", "):
                    yield from rec(r[2:], acc + [name])
                elif r.startswith(" and "):
                    for last, r2 in quoted()(r[5:]):
                        yield acc + [name, last], r2
                else:
                    if acc == []:
                        yield [name], r
        yield from rec(rest, out)
    return p


NAMES = _names_list()

# Relationship partners of a create: "the space 'X'" or "the wall named 'X'".
PARTNER = alt(
    mapv(seq("the space ", ("n", quoted())),
         lambda d: {"k": "spacelabel", "fam": "space", "name": d["n"]}),
    mapv(seq("the ", ("fam", NOUN), " named ", ("n", quoted())),
         lambda d: {"k": "name", "fam": d["fam"], "name": d["n"]}),
    mapv(seq("The space ", ("n", quoted())),
         lambda d: {"k": "spacelabel", "fam": "space", "name": d["n"]}),
    mapv(seq("The ", ("fam", NOUN), " named ", ("n", quoted())),
         lambda d: {"k": "name", "fam": d["fam"], "name": d["n"]}),
)


def partner_list() -> Parser:
    def p(t):
        def rec(rest, acc):
            for item, r in PARTNER(rest):
                if r.startswith(", "):
                    yield from rec(r[2:], acc + [item])
                elif r.startswith(" and "):
                    for last, r2 in PARTNER(r[5:]):
                        yield acc + [item, last], r2
                    if not acc:
                        yield [item], r
                else:
                    if not acc:
                        yield [item], r
        yield from rec(t, [])
    return p


PARTNERS = partner_list()

RELATION = alt(
    mapv(seq(" It bounds ", ("p", PARTNERS), "."),
         lambda d: {"rel": "bounds", "partners": d["p"]}),
    mapv(seq(" ", ("p", PARTNERS), " ", rx(r"bounds?"), " it."),
         lambda d: {"rel": "bounded_by", "partners": d["p"]}),
    mapv(seq(" Establish a connection to ", ("p", PARTNERS), "."),
         lambda d: {"rel": "connects", "partners": d["p"]}),
    mapv(seq(" Connect it to ", ("p", PARTNERS), "."),
         lambda d: {"rel": "connects", "partners": d["p"]}),
    mapv(seq(" Add an IfcRelSpaceBoundary between it and ", ("p", PARTNERS),
             "."), lambda d: {"rel": "boundary_class", "partners": d["p"]}),
    mapv(seq(" Add an IfcRelConnectsElements between it and ",
             ("p", PARTNERS), "."),
         lambda d: {"rel": "connects", "partners": d["p"]}),
)

PREDEF = opt(seq(". Give it the predefined type ",
                 ("pt", rx(r"[A-Z_]+", lambda m: m.group(0)))), {})

WHERE = alt(
    mapv(seq("the storey that contains ", ("el", REFEL)),
         lambda d: {"k": "storey_of", "el": d["el"]}),
    mapv(seq("the storey that ", ("el", REFEL), " belongs to"),
         lambda d: {"k": "storey_of", "el": d["el"]}),
    STOREY,
)

SIZE = alt(
    mapv(seq(("l", LEN), " long, ", ("w", LEN), " thick and ", ("h", LEN),
             " high"), lambda d: {"fam_hint": "wall", **d}),
    mapv(seq(("l", LEN), " by ", ("w", LEN), " in plan and ", ("h", LEN),
             " thick"), lambda d: {"fam_hint": "slab", **d}),
    mapv(seq(("l", LEN), " by ", ("w", LEN), " in section and ", ("h", LEN),
             " high"), lambda d: {"fam_hint": "column", **d}),
    mapv(seq(("l", LEN), " long, ", ("w", LEN), " wide and ", ("h", LEN),
             " high"), lambda d: {"fam_hint": "space", **d}),
    mapv(seq("a length in the x-direction of ", ("l", LEN),
             ", a width in the y-direction of ", ("w", LEN),
             " and a height of ", ("h", LEN)),
         lambda d: {"fam_hint": "axis", **d}),
)

BOX_POSITION = alt(
    mapv(seq(", with its base corner at ", ("p", POINT),
             " in that storey's own coordinates"),
         lambda d: {"pos": "storey", "p": d["p"]}),
    mapv(seq(", with its lowest corner at ", ("p", POINT),
             " in world coordinates, set out along that storey's own axes, "
             "which run ", ("turn", NUM),
             " degrees counter-clockwise from the world axes"),
         lambda d: {"pos": "world", "p": d["p"], "turn": d["turn"]}),
    mapv(seq(", with its lowest corner at ", ("p", POINT)),
         lambda d: {"pos": "world", "p": d["p"]}),
    mapv(seq(". Set its base corner ", ("dx", LEN), " to the ",
             ("xw", rx(r"(east|west)", lambda m: m.group(1))), " (", AXW,
             ") and ", ("dy", LEN), " to the ",
             ("yw", rx(r"(north|south)", lambda m: m.group(1))), " (", AXW,
             ") of ", ("ref", REFEL)),
         lambda d: {"pos": "offset", "dx": d["dx"], "dy": d["dy"],
                    "xw": d["xw"], "yw": d["yw"], "ref": d["ref"]}),
)

DERIVED = alt(
    mapv(seq(("t", LEN), " thick and ", ("h", LEN), " high, so that it fits "
             "the gap between ", ("a", REFEL), " and ", ("b", REFEL),
             ", closing that gap exactly"),
         lambda d: {"pos": "fits_gap", **d}),
    mapv(seq(("h", LEN), " high, so that it sits directly on top of ",
             ("a", REFEL), ", over the same footprint"),
         lambda d: {"pos": "on_top_of", **d}),
    mapv(seq(("l", LEN), " by ", ("w", LEN), " in section, so that it rises "
             "from the floor level of that storey and its top face touches "
             "the underside of ", ("a", REFEL)),
         lambda d: {"pos": "touching_slab_above", **d}),
    mapv(seq("a length in the x-direction of ", ("l", LEN),
             ", a width in the y-direction of ", ("w", LEN),
             " and a height of ", ("h", LEN), ", inside ", ("space", SPACEREF),
             ", standing against ", ("a", REFEL), " and touching it"),
         lambda d: {"pos": "adjacent_to_space", **d}),
)

FILL_WHERE = alt(
    mapv(seq("with the middle of the leaf ", ("c", LEN),
             " along the wall from its start"),
         lambda d: {"where": "centre", "v": d["c"]}),
    mapv(seq("directly ", ("dir", rx(r"(above|below)", lambda m: m.group(1))),
             " ", ("ref", REFEL), " on the storey ",
             rx(r"(above|below)")),
         lambda d: {"where": "aligned", "dir": d["dir"], "ref": d["ref"]}),
    mapv(seq(("a", LEN), " along the wall from its start point"),
         lambda d: {"where": "along", "v": d["a"]}),
)
SILL = alt(
    mapv(seq("with its sill ", ("s", LEN), " above the wall's base"),
         lambda d: d["s"]),
    mapv(lit("standing on the wall's base"), lambda d: 0.0),
)
HOSTED_COUNT = alt(
    mapv(seq("the ", rx(r"(door|window)(?![A-Za-z])")), lambda d: 1),
    mapv(seq("the ", ("n", NUM), " ", rx(r"(doors and windows|doors|windows)")),
         lambda d: int(d["n"])),
)

def _sentences() -> list[tuple[str, Parser]]:
    """Every sentence form, as (edit kind, parser)."""
    T = ("t", TARGET_OR_BARE)
    S = []
    # ------------------------------------------------ compositional tier
    S.append(("create_wall_with_door", seq(
        ADD, " a new wall named ", ("name", quoted()), " on ", ("where", WHERE),
        ", ", ("l", LEN), " long, ", ("w", LEN), " thick and ", ("h", LEN),
        " high, with its base corner at ", ("p", POINT),
        " in that storey's own coordinates. Then put a door named ",
        ("dname", quoted()), " in that new wall, ", ("dw", LEN), " wide and ",
        ("dh", LEN), " high, ", ("along", LEN),
        " along the wall from its start point, and cut the opening it fills",
        END)))
    S.append(("delete_wall_with_fillings", seq(
        DEL, " ", ("count", HOSTED_COUNT), " hosted in ", T,
        ", then remove the wall itself along with the ",
        rx(r"(opening it filled|openings they filled)"), END)))
    S.append(("move_wall_with_fillings", seq(
        MOVE, " ", T, " ", ("mv", MOVEDIR), ", and move ",
        ("count", HOSTED_COUNT), " it hosts by the same offset so ",
        rx(r"(it stays|they stay)"), " in the wall", END)))
    S.append(("move_space_with_bounding_walls", seq(
        MOVE, " ", T, " ", ("mv", MOVEDIR), ", and move the ", ("n", NUM),
        " walls that bound it by the same offset", END)))
    # ------------------------------------------------------- create family
    S.append(("copy_element", seq(
        rx(r"(Copy|Duplicate)(?= )"), " ", T, " ", ("mv", MOVEDIR),
        ", and name the copy ", ("name", quoted()), END)))
    S.append(("array_elements", seq(
        "Make ", ("n", NUM), " copies of ", T, " at a spacing of ",
        ("mv", MOVEDIR), ", named ", ("names", NAMES), " in that order",
        END)))
    S.append(("replace_filling", seq(
        "Replace ", T, " with a ", ("fam", NOUN), " named ", ("name", quoted()),
        ", ", ("w", LEN), " wide and ", ("h", LEN), " high, at the same "
        "position along the wall and ", ("sill", SILL), ". Cut the opening it "
        "fills and take the old opening out with the element it held", END)))
    S.append(("create_filling", seq(
        ADD, " a new ", ("fam", NOUN), " named ", ("name", quoted()), " in ",
        T, ", ", ("w", LEN), " wide and ", ("h", LEN), " high, ",
        ("fw", FILL_WHERE), " and ", ("sill", SILL), ". Cut the opening it fills",
        ("end", REST))))
    S.append(("create_box", seq(
        ADD, " a new ", ("fam", NOUN), " named ", ("name", quoted()), " on ",
        ("where", WHERE), ", ", ("der", DERIVED), ("*", PREDEF),
        ("end", REST))))
    S.append(("create_box", seq(
        ADD, " a new ", ("fam", NOUN), " named ", ("name", quoted()), " on ",
        ("where", WHERE), ", running from ", ("p1", POINT), " to ",
        ("p2", POINT), " with a thickness of ", ("t", LEN), " in the ",
        ("tdir", rx(r"([+-][xy])", lambda m: m.group(1))),
        " direction and a height of ", ("h", LEN), ("*", PREDEF),
        ("end", REST))))
    S.append(("create_box", seq(
        ADD, " a new ", ("fam", NOUN), " named ", ("name", quoted()), " on ",
        ("where", WHERE), ", ", ("size", SIZE), ("bp", BOX_POSITION),
        ("*", PREDEF), ("end", REST))))
    # under-specified create: the storey is left out
    S.append(("clarify_storey", seq(
        ADD, " a new ", ("fam", NOUN), " named ", ("name", quoted()), ", ",
        ("size", SIZE), ", with its base corner at ", ("p", POINT),
        " in the storey's own coordinates", END)))
    # ------------------------------------------------------- update family
    S.append(("move_to_storey", seq(
        MOVE, " ", T, " into ", ("st", STOREY),
        ", leaving it exactly where it stands in the building",
        ("c", CONSTRAINT), END)))
    S.append(("move_to_storey_keep", seq(
        MOVE, " ", T, " into ", ("st", STOREY),
        ", keeping the position it has inside its storey, so it ",
        ("way", rx(r"(rises|drops)", lambda m: m.group(1))), " by ",
        ("d", LEN), ("c", CONSTRAINT), END)))
    S.append(("rehost_filling", seq(
        MOVE, " ", T, " into ", ("wall", REFEL), ", ", ("along", LEN),
        " along that wall from its start point, carrying the opening it fills "
        "with it and leaving the wall it came from whole", ("c", CONSTRAINT),
        END)))
    S.append(("translate", seq(MOVE, " ", T, " ", ("mv", MOVEDIR),
                               ("c", CONSTRAINT), END)))
    S.append(("clarify_move", seq(
        MOVE, " ", ("t", TARGET), " to the ", DIRW, " (", AXW, ")", END)))
    S.append(("resize", seq(
        SETV, " the ", ("dim", DIMWORD), " of ", T, " from ",
        opt(lit("about ")), ("old", LEN), " to ", ("new", LEN),
        ("c", CONSTRAINT), END)))
    S.append(("resize_batch", seq(
        SETV, " the ", ("dim", DIMWORD), " of ", ("t", SET), " to ",
        ("new", LEN), END)))
    S.append(("clarify_resize", seq(
        SETV, " the ", ("dim", DIMWORD), " of ", ("t", TARGET), END)))
    S.append(("rename", seq("Rename ", T, " to ", ("new", quoted()),
                            ("c", CONSTRAINT), END)))
    S.append(("clarify_rename", seq("Rename ", ("t", TARGET), END)))
    S.append(("retype", seq(SETV, " the predefined type of ",
                            ("t", TARGET_SET_BARE), " to ",
                            ("new", rx(r"[A-Z_]+")), ("c", CONSTRAINT), END)))
    S.append(("rotate", seq(
        rx(r"(Rotate|Turn)(?= )"), " ", T, " by ", ("deg", NUM),
        " degrees counter-clockwise about the vertical axis, turning it about ",
        ("pivot", rx(r"(its own placement origin|the centre of its plan)",
                     lambda m: "origin" if "origin" in m.group(1)
                     else "centre")), ("c", CONSTRAINT), END)))
    S.append(("clarify_rotate", seq(
        rx(r"(Rotate|Turn)(?= )"), " ", ("t", TARGET),
        " counter-clockwise about the vertical axis", END)))
    S.append(("mirror_wall", seq(
        rx(r"(Mirror|Reflect)(?= )"), " ", T, " across the vertical plane that "
        "follows the axis of the wall named ", ("wall", quoted()),
        ("c", CONSTRAINT), END)))
    S.append(("mirror_plane", seq(
        rx(r"(Mirror|Reflect)(?= )"), " ", T, " across the vertical plane at ",
        ("axis", rx(r"[xy]")), " = ", ("v", LEN), ("c", CONSTRAINT), END)))
    S.append(("set_pset", seq(
        SETV, " the ", ("prop", PROPWORD), " of ", ("t", TARGET_SET_BARE),
        " in ", ("pset", PSET), " from ", ("old", VALUE), " to ", ("val", VALUE),
        ("c", CONSTRAINT), END)))
    S.append(("set_pset", seq(
        SETV, " the ", ("prop", PROPWORD), " of ", ("t", TARGET_SET_BARE),
        " in ", ("pset", PSET), " to ", ("val", VALUE), ("c", CONSTRAINT),
        END)))
    S.append(("assign_material", seq(
        SETV, " the material of ", T, " to ", ("mat", quoted()),
        ("c", CONSTRAINT), END)))
    S.append(("assign_material", seq(
        "Assign the material ", ("mat", quoted()), " to ",
        ("t", TARGET_SET_BARE), ("c", CONSTRAINT), END)))
    S.append(("assign_type", seq(
        "Assign ", T, " to the type object named ", ("type", quoted()),
        ("c", CONSTRAINT), END)))
    # ------------------------------------------------------- delete family
    S.append(("delete", seq(
        DEL, " ", ("t", TARGET_SET_BARE), " from the model, together with the "
        "relationships that depend on ", rx(r"(it|them)"), ("c", CONSTRAINT),
        END)))
    S.append(("delete", seq(
        DEL, " ", T, " from the model, and delete with it ", ("cl", REST))))
    S.append(("delete", seq(DEL, " ", T, " together with ", ("cl", REST))))
    S.append(("delete", seq(DEL, " ", T, ". Remove ", ("cl", REST))))
    S.append(("delete", seq("Take ", T, " out of the model, and take ",
                            ("cl", REST))))
    return S


SENTENCES = _sentences()

CONTEXT_PREFIXES = (
    "The client wants one change made to this model. ",
    "The design team has agreed on one change to this model. ",
    "The client has asked for the following change. ",
)


def normalise(instruction: str) -> tuple[str, dict]:
    """Undo the request-form wording: context prefix, please, can you."""
    text = instruction.strip()
    form = {"context": None, "request": "imperative"}
    for prefix in CONTEXT_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            form["context"] = prefix.strip()
            break
    if text.startswith("Please "):
        text = text[7:]
        text = text[:1].upper() + text[1:]
        form["request"] = "please"
    elif text.startswith("Can you ") and text.endswith("?"):
        text = text[8:-1] + "."
        text = text[:1].upper() + text[1:]
        form["request"] = "question"
    return text, form


def parse(instruction: str) -> dict:
    """The intent one instruction states, or ``{"recognised": False}``."""
    text, form = normalise(instruction)
    for kind, parser in SENTENCES:
        for value, rest in parser(text):
            if rest != "":
                continue
            intent = _finish(kind, value)
            if intent is None:
                continue
            intent["form"] = form
            intent["recognised"] = True
            return intent
    return {"recognised": False, "form": form, "text": text}


def _finish(kind: str, v: dict) -> dict | None:
    """Turn one parse into an intent, checking the free tails."""
    t = v.get("t")
    if kind == "create_filling":
        rel = _relation_tail(v.get("end", ""), first=".")
        if rel is False:
            return None
        v = dict(v, relation=rel)
    if kind == "create_box":
        tail = v.get("end", "")
        rel = _relation_tail(tail, first=".")
        if rel is False:
            return None
        v = dict(v, relation=rel)
    if kind == "delete" and "cl" in v:
        if not v["cl"].endswith("."):
            return None
    v = {k: val for k, val in v.items() if k not in ("end",)}
    if isinstance(t, dict) and t.get("k") == "bare":
        return {"op": kind, "clarify": "element", "fam": t["fam"], "parse": v}
    if kind == "clarify_storey":
        return {"op": kind, "clarify": "storey", "fam": v["fam"], "parse": v}
    if kind in ("clarify_move", "clarify_resize", "clarify_rename",
                "clarify_rotate"):
        return {"op": kind, "clarify": "dimension",
                "fam": (t or {}).get("fam"), "dim": v.get("dim"), "parse": v}
    return {"op": kind, "clarify": None, "parse": v}


def _relation_tail(tail: str, first: str):
    """The relationship clause that may follow a create sentence."""
    if tail == first:
        return None
    if not tail.startswith(first):
        return False
    rest = tail[len(first):]
    for value, r in RELATION(rest):
        if r == "":
            return value
    return False
