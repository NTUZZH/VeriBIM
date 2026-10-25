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
Remove the 2 windows hosted in the wall window 3E7aVzLr12sRNvTL1BNfoA sits in, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid("3E7aVzLr12sRNvTL1BNfoA")
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
matches = [geom.find_host(named_element)]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3E7aVzLr12sRNvTL1BNfoA IfcWindow Windows_Sgl_Plain:1360x1210mm:867720
1 match(es)
1I3LAMqkj0FODaeJrwSAgV IfcWall Basic Wall:MW 24cm:410642
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("1I3LAMqkj0FODaeJrwSAgV")
for link in getattr(host, 'HasOpenings', None) or ():
    void = link.RelatedOpeningElement
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
3E7aVzLr12sRNvTL1BNfoA IfcWindow Windows_Sgl_Plain:1360x1210mm:867720 in opening 3l6P962XObEkWTaQbrFSqS
3E7aVzLr12sRNvTL1BNfnm IfcWindow Windows_Sgl_Plain:1360x1210mm:867698 in opening 1SYEW5CFvrnzjUIF$Wff6f
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("3E7aVzLr12sRNvTL1BNfnm"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("3E7aVzLr12sRNvTL1BNfoA"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_element(ifc.by_guid("1I3LAMqkj0FODaeJrwSAgV"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("3E7aVzLr12sRNvTL1BNfnm", "3E7aVzLr12sRNvTL1BNfoA", "1I3LAMqkj0FODaeJrwSAgV") if g in present])

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: The wall and the relationships that depended on it are gone. The edited model is committed.

### Example 2
User:
Remove the 7 windows hosted in the wall window 0kZLaNcp14RBDtO8Gi82lt sits in, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid("0kZLaNcp14RBDtO8Gi82lt")
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
hits = [geom.find_host(named_element)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 0kZLaNcp14RBDtO8Gi82lt IfcWindow Instance - Fixed:0915 x 1830mm:458662
3T5CXa9sj8mA4QzMxcTppu IfcWall Basic Wall:Wall-Ext_200 concrete:328307
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("3T5CXa9sj8mA4QzMxcTppu")
for rel in getattr(host, 'HasOpenings', None) or ():
    void = rel.RelatedOpeningElement
    if void is None:
        continue
    for fills in getattr(void, 'HasFillings', None) or ():
        leaf = fills.RelatedBuildingElement
        if leaf is None:
            continue
        print(leaf.GlobalId, leaf.is_a(), leaf.Name, 'in opening', void.GlobalId)
```
Tool result:
```
0kZLaNcp14RBDtO8Gi82lw IfcWindow Instance - Fixed:0915 x 1830mm:458667 in opening 09VByAE9LVCeBRr$LnjZZY
0kZLaNcp14RBDtO8Gi82lX IfcWindow Instance - Fixed:0915 x 1830mm:458672 in opening 2EABijGYwWWr3N$_XLzGby
0kZLaNcp14RBDtO8Gi82ls IfcWindow Instance - Fixed:0915 x 1830mm:458663 in opening 3yX$5K8sZ0j$OB5ODhQyGs
0kZLaNcp14RBDtO8Gi82lv IfcWindow Instance - Fixed:0915 x 1830mm:458664 in opening 1CR$Jo2OV33S9aj2xfym3r
0kZLaNcp14RBDtO8Gi82lu IfcWindow Instance - Fixed:0915 x 1830mm:458665 in opening 0wITitYFnwbZDB6pPSD0sG
0kZLaNcp14RBDtO8Gi82lx IfcWindow Instance - Fixed:0915 x 1830mm:458666 in opening 3F8V$YUC3cZeVXueAjX_aK
0kZLaNcp14RBDtO8Gi82lt IfcWindow Instance - Fixed:0915 x 1830mm:458662 in opening 3T_IKZP5GchdmiVlRMHTGB
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lX"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82ls"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lt"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lu"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lv"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lw"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_filling(ifc.by_guid("0kZLaNcp14RBDtO8Gi82lx"))
# remove the element; a door or a window it holds cannot stay without it
geom.delete_element(ifc.by_guid("3T5CXa9sj8mA4QzMxcTppu"))
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
print('still present:', [g for g in ("0kZLaNcp14RBDtO8Gi82lX", "0kZLaNcp14RBDtO8Gi82ls", "0kZLaNcp14RBDtO8Gi82lt", "0kZLaNcp14RBDtO8Gi82lu", "0kZLaNcp14RBDtO8Gi82lv", "0kZLaNcp14RBDtO8Gi82lw", "0kZLaNcp14RBDtO8Gi82lx", "3T5CXa9sj8mA4QzMxcTppu") if g in present])

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
Remove the 9 windows hosted in the wall window 3MA2RcOF50Gv9gedvfTOtR sits in, then remove the wall itself along with the openings they filled.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# follow the named door or window to the wall it sits in
named_element = ifc.by_guid("3MA2RcOF50Gv9gedvfTOtR")
print('given ->', named_element.GlobalId, named_element.is_a(), named_element.Name)
found = [geom.find_host(named_element)]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3MA2RcOF50Gv9gedvfTOtR IfcWindow Window-Double-Hung:26" x 42":387241
3MA2RcOF50Gv9gedvfTOqR IfcWall Basic Wall:Generic - 12":387177
```
Assistant tool call execute_ifc_code:
```python
# what the wall hosts, through the openings cut in it
host = ifc.by_guid("3MA2RcOF50Gv9gedvfTOqR")
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
3MA2RcOF50Gv9gedvfTOtF IfcWindow Window-Sliding-Double:60" x 48":387261 in opening 3YeaCXg46OFXV$eeW1_it1
3MA2RcOF50Gv9gedvfTOsm IfcWindow Window-Sliding-Double:60" x 48":387266 in opening 0zuQHbeek95XQ5zUOZ1I2r
3MA2RcOF50Gv9gedvfTOtS IfcWindow Window-Double-Hung:26" x 42":387246 in opening 3hHTUxbiX9ZsVmpTijn8JG
3MA2RcOF50Gv9gedvfTOt1 IfcWindow Window-Sliding-Double:60" x 48":387251 in opening 3_muSa$YQ4ZNuj7Snhfivl
3MA2RcOF50Gv9gedvfTOtA IfcWindow Window-Sliding-Double:60" x 48":387256 in opening 0_kMMZ8pOpByhEqyKuJpVO
3MA2RcOF50Gv9gedvfTOte IfcWindow Window-Double-Hung:26" x 42":387226 in opening 16PoEEA88m_xUR_lOiCj6b
3MA2RcOF50Gv9gedvfTOtj IfcWindow Window-Double-Hung:26" x 42":387231 in opening 0CcRabKZEQyFcqFGQe4dwC
3MA2RcOF50Gv9gedvfTOtM IfcWindow Window-Double-Hung:26" x 42":387236 in opening 0L7sglg1A7UByyrxAYoQgA
3MA2RcOF50Gv9gedvfTOtR IfcWindow Window-Double-Hung:26" x 42":387241 in opening 0Vi3fTabIHGpSEjfeACd25
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOsm"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOt1"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtA"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtF"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtM"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtR"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtS"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOte"))
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid("3MA2RcOF50Gv9gedvfTOtj"))
# drop the element together with its placement, geometry and relations
geom.delete_element(ifc.by_guid("3MA2RcOF50Gv9gedvfTOqR"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("3MA2RcOF50Gv9gedvfTOsm", "3MA2RcOF50Gv9gedvfTOt1", "3MA2RcOF50Gv9gedvfTOtA", "3MA2RcOF50Gv9gedvfTOtF", "3MA2RcOF50Gv9gedvfTOtM", "3MA2RcOF50Gv9gedvfTOtR", "3MA2RcOF50Gv9gedvfTOtS", "3MA2RcOF50Gv9gedvfTOte", "3MA2RcOF50Gv9gedvfTOtj", "3MA2RcOF50Gv9gedvfTOqR") if g in present])

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The wall has been removed; the model was committed.
