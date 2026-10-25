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
Rename the wall to 'Partition 210'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
pool = ifc.by_type("IfcWall")
print(len(pool), "IfcWall", 'in the model')
for element in pool[:20]:
    print(' ', element.GlobalId, element.Name)
```
Tool result:
```
4 IfcWall in the model
  064CKbgdv2$uFEsgE5j3ba rail bridge - spandrel wall
  3LTGJZ50P17x4My$lMjBSo rail bridge - spandrel wall
  2tKslGZJz0Nu12g9XAhM2h rail bridge - spandrel wall
  06ymNwhgjC9vHrcokNIGHx rail bridge - spandrel wall
```
Assistant: Which wall do you mean?

### Example 2
User:
Rename the wall to 'Partition 292'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
candidates = ifc.by_type('IfcWall')
print(len(candidates), 'IfcWall', 'in the model')
for target in candidates[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
189 IfcWall in the model
  2cIgW2OJTDieQWoBsIsovZ [L]AD
  03r_vdbtH25RjXPqeHKkek [L]AD
  2krgaB0GP7DAfHc_3z76Gw [L]AD
  0VBdryB4DCBwzuYCpj07xh [L]AD
  0jonUfgb9CHfERqAUaM0B4 [L]AD
  2xI5SBuCLAkfbZce2G3zMp [L]AD
  2Fw2qJG$9FawLYvOW0vcmi [L]AD
  3fj$kdqnr0bw$r$jQCG3rk [L]AD
  1nOVpzQ$15KhKJx3D4EF92 [L]AD
  2$kL08_3jEoOB3pI7eLHmP [L]AD
  0ilDwH_FXCAhdmMgzq$2dE [L]AD
  3G8O$dXmr3PvRaNEOvxdzI [L]AD
  0l95C9dZH2KO7RUkFgODsw [L]AD
  2rhrmsCMb5_AcOOtjuME_1 [L]AD
  17M1hDQaz3ggniFyrXCGEi [L]AD
  1nDYoulk90_PnzNxRwqHFp [L]AD
  0bsTHamgXFtP7ks3Uk4d1u [L]AD
  2J5ICWuZTADhA1DddtWO40 [L]AD
  3Fa_iZuJ1AueTEYC9x9wW5 [L]AD
  292Uz8q4H04wGBtnwK1iSL [L]AD
```
Assistant: Which wall do you mean?

### Example 3
User:
Rename the wall to 'Partition 919'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type("IfcWall")
print(len(candidates), "IfcWall", 'in the model')
for target in candidates[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
4 IfcWall in the model
  064CKbgdv2$uFEsgE5j3ba rail bridge - spandrel wall
  3LTGJZ50P17x4My$lMjBSo rail bridge - spandrel wall
  2tKslGZJz0Nu12g9XAhM2h rail bridge - spandrel wall
  06ymNwhgjC9vHrcokNIGHx rail bridge - spandrel wall
```
Assistant: Which wall do you mean?
