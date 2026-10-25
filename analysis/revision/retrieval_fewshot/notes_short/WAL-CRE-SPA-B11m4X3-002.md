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
The client has asked for the following change. Create a new space named 'Room 946' on storey 'Kellergeschoss', 4 metres long, 3 metres wide and 2.9 metres high. Set its base corner 8 metres to the west (-X) and 6 metres to the south (-Y) of the space named '012'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type("IfcSpace")
       if (e.Name or '').strip() == "012"]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('13xmhGKBD05gOTLwJxmVjX', 'IfcSpace', '012')]
```
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1s4Y8_KBb5tOT8z_Ps3tKD 'Kellergeschoss' -3000.01
0$npCzOybE3gXMIu3KDFgx 'Erdgeschoss' -0.01
0$_Aucl6f8axwbJNsWhhSe '1. Obergeschoss' 2999.99
2xFmxk2cv1bhMi9F1Onf1o '2. Obergeschoss' 5999.99
1CMIWQ7Vv4ev2Wa6Rq4Gb8 'Dachgeschoss' 8999.99
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((4.0, 4.0), (3.0, 3.0), (2.9, 2.9), (8.0, 8.0), (6.0, 6.0),):
    print(stated, "metres", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
4.0 metres = 4.0 m = 4000.0 file units
3.0 metres = 3.0 m = 3000.0 file units
2.9 metres = 2.9 m = 2900.0 file units
8.0 metres = 8.0 m = 8000.0 file units
6.0 metres = 6.0 m = 6000.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
anchor_element = ifc.by_guid("13xmhGKBD05gOTLwJxmVjX")
storey = ifc.by_guid("1s4Y8_KBb5tOT8z_Ps3tKD")
base_corner = geom.origin_in_frame(anchor_element, storey)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [8.9, 9.3, 0.0]
```
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid("1s4Y8_KBb5tOT8z_Ps3tKD")
# work the position out from the element the instruction refers to
anchor_element = ifc.by_guid("13xmhGKBD05gOTLwJxmVjX")
base_corner = geom.origin_in_frame(anchor_element, storey)
created = geom.add_box_element(storey, "IfcSpace", "Room 946", base_corner[0] - 8.0,
                               base_corner[1] - 6.0, 0.0, 4.0, 3.0, 2.9, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(created.GlobalId, created.is_a(), created.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
1bcVVNQjT9wQSgv3c_P_e4 IfcSpace Room 946
model committed
```
Assistant: Finished: the new space is in the model. The file on disk now holds the change.

### Example 2
User:
Add a new wall named 'Partition 801' on storey 'Kellergeschoss', 4 metres long, 0.2 metres thick and 2.9 metres high. Set its base corner 8 metres to the west (-X) and 3 metres to the south (-Y) of the space named '011'. Give it the predefined type PARTITIONING.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcSpace')
       if (e.Name or '').strip() == '011']
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
1oEW11DE52rwm9OVsIc01L IfcSpace 011
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
0$npCzOybE3gXMIu3KDFgx 'Erdgeschoss' -0.01
1s4Y8_KBb5tOT8z_Ps3tKD 'Kellergeschoss' -3000.01
0$_Aucl6f8axwbJNsWhhSe '1. Obergeschoss' 2999.99
2xFmxk2cv1bhMi9F1Onf1o '2. Obergeschoss' 5999.99
1CMIWQ7Vv4ev2Wa6Rq4Gb8 'Dachgeschoss' 8999.99
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((4.0, 4.0), (0.2, 0.2), (2.9, 2.9), (8.0, 8.0), (3.0, 3.0),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
4.0 metres = 4.0 m = 4000.0 file units
0.2 metres = 0.2 m = 200.0 file units
2.9 metres = 2.9 m = 2900.0 file units
8.0 metres = 8.0 m = 8000.0 file units
3.0 metres = 3.0 m = 3000.0 file units
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# the position is measured off the reference, not assumed
neighbour = ifc.by_guid('1oEW11DE52rwm9OVsIc01L')
floor = ifc.by_guid('1s4Y8_KBb5tOT8z_Ps3tKD')
base_corner = geom.origin_in_frame(neighbour, floor)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [9.1, 9.3, 0.0]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
floor = ifc.by_guid('1s4Y8_KBb5tOT8z_Ps3tKD')
# the position is measured off the reference, not assumed
neighbour = ifc.by_guid('1oEW11DE52rwm9OVsIc01L')
base_corner = geom.origin_in_frame(neighbour, floor)
created = geom.add_box_element(floor, 'IfcWall', 'Partition 801', base_corner[0] - 8.0,
                               base_corner[1] - 3.0, 0.0, 4.0, 0.2, 2.9,
                               predefined_type='PARTITIONING', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(created.GlobalId, created.is_a(), created.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
1obesyXUT5ggQdT5a3i9lh IfcWall Partition 801
model committed
```
Assistant: Done. The wall has been created and placed on its storey, and the model has been saved.

### Example 3
User:
Add a new wall named 'Partition 753' on storey 'Level 3', 4 metres long, 0.2 metres thick and 4.9 metres high. Set its base corner 3 metres to the east (+X) and 3 metres to the north (+Y) of the space named '35'. Give it the predefined type MOVABLE.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
hits = [e for e in ifc.by_type('IfcSpace')
       if (e.Name or '').strip() == '35']
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3cyHnpwAvBz84R9Jtlw3oO IfcSpace 35
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3Zu5Bv0LOHrPC10026FoQQ 'Level 0' 0.0
15Z0v90RiHrPC20026FoKR 'Level 1' 5.0
1$XGFH8zTDYfUas2M0n9S8 'Level 2' 10.0
1$XGFH8zTDYfUas2M0n9SN 'Level 3' 15.0
1$XGFH8zTDYfUas2M0n9SI 'Level 4' 20.0
model length unit in metres: 1
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
neighbour = ifc.by_guid('3cyHnpwAvBz84R9Jtlw3oO')
floor = ifc.by_guid('1$XGFH8zTDYfUas2M0n9SN')
base_corner = geom.origin_in_frame(neighbour, floor)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [0.0, 0.0, 0.0]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
floor = ifc.by_guid('1$XGFH8zTDYfUas2M0n9SN')
neighbour = ifc.by_guid('3cyHnpwAvBz84R9Jtlw3oO')
base_corner = geom.origin_in_frame(neighbour, floor)
added = geom.add_box_element(floor, 'IfcWall', 'Partition 753', base_corner[0] + 3.0,
                             base_corner[1] + 3.0, 0.0, 4.0, 0.2, 4.9,
                             predefined_type='MOVABLE', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(added.GlobalId, added.is_a(), added.Name)

commit()
print('model committed')
```
Tool result:
```
34Fb6W_y52X9LTWrVRmxcz IfcWall Partition 753
model committed
```
Assistant: The wall has been created and placed on its storey. The edited model is committed.
