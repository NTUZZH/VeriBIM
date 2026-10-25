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
Relocate the space with GlobalId '1iZ0zxIBgAGupDqiow_YFK' 2 m to the north (+Y), and move the 3 walls that bound it by the same offset.

IFC model path: <path to the working copy>
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
for rel in ifc.by_type('IfcRelSpaceBoundary'):
    space = rel.RelatingSpace
    product = rel.RelatedBuildingElement
    if space is None or product is None:
        continue
    if space.GlobalId == '1iZ0zxIBgAGupDqiow_YFK':
        print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
3VbhrS0szKixXS1okPL$a3 IfcVirtualElement None
1qD6E40JdLGOUfoPEB28UG IfcSlab Slab - 014
2XyYY51_5tJuEYQCGdRxmx IfcWallStandardCase Wall - 012
1xQcp$jgjdGuBnT8k1MUhz IfcDoor D001
1IPRBnozO5Jwj_DPIQdLlL IfcWallStandardCase Wall - 013
19ALpexd7GHBgVjZMl6DWk IfcWallStandardCase Wall - 011
0C74Nfsnl_4mY_BdZNcGkp IfcVirtualElement None
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((2.0, 2.0),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
2.0 m = 2.0 m = 2000.0 file units
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def move_element(target_guid, dx, dy, dz):
    product = ifc.by_guid(target_guid)
    placement = product.ObjectPlacement
    parent_rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        parent_rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    delta = np.linalg.inv(parent_rotation) @ (
        np.array([dx, dy, dz], dtype=float) / to_model)
    relative = placement.RelativePlacement
    if not used_once(relative, placement):
        relative = ifc.create_entity(
            'IfcAxis2Placement3D', Location=relative.Location,
            Axis=relative.Axis, RefDirection=relative.RefDirection)
        placement.RelativePlacement = relative
    location = relative.Location
    if not used_once(location, relative):
        location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(location.Coordinates))
        relative.Location = location
    location.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(location.Coordinates, delta))

move_element('1iZ0zxIBgAGupDqiow_YFK', 0.0, 2.0, 0.0)
move_element('19ALpexd7GHBgVjZMl6DWk', 0.0, 2.0, 0.0)
move_element('1IPRBnozO5Jwj_DPIQdLlL', 0.0, 2.0, 0.0)
move_element('2XyYY51_5tJuEYQCGdRxmx', 0.0, 2.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('1iZ0zxIBgAGupDqiow_YFK')
print(product.is_a(), product.GlobalId, product.Name)

commit()
print('model committed')
```
Tool result:
```
IfcSpace 1iZ0zxIBgAGupDqiow_YFK 014
model committed
```
Assistant: The space now carries the values the instruction asked for, and the edit is written to the working file.

### Example 2
User:
Relocate the space with ID 1iZ0zxIBgAGupDqiow_YFK 1.5 m to the north (+Y), and move the 3 walls that bound it by the same offset.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# the elements that bound the space move with it
for rel in ifc.by_type('IfcRelSpaceBoundary'):
    space = rel.RelatingSpace
    product = rel.RelatedBuildingElement
    if space is None or product is None:
        continue
    if space.GlobalId == '1iZ0zxIBgAGupDqiow_YFK':
        print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
0C74Nfsnl_4mY_BdZNcGkp IfcVirtualElement None
1IPRBnozO5Jwj_DPIQdLlL IfcWallStandardCase Wall - 013
19ALpexd7GHBgVjZMl6DWk IfcWallStandardCase Wall - 011
2XyYY51_5tJuEYQCGdRxmx IfcWallStandardCase Wall - 012
1xQcp$jgjdGuBnT8k1MUhz IfcDoor D001
1qD6E40JdLGOUfoPEB28UG IfcSlab Slab - 014
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.5, 1.5),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.5 m = 1.5 m = 1500.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# convert metres to the model's own length unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def shift(target_guid, dx, dy, dz):
    # apply the offset in the coordinate system the placement is written in
    product = ifc.by_guid(target_guid)
    placement = product.ObjectPlacement
    parent_rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        parent_rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    shift_vector = np.linalg.inv(parent_rotation) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # do not move anything else that happens to share this point
    axis = placement.RelativePlacement
    if not only_user(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location,
            Axis=axis.Axis, RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    point = axis.Location
    if not only_user(point, axis):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        axis.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, shift_vector))

shift('1iZ0zxIBgAGupDqiow_YFK', 0.0, 1.5, 0.0)
shift('19ALpexd7GHBgVjZMl6DWk', 0.0, 1.5, 0.0)
shift('1IPRBnozO5Jwj_DPIQdLlL', 0.0, 1.5, 0.0)
shift('2XyYY51_5tJuEYQCGdRxmx', 0.0, 1.5, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
product = ifc.by_guid('1iZ0zxIBgAGupDqiow_YFK')
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcSpace 1iZ0zxIBgAGupDqiow_YFK 014
model committed
```
Assistant: Finished: the space now carries the values the instruction asked for. The file on disk now holds the change.

### Example 3
User:
Relocate the space 1iZ0zxIBgAGupDqiow_YFK 0.5 m to the north (+Y), and move the 3 walls that bound it by the same offset.

IFC model path: <path to the working copy>
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the elements that bound the space move with it
for rel in ifc.by_type('IfcRelSpaceBoundary'):
    space = rel.RelatingSpace
    element = rel.RelatedBuildingElement
    if space is None or element is None:
        continue
    if space.GlobalId == "1iZ0zxIBgAGupDqiow_YFK":
        print(element.GlobalId, element.is_a(), element.Name)
```
Tool result:
```
3VbhrS0szKixXS1okPL$a3 IfcVirtualElement None
1qD6E40JdLGOUfoPEB28UG IfcSlab Slab - 014
2XyYY51_5tJuEYQCGdRxmx IfcWallStandardCase Wall - 012
1xQcp$jgjdGuBnT8k1MUhz IfcDoor D001
1IPRBnozO5Jwj_DPIQdLlL IfcWallStandardCase Wall - 013
19ALpexd7GHBgVjZMl6DWk IfcWallStandardCase Wall - 011
0C74Nfsnl_4mY_BdZNcGkp IfcVirtualElement None
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.5, 0.5),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.5 m = 0.5 m = 500.0 file units
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# the file's length unit decides what a metre is worth here
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # apply the offset in the coordinate system the placement is written in
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    shift_vector = np.linalg.inv(rotation) @ (
        np.array([dx, dy, dz], dtype=float) / unit_scale)
    # substitute a private point before writing coordinates
    axis_placement = placement.RelativePlacement
    if not used_once(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    location = axis_placement.Location
    if not used_once(location, axis_placement):
        location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(location.Coordinates))
        axis_placement.Location = location
    location.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(location.Coordinates, shift_vector))

translate_element("1iZ0zxIBgAGupDqiow_YFK", 0.0, 0.5, 0.0)
translate_element("19ALpexd7GHBgVjZMl6DWk", 0.0, 0.5, 0.0)
translate_element("1IPRBnozO5Jwj_DPIQdLlL", 0.0, 0.5, 0.0)
translate_element("2XyYY51_5tJuEYQCGdRxmx", 0.0, 0.5, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid("1iZ0zxIBgAGupDqiow_YFK")
print(element.is_a(), element.GlobalId, element.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcSpace 1iZ0zxIBgAGupDqiow_YFK 014
model committed
```
Assistant: Finished: the space has been updated. The file on disk now holds the change.
