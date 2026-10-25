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
Add a new space named 'Room 374' on the storey with the ID 298uW9PODAmgWwAQB0IyK1, 4000 mm long, 3000 mm wide and 3700 mm high, with its base corner at (20380, -720, 0) mm in that storey's own coordinates. Give it the predefined type INTERNAL.

IFC model path: <path to the working copy>
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((20380.0, 20.38), (4000.0, 4.0), (3000.0, 3.0), (3700.0, 3.7),):
    print(stated, "mm", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
20380.0 mm = 20.38 m = 20380.0 file units
4000.0 mm = 4.0 m = 4000.0 file units
3000.0 mm = 3.0 m = 3000.0 file units
3700.0 mm = 3.7 m = 3700.0 file units
```
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid("298uW9PODAmgWwAQB0IyK1")
added = geom.add_box_element(level, "IfcSpace", "Room 374", 20.38, -0.72, 0.0, 4.0, 3.0,
                             3.7, predefined_type="INTERNAL", frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
01MYu8oa5B0g0jrq6phkkr IfcSpace Room 374
model committed
```
Assistant: Finished: the space has been created and placed on its storey. The file on disk now holds the change.

### Example 2
User:
Add a new space named 'Room 100' on the storey that contains the slab named 'Floor:Generic 200mm:444032', 4000 mm long, 3000 mm wide and 3400 mm high, with its base corner at (-940, 6080, 0) mm in that storey's own coordinates. Give it the predefined type SPACE.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'Floor:Generic 200mm:444032']
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('3Kb8uaX718lesovqKDrDdn', 'IfcSlab', 'Floor:Generic 200mm:444032')]
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid('3Kb8uaX718lesovqKDrDdn')
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
3Kb8uaX718lesovqKDrDdn IfcSlab Floor:Generic 200mm:444032 is contained in 1DD4OqS2zCVAGEH7hc4z7J IfcBuildingStorey 2.Second Floor elevation 6999.99999999979
model length unit in metres: 0.001
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((6080.0, 6.08), (4000.0, 4.0), (3000.0, 3.0), (3400.0, 3.4),):
    print(stated, 'mm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
6080.0 mm = 6.08 m = 6080.0 file units
4000.0 mm = 4.0 m = 4000.0 file units
3000.0 mm = 3.0 m = 3000.0 file units
3400.0 mm = 3.4 m = 3400.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
floor = ifc.by_guid('1DD4OqS2zCVAGEH7hc4z7J')
added = geom.add_box_element(floor, 'IfcSpace', 'Room 100', -0.94, 6.08, 0.0, 4.0, 3.0,
                             3.4, predefined_type='SPACE', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
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
0bqfM_jWn1KAk8lN9Wm84I IfcSpace Room 100
model committed
```
Assistant: Done. The space has been created and placed on its storey, and the model has been saved.

### Example 3
User:
Add a new space named 'Room 399' on the storey that contains the slab whose GlobalId is 3rwYQn79534PMaBQij9dEV, 4000 mm long, 3000 mm wide and 3200 mm high, with its base corner at (2950, 12270, 0) mm in that storey's own coordinates. Give it the predefined type GFA.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid('3rwYQn79534PMaBQij9dEV')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('3rwYQn79534PMaBQij9dEV', 'IfcSlab', 'Foundation Slab:STB 50cm:434188')]
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid('3rwYQn79534PMaBQij9dEV')
storey = None
for relation in getattr(product, 'ContainedInStructure', None) or ():
    storey = relation.RelatingStructure
    break
if storey is None:
    for relation in getattr(product, 'Decomposes', None) or ():
        storey = relation.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3rwYQn79534PMaBQij9dEV IfcSlab Foundation Slab:STB 50cm:434188 is contained in 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Groundfloor elevation 0.0
model length unit in metres: 0.001
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((2950.0, 2.95), (12270.0, 12.27), (4000.0, 4.0), (3000.0, 3.0), (3200.0, 3.2),):
    print(stated, 'mm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
2950.0 mm = 2.95 m = 2950.0 file units
12270.0 mm = 12.27 m = 12270.0 file units
4000.0 mm = 4.0 m = 4000.0 file units
3000.0 mm = 3.0 m = 3000.0 file units
3200.0 mm = 3.2 m = 3200.0 file units
```
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
storey = ifc.by_guid('3Zu5Bv0LOHrPC10026FoQQ')
new_element = geom.add_box_element(storey, 'IfcSpace', 'Room 399', 2.95, 12.27, 0.0,
                                   4.0, 3.0, 3.2, predefined_type='GFA', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
1dbwGL15L5OhF8rlOLT2PT IfcSpace Room 399
model committed
```
Assistant: The space has been created and placed on its storey, and the edit is written to the working file.
