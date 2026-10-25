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
Move the IfcColumn on the storey (ID: 1fOVjSd7T40PyRtVEklqJV) that stands about 26.6 m west (-X) of the column (ID: 1cVJlS_6n6jgnWbqp2enFc) 1.22 m to the east (+X).

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element at the stated offset from the named neighbour
storey = ifc.by_guid('1fOVjSd7T40PyRtVEklqJV')
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid('1cVJlS_6n6jgnWbqp2enFc')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
hits = [geom.find_offset(reference, 'IfcColumn', storey,
                         'west', 26.6)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
given -> 1fOVjSd7T40PyRtVEklqJV IfcBuildingStorey Level 3 TOS
given -> 1cVJlS_6n6jgnWbqp2enFc IfcColumn UC-Universal Column-Column:356x368x177UC:267662
[('1cVJlS_6n6jgnWbqp2enFe', 'IfcColumn', 'UC-Universal Column-Column:356x368x177UC:267648')]
```
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * scale

for target_guid in ('1cVJlS_6n6jgnWbqp2enFe',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcColumn 1cVJlS_6n6jgnWbqp2enFe UC-Universal Column-Column:356x368x177UC:267648
  origin (m): [-4.695, 84.031, 165.811]
  contained in: ['Level 3 TOS']
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.22, 1.22),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.22 m = 1.22 m = 1220.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# convert metres to the model's own length unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def move_element(target_guid, dx, dy, dz):
    # shift the element, keeping whatever is placed relative to it
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    offset = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # the placement may share its point with others, so give it its own
    axis = placement.RelativePlacement
    if not used_once(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location,
            Axis=axis.Axis, RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    origin = axis.Location
    if not used_once(origin, axis):
        origin = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(origin.Coordinates))
        axis.Location = origin
    origin.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(origin.Coordinates, offset))

move_element('1cVJlS_6n6jgnWbqp2enFe', 1.22, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
element = ifc.by_guid('1cVJlS_6n6jgnWbqp2enFe')
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcColumn 1cVJlS_6n6jgnWbqp2enFe UC-Universal Column-Column:356x368x177UC:267648
model committed
```
Assistant: Done. The column now carries the values the instruction asked for, and the model has been saved.

### Example 2
User:
Move the wall on the storey with ID 3Zu5Bv0LOHrPC10026FoQQ that stands about 17.4 m east (+X) of the column with ID 0xyVneVyX9VAQy52Zl3yDk 0.73 m to the west (-X).

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
storey = ifc.by_guid("3Zu5Bv0LOHrPC10026FoQQ")
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid("0xyVneVyX9VAQy52Zl3yDk")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
found = [geom.find_offset(reference, "IfcWall", storey,
                          "east", 17.4)]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Ground Floor
given -> 0xyVneVyX9VAQy52Zl3yDk IfcColumn Structural RC Column:Column Type 1:368261
1iqW__JrL2sAEomqsbKP5b IfcWall Basic Wall:Structural shear wall Type1:414801
```
Assistant: Reading the current state of the target.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * to_model

for target_guid in ("1iqW__JrL2sAEomqsbKP5b",):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWall 1iqW__JrL2sAEomqsbKP5b Basic Wall:Structural shear wall Type1:414801
  origin (m): [0.55, 4.111, -2.0]
  contained in: ['Ground Floor']
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.73, 0.73),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
0.73 m = 0.73 m = 73.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def shift(target_guid, dx, dy, dz):
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    parent_rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        parent_rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    delta = np.linalg.inv(parent_rotation) @ (
        np.array([dx, dy, dz], dtype=float) / to_model)
    axis = placement.RelativePlacement
    if not used_once(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location,
            Axis=axis.Axis, RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    origin = axis.Location
    if not used_once(origin, axis):
        origin = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(origin.Coordinates))
        axis.Location = origin
    origin.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(origin.Coordinates, delta))

shift("1iqW__JrL2sAEomqsbKP5b", -0.73, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
element = ifc.by_guid("1iqW__JrL2sAEomqsbKP5b")
print(element.is_a(), element.GlobalId, element.Name)

commit()
print("model committed")
```
Tool result:
```
IfcWall 1iqW__JrL2sAEomqsbKP5b Basic Wall:Structural shear wall Type1:414801
model committed
```
Assistant: Finished: the wall now carries the values the instruction asked for. The file on disk now holds the change.

### Example 3
User:
Shift the IfcWindow on the storey with ID 3hJpVTIdb2fhTTVvI3Hc20 that stands about 24.7 m east (+X) of the window with ID 0_CJ6FjXD118MUZNG8Gru$ by 2.47 m in the -y direction.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element at the stated offset from the named neighbour
storey = ifc.by_guid('3hJpVTIdb2fhTTVvI3Hc20')
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid('0_CJ6FjXD118MUZNG8Gru$')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
hits = [geom.find_offset(reference, 'IfcWindow', storey,
                         'east', 24.7)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3hJpVTIdb2fhTTVvI3Hc20 IfcBuildingStorey Level 3
given -> 0_CJ6FjXD118MUZNG8Gru$ IfcWindow M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:441153
0_CJ6FjXD118MUZNG8Gr_K IfcWindow M_Window-Sliding-Four:1650 x 600mm:441066
```
Assistant tool call execute_ifc_code:
```python
# the wall the element stands in now
leaf = ifc.by_guid('0_CJ6FjXD118MUZNG8Gr_K')
for fills in leaf.FillsVoids or ():
    opening = fills.RelatingOpeningElement
    for voids in (opening.VoidsElements or ()) if opening else ():
        host = voids.RelatingBuildingElement
        if host is None:
            continue
        print('opening', opening.GlobalId, 'is cut in', host.GlobalId, host.is_a(), host.Name)
```
Tool result:
```
opening 1_X9zYilPR7JF3L2bhWvzF is cut in 0_CJ6FjXD118MUZNG8Gr$e IfcWall Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P:440982
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

def move_element(target_guid, dx, dy, dz):
    # move the element by a world-axis offset
    target = ifc.by_guid(target_guid)
    placement = target.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    shift_vector = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # substitute a private point before writing coordinates
    axis_placement = placement.RelativePlacement
    if not only_user(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    point = axis_placement.Location
    if not only_user(point, axis_placement):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        axis_placement.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, shift_vector))

move_element('1_X9zYilPR7JF3L2bhWvzF', 0.0, -2.47, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid('1_X9zYilPR7JF3L2bhWvzF')
print(target.is_a(), target.GlobalId, target.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
IfcOpeningElement 1_X9zYilPR7JF3L2bhWvzF M_Window-Sliding-Four:1650 x 600mm:441066:1
model committed
```
Assistant: Completed. The window now carries the values the instruction asked for; the model was committed.
