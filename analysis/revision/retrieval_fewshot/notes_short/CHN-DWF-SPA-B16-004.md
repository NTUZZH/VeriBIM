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
Remove the 3 doors hosted in the wall on storey 'FLOOR 2' directly above the wall named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:762649', then remove the wall itself along with the openings they filled.

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

# find the element directly over or under the named one
storey = by_name("IfcBuildingStorey", "FLOOR 2")
reference = by_name("IfcWall", 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:762649')
hits = [geom.find_above_below(reference, "IfcWall",
                              "above", storey=storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'FLOOR 2' -> 00Anm4s4r7luYkA9gSCCC_ IfcBuildingStorey FLOOR 2
named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:762649' -> 141UzFEpPAiBNNDMW3_Zd_ IfcWallStandardCase Basic Wall:Interior - 4 7/8" Partition TYPE 3:762649
1 match(es)
06Bn2yUMH0p8373E1g6SFM IfcWallStandardCase Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("06Bn2yUMH0p8373E1g6SFM")
for link in getattr(host, 'HasOpenings', None) or ():
    opening = link.RelatedOpeningElement
    if opening is None:
        continue
    for fills in getattr(opening, 'HasFillings', None) or ():
        unit = fills.RelatedBuildingElement
        if unit is None:
            continue
        print(unit.GlobalId, unit.is_a(), unit.Name, 'in opening', opening.GlobalId)
```
Tool result:
```
06Bn2yUMH0p8373E1g6SEg IfcDoor Double-Flush:72" x 84":780354 in opening 06Bn2yUMH0p8373FDg6SEg
06Bn2yUMH0p8373E1g6SEi IfcDoor Double-Flush:72" x 84":780356 in opening 06Bn2yUMH0p8373FDg6SEi
06Bn2yUMH0p8373E1g6SEk IfcDoor Double-Flush:72" x 84":780358 in opening 06Bn2yUMH0p8373FDg6SEk
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6SEg"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6SEi"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6SEk"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_element(ifc.by_guid("06Bn2yUMH0p8373E1g6SFM"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("06Bn2yUMH0p8373E1g6SEg", "06Bn2yUMH0p8373E1g6SEi", "06Bn2yUMH0p8373E1g6SEk", "06Bn2yUMH0p8373E1g6SFM") if g in present])

# save the edit
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The wall has been removed; the model was committed.

### Example 2
User:
Remove the 3 doors hosted in the wall on storey 'FLOOR 3' directly above the wall named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350', then remove the wall itself along with the openings they filled.

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

# find the element directly over or under the named one
storey = by_name("IfcBuildingStorey", "FLOOR 3")
reference = by_name("IfcWall", 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350')
found = [geom.find_above_below(reference, "IfcWall",
                               "above", storey=storey)]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'FLOOR 3' -> 00Anm4s4r7luYkA9gSEr4H IfcBuildingStorey FLOOR 3
named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350' -> 06Bn2yUMH0p8373E1g6SFM IfcWallStandardCase Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350
06Bn2yUMH0p8373E1g6TgV IfcWallStandardCase Basic Wall:Interior - 4 7/8" Partition TYPE 3:782711
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("06Bn2yUMH0p8373E1g6TgV")
for rel in getattr(host, 'HasOpenings', None) or ():
    void = rel.RelatedOpeningElement
    if void is None:
        continue
    for fills in getattr(void, 'HasFillings', None) or ():
        filling = fills.RelatedBuildingElement
        if filling is None:
            continue
        print(filling.GlobalId, filling.is_a(), filling.Name, 'in opening', void.GlobalId)
```
Tool result:
```
06Bn2yUMH0p8373E1g6TgJ IfcDoor Double-Flush:72" x 84":782715 in opening 06Bn2yUMH0p8373FDg6TgJ
06Bn2yUMH0p8373E1g6TgL IfcDoor Double-Flush:72" x 84":782717 in opening 06Bn2yUMH0p8373FDg6TgL
06Bn2yUMH0p8373E1g6TgN IfcDoor Double-Flush:72" x 84":782719 in opening 06Bn2yUMH0p8373FDg6TgN
```
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6TgJ"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6TgL"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("06Bn2yUMH0p8373E1g6TgN"))
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid("06Bn2yUMH0p8373E1g6TgV"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("06Bn2yUMH0p8373E1g6TgJ", "06Bn2yUMH0p8373E1g6TgL", "06Bn2yUMH0p8373E1g6TgN", "06Bn2yUMH0p8373E1g6TgV") if g in present])

# save the edit
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall has been removed, and the edit is written to the working file.

### Example 3
User:
Please remove the 3 doors hosted in the wall on storey 'FLOOR 3' directly above the wall named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350', then remove the wall itself along with the openings they filled.

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

# find the element directly over or under the named one
storey = by_name('IfcBuildingStorey', 'FLOOR 3')
reference = by_name('IfcWall', 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350')
matches = [geom.find_above_below(reference, 'IfcWall',
                                 'above', storey=storey)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'FLOOR 3' -> 00Anm4s4r7luYkA9gSEr4H IfcBuildingStorey FLOOR 3
named 'Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350' -> 06Bn2yUMH0p8373E1g6SFM IfcWall Basic Wall:Interior - 4 7/8" Partition TYPE 3:780350
1 match(es)
06Bn2yUMH0p8373E1g6TgV IfcWall Basic Wall:Interior - 4 7/8" Partition TYPE 3:782711
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid('06Bn2yUMH0p8373E1g6TgV')
for relation in getattr(host, 'HasOpenings', None) or ():
    opening = relation.RelatedOpeningElement
    if opening is None:
        continue
    for fills in getattr(opening, 'HasFillings', None) or ():
        filling = fills.RelatedBuildingElement
        if filling is None:
            continue
        print(filling.GlobalId, filling.is_a(), filling.Name, 'in opening', opening.GlobalId)
```
Tool result:
```
06Bn2yUMH0p8373E1g6TgJ IfcDoor Double-Flush:72" x 84":782715 in opening 06Bn2yUMH0p8373FDg6TgJ
06Bn2yUMH0p8373E1g6TgL IfcDoor Double-Flush:72" x 84":782717 in opening 06Bn2yUMH0p8373FDg6TgL
06Bn2yUMH0p8373E1g6TgN IfcDoor Double-Flush:72" x 84":782719 in opening 06Bn2yUMH0p8373FDg6TgN
```
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid('06Bn2yUMH0p8373E1g6TgJ'))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid('06Bn2yUMH0p8373E1g6TgL'))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid('06Bn2yUMH0p8373E1g6TgN'))
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid('06Bn2yUMH0p8373E1g6TgV'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('06Bn2yUMH0p8373E1g6TgJ', '06Bn2yUMH0p8373E1g6TgL', '06Bn2yUMH0p8373E1g6TgN', '06Bn2yUMH0p8373E1g6TgV') if g in present])

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The wall has been removed; the model was committed.
