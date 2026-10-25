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
Add a new space named 'Room 451' on the storey with the ID 0UKHUh06v69wKcoKjB04ik, 4 m long, 3 m wide and 2.9 m high, with its lowest corner at (22.60, 30.81, 0.00) m in world coordinates, set out along that storey's own axes, which run 120 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid('0UKHUh06v69wKcoKjB04ik')]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
0UKHUh06v69wKcoKjB04ik IfcBuildingStorey road carriageway - bridge road
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((22.6, 22.6), (30.81, 30.81), (4.0, 4.0), (3.0, 3.0), (2.9, 2.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
22.6 m = 22.6 m = 22600.0 file units
30.81 m = 30.81 m = 30810.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
2.9 m = 2.9 m = 2900.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid('0UKHUh06v69wKcoKjB04ik')
added = geom.add_box_element(level, 'IfcSpace', 'Room 451', 22.6, 30.81, 0.0, 4.0, 3.0,
                             2.9, frame='world')
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
0oHUw273vBdOVRqGy5C54G IfcSpace Room 451
model committed
```
Assistant: The space has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Add a new space named 'Room 720' on the storey with ID 0UKHUh06v69wKcoKjB04ik, 4 m long, 3 m wide and 2.9 m high, with its lowest corner at (20.56, 30.49, 0.00) m in world coordinates, set out along that storey's own axes, which run 120 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((20.56, 20.56), (30.49, 30.49), (4.0, 4.0), (3.0, 3.0), (2.9, 2.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
20.56 m = 20.56 m = 20560.0 file units
30.49 m = 30.49 m = 30490.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
2.9 m = 2.9 m = 2900.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
level = ifc.by_guid('0UKHUh06v69wKcoKjB04ik')
new_element = geom.add_box_element(level, 'IfcSpace', 'Room 720', 20.56, 30.49, 0.0,
                                   4.0, 3.0, 2.9, frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

commit()
print('model committed')
```
Tool result:
```
3c28I4$eX8A8Y32dEXRR_h IfcSpace Room 720
model committed
```
Assistant: Finished: the space has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Add a new space named 'Room 893' on the storey with ID 3JCNkEnxX2HAIohFE8d0li, 4 m long, 3 m wide and 2.9 m high, with its lowest corner at (13.03, 28.46, 0.00) m in world coordinates, set out along that storey's own axes, which run 60 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("3JCNkEnxX2HAIohFE8d0li")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('3JCNkEnxX2HAIohFE8d0li', 'IfcBuildingStorey', 'road carriageway - bridge road')]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((13.03, 13.03), (28.46, 28.46), (4.0, 4.0), (3.0, 3.0), (2.9, 2.9),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
13.03 m = 13.03 m = 13030.0 file units
28.46 m = 28.46 m = 28460.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
2.9 m = 2.9 m = 2900.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
floor = ifc.by_guid("3JCNkEnxX2HAIohFE8d0li")
new_element = geom.add_box_element(floor, "IfcSpace", "Room 893", 13.03, 28.46, 0.0,
                                   4.0, 3.0, 2.9, frame="world")
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
0_tdLc5Gn97hP5hEHQbr$z IfcSpace Room 893
model committed
```
Assistant: Finished: the space has been created and placed on its storey. The file on disk now holds the change.
