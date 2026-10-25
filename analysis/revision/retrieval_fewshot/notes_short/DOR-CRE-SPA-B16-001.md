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
Replace the window on the storey with ID '1xS3BCk291UvhgP2dvNMKI' that stands about 12.2 m south (-Y) of the window with ID '1hOSvn6df7F8_7GcBWlR72' with a door named 'Doorset 813', 0.9 m wide and 2.1 m high, at the same position along the wall and standing on the wall's base. Cut the opening it fills and take the old opening out with the element it held.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element at the stated offset from the named neighbour
storey = ifc.by_guid("1xS3BCk291UvhgP2dvNMKI")
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid("1hOSvn6df7F8_7GcBWlR72")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
hits = [geom.find_offset(reference, "IfcWindow", storey,
                         "south", 12.2)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 1xS3BCk291UvhgP2dvNMKI IfcBuildingStorey Level 1
given -> 1hOSvn6df7F8_7GcBWlR72 IfcWindow M_Fixed:4835mm x 2420mm:4835mm x 2420mm:145788
1hOSvn6df7F8_7GcBWlRRL IfcWindow M_Fixed:750mm x 2200mm:750mm x 2200mm:147051
```
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
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * to_model

for target_guid in ("1hOSvn6df7F8_7GcBWlRRL",):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWindow 1hOSvn6df7F8_7GcBWlRRL M_Fixed:750mm x 2200mm:750mm x 2200mm:147051
  origin (m): [0.417, -12.605, 0.1]
  contained in: ['Level 1']
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
old = ifc.by_guid("1hOSvn6df7F8_7GcBWlRRL")
print(old.GlobalId, old.is_a(), old.Name)
opening_slot = geom.filling_slot(old)
host = opening_slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(opening_slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
1hOSvn6df7F8_7GcBWlRRL IfcWindow M_Fixed:750mm x 2200mm:750mm x 2200mm:147051
hosted in 2O2Fr$t4X7Zf8NOew3FNhv IfcWallStandardCase Basic Wall:Exterior - Brick on Block:138310
slot (m): {'along': 4.778, 'sill': 0.1, 'width': 0.75, 'height': 2.2}
wall (m): {'start': 0.0, 'end': 16.966, 'near': -0.209, 'far': 0.209, 'base': 0.0, 'top': 3.1, 'length': 16.966, 'thickness': 0.417, 'height': 3.1}
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
old = ifc.by_guid("1hOSvn6df7F8_7GcBWlRRL")
leaf = geom.replace_filling(old, "IfcDoor", "Doorset 813", width=0.9, height=2.1,
                            sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
2rrm2jBiH2584$6XEoZyQu IfcDoor Doorset 813
model committed
```
Assistant: The door has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Replace the window on storey '1° PAVIMENTO - TÉRREO (N.O)' that stands about 10.6 m east (+X) of the window with ID 0e$SWHp1zE7vA9ZmBiPLKT with a door named 'Doorset 595', 0.9 m wide and 2.1 m high, at the same position along the wall and standing on the wall's base. Cut the opening it fills and take the old opening out with the element it held.

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

# find the element at the stated offset from the named neighbour
storey = by_name("IfcBuildingStorey", "1° PAVIMENTO - TÉRREO (N.O)")
reference = ifc.by_guid("0e$SWHp1zE7vA9ZmBiPLKT")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
matches = [geom.find_offset(reference, "IfcWindow", storey,
                            "east", 10.6)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '1° PAVIMENTO - TÉRREO (N.O)' -> 31MO7odvv0cAeswhRbr4Rh IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.O)
given -> 0e$SWHp1zE7vA9ZmBiPLKT IfcWindow JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:170x80:948257
0e$SWHp1zE7vA9ZmBiPLLD IfcWindow JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948337
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
0.9 m = 0.9 m = 90.0 file units
2.1 m = 2.1 m = 210.0 file units
```
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
old = ifc.by_guid("0e$SWHp1zE7vA9ZmBiPLLD")
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
0e$SWHp1zE7vA9ZmBiPLLD IfcWindow JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948337
hosted in 1l5YQX3P17wemsuk3NHNuh IfcWall Basic Wall:PAR - EXT - ALV - 25 - ACAB.EXT BASE - ACAB.INT BASE:879000
slot (m): {'along': 11.651, 'sill': 0.55, 'width': 0.8, 'height': 2.3}
wall (m): {'start': 0.0, 'end': 13.761, 'near': -0.125, 'far': 0.125, 'base': 0.0, 'top': 3.95, 'length': 13.761, 'thickness': 0.25, 'height': 3.95}
```
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
old = ifc.by_guid("0e$SWHp1zE7vA9ZmBiPLLD")
leaf = geom.replace_filling(old, "IfcDoor", "Doorset 595", width=0.9, height=2.1,
                            sill=0.0)
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
print("model committed")
```
Tool result:
```
07CuHhwFH1dvtTQNZZOmTT IfcDoor Doorset 595
model committed
```
Assistant: Completed. The door has been created and placed on its storey; the model was committed.

### Example 3
User:
Please replace the window with ID '0D3BlT5oP0NBJakkkihu5K' with a door named 'Doorset 713', 0.91 m wide and 2.1 m high, at the same position along the wall and standing on the wall's base. Cut the opening it fills and take the old opening out with the element it held.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid('0D3BlT5oP0NBJakkkihu5K')]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
0D3BlT5oP0NBJakkkihu5K IfcWindow Windows_Sgl_Plain:910x910mm:334536
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
old = ifc.by_guid('0D3BlT5oP0NBJakkkihu5K')
print(old.GlobalId, old.is_a(), old.Name)
slot = geom.filling_slot(old)
host = slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
0D3BlT5oP0NBJakkkihu5K IfcWindow Windows_Sgl_Plain:910x910mm:334536
hosted in 06fM4ak4j3gP5QCVbwLzgQ IfcWall Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P:324531
slot (m): {'along': 21.88, 'sill': 1.2, 'width': 0.91, 'height': 0.91}
wall (m): {'start': 0.0, 'end': 36.58, 'near': -0.145, 'far': 0.145, 'base': 0.0, 'top': 4.0, 'length': 36.58, 'thickness': 0.29, 'height': 4.0}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
old = ifc.by_guid('0D3BlT5oP0NBJakkkihu5K')
unit = geom.replace_filling(old, 'IfcDoor', 'Doorset 713', width=0.91, height=2.1,
                            sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(unit.GlobalId, unit.is_a(), unit.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
39YuJooSjFwwemnbVfsmHC IfcDoor Doorset 713
model committed
```
Assistant: The new door is in the model. The edited model is committed.
