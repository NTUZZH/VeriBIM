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
Assign the wall with GlobalId 3iM76qwej9Tf9ttHcbQrYo to the type object named 'Basic Wall:Foundation - 300mm Concrete - Retaining', preserving all of its relationships.

IFC model path: <path to the working copy>
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
options = []
for ifc_class in ('IfcWallType', 'IfcTypeProduct'):
    try:
        options = list(ifc.by_type(ifc_class))
    except Exception:
        options = []
    if options:
        break
for element in sorted(options, key=lambda t: (t.Name or '')):
    print(element.GlobalId, element.is_a(), element.Name)
```
Tool result:
```
0nLMa_hqjDM9PNHQIvZ_Vd IfcWallType Basic Wall:Foundation - 200mm Concrete - Retaining
0nLMa_hqjDM9PNHQIvZ_DK IfcWallType Basic Wall:Foundation - 300mm Concrete - Retaining
1qv6ynVKX7xf87anS8vNvs IfcWallType Basic Wall:Foundation - 375mm Concrete w_step
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# the element is typed once, so the type it had goes first
geom.assign_type(ifc.by_guid('3iM76qwej9Tf9ttHcbQrYo'),
                 ifc.by_guid('0nLMa_hqjDM9PNHQIvZ_DK'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid('3iM76qwej9Tf9ttHcbQrYo')
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcWallStandardCase 3iM76qwej9Tf9ttHcbQrYo Basic Wall:Foundation - 375mm Concrete w_step:209396
model committed
```
Assistant: Completed. The wall now carries the values the instruction asked for; the model was committed.

### Example 2
User:
Assign the wall with ID 2L$NVfKM997BK28KaiKgL_ to the type object named 'Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P', preserving all of its relationships.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
candidates = []
for ifc_class in ('IfcWallType', 'IfcTypeProduct'):
    try:
        candidates = list(ifc.by_type(ifc_class))
    except Exception:
        candidates = []
    if candidates:
        break
for product in sorted(candidates, key=lambda t: (t.Name or '')):
    print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
2ru7YPT4T9MuTpOS4FRzxX IfcWallType Basic Wall:Wall-Ext_102Bwk-75Ins-100LBlk-12P
2ru7YPT4T9MuTpOS4FRzxh IfcWallType Basic Wall:Wall-Int_12P-100Blk-12P
```
Assistant tool call execute_ifc_code:
```python
# put the element under the type object the instruction names
geom.assign_type(ifc.by_guid('2L$NVfKM997BK28KaiKgL_'),
                 ifc.by_guid('2ru7YPT4T9MuTpOS4FRzxX'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
product = ifc.by_guid('2L$NVfKM997BK28KaiKgL_')
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcWall 2L$NVfKM997BK28KaiKgL_ Basic Wall:Wall-Int_12P-100Blk-12P:468620
model committed
```
Assistant: The wall now carries the values the instruction asked for. The edited model is committed.

### Example 3
User:
Assign the space with GlobalId 1z5$_f1l51d8cd4qNmlabx to the type object named 'Reception Room 77:489291', preserving all of its relationships.

IFC model path: <path to the working copy>
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
options = []
for ifc_class in ("IfcSpaceType", 'IfcTypeProduct'):
    try:
        options = list(ifc.by_type(ifc_class))
    except Exception:
        options = []
    if options:
        break
for product in sorted(options, key=lambda t: (t.Name or '')):
    print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
1z5$_f1l51d8cd6qNmlab$ IfcSpaceType Lobby / Waiting Room 105:489497
1z5$_f1l51d8cd6qNmlab4 IfcSpaceType Lobby / Waiting Room 112:489506
1z5$_f1l51d8cd6qNmlaST IfcSpaceType Lobby / Waiting Room 12:489083
1z5$_f1l51d8cd6qNmlaVT IfcSpaceType Lobby / Waiting Room 55:489147
1z5$_f1l51d8cd6qNmlaOh IfcSpaceType Lobby / Waiting Room 78:489293
1z5$_f1l51d8cd6qNmlaQh IfcSpaceType Lobby / Waiting Room 96:489421
1z5$_f1l51d8cd6qNmlabm IfcSpaceType Manager Room 102:489494
1z5$_f1l51d8cd6qNmlabv IfcSpaceType Manager Room 109:489503
1z5$_f1l51d8cd6qNmlaIS IfcSpaceType Manager Room 5:488954
1z5$_f1l51d8cd6qNmlaUy IfcSpaceType Manager Room 71:489178
1z5$_f1l51d8cd6qNmlaOp IfcSpaceType Manager Room 83:489301
1z5$_f1l51d8cd6qNmlaQi IfcSpaceType Manager Room 93:489418
1z5$_f1l51d8cd6qNmlaIP IfcSpaceType Meeting Room 10:488959
1z5$_f1l51d8cd6qNmlaUx IfcSpaceType Meeting Room 74:489181
1z5$_f1l51d8cd6qNmlaUu IfcSpaceType Meeting Room 75:489182
1z5$_f1l51d8cd6qNmlaO_ IfcSpaceType Meeting Room 86:489304
1z5$_f1l51d8cd6qNmlaO$ IfcSpaceType Meeting Room 87:489305
1z5$_f1l51d8cd6qNmlaQe IfcSpaceType Meeting Room 97:489422
1z5$_f1l51d8cd6qNmlaQf IfcSpaceType Meeting Room 98:489423
1z5$_f1l51d8cd6qNmlaIO IfcSpaceType Meeting Room 9:488958
1z5$_f1l51d8cd6qNmlabp IfcSpaceType Private Cabin 101:489493
1z5$_f1l51d8cd6qNmlabu IfcSpaceType Private Cabin 108:489502
1z5$_f1l51d8cd6qNmlaIV IfcSpaceType Private Cabin 4:488953
1z5$_f1l51d8cd6qNmlaU$ IfcSpaceType Private Cabin 70:489177
1z5$_f1l51d8cd6qNmlaOo IfcSpa
```
Assistant tool call execute_ifc_code:
```python
# type the element, replacing the type it had
geom.assign_type(ifc.by_guid("1z5$_f1l51d8cd4qNmlabx"),
                 ifc.by_guid("1z5$_f1l51d8cd6qNmlaOj"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
product = ifc.by_guid("1z5$_f1l51d8cd4qNmlabx")
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcSpace 1z5$_f1l51d8cd4qNmlabx 107
model committed
```
Assistant: The space has been updated, and the edit is written to the working file.
