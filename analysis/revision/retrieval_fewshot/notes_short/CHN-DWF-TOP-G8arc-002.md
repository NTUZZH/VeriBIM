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
Take out the 8 doors hosted in the wall in which the door with ID 0hnFKA8$L9uxjrPSl0gsqB is located, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid("0hnFKA8$L9uxjrPSl0gsqB")
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
found = [geom.find_host(named_element)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
given -> 0hnFKA8$L9uxjrPSl0gsqB IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407204
[('1bvoLaxGX6CP5pWWaTsQAj', 'IfcWall', 'Basic Wall:Generic - 8":402716')]
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("1bvoLaxGX6CP5pWWaTsQAj")
for relation in getattr(host, 'HasOpenings', None) or ():
    void = relation.RelatedOpeningElement
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
0hnFKA8$L9uxjrPSl0gsqB IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407204 in opening 2dVlcOHx5q8ebpJi3CNfT9
0hnFKA8$L9uxjrPSl0gsqC IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407203 in opening 2vqEHlQSUN$koa_Zii63tE
0hnFKA8$L9uxjrPSl0gsqD IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407202 in opening 3ks2tH_dCzPQtw1meUn6ls
0hnFKA8$L9uxjrPSl0gsq8 IfcDoor Door-Passage-Uneven-Flush:54'' x 80'':407207 in opening 2s67k2$0RJq652nALsJYOM
0hnFKA8$L9uxjrPSl0gsq9 IfcDoor Door-Passage-Uneven-Flush:54'' x 80'':407206 in opening 3WoiyjNB0MI5xucCHS8xE8
0hnFKA8$L9uxjrPSl0gsqA IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407205 in opening 3QMty1wclbShz758TcS756
0hnFKA8$L9uxjrPSl0gsq6 IfcDoor Door-Passage-Single-Vision_Lite:Door-Passage-Single-Vision_Lite:407209 in opening 3QmXp7LAotK1O2q_NOBL_I
0hnFKA8$L9uxjrPSl0gsq7 IfcDoor Door-Passage-Uneven-Flush:54'' x 80'':407208 in opening 0jmiqv$1eYjZrK$7DZaDDT
```
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsq6"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsq7"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsq8"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsq9"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsqA"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsqB"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsqC"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0hnFKA8$L9uxjrPSl0gsqD"))
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid("1bvoLaxGX6CP5pWWaTsQAj"))
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
print('still present:', [g for g in ("0hnFKA8$L9uxjrPSl0gsq6", "0hnFKA8$L9uxjrPSl0gsq7", "0hnFKA8$L9uxjrPSl0gsq8", "0hnFKA8$L9uxjrPSl0gsq9", "0hnFKA8$L9uxjrPSl0gsqA", "0hnFKA8$L9uxjrPSl0gsqB", "0hnFKA8$L9uxjrPSl0gsqC", "0hnFKA8$L9uxjrPSl0gsqD", "1bvoLaxGX6CP5pWWaTsQAj") if g in present])

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The wall and the relationships that depended on it are gone; the model was committed.

### Example 2
User:
Can you take out the 2 doors hosted in the wall in which the door named 'WC Door:810x2110mm:1104659' is located, then remove the wall itself along with the openings they filled?

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

named_element = by_name('IfcDoor', 'WC Door:810x2110mm:1104659')
found = [geom.find_host(named_element)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'WC Door:810x2110mm:1104659' -> 1yjOWDCLLAXAqWZVbjDy5h IfcDoor WC Door:810x2110mm:1104659
1 match(es)
0h4ACd_aHBKAb7DCOi73Fr IfcWall Basic Wall:Gypsum Wall:1074825
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('0h4ACd_aHBKAb7DCOi73Fr')
for link in getattr(host, 'HasOpenings', None) or ():
    hole = link.RelatedOpeningElement
    if hole is None:
        continue
    for fills in getattr(hole, 'HasFillings', None) or ():
        unit = fills.RelatedBuildingElement
        if unit is None:
            continue
        print(unit.GlobalId, unit.is_a(), unit.Name, 'in opening', hole.GlobalId)
```
Tool result:
```
1yjOWDCLLAXAqWZVbjDy5h IfcDoor WC Door:810x2110mm:1104659 in opening 09vH_VDiVULuoMMaOvAcTb
1yjOWDCLLAXAqWZVbjDy7k IfcDoor WC Door:810x2110mm:1104790 in opening 24EWar2pR1vXhRKUNVa$5l
```
Assistant tool call execute_ifc_code:
```python
geom.delete_filling(ifc.by_guid('1yjOWDCLLAXAqWZVbjDy5h'))
geom.delete_filling(ifc.by_guid('1yjOWDCLLAXAqWZVbjDy7k'))
geom.delete_element(ifc.by_guid('0h4ACd_aHBKAb7DCOi73Fr'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('1yjOWDCLLAXAqWZVbjDy5h', '1yjOWDCLLAXAqWZVbjDy7k', '0h4ACd_aHBKAb7DCOi73Fr') if g in present])

commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall has been removed, and the edit is written to the working file.

### Example 3
User:
Take out the 3 doors hosted in the wall in which the door named 'M_Door-Passage-Single-Flush:750 x 2000mm:404539' is located, then remove the wall itself along with the openings they filled.

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

# follow the named door or window to the wall it sits in
named_element = by_name("IfcDoor", "M_Door-Passage-Single-Flush:750 x 2000mm:404539")
matches = [geom.find_host(named_element)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
named 'M_Door-Passage-Single-Flush:750 x 2000mm:404539' -> 0fuQ8eSiP6TxCwQVIrFfAC IfcDoor M_Door-Passage-Single-Flush:750 x 2000mm:404539
[('0fuQ8eSiP6TxCwQVIrFfA2', 'IfcWallStandardCase', 'Basic Wall:Interior Wall - Blockwork 100:404533')]
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("0fuQ8eSiP6TxCwQVIrFfA2")
for rel in getattr(host, 'HasOpenings', None) or ():
    hole = rel.RelatedOpeningElement
    if hole is None:
        continue
    for fills in getattr(hole, 'HasFillings', None) or ():
        leaf = fills.RelatedBuildingElement
        if leaf is None:
            continue
        print(leaf.GlobalId, leaf.is_a(), leaf.Name, 'in opening', hole.GlobalId)
```
Tool result:
```
0fuQ8eSiP6TxCwQVIrFfAE IfcDoor M_Door-Passage-Single-Flush:750 x 2000mm:404537 in opening 0$sSR2jKc3MgxVkGX_JOMH
0fuQ8eSiP6TxCwQVIrFfAD IfcDoor M_Door-Passage-Single-Flush:750 x 2000mm:404538 in opening 2xcbrpim7GenYAthJcEsUC
0fuQ8eSiP6TxCwQVIrFfAC IfcDoor M_Door-Passage-Single-Flush:750 x 2000mm:404539 in opening 1VlL1wL7lkk1XfoxJR_Wyi
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0fuQ8eSiP6TxCwQVIrFfAC"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0fuQ8eSiP6TxCwQVIrFfAD"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("0fuQ8eSiP6TxCwQVIrFfAE"))
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid("0fuQ8eSiP6TxCwQVIrFfA2"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("0fuQ8eSiP6TxCwQVIrFfAC", "0fuQ8eSiP6TxCwQVIrFfAD", "0fuQ8eSiP6TxCwQVIrFfAE", "0fuQ8eSiP6TxCwQVIrFfA2") if g in present])

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall has been removed, and the edit is written to the working file.
