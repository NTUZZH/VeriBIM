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
The client has asked for the following change. Add a new wall named 'Partition 177' on the storey that the space named 'A104' belongs to, 4 m long, 0.2 m thick and 3 m high, with its base corner at (1.54, -13.43, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcSpace")
       if (e.Name or '').strip() == "A104"]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3Dv6MBGFzBvOlsdVJAgcOh IfcSpace A104
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid("3Dv6MBGFzBvOlsdVJAgcOh")
floor = None
for rel in getattr(product, 'ContainedInStructure', None) or ():
    floor = rel.RelatingStructure
    break
if floor is None:
    for rel in getattr(product, 'Decomposes', None) or ():
        floor = rel.RelatingObject
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
3Dv6MBGFzBvOlsdVJAgcOh IfcSpace A104 is contained in 0o8nNAbaT5OQLV8C9mNFXU IfcBuildingStorey Level 1 elevation 0.0
model length unit in metres: 1
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
floor = ifc.by_guid("0o8nNAbaT5OQLV8C9mNFXU")
created = geom.add_box_element(floor, "IfcWall", "Partition 177", 1.54, -13.43, 0.0,
                               4.0, 0.2, 3.0, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(created.GlobalId, created.is_a(), created.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
0YLX9gcMj2aBXAFzIX1Gw2 IfcWall Partition 177
model committed
```
Assistant: The new wall is in the model. The edited model is committed.

### Example 2
User:
The client has asked for the following change. Add a new space named 'Room 990' on the storey with GlobalId '3JCNkEnxX2HAIohFE8d0li', 4 m long, 3 m wide and 2.9 m high, with its base corner at (-1.90, -4.03, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((4.0, 4.0), (3.0, 3.0), (2.9, 2.9),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
2.9 m = 2.9 m = 2900.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("3JCNkEnxX2HAIohFE8d0li")
new_element = geom.add_box_element(storey, "IfcSpace", "Room 990", -1.9, -4.03, 0.0,
                                   4.0, 3.0, 2.9, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
1qA9o6TXT6_ufHfC4fLWXq IfcSpace Room 990
model committed
```
Assistant: The new space is in the model. The edited model is committed.

### Example 3
User:
The client has asked for the following change. Add a new space named 'Room 312' on the storey that contains the wall named 'SW - 076', 4 m long, 3 m wide and 2.9 m high, with its base corner at (35.55, -6.23, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "SW - 076"]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3wOHUJIaIsGuyL_hJm6YJR IfcWall SW - 076
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid("3wOHUJIaIsGuyL_hJm6YJR")
level = None
for rel in getattr(element, 'ContainedInStructure', None) or ():
    level = rel.RelatingStructure
    break
if level is None:
    for rel in getattr(element, 'Decomposes', None) or ():
        level = rel.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3wOHUJIaIsGuyL_hJm6YJR IfcWall SW - 076 is contained in 2F0V3QPDDFMRTpJqxqPeZR IfcBuildingStorey 1. Story elevation 3000.0
model length unit in metres: 0.001
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((35.55, 35.55), (4.0, 4.0), (3.0, 3.0), (2.9, 2.9),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
35.55 m = 35.55 m = 35550.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
2.9 m = 2.9 m = 2900.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid("2F0V3QPDDFMRTpJqxqPeZR")
added = geom.add_box_element(level, "IfcSpace", "Room 312", 35.55, -6.23, 0.0, 4.0, 3.0,
                             2.9, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added.GlobalId, added.is_a(), added.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
2cps4jrYT9TQkFAxhC8PUZ IfcSpace Room 312
model committed
```
Assistant: The space has been created and placed on its storey, and the edit is written to the working file.
