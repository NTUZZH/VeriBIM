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
Move the column on storey 'Second Floor' that stands about 21.6 m south (-Y) of the column named 'W-Wide Flange-Column:W10X49:240128' 0.71 m to the west (-X).

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

storey = by_name("IfcBuildingStorey", "Second Floor")
reference = by_name("IfcColumn", "W-Wide Flange-Column:W10X49:240128")
matches = [geom.find_offset(reference, "IfcColumn", storey,
                            "south", 21.6)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Second Floor' -> 1MvMAoc2L5LRJwssbEGeEw IfcBuildingStorey Second Floor
named 'W-Wide Flange-Column:W10X49:240128' -> 2iaS6pA019fAV5MeyYcNLX IfcColumn W-Wide Flange-Column:W10X49:240128
1 match(es)
2T5YSnBLj0MfbmybBzYSlf IfcColumn W-Wide Flange-Column:W10X49:225669
```
Assistant: I will check the element's class and position first.
Assistant tool call execute_ifc_code:
```python
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

for target_guid in ("2T5YSnBLj0MfbmybBzYSlf",):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(product, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcColumn 2T5YSnBLj0MfbmybBzYSlf W-Wide Flange-Column:W10X49:225669
  origin (m): [219928.678, 907151.051, 55.677]
  contained in: ['Second Floor']
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.71, 0.71),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
0.71 m = 0.71 m = 2.329396 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def move_element(target_guid, dx, dy, dz):
    product = ifc.by_guid(target_guid)
    placement = product.ObjectPlacement
    rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    shift_vector = np.linalg.inv(rotation) @ (
        np.array([dx, dy, dz], dtype=float) / unit_scale)
    relative = placement.RelativePlacement
    if not only_user(relative, placement):
        relative = ifc.create_entity(
            'IfcAxis2Placement3D', Location=relative.Location,
            Axis=relative.Axis, RefDirection=relative.RefDirection)
        placement.RelativePlacement = relative
    point = relative.Location
    if not only_user(point, relative):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        relative.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, shift_vector))

move_element("2T5YSnBLj0MfbmybBzYSlf", -0.71, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid("2T5YSnBLj0MfbmybBzYSlf")
print(product.is_a(), product.GlobalId, product.Name)

commit()
print("model committed")
```
Tool result:
```
IfcColumn 2T5YSnBLj0MfbmybBzYSlf W-Wide Flange-Column:W10X49:225669
model committed
```
Assistant: Completed. The column now carries the values the instruction asked for; the model was committed.

### Example 2
User:
Relocate the slab on storey 'CIMENTACION' that stands about 2.2 m south (-Y) of the slab named 'Zapata-Rect Adozada X:1000x1000x300mm:2092579' 2.72 m to the south (-Y).

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
storey = by_name("IfcBuildingStorey", "CIMENTACION")
reference = by_name("IfcSlab", "Zapata-Rect Adozada X:1000x1000x300mm:2092579")
found = [geom.find_offset(reference, "IfcSlab", storey,
                          "south", 2.2)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'CIMENTACION' -> 0OCkzK25HA0wxSqRSYGLkp IfcBuildingStorey CIMENTACION
named 'Zapata-Rect Adozada X:1000x1000x300mm:2092579' -> 1KObFFsNL7b864etVJ1P8j IfcSlab Zapata-Rect Adozada X:1000x1000x300mm:2092579
[('1ok_bPb6TBQRw1d9XRyO4N', 'IfcSlab', 'Suelo:Losa 20 cm:2017430')]
```
Assistant: I will check the element's class and position first.
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
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * unit_scale

for target_guid in ("1ok_bPb6TBQRw1d9XRyO4N",):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcSlab 1ok_bPb6TBQRw1d9XRyO4N Suelo:Losa 20 cm:2017430
  origin (m): [0.0, 0.0, -0.6]
  contained in: ['CIMENTACION']
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# convert metres to the model's own length unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # move the element by a world-axis offset
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    offset = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / unit_scale)
    # the placement may share its point with others, so give it its own
    relative = placement.RelativePlacement
    if not only_user(relative, placement):
        relative = ifc.create_entity(
            'IfcAxis2Placement3D', Location=relative.Location,
            Axis=relative.Axis, RefDirection=relative.RefDirection)
        placement.RelativePlacement = relative
    location = relative.Location
    if not only_user(location, relative):
        location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(location.Coordinates))
        relative.Location = location
    location.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(location.Coordinates, offset))

translate_element("1ok_bPb6TBQRw1d9XRyO4N", 0.0, -2.72, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
element = ifc.by_guid("1ok_bPb6TBQRw1d9XRyO4N")
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcSlab 1ok_bPb6TBQRw1d9XRyO4N Suelo:Losa 20 cm:2017430
model committed
```
Assistant: Completed. The slab has been updated; the model was committed.

### Example 3
User:
Shift the column on storey 'Second Floor' that stands about 39.5 m south (-Y) of the column named 'W-Wide Flange-Column:W10X49:242402' 1.28 m to the west (-X).

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
storey = by_name('IfcBuildingStorey', 'Second Floor')
reference = by_name('IfcColumn', 'W-Wide Flange-Column:W10X49:242402')
matches = [geom.find_offset(reference, 'IfcColumn', storey,
                            'south', 39.5)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
named 'Second Floor' -> 1MvMAoc2L5LRJwssbEGeEw IfcBuildingStorey Second Floor
named 'W-Wide Flange-Column:W10X49:242402' -> 2b2aTmjmPCDhDXxQM70YMw IfcColumn W-Wide Flange-Column:W10X49:242402
[('2T5YSnBLj0MfbmybBzYSlg', 'IfcColumn', 'W-Wide Flange-Column:W10X49:225670')]
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.28, 1.28),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
1.28 m = 1.28 m = 4.199475 file units
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# the file's length unit decides what a metre is worth here
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def move_element(target_guid, dx, dy, dz):
    # move the element by a world-axis offset
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    shift_vector = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # the placement may share its point with others, so give it its own
    axis_placement = placement.RelativePlacement
    if not used_once(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    location = axis_placement.Location
    if not used_once(location, axis_placement):
        location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(location.Coordinates))
        axis_placement.Location = location
    location.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(location.Coordinates, shift_vector))

move_element('2T5YSnBLj0MfbmybBzYSlg', -1.28, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid('2T5YSnBLj0MfbmybBzYSlg')
print(element.is_a(), element.GlobalId, element.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcColumn 2T5YSnBLj0MfbmybBzYSlg W-Wide Flange-Column:W10X49:225670
model committed
```
Assistant: Completed. The column has been updated; the model was committed.
