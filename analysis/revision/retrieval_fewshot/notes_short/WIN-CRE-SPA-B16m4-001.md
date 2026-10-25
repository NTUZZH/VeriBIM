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
Please replace the door hosted in the wall named 'Basic Wall:Interior - 123mm Partition:591263' with a window named 'Glazing unit 106', 1.2 m wide and 1.4 m high, at the same position along the wall and with its sill 0.9 m above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

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

# follow the host's openings to what fills them
host = by_name("IfcWall", "Basic Wall:Interior - 123mm Partition:591263")
found = []
for rel in getattr(host, 'HasOpenings', None) or ():
    opening = rel.RelatedOpeningElement
    for fills in (getattr(opening, 'HasFillings', None) or ()) if opening else ():
        leaf = fills.RelatedBuildingElement
        if leaf is not None and leaf.is_a("IfcDoor"):
            found.append(leaf)
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Interior - 123mm Partition:591263' -> 2QRZsMKYn35ff5LwqHZ_Py IfcWallStandardCase Basic Wall:Interior - 123mm Partition:591263
1 match(es)
2QRZsMKYn35ff5LwqHZ_P1 IfcDoor M_Single-Flush:0915 x 2032mm_Wood:591266
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
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale

for target_guid in ("2QRZsMKYn35ff5LwqHZ_P1",):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 2QRZsMKYn35ff5LwqHZ_P1 M_Single-Flush:0915 x 2032mm_Wood:591266
  origin (m): [30.609, 109.212, 176.811]
  contained in: ['Level 3']
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (0.9, 0.9),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.2 m = 1.2 m = 1200.0 file units
1.4 m = 1.4 m = 1400.0 file units
0.9 m = 0.9 m = 900.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
old = ifc.by_guid("2QRZsMKYn35ff5LwqHZ_P1")
print(old.GlobalId, old.is_a(), old.Name)
slot = geom.filling_slot(old)
host = slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
2QRZsMKYn35ff5LwqHZ_P1 IfcDoor M_Single-Flush:0915 x 2032mm_Wood:591266
hosted in 2QRZsMKYn35ff5LwqHZ_Py IfcWallStandardCase Basic Wall:Interior - 123mm Partition:591263
slot (m): {'along': 1.069, 'sill': 0.0, 'width': 0.915, 'height': 2.032}
wall (m): {'start': 0.0, 'end': 4.321, 'near': -0.061, 'far': 0.062, 'base': 0.0, 'top': 4.85, 'length': 4.321, 'thickness': 0.123, 'height': 4.85}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
old = ifc.by_guid("2QRZsMKYn35ff5LwqHZ_P1")
leaf = geom.replace_filling(old, "IfcWindow", "Glazing unit 106", width=1.2, height=1.4,
                            sill=0.9)
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
1gBzKFc3fDnOR4k0Ld8MRM IfcWindow Glazing unit 106
model committed
```
Assistant: Done. The window has been created and placed on its storey, and the model has been saved.

### Example 2
User:
Please replace the door hosted in the wall named 'Basic Wall:Wall type 7 interior:458573' with a window named 'Glazing unit 511', 1.2 m wide and 1.4 m high, at the same position along the wall and with its sill 0.9 m above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

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

# follow the host's openings to what fills them
host = by_name('IfcWall', 'Basic Wall:Wall type 7 interior:458573')
matches = []
for rel in getattr(host, 'HasOpenings', None) or ():
    void = rel.RelatedOpeningElement
    for fills in (getattr(void, 'HasFillings', None) or ()) if void else ():
        leaf = fills.RelatedBuildingElement
        if leaf is not None and leaf.is_a('IfcDoor'):
            matches.append(leaf)
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Wall type 7 interior:458573' -> 2UWRnKBD55YxvbwsqV136q IfcWall Basic Wall:Wall type 7 interior:458573
1 match(es)
2UWRnKBD55YxvbwsqV136t IfcDoor M_Single-Flush:Door Type 2:458574
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (0.9, 0.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
1.2 m = 1.2 m = 120.0 file units
1.4 m = 1.4 m = 140.0 file units
0.9 m = 0.9 m = 90.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
old = ifc.by_guid('2UWRnKBD55YxvbwsqV136t')
print(old.GlobalId, old.is_a(), old.Name)
opening_slot = geom.filling_slot(old)
host = opening_slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(opening_slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
2UWRnKBD55YxvbwsqV136t IfcDoor M_Single-Flush:Door Type 2:458574
hosted in 2UWRnKBD55YxvbwsqV136q IfcWall Basic Wall:Wall type 7 interior:458573
slot (m): {'along': 2.795, 'sill': 0.0, 'width': 0.915, 'height': 2.134}
wall (m): {'start': 0.0, 'end': 4.53, 'near': -0.107, 'far': 0.107, 'base': -0.0, 'top': 3.6, 'length': 4.53, 'thickness': 0.214, 'height': 3.6}
```
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
old = ifc.by_guid('2UWRnKBD55YxvbwsqV136t')
leaf = geom.replace_filling(old, 'IfcWindow', 'Glazing unit 511', width=1.2, height=1.4,
                            sill=0.9)
```
Tool result:
```
(code executed, no output)
```
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
0S6kq8kr9FW9fN5q8ouWhy IfcWindow Glazing unit 511
model committed
```
Assistant: The window has been created and placed on its storey. The edited model is committed.

### Example 3
User:
Please replace the door hosted in the wall named 'Basic Wall:Wall 250:337621' with a window named 'Glazing unit 186', 1.8 m wide and 1.4 m high, at the same position along the wall and with its sill 0.9 m above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

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

# follow the host's openings to what fills them
host = by_name('IfcWall', 'Basic Wall:Wall 250:337621')
matches = []
for relation in getattr(host, 'HasOpenings', None) or ():
    void = relation.RelatedOpeningElement
    for fills in (getattr(void, 'HasFillings', None) or ()) if void else ():
        filling = fills.RelatedBuildingElement
        if filling is not None and filling.is_a('IfcDoor'):
            matches.append(filling)
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Wall 250:337621' -> 0gnFJmo8nC0gBeETNivN2q IfcWallStandardCase Basic Wall:Wall 250:337621
3_wtBbjtD0EP58FPlNlxEJ IfcDoor Doors_ExtDbl_Flush:1800x2100:337659
```
Assistant: Reading the current state of the target.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * to_model

for target_guid in ('3_wtBbjtD0EP58FPlNlxEJ',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 3_wtBbjtD0EP58FPlNlxEJ Doors_ExtDbl_Flush:1800x2100:337659
  origin (m): [-5.735, 13.009, 0.0]
  contained in: ['Ground Floor']
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((1.8, 1.8), (1.4, 1.4), (0.9, 0.9),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.8 m = 1.8 m = 1800.0 file units
1.4 m = 1.4 m = 1400.0 file units
0.9 m = 0.9 m = 900.0 file units
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# measure the wall before placing anything in it
old = ifc.by_guid('3_wtBbjtD0EP58FPlNlxEJ')
print(old.GlobalId, old.is_a(), old.Name)
opening_slot = geom.filling_slot(old)
host = opening_slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(opening_slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
3_wtBbjtD0EP58FPlNlxEJ IfcDoor Doors_ExtDbl_Flush:1800x2100:337659
hosted in 0gnFJmo8nC0gBeETNivN2q IfcWallStandardCase Basic Wall:Wall 250:337621
slot (m): {'along': 2.12, 'sill': 0.0, 'width': 1.8, 'height': 2.1}
wall (m): {'start': 0.0, 'end': 6.04, 'near': -0.125, 'far': 0.125, 'base': 0.0, 'top': 9.2, 'length': 6.04, 'thickness': 0.25, 'height': 9.2}
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
old = ifc.by_guid('3_wtBbjtD0EP58FPlNlxEJ')
filling = geom.replace_filling(old, 'IfcWindow', 'Glazing unit 186', width=1.8,
                               height=1.4, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(filling.GlobalId, filling.is_a(), filling.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
1lWEgPVGT0cvkVcgAutGEG IfcWindow Glazing unit 186
model committed
```
Assistant: Done. The new window is in the model, and the model has been saved.
