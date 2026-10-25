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
Can you remove the door hosted in the wall on the left-hand side as seen from the door with GlobalId '1hOSvn6df7F8_7GcBWlSDm' looking into the space with GlobalId '0BTBFw6f90Nfh9rP1dlXri', then remove the wall itself along with the opening it filled?

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element on the named side, seen through the door
space = ifc.by_guid('0BTBFw6f90Nfh9rP1dlXri')
print('given ->', space.GlobalId, space.is_a(), space.Name)
door = ifc.by_guid('1hOSvn6df7F8_7GcBWlSDm')
print('given ->', door.GlobalId, door.is_a(), door.Name)
found = [geom.find_beside_door(door, space,
                               'left', 'IfcWall')]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 0BTBFw6f90Nfh9rP1dlXri IfcSpace A201
given -> 1hOSvn6df7F8_7GcBWlSDm IfcDoor M_Single-Flush:0864 x 2032mm:0864 x 2032mm:150478
2O2Fr$t4X7Zf8NOew3FL9r IfcWallStandardCase Basic Wall:Interior - Partition (92mm Stud):144586
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FL9r')
for rel in getattr(host, 'HasOpenings', None) or ():
    opening = rel.RelatedOpeningElement
    if opening is None:
        continue
    for fills in getattr(opening, 'HasFillings', None) or ():
        leaf = fills.RelatedBuildingElement
        if leaf is None:
            continue
        print(leaf.GlobalId, leaf.is_a(), leaf.Name, 'in opening', opening.GlobalId)
```
Tool result:
```
2OBrcmyk58NupXoVOHUvPL IfcDoor M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208 in opening 1xS3BCk291UvhgP2dvNnNr
```
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid('2OBrcmyk58NupXoVOHUvPL'))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_element(ifc.by_guid('2O2Fr$t4X7Zf8NOew3FL9r'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('2OBrcmyk58NupXoVOHUvPL', '2O2Fr$t4X7Zf8NOew3FL9r') if g in present])

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall and the relationships that depended on it are gone, and the edit is written to the working file.

### Example 2
User:
Remove the window hosted in the wall on the left-hand side as seen from the door with GlobalId '2k6vBG3yn9hRJUYx$GK5vo' looking into the space with GlobalId '3$FatfHY1Cg9apAMwbKPN8', then remove the wall itself along with the opening it filled.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element on the named side, seen through the door
space = ifc.by_guid("3$FatfHY1Cg9apAMwbKPN8")
print('given ->', space.GlobalId, space.is_a(), space.Name)
door = ifc.by_guid("2k6vBG3yn9hRJUYx$GK5vo")
print('given ->', door.GlobalId, door.is_a(), door.Name)
matches = [geom.find_beside_door(door, space,
                                 "left", "IfcWall")]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3$FatfHY1Cg9apAMwbKPN8 IfcSpace 106
given -> 2k6vBG3yn9hRJUYx$GK5vo IfcDoor Tür-007
1urUcYP71DIf1u38ogU1RV IfcWallStandardCase Wand-007
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("1urUcYP71DIf1u38ogU1RV")
for rel in getattr(host, 'HasOpenings', None) or ():
    void = rel.RelatedOpeningElement
    if void is None:
        continue
    for fills in getattr(void, 'HasFillings', None) or ():
        unit = fills.RelatedBuildingElement
        if unit is None:
            continue
        print(unit.GlobalId, unit.is_a(), unit.Name, 'in opening', void.GlobalId)
```
Tool result:
```
0HtsZ3YcbDMwJN3vvrSgK9 IfcWindow Fenster-008 in opening 0QJo_j0hP1zhBli49JWKDP
```
Assistant tool call execute_ifc_code:
```python
# delete the element, its openings and whatever those openings hold
geom.delete_filling(ifc.by_guid("0HtsZ3YcbDMwJN3vvrSgK9"))
# delete the element, its openings and whatever those openings hold
geom.delete_element(ifc.by_guid("1urUcYP71DIf1u38ogU1RV"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("0HtsZ3YcbDMwJN3vvrSgK9", "1urUcYP71DIf1u38ogU1RV") if g in present])

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Done. The wall and the relationships that depended on it are gone, and the model has been saved.

### Example 3
User:
Remove the door hosted in the wall on the left-hand side as seen from the door named 'M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208' looking into the space 'A201', then remove the wall itself along with the opening it filled.

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

# find the element on the named side, seen through the door
space = by_name('IfcSpace', 'A201')
door = by_name('IfcDoor', 'M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208')
matches = [geom.find_beside_door(door, space,
                                 'left', 'IfcWall')]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'A201' -> 0BTBFw6f90Nfh9rP1dlXri IfcSpace A201
named 'M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208' -> 2OBrcmyk58NupXoVOHUvPL IfcDoor M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208
2O2Fr$t4X7Zf8NOew3FL96 IfcWallStandardCase Basic Wall:Interior - Partition (92mm Stud):144633
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FL96')
for relation in getattr(host, 'HasOpenings', None) or ():
    opening = relation.RelatedOpeningElement
    if opening is None:
        continue
    for fills in getattr(opening, 'HasFillings', None) or ():
        leaf = fills.RelatedBuildingElement
        if leaf is None:
            continue
        print(leaf.GlobalId, leaf.is_a(), leaf.Name, 'in opening', opening.GlobalId)
```
Tool result:
```
2OBrcmyk58NupXoVOHUvVV IfcDoor M_Single-Flush:0864 x 2032mm:0864 x 2032mm:159834 in opening 1xS3BCk291UvhgP2dvNnH$
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid('2OBrcmyk58NupXoVOHUvVV'))
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid('2O2Fr$t4X7Zf8NOew3FL96'))
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
print('still present:', [g for g in ('2OBrcmyk58NupXoVOHUvVV', '2O2Fr$t4X7Zf8NOew3FL96') if g in present])

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall and the relationships that depended on it are gone. The edited model is committed.
