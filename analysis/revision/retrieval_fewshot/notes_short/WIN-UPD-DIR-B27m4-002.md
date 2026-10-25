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
Change the overall height of the window from 1.63 m to 1.3 m.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type("IfcWindow")
print(len(pool), "IfcWindow", 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
11 IfcWindow in the model
  2aGbxcRfH7xwAj5lAAxyJH Ventana 2 hojas:1.20x1.20 m:2040464
  2aGbxcRfH7xwAj5lAAxyM6 Ventana 2 hojas:1.80x1.50 m 2:2040775
  2aGbxcRfH7xwAj5lAAxy9V Ventana 2 hojas:1.80x1.50 m:2040862
  2aGbxcRfH7xwAj5lAAxy9v Ventana 2 hojas:1.80x1.50 m:2040888
  2aGbxcRfH7xwAj5lAAxyB$ Ventana 2 hojas:1.80x1.50 m:2041022
  2aGbxcRfH7xwAj5lAAxyDn Ventana 2 hojas:1.80x1.50 m:2041136
  3Bw42jQbz7jP5t1Eleiv89 Simple 1 hoja:traga luz 800x400 mm:2065436
  3Bw42jQbz7jP5t1EleivBB Simple 1 hoja:traga luz 800x400 mm:2065630
  3Bw42jQbz7jP5t1EleivCF Simple 1 hoja:traga luz 800x400 mm:2065690
  3Bw42jQbz7jP5t1Eleiv0U Simple 1 hoja:traga luz 400x600 mm:2065931
  2cWa1FKRT0EuVuZrnLYh$w Ventana 2 hojas:1.80x1.50 m:2169923
```
Assistant: Which window do you mean?

### Example 2
User:
Change the overall height of the window from 2.5 m to 3.75 m.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type("IfcWindow")
print(len(candidates), "IfcWindow", 'in the model')
for target in candidates[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
104 IfcWindow in the model
  1Lm_zyC$rCAgXKKZJbi1Ho Window-Casement-Triple-Side-Transom:4000 x 2500:369244
  1Lm_zyC$rCAgXKKZJbi1Nv Window-Casement-Triple-Side-Transom:4000 x 2500:369623
  1Lm_zyC$rCAgXKKZJbi1NI Window-Casement-Triple-Side-Transom:4000 x 2500:369660
  1Lm_zyC$rCAgXKKZJbi1NJ Window-Casement-Triple-Side-Transom:4000 x 2500:369661
  1Lm_zyC$rCAgXKKZJbi18z Window-Casement-Triple-Side-Transom:4000 x 2500:369683
  1Lm_zyC$rCAgXKKZJbi18w Window-Casement-Triple-Side-Transom:4000 x 2500:369684
  1Lm_zyC$rCAgXKKZJbi188 Window-Casement-Triple-Side-Transom:4000 x 2500:369702
  1Lm_zyC$rCAgXKKZJbi189 Window-Casement-Triple-Side-Transom:4000 x 2500:369703
  1Lm_zyC$rCAgXKKZJbi186 Window-Casement-Triple-Side-Transom:4000 x 2500:369704
  1Lm_zyC$rCAgXKKZJbi187 Window-Casement-Triple-Side-Transom:4000 x 2500:369705
  1Lm_zyC$rCAgXKKZJbi184 Window-Casement-Triple-Side-Transom:4000 x 2500:369706
  1Lm_zyC$rCAgXKKZJbi185 Window-Casement-Triple-Side-Transom:4000 x 2500:369707
  1Lm_zyC$rCAgXKKZJbi19s Window-Casement-Triple-Side-Transom:4000 x 2500:369752
  1Lm_zyC$rCAgXKKZJbi1Ar Window-Casement-Triple-Side-Transom:4000 x 2500:369819
  1Lm_zyC$rCAgXKKZJbi1Ao Window-Casement-Triple-Side-Transom:4000 x 2500:369820
  1Lm_zyC$rCAgXKKZJbi1Ap Window-Casement-Triple-Side-Transom:4000 x 2500:369821
  1Lm_zyC$rCAgXKKZJbi1Am Window-Casement-Triple-Side-Transom:4000 x 2500:369822
  1Lm_zyC$rCAgXKKZJbi1An Window-Casement-Triple-Side-Transom:4000 x 2500:369823
  1Lm_zyC$rCAgXKKZJbi1AE Window-C
```
Assistant: Which window do you mean?

### Example 3
User:
Change the overall height of the window from 1.21 m to 0.97 m.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type('IfcWindow')
print(len(candidates), 'IfcWindow', 'in the model')
for product in candidates[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
137 IfcWindow in the model
  0B5TcqRH9AvRxkABxkWq4U Windows_Sgl_Plain:910x910mm:410155
  0B5TcqRH9AvRxkABxkWq3v Windows_Sgl_Plain:910x910mm:410572
  0B5TcqRH9AvRxkABxkWqUf Windows_Sgl_Plain:910x910mm:410780
  0B5TcqRH9AvRxkABxkWqV1 Windows_Sgl_Plain:910x910mm:410868
  0B5TcqRH9AvRxkABxkWqR$ Windows_Sgl_Plain:1810x1210mm:411082
  0B5TcqRH9AvRxkABxkWqKe Windows_Sgl_Plain:1810x1210mm:411165
  0B5TcqRH9AvRxkABxkWqLc Windows_Sgl_Plain:1810x1210mm:411219
  0B5TcqRH9AvRxkABxkWqNg Windows_Sgl_Plain:1810x1210mm:411359
  0B5TcqRH9AvRxkABxkWqHP Windows_Sgl_Plain:1810x1210mm:411500
  0B5TcqRH9AvRxkABxkWqIj Windows_Sgl_Plain:1810x1210mm:411544
  0B5TcqRH9AvRxkABxkWqJt Windows_Sgl_Plain:1810x1210mm:411586
  0B5TcqRH9AvRxkABxkWqJf Windows_Sgl_Plain:1810x1210mm:411612
  0B5TcqRH9AvRxkABxkWr0V Windows_Sgl_Plain:1810x1210mm:414506
  0B5TcqRH9AvRxkABxkWr3v Windows_Sgl_Plain:1810x1210mm:414668
  0B5TcqRH9AvRxkABxkWrSr Windows_Sgl_Plain:1810x1210mm:414720
  0B5TcqRH9AvRxkABxkWrSB Windows_Sgl_Plain:1810x1210mm:414782
  0B5TcqRH9AvRxkABxkWrUp Windows_Sgl_Plain:1810x1210mm:414854
  0B5TcqRH9AvRxkABxkWrV$ Windows_Sgl_Plain:1810x1210mm:414922
  0B5TcqRH9AvRxkABxkWrOd Windows_Sgl_Plain:1810x1210mm:414994
  0B5TcqRH9AvRxkABxkWrPp Windows_Sgl_Plain:1810x1210mm:415046
```
Assistant: Which window do you mean?
