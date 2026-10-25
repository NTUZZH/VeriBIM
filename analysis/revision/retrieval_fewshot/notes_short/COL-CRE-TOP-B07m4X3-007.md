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
Add a new column named 'Post 906' on the storey that contains the wall named 'Basic Wall:Wall-Partn_12P-75Std-12P:476077', a length in the x-direction of 0.4 m, a width in the y-direction of 0.4 m and a height of 4.3 m, with its lowest corner at (4.69, -8.96, 0.00) m. Give it the predefined type PIERSTEM_SEGMENT.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:Wall-Partn_12P-75Std-12P:476077"]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
05S4_HpdP7Yf$Q7Cmq8YSq IfcWall Basic Wall:Wall-Partn_12P-75Std-12P:476077
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
target = ifc.by_guid("05S4_HpdP7Yf$Q7Cmq8YSq")
level = None
for rel in getattr(target, 'ContainedInStructure', None) or ():
    level = rel.RelatingStructure
    break
if level is None:
    for rel in getattr(target, 'Decomposes', None) or ():
        level = rel.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
05S4_HpdP7Yf$Q7Cmq8YSq IfcWall Basic Wall:Wall-Partn_12P-75Std-12P:476077 is contained in 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Level 0 elevation 0.0
model length unit in metres: 1
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid("3Zu5Bv0LOHrPC10026FoQQ")
created = geom.add_box_element(level, "IfcColumn", "Post 906", 4.69, -8.96, 0.0, 0.4,
                               0.4, 4.3, predefined_type="PIERSTEM_SEGMENT",
                               frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
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
3sONlrORb4lBL3Kq9U_diP IfcColumn Post 906
model committed
```
Assistant: Finished: the new column is in the model. The file on disk now holds the change.

### Example 2
User:
Create a new column named 'Post 637' on the storey that contains the slab with GUID 2vztDKR3XAE9w6mDSeVUre, a length in the x-direction of 0.4 m, a width in the y-direction of 0.4 m and a height of 4.2 m, with its lowest corner at (5.49, -6.89, 4.60) m. Give it the predefined type PIERSTEM_SEGMENT.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("2vztDKR3XAE9w6mDSeVUre")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('2vztDKR3XAE9w6mDSeVUre', 'IfcSlab', 'Floor:Generic - 12":386006')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid("2vztDKR3XAE9w6mDSeVUre")
storey = None
for relation in getattr(element, 'ContainedInStructure', None) or ():
    storey = relation.RelatingStructure
    break
if storey is None:
    for relation in getattr(element, 'Decomposes', None) or ():
        storey = relation.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2vztDKR3XAE9w6mDSeVUre IfcSlab Floor:Generic - 12":386006 is contained in 2MayaW1Gv4Gviu994fLNmx IfcBuildingStorey Level 2 elevation 4.6
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
storey = ifc.by_guid("2MayaW1Gv4Gviu994fLNmx")
new_element = geom.add_box_element(storey, "IfcColumn", "Post 637", 5.49, -6.89, 4.6,
                                   0.4, 0.4, 4.2, predefined_type="PIERSTEM_SEGMENT",
                                   frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
3fVTBKF_528uY5t70E9Er4 IfcColumn Post 637
model committed
```
Assistant: The column has been created and placed on its storey. The edited model is committed.

### Example 3
User:
Create a new column named 'Post 602' on the storey that contains the column named 'Columns_Rectangular:300x300mm:476586', a length in the x-direction of 0.4 m, a width in the y-direction of 0.4 m and a height of 4.3 m, with its lowest corner at (9.06, -8.40, 4.40) m. Give it the predefined type PIERSTEM.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
matches = [e for e in ifc.by_type("IfcColumn")
       if (e.Name or '').strip() == "Columns_Rectangular:300x300mm:476586"]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
05S4_HpdP7Yf$Q7Cmq8Y4p IfcColumn Columns_Rectangular:300x300mm:476586
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid("05S4_HpdP7Yf$Q7Cmq8Y4p")
level = None
for relation in getattr(target, 'ContainedInStructure', None) or ():
    level = relation.RelatingStructure
    break
if level is None:
    for relation in getattr(target, 'Decomposes', None) or ():
        level = relation.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(target.GlobalId, target.is_a(), target.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
05S4_HpdP7Yf$Q7Cmq8Y4p IfcColumn Columns_Rectangular:300x300mm:476586 is contained in 15Z0v90RiHrPC20026FoKR IfcBuildingStorey Level 1 elevation 4.4
model length unit in metres: 1
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
level = ifc.by_guid("15Z0v90RiHrPC20026FoKR")
created = geom.add_box_element(level, "IfcColumn", "Post 602", 9.06, -8.4, 4.4, 0.4,
                               0.4, 4.3, predefined_type="PIERSTEM", frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(created.GlobalId, created.is_a(), created.Name)

commit()
print("model committed")
```
Tool result:
```
1pEwX6wgTAUfBVo4grp$8K IfcColumn Post 602
model committed
```
Assistant: Done. The new column is in the model, and the model has been saved.
