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

### Example 2
User:
Take out the 4 doors hosted in the wall in which the door with GlobalId '2$Y$HcaijASBp8KdPwKO0F' is located, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
named_element = ifc.by_guid('2$Y$HcaijASBp8KdPwKO0F')
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
hits = [geom.find_host(named_element)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
given -> 2$Y$HcaijASBp8KdPwKO0F IfcDoor Doors_ExtDbl_w-Glazing_Bars_1:1510x2110mm:344151
[('1BjFtlYiH1ZenJIB15ltu0', 'IfcWall', 'Basic Wall:Wall-Ext_215Bwk Internal:360036')]
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('1BjFtlYiH1ZenJIB15ltu0')
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
2$Y$HcaijASBp8KdPwKO3h IfcDoor Doors_ExtDbl_w-Glazing_Bars_1:1510x2110mm:344243 in opening 1ScjYtnu8HfGEjfe7Ptjo7
2$Y$HcaijASBp8KdPwKO37 IfcDoor Doors_ExtDbl_w-Glazing_Bars_1:1510x2110mm:344223 in opening 0HDZc09qs81YGpJqnCGQoo
2$Y$HcaijASBp8KdPwKO3n IfcDoor Doors_ExtDbl_w-Glazing_Bars_1:1510x2110mm:344233 in opening 2krsBHNrWJr71iHV8FQff2
2$Y$HcaijASBp8KdPwKO0F IfcDoor Doors_ExtDbl_w-Glazing_Bars_1:1510x2110mm:344151 in opening 2tL9$Kwvl0uneN3jTu9UXG
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
geom.delete_filling(ifc.by_guid('2$Y$HcaijASBp8KdPwKO0F'))
geom.delete_filling(ifc.by_guid('2$Y$HcaijASBp8KdPwKO37'))
geom.delete_filling(ifc.by_guid('2$Y$HcaijASBp8KdPwKO3h'))
geom.delete_filling(ifc.by_guid('2$Y$HcaijASBp8KdPwKO3n'))
geom.delete_element(ifc.by_guid('1BjFtlYiH1ZenJIB15ltu0'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('2$Y$HcaijASBp8KdPwKO0F', '2$Y$HcaijASBp8KdPwKO37', '2$Y$HcaijASBp8KdPwKO3h', '2$Y$HcaijASBp8KdPwKO3n', '1BjFtlYiH1ZenJIB15ltu0') if g in present])

commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the wall and the relationships that depended on it are gone. The file on disk now holds the change.

### Example 3
User:
Take out the 3 doors hosted in the wall in which the door with GlobalId '33KXaNcZH3Fu5846$5aPGK' is located, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid("33KXaNcZH3Fu5846$5aPGK")
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
hits = [geom.find_host(named_element)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 33KXaNcZH3Fu5846$5aPGK IfcDoor Door-Passage-Single-Two_Lite_Narrow:36" x 96":399051
1 match(es)
33KXaNcZH3Fu5846$5aPGO IfcWallStandardCase Basic Wall:Interior - 79mm Partition (1-hr):399047
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("33KXaNcZH3Fu5846$5aPGO")
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
33KXaNcZH3Fu5846$5aPGL IfcDoor Door-Passage-Single-Two_Lite_Narrow:36" x 96":399050 in opening 33KXaNcZH3Fu5847p5aPGL
33KXaNcZH3Fu5846$5aPGK IfcDoor Door-Passage-Single-Two_Lite_Narrow:36" x 96":399051 in opening 33KXaNcZH3Fu5847p5aPGK
33KXaNcZH3Fu5846$5aPGJ IfcDoor Door-Passage-Single-Two_Lite_Narrow:36" x 96":399052 in opening 33KXaNcZH3Fu5847p5aPGJ
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("33KXaNcZH3Fu5846$5aPGJ"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("33KXaNcZH3Fu5846$5aPGK"))
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid("33KXaNcZH3Fu5846$5aPGL"))
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid("33KXaNcZH3Fu5846$5aPGO"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("33KXaNcZH3Fu5846$5aPGJ", "33KXaNcZH3Fu5846$5aPGK", "33KXaNcZH3Fu5846$5aPGL", "33KXaNcZH3Fu5846$5aPGO") if g in present])

# save the edit
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the wall has been removed. The file on disk now holds the change.
