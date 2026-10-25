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
Add a new window named 'Glazing unit 775' in the wall on storey 'PLANTA BAJA' that stands about 6.5 m east (+X) of the wall named 'Muro básico:BLOQUE 100 mm:1965446', 1.2 m wide and 1.4 m high, with the middle of the leaf 2.16 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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
storey = by_name("IfcBuildingStorey", "PLANTA BAJA")
reference = by_name("IfcWall", "Muro básico:BLOQUE 100 mm:1965446")
matches = [geom.find_offset(reference, "IfcWall", storey,
                            "east", 6.5)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'PLANTA BAJA' -> 0OCkzK25HA0wxSqRSYLGvE IfcBuildingStorey PLANTA BAJA
named 'Muro básico:BLOQUE 100 mm:1965446' -> 0zHCz5TiDEax33E7KiKaks IfcWallStandardCase Muro básico:BLOQUE 100 mm:1965446
31BrNcu85BxOlgMGprRfIT IfcWallStandardCase Muro básico:BLOQUE 100 mm:1950218
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
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * to_model

for target_guid in ("31BrNcu85BxOlgMGprRfIT",):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWallStandardCase 31BrNcu85BxOlgMGprRfIT Muro básico:BLOQUE 100 mm:1950218
  origin (m): [2.651, -7.742, 0.0]
  contained in: ['PLANTA BAJA']
```
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
host = ifc.by_guid("31BrNcu85BxOlgMGprRfIT")
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
31BrNcu85BxOlgMGprRfIT IfcWallStandardCase Muro básico:BLOQUE 100 mm:1950218
wall (m): {'start': 0.0, 'end': 3.9, 'near': -0.05, 'far': 0.05, 'base': 0.0, 'top': 3.0, 'length': 3.9, 'thickness': 0.1, 'height': 3.0}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
host = ifc.by_guid("31BrNcu85BxOlgMGprRfIT")
wall = geom.wall_box(host)
leaf = geom.add_filling(host, "IfcWindow", "Glazing unit 775", width=1.2, height=1.4,
                        along=wall["start"] + 2.16, along_is_centre=True, sill=0.9)
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

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
0Ksj3fOmb5tuTlJqsDY6OF IfcWindow Glazing unit 775
model committed
```
Assistant: Done. The window has been created and placed on its storey, and the model has been saved.

### Example 2
User:
Add a new window named 'Glazing unit 442' in the wall on storey 'PLANTA BAJA' that stands about 5.8 m east (+X) of the column named 'Pilar rectangular hormigón:250 x 250 mm:1969268', 1.2 m wide and 1.4 m high, with the middle of the leaf 1.38 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', 'PLANTA BAJA')
reference = by_name('IfcColumn', 'Pilar rectangular hormigón:250 x 250 mm:1969268')
found = [geom.find_offset(reference, 'IfcWall', storey,
                          'east', 5.8)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'PLANTA BAJA' -> 0OCkzK25HA0wxSqRSYLGvE IfcBuildingStorey PLANTA BAJA
named 'Pilar rectangular hormigón:250 x 250 mm:1969268' -> 2RHyAzft50VP4V7IUHqEpo IfcColumn Pilar rectangular hormigón:250 x 250 mm:1969268
1 match(es)
31BrNcu85BxOlgMGprRfOh IfcWallStandardCase Muro básico:BLOQUE 100 mm:1949884
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# measure the wall before placing anything in it
host = ifc.by_guid('31BrNcu85BxOlgMGprRfOh')
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
31BrNcu85BxOlgMGprRfOh IfcWallStandardCase Muro básico:BLOQUE 100 mm:1949884
wall (m): {'start': -0.0, 'end': 2.285, 'near': -0.05, 'far': 0.05, 'base': 0.0, 'top': 3.0, 'length': 2.285, 'thickness': 0.1, 'height': 3.0}
```
Assistant tool call execute_ifc_code:
```python
# geom cuts the opening, places the leaf and writes the relations
host = ifc.by_guid('31BrNcu85BxOlgMGprRfOh')
wall_box = geom.wall_box(host)
unit = geom.add_filling(host, 'IfcWindow', 'Glazing unit 442', width=1.2, height=1.4,
                        along=wall_box['start'] + 1.38, along_is_centre=True, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
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
1WH58DpST1pfBy5I8RweJv IfcWindow Glazing unit 442
model committed
```
Assistant: Done. The new window is in the model, and the model has been saved.

### Example 3
User:
Add a new window named 'Glazing unit 493' in the wall on storey '01 - Entry Level' that stands about 34.3 m east (+X) of the column named 'M_Concrete-Round-Column:300mm:140998', 1.2 m wide and 1.4 m high, with the middle of the leaf 1.44 m along the wall from its start and with its sill 0.9 m above the wall's base. Cut the opening it fills.

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

storey = by_name("IfcBuildingStorey", "01 - Entry Level")
reference = by_name("IfcColumn", "M_Concrete-Round-Column:300mm:140998")
hits = [geom.find_offset(reference, "IfcWall", storey,
                         "east", 34.3)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '01 - Entry Level' -> 298uW9PODAmgWwAQB0IyQ0 IfcBuildingStorey 01 - Entry Level
named 'M_Concrete-Round-Column:300mm:140998' -> 3wh27gpDH7bg434tPIc7CG IfcColumn M_Concrete-Round-Column:300mm:140998
2UMN_OQKrAshZl3dHPuk8B IfcWallStandardCase 基本墙:Exterior - Insulation on Masonry:154427
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((1.2, 1.2), (1.4, 1.4), (0.9, 0.9), (1.44, 1.44),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.2 m = 1.2 m = 1200.0 file units
1.4 m = 1.4 m = 1400.0 file units
0.9 m = 0.9 m = 900.0 file units
1.44 m = 1.44 m = 1440.0 file units
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("2UMN_OQKrAshZl3dHPuk8B")
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
2UMN_OQKrAshZl3dHPuk8B IfcWallStandardCase 基本墙:Exterior - Insulation on Masonry:154427
wall (m): {'start': -0.0, 'end': 2.64, 'near': -0.151, 'far': 0.152, 'base': 0.0, 'top': 3.8, 'length': 2.64, 'thickness': 0.303, 'height': 3.8}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("2UMN_OQKrAshZl3dHPuk8B")
wall_box = geom.wall_box(host)
unit = geom.add_filling(host, "IfcWindow", "Glazing unit 493", width=1.2, height=1.4,
                        along=wall_box["start"] + 1.44, along_is_centre=True, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
print(unit.GlobalId, unit.is_a(), unit.Name)

commit()
print("model committed")
```
Tool result:
```
3JS$tom$j5FQh7hQcDQUhM IfcWindow Glazing unit 493
model committed
```
Assistant: The new window is in the model, and the edit is written to the working file.
