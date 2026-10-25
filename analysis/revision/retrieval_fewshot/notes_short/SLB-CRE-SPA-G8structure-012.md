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
Create a new slab named 'Deck 819' on storey 'CIMENTACION', 0.2 m high, so that it sits directly on top of the wall named 'Muro básico:BLOQUE 200 mm:1978485', over the same footprint. Give it the predefined type BASESLAB. Establish a connection to the wall named 'Muro básico:BLOQUE 200 mm:1978487'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Muro básico:BLOQUE 200 mm:1978485"]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
2oj0C26un9shtSOTTYIDRz IfcWallStandardCase Muro básico:BLOQUE 200 mm:1978485
```
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
0OCkzK25HA0wxSqRSYGLkp 'CIMENTACION' -0.6
0OCkzK25HA0wxSqRSYLGvE 'PLANTA BAJA' 0.0
0OCkzK25HA0wxSqRSYLGYr 'CUBIERTA' 3.0
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
# the elements the instruction names
wanted = {"Deck 819", "CIMENTACION", "Muro básico:BLOQUE 200 mm:1978485", "Muro básico:BLOQUE 200 mm:1978487"}
for target in ifc.by_type('IfcProduct'):
    label = (target.Name or '', getattr(target, 'LongName', None) or '')
    if wanted.intersection(label):
        print(target.GlobalId, target.is_a(), target.Name)
```
Tool result:
```
2oj0C26un9shtSOTTYIDRz IfcWallStandardCase Muro básico:BLOQUE 200 mm:1978485
2oj0C26un9shtSOTTYIDR$ IfcWallStandardCase Muro básico:BLOQUE 200 mm:1978487
0OCkzK25HA0wxSqRSYGLkp IfcBuildingStorey CIMENTACION
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
neighbour = ifc.by_guid("2oj0C26un9shtSOTTYIDRz")
corner, base_size = geom.spot_on_top_of(neighbour)
print('corner on the top face (m):', [round(v, 3) for v in corner])
print('footprint (m):', [round(v, 3) for v in base_size])
```
Tool result:
```
corner on the top face (m): [-3.187, -6.836, -0.25]
footprint (m): [0.215, 2.415]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
floor = ifc.by_guid("0OCkzK25HA0wxSqRSYGLkp")
# work the position out from the element the instruction refers to
neighbour = ifc.by_guid("2oj0C26un9shtSOTTYIDRz")
corner, base_size = geom.spot_on_top_of(neighbour)
created = geom.add_box_element(floor, "IfcSlab", "Deck 819", corner[0], corner[1],
                               corner[2], base_size[0], base_size[1], 0.2,
                               predefined_type="BASESLAB", frame="world")
geom.connect_elements(created, ifc.by_guid("2oj0C26un9shtSOTTYIDR$"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(created.GlobalId, created.is_a(), created.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
3DB6eU6wP2RgQOAipN6RnA IfcSlab Deck 819
model committed
```
Assistant: Completed. The slab has been created and placed on its storey; the model was committed.

### Example 2
User:
Please create a new slab named 'Deck 343' on storey 'Ebene 4', 0.2 m high, so that it sits directly on top of the wall named 'Basic Wall:DPW 24.0:306284', over the same footprint. Give it the predefined type BASESLAB. Establish a connection to the wall named 'Basic Wall:DPW 24.0:306284'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# find the element the instruction names
found = [e for e in ifc.by_type("IfcWall")
       if (e.Name or '').strip() == "Basic Wall:DPW 24.0:306284"]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
2ilp3ZnMf1VuSVDT9h1034 IfcWallStandardCase Basic Wall:DPW 24.0:306284
```
Assistant tool call execute_ifc_code:
```python
# the instruction names a storey; find which one it is
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
2X79U1hqrFKw7ilF22iywu 'Ebene 1' 0.0
2KxRpJWyL6EeW8ZJpX29tA 'Ebene 2' 4.0
2KxRpJWyL6EeW8ZJpX29sp 'Ebene 3' 4.6
2KxRpJWyL6EeW8ZJpX29sw 'Ebene 4' 8.6
2KxRpJWyL6EeW8ZJpX29sX 'Ebene 5' 9.2
2KxRpJWyL6EeW8ZJpX29se 'Ebene 6' 13.2
2KxRpJWyL6EeW8ZJpX29sl 'Ebene 7' 13.8
2KxRpJWyL6EeW8ZJpX29sM 'Ebene 8' 17.8
2KxRpJWyL6EeW8ZJpX29sT 'Ebene 9' 19.8
model length unit in metres: 1
```
Assistant tool call execute_ifc_code:
```python
# work the position out from the element the instruction refers to
reference = ifc.by_guid("2ilp3ZnMf1VuSVDT9h1034")
base_corner, base_size = geom.spot_on_top_of(reference)
print('corner on the top face (m):', [round(v, 3) for v in base_corner])
print('footprint (m):', [round(v, 3) for v in base_size])
```
Tool result:
```
corner on the top face (m): [10.965, -4.501, 8.3]
footprint (m): [6.568, 0.24]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# build the new element and hang it under the storey
floor = ifc.by_guid("2KxRpJWyL6EeW8ZJpX29sw")
# work the position out from the element the instruction refers to
reference = ifc.by_guid("2ilp3ZnMf1VuSVDT9h1034")
base_corner, base_size = geom.spot_on_top_of(reference)
new_element = geom.add_box_element(floor, "IfcSlab", "Deck 343", base_corner[0],
                                   base_corner[1], base_corner[2], base_size[0],
                                   base_size[1], 0.2, predefined_type="BASESLAB",
                                   frame="world")
geom.connect_elements(new_element, ifc.by_guid("2ilp3ZnMf1VuSVDT9h1034"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(new_element.GlobalId, new_element.is_a(), new_element.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
3a1bwnXD1BRvKXsAtcM03p IfcSlab Deck 343
model committed
```
Assistant: Done. The new slab is in the model, and the model has been saved.

### Example 3
User:
Add a new slab named 'Deck 513' on storey 'T/FDN', 0.2 m high, so that it sits directly on top of the wall named 'Basic Wall:Foundation - Concrete (435mm):140987', over the same footprint. Give it the predefined type BASESLAB. Establish a connection to the wall named 'Basic Wall:Foundation - Concrete (435mm):140987'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
matches = [e for e in ifc.by_type('IfcWall')
       if (e.Name or '').strip() == 'Basic Wall:Foundation - Concrete (435mm):140987']
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
[('2O2Fr$t4X7Zf8NOew3FK04', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (435mm):140987')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
for floor in ifc.by_type('IfcBuildingStorey'):
    print(floor.GlobalId, repr(floor.Name), floor.Elevation)
import ifcopenshell.util.unit
print('model length unit in metres:', ifcopenshell.util.unit.calculate_unit_scale(ifc))
```
Tool result:
```
1xS3BCk291UvhgP2dvNMKI 'Level 1' 0.0
1xS3BCk291UvhgP2dvNMQJ 'Level 2' 3.100000000000378
1xS3BCk291UvhgP2dvNsgp 'T/FDN' -1.25
1xS3BCk291UvhgP2dvNtSE 'Roof' 6.00000000000039
model length unit in metres: 1
```
Assistant: I will read the sizes the placement depends on first.
Assistant tool call execute_ifc_code:
```python
anchor_element = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK04')
base_corner, footprint = geom.spot_on_top_of(anchor_element)
print('corner on the top face (m):', [round(v, 3) for v in base_corner])
print('footprint (m):', [round(v, 3) for v in footprint])
```
Tool result:
```
corner on the top face (m): [0.417, -10.218, 0.0]
footprint (m): [4.2, 0.435]
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
floor = ifc.by_guid('1xS3BCk291UvhgP2dvNsgp')
anchor_element = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK04')
base_corner, footprint = geom.spot_on_top_of(anchor_element)
added = geom.add_box_element(floor, 'IfcSlab', 'Deck 513', base_corner[0],
                             base_corner[1], base_corner[2], footprint[0], footprint[1],
                             0.2, predefined_type='BASESLAB', frame='world')
geom.connect_elements(added, ifc.by_guid('2O2Fr$t4X7Zf8NOew3FK04'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
print(added.GlobalId, added.is_a(), added.Name)

commit()
print('model committed')
```
Tool result:
```
3ArMDrtMb49xImSRbSzSkW IfcSlab Deck 513
model committed
```
Assistant: Done. The slab has been created and placed on its storey, and the model has been saved.
