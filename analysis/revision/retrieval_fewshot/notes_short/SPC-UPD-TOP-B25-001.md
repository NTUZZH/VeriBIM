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
Mirror the space across the vertical plane that follows the axis of the wall named 'Wall - 033'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
pool = ifc.by_type("IfcSpace")
print(len(pool), "IfcSpace", 'in the model')
for product in pool[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
14 IfcSpace in the model
  2_NBtRqv0xHPyZ3gqke_JN 023
  3sstO$18JoIeuAwWsqJXGx 018
  0Xx9gDujQRJ9wzMj5p9LxT 004
  01ZttA0LnYHOt2JmXKzHCD 022
  0fBqEt1YIiJxheeR9u8F$B 017
  2sPqcjDWtyJQ$irRpC14yc 003
  1_H6E$UDhXIA3rHRgu6i2r 021
  1PuuB4jeJnIQvaCklNmi0O 016
  1q4rTWu0ceHuzRXwmrgug$ 024
  1GuYqwaVqdGfeP4vpHa3o4 015
  1iZ0zxIBgAGupDqiow_YFK 014
  1EBPnyWt$bJerAs_yHIWpx 013
  3crvDEgvEyHwTZgAQeD0Zh 001
  3_T9NSZpyiG9AD2xiPaKey 002
```
Assistant: Which space do you mean?

### Example 2
User:
Can you mirror the wall across the vertical plane that follows the axis of the wall named 'Basic Wall:PAR - INT - ALV - 15 - ACAB.INT BASE:1096826'?

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type('IfcWall')
print(len(pool), 'IfcWall', 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
57 IfcWall in the model
  1l5YQX3P17wemsuk3NHM0L Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882598
  0y1oAYEEnBDOgxtEiqfrKl Basic Wall:PAR - EXT - ALV - 34.78 - ACAB.EXT BASE - ACAB.INT BASE:891629
  1l5YQX3P17wemsuk3NHNuh Basic Wall:PAR - EXT - ALV - 25 - ACAB.EXT BASE - ACAB.INT BASE:879000
  1l5YQX3P17wemsuk3NHNWY Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:880529
  1l5YQX3P17wemsuk3NHMV2 Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:880753
  1l5YQX3P17wemsuk3NHMQd Basic Wall:PAR - INT - ALV - 15 - ACAB.INT BASE:880916
  1l5YQX3P17wemsuk3NHMK$ Basic Wall:PAR - INT - ALV - 15 - ACAB.INT BASE:881292
  1l5YQX3P17wemsuk3NHMG$ Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:881548
  1l5YQX3P17wemsuk3NHMEP Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:881706
  1l5YQX3P17wemsuk3NHMAn Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:881922
  1l5YQX3P17wemsuk3NHMBa Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882007
  1l5YQX3P17wemsuk3NHM9V Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882156
  1l5YQX3P17wemsuk3NHM4t Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882308
  1l5YQX3P17wemsuk3NHM5K Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO 
```
Assistant: Which wall do you mean?

### Example 3
User:
Reflect the space across the vertical plane that follows the axis of the wall named 'Basic Wall:Interior - Partition (92mm Stud):203998'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
options = ifc.by_type('IfcSpace')
print(len(options), 'IfcSpace', 'in the model')
for product in options[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
21 IfcSpace in the model
  0BTBFw6f90Nfh9rP1dlXrr A101
  0BTBFw6f90Nfh9rP1dlXri A201
  0BTBFw6f90Nfh9rP1dl_3P B104
  0BTBFw6f90Nfh9rP1dl_3Q B101
  0BTBFw6f90Nfh9rP1dl_3G B201
  2gRXFgjRn2HPE$YoDLX3FV A205
  2gRXFgjRn2HPE$YoDLX3FC B205
  10mjSDZJj9gPS2PrQaxa3z A105
  10mjSDZJj9gPS2PrQaxa4o B105
  0pNy6pOyf7JPmXRLgxs3sW R301
  0BTBFw6f90Nfh9rP1dl_CZ B102
  0BTBFw6f90Nfh9rP1dlXr2 A102
  0BTBFw6f90Nfh9rP1dlXr$ A103
  0BTBFw6f90Nfh9rP1dl_3S B103
  0BTBFw6f90Nfh9rP1dl_3C B204
  0BTBFw6f90Nfh9rP1dlXre A204
  0BTBFw6f90Nfh9rP1dlXru A104
  0BTBFw6f90Nfh9rP1dl_39 B203
  0BTBFw6f90Nfh9rP1dlXrc A202
  0BTBFw6f90Nfh9rP1dl_3A B202
```
Assistant: Which space do you mean?
