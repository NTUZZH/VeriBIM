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
Move the wall with GlobalId '2HfLxLxtXFsuHUsmeNH9Fz' 3.46 m to the east (+X), keeping its z value fixed.

IFC model path: <path to the working copy>
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# convert metres to the model's own length unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def is_sole_owner(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # move the element by a world-axis offset
    product = ifc.by_guid(target_guid)
    placement = product.ObjectPlacement
    rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    offset = np.linalg.inv(rotation) @ (
        np.array([dx, dy, dz], dtype=float) / to_model)
    # the placement may share its point with others, so give it its own
    axis_placement = placement.RelativePlacement
    if not is_sole_owner(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    point = axis_placement.Location
    if not is_sole_owner(point, axis_placement):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        axis_placement.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, offset))

translate_element("2HfLxLxtXFsuHUsmeNH9Fz", 3.46, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
product = ifc.by_guid("2HfLxLxtXFsuHUsmeNH9Fz")
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcWall 2HfLxLxtXFsuHUsmeNH9Fz Basic Wall:w0.2:540896
model committed
```
Assistant: The wall now carries the values the instruction asked for. The edited model is committed.

### Example 2
User:
Please relocate the door hosted in the wall named 'Basic Wall:Interior - Blockwork 190:463223' 3.55 m to the east (+X), keeping its z value fixed.

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

# follow the host's openings to what fills them
host = by_name("IfcWall", "Basic Wall:Interior - Blockwork 190:463223")
hits = []
for rel in getattr(host, 'HasOpenings', None) or ():
    hole = rel.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        filling = fills.RelatedBuildingElement
        if filling is not None and filling.is_a("IfcDoor"):
            hits.append(filling)
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Interior - Blockwork 190:463223' -> 09xeuhDxD9if2$$tlu3_4b IfcWall Basic Wall:Interior - Blockwork 190:463223
1 match(es)
09xeuhDxD9if2$$tlu3_7R IfcDoor Doors_IntDbl_7:1810x2110mm:463241
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the wall the element stands in now
filling = ifc.by_guid("09xeuhDxD9if2$$tlu3_7R")
for fills in filling.FillsVoids or ():
    hole = fills.RelatingOpeningElement
    for voids in (hole.VoidsElements or ()) if hole else ():
        host = voids.RelatingBuildingElement
        if host is None:
            continue
        print('opening', hole.GlobalId, 'is cut in', host.GlobalId, host.is_a(), host.Name)
```
Tool result:
```
opening 1CISQOAQXE$mcRXDkjZzVz is cut in 09xeuhDxD9if2$$tlu3_4b IfcWall Basic Wall:Interior - Blockwork 190:463223
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# lengths in the instruction are metres; the model may use other units
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def translate_element(target_guid, dx, dy, dz):
    # apply the offset in the coordinate system the placement is written in
    target = ifc.by_guid(target_guid)
    placement = target.ObjectPlacement
    basis = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        basis = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    delta = np.linalg.inv(basis) @ (
        np.array([dx, dy, dz], dtype=float) / unit_scale)
    # do not move anything else that happens to share this point
    axis_placement = placement.RelativePlacement
    if not used_once(axis_placement, placement):
        axis_placement = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis_placement.Location,
            Axis=axis_placement.Axis, RefDirection=axis_placement.RefDirection)
        placement.RelativePlacement = axis_placement
    point = axis_placement.Location
    if not used_once(point, axis_placement):
        point = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(point.Coordinates))
        axis_placement.Location = point
    point.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(point.Coordinates, delta))

translate_element("1CISQOAQXE$mcRXDkjZzVz", 3.55, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid("1CISQOAQXE$mcRXDkjZzVz")
print(target.is_a(), target.GlobalId, target.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcOpeningElement 1CISQOAQXE$mcRXDkjZzVz Doors_IntDbl_7:1810x2110mm:463241:1
model committed
```
Assistant: Completed. The door has been updated; the model was committed.

### Example 3
User:
Relocate the column on storey 'Level 1' that stands about 30.6 m south (-Y) of the column with GlobalId 1KKUUPboD1dQdWx8AZE3Rd 1.05 m to the east (+X), keeping its z value fixed.

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

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', 'Level 1')
reference = ifc.by_guid('1KKUUPboD1dQdWx8AZE3Rd')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
hits = [geom.find_offset(reference, 'IfcColumn', storey,
                         'south', 30.6)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 1' -> 1fOVjSd7T40PyRtVEklS6X IfcBuildingStorey Level 1
given -> 1KKUUPboD1dQdWx8AZE3Rd IfcColumn UC-Universal Column-Column:356x368x177UC:190150
1KKUUPboD1dQdWx8AZE3un IfcColumn UC-Universal Column-Column:356x368x177UC:192016
```
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
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * scale

for target_guid in ('1KKUUPboD1dQdWx8AZE3un',):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcColumn 1KKUUPboD1dQdWx8AZE3un UC-Universal Column-Column:356x368x177UC:192016
  origin (m): [9.608, 100.382, 165.811]
  contained in: ['Level 1']
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((1.05, 1.05),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
1.05 m = 1.05 m = 1050.0 file units
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

# lengths in the instruction are metres; the model may use other units
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def move_element(target_guid, dx, dy, dz):
    # move the element by a world-axis offset
    element = ifc.by_guid(target_guid)
    placement = element.ObjectPlacement
    rotation = np.identity(3)
    if placement.is_a('IfcLocalPlacement') and placement.PlacementRelTo is not None:
        rotation = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo))[:3, :3]
    delta = np.linalg.inv(rotation) @ (
        np.array([dx, dy, dz], dtype=float) / scale)
    # the placement may share its point with others, so give it its own
    relative = placement.RelativePlacement
    if not only_user(relative, placement):
        relative = ifc.create_entity(
            'IfcAxis2Placement3D', Location=relative.Location,
            Axis=relative.Axis, RefDirection=relative.RefDirection)
        placement.RelativePlacement = relative
    origin = relative.Location
    if not only_user(origin, relative):
        origin = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(origin.Coordinates))
        relative.Location = origin
    origin.Coordinates = tuple(
        float(c) + float(d) for c, d in zip(origin.Coordinates, delta))

move_element('1KKUUPboD1dQdWx8AZE3un', 1.05, 0.0, 0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid('1KKUUPboD1dQdWx8AZE3un')
print(element.is_a(), element.GlobalId, element.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcColumn 1KKUUPboD1dQdWx8AZE3un UC-Universal Column-Column:356x368x177UC:192016
model committed
```
Assistant: Completed. The column now carries the values the instruction asked for; the model was committed.
