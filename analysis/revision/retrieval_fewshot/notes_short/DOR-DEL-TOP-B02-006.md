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
Delete every door hosted in the wall named 'Basic Wall:Exterior Wall 200mm:239739' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

# list every element the instruction's phrase covers
scope = by_name('IfcWall', 'Basic Wall:Exterior Wall 200mm:239739')
pool = geom.hosted_in(scope, 'IfcDoor')
print(len(pool), 'candidate(s) in scope')
hits = list(pool)
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Exterior Wall 200mm:239739' -> 366SxRcID4IenlY5Q5STkK IfcWall Basic Wall:Exterior Wall 200mm:239739
2 candidate(s) in scope
1$8VVd_jH30gruM7RmImcn IfcDoor Doors_IntDbl_6:1510x2110mm:344904
1$8VVd_jH30gruM7RmImbW IfcDoor Doors_IntDbl_6:1510x2110mm:344985
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid('1$8VVd_jH30gruM7RmImbW'))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid('1$8VVd_jH30gruM7RmImcn'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
# every element the phrase covers, and what is left of its class
members = ('1$8VVd_jH30gruM7RmImbW', '1$8VVd_jH30gruM7RmImcn',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcDoor', 'left in the model:', len(ifc.by_type('IfcDoor')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcDoor left in the model: 75
model committed
```
Assistant: The door and the relationships that depended on it are gone, and the edit is written to the working file.

### Example 2
User:
Delete every door hosted in the wall named 'Basic Wall:Load Bearing Exterior Wall - 300mm Concrete:307029' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

# list every element the instruction's phrase covers
scope = by_name('IfcWall', 'Basic Wall:Load Bearing Exterior Wall - 300mm Concrete:307029')
options = geom.hosted_in(scope, 'IfcDoor')
print(len(options), 'candidate(s) in scope')
matches = list(options)
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Load Bearing Exterior Wall - 300mm Concrete:307029' -> 0VUtd9nnr1rxy6mb1YczLG IfcWall Basic Wall:Load Bearing Exterior Wall - 300mm Concrete:307029
4 candidate(s) in scope
4 match(es)
2SHS3rMDX4vw9NKIqekECa IfcDoor M_Door-Exterior-Revolving-Full Glass-Metal:Main Entrance:393389
2SHS3rMDX4vw9NKIqekE43 IfcDoor M_Door-Exterior-Revolving-Full Glass-Metal:Main Entrance:393866
1OdTOQOP93zRdazWVvBIoI IfcDoor M_Door-Single-Flush_Panel_Double-Acting:Door 1:413292
1OdTOQOP93zRdazWVvBJ9f IfcDoor M_Door-Single-Flush_Panel_Double-Acting:Door 1:413847
```
Assistant: Let me read the target before changing it.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(product):
    placement = getattr(product, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * unit_scale

for target_guid in ('1OdTOQOP93zRdazWVvBIoI', '1OdTOQOP93zRdazWVvBJ9f', '2SHS3rMDX4vw9NKIqekE43', '2SHS3rMDX4vw9NKIqekECa'):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(product, 'HasOpenings', None) or ()), ' contained in:', len(getattr(product, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcDoor 1OdTOQOP93zRdazWVvBIoI M_Door-Single-Flush_Panel_Double-Acting:Door 1:413292
  origin (m): [-16.91, 2.857, 0.0]
  openings: 0  contained in: 1
IfcDoor 1OdTOQOP93zRdazWVvBJ9f M_Door-Single-Flush_Panel_Double-Acting:Door 1:413847
  origin (m): [-16.91, -17.443, 0.0]
  openings: 0  contained in: 1
IfcDoor 2SHS3rMDX4vw9NKIqekE43 M_Door-Exterior-Revolving-Full Glass-Metal:Main Entrance:393866
  origin (m): [-17.21, -6.658, 0.0]
  openings: 3  contained in: 1
IfcDoor 2SHS3rMDX4vw9NKIqekECa M_Door-Exterior-Revolving-Full Glass-Metal:Main Entrance:393389
  origin (m): [-16.91, -5.258, 0.0]
  openings: 3  contained in: 1
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid('1OdTOQOP93zRdazWVvBIoI'))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid('1OdTOQOP93zRdazWVvBJ9f'))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid('2SHS3rMDX4vw9NKIqekE43'))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid('2SHS3rMDX4vw9NKIqekECa'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
# every element the phrase covers, and what is left of its class
members = ('1OdTOQOP93zRdazWVvBIoI', '1OdTOQOP93zRdazWVvBJ9f', '2SHS3rMDX4vw9NKIqekE43', '2SHS3rMDX4vw9NKIqekECa',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcDoor', 'left in the model:', len(ifc.by_type('IfcDoor')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 4 element(s)
members still in the model: []
IfcDoor left in the model: 30
model committed
```
Assistant: Finished: the door has been removed. The file on disk now holds the change.

### Example 3
User:
Delete every door hosted in the wall named 'Basic Wall:Interior - 79mm Partition (1-hr):401647' from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

scope = by_name('IfcWall', 'Basic Wall:Interior - 79mm Partition (1-hr):401647')
options = geom.hosted_in(scope, 'IfcDoor')
print(len(options), 'candidate(s) in scope')
found = list(options)
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Interior - 79mm Partition (1-hr):401647' -> 29dpDEy_PErhmO89e604ve IfcWall Basic Wall:Interior - 79mm Partition (1-hr):401647
2 candidate(s) in scope
2 match(es)
29dpDEy_PErhmO89e604vr IfcDoor M_Single-Flush:0762 x 2032mm:401650
29dpDEy_PErhmO89e604vq IfcDoor M_Single-Flush:0762 x 2032mm:401651
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
geom.delete_filling(ifc.by_guid('29dpDEy_PErhmO89e604vq'))
geom.delete_filling(ifc.by_guid('29dpDEy_PErhmO89e604vr'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
members = ('29dpDEy_PErhmO89e604vq', '29dpDEy_PErhmO89e604vr',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcDoor', 'left in the model:', len(ifc.by_type('IfcDoor')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcDoor left in the model: 49
model committed
```
Assistant: Completed. The door has been removed; the model was committed.
