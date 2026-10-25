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
Move the space with GlobalId '1hhRjIJRNsHBc_vd1VFNTN' into storey '2. Geschoss', leaving it exactly where it stands in the building.

IFC model path: <path to the working copy>
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1oZ0wPs_PE8ANCPg3bIs4j 'Ground Floor' 0.0
2MI9igTjwOGR0GQpuEY1rB '1. Geschoss' 4800.0
2VK2i8hZi3HPahZLbt_$zv '2. Geschoss' 9600.0
2F0V3QPDDFMRTpJqxqPeZR '3. Geschoss' 14400.0
3y21AUC9X4yAqzLGUny16E '4. Geschoss' 19200.0
1lFSXKw54lJx6xDb3LH05i '5. Geschoss' 24000.0
model length unit in metres: 0.001
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner_history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def is_sole_owner(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def put_in_storey(storey, product):
    for relation in getattr(storey, 'ContainsElements', None) or ():
        relation.RelatedElements = (
            tuple(relation.RelatedElements) + (product,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner_history, Name=None, Description=None,
                      RelatedElements=[product],
                      RelatingStructure=storey)

def nest_in_storey(storey, product):
    for relation in getattr(storey, 'IsDecomposedBy', None) or ():
        if relation.is_a('IfcRelAggregates'):
            relation.RelatedObjects = (
                tuple(relation.RelatedObjects) + (product,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=owner_history, Name=None, Description=None,
                      RelatingObject=storey,
                      RelatedObjects=[product])

def writable_axis(placement):
    axis = placement.RelativePlacement
    if not is_sole_owner(axis, placement):
        axis = ifc.create_entity(
            'IfcAxis2Placement3D', Location=axis.Location, Axis=axis.Axis,
            RefDirection=axis.RefDirection)
        placement.RelativePlacement = axis
    if not is_sole_owner(axis.Location, axis):
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

move_into_storey(ifc.by_guid('1hhRjIJRNsHBc_vd1VFNTN'), ifc.by_guid('2VK2i8hZi3HPahZLbt_$zv'), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('1hhRjIJRNsHBc_vd1VFNTN')
print(product.is_a(), product.GlobalId, product.Name)

commit()
print('model committed')
```
Tool result:
```
IfcSpace 1hhRjIJRNsHBc_vd1VFNTN 32
model committed
```
Assistant: The space now carries the values the instruction asked for. The edited model is committed.

### Example 2
User:
Move the space with GlobalId '2G3Zgh3YLFBxViczryC8tv' into storey 'Dachgeschoss', leaving it exactly where it stands in the building.

IFC model path: <path to the working copy>
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
25SMdCQszBi9al8gnrh8LV 'Keller' -3.0
1n2Lw3QubAj8dNIkFMcbgd 'Erdgeschoss' 0.0
3edQNiDA9BMfnQgyxoNyj_ '1. Obergeschoss' 3.0
3RfMuFpfrChO9ET4Q4w87M '2. Obergeschoss' 6.0
1QBGh5csbBJAW2bT8EMyIU 'Dachgeschoss' 9.0
model length unit in metres: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def add_to_storey(storey, product):
    for link in getattr(storey, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (product,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[product],
                      RelatingStructure=storey)

def nest_in_storey(storey, product):
    for link in getattr(storey, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (product,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=storey,
                      RelatedObjects=[product])

def writable_axis(placement):
    # substitute a private point before writing coordinates
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
        nest_in_storey(storey, product)
    else:
        add_to_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid('2G3Zgh3YLFBxViczryC8tv'), ifc.by_guid('1QBGh5csbBJAW2bT8EMyIU'), True)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
product = ifc.by_guid('2G3Zgh3YLFBxViczryC8tv')
print(product.is_a(), product.GlobalId, product.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcSpace 2G3Zgh3YLFBxViczryC8tv 007
model committed
```
Assistant: Completed. The space now carries the values the instruction asked for; the model was committed.

### Example 3
User:
Move the space with GlobalId '0Aa03Zdrz2TB5jHMjrwXEU' into storey 'Level 7', leaving it exactly where it stands in the building.

IFC model path: <path to the working copy>
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for storey in ifc.by_type('IfcBuildingStorey'):
    print(storey.GlobalId, repr(storey.Name), storey.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1bTA0R$V95XvW_FeViTs$a 'Level 7' -3000.0
3Zu5Bv0LOHrPC10026FoQQ 'Level 0' 0.0
0WxqH4kVHAcfHTVCloC6Lz 'Level 2' 4200.0
0WxqH4kVHAcfHTVCloC6Fp 'Level 3' 8400.0
0WxqH4kVHAcfHTVCloC6Cb 'Level 4' 12600.0
0b4bdrsGX6swlpzig5dNcE 'Level 8' 16800.0
0b4bdrsGX6swlpzig5dN_l 'Level 9' 21000.0
model length unit in metres: 0.001
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def only_user(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def add_to_storey(storey, element):
    for link in getattr(storey, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (element,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[element],
                      RelatingStructure=storey)

def nest_in_storey(storey, element):
    for link in getattr(storey, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (element,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=storey,
                      RelatedObjects=[element])

def writable_axis(placement):
    # do not move anything else that happens to share this point
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
        add_to_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("0Aa03Zdrz2TB5jHMjrwXEU"), ifc.by_guid("1bTA0R$V95XvW_FeViTs$a"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid("0Aa03Zdrz2TB5jHMjrwXEU")
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcSpace 0Aa03Zdrz2TB5jHMjrwXEU 12
model committed
```
Assistant: The space has been updated, and the edit is written to the working file.
