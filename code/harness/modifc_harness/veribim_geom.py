"""veribim_geom - geometry and IFC-schema helpers for the editing sandbox.

The module is meant to be injected into the sandbox namespace next to ``ifc``,
so a model can write

    import veribim_geom as vg
    wall = ifc.by_guid('0wT1y1b2f0JPu14Ydwo8PP')
    vg.add_filling(wall, 'IfcDoor', 'Doorset 845', width=0.9, height=2.1,
                   along=3.21, sill=0.0)

and get a door that is placed, sized, voided, filled and contained the way the
benchmark's own generator writes one.

Three conventions are fixed here rather than left to the caller, because the
failure reading of the val-500 create tasks showed they are what the model
guesses wrong:

* **Frames.** A door or a window is placed relative to its host wall's
  ``ObjectPlacement``; a box element is placed relative to its storey's.  The
  caller never writes a world coordinate into a placement.
* **The leaf across the wall.** The leaf's near face sits on the wall body's
  near face and the leaf is exactly as deep as the wall; the opening starts
  50 mm outside that face and is 100 mm deeper than the wall, so it cuts past
  both faces.  Both numbers are read from the host wall's own body, never
  assumed.  This reproduces the generator on all 91 filling tasks of the
  val-500 split.
* **Units.** Every length an argument carries is in metres.  The file's own
  length unit is read here and applied here.

Every function takes IFC entities, not identifiers, and finds the model from
the entity, so there is no model argument to get wrong.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np

import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.geom
import ifcopenshell.guid
import ifcopenshell.util.element
import ifcopenshell.util.placement
import ifcopenshell.util.unit

__all__ = [
    "unit_scale", "to_file_units", "to_metres",
    "world_box", "frame_of", "box_in_frame", "wall_box", "filling_slot",
    "storey_of", "host_wall_of", "opening_of",
    "add_filling", "replace_filling", "delete_filling",
    "add_box_element", "copy_element", "array_elements",
    "add_space_boundary", "connect_elements",
    "origin_in_frame", "spot_on_top_of", "spot_beside_wall_in_space",
    "place_in_structure",
]

#: Opening clearance past each wall face, in metres, as the generator cuts it.
OPENING_CLEARANCE = 0.05


# --------------------------------------------------------------- units


def _file(entity) -> ifcopenshell.file:
    return entity.wrapped_data.file


def unit_scale(model_or_entity) -> float:
    """Metres per file length unit (1.0 for metres, 0.001 for millimetres)."""
    model = (model_or_entity if isinstance(model_or_entity, ifcopenshell.file)
             else _file(model_or_entity))
    value = ifcopenshell.util.unit.calculate_unit_scale(model)
    return float(value) if value else 1.0


def to_file_units(metres: float, model_or_entity) -> float:
    """A length in metres, written in the file's own length unit."""
    return float(metres) / unit_scale(model_or_entity)


def to_metres(value: float, model_or_entity) -> float:
    """A length in the file's own unit, written in metres."""
    return float(value) * unit_scale(model_or_entity)


# ------------------------------------------------------------ geometry


_SETTINGS: dict[bool, object] = {}


def _settings(disable_openings: bool):
    settings = _SETTINGS.get(disable_openings)
    if settings is None:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        settings.set("weld-vertices", True)
        if disable_openings:
            settings.set("disable-opening-subtractions", True)
        _SETTINGS[disable_openings] = settings
    return settings


def _vertices(product, disable_openings: bool = False):
    """World-frame vertices of a product's body, in metres, or None."""
    if not getattr(product, "Representation", None):
        return None
    try:
        shape = ifcopenshell.geom.create_shape(_settings(disable_openings), product)
    except Exception:
        return None
    points = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    return points if points.size else None


def world_box(product, disable_openings: bool = False):
    """The product's axis-aligned box in world metres, as ``(lo, hi)``.

    ``disable_openings`` reads the raw solid, before the openings cut into it,
    which is what a wall's thickness and length have to be measured on.
    """
    points = _vertices(product, disable_openings)
    if points is None:
        return None
    return points.min(axis=0), points.max(axis=0)


def frame_of(product) -> np.ndarray:
    """The product's placement as a 4x4 matrix whose translation is in metres."""
    matrix = np.array(ifcopenshell.util.placement.get_local_placement(
        product.ObjectPlacement), dtype=float)
    matrix[:3, 3] *= unit_scale(product)
    return matrix


def box_in_frame(product, frame_product, disable_openings: bool = False):
    """``product``'s box in ``frame_product``'s own coordinate system, in metres.

    Use it to read where something stands as the element that hosts it sees it:
    a door's position along its wall, a slab's footprint on its storey.
    """
    points = _vertices(product, disable_openings)
    if points is None:
        return None
    inverse = np.linalg.inv(frame_of(frame_product))
    local = (inverse[:3, :3] @ points.T).T + inverse[:3, 3]
    return local.min(axis=0), local.max(axis=0)


def wall_box(wall) -> dict:
    """The wall's own body, measured in the wall's placement frame, in metres.

    The keys are the ones a filling needs: ``start`` and ``end`` along the wall,
    ``near`` and ``far`` across it, ``base`` and ``top``, and the derived
    ``length``, ``thickness`` and ``height``.  A wall whose body cannot be
    meshed returns ``None``.
    """
    box = box_in_frame(wall, wall, disable_openings=True)
    if box is None:
        box = box_in_frame(wall, wall)
    if box is None:
        return None
    lo, hi = box
    return {"start": float(lo[0]), "end": float(hi[0]),
            "near": float(lo[1]), "far": float(hi[1]),
            "base": float(lo[2]), "top": float(hi[2]),
            "length": float(hi[0] - lo[0]),
            "thickness": float(hi[1] - lo[1]),
            "height": float(hi[2] - lo[2])}


# --------------------------------------------------------- relationships


def storey_of(product):
    """The building storey the product is contained in, or None."""
    for relation in getattr(product, "ContainedInStructure", ()) or ():
        structure = relation.RelatingStructure
        while structure is not None:
            if structure.is_a("IfcBuildingStorey"):
                return structure
            parents = getattr(structure, "Decomposes", ()) or ()
            structure = parents[0].RelatingObject if parents else None
    for relation in getattr(product, "Decomposes", ()) or ():
        parent = relation.RelatingObject
        if parent is not None and parent.is_a("IfcBuildingStorey"):
            return parent
    return None


def opening_of(filling):
    """The opening a door or window fills, or None."""
    for relation in getattr(filling, "FillsVoids", ()) or ():
        return relation.RelatingOpeningElement
    return None


def host_wall_of(filling):
    """The wall a door or window is hosted in, or None."""
    opening = opening_of(filling)
    for relation in (getattr(opening, "VoidsElements", ()) or ()) if opening else ():
        return relation.RelatingBuildingElement
    return None


def filling_slot(filling) -> dict:
    """Where an existing door or window sits in its host wall, in metres.

    ``along`` is the near edge of the opening measured along the wall's own x
    axis, ``sill`` is its base above the wall's base, and ``width`` and
    ``height`` size it.  These are the numbers "at the same position along the
    wall" refers to, and they are read from the opening rather than from the
    leaf, because the opening is what the wall was cut to.
    """
    host = host_wall_of(filling)
    opening = opening_of(filling)
    if host is None or opening is None:
        return None
    hole = box_in_frame(opening, host)
    wall = wall_box(host)
    if hole is None or wall is None:
        return None
    lo, hi = hole
    return {"host": host, "opening": opening,
            "along": float(lo[0]), "sill": float(lo[2] - wall["base"]),
            "width": float(hi[0] - lo[0]), "height": float(hi[2] - lo[2])}


def _owner_history(model):
    histories = model.by_type("IfcOwnerHistory")
    return sorted(histories, key=lambda h: h.id())[0] if histories else None


def _context(model, like=None):
    """The representation context created geometry is written into."""
    for product in ([like] if like is not None else []):
        shape = getattr(product, "Representation", None)
        for representation in (shape.Representations or ()) if shape else ():
            if representation.RepresentationIdentifier == "Body" \
                    and representation.ContextOfItems is not None:
                return representation.ContextOfItems
    for context in model.by_type("IfcGeometricRepresentationSubContext"):
        if context.ContextIdentifier == "Body":
            return context
    roots = [c for c in model.by_type("IfcGeometricRepresentationContext")
             if not c.is_a("IfcGeometricRepresentationSubContext")
             and (c.CoordinateSpaceDimension or 3) == 3]
    for context in roots:
        if context.ContextType == "Model":
            return context
    if roots:
        return roots[0]
    raise ValueError("model has no three-dimensional representation context")


def _box_shape(model, context, length: float, width: float, height: float,
               scale: float):
    """A rectangular extrusion, its base corner on the placement origin."""
    profile = model.create_entity(
        "IfcRectangleProfileDef", ProfileType="AREA", ProfileName=None,
        Position=model.create_entity(
            "IfcAxis2Placement2D",
            Location=model.create_entity(
                "IfcCartesianPoint",
                Coordinates=(length / 2.0 / scale, width / 2.0 / scale)),
            RefDirection=None),
        XDim=length / scale, YDim=width / scale)
    solid = model.create_entity(
        "IfcExtrudedAreaSolid", SweptArea=profile,
        Position=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0)),
            Axis=None, RefDirection=None),
        ExtrudedDirection=model.create_entity("IfcDirection",
                                              DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=height / scale)
    representation = model.create_entity(
        "IfcShapeRepresentation", ContextOfItems=context,
        RepresentationIdentifier="Body", RepresentationType="SweptSolid",
        Items=[solid])
    return model.create_entity("IfcProductDefinitionShape", Name=None,
                               Description=None, Representations=[representation])


def _placement(model, parent, x: float, y: float, z: float, scale: float):
    return model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=parent,
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint",
                Coordinates=(x / scale, y / scale, z / scale)),
            Axis=None, RefDirection=None))


def _contain(model, storey, product) -> None:
    for relation in storey.ContainsElements or ():
        relation.RelatedElements = tuple(relation.RelatedElements) + (product,)
        return
    model.create_entity(
        "IfcRelContainedInSpatialStructure", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=None, Description=None,
        RelatedElements=[product], RelatingStructure=storey)


def _aggregate(model, storey, product) -> None:
    for relation in storey.IsDecomposedBy or ():
        if relation.is_a("IfcRelAggregates"):
            relation.RelatedObjects = tuple(relation.RelatedObjects) + (product,)
            return
    model.create_entity(
        "IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=None, Description=None,
        RelatingObject=storey, RelatedObjects=[product])


def place_in_structure(product, storey) -> None:
    """Put a product into its storey: aggregated for a space, contained else."""
    model = _file(product)
    forget_geometry(model)
    if product.is_a("IfcSpace"):
        _aggregate(model, storey, product)
    else:
        _contain(model, storey, product)


# ------------------------------------------------- where a new element goes


def origin_in_frame(product, frame_product):
    """The product's placement origin, read in another product's frame, metres.

    A spatial instruction that says "6 m to the east of the slab named X" is
    measured from X's placement origin expressed in the storey's own system,
    which is what this returns.
    """
    matrix = frame_of(product)
    inverse = np.linalg.inv(frame_of(frame_product))
    point = inverse[:3, :3] @ matrix[:3, 3] + inverse[:3, 3]
    return float(point[0]), float(point[1]), float(point[2])


def spot_on_top_of(reference):
    """Where a new element stands to sit on a reference element's top face.

    Returns ``(lo, size)`` in world metres: the lowest corner over the
    reference's own footprint and at its top, and the footprint's plan size.
    The caller states the new element's own height.
    """
    box = world_box(reference)
    if box is None:
        return None
    lo, hi = box
    return ((float(lo[0]), float(lo[1]), float(hi[2])),
            (float(hi[0] - lo[0]), float(hi[1] - lo[1])))


def spot_beside_wall_in_space(wall, space, length: float, width: float):
    """Where a new element stands against a wall, inside a space, touching it.

    The wall's short plan axis is the one the element stands off; the element's
    near face sits on the wall face that looks into the space, the element is
    centred on the wall along the wall's long plan axis, and its base is the
    space's own floor.  ``length`` runs along the wall and ``width`` across it.
    Returns the lowest corner in world metres.
    """
    wall_b = world_box(wall)
    room = world_box(space)
    if wall_b is None or room is None:
        return None
    size = wall_b[1] - wall_b[0]
    across = int(np.argmin(size[:2]))
    along = 1 - across
    centre = (room[0] + room[1]) / 2.0
    inward = 1.0 if float(centre[across]) > float(wall_b[1][across]) - \
        float(size[across]) / 2.0 else -1.0
    face = float(wall_b[1][across]) if inward > 0 else float(wall_b[0][across])
    lo = [0.0, 0.0, float(room[0][2])]
    lo[across] = face if inward > 0 else face - float(width)
    lo[along] = 0.5 * (float(wall_b[0][along]) + float(wall_b[1][along])) \
        - float(length) / 2.0
    return (float(lo[0]), float(lo[1]), float(lo[2]))


# ------------------------------------------------------- doors and windows


def add_filling(host_wall, ifc_class: str, name: Optional[str], width: float,
                height: float, along: float, sill: float = 0.0,
                predefined_type: Optional[str] = None,
                along_is_centre: bool = False, depth: Optional[float] = None):
    """Cut an opening in a wall and fill it with a door or a window.

    ``along`` is the distance along the wall's own x axis, in metres, to the
    near edge of the leaf; pass ``along_is_centre=True`` when the instruction
    gives the position of the middle of the leaf instead, and half the width is
    taken off here.  ``sill`` is the height of the leaf's base above the wall's
    base.  ``width`` and ``height`` size the leaf.

    What the function guarantees, so the caller never states it:

    * the opening and the leaf both hang from the wall's own placement, so they
      travel with the wall;
    * the leaf's near face sits on the wall's near face and the leaf is as deep
      as the wall, unless ``depth`` says otherwise;
    * the opening starts 50 mm outside the near face and is 100 mm deeper than
      the wall, so it cuts past both faces;
    * an ``IfcRelVoidsElement`` ties the opening to the wall, an
      ``IfcRelFillsElement`` ties the leaf to the opening, and the leaf joins
      the wall's storey;
    * ``OverallWidth`` and ``OverallHeight`` are written in file units.

    Returns the created leaf.
    """
    model = _file(host_wall)
    scale = unit_scale(model)
    history = _owner_history(model)
    wall = wall_box(host_wall)
    forget_geometry(model)
    if wall is None:
        raise ValueError("the host wall has no body that can be measured")
    storey = storey_of(host_wall)
    if storey is None:
        raise ValueError("the host wall is not contained in a storey")

    x = float(along) - (float(width) / 2.0 if along_is_centre else 0.0)
    z = wall["base"] + float(sill)
    leaf_depth = wall["thickness"] if depth is None else float(depth)
    leaf_across = wall["near"]
    hole_across = wall["near"] - OPENING_CLEARANCE
    hole_depth = wall["thickness"] + 2 * OPENING_CLEARANCE

    opening = model.create_entity("IfcOpeningElement",
                                  GlobalId=ifcopenshell.guid.new(),
                                  OwnerHistory=history, Name="Opening",
                                  Description=None)
    opening.ObjectPlacement = _placement(model, host_wall.ObjectPlacement,
                                         x, hole_across, z, scale)
    opening.Representation = _box_shape(model, _context(model, host_wall),
                                        float(width), hole_depth, float(height),
                                        scale)
    if hasattr(opening, "PredefinedType"):
        opening.PredefinedType = "OPENING"
    model.create_entity("IfcRelVoidsElement", GlobalId=ifcopenshell.guid.new(),
                        OwnerHistory=history, Name=None, Description=None,
                        RelatingBuildingElement=host_wall,
                        RelatedOpeningElement=opening)

    leaf = model.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(),
                               OwnerHistory=history, Name=name, Description=None)
    leaf.ObjectPlacement = _placement(model, host_wall.ObjectPlacement,
                                      x, leaf_across, z, scale)
    leaf.Representation = _box_shape(model, _context(model, host_wall),
                                     float(width), leaf_depth, float(height),
                                     scale)
    leaf.OverallHeight = float(height) / scale
    leaf.OverallWidth = float(width) / scale
    if predefined_type is not None and hasattr(leaf, "PredefinedType"):
        leaf.PredefinedType = predefined_type
    model.create_entity("IfcRelFillsElement", GlobalId=ifcopenshell.guid.new(),
                        OwnerHistory=history, Name=None, Description=None,
                        RelatingOpeningElement=opening,
                        RelatedBuildingElement=leaf)
    _contain(model, storey, leaf)
    return leaf


def delete_filling(filling) -> None:
    """Remove a door or a window together with the opening it filled.

    An element that fills no opening is not a filling, and an instruction that
    says "delete it" means the same thing whichever class it names, so such a
    call is handed to ``delete_element`` instead of failing.
    """
    if not (getattr(filling, "FillsVoids", ()) or ()):
        delete_element(filling)
        return
    model = _file(filling)
    forget_geometry(model)
    before = {h.id() for h in model.by_type("IfcOwnerHistory")}
    spare = {r.id() for r in _empty_relations(model)}
    for relation in list(getattr(filling, "FillsVoids", ()) or ()):
        opening = relation.RelatingOpeningElement
        model.remove(relation)
        if opening is None:
            continue
        for voids in list(getattr(opening, "VoidsElements", ()) or ()):
            model.remove(voids)
        _remove_product(model, opening)
    _remove_product(model, filling)
    _sweep_empty_relations(model, spare)
    _freeze_new_histories(model, before)


def _freeze_new_histories(model, before: set) -> None:
    """Drop the ownership records a removal stamped on the file.

    Taking a product out unassigns it from the types and materials it shared,
    and each unassignment writes a fresh ``IfcOwnerHistory`` carrying the
    current time.  A model that already has one keeps only that one, so the
    edit adds no ownership record at all and the same edit written twice gives
    the same file.
    """
    created = [h for h in model.by_type("IfcOwnerHistory") if h.id() not in before]
    if not created:
        return
    existing = sorted((h for h in model.by_type("IfcOwnerHistory")
                       if h.id() in before), key=lambda h: h.id())
    stamps = [h.CreationDate for h in existing if h.CreationDate is not None]
    reference = min(stamps) if stamps else 0
    for history in created:
        history.CreationDate = reference
        history.LastModifiedDate = reference
    canonical = existing[0] if existing else min(created, key=lambda h: h.id())
    for history in sorted(created, key=lambda h: h.id()):
        if history.id() == canonical.id():
            continue
        for relation in list(model.get_inverse(history)):
            for index, value in enumerate(relation):
                if value == history:
                    relation[index] = canonical
        model.remove(history)


def _remove_product(model, product) -> None:
    """Take a product out of the model, and out of everything that lists it.

    The product's placement, its geometry, its property sets and every
    relationship that names it go with it, which is what
    ``ifcopenshell.api.root.remove_product`` does; a relationship that lists
    several products keeps the others.  The ownership records the removal
    stamps on the file are taken off afterwards, so the same removal written
    twice gives the same file.  This leaves the model the benchmark's own
    delete leaves, entity for entity.
    """
    before = {h.id() for h in model.by_type("IfcOwnerHistory")}
    ifcopenshell.api.root.remove_product(model, product=product)
    _freeze_new_histories(model, before)


def replace_filling(old_filling, ifc_class: str, name: Optional[str],
                    width: float, height: float, sill: float = 0.0,
                    predefined_type: Optional[str] = None):
    """Swap a door for a window, or a window for a door, in the same wall.

    The old element and the opening it filled are removed together, which
    leaves the wall whole, and a new opening is cut at the position the old one
    held.  "At the same position along the wall" is read from the old opening,
    so the caller only states the new element's size and sill.  The new leaf is
    never narrower than the hole it inherits.

    Returns the created leaf.
    """
    slot = filling_slot(old_filling)
    if slot is None:
        raise ValueError("the element does not fill an opening in a wall")
    host = slot["host"]
    along = slot["along"]
    effective_width = max(float(width), slot["width"])
    delete_filling(old_filling)
    return add_filling(host, ifc_class, name, effective_width, float(height),
                       along, float(sill), predefined_type)


# --------------------------------------------------------- box elements


def add_box_element(storey, ifc_class: str, name: Optional[str],
                    x: float, y: float, z: float,
                    dx: float, dy: float, dz: float,
                    predefined_type: Optional[str] = None,
                    frame: str = "storey", like=None,
                    long_name: Optional[str] = None):
    """Create a box-shaped element on a storey.

    ``x``, ``y`` and ``z`` are the element's lowest corner and ``dx``, ``dy``
    and ``dz`` its size, all in metres.  ``frame`` says which coordinates the
    corner is given in: ``"storey"`` for the storey's own system, which is what
    an instruction saying "in that storey's own coordinates" means, or
    ``"world"`` for the building's, which is what a bare coordinate means.  A
    world point is converted into the storey's system here, so a storey that
    sits at an elevation or at a plan offset no longer moves the element.

    The element is placed relative to the storey and is contained in it; a
    space is aggregated under it instead.  Returns the created element.
    """
    model = _file(storey)
    scale = unit_scale(model)
    forget_geometry(model)
    if frame == "world":
        matrix = frame_of(storey)
        local = np.linalg.inv(matrix[:3, :3]) @ (
            np.array([x, y, z], dtype=float) - matrix[:3, 3])
        x, y, z = (float(local[0]), float(local[1]), float(local[2]))
    elif frame != "storey":
        raise ValueError("frame is 'storey' or 'world'")
    product = model.create_entity(ifc_class, GlobalId=ifcopenshell.guid.new(),
                                  OwnerHistory=_owner_history(model), Name=name,
                                  Description=None)
    product.ObjectPlacement = _placement(model, storey.ObjectPlacement,
                                         float(x), float(y), float(z), scale)
    product.Representation = _box_shape(model, _context(model, like),
                                        float(dx), float(dy), float(dz), scale)
    if predefined_type is not None and hasattr(product, "PredefinedType"):
        product.PredefinedType = predefined_type
    if product.is_a("IfcSpace"):
        if hasattr(product, "LongName"):
            product.LongName = long_name
        if hasattr(product, "CompositionType"):
            product.CompositionType = "ELEMENT"
        if hasattr(product, "InteriorOrExteriorSpace"):
            product.InteriorOrExteriorSpace = "INTERNAL"
    place_in_structure(product, storey)
    return product


# ------------------------------------------------------- copies and arrays


#: Entities a copy shares with its original rather than duplicating.
_SHARED = ("IfcGeometricRepresentationContext",
           "IfcGeometricRepresentationSubContext", "IfcRepresentationContext",
           "IfcLocalPlacement", "IfcOwnerHistory", "IfcMaterial",
           "IfcMaterialLayerSet", "IfcMaterialLayerSetUsage", "IfcMaterialLayer",
           "IfcPresentationLayerAssignment", "IfcStyledItem")


def copy_element(product, dx: float, dy: float, dz: float,
                 name: Optional[str] = None):
    """Duplicate one element at a world-axis offset given in metres.

    The copy keeps the original's class, attributes, body and orientation, and
    it hangs from the same parent placement and joins the same storey, so the
    model holds it exactly as it holds the element it came from.  The offset is
    stated along the world axes and is rotated into the parent's system here,
    so a copy "0.6 m to the east" moves east whatever the parent's rotation.
    """
    model = _file(product)
    scale = unit_scale(model)
    forget_geometry(model)
    copy = model.create_entity(product.is_a(), GlobalId=ifcopenshell.guid.new(),
                               OwnerHistory=_owner_history(model))
    for attribute in product.wrapped_data.declaration().as_entity().all_attributes():
        field = attribute.name()
        if field in ("GlobalId", "OwnerHistory", "ObjectPlacement",
                     "Representation"):
            continue
        try:
            setattr(copy, field, getattr(product, field))
        except Exception:
            continue
    if name is not None:
        copy.Name = name
    placement = product.ObjectPlacement
    parent = placement.PlacementRelTo if placement is not None \
        and placement.is_a("IfcLocalPlacement") else None
    origin = np.array(ifcopenshell.util.placement.get_local_placement(placement),
                      dtype=float)
    parent_matrix = np.identity(4) if parent is None else np.array(
        ifcopenshell.util.placement.get_local_placement(parent), dtype=float)
    local = np.linalg.inv(parent_matrix) @ origin
    offset = np.linalg.inv(parent_matrix[:3, :3]) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    axis = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity(
            "IfcCartesianPoint",
            Coordinates=tuple(float(v) for v in local[:3, 3] + offset)),
        Axis=model.create_entity(
            "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 2])),
        RefDirection=model.create_entity(
            "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 0])))
    copy.ObjectPlacement = model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=parent, RelativePlacement=axis)
    if product.Representation is not None:
        copy.Representation = ifcopenshell.util.element.copy_deep(
            model, product.Representation, exclude=list(_SHARED))
    storey = storey_of(product)
    if storey is not None:
        place_in_structure(copy, storey)
    return copy


def array_elements(product, count: int, dx: float, dy: float, dz: float,
                   names: Sequence[Optional[str]] = ()):
    """Copy one element ``count`` times at a fixed spacing.

    The nth copy stands n times ``(dx, dy, dz)`` from the original, in world
    metres, so the copies form an evenly spaced row and the first copy is one
    spacing away rather than on top of the original.  Returns the copies in
    order.
    """
    made = []
    for index in range(1, int(count) + 1):
        name = names[index - 1] if index - 1 < len(names) else None
        made.append(copy_element(product, float(dx) * index, float(dy) * index,
                                 float(dz) * index, name))
    return made


# --------------------------------------------------------- relationships


def add_space_boundary(space, element, physical_or_virtual: str = "PHYSICAL",
                       internal_or_external: str = "INTERNAL",
                       name: Optional[str] = None):
    """Record that one element bounds one space, as an ``IfcRelSpaceBoundary``."""
    model = _file(space)
    return model.create_entity(
        "IfcRelSpaceBoundary", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=name, Description=None,
        RelatingSpace=space, RelatedBuildingElement=element,
        ConnectionGeometry=None, PhysicalOrVirtualBoundary=physical_or_virtual,
        InternalOrExternalBoundary=internal_or_external)


def connect_elements(relating, related, name: Optional[str] = None):
    """Record that two elements are connected, as an ``IfcRelConnectsElements``."""
    model = _file(relating)
    return model.create_entity(
        "IfcRelConnectsElements", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=name, Description=None,
        ConnectionGeometry=None, RelatingElement=relating, RelatedElement=related)


# ================================================================= lookups
#
# Finding the element an instruction points at.
#
# An instruction names an element by where it stands: "the wall on storey S
# that stands about 24.1 m east of the column named C", "the slab furthest
# north", "the first window from the south along the wall W".  The functions
# below turn each of those sentences into one element.  Every argument is
# something the sentence itself carries: an element the reader has already
# found by name, a class, a storey, a direction word, a stated distance.  The
# rules the sentence leaves out - how wide a band counts as "about 24.1 m",
# how far off the line a neighbour may sit - are fixed here, once, so the
# caller never has to invent a tolerance.
#
# Each function returns one element and raises ``LookupError`` with the
# nearest candidates when the sentence matches nothing.


#: Direction words an instruction may use, and the world axis and sign each
#: one means.  Both the plain word and the signed-axis form are accepted,
#: because the instructions write them together ("about 24.1 m east (+X)").
_DIRECTIONS = {
    "east": (0, 1), "+x": (0, 1), "x+": (0, 1),
    "west": (0, -1), "-x": (0, -1), "x-": (0, -1),
    "north": (1, 1), "+y": (1, 1), "y+": (1, 1),
    "south": (1, -1), "-y": (1, -1), "y-": (1, -1),
    "up": (2, 1), "above": (2, 1), "+z": (2, 1), "z+": (2, 1),
    "down": (2, -1), "below": (2, -1), "-z": (2, -1), "z-": (2, -1),
}

#: How wide the band around a stated distance is: a tenth of the distance, and
#: never less than a quarter of a metre.  A sentence that says "about 24.1 m"
#: means the reader measures and accepts what is near enough, and this is what
#: near enough is.
_BAND_SHARE = 0.10
_BAND_FLOOR = 0.25

#: How far from either end of a run an element has to stand to count as being
#: between the two elements that end it: a twentieth of the run.  An element
#: standing on top of one of the two is not between them.
_END_CLEARANCE = 0.05


def _direction(word) -> tuple:
    """The world axis and sign one direction word means."""
    key = str(word).strip().lower().replace(" ", "")
    if key in _DIRECTIONS:
        return _DIRECTIONS[key]
    raise ValueError(
        "direction is one of east, west, north, south, up, down "
        "or +X, -X, +Y, -Y, +Z, -Z, not %r" % (word,))


# ------------------------------------------------------ geometry, cached

#: What has already been read off each open model: the world box of every
#: element a lookup has measured, and the storey each product sits on.  Meshing
#: an element costs milliseconds and a lookup over a storey measures every
#: element of a class, so the same box is asked for many times in one call.
#: Every function in this module that changes the model drops what was read
#: from it, so a lookup after an edit reads the model as it now stands.
_READ: dict = {}


def forget_geometry(model_or_entity=None) -> None:
    """Drop what was read off a model, for one model or for all of them.

    Call it after changing a model through plain ifcopenshell code rather than
    through this module, so a later lookup reads the model again.
    """
    if model_or_entity is None:
        _READ.clear()
        return
    model = (model_or_entity if isinstance(model_or_entity, ifcopenshell.file)
             else _file(model_or_entity))
    _READ.pop(id(model), None)


def _read_state(model) -> dict:
    entry = _READ.get(id(model))
    if entry is None or entry[0] is not model:
        entry = (model, {"boxes": {}, "storeys": None})
        _READ[id(model)] = entry
    return entry[1]


def _cached_box(product):
    """The product's world box, measured once per model and kept."""
    boxes = _read_state(_file(product))["boxes"]
    guid = product.GlobalId
    if guid not in boxes:
        boxes[guid] = world_box(product)
    return boxes[guid]


def origin_point(product):
    """The product's placement origin in world metres, as a numpy array.

    This is where the model files the element, not where its body sits.  A
    wall's origin is at one end of it, so an instruction that measures from
    element to element along an axis is read from origins and an instruction
    that says "nearest" or "between" is read from body centres.
    """
    placement = getattr(product, "ObjectPlacement", None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale(product)


def centre(product):
    """The centre of the product's body in world metres, as a numpy array.

    Falls back to the placement origin for an element whose body cannot be
    measured, which is what a reader looking at the model would do.
    """
    box = _cached_box(product)
    if box is None:
        return origin_point(product)
    return (box[0] + box[1]) / 2.0


def plan_length(product):
    """The longer of the product's two plan sides, in metres.

    This is the length an instruction means by "longer than 6.00 m" for a wall
    or a slab, whichever way the element runs.
    """
    box = _cached_box(product)
    if box is None:
        return None
    size = box[1] - box[0]
    return float(max(size[0], size[1]))


def height(product):
    """How tall the product's body is, in metres."""
    box = _cached_box(product)
    if box is None:
        return None
    return float(box[1][2] - box[0][2])


def overall_width(product):
    """A door's or a window's ``OverallWidth``, in metres, or None."""
    value = getattr(product, "OverallWidth", None)
    if value is None:
        return None
    return float(value) * unit_scale(product)


#: What each measured word in a "only the walls longer than 6.00 m" phrase
#: measures, so the caller writes the word the sentence uses.
_MEASURES = {"plan_length": plan_length, "height": height,
             "overall_width": overall_width}


def measure(product, name: str):
    """One measurement of an element in metres, by the name the phrase uses.

    ``plan_length`` is the longer plan side, ``height`` the body height and
    ``overall_width`` a filling's stated width.
    """
    reader = _MEASURES.get(str(name))
    if reader is None:
        raise ValueError("measure is one of %s, not %r"
                         % (", ".join(sorted(_MEASURES)), name))
    return reader(product)


# --------------------------------------------------- containment, by storey


def _storey_ancestor(structure):
    seen = 0
    while structure is not None and seen < 8:
        if structure.is_a("IfcBuildingStorey"):
            return structure
        parents = getattr(structure, "Decomposes", ()) or ()
        structure = parents[0].RelatingObject if parents else None
        seen += 1
    return None


def _storey_map(model) -> dict:
    """The storey each product sits on, read the way the benchmark reads it.

    Containment comes first and aggregation second, so an element that is both
    contained in a space and aggregated under a storey is filed where the
    containment puts it.
    """
    out: dict = {}
    for relation in model.by_type("IfcRelContainedInSpatialStructure"):
        storey = _storey_ancestor(relation.RelatingStructure)
        if storey is None:
            continue
        for element in relation.RelatedElements or ():
            out[element.GlobalId] = storey.GlobalId
    for relation in model.by_type("IfcRelAggregates"):
        storey = _storey_ancestor(relation.RelatingObject)
        if storey is None:
            continue
        for child in relation.RelatedObjects or ():
            out.setdefault(child.GlobalId, storey.GlobalId)
    return out


def on_storey(storey, ifc_class: str) -> list:
    """Every element of one class the storey holds.

    The walk is the benchmark's own: an element is on the storey it is
    contained in, and an element that is only aggregated under a storey is on
    that one.
    """
    model = _file(storey)
    state = _read_state(model)
    filed = state["storeys"]
    if filed is None:
        filed = _storey_map(model)
        state["storeys"] = filed
    wanted = storey.GlobalId
    return [e for e in model.by_type(ifc_class)
            if filed.get(e.GlobalId) == wanted]


def storey_above(storey):
    """The storey immediately above this one, or None."""
    return _storey_step(storey, 1)


def storey_below(storey):
    """The storey immediately below this one, or None."""
    return _storey_step(storey, -1)


def _storey_step(storey, direction: int):
    """The next storey up or down, by elevation, or None when it is not one."""
    model = _file(storey)
    scale = unit_scale(model)
    here = storey.Elevation
    if here is None:
        return None
    here = float(here) * scale
    side = []
    for other in model.by_type("IfcBuildingStorey"):
        if other.GlobalId == storey.GlobalId or other.Elevation is None:
            continue
        level = float(other.Elevation) * scale
        if (level > here + 0.5) if direction > 0 else (level < here - 0.5):
            side.append((level, other))
    if not side:
        return None
    best = min(side, key=lambda pair: abs(pair[0] - here))
    close = [s for level, s in side if abs(level - best[0]) < 1e-6]
    return best[1] if len(close) == 1 else None


# --------------------------------------------------- bounding and hosting


def bounding_elements(space, ifc_class: str = "") -> list:
    """The elements recorded as bounding one space, of one class if given."""
    model = _file(space)
    out = []
    for relation in model.by_type("IfcRelSpaceBoundary"):
        if relation.RelatingSpace is None or relation.RelatedBuildingElement is None:
            continue
        if relation.RelatingSpace.GlobalId != space.GlobalId:
            continue
        element = relation.RelatedBuildingElement
        if ifc_class and not element.is_a(ifc_class):
            continue
        out.append(element)
    return list({e.GlobalId: e for e in out}.values())


def hosted_in(wall, ifc_class: str = "") -> list:
    """The doors and windows a wall hosts, through the openings it carries."""
    out = []
    for voids in getattr(wall, "HasOpenings", ()) or ():
        opening = voids.RelatedOpeningElement
        for fills in (getattr(opening, "HasFillings", ()) or ()) if opening else ():
            filling = fills.RelatedBuildingElement
            if filling is None:
                continue
            if ifc_class and not filling.is_a(ifc_class):
                continue
            out.append(filling)
    return list({e.GlobalId: e for e in out}.values())


# ------------------------------------------------------- the eight lookups


def _report_nearest(what: str, scored: list, unit: str = "m"):
    """The error a failed lookup raises, naming the three nearest candidates."""
    ranked = sorted(scored, key=lambda pair: pair[0])[:3]
    if not ranked:
        return LookupError("%s: no candidate of that class was found" % what)
    lines = ", ".join("%s %s (%.2f %s off)"
                      % (e.is_a(), e.GlobalId, value, unit)
                      for value, e in ranked)
    return LookupError("%s; nearest candidates: %s" % (what, lines))


def find_offset(reference, ifc_class: str, storey, direction, distance: float):
    """The element that stands a stated distance from another, along one axis.

    For "the wall on storey S that stands about 24.1 m east (+X) of the column
    named C": pass the column, ``'IfcWall'``, the storey, ``'east'`` and
    ``24.1``.  The sentence points at a spot, one that stands the stated
    distance from the reference along the named axis.  Candidates are the
    class's elements on that storey, placed by their placement origins.  One
    counts when its offset along the named axis is within a tenth of the stated
    distance, and never less than a quarter of a metre, of what the sentence
    says; of those, the one standing closest to the spot itself is the answer.
    """
    axis, sign = _direction(direction)
    origin = origin_point(reference)
    if origin is None:
        raise LookupError("the reference element has no placement to measure from")
    distance = float(distance)
    band = max(_BAND_FLOOR, _BAND_SHARE * abs(distance))
    spot = np.array(origin, dtype=float)
    spot[axis] += distance * sign
    best = None
    near = []
    for element in on_storey(storey, ifc_class):
        if element.GlobalId == reference.GlobalId:
            continue
        point = origin_point(element)
        if point is None:
            continue
        along = (float(point[axis]) - float(origin[axis])) * sign
        near.append((abs(along - distance), element))
        if abs(along - distance) > band:
            continue
        away = float(np.linalg.norm(point - spot))
        if best is None or away < best[0]:
            best = (away, element)
    if best is None:
        raise _report_nearest(
            "no %s on that storey stands %.2f m %s of %s, within %.2f m"
            % (ifc_class, distance, str(direction), reference.GlobalId, band),
            near)
    return best[1]


def find_extreme(ifc_class: str, storey, direction):
    """The element of one class that stands furthest one way on a storey.

    For "the slab furthest north (+Y) on storey S": pass ``'IfcSlab'``, the
    storey and ``'north'``.  Furthest is read from the placement origins, and
    the element with the largest coordinate along the named direction wins.
    """
    axis, sign = _direction(direction)
    best = None
    for element in on_storey(storey, ifc_class):
        point = origin_point(element)
        if point is None:
            continue
        value = float(point[axis]) * sign
        if best is None or value > best[0]:
            best = (value, element)
    if best is None:
        raise LookupError("storey %s holds no %s with a placement"
                          % (storey.GlobalId, ifc_class))
    return best[1]


def find_nearest(reference, ifc_class: str, storey):
    """The element of one class closest to another element.

    For "the column nearest to the door named D on storey S": pass the door,
    ``'IfcColumn'`` and the storey.  Distance is measured between the centres
    of the two bodies, which is where a reader looking at the model sees them
    stand, and the reference itself is never the answer.
    """
    origin = centre(reference)
    if origin is None:
        raise LookupError("the reference element has no body and no placement")
    best = None
    for element in on_storey(storey, ifc_class):
        if element.GlobalId == reference.GlobalId:
            continue
        point = centre(element)
        if point is None:
            continue
        away = float(np.linalg.norm(point - origin))
        if best is None or away < best[0]:
            best = (away, element)
    if best is None:
        raise LookupError("storey %s holds no other %s"
                          % (storey.GlobalId, ifc_class))
    return best[1]


def find_between(a, b, ifc_class: str, storey):
    """The element of one class standing between two named elements.

    For "the wall on storey S between the column named A and the column named
    B": pass the two columns, ``'IfcWall'`` and the storey.  The two are
    separated along one plan axis, and that axis is the one their centres
    differ on most.  A candidate counts when its centre lies in the run between
    theirs along that axis, clear of both ends by a twentieth of the run, since
    an element standing on top of one of the two is not between them.  Of the
    candidates that count, the one sitting closest to the straight line joining
    the two centres is the answer.
    """
    first, second = centre(a), centre(b)
    if first is None or second is None:
        raise LookupError("one of the two named elements cannot be located")
    axis = int(np.argmax(np.abs((first - second)[:2])))
    low, high = sorted((float(first[axis]), float(second[axis])))
    inset = _END_CLEARANCE * (high - low)
    line = second[:2] - first[:2]
    span = float(np.linalg.norm(line))
    if span < 1e-9:
        raise LookupError("the two named elements stand in the same place")
    line = line / span
    skip = {a.GlobalId, b.GlobalId}
    best = None
    near = []
    for element in on_storey(storey, ifc_class):
        if element.GlobalId in skip:
            continue
        point = centre(element)
        if point is None:
            continue
        offset = point[:2] - first[:2]
        away = abs(float(offset[0] * line[1] - offset[1] * line[0]))
        near.append((away, element))
        if not low + inset <= float(point[axis]) <= high - inset:
            continue
        if best is None or away < best[0]:
            best = (away, element)
    if best is None:
        raise _report_nearest(
            "no %s on that storey stands between %s and %s"
            % (ifc_class, a.GlobalId, b.GlobalId), near)
    return best[1]


def find_ordinal(host, ifc_class: str, direction, index: int):
    """The nth door or window along a wall, counted from one side.

    For "the first window from the south along the wall named W": pass the
    wall, ``'IfcWindow'``, ``'south'`` and ``1``.  The wall's fillings of that
    class are put in order by the centres of their bodies, starting at the side
    the sentence counts from, and the nth of them is the answer.  ``index``
    counts from one, as the sentence does.
    """
    axis, sign = _direction(direction)
    ranked = []
    for element in hosted_in(host, ifc_class):
        point = centre(element)
        if point is None:
            raise LookupError("%s %s has no body to place it in the row"
                              % (element.is_a(), element.GlobalId))
        ranked.append((float(point[axis]) * -sign, element))
    ranked.sort(key=lambda pair: pair[0])
    position = int(index) - 1
    if position < 0 or position >= len(ranked):
        raise LookupError("wall %s hosts %d %s, so there is no number %d"
                          % (host.GlobalId, len(ranked), ifc_class, int(index)))
    return ranked[position][1]


#: Two plan directions count as parallel when the cosine of the angle between
#: them is at least this large (about 26 degrees either way).
OPPOSITE_PARALLEL_COS = 0.9

#: How far past the room's centre, along the reference's normal, an element has
#: to stand to count as being on the far side.  The reference has to stand at
#: least as far from the centre on its own side.
OPPOSITE_MARGIN = 0.25

#: Two far-side elements tie when the stretches over which they face the
#: reference differ by less than this, and so do their distances from the
#: room's centre; the phrase then names neither of them.
OPPOSITE_TIE = 0.10

#: A body whose plan rectangle is less than this much longer than it is wide
#: gives no direction of its own; the placement's x axis is read instead.
_ELONGATION = 1.2


def _curve_points(item):
    """Plan points of an axis curve in the product's own frame, or None."""
    if item.is_a("IfcPolyline"):
        rows = [list(p.Coordinates) for p in item.Points or ()]
    elif item.is_a("IfcIndexedPolyCurve"):
        rows = [list(p) for p in (item.Points.CoordList or ())]
    elif item.is_a("IfcTrimmedCurve") and item.BasisCurve.is_a("IfcLine"):
        ratios = list(item.BasisCurve.Dir.Orientation.DirectionRatios)
        rows = [[0.0, 0.0], ratios]
    else:
        return None
    rows = [(list(r) + [0.0, 0.0])[:2] for r in rows]
    return np.asarray(rows, dtype=float) if len(rows) >= 2 else None


def _axis_direction(wall):
    """The plan direction of a wall's ``Axis`` curve, in world axes, or None.

    The axis is the line the wall was drawn along, so where the file carries one
    it is the wall's direction whatever the body looks like.  A polyline gives
    the direction of its longest segment.
    """
    shape = getattr(wall, "Representation", None)
    if not shape:
        return None
    for representation in shape.Representations or ():
        if (representation.RepresentationIdentifier or "") != "Axis":
            continue
        best = None
        for item in representation.Items or ():
            try:
                points = _curve_points(item)
            except Exception:
                points = None
            if points is None:
                continue
            for start, end in zip(points[:-1], points[1:]):
                step = end - start
                size = float(np.linalg.norm(step))
                if best is None or size > best[0]:
                    best = (size, step)
        if best is None or best[0] < 1e-9:
            continue
        try:
            turn = frame_of(wall)[:3, :3]
        except Exception:
            return None
        plan = (turn @ np.array([best[1][0], best[1][1], 0.0]))[:2]
        size = float(np.linalg.norm(plan))
        if size > 1e-9:
            return plan / size
    return None


def _plan_hull(points):
    """Convex hull of plan points, counter-clockwise (Andrew's monotone chain)."""
    points = np.unique(np.round(points, 6), axis=0)
    if len(points) < 3:
        return points
    order = sorted(map(tuple, points))

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in order:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(order):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.asarray(lower[:-1] + upper[:-1], dtype=float)


def plan_outline(product):
    """Convex hull of the body's plan, world metres, as an (n, 2) array, or None.

    The raw solid is read, before openings cut into it.
    """
    points = _vertices(product, disable_openings=True)
    if points is None:
        return None
    hull = _plan_hull(points[:, :2])
    return hull if len(hull) else None


def _cached_outline(product):
    """``plan_outline``, measured once per model and kept."""
    state = _read_state(_file(product))
    outlines = state.setdefault("outlines", {})
    guid = product.GlobalId
    if guid not in outlines:
        outlines[guid] = plan_outline(product)
    return outlines[guid]


def _body_direction(product):
    """The long side of the smallest rectangle around the body's plan, or None.

    None as well when the rectangle is close to square, since its long side
    then says nothing about which way the element runs.
    """
    hull = plan_outline(product)
    if hull is None or len(hull) < 3:
        return None
    best = None
    for index in range(len(hull)):
        edge = hull[(index + 1) % len(hull)] - hull[index]
        size = float(np.linalg.norm(edge))
        if size < 1e-9:
            continue
        along = edge / size
        across = np.array([-along[1], along[0]])
        first = float(np.ptp(hull @ along))
        second = float(np.ptp(hull @ across))
        area = first * second
        if best is None or area < best[0] - 1e-12:
            best = (area, along if first >= second else across,
                    max(first, second), min(first, second))
    if best is None or best[2] < _ELONGATION * best[3]:
        return None
    return best[1]


def plan_direction(product):
    """The unit plan direction an element runs along, in world axes.

    A door or a window runs along its host wall.  A wall runs along its
    ``Axis`` curve where the file has one; otherwise, and for any other
    element, along the long side of the smallest rectangle around its body's
    plan; an element whose plan is close to square runs along its placement's
    x axis.  The sign is fixed so that the x component is not negative, since
    only the line matters.  Rotated buildings are read in their own axes, never
    in world x and y.
    """
    host = product
    if product.is_a("IfcDoor") or product.is_a("IfcWindow"):
        host = host_wall_of(product) or product
    run = _axis_direction(host) if host.is_a("IfcWall") else None
    if run is None:
        run = _body_direction(host)
    if run is None:
        placement = getattr(host, "ObjectPlacement", None)
        if placement is None:
            return None
        try:
            run = frame_of(host)[:2, 0]
        except Exception:
            return None
        size = float(np.linalg.norm(run))
        if size < 1e-9:
            return None
        run = run / size
    run = np.asarray(run, dtype=float)
    if run[0] < -1e-9 or (abs(run[0]) <= 1e-9 and run[1] < 0):
        run = -run
    return run


def _cached_direction(product):
    """``plan_direction``, measured once per model and kept."""
    state = _read_state(_file(product))
    directions = state.setdefault("directions", {})
    guid = product.GlobalId
    if guid not in directions:
        directions[guid] = plan_direction(product)
    return directions[guid]


def _span(outline, run):
    """The interval an outline covers along a plan direction, or None."""
    if outline is None or len(outline) == 0:
        return None
    along = outline @ run
    return float(along.min()), float(along.max())


def opposite_ranking(reference, space, members, locate, direction, outline):
    """The rule behind "the element opposite R across the space S".

    Shared by this library and by the task generator, which pass their own
    readers: ``locate`` (element -> world centre), ``direction`` (element ->
    unit plan direction) and ``outline`` (element -> plan hull); the numbers
    and the tests are the same in both.

    The reference's normal is its plan direction turned a quarter turn, pointed
    at the side of the room's centre the reference stands on.  A member
    qualifies when it runs parallel to the reference and its centre stands more
    than ``OPPOSITE_MARGIN`` past the room's centre on the other side.  Of the
    members that qualify, the one facing the reference over the longest stretch
    wins (the stretch is measured along the reference and inside the room);
    members that face it over the same stretch, within ``OPPOSITE_TIE``, are
    decided by which stands nearest the room's centre, and members within
    ``OPPOSITE_TIE`` of that one tie with it.

    Returns ``(winners, near, problem)``: ``winners`` is the list of tied best
    elements (empty when nothing qualifies), ``near`` pairs every other member
    with its plan distance from the reference's mirror image across the room's
    centre, and ``problem`` is a sentence when the question cannot be asked at
    all.
    """
    middle = locate(space)
    origin = locate(reference)
    if middle is None or origin is None:
        return [], [], "the space or the reference element cannot be located"
    run = direction(reference)
    if run is None:
        return [], [], "the reference element's direction cannot be read"
    normal = np.array([-float(run[1]), float(run[0])])
    side = float(np.dot((origin - middle)[:2], normal))
    if abs(side) < OPPOSITE_MARGIN:
        return [], [], ("the reference element runs through the room's centre, "
                        "so nothing is opposite it")
    if side < 0:
        normal = -normal
    facing = _span(outline(reference), run)
    room = _span(outline(space), run)
    if facing is not None and room is not None:
        facing = (max(facing[0], room[0]), min(facing[1], room[1]))
    mirror = (2.0 * middle - origin)[:2]
    qualified = []
    near = []
    for element in members:
        if element is None or element.GlobalId == reference.GlobalId:
            continue
        point = locate(element)
        if point is None:
            continue
        near.append((float(np.linalg.norm(point[:2] - mirror)), element))
        other = direction(element)
        if other is None:
            continue
        if abs(float(np.dot(other, run))) < OPPOSITE_PARALLEL_COS:
            continue
        across = float(np.dot((point - middle)[:2], normal))
        if across >= -OPPOSITE_MARGIN:
            continue
        shared = 0.0
        stretch = _span(outline(element), run)
        if facing is not None and stretch is not None:
            shared = max(0.0, min(facing[1], stretch[1]) - max(facing[0], stretch[0]))
        qualified.append((shared, -across, element))
    if not qualified:
        return [], near, None
    longest = max(shared for shared, _distance, _e in qualified)
    qualified = [q for q in qualified if q[0] >= longest - OPPOSITE_TIE]
    best = min(distance for _shared, distance, _e in qualified)
    winners = sorted((e for _shared, distance, e in qualified
                      if distance <= best + OPPOSITE_TIE),
                     key=lambda e: e.GlobalId)
    return winners, near, None


def find_opposite(reference, ifc_class: str, space):
    """The element facing another one across a room.

    For "the wall opposite the wall named W across the space S": pass the wall
    named W, ``'IfcWall'`` and the space.  The answer is an element of the
    class bounding the room that runs parallel to W and stands on the other
    side of the room's centre, measured along the line square to W.  A door or
    a window runs along its host wall.  When several stand on the far side, the
    one facing W over the longest stretch inside the room is the answer, and
    between two that face it equally, the one nearer the room's centre.  A room with no parallel
    element on the far side, or with two equally near, has no answer, and the
    error names the elements standing nearest to where one would be.
    """
    members = bounding_elements(space, ifc_class)
    winners, near, problem = opposite_ranking(
        reference, space, members, centre, _cached_direction, _cached_outline)
    if problem:
        raise LookupError(problem)
    if not winners:
        raise _report_nearest(
            "no %s bounding space %s runs parallel to %s on the other side of "
            "the room's centre" % (ifc_class, space.GlobalId, reference.GlobalId),
            near)
    if len(winners) > 1:
        tied = {e.GlobalId for e in winners}
        raise _report_nearest(
            "%d elements of class %s stand equally near across space %s from "
            "%s, so the phrase names none of them"
            % (len(winners), ifc_class, space.GlobalId, reference.GlobalId),
            [pair for pair in near if pair[1].GlobalId in tied])
    return winners[0]


def find_beside_door(door, space, side: str, ifc_class: str):
    """The element on the left or the right, seen from a door into a room.

    For "the window on the left-hand side as seen from the door named D
    looking into the space S": pass the door, the space, ``'left'`` and
    ``'IfcWindow'``.  The reader faces into the room along the door's own host
    wall, across it, and left and right follow from that.  Of the elements of
    the class bounding the room, the one standing furthest to the named side of
    the door is the answer.
    """
    want = {"left": 1.0, "right": -1.0}.get(str(side).strip().lower())
    if want is None:
        raise ValueError("side is 'left' or 'right', not %r" % (side,))
    host = host_wall_of(door)
    if host is None:
        raise LookupError("door %s is not hosted in a wall, so it has no "
                          "direction to look along" % door.GlobalId)
    forward = np.array(frame_of(host)[:2, 1], dtype=float)
    length = float(np.linalg.norm(forward))
    if length < 1e-9:
        raise LookupError("the door's host wall has no readable direction")
    forward = forward / length
    middle, origin = centre(space), centre(door)
    if middle is None or origin is None:
        raise LookupError("the space or the door cannot be located")
    if float(np.dot(forward, (middle - origin)[:2])) < 0:
        forward = -forward
    left = np.array([-forward[1], forward[0]], dtype=float)
    best = None
    near = []
    for element in bounding_elements(space, ifc_class):
        if element.GlobalId == door.GlobalId:
            continue
        point = centre(element)
        if point is None:
            continue
        sideways = float(np.dot((point - origin)[:2], left)) * want
        near.append((-sideways, element))
        if sideways <= 0:
            continue
        if best is None or sideways > best[0]:
            best = (sideways, element)
    if best is None:
        raise _report_nearest(
            "no %s bounding space %s stands to the %s of door %s"
            % (ifc_class, space.GlobalId, side, door.GlobalId), near)
    return best[1]


def find_above_below(reference, ifc_class: str, direction, storey=None):
    """The element standing directly over or under another one.

    For "the column on storey S directly above the column named C": pass the
    column named C, ``'IfcColumn'`` and ``'above'``.  The answer sits on the
    next storey up, or down for ``'below'``, and is the element of the class
    whose body centre stands closest to the reference's in plan.  Pass
    ``storey`` when the sentence names the storey the answer sits on, and that
    storey is used instead of the neighbouring one.
    """
    word = str(direction).strip().lower()
    if word not in ("above", "below", "up", "down"):
        raise ValueError("direction is 'above' or 'below', not %r" % (direction,))
    up = word in ("above", "up")
    if storey is None:
        here = storey_of(reference)
        if here is None:
            raise LookupError("the reference element is not on a storey")
        storey = storey_above(here) if up else storey_below(here)
        if storey is None:
            raise LookupError("the reference element has no storey %s it"
                              % ("above" if up else "below"))
    origin = centre(reference)
    if origin is None:
        raise LookupError("the reference element cannot be located")
    best = None
    near = []
    for element in on_storey(storey, ifc_class):
        if element.GlobalId == reference.GlobalId:
            continue
        point = centre(element)
        if point is None:
            continue
        away = float(np.linalg.norm((point - origin)[:2]))
        near.append((away, element))
        rise = float(point[2]) - float(origin[2])
        if (rise <= 0) if up else (rise >= 0):
            continue
        if best is None or away < best[0]:
            best = (away, element)
    if best is None:
        raise _report_nearest(
            "no %s on storey %s stands %s %s"
            % (ifc_class, storey.GlobalId, word, reference.GlobalId), near)
    return best[1]


# ------------------------------------------------------ property set writes


#: The IFC value type a property is written as, for the property names the
#: standard sets use.  A name that is not listed takes its type from the value:
#: a flag is a boolean, a piece of text a label, a plain number a real.
_PROPERTY_TYPES = {
    "FireRating": "IfcLabel",
    "IsExternal": "IfcBoolean",
    "LoadBearing": "IfcBoolean",
    "ThermalTransmittance": "IfcThermalTransmittanceMeasure",
}


def _value_type(property_name: str, value) -> str:
    named = _PROPERTY_TYPES.get(str(property_name))
    if named is not None:
        return named
    if isinstance(value, bool):
        return "IfcBoolean"
    if isinstance(value, str):
        return "IfcLabel"
    if isinstance(value, int):
        return "IfcInteger"
    return "IfcReal"


def set_property(element, pset_name: str, property_name: str, value,
                 value_type: Optional[str] = None):
    """Write one property into a named property set on one element.

    The set is created when the element does not carry it.  A set the model
    shares between several elements is copied for this element first, so the
    value never lands on an element the instruction is not about.  The value
    type follows the property's name for the standard sets and from the value
    otherwise; pass ``value_type`` to write it as something else.

    Returns the property set the value now sits in.
    """
    model = _file(element)
    history = _owner_history(model)
    kind = value_type or _value_type(property_name, value)
    pset = None
    for relation in model.by_type("IfcRelDefinesByProperties"):
        definition = relation.RelatingPropertyDefinition
        if definition is None or not definition.is_a("IfcPropertySet"):
            continue
        if (definition.Name or "") != str(pset_name):
            continue
        members = list(relation.RelatedObjects or ())
        if element not in members:
            continue
        if len(members) == 1 and len(model.get_inverse(definition)) == 1:
            pset = definition
            break
        # The set is shared, so this element takes a copy of it and the shared
        # one keeps the elements the edit is not about.
        relation.RelatedObjects = tuple(m for m in members if m != element)
        pset = model.create_entity(
            "IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=history, Name=definition.Name,
            Description=definition.Description,
            HasProperties=[_copy_single_value(model, p)
                           for p in definition.HasProperties or ()])
        model.create_entity(
            "IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=history, Name=None, Description=None,
            RelatedObjects=[element], RelatingPropertyDefinition=pset)
        break
    if pset is None:
        pset = model.create_entity(
            "IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=history, Name=str(pset_name), Description=None,
            HasProperties=[])
        model.create_entity(
            "IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
            OwnerHistory=history, Name=None, Description=None,
            RelatedObjects=[element], RelatingPropertyDefinition=pset)
    nominal = model.create_entity(kind, value)
    for prop in pset.HasProperties or ():
        if prop.is_a("IfcPropertySingleValue") and prop.Name == str(property_name):
            prop.NominalValue = nominal
            return pset
    prop = model.create_entity("IfcPropertySingleValue", Name=str(property_name),
                               NominalValue=nominal, Unit=None)
    pset.HasProperties = tuple(pset.HasProperties or ()) + (prop,)
    return pset


def _copy_single_value(model, prop):
    """One property of a shared set, duplicated for an element's own copy."""
    if prop.is_a("IfcPropertySingleValue"):
        note = _property_note_attribute(model)
        return model.create_entity(
            "IfcPropertySingleValue", Name=prop.Name,
            NominalValue=prop.NominalValue, Unit=prop.Unit,
            **{note: getattr(prop, note, None)})
    return prop


def _property_note_attribute(model) -> str:
    """The name of IfcProperty's free-text attribute.  IFC4X3 renamed
    ``Description`` to ``Specification``; every earlier schema keeps the old name."""
    return "Specification" if str(model.schema).upper().startswith("IFC4X3") else "Description"


#: The short name for the placer, kept beside the long one so a trajectory
#: written either way runs.
spot_beside = spot_beside_wall_in_space


__all__ = __all__ + [
    "find_offset", "find_extreme", "find_nearest", "find_between",
    "find_ordinal", "find_opposite", "find_beside_door", "find_above_below",
    "set_property", "spot_beside",
    "on_storey", "storey_above", "storey_below", "bounding_elements",
    "hosted_in", "centre", "origin_point", "measure", "plan_length",
    "height", "overall_width", "forget_geometry",
]


# ============================================================ moving a body
#
# Two edits an instruction describes in words the model can answer on its own:
# moving a door or a window into another wall, and turning an element about a
# point the sentence names rather than about a coordinate.  Both used to be
# written out with numbers the generator had computed - where the opening sits
# across the new wall, how far the assembly rises, which point the turn is
# about - and none of those numbers is in the sentence.  All of them are in the
# model, so they are read here.


#: How finely a measured pivot is written: to the centimetre.  A point read
#: off the model carries the full precision of the mesh, and turning a small
#: element about a point four millimetres away from the one the benchmark's
#: own edit turns it about costs three per cent of the geometry axis.  The
#: benchmark writes the pivot it computes to the centimetre, and so does this.
_PLACEMENT_PLACES = 2


def _to_cm(value: float) -> float:
    """A measured length written to the centimetre."""
    if _PLACEMENT_PLACES is None:
        return float(value)
    return float(round(float(value), _PLACEMENT_PLACES))


def _sole_user(model, item, owner) -> bool:
    """True when ``item`` is referenced by ``owner`` and by nothing else."""
    inverses = model.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner


def _own_axis(model, placement):
    """The placement's own axis triple, substituted when the model shares it.

    A model often shares one axis placement, or the point inside it, between
    several elements.  Writing through a shared one would move an element the
    edit is not about, so a private copy is put in first.
    """
    axis = placement.RelativePlacement
    if not _sole_user(model, axis, placement):
        axis = model.create_entity("IfcAxis2Placement3D", Location=axis.Location,
                                   Axis=axis.Axis, RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    point = axis.Location
    if not _sole_user(model, point, axis):
        axis.Location = model.create_entity("IfcCartesianPoint",
                                            Coordinates=tuple(point.Coordinates))
    return axis


def _places_only(model, placement, product) -> bool:
    """True when this product is the only one the placement positions."""
    return not [i for i in model.get_inverse(placement)
                if i.is_a("IfcProduct") and i.id() != product.id()]


def _matrix_of(placement) -> np.ndarray:
    """The 4x4 matrix of a local placement, its translation in file units."""
    if placement is None:
        return np.identity(4)
    return np.array(ifcopenshell.util.placement.get_local_placement(placement),
                    dtype=float)


def _tidy(matrix: np.ndarray) -> np.ndarray:
    """A matrix with the arithmetic noise of a trigonometric call removed."""
    return np.round(np.asarray(matrix, dtype=float), 12) + 0.0


def _shift(vector) -> np.ndarray:
    matrix = np.identity(4)
    matrix[:3, 3] = np.asarray(vector, dtype=float)
    return matrix


def sole_extrusion(product):
    """The product's one extruded body, or None when it has no single one."""
    shape = getattr(product, "Representation", None)
    for representation in (shape.Representations or ()) if shape else ():
        if representation.RepresentationIdentifier != "Body":
            continue
        if representation.RepresentationType != "SweptSolid":
            return None
        items = representation.Items or ()
        if len(items) != 1 or not items[0].is_a("IfcExtrudedAreaSolid"):
            return None
        return items[0]
    return None


def _hangs_from(product, placement) -> bool:
    """True when the product's placement is written under ``placement``."""
    current = getattr(product, "ObjectPlacement", None)
    while current is not None and current.is_a("IfcLocalPlacement"):
        if placement is not None and current.id() == placement.id():
            return True
        current = current.PlacementRelTo
    return False


def _replant(product, host, x: float, y: float, z: float,
             depth: Optional[float]) -> None:
    """Hang one product from a wall at a stated point in that wall's frame."""
    model = _file(product)
    scale = unit_scale(model)
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        raise ValueError("%s has no local placement" % product.GlobalId)
    if not _places_only(model, placement, product):
        raise ValueError("%s shares its placement with another element"
                         % product.GlobalId)
    placement.PlacementRelTo = host.ObjectPlacement
    axis = _own_axis(model, placement)
    axis.Location.Coordinates = (float(x) / scale, float(y) / scale,
                                 float(z) / scale)
    axis.Axis = None
    axis.RefDirection = None
    if depth is None:
        return
    solid = sole_extrusion(product)
    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
        raise ValueError("%s has no rectangular profile to resize"
                         % product.GlobalId)
    profile = solid.SweptArea
    if len(model.get_inverse(profile)) != 1:
        profile = model.create_entity(
            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
            ProfileName=profile.ProfileName, Position=profile.Position,
            XDim=profile.XDim, YDim=profile.YDim)
        solid.SweptArea = profile
    profile.YDim = float(depth) / scale


def move_filling(filling, host_wall, along: float, sill: Optional[float] = None):
    """Move a door or a window, with its opening, into another wall.

    ``along`` is the distance along the new wall's own x axis, in metres, to the
    near edge of the opening, which is what "2.2 m along that wall from its
    start point" states.  The wall the element came from is healed and the wall
    it joins is cut instead, because the opening it fills is re-pointed rather
    than rebuilt.

    What the function reads off the model, so the caller never states it:

    * where the opening sits across the new wall, which is 50 mm outside that
      wall's near face, and how deep it cuts, which is the wall's thickness
      plus 100 mm, both the way a new opening is cut;
    * the leaf's own offset from its opening along the wall, which it keeps;
    * how far the whole assembly rises or falls, which is the difference
      between the two walls' bases, so the element keeps the height above its
      wall's base that it had.  Pass ``sill`` to put the leaf's base at a
      stated height above the new wall's base instead;
    * the leaf's new depth, which is the new wall's thickness where the leaf's
      body is a rectangular extrusion, and is left alone where it is not.

    A leaf the model hangs from its own opening follows the opening and is not
    moved twice.  Returns the wall the element left.
    """
    model = _file(filling)
    fills = list(getattr(filling, "FillsVoids", ()) or ())
    if len(fills) != 1:
        raise ValueError("%s does not fill exactly one opening"
                         % filling.GlobalId)
    opening = fills[0].RelatingOpeningElement
    voids = list(getattr(opening, "VoidsElements", ()) or ())
    if len(voids) != 1:
        raise ValueError("%s hangs in an opening that voids no one wall"
                         % filling.GlobalId)
    old_host = voids[0].RelatingBuildingElement
    old = wall_box(old_host)
    new = wall_box(host_wall)
    if old is None or new is None:
        raise ValueError("one of the two walls has no body that can be measured")

    opening_old = origin_in_frame(opening, old_host)
    leaf_old = origin_in_frame(filling, old_host)
    hole_body = box_in_frame(opening, opening)
    leaf_body = box_in_frame(filling, filling)
    if hole_body is None or leaf_body is None:
        raise ValueError("the opening or the leaf has no body that can be measured")
    leaf_follows = _hangs_from(filling, opening.ObjectPlacement)
    rectangular = (sole_extrusion(filling) is not None
                   and sole_extrusion(filling).SweptArea.is_a(
                       "IfcRectangleProfileDef"))

    # The placement here is written at the precision it was measured at.
    # Taking it to the centimetre, which is what the benchmark's own edit
    # writes, was measured on six tasks and moved four of them onto the
    # benchmark exactly and two of them a centimetre the other way, so the
    # measured value is kept.
    hole_x = float(along) - float(hole_body[0][0])
    move = hole_x - float(opening_old[0])
    if sill is None:
        lift = new["base"] - old["base"]
    else:
        lift = (new["base"] + float(sill)
                - (float(leaf_old[2]) + float(leaf_body[0][2])))
    across = new["near"] - OPENING_CLEARANCE
    hole_depth = new["thickness"] + 2 * OPENING_CLEARANCE

    forget_geometry(model)
    voids[0].RelatingBuildingElement = host_wall
    _replant(opening, host_wall, hole_x, across,
             float(opening_old[2]) + lift, hole_depth)
    if not leaf_follows:
        _replant(filling, host_wall, float(leaf_old[0]) + move, new["near"],
                 float(leaf_old[2]) + lift,
                 new["thickness"] if rectangular else None)
    return old_host


def _pivot_point(element, pivot):
    """The world point in metres an element is turned about.

    ``'own'`` is the element's own placement origin, which is what "turning it
    about its own placement origin" names; ``'centre'`` is the middle of its
    plan, which is what "turning it about the centre of its plan" names.  A
    pair or triple of numbers is read as a world point in metres.
    """
    if isinstance(pivot, str):
        word = pivot.strip().lower()
        if word in ("own", "origin", "placement", "its own placement origin"):
            point = origin_point(element)
            if point is None:
                raise ValueError("the element has no placement to turn about")
            return float(point[0]), float(point[1])
        if word in ("centre", "center", "plan", "plan centre", "plan center"):
            box = world_box(element)
            if box is None:
                raise ValueError("the element has no body whose plan has a centre")
            return ((float(box[0][0]) + float(box[1][0])) / 2.0,
                    (float(box[0][1]) + float(box[1][1])) / 2.0)
        raise ValueError("pivot is 'own', 'centre', or a point in metres, "
                         "not %r" % (pivot,))
    values = [float(v) for v in pivot]
    if len(values) < 2:
        raise ValueError("a pivot point needs an x and a y, in metres")
    return values[0], values[1]


def turn_element(element, degrees: float, pivot="own"):
    """Turn one element about the vertical axis by a stated angle.

    ``degrees`` is measured anticlockwise seen from above.  ``pivot`` says which
    vertical line the element turns about: ``'own'`` for its own placement
    origin, ``'centre'`` for the middle of its plan, or a point in world metres.
    The element's own placement is rewritten, so its openings and the doors and
    windows they hold turn with it.
    """
    model = _file(element)
    scale = unit_scale(model)
    pivot_x, pivot_y = _pivot_point(element, pivot)
    pivot_x, pivot_y = _to_cm(pivot_x), _to_cm(pivot_y)
    forget_geometry(model)
    angle = np.radians(float(degrees))
    turn = np.identity(4)
    turn[0, 0], turn[0, 1] = np.cos(angle), -np.sin(angle)
    turn[1, 0], turn[1, 1] = np.sin(angle), np.cos(angle)
    point = np.array([pivot_x / scale, pivot_y / scale, 0.0])
    about = _shift(point) @ _tidy(turn) @ _shift(-point)
    _write_world_frame(element, _tidy(
        about @ _matrix_of(element.ObjectPlacement)))


def _write_world_frame(product, world: np.ndarray) -> None:
    """Give a product the world frame ``world``, keeping its parent placement.

    ``world`` is a 4x4 matrix whose translation is in the file's own length
    unit.  Anything placed relative to this product, an opening for instance,
    keeps its own offset and therefore follows.
    """
    model = _file(product)
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        raise ValueError("%s has no local placement to write" % product.GlobalId)
    if not _places_only(model, placement, product):
        raise ValueError("%s shares its placement with another element"
                         % product.GlobalId)
    parent = _matrix_of(placement.PlacementRelTo)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = _own_axis(model, placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = model.create_entity(
        "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = model.create_entity(
        "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 0]))


def wall_axis(wall):
    """Which world axis a wall runs along, and where its centre line sits.

    Returns ``(word, value)``: the direction word of the axis the wall's own
    length runs along, and the coordinate of its centre line on the other plan
    axis, in world metres.  This is the plane an instruction means by "the
    vertical plane that follows the axis of the wall named W".
    """
    box = world_box(wall)
    if box is None:
        raise ValueError("the wall has no body whose axis can be read")
    size = box[1] - box[0]
    runs = 0 if float(size[0]) >= float(size[1]) else 1
    across = 1 - runs
    middle = (float(box[0][across]) + float(box[1][across])) / 2.0
    return ("east" if runs == 0 else "north"), middle


__all__ = __all__ + [
    "move_filling", "turn_element", "wall_axis", "sole_extrusion",
]


# ================================================== absence, and assignment
#
# Two more sentences the model can answer from the model itself.  The first
# names an element by what it does not carry, "the wall on storey S that hosts
# no door and no window"; the second gives an element a material or a type by
# name.  Both used to be written out round by round, and both are one call now.


def find_without(scope, ifc_class: str, missing):
    """The element of one class that nothing of the named kind is attached to.

    ``scope`` is the storey or the space the sentence names, ``ifc_class`` the
    class it asks for, and ``missing`` the class the sentence excludes, or
    several of them:

    * "the wall on storey S that hosts no door and no window" is
      ``find_without(storey, 'IfcWall', ('IfcDoor', 'IfcWindow'))``;
    * "the wall bounding the space S that hosts no door" is
      ``find_without(space, 'IfcWall', 'IfcDoor')``;
    * "the space on storey S that no window bounds" is
      ``find_without(storey, 'IfcSpace', 'IfcWindow')``;
    * "the only column on storey S that is connected to no other element" is
      ``find_without(storey, 'IfcColumn', 'connection')``, which names a
      relationship in plain words instead of a class.

    What counts as attached follows from the class the sentence asks for.  A
    wall carries doors and windows through the openings cut in it, so a wall is
    kept when none of those is of an excluded class.  A room is bounded by the
    elements recorded against it, so a room is kept when none of those is of an
    excluded class; a room nothing at all bounds is not an answer, since the
    model records nothing about what bounds it either way.

    Returns the one element that matches, and raises ``LookupError`` naming
    what it found when none does or when several do.
    """
    wanted = (missing,) if isinstance(missing, str) else tuple(missing)
    if not wanted:
        raise ValueError("say which class the sentence excludes")
    if all(name in MISSING_RELATIONS for name in wanted):
        return _find_without_relation(scope, ifc_class, wanted)
    if any(name in MISSING_RELATIONS for name in wanted):
        raise ValueError("name either classes or one relationship, not both")
    if scope.is_a("IfcBuildingStorey"):
        candidates = on_storey(scope, ifc_class)
        where = "storey %s" % scope.GlobalId
    elif scope.is_a("IfcSpace"):
        candidates = bounding_elements(scope, ifc_class)
        where = "space %s" % scope.GlobalId
    else:
        raise ValueError("the scope is a storey or a space, not %s"
                         % scope.is_a())
    hits = []
    for element in candidates:
        if element.is_a("IfcSpace"):
            attached = bounding_elements(element)
            if not attached:
                continue
        else:
            attached = hosted_in(element)
        if any(other.is_a(name) for other in attached for name in wanted):
            continue
        hits.append(element)
    excluded = ", ".join(wanted)
    if not hits:
        raise LookupError("every %s on %s carries one of %s"
                          % (ifc_class, where, excluded))
    if len(hits) > 1:
        raise LookupError(
            "%d %s on %s carry none of %s: %s"
            % (len(hits), ifc_class, where, excluded,
               ", ".join(e.GlobalId for e in hits[:5])))
    return hits[0]


def assign_material(element, name: str):
    """Give one element a material, named.

    A material the file already carries under that name is used again rather
    than duplicated, and one is created when the file has none.  An element
    carries one material association, so the association it had is dropped
    first.  Returns the material.
    """
    model = _file(element)
    material = None
    for candidate in sorted(model.by_type("IfcMaterial"), key=lambda m: m.id()):
        if (candidate.Name or "") == str(name):
            material = candidate
            break
    if material is None:
        material = model.create_entity("IfcMaterial", Name=str(name))
    for relation in list(model.by_type("IfcRelAssociatesMaterial")):
        if element in (relation.RelatedObjects or ()):
            _drop_member(model, relation, element)
    model.create_entity(
        "IfcRelAssociatesMaterial", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=None, Description=None,
        RelatedObjects=[element], RelatingMaterial=material)
    return material


def assign_type(element, type_object):
    """Put one element under a type object.

    An element is typed once, so the type it had is dropped first.  Where the
    file already records other elements under this type, the element joins that
    record rather than a second one being written.  Returns the relationship
    the element now sits in.
    """
    model = _file(element)
    for relation in list(model.by_type("IfcRelDefinesByType")):
        if element in (relation.RelatedObjects or ()):
            _drop_member(model, relation, element)
    for relation in sorted(model.by_type("IfcRelDefinesByType"),
                           key=lambda r: r.id()):
        if relation.RelatingType == type_object:
            relation.RelatedObjects = tuple(relation.RelatedObjects or ()) + (element,)
            return relation
    return model.create_entity(
        "IfcRelDefinesByType", GlobalId=ifcopenshell.guid.new(),
        OwnerHistory=_owner_history(model), Name=None, Description=None,
        RelatedObjects=[element], RelatingType=type_object)


def _drop_member(model, relation, product) -> None:
    """Take one product out of a relationship, removing it when it empties."""
    members = [m for m in (relation.RelatedObjects or ()) if m != product]
    if members:
        relation.RelatedObjects = tuple(members)
    else:
        model.remove(relation)


__all__ = __all__ + ["find_without", "assign_material", "assign_type"]


# ============================================= a complete deletion, and the
# five sentences that name an element through what it sits in, joins, bounds,
# stands on, or does not have.


#: The relationship classes a removal can leave standing with nothing on their
#: related side, and the attribute that side is held in.  A class whose sides
#: are single-valued is listed with an empty tuple and is checked attribute by
#: attribute below.
_RELATED_SIDE = {
    "IfcRelAssociatesMaterial": ("RelatedObjects",),
    "IfcRelDefinesByProperties": ("RelatedObjects",),
    "IfcRelDefinesByType": ("RelatedObjects",),
    "IfcRelContainedInSpatialStructure": ("RelatedElements",),
    "IfcRelAggregates": ("RelatedObjects",),
    "IfcRelNests": ("RelatedObjects",),
    "IfcRelAssignsToGroup": ("RelatedObjects",),
    "IfcRelSpaceBoundary": (),
    "IfcRelConnectsElements": (),
    "IfcRelFillsElement": (),
    "IfcRelVoidsElement": (),
}

#: The single-valued sides of the relationship classes above, both ends, since
#: a relationship missing either end names nothing.
_BOTH_ENDS = {
    "IfcRelSpaceBoundary": ("RelatingSpace", "RelatedBuildingElement"),
    "IfcRelConnectsElements": ("RelatingElement", "RelatedElement"),
    "IfcRelFillsElement": ("RelatingOpeningElement", "RelatedBuildingElement"),
    "IfcRelVoidsElement": ("RelatingBuildingElement", "RelatedOpeningElement"),
}


#: The structure a building is held in.  A room is not one of these: a room is
#: an ordinary target of an instruction and is removed like any other element.
_STRUCTURE = ("IfcBuildingStorey", "IfcBuilding", "IfcSite", "IfcProject",
              "IfcProjectLibrary")


def _is_structure(product) -> bool:
    """True for a storey, a building, a site or the project itself."""
    for name in _STRUCTURE:
        try:
            if product.is_a(name):
                return True
        except RuntimeError:
            continue
    return False


def _empty_relations(model) -> list:
    """Every relationship object left with nothing on a side it needs."""
    stale = []
    for ifc_class, attributes in _RELATED_SIDE.items():
        try:
            relations = model.by_type(ifc_class)
        except RuntimeError:
            continue
        for relation in relations:
            if ifc_class in _BOTH_ENDS:
                ends = _BOTH_ENDS[ifc_class]
                if any(getattr(relation, end, None) is None for end in ends):
                    stale.append(relation)
                continue
            for attribute in attributes:
                members = getattr(relation, attribute, None) or ()
                if len(members) == 0:
                    stale.append(relation)
                    break
    # by_type returns subtypes as well, so one relationship can be listed twice.
    return list({r.id(): r for r in stale}.values())


def _sweep_empty_relations(model, spare: set) -> int:
    """Take out the relationship objects a removal emptied.  Returns how many.

    A relationship that lists several products keeps the others when one of
    them is removed, so taking the last one out leaves a relationship naming
    nothing.  Such a row is not readable by anything and is not in the model a
    person would hand over, so it goes with the removal that emptied it.

    ``spare`` holds the rows that already named nothing before the removal.
    A file can carry such rows from the authoring tool that wrote it, and they
    are not this edit's business, so they stay exactly as they were.
    """
    removed = 0
    while True:
        stale = [r for r in _empty_relations(model) if r.id() not in spare]
        if not stale:
            return removed
        for relation in stale:
            try:
                model.remove(relation)
                removed += 1
            except RuntimeError:
                continue


def _fillings_of(product) -> list:
    """The doors and windows the openings in one element hold."""
    out = []
    for voids in getattr(product, "HasOpenings", ()) or ():
        opening = voids.RelatedOpeningElement
        for fills in (getattr(opening, "HasFillings", ()) or ()) if opening else ():
            filling = fills.RelatedBuildingElement
            if filling is not None:
                out.append(filling)
    return list({e.GlobalId: e for e in out}.values())


def delete_element(product) -> None:
    """Remove one element, everything it holds, and the relationships it empties.

    An opening exists to be filled and a door exists to sit in a wall, so a
    wall cannot go while the doors and windows cut into it stay: removing the
    wall alone leaves them standing in mid-air with their material, their
    properties and the room boundaries they used to form still recorded.  This
    call removes the element, the openings cut into it, the doors and windows
    those openings hold, and afterwards every relationship object left with
    nothing on its related side.

    A storey, a building or a site is never removed, and no element other than
    the ones the removed element holds is touched: a wall connected to another
    wall loses the connection and the other wall stays.
    """
    if _is_structure(product):
        raise ValueError("a storey, a building or a site is not removed this "
                         "way; move what it holds first")
    if getattr(product, "FillsVoids", ()) or ():
        # a door or a window goes together with the opening it filled, whichever
        # name the caller used for the removal
        delete_filling(product)
        return
    model = _file(product)
    forget_geometry(model)
    before = {h.id() for h in model.by_type("IfcOwnerHistory")}
    spare = {r.id() for r in _empty_relations(model)}
    for filling in _fillings_of(product):
        ifcopenshell.api.root.remove_product(model, product=filling)
    ifcopenshell.api.root.remove_product(model, product=product)
    _sweep_empty_relations(model, spare)
    _freeze_new_histories(model, before)


def deletion_is_complete(model, guid: str, source=None, report: bool = False):
    """Whether a removal left the model whole.

    Three things are asked of the model the removal produced: the element is
    gone, no door or window the removed element used to hold is still in it,
    and no relationship object names nothing.  ``source`` is the model as it
    stood before the removal.  It is what says which doors and windows the
    element held, and it is also what tells a row the removal emptied from a
    row that already named nothing when the file was written, which several
    files in any corpus carry; without it the orphan reading falls back to a
    filling that fills no opening at all, which a file with unhosted doors
    fails on its own.  With ``report`` the answer is a dictionary listing
    what was found.
    """
    findings = {"present": False, "orphan_fillings": [], "empty_relations": [],
                "dangling": [], "orphan_openings": []}
    try:
        model.by_guid(guid)
        findings["present"] = True
    except RuntimeError:
        pass
    spare = {r.id() for r in _empty_relations(source)} if source is not None \
        else set()
    for relation in _empty_relations(model):
        if relation.id() in spare:
            continue
        findings["empty_relations"].append("%s #%d" % (relation.is_a(),
                                                       relation.id()))
    if source is not None:
        try:
            gone = source.by_guid(guid)
        except RuntimeError:
            gone = None
        held = [f.GlobalId for f in _fillings_of(gone)] if gone is not None else []
        for filling_guid in held:
            try:
                model.by_guid(filling_guid)
            except RuntimeError:
                continue
            findings["orphan_fillings"].append(filling_guid)
        # a removed door or window takes the opening it filled with it
        for relation in (getattr(gone, "FillsVoids", ()) or ()) if gone is not None else ():
            opening = relation.RelatingOpeningElement
            if opening is None:
                continue
            try:
                model.by_guid(opening.GlobalId)
            except RuntimeError:
                continue
            findings["orphan_openings"].append(opening.GlobalId)
    else:
        for ifc_class in ("IfcDoor", "IfcWindow"):
            for filling in model.by_type(ifc_class):
                if not (getattr(filling, "FillsVoids", ()) or ()):
                    findings["orphan_fillings"].append(filling.GlobalId)
    for entity in model:
        for value in entity:
            if isinstance(value, str) and value == guid:
                findings["dangling"].append("%s #%d" % (entity.is_a(), entity.id()))
    ok = (not findings["present"] and not findings["orphan_fillings"]
          and not findings["orphan_openings"]
          and not findings["empty_relations"] and not findings["dangling"])
    findings["ok"] = ok
    return findings if report else ok


# --------------------------------------------------- five more lookups


def find_host(filling):
    """The wall a named door or window sits in.

    "the wall in which the door named D is located" is one call.  The door
    fills an opening and the opening is cut into a wall, so the wall is two
    hops away; this returns it, and raises ``LookupError`` when the element
    fills no opening.
    """
    host = host_wall_of(filling)
    if host is None:
        raise LookupError("%s %s fills no opening, so it sits in no wall"
                          % (filling.is_a(), filling.GlobalId))
    return host


#: The words a sentence uses for the space on the far side of an external wall.
OUTSIDE_WORDS = ("the outside", "outside", "outdoors")


def _bounded_spaces(element) -> list:
    """The spaces one element is recorded as bounding."""
    model = _file(element)
    out = []
    for relation in model.by_type("IfcRelSpaceBoundary"):
        if relation.RelatedBuildingElement is None or relation.RelatingSpace is None:
            continue
        if relation.RelatedBuildingElement.GlobalId == element.GlobalId:
            out.append(relation.RelatingSpace)
    return list({s.GlobalId: s for s in out}.values())


def _is_external(element) -> bool:
    """Whether the model marks the element as external, by its IsExternal flag."""
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


def find_filling_between(space_a, space_b, ifc_class: str):
    """The door or window that joins two rooms, or one room and the outside.

    A door joins the rooms its host wall bounds, so the door the sentence
    names is the one of that class whose wall bounds both rooms.  For "the
    door that connects the room R to the outside", pass the words the sentence
    uses in place of the second room: the wall is then one that the model marks
    as external, or one that bounds the named room and no other.
    """
    outside = isinstance(space_b, str) or space_b is None
    if outside and isinstance(space_b, str) \
            and space_b.strip().lower() not in OUTSIDE_WORDS:
        raise ValueError("the second room is a space, or the words for the "
                         "outside, not %r" % space_b)
    hits = []
    for filling in _file(space_a).by_type(ifc_class):
        host = host_wall_of(filling)
        if host is None:
            continue
        bounded = {s.GlobalId for s in _bounded_spaces(host)}
        if space_a.GlobalId not in bounded:
            continue
        if outside:
            if len(bounded) == 1 or _is_external(host):
                hits.append(filling)
        elif space_b.GlobalId in bounded:
            hits.append(filling)
    other = "the outside" if outside else "space %s" % space_b.GlobalId
    if not hits:
        raise LookupError("no %s sits in a wall between space %s and %s"
                          % (ifc_class, space_a.GlobalId, other))
    if len(hits) > 1:
        raise LookupError("%d elements of class %s sit in a wall between "
                          "space %s and %s: %s"
                          % (len(hits), ifc_class, space_a.GlobalId, other,
                             ", ".join(e.GlobalId for e in hits[:5])))
    return hits[0]


def find_bounding(space, ifc_class: str):
    """The one element of a class that bounds a room.

    "the window that bounds the room R" is one call.  The elements a room is
    bounded by are what the model records against it; this keeps those of the
    class the sentence asks for and expects one.
    """
    hits = bounding_elements(space, ifc_class)
    if not hits:
        raise LookupError("no %s bounds space %s" % (ifc_class, space.GlobalId))
    if len(hits) > 1:
        raise LookupError("%d elements of class %s bound space %s: %s"
                          % (len(hits), ifc_class, space.GlobalId,
                             ", ".join(e.GlobalId for e in hits[:5])))
    return hits[0]


#: How far below the base of the elements above it the top face of the element
#: underneath may sit, in metres, before it is a different floor.
UNDER_GAP = 1.5

#: How much of the ground the walls stand on the element underneath has to
#: cover before it is what the sentence means.  A pad a fifth of that size is
#: not what a reader calls the slab the walls stand on, and a storey whose
#: only candidates are such pads has no answer rather than an arbitrary one.
UNDER_SHARE = 0.20


def find_under(elements_or_storey, ifc_class: str):
    """The slab the given walls stand on.

    "the slab below the walls of the ground storey" is one call: pass the
    storey and the class.  Pass a list of elements instead to name them one by
    one.  The rule is the one a reader applies: of the elements of that class
    whose top face lies at or just below the base of the walls, the one whose
    plan outline covers most of the ground the walls stand on.
    """
    if isinstance(elements_or_storey, (list, tuple)):
        above = list(elements_or_storey)
        model = _file(above[0]) if above else None
        scope = None
    else:
        scope = elements_or_storey
        model = _file(scope)
        above = on_storey(scope, "IfcWall")
    if not above:
        raise LookupError("no wall was found to stand on anything")
    boxes = [world_box(e) for e in above]
    boxes = [b for b in boxes if b is not None]
    if not boxes:
        raise LookupError("the elements above have no readable geometry")
    base = min(float(b[0][2]) for b in boxes)
    low = np.array([min(float(b[0][0]) for b in boxes),
                    min(float(b[0][1]) for b in boxes)])
    high = np.array([max(float(b[1][0]) for b in boxes),
                     max(float(b[1][1]) for b in boxes)])
    area = max(float((high[0] - low[0]) * (high[1] - low[1])), 1e-9)
    named = {e.GlobalId for e in above}
    scored = []
    for candidate in model.by_type(ifc_class):
        if candidate.GlobalId in named:
            continue
        box = world_box(candidate)
        if box is None:
            continue
        top = float(box[1][2])
        drop = base - top
        if drop < -0.05 or drop > UNDER_GAP:
            continue
        overlap_x = min(float(box[1][0]), high[0]) - max(float(box[0][0]), low[0])
        overlap_y = min(float(box[1][1]), high[1]) - max(float(box[0][1]), low[1])
        if overlap_x <= 0 or overlap_y <= 0:
            continue
        share = overlap_x * overlap_y / area
        if share < UNDER_SHARE:
            continue
        scored.append((round(share, 9), -round(abs(drop), 9), candidate))
    if not scored:
        where = ("storey %s" % scope.GlobalId) if scope is not None \
            else "the elements given"
        raise LookupError("no %s carries %s" % (ifc_class, where))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    best = scored[0]
    rivals = [row for row in scored[1:] if row[:2] == best[:2]]
    if rivals:
        raise LookupError("%d elements of class %s lie equally far under the "
                          "walls: %s" % (len(rivals) + 1, ifc_class,
                                         ", ".join(row[2].GlobalId for row
                                                   in [best] + rivals[:4])))
    return best[2]


#: The relationships a sentence can name as the one an element does not have,
#: and the plain words it names them with.
MISSING_RELATIONS = {
    "connection": "IfcRelConnectsElements",
    "space boundary": "IfcRelSpaceBoundary",
}


def _relation_count(element, relation_word: str) -> int:
    """How many relationships of the named kind an element takes part in."""
    ifc_class = MISSING_RELATIONS[relation_word]
    model = _file(element)
    guid = element.GlobalId
    count = 0
    for relation in model.by_type(ifc_class):
        if ifc_class == "IfcRelConnectsElements":
            ends = (relation.RelatingElement, relation.RelatedElement)
        else:
            ends = (relation.RelatedBuildingElement,)
        if any(end is not None and end.GlobalId == guid for end in ends):
            count += 1
    return count


def _find_without_relation(scope, ifc_class: str, wanted: tuple):
    """The one element of a class that takes part in none of a relationship."""
    word = wanted[0]
    if scope.is_a("IfcBuildingStorey"):
        candidates = on_storey(scope, ifc_class)
        where = "storey %s" % scope.GlobalId
    elif scope.is_a("IfcSpace"):
        candidates = bounding_elements(scope, ifc_class)
        where = "space %s" % scope.GlobalId
    else:
        raise ValueError("the scope is a storey or a space, not %s"
                         % scope.is_a())
    hits = [e for e in candidates if _relation_count(e, word) == 0]
    if not hits:
        raise LookupError("every %s on %s has a %s" % (ifc_class, where, word))
    if len(hits) > 1:
        raise LookupError("%d elements of class %s on %s have no %s: %s"
                          % (len(hits), ifc_class, where, word,
                             ", ".join(e.GlobalId for e in hits[:5])))
    return hits[0]


__all__ = __all__ + [
    "delete_element", "deletion_is_complete", "find_host",
    "find_filling_between", "find_bounding", "find_under",
]


# ============================================ what this module actually has
#
# A caller that reaches for a function this module does not have gets back the
# list of the ones it does.  The bare AttributeError says only that the name is
# missing, which leaves a reader guessing and trying again; the message below
# says what is on offer, grouped by what the functions do.  The groups are read
# off the module's own public names, so a function added later appears without
# anyone remembering to list it here.


#: How long the message may get, so it stays readable in a traceback.
_MENU_LIMIT = 600

#: The groups the public names fall into, by the verb each name starts with.
#: Anything that matches no verb only reads the model, which is the first
#: group.
_MENU_GROUPS = (
    ("measuring", ()),
    ("finding", ("find_",)),
    ("placing", ("spot_",)),
    ("editing", ("add_", "set_", "delete_", "replace_", "copy_", "array_",
                 "connect_", "move_", "turn_", "assign_", "place_")),
)


#: Which group gives up a name first when the message is too long.
_MENU_TRIM_ORDER = ("measuring", "placing", "editing", "finding")


def _menu(head: str) -> str:
    """The public names, grouped, trimmed to fit under the limit."""
    shown: dict = {label: [] for label, _ in _MENU_GROUPS}
    for name in sorted(set(__all__)):
        for label, prefixes in _MENU_GROUPS:
            if prefixes and name.startswith(prefixes):
                shown[label].append(name)
                break
        else:
            shown["measuring"].append(name)
    hidden = {label: 0 for label, _ in _MENU_GROUPS}
    while True:
        lines = []
        for label, _prefixes in _MENU_GROUPS:
            if not shown[label] and not hidden[label]:
                continue
            more = " and %d more" % hidden[label] if hidden[label] else ""
            lines.append("  %s: %s%s" % (label, ", ".join(shown[label]), more))
        text = "\n".join(lines)
        if len(head) + len(text) <= _MENU_LIMIT:
            return text
        # The verbs a caller invents are the ones worth showing in full, so
        # the reading group gives up its names first and the editing verbs
        # last.
        cut = next((label for label in _MENU_TRIM_ORDER
                    if len(shown[label]) > 1), "")
        if not cut:
            return text
        shown[cut].pop()
        hidden[cut] += 1


def __getattr__(name: str):
    """Tell a caller what this module has, when it asks for something else.

    A private or dunder name raises the plain error, so anything introspecting
    the module behaves as it would for any other module.
    """
    if name.startswith("_"):
        raise AttributeError("module %r has no attribute %r" % (__name__, name))
    head = "geom has no function %r. Available:\n" % name[:40]
    raise AttributeError(head + _menu(head))
