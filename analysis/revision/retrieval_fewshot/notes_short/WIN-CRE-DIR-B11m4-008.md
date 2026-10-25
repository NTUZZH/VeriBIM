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
Replace the door (ID: 2UWRnKBD55YxvbwsqV137c) with a window named 'Glazing unit 674', 120 cm wide and 140 cm high, at the same position along the wall and with its sill 90 cm above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
matches = [ifc.by_guid("2UWRnKBD55YxvbwsqV137c")]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
2UWRnKBD55YxvbwsqV137c IfcDoor M_Single-Flush:Door Type 2:458527
```
Assistant: The file may not be written in the unit the instruction uses.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((120.0, 1.2), (140.0, 1.4), (90.0, 0.9),):
    print(stated, "cm", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
120.0 cm = 1.2 m = 120.0 file units
140.0 cm = 1.4 m = 140.0 file units
90.0 cm = 0.9 m = 90.0 file units
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
old = ifc.by_guid("2UWRnKBD55YxvbwsqV137c")
print(old.GlobalId, old.is_a(), old.Name)
slot = geom.filling_slot(old)
host = slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
2UWRnKBD55YxvbwsqV137c IfcDoor M_Single-Flush:Door Type 2:458527
hosted in 2UWRnKBD55YxvbwsqV137d IfcWall Basic Wall:Wall type 7 interior:458526
slot (m): {'along': 2.565, 'sill': 0.0, 'width': 0.915, 'height': 2.134}
wall (m): {'start': -0.013, 'end': 4.083, 'near': -0.107, 'far': 0.107, 'base': 0.0, 'top': 3.6, 'length': 4.096, 'thickness': 0.214, 'height': 3.6}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# the geometry helper does the placement arithmetic
old = ifc.by_guid("2UWRnKBD55YxvbwsqV137c")
unit = geom.replace_filling(old, "IfcWindow", "Glazing unit 674", width=1.2, height=1.4,
                            sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(unit.GlobalId, unit.is_a(), unit.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
20hjbYemD6vRTaxJvm8rgp IfcWindow Glazing unit 674
model committed
```
Assistant: The window has been created and placed on its storey, and the edit is written to the working file.

### Example 2
User:
Replace the door hosted in the wall with ID 1fIVuvFffDJRV_SJESOtDs with a window named 'Glazing unit 497', 120 cm wide and 140 cm high, at the same position along the wall and with its sill 90 cm above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('1fIVuvFffDJRV_SJESOtDs')
print('given ->', host.GlobalId, host.is_a(), host.Name)
matches = []
for link in getattr(host, 'HasOpenings', None) or ():
    void = link.RelatedOpeningElement
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
given -> 1fIVuvFffDJRV_SJESOtDs IfcWallStandardCase 基本墙:Exterior - Insulation on Masonry:139854
1 match(es)
2UMN_OQKrAshZl3dHPukU_ IfcDoor M_Single-Flush:0915 x 2134mm:155278
```
Assistant tool call execute_ifc_code:
```python
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

for target_guid in ('2UMN_OQKrAshZl3dHPukU_',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 2UMN_OQKrAshZl3dHPukU_ M_Single-Flush:0915 x 2134mm:155278
  origin (m): [65.572, 6.52, 0.0]
  contained in: ['01 - Entry Level']
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((120.0, 1.2), (140.0, 1.4), (90.0, 0.9),):
    print(stated, 'cm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
120.0 cm = 1.2 m = 1200.0 file units
140.0 cm = 1.4 m = 1400.0 file units
90.0 cm = 0.9 m = 900.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
old = ifc.by_guid('2UMN_OQKrAshZl3dHPukU_')
print(old.GlobalId, old.is_a(), old.Name)
old_slot = geom.filling_slot(old)
host = old_slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(old_slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
2UMN_OQKrAshZl3dHPukU_ IfcDoor M_Single-Flush:0915 x 2134mm:155278
hosted in 1fIVuvFffDJRV_SJESOtDs IfcWallStandardCase 基本墙:Exterior - Insulation on Masonry:139854
slot (m): {'along': 6.454, 'sill': 0.0, 'width': 0.915, 'height': 2.134}
wall (m): {'start': 0.0, 'end': 8.553, 'near': -0.151, 'far': 0.151, 'base': 0.0, 'top': 11.4, 'length': 8.553, 'thickness': 0.303, 'height': 11.4}
```
Assistant tool call execute_ifc_code:
```python
old = ifc.by_guid('2UMN_OQKrAshZl3dHPukU_')
leaf = geom.replace_filling(old, 'IfcWindow', 'Glazing unit 497', width=1.2, height=1.4,
                            sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(leaf.GlobalId, leaf.is_a(), leaf.Name)

commit()
print('model committed')
```
Tool result:
```
39UKH6QzP3s8A3hmRBODyG IfcWindow Glazing unit 497
model committed
```
Assistant: Done. The window has been created and placed on its storey, and the model has been saved.

### Example 3
User:
Replace the door hosted in the wall with ID 3064w0y0nDv9wdb1cWL_I3 with a window named 'Glazing unit 459', 183 cm wide and 140 cm high, at the same position along the wall and with its sill 90 cm above the wall's base. Cut the opening it fills and take the old opening out with the element it held.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# follow the host's openings to what fills them
host = ifc.by_guid('3064w0y0nDv9wdb1cWL_I3')
print('given ->', host.GlobalId, host.is_a(), host.Name)
hits = []
for rel in getattr(host, 'HasOpenings', None) or ():
    hole = rel.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        unit = fills.RelatedBuildingElement
        if unit is not None and unit.is_a('IfcDoor'):
            hits.append(unit)
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3064w0y0nDv9wdb1cWL_I3 IfcWall Basic Wall:Exterior - Metal Panel on Mtl. Stud:813441
1 match(es)
2H0hu_zwv0NRkQTIc6f2Wd IfcDoor M_Double-Flush:1830 x 2134mm_Metal:857523
```
Assistant: Let me read the target before changing it.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * scale

for target_guid in ('2H0hu_zwv0NRkQTIc6f2Wd',):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(target, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcDoor 2H0hu_zwv0NRkQTIc6f2Wd M_Double-Flush:1830 x 2134mm_Metal:857523
  origin (m): [34.041, 113.706, 191.811]
  contained in: ['Level 6']
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((183.0, 1.83), (140.0, 1.4), (90.0, 0.9),):
    print(stated, 'cm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
183.0 cm = 1.83 m = 1830.0 file units
140.0 cm = 1.4 m = 1400.0 file units
90.0 cm = 0.9 m = 900.0 file units
```
Assistant: Let me measure what the instruction refers to.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
old = ifc.by_guid('2H0hu_zwv0NRkQTIc6f2Wd')
print(old.GlobalId, old.is_a(), old.Name)
old_slot = geom.filling_slot(old)
host = old_slot['host']
print('hosted in', host.GlobalId, host.is_a(), host.Name)
print('slot (m):', {k: round(old_slot[k], 3) for k in ('along', 'sill', 'width', 'height')})
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
2H0hu_zwv0NRkQTIc6f2Wd IfcDoor M_Double-Flush:1830 x 2134mm_Metal:857523
hosted in 3064w0y0nDv9wdb1cWL_I3 IfcWall Basic Wall:Exterior - Metal Panel on Mtl. Stud:813441
slot (m): {'along': 2.551, 'sill': 0.0, 'width': 1.83, 'height': 2.134}
wall (m): {'start': 0.0, 'end': 14.18, 'near': -0.129, 'far': 0.129, 'base': 0.0, 'top': 9.0, 'length': 14.18, 'thickness': 0.258, 'height': 9.0}
```
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
old = ifc.by_guid('2H0hu_zwv0NRkQTIc6f2Wd')
unit = geom.replace_filling(old, 'IfcWindow', 'Glazing unit 459', width=1.83,
                            height=1.4, sill=0.9)
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

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
2z9WoHc0T7agflatMUUQu_ IfcWindow Glazing unit 459
model committed
```
Assistant: Completed. The window has been created and placed on its storey; the model was committed.
