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
Please set the fire rating of the IfcWall on storey 'Level 3' that stands about 3.9 m east (+X) of the wall 2_RelSlDf0GhV3YJCmbvpY in Pset_WallCommon to 'F120', preserving all of its relationships.

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
storey = by_name("IfcBuildingStorey", "Level 3")
reference = ifc.by_guid("2_RelSlDf0GhV3YJCmbvpY")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
matches = [geom.find_offset(reference, "IfcWall", storey,
                            "east", 3.9)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
named 'Level 3' -> 2qYKvFEvH4cPghyPNWjrjp IfcBuildingStorey Level 3
given -> 2_RelSlDf0GhV3YJCmbvpY IfcWall Basic Wall:Interior Partition Walls - 138mm:537919
[('2_RelSlDf0GhV3YJCmc5zZ', 'IfcWall', 'Basic Wall:Exterior Wall (Non Load Bearing) - 200mm 2:521918')]
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# the value goes into the named property set on this element
geom.set_property(ifc.by_guid("2_RelSlDf0GhV3YJCmc5zZ"), "Pset_WallCommon",
                  "FireRating", "F120")
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
target = ifc.by_guid("2_RelSlDf0GhV3YJCmc5zZ")
print(target.is_a(), target.GlobalId, target.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcWall 2_RelSlDf0GhV3YJCmc5zZ Basic Wall:Exterior Wall (Non Load Bearing) - 200mm 2:521918
model committed
```
Assistant: Finished: the wall has been updated. The file on disk now holds the change.

### Example 2
User:
Change the fire rating of the wall with GlobalId '2TAW5Oww6HIRfFhZcDemkf' in Pset_WallCommon to 'F90', preserving all of its relationships.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
matches = [ifc.by_guid('2TAW5Oww6HIRfFhZcDemkf')]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2TAW5Oww6HIRfFhZcDemkf IfcWall SW - 005
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
geom.set_property(ifc.by_guid('2TAW5Oww6HIRfFhZcDemkf'), 'Pset_WallCommon',
                  'FireRating', 'F90')
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid('2TAW5Oww6HIRfFhZcDemkf')
print(target.is_a(), target.GlobalId, target.Name)

commit()
print('model committed')
```
Tool result:
```
IfcWall 2TAW5Oww6HIRfFhZcDemkf SW - 005
model committed
```
Assistant: The wall has been updated, and the edit is written to the working file.

### Example 3
User:
Change the load-bearing flag of the IfcWall on storey 'FIRST FLOOR' that hosts no door and no window in Pset_WallCommon from false to true, preserving all of its relationships.

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

# find the element that carries none of what the instruction excludes
storey = by_name('IfcBuildingStorey', 'FIRST FLOOR')
matches = [geom.find_without(storey, 'IfcWall',
                             ('IfcDoor', 'IfcWindow'))]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
named 'FIRST FLOOR' -> 0xQp_ltlz1BBUU3QIJQ3ZK IfcBuildingStorey FIRST FLOOR
[('2v8ISQu19FNPb2D1hUoQQA', 'IfcWallStandardCase', 'Basic Wall:Plywood:30143653')]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# write the value into the property set the instruction names
geom.set_property(ifc.by_guid('2v8ISQu19FNPb2D1hUoQQA'), 'Pset_WallCommon',
                  'LoadBearing', True)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
target = ifc.by_guid('2v8ISQu19FNPb2D1hUoQQA')
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcWallStandardCase 2v8ISQu19FNPb2D1hUoQQA Basic Wall:Plywood:30143653
model committed
```
Assistant: Finished: the wall now carries the values the instruction asked for. The file on disk now holds the change.
