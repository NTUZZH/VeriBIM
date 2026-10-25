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
Create a new column named 'Post 286' on storey 'Level 3', 0.4 m by 0.4 m in section and 3.1 m high. Set its base corner 3 m to the west (-X) and 4 m to the north (+Y) of the space with GlobalId '0Xx9gDujQRJ9wzMj5p9LxT'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid('0Xx9gDujQRJ9wzMj5p9LxT')]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
0Xx9gDujQRJ9wzMj5p9LxT IfcSpace 004
```
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
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.4, 0.4), (3.1, 3.1), (3.0, 3.0), (4.0, 4.0),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.4 m = 0.4 m = 400.0 file units
3.1 m = 3.1 m = 3100.0 file units
3.0 m = 3.0 m = 3000.0 file units
4.0 m = 4.0 m = 4000.0 file units
```
Assistant tool call execute_ifc_code:
```python
# compute the corner the instruction describes
anchor_element = ifc.by_guid('0Xx9gDujQRJ9wzMj5p9LxT')
level = ifc.by_guid('3NANWHsl$nHRzid0ST8VnX')
base_corner = geom.origin_in_frame(anchor_element, level)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [27.467, 7.723, 0.0]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
level = ifc.by_guid('3NANWHsl$nHRzid0ST8VnX')
# compute the corner the instruction describes
anchor_element = ifc.by_guid('0Xx9gDujQRJ9wzMj5p9LxT')
base_corner = geom.origin_in_frame(anchor_element, level)
created = geom.add_box_element(level, 'IfcColumn', 'Post 286', base_corner[0] - 3.0,
                               base_corner[1] + 4.0, 0.0, 0.4, 0.4, 3.1, frame='storey')
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

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
211zbeJs12BBqPcHA8D7jL IfcColumn Post 286
model committed
```
Assistant: The column has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Create a new column named 'Post 772' on storey 'Level 3', 0.4 m by 0.4 m in section and 3.1 m high. Set its base corner 6 m to the west (-X) and 6 m to the north (+Y) of the space named '004'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcSpace")
       if (e.Name or '').strip() == "004"]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('0Xx9gDujQRJ9wzMj5p9LxT', 'IfcSpace', '004')]
```
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
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.4, 0.4), (3.1, 3.1), (6.0, 6.0),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.4 m = 0.4 m = 400.0 file units
3.1 m = 3.1 m = 3100.0 file units
6.0 m = 6.0 m = 6000.0 file units
```
Assistant tool call execute_ifc_code:
```python
# compute the corner the instruction describes
anchor_element = ifc.by_guid("0Xx9gDujQRJ9wzMj5p9LxT")
level = ifc.by_guid("3NANWHsl$nHRzid0ST8VnX")
base_corner = geom.origin_in_frame(anchor_element, level)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [27.467, 7.723, 0.0]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
level = ifc.by_guid("3NANWHsl$nHRzid0ST8VnX")
# compute the corner the instruction describes
anchor_element = ifc.by_guid("0Xx9gDujQRJ9wzMj5p9LxT")
base_corner = geom.origin_in_frame(anchor_element, level)
created = geom.add_box_element(level, "IfcColumn", "Post 772", base_corner[0] - 6.0,
                               base_corner[1] + 6.0, 0.0, 0.4, 0.4, 3.1, frame="storey")
```
Tool result:
```
(code executed, no output)
```
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
2MOpXzeLf1kx4gFXvySXfG IfcColumn Post 772
model committed
```
Assistant: Finished: the column has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Add a new column named 'Post 852' on storey 'Level 1', 0.4 m by 0.4 m in section and 2.3 m high. Set its base corner 3 m to the west (-X) and 4 m to the north (+Y) of the wall named 'Basic Wall:Generic - 225mm Masonry:207124'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
hits = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:Generic - 225mm Masonry:207124"]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3AR$8LNN18Rh_Zduon5YXw IfcWall Basic Wall:Generic - 225mm Masonry:207124
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2dTVw6MAP9_ujUIdKX4tJL 'Level 3' 5.99999999999992
2dTVw6MAP9_ujUIdKX4mRk 'Level 5' 6.69999999999992
2dTVw6MAP9_ujUIdKX4Ska 'Level 1' 0.0
2dTVw6MAP9_ujUIdKX4gvh 'Level 6' 1.54
2dTVw6MAP9_ujUIdKX4SWb 'Level 2' 3.0
2dTVw6MAP9_ujUIdKX4tJv 'Level 4' -0.45
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
anchor_element = ifc.by_guid("3AR$8LNN18Rh_Zduon5YXw")
storey = ifc.by_guid("2dTVw6MAP9_ujUIdKX4Ska")
base_corner = geom.origin_in_frame(anchor_element, storey)
print('reference origin in the storey frame (m):', [round(v, 3) for v in base_corner])
```
Tool result:
```
reference origin in the storey frame (m): [-4.893, -15.622, 2.1]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
storey = ifc.by_guid("2dTVw6MAP9_ujUIdKX4Ska")
anchor_element = ifc.by_guid("3AR$8LNN18Rh_Zduon5YXw")
base_corner = geom.origin_in_frame(anchor_element, storey)
added = geom.add_box_element(storey, "IfcColumn", "Post 852", base_corner[0] - 3.0,
                             base_corner[1] + 4.0, 0.0, 0.4, 0.4, 2.3, frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(added.GlobalId, added.is_a(), added.Name)

commit()
print("model committed")
```
Tool result:
```
27jF2149XF_xoI7NFIzwa7 IfcColumn Post 852
model committed
```
Assistant: The column has been created and placed on its storey. The edited model is committed.
