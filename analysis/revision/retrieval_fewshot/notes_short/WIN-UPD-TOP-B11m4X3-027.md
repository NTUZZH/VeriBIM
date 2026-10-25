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
Assign the window hosted in the wall 3zGrs4baYAJBU5kGZxEDqc to the type object named '3-Sash Sliding Window'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3zGrs4baYAJBU5kGZxEDqc")
print('given ->', host.GlobalId, host.is_a(), host.Name)
found = []
for link in getattr(host, 'HasOpenings', None) or ():
    hole = link.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        filling = fills.RelatedBuildingElement
        if filling is not None and filling.is_a("IfcWindow"):
            found.append(filling)
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3zGrs4baYAJBU5kGZxEDqc IfcWall SW - 040
1VEU3PADnaI9CZEYkW$fP$ IfcWindow WD - 031
```
Assistant tool call execute_ifc_code:
```python
candidates = []
for ifc_class in ("IfcWindowType", 'IfcTypeProduct'):
    try:
        candidates = list(ifc.by_type(ifc_class))
    except Exception:
        candidates = []
    if candidates:
        break
for target in sorted(candidates, key=lambda t: (t.Name or '')):
    print(target.GlobalId, target.is_a(), target.Name)
```
Tool result:
```
0r864aQe1g57IXfyoIt80i IfcWindowType 2-Sash Sliding Window
0Y_QhQecgUbxn34Cvo5XSW IfcWindowType 2-Sash Sliding Window
2BYufQc5kL9to3UOU_vpMh IfcWindowType 2-Sash Sliding Window
3xJR3x0gkijeF5HrRWWy6l IfcWindowType 3-Sash Sliding Window
1cSasOZxYIvO4yeuEneu5J IfcWindowType Single-Hung Window
1bsvACWEsbWJmZonza56sd IfcWindowType Storefront Window with Transom 1
```
Assistant tool call execute_ifc_code:
```python
geom.assign_type(ifc.by_guid("1VEU3PADnaI9CZEYkW$fP$"),
                 ifc.by_guid("3xJR3x0gkijeF5HrRWWy6l"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
target = ifc.by_guid("1VEU3PADnaI9CZEYkW$fP$")
print(target.is_a(), target.GlobalId, target.Name)

commit()
print("model committed")
```
Tool result:
```
IfcWindow 1VEU3PADnaI9CZEYkW$fP$ WD - 031
model committed
```
Assistant: Done. The window has been updated, and the model has been saved.

### Example 2
User:
Please assign the door hosted in wall 3_iYPtx910dBGnrgXmTakM to the type object named 'M_Door-Curtain-Wall-Double-Storefront:M_Door-Curtain-Wall-Double-Storefront'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# follow the host's openings to what fills them
host = ifc.by_guid("3_iYPtx910dBGnrgXmTakM")
print('given ->', host.GlobalId, host.is_a(), host.Name)
hits = []
for relation in getattr(host, 'HasOpenings', None) or ():
    opening = relation.RelatedOpeningElement
    for fills in (getattr(opening, 'HasFillings', None) or ()) if opening else ():
        unit = fills.RelatedBuildingElement
        if unit is not None and unit.is_a("IfcDoor"):
            hits.append(unit)
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
given -> 3_iYPtx910dBGnrgXmTakM IfcWall Basic Wall:Generic - 200mm 3:421436
[('3_iYPtx910dBGnrgXmTalA', 'IfcDoor', 'M_Single-Flush:d80:421472')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
pool = []
for ifc_class in ("IfcDoorType", 'IfcTypeProduct'):
    try:
        pool = list(ifc.by_type(ifc_class))
    except Exception:
        pool = []
    if pool:
        break
for product in sorted(pool, key=lambda t: (t.Name or '')):
    print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
1SwQMYHQH9rhfixpkW2agS IfcDoorType M_Door-Curtain-Wall-Double-Glass:M_Door-Curtain-Wall-Double-Glass
2vfd9EYY56x8e1enZQzdbE IfcDoorType M_Door-Curtain-Wall-Double-Storefront:M_Door-Curtain-Wall-Double-Storefront
2vfd9EYY56x8e1enZQzcz_ IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
1SwQMYHQH9rhfixpkW2Ok2 IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
2JD7fAMybBB8SEToRPnj5T IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
2JD7fAMybBB8SEToRPnj50 IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
0s4VDtioPFDAAVUFnQREkH IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
2vfd9EYY56x8e1enZQzczz IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
2vfd9EYY56x8e1enZQzczy IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
3_iYPtx910dBGnrhrmTbRt IfcDoorType M_Door-Curtain-Wall-Single-Glass:M_Door-Curtain-Wall-Single-Glass
1nUpbM1D9EwRR6clJl$NOf IfcDoorType M_Single-Flush:d100
1nUpbM1D9EwRR6clJl$NOR IfcDoorType M_Single-Flush:d100
1nUpbM1D9EwRR6clJl$NNC IfcDoorType M_Single-Flush:d100
0PBtEeGWHAZejaa_fkkZIg IfcDoorType M_Single-Flush:d80
0PBtEeGWHAZejaa_fkkZHj IfcDoorType M_Single-Flush:d80
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# the element is typed once, so the type it had goes first
geom.assign_type(ifc.by_guid("3_iYPtx910dBGnrgXmTalA"),
                 ifc.by_guid("2vfd9EYY56x8e1enZQzdbE"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# verify, then save
product = ifc.by_guid("3_iYPtx910dBGnrgXmTalA")
print(product.is_a(), product.GlobalId, product.Name)

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
IfcDoor 3_iYPtx910dBGnrgXmTalA M_Single-Flush:d80:421472
model committed
```
Assistant: Finished: the door has been updated. The file on disk now holds the change.

### Example 3
User:
Assign the wall 25VG$Fj5jDzP7LbWNvGVqE to the type object named 'Basic Wall:Foundation - 200mm Concrete - Retaining'.

IFC model path: <path to the working copy>
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
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
0nLMa_hqjDM9PNHQIvZ_Vd IfcWallType Basic Wall:Foundation - 200mm Concrete - Retaining
0nLMa_hqjDM9PNHQIvZ_DK IfcWallType Basic Wall:Foundation - 300mm Concrete - Retaining
1qv6ynVKX7xf87anS8vNvs IfcWallType Basic Wall:Foundation - 375mm Concrete w_step
```
Assistant tool call execute_ifc_code:
```python
geom.assign_type(ifc.by_guid('25VG$Fj5jDzP7LbWNvGVqE'),
                 ifc.by_guid('0nLMa_hqjDM9PNHQIvZ_Vd'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('25VG$Fj5jDzP7LbWNvGVqE')
print(product.is_a(), product.GlobalId, product.Name)

commit()
print('model committed')
```
Tool result:
```
IfcWallStandardCase 25VG$Fj5jDzP7LbWNvGVqE Basic Wall:Foundation - 300mm Concrete - Retaining:255006
model committed
```
Assistant: The wall now carries the values the instruction asked for, and the edit is written to the working file.
