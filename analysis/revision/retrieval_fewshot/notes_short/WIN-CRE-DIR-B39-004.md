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
Create a new window named 'Glazing unit 961' in the wall with GlobalId 3UPoyR0HD5gQ1Y7251gt91, 1.2 meters wide and 1.4 meters high, 10.48 meters along the wall from its start point and with its sill 0.9 meters above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
found = [ifc.by_guid("3UPoyR0HD5gQ1Y7251gt91")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('3UPoyR0HD5gQ1Y7251gt91', 'IfcWallStandardCase', 'Basic Wall:Generic - 8":340661')]
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (10.48, 10.48), (0.9, 0.9),):
    print(stated, "meters", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
1.2 meters = 1.2 m = 3.937008 file units
1.4 meters = 1.4 m = 4.593176 file units
10.48 meters = 10.48 m = 34.383202 file units
0.9 meters = 0.9 m = 2.952756 file units
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3UPoyR0HD5gQ1Y7251gt91")
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
3UPoyR0HD5gQ1Y7251gt91 IfcWallStandardCase Basic Wall:Generic - 8":340661
wall (m): {'start': 0.0, 'end': 39.04, 'near': -0.102, 'far': 0.102, 'base': 0.0, 'top': 2.743, 'length': 39.04, 'thickness': 0.203, 'height': 2.743}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3UPoyR0HD5gQ1Y7251gt91")
leaf = geom.add_filling(host, "IfcWindow", "Glazing unit 961", width=1.2, height=1.4,
                        along=10.48, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

commit()
print("model committed")
```
Tool result:
```
1y0nujaQv7Yv736oC$MOD6 IfcWindow Glazing unit 961
model committed
```
Assistant: The window has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Create a new window named 'Glazing unit 416' in the wall with GlobalId 0dxE1Sy6nDqfpDb5vIMN_Z, 1.2 meters wide and 1.4 meters high, 1.75 meters along the wall from its start point and with its sill 0.9 meters above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("0dxE1Sy6nDqfpDb5vIMN_Z")]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0dxE1Sy6nDqfpDb5vIMN_Z IfcWallStandardCase Basic Wall:Interior - Furring (152 mm Stud):194166
```
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
host = ifc.by_guid("0dxE1Sy6nDqfpDb5vIMN_Z")
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
0dxE1Sy6nDqfpDb5vIMN_Z IfcWallStandardCase Basic Wall:Interior - Furring (152 mm Stud):194166
wall (m): {'start': 0.0, 'end': 4.16, 'near': -0.076, 'far': 0.076, 'base': 0.0, 'top': 2.595, 'length': 4.16, 'thickness': 0.152, 'height': 2.595}
```
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
host = ifc.by_guid("0dxE1Sy6nDqfpDb5vIMN_Z")
leaf = geom.add_filling(host, "IfcWindow", "Glazing unit 416", width=1.2, height=1.4,
                        along=1.75, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
0AOCumeC5CrBqY8RzCIlri IfcWindow Glazing unit 416
model committed
```
Assistant: Completed. The window has been created and placed on its storey; the model was committed.

### Example 3
User:
Add a new window named 'Glazing unit 244' in the wall with GlobalId '2_odAVP0X7VQL2u8kfZf4z', 1.2 meters wide and 1.4 meters high, 1.96 meters along the wall from its start point and with its sill 0.9 meters above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
hits = [ifc.by_guid("2_odAVP0X7VQL2u8kfZf4z")]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2_odAVP0X7VQL2u8kfZf4z IfcWallStandardCase Basic Wall:Interior - 4 1/4" Partition TYPE 10:1220262
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (1.96, 1.96), (0.9, 0.9),):
    print(stated, "meters", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
1.2 meters = 1.2 m = 3.937008 file units
1.4 meters = 1.4 m = 4.593176 file units
1.96 meters = 1.96 m = 6.430446 file units
0.9 meters = 0.9 m = 2.952756 file units
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("2_odAVP0X7VQL2u8kfZf4z")
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
2_odAVP0X7VQL2u8kfZf4z IfcWallStandardCase Basic Wall:Interior - 4 1/4" Partition TYPE 10:1220262
wall (m): {'start': 0.0, 'end': 5.334, 'near': -0.054, 'far': 0.054, 'base': 0.0, 'top': 3.6, 'length': 5.334, 'thickness': 0.108, 'height': 3.6}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("2_odAVP0X7VQL2u8kfZf4z")
unit = geom.add_filling(host, "IfcWindow", "Glazing unit 244", width=1.2, height=1.4,
                        along=1.96, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
print(unit.GlobalId, unit.is_a(), unit.Name)

commit()
print("model committed")
```
Tool result:
```
24b1WYfX97DQ0udFZOd4Hv IfcWindow Glazing unit 244
model committed
```
Assistant: Done. The window has been created and placed on its storey, and the model has been saved.
