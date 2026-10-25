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
Create a new space named 'Room 685' on storey 'T/FDN', 4 m long, 3 m wide and 2.3 m high. Set its base corner 6 m to the west (-X) and 3 m to the north (+Y) of the wall named 'Basic Wall:Foundation - Concrete (435mm):140913'. Give it the predefined type EXTERNAL.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Foundation - Concrete (435mm):140913']
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('2O2Fr$t4X7Zf8NOew3FK3E', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (435mm):140913')]
```
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
1xS3BCk291UvhgP2dvNMKI 'Level 1' 0.0
1xS3BCk291UvhgP2dvNMQJ 'Level 2' 3.100000000000378
1xS3BCk291UvhgP2dvNsgp 'T/FDN' -1.25
1xS3BCk291UvhgP2dvNtSE 'Roof' 6.00000000000039
model length unit in metres: 1
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
reference = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK3E')
floor = ifc.by_guid('1xS3BCk291UvhgP2dvNsgp')
base_corner = geom.origin_in_frame(reference, floor)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [8.383, -7.8, 0.0]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
floor = ifc.by_guid('1xS3BCk291UvhgP2dvNsgp')
# work the position out from the element the instruction refers to
reference = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK3E')
base_corner = geom.origin_in_frame(reference, floor)
new_element = geom.add_box_element(floor, 'IfcSpace', 'Room 685', base_corner[0] - 6.0,
                                   base_corner[1] + 3.0, 0.0, 4.0, 3.0, 2.3,
                                   predefined_type='EXTERNAL', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
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
23127AYzz2lfw7GRNn$exq IfcSpace Room 685
model committed
```
Assistant: Completed. The space has been created and placed on its storey; the model was committed.

### Example 2
User:
Add a new space named 'Room 154' on storey 'Ground Floor', 4 m long, 3 m wide and 3.5 m high. Set its base corner 8 m to the west (-X) and 8 m to the north (+Y) of the wall with GlobalId '05s0mjUTXDIPuE4dIjXFcA'. Give it the predefined type EXTERNAL.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid("05s0mjUTXDIPuE4dIjXFcA")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('05s0mjUTXDIPuE4dIjXFcA', 'IfcWall', 'Basic Wall:Wall type 3:355955')]
```
Assistant: I will list what depends on it first.
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
3hOm6uh1P0qRjR_qjn9ev2 '3rd Floor' 1080.0
0xyVneVyX9VAQy52Zl3yjQ 'Roof ceiling' 1440.0
3Zu5Bv0LOHrPC10026FoQQ 'Ground Floor' 0.0
15Z0v90RiHrPC20026FoKR '1st Floor' 359.999999999995
3hOm6uh1P0qRjR_qjn9evB '2nd Floor' 719.999999999995
13iyLURxL6vAaxLDJO64G3 'Footing level' -300.0
model length unit in metres: 0.01
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((4.0, 4.0), (3.0, 3.0), (3.5, 3.5), (8.0, 8.0),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
4.0 m = 4.0 m = 400.0 file units
3.0 m = 3.0 m = 300.0 file units
3.5 m = 3.5 m = 350.0 file units
8.0 m = 8.0 m = 800.0 file units
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# compute the corner the instruction describes
anchor_element = ifc.by_guid("05s0mjUTXDIPuE4dIjXFcA")
floor = ifc.by_guid("3Zu5Bv0LOHrPC10026FoQQ")
base_corner = geom.origin_in_frame(anchor_element, floor)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [-1.88, -24.639, 0.0]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
floor = ifc.by_guid("3Zu5Bv0LOHrPC10026FoQQ")
# compute the corner the instruction describes
anchor_element = ifc.by_guid("05s0mjUTXDIPuE4dIjXFcA")
base_corner = geom.origin_in_frame(anchor_element, floor)
added = geom.add_box_element(floor, "IfcSpace", "Room 154", base_corner[0] - 8.0,
                             base_corner[1] + 8.0, 0.0, 4.0, 3.0, 3.5,
                             predefined_type="EXTERNAL", frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
2oGCE1eJDAKx9R1nomjsw2 IfcSpace Room 154
model committed
```
Assistant: Finished: the space has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Create a new space named 'Room 173' on storey 'Level 2', 4 m long, 3 m wide and 3.1 m high. Set its base corner 8 m to the west (-X) and 8 m to the north (+Y) of the space named '022'. Give it the predefined type EXTERNAL.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcSpace")
       if (e.Name or '').strip() == "022"]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
01ZttA0LnYHOt2JmXKzHCD IfcSpace 022
```
Assistant: Next I need the elements that go with it.
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
3NANWHsl$nHRzid0ST8VnX 'Level 3' 9600.0
1z8TJmsjXxHx_FFfOhdrEh 'Level 2' 6400.0
2WSdUCQgLA19aleUi6sdSw 'Ground Floor' 0.0
39uTNFPctKJfAqNQwZbq2a 'Level 1' 3200.0
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((4.0, 4.0), (3.0, 3.0), (3.1, 3.1), (8.0, 8.0),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
3.1 m = 3.1 m = 3100.0 file units
8.0 m = 8.0 m = 8000.0 file units
```
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
anchor_element = ifc.by_guid("01ZttA0LnYHOt2JmXKzHCD")
storey = ifc.by_guid("1z8TJmsjXxHx_FFfOhdrEh")
corner = geom.origin_in_frame(anchor_element, storey)
print('reference origin in the storey frame (m):', [round(v, 3) for v in corner])
```
Tool result:
```
reference origin in the storey frame (m): [24.667, 7.723, 0.0]
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("1z8TJmsjXxHx_FFfOhdrEh")
# work the position out from the element the instruction refers to
anchor_element = ifc.by_guid("01ZttA0LnYHOt2JmXKzHCD")
corner = geom.origin_in_frame(anchor_element, storey)
added = geom.add_box_element(storey, "IfcSpace", "Room 173", corner[0] - 8.0,
                             corner[1] + 8.0, 0.0, 4.0, 3.0, 3.1,
                             predefined_type="EXTERNAL", frame="storey")
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
print("model committed")
```
Tool result:
```
3M5CFZGPTFe9HsgiGW_BLr IfcSpace Room 173
model committed
```
Assistant: Completed. The space has been created and placed on its storey; the model was committed.
