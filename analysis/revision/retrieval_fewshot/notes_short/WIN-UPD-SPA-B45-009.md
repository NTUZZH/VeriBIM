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
Assign the window to the type object named 'M_Casement Dbl with Trim:1220 x 1220mm'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type("IfcWindow")
print(len(pool), "IfcWindow", 'in the model')
for product in pool[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
19 IfcWindow in the model
  1afx0JQ$v1QOMjx1njOszn M_Casement 3x3 with Trim:0915 x 1220mm:185310
  1afx0JQ$v1QOMjx1njOszN M_Casement 3x3 with Trim:0915 x 1220mm:185336
  1afx0JQ$v1QOMjx1njOsyF M_Casement 3x3 with Trim:0915 x 1220mm:185248
  1afx0JQ$v1QOMjx1njOszj M_Casement 3x3 with Trim:0915 x 1220mm:185282
  1afx0JQ$v1QOMjx1njOs_s M_Casement 3x3 with Trim:0915 x 1220mm:185113
  1afx0JQ$v1QOMjx1njOs$F M_Casement 3x3 with Trim:0915 x 1220mm:185184
  1afx0JQ$v1QOMjx1njOsYr M_Casement 3x3 with Trim:0915 x 1220mm:185370
  1afx0JQ$v1QOMjx1njOsZ$ M_Fixed:0406 x 0610mm:185424
  0$RfMx2N198BtS5l_G4au9 M_Casement 3x3 with Trim:0915 x 1220mm:188305
  1UQaw$yP14cg0jpQXiLfdV M_Casement Dbl with Trim:1220 x 1220mm:194824
  1afx0JQ$v1QOMjx1njOsWk M_Casement 3x3 with Trim:0915 x 1220mm:185473
  1afx0JQ$v1QOMjx1njOsWj M_Casement 3x3 with Trim:0915 x 1220mm:185474
  1afx0JQ$v1QOMjx1njOsWi M_Casement 3x3 with Trim:0915 x 1220mm:185475
  1afx0JQ$v1QOMjx1njOsWh M_Casement 3x3 with Trim:0915 x 1220mm:185476
  1afx0JQ$v1QOMjx1njOsWg M_Casement 3x3 with Trim:0915 x 1220mm:185477
  1afx0JQ$v1QOMjx1njOsWf M_Casement 3x3 with Trim:0915 x 1220mm:185478
  1afx0JQ$v1QOMjx1njOsWe M_Fixed:0406 x 0610mm:185479
  0$RfMx2N198BtS5l_G4avE M_Casement 3x3 with Trim:0915 x 1220mm:188374
  0ZspxptB98VR5acrkAmDqp M_Casement 3x3 with Trim:0915 x 1220mm:190093
```
Assistant: Which window do you mean?

### Example 2
User:
Assign the window to the type object named '1.20x1.20 m'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
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

### Example 3
User:
Assign the window to the type object named 'Windows_Sgl_Horz_Bars:910x910mm'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type('IfcWindow')
print(len(pool), 'IfcWindow', 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
62 IfcWindow in the model
  3y6GoXdK11eRJl1yIKgwCM Windows_Concept_Plain_Dbl:910x910mm:519541
  0laIO_dyP7zOLHun47JbUo Windows_Concept_Plain_Dbl:910x910mm:558640
  0fTOPzvojCnB$HflWGSKbQ Windows_Concept_Plain_Dbl:910x910mm:518660
  0fTOPzvojCnB$HflWGSK_P Windows_Concept_Plain_Dbl:910x910mm:519367
  3y6GoXdK11eRJl1yIKgxuF Windows_Concept_Plain_Dbl:910x910mm:520300
  3cXayCwsf2VgWLN_j9WJG9 Windows_Concept_Plain_Dbl:910x910mm 2:522571
  1KLGpC7qv9nRXBvPH9rJ1P Windows_Sgl_Horz_Bars:910x910mm:530714
  3y6GoXdK11eRJl1yIKgxxL Windows_Concept_Plain_Dbl:910x910mm:520374
  2pSOckt_5Ajwi4t6RCrRlq Windows_Concept_Plain_Dbl:910x910mm:504718
  2pSOckt_5Ajwi4t6RCrRls Windows_Concept_Plain_Dbl:910x910mm:504716
  1KLGpC7qv9nRXBvPH9rJ1Q Windows_Sgl_Horz_Bars:910x910mm:530713
  2pSOckt_5Ajwi4t6RCrRlk Windows_Concept_Plain_Dbl:910x910mm:504724
  2pSOckt_5Ajwi4t6RCrRlf Windows_Concept_Plain_Dbl:910x910mm:504723
  2pSOckt_5Ajwi4t6RCrRlr Windows_Concept_Plain_Dbl:910x910mm:504719
  2pSOckt_5Ajwi4t6RCrRle Windows_Concept_Plain_Dbl:910x910mm:504722
  2pSOckt_5Ajwi4t6RCrRlh Windows_Concept_Plain_Dbl:910x910mm:504721
  2pSOckt_5Ajwi4t6RCrRlg Windows_Concept_Plain_Dbl:910x910mm:504720
  0laIO_dyP7zOLHun47JbpU Windows_Concept_Plain_Dbl:910x910mm:560476
  2pSOckt_5Ajwi4t6RCrRli Windows_Concept_Plain_Dbl:910x910mm:504726
  2pSOckt_5Ajwi4t6RCrRll Windows_Concept_Plain_Dbl:910x910mm:504725
```
Assistant: Which window do you mean?
