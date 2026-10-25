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
Add a new window named 'Glazing unit 796' in the wall that holds the window named 'Windows_Sgl_Plain:910x910mm:346757', 1.2 m wide and 1.4 m high, with the middle of the leaf 6.26 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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

named_element = by_name("IfcWindow", "Windows_Sgl_Plain:910x910mm:346757")
matches = [geom.find_host(named_element)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Windows_Sgl_Plain:910x910mm:346757' -> 0OihGrSa564upmL79ZIK$J IfcWindow Windows_Sgl_Plain:910x910mm:346757
0fnwgtAozDL9MXvLB_$o_5 IfcWall Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P 2:313982
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * unit_scale

for target_guid in ("0fnwgtAozDL9MXvLB_$o_5",):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(target, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWall 0fnwgtAozDL9MXvLB_$o_5 Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P 2:313982
  origin (m): [-32.204, 5.591, 0.0]
  contained in: ['Level 0']
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("0fnwgtAozDL9MXvLB_$o_5")
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
0fnwgtAozDL9MXvLB_$o_5 IfcWall Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P 2:313982
wall (m): {'start': 0.0, 'end': 18.29, 'near': -0.145, 'far': 0.145, 'base': 0.0, 'top': 4.5, 'length': 18.29, 'thickness': 0.29, 'height': 4.5}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("0fnwgtAozDL9MXvLB_$o_5")
host_box = geom.wall_box(host)
filling = geom.add_filling(host, "IfcWindow", "Glazing unit 796", width=1.2, height=1.4,
                           along=host_box["start"] + 6.26, along_is_centre=True,
                           sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(filling.GlobalId, filling.is_a(), filling.Name)

commit()
print("model committed")
```
Tool result:
```
12MvoUfkL9kRtX40UXtI9Y IfcWindow Glazing unit 796
model committed
```
Assistant: Completed. The window has been created and placed on its storey; the model was committed.

### Example 2
User:
Add a new window named 'Glazing unit 235' in the wall that holds the door named 'PORTA - VAI E VEM - 2 FOLHAS - COM VISOR:PO110 - 110x210:921359', 1.2 m wide and 1.4 m high, with the middle of the leaf 4.75 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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

# follow the named door or window to the wall it sits in
named_element = by_name("IfcDoor", "PORTA - VAI E VEM - 2 FOLHAS - COM VISOR:PO110 - 110x210:921359")
hits = [geom.find_host(named_element)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'PORTA - VAI E VEM - 2 FOLHAS - COM VISOR:PO110 - 110x210:921359' -> 20$K02BTH7ox78yHUbKD_y IfcDoor PORTA - VAI E VEM - 2 FOLHAS - COM VISOR:PO110 - 110x210:921359
1 match(es)
1l5YQX3P17wemsuk3NHM9V IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882156
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (0.9, 0.9), (4.75, 4.75),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
1.2 m = 1.2 m = 120.0 file units
1.4 m = 1.4 m = 140.0 file units
0.9 m = 0.9 m = 90.0 file units
4.75 m = 4.75 m = 475.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
host = ifc.by_guid("1l5YQX3P17wemsuk3NHM9V")
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
1l5YQX3P17wemsuk3NHM9V IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882156
wall (m): {'start': -0.0, 'end': 7.217, 'near': -0.05, 'far': 0.05, 'base': 0.0, 'top': 3.25, 'length': 7.217, 'thickness': 0.1, 'height': 3.25}
```
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
host = ifc.by_guid("1l5YQX3P17wemsuk3NHM9V")
wall = geom.wall_box(host)
filling = geom.add_filling(host, "IfcWindow", "Glazing unit 235", width=1.2, height=1.4,
                           along=wall["start"] + 4.75, along_is_centre=True, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(filling.GlobalId, filling.is_a(), filling.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
3DGGZ1AMLEN9xptql1dQsd IfcWindow Glazing unit 235
model committed
```
Assistant: Completed. The window has been created and placed on its storey; the model was committed.

### Example 3
User:
Add a new window named 'Glazing unit 471' in the wall that holds the door named 'Door-Exterior-Double-Two_Lite:1500 x 2200:388226', 1.2 m wide and 1.4 m high, with the middle of the leaf 3.46 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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

# follow the named door or window to the wall it sits in
named_element = by_name("IfcDoor", "Door-Exterior-Double-Two_Lite:1500 x 2200:388226")
found = [geom.find_host(named_element)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Door-Exterior-Double-Two_Lite:1500 x 2200:388226' -> 0DYVV6xiX8dBBQRf0sq3D5 IfcDoor Door-Exterior-Double-Two_Lite:1500 x 2200:388226
[('0DYVV6xiX8dBBQRf0sq3D6', 'IfcWallStandardCase', 'Basic Wall:Interior - 79mm Partition (1-hr):388225')]
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# measure the wall before placing anything in it
host = ifc.by_guid("0DYVV6xiX8dBBQRf0sq3D6")
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
0DYVV6xiX8dBBQRf0sq3D6 IfcWallStandardCase Basic Wall:Interior - 79mm Partition (1-hr):388225
wall (m): {'start': 0.0, 'end': 5.4, 'near': -0.039, 'far': 0.04, 'base': 0.0, 'top': 3.14, 'length': 5.4, 'thickness': 0.079, 'height': 3.14}
```
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
host = ifc.by_guid("0DYVV6xiX8dBBQRf0sq3D6")
wall_box = geom.wall_box(host)
unit = geom.add_filling(host, "IfcWindow", "Glazing unit 471", width=1.2, height=1.4,
                        along=wall_box["start"] + 3.46, along_is_centre=True, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(unit.GlobalId, unit.is_a(), unit.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
2DIrufCkPBpOh$HEvCZu1q IfcWindow Glazing unit 471
model committed
```
Assistant: The new window is in the model, and the edit is written to the working file.
