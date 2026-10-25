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
Change the overall height of the door hosted in the wall with GlobalId '0FVjM5dW9B5R$waG5uoSDW' from 3 meters to 2.4 meters, keeping its placement fixed.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# follow the host's openings to what fills them
host = ifc.by_guid('0FVjM5dW9B5R$waG5uoSDW')
print('given ->', host.GlobalId, host.is_a(), host.Name)
matches = []
for link in getattr(host, 'HasOpenings', None) or ():
    hole = link.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        unit = fills.RelatedBuildingElement
        if unit is not None and unit.is_a('IfcDoor'):
            matches.append(unit)
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 0FVjM5dW9B5R$waG5uoSDW IfcWall SW - 010
0a8TqWo0L5SQwgC4ARwz1G IfcDoor DOO - 015
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
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale

for target_guid in ('0a8TqWo0L5SQwgC4ARwz1G',):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 0a8TqWo0L5SQwgC4ARwz1G DOO - 015
  origin (m): [4.0, 17.4, 0.0]
  contained in: ['Ground Floor']
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((2.4, 2.4),):
    print(stated, 'meters', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
2.4 meters = 2.4 m = 2400.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

# the file's length unit decides what a metre is worth here
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

# update the attribute
ifc.by_guid('0a8TqWo0L5SQwgC4ARwz1G').OverallHeight = 2.4 / unit_scale
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
product = ifc.by_guid('0a8TqWo0L5SQwgC4ARwz1G')
print(product.is_a(), product.GlobalId, product.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcDoor 0a8TqWo0L5SQwgC4ARwz1G DOO - 015
model committed
```
Assistant: The door has been updated, and the edit is written to the working file.

### Example 2
User:
Please change the overall height of the door hosted in the wall named 'Muro básico:BLOQUE 100 mm:1950060' from 2.02 meters to 1.62 meters, keeping its placement fixed.

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
host = by_name('IfcWall', 'Muro básico:BLOQUE 100 mm:1950060')
matches = []
for relation in getattr(host, 'HasOpenings', None) or ():
    void = relation.RelatedOpeningElement
    for fills in (getattr(void, 'HasFillings', None) or ()) if void else ():
        leaf = fills.RelatedBuildingElement
        if leaf is not None and leaf.is_a('IfcDoor'):
            matches.append(leaf)
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Muro básico:BLOQUE 100 mm:1950060' -> 31BrNcu85BxOlgMGprRfVx IfcWallStandardCase Muro básico:BLOQUE 100 mm:1950060
31BrNcu85BxOlgMGprRfHW IfcDoor Simple 4 Paneles:0800 x 2000 mm:1950455
```
Assistant: I will check the element's class and position first.
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
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * unit_scale

for target_guid in ('31BrNcu85BxOlgMGprRfHW',):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 31BrNcu85BxOlgMGprRfHW Simple 4 Paneles:0800 x 2000 mm:1950455
  origin (m): [1.201, -3.697, 0.0]
  contained in: ['PLANTA BAJA']
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

# the file's length unit decides what a metre is worth here
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

# write the attribute the instruction names
ifc.by_guid('31BrNcu85BxOlgMGprRfHW').OverallHeight = 1.62 / unit_scale
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
product = ifc.by_guid('31BrNcu85BxOlgMGprRfHW')
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcDoor 31BrNcu85BxOlgMGprRfHW Simple 4 Paneles:0800 x 2000 mm:1950455
model committed
```
Assistant: Finished: the door now carries the values the instruction asked for. The file on disk now holds the change.

### Example 3
User:
Change the overall height of the window hosted in the wall named 'Basic Wall:Exterior Wall  - 200mm:364912' from 2.5 meters to 1.88 meters, keeping its placement fixed.

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
host = by_name('IfcWall', 'Basic Wall:Exterior Wall  - 200mm:364912')
hits = []
for rel in getattr(host, 'HasOpenings', None) or ():
    hole = rel.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        filling = fills.RelatedBuildingElement
        if filling is not None and filling.is_a('IfcWindow'):
            hits.append(filling)
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Exterior Wall  - 200mm:364912' -> 16L8xAoTn24hVqnk7rtlLk IfcWallStandardCase Basic Wall:Exterior Wall  - 200mm:364912
1 match(es)
1Lm_zyC$rCAgXKKZJbi100 IfcWindow Window-Casement-Triple-Side-Transom:4000 x 2500:370222
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit

# convert metres to the model's own length unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

# write the attribute the instruction names
ifc.by_guid('1Lm_zyC$rCAgXKKZJbi100').OverallHeight = 1.88 / unit_scale
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid('1Lm_zyC$rCAgXKKZJbi100')
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcWindow 1Lm_zyC$rCAgXKKZJbi100 Window-Casement-Triple-Side-Transom:4000 x 2500:370222
model committed
```
Assistant: The window has been updated. The edited model is committed.
