"""The Revit-export creation family (0.10.0).

Create tasks for six element classes, walls, slabs, columns, rooms, doors and
windows, each worded in three styles:

* **box** (``direct``): the instruction quotes the corner of the element's
  bounding box and its extents, in the storey's own coordinates;
* **relation** (``topological``): the position follows from named elements,
  as in "the wall that closes the gap between the walls A and B";
* **relative** (``spatial``): the position is a stated offset from a named
  element, as in "the minimum corner of the wall A shifted by (0, 1.2, 0.9)".

Every instruction also states the relationships the new element has to carry:
the walls it joins, the column it stands on, the rooms it bounds.  The gold
model carries what a Revit export writes for such an element: a type of the
right size (the file's own or a new generic one), the name "<type>:<tag>", the
property sets Revit writes for the class, the type's material, and the
relationships.  It is built by the editing sandbox's own helper library
(``modifc_harness.veribim_geom``) through ``goldlib.revit_*``, so a trajectory
that calls the library with the instruction's numbers rebuilds it exactly.

As in every family, the parameters are drawn first on a real building and the
instruction is rendered from them.  A position a relation or an offset
describes is computed by the same library function a trajectory calls, so the
gold and the answer agree to the last digit.  The draw keeps the generator's
placement rules: a new element stands inside its storey's footprint, takes no
matter another element of its storey already holds, overlaps no element of its
own class on any storey, and a new door or window keeps ten centimetres of wall
clear of every filling the wall already carries and ten above its head.

The family is selected by name (``op.create.revit`` in a run's family shares,
or the ``modifc_gen.revit_run`` driver); a run that does not name it draws
exactly what it drew before.
"""

from __future__ import annotations

import math
from typing import Any, Optional, Sequence

import numpy as np

from . import goldlib, ops
from .anchors import Anchor
from .ops import Call, EditPlan
from .scene import Scene

#: The family's tag in a record's ``families`` list, and one tag per style.
FAMILY_TAG = "op.create.revit"
STYLE_TAG = {"box": "op.create.revit.box",
             "relation": "op.create.revit.relation",
             "relative": "op.create.revit.relative"}
STYLES = ("box", "relation", "relative")
STYLE_CATEGORY = {"box": "direct", "relation": "topological",
                  "relative": "spatial"}
CATEGORY_CODE = {"direct": "DIR", "topological": "TOP", "spatial": "SPA"}

CLASSES = ("wall", "slab", "column", "space", "door", "window")
IFC_CLASS = {"wall": "IfcWall", "slab": "IfcSlab", "column": "IfcColumn",
             "space": "IfcSpace", "door": "IfcDoor", "window": "IfcWindow"}
FAMILY_CODE = {"wall": "RVW", "slab": "RVS", "column": "RVC", "space": "RVR",
               "door": "RVD", "window": "RVN"}
EDIT_KIND = {family: f"create_revit_{family}" for family in CLASSES}
GOLD_CALL = {"wall": "revit_wall", "slab": "revit_slab", "column": "revit_column",
             "space": "revit_space", "door": "revit_filling",
             "window": "revit_filling"}

#: What the score has to read for this family's edit to be visible in full:
#: the type an element is put under and the material it is given are compared
#: by name, as two more semantic properties.
SCORER_SETTINGS = {"properties_include_material": True,
                   "properties_include_type": True}

#: Words an instruction uses for each class.
NOUN = {"wall": "wall", "slab": "slab", "column": "column", "space": "room",
        "door": "door", "window": "window"}
PLURAL = {"wall": "walls", "slab": "slabs", "column": "columns",
          "space": "rooms", "door": "doors", "window": "windows"}

#: The tallest wall, column or room a draw creates, in metres.  A pair of walls
#: that rises through several storeys does not set the height of a new one.
MAX_HEIGHT = 6.0

#: How many candidate constructions one draw tries before it gives up.
MAX_TRIES = 40

#: A stated relationship's two ends meet: the partner's box comes within this
#: many metres of the new element's.
TOUCH = 0.15

#: Share of a new element's box any one element may already hold.
COLLISION_SHARE = ops.COLLISION_SHARE

#: Wall thicknesses, slab thicknesses, column sections and leaf sizes a draw
#: picks from when the file offers none of its own.
WALL_THICKNESSES = (0.1, 0.125, 0.15, 0.2, 0.24, 0.25, 0.3)
SLAB_THICKNESSES = (0.15, 0.18, 0.2, 0.25, 0.3)
COLUMN_SIDES = (0.25, 0.3, 0.35, 0.4, 0.45, 0.5)
DOOR_SIZES = ((0.81, 2.04), (0.864, 2.134), (0.915, 2.134), (0.9, 2.1), (1.0, 2.1),
              (0.762, 2.032))
WINDOW_SIZES = ((0.6, 1.2), (0.9, 1.2), (1.2, 1.5), (1.5, 1.2), (1.8, 1.5),
                (0.9, 1.5))
WINDOW_SILLS = (0.6, 0.75, 0.8, 0.9, 1.0)

#: Share of draws that name the referenced elements by their names rather than
#: by their GlobalIds, where every one of them has a name of its own.
BY_NAME_SHARE = 0.25


def library():
    return goldlib._revit_library()


def task_id_for(model_key: str, family: str, style: str, index: int) -> str:
    return (f"{FAMILY_CODE[family]}-CRE-{CATEGORY_CODE[STYLE_CATEGORY[style]]}-"
            f"{model_key}-{index:03d}")


# ------------------------------------------------------------------ numbers


def num(value: float, places: int = 3) -> str:
    """A length as an instruction writes it: up to millimetres, no trailing zeros."""
    text = f"{round(float(value), places):.{places}f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _r(value: float, places: int = 3) -> float:
    out = float(round(float(value), places))
    return 0.0 if out == 0.0 else out


def triple(values, places: int = 3) -> str:
    return "(" + ", ".join(num(v, places) for v in values) + ")"


# ------------------------------------------------------------------ the frame


class Frame:
    """One storey of one scene, read the way the draws need it.

    Positions are storey coordinates in metres.  Only storeys whose own axes
    are the world's are drawn on, so a storey coordinate is a world
    coordinate less the storey's origin.
    """

    def __init__(self, scene: Scene, storey):
        self.scene = scene
        self.storey = storey
        self.lib = library()
        matrix = scene.matrix(storey)
        self.origin = np.array(matrix[:3, 3], dtype=float)

    def box(self, product):
        """The product's box in storey coordinates, from the geometry index."""
        box = self.scene.world_box(product)
        if box is None:
            return None
        return box.lo - self.origin, box.hi - self.origin

    def exact(self, product):
        """The product's raw body box in storey coordinates, measured afresh."""
        with self.lib.guid_source(None, quiet=True):
            return self.lib._storey_box(product, self.storey)

    def place(self, name: str, *args, **kwargs) -> dict:
        """Run one of the library's placing functions, silently."""
        with self.lib.guid_source(None, quiet=True):
            return getattr(self.lib, name)(*args, **kwargs)

    def on(self, family: str) -> list:
        return list(self.scene.on_storey(family, self.storey.GlobalId))


def usable_storeys(scene: Scene, rng) -> list:
    out = []
    for storey in scene.storeys:
        if scene.matrix(storey) is None or not ops.storey_world_aligned(scene, storey):
            continue
        if scene.storey_footprint(storey) is None:
            continue
        out.append(storey)
    rng.shuffle(out)
    return out


# ------------------------------------------------------------------ the rules


def stated_height(scene: Scene, storey, shared: float) -> Optional[float]:
    """The height a new element is given, from the height its neighbours share.

    Neighbours that rise through several storeys do not set it: the element is
    then as tall as the storey, which still stays within what they share.
    """
    if shared < 2.0:
        return None
    if shared <= MAX_HEIGHT:
        return _r(shared, 2)
    level = _r(min(ops._storey_height(scene, storey), shared), 2)
    return level if level >= 2.0 else None


def _lattice(lo, hi, per_axis: int) -> np.ndarray:
    return ops.sample_box(np.identity(4), lo, hi, per_axis)


def _same_class_share(scene: Scene, ifc_class: str, lo_w, hi_w,
                      skip: set) -> float:
    index = scene.geometry_index()
    if index["guid"].size == 0:
        return 0.0
    near = np.all(index["lo"] <= hi_w + 1e-6, axis=1) & \
        np.all(index["hi"] >= lo_w - 1e-6, axis=1)
    worst = 0.0
    for position in np.where(near)[0]:
        if not str(index["cls"][position]).startswith(ifc_class):
            continue
        if str(index["guid"][position]) in skip:
            continue
        for per_axis in ops.COLLISION_GRIDS:
            points = _lattice(lo_w, hi_w, per_axis)
            inside = np.all(points >= index["lo"][position] - 1e-6, axis=1) & \
                np.all(points <= index["hi"][position] + 1e-6, axis=1)
            worst = max(worst, float(inside.mean()))
    return worst


def _framing_share(scene: Scene, storey_guid: str, lo_w, hi_w, skip: set,
                   prefixes=("IfcWall", "IfcColumn", "IfcBeam",
                             "IfcCurtainWall", "IfcStair", "IfcRamp")) -> float:
    """Share of a room's box the storey's structure already holds."""
    index = scene.geometry_index()
    if index["guid"].size == 0:
        return 0.0
    here = (index["storey"] == storey_guid) | (index["storey"] == "")
    near = here & np.all(index["lo"] <= hi_w + 1e-6, axis=1) & \
        np.all(index["hi"] >= lo_w - 1e-6, axis=1)
    worst = 0.0
    for position in np.where(near)[0]:
        if not str(index["cls"][position]).startswith(prefixes):
            continue
        if str(index["guid"][position]) in skip:
            continue
        for per_axis in ops.COLLISION_GRIDS:
            points = _lattice(lo_w, hi_w, per_axis)
            inside = np.all(points >= index["lo"][position] - 1e-6, axis=1) & \
                np.all(points <= index["hi"][position] + 1e-6, axis=1)
            worst = max(worst, float(inside.mean()))
    return worst


def fault(frame: Frame, family: str, origin, extents,
          skip: Sequence = ()) -> Optional[str]:
    """Why a box may not hold a new element of one class, or None."""
    scene = frame.scene
    lo = np.asarray(origin, dtype=float)
    hi = lo + np.asarray(extents, dtype=float)
    if np.any(hi - lo <= 0.0):
        return "revit_empty_box"
    lo_w, hi_w = lo + frame.origin, hi + frame.origin
    footprint = scene.storey_footprint(frame.storey)
    if footprint is not None and (
            np.any(lo_w[:2] < footprint.lo[:2] - 0.05)
            or np.any(hi_w[:2] > footprint.hi[:2] + 0.05)):
        return "revit_outside_storey"
    skipped = {getattr(s, "GlobalId", s) for s in skip}
    if family == "space":
        if _framing_share(scene, frame.storey.GlobalId, lo_w, hi_w,
                          skipped) > COLLISION_SHARE:
            return "revit_room_crossed"
    elif family not in ("door", "window"):
        share = max(scene.occupied_share(_lattice(lo_w, hi_w, n),
                                         frame.storey.GlobalId, skipped)
                    for n in ops.COLLISION_GRIDS)
        if share > COLLISION_SHARE:
            return "revit_collides"
    if _same_class_share(scene, IFC_CLASS[family], lo_w, hi_w,
                         skipped) > COLLISION_SHARE:
        return "revit_overlaps_same_class"
    return None


def rooms_touching(frame: Frame, origin, extents, want: int = 2,
                   skip: Sequence = ()) -> list:
    """Rooms of the storey whose box comes within ``TOUCH`` of a box."""
    lo = np.asarray(origin, dtype=float)
    hi = lo + np.asarray(extents, dtype=float)
    skipped = {getattr(s, "GlobalId", s) for s in skip}
    scored = []
    for space in frame.on("space"):
        if space.GlobalId in skipped:
            continue
        box = frame.box(space)
        if box is None:
            continue
        apart = np.maximum(np.maximum(box[0] - hi, lo - box[1]), 0.0)
        gap = float(np.linalg.norm(apart))
        if gap <= TOUCH:
            scored.append((gap, space.GlobalId, space))
    scored.sort(key=lambda item: (item[0], item[1]))
    return [space for _gap, _guid, space in scored[:want]]


# ------------------------------------------------------------------ naming


def _name_table(scene: Scene) -> dict:
    table = getattr(scene, "_revit_names", None)
    if table is None:
        table = {}
        for product in scene.model.by_type("IfcProduct"):
            for label in (getattr(product, "Name", None),
                          getattr(product, "LongName", None)):
                label = str(label or "").strip()
                if label:
                    table[label] = table.get(label, 0) + 1
        setattr(scene, "_revit_names", table)
    return table


def label_of(scene: Scene, element) -> Optional[str]:
    """A name only this element carries in the whole model, or None."""
    table = _name_table(scene)
    candidates = []
    if element.is_a("IfcSpace"):
        candidates.append(getattr(element, "LongName", None))
    candidates.append(element.Name)
    for label in candidates:
        label = str(label or "").strip()
        if label and table.get(label) == 1 and "'" not in label \
                and len(label) <= 60 and len(label) != 22:
            return label
    return None


class Namer:
    """How one instruction refers to the elements it names."""

    def __init__(self, scene: Scene, elements: Sequence, rng):
        self.scene = scene
        named = [e for e in elements if e is not None]
        labels = {e.GlobalId: label_of(scene, e) for e in named}
        fillings_only = all(e.is_a("IfcDoor") or e.is_a("IfcWindow") for e in named)
        self.by_name = bool(named) and all(labels.values()) and not fillings_only \
            and rng.random() < BY_NAME_SHARE
        self.labels = labels if self.by_name else {}

    def token(self, element) -> str:
        label = self.labels.get(element.GlobalId) if self.by_name else None
        return f"'{label}'" if label else element.GlobalId

    def one(self, family: str, element) -> str:
        return f"the {NOUN[family]} {self.token(element)}"

    def many(self, family: str, elements: Sequence) -> str:
        elements = list(elements)
        if len(elements) == 1:
            return self.one(family, elements[0])
        tokens = [self.token(e) for e in elements]
        joined = ", ".join(tokens[:-1]) + " and " + tokens[-1]
        return f"the {PLURAL[family]} {joined}"


def family_of(scene: Scene, element) -> str:
    family = scene.family_of(element)
    return family or "wall"


# ------------------------------------------------------------------ the plan


def _seed(task_id: str) -> str:
    return task_id


def _plan(scene: Scene, family: str, style: str, task_id: str, frame: Frame,
          origin, extents, extra: dict, references: Sequence,
          relation_edges: list, relation_classes: list,
          host=None) -> EditPlan:
    """The edit plan of one drawn task, with its gold call."""
    seed = _seed(task_id)
    taken = lambda guid: scene.by_guid(guid) is not None  # noqa: E731
    guid = goldlib.first_free_minted(seed, taken)
    created = [guid]
    if family in ("door", "window"):
        index = 0
        seen = {guid}
        while True:
            candidate = goldlib.mint_sequence(seed, index)
            index += 1
            if candidate in seen or taken(candidate):
                continue
            created.append(candidate)
            break
    origin = [float(v) for v in origin]
    extents = [float(v) for v in extents]
    storey_guid = frame.storey.GlobalId
    bounds = [r.GlobalId for r in extra.get("bounds", ())]
    if family == "wall":
        args = (guid, seed, storey_guid, *origin, *extents,
                [w.GlobalId for w in extra.get("connect", ())], bounds)
    elif family == "slab":
        args = (guid, seed, storey_guid, *origin, *extents, bounds, [])
    elif family == "column":
        below = extra.get("stands_on")
        args = (guid, seed, storey_guid, *origin, *extents,
                below.GlobalId if below is not None else None, bounds)
    elif family == "space":
        args = (guid, seed, storey_guid, *origin, *extents,
                [e.GlobalId for e in extra.get("bounded_by", ())], None)
    else:
        args = (guid, seed, IFC_CLASS[family], host.GlobalId, *origin, *extents,
                bounds)
    call = Call(GOLD_CALL[family], args,
                f"create the {NOUN[family]} as a Revit export writes it")
    touched = [guid] + ([host.GlobalId] if host is not None else [])
    tags = [FAMILY_TAG, STYLE_TAG[style]]
    if any(edge[0] == "IfcRelSpaceBoundary" for edge in relation_edges):
        tags.append("constraint.relation_on_create.space_boundary")
    if any(edge[0] == "IfcRelConnectsElements" for edge in relation_edges):
        tags.append("constraint.relation_on_create.connection")
    revit = {"style": style, "class": family,
             "construction": extra.get("construction"),
             "placer": extra.get("placer"),
             "placer_args": _guids_of(extra.get("placer_args") or {}),
             "origin": origin, "extents": extents,
             "references": [e.GlobalId for e in references if e is not None],
             "by_name": bool(extra.get("by_name")),
             "stated": extra.get("stated") or {}}
    params = {"storey_guid": storey_guid, "revit": revit,
              "families": tags, "relation_edges": relation_edges,
              "relation_classes": sorted(set(relation_classes)),
              "magnitude": ops.magnitude_bucket(scene, float(max(extents))),
              "entity_type": IFC_CLASS[family]}
    if host is not None:
        params["host_guid"] = host.GlobalId
    return EditPlan(kind=EDIT_KIND[family], operation="create", family=family,
                    calls=[call], target_guids=(guid,),
                    created_guids=tuple(created), touched_guids=tuple(touched),
                    params=params)


def _guids_of(args: dict) -> dict:
    """Placer arguments as the record stores them: elements by GlobalId."""
    out = {}
    for key, value in args.items():
        if isinstance(value, (list, tuple)):
            out[key] = [getattr(v, "GlobalId", v) for v in value]
        else:
            out[key] = getattr(value, "GlobalId", value)
    return out


def _edges(family: str, guid_role: str, extra: dict, storey) -> tuple[list, list]:
    """The relationships the gold writes, as funnel edges and class names.

    The created element's identifier is filled in later, so the edges carry a
    placeholder for it that ``finish`` replaces.
    """
    edges: list = []
    classes = ["IfcRelDefinesByType", "IfcRelDefinesByProperties"]
    if family == "space":
        classes.append("IfcRelAggregates")
        for element in extra.get("bounded_by", ()):
            edges.append(["IfcRelSpaceBoundary", "@", element.GlobalId])
    else:
        classes.append("IfcRelContainedInSpatialStructure")
        for room in extra.get("bounds", ()):
            edges.append(["IfcRelSpaceBoundary", room.GlobalId, "@"])
    if family in ("wall", "slab"):
        classes.append("IfcRelAssociatesMaterial")
    if family == "wall":
        for wall in extra.get("connect", ()):
            edges.append(["IfcRelConnectsElements", "@", wall.GlobalId])
    if family == "column" and extra.get("stands_on") is not None:
        edges.append(["IfcRelConnectsElements", "@", extra["stands_on"].GlobalId])
    if family in ("door", "window"):
        classes += ["IfcRelVoidsElement", "IfcRelFillsElement"]
    for edge in edges:
        classes.append(edge[0])
    return edges, classes


def finish(scene: Scene, family: str, style: str, task_id: str, frame: Frame,
           origin, extents, extra: dict, references: Sequence, text: str,
           host=None):
    """Turn a drawn construction into a plan, an anchor and an instruction."""
    from .generate import Draw

    edges, classes = _edges(family, "@", extra, frame.storey)
    plan = _plan(scene, family, style, task_id, frame, origin, extents, extra,
                 references, [], classes, host)
    guid = plan.created_guids[0]
    plan.params["relation_edges"] = [[e[0], guid if e[1] == "@" else e[1],
                                      guid if e[2] == "@" else e[2]] for e in edges]
    if any(e[0] == "IfcRelSpaceBoundary" for e in edges):
        ops.tag(plan, "constraint.relation_on_create.space_boundary")
    if any(e[0] == "IfcRelConnectsElements" for e in edges):
        ops.tag(plan, "constraint.relation_on_create.connection")
    storey = frame.storey
    phrase = f"storey {storey.GlobalId}"
    anchor = Anchor(kind="guid", family="storey", phrase=phrase,
                    params={"guid": storey.GlobalId})
    plan.params["where"] = phrase
    plan.params["wording"] = {"unit": "m", "unit_word": "m",
                              "request_form": "imperative",
                              "anchor_phrase": phrase, "tags": []}
    return Draw(plan, anchor, (storey.GlobalId,), STYLE_CATEGORY[style], text,
                IFC_CLASS[family])


# ------------------------------------------------------------------ phrasing


def _pick(rng, options: Sequence[str]) -> str:
    return options[int(rng.random() * len(options)) % len(options)]


def _rooms_clause(namer: Namer, rooms: Sequence, rng, what: str = "it") -> str:
    rooms = list(rooms)
    if not rooms:
        return ""
    target = namer.many("space", rooms)
    return _pick(rng, (
        f" Record {what} as a space boundary of {target}.",
        f" Add the space boundaries between {what} and {target}.",
        f" {what.capitalize()} also bounds {target}; write those space boundaries.",
    ))


def _box_words(origin, extents, rng) -> str:
    x, y, z = origin
    dx, dy, dz = extents
    return _pick(rng, (
        f"the lowest corner of its bounding box at {triple(origin)} and extents of "
        f"{num(dx)} m along x, {num(dy)} m along y and {num(dz)} m along z",
        f"a bounding box that begins at {triple(origin)} and reaches {num(dx)} m in "
        f"the +x direction, {num(dy)} m in +y and {num(dz)} m upwards",
        f"a bounding box with minimum point {triple(origin)} and size "
        f"{num(dx)} x {num(dy)} x {num(dz)} m (x, y, z)",
    ))


def _frame_words(rng) -> str:
    return _pick(rng, ("in the storey's own coordinates",
                       "measured in the storey's local frame",
                       "in storey coordinates"))


# ------------------------------------------------------------------ walls


def _thin(box, longest: float = 1.5, thickest: float = 0.6) -> Optional[int]:
    """The run axis of a thin axis-aligned element's box, or None."""
    size = box[1] - box[0]
    run = 0 if size[0] >= size[1] else 1
    if size[run] < longest or size[1 - run] > thickest or size[2] < 2.0:
        return None
    return run


def facing_pairs(frame: Frame, rng, limit: int = 60) -> list:
    """Pairs of parallel walls of the storey facing each other across a gap."""
    walls = []
    for wall in frame.on("wall"):
        box = frame.box(wall)
        if box is None:
            continue
        run = _thin(box)
        if run is not None:
            walls.append((wall, box, run))
    rng.shuffle(walls)
    walls = walls[:160]
    pairs = []
    for i in range(len(walls)):
        a, box_a, run = walls[i]
        for j in range(i + 1, len(walls)):
            b, box_b, run_b = walls[j]
            if run_b != run:
                continue
            across = 1 - run
            if box_a[1][across] <= box_b[0][across]:
                gap = box_b[0][across] - box_a[1][across]
            elif box_b[1][across] <= box_a[0][across]:
                gap = box_a[0][across] - box_b[1][across]
            else:
                continue
            if not 1.5 <= gap <= 10.0:
                continue
            stretch = min(box_a[1][run], box_b[1][run]) - max(box_a[0][run], box_b[0][run])
            if stretch < 1.2:
                continue
            pairs.append((a, b))
    rng.shuffle(pairs)
    return pairs[:limit]


def _wall_thickness(scene: Scene, rng) -> float:
    lib = library()
    own = sorted({round(t, 3) for t in (lib.layer_thickness(w)
                                        for w in scene.model.by_type("IfcWallType"))
                  if t is not None and 0.05 <= t <= 0.5})
    if own and rng.random() < 0.5:
        return float(own[int(rng.random() * len(own)) % len(own)])
    return float(WALL_THICKNESSES[int(rng.random() * len(WALL_THICKNESSES))
                                  % len(WALL_THICKNESSES)])


def _doorway_clear(frame: Frame, walls: Sequence, run: int, low: float,
                   high: float) -> bool:
    """A new wall's span along the two walls stays clear of their fillings."""
    for wall in walls:
        for guid in frame.scene.hosted_by(wall):
            filling = frame.scene.by_guid(guid)
            box = frame.box(filling) if filling is not None else None
            if box is None:
                continue
            if box[0][run] < high + 0.1 and box[1][run] > low - 0.1:
                return False
    return True


def draw_wall(scene: Scene, style: str, task_id: str, rng):
    for storey in usable_storeys(scene, rng):
        frame = Frame(scene, storey)
        for a, b in facing_pairs(frame, rng):
            try:
                run, gap, stretch, base, top = frame.place("_facing", a, b, storey)
            except Exception:
                continue
            height = stated_height(scene, storey, top - base)
            if height is None:
                ops.note_rejection("revit_wall_height_out_of_range")
                continue
            thickness = _wall_thickness(scene, rng)
            if stretch[1] - stretch[0] < thickness + 0.6:
                continue
            across = 1 - run
            extra: dict = {"connect": [a, b]}
            stated: dict = {"thickness": thickness, "height": height}
            references = [a, b]
            if style == "relation":
                spot = frame.place("wall_between", a, b, storey, thickness,
                                   height=height)
                origin, extents = spot["origin"], spot["extents"]
                extra.update(construction="closes_gap", placer="wall_between",
                             placer_args={"a": a, "b": b, "thickness": thickness,
                                          "height": height})
            elif style == "relative" and rng.random() < 0.6:
                found = None
                doors = [scene.by_guid(g) for w in (a, b) for g in scene.hosted_by(w)]
                doors = [d for d in doors if d is not None and d.is_a("IfcDoor")]
                rng.shuffle(doors)
                for door in doors[:4]:
                    box = frame.box(door)
                    if box is None:
                        continue
                    sign = 1 if rng.random() < 0.5 else -1
                    distance = _r(rng.uniform(0.3, 2.0), 2)
                    word = ("+" if sign > 0 else "-") + "xy"[run]
                    try:
                        spot = frame.place("wall_from_jamb", door, a, b, storey,
                                           distance, word, thickness, height=height)
                    except Exception:
                        continue
                    found = (door, distance, word, spot)
                    break
                if found is None:
                    ops.note_rejection("revit_wall_no_jamb")
                    continue
                door, distance, word, spot = found
                origin, extents = spot["origin"], spot["extents"]
                extra.update(construction="from_jamb", placer="wall_from_jamb",
                             door=door,
                             placer_args={"door": door, "a": a, "b": b,
                                          "distance": distance, "direction": word,
                                          "thickness": thickness, "height": height})
                stated.update(distance=distance, direction=word)
                references.append(door)
            else:
                low = rng.uniform(stretch[0] + 0.2, stretch[1] - 0.2 - thickness)
                origin = [0.0, 0.0, base]
                extents = [0.0, 0.0, height]
                origin[across], extents[across] = gap[0], gap[1] - gap[0]
                origin[run], extents[run] = low, thickness
                origin = [_r(v) for v in origin]
                extents = [_r(v) for v in extents]
                if style == "relative":
                    corner = frame.exact(a)[0]
                    offset = [_r(origin[i] - corner[i]) for i in range(3)]
                    spot = frame.place("corner_from", a, storey, offset)
                    origin = list(spot)
                    extra.update(construction="from_corner", placer="corner_from",
                                 corner_of=a,
                                 placer_args={"reference": a, "offset": offset})
                    stated.update(offset=offset, extents=extents)
                else:
                    extra.update(construction="box", placer=None)
            low_run = origin[run]
            if not _doorway_clear(frame, (a, b), run, low_run,
                                  low_run + extents[run]):
                ops.note_rejection("revit_wall_blocks_filling")
                continue
            why = fault(frame, "wall", origin, extents, skip=(a, b))
            if why is not None:
                ops.note_rejection(why)
                continue
            rooms = rooms_touching(frame, origin, extents, 2)
            extra["bounds"] = rooms
            namer = Namer(scene, references + rooms, rng)
            extra["by_name"] = namer.by_name
            extra["stated"] = stated
            text = _wall_text(style, namer, frame, a, b, rooms, origin, extents,
                              extra, stated, rng)
            return finish(scene, "wall", style, task_id, frame, origin, extents,
                          extra, references + rooms, text), ""
    return None, "revit_no_wall_site"


def _wall_text(style, namer, frame, a, b, rooms, origin, extents, extra, stated,
               rng) -> str:
    storey = frame.storey.GlobalId
    walls = namer.many("wall", [a, b])
    joins = _pick(rng, (
        f"Add a path connection from the new wall to each of {walls}.",
        f"Link the new wall to {walls} through path connections.",
        f"It meets {walls}; record each join as a path connection.",
    ))
    rooms_part = _rooms_clause(namer, rooms, rng)
    if style == "box":
        head = _pick(rng, (
            f"Add a wall on storey {storey} with {_box_words(origin, extents, rng)}, "
            f"{_frame_words(rng)}.",
            f"Create a new wall in storey {storey}. Give it "
            f"{_box_words(origin, extents, rng)} ({_frame_words(rng)}).",
            f"Model one more wall on storey {storey}: "
            f"{_box_words(origin, extents, rng)}, {_frame_words(rng)}.",
        ))
        return f"{head} {joins}{rooms_part}"
    t, h = num(stated["thickness"]), num(stated["height"], 2)
    if style == "relation":
        head = _pick(rng, (
            f"On storey {storey}, {walls} are parallel and face each other. "
            f"Close the space between them with a new wall at right angles to both, "
            f"running from the face of one to the face of the other and centred on "
            f"the length where they overlap. Make it {t} m thick and {h} m high, "
            f"standing on the same base as those walls.",
            f"Put a new wall on storey {storey} that spans the space separating "
            f"{walls}, which run side by side. It is perpendicular to both, touches "
            f"each of them, sits midway along the stretch they share, is {t} m thick "
            f"and rises {h} m from their common base.",
            f"Between {walls} on storey {storey} there is an open gap. Fill it with "
            f"a wall {t} m thick and {h} m tall that runs square to them from one "
            f"face to the other, centred on the part where the two walls face each "
            f"other, with its base level with theirs.",
        ))
        return f"{head} {joins}{rooms_part}"
    if extra["construction"] == "from_jamb":
        door = namer.one("door", extra["door"])
        d, word = num(stated["distance"], 2), stated["direction"]
        head = _pick(rng, (
            f"On storey {storey}, add a wall {t} m thick and {h} m high that spans at "
            f"right angles from {namer.one('wall', a)} to {namer.one('wall', b)}. "
            f"Its face nearer to {door} stands {d} m in the {word} direction from "
            f"the {word} jamb of that door, and its base is level with the two walls.",
            f"Starting {d} m in {word} beyond the {word}-side jamb of {door}, build a "
            f"{t} m thick wall on storey {storey} that crosses square from "
            f"{namer.one('wall', a)} to {namer.one('wall', b)}; it is {h} m tall and "
            f"shares their base.",
        ))
        return f"{head} {joins}{rooms_part}"
    ox = triple(stated["offset"])
    head = _pick(rng, (
        f"On storey {storey}, place a wall whose bounding box starts at the minimum "
        f"corner of {namer.one('wall', a)}'s bounding box moved by {ox} m and measures "
        f"{num(extents[0])} m in x, {num(extents[1])} m in y and {num(extents[2])} m "
        f"in z, all in storey coordinates.",
        f"Take the lowest corner of the bounding box of {namer.one('wall', a)} on "
        f"storey {storey}, add {ox} m to it, and create a wall whose box begins "
        f"there and spans {triple(extents)} m along x, y and z (storey frame).",
    ))
    return f"{head} {joins}{rooms_part}"


# ------------------------------------------------------------------ slabs


def _slab_thickness(scene: Scene, rng) -> float:
    lib = library()
    own = sorted({round(t, 3) for t in (lib.layer_thickness(s)
                                        for s in scene.model.by_type("IfcSlabType")
                                        if str(getattr(s, "PredefinedType", "")) == "FLOOR")
                  if t is not None and 0.08 <= t <= 0.6})
    if own and rng.random() < 0.5:
        return float(own[int(rng.random() * len(own)) % len(own)])
    return float(SLAB_THICKNESSES[int(rng.random() * len(SLAB_THICKNESSES))
                                  % len(SLAB_THICKNESSES)])


def room_walls(frame: Frame, room) -> Optional[list]:
    """The four walls that close a rectangular room, one on each side, or None."""
    box = frame.box(room)
    if box is None:
        return None
    lo, hi = box
    if np.any((hi - lo)[:2] < 1.2):
        return None
    sides = {}
    for wall in frame.on("wall"):
        wbox = frame.box(wall)
        if wbox is None:
            continue
        run = _thin(wbox, longest=0.8)
        if run is None:
            continue
        across = 1 - run
        cover = min(wbox[1][run], hi[run]) - max(wbox[0][run], lo[run])
        if cover < 0.5 * (hi[run] - lo[run]):
            continue
        for key, face, inner in (("low", lo[across], wbox[1][across]),
                                 ("high", hi[across], wbox[0][across])):
            if abs(float(inner) - float(face)) > TOUCH:
                continue
            slot = (across, key)
            if slot not in sides or cover > sides[slot][0]:
                sides[slot] = (cover, wall)
    wanted = [(0, "low"), (0, "high"), (1, "low"), (1, "high")]
    if any(slot not in sides for slot in wanted):
        return None
    return [sides[slot][1] for slot in wanted]


def draw_slab(scene: Scene, style: str, task_id: str, rng):
    for storey in usable_storeys(scene, rng):
        frame = Frame(scene, storey)
        rooms = [r for r in frame.on("space") if frame.box(r) is not None]
        slabs = []
        for slab in frame.on("slab"):
            box = frame.box(slab)
            if box is None:
                continue
            size = box[1] - box[0]
            if 1.0 <= size[0] <= 15.0 and 1.0 <= size[1] <= 15.0 and size[2] <= 0.6:
                slabs.append(slab)
        options = []
        for room in rooms[:60]:
            options.append(("on_room", room))
            options.append(("over_walls", room))
        for slab in slabs[:60]:
            options.append(("above", slab))
        rng.shuffle(options)
        if style == "relation":
            options.sort(key=lambda o: {"over_walls": 0, "on_room": 1,
                                        "above": 2}[o[0]] + rng.random() * 2.5)
        for construction, element in options[:MAX_TRIES]:
            thickness = _slab_thickness(scene, rng)
            extra: dict = {"construction": construction}
            stated: dict = {"thickness": thickness}
            references = [element]
            bounds: list = []
            skip: list = [element]
            try:
                if construction == "on_room":
                    spot = frame.place("slab_on_room", element, storey, thickness)
                    bounds = [element]
                    extra.update(placer="slab_on_room",
                                 placer_args={"room": element, "thickness": thickness})
                elif construction == "over_walls":
                    walls = room_walls(frame, element)
                    if walls is None:
                        continue
                    spot = frame.place("slab_over_walls", walls, storey, thickness)
                    bounds = [element]
                    references = [element] + walls
                    skip += walls
                    extra.update(placer="slab_over_walls", walls=walls,
                                 placer_args={"walls": walls, "thickness": thickness})
                else:
                    distance = float(_pick(rng, (0.6, 0.9, 1.2, 1.5, 2.0, 2.4, 2.7)))
                    spot = frame.place("slab_above", element, storey, distance,
                                       thickness)
                    stated["distance"] = distance
                    extra.update(placer="slab_above",
                                 placer_args={"slab": element, "distance": distance,
                                              "thickness": thickness})
            except Exception:
                continue
            origin, extents = list(spot["origin"]), list(spot["extents"])
            if style == "box":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                extra["placer"] = None
                extra.pop("placer_args", None)
            elif style == "relative":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                corner = frame.exact(element)[0]
                offset = [_r(origin[i] - corner[i]) for i in range(3)]
                origin = list(frame.place("corner_from", element, storey, offset))
                extra.update(placer="corner_from", corner_of=element,
                             placer_args={"reference": element, "offset": offset})
                stated.update(offset=offset, extents=extents)
                references = [element]
            why = fault(frame, "slab", origin, extents, skip=skip)
            if why is not None:
                ops.note_rejection(why)
                continue
            if construction == "above":
                bounds = rooms_touching(frame, origin, extents, 1)
            extra["bounds"] = bounds
            namer = Namer(scene, (references if style != "box" else []) + bounds, rng)
            extra["by_name"] = namer.by_name
            extra["stated"] = stated
            text = _slab_text(style, namer, frame, construction, element, extra,
                              origin, extents, stated, bounds, rng)
            return finish(scene, "slab", style, task_id, frame, origin, extents,
                          extra, references + bounds, text), ""
    return None, "revit_no_slab_site"


def _slab_text(style, namer, frame, construction, element, extra, origin, extents,
               stated, bounds, rng) -> str:
    storey = frame.storey.GlobalId
    rooms_part = _rooms_clause(namer, bounds, rng, "the slab")
    t = num(stated["thickness"])
    if style == "box":
        head = _pick(rng, (
            f"Add a floor slab on storey {storey} with "
            f"{_box_words(origin, extents, rng)}, {_frame_words(rng)}; the z extent "
            f"is its thickness.",
            f"Create a slab in storey {storey} with {_box_words(origin, extents, rng)}"
            f" ({_frame_words(rng)}).",
            f"Model a new floor slab on storey {storey}: "
            f"{_box_words(origin, extents, rng)}, {_frame_words(rng)}.",
        ))
        return f"{head}{rooms_part}"
    if style == "relative":
        reference = namer.one(family_of(namer.scene, element), element)
        ox = triple(stated["offset"])
        head = _pick(rng, (
            f"On storey {storey}, add a floor slab whose bounding box begins at the "
            f"minimum corner of {reference}'s bounding box shifted by {ox} m and "
            f"measures {num(extents[0])} m in x, {num(extents[1])} m in y and "
            f"{num(extents[2])} m in z (storey coordinates).",
            f"Read the lowest corner of the bounding box of {reference} in the "
            f"coordinates of storey {storey}, add {ox} m, and place a slab of "
            f"{triple(extents)} m (x, y, z) with its box starting at that point.",
        ))
        return f"{head}{rooms_part}"
    room = namer.one("space", element) if construction != "above" else ""
    if construction == "over_walls":
        walls = namer.many("wall", extra["walls"])
        head = _pick(rng, (
            f"On storey {storey}, cover {room} with a floor slab {t} m thick that "
            f"reaches the outer faces of {walls}, which enclose that room, with its "
            f"top level with the floor of the storey above.",
            f"Add a {t} m slab over {room} on storey {storey}. In plan it lines up "
            f"with the outer faces of {walls}, which enclose the room; its top face "
            f"is at the elevation of the next storey up.",
        ))
    elif construction == "on_room":
        head = _pick(rng, (
            f"On storey {storey}, add a floor slab {t} m thick that covers the plan "
            f"of {room} and rests on the top of that room's volume.",
            f"Put a {t} m thick slab on storey {storey} directly over {room}: same "
            f"plan rectangle as the room's box, underside at the room's top.",
        ))
    else:
        slab = namer.one("slab", element)
        d = num(stated["distance"], 2)
        head = _pick(rng, (
            f"On storey {storey}, add a floor slab {t} m thick with the same plan "
            f"as {slab}, its underside {d} m above the top face of that slab.",
            f"Copy the plan outline of {slab} into a new {t} m slab on storey "
            f"{storey}, raised so that its underside sits {d} m over the top of "
            f"{slab}.",
        ))
    return f"{head}{rooms_part}"


# ------------------------------------------------------------------ columns


def _rect_columns(frame: Frame) -> list:
    lib = frame.lib
    out = []
    for column in frame.on("column"):
        box = frame.box(column)
        if box is None:
            continue
        section = lib.rectangular_section(column)
        if section is None:
            continue
        plan = tuple(sorted(float(v) for v in (box[1] - box[0])[:2]))
        if abs(plan[0] - section[0]) > 0.01 or abs(plan[1] - section[1]) > 0.01:
            continue
        out.append(column)
    return out


def in_line_pairs(frame: Frame, rng, smallest: float, largest: float,
                  limit: int = 40) -> list:
    """Pairs of walls on one line with a gap between their ends."""
    walls = []
    for wall in frame.on("wall"):
        box = frame.box(wall)
        if box is None:
            continue
        run = _thin(box, longest=0.6)
        if run is not None:
            walls.append((wall, box, run))
    rng.shuffle(walls)
    walls = walls[:200]
    pairs = []
    for i in range(len(walls)):
        a, box_a, run = walls[i]
        for j in range(i + 1, len(walls)):
            b, box_b, run_b = walls[j]
            if run_b != run:
                continue
            across = 1 - run
            low = max(box_a[0][across], box_b[0][across])
            high = min(box_a[1][across], box_b[1][across])
            if high - low < 0.05:
                continue
            if box_a[1][run] <= box_b[0][run]:
                gap = box_b[0][run] - box_a[1][run]
            elif box_b[1][run] <= box_a[0][run]:
                gap = box_a[0][run] - box_b[1][run]
            else:
                continue
            if smallest <= gap <= largest:
                pairs.append((a, b))
    rng.shuffle(pairs)
    return pairs[:limit]


def draw_column(scene: Scene, style: str, task_id: str, rng):
    for storey in usable_storeys(scene, rng):
        frame = Frame(scene, storey)
        options: list = []
        above = scene.storey_neighbour(storey, +1)
        if above is not None and ops.storey_world_aligned(scene, above) \
                and scene.storey_footprint(above) is not None:
            options += [("on_top", c) for c in _rect_columns(frame)[:40]]
        options += [("in_gap", pair) for pair in in_line_pairs(frame, rng, 0.15, 0.8)]
        options += [("in_room", r) for r in frame.on("space")[:60]
                    if frame.box(r) is not None]
        rng.shuffle(options)
        if style == "relation":
            options.sort(key=lambda o: {"on_top": 0, "in_gap": 0, "in_room": 1}[o[0]]
                         + rng.random() * 1.5)
        for construction, element in options[:MAX_TRIES]:
            extra: dict = {"construction": construction}
            stated: dict = {}
            target = frame
            skip: list = []
            try:
                if construction == "on_top":
                    target = Frame(scene, above)
                    level = scene.storey_neighbour(above, +1)
                    lo, hi = target.exact(element)
                    if level is not None and level.Elevation is not None:
                        height = (float(level.Elevation) - float(above.Elevation)) \
                            * scene.unit_scale - float(hi[2])
                    else:
                        height = float(hi[2] - lo[2])
                    height = _r(height, 2)
                    if not 2.0 <= height <= 8.0:
                        continue
                    spot = target.place("column_on_top", element, above, height)
                    references = [element]
                    extra.update(stands_on=element, placer="column_on_top",
                                 placer_args={"column": element, "height": height})
                    stated["height"] = height
                    skip = [element]
                elif construction == "in_gap":
                    a, b = element
                    lo_a, hi_a = frame.exact(a)
                    lo_b, hi_b = frame.exact(b)
                    height = stated_height(scene, storey, min(hi_a[2], hi_b[2])
                                           - max(lo_a[2], lo_b[2]))
                    if height is None:
                        continue
                    spot = frame.place("column_in_gap", a, b, storey, height=height)
                    references = [a, b]
                    extra.update(placer="column_in_gap", walls=[a, b],
                                 placer_args={"a": a, "b": b, "height": height})
                    stated["height"] = height
                    stated["section"] = [_r(v) for v in spot["extents"][:2]]
                    skip = [a, b]
                else:
                    lo, hi = frame.exact(element)
                    width = float(_pick(rng, COLUMN_SIDES))
                    depth = width if rng.random() < 0.6 else float(_pick(rng, COLUMN_SIDES))
                    height = stated_height(scene, storey, float(hi[2] - lo[2]))
                    if height is None or np.any((hi - lo)[:2] < 1.5):
                        continue
                    spot = frame.place("column_in_room", element, storey, width,
                                       depth, height=height)
                    references = [element]
                    extra.update(placer="column_in_room", room=element,
                                 placer_args={"room": element, "width": width,
                                              "depth": depth, "height": height})
                    stated.update(width=width, depth=depth, height=height)
            except Exception:
                continue
            origin, extents = list(spot["origin"]), list(spot["extents"])
            corner_of = references[0]
            if style == "box":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                extra["placer"] = None
                extra.pop("placer_args", None)
            elif style == "relative":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                corner = target.exact(corner_of)[0]
                offset = [_r(origin[i] - corner[i]) for i in range(3)]
                origin = list(target.place("corner_from", corner_of, target.storey,
                                           offset))
                extra.update(placer="corner_from", corner_of=corner_of,
                             placer_args={"reference": corner_of, "offset": offset})
                stated.update(offset=offset, extents=extents)
            why = fault(target, "column", origin, extents, skip=skip)
            if why is not None:
                ops.note_rejection(why)
                continue
            if construction == "in_room":
                bounds = [element]
            else:
                bounds = rooms_touching(target, origin, extents, 1)
            extra["bounds"] = bounds
            if construction != "on_top":
                extra.pop("stands_on", None)
            names = list(references) + bounds
            mentioned = list(bounds) + ([below] if (below := extra.get("stands_on")) is not None else [])
            if style != "box":
                mentioned = names
            namer = Namer(scene, mentioned, rng)
            extra["by_name"] = namer.by_name
            extra["stated"] = stated
            text = _column_text(style, namer, target, construction, references, extra,
                                origin, extents, stated, bounds, rng)
            return finish(scene, "column", style, task_id, target, origin, extents,
                          extra, list(dict.fromkeys(names)), text), ""
    return None, "revit_no_column_site"


def _column_text(style, namer, frame, construction, references, extra, origin,
                 extents, stated, bounds, rng) -> str:
    storey = frame.storey.GlobalId
    rooms_part = _rooms_clause(namer, bounds, rng, "the column")
    below = extra.get("stands_on")
    link = ""
    if below is not None:
        link = _pick(rng, (
            f" Connect it to {namer.one('column', below)}, which it stands on, with "
            f"an element connection.",
            f" Record an element connection between the new column and "
            f"{namer.one('column', below)} beneath it.",
        ))
    if style == "box":
        head = _pick(rng, (
            f"Add a column on storey {storey} with {_box_words(origin, extents, rng)},"
            f" {_frame_words(rng)}.",
            f"Create a rectangular column in storey {storey}: "
            f"{_box_words(origin, extents, rng)} ({_frame_words(rng)}).",
        ))
        return f"{head}{link}{rooms_part}"
    if style == "relative":
        element = extra["corner_of"]
        reference = namer.one(family_of(namer.scene, element), element)
        ox = triple(stated["offset"])
        head = _pick(rng, (
            f"On storey {storey}, add a column whose bounding box starts at the "
            f"minimum corner of {reference}'s bounding box offset by {ox} m and "
            f"measures {num(extents[0])} m in x, {num(extents[1])} m in y and "
            f"{num(extents[2])} m in z, in that storey's coordinates.",
            f"Shift the lowest bounding-box corner of {reference} by {ox} m in the "
            f"frame of storey {storey} and put a column there, {triple(extents)} m "
            f"along x, y and z.",
        ))
        return f"{head}{link}{rooms_part}"
    if construction == "on_top":
        column = namer.one("column", below)
        h = num(stated["height"], 2)
        head = _pick(rng, (
            f"On storey {storey}, stand a new column on {column}: it keeps that "
            f"column's cross-section, starts at its top face and is {h} m high.",
            f"Continue {column} upwards: add a column on storey {storey} with the "
            f"same footprint whose base is the top face of {column}, {h} m tall.",
        ))
    elif construction == "in_gap":
        walls = namer.many("wall", extra["walls"])
        a, b = stated["section"]
        h = num(stated["height"], 2)
        head = _pick(rng, (
            f"On storey {storey}, {walls} stand in line with an open stretch between "
            f"their ends; close it with a column {num(a)} m by {num(b)} m in plan and "
            f"{h} m high, sitting on the walls' base.",
            f"Close the opening between the ends of {walls} on storey {storey} with "
            f"a rectangular column: {num(a)} m along x, {num(b)} m along y, {h} m "
            f"tall from their common base.",
        ))
    else:
        room = namer.one("space", extra["room"])
        h = num(stated["height"], 2)
        w, d = num(stated["width"]), num(stated["depth"])
        head = _pick(rng, (
            f"On storey {storey}, add a column {w} m along x by {d} m along y at the "
            f"centre of the plan of {room}, standing on the room's floor and {h} m "
            f"tall.",
            f"Place a rectangular column ({w} m in x, {d} m in y, {h} m high) on "
            f"storey {storey}, centred in {room} and starting at the bottom of the "
            f"room's box.",
        ))
    return f"{head}{link}{rooms_part}"


# ------------------------------------------------------------------ rooms


def enclosures(frame: Frame, rng, limit: int = 30) -> list:
    """Four walls of the storey that close a rectangle no room fills yet."""
    walls = []
    for wall in frame.on("wall"):
        box = frame.box(wall)
        if box is None:
            continue
        run = _thin(box, longest=1.0)
        if run is not None:
            walls.append((wall, box, run))
    rng.shuffle(walls)
    along_x = [w for w in walls if w[2] == 0][:90]
    along_y = [w for w in walls if w[2] == 1][:90]
    found = []
    for i, (s, sb, _r0) in enumerate(along_x):
        for n, nb, _r1 in along_x:
            if n is s:
                continue
            gap = nb[0][1] - sb[1][1]
            if not 1.5 <= gap <= 12.0:
                continue
            ox0, ox1 = max(sb[0][0], nb[0][0]), min(sb[1][0], nb[1][0])
            if ox1 - ox0 < 1.5:
                continue
            sides = [(w, b) for w, b, _r in along_y
                     if b[0][1] <= sb[1][1] + 0.05 and b[1][1] >= nb[0][1] - 0.05
                     and b[1][0] >= ox0 - 0.3 and b[0][0] <= ox1 + 0.3]
            sides.sort(key=lambda item: float(item[1][0][0]))
            for k in range(len(sides) - 1):
                (l, lb), (r, rb) = sides[k], sides[k + 1]
                if rb[0][0] - lb[1][0] < 1.5:
                    continue
                if sb[0][0] > lb[1][0] + 0.05 or sb[1][0] < rb[0][0] - 0.05:
                    continue
                if nb[0][0] > lb[1][0] + 0.05 or nb[1][0] < rb[0][0] - 0.05:
                    continue
                found.append((s, n, l, r))
            if len(found) >= limit * 3:
                break
        if len(found) >= limit * 3:
            break
    rng.shuffle(found)
    return found[:limit]


def _room_bounders(frame: Frame, walls: Sequence, origin, extents) -> list:
    """The walls, their doors and windows facing the room, and the slab below."""
    scene = frame.scene
    lo = np.asarray(origin, dtype=float)
    hi = lo + np.asarray(extents, dtype=float)
    out = list(walls)
    for wall in walls:
        for guid in scene.hosted_by(wall):
            filling = scene.by_guid(guid)
            box = frame.box(filling) if filling is not None else None
            if box is None:
                continue
            apart = np.maximum(np.maximum(box[0] - hi, lo - box[1]), 0.0)
            if float(np.linalg.norm(apart)) <= TOUCH:
                out.append(filling)
    area = float((hi[0] - lo[0]) * (hi[1] - lo[1]))
    best = None
    for slab in scene.elements("slab"):
        box = frame.box(slab)
        if box is None or abs(float(box[1][2]) - float(lo[2])) > TOUCH:
            continue
        cover = max(0.0, min(box[1][0], hi[0]) - max(box[0][0], lo[0])) * \
            max(0.0, min(box[1][1], hi[1]) - max(box[0][1], lo[1]))
        if cover >= 0.9 * area and (best is None or cover > best[0]):
            best = (cover, slab)
    if best is not None:
        out.append(best[1])
    return out[:8]


def draw_space(scene: Scene, style: str, task_id: str, rng):
    for storey in usable_storeys(scene, rng):
        frame = Frame(scene, storey)
        for walls in enclosures(frame, rng):
            boxes = [frame.exact(w) for w in walls]
            height = stated_height(scene, storey, min(b[1][2] for b in boxes)
                                   - max(b[0][2] for b in boxes))
            if height is None:
                continue
            try:
                spot = frame.place("room_inside_walls", list(walls), storey,
                                   height=height)
            except Exception:
                continue
            origin, extents = list(spot["origin"]), list(spot["extents"])
            extra: dict = {"construction": "inside_walls", "placer": "room_inside_walls",
                           "walls": list(walls),
                           "placer_args": {"walls": list(walls), "height": height}}
            stated: dict = {"height": height}
            if style == "box":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                extra["placer"] = None
                extra.pop("placer_args", None)
            elif style == "relative":
                origin, extents = [_r(v) for v in origin], [_r(v) for v in extents]
                anchor_wall = walls[int(rng.random() * 4) % 4]
                corner = frame.exact(anchor_wall)[0]
                offset = [_r(origin[i] - corner[i]) for i in range(3)]
                origin = list(frame.place("corner_from", anchor_wall, storey, offset))
                extra.update(placer="corner_from", corner_of=anchor_wall,
                             placer_args={"reference": anchor_wall, "offset": offset})
                stated.update(offset=offset, extents=extents)
            why = fault(frame, "space", origin, extents, skip=walls)
            if why is not None:
                ops.note_rejection(why)
                continue
            if style == "box":
                bounded = _room_bounders(frame, walls, origin, extents)
            else:
                bounded = list(walls)
            extra["bounded_by"] = bounded
            namer = Namer(scene, bounded, rng)
            extra["by_name"] = namer.by_name
            extra["stated"] = stated
            text = _space_text(style, namer, frame, walls, bounded, extra, origin,
                               extents, stated, rng)
            return finish(scene, "space", style, task_id, frame, origin, extents,
                          extra, bounded, text), ""
    return None, "revit_no_room_site"


def _bounder_phrase(namer: Namer, elements: Sequence) -> str:
    groups: dict = {}
    for element in elements:
        family = family_of(namer.scene, element)
        groups.setdefault(family, []).append(element)
    parts = [namer.many(family, members) for family, members in groups.items()]
    if len(parts) == 1:
        return parts[0]
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _space_text(style, namer, frame, walls, bounded, extra, origin, extents, stated,
                rng) -> str:
    storey = frame.storey.GlobalId
    aggregate = _pick(rng, (
        f" Aggregate the room under storey {storey} rather than containing it.",
        f" The room belongs to storey {storey} through aggregation.",
        f" Attach it to storey {storey} by aggregation.",
    ))
    bound_part = _pick(rng, (
        f" Write space boundaries from the room to {_bounder_phrase(namer, bounded)}.",
        f" Record {_bounder_phrase(namer, bounded)} as the room's boundaries.",
    ))
    if style == "box":
        head = _pick(rng, (
            f"Add a room (IfcSpace) on storey {storey} with "
            f"{_box_words(origin, extents, rng)}, {_frame_words(rng)}.",
            f"Create a new space in storey {storey}: "
            f"{_box_words(origin, extents, rng)} ({_frame_words(rng)}).",
        ))
        return f"{head}{bound_part}{aggregate}"
    if style == "relation":
        enclosing = namer.many("wall", walls)
        h = num(stated["height"], 2)
        head = _pick(rng, (
            f"On storey {storey}, add a room that fills the rectangle the four "
            f"{PLURAL['wall']} {enclosing[len('the walls '):]} close off, from their "
            f"inner faces, {h} m high above their base.",
            f"Create a space {h} m tall on storey {storey} occupying exactly the area "
            f"that {enclosing} close off, measured between their inner faces.",
        ))
        return f"{head}{bound_part}{aggregate}"
    element = extra["corner_of"]
    ox = triple(stated["offset"])
    head = _pick(rng, (
        f"On storey {storey}, add a room whose bounding box starts at the minimum "
        f"corner of {namer.one('wall', element)}'s bounding box moved by {ox} m, "
        f"with extents {triple(extents)} m along x, y and z (storey coordinates).",
        f"Take the lowest corner of the box of {namer.one('wall', element)} in the "
        f"frame of storey {storey}, add {ox} m, and create a space there measuring "
        f"{num(extents[0])} by {num(extents[1])} by {num(extents[2])} m.",
    ))
    return f"{head}{bound_part}{aggregate}"


# ------------------------------------------------------------------ doors, windows


def _host_walls(frame: Frame, rng) -> list:
    lib = frame.lib
    out = []
    to_storey = np.linalg.inv(lib.frame_of(frame.storey))
    for wall in frame.on("wall"):
        box = frame.box(wall)
        if box is None or _thin(box) is None:
            continue
        rotation = (to_storey @ lib.frame_of(wall))[:3, :3]
        if not lib._aligned(rotation):
            continue
        out.append(wall)
    rng.shuffle(out)
    return out[:60]


def _spans(frame: Frame, wall) -> list:
    lib = frame.lib
    spans = []
    for guid in frame.scene.hosted_by(wall):
        filling = frame.scene.by_guid(guid)
        if filling is None:
            continue
        with lib.guid_source(None, quiet=True):
            slot = lib.filling_slot(filling)
            if slot is not None:
                spans.append((slot["along"], slot["along"] + slot["width"]))
                continue
            box = lib.box_in_frame(filling, wall)
        if box is not None:
            spans.append((float(box[0][0]), float(box[1][0])))
    return spans


def _local_of(frame: Frame, wall, origin, extents):
    lib = frame.lib
    to_wall = np.linalg.inv(lib.frame_of(wall)) @ lib.frame_of(frame.storey)
    lo = np.asarray(origin, dtype=float)
    hi = lo + np.asarray(extents, dtype=float)
    corners = np.array([[a, b, c] for a in (lo[0], hi[0]) for b in (lo[1], hi[1])
                        for c in (lo[2], hi[2])])
    local = (to_wall[:3, :3] @ corners.T).T + to_wall[:3, 3]
    return local.min(axis=0), local.max(axis=0)


def _slot_fault(frame: Frame, wall, origin, extents) -> Optional[str]:
    lib = frame.lib
    with lib.guid_source(None, quiet=True):
        box = lib.wall_box(wall)
    if box is None:
        return "revit_wall_unmeasurable"
    lo, hi = _local_of(frame, wall, origin, extents)
    if lo[0] < box["start"] + 0.05 or hi[0] > box["end"] - 0.05:
        return "revit_filling_past_wall_end"
    if lo[2] < box["base"] - 1e-6 or hi[2] > box["top"] - ops.FILLING_HEADROOM:
        return "revit_filling_taller_than_wall"
    if lo[1] > box["near"] + 0.01 or hi[1] < box["far"] - 0.01:
        return "revit_opening_not_through"
    for low, high in _spans(frame, wall):
        if lo[0] < high + ops.FILLING_CLEARANCE and hi[0] > low - ops.FILLING_CLEARANCE:
            return "revit_filling_overlaps_filling"
    return None


def _leaf_size(scene: Scene, family: str, rng) -> tuple:
    ifc_class = IFC_CLASS[family]
    own = []
    for element in scene.model.by_type(ifc_class):
        width = getattr(element, "OverallWidth", None)
        tall = getattr(element, "OverallHeight", None)
        if width and tall:
            size = (_r(float(width) * scene.unit_scale), _r(float(tall) * scene.unit_scale))
            if family == "door" and 0.6 <= size[0] <= 1.8 and 1.9 <= size[1] <= 2.6:
                own.append(size)
            if family == "window" and 0.4 <= size[0] <= 2.5 and 0.4 <= size[1] <= 2.2:
                own.append(size)
    own = sorted(set(own))
    if own and rng.random() < 0.5:
        return own[int(rng.random() * len(own)) % len(own)]
    pool = DOOR_SIZES if family == "door" else WINDOW_SIZES
    return pool[int(rng.random() * len(pool)) % len(pool)]


def _separating(frame: Frame, wall) -> Optional[list]:
    """The two rooms a wall stands between, one on each side, or None."""
    box = frame.box(wall)
    if box is None:
        return None
    run = _thin(box)
    if run is None:
        return None
    across = 1 - run
    sides: dict = {}
    for space in frame.on("space"):
        sbox = frame.box(space)
        if sbox is None:
            continue
        cover = min(sbox[1][run], box[1][run]) - max(sbox[0][run], box[0][run])
        if cover < 0.8:
            continue
        if abs(float(sbox[1][across]) - float(box[0][across])) <= TOUCH:
            sides.setdefault("low", []).append(space)
        elif abs(float(sbox[0][across]) - float(box[1][across])) <= TOUCH:
            sides.setdefault("high", []).append(space)
    if len(sides.get("low", ())) != 1 or len(sides.get("high", ())) != 1:
        return None
    return [sides["low"][0], sides["high"][0]]


def draw_filling(scene: Scene, family: str, style: str, task_id: str, rng):
    lib = library()
    ifc_class = IFC_CLASS[family]
    for storey in usable_storeys(scene, rng):
        frame = Frame(scene, storey)
        walls = _host_walls(frame, rng)
        if not walls:
            continue
        likes = [e for e in scene.model.by_type(ifc_class)
                 if scene.host_of(e) is not None]
        rng.shuffle(likes)
        attempts = []
        if style == "relation":
            mine = [e for e in likes if scene.storey_guid_of(e) == storey.GlobalId]
            if family == "door":
                for wall in walls:
                    attempts.append(("centred", wall))
                attempts += [("beside", e) for e in mine[:10]]
            else:
                attempts += [("beside", e) for e in mine[:20]]
                for wall in walls[:20]:
                    attempts.append(("centred", wall))
        else:
            attempts = [("free", wall) for wall in walls]
        for construction, element in attempts[:MAX_TRIES]:
            extra: dict = {"construction": construction}
            stated: dict = {}
            references: list = []
            bounds: list = []
            try:
                if construction == "free":
                    wall = element
                    with lib.guid_source(None, quiet=True):
                        box = lib.wall_box(wall)
                    width, height = _leaf_size(scene, family, rng)
                    sill = 0.0 if family == "door" else float(_pick(rng, WINDOW_SILLS))
                    if box is None or box["length"] < width + 1.0 or \
                            box["height"] < sill + height + ops.FILLING_HEADROOM:
                        continue
                    if not rooms_touching(frame, *_world_free(frame, wall), 1):
                        continue
                    along = rng.uniform(box["start"] + 0.3,
                                        box["end"] - 0.3 - width)
                    lo = (along, box["near"], box["base"] + sill)
                    hi = (along + width, box["far"], box["base"] + sill + height)
                    with lib.guid_source(None, quiet=True):
                        slo, shi = lib._wall_local_to_storey(wall, storey, lo, hi)
                    origin = [_r(v) for v in slo]
                    extents = [_r(v) for v in shi - slo]
                    extra["placer"] = None
                    if style == "relative":
                        corner = frame.exact(wall)[0]
                        offset = [_r(origin[i] - corner[i]) for i in range(3)]
                        origin = list(frame.place("corner_from", wall, storey, offset))
                        extra.update(placer="corner_from", corner_of=wall,
                                     placer_args={"reference": wall, "offset": offset})
                        stated.update(offset=offset, extents=extents)
                    host = wall
                    references = [wall]
                elif construction == "centred":
                    wall = element
                    rooms = _separating(frame, wall) if family == "door" else None
                    if family == "door" and rooms is None:
                        continue
                    if rooms is not None:
                        try:
                            between = frame.place("find_wall_between_rooms",
                                                  rooms[0], rooms[1])
                        except Exception:
                            continue
                        if between.GlobalId != wall.GlobalId:
                            continue
                    pool = [e for e in likes if scene.host_of(e) != wall.GlobalId][:6]
                    spot = None
                    like = None
                    for candidate in pool:
                        try:
                            spot = frame.place("opening_centred", wall, candidate,
                                               storey)
                        except Exception:
                            continue
                        if _slot_fault(frame, wall, spot["origin"], spot["extents"]) is None:
                            like = candidate
                            break
                    if like is None:
                        continue
                    origin, extents = list(spot["origin"]), list(spot["extents"])
                    host = wall
                    references = [wall, like] if family == "window" else [like]
                    extra.update(placer="opening_centred", like=like, wall=wall,
                                 placer_args={"wall": wall, "like": like})
                    if rooms is not None:
                        extra["separates"] = rooms
                        extra["placer_args"]["rooms"] = rooms
                        bounds = rooms
                else:
                    like = element
                    with lib.guid_source(None, quiet=True):
                        slot = lib.filling_slot(like)
                    if slot is None:
                        continue
                    host = slot["host"]
                    if host.GlobalId not in {w.GlobalId for w in walls}:
                        continue
                    lo_w, hi_w = frame.exact(host)
                    run = 0 if (hi_w - lo_w)[0] >= (hi_w - lo_w)[1] else 1
                    sign = 1 if rng.random() < 0.5 else -1
                    distance = _r(slot["width"] + rng.uniform(0.3, 2.0), 2)
                    word = ("+" if sign > 0 else "-") + "xy"[run]
                    spot = frame.place("opening_beside", like, storey, distance, word)
                    origin, extents = list(spot["origin"]), list(spot["extents"])
                    references = [like]
                    extra.update(placer="opening_beside", like=like,
                                 placer_args={"like": like, "distance": distance,
                                              "direction": word})
                    stated.update(distance=distance, direction=word)
            except Exception:
                continue
            why = _slot_fault(frame, host, origin, extents)
            if why is None:
                why = fault(frame, family, origin, extents, skip=[host])
            if why is not None:
                ops.note_rejection(why)
                continue
            if not bounds:
                bounds = rooms_touching(frame, origin, extents, 2)
            extra["bounds"] = bounds
            if construction == "beside":
                mentioned = references + bounds
            elif construction == "centred" and family == "door":
                mentioned = references + list(extra.get("separates") or ()) + bounds
            else:
                mentioned = [host] + references + bounds
            namer = Namer(scene, mentioned, rng)
            extra["by_name"] = namer.by_name
            extra["stated"] = stated
            text = _filling_text(family, style, namer, frame, host, construction,
                                 extra, origin, extents, stated, bounds, rng)
            names = list(dict.fromkeys([host] + references + bounds))
            return finish(scene, family, style, task_id, frame, origin, extents,
                          extra, names, text, host=host), ""
    return None, f"revit_no_{family}_site"


def _world_free(frame: Frame, wall):
    box = frame.box(wall)
    return list(box[0]), list(box[1] - box[0])


def _filling_text(family, style, namer, frame, host, construction, extra, origin,
                  extents, stated, bounds, rng) -> str:
    storey = frame.storey.GlobalId
    noun = NOUN[family]
    wall = namer.one("wall", host)
    rooms = namer.many("space", bounds) if bounds else ""
    tail = _pick(rng, (
        f" The {noun} gets its own opening element that voids the wall and that the "
        f"{noun} fills; keep the {noun} on storey {storey}.",
        f" Model the opening as a separate element cutting the wall, put the {noun} "
        f"into it, and contain the {noun} in storey {storey}.",
        f" Cut the wall with a new opening, let the {noun} fill that opening, and "
        f"assign the {noun} to storey {storey}.",
    ))
    if bounds:
        tail += _pick(rng, (
            f" Also record the {noun} as a space boundary of {rooms}.",
            f" Write space boundaries between the {noun} and {rooms}.",
        ))
    if style == "box":
        head = _pick(rng, (
            f"Insert a {noun} into {wall}; its opening occupies a box whose lowest "
            f"corner is {triple(origin)} and whose sizes are {num(extents[0])} m along "
            f"x, {num(extents[1])} m along y and {num(extents[2])} m along z, "
            f"{_frame_words(rng)}.",
            f"Add a {noun} to {wall}, with an opening whose box starts at "
            f"{triple(origin)} and spans {triple(extents)} m in x, y and z "
            f"({_frame_words(rng)}).",
        ))
        return head + tail
    if style == "relative":
        ox = triple(stated["offset"])
        head = _pick(rng, (
            f"Add a {noun} to {wall}. Its opening's bounding box begins at the "
            f"minimum point of that wall's bounding box plus {ox} m and measures "
            f"{triple(extents)} m along x, y and z, in the coordinates of storey "
            f"{storey}.",
            f"Take the lowest corner of {wall}'s bounding box, add {ox} m in storey "
            f"coordinates, and cut a {noun} opening there of {num(extents[0])} by "
            f"{num(extents[1])} by {num(extents[2])} m (x, y, z).",
        ))
        return head + tail
    like = extra.get("like")
    if construction == "centred":
        like_phrase = namer.one(family, like)
        if family == "door":
            between = namer.many("space", extra["separates"])
            head = _pick(rng, (
                f"Add a door to the dividing wall between {between}; put it at the "
                f"middle of that wall's length and give its opening the width, height "
                f"and sill of {like_phrase}.",
                f"Between {between} there is one dividing wall; put a door in the "
                f"middle of its length whose opening copies the width, height and "
                f"sill of {like_phrase}.",
            ))
        else:
            head = _pick(rng, (
                f"Add a window to {wall} at the middle of its length; its opening "
                f"copies the size and the sill height of {like_phrase}.",
                f"Centre a new window on the length of {wall}; its opening has the "
                f"width, height and sill of {like_phrase}.",
            ))
        return head + tail
    like_phrase = namer.one(family, like)
    d, word = num(stated["distance"], 2), stated["direction"]
    head = _pick(rng, (
        f"Add a {noun} to the wall that carries {like_phrase}; it has the same size "
        f"and height, and its opening is shifted {d} m in {word} from the opening "
        f"of {like_phrase}.",
        f"In the same wall as {like_phrase}, place another {noun} whose opening "
        f"repeats that one moved {d} m along {word}.",
    ))
    return head + tail


# ------------------------------------------------------------------ dispatch


DRAWERS = {"wall": draw_wall, "slab": draw_slab, "column": draw_column,
           "space": draw_space}


def draw(scene: Scene, family: str, style: str, task_id: str, rng):
    """One drawn task of the family, or ``(None, reason)``."""
    if family in ("door", "window"):
        return draw_filling(scene, family, style, task_id, rng)
    return DRAWERS[family](scene, style, task_id, rng)
