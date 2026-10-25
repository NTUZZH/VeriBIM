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
Set the overall height of the window with ID 2pSOckt_5Ajwi4t6RCrRlq from 1.5 m to 2.25 m, keeping its placement fixed.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid("2pSOckt_5Ajwi4t6RCrRlq")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('2pSOckt_5Ajwi4t6RCrRlq', 'IfcWindow', 'Windows_Concept_Plain_Dbl:910x910mm:504718')]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((2.25, 2.25),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
2.25 m = 2.25 m = 2250.0 file units
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

# convert metres to the model's own length unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

# update the attribute
ifc.by_guid("2pSOckt_5Ajwi4t6RCrRlq").OverallHeight = 2.25 / unit_scale
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid("2pSOckt_5Ajwi4t6RCrRlq")
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcWindow 2pSOckt_5Ajwi4t6RCrRlq Windows_Concept_Plain_Dbl:910x910mm:504718
model committed
```
Assistant: Finished: the window has been updated. The file on disk now holds the change.

### Example 2
User:
Change the overall height of the window with GlobalId '0_CJ6FjXD118MUZNG8Gt0o' from 1.22 m to 1.83 m, keeping its placement fixed.

IFC model path: <path to the working copy>
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

# lengths in the instruction are metres; the model may use other units
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)

# set the attribute on the target
ifc.by_guid("0_CJ6FjXD118MUZNG8Gt0o").OverallHeight = 1.83 / to_model
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
product = ifc.by_guid("0_CJ6FjXD118MUZNG8Gt0o")
print(product.is_a(), product.GlobalId, product.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcWindow 0_CJ6FjXD118MUZNG8Gt0o M_Instance-Window-Fixed:0610 x 1220mm:431436
model committed
```
Assistant: Finished: the window now carries the values the instruction asked for. The file on disk now holds the change.

### Example 3
User:
Change the overall height of the window with GlobalId '2a8ZenkKr2kwMa35sWQ5xD' from 1.21 m to 0.97 m, keeping its placement fixed.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
hits = [ifc.by_guid('2a8ZenkKr2kwMa35sWQ5xD')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('2a8ZenkKr2kwMa35sWQ5xD', 'IfcWindow', 'Windows_Sgl_Plain:1810x1210mm:350009')]
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((0.97, 0.97),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
0.97 m = 0.97 m = 97.0 file units
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

ifc.by_guid('2a8ZenkKr2kwMa35sWQ5xD').OverallHeight = 0.97 / scale
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid('2a8ZenkKr2kwMa35sWQ5xD')
print(target.is_a(), target.GlobalId, target.Name)

commit()
print('model committed')
```
Tool result:
```
IfcWindow 2a8ZenkKr2kwMa35sWQ5xD Windows_Sgl_Plain:1810x1210mm:350009
model committed
```
Assistant: Completed. The window has been updated; the model was committed.
