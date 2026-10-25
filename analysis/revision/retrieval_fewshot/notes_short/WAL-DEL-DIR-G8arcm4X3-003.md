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
Delete the walls with GlobalIds '1sutQ05rXFjQzS_OAtbXNc', '1sutQ05rXFjQzS_OAtbXNg' and '1sutQ05rXFjQzS_OAtbXNp' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
for target_guid in ('1sutQ05rXFjQzS_OAtbXNc', '1sutQ05rXFjQzS_OAtbXNg', '1sutQ05rXFjQzS_OAtbXNp'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
# every element the phrase covers, and what is left of its class
members = ('1sutQ05rXFjQzS_OAtbXNc', '1sutQ05rXFjQzS_OAtbXNg', '1sutQ05rXFjQzS_OAtbXNp',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 3 element(s)
members still in the model: []
IfcWall left in the model: 115
model committed
```
Assistant: Finished: the wall and the relationships that depended on it are gone. The file on disk now holds the change.

### Example 2
User:
Delete the walls with GlobalIds '2x9OOIZiz9L8_fLNfvkt3q' and '2x9OOIZiz9L8_fLNfvkt5Y' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
geom.delete_element(ifc.by_guid('2x9OOIZiz9L8_fLNfvkt3q'))
geom.delete_element(ifc.by_guid('2x9OOIZiz9L8_fLNfvkt5Y'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
members = ('2x9OOIZiz9L8_fLNfvkt3q', '2x9OOIZiz9L8_fLNfvkt5Y',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcWall left in the model: 191
model committed
```
Assistant: Done. The wall and the relationships that depended on it are gone, and the model has been saved.

### Example 3
User:
Delete the walls with GlobalIds '3r7EAQMbvCT82RJYJ$usTK' and '3r7EAQMbvCT82RJYJ$usTG' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('3r7EAQMbvCT82RJYJ$usTG'))
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('3r7EAQMbvCT82RJYJ$usTK'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
# every element the phrase covers, and what is left of its class
members = ('3r7EAQMbvCT82RJYJ$usTG', '3r7EAQMbvCT82RJYJ$usTK',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcWall left in the model: 141
model committed
```
Assistant: The wall and the relationships that depended on it are gone, and the edit is written to the working file.
