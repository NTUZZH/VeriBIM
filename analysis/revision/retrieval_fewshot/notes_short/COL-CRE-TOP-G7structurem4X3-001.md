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
Add a new column named 'Post 696' on the storey that contains the wall named 'Basic Wall:Foundation - 375mm Concrete w_step:208780', 0.4 m by 0.4 m in section and 4.9 m high, with its base corner at (9.72, 64.57, 0.00) m in that storey's own coordinates. Give it the predefined type PILASTER. Establish a connection to the wall named 'Basic Wall:Foundation - 375mm Concrete w_step:209229'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:Foundation - 375mm Concrete w_step:208780"]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
3iM76qwej9Tf9ttHcbQqRA IfcWallStandardCase Basic Wall:Foundation - 375mm Concrete w_step:208780
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
target = ifc.by_guid("3iM76qwej9Tf9ttHcbQqRA")
storey = None
for relation in getattr(target, 'ContainedInStructure', None) or ():
    storey = relation.RelatingStructure
    break
if storey is None:
    for relation in getattr(target, 'Decomposes', None) or ():
        storey = relation.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3iM76qwej9Tf9ttHcbQqRA IfcWallStandardCase Basic Wall:Foundation - 375mm Concrete w_step:208780 is contained in 1fOVjSd7T40PyRtVEklS6X IfcBuildingStorey Level 1 elevation 6.59062507910815e-10
model length unit in metres: 0.001
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the elements the instruction names
wanted = {"Post 696", "Basic Wall:Foundation - 375mm Concrete w_step:208780", "Basic Wall:Foundation - 375mm Concrete w_step:209229"}
for target in ifc.by_type('IfcProduct'):
    label = (target.Name or '', getattr(target, 'LongName', None) or '')
    if wanted.intersection(label):
        print(target.GlobalId, target.is_a(), target.Name)
```
Tool result:
```
3iM76qwej9Tf9ttHcbQqRA IfcWallStandardCase Basic Wall:Foundation - 375mm Concrete w_step:208780
3iM76qwej9Tf9ttHcbQrWB IfcWallStandardCase Basic Wall:Foundation - 375mm Concrete w_step:209229
0PIrRTFbzB18iI$upV_AUE IfcOpeningElement Basic Wall:Foundation - 375mm Concrete w_step:208780
0PIrRTFbzB18iI$upV_AUB IfcOpeningElement Basic Wall:Foundation - 375mm Concrete w_step:209229
3VIrWTmJT9Ehf_68LVs_dR IfcOpeningElement Basic Wall:Foundation - 375mm Concrete w_step:209229
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((9.72, 9.72), (64.57, 64.57), (0.4, 0.4), (4.9, 4.9),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
9.72 m = 9.72 m = 9720.0 file units
64.57 m = 64.57 m = 64570.0 file units
0.4 m = 0.4 m = 400.0 file units
4.9 m = 4.9 m = 4900.0 file units
```
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("1fOVjSd7T40PyRtVEklS6X")
new_element = geom.add_box_element(storey, "IfcColumn", "Post 696", 9.72, 64.57, 0.0,
                                   0.4, 0.4, 4.9, predefined_type="PILASTER",
                                   frame="storey")
geom.connect_elements(new_element, ifc.by_guid("3iM76qwej9Tf9ttHcbQrWB"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
3v4ikt26rB0Pk_m3Q580LE IfcColumn Post 696
model committed
```
Assistant: The column has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
The client wants one change made to this model. Add a new column named 'Post 912' on the storey with ID '0IHaiP6S556PWPZjOmSHWo', 0.4 m by 0.4 m in section and 4.4 m high, with its base corner at (18.37, -7.62, 0.00) m in that storey's own coordinates. Give it the predefined type PILASTER.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
hits = [ifc.by_guid('0IHaiP6S556PWPZjOmSHWo')]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0IHaiP6S556PWPZjOmSHWo IfcBuildingStorey Level 2
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((18.37, 18.37), (0.4, 0.4), (4.4, 4.4),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
18.37 m = 18.37 m = 18370.0 file units
0.4 m = 0.4 m = 400.0 file units
4.4 m = 4.4 m = 4400.0 file units
```
Assistant tool call execute_ifc_code:
```python
level = ifc.by_guid('0IHaiP6S556PWPZjOmSHWo')
created = geom.add_box_element(level, 'IfcColumn', 'Post 912', 18.37, -7.62, 0.0, 0.4,
                               0.4, 4.4, predefined_type='PILASTER', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(created.GlobalId, created.is_a(), created.Name)

commit()
print('model committed')
```
Tool result:
```
2DbgeQ0zP538KlH29eDDqr IfcColumn Post 912
model committed
```
Assistant: The column has been created and placed on its storey. The edited model is committed.

### Example 3
User:
The client wants one change made to this model. Add a new column named 'Post 603' on the storey that contains the wall named 'Basic Wall:Foundation - 300mm Concrete - Retaining:255225', 0.4 m by 0.4 m in section and 4.9 m high, with its base corner at (22.31, 101.96, 0.00) m in that storey's own coordinates.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Foundation - 300mm Concrete - Retaining:255225']
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
25VG$Fj5jDzP7LbWNvGVtf IfcWallStandardCase Basic Wall:Foundation - 300mm Concrete - Retaining:255225
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
target = ifc.by_guid('25VG$Fj5jDzP7LbWNvGVtf')
floor = None
for link in getattr(target, 'ContainedInStructure', None) or ():
    floor = link.RelatingStructure
    break
if floor is None:
    for link in getattr(target, 'Decomposes', None) or ():
        floor = link.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
25VG$Fj5jDzP7LbWNvGVtf IfcWallStandardCase Basic Wall:Foundation - 300mm Concrete - Retaining:255225 is contained in 1fOVjSd7T40PyRtVEklS6X IfcBuildingStorey Level 1 elevation 6.59062507910815e-10
model length unit in metres: 0.001
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((22.31, 22.31), (101.96, 101.96), (0.4, 0.4), (4.9, 4.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
22.31 m = 22.31 m = 22310.0 file units
101.96 m = 101.96 m = 101960.0 file units
0.4 m = 0.4 m = 400.0 file units
4.9 m = 4.9 m = 4900.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
floor = ifc.by_guid('1fOVjSd7T40PyRtVEklS6X')
added = geom.add_box_element(floor, 'IfcColumn', 'Post 603', 22.31, 101.96, 0.0, 0.4,
                             0.4, 4.9, frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
3UG41ntHn5OAkAtJjeOpJ6 IfcColumn Post 603
model committed
```
Assistant: Done. The new column is in the model, and the model has been saved.
