"""Inspection rounds, derived from a task's anchor metadata.

A task record stores the predicate behind its instruction's phrase: the kind of
anchor, and the parameters the generator checked it with. This module turns that
predicate into Python the model runs in the sandbox, so the trajectory resolves
the phrase the way a reader would have to, on the model itself.

Nothing here fabricates a result. The snippet is generated, executed against the
working copy of the source model, and the trajectory is only kept when the round
really printed the identifier the anchor is supposed to single out.

Two rounds are available. The first resolves the anchor. The second reads the
element the first one found, which is what a careful answer does before editing
anything: it confirms the class, where the element sits, and what depends on it.

Version 0.7.0 of the generator writes nine further anchor kinds and seven
further edits, and each of them needs a lookup of its own before the edit can
name what it touches. A phrase that picks the nearest element, the one between
two others, the one on the left as seen through a door, or every element of a
storey over a stated height is resolved here the way the generator resolved it,
from the elements' own bodies rather than from their placement origins. An edit
that re-hosts a door, moves an element to another storey, gives it a material or
writes a property on it gets a round that lists what the model already holds, so
the name or the identifier the edit uses is one the trajectory has read.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from .style import Style

FAMILY_CLASS = {
    "wall": "IfcWall",
    "slab": "IfcSlab",
    "space": "IfcSpace",
    "door": "IfcDoor",
    "window": "IfcWindow",
    "column": "IfcColumn",
    "storey": "IfcBuildingStorey",
}

AXIS_WORDS = {
    (0, 1): "east (+X)", (0, -1): "west (-X)",
    (1, 1): "north (+Y)", (1, -1): "south (-Y)",
    (2, 1): "up (+Z)", (2, -1): "down (-Z)",
}


@dataclass
class Round:
    """One inspection round: the code, and what its output has to contain."""

    code: str
    expect_guids: tuple[str, ...] = ()
    purpose: str = ""


# ------------------------------------------------------------------ preludes

def _prelude_world_point(s: Style) -> str:
    return f"""import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

{s.name('scale')} = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point({s.name('product')}):
    placement = getattr({s.name('product')}, 'ObjectPlacement', None)
    if placement is None:
        return None
    {s.name('matrix')} = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return {s.name('matrix')}[:3, 3] * {s.name('scale')}
"""


def _prelude_on_storey(s: Style) -> str:
    return f"""def contained_elements(structure):
    found = []
    for {s.name('relation')} in getattr(structure, 'ContainsElements', None) or ():
        found.extend({s.name('relation')}.RelatedElements or ())
    for {s.name('relation')} in getattr(structure, 'IsDecomposedBy', None) or ():
        for child in {s.name('relation')}.RelatedObjects or ():
            if child.is_a('IfcSpatialStructureElement') or child.is_a('IfcSpatialElement'):
                found.append(child)
                found.extend(contained_elements(child))
            else:
                found.append(child)
    return found


def on_storey(storey_guid, ifc_class):
    return [e for e in contained_elements(ifc.by_guid(storey_guid))
            if e.is_a(ifc_class)]
"""


def _prelude_by_name(s: Style) -> str:
    """Find an element by the name the instruction quotes.

    The instruction names the elements its phrase refers to, and the model is
    what turns such a name into an identifier. The lookup prints what it found,
    so the identifier is on the record before any later round uses it, and it
    refuses to guess when a name does not single out one element. The names
    inside are literals rather than style draws, because the line that calls the
    lookup and the body that uses its result are written apart.
    """
    return """def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]
"""


def _prelude_relations(s: Style) -> str:
    """The relationship maps the generator indexes, read the same way.

    The names inside are literals rather than drawn from the style pools,
    because a relative anchor and the edit that follows it can both need them
    and two draws of one pool can collide.
    """
    return """def relation_index():
    hosted, host_of, space_elements = {}, {}, {}
    for relation in ifc.by_type('IfcRelVoidsElement'):
        opening = relation.RelatedOpeningElement
        host = relation.RelatingBuildingElement
        if opening is None or host is None:
            continue
        for fills in getattr(opening, 'HasFillings', None) or ():
            filling = fills.RelatedBuildingElement
            if filling is None:
                continue
            host_of[filling.GlobalId] = host.GlobalId
            hosted.setdefault(host.GlobalId, []).append(filling.GlobalId)
    for relation in ifc.by_type('IfcRelSpaceBoundary'):
        space = relation.RelatingSpace
        bounder = relation.RelatedBuildingElement
        if space is None or bounder is None:
            continue
        space_elements.setdefault(space.GlobalId, []).append(bounder.GlobalId)
    for mapping in (hosted, space_elements):
        for key, values in mapping.items():
            mapping[key] = sorted(dict.fromkeys(values))
    return hosted, host_of, space_elements


HOSTED, HOST_OF, SPACE_ELEMENTS = relation_index()
"""


def _prelude_geometry(s: Style) -> str:
    """Where an element stands, read from its body rather than its origin.

    A wall's placement origin sits at one end of it, so a phrase like "nearest"
    or "between" resolved from the origin means something a reader looking at
    the model cannot see. The generator resolves those phrases from the centre
    of the element's world bounding box, and so does this.
    """
    return f"""import ifcopenshell.geom

GEOM_SETTINGS = ifcopenshell.geom.settings()
GEOM_SETTINGS.set('use-world-coords', True)
BOX_CACHE = {{}}


def world_box(product):
{s.comment('geometry', '    ')}    guid_key = product.GlobalId
    if guid_key in BOX_CACHE:
        return BOX_CACHE[guid_key]
    box = None
    try:
        shape = ifcopenshell.geom.create_shape(GEOM_SETTINGS, product)
        points = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
        if points.size:
            box = (points.min(axis=0), points.max(axis=0))
    except Exception:
        box = None
    BOX_CACHE[guid_key] = box
    return box


def body_centre(product):
    box = world_box(product)
    if box is not None:
        return (box[0] + box[1]) / 2.0
    return world_point(product)
"""


def _prelude_measure(s: Style) -> str:
    """One measurement of an element in metres, the way the set phrase reads it."""
    return f"""def measure(product, name):
    if name == 'overall_width':
        value = getattr(product, 'OverallWidth', None)
        return None if value is None else float(value) * {s.name('scale')}
    box = world_box(product)
    if box is None:
        return None
    size = box[1] - box[0]
    if name == 'height':
        return float(size[2])
    if name == 'plan_length':
        return float(max(size[0], size[1]))
    return None
"""


#: The order the preludes are written in, since each one uses the one before it.
_PRELUDE_ORDER = ("world_point", "on_storey", "by_name", "relations", "geometry",
                  "measure")

_PRELUDE_BUILDERS = {
    "world_point": _prelude_world_point,
    "on_storey": _prelude_on_storey,
    "by_name": _prelude_by_name,
    "relations": _prelude_relations,
    "geometry": _prelude_geometry,
    "measure": _prelude_measure,
}


# ------------------------------------------------------- per-kind resolution

#: The variable each anchor parameter is bound to inside a resolve round. The
#: names are literals rather than style draws, because the lookup line and the
#: body that uses its result are generated apart and two draws of one pool
#: collide.
KEY_VAR = {
    "guid": "named_target",
    "storey_guid": "storey",
    "scope_guid": "scope",
    "space_guid": "space",
    "space_a_guid": "space_a",
    "space_b_guid": "space_b",
    "reference_guid": "reference",
    "a_guid": "first",
    "b_guid": "second",
    "host_guid": "host",
    "other_guid": "named_other",
    "door_guid": "door",
    "element_guid": "named_element",
    "element_b_guid": "named_element_b",
}

#: The order the name lookups are written in. The storey comes first, since a
#: name two elements share is told apart by the storey the instruction names.
LOOKUP_ORDER = ("storey_guid", "scope_guid", "space_guid", "space_a_guid",
                "space_b_guid", "reference_guid", "a_guid", "b_guid",
                "host_guid", "other_guid", "door_guid", "element_guid",
                "element_b_guid", "guid")


@dataclass
class Ref:
    """An element the instruction names, found in the model by that name.

    ``on_storey`` holds the variable of the storey that tells the element apart
    from another of the same class carrying the same name; it is empty when the
    name is already unique in the model.
    """

    ifc_class: str
    name: str
    on_storey: str = ""


@dataclass
class GuidRef:
    """An element the instruction gives by its identifier.

    The lookup is one call, ``ifc.by_guid``, and the line after it prints what
    the identifier resolved to in the shape every lookup round prints a row:
    identifier, class and name, marked as the element the instruction gave, so
    the reference is on the record before the round uses it.
    """

    guid: str


def is_name_ref(ref) -> bool:
    return isinstance(ref, Ref)


def _lookup_lines(refs: dict, s: Style) -> list[str]:
    """One line per named element, binding it to the variable the body uses."""
    lines: list[str] = []
    for key in LOOKUP_ORDER:
        ref = refs.get(key)
        if ref is None:
            continue
        var = KEY_VAR[key]
        if isinstance(ref, GuidRef):
            lines.append(f"{var} = ifc.by_guid({s.string(ref.guid)})")
            lines.append(f"print('given ->', {var}.GlobalId, {var}.is_a(),"
                         f" {var}.Name)")
            continue
        if ref.on_storey:
            lines.append(f"{var} = by_name_on_storey({s.string(ref.ifc_class)},"
                         f" {s.string(ref.name)}, {ref.on_storey})")
        else:
            lines.append(f"{var} = by_name({s.string(ref.ifc_class)},"
                         f" {s.string(ref.name)})")
    return lines


#: The direction word each world axis and sign is written with, as the
#: instruction writes it.
DIRECTION_WORDS = {(0, 1): "east", (0, -1): "west", (1, 1): "north",
                   (1, -1): "south", (2, 1): "up", (2, -1): "down"}

#: Which side a row is counted from, given the direction the order runs in.
#: "the first window from the south" runs north, so the phrase names the south.
COUNTED_FROM = {"east": "west", "west": "east",
                "north": "south", "south": "north"}


def stated_distance(phrase: str, params: dict) -> float:
    """The distance the instruction writes, read off the phrase itself.

    The phrase carries one decimal ("about 24.1 m east"), while the task record
    keeps two, so the number the emitted call writes is the one the reader has.
    """
    found = re.search(r"about\s+([0-9]+(?:\.[0-9]+)?)\s*m\b", phrase or "")
    if found:
        return float(found.group(1))
    return round(float(params["distance"]), 1)


def _geom_resolve(kind: str, params: dict, ifc_class: str, s: Style,
                  phrase: str, name_of) -> tuple[list[str], set[str]]:
    """The one library call that turns the instruction's phrase into an element.

    Every argument is something the sentence carries: the elements it names,
    the class, the storey, a direction word, a stated distance.  The rules the
    sentence leaves out live in the library, so the round holds no tolerance
    the reader could not have known.
    """
    cls = s.string(ifc_class)

    if kind == "offset":
        word = DIRECTION_WORDS[(int(params["axis"]), int(params["sign"]))]
        return ([f"geom.find_offset({name_of('reference_guid')}, {cls},"
                 f" {name_of('storey_guid')},",
                 f"                 {s.string(word)},"
                 f" {stated_distance(phrase, params)!r})"], set())

    if kind == "extreme":
        word = DIRECTION_WORDS[(int(params["axis"]), int(params["sign"]))]
        return ([f"geom.find_extreme({cls}, {name_of('storey_guid')},"
                 f" {s.string(word)})"], set())

    if kind == "nearest":
        return ([f"geom.find_nearest({name_of('reference_guid')}, {cls},",
                 f"                  {name_of('storey_guid')})"], set())

    if kind == "between":
        return ([f"geom.find_between({name_of('a_guid')}, {name_of('b_guid')},",
                 f"                  {cls}, {name_of('storey_guid')})"], set())

    if kind == "ordinal":
        word = DIRECTION_WORDS[(int(params["axis"]), int(params["sign"]))]
        return ([f"geom.find_ordinal({name_of('host_guid')}, {cls},",
                 f"                  {s.string(COUNTED_FROM[word])},"
                 f" {int(params['index']) + 1})"], set())

    if kind == "opposite":
        return ([f"geom.find_opposite({name_of('reference_guid')}, {cls},",
                 f"                   {name_of('space_guid')})"], set())

    if kind == "egocentric":
        return ([f"geom.find_beside_door({name_of('door_guid')},"
                 f" {name_of('space_guid')},",
                 f"                      {s.string(params['side'])}, {cls})"],
                set())

    if kind == "above_below":
        return ([f"geom.find_above_below({name_of('reference_guid')}, {cls},",
                 f"                      {s.string(params['direction'])},"
                 f" storey={name_of('storey_guid')})"], set())

    if kind == "host_of":
        return ([f"geom.find_host({name_of('element_guid')})"], set())

    if kind == "joins":
        if params.get("outside"):
            second = s.string("the outside")
        else:
            second = name_of("space_b_guid")
        return ([f"geom.find_filling_between({name_of('space_a_guid')},"
                 f" {second},",
                 f"                          {cls})"], set())

    if kind == "bounds":
        return ([f"geom.find_bounding({name_of('space_guid')}, {cls})"], set())

    if kind == "under":
        return ([f"geom.find_under({name_of('storey_guid')}, {cls})"], set())

    if kind == "without_relation":
        return ([f"geom.find_without({name_of('storey_guid')}, {cls},",
                 f"                  {s.string(params['relation'])})"], set())

    if kind == "negation":
        variant = params["variant"]
        if variant == "wall_without_filling":
            excluded = (f"({s.string('IfcDoor')}, {s.string('IfcWindow')})")
            scope = name_of("storey_guid")
        elif variant == "space_without_boundary":
            excluded = s.string(FAMILY_CLASS[params["missing"]])
            scope = name_of("storey_guid")
        elif variant == "bounding_wall_without_filling":
            excluded = s.string(FAMILY_CLASS[params["missing"]])
            scope = name_of("space_guid")
        else:
            raise KeyError(f"no library lookup for negation variant {variant!r}")
        return ([f"geom.find_without({scope}, {cls},",
                 f"                  {excluded})"], set())

    raise KeyError(f"no library lookup for anchor kind {kind!r}")


#: The anchor kinds the library resolves on its own.  Each of them used to be
#: written out as a predicate carrying the generator's own tolerances, which
#: are numbers no reader of the instruction has.
GEOM_LOOKUPS = ("offset", "extreme", "nearest", "between", "ordinal",
                "opposite", "egocentric", "above_below", "negation",
                "host_of", "joins", "bounds", "under", "without_relation")


def _resolve_body(kind: str, params: dict, ifc_class: str, s: Style,
                  refs: dict | None = None, phrase: str = "") -> tuple[str, set[str]]:
    """Code that fills ``matches``, and the preludes it needs.

    ``refs`` names the parameters the instruction gives in words rather than as
    an identifier. Each of them is looked up by that name before the body runs,
    so the code holds no identifier the instruction did not carry.
    """
    refs = refs or {}
    m = s.name("matches")
    needs: set[str] = set()
    if any(is_name_ref(ref) for ref in refs.values()):
        needs.add("by_name")
        if any(is_name_ref(ref) and ref.on_storey for ref in refs.values()):
            needs.add("on_storey")
    head = _lookup_lines(refs, s)

    def gid(key: str) -> str:
        """The identifier of one parameter, as an expression."""
        if key in refs:
            return f"{KEY_VAR[key]}.GlobalId"
        return s.string(params[key])

    def bind(key: str) -> list[str]:
        """Bind a parameter the body needs as an object, if a lookup has not."""
        if key in refs:
            return []
        return [f"{KEY_VAR[key]} = ifc.by_guid({s.string(params[key])})"]

    def done(lines: list[str], extra: set[str] = frozenset()) -> tuple[str, set[str]]:
        needs.update(extra)
        return ("\n".join(head + lines), needs)

    if s.geom_lib and kind in GEOM_LOOKUPS:
        # One library call, with the arguments the sentence carries.  The
        # elements it names are bound first, by name where the sentence gives a
        # name and by identifier where it gives one.
        bound: list[str] = []
        for key in LOOKUP_ORDER:
            if key in params and key in KEY_VAR:
                bound.extend(bind(key))
        call, extra = _geom_resolve(kind, params, ifc_class, s, phrase,
                                    lambda key: KEY_VAR[key])
        call[0] = f"{m} = [" + call[0]
        call[-1] = call[-1] + "]"
        pad = " " * (len(m) + 4)
        lines = [call[0]] + [pad + line for line in call[1:]]
        return done(bound + lines, extra)

    if kind == "guid":
        if "guid" in refs:
            return done([f"{m} = [named_target]"])
        return done([f"{m} = [ifc.by_guid({s.string(params['guid'])})]"])

    if kind == "name":
        return done([
            f"{m} = [e for e in ifc.by_type({s.string(ifc_class)})",
            f"       if (e.Name or '').strip() == {s.string(params['name'])}]",
        ])

    if kind == "in_storey":
        return done([f"{m} = on_storey({gid('storey_guid')}, {s.string(ifc_class)})"],
                    {"on_storey"})

    if kind == "hosted":
        return done(bind("host_guid") + [
            f"{m} = []",
            f"for {s.name('relation')} in getattr(host, 'HasOpenings', None) or ():",
            f"    {s.name('opening')} = {s.name('relation')}.RelatedOpeningElement",
            f"    for fills in (getattr({s.name('opening')}, 'HasFillings', None) or ()) if {s.name('opening')} else ():",
            f"        {s.name('filling')} = fills.RelatedBuildingElement",
            f"        if {s.name('filling')} is not None and {s.name('filling')}.is_a({s.string(ifc_class)}):",
            f"            {m}.append({s.name('filling')})",
        ])

    if kind == "bounding":
        return done([
            f"bounded = {{}}",
            f"for {s.name('relation')} in ifc.by_type('IfcRelSpaceBoundary'):",
            f"    {s.name('room')} = {s.name('relation')}.RelatingSpace",
            f"    {s.name('product')} = {s.name('relation')}.RelatedBuildingElement",
            f"    if {s.name('room')} is None or {s.name('product')} is None:",
            f"        continue",
            f"    bounded.setdefault({s.name('product')}.GlobalId, set()).add({s.name('room')}.GlobalId)",
            f"{m} = [e for e in ifc.by_type({s.string(ifc_class)})",
            f"       if {{{gid('space_a_guid')}, {gid('space_b_guid')}}}",
            f"       <= bounded.get(e.GlobalId, set())]",
        ])

    if kind == "space_of" and params.get("element_b_guid"):
        # Two elements the room is bounded by: the room both of them bound.
        return done([
            f"rooms_of = {{}}",
            f"for {s.name('relation')} in ifc.by_type('IfcRelSpaceBoundary'):",
            f"    {s.name('product')} = {s.name('relation')}.RelatedBuildingElement",
            f"    {s.name('room')} = {s.name('relation')}.RelatingSpace",
            f"    if {s.name('product')} is None or {s.name('room')} is None:",
            f"        continue",
            f"    if {s.name('room')}.is_a({s.string(ifc_class)}):",
            f"        rooms_of.setdefault({s.name('product')}.GlobalId, {{}})"
            f"[{s.name('room')}.GlobalId] = {s.name('room')}",
            f"first_rooms = rooms_of.get({gid('element_guid')}, {{}})",
            f"second_rooms = rooms_of.get({gid('element_b_guid')}, {{}})",
            f"{m} = [first_rooms[g] for g in sorted(first_rooms) if g in second_rooms]",
        ])

    if kind == "space_of":
        return done([
            f"{m} = []",
            f"for {s.name('relation')} in ifc.by_type('IfcRelSpaceBoundary'):",
            f"    {s.name('product')} = {s.name('relation')}.RelatedBuildingElement",
            f"    {s.name('room')} = {s.name('relation')}.RelatingSpace",
            f"    if {s.name('product')} is None or {s.name('room')} is None:",
            f"        continue",
            f"    if {s.name('product')}.GlobalId == {gid('element_guid')} \\",
            f"            and {s.name('room')}.is_a({s.string(ifc_class)}):",
            f"        {m}.append({s.name('room')})",
            f"{m} = list({{e.GlobalId: e for e in {m}}}.values())",
        ])

    if kind == "connects":
        return done([
            f"{m} = []",
            f"for {s.name('relation')} in ifc.by_type('IfcRelConnectsElements'):",
            f"    left, right = {s.name('relation')}.RelatingElement, {s.name('relation')}.RelatedElement",
            f"    if left is None or right is None:",
            f"        continue",
            f"    if left.GlobalId == {gid('other_guid')} and right.is_a({s.string(ifc_class)}):",
            f"        {m}.append(right)",
            f"    elif right.GlobalId == {gid('other_guid')} and left.is_a({s.string(ifc_class)}):",
            f"        {m}.append(left)",
            f"{m} = list({{e.GlobalId: e for e in {m}}}.values())",
        ])

    if kind == "extreme":
        axis, sign = int(params["axis"]), int(params["sign"])
        return done([
            f"{s.name('candidates')} = on_storey({gid('storey_guid')},"
            f" {s.string(ifc_class)})",
            f"placed = [(world_point(e), e) for e in {s.name('candidates')}]",
            f"placed = [(p, e) for p, e in placed if p is not None]",
            f"best = max(float(p[{axis}]) * {sign} for p, e in placed)",
            f"{m} = [e for p, e in placed",
            f"       if float(p[{axis}]) * {sign} >= best - {float(params['margin'])!r}]",
        ], {"world_point", "on_storey"})

    if kind == "offset":
        axis, sign = int(params["axis"]), int(params["sign"])
        return done(bind("reference_guid") + [
            f"origin = world_point(reference)",
            f"{s.name('candidates')} = on_storey({gid('storey_guid')},"
            f" {s.string(ifc_class)})",
            f"{m} = []",
            f"for e in {s.name('candidates')}:",
            f"    point = world_point(e)",
            f"    if point is None or e.GlobalId == reference.GlobalId:",
            f"        continue",
            f"    {s.name('offset')} = point - origin",
            f"    if abs(float({s.name('offset')}[{axis}]) * {sign} - {float(params['distance'])!r}) > {float(params['tolerance'])!r}:",
            f"        continue",
            f"    if any(abs(float({s.name('offset')}[other])) > {float(params['lateral_tolerance'])!r}",
            f"           for other in range(3) if other != {axis}):",
            f"        continue",
            f"    {m}.append(e)",
        ], {"world_point", "on_storey"})

    if kind == "separates":
        # The same predicate as ``bounding``: an element that separates two
        # spaces is an element both of them are bounded by.
        return _resolve_body("bounding", params, ifc_class, s, refs)

    if kind == "nearest":
        return done(bind("reference_guid") + [
            f"origin = body_centre(reference)",
            f"{s.name('candidates')} = on_storey({gid('storey_guid')},"
            f" {s.string(ifc_class)})",
            f"ranked = []",
            f"for e in {s.name('candidates')}:",
            f"    point = body_centre(e)",
            f"    if point is None or e.GlobalId == reference.GlobalId:",
            f"        continue",
            f"    ranked.append((float(np.linalg.norm(point - origin)), e))",
            f"best = min(distance for distance, e in ranked)",
            f"{m} = [e for distance, e in ranked",
            f"       if distance <= best + {float(params['margin'])!r}]",
        ], {"world_point", "on_storey", "geometry"})

    if kind == "between":
        axis = int(params["axis"])
        return done(bind("a_guid") + bind("b_guid") + [
            f"a, b = body_centre(first), body_centre(second)",
            f"low, high = sorted((float(a[{axis}]), float(b[{axis}])))",
            f"line = 0.5 * (float(a[{1 - axis}]) + float(b[{1 - axis}]))",
            f"{s.name('candidates')} = on_storey({gid('storey_guid')},"
            f" {s.string(ifc_class)})",
            f"{m} = []",
            f"for e in {s.name('candidates')}:",
            f"    point = body_centre(e)",
            f"    if point is None or e.GlobalId in (first.GlobalId, second.GlobalId):",
            f"        continue",
            f"    if not low + {float(params['inset'])!r} <= float(point[{axis}])"
            f" <= high - {float(params['inset'])!r}:",
            f"        continue",
            f"    if abs(float(point[{1 - axis}]) - line) >"
            f" {float(params['lateral_tolerance'])!r}:",
            f"        continue",
            f"    {m}.append(e)",
        ], {"world_point", "on_storey", "geometry"})

    if kind == "above_below":
        sign = 1.0 if params["direction"] == "above" else -1.0
        return done(bind("reference_guid") + [
            f"origin = body_centre(reference)",
            f"{s.name('candidates')} = on_storey({gid('storey_guid')},"
            f" {s.string(ifc_class)})",
            f"{m} = []",
            f"for e in {s.name('candidates')}:",
            f"    point = body_centre(e)",
            f"    if point is None or e.GlobalId == reference.GlobalId:",
            f"        continue",
            f"    if float(np.linalg.norm((point - origin)[:2])) >"
            f" {float(params['tolerance'])!r}:",
            f"        continue",
            f"    if (float(point[2]) - float(origin[2])) * {sign!r} <= 0.5:",
            f"        continue",
            f"    {m}.append(e)",
        ], {"world_point", "on_storey", "geometry"})

    if kind == "opposite":
        # The reading of "opposite" lives in the library alone: the
        # element parallel to the reference, on the far side of the room's
        # centre along the reference's normal.  The axis rule this style used
        # to write out read the phrase differently, so the round now makes the
        # library style's call, after the same two lookups.
        return done(bind("reference_guid") + bind("space_guid") + [
            f"{m} = [geom.find_opposite(reference, {s.string(ifc_class)},",
            f"{' ' * (len(m) + 23)}space)]",
        ])

    if kind == "egocentric":
        want = 1.0 if params["side"] == "left" else -1.0
        return done(bind("door_guid") + bind("space_guid") + [
            f"host = ifc.by_guid(HOST_OF[door.GlobalId])",
            f"frame = np.array(ifcopenshell.util.placement.get_local_placement(",
            f"    host.ObjectPlacement), dtype=float)",
            f"forward = np.array(frame[:2, 1], dtype=float)",
            f"forward = forward / float(np.linalg.norm(forward))",
            f"middle, origin = body_centre(space), body_centre(door)",
            f"if float(np.dot(forward, (middle - origin)[:2])) < 0:",
            f"    forward = -forward",
            f"left = np.array([-forward[1], forward[0]], dtype=float)",
            f"{m} = []",
            f"for bounder_guid in SPACE_ELEMENTS.get(space.GlobalId, ()):",
            f"    e = ifc.by_guid(bounder_guid)",
            f"    if bounder_guid == door.GlobalId or not e.is_a({s.string(ifc_class)}):",
            f"        continue",
            f"    point = body_centre(e)",
            f"    if point is None:",
            f"        continue",
            f"    if float(np.dot((point - origin)[:2], left)) * {want!r} <"
            f" {float(params['tolerance'])!r}:",
            f"        continue",
            f"    {m}.append(e)",
        ], {"world_point", "relations", "geometry"})

    if kind == "ordinal":
        axis, sign = int(params["axis"]), int(params["sign"])
        return done(bind("host_guid") + [
            f"ranked = []",
            f"for filling_guid in HOSTED.get(host.GlobalId, ()):",
            f"    e = ifc.by_guid(filling_guid)",
            f"    if not e.is_a({s.string(ifc_class)}):",
            f"        continue",
            f"    ranked.append((float(body_centre(e)[{axis}]) * {sign}, e))",
            f"ranked.sort(key=lambda pair: pair[0])",
            f"{m} = [ranked[{int(params['index'])}][1]]",
        ], {"world_point", "relations", "geometry"})

    if kind == "negation":
        variant = params["variant"]
        missing = FAMILY_CLASS[params["missing"]] if params.get("missing") else ""
        if variant == "bounding_wall_without_filling":
            return done(bind("space_guid") + [
                f"{m} = []",
                f"for bounder_guid in SPACE_ELEMENTS.get(space.GlobalId, ()):",
                f"    e = ifc.by_guid(bounder_guid)",
                f"    if not e.is_a('IfcWall'):",
                f"        continue",
                f"    carried = [ifc.by_guid(g) for g in HOSTED.get(bounder_guid, ())]",
                f"    if not any(f.is_a({s.string(missing)}) for f in carried):",
                f"        {m}.append(e)",
            ], {"relations"})
        if variant == "wall_without_filling":
            return done([
                f"{m} = []",
                f"for e in on_storey({gid('storey_guid')}, 'IfcWall'):",
                f"    carried = [ifc.by_guid(g) for g in HOSTED.get(e.GlobalId, ())]",
                f"    if not any(f.is_a('IfcDoor') or f.is_a('IfcWindow')"
                f" for f in carried):",
                f"        {m}.append(e)",
            ], {"relations", "on_storey"})
        if variant == "space_without_boundary":
            return done([
                f"{m} = []",
                f"for {s.name('room')} in on_storey({gid('storey_guid')}, 'IfcSpace'):",
                f"    bounders = [ifc.by_guid(g)",
                f"                for g in SPACE_ELEMENTS.get({s.name('room')}.GlobalId, ())]",
                f"    if not bounders:",
                f"        continue",
                f"    if not any(e.is_a({s.string(missing)}) for e in bounders):",
                f"        {m}.append({s.name('room')})",
            ], {"relations", "on_storey"})
        raise KeyError(f"no inspection query for negation variant {variant!r}")

    if kind == "set" and params.get("scope") == "ids":
        # A set the instruction names by its members' identifiers: one lookup
        # per identifier, in the order the sentence lists them.
        members = ", ".join(f"ifc.by_guid({s.string(g)})"
                            for g in params.get("member_guids") or ())
        return done([f"{m} = [{members}]"])

    if kind == "set":
        scope = params["scope"]
        condition = params.get("condition")
        if s.geom_lib:
            # Where the phrase looks is one library call: a storey holds the
            # class's elements, a wall hosts its doors and windows, a room is
            # bounded by what stands against it.
            reader = {"storey": "geom.on_storey", "host": "geom.hosted_in",
                      "space": "geom.bounding_elements"}.get(scope)
            if reader is None:
                raise KeyError(f"no inspection query for set scope {scope!r}")
            pool = bind("scope_guid") + [
                f"{s.name('candidates')} = {reader}({KEY_VAR['scope_guid']},"
                f" {s.string(ifc_class)})",
                f"print(len({s.name('candidates')}), 'candidate(s) in scope')",
            ]
            if not condition:
                return done(pool + [f"{m} = list({s.name('candidates')})"])
            return done(pool + [
                f"{m} = [e for e in {s.name('candidates')}",
                f"       if (geom.measure(e, {s.string(condition['measure'])})"
                f" or 0.0)",
                f"       > {float(condition['threshold'])!r}]",
            ])
        extra = {"world_point", "relations", "geometry", "measure"}
        if scope == "storey":
            extra.add("on_storey")
            pool = [f"{s.name('candidates')} = on_storey({gid('scope_guid')},"
                    f" {s.string(ifc_class)})"]
        elif scope == "host":
            pool = [f"{s.name('candidates')} = [ifc.by_guid(g) for g in",
                    f"    HOSTED.get({gid('scope_guid')}, ())]",
                    f"{s.name('candidates')} = [e for e in {s.name('candidates')}",
                    f"    if e.is_a({s.string(ifc_class)})]"]
        elif scope == "space":
            pool = [f"{s.name('candidates')} = [ifc.by_guid(g) for g in",
                    f"    SPACE_ELEMENTS.get({gid('scope_guid')}, ())]",
                    f"{s.name('candidates')} = [e for e in {s.name('candidates')}",
                    f"    if e.is_a({s.string(ifc_class)})]"]
        else:
            raise KeyError(f"no inspection query for set scope {scope!r}")
        # The phrase covers a set drawn from this pool, so how many candidates
        # the scope holds is read out before the condition narrows them.
        pool = bind("scope_guid") + pool + [
            f"print(len({s.name('candidates')}), 'candidate(s) in scope')",
        ]
        if not condition:
            return done(pool + [f"{m} = list({s.name('candidates')})"], extra)
        return done(pool + [
            f"{m} = [e for e in {s.name('candidates')}",
            f"       if (measure(e, {s.string(condition['measure'])}) or 0.0)",
            f"       > {float(condition['threshold'])!r}]",
        ], extra)

    raise KeyError(f"no inspection query for anchor kind {kind!r}")


_PURPOSE = {
    "guid": "read the element the instruction names by GlobalId",
    "name": "find the element the instruction names",
    "in_storey": "list what the storey holds, of the class the instruction names",
    "hosted": "follow the host's openings to what fills them",
    "bounding": "find the element that bounds both named spaces",
    "space_of": "find the space the named element bounds",
    "connects": "follow the connection from the named element",
    "extreme": "find the element furthest along the axis the instruction names",
    "offset": "find the element at the stated offset from the named neighbour",
    "separates": "find the element that stands between the two named spaces",
    "nearest": "find the element closest to the one the instruction names",
    "between": "find the element standing between the two the instruction names",
    "above_below": "find the element directly over or under the named one",
    "opposite": "find the element facing the named one across the space",
    "egocentric": "find the element on the named side, seen through the door",
    "ordinal": "count the fillings along the wall and take the one asked for",
    "negation": "find the element that carries none of what the instruction excludes",
    "set": "list every element the instruction's phrase covers",
    "host_of": "follow the named door or window to the wall it sits in",
    "joins": "find the element in the wall between the rooms the instruction names",
    "bounds": "find the element that bounds the room the instruction names",
    "under": "find the element the storey's walls stand on",
    "without_relation": "find the element that takes part in no such relationship",
}


def _report(s: Style, variable: str) -> str:
    """How a round tells the reader what it found."""
    if s.report == "result":
        return (
            f"result = [(e.GlobalId, e.is_a(), e.Name) for e in {variable}]"
        )
    if s.report == "print_rows":
        return (
            f"print(len({variable}), 'match(es)')\n"
            f"for e in {variable}:\n"
            f"    print(e.GlobalId, e.is_a(), e.Name)"
        )
    return (
        f"for e in {variable}:\n"
        f"    print(e.GlobalId, e.is_a(), e.Name)"
    )


def resolve_round(anchor: dict, style: Style,
                  refs: dict | None = None) -> Round:
    """The round that turns the instruction's phrase into an identifier.

    ``refs`` carries the parameters the instruction gives by name. Each one is
    looked up in the model before the predicate runs, so the round holds no
    identifier the instruction did not carry and the trajectory shows the step
    a reader has to take.
    """
    kind = anchor["kind"]
    family = anchor["family"]
    ifc_class = FAMILY_CLASS[family]
    params = dict(anchor.get("params") or {})
    body, needs = _resolve_body(kind, params, ifc_class, style, refs,
                                anchor.get("phrase", ""))

    parts: list[str] = []
    comment = _PURPOSE[kind]
    if style.comments:
        parts.append(f"# {comment}")
    prelude = [_PRELUDE_BUILDERS[key](style).rstrip("\n")
               for key in _PRELUDE_ORDER if key in needs]
    code = "\n\n".join(prelude + ["\n".join(parts + [body])])
    code = code + "\n" + _report(style, style.name("matches")) + "\n"
    return Round(code=code, expect_guids=tuple(anchor.get("expected") or ()),
                 purpose=comment)


# --------------------------------------------------------- second inspection

def detail_round(task: dict, guids: tuple[str, ...], style: Style) -> Round:
    """A read of the elements the first round found, before anything is edited."""
    s = style
    operation = task.get("operation", "update")
    listed = ", ".join(s.string(g) for g in guids)
    header = f"for target_guid in ({listed},):" if len(guids) == 1 else \
             f"for target_guid in ({listed}):"

    lines: list[str] = []
    if s.comments:
        lines.append("# read the target before editing it")
    lines.append(_prelude_world_point(s).rstrip("\n"))
    lines.append("")
    lines.append(header)
    lines.append(f"    {s.name('product')} = ifc.by_guid(target_guid)")
    lines.append(
        f"    print({s.name('product')}.is_a(), {s.name('product')}.GlobalId, "
        f"{s.name('product')}.Name)"
    )
    lines.append(f"    point = world_point({s.name('product')})")
    lines.append("    if point is not None:")
    lines.append("        print('  origin (m):', [round(float(v), 3) for v in point])")
    if operation == "delete":
        lines.append(
            f"    print('  openings:', len(getattr({s.name('product')}, 'HasOpenings', None) or ()),"
            f" ' contained in:',"
            f" len(getattr({s.name('product')}, 'ContainedInStructure', None) or ()))"
        )
    else:
        lines.append(
            f"    print('  contained in:',"
            f" [r.RelatingStructure.Name for r in getattr({s.name('product')}, 'ContainedInStructure', None) or ()])"
        )
    return Round(code="\n".join(lines) + "\n", expect_guids=guids,
                 purpose="read the target before editing it")


def storey_round(task: dict, storey_guid: str, style: Style) -> Round:
    """For a create task: read the storey the new element goes on."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# read the storey the new element will be placed on")
    lines.append(_prelude_world_point(s).rstrip("\n"))
    lines.append("")
    lines.append(f"{s.name('storey')} = ifc.by_guid({s.string(storey_guid)})")
    lines.append(
        f"print({s.name('storey')}.is_a(), {s.name('storey')}.GlobalId,"
        f" {s.name('storey')}.Name, {s.name('storey')}.Elevation)"
    )
    lines.append(f"point = world_point({s.name('storey')})")
    lines.append("if point is not None:")
    lines.append("    print('storey origin (m):', [round(float(v), 3) for v in point])")
    lines.append(
        f"print('elements contained:',"
        f" sum(len(r.RelatedElements or ()) for r in getattr({s.name('storey')}, 'ContainsElements', None) or ()))"
    )
    lines.append(f"print('model length unit in metres:', {s.name('scale')})")
    return Round(code="\n".join(lines) + "\n", expect_guids=(storey_guid,),
                 purpose="read the storey the new element goes on")


# ------------------------------------------------------------- discovery

def storeys_round(style: Style) -> Round:
    """List the storeys, which is how a name in the instruction becomes an id."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the instruction names a storey; find which one it is")
    lines.append(f"for {s.name('storey')} in ifc.by_type('IfcBuildingStorey'):")
    lines.append(
        f"    print({s.name('storey')}.GlobalId, repr({s.name('storey')}.Name),"
        f" {s.name('storey')}.Elevation)"
    )
    lines.append("import ifcopenshell.util.unit")
    lines.append(
        f"print('model length unit in metres:',"
        f" ifcopenshell.util.unit.calculate_unit_scale(ifc))"
    )
    return Round(code="\n".join(lines) + "\n", purpose="identify the storey by name")


def storey_of_round(referent_guid: str, style: Style) -> Round:
    """The storey a named element or space sits on, read off that element.

    An instruction that says "on the storey that contains the column named 'X'"
    gives the storey no name, so a listing of every storey in the building shows
    the reader nothing about which one is meant. The link is read instead:
    containment for an element, decomposition for a space, followed up until a
    storey is reached. What is printed is the element, the storey it resolves
    to, and that storey's name and elevation, so the identifier the edit uses
    comes with the reason it was chosen.
    """
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the instruction gives the storey through an element;"
                     " follow the link")
    lines.append(f"{s.name('product')} = ifc.by_guid({s.string(referent_guid)})")
    lines.append(f"{s.name('storey')} = None")
    lines.append(f"for {s.name('relation')} in getattr({s.name('product')},"
                 f" 'ContainedInStructure', None) or ():")
    lines.append(f"    {s.name('storey')} = {s.name('relation')}.RelatingStructure")
    lines.append("    break")
    lines.append(f"if {s.name('storey')} is None:")
    lines.append(f"    for {s.name('relation')} in getattr({s.name('product')},"
                 f" 'Decomposes', None) or ():")
    lines.append(f"        {s.name('storey')} = {s.name('relation')}.RelatingObject")
    lines.append("        break")
    lines.append(f"while {s.name('storey')} is not None and not"
                 f" {s.name('storey')}.is_a('IfcBuildingStorey'):")
    lines.append(f"    parents = getattr({s.name('storey')}, 'Decomposes', None) or ()")
    lines.append(f"    {s.name('storey')} = parents[0].RelatingObject if parents else None")
    lines.append(f"if {s.name('storey')} is None:")
    lines.append("    raise ValueError('the element sits on no storey')")
    lines.append(f"print({s.name('product')}.GlobalId, {s.name('product')}.is_a(),"
                 f" {s.name('product')}.Name, 'is contained in',"
                 f" {s.name('storey')}.GlobalId, {s.name('storey')}.is_a(),"
                 f" {s.name('storey')}.Name, 'elevation',"
                 f" getattr({s.name('storey')}, 'Elevation', None))")
    lines.append("import ifcopenshell.util.unit")
    lines.append("print('model length unit in metres:',"
                 " ifcopenshell.util.unit.calculate_unit_scale(ifc))")
    return Round(code="\n".join(lines) + "\n", expect_guids=(referent_guid,),
                 purpose="read the storey the named element is contained in")


def hosted_round(host_guid: str, style: Style) -> Round:
    """List what a wall hosts, which a deletion of its fillings has to know."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# what the wall hosts, through the openings cut in it")
    lines.append(f"host = ifc.by_guid({s.string(host_guid)})")
    lines.append(f"for {s.name('relation')} in getattr(host, 'HasOpenings', None) or ():")
    lines.append(f"    {s.name('opening')} = {s.name('relation')}.RelatedOpeningElement")
    lines.append(f"    if {s.name('opening')} is None:")
    lines.append("        continue")
    lines.append(f"    for fills in getattr({s.name('opening')}, 'HasFillings', None) or ():")
    lines.append(f"        {s.name('filling')} = fills.RelatedBuildingElement")
    lines.append(f"        if {s.name('filling')} is None:")
    lines.append("            continue")
    lines.append(
        f"        print({s.name('filling')}.GlobalId, {s.name('filling')}.is_a(),"
        f" {s.name('filling')}.Name, 'in opening', {s.name('opening')}.GlobalId)"
    )
    return Round(code="\n".join(lines) + "\n",
                 purpose="list what the host wall carries")


def bounding_round(space_guid: str, style: Style) -> Round:
    """List the elements that bound a space, which moving a space has to know."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the elements that bound the space move with it")
    lines.append(f"for {s.name('relation')} in ifc.by_type('IfcRelSpaceBoundary'):")
    lines.append(f"    space = {s.name('relation')}.RelatingSpace")
    lines.append(f"    {s.name('product')} = {s.name('relation')}.RelatedBuildingElement")
    lines.append(f"    if space is None or {s.name('product')} is None:")
    lines.append("        continue")
    lines.append(f"    if space.GlobalId == {s.string(space_guid)}:")
    lines.append(
        f"        print({s.name('product')}.GlobalId, {s.name('product')}.is_a(),"
        f" {s.name('product')}.Name)"
    )
    return Round(code="\n".join(lines) + "\n",
                 purpose="list the elements bounding the space")


# ------------------------------------------- rounds the 0.7.0 families need

def type_objects_round(family: str, style: Style) -> Round:
    """List the type objects the model already holds, with their names.

    An instruction names the type by its name, so the identifier the assignment
    uses has to come out of the model. The class of the family is tried first
    and the whole type-object list is the fallback, because IFC2X3 does not
    carry every type class IFC4 does.
    """
    s = style
    element_class = FAMILY_CLASS.get(family, "IfcBuildingElement")
    lines: list[str] = []
    if s.comments:
        lines.append("# the type objects the model already defines")
    lines.append(f"{s.name('candidates')} = []")
    lines.append(f"for ifc_class in ({s.string(element_class + 'Type')},"
                 f" 'IfcTypeProduct'):")
    lines.append("    try:")
    lines.append(f"        {s.name('candidates')} = list(ifc.by_type(ifc_class))")
    lines.append("    except Exception:")
    lines.append(f"        {s.name('candidates')} = []")
    lines.append(f"    if {s.name('candidates')}:")
    lines.append("        break")
    lines.append(f"for {s.name('product')} in sorted({s.name('candidates')},"
                 f" key=lambda t: (t.Name or '')):")
    lines.append(f"    print({s.name('product')}.GlobalId, {s.name('product')}.is_a(),"
                 f" {s.name('product')}.Name)")
    return Round(code="\n".join(lines) + "\n",
                 purpose="list the type objects the model defines")


def materials_round(style: Style) -> Round:
    """List the materials already in the model, before one is assigned.

    A material is named rather than identified, so this round is what tells the
    reader whether the name the instruction gives is one the file already uses
    or one the edit has to create.
    """
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the materials the model already carries")
    lines.append(f"{s.name('candidates')} = sorted(")
    lines.append("    {m.Name for m in ifc.by_type('IfcMaterial') if m.Name})")
    lines.append(f"print(len({s.name('candidates')}), 'material(s) in the model')")
    lines.append(f"for {s.name('label')} in {s.name('candidates')}:")
    lines.append(f"    print(' ', {s.name('label')})")
    return Round(code="\n".join(lines) + "\n",
                 purpose="list the materials the model already holds")


def host_round(filling_guid: str, style: Style) -> Round:
    """Find the wall a door or a window currently stands in."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the wall the element stands in now")
    lines.append(f"{s.name('filling')} = ifc.by_guid({s.string(filling_guid)})")
    lines.append(f"for fills in {s.name('filling')}.FillsVoids or ():")
    lines.append(f"    {s.name('opening')} = fills.RelatingOpeningElement")
    lines.append(f"    for voids in ({s.name('opening')}.VoidsElements or ())"
                 f" if {s.name('opening')} else ():")
    lines.append("        host = voids.RelatingBuildingElement")
    lines.append("        if host is None:")
    lines.append("            continue")
    lines.append(f"        print('opening', {s.name('opening')}.GlobalId,"
                 f" 'is cut in', host.GlobalId, host.is_a(), host.Name)")
    return Round(code="\n".join(lines) + "\n",
                 purpose="find the wall the element stands in")


def rehost_candidates_round(filling_guid: str, style: Style) -> Round:
    """The walls a filling could be moved into, and what each already carries.

    The instruction names the destination wall by name, so the identifier has to
    be read off the model. The generator draws the destination from the walls of
    the storey the element already stands on, so that is the list, and each
    wall's length and its existing fillings are printed with it because a
    re-hosted door has to fit between them.
    """
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the walls on this storey, and what each of them carries")
    lines.append(_prelude_relations(s).rstrip("\n"))
    lines.append(_prelude_on_storey(s).rstrip("\n"))
    lines.append("")
    lines.append(f"{s.name('filling')} = ifc.by_guid({s.string(filling_guid)})")
    lines.append("host = None")
    lines.append(f"for fills in {s.name('filling')}.FillsVoids or ():")
    lines.append(f"    {s.name('opening')} = fills.RelatingOpeningElement")
    lines.append(f"    for voids in ({s.name('opening')}.VoidsElements or ())"
                 f" if {s.name('opening')} else ():")
    lines.append("        host = voids.RelatingBuildingElement")
    lines.append("if host is None:")
    lines.append("    raise ValueError('the element stands in no wall')")
    lines.append("print('currently in', host.GlobalId, host.is_a(), host.Name)")
    lines.append(f"{s.name('storey')} = None")
    lines.append("for relation in host.ContainedInStructure or ():")
    lines.append("    structure = relation.RelatingStructure")
    lines.append("    while structure is not None:")
    lines.append("        if structure.is_a('IfcBuildingStorey'):")
    lines.append(f"            {s.name('storey')} = structure")
    lines.append("            break")
    lines.append("        parents = structure.Decomposes or ()")
    lines.append("        structure = parents[0].RelatingObject if parents else None")
    lines.append(f"{s.name('candidates')} = ("
                 f"on_storey({s.name('storey')}.GlobalId, 'IfcWall')")
    lines.append(f"              if {s.name('storey')} is not None else [])")
    lines.append(f"for {s.name('product')} in sorted({s.name('candidates')},"
                 f" key=lambda w: (w.Name or '', w.GlobalId)):")
    lines.append(f"    print({s.name('product')}.GlobalId, {s.name('product')}.Name,")
    lines.append(f"          'carries', len(HOSTED.get({s.name('product')}.GlobalId, ())),"
                 f" 'filling(s)')")
    return Round(code="\n".join(lines) + "\n",
                 purpose="list the walls the element could move into")


#: Gold-call keywords whose value is a length in metres, which an instruction
#: may have quoted in another unit.
LENGTH_KEYS = ("x", "y", "z", "dx", "dy", "dz", "length", "width", "height",
               "along", "across", "sill", "leaf_along", "leaf_across",
               "leaf_sill", "thickness", "leaf_depth", "metres", "depth",
               "value", "x1", "y1", "x2", "y2", "spacing")


def stated_lengths(calls, unit: str) -> list[tuple[float, float]]:
    """Each length the edit uses, as the instruction writes it and in metres."""
    per_unit = {"m": 1.0, "mm": 0.001, "cm": 0.01}.get(unit, 1.0)
    out: list[tuple[float, float]] = []
    for call in calls:
        for key in LENGTH_KEYS:
            if key == "value" and call.func == "set_property_value":
                # A property value is whatever the property holds, and a fire
                # rating or a load is not a length the instruction converted.
                continue
            value = call.kwargs.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            metres = float(value)
            pair = (round(metres / per_unit, 6), metres)
            if pair not in out:
                out.append(pair)
    return out[:8]


def quoted_lengths(code: str, unit: str, instruction: str) -> list[tuple[float, float]]:
    """The lengths the edit writes that the instruction itself quotes.

    The gold call carries numbers the generator worked out from the sentence:
    the near edge of a leaf whose centre the instruction gives, the depth of an
    opening, the corner of an element placed against something else. None of
    those is a number a reader has at this point, so listing them here would put
    a value in the transcript that nothing had shown. What is left is the
    lengths the edit writes and the instruction states, each with the number the
    instruction wrote and the same number in metres.
    """
    from .observed import numbers_in_code, numbers_in_text

    per_unit = {"m": 1.0, "mm": 0.001, "cm": 0.01}.get(unit, 1.0)
    quoted = numbers_in_text(instruction)
    out: list[tuple[float, float]] = []
    for value in numbers_in_code(code, floats_only=True):
        stated = round(value / per_unit, 6)
        if not any(abs(stated - number) <= 1e-6 for number in quoted):
            continue
        pair = (stated, value)
        if pair not in out:
            out.append(pair)
    return out[:8]


def units_round(calls, unit: str, unit_word: str, style: Style,
                code: str = "", instruction: str = "") -> Round:
    """Read the file's own length unit, and convert the stated lengths into it.

    The instruction may quote millimetres or centimetres while the file is
    written in metres, or the other way round, so the conversion is done in code
    against the unit the file declares rather than assumed. ``code`` is the edit
    the round precedes: where it is given, the round lists the lengths that edit
    writes and the instruction quotes, and nothing the generator derived.
    """
    s = style
    pairs = (quoted_lengths(code, unit, instruction) if code
             else stated_lengths(calls, unit))
    lines: list[str] = []
    if s.comments:
        lines.append("# the file's own length unit, and what the stated sizes are in it")
    lines.append("import ifcopenshell.util.unit")
    lines.append(f"{s.name('scale')} = ifcopenshell.util.unit.calculate_unit_scale(ifc)")
    lines.append(f"print('one file length unit is', {s.name('scale')}, 'metres')")
    if pairs:
        listed = ", ".join(f"({stated!r}, {metres!r})" for stated, metres in pairs)
        lines.append(f"for stated, metres in ({listed},):")
        lines.append(f"    print(stated, {s.string(unit_word)}, '=', round(metres, 6),"
                     f" 'm', '=', round(metres / {s.name('scale')}, 6), 'file units')")
    return Round(code="\n".join(lines) + "\n",
                 purpose="read the file's length unit and convert the stated sizes")


def spaces_round(style: Style) -> Round:
    """List the spaces, which is how a room name in the instruction becomes an id."""
    s = style
    lines: list[str] = []
    if s.comments:
        lines.append("# the instruction names a space; find which one it is")
    lines.append(f"for {s.name('product')} in ifc.by_type('IfcSpace'):")
    lines.append(f"    print({s.name('product')}.GlobalId,"
                 f" repr({s.name('product')}.Name),"
                 f" repr(getattr({s.name('product')}, 'LongName', None)))")
    return Round(code="\n".join(lines) + "\n",
                 purpose="identify the space the instruction names")


def named_round(names: Sequence[str], style: Style) -> Round:
    """Find the elements whose name the instruction quotes.

    An instruction that asks for a connection or a boundary names the other end
    by its name, so the identifier the relationship needs is read off the model
    by matching that name rather than assumed.
    """
    s = style
    listed = ", ".join(s.string(name) for name in names)
    lines: list[str] = []
    if s.comments:
        lines.append("# the elements the instruction names")
    lines.append(f"{s.name('wanted')} = {{{listed}}}")
    lines.append(f"for {s.name('product')} in ifc.by_type('IfcProduct'):")
    lines.append(f"    {s.name('label')} = ({s.name('product')}.Name or '',"
                 f" getattr({s.name('product')}, 'LongName', None) or '')")
    lines.append(f"    if {s.name('wanted')}.intersection({s.name('label')}):")
    lines.append(f"        print({s.name('product')}.GlobalId,"
                 f" {s.name('product')}.is_a(), {s.name('product')}.Name)")
    return Round(code="\n".join(lines) + "\n",
                 purpose="find the elements the instruction names")


# ------------------------------------------ measuring, through the sandbox's geom

def wall_box_round(wall_guid: str, style: Style) -> Round:
    """Measure the wall a door or a window is about to be cut into.

    The numbers a filling needs are the wall's own: how long it is, how thick,
    how high, and where its base sits. They are read off the wall rather than
    assumed, and printing them puts them in the transcript, where the position
    the next round writes can be checked against them.
    """
    s = style
    host = "host"
    box = s.name("wall_box")
    lines: list[str] = []
    if s.comments:
        lines.append(f"# {s._comments.get('measure', 'measure the wall')}")
    lines.append(f"{host} = ifc.by_guid({s.string(wall_guid)})")
    lines.append(f"print({host}.GlobalId, {host}.is_a(), {host}.Name)")
    lines.append(f"{box} = geom.wall_box({host})")
    lines.append(f"print('wall (m):', {{k: round(v, 3) for k, v in {box}.items()"
                 f" if not isinstance(v, str)}})")
    return Round(code="\n".join(lines) + "\n", expect_guids=(wall_guid,),
                 purpose="measure the wall the filling goes into")


def filling_slot_round(filling_guid: str, style: Style) -> Round:
    """Read where an existing door or window sits, and the wall that holds it.

    A replacement keeps the position along the wall, so that position is read
    off the opening the old element fills before anything is removed.
    """
    s = style
    old = "old"
    slot = s.name("slot")
    box = s.name("wall_box")
    lines: list[str] = []
    if s.comments:
        lines.append(f"# {s._comments.get('measure', 'measure the wall')}")
    lines.append(f"{old} = ifc.by_guid({s.string(filling_guid)})")
    # The element's own line, because this round can be the first one of the
    # trajectory: the library reads the wall off the element, so an instruction
    # that writes the identifier out needs no lookup before this.
    lines.append(f"print({old}.GlobalId, {old}.is_a(), {old}.Name)")
    lines.append(f"{slot} = geom.filling_slot({old})")
    lines.append(f"host = {slot}['host']")
    lines.append("print('hosted in', host.GlobalId, host.is_a(), host.Name)")
    lines.append(f"print('slot (m):', {{k: round({slot}[k], 3)"
                 f" for k in ('along', 'sill', 'width', 'height')}})")
    lines.append(f"{box} = geom.wall_box(host)")
    lines.append(f"print('wall (m):', {{k: round(v, 3) for k, v in {box}.items()"
                 f" if not isinstance(v, str)}})")
    return Round(code="\n".join(lines) + "\n", expect_guids=(filling_guid,),
                 purpose="read where the element sits in its wall")


def origin_offset_round(reference_guid: str, storey_guid: str,
                        style: Style) -> Round:
    """Read the named element's origin in the storey's own system.

    An instruction that puts a new element so many metres east of a named one
    is measured from that element's origin, in the frame the new coordinate is
    written in, so that origin is read before the offset is added to it.
    """
    s = style
    reference = s.name("reference")
    level = s.name("storey")
    corner = s.name("corner")
    lines: list[str] = []
    if s.comments:
        lines.append(f"# {s._comments.get('place', 'measure the reference')}")
    lines.append(f"{reference} = ifc.by_guid({s.string(reference_guid)})")
    lines.append(f"{level} = ifc.by_guid({s.string(storey_guid)})")
    lines.append(f"{corner} = geom.origin_in_frame({reference}, {level})")
    lines.append(f"print('reference origin in the storey frame (m):',"
                 f" [round(v, 3) for v in {corner}])")
    return Round(code="\n".join(lines) + "\n",
                 purpose="read the origin the offset is measured from")


def on_top_round(reference_guid: str, style: Style) -> Round:
    """Read the top face and the footprint of the element being stood on."""
    s = style
    reference = s.name("reference")
    corner = s.name("corner")
    footprint = s.name("footprint")
    lines: list[str] = []
    if s.comments:
        lines.append(f"# {s._comments.get('place', 'measure the reference')}")
    lines.append(f"{reference} = ifc.by_guid({s.string(reference_guid)})")
    lines.append(f"{corner}, {footprint} = geom.spot_on_top_of({reference})")
    lines.append(f"print('corner on the top face (m):',"
                 f" [round(v, 3) for v in {corner}])")
    lines.append(f"print('footprint (m):', [round(v, 3) for v in {footprint}])")
    return Round(code="\n".join(lines) + "\n",
                 purpose="read the top face the new element stands on")


def beside_wall_round(wall_guid: str, space_guid: str, length: float,
                      width: float, style: Style) -> Round:
    """Read where an element stands against a wall inside a room."""
    s = style
    wall = "wall"
    room = s.name("room")
    corner = s.name("corner")
    lines: list[str] = []
    if s.comments:
        lines.append(f"# {s._comments.get('place', 'measure the reference')}")
    lines.append(f"{wall} = ifc.by_guid({s.string(wall_guid)})")
    lines.append(f"{room} = ifc.by_guid({s.string(space_guid)})")
    lines.append(f"{corner} = geom.spot_beside_wall_in_space("
                 f"{wall}, {room}, {float(length)!r}, {float(width)!r})")
    lines.append(f"print('corner against the wall (m):',"
                 f" [round(v, 3) for v in {corner}])")
    return Round(code="\n".join(lines) + "\n",
                 purpose="read where the element stands against the wall")
