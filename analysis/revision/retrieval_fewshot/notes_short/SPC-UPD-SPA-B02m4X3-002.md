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
Can you move the space nearest to the space named 'A201' on storey 'Level 2' into storey 'Level 1', leaving it exactly where it stands in the building, preserving all of its relationships?

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

# find the element closest to the one the instruction names
storey = by_name("IfcBuildingStorey", "Level 2")
reference = by_name("IfcSpace", "A201")
hits = [geom.find_nearest(reference, "IfcSpace",
                          storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 2' -> 0o8nNAbaT5OQLV8C9mNFlV IfcBuildingStorey Level 2
named 'A201' -> 0CRPz_SEr94Ah74P8LhwKv IfcSpace A201
1 match(es)
3YWx8nQAj0DhPfgLl9dDeU IfcSpace A201-M
```
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
0o8nNAbaT5OQLV8C9mLSZW 'Roof' 6.000000000000384
0o8nNAbaT5OQLV8C9mNFXU 'Level 1' 0.0
0o8nNAbaT5OQLV8C9mNFlV 'Level 2' 3.100000000000372
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

owner = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def contain_in_storey(storey, element):
    for link in getattr(storey, 'ContainsElements', None) or ():
        link.RelatedElements = (
            tuple(link.RelatedElements) + (element,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatedElements=[element],
                      RelatingStructure=storey)

def add_under_storey(storey, element):
    for link in getattr(storey, 'IsDecomposedBy', None) or ():
        if link.is_a('IfcRelAggregates'):
            link.RelatedObjects = (
                tuple(link.RelatedObjects) + (element,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=owner, Name=None, Description=None,
                      RelatingObject=storey,
                      RelatedObjects=[element])

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
        add_under_storey(storey, product)
    else:
        contain_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("3YWx8nQAj0DhPfgLl9dDeU"), ifc.by_guid("0o8nNAbaT5OQLV8C9mNFXU"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
element = ifc.by_guid("3YWx8nQAj0DhPfgLl9dDeU")
print(element.is_a(), element.GlobalId, element.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcSpace 3YWx8nQAj0DhPfgLl9dDeU A201-M
model committed
```
Assistant: The space now carries the values the instruction asked for, and the edit is written to the working file.

### Example 2
User:
Move the space nearest to the wall with ID 1DQjTWFWv4EhiD_wf1$CdU on storey '03 Second Floor' into storey '04 Third Floor', leaving it exactly where it stands in the building, preserving all of its relationships.

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

# find the element closest to the one the instruction names
storey = by_name('IfcBuildingStorey', '03 Second Floor')
reference = ifc.by_guid('1DQjTWFWv4EhiD_wf1$CdU')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
found = [geom.find_nearest(reference, 'IfcSpace',
                           storey)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '03 Second Floor' -> 0jlr3YnUH1mO0yDQYgS5ce IfcBuildingStorey 03 Second Floor
given -> 1DQjTWFWv4EhiD_wf1$CdU IfcWall Basic Wall:Exterior Walls:548054
1 match(es)
0wk6XWyTP2fhbsagQB1zsd IfcSpace 25
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
0jlr3YnUH1mO0yDQYgS5bd '00 Foundation Level' -1.99999999999965
1w2kgyXAD2C9c7QsT4npO9 '01 Ground Floor' 3.49539269960114e-13
1w2kgyXAD2C9c7QsT4npsv '02 First Floor' 4.09999999999966
0jlr3YnUH1mO0yDQYgS5ce '03 Second Floor' 8.19999999999965
0jlr3YnUH1mO0yDQYgS5cn '04 Third Floor' 12.2999999999997
0jlr3YnUH1mO0yDQYgS5cs '05 Fourth Floor Cafe & Restaurant' 16.3999999999997
0jlr3YnUH1mO0yDQYgS5P5 '06 Roof' 20.4999999999997
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def used_once(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def add_to_storey(level, target):
    for relation in getattr(level, 'ContainsElements', None) or ():
        relation.RelatedElements = (
            tuple(relation.RelatedElements) + (target,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[target],
                      RelatingStructure=level)

def aggregate_into_storey(level, target):
    for relation in getattr(level, 'IsDecomposedBy', None) or ():
        if relation.is_a('IfcRelAggregates'):
            relation.RelatedObjects = (
                tuple(relation.RelatedObjects) + (target,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=level,
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
        aggregate_into_storey(storey, product)
    else:
        add_to_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid('0wk6XWyTP2fhbsagQB1zsd'), ifc.by_guid('0jlr3YnUH1mO0yDQYgS5cn'), True)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
target = ifc.by_guid('0wk6XWyTP2fhbsagQB1zsd')
print(target.is_a(), target.GlobalId, target.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcSpace 0wk6XWyTP2fhbsagQB1zsd 25
model committed
```
Assistant: Completed. The space now carries the values the instruction asked for; the model was committed.

### Example 3
User:
Move the column nearest to the wall named 'Basic Wall:Concrete - 300mm:1518086' on storey 'GROUND FLOOR' into storey 'EVA 5.5mPD', leaving it exactly where it stands in the building, preserving all of its relationships.

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

# find the element closest to the one the instruction names
storey = by_name("IfcBuildingStorey", "GROUND FLOOR")
reference = by_name("IfcWall", "Basic Wall:Concrete - 300mm:1518086")
hits = [geom.find_nearest(reference, "IfcColumn",
                          storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'GROUND FLOOR' -> 2zLsHd4mf4JBb2o9C5Fx$o IfcBuildingStorey GROUND FLOOR
named 'Basic Wall:Concrete - 300mm:1518086' -> 2QF3$F$XHF1A$PuubJ8WX_ IfcWall Basic Wall:Concrete - 300mm:1518086
1 match(es)
2QF3$F$XHF1A$PuubJ8YOL IfcColumn M_Concrete-Rectangular-Column:500 x 600mm:1508461
```
Assistant: Next I need the elements that go with it.
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
2zLsHd4mf4JBb2o9C5C4lR 'Level 1' 0.0
2zLsHd4mf4JBb2o9C59qWi 'EXIT FLOOR (GRID 1A)' 800.0
2zLsHd4mf4JBb2o9C59qX8 'TBE ROOM FLOOR' 1200.0
2zLsHd4mf4JBb2o9C59qXF 'SERVER ROOM FLOOR' 1350.0
2zLsHd4mf4JBb2o9C59qeC 'E&M TRENCH' 1750.2
2zLsHd4mf4JBb2o9C59rj8 'EVA 5.1mPD' 1900.0
2zLsHd4mf4JBb2o9C59rjF 'EVA 5.5mPD' 2300.0
2zLsHd4mf4JBb2o9C59rj9 'EVA 6mPD' 2800.0
2zLsHd4mf4JBb2o9C59rjD 'EVA 6.5mPD' 3300.0
2zLsHd4mf4JBb2o9C59rjC 'EVA 6.65mPD' 3449.99999999965
2zLsHd4mf4JBb2o9C5Fx$o 'GROUND FLOOR' 3949.99999999953
2zLsHd4mf4JBb2o9C5C4XQ 'Level 2' 3999.99999999967
2zLsHd4mf4JBb2o9C59rjp 'EVA 7.5mPD' 4300.0
2zLsHd4mf4JBb2o9C58Ekc 'GROUND FLOOR CEILING' 6150.0
2zLsHd4mf4JBb2o9C58DSG 'GRID G' 6950.0
2zLsHd4mf4JBb2o9C59qwM 'LANDING (GRID A)' 7100.0
2zLsHd4mf4JBb2o9C59qwN 'GREEN ROOF (GRID A)' 7400.0
2zLsHd4mf4JBb2o9C59qwR 'CT PLANT RM FLOOR' 8725.0
2zLsHd4mf4JBb2o9C5FxpV 'MEZZANINE FLOOR' 8749.99999999953
2zLsHd4mf4JBb2o9C59hLH 'GRID N' 19999.9999999995
2zLsHd4mf4JBb2o9C59r7$ 'Upper Roof' 21000.0
model length unit in metres: 0.001
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement

history = min(ifc.by_type('IfcOwnerHistory'), key=lambda h: h.id(), default=None)

def is_sole_owner(item, owner):
    inverses = ifc.get_inverse(item)
    return len(inverses) == 1 and next(iter(inverses)) == owner

def put_in_storey(storey, target):
    for rel in getattr(storey, 'ContainsElements', None) or ():
        rel.RelatedElements = (
            tuple(rel.RelatedElements) + (target,))
        return
    ifc.create_entity('IfcRelContainedInSpatialStructure', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatedElements=[target],
                      RelatingStructure=storey)

def aggregate_into_storey(storey, target):
    for rel in getattr(storey, 'IsDecomposedBy', None) or ():
        if rel.is_a('IfcRelAggregates'):
            rel.RelatedObjects = (
                tuple(rel.RelatedObjects) + (target,))
            return
    ifc.create_entity('IfcRelAggregates', GlobalId=guid.new(),
                      OwnerHistory=history, Name=None, Description=None,
                      RelatingObject=storey,
                      RelatedObjects=[target])

def writable_axis(placement):
    # substitute a private point before writing coordinates
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
        aggregate_into_storey(storey, product)
    else:
        put_in_storey(storey, product)
    placement.PlacementRelTo = storey.ObjectPlacement
    if keep_world:
        write_world_frame(product, world)

move_into_storey(ifc.by_guid("2QF3$F$XHF1A$PuubJ8YOL"), ifc.by_guid("2zLsHd4mf4JBb2o9C59rjF"), True)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid("2QF3$F$XHF1A$PuubJ8YOL")
print(target.is_a(), target.GlobalId, target.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcColumn 2QF3$F$XHF1A$PuubJ8YOL M_Concrete-Rectangular-Column:500 x 600mm:1508461
model committed
```
Assistant: Done. The column has been updated, and the model has been saved.
