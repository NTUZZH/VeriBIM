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
Please delete the door from the model, together with the relationships that depend on it.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type("IfcDoor")
print(len(pool), "IfcDoor", 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
60 IfcDoor in the model
  2VXG0wWCz48QXcHEDK0A02 M_Single-Flush:0915 x 2134mm:401725
  2BdOpt6Pj6mADQtOgybs_q M_Single-Flush:0915 x 2134mm:402918
  2BdOpt6Pj6mADQtOgybsoV M_Single-Flush:0915 x 2134mm:403149
  2BdOpt6Pj6mADQtOgybsqj M_Single-Flush:0915 x 2134mm:403327
  2BdOpt6Pj6mADQtOgybssX M_Single-Flush:0915 x 2134mm:403443
  2BdOpt6Pj6mADQtOgybs8r M_Single-Flush:0915 x 2134mm:403559
  2BdOpt6Pj6mADQtOgybsCp M_Single-Flush:0915 x 2134mm:403809
  2BdOpt6Pj6mADQtOgybs1N M_Single-Flush:0915 x 2134mm:403973
  3xnY5pveL6xBboJ4yY7j9g M_Single-Flush:0915 x 2134mm:464698
  3xnY5pveL6xBboJ4yY7jrD M_Single-Flush:0915 x 2134mm:464925
  3xnY5pveL6xBboJ4yY7jq1 M_Single-Flush:0915 x 2134mm:464977
  3xnY5pveL6xBboJ4yY7jnD M_Single-Flush:0915 x 2134mm:465181
  3xnY5pveL6xBboJ4yY7jzd M_Single-Flush:0915 x 2134mm:465463
  3xnY5pveL6xBboJ4yY7jze M_Single-Flush:0915 x 2134mm:465464
  3xnY5pveL6xBboJ4yY7jzf M_Single-Flush:0915 x 2134mm:465465
  3xnY5pveL6xBboJ4yY7jzg M_Single-Flush:0915 x 2134mm:465466
  3xnY5pveL6xBboJ4yY7jzh M_Single-Flush:0915 x 2134mm:465467
  3xnY5pveL6xBboJ4yY7jzi M_Single-Flush:0915 x 2134mm:465468
  3xnY5pveL6xBboJ4yY7jzj M_Single-Flush:0915 x 2134mm:465469
  3xnY5pveL6xBboJ4yY7jzk M_Single-Flush:0915 x 2134mm:465470
```
Assistant: Which door do you mean?

### Example 2
User:
Please delete the door from the model, together with the relationships that depend on it.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
candidates = ifc.by_type("IfcDoor")
print(len(candidates), "IfcDoor", 'in the model')
for target in candidates[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
13 IfcDoor in the model
  3TwoY2Ff63GeA28YwTefgD DOO - 031
  1pE9vu_w0UJQ5FSQ69XjSK DOO - 033
  0mgYpoqmSZIvzHfrUb7hzh DOO - 030
  3VfKKCbpt3JOKfviN8svS4 DOO - 032
  0aZmyr8EJQIOMKk__yNzMs DOO - 038
  34r6rKx$QOHv1m9ZV28Crc DOO - 034
  1o0rr9gT8oIRKiigjybqm2 DOO - 035
  16QrjjgRvlGhkZLDagsBc4 DOO - 024
  0cgAvCwQJwGPC7LJaOLK8N DOO - 026
  2KmP7v1IgsIOyFmnErYHFm DOO - 025
  0fOM0FJenTIAj7EQ14H1Cs DOO - 027
  23YuZ0GIj4Gh6X75ZtZ44Q DOO - 028
  2Pz9e1lCHQHALY2sGVrC2F DOO - 029
```
Assistant: Which door do you mean?

### Example 3
User:
Please delete the door from the model, together with the relationships that depend on it.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
pool = ifc.by_type("IfcDoor")
print(len(pool), "IfcDoor", 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
40 IfcDoor in the model
  2NzPmYZy8kHAKF_OcdF5dY DOO - 020
  3cykYsTXT5GPjIlVdHFMKJ DOO - 024
  0vCRGc7QYNIBjLTY3wQyzr DOO - 021
  2Mym6zEGI6IwfPJ9F9G6In DOO - 023
  0k37rQVfEoJ9GEpSJxAkTg DOO - 013
  3yiL8yg65iHAEnHgO37fy1 DOO - 012
  20KcHXpBwPIfpF213fvU7c DOO - 012
  3PKKpBppW_HAW6ElI1r9kn DOO - 009
  3$7U7N_MfkHhEm6g4g3t0j DOO - 008
  3V4ahzUIYdIQgvh5gbq18P DOO - 017
  1ipz64_ZJGJ8vFXIXF4pWN DOO - 013
  101nm5GRhXGOKWbZHbVBs8 DOO - 015
  3yXmfW$8HAJQ_QX1uzB45y DOO - 009
  1ljAS$YNxmGgUIN3xZZ2_1 DOO - 008
  1p4e7vA2YeGOu5mHXT2Cew DOO - 013
  2Dc3WhUCvmGftq6sV5hBTW DOO - 012
  1B4iNUQnF_JxI3AWPLI6GE DOO - 013
  2uhYN9yfyzHwfB6CKqpPrb DOO - 015
  0amDT4j37rGAZWjzAAUM2y DOO - 024
  05qfsw1C5gHO0HDyh_r4Sg DOO - 012
```
Assistant: Which door do you mean?
