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
Add a new wall named 'Partition 199' on the storey identified as 31MO7odvv0cAeswhRbr4Rh, 4 m long, 0.2 m thick and 3.35 m high, with its base corner at (-10.85, -8.31, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 417' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid('31MO7odvv0cAeswhRbr4Rh')]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
31MO7odvv0cAeswhRbr4Rh IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.O)
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((4.0, 4.0), (0.2, 0.2), (3.35, 3.35), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
4.0 m = 4.0 m = 400.0 file units
0.2 m = 0.2 m = 20.0 file units
3.35 m = 3.35 m = 335.0 file units
0.9 m = 0.9 m = 90.0 file units
2.1 m = 2.1 m = 210.0 file units
1.55 m = 1.55 m = 155.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
storey = ifc.by_guid('31MO7odvv0cAeswhRbr4Rh')
created = geom.add_box_element(storey, 'IfcWall', 'Partition 199', -10.85, -8.31, 0.0,
                               4.0, 0.2, 3.35, frame='storey')
# geom cuts the opening, places the leaf and writes the relations
unit = geom.add_filling(created, 'IfcDoor', 'Doorset 417', width=0.9, height=2.1,
                        along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(created.GlobalId, created.is_a(), created.Name)
print(unit.GlobalId, unit.is_a(), unit.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
2x1dQqWUb9yOOXGPtgn0VJ IfcWall Partition 199
06bH7SDuTBBwXBnyArAZFI IfcDoor Doorset 417
model committed
```
Assistant: Completed. The new wall is in the model; the model was committed.

### Example 2
User:
Add a new wall named 'Partition 913' on the storey identified as 3hJpVTIdb2fhTTVvI3Hc20, 4 m long, 0.2 m thick and 4.9 m high, with its base corner at (-0.75, 1.51, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 146' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid("3hJpVTIdb2fhTTVvI3Hc20")]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3hJpVTIdb2fhTTVvI3Hc20 IfcBuildingStorey Level 3
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
level = ifc.by_guid("3hJpVTIdb2fhTTVvI3Hc20")
added = geom.add_box_element(level, "IfcWall", "Partition 913", -0.75, 1.51, 0.0, 4.0,
                             0.2, 4.9, frame="storey")
# geom does the placement and the relationships
leaf = geom.add_filling(added, "IfcDoor", "Doorset 146", width=0.9, height=2.1,
                        along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(added.GlobalId, added.is_a(), added.Name)
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
1byGzWFPD3$RtJ2XLF6bXz IfcWall Partition 913
3sQKXHI5XDog_XPGLr0C9b IfcDoor Doorset 146
model committed
```
Assistant: Completed. The new wall is in the model; the model was committed.

### Example 3
User:
Add a new wall named 'Partition 346' on the storey identified as 2zLsHd4mf4JBb2o9C59rjD, 4 m long, 0.2 m thick and 2.3 m high, with its base corner at (-2.34, 8.34, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 992' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid("2zLsHd4mf4JBb2o9C59rjD")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('2zLsHd4mf4JBb2o9C59rjD', 'IfcBuildingStorey', 'EVA 6.5mPD')]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((8.34, 8.34), (4.0, 4.0), (0.2, 0.2), (2.3, 2.3), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
8.34 m = 8.34 m = 8340.0 file units
4.0 m = 4.0 m = 4000.0 file units
0.2 m = 0.2 m = 200.0 file units
2.3 m = 2.3 m = 2300.0 file units
0.9 m = 0.9 m = 900.0 file units
2.1 m = 2.1 m = 2100.0 file units
1.55 m = 1.55 m = 1550.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("2zLsHd4mf4JBb2o9C59rjD")
new_element = geom.add_box_element(storey, "IfcWall", "Partition 346", -2.34, 8.34, 0.0,
                                   4.0, 0.2, 2.3, frame="storey")
# geom does the placement and the relationships
filling = geom.add_filling(new_element, "IfcDoor", "Doorset 992", width=0.9, height=2.1,
                           along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(new_element.GlobalId, new_element.is_a(), new_element.Name)
print(filling.GlobalId, filling.is_a(), filling.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
099c7hdsn7ugpUebesa1PH IfcWall Partition 346
2PzOsmxqX3Z8uuMw2On2a0 IfcDoor Doorset 992
model committed
```
Assistant: The new wall is in the model, and the edit is written to the working file.
