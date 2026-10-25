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
The client wants one change made to this model. Add a new window named 'Glazing unit 324' in wall 0sSFynUySwIPv12WZal8L8, 1.2 metres wide and 1.4 metres high, 14.8 metres along the wall from its start point and with its sill 0.9 metres above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("0sSFynUySwIPv12WZal8L8")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
[('0sSFynUySwIPv12WZal8L8', 'IfcWallStandardCase', 'Wall - 036')]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (14.8, 14.8), (0.9, 0.9),):
    print(stated, "metres", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.2 metres = 1.2 m = 1200.0 file units
1.4 metres = 1.4 m = 1400.0 file units
14.8 metres = 14.8 m = 14800.0 file units
0.9 metres = 0.9 m = 900.0 file units
```
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
host = ifc.by_guid("0sSFynUySwIPv12WZal8L8")
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
0sSFynUySwIPv12WZal8L8 IfcWallStandardCase Wall - 036
wall (m): {'start': 0.0, 'end': 26.9, 'near': -0.2, 'far': 0.0, 'base': 0.0, 'top': 3.2, 'length': 26.9, 'thickness': 0.2, 'height': 3.2}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
host = ifc.by_guid("0sSFynUySwIPv12WZal8L8")
leaf = geom.add_filling(host, "IfcWindow", "Glazing unit 324", width=1.2, height=1.4,
                        along=14.8, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
2X_mnWeGv3nxbtjoESbdOj IfcWindow Glazing unit 324
model committed
```
Assistant: Completed. The new window is in the model; the model was committed.

### Example 2
User:
Add a new window named 'Glazing unit 714' in the wall with GlobalId '2QF3$F$XHF1A$PuubJ8ZAS', 1.2 metres wide and 1.4 metres high, 3.71 metres along the wall from its start point and with its sill 0.9 metres above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid("2QF3$F$XHF1A$PuubJ8ZAS")]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
2QF3$F$XHF1A$PuubJ8ZAS IfcWallStandardCase Basic Wall:Concrete - 300mm:1511652
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (3.71, 3.71), (0.9, 0.9),):
    print(stated, "metres", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.2 metres = 1.2 m = 1200.0 file units
1.4 metres = 1.4 m = 1400.0 file units
3.71 metres = 3.71 m = 3710.0 file units
0.9 metres = 0.9 m = 900.0 file units
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
host = ifc.by_guid("2QF3$F$XHF1A$PuubJ8ZAS")
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
2QF3$F$XHF1A$PuubJ8ZAS IfcWallStandardCase Basic Wall:Concrete - 300mm:1511652
wall (m): {'start': 0.0, 'end': 6.989, 'near': -0.15, 'far': 0.15, 'base': 0.0, 'top': 5.5, 'length': 6.989, 'thickness': 0.3, 'height': 5.5}
```
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
host = ifc.by_guid("2QF3$F$XHF1A$PuubJ8ZAS")
leaf = geom.add_filling(host, "IfcWindow", "Glazing unit 714", width=1.2, height=1.4,
                        along=3.71, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
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
0ld_1KeSn4qwGXPYvSlbt7 IfcWindow Glazing unit 714
model committed
```
Assistant: The window has been created and placed on its storey. The edited model is committed.

### Example 3
User:
Add a new window named 'Glazing unit 351' in the wall with GlobalId '31BrNcu85BxOlgMGprRfIT', 1.2 metres wide and 1.4 metres high, 1.69 metres along the wall from its start point and with its sill 0.9 metres above the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid("31BrNcu85BxOlgMGprRfIT")]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
31BrNcu85BxOlgMGprRfIT IfcWallStandardCase Muro básico:BLOQUE 100 mm:1950218
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# measure the wall before placing anything in it
host = ifc.by_guid("31BrNcu85BxOlgMGprRfIT")
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
31BrNcu85BxOlgMGprRfIT IfcWallStandardCase Muro básico:BLOQUE 100 mm:1950218
wall (m): {'start': 0.0, 'end': 3.9, 'near': -0.05, 'far': 0.05, 'base': 0.0, 'top': 3.0, 'length': 3.9, 'thickness': 0.1, 'height': 3.0}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
host = ifc.by_guid("31BrNcu85BxOlgMGprRfIT")
filling = geom.add_filling(host, "IfcWindow", "Glazing unit 351", width=1.2, height=1.4,
                           along=1.69, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(filling.GlobalId, filling.is_a(), filling.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
2enzjTqpv5yAV5ufdtPWJm IfcWindow Glazing unit 351
model committed
```
Assistant: Completed. The new window is in the model; the model was committed.
