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
Add a new wall named 'Partition 626' on the storey that contains the wall named 'Basic Wall:Generic - 8":340729', 4 m long, 0.2 m thick and 2.9 m high, with its lowest corner at (219906.36, 907188.26, 73.46) m in world coordinates, set out along that storey's own axes, which run 68 degrees counter-clockwise from the world axes. Give it the predefined type PARTITIONING.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Generic - 8":340729']
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('3UPoyR0HD5gQ1Y7251gt8D', 'IfcWallStandardCase', 'Basic Wall:Generic - 8":340729')]
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('3UPoyR0HD5gQ1Y7251gt8D')
floor = None
for rel in getattr(element, 'ContainedInStructure', None) or ():
    floor = rel.RelatingStructure
    break
if floor is None:
    for rel in getattr(element, 'Decomposes', None) or ():
        floor = rel.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3UPoyR0HD5gQ1Y7251gt8D IfcWallStandardCase Basic Wall:Generic - 8":340729 is contained in 1MvMAoc2L5LRJwssbEGeCK IfcBuildingStorey TO Screen Wall elevation 58.3333333333327
model length unit in metres: 0.3048
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((219906.36, 219906.36), (907188.26, 907188.26), (73.46, 73.46), (4.0, 4.0), (0.2, 0.2), (2.9, 2.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
219906.36 m = 219906.36 m = 721477.559055 file units
907188.26 m = 907188.26 m = 2976339.435696 file units
73.46 m = 73.46 m = 241.010499 file units
4.0 m = 4.0 m = 13.12336 file units
0.2 m = 0.2 m = 0.656168 file units
2.9 m = 2.9 m = 9.514436 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
floor = ifc.by_guid('1MvMAoc2L5LRJwssbEGeCK')
added = geom.add_box_element(floor, 'IfcWall', 'Partition 626', 219906.36, 907188.26,
                             73.46, 4.0, 0.2, 2.9, predefined_type='PARTITIONING',
                             frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(added.GlobalId, added.is_a(), added.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
1gZDKCW5nEvg3_$F43yXPp IfcWall Partition 626
model committed
```
Assistant: The wall has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Add a new wall named 'Partition 305' on the storey that contains the slab with ID '2NHvq8aQHFkOm$eQh4wVay', 4 m long, 0.2 m thick and 3.93 m high, with its lowest corner at (219933.22, 907152.32, 66.65) m in world coordinates, set out along that storey's own axes, which run 68 degrees counter-clockwise from the world axes. Give it the predefined type PARTITIONING.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid("2NHvq8aQHFkOm$eQh4wVay")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('2NHvq8aQHFkOm$eQh4wVay', 'IfcSlab', 'Floor:Floor Finish - RF-3:1248581')]
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid("2NHvq8aQHFkOm$eQh4wVay")
floor = None
for link in getattr(product, 'ContainedInStructure', None) or ():
    floor = link.RelatingStructure
    break
if floor is None:
    for link in getattr(product, 'Decomposes', None) or ():
        floor = link.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2NHvq8aQHFkOm$eQh4wVay IfcSlab Floor:Floor Finish - RF-3:1248581 is contained in 00Anm4s4r7luYkA9gSEr4H IfcBuildingStorey FLOOR 3 elevation 218.666666666667
model length unit in metres: 0.3048
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((219933.22, 219933.22), (907152.32, 907152.32), (66.65, 66.65), (4.0, 4.0), (0.2, 0.2), (3.93, 3.93),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
219933.22 m = 219933.22 m = 721565.682415 file units
907152.32 m = 907152.32 m = 2976221.52231 file units
66.65 m = 66.65 m = 218.667979 file units
4.0 m = 4.0 m = 13.12336 file units
0.2 m = 0.2 m = 0.656168 file units
3.93 m = 3.93 m = 12.893701 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
floor = ifc.by_guid("00Anm4s4r7luYkA9gSEr4H")
added = geom.add_box_element(floor, "IfcWall", "Partition 305", 219933.22, 907152.32,
                             66.65, 4.0, 0.2, 3.93, predefined_type="PARTITIONING",
                             frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
3D$RG0kXn7HuSZRHlMLGcb IfcWall Partition 305
model committed
```
Assistant: Finished: the wall has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Add a new wall named 'Partition 424' on the storey that contains the wall named 'Basic Wall:Foundation - 375mm Concrete w_step:208780', 4 m long, 0.2 m thick and 4.9 m high, with its lowest corner at (9.39, 89.73, 165.81) m in world coordinates, set out along that storey's own axes, which run 5 degrees counter-clockwise from the world axes. Give it the predefined type MOVABLE.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
found = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Foundation - 375mm Concrete w_step:208780']
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3iM76qwej9Tf9ttHcbQqRA IfcWall Basic Wall:Foundation - 375mm Concrete w_step:208780
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid('3iM76qwej9Tf9ttHcbQqRA')
storey = None
for link in getattr(target, 'ContainedInStructure', None) or ():
    storey = link.RelatingStructure
    break
if storey is None:
    for link in getattr(target, 'Decomposes', None) or ():
        storey = link.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3iM76qwej9Tf9ttHcbQqRA IfcWall Basic Wall:Foundation - 375mm Concrete w_step:208780 is contained in 1fOVjSd7T40PyRtVEklS6X IfcBuildingStorey Level 1 elevation 6.59062507910815e-10
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((9.39, 9.39), (89.73, 89.73), (165.81, 165.81), (4.0, 4.0), (0.2, 0.2), (4.9, 4.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
9.39 m = 9.39 m = 9390.0 file units
89.73 m = 89.73 m = 89730.0 file units
165.81 m = 165.81 m = 165810.0 file units
4.0 m = 4.0 m = 4000.0 file units
0.2 m = 0.2 m = 200.0 file units
4.9 m = 4.9 m = 4900.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
storey = ifc.by_guid('1fOVjSd7T40PyRtVEklS6X')
new_element = geom.add_box_element(storey, 'IfcWall', 'Partition 424', 9.39, 89.73,
                                   165.81, 4.0, 0.2, 4.9, predefined_type='MOVABLE',
                                   frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

commit()
print('model committed')
```
Tool result:
```
0d$Yv4Taz23uHu3rKc6Ij2 IfcWall Partition 424
model committed
```
Assistant: The wall has been created and placed on its storey. The edited model is committed.
