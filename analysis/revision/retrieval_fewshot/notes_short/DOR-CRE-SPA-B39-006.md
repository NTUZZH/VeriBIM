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
Create a new door named 'Doorset 657' in the wall on storey 'Level 0' that stands about 2.2 m north (+Y) of the wall named 'Basic Wall:WALL:548401', 0.9 m wide and 2.1 m high, 0.9 m along the wall from its start point and standing on the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
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

storey = by_name('IfcBuildingStorey', 'Level 0')
reference = by_name('IfcWall', 'Basic Wall:WALL:548401')
hits = [geom.find_offset(reference, 'IfcWall', storey,
                         'north', 2.2)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 0' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Level 0
named 'Basic Wall:WALL:548401' -> 0PCu1ujKrAOfcdL5f2cSNA IfcWall Basic Wall:WALL:548401
1 match(es)
0PCu1ujKrAOfcdL5f2cSKD IfcWall Basic Wall:WALL:548598
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('0PCu1ujKrAOfcdL5f2cSKD')
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
0PCu1ujKrAOfcdL5f2cSKD IfcWall Basic Wall:WALL:548598
wall (m): {'start': 0.0, 'end': 2.006, 'near': -0.131, 'far': 0.131, 'base': 0.0, 'top': 18.4, 'length': 2.006, 'thickness': 0.262, 'height': 18.4}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('0PCu1ujKrAOfcdL5f2cSKD')
filling = geom.add_filling(host, 'IfcDoor', 'Doorset 657', width=0.9, height=2.1,
                           along=0.9, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(filling.GlobalId, filling.is_a(), filling.Name)

commit()
print('model committed')
```
Tool result:
```
2MTf2zZ2nBkBOjQ6aLd8Ui IfcDoor Doorset 657
model committed
```
Assistant: Done. The door has been created and placed on its storey, and the model has been saved.

### Example 2
User:
Create a new door named 'Doorset 956' in the wall on storey 'Level 0' that stands about 16.7 m north (+Y) of the wall named 'Basic Wall:WALL:333225', 0.9 m wide and 2.1 m high, 15.64 m along the wall from its start point and standing on the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
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

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', 'Level 0')
reference = by_name('IfcWall', 'Basic Wall:WALL:333225')
found = [geom.find_offset(reference, 'IfcWall', storey,
                          'north', 16.7)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Level 0' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Level 0
named 'Basic Wall:WALL:333225' -> 1Veobsv750OAC9cFcolE2Y IfcWallStandardCase Basic Wall:WALL:333225
[('3mC5rj4wL5ZfT78mw_njur', 'IfcWallStandardCase', 'Basic Wall:Exterior Load Bearing wall:316347')]
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

for target_guid in ('3mC5rj4wL5ZfT78mw_njur',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWallStandardCase 3mC5rj4wL5ZfT78mw_njur Basic Wall:Exterior Load Bearing wall:316347
  origin (m): [-12.693, 19.64, 0.0]
  contained in: ['Level 0']
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
host = ifc.by_guid('3mC5rj4wL5ZfT78mw_njur')
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
3mC5rj4wL5ZfT78mw_njur IfcWallStandardCase Basic Wall:Exterior Load Bearing wall:316347
wall (m): {'start': 0.0, 'end': 28.8, 'near': -0.156, 'far': 0.156, 'base': 0.0, 'top': 14.1, 'length': 28.8, 'thickness': 0.312, 'height': 14.1}
```
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
host = ifc.by_guid('3mC5rj4wL5ZfT78mw_njur')
leaf = geom.add_filling(host, 'IfcDoor', 'Doorset 956', width=0.9, height=2.1,
                        along=15.64, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
28Wo6dC$D7vOd2AuxpciD4 IfcDoor Doorset 956
model committed
```
Assistant: The new door is in the model. The edited model is committed.

### Example 3
User:
Create a new door named 'Doorset 783' in the wall on storey 'Level 2' that stands about 1.5 m north (+Y) of the wall named 'Basic Wall:RC 300mm:475133', 0.9 m wide and 2.1 m high, 1.25 m along the wall from its start point and standing on the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
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

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', 'Level 2')
reference = by_name('IfcWall', 'Basic Wall:RC 300mm:475133')
hits = [geom.find_offset(reference, 'IfcWall', storey,
                         'north', 1.5)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 2' -> 316DwlO2f6Muoj3Y_RU6Ed IfcBuildingStorey Level 2
named 'Basic Wall:RC 300mm:475133' -> 19YGw6jQX2lfyaqLrAUfYp IfcWall Basic Wall:RC 300mm:475133
19YGw6jQX2lfyaqLrAUfYr IfcWall Basic Wall:RC 300mm:475131
```
Assistant: Reading the current state of the target.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(product):
    placement = getattr(product, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * to_model

for target_guid in ('19YGw6jQX2lfyaqLrAUfYr',):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWall 19YGw6jQX2lfyaqLrAUfYr Basic Wall:RC 300mm:475131
  origin (m): [0.197, 3.201, 8.0]
  contained in: ['Level 2']
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1), (1.25, 1.25),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.9 m = 0.9 m = 900.0 file units
2.1 m = 2.1 m = 2100.0 file units
1.25 m = 1.25 m = 1250.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
host = ifc.by_guid('19YGw6jQX2lfyaqLrAUfYr')
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
19YGw6jQX2lfyaqLrAUfYr IfcWall Basic Wall:RC 300mm:475131
wall (m): {'start': 0.0, 'end': 4.5, 'near': -0.15, 'far': 0.15, 'base': 0.0, 'top': 3.78, 'length': 4.5, 'thickness': 0.3, 'height': 3.78}
```
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
host = ifc.by_guid('19YGw6jQX2lfyaqLrAUfYr')
leaf = geom.add_filling(host, 'IfcDoor', 'Doorset 783', width=0.9, height=2.1,
                        along=1.25, sill=0.0)
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

# save the edit
commit()
print('model committed')
```
Tool result:
```
2mqMY1PD1BG9d8_53o$tTD IfcDoor Doorset 783
model committed
```
Assistant: Finished: the door has been created and placed on its storey. The file on disk now holds the change.
