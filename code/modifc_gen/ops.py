"""The edit-operation library.

Each planner draws one parameterised edit for one element family and returns an
``EditPlan``: the calls the gold script will make, the entities the edit
touches, and the parameters the instruction is rendered from.  A planner returns
``None`` when the model cannot host that edit, and the caller counts the refusal
rather than working around it.

Feasibility is decided here, before anything is written.  An edit has to keep
dimensions positive, keep the element inside the storey it belongs to, and
change something the score can see; an edit that would move or resize a shape
several elements share is refused, because it would silently edit them too.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

import ifcopenshell.guid
import ifcopenshell.util.attribute

from . import conditions, families, goldlib, settings
from .scene import AXIS_WORDS, FAMILIES, Extent, Scene

# Distances, in metres, a translate edit may use, before the storey-size cap.
TRANSLATE_DISTANCES = (0.5, 1.0, 1.5, 2.0, 3.0, 5.0)

# Multipliers a resize edit may apply to an existing dimension.
RESIZE_FACTORS = (0.75, 0.8, 1.2, 1.25, 1.5)

# Sizes, in metres, a created element is given.
CREATE_SIZES = {
    "wall": (4.0, 0.20, 3.00),
    "slab": (4.0, 4.0, 0.20),
    "column": (0.40, 0.40, 3.00),
    "space": (4.0, 3.0, 2.70),
}

# Sizes, in metres, of a created door or window, and how high its sill sits.
CREATE_FILLING = {"door": (0.90, 2.10, 0.0), "window": (1.20, 1.40, 0.90)}

# IFC classes the create family instantiates.
BOX_CLASS = {"wall": "IfcWall", "slab": "IfcSlab", "column": "IfcColumn",
             "space": "IfcSpace"}
FILLING_CLASS = {"door": "IfcDoor", "window": "IfcWindow"}

# Names a rename edit may give an element, completed with a running number.
RENAME_STEMS = {
    "wall": "Partition", "slab": "Deck", "space": "Room",
    "door": "Doorset", "window": "Glazing unit", "column": "Post",
}

# Predefined types that need a companion ObjectType or say nothing, and so are
# never chosen as a retype target.
UNUSABLE_TYPES = ("USERDEFINED", "NOTDEFINED")

# Attributes the score ignores; an edit that changed only these would be
# invisible to the score and is refused.
INVISIBLE_ATTRIBUTES = ("Tag", "Description", "LongName")

# How many times a placement is redrawn before the draw is refused.
PLACEMENT_ATTEMPTS = 16

# Share of a body's own volume that may sit inside any one neighbour before the
# placement counts as a collision.  The share a lattice measures moves a little
# with the lattice, so the bar sits below the share the physical audit calls a
# collision rather than on it.
COLLISION_SHARE = 0.02

# Points per axis in the lattices that sample a body for the collision test.
# Two lattices are read and the larger share decides, because a body can slip
# between the points of one of them.
COLLISION_GRIDS = (10, 14)
COLLISION_GRID = COLLISION_GRIDS[-1]

# Metres of clear wall a new door or window keeps from every filling the wall
# already carries, measured along the wall.
FILLING_CLEARANCE = 0.10

# Metres of wall that must stand above the head of a new door or window.
FILLING_HEADROOM = 0.10

# How often each placement rule refused a draw, for the run's funnel.
REJECTIONS: dict[str, int] = {}


def note_rejection(rule: str) -> None:
    REJECTIONS[rule] = REJECTIONS.get(rule, 0) + 1


def rejection_counts() -> dict[str, int]:
    return dict(sorted(REJECTIONS.items()))


def reset_rejections() -> None:
    REJECTIONS.clear()


def occupied_share(scene: Scene, matrix: np.ndarray, lo, hi, storey_guid: str,
                   skip: Sequence[str] = ()) -> float:
    """Largest share of a box any one neighbour of the storey already holds."""
    return max(scene.occupied_share(sample_box(matrix, lo, hi, per_axis),
                                    storey_guid, skip)
               for per_axis in COLLISION_GRIDS)


def sample_box(matrix: np.ndarray, lo, hi, per_axis: int = COLLISION_GRID
               ) -> np.ndarray:
    """World points on a regular lattice inside a box given in a local frame."""
    axes = []
    for i in range(3):
        edges = (np.arange(per_axis) + 0.5) / per_axis
        axes.append(float(lo[i]) + edges * float(hi[i] - lo[i]))
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return (matrix[:3, :3] @ grid.T).T + matrix[:3, 3]


@dataclass(frozen=True)
class Call:
    """One call the gold script makes, with its arguments already literal."""

    func: str
    args: tuple
    comment: str = ""


@dataclass
class EditPlan:
    """A parameterised edit, ready to be written out and executed."""

    kind: str
    operation: str
    family: str
    calls: list[Call]
    target_guids: tuple[str, ...] = ()
    touched_guids: tuple[str, ...] = ()
    created_guids: tuple[str, ...] = ()
    removed_guids: tuple[str, ...] = ()
    # Relationship entities the edit creates.  Kept apart from the created
    # products because they carry no geometry, and every check that reads a
    # created entity as a body would have to special-case them otherwise.
    relation_guids: tuple[str, ...] = ()
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def elements_touched(self) -> int:
        return len(set(self.touched_guids) | set(self.created_guids)
                   | set(self.removed_guids))


def mint_guid(task_id: str, role: str) -> str:
    """A stable IFC identifier for an entity a task creates.

    Derived from the task identifier, so re-running the generator or the gold
    script yields the same identifier and the two models can be compared entity
    for entity.
    """
    digest = hashlib.sha256(f"{task_id}|{role}".encode("utf-8")).hexdigest()
    return ifcopenshell.guid.compress(digest[:32])


def free_guid(scene: Scene, task_id: str, role: str) -> str:
    """A minted identifier the source model does not already carry."""
    for attempt in range(8):
        guid = mint_guid(task_id, role if attempt == 0 else f"{role}#{attempt}")
        if scene.by_guid(guid) is None:
            return guid
    raise RuntimeError("could not mint a free identifier")


def predefined_types(product) -> tuple[str, ...]:
    """Values the product's ``PredefinedType`` may legally take."""
    try:
        declaration = product.wrapped_data.declaration().as_entity()
    except Exception:
        return ()
    for attribute in declaration.all_attributes():
        if attribute.name() != "PredefinedType":
            continue
        try:
            items = ifcopenshell.util.attribute.get_enum_items(attribute)
        except Exception:
            return ()
        return tuple(v for v in items if v not in UNUSABLE_TYPES)
    return ()


def _round(value: float, places: int = 2) -> float:
    return float(round(float(value), places))


def _storey_height(scene: Scene, storey) -> float:
    """Distance to the storey above, in metres, or a plain default."""
    elevations = [float(s.Elevation) * scene.unit_scale for s in scene.storeys
                  if s.Elevation is not None]
    here = storey.Elevation
    if here is None or len(elevations) < 2:
        return 3.0
    here = float(here) * scene.unit_scale
    above = [e for e in elevations if e > here + 0.5]
    if not above:
        return 3.0
    return float(min(max(min(above) - here, 2.4), 5.0))


def magnitude_bucket(scene: Scene, metres: float) -> str:
    """How large a length is against the size of the model it is applied in."""
    diagonal = scene.scene_diagonal()
    if diagonal <= 0.0:
        return "unknown"
    ratio = metres / diagonal
    if ratio < 0.01:
        return "small"
    if ratio < 0.05:
        return "medium"
    return "large"


# ------------------------------------------------------------ update family


def axis_extent(scene: Scene, product, axis: int) -> Optional[float]:
    """How long an element is along one world axis, from the scorer's own mesh.

    The scorer pairs entities by the overlap of their oriented bounding boxes,
    so the element's own size along the axis it moves is what decides whether a
    move displaces it past itself.  The mesher is the scorer's, so the number
    agrees with what the score will read, and the mesh is cached per scene.
    """
    mesh = scene.mesh(product)
    if mesh is None:
        return None
    return float(mesh.verts[:, axis].max() - mesh.verts[:, axis].min())


def placement_chain(product) -> list[int]:
    """Identifiers of the placements a product's own placement hangs from."""
    out: list[int] = []
    placement = getattr(product, "ObjectPlacement", None)
    depth = 0
    while placement is not None and depth < 16:
        out.append(placement.id())
        placement = getattr(placement, "PlacementRelTo", None)
        depth += 1
    return out


def moves_with(child, parent) -> bool:
    """True when moving ``parent`` already moves ``child``.

    Two products that share one placement move together, so the child's own
    placement counts as well as the ones it hangs from.
    """
    parent_placement = getattr(parent, "ObjectPlacement", None)
    if parent_placement is None:
        return False
    if getattr(child, "GlobalId", None) == getattr(parent, "GlobalId", None):
        return True
    return parent_placement.id() in placement_chain(child)


def own_opening(product):
    """The opening a door or window fills, if it fills one."""
    for fills in getattr(product, "FillsVoids", ()) or ():
        if fills.RelatingOpeningElement is not None:
            return fills.RelatingOpeningElement
    return None


def stranded_dependants(scene: Scene, product) -> list:
    """Openings and fillings a move of the product would leave behind."""
    out = []
    for relation in getattr(product, "HasOpenings", ()) or ():
        opening = relation.RelatedOpeningElement
        if opening is None:
            continue
        if not moves_with(opening, product):
            out.append(opening)
        for fill in getattr(opening, "HasFillings", ()) or ():
            filling = fill.RelatedBuildingElement
            if filling is not None and not moves_with(filling, product):
                out.append(filling)
    return out


def world_corners(matrix: np.ndarray, box: Extent) -> np.ndarray:
    """The eight corners of a box, given in a local frame, in world axes."""
    corners = np.array([[x, y, z]
                        for x in (box.lo[0], box.hi[0])
                        for y in (box.lo[1], box.hi[1])
                        for z in (box.lo[2], box.hi[2])], dtype=float)
    return (matrix[:3, :3] @ corners.T).T + matrix[:3, 3]


def destination_fault(scene: Scene, product, offset: np.ndarray, storey,
                      skip: Sequence[str] = ()) -> Optional[str]:
    """Why a body may not be moved to where the offset would put it."""
    matrix = scene.matrix(product)
    box = scene.box_in_frame(product, matrix)
    if matrix is None or box is None:
        return "no_geometry"
    moved = np.array(matrix, dtype=float)
    moved[:3, 3] = moved[:3, 3] + np.asarray(offset, dtype=float)
    # A move stays inside the ground the storey's own fabric covers.
    footprint = scene.storey_footprint(storey)
    if footprint is not None:
        corners = world_corners(moved, box)
        lo = corners.min(axis=0)
        hi = corners.max(axis=0)
        if bool(np.any(lo[:2] < footprint.lo[:2])
                or np.any(hi[:2] > footprint.hi[:2])):
            return "moved_outside_storey"
    # A move does not put the body where another element already stands.  The
    # storeys read are the ones a create reads, not the moved element's alone.
    if occupied_over_storeys(scene, moved, box.lo, box.hi,
                             (storey.GlobalId,)
                             + related_storey_guids(scene, product),
                             skip) > COLLISION_SHARE:
        return "move_created_collision"
    return None


def related_storey_guids(scene: Scene, product) -> tuple[str, ...]:
    """The storeys whose fabric a body could stand in, not only its own.

    A wall and the door it hosts are not always filed on the same storey, so a
    collision test that reads one of them reads only part of the matter the
    body would occupy.  The create-a-door-where-a-window-stood path already
    reads the storey of the element and the storey of its host; this names the
    same set for a move and for a reflection, so all three ask the same
    question.  An element the model files nowhere is a neighbour of every
    storey and is already read whichever storey is asked for.
    """
    guids = [scene.storey_guid_of(product)]
    host = scene.host_of(product)
    if host:
        hosting = scene.by_guid(host)
        if hosting is not None:
            guids.append(scene.storey_guid_of(hosting))
    for guid in scene.hosted_by(product):
        filling = scene.by_guid(guid)
        if filling is not None:
            guids.append(scene.storey_guid_of(filling))
    return tuple(dict.fromkeys(g for g in guids if g))


def resize_filling_fault(scene: Scene, product, axis: int, new_lo: float,
                         new_hi: float) -> Optional[str]:
    """Why an element carrying a door or a window may not be resized.

    A resize rewrites the body and leaves every filling where it was, so a wall
    that loses length ends with a door hanging past its end and one that loses
    height ends with a door standing above its top.  The new span of the body
    along the axis the edit changes is compared with each filling's own box,
    both read in the element's own frame, and a filling that would fall outside
    refuses the draw.
    """
    hosted = scene.hosted_by(product)
    if not hosted:
        return None
    frame = scene.matrix(product)
    if frame is None:
        return None
    for guid in hosted:
        filling = scene.by_guid(guid)
        if filling is None:
            continue
        box = scene.box_in_frame(filling, frame)
        if box is None:
            return "resize_filling_unreadable"
        if float(box.lo[axis]) < new_lo - 1e-6 \
                or float(box.hi[axis]) > new_hi + 1e-6:
            return "filling_outside_resized_body"
    return None


def resized_span(scene: Scene, product, axis: int, new: float,
                 centred: bool) -> Optional[tuple[float, float]]:
    """Where the body's edges land on one axis after the size is set to ``new``.

    A swept depth grows from the base of the sweep, so the low edge stays put.
    A rectangular profile is centred on its own position, so both edges move.
    """
    frame = scene.matrix(product)
    if frame is None:
        return None
    box = scene.box_in_frame(product, frame)
    if box is None:
        return None
    if centred:
        middle = 0.5 * (float(box.lo[axis]) + float(box.hi[axis]))
        return (middle - new / 2.0, middle + new / 2.0)
    return (float(box.lo[axis]), float(box.lo[axis]) + new)


def wall_run_axis(scene: Scene, wall) -> Optional[tuple[int, float]]:
    """The world axis a wall runs along, and which way its own x axis points."""
    matrix = scene.matrix(wall)
    if matrix is None:
        return None
    direction = np.array(matrix[:3, 0], dtype=float)
    norm = float(np.linalg.norm(direction))
    if norm <= 0.0:
        return None
    direction = direction / norm
    for axis in (0, 1):
        if abs(float(direction[axis])) > 0.999:
            return axis, float(np.sign(direction[axis]))
    return None


def filling_slide_fault(scene: Scene, filling, host, shift: float,
                        clearance: float = FILLING_CLEARANCE) -> Optional[str]:
    """Why a door or window may not slide ``shift`` metres along its wall."""
    frame = scene.matrix(host)
    wall_box = scene.box_in_frame(host, frame)
    own = scene.box_in_frame(filling, frame)
    if frame is None or wall_box is None or own is None:
        return "no_geometry"
    low = float(own.lo[0]) + shift
    high = float(own.hi[0]) + shift
    # A door or window stays within the length of the wall that hosts it.
    if low < float(wall_box.lo[0]) or high > float(wall_box.hi[0]):
        return "filling_outside_host"
    # It also keeps clear of every other filling the same wall carries.
    for guid in scene.hosted_by(host):
        if guid == filling.GlobalId:
            continue
        other = scene.by_guid(guid)
        if other is None:
            continue
        box = scene.box_in_frame(other, frame)
        if box is None:
            continue
        if low < float(box.hi[0]) + clearance and \
                high > float(box.lo[0]) - clearance:
            return "filling_overlaps_filling"
    return None


def plan_translate(scene: Scene, product, rng) -> Optional[EditPlan]:
    storey = scene.storey_of(product)
    point = scene.point(product)
    if storey is None or point is None:
        return None
    extent = scene.storey_extent(storey)
    if extent is None:
        return None
    family = scene.family_of(product)
    guid = product.GlobalId
    carried = []
    host = None
    run = None
    movers = [product]
    if family in ("door", "window"):
        # A door or window is moved only together with the opening it fills, so
        # the hole in the wall goes where the leaf goes.  Which of the two is
        # written depends on how the model hangs them: a leaf placed relative to
        # its opening follows the opening, and moving both would move the leaf
        # twice.
        opening = own_opening(product)
        host_guid = scene.host_of(product)
        host = scene.by_guid(host_guid) if host_guid else None
        if opening is None or host is None:
            note_rejection("translate_filling_without_opening")
            return None
        if moves_with(product, opening):
            movers = [opening]
        elif not moves_with(opening, product):
            carried.append(opening)
        run = wall_run_axis(scene, host)
        if run is None:
            note_rejection("translate_host_wall_not_axis_aligned")
            return None
    elif stranded_dependants(scene, product):
        # Moving a host alone would strand the openings and fillings it carries,
        # which is the compositional tier's edit rather than this one.
        note_rejection("translate_leaves_dependant")
        return None

    skip = [guid] + [o.GlobalId for o in carried] \
        + [m.GlobalId for m in movers]
    if host is not None:
        skip.append(host.GlobalId)

    for _attempt in range(PLACEMENT_ATTEMPTS):
        axis = rng.choice([0, 1])
        sign = rng.choice([1, -1])
        cap = max(0.5, 0.15 * float(extent.size[axis]))
        if settings.SETTINGS.translate_relative:
            # Draw the distance from the element's own extent along the axis it
            # moves, so the moved element no longer overlaps where it was.  The
            # storey guard below still applies, and a target for which no such
            # move fits inside the storey is refused rather than moved a token
            # amount.
            own = axis_extent(scene, product, axis)
            if own is None or own <= 0:
                return None
            low, high = settings.SETTINGS.translate_extent_range
            room = max(0.5, 0.45 * float(extent.size[axis]))
            if own * low > room:
                note_rejection("translate_no_room_on_axis")
                continue
            top = min(own * high, room)
            distance = round(rng.uniform(own * low, top), 2)
            if distance <= 0:
                note_rejection("translate_no_room_on_axis")
                continue
        else:
            choices = [d for d in TRANSLATE_DISTANCES if d <= cap]
            if not choices:
                note_rejection("translate_no_room_on_axis")
                continue
            distance = float(rng.choice(choices))
        offset = np.zeros(3)
        offset[axis] = sign * distance
        if run is not None:
            wall_axis, direction = run
            if axis != wall_axis:
                note_rejection("translate_across_host_wall")
                continue
            fault = filling_slide_fault(scene, product, host,
                                        sign * distance * direction)
            if fault is not None:
                note_rejection(fault)
                continue
        margin = np.maximum(0.1 * extent.size, 1.0)
        if not Extent(extent.lo - margin,
                      extent.hi + margin).contains(point + offset):
            note_rejection("translate_origin_outside_storey")
            continue
        fault = destination_fault(scene, product, offset, storey, skip)
        if fault is not None:
            note_rejection(fault)
            continue
        word, axis_word = AXIS_WORDS[(axis, sign)]
        # A move is quoted either by the compass word the earlier waves used or
        # by the signed world axis, which is how a benchmark prompt states it.
        chosen = families.choose("spec.displacement", rng)
        form = ("axis" if chosen is not None
                and chosen.tag == "spec.axis_displacement" else "compass")
        calls = []
        for mover in movers:
            comment = ("move the element along the world axes, in metres"
                       if mover.GlobalId == guid
                       else "move the opening the element hangs from, which "
                            "carries the element with it")
            calls.append(Call("translate",
                              (mover.GlobalId, _round(offset[0]),
                               _round(offset[1]), _round(offset[2])), comment))
        for opening in carried:
            calls.append(Call("translate",
                              (opening.GlobalId, _round(offset[0]),
                               _round(offset[1]), _round(offset[2])),
                              "carry the opening the element fills with it"))
        return EditPlan(
            kind="translate", operation="update", family=family,
            calls=calls, target_guids=(guid,), touched_guids=(guid,),
            params={"distance": _round(distance), "direction": word,
                    "axis_word": axis_word, "axis": axis, "sign": sign,
                    "direction_form": form,
                    "families": (["spec.axis_displacement"] if form == "axis"
                                 else ["spec.compass_displacement"]),
                    "n_openings_carried": len(carried),
                    "magnitude": magnitude_bucket(scene, distance)})
    return None


def plan_resize_extrusion(scene: Scene, product, rng) -> Optional[EditPlan]:
    """Change the depth of an element's single extruded body.

    A body that is not one swept profile has no depth to set, so the edit is
    undefinable on it rather than merely hard.  Which bodies those are is stated
    once in :mod:`modifc_gen.conditions`, and the refusal is counted under the
    kind of body it was refused for, so a run reports how much of the corpus each
    edit cannot reach.
    """
    solid = goldlib.sole_extrusion(scene.model, product)
    if solid is None:
        if conditions.undefinable_reason(product, "resize_extrusion"):
            note_rejection(
                f"resize_undefinable_on_{conditions.representation_kind(product)}")
        return None
    direction = scene.extrusion_axis(product)
    if direction is None or abs(float(direction[2])) < 0.99:
        return None
    old = float(solid.Depth) * scene.unit_scale
    if not 0.05 <= old <= 30.0:
        return None
    family = scene.family_of(product)
    word = "thickness" if family == "slab" else "height"
    new = _round(old * float(rng.choice(RESIZE_FACTORS)))
    if abs(new - old) < 0.02 or not 0.05 <= new <= 30.0:
        return None
    # The sweep runs up the element's own z axis, so the base stays where it is
    # and only the head moves; a filling the new head would stand above refuses
    # the draw.
    span = resized_span(scene, product, 2, new, centred=False)
    if span is not None:
        fault = resize_filling_fault(scene, product, 2, span[0], span[1])
        if fault is not None:
            note_rejection(fault)
            return None
    guid = product.GlobalId
    return EditPlan(
        kind="resize_extrusion", operation="update", family=family,
        calls=[Call("set_extrusion_depth", (guid, new),
                    f"set the {word} of the extruded body, in metres")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"dimension": word, "old": _round(old), "new": new,
                "magnitude": magnitude_bucket(scene, abs(new - old))})


def plan_resize_profile(scene: Scene, product, rng) -> Optional[EditPlan]:
    """Change one side of an element's rectangular extruded profile.

    Undefinable on a body that carries no profile, for the reason the depth
    resize above states, and counted the same way.
    """
    solid = goldlib.sole_extrusion(scene.model, product)
    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
        if solid is None and conditions.undefinable_reason(product,
                                                           "resize_profile"):
            note_rejection(
                f"resize_undefinable_on_{conditions.representation_kind(product)}")
        return None
    dimension = str(rng.choice(["XDim", "YDim"]))
    old = float(getattr(solid.SweptArea, dimension)) * scene.unit_scale
    if not 0.05 <= old <= 30.0:
        return None
    new = _round(old * float(rng.choice(RESIZE_FACTORS)))
    if abs(new - old) < 0.02 or not 0.05 <= new <= 30.0:
        return None
    # A rectangular profile is centred on its own position, so shortening a
    # wall pulls both ends in and a door near either end can be left outside.
    axis = 0 if dimension == "XDim" else 1
    span = resized_span(scene, product, axis, new, centred=True)
    if span is not None:
        fault = resize_filling_fault(scene, product, axis, span[0], span[1])
        if fault is not None:
            note_rejection(fault)
            return None
    family = scene.family_of(product)
    word = "length" if dimension == "XDim" else "width"
    if family == "wall" and dimension == "YDim":
        word = "thickness"
    guid = product.GlobalId
    return EditPlan(
        kind="resize_profile", operation="update", family=family,
        calls=[Call("set_profile_dimension", (guid, dimension, new),
                    f"set the {word} of the element's profile, in metres")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"dimension": word, "old": _round(old), "new": new,
                "magnitude": magnitude_bucket(scene, abs(new - old))})


def plan_resize_overall(scene: Scene, product, rng) -> Optional[EditPlan]:
    """Change a door's or a window's recorded overall height or width."""
    family = scene.family_of(product)
    if family not in ("door", "window"):
        return None
    attribute = str(rng.choice(["OverallHeight", "OverallWidth"]))
    current = getattr(product, attribute, None)
    if current is None:
        return None
    old = float(current) * scene.unit_scale
    if not 0.2 <= old <= 6.0:
        return None
    new = _round(old * float(rng.choice(RESIZE_FACTORS)))
    if abs(new - old) < 0.05 or not 0.2 <= new <= 6.0:
        return None
    word = "overall height" if attribute == "OverallHeight" else "overall width"
    guid = product.GlobalId
    return EditPlan(
        kind="resize_overall", operation="update", family=family,
        calls=[Call("set_length_attribute", (guid, attribute, new),
                    f"set the {word}, in metres")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"dimension": word, "old": _round(old), "new": new,
                "magnitude": magnitude_bucket(scene, abs(new - old))})


def plan_rename(scene: Scene, product, rng) -> Optional[EditPlan]:
    family = scene.family_of(product)
    stem = RENAME_STEMS.get(family)
    if stem is None:
        return None
    used = {(e.Name or "").strip() for e in scene.elements(family)}
    for _ in range(24):
        name = f"{stem} {rng.randint(100, 998)}"
        if name not in used:
            break
    else:
        return None
    if (product.Name or "").strip() == name:
        return None
    guid = product.GlobalId
    return EditPlan(
        kind="rename", operation="update", family=family,
        calls=[Call("set_attribute", (guid, "Name", name), "rename the element")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"old": (product.Name or "").strip() or None, "new": name,
                "magnitude": "small"})


def plan_retype(scene: Scene, product, rng) -> Optional[EditPlan]:
    values = predefined_types(product)
    if not values:
        return None
    current = getattr(product, "PredefinedType", None)
    choices = [v for v in values if v != current]
    if not choices:
        return None
    value = str(rng.choice(choices))
    guid = product.GlobalId
    return EditPlan(
        kind="retype", operation="update", family=scene.family_of(product),
        calls=[Call("set_attribute", (guid, "PredefinedType", value),
                    "set the element's predefined type")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"old": current, "new": value, "magnitude": "small"})


UPDATE_PLANNERS = {
    "wall": (plan_translate, plan_resize_extrusion, plan_resize_profile,
             plan_rename, plan_retype),
    "slab": (plan_translate, plan_resize_extrusion, plan_resize_profile,
             plan_rename, plan_retype),
    "space": (plan_translate, plan_resize_extrusion, plan_rename, plan_retype),
    "column": (plan_translate, plan_resize_extrusion, plan_resize_profile,
               plan_rename, plan_retype),
    "door": (plan_translate, plan_resize_overall, plan_rename, plan_retype),
    "window": (plan_translate, plan_resize_overall, plan_rename, plan_retype),
}


ATTRIBUTE_PLANNER_NAMES = {"plan_rename", "plan_retype", "plan_resize_overall"}


def _weighted_order(planners, rng) -> list:
    """The family's planners, in the order this draw will try them.

    An attribute-only planner carries the weight the wave's settings give it, so
    halving that weight halves how often such an edit is the one drawn, without
    removing the kind from the library.
    """
    weight = float(settings.SETTINGS.attribute_weight)
    weighted = []
    for planner in planners:
        if planner.__name__ not in ATTRIBUTE_PLANNER_NAMES:
            key = rng.random()
        elif weight <= 0:
            key = -1.0
        else:
            # Efraimidis and Spirakis: a weighted permutation is obtained by
            # sorting on a uniform draw raised to the power one over the
            # weight, largest first.  A weight of one half therefore halves how
            # often such a planner comes out in front of the others.
            key = rng.random() ** (1.0 / weight)
        weighted.append((key, planner.__name__, planner))
    weighted.sort(key=lambda triple: (-triple[0], triple[1]))
    return [planner for _key, _name, planner in weighted]


def plan_update(scene: Scene, product, rng, task_id: str = ""
                ) -> Optional[EditPlan]:
    """One update edit for a product, trying the family's planners in turn.

    A share of the draws asks for one of the operations 0.6.0 adds first, in the
    order the registry's weights put them in.  A product none of them applies to
    falls back to the earlier planners rather than being refused, so no cell of
    the grid loses yield to an operation the model cannot carry.
    """
    if not scene.has_body(product):
        return None
    family = scene.family_of(product)
    if families.draw("op.update.new", rng):
        plan = _new_operation(scene, product, rng, task_id, family,
                              "op.update.new", NEW_UPDATE_PLANNERS)
        if plan is not None:
            attach_constraint(plan, rng)
            return plan
    planners = _weighted_order(UPDATE_PLANNERS.get(family, ()), rng)
    for planner in planners:
        try:
            plan = planner(scene, product, rng)
        except Exception:
            plan = None
        if plan is not None:
            attach_constraint(plan, rng)
            return plan
    return None


def _new_operation(scene: Scene, product, rng, task_id: str, family: str,
                   group: str, table: dict) -> Optional[EditPlan]:
    """The first of a group's operations this product can carry."""
    for entry in families.members(group, rng):
        planner, allowed = table.get(entry.tag, (None, ()))
        if planner is None or family not in allowed:
            continue
        try:
            plan = planner(scene, product, rng, task_id)
        except Exception:
            plan = None
        if plan is not None:
            return plan
    return None


# ------------------------------------------------------------ delete family


# ---------------------------------------------- a delete that names relations
# A work order written by a person often lists what goes with the element:
# "delete the column with ID A; also delete its connection to column B and its
# assignment to storey C".  The element is the only thing the edit removes;
# the relationships named are relationships that element takes part in, and
# they go because it goes.  The gold is therefore the same under this wording
# as under the plain one, which is what makes this a wording family.


#: How many relationships one sentence names, at most, so it stays readable.
MAX_NAMED_RELATIONS = 3


def _named_relation_clauses(scene: Scene, product) -> list[dict]:
    """The relationships the element takes part in, written out in words."""
    clauses: list[dict] = []
    for guid in scene.connected(product):
        other = scene.by_guid(guid)
        family = scene.family_of(other) if other is not None else None
        name = scene.unique_name(other) if other is not None else None
        if not name or family in (None, "storey"):
            continue
        clauses.append({"relation": "connection",
                        "text": f"its connection to the {family} named "
                                f"'{name}'"})
        break
    storey = scene.storey_of(product)
    label = scene.storey_label(storey) if storey is not None else None
    if label:
        clauses.append({"relation": "containment",
                        "text": f"its assignment to {label}"})
    rooms = []
    for guid in scene.bounded_spaces(product):
        space = scene.by_guid(guid)
        phrase = scene.space_phrase(space) if space is not None else None
        if phrase:
            rooms.append(phrase)
        if len(rooms) == 2:
            break
    if len(rooms) == 1:
        clauses.append({"relation": "space_boundary",
                        "text": f"the boundary it forms with the {rooms[0]}"})
    elif len(rooms) == 2:
        clauses.append({"relation": "space_boundary",
                        "text": f"the boundaries it forms with the {rooms[0]} "
                                f"and the {rooms[1]}"})
    host_guid = scene.host_of(product)
    host = scene.by_guid(host_guid) if host_guid else None
    host_name = scene.unique_name(host) if host is not None else None
    if host_name:
        clauses.append({"relation": "opening",
                        "text": f"the opening it fills in the wall named "
                                f"'{host_name}'"})
    return clauses[:MAX_NAMED_RELATIONS]


def attach_named_relations(scene: Scene, product, plan: EditPlan, rng) -> bool:
    """Write the sentence's list of relationships into the plan, if one is drawn.

    The list names relationships the element already takes part in, so the
    instruction asks for nothing the plain wording did not already ask for.
    """
    if plan.params.get("scope") == "batch" or plan.params.get("constraint"):
        return False
    if not families.draw("wording.relationship_named", rng):
        return False
    clauses = _named_relation_clauses(scene, product)
    if len(clauses) < 2:
        return False
    keep = clauses if len(clauses) == 2 else clauses[:rng.choice((2, 3))]
    plan.params["named_relations"] = keep
    plan.params["named_relations_form"] = int(rng.randrange(4))
    tag(plan, "wording.relationship_named")
    return True


def own_dependants(scene: Scene, product) -> tuple[list, list]:
    """The openings cut into an element, and what those openings hold.

    Both go when the element goes: an opening voids a host and cannot outlive
    it, and a door or a window exists by filling an opening.  The lists are
    what the record names as removed, so a reader of the task can check the
    gold model against them element by element.
    """
    openings, fillings = [], []
    for relation in getattr(product, "HasOpenings", ()) or ():
        opening = relation.RelatedOpeningElement
        if opening is None:
            continue
        openings.append(opening)
        for fill in getattr(opening, "HasFillings", ()) or ():
            filling = fill.RelatedBuildingElement
            if filling is not None:
                fillings.append(filling)
    return (list({o.GlobalId: o for o in openings}.values()),
            list({f.GlobalId: f for f in fillings}.values()))


def plan_delete(scene: Scene, product, rng) -> Optional[EditPlan]:
    """Remove one element and everything that cannot exist without it.

    An element that hosts doors or windows is removed with them.  The library
    call the gold and the sandbox share takes the openings cut into the
    element and the fillings those openings hold, so the instruction says
    "delete the wall" and the model that comes back has no door standing in
    mid-air.  The compositional tier still draws the same edit written out
    step by step, which is a different task and a different sentence.
    """
    family = scene.family_of(product)
    if family is None:
        return None
    guid = product.GlobalId
    opening = own_opening(product) if family in ("door", "window") else None
    if opening is not None and settings.SETTINGS.delete_filling_removes_opening:
        # A removed door or window takes the hole it filled with it, so the wall
        # is not left voided by an opening nothing fills.
        plan = EditPlan(
            kind="delete", operation="delete", family=family,
            calls=[Call("delete_filling_with_opening", (guid,),
                        "remove the element, the opening it fills and the two "
                        "relationships that tie them to the wall")],
            target_guids=(guid,), removed_guids=(guid, opening.GlobalId),
            touched_guids=(guid,), params={"magnitude": "small",
                                           "opening_removed": True})
        attach_constraint(plan, rng)
        attach_named_relations(scene, product, plan, rng)
        return plan
    openings, fillings = own_dependants(scene, product)
    removed = [guid] + [o.GlobalId for o in openings] + \
        [f.GlobalId for f in fillings]
    params = {"magnitude": "small"}
    if fillings:
        params["hosted_removed"] = [
            {"guid": f.GlobalId, "family": scene.family_of(f),
             "name": (f.Name or "").strip() or None} for f in fillings]
    if openings:
        params["openings_removed"] = [o.GlobalId for o in openings]
    plan = EditPlan(
        kind="delete", operation="delete", family=family,
        calls=[Call("delete_element", (guid,),
                    "remove the element and its dependent relationships")],
        target_guids=(guid,), removed_guids=tuple(removed),
        touched_guids=(guid,), params=params)
    attach_constraint(plan, rng)
    attach_named_relations(scene, product, plan, rng)
    return plan


# ------------------------------------------------------------ create family


def storey_axis_aligned(scene: Scene, storey) -> bool:
    """True when the storey's own x and y axes run along the world axes."""
    matrix = scene.matrix(storey)
    if matrix is None:
        return False
    return abs(float(matrix[0, 0])) > 0.999 and abs(float(matrix[1, 1])) > 0.999


def spot_fault(scene: Scene, storey, x: float, y: float, z: float,
               size: tuple[float, float, float]) -> Optional[str]:
    """Why a box of that size may not stand at that point on the storey."""
    matrix = scene.matrix(storey)
    if matrix is None:
        return None
    length, width, height = size
    box = Extent(np.array([x, y, z], dtype=float),
                 np.array([x + length, y + width, z + max(height, 0.0)],
                          dtype=float))
    # A created element stands inside the ground the storey's own fabric covers.
    # The footprint is a box in world axes, and a storey turned against those
    # axes is not the box its own coordinates would suggest, so the element's
    # corners are compared where the footprint was measured.  A storey too
    # little of whose fabric can be meshed has no footprint to test against, and
    # only the collision rule below applies to it.
    footprint = scene.storey_footprint(storey)
    if footprint is not None:
        corners = world_corners(matrix, box)
        if bool(np.any(corners[:, :2].min(axis=0) < footprint.lo[:2])
                or np.any(corners[:, :2].max(axis=0) > footprint.hi[:2])):
            return "created_outside_storey"
    if height <= 0.0:
        return None
    # A created element does not stand where another element already stands.
    if occupied_share(scene, matrix, box.lo, box.hi,
                      storey.GlobalId) > COLLISION_SHARE:
        return "created_element_collides"
    return None


def free_spot(scene: Scene, storey, footprint: tuple[float, float], rng,
              height: float = 0.0, z: float = 0.0
              ) -> Optional[tuple[float, float]]:
    """A base point inside the storey's footprint, in storey coordinates.

    The point is drawn from the middle of the footprint and the element's own
    footprint has to fit inside it, so a created element never lands outside the
    storey it is said to belong to.  The drawn box is then tested against the
    storey's fabric and redrawn where it would occupy matter.
    """
    extent = scene.storey_local_extent(storey)
    if extent is None:
        return None
    span = extent.size
    if span[0] < footprint[0] + 2.0 or span[1] < footprint[1] + 2.0:
        return None
    for _ in range(PLACEMENT_ATTEMPTS):
        x = float(extent.lo[0] + rng.uniform(0.15, 0.75) * span[0])
        y = float(extent.lo[1] + rng.uniform(0.15, 0.75) * span[1])
        if not (x + footprint[0] <= extent.hi[0]
                and y + footprint[1] <= extent.hi[1]):
            continue
        x = _round(x)
        y = _round(y)
        fault = spot_fault(scene, storey, x, y, z,
                           (footprint[0], footprint[1], height))
        if fault is not None:
            note_rejection(fault)
            continue
        return (x, y)
    return None


def plan_create_box(scene: Scene, family: str, storey, task_id: str, rng,
                    like_guid: Optional[str] = None) -> Optional[EditPlan]:
    """Create a box-shaped wall, slab, column or space on a storey."""
    if family not in CREATE_SIZES:
        return None
    if like_guid is None:
        like_guid = scene.body_donor()
    length, width, height = CREATE_SIZES[family]
    if family in ("wall", "column", "space"):
        height = _round(_storey_height(scene, storey) - 0.1)
    spot = free_spot(scene, storey, (length, width), rng, height, 0.0)
    if spot is None:
        return None
    x, y = spot
    guid = free_guid(scene, task_id, "product")
    relation_guid = free_guid(scene, task_id, "containment")
    name = f"{RENAME_STEMS[family]} {rng.randint(100, 998)}"
    values = ()
    sample = scene.elements(family)
    if sample:
        values = predefined_types(sample[0])
    predefined = str(rng.choice(values)) if values else None
    long_name = f"New {family}" if family == "space" else None
    return EditPlan(
        kind="create_box", operation="create", family=family,
        calls=[Call("add_box_element",
                    (BOX_CLASS[family],
                     guid, name, storey.GlobalId, relation_guid, x, y, 0.0,
                     length, width, height, predefined, like_guid, long_name),
                    "create the element and put it in the storey")],
        target_guids=(guid,), created_guids=(guid,), touched_guids=(guid,),
        params={"x": x, "y": y, "z": 0.0, "length": length, "width": width,
                "height": height, "name": name, "predefined_type": predefined,
                "storey_guid": storey.GlobalId, "long_name": long_name,
                "magnitude": magnitude_bucket(scene, max(length, width, height))})


def filling_spans(scene: Scene, wall) -> list[tuple[float, float]]:
    """Along-wall spans of every door and window the wall already carries."""
    frame = scene.matrix(wall)
    if frame is None:
        return []
    spans = []
    for guid in scene.hosted_by(wall):
        element = scene.by_guid(guid)
        if element is None:
            continue
        box = scene.box_in_frame(element, frame)
        if box is not None:
            spans.append((float(box.lo[0]), float(box.hi[0])))
    return spans


def wall_opening_slot(scene: Scene, wall, width: float, height: float,
                      sill: float, rng
                      ) -> Optional[tuple[float, float, float, float]]:
    """Where a new opening may sit in a wall: along, across, depth and base.

    Read from the wall's own extruded profile, so the opening lands inside the
    wall rather than beside it.  A wall whose body cannot be measured is
    refused.
    """
    extent = scene.local_extent(wall)
    if extent is None:
        return None
    body = scene.box_in_frame(wall, scene.matrix(wall))
    if body is None:
        return None
    # The opening is positioned from the profile arithmetic, so a wall whose
    # solid does not agree with that arithmetic is refused rather than guessed
    # at, and the solid itself is then what the rules below measure.
    if float(np.abs(np.concatenate([body.lo - extent.lo,
                                    body.hi - extent.hi])).max()) > 0.1:
        note_rejection("wall_body_disagrees_with_profile")
        return None
    extent = body
    length = float(extent.hi[0] - extent.lo[0])
    thickness = float(extent.hi[1] - extent.lo[1])
    if length < width + 1.0 or not 0.05 <= thickness <= 1.5:
        return None
    # A wall hosts a door or a window only where its own body is tall enough to
    # carry the leaf and its sill and still close over the head.
    if float(extent.hi[2] - extent.lo[2]) < sill + height + FILLING_HEADROOM:
        note_rejection("filling_taller_than_wall")
        return None
    across = _round(float(extent.lo[1]) - 0.05)
    base = float(extent.lo[2])
    spans = filling_spans(scene, wall)
    for _ in range(PLACEMENT_ATTEMPTS):
        along = _round(float(extent.lo[0]) + rng.uniform(0.25, 0.6) * length)
        if along + width > float(extent.hi[0]) - 0.2:
            note_rejection("filling_past_wall_end")
            continue
        # A new door or window keeps clear of every filling the wall carries.
        if any(along < high + FILLING_CLEARANCE
               and along + width > low - FILLING_CLEARANCE
               for low, high in spans):
            note_rejection("filling_overlaps_filling")
            continue
        return (along, across, _round(thickness + 0.1), _round(base + sill))
    return None


def plan_create_filling(scene: Scene, family: str, wall, task_id: str, rng
                        ) -> Optional[EditPlan]:
    """Create a door or a window hosted in an existing wall."""
    if family not in CREATE_FILLING:
        return None
    width, height, sill = CREATE_FILLING[family]
    slot = wall_opening_slot(scene, wall, width, height, sill, rng)
    if slot is None:
        return None
    if scene.storey_of(wall) is None:
        return None
    along, across, thickness, base = slot
    # The leaf fills the wall's own thickness; only the opening cuts past both
    # faces, so the door or window does not stand proud of the wall.
    leaf_across = _round(across + 0.05)
    leaf_depth = _round(thickness - 0.1)
    guid = free_guid(scene, task_id, "product")
    values = ()
    sample = scene.elements(family)
    if sample:
        values = predefined_types(sample[0])
    predefined = str(rng.choice(values)) if values else None
    # No instruction states a door's or a window's predefined type, so the gold
    # leaves it unset: a value the sentence never gives is one no reader could
    # write.  The draw above stays, so every later draw of this
    # task, and of every task after it, is what it was.
    predefined = None
    name = f"{RENAME_STEMS[family]} {rng.randint(100, 998)}"
    opening_guid = free_guid(scene, task_id, "opening")
    return EditPlan(
        kind="create_filling", operation="create", family=family,
        calls=[Call("add_filling",
                    (FILLING_CLASS[family], guid,
                     name, wall.GlobalId, opening_guid,
                     free_guid(scene, task_id, "voids"),
                     free_guid(scene, task_id, "fills"),
                     free_guid(scene, task_id, "containment"),
                     along, across, base, width, height, thickness, predefined,
                     leaf_across, leaf_depth),
                    "cut an opening in the wall and fill it")],
        target_guids=(guid,), created_guids=(guid, opening_guid),
        touched_guids=(guid, wall.GlobalId),
        params={"along": along, "sill": sill, "width": width, "height": height,
                "name": name, "predefined_type": predefined,
                "host_guid": wall.GlobalId,
                "magnitude": magnitude_bucket(scene, max(width, height))})


def respot_from_reference(scene: Scene, plan: EditPlan, storey, reference,
                          rng) -> bool:
    """Re-express a created element's position as an offset from a neighbour.

    A spatial instruction says where to put the new element relative to an
    element the reader can find, so the position has to be recomputed from that
    neighbour rather than quoted as a coordinate.  Returns False when the
    storey's axes are not aligned with the world axes, since the offset words
    would then not mean what they say.
    """
    if not storey_axis_aligned(scene, storey):
        return False
    matrix = scene.matrix(storey)
    point = scene.point(reference)
    extent = scene.storey_local_extent(storey)
    if matrix is None or point is None or extent is None:
        return False
    local = np.linalg.inv(matrix)[:3, :3] @ point + np.linalg.inv(matrix)[:3, 3]
    footprint = (plan.params["length"], plan.params["width"])
    size = (plan.params["length"], plan.params["width"],
            float(plan.params.get("height", 0.0)))
    base_z = float(plan.params.get("z", 0.0))
    steps = [-8.0, -6.0, -4.0, -3.0, 3.0, 4.0, 6.0, 8.0]
    rng.shuffle(steps)
    for dx in steps:
        for dy in steps:
            x = float(local[0]) + dx
            y = float(local[1]) + dy
            if not (extent.lo[0] <= x and x + footprint[0] <= extent.hi[0]):
                continue
            if not (extent.lo[1] <= y and y + footprint[1] <= extent.hi[1]):
                continue
            fault = spot_fault(scene, storey, x, y, base_z, size)
            if fault is not None:
                note_rejection(fault)
                continue
            word_x, axis_x = AXIS_WORDS[(0, 1 if dx > 0 else -1)]
            word_y, axis_y = AXIS_WORDS[(1, 1 if dy > 0 else -1)]
            plan.params["x"] = x
            plan.params["y"] = y
            plan.params["offset"] = {
                "reference_guid": reference.GlobalId,
                "dx": abs(dx), "dy": abs(dy), "x_word": word_x,
                "x_axis": axis_x, "y_word": word_y, "y_axis": axis_y}
            call = plan.calls[0]
            args = list(call.args)
            args[5], args[6] = x, y
            plan.calls[0] = Call(call.func, tuple(args), call.comment)
            return True
    return False


# =====================================================================
# 0.5.0: the requirement families the benchmark's published task scope
# carries.  Three of them change what a create task asks for: where the new
# element goes when no coordinate is given, which frame a coordinate is read
# in, and which relationships the new element has to carry.
# =====================================================================

# The relation classes a gold script may write on a create task.
SPACE_BOUNDARY = "IfcRelSpaceBoundary"
CONNECTS_ELEMENTS = "IfcRelConnectsElements"
CONTAINED_IN_STOREY = "IfcRelContainedInSpatialStructure"

# Families that may be asked to bound spaces, and families that may be asked
# to connect to other elements.
BOUNDARY_FAMILIES = ("wall", "slab", "column", "door", "window", "space")
CONNECTS_FAMILIES = ("wall", "slab", "column")

# How far, in metres, a named space or element may sit from a created element
# before the relationship the instruction states would be untrue of the model.
RELATION_REACH = 8.0

# A space boundary or a connection says the two ends meet, so the named partner
# has to touch the created element and not merely stand near it.  The gap is
# measured between the two world boxes, which is what an authoring tool would
# have to see before writing the relationship itself.
RELATION_TOUCH = 0.15

# How far a created element may sit from the edge of the storey's footprint and
# still be called an external boundary.
EXTERNAL_MARGIN = 0.5


def tag(plan: EditPlan, name: str) -> None:
    """Record that one of the 0.5.0 requirement families is used by this task."""
    families = plan.params.setdefault("families", [])
    if name not in families:
        families.append(name)


def storey_world_aligned(scene: Scene, storey) -> bool:
    """True when the storey's own axes are the world axes, same sign and order."""
    matrix = scene.matrix(storey)
    if matrix is None:
        return False
    return bool(np.abs(np.array(matrix)[:3, :3] - np.identity(3)).max() < 1e-3)


def world_to_storey(scene: Scene, storey, point) -> Optional[np.ndarray]:
    """A world point in metres, expressed in the storey's own coordinates."""
    matrix = scene.matrix(storey)
    if matrix is None:
        return None
    inverse = np.linalg.inv(np.array(matrix, dtype=float))
    return inverse[:3, :3] @ np.asarray(point, dtype=float) + inverse[:3, 3]


def world_spot_fault(scene: Scene, storey, lo, size) -> Optional[str]:
    """Why a box may not stand at a world point, using the storey's own rules."""
    local = world_to_storey(scene, storey, lo)
    if local is None:
        return "no_storey_placement"
    return spot_fault(scene, storey, float(local[0]), float(local[1]),
                      float(local[2]), tuple(float(v) for v in size))


def storey_base_z(scene: Scene, storey) -> float:
    """World elevation of the storey's own origin, in metres."""
    matrix = scene.matrix(storey)
    if matrix is None:
        return 0.0
    return float(np.array(matrix)[2, 3])


def _world_box(scene: Scene, product) -> Optional[Extent]:
    return scene.world_box(product)


def _named_on_storey(scene: Scene, family: str, storey_guid: str, rng,
                     limit: int = 40) -> list:
    """Elements of one family on one storey that a phrase may name."""
    pool = [e for e in scene.on_storey(family, storey_guid)
            if scene.unique_name(e)]
    rng.shuffle(pool)
    return pool[:limit]


def _set_box_call(plan: EditPlan, lo, size, world: bool,
                  turn: float = 0.0) -> None:
    """Rewrite the create call so it places the box where the draw decided.

    ``turn`` is how far the storey's own axes stand from the world axes, in
    degrees.  On a storey that follows the world axes the box's size runs along
    those axes and its world box is known from the corner and the size, which is
    what the funnel checks.  On a turned storey the size runs along the storey's
    own axes instead, so what the instruction fixes, and what the funnel checks,
    is the world position of the corner it quotes.
    """
    call = plan.calls[0]
    args = list(call.args)
    args[5], args[6], args[7] = (_round(lo[0]), _round(lo[1]), _round(lo[2]))
    args[8], args[9], args[10] = (_round(size[0]), _round(size[1]),
                                  _round(size[2]))
    turned = float(turn) > conditions.ROTATION_TOLERANCE
    if not world:
        func = "add_box_element"
    elif turned:
        func = "add_box_element_world_turned"
    else:
        func = "add_box_element_world"
    plan.calls[0] = Call(func, tuple(args), call.comment)
    plan.params["x"] = _round(lo[0])
    plan.params["y"] = _round(lo[1])
    plan.params["z"] = _round(lo[2])
    plan.params["length"] = _round(size[0])
    plan.params["width"] = _round(size[1])
    plan.params["height"] = _round(size[2])
    plan.params["frame"] = "world" if world else "storey"
    plan.params["storey_rotation_deg"] = round(float(turn), 1) if turned else None
    plan.params["expected_world_box"] = {
        "guid": plan.created_guids[0],
        "lo": [_round(lo[0]), _round(lo[1]), _round(lo[2])],
        "hi": [_round(lo[0] + size[0]), _round(lo[1] + size[1]),
               _round(lo[2] + size[2])],
        "tolerance": 0.05} if world and not turned else None
    plan.params["expected_world_origin"] = {
        "guid": plan.created_guids[0],
        "point": [_round(lo[0]), _round(lo[1]), _round(lo[2])],
        "tolerance": 0.05} if world and turned else None


# --------------------------------------------------- derived placement kinds


def _derive_fits_gap(scene: Scene, plan: EditPlan, storey, rng
                     ) -> Optional[dict[str, Any]]:
    """Close the gap between two named walls that run along one line."""
    if plan.family != "wall":
        return None
    walls = _named_on_storey(scene, "wall", storey.GlobalId, rng, 24)
    boxed = [(w, _world_box(scene, w)) for w in walls]
    boxed = [(w, b) for w, b in boxed if b is not None]
    for i in range(len(boxed)):
        for j in range(i + 1, len(boxed)):
            first, box_a = boxed[i]
            second, box_b = boxed[j]
            for axis in (0, 1):
                other = 1 - axis
                # The two walls have to run along the same line, so their extents
                # across that line overlap and their gap along it is real.
                low = max(float(box_a.lo[other]), float(box_b.lo[other]))
                high = min(float(box_a.hi[other]), float(box_b.hi[other]))
                if high - low < 0.05:
                    continue
                # Only two thin walls standing on one line leave a gap a third
                # wall closes.  Two blocks that merely overlap across the line
                # would give the new wall a cross-section metres deep, which is
                # not what the words say, so they are passed over.
                if high - low > 1.2 or float(box_a.size[other]) > 1.2 \
                        or float(box_b.size[other]) > 1.2:
                    continue
                if float(box_a.hi[axis]) <= float(box_b.lo[axis]):
                    start, end = float(box_a.hi[axis]), float(box_b.lo[axis])
                    left, right = first, second
                elif float(box_b.hi[axis]) <= float(box_a.lo[axis]):
                    start, end = float(box_b.hi[axis]), float(box_a.lo[axis])
                    left, right = second, first
                else:
                    continue
                gap = end - start
                if not 0.4 <= gap <= 8.0:
                    continue
                base = max(float(box_a.lo[2]), float(box_b.lo[2]))
                top = min(float(box_a.hi[2]), float(box_b.hi[2]))
                if top - base < 1.5:
                    continue
                lo = [0.0, 0.0, base]
                size = [0.0, 0.0, top - base]
                lo[axis], size[axis] = start, gap
                lo[other], size[other] = low, high - low
                fault = world_spot_fault(scene, storey, lo, size)
                if fault is not None:
                    note_rejection(f"derived_fits_gap_{fault}")
                    continue
                return {"kind": "fits_gap", "lo": lo, "size": size,
                        "refs": [left.GlobalId, right.GlobalId],
                        "anchor_guid": left.GlobalId,
                        "thickness": _round(high - low),
                        "a_name": scene.unique_name(left),
                        "b_name": scene.unique_name(right),
                        "a_family": scene.family_of(left),
                        "b_family": scene.family_of(right)}
    return None


def _derive_on_top_of(scene: Scene, plan: EditPlan, storey, rng
                      ) -> Optional[dict[str, Any]]:
    """Stand the new element on the top face of a named one."""
    family = plan.family
    donors = {"column": ("column",), "wall": ("wall", "slab"),
              "slab": ("wall", "slab", "column")}.get(family)
    if donors is None:
        return None
    height = float(plan.params["height"])
    for donor_family in donors:
        for reference in _named_on_storey(scene, donor_family, storey.GlobalId,
                                          rng, 16):
            box = _world_box(scene, reference)
            if box is None:
                continue
            plan_size = box.size[:2]
            if not (0.1 <= float(plan_size[0]) <= 8.0
                    and 0.1 <= float(plan_size[1]) <= 8.0):
                continue
            lo = [float(box.lo[0]), float(box.lo[1]), float(box.hi[2])]
            size = [float(plan_size[0]), float(plan_size[1]), height]
            fault = world_spot_fault(scene, storey, lo, size)
            if fault is not None:
                note_rejection(f"derived_on_top_of_{fault}")
                continue
            return {"kind": "on_top_of", "lo": lo, "size": size,
                    "refs": [reference.GlobalId],
                    "anchor_guid": reference.GlobalId,
                    "a_name": scene.unique_name(reference),
                    "a_family": donor_family}
    return None


def _derive_adjacent_to_space(scene: Scene, plan: EditPlan, storey, rng
                              ) -> Optional[dict[str, Any]]:
    """Stand the new element against a named room's boundary wall, inside it."""
    height = float(plan.params["height"])
    length = float(plan.params["length"])
    width = float(plan.params["width"])
    spaces = _named_on_storey(scene, "space", storey.GlobalId, rng, 16)
    for space in spaces:
        label = scene.space_phrase(space)
        room = _world_box(scene, space)
        if not label or room is None:
            continue
        centre = (room.lo + room.hi) / 2.0
        for guid in scene.space_elements(space):
            wall = scene.by_guid(guid)
            if wall is None or scene.family_of(wall) != "wall":
                continue
            name = scene.unique_name(wall)
            box = _world_box(scene, wall)
            if not name or box is None:
                continue
            # The wall's short plan axis is the one the new element stands off.
            across = int(np.argmin(box.size[:2]))
            along = 1 - across
            inward = 1.0 if float(centre[across]) > float(box.hi[across]) - \
                float(box.size[across]) / 2.0 else -1.0
            face = float(box.hi[across]) if inward > 0 else float(box.lo[across])
            size = [0.0, 0.0, height]
            size[across] = width
            size[along] = length
            lo = [0.0, 0.0, float(room.lo[2])]
            lo[across] = face if inward > 0 else face - width
            lo[along] = _round(0.5 * (float(box.lo[along]) + float(box.hi[along]))
                               - length / 2.0)
            fault = world_spot_fault(scene, storey, lo, size)
            if fault is not None:
                note_rejection(f"derived_adjacent_to_space_{fault}")
                continue
            return {"kind": "adjacent_to_space", "lo": lo, "size": size,
                    "refs": [space.GlobalId, wall.GlobalId],
                    "anchor_guid": wall.GlobalId,
                    "space_label": label, "a_name": name, "a_family": "wall"}
    return None


def _derive_touching_slab_above(scene: Scene, plan: EditPlan, storey, rng
                                ) -> Optional[dict[str, Any]]:
    """Rise from the storey's floor and stop at the underside of a named slab."""
    if plan.family not in ("column", "wall"):
        return None
    base = storey_base_z(scene, storey)
    length = float(plan.params["length"])
    width = float(plan.params["width"])
    candidates = _named_on_storey(scene, "slab", storey.GlobalId, rng, 12)
    above = scene.storey_neighbour(storey, 1)
    if above is not None:
        candidates += _named_on_storey(scene, "slab", above.GlobalId, rng, 12)
    for slab in candidates:
        box = _world_box(scene, slab)
        name = scene.unique_name(slab)
        if box is None or not name:
            continue
        height = float(box.lo[2]) - base
        if not 2.0 <= height <= 6.0:
            continue
        if float(box.size[0]) < length + 1.0 or float(box.size[1]) < width + 1.0:
            continue
        for _ in range(PLACEMENT_ATTEMPTS):
            x = _round(float(box.lo[0]) + rng.uniform(0.2, 0.8)
                       * (float(box.size[0]) - length))
            y = _round(float(box.lo[1]) + rng.uniform(0.2, 0.8)
                       * (float(box.size[1]) - width))
            lo = [x, y, base]
            size = [length, width, _round(height)]
            fault = world_spot_fault(scene, storey, lo, size)
            if fault is not None:
                note_rejection(f"derived_touching_slab_{fault}")
                continue
            return {"kind": "touching_slab_above", "lo": lo, "size": size,
                    "refs": [slab.GlobalId], "anchor_guid": slab.GlobalId,
                    "a_name": name, "a_family": "slab"}
    return None


# How often each derived placement kind was asked for and could not be built,
# so a run can report which kinds this corpus does not support.
DERIVED_ATTEMPTS: dict[str, int] = {}


def note_derived(kind: str, ok: bool) -> None:
    DERIVED_ATTEMPTS[f"{kind}:{'ok' if ok else 'refused'}"] = \
        DERIVED_ATTEMPTS.get(f"{kind}:{'ok' if ok else 'refused'}", 0) + 1


def derived_counts() -> dict[str, int]:
    return dict(sorted(DERIVED_ATTEMPTS.items()))


def reset_derived() -> None:
    DERIVED_ATTEMPTS.clear()


def derive_box_placement(scene: Scene, plan: EditPlan, storey, rng) -> bool:
    """Replace a created box's quoted position with one read off the model.

    Returns False when no kind applies, and the caller then keeps the position
    the draw already had.  The storey has to stand square with the world axes,
    because every kind is expressed in world metres and the words the
    instruction uses for the axes would otherwise not mean what they say.
    """
    if not storey_world_aligned(scene, storey):
        note_rejection("derived_storey_not_world_aligned")
        return False
    for family in families.members("spec.element_relative", rng, target="box"):
        builder = families.build(family)
        try:
            drawn = builder(scene, plan, storey, rng)
        except Exception:
            drawn = None
        note_derived(family.tag, drawn is not None)
        if drawn is None:
            continue
        _set_box_call(plan, drawn["lo"], drawn["size"], world=True)
        plan.params["placement"] = drawn
        plan.params["magnitude"] = magnitude_bucket(scene, max(drawn["size"]))
        tag(plan, family.tag)
        return True
    return False


# ------------------------------------------- derived placement for fillings


def derive_filling_placement(scene: Scene, plan: EditPlan, wall, rng) -> bool:
    """Give a created door or window a position read off the model.

    Two kinds apply to a filling.  One states the distance to the middle of the
    leaf rather than to its edge, so the reader has to halve the width before
    placing it.  The other puts the leaf directly above or below a named door or
    window on the storey next door, which is read from that element's position.
    """
    for family in families.members("spec.element_relative", rng,
                                   target="filling"):
        builder = families.build(family)
        try:
            ok = builder(scene, plan, wall, rng)
        except Exception:
            ok = False
        note_derived(family.tag, ok)
        if ok:
            tag(plan, family.tag)
            return True
    return False


def _derive_centred_on_wall(scene: Scene, plan: EditPlan, wall, rng) -> bool:
    """State where the middle of the leaf sits, measured from the wall's start."""
    extent = scene.local_extent(wall)
    if extent is None:
        return False
    along = float(plan.params["along"])
    width = float(plan.params["width"])
    centre = _round(along + width / 2.0 - float(extent.lo[0]))
    if centre <= 0.0:
        return False
    plan.params["placement"] = {"kind": "centred_on_wall",
                                "refs": [wall.GlobalId],
                                "centre_from_start": centre,
                                "a_name": scene.unique_name(wall),
                                "a_family": "wall"}
    return True


def _derive_above_below_filling(scene: Scene, plan: EditPlan, wall, rng) -> bool:
    """Line the new leaf up with a named one on the storey above or below."""
    storey = scene.storey_of(wall)
    if storey is None:
        return False
    frame = scene.matrix(wall)
    own = scene.box_in_frame(wall, frame)
    if frame is None or own is None:
        return False
    width = float(plan.params["width"])
    for direction, step in (("above", -1), ("below", 1)):
        neighbour = scene.storey_neighbour(storey, step)
        if neighbour is None:
            continue
        for family in ("door", "window"):
            for reference in _named_on_storey(scene, family,
                                              neighbour.GlobalId, rng, 12):
                point = scene.centre(reference)
                if point is None:
                    continue
                local = np.linalg.inv(frame)[:3, :3] @ point \
                    + np.linalg.inv(frame)[:3, 3]
                if abs(float(local[1])) > 1.0:
                    continue
                along = _round(float(local[0]) - width / 2.0)
                if along < float(own.lo[0]) + 0.2 or \
                        along + width > float(own.hi[0]) - 0.2:
                    continue
                spans = filling_spans(scene, wall)
                if any(along < high + FILLING_CLEARANCE
                       and along + width > low - FILLING_CLEARANCE
                       for low, high in spans):
                    note_rejection("derived_above_below_overlaps_filling")
                    continue
                call = plan.calls[0]
                args = list(call.args)
                args[8] = along
                plan.calls[0] = Call(call.func, tuple(args), call.comment)
                plan.params["along"] = along
                plan.params["placement"] = {
                    "kind": "above_below_filling", "refs": [reference.GlobalId],
                    "direction": direction,
                    "a_name": scene.unique_name(reference),
                    "a_family": family}
                return True
    return False


# ------------------------------------------------------ relation requirements


def _boundary_kind(scene: Scene, storey, box) -> str:
    """Whether a created element's boundary counts as internal or external."""
    footprint = scene.storey_footprint(storey)
    if footprint is None or box is None:
        return "INTERNAL"
    lo = np.asarray(box["lo"], dtype=float)
    hi = np.asarray(box["hi"], dtype=float)
    near = np.minimum(np.abs(lo[:2] - footprint.lo[:2]),
                      np.abs(hi[:2] - footprint.hi[:2]))
    return "EXTERNAL" if float(near.min()) <= EXTERNAL_MARGIN else "INTERNAL"


def _element_world_box(scene: Scene, plan: EditPlan) -> Optional[dict[str, Any]]:
    expected = plan.params.get("expected_world_box")
    if expected:
        return expected
    return None


def _box_gap(first, second) -> float:
    """Distance between two world boxes, zero where they overlap."""
    lo_a, hi_a = first
    lo_b, hi_b = second
    apart = np.maximum(np.maximum(lo_a - hi_b, lo_b - hi_a), 0.0)
    return float(np.linalg.norm(apart))


def _created_world_box(scene: Scene, plan: EditPlan, storey):
    """World box of the element the plan creates, before the model carries it.

    The box is read from the parameters the create call will use, through the
    frame those parameters are stated in, so it is available at draw time.
    """
    expected = plan.params.get("expected_world_box")
    if expected:
        return (np.asarray(expected["lo"], dtype=float),
                np.asarray(expected["hi"], dtype=float))
    params = plan.params
    if plan.kind == "create_box":
        frame = scene.matrix(storey)
        lo = np.array([params["x"], params["y"], params["z"]], dtype=float)
        size = np.array([params["length"], params["width"], params["height"]],
                        dtype=float)
    elif plan.kind == "create_filling":
        host = scene.by_guid(params.get("host_guid", ""))
        frame = None if host is None else scene.matrix(host)
        across = params.get("filling_across")
        across = params.get("across", 0.0) if across is None else across
        depth = params.get("filling_depth")
        depth = params.get("thickness", 0.0) if depth is None else depth
        lo = np.array([params["along"], float(across), params["sill"]],
                      dtype=float)
        size = np.array([params["width"], float(depth), params["height"]],
                        dtype=float)
    else:
        return None
    if frame is None:
        return None
    frame = np.asarray(frame, dtype=float)
    corners = np.array([[lo[0] + size[0] * i, lo[1] + size[1] * j,
                         lo[2] + size[2] * k]
                        for i in (0, 1) for j in (0, 1) for k in (0, 1)])
    world = (frame[:3, :3] @ corners.T).T + frame[:3, 3]
    return world.min(axis=0), world.max(axis=0)


def _near_named(scene: Scene, storey, family: str, centre, rng, want: int,
                reach: float = RELATION_REACH, box=None) -> list:
    """Named elements of a family on the storey that touch the created box.

    Standing near is not enough.  A relationship states that the two ends meet,
    so a candidate whose world box is further than ``RELATION_TOUCH`` from the
    created element's is refused, as is one whose body the index cannot measure.
    The survivors come out with the closest first.
    """
    scored = []
    for element in scene.on_storey(family, storey.GlobalId):
        if not scene.unique_name(element) and family != "space":
            continue
        if family == "space" and not scene.space_phrase(element):
            continue
        point = scene.centre(element)
        if point is None:
            continue
        distance = float(np.linalg.norm(np.asarray(centre) - point))
        if distance > reach:
            continue
        if box is not None:
            other = scene.world_box(element)
            if other is None:
                note_rejection("relation_partner_has_no_body")
                continue
            gap = _box_gap(box, (other.lo, other.hi))
            if gap > RELATION_TOUCH:
                note_rejection("relation_partner_not_touching")
                continue
            distance = gap
        scored.append((distance, element.GlobalId, element))
    scored.sort(key=lambda triple: (triple[0], triple[1]))
    return [element for _d, _g, element in scored[:want]]


def attach_relations(scene: Scene, plan: EditPlan, storey, task_id: str, rng
                     ) -> bool:
    """State a relationship the new element has to carry, and write it.

    A create instruction may say which rooms the new element bounds, or which
    elements it is connected to.  The relationship is only stated where the
    model can carry it: the rooms or elements named have to exist on the same
    storey, close enough to the new element for the statement to be true, and
    each has to have a name a phrase can use.
    """
    family = plan.family
    guid = plan.created_guids[0] if plan.created_guids else None
    if guid is None:
        return False
    box = _element_world_box(scene, plan)
    if box is not None:
        centre = (np.asarray(box["lo"], dtype=float)
                  + np.asarray(box["hi"], dtype=float)) / 2.0
    else:
        centre = _plan_centre(scene, plan, storey)
    if centre is None:
        return False
    world = _created_world_box(scene, plan, storey)
    if world is None:
        # Without a box for the new element there is no way to tell whether the
        # partner touches it, so no relationship is stated.
        note_rejection("relation_created_box_unknown")
        return False
    plan.params["relation_world_box"] = [world[0].tolist(), world[1].tolist()]
    for entry in families.members("constraint.relation_on_create", rng):
        if entry.tag.endswith("space_boundary") and family not in BOUNDARY_FAMILIES:
            continue
        if entry.tag.endswith("connection") and family not in CONNECTS_FAMILIES:
            continue
        builder = families.build(entry)
        if builder(scene, plan, storey, task_id, rng, centre, box):
            tag(plan, entry.tag)
            plan.params.pop("relation_world_box", None)
            return True
    plan.params.pop("relation_world_box", None)
    return False


def _plan_centre(scene: Scene, plan: EditPlan, storey) -> Optional[np.ndarray]:
    """Where the created element stands in world metres, from its parameters."""
    if plan.kind == "create_filling":
        host = scene.by_guid(plan.params.get("host_guid", ""))
        if host is None:
            return None
        frame = scene.matrix(host)
        if frame is None:
            return None
        local = np.array([float(plan.params["along"])
                          + float(plan.params["width"]) / 2.0, 0.0,
                          float(plan.params.get("sill", 0.0))], dtype=float)
        return frame[:3, :3] @ local + frame[:3, 3]
    matrix = scene.matrix(storey)
    if matrix is None:
        return None
    local = np.array([float(plan.params["x"]) + float(plan.params["length"]) / 2.0,
                      float(plan.params["y"]) + float(plan.params["width"]) / 2.0,
                      float(plan.params["z"])], dtype=float)
    return np.array(matrix)[:3, :3] @ local + np.array(matrix)[:3, 3]


def _relation_box(plan: EditPlan):
    """The created element's world box, as ``attach_relations`` measured it."""
    stored = plan.params.get("relation_world_box")
    if not stored:
        return None
    return (np.asarray(stored[0], dtype=float),
            np.asarray(stored[1], dtype=float))


def _record_relation(plan: EditPlan, ifc_class: str, relating: str,
                     related: str, relation_guid: str) -> None:
    plan.params.setdefault("relation_edges", []).append(
        [ifc_class, relating, related])
    plan.relation_guids = tuple(plan.relation_guids) + (relation_guid,)


def _attach_space_boundary(scene: Scene, plan: EditPlan, storey, task_id: str,
                           rng, centre, box=None) -> bool:
    guid = plan.created_guids[0]
    world = _relation_box(plan)
    family = plan.family
    want = 2 if rng.random() < 0.6 else 1
    if family == "space":
        # A new room is bounded by walls rather than the other way round, so the
        # relationship is written with the created space on the relating end.
        partners = _near_named(scene, storey, "wall", centre, rng, want,
                               box=world)
        if not partners:
            return False
        kind = _boundary_kind(scene, storey, box)
        phrases = []
        for index, wall in enumerate(partners):
            relation_guid = free_guid(scene, task_id, f"boundary{index}")
            plan.calls.append(Call(
                "add_space_boundary",
                (relation_guid, guid, wall.GlobalId, "PHYSICAL", kind, None),
                "record that the named wall bounds the new space"))
            _record_relation(plan, SPACE_BOUNDARY, guid, wall.GlobalId,
                             relation_guid)
            phrases.append(scene.unique_name(wall))
        plan.params["relation"] = {"kind": "bounded_by", "names": phrases,
                                   "partner_family": "wall",
                                   "ifc_class": SPACE_BOUNDARY}
        return True
    partners = _near_named(scene, storey, "space", centre, rng, want,
                           box=world)
    if not partners:
        return False
    kind = _boundary_kind(scene, storey, box)
    phrases = []
    for index, space in enumerate(partners):
        relation_guid = free_guid(scene, task_id, f"boundary{index}")
        plan.calls.append(Call(
            "add_space_boundary",
            (relation_guid, space.GlobalId, guid, "PHYSICAL", kind, None),
            "record that the new element bounds the named space"))
        _record_relation(plan, SPACE_BOUNDARY, space.GlobalId, guid,
                         relation_guid)
        phrases.append(scene.space_phrase(space))
    plan.params["relation"] = {"kind": "bounds", "names": phrases,
                               "partner_family": "space",
                               "ifc_class": SPACE_BOUNDARY}
    return True


def _attach_connects(scene: Scene, plan: EditPlan, storey, task_id: str, rng,
                     centre, box=None) -> bool:
    guid = plan.created_guids[0]
    world = _relation_box(plan)
    want = 2 if rng.random() < 0.5 else 1
    partner_family = "wall" if rng.random() < 0.7 else "column"
    partners = _near_named(scene, storey, partner_family, centre, rng, want,
                           box=world)
    if not partners:
        return False
    phrases = []
    for index, other in enumerate(partners):
        relation_guid = free_guid(scene, task_id, f"connects{index}")
        plan.calls.append(Call(
            "connect_elements", (relation_guid, guid, other.GlobalId, None),
            "record the connection between the new element and the named one"))
        _record_relation(plan, CONNECTS_ELEMENTS, guid, other.GlobalId,
                         relation_guid)
        phrases.append(scene.unique_name(other))
    plan.params["relation"] = {"kind": "connects", "names": phrases,
                               "partner_family": partner_family,
                               "ifc_class": CONNECTS_ELEMENTS}
    return True


# ------------------------------------------------------- coordinate forms


def use_world_coordinates(scene: Scene, plan: EditPlan, storey) -> bool:
    """Quote a created box's position in world metres instead of storey metres.

    The numbers change frame, not place: the box lands exactly where the storey
    coordinates would have put it, and the elevation the instruction quotes is
    the storey's own rather than zero.
    """
    if plan.params.get("frame") == "world":
        return True
    matrix = scene.matrix(storey)
    if matrix is None:
        return False
    turn = conditions.storey_rotation(scene, storey)
    if not storey_world_aligned(scene, storey):
        # A storey drawn on a skewed grid is converted rather than refused, but
        # only when its own axes are a turn about the vertical and nothing else.
        # A mirrored or a tilted system would make the words "length" and
        # "height" mean something the reader cannot see.
        if not conditions.is_upright_turn(matrix):
            note_rejection("world_storey_axes_not_a_turn")
            return False
    local = np.array([float(plan.params["x"]), float(plan.params["y"]),
                      float(plan.params["z"])], dtype=float)
    world = np.array(matrix)[:3, :3] @ local + np.array(matrix)[:3, 3]
    size = (float(plan.params["length"]), float(plan.params["width"]),
            float(plan.params["height"]))
    _set_box_call(plan, world, size, world=True, turn=turn)
    tag(plan, "spec.world_frame")
    if float(turn) > conditions.ROTATION_TOLERANCE:
        tag(plan, "model.placement.rotated_storey")
    return True


def use_wall_span(scene: Scene, plan: EditPlan, storey, rng) -> bool:
    """State a created wall as the line its faces follow, in world metres.

    The wall is given as two world points at one elevation, the side its
    thickness lies on, and its height, which is how a work order describes a
    wall a person is about to set out.
    """
    if plan.family != "wall" or plan.params.get("frame") != "world":
        return False
    if plan.params.get("storey_rotation_deg"):
        # The span is two world points and a thickness on a world axis, which
        # only describes a wall built on the world grid.
        return False
    lo = np.array([float(plan.params["x"]), float(plan.params["y"]),
                   float(plan.params["z"])], dtype=float)
    size = np.array([float(plan.params["length"]), float(plan.params["width"]),
                     float(plan.params["height"])], dtype=float)
    run = int(np.argmax(size[:2]))
    across = 1 - run
    if float(size[run]) < 2.0 * float(size[across]):
        return False
    direction = str(rng.choice(["+", "-"]))
    line = float(lo[across]) if direction == "+" else float(lo[across] + size[across])
    start = [0.0, 0.0, float(lo[2])]
    end = [0.0, 0.0, float(lo[2])]
    start[run], end[run] = float(lo[run]), float(lo[run] + size[run])
    start[across] = end[across] = line
    axis_word = "x" if across == 0 else "y"
    call = plan.calls[0]
    args = list(call.args)
    # add_wall_span takes the span rather than a corner and a size.
    plan.calls[0] = Call(
        "add_wall_span",
        (args[1], args[2], args[3], args[4],
         _round(start[0]), _round(start[1]), _round(start[2]),
         _round(end[0]), _round(end[1]), _round(end[2]),
         _round(size[across]), f"{direction}{axis_word}", _round(size[2]),
         args[11], args[12]),
        "set the wall out along the line its faces follow")
    plan.params["span"] = {"start": [_round(v) for v in start],
                           "end": [_round(v) for v in end],
                           "thickness": _round(size[across]),
                           "thickness_direction": f"{direction}{axis_word}",
                           "height": _round(size[2])}
    tag(plan, "spec.endpoints")
    return True


# --------------------------------------------------------- constraint clauses

def constraint_for(plan: EditPlan, rng) -> Optional[str]:
    """A constraint clause the gold edit already satisfies, or None.

    Which clauses an edit admits is a property of the edit and is stated once,
    beside the family in the registry, so a new clause is a registry entry and a
    predicate rather than another branch here.
    """
    if not families.draw("constraint.on_edit", rng):
        return None
    admitted = [f for f in families.candidates("constraint.on_edit")
                if families.admits(f, plan)]
    if not admitted:
        return None
    total = sum(families.weight(f) for f in admitted)
    point = rng.random() * total
    for family in sorted(admitted, key=lambda f: f.tag):
        point -= families.weight(family)
        if point <= 0:
            return family.tag
    return admitted[-1].tag


def attach_constraint(plan: EditPlan, rng) -> None:
    """Add an invariance clause to an edit that already satisfies it.

    The clause states something the gold does rather than something it has to be
    made to do, so it constrains the reader and not the generator: a rename
    leaves the element where it stands, and saying so is true of the gold model
    that was already written.
    """
    name = constraint_for(plan, rng)
    if name is None:
        return
    plan.params["constraint"] = name
    tag(plan, name)


# Which relationship classes each gold call writes into the model.
CALL_RELATIONS = {
    "add_box_element": (CONTAINED_IN_STOREY,),
    "add_box_element_world": (CONTAINED_IN_STOREY,),
    "add_wall_span": (CONTAINED_IN_STOREY,),
    "add_filling": ("IfcRelVoidsElement", "IfcRelFillsElement",
                    CONTAINED_IN_STOREY),
    "add_space_boundary": (SPACE_BOUNDARY,),
    "connect_elements": (CONNECTS_ELEMENTS,),
    # 0.6.0
    "copy_element": (CONTAINED_IN_STOREY,),
    "array_elements": (CONTAINED_IN_STOREY,),
    "replace_filling": ("IfcRelVoidsElement", "IfcRelFillsElement",
                        CONTAINED_IN_STOREY),
    "rehost_filling": ("IfcRelVoidsElement",),
    "move_to_storey": (CONTAINED_IN_STOREY,),
    "assign_material": ("IfcRelAssociatesMaterial",),
    "assign_type": ("IfcRelDefinesByType",),
    "set_property_value": ("IfcRelDefinesByProperties",),
}


def required_relations(plan: EditPlan) -> list[str]:
    """The relationship classes the gold script adds, for the task record.

    Stage A stratifies on this and Stage C rewards it, so it is read off the
    calls the script actually makes rather than declared alongside them.  A
    space is aggregated under its storey rather than contained in it, which the
    box writer decides from the class it is given.
    """
    out: list[str] = list(plan.params.get("relation_classes") or ())
    for call in plan.calls:
        for name in CALL_RELATIONS.get(call.func, ()):
            if name == CONTAINED_IN_STOREY and call.args and \
                    call.args[0] == "IfcSpace":
                name = "IfcRelAggregates"
            if name not in out:
                out.append(name)
    return sorted(out)


def family_tags(plan: EditPlan, anchor_kind: str = "",
                tier: str = "single") -> list[str]:
    """Every requirement family one task uses, named after the taxonomy.

    The reference the instruction uses, the operation it performs and the scope
    it covers are read off the task rather than declared by the planner, so a
    record carries a label for every layer the generator can settle.
    """
    from .anchors import KIND_FAMILY

    tags = list(plan.params.get("families") or ())
    reference = KIND_FAMILY.get(anchor_kind)
    if reference:
        tags.append(reference)
    scope = plan.params.get("scope")
    names = [families.operation_tag(plan.kind)]
    names.append(f"scope.{scope}" if scope else families.scope_tag(tier))
    for name in names:
        if name:
            tags.append(name)
    return sorted(dict.fromkeys(tags))


def use_axis_dimensions(scene: Scene, plan: EditPlan, storey, rng) -> bool:
    """State a created box's size by the world axis each dimension runs along.

    Only meaningful once the position is quoted in the world frame, because the
    axes the numbers refer to are then the world axes.
    """
    if plan.params.get("frame") != "world":
        return False
    if plan.params.get("storey_rotation_deg"):
        # On a turned storey the element's own axes are not the world axes, so
        # a size stated per world axis would not be the size of the element.
        return False
    plan.params["size_form"] = "axis"
    tag(plan, "spec.axis_dimensions")
    return True


# =====================================================================
# 0.6.0: the operations of the taxonomy's first layer, and the scopes of its
# fifth.  Each planner draws one edit, refuses what the model cannot carry and
# leaves the counting to the caller, exactly as the earlier planners do.
# =====================================================================

# Angles, in degrees, a rotation may turn an element through.  A half turn is
# absent because a box turned through it stands where it stood.
ROTATION_ANGLES = (15.0, 30.0, 45.0, 60.0, 90.0)

# How far, in metres, a mirrored element has to end up from where it stood
# before the edit is worth writing: a plane through the element itself would
# otherwise leave it almost in place.
MIRROR_MIN_SHIFT = 0.5

# The property set each family carries its common values in, and the values a
# task may write into it.  Every entry names the IFC type the value is written
# as, so the model carries a fire rating as a label and a transmittance as a
# measure rather than as a string.
PSET_OF_FAMILY = {
    "wall": "Pset_WallCommon", "slab": "Pset_SlabCommon",
    "column": "Pset_ColumnCommon", "door": "Pset_DoorCommon",
    "window": "Pset_WindowCommon",
}

PSET_PROPERTIES: dict[str, tuple[tuple[str, str, tuple], ...]] = {
    "Pset_WallCommon": (
        ("FireRating", "IfcLabel", ("F30", "F60", "F90", "F120")),
        ("IsExternal", "IfcBoolean", (True, False)),
        ("LoadBearing", "IfcBoolean", (True, False)),
        ("ThermalTransmittance", "IfcThermalTransmittanceMeasure",
         (0.15, 0.24, 0.35, 1.40)),
    ),
    "Pset_SlabCommon": (
        ("FireRating", "IfcLabel", ("F30", "F60", "F90", "F120")),
        ("IsExternal", "IfcBoolean", (True, False)),
        ("LoadBearing", "IfcBoolean", (True, False)),
        ("ThermalTransmittance", "IfcThermalTransmittanceMeasure",
         (0.15, 0.22, 0.30)),
    ),
    "Pset_ColumnCommon": (
        ("FireRating", "IfcLabel", ("F30", "F60", "F90", "F120")),
        ("IsExternal", "IfcBoolean", (True, False)),
        ("LoadBearing", "IfcBoolean", (True, False)),
    ),
    "Pset_DoorCommon": (
        ("FireRating", "IfcLabel", ("F30", "F60", "F90")),
        ("IsExternal", "IfcBoolean", (True, False)),
        ("ThermalTransmittance", "IfcThermalTransmittanceMeasure",
         (1.30, 1.80, 2.20)),
    ),
    "Pset_WindowCommon": (
        ("FireRating", "IfcLabel", ("F30", "F60", "F90")),
        ("IsExternal", "IfcBoolean", (True, False)),
        ("ThermalTransmittance", "IfcThermalTransmittanceMeasure",
         (0.80, 1.10, 1.40)),
    ),
}

#: How each property reads in an instruction.
PROPERTY_WORDS = {
    "FireRating": "fire rating",
    "IsExternal": "external flag",
    "LoadBearing": "load-bearing flag",
    "ThermalTransmittance": "thermal transmittance",
}

#: Materials a task may name when the model carries none worth naming.
#: What each family may plausibly be made of, and the words that recognise the
#: same material in a name the model already carries.  A benchmark a builder
#: reads has to ask for a wall of brick and a window of aluminium, not a wall of
#: whatever string the exporter happened to leave in the file.  The keywords
#: carry the languages this corpus is written in as well as English, because a
#: German model calls concrete Beton and a Spanish one hormigon.
MATERIAL_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Brick masonry": ("brick", "masonry", "mauerwerk", "ziegel", "brique",
                      "ladrillo", "tijolo", "murverk", "tegl"),
    "Concrete": ("concrete", "beton", "béton", "hormigon", "hormigón",
                 "concreto", "betong"),
    "Reinforced concrete": ("reinforced concrete", "stahlbeton",
                            "béton armé", "beton arme", "hormigon armado",
                            "hormigón armado", "concreto armado",
                            "armert betong"),
    "Precast concrete": ("precast", "fertigteil", "prefabricado",
                         "préfabriqué", "prefabricado de concreto"),
    "Aerated concrete block": ("aerated", "porenbeton", "ytong", "gasbeton",
                               "beton cellulaire", "béton cellulaire"),
    "Cross-laminated timber": ("cross-laminated", "clt", "brettsperrholz",
                               "bois lamellé", "madera contralaminada"),
    "Glulam timber": ("glulam", "brettschichtholz", "lamellé collé",
                      "laminada encolada"),
    "Plasterboard on studs": ("plasterboard", "gypsum", "gipskarton", "gips",
                              "placo", "plaque de platre", "yeso", "gesso"),
    "Composite steel deck": ("composite deck", "verbunddecke", "steel deck",
                             "chapa colaborante"),
    "Structural steel": ("steel", "stahl", "acier", "acero", "aço", "aco",
                         "stål", "stal"),
    "Timber": ("timber", "wood", "holz", "bois", "madera", "madeira", "tre",
               "tré", "tra"),
    "Aluminium": ("aluminium", "aluminum", "alu"),
    "Glazed aluminium": ("glazed aluminium", "glazed aluminum",
                         "aluminium vitré"),
    "PVC-u": ("pvc", "kunststoff", "plastico", "plástico"),
}

#: The materials each family may be asked for, in the order a draw shuffles.
MATERIAL_VOCABULARY: dict[str, tuple[str, ...]] = {
    "wall": ("Brick masonry", "Concrete", "Aerated concrete block",
             "Cross-laminated timber", "Plasterboard on studs"),
    "slab": ("Reinforced concrete", "Precast concrete",
             "Cross-laminated timber", "Composite steel deck"),
    "column": ("Reinforced concrete", "Structural steel", "Glulam timber"),
    "door": ("Timber", "Structural steel", "Aluminium", "Glazed aluminium"),
    "window": ("Aluminium", "Timber", "PVC-u", "Structural steel"),
}

#: Materials a family may also be given when the model already names one, even
#: though a draw would not ask for them by name.  A wall of reinforced concrete
#: is a wall a building has; a door of it is not.
MATERIAL_ALSO_ACCEPTS: dict[str, tuple[str, ...]] = {
    "wall": ("Reinforced concrete", "Precast concrete"),
    "slab": ("Concrete",),
    "column": ("Concrete", "Precast concrete"),
    "door": (),
    "window": (),
}


def material_kind(name: str) -> Optional[str]:
    """Which material a name in the model stands for, or ``None``.

    The longest keyword that occurs in the name decides, so ``Stahlbeton`` is
    reinforced concrete rather than steel and ``Leichtbeton`` is concrete.
    """
    lowered = name.lower()
    best, longest = None, 0
    for entry, keywords in MATERIAL_KEYWORDS.items():
        for word in keywords:
            if word in lowered and len(word) > longest:
                best, longest = entry, len(word)
    return best

#: The type classes each family may be assigned to, IFC2X3 styles included.
TYPE_CLASSES = {
    "wall": ("IfcWallType",), "slab": ("IfcSlabType",),
    "column": ("IfcColumnType",), "space": ("IfcSpaceType",),
    "door": ("IfcDoorType", "IfcDoorStyle"),
    "window": ("IfcWindowType", "IfcWindowStyle"),
}

#: How many copies an array task writes.
ARRAY_COUNTS = (2, 3, 4)

#: Metres the box a re-hosted leaf is tested against is grown by, on every
#: axis, before the test is run.
REHOST_MARGIN = 0.05

#: The most members one batch edit is written over.  A larger set costs one
#: rebuilt entity per member in the funnel and says nothing a smaller one does
#: not.
MAX_BATCH = 12


def _placement_is_own(scene: Scene, product) -> bool:
    """True when the element's placement positions it and nothing else."""
    placement = getattr(product, "ObjectPlacement", None)
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        return False
    users = [i for i in scene.model.get_inverse(placement)
             if i.is_a("IfcProduct") and i.id() != product.id()]
    return not users


def occupied_over_storeys(scene: Scene, matrix: np.ndarray, lo, hi,
                          storey_guids: Sequence[str],
                          skip: Sequence[str] = ()) -> float:
    """The largest share any neighbour of any of these storeys already holds.

    A wall and the door it hosts are not always recorded on the same storey, so
    a test that reads one of them reads only half the neighbours the element
    actually stands among.
    """
    worst = 0.0
    for guid in dict.fromkeys(g for g in storey_guids if g):
        worst = max(worst, occupied_share(scene, matrix, lo, hi, guid, skip))
    return worst


def transform_fault(scene: Scene, product, matrix: np.ndarray, storey,
                    skip: Sequence[str], box=None,
                    collision: bool = True) -> Optional[str]:
    """Why an element's body may not stand in a new frame.

    The body is read in the element's own axes, so the test is exact for a
    turned or a reflected element rather than for the box around it.
    """
    if box is None:
        box = scene.own_frame_box(product)
    if box is None:
        return "transform_body_unreadable"
    footprint = scene.storey_footprint(storey)
    if footprint is not None:
        corners = world_corners(np.asarray(matrix, dtype=float), box)
        if bool(np.any(corners[:, :2].min(axis=0) < footprint.lo[:2] - 1e-6)
                or np.any(corners[:, :2].max(axis=0) > footprint.hi[:2] + 1e-6)):
            return "transformed_outside_storey"
    if collision and occupied_over_storeys(
            scene, np.asarray(matrix, dtype=float), box.lo, box.hi,
            (storey.GlobalId,) + related_storey_guids(scene, product),
            skip) > COLLISION_SHARE:
        return "transformed_element_collides"
    return None


def outside_footprint(scene: Scene, storey, matrix, lo, size) -> bool:
    """Whether a box given in some frame stands outside the storey's footprint.

    The box is given by its low corner and its size in the frame ``matrix``
    describes, and its eight corners are compared with the storey's footprint in
    plan.  A storey too few of whose elements carry a body has no footprint to
    compare against and is not judged.
    """
    footprint = scene.storey_footprint(storey)
    if footprint is None:
        return False
    low = np.asarray(lo, dtype=float)
    box = Extent(low, low + np.asarray(size, dtype=float))
    corners = world_corners(np.asarray(matrix, dtype=float), box)
    return bool(np.any(corners[:, :2].min(axis=0) < footprint.lo[:2] - 1e-6)
                or np.any(corners[:, :2].max(axis=0) > footprint.hi[:2] + 1e-6))


def _turn_matrix(degrees: float, pivot: np.ndarray) -> np.ndarray:
    angle = np.radians(float(degrees))
    turn = np.identity(4)
    turn[0, 0], turn[0, 1] = np.cos(angle), -np.sin(angle)
    turn[1, 0], turn[1, 1] = np.sin(angle), np.cos(angle)
    about = np.identity(4)
    about[:3, 3] = np.array([pivot[0], pivot[1], 0.0], dtype=float)
    back = np.identity(4)
    back[:3, 3] = -about[:3, 3]
    return about @ np.round(turn, 12) @ back


def plan_rotate(scene: Scene, product, rng, task_id: str = ""
                ) -> Optional[EditPlan]:
    """Turn one element about the vertical axis by a stated angle."""
    family = scene.family_of(product)
    if family in ("door", "window"):
        # A leaf turned out of its opening no longer sits in the wall it fills.
        return None
    if not _placement_is_own(scene, product):
        note_rejection("rotate_shared_placement")
        return None
    if stranded_dependants(scene, product):
        note_rejection("rotate_leaves_dependant")
        return None
    storey = scene.storey_of(product)
    matrix = scene.matrix(product)
    box = scene.own_frame_box(product)
    world = scene.world_box(product)
    if storey is None or matrix is None or box is None or world is None:
        return None
    if float(min(world.size[0], world.size[1])) < 0.05:
        return None
    origin = np.array(matrix, dtype=float)[:3, 3]
    centre = (world.lo + world.hi) / 2.0
    skip = [product.GlobalId] + list(scene.hosted_by(product))
    for _attempt in range(PLACEMENT_ATTEMPTS):
        degrees = float(rng.choice(ROTATION_ANGLES))
        if rng.random() < 0.5:
            pivot, pivot_word = origin, "origin"
        else:
            pivot, pivot_word = centre, "centre"
        turned = _turn_matrix(degrees, pivot) @ np.array(matrix, dtype=float)
        fault = transform_fault(scene, product, turned, storey, skip, box)
        if fault is not None:
            note_rejection(fault)
            continue
        guid = product.GlobalId
        return EditPlan(
            kind="rotate", operation="update", family=family,
            calls=[Call("rotate", (guid, _round(degrees), _round(pivot[0]),
                                   _round(pivot[1])),
                        "turn the element about the vertical axis, in degrees, "
                        "about a world point in metres")],
            target_guids=(guid,), touched_guids=(guid,),
            params={"degrees": _round(degrees), "pivot": pivot_word,
                    "pivot_x": _round(pivot[0]), "pivot_y": _round(pivot[1]),
                    "magnitude": magnitude_bucket(
                        scene, float(max(world.size[0], world.size[1])))})
    return None


def _mirror_plane_from_wall(scene: Scene, wall) -> Optional[tuple]:
    """The vertical plane a named wall's own axis defines, in world metres."""
    run = wall_run_axis(scene, wall)
    box = scene.world_box(wall)
    if run is None or box is None:
        return None
    axis, _direction = run
    across = 1 - axis
    centre = float((box.lo[across] + box.hi[across]) / 2.0)
    normal = [0.0, 0.0]
    normal[across] = 1.0
    point = [0.0, 0.0]
    point[across] = centre
    return point, normal, across


def plan_mirror(scene: Scene, product, rng, task_id: str = ""
                ) -> Optional[EditPlan]:
    """Reflect one element across the axis of a named wall or a stated plane."""
    family = scene.family_of(product)
    if family in ("door", "window"):
        return None
    if not _placement_is_own(scene, product):
        note_rejection("mirror_shared_placement")
        return None
    if stranded_dependants(scene, product):
        note_rejection("mirror_leaves_dependant")
        return None
    body = goldlib.mirrorable_body(scene.model, product)
    if body is None:
        # A mirror is a flip of the element's own profile about its centre, so a
        # body with no profile of its own cannot carry one.  Geometry borrowed
        # from a type object has a profile, but it belongs to every element of
        # that type, so flipping it would reflect elements the instruction never
        # named.
        kind = conditions.representation_kind(product)
        note_rejection(f"mirror_undefinable_on_{kind}"
                       if conditions.undefinable_reason(product, "mirror")
                       else "mirror_body_not_flippable")
        return None
    _solid, own_centre = body
    storey = scene.storey_of(product)
    matrix = scene.matrix(product)
    box = scene.own_frame_box(product)
    world = scene.world_box(product)
    if storey is None or matrix is None or box is None or world is None:
        return None
    candidates: list[tuple] = []
    for wall in _named_on_storey(scene, "wall", storey.GlobalId, rng, limit=12):
        if wall.GlobalId == product.GlobalId:
            continue
        plane = _mirror_plane_from_wall(scene, wall)
        if plane is None:
            continue
        point, normal, across = plane
        candidates.append(("wall_axis", point, normal, across,
                           scene.unique_name(wall)))
    footprint = scene.storey_footprint(storey)
    if footprint is not None:
        for across in (0, 1):
            offset = float(rng.choice([1.0, 1.5, 2.0, 3.0]))
            value = _round(float(world.hi[across]) + offset)
            point = [0.0, 0.0]
            point[across] = value
            normal = [0.0, 0.0]
            normal[across] = 1.0
            candidates.append(("point", point, normal, across, None))
    rng.shuffle(candidates)
    skip = [product.GlobalId] + list(scene.hosted_by(product))
    for kind, point, normal, across, name in candidates:
        plane_value = float(point[across])
        shift = abs(2.0 * plane_value
                    - float(world.lo[across] + world.hi[across]))
        if shift < MIRROR_MIN_SHIFT:
            note_rejection("mirror_plane_too_close")
            continue
        reflect = np.identity(4)
        reflect[across, across] = -1.0
        reflect[across, 3] = 2.0 * plane_value
        flip = np.identity(4)
        flip[0, 0] = -1.0
        flip[0, 3] = 2.0 * float(own_centre)
        turned = reflect @ np.array(matrix, dtype=float) @ flip
        flipped = Extent(
            np.array([2.0 * own_centre - box.hi[0], box.lo[1], box.lo[2]]),
            np.array([2.0 * own_centre - box.lo[0], box.hi[1], box.hi[2]]))
        fault = transform_fault(scene, product, turned, storey, skip, flipped)
        if fault is not None:
            note_rejection(fault)
            continue
        guid = product.GlobalId
        word = "x" if across == 0 else "y"
        return EditPlan(
            kind="mirror", operation="update", family=family,
            calls=[Call("mirror", (guid, _round(point[0]), _round(point[1]),
                                   _round(normal[0]), _round(normal[1])),
                        "reflect the element across a vertical plane, given by "
                        "a world point and the direction its normal runs in")],
            target_guids=(guid,), touched_guids=(guid,),
            params={"plane_kind": kind, "plane_wall": name,
                    "plane_axis": word, "plane_value": _round(plane_value),
                    "magnitude": magnitude_bucket(scene, shift)})
    return None


# ------------------------------------------------------- property-set values


def property_index(scene: Scene) -> dict[str, dict[str, dict[str, Any]]]:
    """Every element's own property-set values, read once per model.

    Walking the model's property relationships for one value costs the same as
    walking them for all of them, and a draw asks for several, so the whole map
    is built on the first question and cached on the scene beside the geometry
    index.
    """
    index = getattr(scene, "_own_property_index", None)
    if index is not None:
        return index
    index = {}
    for relation in scene.model.by_type("IfcRelDefinesByProperties"):
        definition = relation.RelatingPropertyDefinition
        if definition is None or not definition.is_a("IfcPropertySet"):
            continue
        values = {}
        for prop in definition.HasProperties or ():
            if prop.is_a("IfcPropertySingleValue"):
                value = prop.NominalValue
                values[prop.Name] = None if value is None else value.wrappedValue
        name = definition.Name or ""
        for member in relation.RelatedObjects or ():
            index.setdefault(member.GlobalId, {}).setdefault(name, {}).update(values)
    setattr(scene, "_own_property_index", index)
    return index


def own_property_value(scene: Scene, product, pset_name: str,
                       property_name: str):
    """The value the element's own property set carries, or ``None``.

    Only the sets attached to this element are read, because that is what the
    edit writes; a value the element inherits from its type is left alone.
    """
    return property_index(scene).get(product.GlobalId, {}).get(
        pset_name, {}).get(property_name)


def _differs(old, new) -> bool:
    """Whether writing ``new`` over ``old`` changes what the score reads.

    The score compares numbers within five per cent, so a new number has to
    stand clear of that band to be an edit rather than a rounding.
    """
    if old is None:
        return True
    if isinstance(old, bool) or isinstance(new, bool):
        return bool(old) != bool(new)
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        denominator = max(abs(float(old)), abs(float(new)))
        if denominator == 0.0:
            return False
        return abs(float(old) - float(new)) / denominator > 0.2
    return str(old) != str(new)


def plan_set_pset(scene: Scene, product, rng, task_id: str = ""
                  ) -> Optional[EditPlan]:
    """Set or change one property-set value on an element."""
    family = scene.family_of(product)
    pset_name = PSET_OF_FAMILY.get(family or "")
    if pset_name is None:
        return None
    entries = list(PSET_PROPERTIES[pset_name])
    rng.shuffle(entries)
    for property_name, value_type, choices in entries:
        current = own_property_value(scene, product, pset_name, property_name)
        options = [v for v in choices if _differs(current, v)]
        if not options:
            continue
        value = options[int(rng.random() * len(options)) % len(options)]
        guid = product.GlobalId
        return EditPlan(
            kind="set_pset", operation="update", family=family,
            calls=[Call("set_property_value",
                        (guid, pset_name, property_name, value, value_type,
                         free_guid(scene, task_id or guid, "pset"),
                         free_guid(scene, task_id or guid, "psetrel")),
                        "write one property-set value, creating the set if the "
                        "element does not carry it")],
            target_guids=(guid,), touched_guids=(guid,),
            params={"pset": pset_name, "property": property_name,
                    "property_word": PROPERTY_WORDS[property_name],
                    "value": value, "value_type": value_type,
                    "old": current, "magnitude": "small"})
    return None


# ------------------------------------------------------ material and type


def _current_material_name(scene: Scene, product) -> Optional[str]:
    import ifcopenshell.util.element as element_util

    try:
        material = element_util.get_material(product)
    except Exception:
        return None
    if material is None:
        return None
    name = getattr(material, "Name", None)
    return str(name) if name else None


def material_names(scene: Scene) -> list[str]:
    """Every material name the model already carries, in a stable order."""
    return sorted({(m.Name or "").strip()
                   for m in scene.model.by_type("IfcMaterial")
                   if (m.Name or "").strip()})


def material_choice(scene: Scene, family: str, current: Optional[str], rng
                    ) -> Optional[tuple[str, str]]:
    """A material this family may be made of, and where the name came from.

    A name the model already carries is preferred, so the instruction asks for
    something the building is built of, but only when that name means the
    material the vocabulary asked for.  Otherwise the material is created under
    the plain name, which is the name the instruction then quotes.
    """
    wanted = MATERIAL_VOCABULARY.get(family or "")
    if not wanted:
        return None
    accepted = set(wanted) | set(MATERIAL_ALSO_ACCEPTS.get(family, ()))
    existing = material_names(scene)
    matches = sorted({name for name in existing
                      if name != current and material_kind(name) in accepted})
    if matches:
        return str(rng.choice(matches)), "existing"
    options = list(wanted)
    rng.shuffle(options)
    for entry in options:
        if entry != current and entry not in existing:
            return entry, "new"
    return None


def plan_assign_material(scene: Scene, product, rng, task_id: str = ""
                         ) -> Optional[EditPlan]:
    """Associate one element with a material it does not already carry.

    A space is not given a material: a room is a volume of air and no authoring
    tool records what it is made of.
    """
    family = scene.family_of(product)
    current = _current_material_name(scene, product)
    chosen = material_choice(scene, family, current, rng)
    if chosen is None:
        return None
    name, source = chosen
    guid = product.GlobalId
    return EditPlan(
        kind="assign_material", operation="update", family=family,
        calls=[Call("assign_material",
                    (guid, name, free_guid(scene, task_id or guid, "material")),
                    "associate the element with the material, replacing the "
                    "association it had")],
        target_guids=(guid,), touched_guids=(guid,),
        params={"material": name, "material_source": source, "old": current,
                "magnitude": "small"})


def plan_assign_type(scene: Scene, product, rng, task_id: str = ""
                     ) -> Optional[EditPlan]:
    """Assign one element to an existing type object of the right class."""
    import ifcopenshell.util.element as element_util

    family = scene.family_of(product)
    classes = TYPE_CLASSES.get(family or "")
    if not classes:
        return None
    try:
        current = element_util.get_type(product)
    except Exception:
        current = None
    current_guid = getattr(current, "GlobalId", None)
    candidates = []
    for ifc_class in classes:
        try:
            candidates.extend(scene.model.by_type(ifc_class))
        except Exception:
            continue
    counts: dict[str, int] = {}
    for candidate in candidates:
        name = (candidate.Name or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1
    usable = [c for c in candidates
              if c.GlobalId != current_guid
              and (c.Name or "").strip()
              and counts.get((c.Name or "").strip(), 0) == 1]
    if not usable:
        return None
    usable.sort(key=lambda c: c.GlobalId)
    chosen = usable[int(rng.random() * len(usable)) % len(usable)]
    guid = product.GlobalId
    return EditPlan(
        kind="assign_type", operation="update", family=family,
        calls=[Call("assign_type",
                    (guid, chosen.GlobalId,
                     free_guid(scene, task_id or guid, "typerel")),
                    "assign the element to the type object, replacing the type "
                    "it had"),],
        target_guids=(guid,), touched_guids=(guid,),
        params={"type_name": (chosen.Name or "").strip(),
                "type_class": chosen.is_a(), "type_guid": chosen.GlobalId,
                "old": (getattr(current, "Name", None) or None),
                "magnitude": "small"})


# ------------------------------------------------------ another storey


def plan_move_to_storey(scene: Scene, product, rng, task_id: str = ""
                        ) -> Optional[EditPlan]:
    """Move one element into another storey, in the model and in space."""
    family = scene.family_of(product)
    if family in ("door", "window"):
        return None
    if scene.hosted_by(product):
        # A wall that carries doors would leave them contained in the storey it
        # left, which is the compositional tier's edit rather than this one.
        note_rejection("restorey_leaves_fillings")
        return None
    if not _placement_is_own(scene, product) or stranded_dependants(scene, product):
        note_rejection("restorey_shared_placement")
        return None
    storey = scene.storey_of(product)
    matrix = scene.matrix(product)
    box = scene.own_frame_box(product)
    if storey is None or matrix is None or box is None:
        return None
    here = scene.matrix(storey)
    if here is None:
        return None
    others = [s for s in scene.storeys
              if s.GlobalId != storey.GlobalId and scene.storey_label(s)]
    rng.shuffle(others)
    for target in others:
        there = scene.matrix(target)
        if there is None:
            continue
        if float(np.abs(np.array(there)[:3, :3] - np.array(here)[:3, :3]).max()) > 1e-6:
            note_rejection("restorey_storeys_turned_apart")
            continue
        delta = np.array(there, dtype=float)[:3, 3] - np.array(here, dtype=float)[:3, 3]
        keep_world = rng.random() < 0.5
        moved = np.array(matrix, dtype=float).copy()
        if not keep_world:
            moved[:3, 3] = moved[:3, 3] + delta
        # The element has to lie inside the footprint of the storey it joins,
        # whether or not it moves, because a storey that does not cover it is
        # not a storey it belongs to.  An element that keeps its world position
        # keeps the neighbours it already stood among, so only the footprint is
        # asked about there.
        fault = transform_fault(scene, product, moved, target,
                                [product.GlobalId], box,
                                collision=not keep_world)
        if fault is not None:
            note_rejection(fault)
            continue
        if not keep_world and float(np.abs(delta).max()) < 0.2:
            note_rejection("restorey_storeys_at_one_elevation")
            continue
        guid = product.GlobalId
        return EditPlan(
            kind="move_to_storey", operation="update", family=family,
            calls=[Call("move_to_storey",
                        (guid, target.GlobalId,
                         free_guid(scene, task_id or guid, "containment"),
                         bool(keep_world)),
                        "put the element in the other storey and re-place it")],
            target_guids=(guid,), touched_guids=(guid,),
            params={"storey_from": scene.storey_label(storey),
                    "storey_to": scene.storey_label(target),
                    "storey_to_guid": target.GlobalId,
                    "keep_world": bool(keep_world),
                    "elevation_shift": _round(float(delta[2])),
                    "magnitude": magnitude_bucket(
                        scene, float(np.abs(delta).max()))})
    return None


# ------------------------------------------------------------ re-hosting


def _rectangular_extrusion(scene: Scene, product) -> bool:
    solid = goldlib.sole_extrusion(scene.model, product)
    return solid is not None and solid.SweptArea.is_a("IfcRectangleProfileDef")


def _origin_in_frame(scene: Scene, product, frame) -> Optional[np.ndarray]:
    """A product's placement origin, expressed in another element's frame."""
    matrix = scene.matrix(product)
    if matrix is None or frame is None:
        return None
    inverse = np.linalg.inv(np.asarray(frame, dtype=float))
    return inverse[:3, :3] @ np.asarray(matrix, dtype=float)[:3, 3] \
        + inverse[:3, 3]


def _hangs_from(child, ancestor_placement) -> bool:
    placement = getattr(child, "ObjectPlacement", None)
    while placement is not None and placement.is_a("IfcLocalPlacement"):
        if placement.id() == ancestor_placement.id():
            return True
        placement = placement.PlacementRelTo
    return False


def plan_rehost(scene: Scene, product, rng, task_id: str = ""
                ) -> Optional[EditPlan]:
    """Move a door or a window, with its opening, into another wall."""
    family = scene.family_of(product)
    if family not in ("door", "window"):
        return None
    opening = own_opening(product)
    host_guid = scene.host_of(product)
    host = scene.by_guid(host_guid) if host_guid else None
    if opening is None or host is None:
        note_rejection("rehost_without_opening")
        return None
    if not _placement_is_own(scene, opening) or not _rectangular_extrusion(scene, opening):
        note_rejection("rehost_opening_not_rewritable")
        return None
    host_placement = host.ObjectPlacement
    if opening.ObjectPlacement.PlacementRelTo is None or \
            opening.ObjectPlacement.PlacementRelTo.id() != host_placement.id():
        note_rejection("rehost_opening_not_hung_from_host")
        return None
    leaf_follows = _hangs_from(product, opening.ObjectPlacement)
    if not leaf_follows:
        if not _placement_is_own(scene, product):
            note_rejection("rehost_leaf_shared_placement")
            return None
        parent = product.ObjectPlacement.PlacementRelTo
        if parent is None or parent.id() != host_placement.id():
            note_rejection("rehost_leaf_not_hung_from_host")
            return None
    old_frame = scene.matrix(host)
    old_body = scene.box_in_frame(host, old_frame)
    hole = scene.box_in_frame(opening, old_frame)
    leaf_box = scene.box_in_frame(product, old_frame)
    if old_frame is None or old_body is None or hole is None or leaf_box is None:
        return None
    width = float(hole.size[0])
    height = float(hole.size[2])
    sill_above_base = float(hole.lo[2] - old_body.lo[2])
    if width < 0.3 or height < 0.3 or sill_above_base < -0.05:
        return None
    # The whole assembly travels by one offset inside the wall frames, so every
    # body keeps the place it had relative to every other.  The two placements
    # are read in the old wall's own coordinates, because that is the frame the
    # offset is applied in.
    opening_origin = _origin_in_frame(scene, opening, old_frame)
    leaf_origin = _origin_in_frame(scene, product, old_frame)
    if opening_origin is None or leaf_origin is None:
        return None
    leaf_depth = None
    if not leaf_follows and _rectangular_extrusion(scene, product):
        leaf_depth = True
    # The writer clears the leaf's and the opening's own rotation, so after the
    # edit both bodies stand along the new wall's axes.  The ground they take is
    # therefore their body read in their own axes and hung at the point the gold
    # will write, not the box they happened to cast in the wall they came from.
    # Reading the old wall's box let a door that stood turned in its opening
    # land a fifth of its volume inside a proxy in the 0.7.0 pilot.
    own_leaf = scene.own_frame_box(product)
    own_hole = scene.own_frame_box(opening)
    if own_leaf is None or own_hole is None:
        note_rejection("rehost_body_unreadable")
        return None
    storey = scene.storey_of(host)
    if storey is None:
        return None
    walls = [w for w in scene.on_storey("wall", storey.GlobalId)
             if w.GlobalId != host.GlobalId and scene.unique_name(w)]
    rng.shuffle(walls)
    for wall in walls[:16]:
        frame = scene.matrix(wall)
        body = scene.box_in_frame(wall, frame)
        if frame is None or body is None:
            continue
        if wall_run_axis(scene, wall) is None:
            continue
        thickness = float(body.size[1])
        if not 0.05 <= thickness <= 1.5:
            continue
        if float(body.size[2]) < sill_above_base + height + FILLING_HEADROOM:
            note_rejection("rehost_wall_too_short")
            continue
        length = float(body.size[0])
        if length < width + 1.0:
            continue
        spans = filling_spans(scene, wall)
        across = _round(float(body.lo[1]) - 0.05)
        # The assembly rises or falls by the difference between the two walls'
        # own bases, so the opening keeps the height above its wall's base that
        # it had, and the leaf keeps the height it had above the opening.
        lift = float(body.lo[2] - old_body.lo[2])
        # The leaf takes the new wall's thickness where its body can be
        # rewritten, and keeps its own depth where it cannot.  Across the wall
        # the test covers both readings, the body's own extent and the depth the
        # writer would give it, because over-testing can only refuse a position
        # and never let a bad one through.
        depth = thickness if leaf_depth else float(own_leaf.size[1])
        leaf_across_lo = min(float(own_leaf.lo[1]), -depth / 2.0)
        leaf_across_hi = max(float(own_leaf.hi[1]), depth / 2.0)
        # The ground the leaf takes is its own body, not the hole it hangs in.
        size = np.array([float(own_leaf.size[0]),
                         leaf_across_hi - leaf_across_lo,
                         float(own_leaf.size[2])], dtype=float)
        # Everything the leaf and its opening leave behind or take with them is
        # excluded from the collision test; anything else standing where the
        # leaf would go is a reason to try another position.
        skip = [product.GlobalId, opening.GlobalId, host.GlobalId,
                wall.GlobalId]
        # A wall and the leaf it carries are not always recorded on the same
        # storey, so both are asked what stands there.
        storeys = (scene.storey_guid_of(wall), scene.storey_guid_of(product),
                   storey.GlobalId)
        # The storey the assembly joins is the one the wall it moves into
        # belongs to, which is not always the one it came from.
        destination = scene.storey_of(wall) or storey
        # The two bodies together are what has to fit between the wall's ends
        # and clear of the fillings it already carries.  Along the wall each is
        # measured from the origin the gold will place it at, which is where it
        # will stand once its own rotation is cleared.
        span_lo = min(float(opening_origin[0]) + float(own_hole.lo[0]),
                      float(leaf_origin[0]) + float(own_leaf.lo[0]))
        span_hi = max(float(opening_origin[0]) + float(own_hole.hi[0]),
                      float(leaf_origin[0]) + float(own_leaf.hi[0]))
        along = None
        shift = None
        for _ in range(PLACEMENT_ATTEMPTS):
            candidate = _round(float(body.lo[0]) + rng.uniform(0.25, 0.6) * length)
            move = candidate - (float(opening_origin[0])
                                + float(own_hole.lo[0]))
            if span_lo + move < float(body.lo[0]) + 0.1 \
                    or span_hi + move > float(body.hi[0]) - 0.1:
                note_rejection("rehost_past_wall_end")
                continue
            if any(span_lo + move < high + FILLING_CLEARANCE
                   and span_hi + move > low - FILLING_CLEARANCE
                   for low, high in spans):
                note_rejection("rehost_overlaps_filling")
                continue
            # A wall long enough to take the leaf is not by itself a wall the
            # leaf can stand in: a wall crossing it, a radiator or a piece of
            # furniture may already hold that ground.  The box is grown by a
            # margin and any overlap at all refuses the position, because the
            # audit reads the leaf's own oriented body while this reads a box
            # in the wall's axes, and the two need not agree to the centimetre.
            # The leaf's body is offset from its own placement, and across the
            # wall that offset is what decides whether the leaf reaches past
            # the wall face into what stands against it.
            lo = np.array([float(leaf_origin[0]) + move + float(own_leaf.lo[0]),
                           _round(across + 0.05) + leaf_across_lo,
                           float(leaf_origin[2]) + lift + float(own_leaf.lo[2])],
                          dtype=float)
            if occupied_over_storeys(
                    scene, np.asarray(frame, dtype=float), lo - REHOST_MARGIN,
                    lo + size + REHOST_MARGIN, storeys, skip) > 0.0:
                note_rejection("rehost_element_collides")
                continue
            # The opening is not the leaf.  It cuts five centimetres past each
            # wall face and is wider and taller than the leaf it holds, so it
            # can stand outside the storey's footprint where the leaf does not,
            # which is what a window re-hosted in the 0.7.0 pilot did.  Both
            # bodies are therefore tested against the footprint of the storey
            # the assembly joins.
            hole_depth = _round(thickness + 0.1)
            hole_across_lo = min(float(own_hole.lo[1]), -hole_depth / 2.0)
            hole_across_hi = max(float(own_hole.hi[1]), hole_depth / 2.0)
            opening_lo = np.array(
                [float(opening_origin[0]) + move + float(own_hole.lo[0]),
                 _round(across) + hole_across_lo,
                 float(opening_origin[2]) + lift + float(own_hole.lo[2])],
                dtype=float)
            opening_size = np.array([float(own_hole.size[0]),
                                     hole_across_hi - hole_across_lo,
                                     float(own_hole.size[2])], dtype=float)
            if outside_footprint(scene, destination, frame, lo, size) or \
                    outside_footprint(scene, destination, frame, opening_lo,
                                      opening_size):
                note_rejection("rehost_outside_storey")
                continue
            # The opening and the leaf travel together, so the ground the
            # opening takes is tested for a collision as well as for the
            # footprint: the hole is wider and deeper than the leaf it holds.
            if occupied_over_storeys(
                    scene, np.asarray(frame, dtype=float),
                    opening_lo - REHOST_MARGIN,
                    opening_lo + opening_size + REHOST_MARGIN,
                    storeys, skip) > 0.0:
                note_rejection("rehost_opening_collides")
                continue
            along, shift = candidate, move
            break
        if along is None:
            continue
        guid = product.GlobalId
        return EditPlan(
            kind="rehost_filling", operation="update", family=family,
            calls=[Call("rehost_filling",
                        (guid, wall.GlobalId,
                         _round(float(opening_origin[0]) + shift), across,
                         _round(float(opening_origin[2]) + lift),
                         _round(float(leaf_origin[0]) + shift),
                         _round(across + 0.05),
                         _round(float(leaf_origin[2]) + lift),
                         _round(thickness + 0.1),
                         _round(thickness) if leaf_depth else None),
                        "re-point the opening at the other wall and re-place "
                        "the opening and the leaf in that wall's own frame")],
            target_guids=(guid,),
            touched_guids=(guid, host.GlobalId, wall.GlobalId,
                           opening.GlobalId),
            params={"host_from": scene.unique_name(host),
                    "host_from_guid": host.GlobalId,
                    "host_to": scene.unique_name(wall),
                    "host_to_guid": wall.GlobalId,
                    "along": along, "width": _round(width),
                    "height": _round(height),
                    "sill_above_base": _round(sill_above_base),
                    "magnitude": magnitude_bucket(scene, width)})
    return None


# --------------------------------------------------------- copy and array


def _copyable(scene: Scene, product) -> bool:
    if scene.family_of(product) not in ("wall", "slab", "column"):
        return False
    if scene.hosted_by(product) or stranded_dependants(scene, product):
        return False
    return scene.has_body(product) and scene.own_frame_box(product) is not None


def _copy_offsets(scene: Scene, product, rng) -> list[tuple[int, int, float]]:
    """Offsets a copy may stand at: an axis, a sign and a distance in metres."""
    world = scene.world_box(product)
    if world is None:
        return []
    out = []
    for axis in (0, 1):
        reach = max(float(world.size[axis]), 0.5)
        for factor in (1.2, 1.5, 2.0):
            out.append((axis, 1, _round(reach * factor)))
            out.append((axis, -1, _round(reach * factor)))
    rng.shuffle(out)
    return out


def plan_copy(scene: Scene, product, rng, task_id: str = "") -> Optional[EditPlan]:
    """Duplicate one element at a stated offset."""
    if not _copyable(scene, product):
        return None
    storey = scene.storey_of(product)
    matrix = scene.matrix(product)
    box = scene.own_frame_box(product)
    if storey is None or matrix is None or box is None:
        return None
    family = scene.family_of(product)
    for axis, sign, distance in _copy_offsets(scene, product, rng):
        offset = np.zeros(3)
        offset[axis] = sign * distance
        moved = np.array(matrix, dtype=float).copy()
        moved[:3, 3] = moved[:3, 3] + offset
        fault = transform_fault(scene, product, moved, storey,
                                [product.GlobalId], box)
        if fault is not None:
            note_rejection(fault)
            continue
        word, axis_word = AXIS_WORDS[(axis, sign)]
        guid = product.GlobalId
        new_guid = free_guid(scene, task_id, "copy")
        name = f"{RENAME_STEMS[family]} {rng.randint(100, 998)}"
        return EditPlan(
            kind="copy_element", operation="create", family=family,
            calls=[Call("copy_element",
                        (guid, new_guid, _round(offset[0]), _round(offset[1]),
                         0.0, name, free_guid(scene, task_id, "containment")),
                        "duplicate the element at a world-axis offset in metres"
                        )],
            target_guids=(new_guid,), created_guids=(new_guid,),
            touched_guids=(new_guid,),
            params={"source_guid": guid, "distance": _round(distance),
                    "direction": word, "axis_word": axis_word, "axis": axis,
                    "sign": sign, "name": name,
                    "entity_type": BOX_CLASS[family],
                    "magnitude": magnitude_bucket(scene, distance)})
    return None


def plan_array(scene: Scene, product, rng, task_id: str = "") -> Optional[EditPlan]:
    """Copy one element several times at a fixed spacing along one direction."""
    if not _copyable(scene, product):
        return None
    storey = scene.storey_of(product)
    matrix = scene.matrix(product)
    box = scene.own_frame_box(product)
    world = scene.world_box(product)
    if storey is None or matrix is None or box is None or world is None:
        return None
    family = scene.family_of(product)
    count = int(rng.choice(ARRAY_COUNTS))
    for axis, sign, distance in _copy_offsets(scene, product, rng):
        offset = np.zeros(3)
        offset[axis] = sign * distance
        ok = True
        for step in range(1, count + 1):
            moved = np.array(matrix, dtype=float).copy()
            moved[:3, 3] = moved[:3, 3] + offset * step
            fault = transform_fault(scene, product, moved, storey,
                                    [product.GlobalId], box)
            if fault is not None:
                note_rejection(fault)
                ok = False
                break
        if not ok:
            continue
        word, axis_word = AXIS_WORDS[(axis, sign)]
        guid = product.GlobalId
        new_guids = [free_guid(scene, task_id, f"copy{i}") for i in range(count)]
        stem = RENAME_STEMS[family]
        base = rng.randint(100, 900)
        names = [f"{stem} {base + i}" for i in range(count)]
        relations = [free_guid(scene, task_id, f"containment{i}")
                     for i in range(count)]
        return EditPlan(
            kind="array_elements", operation="create", family=family,
            calls=[Call("array_elements",
                        (guid, new_guids, _round(offset[0]), _round(offset[1]),
                         0.0, names, relations),
                        "copy the element the stated number of times at a "
                        "fixed spacing along a world axis")],
            target_guids=tuple(new_guids), created_guids=tuple(new_guids),
            touched_guids=tuple(new_guids),
            params={"source_guid": guid, "count": count,
                    "spacing": _round(distance), "direction": word,
                    "axis_word": axis_word, "axis": axis, "sign": sign,
                    "names": names, "entity_type": BOX_CLASS[family],
                    "magnitude": magnitude_bucket(scene, distance * count)})
    return None


# ------------------------------------------------------------ replacement


#: What a replacement puts in the place of what it takes out.
REPLACEMENT = {"window": "door", "door": "window"}


def plan_replace(scene: Scene, product, rng, task_id: str = ""
                 ) -> Optional[EditPlan]:
    """Put a door where a window stood, or a window where a door stood."""
    family = scene.family_of(product)
    replacement = REPLACEMENT.get(family or "")
    if replacement is None:
        return None
    opening = own_opening(product)
    host_guid = scene.host_of(product)
    host = scene.by_guid(host_guid) if host_guid else None
    if opening is None or host is None:
        note_rejection("replace_without_opening")
        return None
    frame = scene.matrix(host)
    body = scene.box_in_frame(host, frame)
    hole = scene.box_in_frame(opening, frame)
    if frame is None or body is None or hole is None:
        return None
    if scene.storey_of(host) is None:
        return None
    width, height, sill = CREATE_FILLING[replacement]
    width = _round(max(width, float(hole.size[0])))
    thickness = _round(float(body.size[1]))
    if not 0.05 <= thickness <= 1.5:
        return None
    if float(body.size[2]) < sill + height + FILLING_HEADROOM:
        note_rejection("replace_wall_too_short")
        return None
    along = _round(float(hole.lo[0]))
    if along + width > float(body.hi[0]) - 0.2 or along < float(body.lo[0]):
        note_rejection("replace_past_wall_end")
        return None
    others = []
    for other_guid in scene.hosted_by(host):
        if other_guid == product.GlobalId:
            continue
        span = _span_of(scene, other_guid, frame)
        if span is not None:
            others.append(span)
    if any(along < high + FILLING_CLEARANCE
           and along + width > low - FILLING_CLEARANCE for low, high in others):
        note_rejection("replace_overlaps_filling")
        return None
    across = _round(float(body.lo[1]) - 0.05)
    base = _round(float(body.lo[2]) + sill)
    # A door put where a window stood reaches ground the window left alone, so
    # the leaf's own box is measured against what already stands there.  The
    # bar is half the one the audit calls a collision, because the audit adds
    # up what every neighbour holds while this reads the largest one.
    leaf_lo = np.array([along, _round(across + 0.05), base], dtype=float)
    leaf_size = np.array([width, thickness, height], dtype=float)
    if occupied_over_storeys(
            scene, np.asarray(frame, dtype=float), leaf_lo, leaf_lo + leaf_size,
            (scene.storey_guid_of(host), scene.storey_guid_of(product)),
            [product.GlobalId, opening.GlobalId, host.GlobalId]
            ) > COLLISION_SHARE / 2.0:
        note_rejection("replace_element_collides")
        return None
    values = ()
    sample = scene.elements(replacement)
    if sample:
        values = predefined_types(sample[0])
    predefined = str(rng.choice(values)) if values else None
    # As for a created filling: the instruction never states the new door's or
    # window's predefined type, so it stays unset, and the draw is kept so the
    # rest of the task's draws are unchanged.
    predefined = None
    name = f"{RENAME_STEMS[replacement]} {rng.randint(100, 998)}"
    new_guid = free_guid(scene, task_id, "product")
    guid = product.GlobalId
    return EditPlan(
        kind="replace_filling", operation="create", family=replacement,
        calls=[Call("replace_filling",
                    (guid, FILLING_CLASS[replacement], new_guid, name,
                     host.GlobalId, free_guid(scene, task_id, "opening"),
                     free_guid(scene, task_id, "voids"),
                     free_guid(scene, task_id, "fills"),
                     free_guid(scene, task_id, "containment"),
                     along, across, base, width, height,
                     _round(thickness + 0.1), predefined,
                     _round(across + 0.05), thickness),
                    "take the element and its opening out of the wall, then cut "
                    "the new opening and fill it")],
        target_guids=(new_guid,), created_guids=(new_guid,),
        removed_guids=(guid, opening.GlobalId),
        touched_guids=(new_guid, host.GlobalId),
        params={"replaced_guid": guid, "replaced_family": family,
                "name": name, "width": width, "height": height, "sill": sill,
                "predefined_type": predefined,
                "entity_type": FILLING_CLASS[replacement],
                "host_guid": host.GlobalId,
                "magnitude": magnitude_bucket(scene, max(width, height))})


def _span_of(scene: Scene, guid: str, frame):
    element = scene.by_guid(guid)
    if element is None:
        return None
    box = scene.box_in_frame(element, frame)
    if box is None:
        return None
    return (float(box.lo[0]), float(box.hi[0]))


# -------------------------------------------------------------- the scopes


#: Which edit a batch may apply to every member of a set.
BATCH_KINDS = ("set_pset", "assign_material", "retype", "resize_extrusion",
               "delete")


def _batch_pset(scene: Scene, members, rng, task_id: str):
    family = scene.family_of(members[0])
    pset_name = PSET_OF_FAMILY.get(family or "")
    if pset_name is None:
        return None
    entries = list(PSET_PROPERTIES[pset_name])
    rng.shuffle(entries)
    for property_name, value_type, choices in entries:
        options = list(choices)
        rng.shuffle(options)
        for value in options:
            if all(_differs(own_property_value(scene, m, pset_name,
                                               property_name), value)
                   for m in members):
                calls = [Call("set_property_value",
                              (m.GlobalId, pset_name, property_name, value,
                               value_type,
                               free_guid(scene, task_id, f"pset{i}"),
                               free_guid(scene, task_id, f"psetrel{i}")),
                              "write the value on this member of the set")
                         for i, m in enumerate(members)]
                return ("set_pset", calls,
                        {"pset": pset_name, "property": property_name,
                         "property_word": PROPERTY_WORDS[property_name],
                         "value": value, "value_type": value_type})
    return None


def _batch_material(scene: Scene, members, rng, task_id: str):
    family = scene.family_of(members[0])
    if family not in MATERIAL_VOCABULARY:
        return None
    current = {_current_material_name(scene, m) for m in members}
    chosen = None
    for _attempt in range(6):
        candidate = material_choice(scene, family, None, rng)
        if candidate is not None and candidate[0] not in current:
            chosen = candidate
            break
    if chosen is None:
        return None
    name, source = chosen
    calls = [Call("assign_material",
                  (m.GlobalId, name, free_guid(scene, task_id, f"material{i}")),
                  "associate this member of the set with the material")
             for i, m in enumerate(members)]
    return ("assign_material", calls,
            {"material": name, "material_source": source})


def _batch_retype(scene: Scene, members, rng, task_id: str):
    values = predefined_types(members[0])
    if not values:
        return None
    current = {getattr(m, "PredefinedType", None) for m in members}
    options = [v for v in values if v not in current]
    if not options:
        return None
    value = str(rng.choice(options))
    calls = [Call("set_attribute", (m.GlobalId, "PredefinedType", value),
                  "set the predefined type of this member of the set")
             for m in members]
    return ("retype", calls, {"new": value})


def _lowest_safe_depth(scene: Scene, product) -> float:
    """How short an element may be made without stranding what it hosts.

    A wall shortened below the head of the door it carries leaves the door
    standing out of the top of it, which is the one thing a resize can do to a
    building that a person would refuse.
    """
    hosted = scene.hosted_by(product)
    if not hosted:
        return 0.0
    frame = scene.matrix(product)
    body = scene.box_in_frame(product, frame)
    if frame is None or body is None:
        return float("inf")
    highest = 0.0
    for guid in hosted:
        filling = scene.by_guid(guid)
        box = scene.box_in_frame(filling, frame) if filling is not None else None
        if box is None:
            return float("inf")
        highest = max(highest, float(box.hi[2] - body.lo[2]))
    return highest + FILLING_HEADROOM


def _batch_resize(scene: Scene, members, rng, task_id: str):
    depths = []
    floor = 0.0
    for member in members:
        solid = goldlib.sole_extrusion(scene.model, member)
        direction = scene.extrusion_axis(member)
        if solid is None or direction is None or abs(float(direction[2])) < 0.99:
            return None
        depth = float(solid.Depth) * scene.unit_scale
        if not 0.05 <= depth <= 30.0:
            return None
        depths.append(depth)
        floor = max(floor, _lowest_safe_depth(scene, member))
    if floor == float("inf"):
        note_rejection("batch_resize_filling_unmeasurable")
        return None
    new = _round(float(np.median(depths)) * float(rng.choice(RESIZE_FACTORS)))
    if not 0.05 <= new <= 30.0 or any(abs(new - d) < 0.05 for d in depths):
        return None
    if new < floor:
        # One member carries a door or a window the new height would leave
        # standing out of the top of it.
        note_rejection("batch_resize_strands_filling")
        return None
    family = scene.family_of(members[0])
    word = "thickness" if family == "slab" else "height"
    calls = [Call("set_extrusion_depth", (m.GlobalId, new),
                  f"set the {word} of this member of the set, in metres")
             for m in members]
    return ("resize_extrusion", calls, {"dimension": word, "new": new})


def _batch_delete(scene: Scene, members, rng, task_id: str):
    calls = []
    removed: list[str] = []
    for member in members:
        family = scene.family_of(member)
        if scene.hosted_by(member):
            return None
        opening = own_opening(member) if family in ("door", "window") else None
        if opening is not None and settings.SETTINGS.delete_filling_removes_opening:
            calls.append(Call("delete_filling_with_opening", (member.GlobalId,),
                              "remove this member of the set, the opening it "
                              "fills and the two relationships"))
            removed.extend([member.GlobalId, opening.GlobalId])
        else:
            calls.append(Call("delete_element", (member.GlobalId,),
                              "remove this member of the set and its dependent "
                              "relationships"))
            removed.append(member.GlobalId)
    return ("delete", calls, {"removed": removed})


BATCH_BUILDERS = {
    "set_pset": _batch_pset,
    "assign_material": _batch_material,
    "retype": _batch_retype,
    "resize_extrusion": _batch_resize,
    "delete": _batch_delete,
}


def plan_batch(scene: Scene, members: Sequence[Any], rng, task_id: str,
               pool: Sequence[str] = (), conditional: bool = False,
               operation: str = "update") -> Optional[EditPlan]:
    """One edit applied to every member of a set.

    The set has already been resolved from the instruction's own phrase, so the
    planner's job is to find an edit every member can carry and to write it once
    per member.  The pool the set was drawn from travels with the plan, because
    the funnel checks that the gold changed the members and nothing else in it.
    """
    if len(members) < 2:
        return None
    family = scene.family_of(members[0])
    if family is None or any(scene.family_of(m) != family for m in members):
        return None
    kinds = [k for k in BATCH_KINDS
             if (k == "delete") == (operation == "delete")]
    rng.shuffle(kinds)
    for kind in kinds:
        try:
            built = BATCH_BUILDERS[kind](scene, list(members), rng, task_id)
        except Exception:
            built = None
        if built is None:
            continue
        name, calls, params = built
        guids = tuple(m.GlobalId for m in members)
        removed = tuple(params.pop("removed", ())) if name == "delete" else ()
        plan = EditPlan(
            kind=name, operation=operation, family=family, calls=calls,
            target_guids=guids, touched_guids=guids, removed_guids=removed,
            params=dict(params, scope="batch", n_members=len(members),
                        batch_members=list(guids), batch_pool=list(pool),
                        magnitude=params.get("magnitude", "small"),
                        families=["scope.batch"]
                        + (["scope.conditional"] if conditional else [])))
        return plan
    return None


#: The operations 0.6.0 adds to the update family, and which families each one
#: applies to.  The registry holds the weights; this maps a tag to its planner.
NEW_UPDATE_PLANNERS: dict[str, tuple] = {
    "op.update.rotate": (plan_rotate, ("wall", "slab", "column", "space")),
    "op.update.mirror": (plan_mirror, ("wall", "slab", "column", "space")),
    "op.update.pset": (plan_set_pset,
                       ("wall", "slab", "column", "door", "window")),
    "op.update.material": (plan_assign_material,
                           ("wall", "slab", "column", "door", "window")),
    "op.update.type_object": (plan_assign_type, FAMILIES),
    "op.update.restorey": (plan_move_to_storey,
                           ("wall", "slab", "column", "space")),
    "op.update.rehost": (plan_rehost, ("door", "window")),
}

#: The operations that add elements rather than change one.  A copy and an
#: array duplicate an element of the cell's own family; a replacement puts an
#: element of that family where one of the other kind of filling stood.
NEW_CREATE_PLANNERS: dict[str, tuple] = {
    "op.copy": (plan_copy, ("wall", "slab", "column")),
    "op.array": (plan_array, ("wall", "slab", "column")),
    "op.replace": (plan_replace, ("door", "window")),
}


def new_create_source_family(family: str) -> str:
    """Which family a create task of ``family`` draws its source element from.

    A copy and an array duplicate an element of the same family.  A replacement
    puts a door where a window stood and a window where a door stood, so its
    source is the other kind of filling.
    """
    return REPLACEMENT.get(family, family)


def plan_create_new(scene: Scene, family: str, product, rng, task_id: str
                    ) -> Optional[EditPlan]:
    """One of the create-side operations 0.6.0 adds, for a drawn source element."""
    source_family = scene.family_of(product)
    if source_family is None:
        return None
    for entry in families.members("op.create.new", rng):
        planner, allowed = NEW_CREATE_PLANNERS.get(entry.tag, (None, ()))
        if planner is None or source_family not in allowed:
            continue
        if entry.tag == "op.replace" and REPLACEMENT.get(source_family) != family:
            continue
        if entry.tag != "op.replace" and source_family != family:
            continue
        try:
            plan = planner(scene, product, rng, task_id)
        except Exception:
            plan = None
        if plan is not None:
            return plan
    return None
