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
Please add a new slab named 'Deck 723' on storey 'Ground Floor', 0.2 m high, so that it sits directly on top of the wall with GUID 3qr9kVSuzFt9fVZcn5kw0q, over the same footprint. Give it the predefined type SIDEWALK.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("3qr9kVSuzFt9fVZcn5kw0q")]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3qr9kVSuzFt9fVZcn5kw0q IfcWall Basic Wall:Wall 250:317362
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
3Zu5Bv0LOHrPC10026FoQQ 'Ground Floor' 0.0
15Z0v90RiHrPC20026FoKR 'First Floor' 4600.0
3qr9kVSuzFt9fVZcn5kxbH 'Second FLoor' 9200.0
3qr9kVSuzFt9fVZcn5kwSP 'Third Floor' 13800.0
3qr9kVSuzFt9fVZcn5kwIW 'Level 4' 18400.0
3qr9kVSuzFt9fVZcn5kwh0 'Roof' 23000.0
model length unit in metres: 0.001
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.2, 0.2),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.2 m = 0.2 m = 200.0 file units
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
reference = ifc.by_guid("3qr9kVSuzFt9fVZcn5kw0q")
corner, footprint = geom.spot_on_top_of(reference)
print('corner on the top face (m):', [round(v, 3) for v in corner])
print('footprint (m):', [round(v, 3) for v in footprint])
```
Tool result:
```
corner on the top face (m): [-9.655, -9.531, 18.4]
footprint (m): [6.29, 0.25]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid("3Zu5Bv0LOHrPC10026FoQQ")
# work the position out from the element the instruction refers to
reference = ifc.by_guid("3qr9kVSuzFt9fVZcn5kw0q")
corner, footprint = geom.spot_on_top_of(reference)
new_element = geom.add_box_element(storey, "IfcSlab", "Deck 723", corner[0], corner[1],
                                   corner[2], footprint[0], footprint[1], 0.2,
                                   predefined_type="SIDEWALK", frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
0pMdMiBL5AL8_Qauv5JkQm IfcSlab Deck 723
model committed
```
Assistant: The slab has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Insert a new slab named 'Deck 618' on storey 'T/FDN', 0.2 meters high, so that it sits directly on top of the wall (ID: 2O2Fr$t4X7Zf8NOew3FK3E), over the same footprint. Give it the predefined type ROOF.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK3E')]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
2O2Fr$t4X7Zf8NOew3FK3E IfcWallStandardCase Basic Wall:Foundation - Concrete (435mm):140913
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
1xS3BCk291UvhgP2dvNMKI 'Level 1' 0.0
1xS3BCk291UvhgP2dvNMQJ 'Level 2' 3.100000000000378
1xS3BCk291UvhgP2dvNsgp 'T/FDN' -1.25
1xS3BCk291UvhgP2dvNtSE 'Roof' 6.00000000000039
model length unit in metres: 1
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# compute the corner the instruction describes
neighbour = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK3E')
corner, plan_size = geom.spot_on_top_of(neighbour)
print('corner on the top face (m):', [round(v, 3) for v in corner])
print('footprint (m):', [round(v, 3) for v in plan_size])
```
Tool result:
```
corner on the top face (m): [4.182, -8.018, 0.0]
footprint (m): [4.2, 0.435]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid('1xS3BCk291UvhgP2dvNsgp')
# compute the corner the instruction describes
neighbour = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK3E')
corner, plan_size = geom.spot_on_top_of(neighbour)
new_element = geom.add_box_element(level, 'IfcSlab', 'Deck 618', corner[0], corner[1],
                                   corner[2], plan_size[0], plan_size[1], 0.2,
                                   predefined_type='ROOF', frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
0omBpGgMvB$9XLR$axnwu9 IfcSlab Deck 618
model committed
```
Assistant: The slab has been created and placed on its storey, and the edit is written to the working file.

### Example 3
User:
Add a new slab named 'Deck 166' on storey 'Level 2', 0.2 m high, so that it sits directly on top of the IfcWall named 'Basic Wall:Generic - 200mm 2:327425', over the same footprint. Give it the predefined type SIDEWALK.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Generic - 200mm 2:327425']
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0jlV5f2T92gfxCIFypztby IfcWall Basic Wall:Generic - 200mm 2:327425
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
0jlV5f2T92gfxCIFypzevi 'Level 5' 15300.0
1HrVpXTSD7uBSH992ojAJ7 'Level 4' 15300.0
2pSOckt_5Ajwi4t6RCrRpL 'Level 6' 20400.0
3Aw$FV5MbAufEo59pkoNgA 'Level 1' 0.0
3kSL0VGKv3gxJCujeqtuJj 'Level 2' 5100.0
1HrVpXTSD7uBSH992ojAPl 'Level 3' 10200.0
2qYKvFEvH4cPghyPNWjrgR 'B.O. Footing' -4600.0
2qYKvFEvH4cPghyPNWjrgr 'T.O. Footing' -4300.0
2qYKvFEvH4cPghyPNWjrjP 'T.O. Slab' -4000.0
2qYKvFEvH4cPghyPNWjrjp 'T.O. Fnd. Wall' -300.0
model length unit in metres: 0.001
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((0.2, 0.2),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.2 m = 0.2 m = 200.0 file units
```
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
neighbour = ifc.by_guid('0jlV5f2T92gfxCIFypztby')
corner, plan_size = geom.spot_on_top_of(neighbour)
print('corner on the top face (m):', [round(v, 3) for v in corner])
print('footprint (m):', [round(v, 3) for v in plan_size])
```
Tool result:
```
corner on the top face (m): [-17.832, -3.176, 9.85]
footprint (m): [0.2, 4.8]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid('3kSL0VGKv3gxJCujeqtuJj')
# work the position out from the element the instruction refers to
neighbour = ifc.by_guid('0jlV5f2T92gfxCIFypztby')
corner, plan_size = geom.spot_on_top_of(neighbour)
new_element = geom.add_box_element(level, 'IfcSlab', 'Deck 166', corner[0], corner[1],
                                   corner[2], plan_size[0], plan_size[1], 0.2,
                                   predefined_type='SIDEWALK', frame='world')
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

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
2JkbPZC$P7_ukLnFgN92IB IfcSlab Deck 166
model committed
```
Assistant: Finished: the slab has been created and placed on its storey. The file on disk now holds the change.
