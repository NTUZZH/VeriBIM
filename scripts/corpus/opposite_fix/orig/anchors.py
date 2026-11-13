"""How an instruction points at the element it is about.

An anchor is two things that have to agree: a phrase a person can read, and a
predicate a program can run.  The phrase goes into the instruction; the
predicate is run against the source model and must return the intended element
and nothing else.  A task whose anchor resolves to no element, or to more than
one, is rejected before it reaches the dataset, which is what makes a spatial or
a topological instruction safe to ask for.

Anchors are stored in the task record as a kind plus its parameters, so the
uniqueness check can be repeated later from the record alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import numpy as np

from . import families, idspell, settings
from .scene import AXIS_WORDS, Extent, FAMILIES, Scene

# How many relationship hops each anchor kind asks the reader to follow.  The
# figure is one of the difficulty features and is comparable with BIM-Edit's.
CHAIN_LENGTH = {
    "guid": 0,
    "name": 0,
    "offset": 1,
    "extreme": 1,
    "in_storey": 1,
    "hosted": 2,
    "bounding": 2,
    "space_of": 2,
    "connects": 1,
    # 0.5.0: relative and topological references.
    "nearest": 1,
    "between": 1,
    "above_below": 1,
    "opposite": 2,
    "separates": 2,
    "egocentric": 3,
    # 0.6.0: a set, a place in a row, and the absence of something.
    "set": 2,
    "ordinal": 2,
    "negation": 2,
    # 0.8.0: the references a person writes without thinking about them.
    "host_of": 2,
    "joins": 3,
    "bounds": 2,
    "under": 2,
    "without_relation": 2,
}

# Which instruction style each anchor kind belongs to.
CATEGORY = {
    "guid": "direct",
    "name": "direct",
    "offset": "spatial",
    "extreme": "spatial",
    "in_storey": "topological",
    "hosted": "topological",
    "bounding": "topological",
    "space_of": "topological",
    "connects": "topological",
    "nearest": "spatial",
    "between": "spatial",
    "above_below": "spatial",
    "opposite": "topological",
    "separates": "topological",
    "egocentric": "topological",
    "set": "topological",
    "ordinal": "spatial",
    "negation": "topological",
    "host_of": "topological",
    "joins": "topological",
    "bounds": "topological",
    "under": "spatial",
    "without_relation": "topological",
}

# The anchor kinds 0.5.0 adds, and the requirement family each answers.  The
# registry holds the weights and the style; this maps a stored anchor back to
# its family so a record written before the registry existed still counts.
# The anchor kinds a single-element draw may reach through the registry.  The
# set kind is not among them: it names several elements at once and is drawn by
# the batch scope rather than by the reference draw.
NEW_KINDS = ("nearest", "between", "above_below", "opposite", "separates",
             "egocentric", "ordinal", "negation",
             "host_of", "joins", "bounds", "under", "without_relation")

KIND_FAMILY = {
    "nearest": "ref.relative.nearest",
    "between": "ref.relative.between",
    "above_below": "ref.relative.above_below",
    "opposite": "ref.relative.opposite",
    "separates": "ref.topological.separates",
    "egocentric": "ref.viewpoint.through_door",
    "set": "ref.set",
    "ordinal": "ref.ordinal",
    "negation": "ref.negation",
    "host_of": "ref.host_of_filling",
    "joins": "ref.joins_spaces",
    "bounds": "ref.bounds_space",
    "under": "ref.under_walls",
    "without_relation": "ref.without_relation",
}


@dataclass(frozen=True)
class Anchor:
    """A phrase and the predicate that must single out one element."""

    kind: str
    family: str
    phrase: str
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def category(self) -> str:
        return CATEGORY[self.kind]

    @property
    def chain_length(self) -> int:
        return CHAIN_LENGTH[self.kind]

    def resolve(self, scene: Scene) -> list[str]:
        return RESOLVERS[self.kind](self, scene)

    def as_record(self) -> dict[str, Any]:
        return {"kind": self.kind, "family": self.family, "phrase": self.phrase,
                "params": self.params}


def from_record(record: dict[str, Any]) -> Anchor:
    return Anchor(kind=record["kind"], family=record["family"],
                  phrase=record["phrase"], params=dict(record.get("params") or {}))


# ------------------------------------------------------------------ helpers


ARTICLE = {"wall": "wall", "slab": "slab", "space": "space", "door": "door",
           "window": "window", "column": "column"}


def _family_members(scene: Scene, family: str) -> list[Any]:
    return scene.elements(family)


def _on_storey(scene: Scene, family: str, storey_guid: str) -> list[Any]:
    return scene.on_storey(family, storey_guid)


def reference_phrase(scene: Scene, product) -> Optional[str]:
    """A phrase naming one element, used inside a longer anchor phrase."""
    family = scene.family_of(product)
    if family is None:
        return None
    if family == "space":
        phrase = scene.space_phrase(product)
        if phrase:
            return f"the {phrase}"
    name = scene.unique_name(product)
    if name:
        return f"the {ARTICLE[family]} named '{name}'"
    return f"the {ARTICLE[family]} with GlobalId '{product.GlobalId}'"


# --------------------------------------------------------------- resolvers


def _resolve_guid(anchor: Anchor, scene: Scene) -> list[str]:
    product = scene.by_guid(anchor.params["guid"])
    if product is None or scene.family_of(product) != anchor.family:
        return []
    return [product.GlobalId]


def _resolve_name(anchor: Anchor, scene: Scene) -> list[str]:
    name = anchor.params["name"]
    return sorted(e.GlobalId for e in _family_members(scene, anchor.family)
                  if (e.Name or "").strip() == name)


def _resolve_offset(anchor: Anchor, scene: Scene) -> list[str]:
    reference = scene.by_guid(anchor.params["reference_guid"])
    if reference is None:
        return []
    origin = scene.point(reference)
    if origin is None:
        return []
    axis = int(anchor.params["axis"])
    sign = int(anchor.params["sign"])
    distance = float(anchor.params["distance"])
    tolerance = float(anchor.params["tolerance"])
    lateral = float(anchor.params["lateral_tolerance"])
    candidates = _on_storey(scene, anchor.family, anchor.params["storey_guid"])
    hits = []
    for element in candidates:
        point = scene.point(element)
        if point is None or element.GlobalId == reference.GlobalId:
            continue
        delta = point - origin
        if abs(delta[axis] * sign - distance) > tolerance:
            continue
        if any(abs(delta[other]) > lateral
               for other in range(3) if other != axis):
            continue
        hits.append(element.GlobalId)
    return sorted(hits)


def _resolve_extreme(anchor: Anchor, scene: Scene) -> list[str]:
    axis = int(anchor.params["axis"])
    sign = int(anchor.params["sign"])
    margin = float(anchor.params["margin"])
    candidates = _on_storey(scene, anchor.family, anchor.params["storey_guid"])
    scored = [(scene.point(e), e) for e in candidates]
    scored = [(p, e) for p, e in scored if p is not None]
    if not scored:
        return []
    best = max(float(p[axis]) * sign for p, _ in scored)
    return sorted(e.GlobalId for p, e in scored
                  if float(p[axis]) * sign >= best - margin)


def _resolve_in_storey(anchor: Anchor, scene: Scene) -> list[str]:
    return sorted(e.GlobalId for e in
                  _on_storey(scene, anchor.family, anchor.params["storey_guid"]))


def _resolve_hosted(anchor: Anchor, scene: Scene) -> list[str]:
    host = scene.by_guid(anchor.params["host_guid"])
    if host is None:
        return []
    hits = []
    for guid in scene.hosted_by(host):
        element = scene.by_guid(guid)
        if element is not None and scene.family_of(element) == anchor.family:
            hits.append(guid)
    return sorted(hits)


def _resolve_bounding(anchor: Anchor, scene: Scene) -> list[str]:
    first = anchor.params["space_a_guid"]
    second = anchor.params["space_b_guid"]
    hits = []
    for element in _family_members(scene, anchor.family):
        spaces = set(scene.bounded_spaces(element))
        if first in spaces and second in spaces:
            hits.append(element.GlobalId)
    return sorted(hits)


def _resolve_space_of(anchor: Anchor, scene: Scene) -> list[str]:
    element = scene.by_guid(anchor.params["element_guid"])
    if element is None:
        return []
    hits = []
    for guid in scene.bounded_spaces(element):
        space = scene.by_guid(guid)
        if space is not None and scene.family_of(space) == anchor.family:
            hits.append(guid)
    second_guid = anchor.params.get("element_b_guid")
    if second_guid:
        # "the space bounded by the walls A and B": both have to bound it.
        second = scene.by_guid(second_guid)
        if second is None:
            return []
        both = set(scene.bounded_spaces(second))
        hits = [guid for guid in hits if guid in both]
    return sorted(hits)


def _resolve_connects(anchor: Anchor, scene: Scene) -> list[str]:
    other = scene.by_guid(anchor.params["other_guid"])
    if other is None:
        return []
    hits = []
    for guid in scene.connected(other):
        element = scene.by_guid(guid)
        if element is not None and scene.family_of(element) == anchor.family:
            hits.append(guid)
    return sorted(hits)


def _plan_distance(first: np.ndarray, second: np.ndarray) -> float:
    return float(np.linalg.norm((first - second)[:2]))


def _resolve_nearest(anchor: Anchor, scene: Scene) -> list[str]:
    reference = scene.by_guid(anchor.params["reference_guid"])
    if reference is None:
        return []
    origin = scene.centre(reference)
    if origin is None:
        return []
    margin = float(anchor.params["margin"])
    scored = []
    for element in _on_storey(scene, anchor.family, anchor.params["storey_guid"]):
        if element.GlobalId == reference.GlobalId:
            continue
        point = scene.centre(element)
        if point is None:
            continue
        scored.append((float(np.linalg.norm(point - origin)), element.GlobalId))
    if not scored:
        return []
    best = min(distance for distance, _guid in scored)
    return sorted(guid for distance, guid in scored if distance <= best + margin)


def _resolve_between(anchor: Anchor, scene: Scene) -> list[str]:
    first = scene.by_guid(anchor.params["a_guid"])
    second = scene.by_guid(anchor.params["b_guid"])
    if first is None or second is None:
        return []
    a = scene.centre(first)
    b = scene.centre(second)
    if a is None or b is None:
        return []
    axis = int(anchor.params["axis"])
    inset = float(anchor.params["inset"])
    lateral = float(anchor.params["lateral_tolerance"])
    low, high = sorted((float(a[axis]), float(b[axis])))
    if high - low <= 2 * inset:
        return []
    other = 1 - axis
    line = 0.5 * (float(a[other]) + float(b[other]))
    hits = []
    for element in _on_storey(scene, anchor.family, anchor.params["storey_guid"]):
        if element.GlobalId in (first.GlobalId, second.GlobalId):
            continue
        point = scene.centre(element)
        if point is None:
            continue
        if not low + inset <= float(point[axis]) <= high - inset:
            continue
        if abs(float(point[other]) - line) > lateral:
            continue
        hits.append(element.GlobalId)
    return sorted(hits)


def _resolve_above_below(anchor: Anchor, scene: Scene) -> list[str]:
    reference = scene.by_guid(anchor.params["reference_guid"])
    if reference is None:
        return []
    origin = scene.centre(reference)
    if origin is None:
        return []
    tolerance = float(anchor.params["tolerance"])
    sign = 1.0 if anchor.params["direction"] == "above" else -1.0
    hits = []
    for element in _on_storey(scene, anchor.family, anchor.params["storey_guid"]):
        if element.GlobalId == reference.GlobalId:
            continue
        point = scene.centre(element)
        if point is None:
            continue
        if _plan_distance(point, origin) > tolerance:
            continue
        if (float(point[2]) - float(origin[2])) * sign <= 0.5:
            continue
        hits.append(element.GlobalId)
    return sorted(hits)


def _resolve_opposite(anchor: Anchor, scene: Scene) -> list[str]:
    reference = scene.by_guid(anchor.params["reference_guid"])
    space = scene.by_guid(anchor.params["space_guid"])
    if reference is None or space is None:
        return []
    middle = scene.centre(space)
    origin = scene.centre(reference)
    if middle is None or origin is None:
        return []
    axis = int(anchor.params["axis"])
    offset = float(anchor.params["min_offset"])
    side = 1.0 if float(origin[axis]) > float(middle[axis]) else -1.0
    hits = []
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        if element is None or guid == reference.GlobalId:
            continue
        if scene.family_of(element) != anchor.family:
            continue
        point = scene.centre(element)
        if point is None:
            continue
        delta = (float(point[axis]) - float(middle[axis])) * side
        if delta > -offset:
            continue
        hits.append(guid)
    return sorted(hits)


def _resolve_egocentric(anchor: Anchor, scene: Scene) -> list[str]:
    door = scene.by_guid(anchor.params["door_guid"])
    space = scene.by_guid(anchor.params["space_guid"])
    if door is None or space is None:
        return []
    view = _view_frame(scene, door, space)
    if view is None:
        return []
    _forward, left = view
    origin = scene.centre(door)
    if origin is None:
        return []
    want = 1.0 if anchor.params["side"] == "left" else -1.0
    tolerance = float(anchor.params["tolerance"])
    hits = []
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        if element is None or guid == door.GlobalId:
            continue
        if scene.family_of(element) != anchor.family:
            continue
        point = scene.centre(element)
        if point is None:
            continue
        sideways = float(np.dot((point - origin)[:2], left)) * want
        if sideways < tolerance:
            continue
        hits.append(guid)
    return sorted(hits)


def _view_frame(scene: Scene, door, space):
    """Which way a reader faces on entering a space through a door.

    The direction is the door's host wall's own across-axis, turned to point at
    the space, and the left-hand side follows from it.  A door whose host wall
    cannot be read, or which stands in the plane of the space's centre, gives no
    frame and the anchor is not offered.
    """
    host_guid = scene.host_of(door)
    host = scene.by_guid(host_guid) if host_guid else None
    if host is None:
        return None
    matrix = scene.matrix(host)
    middle = scene.centre(space)
    origin = scene.centre(door)
    if matrix is None or middle is None or origin is None:
        return None
    forward = np.array(matrix[:2, 1], dtype=float)
    norm = float(np.linalg.norm(forward))
    if norm < 1e-6:
        return None
    forward = forward / norm
    towards = (middle - origin)[:2]
    if float(np.linalg.norm(towards)) < 0.5:
        return None
    if float(np.dot(forward, towards)) < 0:
        forward = -forward
    left = np.array([-forward[1], forward[0]], dtype=float)
    return forward, left


RESOLVERS: dict[str, Callable[[Anchor, Scene], list[str]]] = {
    "guid": _resolve_guid,
    "name": _resolve_name,
    "offset": _resolve_offset,
    "extreme": _resolve_extreme,
    "in_storey": _resolve_in_storey,
    "hosted": _resolve_hosted,
    "bounding": _resolve_bounding,
    "space_of": _resolve_space_of,
    "connects": _resolve_connects,
    "nearest": _resolve_nearest,
    "between": _resolve_between,
    "above_below": _resolve_above_below,
    "opposite": _resolve_opposite,
    "separates": _resolve_bounding,
    "egocentric": _resolve_egocentric,
    "set": lambda a, s: _resolve_set(a, s),
    "ordinal": lambda a, s: _resolve_ordinal(a, s),
    "negation": lambda a, s: _resolve_negation(a, s),
    "host_of": lambda a, s: _resolve_host_of(a, s),
    "joins": lambda a, s: _resolve_joins(a, s),
    "bounds": lambda a, s: _resolve_bounds(a, s),
    "under": lambda a, s: _resolve_under(a, s),
    "without_relation": lambda a, s: _resolve_without_relation(a, s),
}


# ---------------------------------------------------------------- builders


def guid_anchor(scene: Scene, product) -> Anchor:
    family = scene.family_of(product)
    return Anchor(kind="guid", family=family,
                  phrase=f"the {ARTICLE[family]} with GlobalId '{product.GlobalId}'",
                  params={"guid": product.GlobalId})


def offset_anchors(scene: Scene, product, rng, limit: int = 24) -> list[Anchor]:
    """Anchors that place the target relative to a named neighbour.

    A neighbour is usable when its own name singles it out, when it sits close
    to one world axis from the target, and when no third element sits in the
    same place: the tolerances the phrase implies are the tolerances the
    predicate uses.
    """
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return []
    storey_label = scene.storey_label(storey)
    if storey_label is None:
        return []
    point = scene.point(product)
    if point is None:
        return []
    pool = list(scene.on_storey(family, storey.GlobalId))
    pool += list(scene.on_storey("column", storey.GlobalId))
    rng.shuffle(pool)
    out: list[Anchor] = []
    for reference in pool:
        if len(out) >= limit:
            break
        if reference.GlobalId == product.GlobalId:
            continue
        name = scene.unique_name(reference)
        if not name:
            continue
        origin = scene.point(reference)
        if origin is None:
            continue
        delta = point - origin
        axis = int(np.argmax(np.abs(delta)))
        distance = float(abs(delta[axis]))
        if distance < 1.0 or distance > 40.0:
            continue
        lateral = float(max(abs(delta[other]) for other in range(3)
                            if other != axis))
        if lateral > 0.35 * distance:
            continue
        sign = 1 if delta[axis] > 0 else -1
        word, axis_word = AXIS_WORDS[(axis, sign)]
        tolerance = max(0.25, 0.1 * distance)
        lateral_tolerance = max(0.5, lateral * 1.2)
        reference_family = scene.family_of(reference)
        anchor = Anchor(
            kind="offset", family=family,
            phrase=(f"the {ARTICLE[family]} on {storey_label} that stands about "
                    f"{distance:.1f} m {word} ({axis_word}) of the "
                    f"{ARTICLE[reference_family]} named '{name}'"),
            params={"reference_guid": reference.GlobalId,
                    "storey_guid": storey.GlobalId, "axis": axis, "sign": sign,
                    "distance": round(distance, 2), "tolerance": round(tolerance, 3),
                    "lateral_tolerance": round(lateral_tolerance, 3)})
        out.append(anchor)
    return out


def extreme_anchors(scene: Scene, product) -> list[Anchor]:
    """Anchors that name the target as the furthest one along a world axis."""
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return []
    storey_label = scene.storey_label(storey)
    if storey_label is None:
        return []
    out = []
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        word, axis_word = AXIS_WORDS[(axis, sign)]
        out.append(Anchor(
            kind="extreme", family=family,
            phrase=(f"the {ARTICLE[family]} furthest {word} ({axis_word}) on "
                    f"{storey_label}"),
            params={"storey_guid": storey.GlobalId, "axis": axis, "sign": sign,
                    "margin": 0.05}))
    return out


def in_storey_anchor(scene: Scene, product) -> Optional[Anchor]:
    """An anchor for the only element of its family a storey contains."""
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return None
    storey_label = scene.storey_label(storey)
    if storey_label is None:
        return None
    return Anchor(kind="in_storey", family=family,
                  phrase=f"the only {ARTICLE[family]} contained in {storey_label}",
                  params={"storey_guid": storey.GlobalId})


def hosted_anchor(scene: Scene, product) -> Optional[Anchor]:
    """An anchor for a door or a window, named through the wall that hosts it."""
    family = scene.family_of(product)
    host_guid = scene.host_of(product)
    if family not in ("door", "window") or host_guid is None:
        return None
    host = scene.by_guid(host_guid)
    if host is None:
        return None
    host_phrase = reference_phrase(scene, host)
    if host_phrase is None:
        return None
    return Anchor(kind="hosted", family=family,
                  phrase=f"the {ARTICLE[family]} hosted in {host_phrase}",
                  params={"host_guid": host_guid})


def bounding_anchor(scene: Scene, product) -> Optional[Anchor]:
    """An anchor for an element named through the two spaces it separates."""
    family = scene.family_of(product)
    if family is None:
        return None
    spaces = [scene.by_guid(g) for g in scene.bounded_spaces(product)]
    named = [(s, scene.space_phrase(s)) for s in spaces if s is not None]
    named = [(s, p) for s, p in named if p]
    if len(named) < 2:
        return None
    first, second = named[0], named[1]
    return Anchor(kind="bounding", family=family,
                  phrase=(f"the {ARTICLE[family]} that bounds both the "
                          f"{first[1]} and the {second[1]}"),
                  params={"space_a_guid": first[0].GlobalId,
                          "space_b_guid": second[0].GlobalId})


#: How often a space named through what bounds it is named through two of
#: its bounding elements rather than one (0.9.0).
SPACE_OF_PAIR_SHARE = 0.30


def space_of_pair_anchor(scene: Scene, space) -> Optional[Anchor]:
    """An anchor for a space named through two elements that both bound it.

    "the space bounded by the wall named 'A' and the wall named 'B'" names the
    room a reader finds between two walls; the identifier rewrite turns it into
    "the space bounded by the walls with IDs A and B".  Only elements whose
    name is their own are used, and the pair is kept only when no other space
    is bounded by both.
    """
    if scene.family_of(space) != "space":
        return None
    named = []
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        if element is None or scene.family_of(element) not in ("wall", "slab"):
            continue
        phrase = reference_phrase(scene, element)
        if phrase is None or "GlobalId" in phrase:
            continue
        named.append((guid, phrase, scene.family_of(element)))
    for index, (first, first_phrase, first_family) in enumerate(named):
        for second, second_phrase, second_family in named[index + 1:]:
            if first_family != second_family:
                continue
            anchor = Anchor(kind="space_of", family="space",
                            phrase=(f"the space bounded by {first_phrase} and "
                                    f"{second_phrase}"),
                            params={"element_guid": first,
                                    "element_b_guid": second})
            if _resolve_space_of(anchor, scene) == [space.GlobalId]:
                return anchor
    return None


def space_of_anchor(scene: Scene, space, rng=None) -> Optional[Anchor]:
    """An anchor for a space named through an element that bounds it."""
    if scene.family_of(space) != "space":
        return None
    if rng is not None and rng.random() < SPACE_OF_PAIR_SHARE:
        pair = space_of_pair_anchor(scene, space)
        if pair is not None:
            return pair
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        if element is None or scene.family_of(element) not in ("wall", "slab"):
            continue
        if len(_resolve_space_of(Anchor("space_of", "space", "",
                                        {"element_guid": guid}), scene)) != 1:
            continue
        phrase = reference_phrase(scene, element)
        if phrase is None or "GlobalId" in phrase:
            continue
        return Anchor(kind="space_of", family="space",
                      phrase=f"the space bounded by {phrase}",
                      params={"element_guid": guid})
    return None


def connects_anchor(scene: Scene, product) -> Optional[Anchor]:
    """An anchor for an element named through what the model connects it to."""
    family = scene.family_of(product)
    if family is None:
        return None
    for guid in scene.connected(product):
        other = scene.by_guid(guid)
        if other is None:
            continue
        other_family = scene.family_of(other)
        if other_family is None or other_family == "storey":
            continue
        name = scene.unique_name(other)
        if not name:
            continue
        return Anchor(kind="connects", family=family,
                      phrase=(f"the {ARTICLE[family]} connected to the "
                              f"{ARTICLE[other_family]} named '{name}'"),
                      params={"other_guid": guid})
    return None


# ------------------------------------------- builders, relative reference


def _named_neighbours(scene: Scene, storey_guid: str, rng, limit: int = 30
                      ) -> list[Any]:
    """Elements of the storey a phrase may name, each with a unique name."""
    pool: list[Any] = []
    for family in FAMILIES:
        for element in scene.on_storey(family, storey_guid):
            if scene.unique_name(element):
                pool.append(element)
    rng.shuffle(pool)
    return pool[:limit]


def nearest_anchors(scene: Scene, product, rng, limit: int = 8) -> list[Anchor]:
    """Anchors naming the target as the closest of its family to a neighbour."""
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return []
    storey_label = scene.storey_label(storey)
    if storey_label is None:
        return []
    peers = [(e, scene.centre(e)) for e in scene.on_storey(family, storey.GlobalId)]
    peers = [(e, c) for e, c in peers if c is not None]
    if len(peers) < 2:
        return []
    out: list[Anchor] = []
    for reference in _named_neighbours(scene, storey.GlobalId, rng):
        if len(out) >= limit:
            break
        if reference.GlobalId == product.GlobalId:
            continue
        origin = scene.centre(reference)
        if origin is None:
            continue
        ranked = sorted(
            ((float(np.linalg.norm(c - origin)), e.GlobalId)
             for e, c in peers if e.GlobalId != reference.GlobalId),
            key=lambda pair: (pair[0], pair[1]))
        if len(ranked) < 2 or ranked[0][1] != product.GlobalId:
            continue
        # The phrase only means one element when the runner-up is clearly
        # further away, so a reader measuring by eye reaches the same answer.
        if ranked[1][0] - ranked[0][0] < 0.75:
            continue
        reference_family = scene.family_of(reference)
        out.append(Anchor(
            kind="nearest", family=family,
            phrase=(f"the {ARTICLE[family]} nearest to the "
                    f"{ARTICLE[reference_family]} named "
                    f"'{scene.unique_name(reference)}' on {storey_label}"),
            params={"reference_guid": reference.GlobalId,
                    "storey_guid": storey.GlobalId, "margin": 0.25}))
    return out


def between_anchors(scene: Scene, product, rng, limit: int = 6) -> list[Anchor]:
    """Anchors naming the target as the element between two named neighbours."""
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return []
    storey_label = scene.storey_label(storey)
    if storey_label is None:
        return []
    middle = scene.centre(product)
    if middle is None:
        return []
    pool = [(e, scene.centre(e))
            for e in _named_neighbours(scene, storey.GlobalId, rng, 24)]
    pool = [(e, c) for e, c in pool if c is not None
            and e.GlobalId != product.GlobalId]
    out: list[Anchor] = []
    for axis in (0, 1):
        other = 1 - axis
        near = [(e, c) for e, c in pool
                if abs(float(c[other]) - float(middle[other])) < 2.0]
        before = [(e, c) for e, c in near if float(c[axis]) < float(middle[axis]) - 1.0]
        after = [(e, c) for e, c in near if float(c[axis]) > float(middle[axis]) + 1.0]
        if not before or not after:
            continue
        first = min(before, key=lambda pair: float(middle[axis]) - float(pair[1][axis]))
        second = min(after, key=lambda pair: float(pair[1][axis]) - float(middle[axis]))
        a_family = scene.family_of(first[0])
        b_family = scene.family_of(second[0])
        out.append(Anchor(
            kind="between", family=family,
            phrase=(f"the {ARTICLE[family]} on {storey_label} that stands "
                    f"between the {ARTICLE[a_family]} named "
                    f"'{scene.unique_name(first[0])}' and the "
                    f"{ARTICLE[b_family]} named "
                    f"'{scene.unique_name(second[0])}'"),
            params={"a_guid": first[0].GlobalId, "b_guid": second[0].GlobalId,
                    "storey_guid": storey.GlobalId, "axis": axis,
                    "inset": 0.2, "lateral_tolerance": 2.0}))
        if len(out) >= limit:
            break
    return out


def above_below_anchors(scene: Scene, product, rng) -> list[Anchor]:
    """Anchors naming the target by the element it stands over or under."""
    family = scene.family_of(product)
    storey = scene.storey_of(product)
    if family is None or storey is None:
        return []
    storey_label = scene.storey_label(storey)
    middle = scene.centre(product)
    if storey_label is None or middle is None:
        return []
    out: list[Anchor] = []
    for direction, step in (("above", -1), ("below", 1)):
        neighbour = scene.storey_neighbour(storey, step)
        if neighbour is None:
            continue
        for reference in scene.on_storey(family, neighbour.GlobalId):
            name = scene.unique_name(reference)
            point = scene.centre(reference)
            if not name or point is None:
                continue
            if _plan_distance(point, middle) > 0.5:
                continue
            out.append(Anchor(
                kind="above_below", family=family,
                phrase=(f"the {ARTICLE[family]} on {storey_label} directly "
                        f"{direction} the {ARTICLE[family]} named '{name}'"),
                params={"reference_guid": reference.GlobalId,
                        "storey_guid": storey.GlobalId,
                        "direction": direction, "tolerance": 0.5}))
            break
    return out


# ---------------------------------------- builders, topological reference


def separates_anchors(scene: Scene, product, rng) -> list[Anchor]:
    """Anchors naming an element by the two rooms it stands between."""
    anchor = separates_anchor(scene, product)
    return [anchor] if anchor is not None else []


#: How far, in metres, a room may stand from an element the phrase says it
#: separates.  The word claims contact, so a relationship the source model
#: carries is not enough on its own and the two bodies have to meet.
SEPARATES_TOUCH = 0.15


def _touches(scene: Scene, product, other) -> bool:
    """Whether two elements' world boxes meet, as far as the index can tell."""
    first = scene.world_box(product)
    second = scene.world_box(other)
    if first is None or second is None:
        return False
    apart = np.maximum(np.maximum(first.lo - second.hi, second.lo - first.hi),
                       0.0)
    return float(np.linalg.norm(apart)) <= SEPARATES_TOUCH


def separates_anchor(scene: Scene, product) -> Optional[Anchor]:
    """An anchor naming an element by the two rooms it stands between."""
    base = bounding_anchor(scene, product)
    if base is None:
        return None
    first = scene.by_guid(base.params["space_a_guid"])
    second = scene.by_guid(base.params["space_b_guid"])
    if first is None or second is None:
        return None
    if not (_touches(scene, product, first) and _touches(scene, product, second)):
        return None
    return Anchor(kind="separates", family=base.family,
                  phrase=(f"the {ARTICLE[base.family]} that separates the "
                          f"{scene.space_phrase(first)} from the "
                          f"{scene.space_phrase(second)}"),
                  params=dict(base.params))


def opposite_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming the target as the element facing another across a room."""
    family = scene.family_of(product)
    if family is None:
        return []
    middle_guids = list(scene.bounded_spaces(product))
    rng.shuffle(middle_guids)
    out: list[Anchor] = []
    for space_guid in middle_guids:
        space = scene.by_guid(space_guid)
        if space is None:
            continue
        space_label = scene.space_phrase(space)
        centre = scene.centre(space)
        target = scene.centre(product)
        if not space_label or centre is None or target is None:
            continue
        axis = int(np.argmax(np.abs((target - centre)[:2])))
        if abs(float((target - centre)[axis])) < 0.5:
            continue
        for guid in scene.space_elements(space):
            reference = scene.by_guid(guid)
            if reference is None or guid == product.GlobalId:
                continue
            if scene.family_of(reference) != family:
                continue
            name = scene.unique_name(reference)
            point = scene.centre(reference)
            if not name or point is None:
                continue
            if (float(point[axis]) - float(centre[axis])) * \
                    (float(target[axis]) - float(centre[axis])) >= 0:
                continue
            out.append(Anchor(
                kind="opposite", family=family,
                phrase=(f"the {ARTICLE[family]} opposite the "
                        f"{ARTICLE[family]} named '{name}' across the "
                        f"{space_label}"),
                params={"reference_guid": guid, "space_guid": space_guid,
                        "axis": axis, "min_offset": 0.25}))
            break
        if len(out) >= limit:
            break
    return out


def egocentric_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming the target by the side it sits on, seen through a door.

    The reader stands in a named doorway and looks into a named room, so the
    viewing direction is the door's host wall turned to face the room and the
    left-hand side follows from it.  The anchor is only offered where that
    direction can be read from the model, and it is kept only where the
    predicate then returns the target and nothing else.
    """
    family = scene.family_of(product)
    if family is None:
        return []
    space_guids = list(scene.bounded_spaces(product))
    rng.shuffle(space_guids)
    out: list[Anchor] = []
    for space_guid in space_guids:
        space = scene.by_guid(space_guid)
        if space is None:
            continue
        space_label = scene.space_phrase(space)
        if not space_label:
            continue
        for guid in scene.space_elements(space):
            door = scene.by_guid(guid)
            if door is None or guid == product.GlobalId:
                continue
            if scene.family_of(door) != "door":
                continue
            name = scene.unique_name(door)
            if not name:
                continue
            view = _view_frame(scene, door, space)
            origin = scene.centre(door)
            point = scene.centre(product)
            if view is None or origin is None or point is None:
                continue
            _forward, left = view
            sideways = float(np.dot((point - origin)[:2], left))
            if abs(sideways) < 0.5:
                continue
            side = "left" if sideways > 0 else "right"
            out.append(Anchor(
                kind="egocentric", family=family,
                phrase=(f"the {ARTICLE[family]} on the {side}-hand side as "
                        f"seen from the door named '{name}' looking into the "
                        f"{space_label}"),
                params={"door_guid": guid, "space_guid": space_guid,
                        "side": side, "tolerance": 0.5}))
            if len(out) >= limit:
                return out
    return out


def new_kind_anchors(scene: Scene, product, category: str, rng) -> list[Anchor]:
    """The reference families of one instruction style, in weighted order.

    Which families exist and how often each is tried comes from the registry,
    so a reference family added later is drawn here without this function
    learning its name.
    """
    out: list[Anchor] = []
    for family in families.members("ref.new", rng, style=category):
        builder = families.build(family)
        if builder is None:
            continue
        try:
            out.extend(builder(scene, product, rng) or ())
        except Exception:
            continue
    return out


def unique_anchor(anchors: list[Anchor], scene: Scene, target_guid: str
                  ) -> Optional[Anchor]:
    """The first anchor in the list that resolves to the target and nothing else."""
    for anchor in anchors:
        if anchor is None:
            continue
        if anchor.resolve(scene) == [target_guid]:
            return anchor
    return None


def build_anchor(scene: Scene, product, category: str, rng) -> Optional[Anchor]:
    """An anchor of the requested style that singles the product out."""
    guid = product.GlobalId
    if category == "direct":
        return unique_anchor([guid_anchor(scene, product)], scene, guid)
    # A share of the spatial and topological anchors is drawn from the relative
    # and topological kinds 0.5.0 adds.  The draw is a preference rather than a
    # requirement: a target none of the new kinds can name falls back to the
    # earlier ones instead of being refused, so no cell of the grid loses yield.
    if families.draw("ref.new", rng):
        anchor = unique_anchor(new_kind_anchors(scene, product, category, rng),
                               scene, guid)
        if anchor is not None:
            return anchor
    if category == "spatial":
        candidates = offset_anchors(scene, product, rng)
        candidates += extreme_anchors(scene, product)
        return unique_anchor(candidates, scene, guid)
    candidates = [hosted_anchor(scene, product), bounding_anchor(scene, product),
                  space_of_anchor(scene, product, rng),
                  connects_anchor(scene, product),
                  in_storey_anchor(scene, product)]
    candidates = [c for c in candidates if c is not None]
    # A topological instruction that names its target through a host, through
    # the spaces it bounds, or through the wall that bounds it, traverses two
    # relationship hops; naming it through the storey that contains it
    # traverses one.  Where the wave asks for the harder reference, a target
    # that only supports the shorter one is refused, and the draw moves on to
    # another target rather than settling.
    if settings.SETTINGS.two_hop_only_prob > 0 and \
            rng.random() < settings.SETTINGS.two_hop_only_prob:
        two_hop = [c for c in candidates if CHAIN_LENGTH.get(c.kind, 0) >= 2]
        return unique_anchor(two_hop, scene, guid)
    return unique_anchor(candidates, scene, guid)


# =====================================================================
# 0.6.0: references that name a set, a position in a row, or the element that
# lacks something.  A set anchor resolves to every element the phrase covers
# rather than to one, which is what lets an instruction ask for a batch edit.
# =====================================================================

#: Plural words for the families a set phrase names.
PLURAL = {"wall": "walls", "slab": "slabs", "space": "spaces",
          "door": "doors", "window": "windows", "column": "columns"}

#: Ordinal words a position phrase uses, in order.
ORDINALS = ("first", "second", "third", "fourth", "fifth")

#: How a measured condition reads, and how it is measured.  ``overall_width``
#: is the recorded attribute; the other two are read from the element's world
#: box, which the geometry index already holds.
CONDITIONS = {
    "overall_width": ("wider than", ("door", "window")),
    "height": ("taller than", ("wall", "column", "space")),
    "plan_length": ("longer than", ("wall", "slab")),
}

#: How far a member's measurement has to stand from the threshold before the
#: condition is used, so that no arithmetic detail decides membership.
CONDITION_MARGIN = 0.15

#: Metres a threshold is rounded to.  A person asks for the doors wider than a
#: metre, not for the doors wider than 1.07 m, and a number carried to the
#: centimetre reads as a value read off the data rather than as a requirement.
CONDITION_STEP = 0.5

#: The share of a set a condition has to keep.  A condition that keeps almost
#: all of it, or almost none, is not a condition the reader has to weigh.
CONDITION_KEEP = (1.0 / 3.0, 2.0 / 3.0)


def _family_of(scene: Scene, guid: str) -> Optional[str]:
    """The family of the element one identifier names, or ``None``."""
    element = scene.by_guid(guid)
    return None if element is None else scene.family_of(element)


def measure(scene: Scene, element, name: str) -> Optional[float]:
    """One measurement of an element, in metres, or ``None`` when unreadable."""
    if name == "overall_width":
        value = getattr(element, "OverallWidth", None)
        if value is None:
            return None
        try:
            return float(value) * scene.unit_scale
        except (TypeError, ValueError):
            return None
    box = scene.world_box(element)
    if box is None:
        return None
    if name == "height":
        return float(box.size[2])
    if name == "plan_length":
        return float(max(box.size[0], box.size[1]))
    return None


def _set_pool(anchor: Anchor, scene: Scene) -> Optional[list[Any]]:
    """Every element the set phrase's scope covers, before its condition."""
    scope = anchor.params["scope"]
    guid = anchor.params.get("scope_guid")
    if scope == "ids":
        # A set named by its members' identifiers covers exactly those.
        members = [scene.by_guid(g) for g in anchor.params.get("member_guids") or ()]
        if any(m is None or scene.family_of(m) != anchor.family
               for m in members):
            return None
        return members
    if scope == "storey":
        return _on_storey(scene, anchor.family, guid)
    anchor_of = scene.by_guid(guid)
    if anchor_of is None:
        return None
    if scope == "host":
        members = scene.hosted_by(anchor_of)
    elif scope == "space":
        members = scene.space_elements(anchor_of)
    else:
        return None
    out = []
    for member_guid in members:
        element = scene.by_guid(member_guid)
        if element is not None and scene.family_of(element) == anchor.family:
            out.append(element)
    return out


def _resolve_set(anchor: Anchor, scene: Scene) -> list[str]:
    pool = _set_pool(anchor, scene)
    if not pool:
        return []
    condition = anchor.params.get("condition")
    if not condition:
        return sorted(e.GlobalId for e in pool)
    name = condition["measure"]
    threshold = float(condition["threshold"])
    hits = []
    for element in pool:
        value = measure(scene, element, name)
        if value is None:
            # A pool the phrase cannot measure in full is a phrase whose reader
            # and whose checker would not agree, so it names nothing.
            return []
        if value > threshold:
            hits.append(element.GlobalId)
    return sorted(hits)


def _resolve_ordinal(anchor: Anchor, scene: Scene) -> list[str]:
    host = scene.by_guid(anchor.params["host_guid"])
    if host is None:
        return []
    axis = int(anchor.params["axis"])
    sign = int(anchor.params["sign"])
    gap = float(anchor.params.get("min_gap", 0.2))
    ranked = []
    for guid in scene.hosted_by(host):
        element = scene.by_guid(guid)
        if element is None or scene.family_of(element) != anchor.family:
            continue
        centre = scene.centre(element)
        if centre is None:
            return []
        ranked.append((float(centre[axis]) * sign, guid))
    ranked.sort()
    index = int(anchor.params["index"])
    if index >= len(ranked):
        return []
    for first, second in zip(ranked, ranked[1:]):
        if second[0] - first[0] < gap:
            # Two elements the phrase cannot tell apart in the order it counts.
            return []
    return [ranked[index][1]]


def _bounding_families(scene: Scene, space) -> set[str]:
    out = set()
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        family = scene.family_of(element) if element is not None else None
        if family:
            out.add(family)
    return out


def _resolve_negation(anchor: Anchor, scene: Scene) -> list[str]:
    variant = anchor.params["variant"]
    missing = anchor.params.get("missing")
    if variant == "space_without_boundary":
        hits = []
        for space in _on_storey(scene, "space", anchor.params["storey_guid"]):
            if not scene.space_phrase(space):
                continue
            families_here = _bounding_families(scene, space)
            if not families_here:
                continue
            if missing not in families_here:
                hits.append(space.GlobalId)
        return sorted(hits)
    if variant == "wall_without_filling":
        hits = []
        for wall in _on_storey(scene, "wall", anchor.params["storey_guid"]):
            hosted = [_family_of(scene, g) for g in scene.hosted_by(wall)]
            if not any(f in ("door", "window") for f in hosted):
                hits.append(wall.GlobalId)
        return sorted(hits)
    if variant == "bounding_wall_without_filling":
        space = scene.by_guid(anchor.params["space_guid"])
        if space is None:
            return []
        hits = []
        for guid in scene.space_elements(space):
            element = scene.by_guid(guid)
            if element is None or scene.family_of(element) != "wall":
                continue
            hosted = [_family_of(scene, g)
                      for g in scene.hosted_by(element)]
            if missing not in hosted:
                hits.append(guid)
        return sorted(hits)
    return []


# ------------------------------------------------------------- builders


#: How many members a set named by identifiers lists, at most.  A work order
#: lists a handful of identifiers; a longer list is a schedule, not a sentence.
ID_LIST_SIZES = (2, 2, 3, 3, 4)


def id_list_anchors(scene: Scene, family: str, rng, limit: int = 3
                    ) -> list[Anchor]:
    """Phrases that name a set by the identifiers of its members (0.9.0).

    "Delete the walls with IDs A, B and C" is a set a person writes when they
    already know which elements they mean.  The members are drawn from one
    storey, which is where a person picking elements off a plan finds them, and
    the identifiers are spelled in one drawn form.
    """
    out: list[Anchor] = []
    storeys = list(scene.storeys)
    rng.shuffle(storeys)
    for storey in storeys:
        if len(out) >= limit:
            break
        members = list(scene.on_storey(family, storey.GlobalId))
        if len(members) < 2:
            continue
        rng.shuffle(members)
        size = min(len(members), ID_LIST_SIZES[int(rng.random()
                                                   * len(ID_LIST_SIZES))])
        chosen = [m.GlobalId for m in members[:size]]
        form = idspell.draw_form(rng)
        out.append(Anchor(
            kind="set", family=family,
            phrase=idspell.spell_list(form, ARTICLE[family], chosen),
            params={"scope": "ids", "member_guids": sorted(chosen),
                    "id_form": form, "scope_label": "", "condition": None}))
    return out


def set_anchors(scene: Scene, family: str, rng, conditional: bool = False,
                limit: int = 12, id_list: bool = False) -> list[Anchor]:
    """Phrases that name a whole set of elements of one family.

    A set is named by the storey it sits on, by the wall that hosts it or by
    the room it stands in, and a conditional set adds a measured threshold.  The
    caller resolves each candidate and keeps the first one whose members it can
    edit, so a phrase that covers nothing costs nothing.  With ``id_list`` the
    set is named by its members' identifiers instead (0.9.0).
    """
    if id_list:
        return id_list_anchors(scene, family, rng)
    candidates: list[Anchor] = []
    plural = PLURAL[family]
    for storey in scene.storeys:
        label = scene.storey_label(storey)
        if label is None:
            continue
        if len(scene.on_storey(family, storey.GlobalId)) < 2:
            continue
        candidates.append(Anchor(
            kind="set", family=family,
            phrase=f"all the {plural} on {label}",
            params={"scope": "storey", "scope_guid": storey.GlobalId,
                    "scope_label": label, "condition": None}))
    if family in ("door", "window"):
        # Only a wall the model records as hosting something can host a set, so
        # the walls that carry nothing are never looked at.
        hosts = [scene.by_guid(guid) for guid in sorted(scene._hosted)]
        for wall in hosts:
            if wall is None or scene.family_of(wall) != "wall":
                continue
            name = scene.unique_name(wall)
            hosted = [g for g in scene.hosted_by(wall)
                      if _family_of(scene, g) == family]
            if not name or len(hosted) < 2:
                continue
            candidates.append(Anchor(
                kind="set", family=family,
                phrase=f"every {family} hosted in the wall named '{name}'",
                params={"scope": "host", "scope_guid": wall.GlobalId,
                        "scope_label": name, "condition": None}))
    for space in scene.elements("space")[:200]:
        phrase = scene.space_phrase(space)
        if not phrase:
            continue
        members = [g for g in scene.space_elements(space)
                   if _family_of(scene, g) == family]
        if len(members) < 2:
            continue
        candidates.append(Anchor(
            kind="set", family=family,
            phrase=f"the {plural} that bound the {phrase}",
            params={"scope": "space", "scope_guid": space.GlobalId,
                    "scope_label": phrase, "condition": None}))
    rng.shuffle(candidates)
    candidates = candidates[:limit]
    if not conditional:
        return candidates
    return [c for c in (_with_condition(scene, base, rng)
                        for base in candidates) if c is not None]


def _with_condition(scene: Scene, base: Anchor, rng) -> Optional[Anchor]:
    """The same set phrase, narrowed by a measured threshold.

    The threshold is drawn so that it splits the pool and stands clear of every
    member's measurement, which is what makes membership a property of the
    building rather than of the arithmetic.
    """
    usable = [name for name, (_word, allowed) in CONDITIONS.items()
              if base.family in allowed]
    rng.shuffle(usable)
    pool = _set_pool(base, scene)
    if not pool or len(pool) < 3:
        return None
    for name in usable:
        values = [measure(scene, element, name) for element in pool]
        if any(v is None for v in values):
            continue
        least = max(2, int(-(-len(values) * CONDITION_KEEP[0] // 1)))
        most = int(len(values) * CONDITION_KEEP[1])
        if least > most:
            continue
        for threshold in _round_numbers(min(values), max(values)):
            if min(abs(v - threshold) for v in values) < CONDITION_MARGIN:
                continue
            kept = sum(1 for v in values if v > threshold)
            if not least <= kept <= most:
                continue
            word = CONDITIONS[name][0]
            return Anchor(
                kind="set", family=base.family,
                phrase=(f"only the {PLURAL[base.family]} {_scope_phrase(base)} "
                        f"{word} {threshold:.2f} m"),
                params=dict(base.params,
                            condition={"measure": name,
                                       "threshold": threshold}))
    return None


def _round_numbers(low: float, high: float) -> list[float]:
    """Round thresholds inside a range, from the middle of it outwards.

    The middle is tried first because a threshold there is the one most likely
    to divide the set rather than to shave one member off an end.
    """
    first = int(-(-(low + CONDITION_MARGIN) / CONDITION_STEP // 1))
    last = int((high - CONDITION_MARGIN) / CONDITION_STEP)
    steps = [round(k * CONDITION_STEP, 2) for k in range(first, last + 1)]
    if not steps:
        return []
    middle = (low + high) / 2.0
    return sorted(steps, key=lambda value: (abs(value - middle), value))


def _scope_phrase(anchor: Anchor) -> str:
    """How a conditional set phrase says where it looks."""
    scope = anchor.params["scope"]
    label = anchor.params["scope_label"]
    if scope == "storey":
        return f"on {label}"
    if scope == "host":
        return f"hosted in the wall named '{label}'"
    return f"bounding the {label}"


def ordinal_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming a door or a window by its place in a wall's row."""
    family = scene.family_of(product)
    host_guid = scene.host_of(product)
    if family not in ("door", "window") or host_guid is None:
        return []
    host = scene.by_guid(host_guid)
    if host is None:
        return []
    name = scene.unique_name(host)
    if not name:
        return []
    siblings = [g for g in scene.hosted_by(host)
                if _family_of(scene, g) == family]
    if len(siblings) < 2:
        return []
    out: list[Anchor] = []
    for axis, sign in ((0, 1), (0, -1), (1, 1), (1, -1)):
        word = AXIS_WORDS[(axis, sign)][0]
        # Counting starts at the side the phrase names, so a row read from the
        # west starts at the smallest x.
        from_word = {"east": "west", "west": "east",
                     "north": "south", "south": "north"}[word]
        ranked = []
        broken = False
        for guid in siblings:
            element = scene.by_guid(guid)
            centre = scene.centre(element) if element is not None else None
            if centre is None:
                broken = True
                break
            ranked.append((float(centre[axis]) * sign, guid))
        if broken:
            continue
        ranked.sort()
        index = [g for _v, g in ranked].index(product.GlobalId)
        if index >= len(ORDINALS):
            continue
        out.append(Anchor(
            kind="ordinal", family=family,
            phrase=(f"the {ORDINALS[index]} {family} from the {from_word} "
                    f"along the wall named '{name}'"),
            params={"host_guid": host_guid, "axis": axis, "sign": sign,
                    "index": index, "min_gap": 0.2}))
    rng.shuffle(out)
    return out[:limit]


def negation_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming an element by something it does not have."""
    family = scene.family_of(product)
    out: list[Anchor] = []
    if family == "space":
        storey = scene.storey_of(product)
        label = scene.storey_label(storey) if storey is not None else None
        if label and scene.space_phrase(product):
            for missing in ("window", "door"):
                out.append(Anchor(
                    kind="negation", family="space",
                    phrase=f"the space on {label} that no {missing} bounds",
                    params={"variant": "space_without_boundary",
                            "storey_guid": storey.GlobalId,
                            "missing": missing}))
    if family == "wall":
        storey = scene.storey_of(product)
        label = scene.storey_label(storey) if storey is not None else None
        if label:
            out.append(Anchor(
                kind="negation", family="wall",
                phrase=(f"the wall on {label} that hosts no door and no "
                        f"window"),
                params={"variant": "wall_without_filling",
                        "storey_guid": storey.GlobalId, "missing": None}))
        for guid in scene.bounded_spaces(product):
            space = scene.by_guid(guid)
            phrase = scene.space_phrase(space) if space is not None else None
            if not phrase:
                continue
            for missing in ("door", "window"):
                out.append(Anchor(
                    kind="negation", family="wall",
                    phrase=(f"the wall bounding the {phrase} that hosts no "
                            f"{missing}"),
                    params={"variant": "bounding_wall_without_filling",
                            "space_guid": guid, "missing": missing}))
    rng.shuffle(out)
    return out[:limit]


# =====================================================================
# 0.8.0: the references a person writes without thinking about them.  A door
# is named by the wall it sits in or by the two rooms it joins, a window by
# the room it bounds, a slab by the walls standing on it, and an element by
# the one relationship it does not have.  Each resolves here, from the model
# alone, so the answer the sandbox's library gives can be measured against it.
# =====================================================================


#: How far below the base of the walls above it the top face of the element
#: underneath may sit, in metres, before it belongs to another floor.
UNDER_GAP = 1.5

#: How far the top face may stand above that base and still be underneath, in
#: metres, which covers a slab the walls are set into.
UNDER_RISE = 0.05

#: How much of the ground the walls stand on the element underneath has to
#: cover before the phrase means it.  Measured over the corpus, a storey's
#: real floor slab covers at least a quarter of that ground, while the few
#: cases below a fifth are small pads no reader would call the floor.
UNDER_SHARE = 0.20


def _is_external(element) -> bool:
    """Whether the model marks an element as external, through IsExternal."""
    for definition in getattr(element, "IsDefinedBy", ()) or ():
        if not definition.is_a("IfcRelDefinesByProperties"):
            continue
        pset = definition.RelatingPropertyDefinition
        for prop in (getattr(pset, "HasProperties", ()) or ()) if pset else ():
            if prop.is_a("IfcPropertySingleValue") and prop.Name == "IsExternal":
                value = getattr(prop.NominalValue, "wrappedValue", None)
                if value is not None:
                    return bool(value)
    return False


def _resolve_host_of(anchor: Anchor, scene: Scene) -> list[str]:
    element = scene.by_guid(anchor.params["element_guid"])
    if element is None:
        return []
    host_guid = scene.host_of(element)
    if host_guid is None:
        return []
    host = scene.by_guid(host_guid)
    if host is None or scene.family_of(host) != anchor.family:
        return []
    return [host_guid]


def _resolve_joins(anchor: Anchor, scene: Scene) -> list[str]:
    first = scene.by_guid(anchor.params["space_a_guid"])
    if first is None:
        return []
    outside = bool(anchor.params.get("outside"))
    second = None if outside else scene.by_guid(anchor.params.get("space_b_guid"))
    if not outside and second is None:
        return []
    hits = []
    for element in _family_members(scene, anchor.family):
        host_guid = scene.host_of(element)
        host = scene.by_guid(host_guid) if host_guid else None
        if host is None:
            continue
        bounded = set(scene.bounded_spaces(host))
        if first.GlobalId not in bounded:
            continue
        if outside:
            if len(bounded) == 1 or _is_external(host):
                hits.append(element.GlobalId)
        elif second.GlobalId in bounded:
            hits.append(element.GlobalId)
    return sorted(set(hits))


def _resolve_bounds(anchor: Anchor, scene: Scene) -> list[str]:
    space = scene.by_guid(anchor.params["space_guid"])
    if space is None:
        return []
    return sorted({guid for guid in scene.space_elements(space)
                   if _family_of(scene, guid) == anchor.family})


def _plan_overlap(first, second) -> float:
    """Area two plan footprints share, in square metres."""
    width = min(first.hi[0], second.hi[0]) - max(first.lo[0], second.lo[0])
    depth = min(first.hi[1], second.hi[1]) - max(first.lo[1], second.lo[1])
    if width <= 0 or depth <= 0:
        return 0.0
    return float(width * depth)


def _resolve_under(anchor: Anchor, scene: Scene) -> list[str]:
    """The element of the family that the storey's walls stand on.

    The answer depends on the storey and the family and on nothing else, and
    the draw asks for it once per candidate element, so it is worked out once
    per storey and kept on the scene, which is what ``on_storey`` does with
    its own grouping.
    """
    memo = getattr(scene, "_under_memo", None)
    if memo is None:
        memo = {}
        setattr(scene, "_under_memo", memo)
    key = (anchor.params["storey_guid"], anchor.family)
    if key not in memo:
        memo[key] = _under_answer(anchor, scene)
    return list(memo[key])


def _under_answer(anchor: Anchor, scene: Scene) -> list[str]:
    storey_guid = anchor.params["storey_guid"]
    walls = [w for w in scene.on_storey("wall", storey_guid)
             if scene.world_box(w) is not None]
    if not walls:
        return []
    boxes = [scene.world_box(w) for w in walls]
    base = min(float(b.lo[2]) for b in boxes)
    ground = Extent(lo=np.array([min(float(b.lo[0]) for b in boxes),
                                min(float(b.lo[1]) for b in boxes), 0.0]),
                    hi=np.array([max(float(b.hi[0]) for b in boxes),
                                 max(float(b.hi[1]) for b in boxes), 0.0]))
    area = max(float((ground.hi[0] - ground.lo[0])
                     * (ground.hi[1] - ground.lo[1])), 1e-9)
    named = {w.GlobalId for w in walls}
    scored = []
    for candidate in _family_members(scene, anchor.family):
        if candidate.GlobalId in named:
            continue
        box = scene.world_box(candidate)
        if box is None:
            continue
        drop = base - float(box.hi[2])
        if drop < -UNDER_RISE or drop > UNDER_GAP:
            continue
        share = _plan_overlap(ground, box) / area
        if share < UNDER_SHARE:
            continue
        scored.append((round(share, 9), -round(abs(drop), 9),
                       candidate.GlobalId))
    if not scored:
        return []
    best = max(scored)[:2]
    return sorted(guid for share, near, guid in scored
                  if (share, near) == best)


#: The relationships a sentence names as the one an element does not have.
MISSING_RELATIONS = ("connection", "space boundary")


def _resolve_without_relation(anchor: Anchor, scene: Scene) -> list[str]:
    relation = anchor.params["relation"]
    hits = []
    for element in _on_storey(scene, anchor.family,
                              anchor.params["storey_guid"]):
        if relation == "connection":
            related = scene.connected(element)
        elif relation == "space boundary":
            related = scene.bounded_spaces(element)
        else:
            return []
        if not related:
            hits.append(element.GlobalId)
    return sorted(hits)


# ---------------------------------------------- builders, 0.8.0 references


def host_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming a wall through a door or a window it holds."""
    if scene.family_of(product) != "wall":
        return []
    out: list[Anchor] = []
    for guid in scene.hosted_by(product):
        filling = scene.by_guid(guid)
        family = scene.family_of(filling) if filling is not None else None
        if family not in ("door", "window"):
            continue
        name = scene.unique_name(filling)
        if not name:
            continue
        for phrase in (f"the wall in which the {family} named '{name}' is "
                       f"located",
                       f"the wall the {family} named '{name}' sits in",
                       f"the wall that holds the {family} named '{name}'"):
            out.append(Anchor(kind="host_of", family="wall", phrase=phrase,
                              params={"element_guid": guid}))
    rng.shuffle(out)
    return out[:limit]


def joins_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming a door or a window through the rooms it joins."""
    family = scene.family_of(product)
    if family not in ("door", "window"):
        return []
    host_guid = scene.host_of(product)
    host = scene.by_guid(host_guid) if host_guid else None
    if host is None:
        return []
    rooms = [(s, scene.space_phrase(s)) for s in
             (scene.by_guid(g) for g in scene.bounded_spaces(host))
             if s is not None]
    rooms = [(s, phrase) for s, phrase in rooms if phrase]
    out: list[Anchor] = []
    if len(rooms) >= 2:
        (first, one), (second, two) = rooms[0], rooms[1]
        params = {"space_a_guid": first.GlobalId,
                  "space_b_guid": second.GlobalId}
        for phrase in (f"the {family} that connects the {one} to the {two}",
                       f"the {family} between the {one} and the {two}",
                       f"the {family} joining the {one} and the {two}"):
            out.append(Anchor(kind="joins", family=family, phrase=phrase,
                              params=dict(params)))
    if rooms and (len(rooms) == 1 or _is_external(host)):
        first, one = rooms[0]
        params = {"space_a_guid": first.GlobalId, "outside": True}
        for phrase in (f"the {family} that connects the {one} to the outside",
                       f"the {family} that leads from the {one} to the "
                       f"outside"):
            out.append(Anchor(kind="joins", family=family, phrase=phrase,
                              params=dict(params)))
    rng.shuffle(out)
    return out[:limit]


def bounds_anchors(scene: Scene, product, rng, limit: int = 4) -> list[Anchor]:
    """Anchors naming an element through the one room it bounds."""
    family = scene.family_of(product)
    if family is None or family in ("space", "storey"):
        return []
    out: list[Anchor] = []
    for guid in scene.bounded_spaces(product):
        space = scene.by_guid(guid)
        phrase = scene.space_phrase(space) if space is not None else None
        if not phrase:
            continue
        for words in (f"the {ARTICLE[family]} that bounds the {phrase}",
                      f"the {ARTICLE[family]} bounding the {phrase}"):
            out.append(Anchor(kind="bounds", family=family, phrase=words,
                              params={"space_guid": guid}))
    rng.shuffle(out)
    return out[:limit]


def under_anchors(scene: Scene, product, rng, limit: int = 2) -> list[Anchor]:
    """Anchors naming a slab through the walls that stand on it."""
    family = scene.family_of(product)
    if family != "slab":
        return []
    out: list[Anchor] = []
    for storey in scene.storeys:
        label = scene.storey_label(storey)
        if not label:
            continue
        probe = Anchor(kind="under", family=family, phrase="",
                       params={"storey_guid": storey.GlobalId})
        if _resolve_under(probe, scene) != [product.GlobalId]:
            continue
        for words in (f"the {family} below the walls of {label}",
                      f"the {family} the walls of {label} stand on"):
            out.append(Anchor(kind="under", family=family, phrase=words,
                              params={"storey_guid": storey.GlobalId}))
    rng.shuffle(out)
    return out[:limit]


def without_relation_anchors(scene: Scene, product, rng, limit: int = 4
                             ) -> list[Anchor]:
    """Anchors naming an element by the one relationship it does not have."""
    family = scene.family_of(product)
    if family is None or family == "storey":
        return []
    storey = scene.storey_of(product)
    label = scene.storey_label(storey) if storey is not None else None
    if not label:
        return []
    out: list[Anchor] = []
    # The sentence names the relationship in the same words the lookup takes,
    # so the trajectory's call quotes nothing the reader was not given.
    if not scene.connected(product):
        params = {"storey_guid": storey.GlobalId, "relation": "connection"}
        for words in (f"the only {ARTICLE[family]} on {label} that has no "
                      f"connection to another element",
                      f"the {ARTICLE[family]} on {label} with no connection "
                      f"to any other element"):
            out.append(Anchor(kind="without_relation", family=family,
                              phrase=words, params=dict(params)))
    if family != "space" and not scene.bounded_spaces(product):
        params = {"storey_guid": storey.GlobalId,
                  "relation": "space boundary"}
        for words in (f"the only {ARTICLE[family]} on {label} that has no "
                      f"space boundary",
                      f"the {ARTICLE[family]} on {label} recorded with no "
                      f"space boundary"):
            out.append(Anchor(kind="without_relation", family=family,
                              phrase=words, params=dict(params)))
    rng.shuffle(out)
    return out[:limit]
