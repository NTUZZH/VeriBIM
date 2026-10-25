Note: the execution namespace also holds a helper library bound as `geom` (Python module `veribim_geom`, built on ifcopenshell and numpy). Every length it takes or returns is in metres, whatever the file's own unit. Lookups return exactly one element or raise a LookupError that names the nearest candidates. Available functions:

This `geom` is the helper module `veribim_geom`, not `ifcopenshell.geom`; the ifcopenshell geometry module is reached as `ifcopenshell.geom` if it is needed.

Measuring
- geom.unit_scale(model_or_entity): metres per file length unit.
- geom.world_box(product): the product's axis-aligned box in world metres, as (lo, hi).
- geom.wall_box(wall): the wall's own body in its placement frame: start, end, near, far, base, top, length, thickness, height.
- geom.box_in_frame(product, frame_product): a product's box in another product's coordinate system.
- geom.origin_in_frame(product, frame_product): a product's placement origin read in another product's frame.
- geom.origin_point(product) / geom.centre(product): placement origin / body centre in world metres.
- geom.filling_slot(filling): where a door or window sits in its host wall: host, along, sill, width, height.
- geom.storey_of(product), geom.host_wall_of(filling), geom.opening_of(filling).
- geom.on_storey(storey, ifc_class): every element of one class the storey holds.
- geom.hosted_in(wall, ifc_class=''): the doors and windows a wall hosts.
- geom.bounding_elements(space, ifc_class=''): the elements recorded as bounding a space.
- geom.storey_above(storey), geom.storey_below(storey).
- geom.measure(product, name): one measurement by the word a phrase uses ('plan_length', 'height', 'overall_width').

Finding the element a sentence describes
- geom.find_offset(reference, ifc_class, storey, direction, distance): "the wall on storey S about 12.4 m east of X" -> find_offset(X, 'IfcWall', S, 'east', 12.4).
- geom.find_extreme(ifc_class, storey, direction): "the slab furthest north on storey S".
- geom.find_nearest(reference, ifc_class, storey): "the column nearest to X on storey S".
- geom.find_between(a, b, ifc_class, storey): "the wall between A and B".
- geom.find_ordinal(host, ifc_class, direction, index): "the second window from the south along wall W" -> find_ordinal(W, 'IfcWindow', 'south', 2).
- geom.find_opposite(reference, ifc_class, space): "the wall opposite W across space S".
- geom.find_beside_door(door, space, side, ifc_class): "the wall on the left-hand side as seen from door D looking into space S".
- geom.find_above_below(reference, ifc_class, direction, storey=None): "the column directly above X".

Placing
- geom.spot_on_top_of(reference): where a new element stands to sit on a reference element's top face.
- geom.spot_beside(wall, space, length, width): where a new element stands against a wall, inside a space, touching it.

Editing (each call also writes the relationships the edit needs)
- geom.add_filling(host_wall, ifc_class, name, width, height, along, sill=0.0, predefined_type=None, along_is_centre=False): cut an opening in a wall and fill it with a door or window.
- geom.replace_filling(old_filling, ifc_class, name, width, height, sill=0.0, predefined_type=None): swap a door for a window or a window for a door in the same wall.
- geom.delete_filling(filling): remove a door or window together with the opening it filled.
- geom.move_filling(filling, host_wall, along, sill=None): move a door or window, with its opening, into another wall.
- geom.add_box_element(storey, ifc_class, name, x, y, z, dx, dy, dz, predefined_type=None, frame='storey'|'world'): create a box-shaped element on a storey.
- geom.copy_element(product, dx, dy, dz, name=None); geom.array_elements(product, count, dx, dy, dz, names=()).
- geom.turn_element(element, degrees, pivot='own'|'centre'|(x, y)): turn an element about the vertical axis.
- geom.set_property(element, pset_name, property_name, value): write one property into a named property set.
- geom.add_space_boundary(space, element); geom.connect_elements(relating, related); geom.place_in_structure(product, storey).

## Three worked examples (reference dialogues on other buildings)

### Example 1
User:
Delete the space on storey '2. Story' that stands about 18.1 m north (+Y) of the room with ID 37b1xsX9XqJgUBwtrE2J82 from the model, together with the relationships that depend on it.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
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

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', '2. Story')
reference = ifc.by_guid('37b1xsX9XqJgUBwtrE2J82')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
found = [geom.find_offset(reference, 'IfcSpace', storey,
                          'north', 18.1)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named '2. Story' -> 3y21AUC9X4yAqzLGUny16E IfcBuildingStorey 2. Story
given -> 37b1xsX9XqJgUBwtrE2J82 IfcSpace 15
[('27eX8tgYl7HejrY2o_eUuK', 'IfcSpace', '17')]
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid('27eX8tgYl7HejrY2o_eUuK'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('27eX8tgYl7HejrY2o_eUuK',) if g in present])

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The space and the relationships that depended on it are gone, and the edit is written to the working file.

### Example 2
User:
Move the window on storey 'Level 2' that stands about 26.7 m west (-X) of the window named 'W009' 3.83 m to the north (+Y).

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
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

# find the element at the stated offset from the named neighbour
storey = by_name("IfcBuildingStorey", "Level 2")
reference = by_name("IfcWindow", "W009")
matches = [geom.find_offset(reference, "IfcWindow", storey,
                            "west", 26.7)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 2' -> 1z8TJmsjXxHx_FFfOhdrEh IfcBuildingStorey Level 2
named 'W009' -> 2p7ZSq4UgAIPCTci8J_N0N IfcWindow W009
0qmFiUJtkrGfn6LZjRTmnD IfcWindow W006
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the wall the element stands in now
filling = ifc.by_guid("0qmFiUJtkrGfn6LZjRTmnD")
for fills in filling.FillsVoids or ():
    opening = fills.RelatingOpeningElement
    for voids in (opening.VoidsElements or ()) if opening else ():
        host = voids.RelatingBuildingElement
        if host is None:
            continue
        print('opening', opening.GlobalId, 'is cut in', host.GlobalId, host.is_a(), host.Name)
```
Tool result:
```
opening 2pleIG0Cr_XQSlUPsG7Uax is cut in 0$w3o50cgJGOpeOW3jR5Ti IfcWallStandardCase Wall - 023
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((3.83, 3.83),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
3.83 m = 3.83 m = 3830.0 file units
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# lengths in the instruction are metres; the model may use other units
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def is_sole_owner(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # apply the offset in the coordinate system the placement is written in
    product = ifc.by_guid(target_guid)
    placement = product.ObjectPlacement
    parent_rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        parent_rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    offset = np.linalg.inv(parent_rotation) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # substitute a private point before writing coordinates
    axis_placement = placement.RelativePlacement
    if not is_sole_owner(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    location = axis_placement.Location
    if not is_sole_owner(location, axis_placement):
        location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(location.Coordinates))
        axis_placement.Location = location
    location.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(location.Coordinates, offset))

translate_element("2pleIG0Cr_XQSlUPsG7Uax", 0.0, 3.83, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
product = ifc.by_guid("2pleIG0Cr_XQSlUPsG7Uax")
print(product.is_a(), product.GlobalId, product.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcOpeningElement 2pleIG0Cr_XQSlUPsG7Uax W006
model committed
```
Assistant: Finished: the window has been updated. The file on disk now holds the change.

### Example 3
User:
Relocate the space on the storey with ID 3edQNiDA9BMfnQgyxoNyj_ that stands about 12.2 m west (-X) of the room with ID 3iSzpa9d93jhTDB7hG0QBW 1.5 m to the south (-Y), and move the 4 walls that bound it by the same offset.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element at the stated offset from the named neighbour
storey = ifc.by_guid('3edQNiDA9BMfnQgyxoNyj_')
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid('3iSzpa9d93jhTDB7hG0QBW')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
matches = [geom.find_offset(reference, 'IfcSpace', storey,
                            'west', 12.2)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3edQNiDA9BMfnQgyxoNyj_ IfcBuildingStorey 1. Obergeschoss
given -> 3iSzpa9d93jhTDB7hG0QBW IfcSpace 205
3shuyF_Yb7yu2P$QLB2s8G IfcSpace 202
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the elements that bound the space move with it
for link in ifc.by_type('IfcRelSpaceBoundary'):
    space = link.RelatingSpace
    target = link.RelatedBuildingElement
    if space is None or target is None:
        continue
    if space.GlobalId == '3shuyF_Yb7yu2P$QLB2s8G':
        print(target.GlobalId, target.is_a(), target.Name)
```
Tool result:
```
3qz8vRMKXCHubRHdl$maGl IfcDoor Tür-004
2Og5$70yb1DxR1TY1w8bzN IfcSlab Decke-001
33jlsNXXLCaQ28opnwDi77 IfcWallStandardCase Wand-018
3EtzNx_Z1BD9$bnmCd_7Ak IfcSlab Decke-002
1y52BJ9iLBoAyZV5YvNxz0 IfcWallStandardCase Wand-019
14tRml$oP0Rhmg9zCpGzdf IfcWindow Fenster-002
0AlQO9vJD8yQs$jjO$RhN4 IfcWindow Fenster-002
2muLeR9tf5FfEKGfOAn8sb IfcWindow Fenster-002
0L1ke1dG93fxxhtLVwOTsT IfcWindow Fenster-002
2udBPbKibCZ8zbfpJmtDTM IfcWallStandardCase Wand-010
3Tizqrq5LBwRkVzeahshML IfcWallStandardCase Wand-014
2Og5$70yb1DxR1TY1w8bzN IfcSlab Decke-001
2Og5$70yb1DxR1TY1w8bzN IfcSlab Decke-001
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# the file's length unit decides what a metre is worth here
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def is_sole_owner(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # apply the offset in the coordinate system the placement is written in
    target = ifc.by_guid(target_guid)
    placement = target.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    offset = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / to_model)
    # substitute a private point before writing coordinates
    relative = placement.RelativePlacement
    if not is_sole_owner(relative, placement):
        relative = ifc.create_entity(
            'IfcAxis2Placement3D', Location=relative.Location,
            Axis=relative.Axis, RefDirection=relative.RefDirection)
        placement.RelativePlacement = relative
    point = relative.Location
    if not is_sole_owner(point, relative):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        relative.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, offset))

translate_element('3shuyF_Yb7yu2P$QLB2s8G', 0.0, -1.5, 0.0)
translate_element('1y52BJ9iLBoAyZV5YvNxz0', 0.0, -1.5, 0.0)
translate_element('2udBPbKibCZ8zbfpJmtDTM', 0.0, -1.5, 0.0)
translate_element('33jlsNXXLCaQ28opnwDi77', 0.0, -1.5, 0.0)
translate_element('3Tizqrq5LBwRkVzeahshML', 0.0, -1.5, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
target = ifc.by_guid('3shuyF_Yb7yu2P$QLB2s8G')
print(target.is_a(), target.GlobalId, target.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
IfcSpace 3shuyF_Yb7yu2P$QLB2s8G 202
model committed
```
Assistant: Completed. The space has been updated; the model was committed.
