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
Please delete the space with GlobalId '0kP5pC5rDAj83jeQxKkELy' from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid('0kP5pC5rDAj83jeQxKkELy')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('0kP5pC5rDAj83jeQxKkELy', 'IfcSpace', '37')]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# delete the element, its openings and whatever those openings hold
geom.delete_element(ifc.by_guid('0kP5pC5rDAj83jeQxKkELy'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('0kP5pC5rDAj83jeQxKkELy',) if g in present])

# save the edit
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The space has been removed, and the edit is written to the working file.

### Example 2
User:
Please delete the space with GlobalId '0kP5pC5rDAj83jeQxKkELH' from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid("0kP5pC5rDAj83jeQxKkELH")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('0kP5pC5rDAj83jeQxKkELH', 'IfcSpace', '31')]
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid("0kP5pC5rDAj83jeQxKkELH"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("0kP5pC5rDAj83jeQxKkELH",) if g in present])

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: The space has been removed, and the edit is written to the working file.

### Example 3
User:
Delete the space with GlobalId '3WIha3hdX8G8EHDzIXbHPX' from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid("3WIha3hdX8G8EHDzIXbHPX")]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3WIha3hdX8G8EHDzIXbHPX IfcSpace A102
```
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid("3WIha3hdX8G8EHDzIXbHPX"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("3WIha3hdX8G8EHDzIXbHPX",) if g in present])

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: The space and the relationships that depended on it are gone, and the edit is written to the working file.
