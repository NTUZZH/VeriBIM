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
Move the space on storey 'Ground Floor' that stands between the window named 'WD - 071' and the window named 'WD - 069' into storey '2. Story', leaving it exactly where it stands in the building.

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

# find the element standing between the two the instruction names
storey = by_name("IfcBuildingStorey", "Ground Floor")
first = by_name("IfcWindow", "WD - 071")
second = by_name("IfcWindow", "WD - 069")
hits = [geom.find_between(first, second,
                          "IfcSpace", storey)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
named 'Ground Floor' -> 1oZ0wPs_PE8ANCPg3bIs4j IfcBuildingStorey Ground Floor
named 'WD - 071' -> 2nY0fN1ZJiGRuAwTbHsZWV IfcWindow WD - 071
named 'WD - 069' -> 01H9AkBqfrGw1JFlPwYare IfcWindow WD - 069
[('3Y_DG1LCw8GPKzAM9XjfeF', 'IfcSpace', '01')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for level in ifc.by_type('IfcBuildingStorey'):
    print(level.GlobalId, repr(level.Name), level.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1oZ0wPs_PE8ANCPg3bIs4j 'Ground Floor' 0.0
2F0V3QPDDFMRTpJqxqPeZR '1. Story' 3900.0
3y21AUC9X4yAqzLGUny16E '2. Story' 7800.0
0oDVLe405wJOYktB543xA2 '3. Story' 11700.0
0_QWoW2mE3Ggba6Hx2fMqz '4. Story' 15600.0
23bpvT20MdJx$Wz1yfgQlF '5. Story' 19500.0
model length unit in metres: 0.001
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def contain_in_storey(level, element):
    for link in getattr(level, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (element,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[element],
                      RelatingStructure=level)

def nest_in_storey(level, element):
    for link in getattr(level, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (element,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=level,
                      RelatedObjects=[element])

def writable_axis(placement):
    # substitute a private point before writing coordinates
    axis = placement.RelativePlacement
    if not only_user(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location, Axis=axis.Axis,
            RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    if not only_user(axis.Location, axis):
        axis.Location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(axis.Location.Coordinates))
    return axis

def write_world_frame(product, world):
    placement = product.ObjectPlacement
    parent = np.identity(4)
    if placement.PlacementRelTo is not None:
        parent = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo), dtype=float)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = writable_axis(placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 0]))

def move_into_storey(product, storey, keep_world):
    placement = product.ObjectPlacement
    world = np.array(ifcopenshell.util.placement.get_local_placement(placement),
                     dtype=float)
    holder = None
    for relation in getattr(product, 'ContainedInStructure', None) or ():
        holder = relation
        break
    if holder is None:
        for relation in getattr(product, 'Decomposes', None) or ():
            if relation.is_a('IfcRelAggregates'):
                holder = relation
                break
    if holder is not None:
        held = ('RelatedObjects' if holder.is_a('IfcRelAggregates')
                else 'RelatedElements')
        members = [m for m in (getattr(holder, held) or ()) if m != product]
        if members:
            setattr(holder, held, tuple(members))
        else:
            ifc.remove(holder)
    if product.is_a('IfcSpatialStructureElement') or product.is_a('IfcSpace'):
        nest_in_storey(storey, product)
    else:
        contain_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("3Y_DG1LCw8GPKzAM9XjfeF"), ifc.by_guid("3y21AUC9X4yAqzLGUny16E"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
element = ifc.by_guid("3Y_DG1LCw8GPKzAM9XjfeF")
print(element.is_a(), element.GlobalId, element.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcSpace 3Y_DG1LCw8GPKzAM9XjfeF 01
model committed
```
Assistant: Done. The space now carries the values the instruction asked for, and the model has been saved.

### Example 2
User:
Can you move the space on storey 'Ground Floor' that stands between the window named 'Windows_Sgl_Plain:910x910mm:374291' and the door named 'Doors_IntSgl:810x2110mm:424036' into storey 'Floor 3', leaving it exactly where it stands in the building?

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

# find the element standing between the two the instruction names
storey = by_name('IfcBuildingStorey', 'Ground Floor')
first = by_name('IfcWindow', 'Windows_Sgl_Plain:910x910mm:374291')
second = by_name('IfcDoor', 'Doors_IntSgl:810x2110mm:424036')
hits = [geom.find_between(first, second,
                          'IfcSpace', storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Ground Floor' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Ground Floor
named 'Windows_Sgl_Plain:910x910mm:374291' -> 02Is$GMEP6Z9T5ctXePW4S IfcWindow Windows_Sgl_Plain:910x910mm:374291
named 'Doors_IntSgl:810x2110mm:424036' -> 323i7xqz98l92vUztLixM_ IfcDoor Doors_IntSgl:810x2110mm:424036
1 match(es)
3pk0g6KqP1SOtG9hcdYLTE IfcSpace 1
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3Zu5Bv0LOHrPC10026FoQQ 'Ground Floor' 0.0
15Z0v90RiHrPC20026FoKR 'Floor 1' 3.4
2Sw4U2s6bAdRSu3_Og4L7B 'Floor 2' 6.8
2Sw4U2s6bAdRSu3_Og4LUY 'Floor 3' 10.2
2tQ__s5tn9XfKiBK6$PaPt 'Floor 4' 13.6
model length unit in metres: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner_history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def put_in_storey(floor, target):
    for link in getattr(floor, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (target,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner_history, Name=None, Description=None,
                      RelatedElements=[target],
                      RelatingStructure=floor)

def add_under_storey(floor, target):
    for link in getattr(floor, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (target,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=owner_history, Name=None, Description=None,
                      RelatingObject=floor,
                      RelatedObjects=[target])

def writable_axis(placement):
    # do not move anything else that happens to share this point
    axis = placement.RelativePlacement
    if not used_once(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location, Axis=axis.Axis,
            RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    if not used_once(axis.Location, axis):
        axis.Location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(axis.Location.Coordinates))
    return axis

def write_world_frame(product, world):
    placement = product.ObjectPlacement
    parent = np.identity(4)
    if placement.PlacementRelTo is not None:
        parent = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo), dtype=float)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = writable_axis(placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 0]))

def move_into_storey(product, storey, keep_world):
    placement = product.ObjectPlacement
    world = np.array(ifcopenshell.util.placement.get_local_placement(placement),
                     dtype=float)
    holder = None
    for relation in getattr(product, 'ContainedInStructure', None) or ():
        holder = relation
        break
    if holder is None:
        for relation in getattr(product, 'Decomposes', None) or ():
            if relation.is_a('IfcRelAggregates'):
                holder = relation
                break
    if holder is not None:
        held = ('RelatedObjects' if holder.is_a('IfcRelAggregates')
                else 'RelatedElements')
        members = [m for m in (getattr(holder, held) or ()) if m != product]
        if members:
            setattr(holder, held, tuple(members))
        else:
            ifc.remove(holder)
    if product.is_a('IfcSpatialStructureElement') or product.is_a('IfcSpace'):
        add_under_storey(storey, product)
    else:
        put_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid('3pk0g6KqP1SOtG9hcdYLTE'), ifc.by_guid('2Sw4U2s6bAdRSu3_Og4LUY'), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
target = ifc.by_guid('3pk0g6KqP1SOtG9hcdYLTE')
print(target.is_a(), target.GlobalId, target.Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
IfcSpace 3pk0g6KqP1SOtG9hcdYLTE 1
model committed
```
Assistant: The space has been updated. The edited model is committed.

### Example 3
User:
Move the space on storey 'Ground Floor' that stands between the door named 'DOO - 003' and the door named 'DOO - 001' into storey '2. Story', leaving it exactly where it stands in the building.

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

# find the element standing between the two the instruction names
storey = by_name("IfcBuildingStorey", "Ground Floor")
first = by_name("IfcDoor", "DOO - 003")
second = by_name("IfcDoor", "DOO - 001")
hits = [geom.find_between(first, second,
                          "IfcSpace", storey)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
named 'Ground Floor' -> 1oZ0wPs_PE8ANCPg3bIs4j IfcBuildingStorey Ground Floor
named 'DOO - 003' -> 3ARJSEymSIGgY6UoqIukwn IfcDoor DOO - 003
named 'DOO - 001' -> 2csGTEFbFsGuR0NxKD4lgg IfcDoor DOO - 001
[('1i7H90PEI7GesVY7q7db0D', 'IfcSpace', '05')]
```
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
0IlZZTCXBtGg_nrNZIxV9F 'Roof' 19200.0
1HHohCaVoIHPBNl1_mmI2U '5. Story' 16000.0
00TDNY16vqHB0p166$_a$G '4. Story' 12800.0
2F0V3QPDDFMRTpJqxqPeZR '1. Story' 3200.0
1oZ0wPs_PE8ANCPg3bIs4j 'Ground Floor' 0.0
3y21AUC9X4yAqzLGUny16E '2. Story' 6400.0
0Xs8bhxcAqHAzgPkVKwF0S '3. Story' 9600.0
model length unit in metres: 0.001
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def contain_in_storey(floor, target):
    for link in getattr(floor, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (target,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatedElements=[target],
                      RelatingStructure=floor)

def add_under_storey(floor, target):
    for link in getattr(floor, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (target,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatingObject=floor,
                      RelatedObjects=[target])

def writable_axis(placement):
    # the placement may share its point with others, so give it its own
    axis = placement.RelativePlacement
    if not only_user(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location, Axis=axis.Axis,
            RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    if not only_user(axis.Location, axis):
        axis.Location = ifc.create_entity(
            'IfcCartesianPoint', Coordinates=tuple(axis.Location.Coordinates))
    return axis

def write_world_frame(product, world):
    placement = product.ObjectPlacement
    parent = np.identity(4)
    if placement.PlacementRelTo is not None:
        parent = np.array(ifcopenshell.util.placement.get_local_placement(
            placement.PlacementRelTo), dtype=float)
    local = np.linalg.inv(parent) @ np.asarray(world, dtype=float)
    axis = writable_axis(placement)
    axis.Location.Coordinates = tuple(float(v) for v in local[:3, 3])
    axis.Axis = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 2]))
    axis.RefDirection = ifc.create_entity(
        'IfcDirection', DirectionRatios=tuple(float(v) for v in local[:3, 0]))

def move_into_storey(product, storey, keep_world):
    placement = product.ObjectPlacement
    world = np.array(ifcopenshell.util.placement.get_local_placement(placement),
                     dtype=float)
    holder = None
    for relation in getattr(product, 'ContainedInStructure', None) or ():
        holder = relation
        break
    if holder is None:
        for relation in getattr(product, 'Decomposes', None) or ():
            if relation.is_a('IfcRelAggregates'):
                holder = relation
                break
    if holder is not None:
        held = ('RelatedObjects' if holder.is_a('IfcRelAggregates')
                else 'RelatedElements')
        members = [m for m in (getattr(holder, held) or ()) if m != product]
        if members:
            setattr(holder, held, tuple(members))
        else:
            ifc.remove(holder)
    if product.is_a('IfcSpatialStructureElement') or product.is_a('IfcSpace'):
        add_under_storey(storey, product)
    else:
        contain_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("1i7H90PEI7GesVY7q7db0D"), ifc.by_guid("3y21AUC9X4yAqzLGUny16E"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
target = ifc.by_guid("1i7H90PEI7GesVY7q7db0D")
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcSpace 1i7H90PEI7GesVY7q7db0D 05
model committed
```
Assistant: Completed. The space has been updated; the model was committed.
