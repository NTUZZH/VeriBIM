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
Assign the material 'Wood - Sheathing - plywood' to the window.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type("IfcWindow")
print(len(candidates), "IfcWindow", 'in the model')
for element in candidates[:20]:
    print(' ', element.GlobalId, element.Name)
```
Tool result:
```
24 IfcWindow in the model
  1hOSvn6df7F8_7GcBWlR72 M_Fixed:4835mm x 2420mm:4835mm x 2420mm:145788
  1hOSvn6df7F8_7GcBWlRBU M_Fixed:4835mm x 2420mm:4835mm x 2420mm:146016
  1hOSvn6df7F8_7GcBWlRLx M_Fixed:750mm x 2200mm:750mm x 2200mm:146885
  1hOSvn6df7F8_7GcBWlRRL M_Fixed:750mm x 2200mm:750mm x 2200mm:147051
  1hOSvn6df7F8_7GcBWlSXO M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686
  1hOSvn6df7F8_7GcBWlSga M_Fixed:819mm x 759mm:819mm x 759mm:147994
  1hOSvn6df7F8_7GcBWlSp1 M_Casement:819mm x 759mm:819mm x 759mm:148607
  1hOSvn6df7F8_7GcBWlSnC M_Fixed:819mm x 759mm:819mm x 759mm:148722
  1hOSvn6df7F8_7GcBWlS_W M_Fixed:2800mm x 2410mm:2800mm x 2410mm:149278
  1hOSvn6df7F8_7GcBWlS2V M_Fixed:819mm x 759mm:819mm x 759mm:149537
  1hOSvn6df7F8_7GcBWlS1M M_Casement:819mm x 759mm:819mm x 759mm:149736
  1hOSvn6df7F8_7GcBWlS4Q M_Fixed:819mm x 759mm:819mm x 759mm:149924
  1l0GAJtRTFv8$zmKJOH4$e M_Fixed:2800mm x 2410mm:2800mm x 2410mm:180318
  1l0GAJtRTFv8$zmKJOH4u1 M_Fixed:819mm x 759mm:819mm x 759mm:180663
  1l0GAJtRTFv8$zmKJOH4qs M_Fixed:819mm x 759mm:819mm x 759mm:180864
  1l0GAJtRTFv8$zmKJOH4oq M_Casement:819mm x 759mm:819mm x 759mm:180994
  1l0GAJtRTFv8$zmKJOH4pU M_Fixed:2800mm x 2410mm:2800mm x 2410mm:181096
  1l0GAJtRTFv8$zmKJOH4kJ M_Fixed:819mm x 759mm:819mm x 759mm:181285
  1l0GAJtRTFv8$zmKJOH4gQ M_Casement:819mm x 759mm:819mm x 759mm:181548
  1l0GAJtRTFv8$zmKJOH4hv M_Fixed:819mm x 759mm:819mm x 759mm:181583
```
Assistant: Which window do you mean?

### Example 2
User:
Assign the material 'Steel - Structural' to the window.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
options = ifc.by_type('IfcWindow')
print(len(options), 'IfcWindow', 'in the model')
for element in options[:20]:
    print(' ', element.GlobalId, element.Name)
```
Tool result:
```
90 IfcWindow in the model
  2xj2ISBRPAEf6nlGenrC7h WD - 050
  17qulBNsnEhv6bTvunh28y WD - 050
  2iLHrxIIj1YRjsGI6W0j6_ WD - 050
  3QZem7wCD4sfBCNj4t0CNd WD - 050
  3xDXlY_ATBGR3oBjdWWQEO WD - 050
  1HAMGt6CPAvB1pn88ZTtoD WD - 050
  0d7SU9V$TEEw$3W14c$Fv5 WD - 059
  1RtBoA9P12Cu82fxb0YAe3 WD - 060
  1L_IC4rSrE7hqRJfOEuJK7 WD - 068
  2U34KVpdf0lgQ8Po25yyo4 WD - 055
  3cKrrt1TL6TfDxlQFQa1Fk WD - 055
  31yQpJOl9D7ubT64MSD2ly WD - 055
  1re1qSl2X1r8i3S9OS6FPg WD - 063
  1AZuG4YzL2ogWiuYE3wMXi WD - 066
  10nkJGUc59KRobb0VfdXZT WD - 067
  2sKM2F5_f7KvcKhkAi$h2v WD - 062
  0wg6wNCMTESxUpHY8zzSE3 WD - 061
  3ELPdk01DABgVHLPLXL_IJ WD - 058
  0mFB0nmAP2Mfe2FHs9FUxX WD - 064
  0hQS0tebf0sw$3O2Y1JEb3 WD - 065
```
Assistant: Which window do you mean?

### Example 3
User:
Assign the material 'SSG_Plastic_Laminate_Wood_PBR' to the window.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
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
107 IfcWindow in the model
  2AkJygAtzDjRoRyHyG5XwX M_Curtain Wall-Awning:M_Curtain Wall-Awning:763179
  2AkJygAtzDjRoRyHyG5Xwc M_Curtain Wall-Awning:M_Curtain Wall-Awning:763180
  2AkJygAtzDjRoRyHyG5X9E M_Curtain Wall-Awning:M_Curtain Wall-Awning:764356
  2AkJygAtzDjRoRyHyG5X9F M_Curtain Wall-Awning:M_Curtain Wall-Awning:764357
  2guGa4mIz7q8$Tp6zoOhff Windows_Sgl_Plain:1360x1210mm:451736
  2guGa4mIz7q8$Tp6zoOhYE Windows_Sgl_Plain:1360x1210mm:452223
  31d_$DsYLFnhF8SJ6d6CjF FE 4 tlg - Fix im Rahmen:2750 x 1400:537052
  31d_$DsYLFnhF8SJ6d6CaS FE 4 tlg - Fix im Rahmen:2750 x 1400:537487
  31d_$DsYLFnhF8SJ6d6Cai FE 4 tlg - Fix im Rahmen:2750 x 1400:537535
  31d_$DsYLFnhF8SJ6d6Cxy FE 4 tlg - Fix im Rahmen:2750 x 1400:537711
  31d_$DsYLFnhF8SJ6d6Cq_ Windows_Tpl_Variable_Casement:1360x1210mm:538541
  31d_$DsYLFnhF8SJ6d6CCh Windows_Tpl_Variable_Casement:1360x1210mm:539064
  31d_$DsYLFnhF8SJ6d6CD6 Windows_Tpl_Variable_Casement:1360x1210mm:539093
  31d_$DsYLFnhF8SJ6d6C2o Windows_Tpl_Variable_Casement:1360x1210mm:539169
  1UvqXwTjHAe8w7vnauyQBl Windows_Tpl_Variable_Casement:1360x1210mm:539366
  1UvqXwTjHAe8w7vnauyQEx Windows_Tpl_Variable_Casement:1360x1210mm:539570
  1UvqXwTjHAe8w7vnauyQG5 Windows_Tpl_Variable_Casement:1360x1210mm:539660
  1UvqXwTjHAe8w7vnauyQJr Windows_Tpl_Variable_Casement:1360x1210mm:539900
  0cQWmnnqv6uvhIgiHOhTCp Windows_Sgl_Plain:1360x1210mm:588792
  0cQWmnnqv6uvhIgiHOhTJH Windows_Sgl_Plain:1360x1210mm:588826
```
Assistant: Which window do you mean?
