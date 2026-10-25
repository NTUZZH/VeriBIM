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
Please add a new wall named 'Partition 296' on the storey that contains the slab named 'SLA - 022', 4 m long, 0.2 m thick and 4.7 m high, with its base corner at (8.48, 16.45, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 762' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'SLA - 022']
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('2Ir4CUi4cQJhSwpSdptfwf', 'IfcSlab', 'SLA - 022')]
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('2Ir4CUi4cQJhSwpSdptfwf')
level = None
for link in getattr(element, 'ContainedInStructure', None) or ():
    level = link.RelatingStructure
    break
if level is None:
    for link in getattr(element, 'Decomposes', None) or ():
        level = link.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2Ir4CUi4cQJhSwpSdptfwf IfcSlab SLA - 022 is contained in 2VK2i8hZi3HPahZLbt_$zv IfcBuildingStorey 2. Geschoss elevation 9600.0
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((8.48, 8.48), (16.45, 16.45), (4.0, 4.0), (0.2, 0.2), (4.7, 4.7), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
8.48 m = 8.48 m = 8480.0 file units
16.45 m = 16.45 m = 16450.0 file units
4.0 m = 4.0 m = 4000.0 file units
0.2 m = 0.2 m = 200.0 file units
4.7 m = 4.7 m = 4700.0 file units
0.9 m = 0.9 m = 900.0 file units
2.1 m = 2.1 m = 2100.0 file units
1.55 m = 1.55 m = 1550.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid('2VK2i8hZi3HPahZLbt_$zv')
new_element = geom.add_box_element(level, 'IfcWall', 'Partition 296', 8.48, 16.45, 0.0,
                                   4.0, 0.2, 4.7, frame='storey')
# geom does the placement and the relationships
filling = geom.add_filling(new_element, 'IfcDoor', 'Doorset 762', width=0.9, height=2.1,
                           along=1.55, sill=0.0)
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
print(filling.GlobalId, filling.is_a(), filling.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
3tmejxMeH3kwnmBl1qq0Aj IfcWall Partition 296
3eJg02mQT8AenvZm0OYlzy IfcDoor Doorset 762
model committed
```
Assistant: Finished: the wall has been created and placed on its storey. The file on disk now holds the change.

### Example 2
User:
Please add a new wall named 'Partition 925' on the storey that contains the slab named 'Floor:Insitu Concrete 200 mm:436409', 4 m long, 0.2 m thick and 2.3 m high, with its base corner at (-7.62, 2.71, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 662' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
matches = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'Floor:Insitu Concrete 200 mm:436409']
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('2nSCJOFuLFiROH4YSfeOrN', 'IfcSlab', 'Floor:Insitu Concrete 200 mm:436409')]
```
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('2nSCJOFuLFiROH4YSfeOrN')
level = None
for link in getattr(product, 'ContainedInStructure', None) or ():
    level = link.RelatingStructure
    break
if level is None:
    for link in getattr(product, 'Decomposes', None) or ():
        level = link.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2nSCJOFuLFiROH4YSfeOrN IfcSlab Floor:Insitu Concrete 200 mm:436409 is contained in 2SUHiIuPP9dQbBrsCEwE7F IfcBuildingStorey 1F - N elevation 5400.0
model length unit in metres: 0.001
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((2.71, 2.71), (4.0, 4.0), (0.2, 0.2), (2.3, 2.3), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
2.71 m = 2.71 m = 2710.0 file units
4.0 m = 4.0 m = 4000.0 file units
0.2 m = 0.2 m = 200.0 file units
2.3 m = 2.3 m = 2300.0 file units
0.9 m = 0.9 m = 900.0 file units
2.1 m = 2.1 m = 2100.0 file units
1.55 m = 1.55 m = 1550.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
level = ifc.by_guid('2SUHiIuPP9dQbBrsCEwE7F')
added = geom.add_box_element(level, 'IfcWall', 'Partition 925', -7.62, 2.71, 0.0, 4.0,
                             0.2, 2.3, frame='storey')
filling = geom.add_filling(added, 'IfcDoor', 'Doorset 662', width=0.9, height=2.1,
                           along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(added.GlobalId, added.is_a(), added.Name)
print(filling.GlobalId, filling.is_a(), filling.Name)

commit()
print('model committed')
```
Tool result:
```
1Y$fS1_f51LRTtFbldyVXh IfcWall Partition 925
34wofwUk5B8AVcA8VNyTsT IfcDoor Doorset 662
model committed
```
Assistant: The new wall is in the model. The edited model is committed.

### Example 3
User:
Please add a new wall named 'Partition 748' on the storey that contains the slab named 'Floor:Floor 6":353533', 4 m long, 0.2 m thick and 2.3 m high, with its base corner at (0.14, -18.67, 0.00) m in that storey's own coordinates. Then put a door named 'Doorset 892' in that new wall, 0.9 m wide and 2.1 m high, 1.55 m along the wall from its start point, and cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'Floor:Floor 6":353533']
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2x9OOIZiz9L8_fLNfvkta_ IfcSlab Floor:Floor 6":353533
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('2x9OOIZiz9L8_fLNfvkta_')
storey = None
for link in getattr(element, 'ContainedInStructure', None) or ():
    storey = link.RelatingStructure
    break
if storey is None:
    for link in getattr(element, 'Decomposes', None) or ():
        storey = link.RelatingObject
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
2x9OOIZiz9L8_fLNfvkta_ IfcSlab Floor:Floor 6":353533 is contained in 1B1Ic8w3jB6wMndnPPtqdD IfcBuildingStorey T.F elevation 34.4488188976371
model length unit in metres: 0.3048
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.14, 0.14), (4.0, 4.0), (0.2, 0.2), (2.3, 2.3), (0.9, 0.9), (2.1, 2.1), (1.55, 1.55),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
0.14 m = 0.14 m = 0.459318 file units
4.0 m = 4.0 m = 13.12336 file units
0.2 m = 0.2 m = 0.656168 file units
2.3 m = 2.3 m = 7.545932 file units
0.9 m = 0.9 m = 2.952756 file units
2.1 m = 2.1 m = 6.889764 file units
1.55 m = 1.55 m = 5.085302 file units
```
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid('1B1Ic8w3jB6wMndnPPtqdD')
new_element = geom.add_box_element(storey, 'IfcWall', 'Partition 748', 0.14, -18.67,
                                   0.0, 4.0, 0.2, 2.3, frame='storey')
# geom does the placement and the relationships
leaf = geom.add_filling(new_element, 'IfcDoor', 'Doorset 892', width=0.9, height=2.1,
                        along=1.55, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(new_element.GlobalId, new_element.is_a(), new_element.Name)
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
339JNdMR152weyJCUXMJKT IfcWall Partition 748
0oxlp46h91eAKgUciLVWO5 IfcDoor Doorset 892
model committed
```
Assistant: Done. The new wall is in the model, and the model has been saved.
