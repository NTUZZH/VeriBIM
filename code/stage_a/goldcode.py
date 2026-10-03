"""The gold edit, rewritten as code the harness sandbox can run.

A generated task ships its edit as a standalone script that calls the
generator's own runtime (``modifc_gen.goldlib``) and writes a new file. Neither
half of that is available to a model at evaluation time: the sandbox pre-binds
one open model as ``ifc`` and offers ``ifcopenshell`` and its api and util
packages, and nothing else. Training on the generator's script would teach an
import that does not exist and a file-writing idiom the protocol does not use.

This module therefore reads the gold script, recovers the sequence of edit
operations it performs, and emits the same edit as plain IfcOpenShell code
against the pre-bound model. The emitted code is what a competent answer to the
task looks like, and the trajectory it belongs to is only kept if running it in
the sandbox reproduces the gold edit to the verifier's satisfaction.

Two differences from the generator's runtime are deliberate:

*Identifiers of created entities come from ``guid.new()``.* The gold script
passes fixed GlobalIds so that regenerating a task reproduces it byte for byte.
A model cannot know those strings, and a training target that contains them
would teach it to invent identifiers. The verifier pairs created entities
geometrically rather than by identifier, so a fresh identifier costs nothing.

*Owner histories created by a deletion are not frozen.* The generator rewrites
their timestamps so a regenerated file is byte-identical to the published one.
That is a property of the data build, not of a correct edit, and none of the
three score axes reads a timestamp.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Optional

from .style import Style


@dataclass
class GoldCall:
    """One operation from the gold script."""

    func: str
    kwargs: dict[str, Any]
    comment: str = ""


def parse_gold_script(source: str) -> list[GoldCall]:
    """Recover the ordered edit operations from a gold script's ``apply_edit``."""
    tree = ast.parse(source)
    body = None
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "apply_edit":
            body = node
            break
    if body is None:
        raise ValueError("gold script has no apply_edit function")

    calls: list[GoldCall] = []
    for node in ast.walk(body):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
            continue
        if func.value.id != "goldlib":
            continue
        kwargs = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
        calls.append(GoldCall(func=func.attr, kwargs=kwargs))
    return calls


# --------------------------------------------------------------- helper code

def _helper_sole_owner(s: Style) -> str:
    return f"""def {s.name('sole_owner_fn')}(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner
"""


def _helper_body(s: Style) -> str:
    return f"""def {s.name('body_fn')}({s.name('product')}):
    shape = getattr({s.name('product')}, 'Representation', None)
    if shape is None:
        return None
    for representation in shape.Representations or ():
        if representation.RepresentationIdentifier == 'Body':
            return representation
    return None
"""


def _helper_extrusion(s: Style) -> str:
    return f"""def {s.name('extrusion_fn')}({s.name('product')}):
    representation = {s.name('body_fn')}({s.name('product')})
    if representation is None or representation.RepresentationType != 'SweptSolid':
        return None
    items = representation.Items or ()
    if len(items) != 1 or not items[0].is_a('IfcExtrudedAreaSolid'):
        return None
    return items[0]
"""


#: The order the generator's own donor search walks, so a created body lands in
#: the context an existing body of the model already uses.
_DONOR_CLASSES = "('IfcWall', 'IfcSlab', 'IfcSpace', 'IfcDoor', 'IfcWindow', 'IfcColumn')"


def _helper_context(s: Style) -> str:
    return f"""def {s.name('context_fn')}(like=None):
{s.comment('context', '    ')}    if like is None:
        for ifc_class in {_DONOR_CLASSES}:
            for candidate in ifc.by_type(ifc_class):
                if {s.name('body_fn')}(candidate) is not None:
                    like = candidate
                    break
            if like is not None:
                break
    if like is not None:
        representation = {s.name('body_fn')}(like)
        if representation is not None and representation.ContextOfItems is not None:
            return representation.ContextOfItems
    for candidate in ifc.by_type('IfcGeometricRepresentationSubContext'):
        if candidate.ContextIdentifier == 'Body':
            return candidate
    roots = [c for c in ifc.by_type('IfcGeometricRepresentationContext')
             if not c.is_a('IfcGeometricRepresentationSubContext')
             and (c.CoordinateSpaceDimension or 3) == 3]
    for candidate in roots:
        if candidate.ContextType == 'Model':
            return candidate
    return roots[0]
"""


def _helper_shape(s: Style) -> str:
    scale = s.name("scale")
    return f"""def {s.name('shape_fn')}({s.name('context')}, length, width, height):
    {s.name('profile')} = ifc.create_entity(
        'IfcRectangleProfileDef', ProfileType='AREA', ProfileName=None,
        Position=ifc.create_entity(
            'IfcAxis2Placement2D',
            Location=ifc.create_entity(
                'IfcCartesianPoint',
                Coordinates=(length / 2.0 / {scale}, width / 2.0 / {scale})),
            RefDirection=None),
        XDim=length / {scale}, YDim=width / {scale})
    {s.name('solid')} = ifc.create_entity(
        'IfcExtrudedAreaSolid', SweptArea={s.name('profile')},
        Position=ifc.create_entity(
            'IfcAxis2Placement3D',
            Location=ifc.create_entity('IfcCartesianPoint', Coordinates=(0.0, 0.0, 0.0)),
            Axis=None, RefDirection=None),
        ExtrudedDirection=ifc.create_entity('IfcDirection', DirectionRatios=(0.0, 0.0, 1.0)),
        Depth=height / {scale})
    representation = ifc.create_entity(
        'IfcShapeRepresentation', ContextOfItems={s.name('context')},
        RepresentationIdentifier='Body', RepresentationType='SweptSolid',
        Items=[{s.name('solid')}])
    return ifc.create_entity('IfcProductDefinitionShape', Name=None, Description=None,
                             Representations=[representation])
"""


def _helper_placement(s: Style) -> str:
    scale = s.name("scale")
    return f"""def {s.name('place_fn')}(parent, x, y, z):
    return ifc.create_entity(
        'IfcLocalPlacement', PlacementRelTo=parent,
        RelativePlacement=ifc.create_entity(
            'IfcAxis2Placement3D',
            Location=ifc.create_entity(
                'IfcCartesianPoint',
                Coordinates=(x / {scale}, y / {scale}, z / {scale})),
            Axis=None, RefDirection=None))
"""


def _helper_place_world(s: Style) -> str:
    """A placement written from a world point rather than a storey-local one.

    The local names inside are literals rather than drawn from the style pools,
    because two pools can offer the same word and a collision here would have
    one line overwrite another.
    """
    scale = s.name("scale")
    return f"""def {s.name('place_world_fn')}({s.name('storey')}, x, y, z):
    frame = np.array(ifcopenshell.util.placement.get_local_placement(
        {s.name('storey')}.ObjectPlacement))
    world_point = np.array([x, y, z], dtype=float) / {scale}
    local_point = np.linalg.inv(frame[:3, :3]) @ (world_point - frame[:3, 3])
    return {s.name('place_fn')}({s.name('storey')}.ObjectPlacement,
                                float(local_point[0]) * {scale},
                                float(local_point[1]) * {scale},
                                float(local_point[2]) * {scale})
"""


def _helper_contain(s: Style) -> str:
    return f"""def {s.name('contain_fn')}({s.name('storey')}, {s.name('product')}):
    for {s.name('relation')} in getattr({s.name('storey')}, 'ContainsElements', None) or ():
        {s.name('relation')}.RelatedElements = (
            tuple({s.name('relation')}.RelatedElements) + ({s.name('product')},))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory={s.name('history')}, Name=None, Description=None,
                      RelatedElements=[{s.name('product')}],
                      RelatingStructure={s.name('storey')})
"""


def _helper_aggregate(s: Style) -> str:
    return f"""def {s.name('aggregate_fn')}({s.name('storey')}, {s.name('product')}):
    for {s.name('relation')} in getattr({s.name('storey')}, 'IsDecomposedBy', None) or ():
        if {s.name('relation')}.is_a('IfcRelAggregates'):
            {s.name('relation')}.RelatedObjects = (
                tuple({s.name('relation')}.RelatedObjects) + ({s.name('product')},))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory={s.name('history')}, Name=None, Description=None,
                      RelatingObject={s.name('storey')},
                      RelatedObjects=[{s.name('product')}])
"""


def _helper_storey_of(s: Style) -> str:
    return f"""def {s.name('storey_fn')}({s.name('product')}):
    for {s.name('relation')} in getattr({s.name('product')}, 'ContainedInStructure', None) or ():
        structure = {s.name('relation')}.RelatingStructure
        while structure is not None:
            if structure.is_a('IfcBuildingStorey'):
                return structure
            parents = structure.Decomposes or ()
            structure = parents[0].RelatingObject if parents else None
    return None
"""


def _helper_move(s: Style) -> str:
    return f"""def {s.name('move_fn')}(target_guid, dx, dy, dz):
{s.comment('move', '    ')}    {s.name('product')} = ifc.by_guid(target_guid)
    placement = {s.name('product')}.ObjectPlacement
    {s.name('rotation')} = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        {s.name('rotation')} = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    {s.name('offset')} = np.linalg.inv({s.name('rotation')}) @ (
        np.array([dx, dy, dz], dtype=float) / {s.name('scale')})
{s.comment('copy_on_write', '    ')}    {s.name('axis')} = placement.RelativePlacement
    if not {s.name('sole_owner_fn')}({s.name('axis')}, placement):
        {s.name('axis')} = ifc.create_entity(
            'IfcAxis2Placement3D', Location={s.name('axis')}.Location,
            Axis={s.name('axis')}.Axis, RefDirection={s.name('axis')}.RefDirection)
        placement.RelativePlacement = {s.name('axis')}
    {s.name('point')} = {s.name('axis')}.Location
    if not {s.name('sole_owner_fn')}({s.name('point')}, {s.name('axis')}):
        {s.name('point')} = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple({s.name('point')}.Coordinates))
        {s.name('axis')}.Location = {s.name('point')}
    {s.name('point')}.Coordinates = tuple(
        float(c) + float(d) for c, d in zip({s.name('point')}.Coordinates, {s.name('offset')}))
"""


def _helper_writable_axis(s: Style) -> str:
    """The axis placement an element may be written through, copied when shared.

    The local names inside the helpers below are literals rather than drawn
    from the style pools, because two pools can offer the same word and a
    collision here would have one line overwrite another.
    """
    return f"""def writable_axis(placement):
{s.comment('copy_on_write', '    ')}    axis = placement.RelativePlacement
    if not {s.name('sole_owner_fn')}(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location, Axis=axis.Axis,
            RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    if not {s.name('sole_owner_fn')}(axis.Location, axis):
        axis.Location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(axis.Location.Coordinates))
    return axis
"""


def _helper_write_world(s: Style) -> str:
    """Give a product a world frame, expressed in the frame it hangs from.

    The matrix comes in with its translation in the model's own length unit,
    which is the unit IfcOpenShell's placement utility reads and writes.
    """
    return f"""def write_world_frame(product, world):
    placement = product.ObjectPlacement
    parent = np.identity(4)
    if placement.PlacementRelTo is not None:
        parent = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo), dtype=float)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = writable_axis(placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 0]))
"""


def _helper_turn(s: Style) -> str:
    scale = s.name("scale")
    return f"""def turn_element(product, degrees, pivot_x, pivot_y):
    angle = math.radians(float(degrees))
    turn = np.identity(4)
    turn[0, 0], turn[0, 1] = math.cos(angle), -math.sin(angle)
    turn[1, 0], turn[1, 1] = math.sin(angle), math.cos(angle)
    pivot = np.array([float(pivot_x) / {scale}, float(pivot_y) / {scale}, 0.0])
    forward = np.identity(4)
    forward[:3, 3] = pivot
    backward = np.identity(4)
    backward[:3, 3] = -pivot
    about = forward @ (np.round(turn, 12) + 0.0) @ backward
    world = np.array(ifcopenshell.util.placement.get_local_placement(
        product.ObjectPlacement), dtype=float)
    write_world_frame(product, np.round(about @ world, 12) + 0.0)
"""


def _helper_flip_profile(s: Style) -> str:
    """Reflect a swept profile about its own x-centre, in place.

    A rectangle is its own mirror image about the centre it is drawn on, so
    only a polyline outline is rewritten. A profile or a curve the model shares
    with other elements is copied first.
    """
    return f"""def flip_profile(solid):
    outline = solid.SweptArea
    if outline.is_a('IfcRectangleProfileDef'):
        return
    curve = outline.OuterCurve
    coordinates = [tuple(float(v) for v in p.Coordinates) for p in curve.Points]
    closed = len(coordinates) > 1 and coordinates[0] == coordinates[-1]
    corners = coordinates[:-1] if closed else coordinates
    line = min(c[0] for c in corners) + max(c[0] for c in corners)
    flipped = [(line - c[0],) + tuple(c[1:]) for c in corners]
    flipped = [flipped[0]] + flipped[1:][::-1]
    if closed:
        flipped = flipped + [flipped[0]]
    if len(ifc.get_inverse(outline)) != 1:
        outline = ifc.create_entity(
            'IfcArbitraryClosedProfileDef', ProfileType=outline.ProfileType,
            ProfileName=outline.ProfileName, OuterCurve=curve)
        solid.SweptArea = outline
    if len(ifc.get_inverse(curve)) != 1:
        curve = ifc.create_entity('IfcPolyline', Points=list(curve.Points))
        outline.OuterCurve = curve
    curve.Points = [ifc.create_entity('IfcCartesianPoint', Coordinates=c)
                    for c in flipped]
"""


def _helper_mirror(s: Style) -> str:
    """A reflection, written as a rotation of the frame and a flip of the shape.

    IFC carries no left-handed frame, so the two are composed instead. The
    element's own x-centre is read off the profile, which the generator
    guarantees is swept along the local vertical with no rotation of its own.
    """
    scale = s.name("scale")
    return f"""def mirror_element(product, point_x, point_y, normal_x, normal_y):
    solid = {s.name('extrusion_fn')}(product)
    if solid is None:
        raise ValueError({s.string('the element has no single editable extrusion')})
    outline = solid.SweptArea
    if outline.is_a('IfcRectangleProfileDef'):
        centre = 0.0
        if outline.Position is not None:
            centre = float(outline.Position.Location.Coordinates[0])
    else:
        spread = [float(p.Coordinates[0]) for p in outline.OuterCurve.Points]
        centre = (min(spread) + max(spread)) / 2.0
    if solid.Position is not None:
        centre = centre + float(solid.Position.Location.Coordinates[0])
    centre = centre * {scale}
    normal = np.array([float(normal_x), float(normal_y), 0.0])
    normal = normal / float(np.linalg.norm(normal))
    reflect = np.identity(4)
    reflect[:3, :3] = np.identity(3) - 2.0 * np.outer(normal, normal)
    through = np.array([float(point_x) / {scale}, float(point_y) / {scale}, 0.0])
    forward = np.identity(4)
    forward[:3, 3] = through
    backward = np.identity(4)
    backward[:3, 3] = -through
    plane = forward @ (np.round(reflect, 12) + 0.0) @ backward
    flip = np.identity(4)
    flip[0, 0] = -1.0
    flip[0, 3] = 2.0 * centre / {scale}
    world = np.array(ifcopenshell.util.placement.get_local_placement(
        product.ObjectPlacement), dtype=float)
    flip_profile(solid)
    write_world_frame(product, np.round(plane @ world @ flip, 12) + 0.0)
"""


def _helper_pset(s: Style) -> str:
    """One property-set value, written on the element's own copy of the set."""
    history = s.name("history")
    return f"""def write_pset_value(product, pset_name, property_name, value, value_type):
    pset = None
    for relation in ifc.by_type('IfcRelDefinesByProperties'):
        definition = relation.RelatingPropertyDefinition
        if definition is None or not definition.is_a('IfcPropertySet'):
            continue
        if (definition.Name or '') != pset_name:
            continue
        members = list(relation.RelatedObjects or ())
        if product not in members:
            continue
        if len(members) == 1 and len(ifc.get_inverse(definition)) == 1:
            pset = definition
            break
        relation.RelatedObjects = tuple(m for m in members if m != product)
        pset = ifc.create_entity(
            'IfcPropertySet', GlobalId=guid.new(), OwnerHistory={history},
            Name=definition.Name, Description=definition.Description,
            HasProperties=[
                ifc.create_entity(
                    'IfcPropertySingleValue', Name=p.Name,
                    Description=p.Description, NominalValue=p.NominalValue,
                    Unit=p.Unit)
                if p.is_a('IfcPropertySingleValue') else p
                for p in definition.HasProperties or ()])
        ifc.create_entity(
            'IfcRelDefinesByProperties', GlobalId=guid.new(),
            OwnerHistory={history}, Name=None, Description=None,
            RelatedObjects=[product], RelatingPropertyDefinition=pset)
        break
    if pset is None:
        pset = ifc.create_entity(
            'IfcPropertySet', GlobalId=guid.new(), OwnerHistory={history},
            Name=pset_name, Description=None, HasProperties=[])
        ifc.create_entity(
            'IfcRelDefinesByProperties', GlobalId=guid.new(),
            OwnerHistory={history}, Name=None, Description=None,
            RelatedObjects=[product], RelatingPropertyDefinition=pset)
    nominal = ifc.create_entity(value_type, value)
    for prop in pset.HasProperties or ():
        if prop.is_a('IfcPropertySingleValue') and prop.Name == property_name:
            prop.NominalValue = nominal
            return
    pset.HasProperties = tuple(pset.HasProperties or ()) + (
        ifc.create_entity('IfcPropertySingleValue', Name=property_name,
                          Description=None, NominalValue=nominal, Unit=None),)
"""


def _helper_material(s: Style) -> str:
    history = s.name("history")
    return f"""def attach_material(product, material_name):
    material = None
    for candidate in sorted(ifc.by_type('IfcMaterial'), key=lambda m: m.id()):
        if (candidate.Name or '') == material_name:
            material = candidate
            break
    if material is None:
        material = ifc.create_entity('IfcMaterial', Name=material_name)
    for relation in list(ifc.by_type('IfcRelAssociatesMaterial')):
        held = list(relation.RelatedObjects or ())
        if product not in held:
            continue
        members = [m for m in held if m != product]
        if members:
            relation.RelatedObjects = tuple(members)
        else:
            ifc.remove(relation)
    ifc.create_entity('IfcRelAssociatesMaterial', GlobalId=guid.new(),
                      OwnerHistory={history}, Name=None, Description=None,
                      RelatedObjects=[product], RelatingMaterial=material)
"""


def _helper_type(s: Style) -> str:
    history = s.name("history")
    return f"""def attach_type(product, type_object):
    for relation in list(ifc.by_type('IfcRelDefinesByType')):
        held = list(relation.RelatedObjects or ())
        if product not in held:
            continue
        members = [m for m in held if m != product]
        if members:
            relation.RelatedObjects = tuple(members)
        else:
            ifc.remove(relation)
    for relation in sorted(ifc.by_type('IfcRelDefinesByType'),
                           key=lambda r: r.id()):
        if relation.RelatingType == type_object:
            relation.RelatedObjects = (
                tuple(relation.RelatedObjects or ()) + (product,))
            return
    ifc.create_entity('IfcRelDefinesByType', GlobalId=guid.new(),
                      OwnerHistory={history}, Name=None, Description=None,
                      RelatedObjects=[product], RelatingType=type_object)
"""


def _helper_restorey(s: Style) -> str:
    """Move an element into another storey, in the model and in space."""
    return f"""def move_into_storey(product, storey, keep_world):
    placement = product.ObjectPlacement
    world = np.array(ifcopenshell.util.placement.get_local_placement(placement),
                     dtype=float)
    holder = None
    for relation in getattr(product, 'ContainedInStructure', None) or ():
        holder = relation
        break
    if holder is None:
        for relation in getattr(product, 'Decomposes', None) or ():
            if relation.is_a('IfcRelAggregates'):
                holder = relation
                break
    if holder is not None:
        held = ('RelatedObjects' if holder.is_a('IfcRelAggregates')
                else 'RelatedElements')
        members = [m for m in (getattr(holder, held) or ()) if m != product]
        if members:
            setattr(holder, held, tuple(members))
        else:
            ifc.remove(holder)
    if product.is_a('IfcSpatialStructureElement') or product.is_a('IfcSpace'):
        {s.name('aggregate_fn')}(storey, product)
    else:
        {s.name('contain_fn')}(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)
"""


def _helper_replant(s: Style) -> str:
    """Hang one product from a wall at a stated point in that wall's frame."""
    scale = s.name("scale")
    return f"""def replant_in_wall(product, host, x, y, z, depth):
    placement = product.ObjectPlacement
    placement.PlacementRelTo = host.ObjectPlacement
    axis = writable_axis(placement)
    axis.Location.Coordinates = (float(x) / {scale}, float(y) / {scale},
                                 float(z) / {scale})
    axis.Axis = None
    axis.RefDirection = None
    if depth is None:
        return
    solid = {s.name('extrusion_fn')}(product)
    if solid is None or not solid.SweptArea.is_a('IfcRectangleProfileDef'):
        raise ValueError({s.string('the element has no rectangular extruded profile')})
    outline = solid.SweptArea
    if len(ifc.get_inverse(outline)) != 1:
        outline = ifc.create_entity(
            'IfcRectangleProfileDef', ProfileType=outline.ProfileType,
            ProfileName=outline.ProfileName, Position=outline.Position,
            XDim=outline.XDim, YDim=outline.YDim)
        solid.SweptArea = outline
    outline.YDim = float(depth) / {scale}
"""


def _helper_rehost(s: Style) -> str:
    """Move a door or a window, with its opening, into another wall.

    A leaf the model hangs from its own opening follows the opening, so it is
    not moved twice.
    """
    return f"""def rehost_into_wall(product, host, along, across, sill, leaf_along,
                     leaf_across, leaf_sill, thickness, leaf_depth):
    fills = list(getattr(product, 'FillsVoids', None) or ())
    if len(fills) != 1:
        raise ValueError({s.string('the element does not fill exactly one opening')})
    hole = fills[0].RelatingOpeningElement
    voids = list(getattr(hole, 'VoidsElements', None) or ())
    if len(voids) != 1:
        raise ValueError({s.string('the opening does not void exactly one wall')})
    voids[0].RelatingBuildingElement = host
    follows = False
    current = product.ObjectPlacement
    while current is not None and current.is_a('IfcLocalPlacement'):
        if current.id() == hole.ObjectPlacement.id():
            follows = True
            break
        current = current.PlacementRelTo
    replant_in_wall(hole, host, along, across, sill, thickness)
    if not follows:
        replant_in_wall(product, host, leaf_along, leaf_across, leaf_sill,
                        leaf_depth)
"""


#: Entities a copied element shares with its original rather than duplicating:
#: the representation contexts, the placement it hangs from, and the units.
_COPY_SHARED = ("IfcGeometricRepresentationContext",
                "IfcGeometricRepresentationSubContext",
                "IfcRepresentationContext", "IfcLocalPlacement",
                "IfcOwnerHistory", "IfcMaterial", "IfcMaterialLayerSet",
                "IfcMaterialLayerSetUsage", "IfcMaterialLayer",
                "IfcPresentationLayerAssignment", "IfcStyledItem")


def _helper_duplicate(s: Style) -> str:
    """One element duplicated at a world-axis offset given in metres."""
    scale = s.name("scale")
    history = s.name("history")
    shared = ",\n    ".join(
        ", ".join(f"'{name}'" for name in _COPY_SHARED[start:start + 3])
        for start in range(0, len(_COPY_SHARED), 3))
    return f"""shared_entities = [
    {shared}]


def duplicate_element(product, dx, dy, dz, copy_name):
    copy = ifc.create_entity(product.is_a(), GlobalId=guid.new(),
                             OwnerHistory={history})
    for attribute in product.wrapped_data.declaration().as_entity().all_attributes():
        field = attribute.name()
        if field in ('GlobalId', 'OwnerHistory', 'ObjectPlacement',
                     'Representation'):
            continue
        try:
            setattr(copy, field, getattr(product, field))
        except Exception:
            continue
    if copy_name is not None:
        copy.Name = copy_name
    placement = product.ObjectPlacement
    parent = None
    if placement is not None and placement.is_a('IfcLocalPlacement'):
        parent = placement.PlacementRelTo
    frame = np.identity(4)
    if parent is not None:
        frame = np.array(ifcopenshell.util.placement.get_local_placement(parent),
                         dtype=float)
    origin = np.identity(4)
    if placement is not None:
        origin = np.array(ifcopenshell.util.placement.get_local_placement(
            placement), dtype=float)
    local = np.linalg.inv(frame) @ origin
    step = np.linalg.inv(frame[:3, :3]) @ (
        np.array([dx, dy, dz], dtype=float) / {scale})
    copy.ObjectPlacement = ifc.create_entity(
        'IfcLocalPlacement', PlacementRelTo=parent,
        RelativePlacement=ifc.create_entity(
            'IfcAxis2Placement3D',
            Location=ifc.create_entity(
                'IfcCartesianPoint',
                Coordinates=tuple(float(v) for v in local[:3, 3] + step)),
            Axis=ifc.create_entity(
                'IfcDirection',
                DirectionRatios=tuple(float(v) for v in local[:3, 2])),
            RefDirection=ifc.create_entity(
                'IfcDirection',
                DirectionRatios=tuple(float(v) for v in local[:3, 0]))))
    if product.Representation is not None:
        copy.Representation = ifcopenshell.util.element.copy_deep(
            ifc, product.Representation, exclude=list(shared_entities))
    holder = {s.name('storey_fn')}(product)
    if holder is not None:
        if copy.is_a('IfcSpace'):
            {s.name('aggregate_fn')}(holder, copy)
        else:
            {s.name('contain_fn')}(holder, copy)
    return copy
"""


#: Which helpers each operation needs, in dependency order.
_NEEDS: dict[str, tuple[str, ...]] = {
    "translate": ("numpy", "placement", "scale", "sole_owner", "move"),
    "set_attribute": (),
    "set_length_attribute": ("scale",),
    "set_extrusion_depth": ("scale", "body", "extrusion"),
    "set_profile_dimension": ("scale", "body", "extrusion", "sole_owner"),
    "delete_element": ("api_root",),
    "add_box_element": ("scale", "history", "body", "context", "shape", "place"),
    "add_box_element_world": ("numpy", "placement", "scale", "history", "body",
                              "context", "shape", "place", "place_world"),
    # 0.7.0: the same call on a storey whose own axes are turned against the
    # world axes.  The helper already converts through the storey's full
    # placement matrix, so a turned storey needs no arithmetic of its own.
    "add_box_element_world_turned": ("numpy", "placement", "scale", "history",
                                     "body", "context", "shape", "place",
                                     "place_world"),
    "add_wall_span": ("numpy", "placement", "scale", "history", "body",
                      "context", "shape", "place", "place_world", "contain"),
    "add_filling": ("scale", "history", "body", "context", "shape", "place",
                    "contain", "storey_of"),
    "delete_filling_with_opening": ("api_root",),
    "add_space_boundary": ("history",),
    "connect_elements": ("history",),
    "rotate": ("math", "numpy", "placement", "scale", "sole_owner",
               "writable_axis", "write_world", "turn"),
    "mirror": ("numpy", "placement", "scale", "sole_owner", "body", "extrusion",
               "writable_axis", "write_world", "flip_profile", "mirror"),
    "set_property_value": ("history", "pset"),
    "assign_material": ("history", "material"),
    "assign_type": ("history", "type_object"),
    "move_to_storey": ("numpy", "placement", "history", "sole_owner",
                       "writable_axis", "write_world", "contain", "aggregate",
                       "restorey"),
    "rehost_filling": ("scale", "sole_owner", "body", "extrusion",
                       "writable_axis", "replant", "rehost"),
    "copy_element": ("numpy", "placement", "scale", "history", "util_element",
                     "contain", "aggregate", "storey_of", "duplicate"),
    "array_elements": ("numpy", "placement", "scale", "history", "util_element",
                       "contain", "aggregate", "storey_of", "duplicate"),
    "replace_filling": ("api_root", "scale", "history", "body", "context",
                        "shape", "place", "contain", "storey_of"),
}

_HELPER_ORDER = ("sole_owner", "body", "extrusion", "context", "shape", "place",
                 "place_world", "contain", "aggregate", "storey_of", "move",
                 "writable_axis", "write_world", "flip_profile", "replant",
                 "turn", "mirror", "pset", "material", "type_object",
                 "restorey", "rehost", "duplicate")

_HELPER_BUILDERS = {
    "sole_owner": _helper_sole_owner,
    "body": _helper_body,
    "extrusion": _helper_extrusion,
    "context": _helper_context,
    "shape": _helper_shape,
    "place": _helper_placement,
    "place_world": _helper_place_world,
    "contain": _helper_contain,
    "aggregate": _helper_aggregate,
    "storey_of": _helper_storey_of,
    "move": _helper_move,
    "writable_axis": _helper_writable_axis,
    "write_world": _helper_write_world,
    "flip_profile": _helper_flip_profile,
    "replant": _helper_replant,
    "turn": _helper_turn,
    "mirror": _helper_mirror,
    "pset": _helper_pset,
    "material": _helper_material,
    "type_object": _helper_type,
    "restorey": _helper_restorey,
    "rehost": _helper_rehost,
    "duplicate": _helper_duplicate,
}


# ------------------------------------------------------------- emitters

def _num(value: float) -> str:
    """A float literal without a long decimal tail."""
    if isinstance(value, bool):
        return repr(value)
    if isinstance(value, int):
        return f"{float(value)!r}"
    text = repr(round(float(value), 9))
    return text


@dataclass
class _Emitter:
    style: Style
    lines: list[str] = field(default_factory=list)
    created: dict[str, str] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)
    #: The task's own ``edit_params``, which carry the numbers the instruction
    #: states and the placement wording behind them. The library style reads
    #: them so the emitted call holds the instruction's number rather than the
    #: coordinate the generator worked out from it.
    params: dict = field(default_factory=dict)
    #: Identifiers a measured placement looks up, beyond the ones the gold call
    #: names. A trajectory has to resolve these before the edit runs.
    extra_refs: list[str] = field(default_factory=list)
    #: The instruction, which is what decides whether a predefined type is a
    #: value the reader was given or one the generator chose on its own.
    instruction: str = ""

    def ref(self, gold_guid: str) -> str:
        """An expression naming the entity a gold GlobalId refers to.

        Entities the edit itself created are held in a local variable, because
        their identifier is drawn fresh and the literal from the gold script
        would not resolve.
        """
        if gold_guid in self.created:
            return self.created[gold_guid]
        return f"ifc.by_guid({self.style.string(gold_guid)})"

    def fresh(self, base: str) -> str:
        """A variable name for ``base``, numbered from the second use on."""
        count = self.counters.get(base, 0) + 1
        self.counters[base] = count
        return base if count == 1 else f"{base}_{count}"


def _emit_translate(em: _Emitter, kw: dict) -> None:
    s = em.style
    em.lines.append(
        f"{s.name('move_fn')}({s.string(kw['guid'])}, {_num(kw['dx'])}, "
        f"{_num(kw['dy'])}, {_num(kw['dz'])})"
    )


def _emit_set_attribute(em: _Emitter, kw: dict) -> None:
    s = em.style
    value = kw["value"]
    literal = s.string(value) if isinstance(value, str) else repr(value)
    comment = s.comment("attribute")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{em.ref(kw['guid'])}.{kw['name']} = {literal}")


def _emit_set_length_attribute(em: _Emitter, kw: dict) -> None:
    s = em.style
    comment = s.comment("attribute")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(
        f"{em.ref(kw['guid'])}.{kw['name']} = {_num(kw['metres'])} / {s.name('scale')}"
    )


def _emit_set_extrusion_depth(em: _Emitter, kw: dict) -> None:
    s = em.style
    name = em.fresh(s.name("solid"))
    comment = s.comment("geometry")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{name} = {s.name('extrusion_fn')}({em.ref(kw['guid'])})")
    em.lines.append(f"if {name} is None:")
    em.lines.append(
        f"    raise ValueError({s.string('the element has no single editable extrusion')})"
    )
    em.lines.append(f"{name}.Depth = {_num(kw['depth'])} / {s.name('scale')}")


def _emit_set_profile_dimension(em: _Emitter, kw: dict) -> None:
    s = em.style
    solid = em.fresh(s.name("solid"))
    profile = s.name("profile")
    comment = s.comment("geometry")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{solid} = {s.name('extrusion_fn')}({em.ref(kw['guid'])})")
    em.lines.append(f"if {solid} is None or not {solid}.SweptArea.is_a('IfcRectangleProfileDef'):")
    em.lines.append(
        f"    raise ValueError({s.string('the element has no rectangular extruded profile')})"
    )
    em.lines.append(f"{profile} = {solid}.SweptArea")
    em.lines.append(f"if len(ifc.get_inverse({profile})) != 1:")
    em.lines.append(
        f"    {profile} = ifc.create_entity(\n"
        f"        'IfcRectangleProfileDef', ProfileType={profile}.ProfileType,\n"
        f"        ProfileName={profile}.ProfileName, Position={profile}.Position,\n"
        f"        XDim={profile}.XDim, YDim={profile}.YDim)\n"
        f"    {solid}.SweptArea = {profile}"
    )
    em.lines.append(
        f"{profile}.{kw['dimension']} = {_num(kw['value'])} / {s.name('scale')}"
    )


def _emit_delete_batch(em: _Emitter, guids: list[str]) -> None:
    """Several deletions written as one loop, which is how a person would write it."""
    s = em.style
    comment = s.comment("delete")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    listed = ", ".join(s.string(g) for g in guids)
    em.lines.append(f"for target_guid in ({listed}):")
    em.lines.append("    ifcopenshell.api.root.remove_product(ifc, product=ifc.by_guid(target_guid))")


def _emit_add_box_element(em: _Emitter, kw: dict) -> None:
    s = em.style
    storey = em.fresh(s.name("storey"))
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{storey} = {em.ref(kw['storey_guid'])}")
    name_literal = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(
        f"{created} = ifc.create_entity(\n"
        f"    {s.string(kw['ifc_class'])}, GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name={name_literal}, Description=None)"
    )
    # The donor element the generator used is not named in the instruction, so
    # the emitted code finds it the same way rather than carrying a literal
    # identifier the model could not have known.
    context_arg = ""
    if kw.get("_frame") == "world":
        em.lines.append(
            f"{created}.ObjectPlacement = {s.name('place_world_fn')}({storey}, "
            f"{_num(kw['x'])}, {_num(kw['y'])}, {_num(kw['z'])})"
        )
    else:
        em.lines.append(
            f"{created}.ObjectPlacement = {s.name('place_fn')}({storey}.ObjectPlacement, "
            f"{_num(kw['x'])}, {_num(kw['y'])}, {_num(kw['z'])})"
        )
    em.lines.append(
        f"{created}.Representation = {s.name('shape_fn')}("
        f"{s.name('context_fn')}({context_arg}), "
        f"{_num(kw['length'])}, {_num(kw['width'])}, {_num(kw['height'])})"
    )
    if kw.get("predefined_type") is not None:
        em.lines.append(f"{created}.PredefinedType = {s.string(kw['predefined_type'])}")
    if kw["ifc_class"] == "IfcSpace":
        long_name = kw.get("long_name")
        em.lines.append(
            f"{created}.LongName = "
            + (s.string(long_name) if long_name is not None else "None")
        )
        em.lines.append(f"if hasattr({created}, 'CompositionType'):")
        em.lines.append(f"    {created}.CompositionType = 'ELEMENT'")
        em.lines.append(f"if hasattr({created}, 'InteriorOrExteriorSpace'):")
        em.lines.append(f"    {created}.InteriorOrExteriorSpace = 'INTERNAL'")
        em.lines.append(f"{s.name('aggregate_fn')}({storey}, {created})")
    else:
        em.lines.append(f"{s.name('contain_fn')}({storey}, {created})")
    em.created[kw["guid"]] = created


def _emit_add_filling(em: _Emitter, kw: dict) -> None:
    s = em.style
    host = em.fresh("host")
    opening = em.fresh(s.name("opening"))
    filling = em.fresh(s.name("filling"))
    comment = s.comment("filling")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{host} = {em.ref(kw['host_guid'])}")
    em.lines.append(
        f"{opening} = ifc.create_entity(\n"
        f"    'IfcOpeningElement', GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name='Opening', Description=None)"
    )
    em.lines.append(
        f"{opening}.ObjectPlacement = {s.name('place_fn')}({host}.ObjectPlacement, "
        f"{_num(kw['along'])}, {_num(kw['across'])}, {_num(kw['sill'])})"
    )
    em.lines.append(
        f"{opening}.Representation = {s.name('shape_fn')}({s.name('context_fn')}({host}), "
        f"{_num(kw['width'])}, {_num(kw['thickness'])}, {_num(kw['height'])})"
    )
    em.lines.append(f"if hasattr({opening}, 'PredefinedType'):")
    em.lines.append(f"    {opening}.PredefinedType = 'OPENING'")
    em.lines.append(
        f"ifc.create_entity(\n"
        f"    'IfcRelVoidsElement', GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name=None, Description=None,\n"
        f"    RelatingBuildingElement={host}, RelatedOpeningElement={opening})"
    )
    name_literal = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(
        f"{filling} = ifc.create_entity(\n"
        f"    {s.string(kw['ifc_class'])}, GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name={name_literal}, Description=None)"
    )
    # The opening cuts past both wall faces while the leaf takes the wall's own
    # thickness, so the door or window sits flush with the wall.  Where the gold
    # script does not say, the leaf takes the opening's position and depth.
    leaf_across = kw.get("filling_across")
    leaf_depth = kw.get("filling_depth")
    leaf_across = kw["across"] if leaf_across is None else leaf_across
    leaf_depth = kw["thickness"] if leaf_depth is None else leaf_depth
    em.lines.append(
        f"{filling}.ObjectPlacement = {s.name('place_fn')}({host}.ObjectPlacement, "
        f"{_num(kw['along'])}, {_num(leaf_across)}, {_num(kw['sill'])})"
    )
    em.lines.append(
        f"{filling}.Representation = {s.name('shape_fn')}({s.name('context_fn')}({host}), "
        f"{_num(kw['width'])}, {_num(leaf_depth)}, {_num(kw['height'])})"
    )
    em.lines.append(f"{filling}.OverallHeight = {_num(kw['height'])} / {s.name('scale')}")
    em.lines.append(f"{filling}.OverallWidth = {_num(kw['width'])} / {s.name('scale')}")
    if kw.get("predefined_type") is not None:
        em.lines.append(f"if hasattr({filling}, 'PredefinedType'):")
        em.lines.append(f"    {filling}.PredefinedType = {s.string(kw['predefined_type'])}")
    em.lines.append(
        f"ifc.create_entity(\n"
        f"    'IfcRelFillsElement', GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name=None, Description=None,\n"
        f"    RelatingOpeningElement={opening}, RelatedBuildingElement={filling})"
    )
    em.lines.append(f"{s.name('contain_fn')}({s.name('storey_fn')}({host}), {filling})")
    em.created[kw["guid"]] = filling


def _emit_add_box_element_world(em: _Emitter, kw: dict) -> None:
    """A box whose position is quoted in world metres rather than storey metres."""
    _emit_add_box_element(em, dict(kw, _frame="world"))


#: Which axis a wall's thickness lies on, and which way, per the word the
#: instruction uses. The same table the generator's own span call uses.
_THICKNESS_DIRECTIONS = {"+x": (0, 1.0), "-x": (0, -1.0),
                         "+y": (1, 1.0), "-y": (1, -1.0)}


def _wall_span_box(kw: dict) -> dict:
    """A wall given as the line its faces follow, turned into a box.

    The span, the side the thickness lies on and the height fix one box in world
    metres, and the arithmetic is done here so the emitted code writes the same
    corner and the same size the gold script produced.
    """
    across, sign = _THICKNESS_DIRECTIONS[kw["thickness_direction"]]
    delta = [float(kw["x2"]) - float(kw["x1"]), float(kw["y2"]) - float(kw["y1"])]
    run = 0 if abs(delta[0]) >= abs(delta[1]) else 1
    lo = [min(float(kw["x1"]), float(kw["x2"])),
          min(float(kw["y1"]), float(kw["y2"]))]
    size = [0.0, 0.0]
    size[run] = abs(delta[run])
    size[across] = float(kw["thickness"])
    if sign < 0:
        lo[across] -= float(kw["thickness"])
    return {"ifc_class": "IfcWall", "guid": kw["guid"], "name": kw.get("name"),
            "storey_guid": kw["storey_guid"], "x": lo[0], "y": lo[1],
            "z": float(kw["z1"]), "length": size[0], "width": size[1],
            "height": float(kw["height"]),
            "predefined_type": kw.get("predefined_type")}


def _emit_add_wall_span(em: _Emitter, kw: dict) -> None:
    _emit_add_box_element(em, dict(_wall_span_box(kw), _frame="world"))


def _emit_add_space_boundary(em: _Emitter, kw: dict) -> None:
    s = em.style
    comment = s.comment("relation")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    name = kw.get("name")
    em.lines.append(
        f"ifc.create_entity(\n"
        f"    'IfcRelSpaceBoundary', GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name={s.string(name) if name is not None else 'None'}, Description=None,\n"
        f"    RelatingSpace={em.ref(kw['space_guid'])},\n"
        f"    RelatedBuildingElement={em.ref(kw['element_guid'])},\n"
        f"    ConnectionGeometry=None,\n"
        f"    PhysicalOrVirtualBoundary={s.string(kw.get('physical_or_virtual') or 'PHYSICAL')},\n"
        f"    InternalOrExternalBoundary={s.string(kw.get('internal_or_external') or 'INTERNAL')})"
    )


def _emit_connect_elements(em: _Emitter, kw: dict) -> None:
    s = em.style
    comment = s.comment("relation")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    name = kw.get("name")
    em.lines.append(
        f"ifc.create_entity(\n"
        f"    'IfcRelConnectsElements', GlobalId=guid.new(), OwnerHistory={s.name('history')},\n"
        f"    Name={s.string(name) if name is not None else 'None'}, Description=None,\n"
        f"    ConnectionGeometry=None,\n"
        f"    RelatingElement={em.ref(kw['relating_guid'])},\n"
        f"    RelatedElement={em.ref(kw['related_guid'])})"
    )


def _emit_delete_filling_with_opening(em: _Emitter, kw: dict) -> None:
    """Remove a door or window together with the opening it filled."""
    s = em.style
    target = em.fresh(s.name("target"))
    comment = s.comment("delete")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{target} = {em.ref(kw['guid'])}")
    em.lines.append(f"for fills in {target}.FillsVoids or ():")
    em.lines.append("    opening = fills.RelatingOpeningElement")
    em.lines.append("    ifc.remove(fills)")
    em.lines.append("    if opening is not None:")
    em.lines.append("        for voids in opening.VoidsElements or ():")
    em.lines.append("            ifc.remove(voids)")
    em.lines.append("        ifcopenshell.api.root.remove_product(ifc, product=opening)")
    em.lines.append(f"ifcopenshell.api.root.remove_product(ifc, product={target})")


def _value(s: Style, value: Any) -> str:
    """A property value written as the literal its IFC value type expects."""
    if isinstance(value, str):
        return s.string(value)
    if isinstance(value, bool) or isinstance(value, int):
        return repr(value)
    return repr(round(float(value), 9))


def _emit_rotate(em: _Emitter, kw: dict) -> None:
    em.lines.append(
        f"turn_element({em.ref(kw['guid'])}, {_num(kw['degrees'])}, "
        f"{_num(kw['pivot_x'])}, {_num(kw['pivot_y'])})"
    )


def _emit_mirror(em: _Emitter, kw: dict) -> None:
    em.lines.append(
        f"mirror_element({em.ref(kw['guid'])}, {_num(kw['point_x'])}, "
        f"{_num(kw['point_y'])},\n"
        f"               {_num(kw['normal_x'])}, {_num(kw['normal_y'])})"
    )


def _emit_set_property_value(em: _Emitter, kw: dict) -> None:
    s = em.style
    em.lines.append(
        f"write_pset_value(\n"
        f"    {em.ref(kw['guid'])}, {s.string(kw['pset_name'])}, "
        f"{s.string(kw['property_name'])},\n"
        f"    {_value(s, kw['value'])}, {s.string(kw['value_type'])})"
    )


def _emit_assign_material(em: _Emitter, kw: dict) -> None:
    s = em.style
    em.lines.append(
        f"attach_material({em.ref(kw['guid'])}, {s.string(kw['material_name'])})"
    )


def _emit_assign_type(em: _Emitter, kw: dict) -> None:
    em.lines.append(
        f"attach_type({em.ref(kw['guid'])}, {em.ref(kw['type_guid'])})"
    )


def _emit_move_to_storey(em: _Emitter, kw: dict) -> None:
    keep = bool(kw.get("keep_world", True))
    em.lines.append(
        f"move_into_storey({em.ref(kw['guid'])}, {em.ref(kw['storey_guid'])}, "
        f"{keep!r})"
    )


def _emit_rehost_filling(em: _Emitter, kw: dict) -> None:
    depth = kw.get("leaf_depth")
    em.lines.append(
        f"rehost_into_wall(\n"
        f"    {em.ref(kw['guid'])}, {em.ref(kw['host_guid'])}, "
        f"{_num(kw['along'])}, {_num(kw['across'])}, {_num(kw['sill'])},\n"
        f"    {_num(kw['leaf_along'])}, {_num(kw['leaf_across'])}, "
        f"{_num(kw['leaf_sill'])}, {_num(kw['thickness'])}, "
        + ("None" if depth is None else _num(depth)) + ")"
    )


def _emit_copy_element(em: _Emitter, kw: dict) -> None:
    s = em.style
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(
        f"{created} = duplicate_element(\n"
        f"    {em.ref(kw['guid'])}, {_num(kw['dx'])}, {_num(kw['dy'])}, "
        f"{_num(kw['dz'])}, {name})"
    )
    em.created[kw["new_guid"]] = created


def _emit_array_elements(em: _Emitter, kw: dict) -> None:
    """The copy, repeated, with the offset growing by one spacing each time."""
    s = em.style
    source = em.fresh(s.name("product"))
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    gold_guids = list(kw["new_guids"])
    names = list(kw.get("names") or ())
    names = [names[i] if i < len(names) else None for i in range(len(gold_guids))]
    listed = ", ".join(s.string(n) if n is not None else "None" for n in names)
    em.lines.append(f"{source} = {em.ref(kw['guid'])}")
    em.lines.append(f"{created} = []")
    em.lines.append(f"for step, copy_name in enumerate(({listed},), start=1):")
    em.lines.append(
        f"    {created}.append(duplicate_element(\n"
        f"        {source}, {_num(kw['dx'])} * step, {_num(kw['dy'])} * step,\n"
        f"        {_num(kw['dz'])} * step, copy_name))"
    )
    for index, gold_guid in enumerate(gold_guids):
        em.created[gold_guid] = f"{created}[{index}]"


def _emit_replace_filling(em: _Emitter, kw: dict) -> None:
    """The element and its opening taken out, then the new one cut and filled."""
    _emit_delete_filling_with_opening(em, {"guid": kw["guid"]})
    _emit_add_filling(em, {
        "ifc_class": kw["ifc_class"], "guid": kw["new_guid"],
        "name": kw.get("name"), "host_guid": kw["host_guid"],
        "along": kw["along"], "across": kw["across"], "sill": kw["sill"],
        "width": kw["width"], "height": kw["height"],
        "thickness": kw["thickness"],
        "predefined_type": kw.get("predefined_type"),
        "filling_across": kw.get("filling_across"),
        "filling_depth": kw.get("filling_depth")})


# ------------------------------------------------- the sandbox's geometry helper

#: The operations the sandbox's geometry helper (``geom``) performs on its own.
#: Under the library style the emitted code hands each of them to ``geom`` with
#: the arguments the instruction states, and writes none of the profiles,
#: extrusions, placements or relationship entities the helper builds inside.
GEOM_CALLS = frozenset({
    "add_filling", "replace_filling", "add_box_element",
    "add_box_element_world", "add_box_element_world_turned", "add_wall_span",
    "copy_element", "array_elements", "add_space_boundary", "connect_elements",
    "delete_filling_with_opening", "delete_element", "set_property_value",
    "rehost_filling", "rotate", "assign_material", "assign_type",
})

#: How wide a generated line may get before its argument list is broken.
_WRAP = 88


def _geom_call(name: str, positional: list[str],
               keyword: list[tuple[str, str]], lead: str = "") -> str:
    """One ``geom.<name>(...)`` call, wrapped at the argument list."""
    args = list(positional) + [f"{key}={value}" for key, value in keyword]
    head = f"{lead}geom.{name}("
    single = head + ", ".join(args) + ")"
    if len(single) <= _WRAP:
        return single
    pad = " " * len(head)
    lines: list[str] = []
    current = head
    for index, argument in enumerate(args):
        piece = argument + ("," if index < len(args) - 1 else ")")
        if current != head and len(current) + len(piece) > _WRAP:
            lines.append(current.rstrip())
            current = pad
        current += piece + " "
    lines.append(current.rstrip())
    return "\n".join(lines)


def _stated_type(em: "_Emitter", value) -> Optional[str]:
    """The predefined type, when the instruction is the place it comes from.

    An instruction that wants a type says so, as "Give it the predefined type
    ROOF". Where it does not, the gold script still carries one, because the
    generator drew it when it built the task. Writing that token would put a
    value in the edit that no reader of the sentence could have produced, so it
    is left out and the task's own score decides whether it was needed.
    """
    if value is None:
        return None
    return str(value) if str(value) in (em.instruction or "") else None


def _gnum(value: float) -> str:
    """A float literal for a library call, with no negative zero."""
    text = _num(value)
    return "0.0" if text == "-0.0" else text


def _signed(value: float) -> str:
    """``+ 3.0`` or ``- 3.0``, for an offset added to a measured coordinate."""
    return ("- " if value < 0 else "+ ") + _num(abs(value))


def _placement_of(em: "_Emitter") -> dict:
    return (em.params or {}).get("placement") or {}


def _centre_along(em: "_Emitter", kw: dict) -> float | None:
    """The centre of the leaf, where the instruction gives that instead of its edge.

    The generator records the wording under ``placement``: the sentence says how
    far along the wall the middle of the leaf sits, measured from the wall's
    start, and the gold call carries the near edge in the wall's own frame. The
    two differ by half the width and by where the wall's body starts, which is
    ``centre = along + width / 2 - extent.lo[0]`` in the generator
    (``modifc_gen.ops._derive_centred_on_wall``). The emitted call therefore
    holds the number the instruction wrote and adds the start the measuring
    round read, and ``along_is_centre=True`` takes off the half width.
    """
    placement = _placement_of(em)
    if placement.get("kind") != "centred_on_wall":
        return None
    centre = placement.get("centre_from_start")
    return None if centre is None else float(centre)


def _geom_add_filling(em: "_Emitter", kw: dict) -> None:
    s = em.style
    host = em.fresh("host")
    leaf = em.fresh(s.name("filling"))
    comment = s.comment("library")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    if kw["host_guid"] in em.created:
        host = em.created[kw["host_guid"]]
    else:
        em.lines.append(f"{host} = {em.ref(kw['host_guid'])}")
    centre = _centre_along(em, kw)
    keyword: list[tuple[str, str]] = [("width", _gnum(kw["width"])),
                                      ("height", _gnum(kw["height"]))]
    if centre is None:
        keyword.append(("along", _gnum(kw["along"])))
    else:
        # The distance is measured from where the wall's body starts, so the
        # wall is measured here and the instruction's own number added to it.
        box = em.fresh(s.name("wall_box"))
        em.lines.append(f"{box} = geom.wall_box({host})")
        keyword.append(("along", f"{box}[{s.string('start')}] + {_gnum(centre)}"))
        keyword.append(("along_is_centre", "True"))
    keyword.append(("sill", _gnum(kw["sill"])))
    stated = _stated_type(em, kw.get("predefined_type"))
    if stated is not None:
        keyword.append(("predefined_type", s.string(stated)))
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(_geom_call(
        "add_filling", [host, s.string(kw["ifc_class"]), name], keyword,
        lead=f"{leaf} = "))
    em.created[kw["guid"]] = leaf


def _geom_replace_filling(em: "_Emitter", kw: dict) -> None:
    """The old element, its opening and the new one, in one call.

    The library reads the position along the wall off the opening the old
    element filled, which is what "at the same position along the wall" names,
    so the emitted call states only the new element's class, name, size and
    sill.
    """
    s = em.style
    old = em.fresh("old")
    leaf = em.fresh(s.name("filling"))
    comment = s.comment("library")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{old} = {em.ref(kw['guid'])}")
    keyword: list[tuple[str, str]] = [("width", _gnum(kw["width"])),
                                      ("height", _gnum(kw["height"])),
                                      ("sill", _gnum(kw["sill"]))]
    stated = _stated_type(em, kw.get("predefined_type"))
    if stated is not None:
        keyword.append(("predefined_type", s.string(stated)))
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(_geom_call(
        "replace_filling", [old, s.string(kw["ifc_class"]), name], keyword,
        lead=f"{leaf} = "))
    em.created[kw["new_guid"]] = leaf


def _box_corner(em: "_Emitter", kw: dict, frame: str,
                storey: str) -> tuple[list[str], list[str], list[str]]:
    """Where a new box stands, as the instruction describes it.

    Returns the lines that measure the position, the three coordinate
    expressions and the three size expressions. Three wordings are measured
    rather than quoted: a corner stated as an offset from a named element, an
    element sitting on top of another, and an element standing against a wall
    inside a room. Everything else keeps the coordinate the instruction writes.
    """
    s = em.style
    params = em.params or {}
    placement = _placement_of(em)
    kind = placement.get("kind")
    size = [_gnum(kw["length"]), _gnum(kw["width"]), _gnum(kw["height"])]
    plain = ([], [_gnum(kw["x"]), _gnum(kw["y"]), _gnum(kw["z"])], size)

    offset = params.get("offset") or {}
    if frame == "storey" and offset.get("reference_guid"):
        reference_guid = offset["reference_guid"]
        if reference_guid in em.created:
            return plain
        reference = em.fresh(s.name("reference"))
        corner = em.fresh(s.name("corner"))
        dx = float(offset["dx"]) * (-1 if str(offset.get("x_axis", "+X")).startswith("-") else 1)
        dy = float(offset["dy"]) * (-1 if str(offset.get("y_axis", "+Y")).startswith("-") else 1)
        lines = [s.comment("place").rstrip("\n")] if s.comments else []
        lines.append(f"{reference} = {em.ref(reference_guid)}")
        lines.append(f"{corner} = geom.origin_in_frame({reference}, {storey})")
        em.extra_refs.append(reference_guid)
        return (lines, [f"{corner}[0] {_signed(dx)}", f"{corner}[1] {_signed(dy)}",
                        _gnum(kw["z"])], size)

    if frame == "world" and kind == "on_top_of":
        reference_guid = placement.get("anchor_guid") or (placement.get("refs") or [None])[0]
        if not reference_guid or reference_guid in em.created:
            return plain
        reference = em.fresh(s.name("reference"))
        corner = em.fresh(s.name("corner"))
        footprint = em.fresh(s.name("footprint"))
        lines = [s.comment("place").rstrip("\n")] if s.comments else []
        lines.append(f"{reference} = {em.ref(reference_guid)}")
        lines.append(f"{corner}, {footprint} = geom.spot_on_top_of({reference})")
        em.extra_refs.append(reference_guid)
        return (lines, [f"{corner}[0]", f"{corner}[1]", f"{corner}[2]"],
                [f"{footprint}[0]", f"{footprint}[1]", _gnum(kw["height"])])

    if frame == "world" and kind == "adjacent_to_space":
        wall_guid = placement.get("anchor_guid")
        refs = [g for g in (placement.get("refs") or ()) if g != wall_guid]
        if not wall_guid or not refs or wall_guid in em.created:
            return plain
        space_guid = refs[0]
        wall = em.fresh("wall")
        room = em.fresh(s.name("room"))
        corner = em.fresh(s.name("corner"))
        lines = [s.comment("place").rstrip("\n")] if s.comments else []
        lines.append(f"{wall} = {em.ref(wall_guid)}")
        lines.append(f"{room} = {em.ref(space_guid)}")
        lines.append(f"{corner} = geom.spot_beside("
                     f"{wall}, {room}, {_gnum(kw['length'])}, {_gnum(kw['width'])})")
        em.extra_refs.extend([wall_guid, space_guid])
        return (lines, [f"{corner}[0]", f"{corner}[1]", f"{corner}[2]"], size)

    return plain


def _geom_add_box_element(em: "_Emitter", kw: dict) -> None:
    s = em.style
    frame = "world" if kw.get("_frame") == "world" else "storey"
    storey = em.fresh(s.name("storey"))
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{storey} = {em.ref(kw['storey_guid'])}")
    lines, point, size = _box_corner(em, kw, frame, storey)
    em.lines.extend(line for line in lines if line)
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    keyword: list[tuple[str, str]] = []
    stated = _stated_type(em, kw.get("predefined_type"))
    if stated is not None:
        keyword.append(("predefined_type", s.string(stated)))
    keyword.append(("frame", s.string(frame)))
    # ``LongName`` is not written. The generator gives a created space the fixed
    # long name "New space", the instruction never states it, and the scorer's
    # property comparison ignores the attribute, so writing it would put a
    # string in the edit that nothing in the task asked for.
    em.lines.append(_geom_call(
        "add_box_element", [storey, s.string(kw["ifc_class"]), name] + point + size,
        keyword, lead=f"{created} = "))
    em.created[kw["guid"]] = created


def _geom_add_box_element_world(em: "_Emitter", kw: dict) -> None:
    _geom_add_box_element(em, dict(kw, _frame="world"))


#: How the wall's body lies against the line the instruction gives.
_SIDE_WORD = {"+x": "the +x side", "-x": "the -x side",
              "+y": "the +y side", "-y": "the -y side"}


def _geom_add_wall_span(em: "_Emitter", kw: dict) -> None:
    """A wall given as the line it runs along, written as the box that follows.

    The library has no call for a span. The instruction gives the two ends, the
    thickness, the side the thickness lies on and the height, and the box
    follows from those by the rule ``modifc_gen.goldlib.add_wall_span`` uses:
    the run is the axis the two ends differ on, the length is that difference,
    the lowest corner is the lower end, and the corner moves back by the
    thickness when the body lies on the negative side. That arithmetic is
    written into the emitted code rather than done here, so the only numbers in
    the edit are the ones the instruction states.
    """
    s = em.style
    across, sign = _THICKNESS_DIRECTIONS[kw["thickness_direction"]]
    run = 0 if abs(float(kw["x2"]) - float(kw["x1"])) >= \
        abs(float(kw["y2"]) - float(kw["y1"])) else 1
    storey = em.fresh(s.name("storey"))
    created = em.fresh(s.name("created"))
    length = em.fresh("length")
    corner_x = em.fresh("corner_x")
    corner_y = em.fresh("corner_y")

    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(f"{storey} = {em.ref(kw['storey_guid'])}")
    if s.comments:
        em.lines.append(f"# the wall runs along the line the instruction gives,"
                        f" with its body on {_SIDE_WORD[kw['thickness_direction']]}")
    em.lines.append(f"x1, y1, z1 = {_gnum(kw['x1'])}, {_gnum(kw['y1'])}, "
                    f"{_gnum(kw['z1'])}")
    em.lines.append(f"x2, y2 = {_gnum(kw['x2'])}, {_gnum(kw['y2'])}")
    em.lines.append(f"thickness, height = {_gnum(kw['thickness'])}, "
                    f"{_gnum(kw['height'])}")
    em.lines.append(f"{length} = abs(x2 - x1)" if run == 0
                    else f"{length} = abs(y2 - y1)")
    back = " - thickness" if sign < 0 else ""
    em.lines.append(f"{corner_x} = min(x1, x2)" + (back if across == 0 else ""))
    em.lines.append(f"{corner_y} = min(y1, y2)" + (back if across == 1 else ""))
    size = ([length, "thickness"] if run == 0 else ["thickness", length])
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    keyword: list[tuple[str, str]] = []
    stated = _stated_type(em, kw.get("predefined_type"))
    if stated is not None:
        keyword.append(("predefined_type", s.string(stated)))
    keyword.append(("frame", s.string("world")))
    em.lines.append(_geom_call(
        "add_box_element",
        [storey, s.string("IfcWall"), name, corner_x, corner_y, "z1",
         size[0], size[1], "height"],
        keyword, lead=f"{created} = "))
    em.created[kw["guid"]] = created


def _geom_copy_element(em: "_Emitter", kw: dict) -> None:
    s = em.style
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    name = s.string(kw["name"]) if kw.get("name") is not None else "None"
    em.lines.append(_geom_call(
        "copy_element",
        [em.ref(kw["guid"]), _gnum(kw["dx"]), _gnum(kw["dy"]), _gnum(kw["dz"]), name],
        [], lead=f"{created} = "))
    em.created[kw["new_guid"]] = created


def _geom_array_elements(em: "_Emitter", kw: dict) -> None:
    s = em.style
    source = em.fresh(s.name("product"))
    created = em.fresh(s.name("created"))
    comment = s.comment("create")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    gold_guids = list(kw["new_guids"])
    names = list(kw.get("names") or ())
    names = [names[i] if i < len(names) else None for i in range(len(gold_guids))]
    listed = ", ".join(s.string(n) if n is not None else "None" for n in names)
    em.lines.append(f"{source} = {em.ref(kw['guid'])}")
    em.lines.append(_geom_call(
        "array_elements",
        [source, repr(len(gold_guids)), _gnum(kw["dx"]), _gnum(kw["dy"]),
         _gnum(kw["dz"]), f"[{listed}]"],
        [], lead=f"{created} = "))
    for index, gold_guid in enumerate(gold_guids):
        em.created[gold_guid] = f"{created}[{index}]"


def _geom_add_space_boundary(em: "_Emitter", kw: dict) -> None:
    s = em.style
    comment = s.comment("relation")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    keyword: list[tuple[str, str]] = []
    physical = kw.get("physical_or_virtual") or "PHYSICAL"
    internal = kw.get("internal_or_external") or "INTERNAL"
    if physical != "PHYSICAL":
        keyword.append(("physical_or_virtual", s.string(physical)))
    if internal != "INTERNAL":
        keyword.append(("internal_or_external", s.string(internal)))
    if kw.get("name") is not None:
        keyword.append(("name", s.string(kw["name"])))
    em.lines.append(_geom_call(
        "add_space_boundary",
        [em.ref(kw["space_guid"]), em.ref(kw["element_guid"])], keyword))


def _geom_connect_elements(em: "_Emitter", kw: dict) -> None:
    s = em.style
    comment = s.comment("relation")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    keyword = [("name", s.string(kw["name"]))] if kw.get("name") is not None else []
    em.lines.append(_geom_call(
        "connect_elements",
        [em.ref(kw["relating_guid"]), em.ref(kw["related_guid"])], keyword))


#: What each pivot word of a ``rotate`` instruction means to the library.
_PIVOT_WORDS = {"origin": "own", "centre": "centre"}


def _geom_assign_material(em: "_Emitter", kw: dict) -> None:
    """A material association, handed to the library.

    The sentence gives the element and the material's name.  Whether the file
    already carries a material under that name, and which association the
    element has to lose first, are read off the model.
    """
    s = em.style
    # A batch assigns the same material to many elements, and one comment says
    # it for all of them.
    comment = s.comment("material") if em.fresh("material_note") == "material_note" else ""
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call(
        "assign_material",
        [em.ref(kw["guid"]), s.string(kw["material_name"])], []))


def _geom_assign_type(em: "_Emitter", kw: dict) -> None:
    """A type assignment, handed to the library.

    The sentence gives the element and the type object, which an earlier round
    found by name.  Whether other elements already sit under that type, and
    which assignment the element has to lose first, are read off the model.
    """
    s = em.style
    comment = s.comment("type") if em.fresh("type_note") == "type_note" else ""
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call(
        "assign_type", [em.ref(kw["guid"]), em.ref(kw["type_guid"])], []))


def _geom_move_filling(em: "_Emitter", kw: dict) -> None:
    """A door or a window moved into another wall, handed to the library.

    The sentence states the wall and how far along it the element goes.  Where
    the opening sits across that wall, how far the assembly rises and how deep
    the leaf becomes are read off the two walls, so none of them is written.
    """
    s = em.style
    along = (em.params or {}).get("along")
    if along is None:
        _emit_rehost_filling(em, kw)
        return
    comment = s.comment("rehost")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call(
        "move_filling", [em.ref(kw["guid"]), em.ref(kw["host_guid"]),
                         _gnum(along)], []))


def _geom_turn_element(em: "_Emitter", kw: dict) -> None:
    """A turn about the point the sentence names, handed to the library.

    The instruction gives the angle and says what the element turns about, its
    own placement origin or the centre of its plan, and the library reads that
    point off the element.
    """
    s = em.style
    pivot = _PIVOT_WORDS.get((em.params or {}).get("pivot"))
    if pivot is None:
        _emit_rotate(em, kw)
        return
    comment = s.comment("turn")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call(
        "turn_element", [em.ref(kw["guid"]), _gnum(kw["degrees"])],
        [("pivot", s.string(pivot))]))


def _geom_set_property(em: "_Emitter", kw: dict) -> None:
    """One property-set write, handed to the library.

    The value type the gold call carries is not stated in the instruction, and
    the library reads it off the property's own name, so the call writes only
    the set, the property and the value the sentence gives.
    """
    s = em.style
    comment = s.comment("property")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call(
        "set_property",
        [em.ref(kw["guid"]), s.string(kw["pset_name"]),
         s.string(kw["property_name"]), _value(s, kw["value"])], []))


def _geom_delete_filling(em: "_Emitter", kw: dict) -> None:
    s = em.style
    comment = s.comment("delete")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call("delete_filling", [em.ref(kw["guid"])], []))


def _geom_delete_element(em: "_Emitter", kw: dict) -> None:
    """One call takes the element, what it holds, and what it empties.

    ``geom.delete_element`` removes the element, the openings cut into it, the
    doors and windows those openings hold, and the relationship objects the
    removal leaves naming nothing, so the round says what the instruction says
    and nothing about how a removal is written.
    """
    s = em.style
    comment = s.comment("delete")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    em.lines.append(_geom_call("delete_element", [em.ref(kw["guid"])], []))


def _geom_delete_batch(em: "_Emitter", guids: list) -> None:
    """Several deletions written as one loop over the identifiers."""
    s = em.style
    comment = s.comment("delete")
    if comment:
        em.lines.append(comment.rstrip("\n"))
    listed = ", ".join(s.string(g) for g in guids)
    em.lines.append(f"for target_guid in ({listed}):")
    em.lines.append("    geom.delete_element(ifc.by_guid(target_guid))")


_GEOM_EMITTERS = {
    "add_filling": _geom_add_filling,
    "replace_filling": _geom_replace_filling,
    "add_box_element": _geom_add_box_element,
    "add_box_element_world": _geom_add_box_element_world,
    "add_box_element_world_turned": _geom_add_box_element_world,
    "add_wall_span": _geom_add_wall_span,
    "copy_element": _geom_copy_element,
    "array_elements": _geom_array_elements,
    "add_space_boundary": _geom_add_space_boundary,
    "connect_elements": _geom_connect_elements,
    "delete_filling_with_opening": _geom_delete_filling,
    "delete_element": _geom_delete_element,
    "set_property_value": _geom_set_property,
    "rehost_filling": _geom_move_filling,
    "rotate": _geom_turn_element,
    "assign_material": _geom_assign_material,
    "assign_type": _geom_assign_type,
}


_EMITTERS = {
    "translate": _emit_translate,
    "set_attribute": _emit_set_attribute,
    "set_length_attribute": _emit_set_length_attribute,
    "set_extrusion_depth": _emit_set_extrusion_depth,
    "set_profile_dimension": _emit_set_profile_dimension,
    "add_box_element": _emit_add_box_element,
    "add_filling": _emit_add_filling,
    "add_box_element_world": _emit_add_box_element_world,
    "add_box_element_world_turned": _emit_add_box_element_world,
    "add_wall_span": _emit_add_wall_span,
    "add_space_boundary": _emit_add_space_boundary,
    "connect_elements": _emit_connect_elements,
    "delete_filling_with_opening": _emit_delete_filling_with_opening,
    "rotate": _emit_rotate,
    "mirror": _emit_mirror,
    "set_property_value": _emit_set_property_value,
    "assign_material": _emit_assign_material,
    "assign_type": _emit_assign_type,
    "move_to_storey": _emit_move_to_storey,
    "rehost_filling": _emit_rehost_filling,
    "copy_element": _emit_copy_element,
    "array_elements": _emit_array_elements,
    "replace_filling": _emit_replace_filling,
}


#: Which keyword of each operation names an entity the model has to find first.
_EXISTING_GUID_ARG = {
    "translate": ("guid",),
    "set_attribute": ("guid",),
    "set_length_attribute": ("guid",),
    "set_extrusion_depth": ("guid",),
    "set_profile_dimension": ("guid",),
    "delete_element": ("guid",),
    "add_box_element": ("storey_guid",),
    "add_box_element_world": ("storey_guid",),
    "add_box_element_world_turned": ("storey_guid",),
    "add_wall_span": ("storey_guid",),
    "add_filling": ("host_guid",),
    "delete_filling_with_opening": ("guid",),
    "add_space_boundary": ("space_guid", "element_guid"),
    "connect_elements": ("relating_guid", "related_guid"),
    "rotate": ("guid",),
    "mirror": ("guid",),
    "set_property_value": ("guid",),
    "assign_material": ("guid",),
    "assign_type": ("guid", "type_guid"),
    "move_to_storey": ("guid", "storey_guid"),
    "rehost_filling": ("guid", "host_guid"),
    "copy_element": ("guid",),
    "array_elements": ("guid",),
    "replace_filling": ("guid", "host_guid"),
}


#: Which keyword of each operation names the entities the edit itself creates,
#: whose identifiers are drawn fresh and therefore never looked up.
_CREATED_GUID_ARG = {
    "add_box_element": "guid",
    "add_box_element_world": "guid",
    "add_box_element_world_turned": "guid",
    "add_wall_span": "guid",
    "add_filling": "guid",
    "copy_element": "new_guid",
    "replace_filling": "new_guid",
    "array_elements": "new_guids",
}


def referenced_guids(calls: list[GoldCall], geom: bool = False) -> list[str]:
    """Identifiers of entities the emitted code looks up in the model.

    Identifiers the edit itself creates are excluded: they are drawn fresh and
    held in a variable. What remains is what a trajectory has to have found
    before the edit runs, either from the instruction or from an inspection
    round, and that is the coherence property the synthesizer checks.
    """
    created: set[str] = set()
    needed: list[str] = []
    for call in calls:
        keys = _EXISTING_GUID_ARG.get(call.func, ())
        if geom and call.func == "replace_filling":
            # The library reads the wall off the element it replaces, so the
            # edit never names the wall and no round has to find it.
            keys = tuple(key for key in keys if key != "host_guid")
        for key in keys:
            value = call.kwargs.get(key)
            if value and value not in created and value not in needed:
                needed.append(value)
        key = _CREATED_GUID_ARG.get(call.func)
        if key == "new_guids":
            created.update(call.kwargs.get(key) or ())
        elif key is not None:
            created.add(call.kwargs[key])
    return needed


def required_helpers(calls: list[GoldCall], geom: bool = False) -> set[str]:
    needed: set[str] = set()
    for call in calls:
        if geom and call.func in GEOM_CALLS:
            # The library builds the geometry and the relationships itself, so
            # none of the hand-written helpers is written for these calls.
            continue
        needed.update(_NEEDS.get(call.func, ()))
        if call.func in ("add_box_element", "add_box_element_world",
                         "add_box_element_world_turned"):
            if call.kwargs.get("ifc_class") == "IfcSpace":
                needed.add("aggregate")
            else:
                needed.add("contain")
    return needed


@dataclass
class EmittedEdit:
    """The edit snippet plus what a later turn needs to know about it."""

    code: str
    created_vars: list[str] = field(default_factory=list)
    referenced_guids: list[str] = field(default_factory=list)
    removed_guids: list[str] = field(default_factory=list)


def emit_edit(calls: list[GoldCall], style: Style,
              params: dict | None = None, instruction: str = "") -> EmittedEdit:
    """Plain IfcOpenShell source for one task's edit, against the pre-bound model.

    ``params`` is the task's ``edit_params``. Under the library style it decides
    which wording a create call was written from, so the emitted call carries
    the number the instruction states and the library derives the rest.
    """
    geom = bool(style.geom_lib)
    needed = required_helpers(calls, geom)
    parts: list[str] = []

    imports: list[str] = []
    if "math" in needed:
        imports.append("import math")
    if "numpy" in needed:
        imports.append("import numpy as np")
    if "placement" in needed:
        imports.append("import ifcopenshell.util.placement")
    if "scale" in needed:
        imports.append("import ifcopenshell.util.unit")
    if "util_element" in needed:
        imports.append("import ifcopenshell.util.element")
    if "api_root" in needed:
        imports.append("import ifcopenshell.api.root")
    if imports:
        parts.append("\n".join(imports))

    preamble: list[str] = []
    if "scale" in needed:
        comment = style.comment("units")
        if comment:
            preamble.append(comment.rstrip("\n"))
        preamble.append(
            f"{style.name('scale')} = ifcopenshell.util.unit.calculate_unit_scale(ifc)"
        )
    if "history" in needed:
        preamble.append(
            f"{style.name('history')} = min(ifc.by_type('IfcOwnerHistory'), "
            f"key=lambda h: h.id(), default=None)"
        )
    if preamble:
        parts.append("\n".join(preamble))

    for key in _HELPER_ORDER:
        if key in needed:
            parts.append(_HELPER_BUILDERS[key](style).rstrip("\n"))

    emitter = _Emitter(style=style, params=dict(params or {}),
                       instruction=instruction or "")
    index = 0
    while index < len(calls):
        call = calls[index]
        if call.func == "delete_element":
            run = [call.kwargs["guid"]]
            while index + 1 < len(calls) and calls[index + 1].func == "delete_element":
                index += 1
                run.append(calls[index].kwargs["guid"])
            if len(run) >= 3:
                if geom:
                    _geom_delete_batch(emitter, run)
                else:
                    _emit_delete_batch(emitter, run)
            elif geom:
                for gold_guid in run:
                    _geom_delete_element(emitter, {"guid": gold_guid})
            else:
                comment = style.comment("delete")
                if comment:
                    emitter.lines.append(comment.rstrip("\n"))
                for gold_guid in run:
                    emitter.lines.append(
                        "ifcopenshell.api.root.remove_product("
                        f"ifc, product={emitter.ref(gold_guid)})"
                    )
        elif geom and call.func in _GEOM_EMITTERS:
            _GEOM_EMITTERS[call.func](emitter, call.kwargs)
        else:
            _EMITTERS[call.func](emitter, call.kwargs)
        index += 1
    parts.append("\n".join(emitter.lines))

    code = "\n\n".join(p for p in parts if p.strip()) + "\n"
    found = referenced_guids(calls, geom)
    for guid in emitter.extra_refs:
        if guid not in found and guid not in emitter.created:
            found.append(guid)
    return EmittedEdit(
        code=code,
        created_vars=list(emitter.created.values()),
        referenced_guids=found,
        removed_guids=[c.kwargs["guid"] for c in calls
                       if c.func in ("delete_element",
                                     "delete_filling_with_opening",
                                     "replace_filling")],
    )


def emit_edit_code(calls: list[GoldCall], style: Style) -> str:
    """The snippet on its own, for callers that need nothing else."""
    return emit_edit(calls, style).code
