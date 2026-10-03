"""The runtime a gold edit script calls.

Every gold script is a short, readable Python file that opens a source model,
calls a handful of functions from this module and writes the result.  Two
properties matter and both are enforced here rather than in the caller.

*Determinism.*  Nothing in this module draws a random number, reads the clock or
depends on dictionary order.  Identifiers of created entities are passed in by
the caller, so re-running a script on a fresh copy of the same source model
produces the same model again, entity for entity.

*Units.*  Every length a script passes is in metres.  The model's own length
unit is read from the file and applied here, so one script text works whether
the source model is written in metres, millimetres or feet.
"""

from __future__ import annotations

import math
from typing import Any, Iterable, Optional, Sequence

import numpy as np

import ifcopenshell
import ifcopenshell.api.root
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# Elements a wall may host through an opening.
FILLING_CLASSES = ("IfcDoor", "IfcWindow")


# ----------------------------------------------------------------- utilities


def unit_scale(model: ifcopenshell.file) -> float:
    """Metres per model length unit (1.0 for metres, 0.001 for millimetres)."""
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    return float(scale) if scale else 1.0


def entity(model: ifcopenshell.file, guid: str):
    """The entity carrying ``guid``; raises if the model does not have it."""
    return model.by_guid(guid)


def owner_history(model: ifcopenshell.file):
    """An owner history to stamp on created entities, or None.

    IFC2X3 makes ``IfcRoot.OwnerHistory`` mandatory, so a created entity has to
    carry one.  Reusing the file's own history keeps the result deterministic
    and avoids inventing an author for an edit.
    """
    histories = model.by_type("IfcOwnerHistory")
    if not histories:
        return None
    return sorted(histories, key=lambda h: h.id())[0]


def _parent_rotation(product) -> np.ndarray:
    """Rotation of the coordinate system a product's placement is written in."""
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        return np.identity(3)
    parent = placement.PlacementRelTo
    if parent is None:
        return np.identity(3)
    matrix = ifcopenshell.util.placement.get_local_placement(parent)
    return np.array(matrix)[:3, :3]


def _sole_owner(model: ifcopenshell.file, item, owner) -> bool:
    """True when ``item`` is referenced by ``owner`` and by nothing else."""
    inverses = model.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner


def _writable_location(model: ifcopenshell.file, placement):
    """The cartesian point a placement's origin may be written through.

    A model often shares one cartesian point between several placements.  When
    that is the case a fresh point is substituted first, so writing one
    element's position never moves another.
    """
    axis = placement.RelativePlacement
    if not _sole_owner(model, axis, placement):
        axis = model.create_entity(
            "IfcAxis2Placement3D",
            Location=axis.Location,
            Axis=axis.Axis,
            RefDirection=axis.RefDirection,
        )
        placement.RelativePlacement = axis
    point = axis.Location
    if not _sole_owner(model, point, axis):
        point = model.create_entity("IfcCartesianPoint",
                                    Coordinates=tuple(point.Coordinates))
        axis.Location = point
    return point


def body_representation(product):
    """The product's own ``Body`` shape representation, or None."""
    shape = getattr(product, "Representation", None)
    if shape is None:
        return None
    for representation in shape.Representations or ():
        if representation.RepresentationIdentifier == "Body":
            return representation
    return None


def sole_extrusion(model: ifcopenshell.file, product):
    """The single extruded solid that forms a product's body, or None.

    Returns the solid only when editing it can affect this product alone: the
    body holds exactly one extrusion, and that extrusion is used by exactly one
    shape representation (presentation styles and layer assignments are not
    counted, since they carry no geometry).
    """
    representation = body_representation(product)
    if representation is None or representation.RepresentationType != "SweptSolid":
        return None
    items = representation.Items or ()
    if len(items) != 1 or not items[0].is_a("IfcExtrudedAreaSolid"):
        return None
    solid = items[0]
    users = [i for i in model.get_inverse(solid) if i.is_a("IfcShapeRepresentation")]
    if len(users) != 1:
        return None
    shapes = [i for i in model.get_inverse(representation)
              if i.is_a("IfcProductDefinitionShape")]
    if len(shapes) != 1:
        return None
    products = [i for i in model.get_inverse(shapes[0]) if i.is_a("IfcProduct")]
    if len(products) != 1:
        return None
    return solid


def extrusion_world_direction(product, solid) -> np.ndarray:
    """Direction the solid is extruded along, in world axes."""
    matrix = np.array(ifcopenshell.util.placement.get_local_placement(
        product.ObjectPlacement))
    local = np.identity(4)
    position = solid.Position
    if position is not None:
        local = np.array(ifcopenshell.util.placement.get_axis2placement(position))
    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
    world = matrix[:3, :3] @ local[:3, :3] @ direction
    norm = float(np.linalg.norm(world))
    return world / norm if norm else world


# ------------------------------------------------------------ update family


def translate(model: ifcopenshell.file, guid: str,
              dx: float, dy: float, dz: float) -> None:
    """Move one element by a world-axis offset given in metres.

    The offset is rotated into the coordinate system the element's placement is
    written in, so the element ends up exactly ``(dx, dy, dz)`` further along
    the world axes however its own placement is oriented.  Anything placed
    relative to this element, an opening for instance, moves with it.
    """
    product = entity(model, guid)
    placement = product.ObjectPlacement
    scale = unit_scale(model)
    world = np.array([dx, dy, dz], dtype=float) / scale
    local = np.linalg.inv(_parent_rotation(product)) @ world
    point = _writable_location(model, placement)
    coordinates = list(point.Coordinates)
    for i in range(3):
        coordinates[i] = float(coordinates[i]) + float(local[i])
    point.Coordinates = tuple(coordinates)


def set_attribute(model: ifcopenshell.file, guid: str, name: str, value: Any) -> None:
    """Write one direct attribute of an element."""
    setattr(entity(model, guid), name, value)


def set_length_attribute(model: ifcopenshell.file, guid: str, name: str,
                         metres: float) -> None:
    """Write a length-valued attribute, converting metres to model units."""
    setattr(entity(model, guid), name, float(metres) / unit_scale(model))


def set_extrusion_depth(model: ifcopenshell.file, guid: str, depth: float) -> None:
    """Set the depth of the element's single extruded body, in metres."""
    product = entity(model, guid)
    solid = sole_extrusion(model, product)
    if solid is None:
        raise ValueError(f"{guid} has no single editable extrusion")
    solid.Depth = float(depth) / unit_scale(model)


def set_profile_dimension(model: ifcopenshell.file, guid: str,
                          dimension: str, value: float) -> None:
    """Set ``XDim`` or ``YDim`` of a rectangular extruded profile, in metres."""
    product = entity(model, guid)
    solid = sole_extrusion(model, product)
    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
        raise ValueError(f"{guid} has no rectangular extruded profile")
    profile = solid.SweptArea
    if len(model.get_inverse(profile)) != 1:
        profile = model.create_entity(
            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
            ProfileName=profile.ProfileName, Position=profile.Position,
            XDim=profile.XDim, YDim=profile.YDim)
        solid.SweptArea = profile
    setattr(profile, dimension, float(value) / unit_scale(model))


# ------------------------------------------------------------ delete family


def _redirect(model: ifcopenshell.file, old, new) -> None:
    """Point everything that refers to ``old`` at ``new`` instead."""
    for referrer in model.get_inverse(old):
        for index, value in enumerate(referrer):
            if value == old:
                referrer[index] = new
            elif isinstance(value, tuple) and old in value:
                referrer[index] = tuple(new if item == old else item
                                        for item in value)


def freeze_new_histories(model: ifcopenshell.file,
                         before: set[int]) -> None:
    """Take the clock and the ambiguity out of an owner history an edit created.

    Unassigning a material or a type stamps a fresh ``IfcOwnerHistory`` with the
    current time, and stamps more than one of them, identical in content.  Both
    facts made the same edit write a different file on every run: the timestamp
    moved with the clock, and which of two identical histories a relationship
    pointed at depended on the hash seed of the process.  Neither belongs in a
    published model either, since both record the moment of generation rather
    than anything about the building.

    A model that already has an owner history keeps only that one: every
    reference to a created history is redirected to it and the created history
    is removed, so the edit adds no ownership record at all.  A model with none
    keeps a single created history, its two timestamps set to zero.
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
        _redirect(model, history, canonical)
        model.remove(history)


# Relationship families whose member attribute the schema declares a SET, so
# its order carries no meaning and may be normalised.  Ordered aggregates such
# as IfcRelNests are deliberately absent.
_SET_MEMBERS: tuple[tuple[str, str], ...] = (
    ("IfcRelDefines", "RelatedObjects"),
    ("IfcRelAssociates", "RelatedObjects"),
    ("IfcRelAssigns", "RelatedObjects"),
    ("IfcRelAggregates", "RelatedObjects"),
    ("IfcRelContainedInSpatialStructure", "RelatedElements"),
)


def _set_members(model: ifcopenshell.file):
    """Every relationship whose member attribute is a schema SET, with that name."""
    for base, attribute in _SET_MEMBERS:
        for relationship in model.by_type(base):
            members = getattr(relationship, attribute, None)
            if members is not None:
                yield relationship, attribute, members


def snapshot_set_members(model: ifcopenshell.file) -> dict[int, frozenset]:
    """What each SET-valued relationship holds, before an edit changes it."""
    return {relationship.id(): frozenset(m.id() for m in members)
            for relationship, _attribute, members in _set_members(model)}


def canonicalize_changed_sets(model: ifcopenshell.file,
                              before: dict[int, frozenset]) -> None:
    """Order the members of every SET-valued relationship the edit changed.

    Removing a product unassigns it from the types, materials and property sets
    it shared with others, and IfcOpenShell rebuilds those SET-valued
    attributes from an unordered container.  The order it produces depends on
    the hash seed of the process that ran the edit, so the same script wrote a
    different file in a different process while saying exactly the same thing.
    Sorting the members of the relationships that actually changed removes the
    only source of that difference, and touches nothing the edit left alone.
    """
    for relationship, attribute, members in _set_members(model):
        current = frozenset(m.id() for m in members)
        if before.get(relationship.id()) == current:
            continue
        setattr(relationship, attribute,
                tuple(sorted(members, key=lambda m: m.id())))


def _geom():
    """The sandbox's helper library, which the gold shares its deletions with.

    A deletion is the one edit where the model the gold writes and the model
    the sandbox writes have to agree entity for entity, so both run the same
    code rather than two copies of the same rule.
    """
    try:
        from modifc_harness import veribim_geom
    except ImportError:
        import sys
        from pathlib import Path

        harness = Path(__file__).resolve().parents[1] / "harness"
        if str(harness) not in sys.path:
            sys.path.insert(0, str(harness))
        from modifc_harness import veribim_geom
    return veribim_geom


def delete_element(model: ifcopenshell.file, guid: str) -> None:
    """Remove one element, what it holds, and the relationships it empties.

    Representations, placements, property sets, containment, aggregation,
    space boundaries and the openings the element carries all go with it, and
    so do the doors and windows those openings hold: a filling cannot exist
    without the host it fills.  Every relationship object the removal leaves
    with nothing on its related side goes as well, while a row that already
    named nothing before the edit stays as it was.
    """
    before = {h.id() for h in model.by_type("IfcOwnerHistory")}
    sets = snapshot_set_members(model)
    _geom().delete_element(entity(model, guid))
    freeze_new_histories(model, before)
    canonicalize_changed_sets(model, sets)


def delete_filling_with_opening(model: ifcopenshell.file, guid: str) -> None:
    """Remove a door or window, the opening it fills and their relationships.

    A wall is voided by an opening so that something can sit in the hole, so
    taking the door out without the opening leaves the wall cut for nothing.
    Both products go, and with them the ``IfcRelFillsElement`` that tied the two
    together and the ``IfcRelVoidsElement`` that tied the opening to the wall.
    """
    before = {h.id() for h in model.by_type("IfcOwnerHistory")}
    sets = snapshot_set_members(model)
    _geom().delete_filling(entity(model, guid))
    freeze_new_histories(model, before)
    canonicalize_changed_sets(model, sets)


# ------------------------------------------------------------ create family


def _context(model: ifcopenshell.file, like_guid: Optional[str]):
    """The representation context created geometry is written into.

    The context of an existing element's body is reused where one is named, so
    created geometry lands in the same subcontext as the model's own.
    """
    if like_guid:
        representation = body_representation(entity(model, like_guid))
        if representation is not None and representation.ContextOfItems is not None:
            return representation.ContextOfItems
    for context in model.by_type("IfcGeometricRepresentationSubContext"):
        if context.ContextIdentifier == "Body":
            return context
    roots = [c for c in model.by_type("IfcGeometricRepresentationContext")
             if not c.is_a("IfcGeometricRepresentationSubContext")
             and (c.CoordinateSpaceDimension or 3) == 3]
    # A file that names its context "Model" is the common case; some exporters
    # leave the type blank and ship a single context, which is then the one.
    for context in roots:
        if context.ContextType == "Model":
            return context
    if roots:
        return roots[0]
    raise ValueError("model has no three-dimensional representation context")


def _box_shape(model: ifcopenshell.file, context, length: float, width: float,
               height: float, scale: float):
    """A rectangular extrusion of the given size, its base corner at the origin."""
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


def _placement(model: ifcopenshell.file, parent, x: float, y: float, z: float,
               scale: float):
    """A local placement at ``(x, y, z)`` metres inside the parent's system."""
    return model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=parent,
        RelativePlacement=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity(
                "IfcCartesianPoint",
                Coordinates=(x / scale, y / scale, z / scale)),
            Axis=None, RefDirection=None))


def _contain_in_storey(model: ifcopenshell.file, storey, product,
                       relation_guid: str) -> None:
    """Put a product into a storey's containment relationship."""
    for relation in storey.ContainsElements or ():
        relation.RelatedElements = tuple(relation.RelatedElements) + (product,)
        return
    model.create_entity(
        "IfcRelContainedInSpatialStructure", GlobalId=relation_guid,
        OwnerHistory=owner_history(model), Name=None, Description=None,
        RelatedElements=[product], RelatingStructure=storey)


def _aggregate_into_storey(model: ifcopenshell.file, storey, product,
                           relation_guid: str) -> None:
    """Put a spatial element under a storey's aggregation relationship."""
    for relation in storey.IsDecomposedBy or ():
        if relation.is_a("IfcRelAggregates"):
            relation.RelatedObjects = tuple(relation.RelatedObjects) + (product,)
            return
    model.create_entity(
        "IfcRelAggregates", GlobalId=relation_guid,
        OwnerHistory=owner_history(model), Name=None, Description=None,
        RelatingObject=storey, RelatedObjects=[product])


def add_box_element(model: ifcopenshell.file, ifc_class: str, guid: str,
                    name: Optional[str], storey_guid: str, relation_guid: str,
                    x: float, y: float, z: float, length: float, width: float,
                    height: float, predefined_type: Optional[str] = None,
                    like_guid: Optional[str] = None,
                    long_name: Optional[str] = None):
    """Create a box-shaped element on a storey.

    ``x``, ``y`` and ``z`` are metres in the storey's own coordinate system and
    ``length``, ``width`` and ``height`` are the box's size in metres along the
    storey's x, y and z axes.  The element is placed relative to the storey and
    is either contained in it, or, for a space, aggregated under it.
    """
    storey = entity(model, storey_guid)
    scale = unit_scale(model)
    history = owner_history(model)
    product = model.create_entity(ifc_class, GlobalId=guid, OwnerHistory=history,
                                  Name=name, Description=None)
    product.ObjectPlacement = _placement(model, storey.ObjectPlacement, x, y, z,
                                         scale)
    product.Representation = _box_shape(model, _context(model, like_guid), length,
                                        width, height, scale)
    if predefined_type is not None:
        product.PredefinedType = predefined_type
    if ifc_class == "IfcSpace":
        product.LongName = long_name
        if hasattr(product, "CompositionType"):
            product.CompositionType = "ELEMENT"
        if hasattr(product, "InteriorOrExteriorSpace"):
            product.InteriorOrExteriorSpace = "INTERNAL"
        _aggregate_into_storey(model, storey, product, relation_guid)
    else:
        _contain_in_storey(model, storey, product, relation_guid)
    return product


def add_filling(model: ifcopenshell.file, ifc_class: str, guid: str,
                name: Optional[str], host_guid: str, opening_guid: str,
                voids_guid: str, fills_guid: str, relation_guid: str,
                along: float, across: float, sill: float, width: float,
                height: float, thickness: float,
                predefined_type: Optional[str] = None,
                filling_across: Optional[float] = None,
                filling_depth: Optional[float] = None):
    """Cut an opening in a wall and fill it with a door or a window.

    ``along``, ``across`` and ``sill`` are metres in the wall's own coordinate
    system: distance along the wall, the near face of the opening across the
    wall, and the height of the opening's base.  ``width`` and ``height`` size
    the opening and ``thickness`` is how far it cuts through the wall.  The
    opening is placed relative to the wall, so the filling follows the wall if
    the wall is later moved.

    ``filling_across`` and ``filling_depth`` give the leaf its own position and
    depth across the wall, so the opening can cut past both wall faces while the
    door or window sits flush with them.  Left out, the leaf takes the opening's
    own position and depth.
    """
    host = entity(model, host_guid)
    scale = unit_scale(model)
    history = owner_history(model)
    storey = _containing_storey(host)
    if storey is None:
        raise ValueError(f"{host_guid} is not contained in a storey")

    opening = model.create_entity("IfcOpeningElement", GlobalId=opening_guid,
                                  OwnerHistory=history, Name="Opening",
                                  Description=None)
    opening.ObjectPlacement = _placement(model, host.ObjectPlacement, along,
                                         across, sill, scale)
    opening.Representation = _box_shape(model, _context(model, host_guid), width,
                                        thickness, height, scale)
    if hasattr(opening, "PredefinedType"):
        opening.PredefinedType = "OPENING"
    model.create_entity("IfcRelVoidsElement", GlobalId=voids_guid,
                        OwnerHistory=history, Name=None, Description=None,
                        RelatingBuildingElement=host, RelatedOpeningElement=opening)

    leaf_across = across if filling_across is None else float(filling_across)
    leaf_depth = thickness if filling_depth is None else float(filling_depth)
    filling = model.create_entity(ifc_class, GlobalId=guid, OwnerHistory=history,
                                 Name=name, Description=None)
    filling.ObjectPlacement = _placement(model, host.ObjectPlacement, along,
                                         leaf_across, sill, scale)
    filling.Representation = _box_shape(model, _context(model, host_guid), width,
                                        leaf_depth, height, scale)
    filling.OverallHeight = height / scale
    filling.OverallWidth = width / scale
    if predefined_type is not None and hasattr(filling, "PredefinedType"):
        filling.PredefinedType = predefined_type
    model.create_entity("IfcRelFillsElement", GlobalId=fills_guid,
                        OwnerHistory=history, Name=None, Description=None,
                        RelatingOpeningElement=opening, RelatedBuildingElement=filling)
    _contain_in_storey(model, storey, filling, relation_guid)
    return filling


def _containing_storey(product):
    for relation in getattr(product, "ContainedInStructure", ()) or ():
        structure = relation.RelatingStructure
        if structure.is_a("IfcBuildingStorey"):
            return structure
        while structure is not None:
            if structure.is_a("IfcBuildingStorey"):
                return structure
            parents = getattr(structure, "Decomposes", ()) or ()
            structure = parents[0].RelatingObject if parents else None
    return None


# ------------------------------------------------- world-frame construction


def _placement_matrix(placement) -> np.ndarray:
    """The 4x4 matrix of a local placement, its translation in model units."""
    if placement is None:
        return np.identity(4)
    return np.array(ifcopenshell.util.placement.get_local_placement(placement),
                    dtype=float)


def world_to_parent(model: ifcopenshell.file, parent_placement,
                    x: float, y: float, z: float) -> tuple[float, float, float]:
    """A world point in metres, re-expressed in the parent placement's system.

    The result is still in metres, because the placement writers below convert
    metres to the model's own unit themselves.  A world coordinate in an
    instruction therefore reaches the model unchanged in meaning however the
    storey it hangs from is positioned.
    """
    scale = unit_scale(model)
    matrix = _placement_matrix(parent_placement)
    world = np.array([x, y, z], dtype=float) / scale
    local = np.linalg.inv(matrix[:3, :3]) @ (world - matrix[:3, 3])
    return (float(local[0] * scale), float(local[1] * scale),
            float(local[2] * scale))


def _world_aligned(placement) -> bool:
    """True when the placement's axes are the world axes, same sign and order."""
    rotation = _placement_matrix(placement)[:3, :3]
    return bool(np.abs(rotation - np.identity(3)).max() < 1e-3)


def add_box_element_world(model: ifcopenshell.file, ifc_class: str, guid: str,
                          name: Optional[str], storey_guid: str,
                          relation_guid: str, x: float, y: float, z: float,
                          length: float, width: float, height: float,
                          predefined_type: Optional[str] = None,
                          like_guid: Optional[str] = None,
                          long_name: Optional[str] = None):
    """Create a box-shaped element from world coordinates in metres.

    ``x``, ``y`` and ``z`` are the lowest corner of the box in the world frame
    and ``length``, ``width`` and ``height`` are its size along the world axes.
    The point is converted into the storey's own system here, so the numbers a
    work order quotes are the numbers the script carries.  A storey whose axes
    are turned against the world axes is refused rather than guessed at, since
    the size words would then not mean what they say.
    """
    storey = entity(model, storey_guid)
    if not _world_aligned(storey.ObjectPlacement):
        raise ValueError(f"{storey_guid} is not aligned with the world axes")
    local = world_to_parent(model, storey.ObjectPlacement, x, y, z)
    return add_box_element(model, ifc_class, guid, name, storey_guid,
                           relation_guid, local[0], local[1], local[2],
                           length, width, height, predefined_type, like_guid,
                           long_name)


def add_box_element_world_turned(model: ifcopenshell.file, ifc_class: str,
                                 guid: str, name: Optional[str],
                                 storey_guid: str, relation_guid: str,
                                 x: float, y: float, z: float, length: float,
                                 width: float, height: float,
                                 predefined_type: Optional[str] = None,
                                 like_guid: Optional[str] = None,
                                 long_name: Optional[str] = None):
    """Create a box on a storey whose own axes are turned against the world's.

    ``x``, ``y`` and ``z`` are the world point the element's base corner stands
    at, in metres, and ``length``, ``width`` and ``height`` are its size along
    the storey's own axes, which is how a work order states an element built on
    a skewed grid.  The storey's placement has to be a turn about the vertical
    and nothing else, so the conversion is exact.
    """
    storey = entity(model, storey_guid)
    matrix = _placement_matrix(storey.ObjectPlacement)
    rotation = np.array(matrix, dtype=float)[:3, :3]
    if abs(float(rotation[2, 2]) - 1.0) > 1e-6 or \
            abs(float(np.linalg.det(rotation[:2, :2])) - 1.0) > 1e-6:
        raise ValueError(f"{storey_guid} is not turned about the vertical axis")
    local = world_to_parent(model, storey.ObjectPlacement, x, y, z)
    return add_box_element(model, ifc_class, guid, name, storey_guid,
                           relation_guid, local[0], local[1], local[2],
                           length, width, height, predefined_type, like_guid,
                           long_name)


# How a wall's thickness is written out from the line its faces follow.
THICKNESS_DIRECTIONS = {"+x": (0, 1.0), "-x": (0, -1.0),
                        "+y": (1, 1.0), "-y": (1, -1.0)}


def add_wall_span(model: ifcopenshell.file, guid: str, name: Optional[str],
                  storey_guid: str, relation_guid: str,
                  x1: float, y1: float, z1: float,
                  x2: float, y2: float, z2: float,
                  thickness: float, thickness_direction: str, height: float,
                  predefined_type: Optional[str] = None,
                  like_guid: Optional[str] = None):
    """Create a wall along the world-frame line from one point to another.

    The wall runs from ``(x1, y1, z1)`` to ``(x2, y2, z2)``, which must lie on
    one world axis and at one elevation.  ``thickness_direction`` says which way
    the wall's body extends from that line, as ``+x``, ``-x``, ``+y`` or ``-y``,
    and ``height`` is how far it rises from the line.
    """
    if thickness_direction not in THICKNESS_DIRECTIONS:
        raise ValueError(f"unknown thickness direction {thickness_direction}")
    if abs(float(z1) - float(z2)) > 1e-6:
        raise ValueError("a wall span stands at one elevation")
    delta = np.array([float(x2) - float(x1), float(y2) - float(y1)], dtype=float)
    run = int(np.argmax(np.abs(delta)))
    if abs(float(delta[1 - run])) > 1e-6:
        raise ValueError("a wall span runs along one world axis")
    across, sign = THICKNESS_DIRECTIONS[thickness_direction]
    if across == run:
        raise ValueError("a wall's thickness runs across its length")
    lo = [min(float(x1), float(x2)), min(float(y1), float(y2))]
    size = [0.0, 0.0]
    size[run] = float(abs(delta[run]))
    size[across] = float(thickness)
    if sign < 0:
        lo[across] -= float(thickness)
    return add_box_element_world(model, "IfcWall", guid, name, storey_guid,
                                 relation_guid, lo[0], lo[1], float(z1),
                                 size[0], size[1], float(height),
                                 predefined_type, like_guid, None)


# ----------------------------------------------------------- relation family


def add_space_boundary(model: ifcopenshell.file, guid: str, space_guid: str,
                       element_guid: str,
                       physical_or_virtual: str = "PHYSICAL",
                       internal_or_external: str = "INTERNAL",
                       name: Optional[str] = None):
    """Record that one element bounds one space.

    Written as an ``IfcRelSpaceBoundary``, the first-level boundary both IFC2X3
    and IFC4 carry, with no connection geometry: the relationship states which
    element bounds which space, and the surface between them is left to the
    exporter that owns it.
    """
    space = entity(model, space_guid)
    element = entity(model, element_guid)
    return model.create_entity(
        "IfcRelSpaceBoundary", GlobalId=guid, OwnerHistory=owner_history(model),
        Name=name, Description=None, RelatingSpace=space,
        RelatedBuildingElement=element, ConnectionGeometry=None,
        PhysicalOrVirtualBoundary=physical_or_virtual,
        InternalOrExternalBoundary=internal_or_external)


def connect_elements(model: ifcopenshell.file, guid: str, relating_guid: str,
                     related_guid: str, name: Optional[str] = None):
    """Record that two elements are connected, as an ``IfcRelConnectsElements``."""
    relating = entity(model, relating_guid)
    related = entity(model, related_guid)
    return model.create_entity(
        "IfcRelConnectsElements", GlobalId=guid,
        OwnerHistory=owner_history(model), Name=name, Description=None,
        ConnectionGeometry=None, RelatingElement=relating,
        RelatedElement=related)


# ----------------------------------------------- reading a body for a script


def world_extent(model: ifcopenshell.file, guid: str
                 ) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """World box of an element's single extruded body, in metres.

    Read from the profile and the placement rather than from a triangulation,
    so a gold script can measure a neighbour without a geometry kernel.  Returns
    ``None`` when the element carries no body this arithmetic can read.
    """
    product = entity(model, guid)
    solid = sole_extrusion(model, product)
    if solid is None:
        return None
    scale = unit_scale(model)
    points = _profile_corners(solid.SweptArea)
    if points is None:
        return None
    points = points * scale
    depth = float(solid.Depth) * scale
    position = np.identity(4)
    if solid.Position is not None:
        position = np.array(ifcopenshell.util.placement.get_axis2placement(
            solid.Position), dtype=float)
        position[:3, 3] = position[:3, 3] * scale
    corners = np.array([[px, py, pz]
                        for px, py in points
                        for pz in (0.0, depth)], dtype=float)
    corners = (position[:3, :3] @ corners.T).T + position[:3, 3]
    matrix = _placement_matrix(product.ObjectPlacement)
    matrix = matrix.copy()
    matrix[:3, 3] = matrix[:3, 3] * scale
    world = (matrix[:3, :3] @ corners.T).T + matrix[:3, 3]
    return world.min(axis=0), world.max(axis=0)


def _profile_corners(profile) -> Optional[np.ndarray]:
    """Corner points of a profile in its own plane, in model units."""
    if profile.is_a("IfcRectangleProfileDef"):
        half = np.array([float(profile.XDim) / 2.0, float(profile.YDim) / 2.0])
        points = np.array([[-half[0], -half[1]], [half[0], -half[1]],
                           [half[0], half[1]], [-half[0], half[1]]])
    elif profile.is_a("IfcArbitraryClosedProfileDef"):
        curve = profile.OuterCurve
        if not curve.is_a("IfcPolyline"):
            return None
        points = np.array([p.Coordinates[:2] for p in curve.Points], dtype=float)
    else:
        return None
    position = getattr(profile, "Position", None)
    if position is not None:
        origin = np.array(position.Location.Coordinates, dtype=float)
        if position.RefDirection is not None:
            ref = np.array(position.RefDirection.DirectionRatios, dtype=float)
            norm = float(np.linalg.norm(ref)) or 1.0
            ref = ref / norm
            rotation = np.array([[ref[0], -ref[1]], [ref[1], ref[0]]])
        else:
            rotation = np.identity(2)
        points = (rotation @ points.T).T + origin
    return points


# =====================================================================
# 0.6.0: the layer 1 operations and the layer 5 scopes.
#
# Every function below writes one operation of the requirement taxonomy's
# first layer.  Two properties carry over from the earlier sections and are
# enforced here rather than in the caller: nothing reads the clock or a
# random source, and every length crossing the interface is in metres.
# =====================================================================


def _writable_axis(model: ifcopenshell.file, placement):
    """The placement's own axis triple, substituted when it is shared.

    A model often shares one axis placement, or the point inside it, between
    several elements.  Writing through a shared one would turn or move an
    element the edit was never about, so a private copy is substituted first.
    """
    _writable_location(model, placement)
    return placement.RelativePlacement


def _sole_product(model: ifcopenshell.file, placement, product) -> bool:
    """True when this product is the only one the placement positions."""
    users = [i for i in model.get_inverse(placement)
             if i.is_a("IfcProduct") and i.id() != product.id()]
    return not users


def _write_world_frame(model: ifcopenshell.file, product,
                       world: np.ndarray) -> None:
    """Give a product the world frame ``world``, keeping its parent placement.

    ``world`` is a 4x4 matrix whose translation is in the model's own length
    unit, which is the unit IfcOpenShell's placement utility reads and writes.
    Anything placed relative to this product, an opening for instance, keeps
    its own offset and therefore follows.
    """
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        raise ValueError(f"{product.GlobalId} has no local placement to write")
    if not _sole_product(model, placement, product):
        raise ValueError(f"{product.GlobalId} shares its placement")
    parent = _placement_matrix(placement.PlacementRelTo)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = _writable_axis(model, placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = model.create_entity(
        "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = model.create_entity(
        "IfcDirection", DirectionRatios=tuple(float(v) for v in local[:3, 0]))


def _clean(matrix: np.ndarray) -> np.ndarray:
    """A matrix with the arithmetic noise of a trigonometric call removed."""
    return np.round(np.asarray(matrix, dtype=float), 12) + 0.0


def _translation(vector) -> np.ndarray:
    matrix = np.identity(4)
    matrix[:3, 3] = np.asarray(vector, dtype=float)
    return matrix


def rotate(model: ifcopenshell.file, guid: str, degrees: float,
           pivot_x: float, pivot_y: float) -> None:
    """Turn one element about the vertical axis by a stated angle.

    ``degrees`` is measured anticlockwise seen from above and ``pivot_x`` and
    ``pivot_y`` are the world point the element turns about, in metres.  The
    element's own placement is rewritten, so its openings and its fillings turn
    with it.
    """
    product = entity(model, guid)
    scale = unit_scale(model)
    angle = math.radians(float(degrees))
    turn = np.identity(4)
    turn[0, 0], turn[0, 1] = math.cos(angle), -math.sin(angle)
    turn[1, 0], turn[1, 1] = math.sin(angle), math.cos(angle)
    pivot = np.array([float(pivot_x) / scale, float(pivot_y) / scale, 0.0])
    about = _translation(pivot) @ _clean(turn) @ _translation(-pivot)
    _write_world_frame(model, product,
                       _clean(about @ _placement_matrix(product.ObjectPlacement)))


def _identity_position(solid) -> bool:
    """True when the solid's own position adds no rotation to the element's frame."""
    position = solid.Position
    if position is None:
        return True
    axis = position.Axis
    reference = position.RefDirection
    if axis is not None:
        ratios = np.array(axis.DirectionRatios, dtype=float)
        if float(np.abs(ratios - np.array([0.0, 0.0, 1.0])).max()) > 1e-6:
            return False
    if reference is not None:
        ratios = np.array(reference.DirectionRatios, dtype=float)
        if float(np.abs(ratios[:2] - np.array([1.0, 0.0])).max()) > 1e-6:
            return False
    return True


def mirrorable_body(model: ifcopenshell.file, product):
    """The element's body and its own x-centre, when a mirror can be written.

    A mirror is exact only where the shape can be flipped as well as the frame.
    The shape has to be one extrusion, swept upwards along the element's own
    vertical, over a rectangle or over a closed polyline with no voids, and the
    extrusion has to add no rotation of its own.  Anything else returns ``None``
    and the caller refuses the edit rather than mirroring the frame alone, which
    would move a shape a wall's mitred end makes asymmetric.
    """
    solid = sole_extrusion(model, product)
    if solid is None or not _identity_position(solid):
        return None
    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
    if float(np.abs(direction - np.array([0.0, 0.0, 1.0])).max()) > 1e-6:
        return None
    profile = solid.SweptArea
    if profile.is_a("IfcArbitraryProfileDefWithVoids"):
        return None
    if profile.is_a("IfcArbitraryClosedProfileDef"):
        if not profile.OuterCurve.is_a("IfcPolyline"):
            return None
        # The flip below is written on the curve's own points, so a profile
        # drawn in a system of its own is refused rather than flipped about the
        # wrong line.
        reference = getattr(profile, "Position", None)
        if reference is not None:
            location = np.array(reference.Location.Coordinates, dtype=float)
            if float(np.abs(location).max()) > 1e-9:
                return None
            if reference.RefDirection is not None:
                ratios = np.array(reference.RefDirection.DirectionRatios,
                                  dtype=float)
                if float(np.abs(ratios - np.array([1.0, 0.0])).max()) > 1e-6:
                    return None
    elif not profile.is_a("IfcRectangleProfileDef"):
        return None
    points = _profile_corners(profile)
    if points is None or len(points) < 3:
        return None
    scale = unit_scale(model)
    offset = 0.0
    if solid.Position is not None:
        offset = float(np.array(ifcopenshell.util.placement.get_axis2placement(
            solid.Position), dtype=float)[0, 3])
    centre = (float(points[:, 0].min()) + float(points[:, 0].max())) / 2.0
    return solid, (centre + offset) * scale


def _mirror_profile(model: ifcopenshell.file, solid) -> None:
    """Flip the swept profile about its own x-centre, in place.

    A profile the model shares with other elements is copied first, so flipping
    one element's shape never flips another's.
    """
    profile = solid.SweptArea
    if profile.is_a("IfcRectangleProfileDef"):
        # A rectangle is its own mirror image about the centre it is drawn on.
        return
    curve = profile.OuterCurve
    coordinates = [tuple(float(v) for v in point.Coordinates)
                   for point in curve.Points]
    closed = len(coordinates) > 1 and coordinates[0] == coordinates[-1]
    body = coordinates[:-1] if closed else coordinates
    axis = (min(c[0] for c in body) + max(c[0] for c in body))
    flipped = [(axis - c[0],) + tuple(c[1:]) for c in body]
    # Reflecting a closed outline reverses the direction it is drawn in, so the
    # points are put back in the order that keeps the outline wound as it was.
    flipped = [flipped[0]] + flipped[1:][::-1]
    if closed:
        flipped = flipped + [flipped[0]]
    if len(model.get_inverse(profile)) != 1:
        profile = model.create_entity(
            "IfcArbitraryClosedProfileDef", ProfileType=profile.ProfileType,
            ProfileName=profile.ProfileName, OuterCurve=curve)
        solid.SweptArea = profile
    if len(model.get_inverse(curve)) != 1:
        curve = model.create_entity("IfcPolyline", Points=list(curve.Points))
        profile.OuterCurve = curve
    curve.Points = [model.create_entity("IfcCartesianPoint", Coordinates=point)
                    for point in flipped]


def mirror(model: ifcopenshell.file, guid: str, point_x: float, point_y: float,
           normal_x: float, normal_y: float) -> None:
    """Reflect one element across a vertical plane, in world metres.

    The plane passes through ``(point_x, point_y)`` and its normal lies along
    ``(normal_x, normal_y)``, both in the world frame.  A reflection turns a
    right-handed frame into a left-handed one, which IFC does not carry, so the
    edit writes it as a proper rotation of the element's frame together with a
    flip of the element's own profile.  The two compose to the reflection
    exactly, and an element whose shape cannot be flipped is refused.
    """
    product = entity(model, guid)
    body = mirrorable_body(model, product)
    if body is None:
        raise ValueError(f"{guid} has no body a mirror can be written for")
    solid, centre = body
    scale = unit_scale(model)
    normal = np.array([float(normal_x), float(normal_y), 0.0], dtype=float)
    length = float(np.linalg.norm(normal))
    if length < 1e-9:
        raise ValueError("a mirror plane needs a horizontal normal")
    normal = normal / length
    reflect = np.identity(4)
    reflect[:3, :3] = np.identity(3) - 2.0 * np.outer(normal, normal)
    point = np.array([float(point_x) / scale, float(point_y) / scale, 0.0])
    plane = _translation(point) @ _clean(reflect) @ _translation(-point)
    flip = np.identity(4)
    flip[0, 0] = -1.0
    flip[0, 3] = 2.0 * centre / scale
    world = _placement_matrix(product.ObjectPlacement)
    _mirror_profile(model, solid)
    _write_world_frame(model, product, _clean(plane @ world @ flip))


# --------------------------------------------------------- property values


#: How a property value is written into the model, by the name of its type.
PROPERTY_VALUE_TYPES = ("IfcLabel", "IfcBoolean", "IfcText", "IfcInteger",
                        "IfcReal", "IfcThermalTransmittanceMeasure",
                        "IfcLengthMeasure", "IfcIdentifier")


def _own_property_set(model: ifcopenshell.file, product, pset_name: str,
                      pset_guid: str, relation_guid: str):
    """The element's own property set of that name, created or split off.

    A property set the model shares between several elements is copied for this
    element first, so writing a value here never writes it on another element.
    """
    history = owner_history(model)
    for relation in model.by_type("IfcRelDefinesByProperties"):
        definition = relation.RelatingPropertyDefinition
        if definition is None or not definition.is_a("IfcPropertySet"):
            continue
        if (definition.Name or "") != pset_name:
            continue
        members = list(relation.RelatedObjects or ())
        if product not in members:
            continue
        if len(members) == 1 and len(model.get_inverse(definition)) == 1:
            return definition
        # The set is shared, so this element gets a copy of it and the shared
        # one keeps the elements the edit is not about.
        relation.RelatedObjects = tuple(m for m in members if m != product)
        copy = model.create_entity(
            "IfcPropertySet", GlobalId=pset_guid, OwnerHistory=history,
            Name=definition.Name, Description=definition.Description,
            HasProperties=[_copy_property(model, p)
                           for p in definition.HasProperties or ()])
        model.create_entity(
            "IfcRelDefinesByProperties", GlobalId=relation_guid,
            OwnerHistory=history, Name=None, Description=None,
            RelatedObjects=[product], RelatingPropertyDefinition=copy)
        return copy
    pset = model.create_entity("IfcPropertySet", GlobalId=pset_guid,
                               OwnerHistory=history, Name=pset_name,
                               Description=None, HasProperties=[])
    model.create_entity("IfcRelDefinesByProperties", GlobalId=relation_guid,
                        OwnerHistory=history, Name=None, Description=None,
                        RelatedObjects=[product],
                        RelatingPropertyDefinition=pset)
    return pset


def _copy_property(model: ifcopenshell.file, prop):
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


def set_property_value(model: ifcopenshell.file, guid: str, pset_name: str,
                       property_name: str, value: Any, value_type: str,
                       pset_guid: str, relation_guid: str) -> None:
    """Write one property-set value on an element, creating the set if absent.

    ``value_type`` names the IFC value type the number, string or flag is
    written as, so a fire rating reaches the model as an ``IfcLabel`` and a
    thermal transmittance as an ``IfcThermalTransmittanceMeasure``.  The value
    is carried by an ``IfcPropertySingleValue`` inside an ``IfcPropertySet``
    that the element owns through an ``IfcRelDefinesByProperties``.
    """
    if value_type not in PROPERTY_VALUE_TYPES:
        raise ValueError(f"unsupported property value type {value_type}")
    product = entity(model, guid)
    pset = _own_property_set(model, product, pset_name, pset_guid,
                             relation_guid)
    nominal = model.create_entity(value_type, value)
    for prop in pset.HasProperties or ():
        if prop.is_a("IfcPropertySingleValue") and prop.Name == property_name:
            prop.NominalValue = nominal
            return
    prop = model.create_entity("IfcPropertySingleValue", Name=property_name,
                               NominalValue=nominal, Unit=None)
    pset.HasProperties = tuple(pset.HasProperties or ()) + (prop,)


# ------------------------------------------------------ material and type


def _detach(model: ifcopenshell.file, relation, product) -> None:
    """Drop one product from a relationship, removing the relationship if empty."""
    members = [m for m in (relation.RelatedObjects or ()) if m != product]
    if members:
        relation.RelatedObjects = tuple(members)
    else:
        model.remove(relation)


def assign_material(model: ifcopenshell.file, guid: str, material_name: str,
                    relation_guid: str) -> None:
    """Associate one element with a material, by name.

    A material the file already carries under that name is reused; otherwise one
    is created.  An element carries one material association, so the association
    it already had is dropped first.
    """
    product = entity(model, guid)
    material = None
    for candidate in sorted(model.by_type("IfcMaterial"), key=lambda m: m.id()):
        if (candidate.Name or "") == material_name:
            material = candidate
            break
    if material is None:
        material = model.create_entity("IfcMaterial", Name=material_name)
    for relation in list(model.by_type("IfcRelAssociatesMaterial")):
        if product in (relation.RelatedObjects or ()):
            _detach(model, relation, product)
    model.create_entity("IfcRelAssociatesMaterial", GlobalId=relation_guid,
                        OwnerHistory=owner_history(model), Name=None,
                        Description=None, RelatedObjects=[product],
                        RelatingMaterial=material)


def assign_type(model: ifcopenshell.file, guid: str, type_guid: str,
                relation_guid: str) -> None:
    """Assign one element to an existing type object.

    Written as an ``IfcRelDefinesByType``.  An element is typed once, so the
    type it already had is dropped first, and an existing relationship for the
    new type takes the element rather than a second relationship being written.
    """
    product = entity(model, guid)
    type_object = entity(model, type_guid)
    for relation in list(model.by_type("IfcRelDefinesByType")):
        if product in (relation.RelatedObjects or ()):
            _detach(model, relation, product)
    existing = None
    for relation in sorted(model.by_type("IfcRelDefinesByType"),
                           key=lambda r: r.id()):
        if relation.RelatingType == type_object:
            existing = relation
            break
    if existing is not None:
        existing.RelatedObjects = tuple(existing.RelatedObjects or ()) + (product,)
        return
    model.create_entity("IfcRelDefinesByType", GlobalId=relation_guid,
                        OwnerHistory=owner_history(model), Name=None,
                        Description=None, RelatedObjects=[product],
                        RelatingType=type_object)


# --------------------------------------------------- containment and hosting


def _containment_of(model: ifcopenshell.file, product):
    """The relationship that puts a product in a spatial structure."""
    for relation in getattr(product, "ContainedInStructure", ()) or ():
        return relation
    for relation in getattr(product, "Decomposes", ()) or ():
        if relation.is_a("IfcRelAggregates"):
            return relation
    return None


def move_to_storey(model: ifcopenshell.file, guid: str, storey_guid: str,
                   relation_guid: str, keep_world: bool = True) -> None:
    """Move one element into another storey, in the model and in space.

    The element leaves the spatial-structure relationship it was in and joins
    the named storey's.  With ``keep_world`` true its placement is rewritten so
    it stands exactly where it stood; with ``keep_world`` false it keeps the
    coordinates it had inside its old storey and therefore rises or falls by the
    difference between the two storeys' elevations.
    """
    product = entity(model, guid)
    storey = entity(model, storey_guid)
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        raise ValueError(f"{guid} has no local placement to re-hang")
    if not _sole_product(model, placement, product):
        raise ValueError(f"{guid} shares its placement")
    world = _placement_matrix(placement)
    relation = _containment_of(model, product)
    if relation is not None:
        if relation.is_a("IfcRelAggregates"):
            members = [m for m in (relation.RelatedObjects or ()) if m != product]
            if members:
                relation.RelatedObjects = tuple(members)
            else:
                model.remove(relation)
        else:
            members = [m for m in (relation.RelatedElements or ())
                       if m != product]
            if members:
                relation.RelatedElements = tuple(members)
            else:
                model.remove(relation)
    if product.is_a("IfcSpatialStructureElement") or product.is_a("IfcSpace"):
        _aggregate_into_storey(model, storey, product, relation_guid)
    else:
        _contain_in_storey(model, storey, product, relation_guid)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        _write_world_frame(model, product, world)


def _hangs_from(product, placement) -> bool:
    """True when the product's placement is written under ``placement``."""
    current = getattr(product, "ObjectPlacement", None)
    while current is not None and current.is_a("IfcLocalPlacement"):
        if current.id() == placement.id():
            return True
        current = current.PlacementRelTo
    return False


def _replant(model: ifcopenshell.file, product, host, x: float, y: float,
             z: float, depth: Optional[float], scale: float) -> None:
    """Hang one product from a wall at a stated point in that wall's frame."""
    placement = product.ObjectPlacement
    if placement is None or not placement.is_a("IfcLocalPlacement"):
        raise ValueError(f"{product.GlobalId} has no local placement")
    if not _sole_product(model, placement, product):
        raise ValueError(f"{product.GlobalId} shares its placement")
    placement.PlacementRelTo = host.ObjectPlacement
    axis = _writable_axis(model, placement)
    axis.Location.Coordinates = (float(x) / scale, float(y) / scale,
                                 float(z) / scale)
    axis.Axis = None
    axis.RefDirection = None
    if depth is None:
        return
    solid = sole_extrusion(model, product)
    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
        raise ValueError(f"{product.GlobalId} has no rectangular profile")
    profile = solid.SweptArea
    if len(model.get_inverse(profile)) != 1:
        profile = model.create_entity(
            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
            ProfileName=profile.ProfileName, Position=profile.Position,
            XDim=profile.XDim, YDim=profile.YDim)
        solid.SweptArea = profile
    profile.YDim = float(depth) / scale


def rehost_filling(model: ifcopenshell.file, guid: str, host_guid: str,
                   along: float, across: float, sill: float,
                   leaf_along: float, leaf_across: float, leaf_sill: float,
                   thickness: float,
                   leaf_depth: Optional[float] = None) -> None:
    """Move a door or a window, with its opening, into another wall.

    The opening the element fills is re-pointed at the named wall, so the wall
    it left is healed and the wall it joins is cut instead.  ``along``,
    ``across`` and ``sill`` place the opening in the new wall's own coordinates
    and ``thickness`` is how far it cuts through.  The leaf is placed by its own
    three, which the caller works out so that the leaf keeps the offset from its
    opening that the model gave it.  A leaf the model hangs from its own opening
    follows the opening and is not moved twice, and a leaf whose body is not a
    rectangular extrusion keeps the body it has, which ``leaf_depth`` of
    ``None`` asks for.
    """
    filling = entity(model, guid)
    host = entity(model, host_guid)
    scale = unit_scale(model)
    fills = list(getattr(filling, "FillsVoids", ()) or ())
    if len(fills) != 1:
        raise ValueError(f"{guid} does not fill exactly one opening")
    opening = fills[0].RelatingOpeningElement
    voids = list(getattr(opening, "VoidsElements", ()) or ())
    if len(voids) != 1:
        raise ValueError(f"{guid} hangs in an opening that voids no one wall")
    voids[0].RelatingBuildingElement = host
    leaf_follows = _hangs_from(filling, opening.ObjectPlacement)
    _replant(model, opening, host, along, across, sill, thickness, scale)
    if not leaf_follows:
        _replant(model, filling, host, leaf_along, leaf_across, leaf_sill,
                 leaf_depth, scale)


# --------------------------------------------------------- copy and array


#: Entities a copied element shares with its original rather than duplicating:
#: the representation contexts, the placement it hangs from, and the units.
_COPY_SHARED = ("IfcGeometricRepresentationContext",
                "IfcGeometricRepresentationSubContext",
                "IfcRepresentationContext", "IfcLocalPlacement",
                "IfcOwnerHistory", "IfcMaterial", "IfcMaterialLayerSet",
                "IfcMaterialLayerSetUsage", "IfcMaterialLayer",
                "IfcPresentationLayerAssignment", "IfcStyledItem")


def copy_element(model: ifcopenshell.file, guid: str, new_guid: str,
                 dx: float, dy: float, dz: float, name: Optional[str],
                 relation_guid: str) -> Any:
    """Duplicate one element at a world-axis offset given in metres.

    The copy carries the original's class, its attributes and a duplicate of its
    body, under a new identifier and, where one is given, a new name.  It hangs
    from the same parent placement as the original and is put into the same
    storey, so the model holds it exactly as it holds the element it came from.
    """
    import ifcopenshell.util.element as element_util

    product = entity(model, guid)
    scale = unit_scale(model)
    history = owner_history(model)
    copy = model.create_entity(product.is_a(), GlobalId=new_guid,
                               OwnerHistory=history)
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
    origin = _placement_matrix(placement)
    local = np.linalg.inv(_placement_matrix(parent)) @ origin
    offset = np.linalg.inv(_placement_matrix(parent)[:3, :3]) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    axis = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity(
            "IfcCartesianPoint",
            Coordinates=tuple(float(v) for v in local[:3, 3] + offset)),
        Axis=model.create_entity(
            "IfcDirection",
            DirectionRatios=tuple(float(v) for v in local[:3, 2])),
        RefDirection=model.create_entity(
            "IfcDirection",
            DirectionRatios=tuple(float(v) for v in local[:3, 0])))
    copy.ObjectPlacement = model.create_entity(
        "IfcLocalPlacement", PlacementRelTo=parent, RelativePlacement=axis)
    if product.Representation is not None:
        copy.Representation = element_util.copy_deep(
            model, product.Representation, exclude=list(_COPY_SHARED))
    storey = _containing_storey(product)
    if storey is not None:
        if copy.is_a("IfcSpace"):
            _aggregate_into_storey(model, storey, copy, relation_guid)
        else:
            _contain_in_storey(model, storey, copy, relation_guid)
    return copy


def array_elements(model: ifcopenshell.file, guid: str, new_guids: Sequence[str],
                   dx: float, dy: float, dz: float, names: Sequence[Optional[str]],
                   relation_guids: Sequence[str]) -> None:
    """Copy one element several times at a fixed spacing along one direction.

    The nth copy stands n times ``(dx, dy, dz)`` from the original, in world
    metres, so the copies form an evenly spaced row.
    """
    for index, new_guid in enumerate(new_guids, start=1):
        name = names[index - 1] if index - 1 < len(names) else None
        relation = relation_guids[index - 1] if index - 1 < len(relation_guids) \
            else new_guid
        copy_element(model, guid, new_guid, float(dx) * index, float(dy) * index,
                     float(dz) * index, name, relation)


# ------------------------------------------------------------- replacement


def replace_filling(model: ifcopenshell.file, guid: str, ifc_class: str,
                    new_guid: str, name: Optional[str], host_guid: str,
                    opening_guid: str, voids_guid: str, fills_guid: str,
                    relation_guid: str, along: float, across: float,
                    sill: float, width: float, height: float,
                    thickness: float, predefined_type: Optional[str] = None,
                    filling_across: Optional[float] = None,
                    filling_depth: Optional[float] = None):
    """Replace a door by a window, or a window by a door, in the same wall.

    The element and the opening it filled are removed together, which leaves the
    wall whole, and an opening of the stated size is then cut in the same wall
    and filled with the new element.  The two halves are the operations a
    deletion and a creation already use, so what the model ends up holding is
    what a create task would have written.
    """
    delete_filling_with_opening(model, guid)
    return add_filling(model, ifc_class, new_guid, name, host_guid,
                       opening_guid, voids_guid, fills_guid, relation_guid,
                       along, across, sill, width, height, thickness,
                       predefined_type, filling_across, filling_depth)
