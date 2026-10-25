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
Add a new wall named 'Partition 722' on storey 'Level 2', 4 m long, 0.2 m thick and 4.5 m high, with its base corner at (-8.01, -3.90, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 125' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3Zu5Bv0LOHrPC10026FoQQ 'Level 0' 0.0
15Z0v90RiHrPC20026FoKR 'Level 1' 4.6
1PB$CljZz5YgtLh8Newt5s 'Level 2' 9.2
1PB$CljZz5YgtLh8Newt52 'Level 3' 13.8
1PB$CljZz5YgtLh8Newt4k 'Level 4' 18.4
1PB$CljZz5YgtLh8Newt7w 'Level 5' 23.0
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
storey = ifc.by_guid('1PB$CljZz5YgtLh8Newt5s')
created = geom.add_box_element(storey, 'IfcWall', 'Partition 722', -8.01, -3.9, 0.0,
                               4.0, 0.2, 4.5, frame='storey')
leaf = geom.add_filling(created, 'IfcDoor', 'Doorset 125', width=0.9, height=2.1,
                        along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(created.GlobalId, created.is_a(), created.Name)
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

commit()
print('model committed')
```
Tool result:
```
2uBUj_gefFQfEdMeI60Zox IfcWall Partition 722
2pRi$N7wXEw8CJcR_RZunU IfcDoor Doorset 125
model committed
```
Assistant: Completed. The new wall is in the model; the model was committed.

### Example 2
User:
Add a new wall named 'Partition 949' on storey 'Ground Floor', 4 m long, 0.2 m thick and 3.1 m high, with its base corner at (18.73, 13.36, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 839' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for level in ifc.by_type('IfcBuildingStorey'):
    print(level.GlobalId, repr(level.Name), level.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2WSdUCQgLA19aleUi6sdSw 'Ground Floor' 0.0
39uTNFPctKJfAqNQwZbq2a 'Level 1' 3200.0
1z8TJmsjXxHx_FFfOhdrEh 'Level 2' 6400.0
3NANWHsl$nHRzid0ST8VnX 'Level 3' 9600.0
1gC6$h2tT0BPb0XIhuxjks 'Roof' 12800.0
model length unit in metres: 0.001
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((18.73, 18.73), (13.36, 13.36), (4.0, 4.0), (0.2, 0.2), (3.1, 3.1), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
18.73 m = 18.73 m = 18730.0 file units
13.36 m = 13.36 m = 13360.0 file units
4.0 m = 4.0 m = 4000.0 file units
0.2 m = 0.2 m = 200.0 file units
3.1 m = 3.1 m = 3100.0 file units
0.9 m = 0.9 m = 900.0 file units
2.1 m = 2.1 m = 2100.0 file units
1.55 m = 1.55 m = 1550.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
level = ifc.by_guid('2WSdUCQgLA19aleUi6sdSw')
added = geom.add_box_element(level, 'IfcWall', 'Partition 949', 18.73, 13.36, 0.0, 4.0,
                             0.2, 3.1, frame='storey')
# geom cuts the opening, places the leaf and writes the relations
leaf = geom.add_filling(added, 'IfcDoor', 'Doorset 839', width=0.9, height=2.1,
                        along=1.55, sill=0.0)
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
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
1rGmlwME9EaA_eSyhnLNI6 IfcWall Partition 949
1lmGzUzwr3F9SmyXDayrcN IfcDoor Doorset 839
model committed
```
Assistant: The wall has been created and placed on its storey. The edited model is committed.

### Example 3
User:
Add a new wall named 'Partition 177' on storey 'Second Floor', 4 m long, 0.2 m thick and 3.5 m high, with its base corner at (26.21, -26.64, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 119' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for level in ifc.by_type('IfcBuildingStorey'):
    print(level.GlobalId, repr(level.Name), level.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1MvMAoc2L5LRJwssbEGR_8 'Basement (Parking)' 3.14065289920448e-13
1MvMAoc2L5LRJwssbEGllK '1st-TOS Parking' 9.62499999999807
1MvMAoc2L5LRJwssbEGlhR '1st-TOS Main' 10.8124999999989
1MvMAoc2L5LRJwssbEGS7s 'First Floor' 11.3333333333338
1MvMAoc2L5LRJwssbEGljI '2nd-TOS' 23.1458333333327
1MvMAoc2L5LRJwssbEGeEw 'Second Floor' 23.666666666666
1MvMAoc2L5LRJwssbEGlZa '3rd-TOS' 35.479166666666
1MvMAoc2L5LRJwssbEGeC7 'Roof TOS' 49.2083333333327
1MvMAoc2L5LRJwssbEGeCK 'TO Screen Wall' 58.3333333333327
model length unit in metres: 0.3048
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((26.21, 26.21), (4.0, 4.0), (0.2, 0.2), (3.5, 3.5), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
26.21 m = 26.21 m = 85.990814 file units
4.0 m = 4.0 m = 13.12336 file units
0.2 m = 0.2 m = 0.656168 file units
3.5 m = 3.5 m = 11.48294 file units
0.9 m = 0.9 m = 2.952756 file units
2.1 m = 2.1 m = 6.889764 file units
1.55 m = 1.55 m = 5.085302 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
level = ifc.by_guid('1MvMAoc2L5LRJwssbEGeEw')
added = geom.add_box_element(level, 'IfcWall', 'Partition 177', 26.21, -26.64, 0.0, 4.0,
                             0.2, 3.5, frame='storey')
# geom does the placement and the relationships
filling = geom.add_filling(added, 'IfcDoor', 'Doorset 119', width=0.9, height=2.1,
                           along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added.GlobalId, added.is_a(), added.Name)
print(filling.GlobalId, filling.is_a(), filling.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
080Oph0Rb4lAZA4Djeset1 IfcWall Partition 177
1AlHUtsIr2OeTrBGakZTBN IfcDoor Doorset 119
model committed
```
Assistant: The wall has been created and placed on its storey, and the edit is written to the working file.
