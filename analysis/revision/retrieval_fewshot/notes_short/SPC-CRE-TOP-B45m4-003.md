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
Add a new space named 'Room 998' on the storey that contains the wall named 'Basic Wall:Exterior - Metal Panel on Mtl. Stud:219988', 4 m long, 3 m wide and 4.9 m high, with its base corner at (27.21, 83.91, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
matches = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Exterior - Metal Panel on Mtl. Stud:219988']
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2vC5R7dGrFZuLX90Lfvwcd IfcWall Basic Wall:Exterior - Metal Panel on Mtl. Stud:219988
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid('2vC5R7dGrFZuLX90Lfvwcd')
floor = None
for relation in getattr(target, 'ContainedInStructure', None) or ():
    floor = relation.RelatingStructure
    break
if floor is None:
    for relation in getattr(target, 'Decomposes', None) or ():
        floor = relation.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2vC5R7dGrFZuLX90Lfvwcd IfcWall Basic Wall:Exterior - Metal Panel on Mtl. Stud:219988 is contained in 2hExBg8jj4NRG6zzD0Rw2Q IfcBuildingStorey Level 3 elevation 11000.0
model length unit in metres: 0.001
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((27.21, 27.21), (83.91, 83.91), (4.0, 4.0), (3.0, 3.0), (4.9, 4.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
27.21 m = 27.21 m = 27210.0 file units
83.91 m = 83.91 m = 83910.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
4.9 m = 4.9 m = 4900.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
floor = ifc.by_guid('2hExBg8jj4NRG6zzD0Rw2Q')
new_element = geom.add_box_element(floor, 'IfcSpace', 'Room 998', 27.21, 83.91, 0.0,
                                   4.0, 3.0, 4.9, frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

commit()
print('model committed')
```
Tool result:
```
0HJqgh0b9APOqxuGDirfSD IfcSpace Room 998
model committed
```
Assistant: Finished: the space has been created and placed on its storey. The file on disk now holds the change.

### Example 2
User:
Add a new space named 'Room 941' on the storey that contains the wall named 'Basic Wall:DPW 24.0:306766', 4 m long, 3 m wide and 2.3 m high, with its base corner at (5.57, 5.37, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:DPW 24.0:306766"]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3ElN6YhcH0YegYABPC2lj0 IfcWallStandardCase Basic Wall:DPW 24.0:306766
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid("3ElN6YhcH0YegYABPC2lj0")
storey = None
for link in getattr(element, 'ContainedInStructure', None) or ():
    storey = link.RelatingStructure
    break
if storey is None:
    for link in getattr(element, 'Decomposes', None) or ():
        storey = link.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3ElN6YhcH0YegYABPC2lj0 IfcWallStandardCase Basic Wall:DPW 24.0:306766 is contained in 2KxRpJWyL6EeW8ZJpX29se IfcBuildingStorey Ebene 6 elevation 13.2
model length unit in metres: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("2KxRpJWyL6EeW8ZJpX29se")
new_element = geom.add_box_element(storey, "IfcSpace", "Room 941", 5.57, 5.37, 0.0, 4.0,
                                   3.0, 2.3, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
1JdXqR5dz0cwg1M5kc1IVF IfcSpace Room 941
model committed
```
Assistant: The new space is in the model, and the edit is written to the working file.

### Example 3
User:
Add a new space named 'Room 559' on the storey that contains the wall named 'SW - 024', 4 m long, 3 m wide and 4.3 m high, with its base corner at (9.78, -2.41, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'SW - 024']
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2__IHwziTDtwcE_G1KyE_2 IfcWall SW - 024
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid('2__IHwziTDtwcE_G1KyE_2')
level = None
for rel in getattr(product, 'ContainedInStructure', None) or ():
    level = rel.RelatingStructure
    break
if level is None:
    for rel in getattr(product, 'Decomposes', None) or ():
        level = rel.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2__IHwziTDtwcE_G1KyE_2 IfcWall SW - 024 is contained in 2F0V3QPDDFMRTpJqxqPeZR IfcBuildingStorey First Floor elevation 4400.0
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((9.78, 9.78), (4.0, 4.0), (3.0, 3.0), (4.3, 4.3),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
9.78 m = 9.78 m = 9780.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
4.3 m = 4.3 m = 4300.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
level = ifc.by_guid('2F0V3QPDDFMRTpJqxqPeZR')
added = geom.add_box_element(level, 'IfcSpace', 'Room 559', 9.78, -2.41, 0.0, 4.0, 3.0,
                             4.3, frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
11oxJv2b98BeDPvcrLkMBH IfcSpace Room 559
model committed
```
Assistant: Completed. The space has been created and placed on its storey; the model was committed.
