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
Shift the IfcColumn on the storey with GlobalId '15Z0v90RiHrPC20026FoKR' directly above the column with GlobalId '1JLj0zzc13lf57LAEk4xyw' into storey 'slab', leaving it exactly where it stands in the building.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
storey = ifc.by_guid("15Z0v90RiHrPC20026FoKR")
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
reference = ifc.by_guid("1JLj0zzc13lf57LAEk4xyw")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
matches = [geom.find_above_below(reference, "IfcColumn",
                                 "above", storey=storey)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 15Z0v90RiHrPC20026FoKR IfcBuildingStorey 1st Floor
given -> 1JLj0zzc13lf57LAEk4xyw IfcColumn UC-Universal Columns-Column:UC305x305x97:374088
1 match(es)
2L$NVfKM997BK28KaiKfGp IfcColumn UC-Universal Columns-Column:UC305x305x97:464833
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
3Zu5Bv0LOHrPC10026FoQQ 'Ground floor' 0.0
15Z0v90RiHrPC20026FoKR '1st Floor' 4.1
06lHcgBc1Fmfpuzjwb$HRq '2nd Floor' 8.2
06lHcgBc1Fmfpuzjwb$HOG '3rd Floor' 12.3
06lHcgBc1Fmfpuzjwb$HVg '4th Floor' 16.4
0rA4MuXJb0x9scv1yxAtMl 'slab' 20.5
model length unit in metres: 1
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def put_in_storey(floor, element):
    for link in getattr(floor, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (element,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatedElements=[element],
                      RelatingStructure=floor)

def nest_in_storey(floor, element):
    for link in getattr(floor, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (element,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatingObject=floor,
                      RelatedObjects=[element])

def writable_axis(placement):
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
        put_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("2L$NVfKM997BK28KaiKfGp"), ifc.by_guid("0rA4MuXJb0x9scv1yxAtMl"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
element = ifc.by_guid("2L$NVfKM997BK28KaiKfGp")
print(element.is_a(), element.GlobalId, element.Name)

commit()
print("model committed")
```
Tool result:
```
IfcColumn 2L$NVfKM997BK28KaiKfGp UC-Universal Columns-Column:UC305x305x97:464833
model committed
```
Assistant: The column has been updated, and the edit is written to the working file.

### Example 2
User:
Shift the column on storey 'Level 4' directly above the column named 'Concrete-Rectangular-Column:12 x 18:476914' into storey 'Level 1', leaving it exactly where it stands in the building.

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

# find the element directly over or under the named one
storey = by_name("IfcBuildingStorey", "Level 4")
reference = by_name("IfcColumn", "Concrete-Rectangular-Column:12 x 18:476914")
matches = [geom.find_above_below(reference, "IfcColumn",
                                 "above", storey=storey)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 4' -> 3Oc$NAV7v9WghbVnfWtUGM IfcBuildingStorey Level 4
named 'Concrete-Rectangular-Column:12 x 18:476914' -> 0PRz5qt8nBtwX26Sm71tJ5 IfcColumn Concrete-Rectangular-Column:12 x 18:476914
1 match(es)
0PRz5qt8nBtwX26Sm71tJ0 IfcColumn Concrete-Rectangular-Column:12 x 18:476919
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
2MayaW1Gv4Gviu994fLNUo 'Level 1' 0.0
2ZxBN$Tn90w8eyZlJ2sdUW 'Level 2 U' 4.2952
2MayaW1Gv4Gviu994fLNmx 'Level 2' 4.6
3MA2RcOF50Gv9gedvfTO1L 'Level 3 U' 8.8952
3Oc$NAV7v9WghbVnfWtVh3 'Level 3' 9.2
3MA2RcOF50Gv9gedvfTOFr 'Level 4 U' 13.4952
3Oc$NAV7v9WghbVnfWtUGM 'Level 4' 13.8
3MA2RcOF50Gv9gedvfTOBq 'Level 5 U' 18.0952
3Oc$NAV7v9WghbVnfWtUOx 'Level 5' 18.4
3Oc$NAV7v9WghbVnfWtUR2 'Roof' 23.0
model length unit in metres: 1
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner_history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def put_in_storey(floor, target):
    for rel in getattr(floor, 'ContainsElements', None) or ():
        rel.RelatedElements = (
            tuple(rel.RelatedElements) + (target,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner_history, Name=None, Description=None,
                      RelatedElements=[target],
                      RelatingStructure=floor)

def add_under_storey(floor, target):
    for rel in getattr(floor, 'IsDecomposedBy', None) or ():
        if rel.is_a('IfcRelAggregates'):
            rel.RelatedObjects = (
                tuple(rel.RelatedObjects) + (target,))
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

move_into_storey(ifc.by_guid("0PRz5qt8nBtwX26Sm71tJ0"), ifc.by_guid("2MayaW1Gv4Gviu994fLNUo"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
target = ifc.by_guid("0PRz5qt8nBtwX26Sm71tJ0")
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcColumn 0PRz5qt8nBtwX26Sm71tJ0 Concrete-Rectangular-Column:12 x 18:476919
model committed
```
Assistant: The column now carries the values the instruction asked for. The edited model is committed.

### Example 3
User:
Move the column on the storey with GlobalId '3Zu5Bv0LOHrPC10026FoQQ' that stands between the wall with GlobalId '2HfLxLxtXFsuHUsmeNHE0t' and the column with GlobalId '1ukRS5aU56Ng3SfmpLU2Vj' into storey 'fourth floor', leaving it exactly where it stands in the building.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element standing between the two the instruction names
storey = ifc.by_guid('3Zu5Bv0LOHrPC10026FoQQ')
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
first = ifc.by_guid('2HfLxLxtXFsuHUsmeNHE0t')
print('given ->', first.GlobalId, first.is_a(), first.Name)
second = ifc.by_guid('1ukRS5aU56Ng3SfmpLU2Vj')
print('given ->', second.GlobalId, second.is_a(), second.Name)
found = [geom.find_between(first, second,
                           'IfcColumn', storey)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Ground floor
given -> 2HfLxLxtXFsuHUsmeNHE0t IfcWall Basic Wall:w0.2:537386
given -> 1ukRS5aU56Ng3SfmpLU2Vj IfcColumn Columns_Rectangular:250x300mm:315422
1 match(es)
3MDJp6Bef33BNFzYYQK$HU IfcColumn Columns_Rectangular:250x300mm:321002
```
Assistant: Let me read the related elements before editing.
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
3Zu5Bv0LOHrPC10026FoQQ 'Ground floor' 0.0
15Z0v90RiHrPC20026FoKR 'first floor' 4.2
3_CEyLKGT6ffruo1RgXG6H 'second floor' 8.4
3_CEyLKGT6ffruo1RgXG1V 'Third floor' 12.6
3_CEyLKGT6ffruo1RgXGEg 'fourth floor' 16.8
3_CEyLKGT6ffruo1RgXG86 'Roof' 21.0
model length unit in metres: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def add_to_storey(floor, element):
    for rel in getattr(floor, 'ContainsElements', None) or ():
        rel.RelatedElements = (
            tuple(rel.RelatedElements) + (element,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[element],
                      RelatingStructure=floor)

def add_under_storey(floor, element):
    for rel in getattr(floor, 'IsDecomposedBy', None) or ():
        if rel.is_a('IfcRelAggregates'):
            rel.RelatedObjects = (
                tuple(rel.RelatedObjects) + (element,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=floor,
                      RelatedObjects=[element])

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
        add_to_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid('3MDJp6Bef33BNFzYYQK$HU'), ifc.by_guid('3_CEyLKGT6ffruo1RgXGEg'), True)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid('3MDJp6Bef33BNFzYYQK$HU')
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcColumn 3MDJp6Bef33BNFzYYQK$HU Columns_Rectangular:250x300mm:321002
model committed
```
Assistant: The column now carries the values the instruction asked for. The edited model is committed.
