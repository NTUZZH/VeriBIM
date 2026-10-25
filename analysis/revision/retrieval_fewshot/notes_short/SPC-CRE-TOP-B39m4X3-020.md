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
Add a new space named 'Room 894' on the storey that contains the slab named 'Floor:Concrete-150 mm slab:248538', 4 m long, 3 m wide and 4.9 m high, with its lowest corner at (61.51, 67.26, 165.81) m in world coordinates, set out along that storey's own axes, which run 5 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'Floor:Concrete-150 mm slab:248538']
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0nLMa_hqjDM9PNHQIvZ_6t IfcSlab Floor:Concrete-150 mm slab:248538
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid('0nLMa_hqjDM9PNHQIvZ_6t')
storey = None
for rel in getattr(product, 'ContainedInStructure', None) or ():
    storey = rel.RelatingStructure
    break
if storey is None:
    for rel in getattr(product, 'Decomposes', None) or ():
        storey = rel.RelatingObject
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
0nLMa_hqjDM9PNHQIvZ_6t IfcSlab Floor:Concrete-150 mm slab:248538 is contained in 1fOVjSd7T40PyRtVEklS6X IfcBuildingStorey Level 1 elevation 6.59062507910815e-10
model length unit in metres: 0.001
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((61.51, 61.51), (67.26, 67.26), (165.81, 165.81), (4.0, 4.0), (3.0, 3.0), (4.9, 4.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
61.51 m = 61.51 m = 61510.0 file units
67.26 m = 67.26 m = 67260.0 file units
165.81 m = 165.81 m = 165810.0 file units
4.0 m = 4.0 m = 4000.0 file units
3.0 m = 3.0 m = 3000.0 file units
4.9 m = 4.9 m = 4900.0 file units
```
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
storey = ifc.by_guid('1fOVjSd7T40PyRtVEklS6X')
created = geom.add_box_element(storey, 'IfcSpace', 'Room 894', 61.51, 67.26, 165.81,
                               4.0, 3.0, 4.9, frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(created.GlobalId, created.is_a(), created.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
0EEX_aJdXAbwYe4aDc_p2I IfcSpace Room 894
model committed
```
Assistant: The new space is in the model, and the edit is written to the working file.

### Example 2
User:
Add a new space named 'Room 251' on the storey that contains the slab named 'Floor:Floor Finish - CA-1:1243000:5', 4 m long, 3 m wide and 3.66 m high, with its lowest corner at (219933.04, 907142.61, 62.89) m in world coordinates, set out along that storey's own axes, which run 68 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcSlab')
       if (e.Name or '').strip() == 'Floor:Floor Finish - CA-1:1243000:5']
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('1BONy$ExX5Bxr3qKd7YWxH', 'IfcSlab', 'Floor:Floor Finish - CA-1:1243000:5')]
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('1BONy$ExX5Bxr3qKd7YWxH')
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
1BONy$ExX5Bxr3qKd7YWxH IfcSlab Floor:Floor Finish - CA-1:1243000:5 is contained in 00Anm4s4r7luYkA9gSCCC_ IfcBuildingStorey FLOOR 2 elevation 206.333333333333
model length unit in metres: 0.3048
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((219933.04, 219933.04), (907142.61, 907142.61), (62.89, 62.89), (4.0, 4.0), (3.0, 3.0), (3.66, 3.66),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
219933.04 m = 219933.04 m = 721565.091864 file units
907142.61 m = 907142.61 m = 2976189.665354 file units
62.89 m = 62.89 m = 206.332021 file units
4.0 m = 4.0 m = 13.12336 file units
3.0 m = 3.0 m = 9.84252 file units
3.66 m = 3.66 m = 12.007874 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid('00Anm4s4r7luYkA9gSCCC_')
new_element = geom.add_box_element(level, 'IfcSpace', 'Room 251', 219933.04, 907142.61,
                                   62.89, 4.0, 3.0, 3.66, frame='world')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
2qV12K6qP6k9qIAFnTcX3g IfcSpace Room 251
model committed
```
Assistant: Completed. The new space is in the model; the model was committed.

### Example 3
User:
Insert a new space named 'Room 363' on the storey that contains the slab named 'Floor:Concrete Slab:778673', 4 m long, 3 m wide and 3.35 m high, with its lowest corner at (219900.12, 907128.21, 55.68) m in world coordinates, set out along that storey's own axes, which run 68 degrees counter-clockwise from the world axes.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type("IfcSlab")
       if (e.Name or '').strip() == "Floor:Concrete Slab:778673"]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
141UzFEpPAiBNNDMW3_djM IfcSlab Floor:Concrete Slab:778673
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
product = ifc.by_guid("141UzFEpPAiBNNDMW3_djM")
level = None
for relation in getattr(product, 'ContainedInStructure', None) or ():
    level = relation.RelatingStructure
    break
if level is None:
    for relation in getattr(product, 'Decomposes', None) or ():
        level = relation.RelatingObject
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
141UzFEpPAiBNNDMW3_djM IfcSlab Floor:Concrete Slab:778673 is contained in 00Anm4s4r7luYkA9gSC2lj IfcBuildingStorey BASEMENT LEVEL elevation 182.666666666667
model length unit in metres: 0.3048
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((219900.12, 219900.12), (907128.21, 907128.21), (55.68, 55.68), (4.0, 4.0), (3.0, 3.0), (3.35, 3.35),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
219900.12 m = 219900.12 m = 721457.086614 file units
907128.21 m = 907128.21 m = 2976142.42126 file units
55.68 m = 55.68 m = 182.677165 file units
4.0 m = 4.0 m = 13.12336 file units
3.0 m = 3.0 m = 9.84252 file units
3.35 m = 3.35 m = 10.990814 file units
```
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
level = ifc.by_guid("00Anm4s4r7luYkA9gSC2lj")
added = geom.add_box_element(level, "IfcSpace", "Room 363", 219900.12, 907128.21, 55.68,
                             4.0, 3.0, 3.35, frame="world")
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
1tP8pchRb9AAOS0uh0HiL2 IfcSpace Room 363
model committed
```
Assistant: Finished: the new space is in the model. The file on disk now holds the change.
