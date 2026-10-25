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
Add a new space named 'Room 857' on the storey that contains the wall named '基本墙:Interior - 138mm Partition (1-hr):157705', a length in the x-direction of 4 metres, a width in the y-direction of 3 metres and a height of 3.7 metres, with its lowest corner at (13.58, 28.99, 3.80) metres.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
found = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == '基本墙:Interior - 138mm Partition (1-hr):157705']
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
2UMN_OQKrAshZl3dHPuj4v IfcWallStandardCase 基本墙:Interior - 138mm Partition (1-hr):157705
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('2UMN_OQKrAshZl3dHPuj4v')
floor = None
for link in getattr(product, 'ContainedInStructure', None) or ():
    floor = link.RelatingStructure
    break
if floor is None:
    for link in getattr(product, 'Decomposes', None) or ():
        floor = link.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2UMN_OQKrAshZl3dHPuj4v IfcWallStandardCase 基本墙:Interior - 138mm Partition (1-hr):157705 is contained in 298uW9PODAmgWwAQB0IyK1 IfcBuildingStorey 02 - Floor elevation 3800.00000000151
model length unit in metres: 0.001
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((13.58, 13.58), (28.99, 28.99), (3.8, 3.8), (4.0, 4.0), (3.0, 3.0), (3.7, 3.7),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
13.58 metres = 13.58 m = 13580.0 file units
28.99 metres = 28.99 m = 28990.0 file units
3.8 metres = 3.8 m = 3800.0 file units
4.0 metres = 4.0 m = 4000.0 file units
3.0 metres = 3.0 m = 3000.0 file units
3.7 metres = 3.7 m = 3700.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
floor = ifc.by_guid('298uW9PODAmgWwAQB0IyK1')
created = geom.add_box_element(floor, 'IfcSpace', 'Room 857', 13.58, 28.99, 3.8, 4.0,
                               3.0, 3.7, frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(created.GlobalId, created.is_a(), created.Name)

commit()
print('model committed')
```
Tool result:
```
3pzPLsqHXFBvRF1APcc$Mc IfcSpace Room 857
model committed
```
Assistant: The space has been created and placed on its storey. The edited model is committed.

### Example 2
User:
Add a new column named 'Post 379' on the storey that contains the wall named 'Muro básico:BLOQUE 200 mm:1978485', a length in the x-direction of 0.4 metres, a width in the y-direction of 0.4 metres and a height of 2.3 metres, with its lowest corner at (-0.71, -2.34, -0.60) metres.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Muro básico:BLOQUE 200 mm:1978485"]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('2oj0C26un9shtSOTTYIDRz', 'IfcWallStandardCase', 'Muro básico:BLOQUE 200 mm:1978485')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid("2oj0C26un9shtSOTTYIDRz")
storey = None
for link in getattr(product, 'ContainedInStructure', None) or ():
    storey = link.RelatingStructure
    break
if storey is None:
    for link in getattr(product, 'Decomposes', None) or ():
        storey = link.RelatingObject
        break
while storey is not None and not storey.is_a('IfcBuildingStorey'):
    parents = getattr(storey, 'Decomposes', None) or ()
    storey = parents[0].RelatingObject if parents else None
if storey is None:
    raise ValueError('the element sits on no storey')
print(product.GlobalId, product.is_a(), product.Name, 'is contained in', storey.GlobalId, storey.is_a(), storey.Name, 'elevation', getattr(storey, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2oj0C26un9shtSOTTYIDRz IfcWallStandardCase Muro básico:BLOQUE 200 mm:1978485 is contained in 0OCkzK25HA0wxSqRSYGLkp IfcBuildingStorey CIMENTACION elevation -0.6
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid("0OCkzK25HA0wxSqRSYGLkp")
added = geom.add_box_element(storey, "IfcColumn", "Post 379", -0.71, -2.34, -0.6, 0.4,
                             0.4, 2.3, frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
1qeDkD$WH9WvnJwm9lXEp6 IfcColumn Post 379
model committed
```
Assistant: Finished: the new column is in the model. The file on disk now holds the change.

### Example 3
User:
Insert a new wall named 'Partition 363' on the storey that contains the column named 'M_Concreto-Retangular-Coluna:320 x 350mm:1109621', a length in the x-direction of 4 metres, a width in the y-direction of 0.2 metres and a height of 3.35 metres, with its lowest corner at (7.95, 32.93, -0.05) metres.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type("IfcColumn")
       if (e.Name or '').strip() == "M_Concreto-Retangular-Coluna:320 x 350mm:1109621"]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('17bNRqTtr0OArtuGEocUNY', 'IfcColumn', 'M_Concreto-Retangular-Coluna:320 x 350mm:1109621')]
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
target = ifc.by_guid("17bNRqTtr0OArtuGEocUNY")
storey = None
for link in getattr(target, 'ContainedInStructure', None) or ():
    storey = link.RelatingStructure
    break
if storey is None:
    for link in getattr(target, 'Decomposes', None) or ():
        storey = link.RelatingObject
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
17bNRqTtr0OArtuGEocUNY IfcColumn M_Concreto-Retangular-Coluna:320 x 350mm:1109621 is contained in 31MO7odvv0cAeswhRbr4Rh IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.O) elevation -5.00000000000005
model length unit in metres: 0.01
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((7.95, 7.95), (32.93, 32.93), (4.0, 4.0), (0.2, 0.2), (3.35, 3.35),):
    print(stated, "metres", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
7.95 metres = 7.95 m = 795.0 file units
32.93 metres = 32.93 m = 3293.0 file units
4.0 metres = 4.0 m = 400.0 file units
0.2 metres = 0.2 m = 20.0 file units
3.35 metres = 3.35 m = 335.0 file units
```
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid("31MO7odvv0cAeswhRbr4Rh")
added = geom.add_box_element(storey, "IfcWall", "Partition 363", 7.95, 32.93, -0.05,
                             4.0, 0.2, 3.35, frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
3AgOV9l3H9WhQB_wsx1sx_ IfcWall Partition 363
model committed
```
Assistant: Finished: the wall has been created and placed on its storey. The file on disk now holds the change.
