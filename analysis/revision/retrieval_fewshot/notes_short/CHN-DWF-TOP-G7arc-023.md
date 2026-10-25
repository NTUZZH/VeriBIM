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
Remove the door hosted in the wall the door 05S4_HpdP7Yf$Q7Cmq8YnW sits in, then remove the wall itself along with the opening it filled.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid('05S4_HpdP7Yf$Q7Cmq8YnW')
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
hits = [geom.find_host(named_element)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 05S4_HpdP7Yf$Q7Cmq8YnW IfcDoor Doors_IntSgl:810x2110mm:477433
05S4_HpdP7Yf$Q7Cmq8Ynl IfcWall Basic Wall:Wall-Partn_12P-70MStd-12P:477430
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid('05S4_HpdP7Yf$Q7Cmq8YnW'))
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('05S4_HpdP7Yf$Q7Cmq8Ynl'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('05S4_HpdP7Yf$Q7Cmq8YnW', '05S4_HpdP7Yf$Q7Cmq8Ynl') if g in present])

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The wall has been removed; the model was committed.

### Example 2
User:
Remove the door hosted in the wall the door with ID 2D6LgO1U67IhneCglmaXNT sits in, then remove the wall itself along with the opening it filled.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid('2D6LgO1U67IhneCglmaXNT')
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
found = [geom.find_host(named_element)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
given -> 2D6LgO1U67IhneCglmaXNT IfcDoor DOO - 010
[('3wOHUJIaIsGuyL_hJm6YJR', 'IfcWall', 'SW - 076')]
```
Assistant: I will check the element's class and position first.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * scale

for target_guid in ('3wOHUJIaIsGuyL_hJm6YJR',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(element, 'HasOpenings', None) or ()), ' contained in:', len(getattr(element, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWall 3wOHUJIaIsGuyL_hJm6YJR SW - 076
  origin (m): [32.761, 15.66, 3.0]
  openings: 1  contained in: 1
```
Assistant tool call execute_ifc_code:
```python
# delete the element, its openings and whatever those openings hold
geom.delete_filling(ifc.by_guid('2D6LgO1U67IhneCglmaXNT'))
# delete the element, its openings and whatever those openings hold
geom.delete_element(ifc.by_guid('3wOHUJIaIsGuyL_hJm6YJR'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('2D6LgO1U67IhneCglmaXNT', '3wOHUJIaIsGuyL_hJm6YJR') if g in present])

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the wall and the relationships that depended on it are gone. The file on disk now holds the change.

### Example 3
User:
Remove the door hosted in the wall door 06$N_wBX59h95Xezcuh7_W sits in, then remove the wall itself along with the opening it filled.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid('06$N_wBX59h95Xezcuh7_W')
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
matches = [geom.find_host(named_element)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 06$N_wBX59h95Xezcuh7_W IfcDoor M_Single-Flush:Door Type 1:423318
1 match(es)
3pNwAP6MrAKfYPHh5R4jtr IfcWall Basic Wall:Wall 150mm, Internal:404939
```
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * unit_scale

for target_guid in ('3pNwAP6MrAKfYPHh5R4jtr',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(element, 'HasOpenings', None) or ()), ' contained in:', len(getattr(element, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWall 3pNwAP6MrAKfYPHh5R4jtr Basic Wall:Wall 150mm, Internal:404939
  origin (m): [-12.32, 20.894, 0.0]
  openings: 1  contained in: 1
```
Assistant tool call execute_ifc_code:
```python
# delete the element, its openings and whatever those openings hold
geom.delete_filling(ifc.by_guid('06$N_wBX59h95Xezcuh7_W'))
# delete the element, its openings and whatever those openings hold
geom.delete_element(ifc.by_guid('3pNwAP6MrAKfYPHh5R4jtr'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('06$N_wBX59h95Xezcuh7_W', '3pNwAP6MrAKfYPHh5R4jtr') if g in present])

# save the edit
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall has been removed. The edited model is committed.
