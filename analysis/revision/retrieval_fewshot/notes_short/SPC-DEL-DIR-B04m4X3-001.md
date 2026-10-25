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
Take out the spaces with the IDs 0XnbrDepDECwarBphgi2lP and 3Dk33csRTE8OD_Brse40lc from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# list every element the instruction's phrase covers
hits = [ifc.by_guid('0XnbrDepDECwarBphgi2lP'), ifc.by_guid('3Dk33csRTE8OD_Brse40lc')]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2 match(es)
0XnbrDepDECwarBphgi2lP IfcSpace L003
3Dk33csRTE8OD_Brse40lc IfcSpace R002
```
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('0XnbrDepDECwarBphgi2lP'))
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('3Dk33csRTE8OD_Brse40lc'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
# every element the phrase covers, and what is left of its class
members = ('0XnbrDepDECwarBphgi2lP', '3Dk33csRTE8OD_Brse40lc',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcSpace', 'left in the model:', len(ifc.by_type('IfcSpace')))

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcSpace left in the model: 70
model committed
```
Assistant: Done. The space and the relationships that depended on it are gone, and the model has been saved.

### Example 2
User:
Delete the spaces with the IDs 1EeakBa7XFj9nU5DMcSkDr, 17B1Zy2WX6gBuHOkaHN5cV, 0zxTyXbCvCYeCGPqxzi2aO and 3us9EorAn8fff9nvDQfezH from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
found = [ifc.by_guid('0zxTyXbCvCYeCGPqxzi2aO'), ifc.by_guid('17B1Zy2WX6gBuHOkaHN5cV'), ifc.by_guid('1EeakBa7XFj9nU5DMcSkDr'), ifc.by_guid('3us9EorAn8fff9nvDQfezH')]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0zxTyXbCvCYeCGPqxzi2aO IfcSpace 320
17B1Zy2WX6gBuHOkaHN5cV IfcSpace 301
1EeakBa7XFj9nU5DMcSkDr IfcSpace 309
3us9EorAn8fff9nvDQfezH IfcSpace 314
```
Assistant tool call execute_ifc_code:
```python
for target_guid in ('0zxTyXbCvCYeCGPqxzi2aO', '17B1Zy2WX6gBuHOkaHN5cV', '1EeakBa7XFj9nU5DMcSkDr', '3us9EorAn8fff9nvDQfezH'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
members = ('0zxTyXbCvCYeCGPqxzi2aO', '17B1Zy2WX6gBuHOkaHN5cV', '1EeakBa7XFj9nU5DMcSkDr', '3us9EorAn8fff9nvDQfezH',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcSpace', 'left in the model:', len(ifc.by_type('IfcSpace')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 4 element(s)
members still in the model: []
IfcSpace left in the model: 78
model committed
```
Assistant: Finished: the space and the relationships that depended on it are gone. The file on disk now holds the change.

### Example 3
User:
Please delete the spaces with the IDs 06FbghiVw0IuN0vdz92TEV and 2SiJvWcZz$I8rkpDAzs5Ho from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
hits = [ifc.by_guid('06FbghiVw0IuN0vdz92TEV'), ifc.by_guid('2SiJvWcZz$I8rkpDAzs5Ho')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('06FbghiVw0IuN0vdz92TEV', 'IfcSpace', '04'), ('2SiJvWcZz$I8rkpDAzs5Ho', 'IfcSpace', '03')]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
geom.delete_element(ifc.by_guid('06FbghiVw0IuN0vdz92TEV'))
geom.delete_element(ifc.by_guid('2SiJvWcZz$I8rkpDAzs5Ho'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
members = ('06FbghiVw0IuN0vdz92TEV', '2SiJvWcZz$I8rkpDAzs5Ho',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcSpace', 'left in the model:', len(ifc.by_type('IfcSpace')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcSpace left in the model: 38
model committed
```
Assistant: Finished: the space and the relationships that depended on it are gone. The file on disk now holds the change.
