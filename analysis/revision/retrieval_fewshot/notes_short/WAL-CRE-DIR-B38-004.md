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
Duplicate IfcWall ID 3iM76qwej9Tf9ttHcbQrlG 3.61 m to the south (-Y), and name the copy 'Partition 254'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
found = [ifc.by_guid('3iM76qwej9Tf9ttHcbQrlG')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('3iM76qwej9Tf9ttHcbQrlG', 'IfcWall', 'Basic Wall:Foundation - 375mm Concrete w_step:209558')]
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((3.61, 3.61),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
3.61 m = 3.61 m = 3610.0 file units
```
Assistant tool call execute_ifc_code:
```python
added = geom.copy_element(ifc.by_guid('3iM76qwej9Tf9ttHcbQrlG'), 0.0, -3.61, 0.0,
                          'Partition 254')
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(added.GlobalId, added.is_a(), added.Name)

commit()
print('model committed')
```
Tool result:
```
06BiSMjfTEhgg5R5R_vMLi IfcWall Partition 254
model committed
```
Assistant: Completed. The new wall is in the model; the model was committed.

### Example 2
User:
Duplicate the column with GUID 0GPDis$EfEDBfMOcU9bEfC 1 metres to the north (+Y), and name the copy 'Post 385'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
matches = [ifc.by_guid('0GPDis$EfEDBfMOcU9bEfC')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('0GPDis$EfEDBfMOcU9bEfC', 'IfcColumn', 'Glulam-Western Species-Column:350 x 350:466429')]
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
```
Tool result:
```
one file length unit is 0.001 metres
```
Assistant tool call execute_ifc_code:
```python
new_element = geom.copy_element(ifc.by_guid('0GPDis$EfEDBfMOcU9bEfC'), 0.0, 1.0, 0.0,
                                'Post 385')
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

commit()
print('model committed')
```
Tool result:
```
3jn7DmfVP1IeWtYu6Fn23q IfcColumn Post 385
model committed
```
Assistant: Finished: the column has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Duplicate the slab identified as 2KM$EeaK1AvOQ4moVAFIaf 1.5 metres to the north (+Y), and name the copy 'Deck 337'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid("2KM$EeaK1AvOQ4moVAFIaf")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('2KM$EeaK1AvOQ4moVAFIaf', 'IfcSlab', None)]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((1.5, 1.5),):
    print(stated, "metres", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.5 metres = 1.5 m = 1500.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
created = geom.copy_element(ifc.by_guid("2KM$EeaK1AvOQ4moVAFIaf"), 0.0, 1.5, 0.0,
                            "Deck 337")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
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
3mzz4pi9T5tvYvgH67Ciqh IfcSlab Deck 337
model committed
```
Assistant: The new slab is in the model, and the edit is written to the working file.
