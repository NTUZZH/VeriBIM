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
Add a new slab named 'Deck 199' on the storey that contains the wall named 'Mur de base:Bardage double peau Horizontal Rouge RAL 3001:5516419', 4 m by 4 m in plan and 0.2 m thick, with its base corner at (40.70, -125.83, 0.00) m in that storey's own coordinates. Give it the predefined type LANDING.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
matches = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Mur de base:Bardage double peau Horizontal Rouge RAL 3001:5516419']
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2k8RdjHL9Aox3kizsNechO IfcWallStandardCase Mur de base:Bardage double peau Horizontal Rouge RAL 3001:5516419
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('2k8RdjHL9Aox3kizsNechO')
floor = None
for link in getattr(element, 'ContainedInStructure', None) or ():
    floor = link.RelatingStructure
    break
if floor is None:
    for link in getattr(element, 'Decomposes', None) or ():
        floor = link.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2k8RdjHL9Aox3kizsNechO IfcWallStandardCase Mur de base:Bardage double peau Horizontal Rouge RAL 3001:5516419 is contained in 0ELnodLOr8mQ4vsWfSh2VC IfcBuildingStorey R+2 (Bureaux) elevation 7.91999999999652
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
floor = ifc.by_guid('0ELnodLOr8mQ4vsWfSh2VC')
added = geom.add_box_element(floor, 'IfcSlab', 'Deck 199', 40.7, -125.83, 0.0, 4.0, 4.0,
                             0.2, predefined_type='LANDING', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
1MxRGWbmvDneJyySxEMjXt IfcSlab Deck 199
model committed
```
Assistant: Done. The slab has been created and placed on its storey, and the model has been saved.

### Example 2
User:
Add a new slab named 'Deck 107' on the storey that contains the wall named 'Basic Wall:Int_rm_sep_Wall_100m:386687', 4 m by 4 m in plan and 0.2 m thick, with its base corner at (-4.76, -8.61, 0.00) m in that storey's own coordinates. Give it the predefined type FLOOR.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:Int_rm_sep_Wall_100m:386687"]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
[('0pJ3mcOQj1Yun_U0JJ7TtW', 'IfcWall', 'Basic Wall:Int_rm_sep_Wall_100m:386687')]
```
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid("0pJ3mcOQj1Yun_U0JJ7TtW")
level = None
for relation in getattr(element, 'ContainedInStructure', None) or ():
    level = relation.RelatingStructure
    break
if level is None:
    for relation in getattr(element, 'Decomposes', None) or ():
        level = relation.RelatingObject
        break
while level is not None and not level.is_a('IfcBuildingStorey'):
    parents = getattr(level, 'Decomposes', None) or ()
    level = parents[0].RelatingObject if parents else None
if level is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', level.GlobalId, level.is_a(), level.Name, 'elevation', getattr(level, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
0pJ3mcOQj1Yun_U0JJ7TtW IfcWall Basic Wall:Int_rm_sep_Wall_100m:386687 is contained in 15Z0v90RiHrPC20026FoKR IfcBuildingStorey Level 1 elevation 370.0
model length unit in metres: 0.01
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((4.0, 4.0), (0.2, 0.2),):
    print(stated, "m", '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
4.0 m = 4.0 m = 400.0 file units
0.2 m = 0.2 m = 20.0 file units
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
level = ifc.by_guid("15Z0v90RiHrPC20026FoKR")
added = geom.add_box_element(level, "IfcSlab", "Deck 107", -4.76, -8.61, 0.0, 4.0, 4.0,
                             0.2, predefined_type="FLOOR", frame="storey")
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(added.GlobalId, added.is_a(), added.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
3FkHUnxwn8fwNxBt0az7$y IfcSlab Deck 107
model committed
```
Assistant: Done. The slab has been created and placed on its storey, and the model has been saved.

### Example 3
User:
Add a new slab named 'Deck 255' on the storey that contains the wall named 'Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:883085', 4 m by 4 m in plan and 0.2 m thick, with its base corner at (-4.20, 2.36, 0.00) m in that storey's own coordinates. Give it the predefined type FLOOR.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
hits = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:883085']
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1l5YQX3P17wemsuk3NHMu_ IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:883085
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the instruction gives the storey through an element; follow the link
element = ifc.by_guid('1l5YQX3P17wemsuk3NHMu_')
floor = None
for rel in getattr(element, 'ContainedInStructure', None) or ():
    floor = rel.RelatingStructure
    break
if floor is None:
    for rel in getattr(element, 'Decomposes', None) or ():
        floor = rel.RelatingObject
        break
while floor is not None and not floor.is_a('IfcBuildingStorey'):
    parents = getattr(floor, 'Decomposes', None) or ()
    floor = parents[0].RelatingObject if parents else None
if floor is None:
    raise ValueError('the element sits on no storey')
print(element.GlobalId, element.is_a(), element.Name, 'is contained in', floor.GlobalId, floor.is_a(), floor.Name, 'elevation', getattr(floor, 'Elevation', None))
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1l5YQX3P17wemsuk3NHMu_ IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:883085 is contained in 31MO7odvv0cAeswhRbr4Rh IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.O) elevation -5.00000000000005
model length unit in metres: 0.01
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', scale, 'metres')
for stated, metres in ((2.36, 2.36), (4.0, 4.0), (0.2, 0.2),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
2.36 m = 2.36 m = 236.0 file units
4.0 m = 4.0 m = 400.0 file units
0.2 m = 0.2 m = 20.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
floor = ifc.by_guid('31MO7odvv0cAeswhRbr4Rh')
added = geom.add_box_element(floor, 'IfcSlab', 'Deck 255', -4.2, 2.36, 0.0, 4.0, 4.0,
                             0.2, predefined_type='FLOOR', frame='storey')
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added.GlobalId, added.is_a(), added.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
1Ha3p5Nn538BduZQcz9cLn IfcSlab Deck 255
model committed
```
Assistant: Completed. The slab has been created and placed on its storey; the model was committed.
