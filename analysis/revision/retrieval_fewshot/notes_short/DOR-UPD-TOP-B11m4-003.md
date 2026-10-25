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
Assign the material 'Wood - Dimensional Lumber' to the door.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type('IfcDoor')
print(len(candidates), 'IfcDoor', 'in the model')
for product in candidates[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
14 IfcDoor in the model
  1hOSvn6df7F8_7GcBWlRGQ M_Single-Flush:1250mm x 2010mm:1250mm x 2010mm:146596
  1hOSvn6df7F8_7GcBWlRH8 M_Single-Flush:1250mm x 2010mm:1250mm x 2010mm:146678
  1hOSvn6df7F8_7GcBWlS8Z M_Single-Flush:0762 x 2032mm:0762 x 2032mm:150173
  1hOSvn6df7F8_7GcBWlS9F M_Single-Flush:0762 x 2032mm:0762 x 2032mm:150257
  1hOSvn6df7F8_7GcBWlSFK M_Single-Flush:0864 x 2032mm:0864 x 2032mm:150378
  1hOSvn6df7F8_7GcBWlSDm M_Single-Flush:0864 x 2032mm:0864 x 2032mm:150478
  2OBrcmyk58NupXoVOHUuXp M_Single-Flush:0864 x 2032mm:0864 x 2032mm:159734
  2OBrcmyk58NupXoVOHUvVV M_Single-Flush:0864 x 2032mm:0864 x 2032mm:159834
  2OBrcmyk58NupXoVOHUvR4 M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160065
  2OBrcmyk58NupXoVOHUvPL M_Single-Flush:0864 x 2032mm:0864 x 2032mm:160208
  1s1jVhK8z0pgKYcr9jt781 M_Single-Glass 1:0813 x 2420mm:0813 x 2420mm:171853
  1s1jVhK8z0pgKYcr9jt7AB M_Single-Glass 1:0813 x 2420mm:0813 x 2420mm:171975
  1aj$VJZFn2TxepZUBcKp$i M_Single-Flush:0762 x 2032mm:0762 x 2032mm:203720
  1aj$VJZFn2TxepZUBcKpac M_Single-Flush:0762 x 2032mm:0762 x 2032mm:204034
```
Assistant: Which door do you mean?

### Example 2
User:
Assign the material 'Steel, Polished' to the door.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type("IfcDoor")
print(len(pool), "IfcDoor", 'in the model')
for element in pool[:20]:
    print(' ', element.GlobalId, element.Name)
```
Tool result:
```
45 IfcDoor in the model
  0V$1ZMoYT79Qa7WB7xXlNj M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass:423888
  0V$1ZMoYT79Qa7WB7xXlKT M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass:423712
  0V$1ZMoYT79Qa7WB7xXlHB M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass:423542
  0k8z$D6xH488BMoSpT9OUs M_Door-Double-Sliding:1100 x 2000mm:438792
  0XoZPhm_512fXHcSqcVhSF M_Door-Double-Sliding:1100 x 2000mm:438871
  0gI$9k8nj7WQY4ujoOkzzM M_Door-Double-Sliding:1100 x 2000mm:443459
  0gI$9k8nj7WQY4ujoOkzzH M_Door-Double-Sliding:1100 x 2000mm:443460
  0gI$9k8nj7WQY4ujoOkzzs M_Door-Double-Sliding:1100 x 2000mm:443491
  0gI$9k8nj7WQY4ujoOkzzn M_Door-Double-Sliding:1100 x 2000mm:443492
  0otmyyExX2zhmKtVyuILUp M_Door-Passage-Single-Flush:750 x 2000mm:483833
  0otmyyExX2zhmKtVyuILJQ M_Door-Passage-Single-Flush:750 x 2000mm:483984
  0otmyyExX2zhmKtVyuILI3 M_Door-Passage-Single-Flush:750 x 2000mm:484041
  0otmyyExX2zhmKtVyuILLt M_Door-Passage-Single-Flush:750 x 2000mm:484157
  0otmyyExX2zhmKtVyuILaS M_Door-Interior-Single-Flush_Panel-Wood:550 x 2000mm:487254
  3QzNZxVf54ROJZRW5d5$QR M_Door-Interior-Single-Flush_Panel-Wood:550 x 2000mm:489376
  0q47oH26vFKPWZPAaG4UWW M_Door-Passage-Single-Flush:750 x 2000mm:491871
  0q47oH26vFKPWZPAaG4Ujt M_Door-Passage-Single-Flush:750 x 2000mm:492040
  1Uoy0A2DnAhhjHjlBrLzr$ M_Door-Passage-Single-Flush:900 x 2000mm:493868
  1Uoy0A2DnAhhjHjlBrLzvP M_Door-Passage-Single-Flush:900 x 2000mm:494090
  1Uoy0A2DnAhhjHjlBr
```
Assistant: Which door do you mean?

### Example 3
User:
Assign the material 'Air Barrier - Air Infiltration Barrier' to the door.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
options = ifc.by_type("IfcDoor")
print(len(options), "IfcDoor", 'in the model')
for target in options[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
122 IfcDoor in the model
  3j7ZcrARP1eeaxjkzRbKEQ Exit Door Discharge 1
  3j7ZcrARP1eeaxjkzRbK5D Single Flush_180 swing mw:36" x 84" x 180 swing:758767
  141UzFEpPAiBNNDMW3_Zre Double-Flush:72" x 84":763791
  141UzFEpPAiBNNDMW3_Zr8 Double-Flush:72" x 84":763823
  141UzFEpPAiBNNDMW3_Zqh Double-Flush:72" x 84":763852
  141UzFEpPAiBNNDMW3_Y0i Single-Flush:36" x 84":768715
  141UzFEpPAiBNNDMW3_Y04 Single-Flush:36" x 84":768739
  141UzFEpPAiBNNDMW3_a_f Single Flush_180 swing mw:36" x 84" x 180 swing:775502
  141UzFEpPAiBNNDMW3_a_N Single-Flush:36" x 84":775536
  06Bn2yUMH0p8373E1g6SEg Double-Flush:72" x 84":780354
  06Bn2yUMH0p8373E1g6SEi Double-Flush:72" x 84":780356
  06Bn2yUMH0p8373E1g6SEk Double-Flush:72" x 84":780358
  06Bn2yUMH0p8373E1g6SE1 Single-Flush:36" x 84":780393
  06Bn2yUMH0p8373E1g6SE3 Single-Flush:36" x 84":780395
  06Bn2yUMH0p8373E1g6SDX Single Flush_180 swing mw:36" x 84" x 180 swing:780425
  06Bn2yUMH0p8373E1g6S7p Exit Door 1
  06Bn2yUMH0p8373E1g6S4B Exit Door 2
  06Bn2yUMH0p8373E1g6TgJ Double-Flush:72" x 84":782715
  06Bn2yUMH0p8373E1g6TgL Double-Flush:72" x 84":782717
  06Bn2yUMH0p8373E1g6TgN Double-Flush:72" x 84":782719
```
Assistant: Which door do you mean?
