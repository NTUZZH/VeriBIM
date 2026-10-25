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
Make 3 copies of the wall with GlobalId '3_wSUpxabBcuFM0HSebKIP' at a spacing of 4.87 m to the south (-Y), named 'Partition 104', 'Partition 105' and 'Partition 106' in that order.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid('3_wSUpxabBcuFM0HSebKIP')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('3_wSUpxabBcuFM0HSebKIP', 'IfcWall', 'Basic Wall:Wall-Int_12P-100Blk-12P:326503')]
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
element = ifc.by_guid('3_wSUpxabBcuFM0HSebKIP')
added = geom.array_elements(element, 3, 0.0, -4.87, 0.0,
                            ['Partition 104', 'Partition 105', 'Partition 106'])
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added[0].GlobalId, added[0].is_a(), added[0].Name)
print(added[1].GlobalId, added[1].is_a(), added[1].Name)
print(added[2].GlobalId, added[2].is_a(), added[2].Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
1x4McMKsHBh9gwVhN0i0o5 IfcWall Partition 104
2kG96z5YjFYQ57WWnAaq_Z IfcWall Partition 105
09Lkwv78L5uuuGw$0dT2fs IfcWall Partition 106
model committed
```
Assistant: The new wall is in the model, and the edit is written to the working file.

### Example 2
User:
Make 4 copies of the slab with GlobalId '3E7dFA6WPAEf$oSkzcpO0v' at a spacing of 0.83 m to the south (-Y), named 'Deck 242', 'Deck 243', 'Deck 244' and 'Deck 245' in that order.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
hits = [ifc.by_guid("3E7dFA6WPAEf$oSkzcpO0v")]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3E7dFA6WPAEf$oSkzcpO0v IfcSlab GROUT
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.83, 0.83),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.83 m = 0.83 m = 830.0 file units
```
Assistant tool call execute_ifc_code:
```python
element = ifc.by_guid("3E7dFA6WPAEf$oSkzcpO0v")
created = geom.array_elements(element, 4, 0.0, -0.83, 0.0,
                              ["Deck 242", "Deck 243", "Deck 244", "Deck 245"])
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(created[0].GlobalId, created[0].is_a(), created[0].Name)
print(created[1].GlobalId, created[1].is_a(), created[1].Name)
print(created[2].GlobalId, created[2].is_a(), created[2].Name)
print(created[3].GlobalId, created[3].is_a(), created[3].Name)

commit()
print("model committed")
```
Tool result:
```
1MFXdyrUn0hxie462NkW99 IfcSlab Deck 242
2s5ndfeAj4IPuIXm69G9YS IfcSlab Deck 243
3_WVBKMbP16P4WtJsZL0x$ IfcSlab Deck 244
1UR5sASDzDNOlKdtJ7CD9f IfcSlab Deck 245
model committed
```
Assistant: Completed. The slab has been created and placed on its storey; the model was committed.

### Example 3
User:
Make 4 copies of the wall with GlobalId '1Veobsv750OAC9cFcolESP' at a spacing of 5.19 m to the north (+Y), named 'Partition 399', 'Partition 400', 'Partition 401' and 'Partition 402' in that order.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid('1Veobsv750OAC9cFcolESP')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('1Veobsv750OAC9cFcolESP', 'IfcWallStandardCase', 'Basic Wall:WALL:332306')]
```
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
element = ifc.by_guid('1Veobsv750OAC9cFcolESP')
created = geom.array_elements(element, 4, 0.0, 5.19, 0.0,
                              ['Partition 399', 'Partition 400', 'Partition 401', 'Partition 402'])
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(created[0].GlobalId, created[0].is_a(), created[0].Name)
print(created[1].GlobalId, created[1].is_a(), created[1].Name)
print(created[2].GlobalId, created[2].is_a(), created[2].Name)
print(created[3].GlobalId, created[3].is_a(), created[3].Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
1UZJHmn0P09hBrZ5Mddz7X IfcWallStandardCase Partition 399
17IYQiR$r9YQYvtQFIpmfE IfcWallStandardCase Partition 400
2f4ZznfxT1rv4zdPCBvdmw IfcWallStandardCase Partition 401
0ntqk8P9PDqPsRw_xaq2HT IfcWallStandardCase Partition 402
model committed
```
Assistant: Finished: the new wall is in the model. The file on disk now holds the change.
