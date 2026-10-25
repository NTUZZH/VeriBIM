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
Assign the window on storey 'Level 2' that stands about 7.1 m east (+X) of the window named 'M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686' to the type object named '4835mm x 2420mm'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

# find the element at the stated offset from the named neighbour
storey = by_name('IfcBuildingStorey', 'Level 2')
reference = by_name('IfcWindow', 'M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686')
found = [geom.find_offset(reference, 'IfcWindow', storey,
                          'east', 7.1)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 2' -> 1xS3BCk291UvhgP2dvNMQJ IfcBuildingStorey Level 2
named 'M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686' -> 1hOSvn6df7F8_7GcBWlSXO IfcWindow M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686
1 match(es)
1l0GAJtRTFv8$zmKJOH4pU IfcWindow M_Fixed:2800mm x 2410mm:2800mm x 2410mm:181096
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
pool = []
for ifc_class in ('IfcWindowType', 'IfcTypeProduct'):
    try:
        pool = list(ifc.by_type(ifc_class))
    except Exception:
        pool = []
    if pool:
        break
for target in sorted(pool, key=lambda t: (t.Name or '')):
    print(target.GlobalId, target.is_a(), target.Name)
```
Tool result:
```
2OBrcmyk58NupXoVOHUsk4 IfcFurnitureType 0610 x 0610 x 0610mm
2S67XPaW1CHg1jrMmPps_z IfcDoorStyle 0762 x 2032mm
2klOFZffH6WQFlV10uM1wF IfcDoorStyle 0762 x 2032mm
0pB8AT2hfEtQhuGzBhCesc IfcDoorStyle 0813 x 2420mm
20jGDLfPn5F8bVb$wXnrpD IfcDoorStyle 0864 x 2032mm
3HoP2o48vFlPEmd6lsQCdI IfcDoorStyle 0864 x 2032mm
2OBrcmyk58NupXoVOHUsk0 IfcFurnitureType 0915 x 1830 x 0457mm
0wkEuT1wr1kOyafLY4vy9t IfcFurnitureType 1000 mm
0iEHWY1$XA8eQeeULq4jRb IfcFurnitureType 1000 mm
1aj$VJZFn2TxepZUBcKp0h IfcFurnitureType 1000mm
0wkEuT1wr1kOyafLY4v$qt IfcFurnitureType 1000mm
1aj$VJZFn2TxepZUBcKp3g IfcFurnitureType 1000mm
29AJardrPBzPvPF6$RkL5e IfcWindowStyle 1180 x 1170mm
28VDfyq51BtxN68z6Brpvs IfcDoorStyle 1250mm x 2010mm
2OBrcmyk58NupXoVOHUvfp IfcFurnitureType 1525 x 2007mm - Queen
2OBrcmyk58NupXoVOHUsvk IfcFurnitureType 1830mm
2OBrcmyk58NupXoVOHUvfz IfcFurnitureType 1981 x 2032mm - King
1Hp7d9GfPDLRfj2gMllatM IfcWindowStyle 2800mm x 2410mm
2gRXFgjRn2HPE$YoDLX0$a IfcFurnitureType 450 x 450 mm
1Jx6Wzbs17ugoFEefHo1BC IfcWindowStyle 4835mm x 2420mm
3gitB6$NLAKweiR$I8cy2i IfcFurnitureType 600mm Depth
0EJeriCD16NwEG0qluVLDa IfcFurnitureType 600mm Depth
1aj$VJZFn2TxepZUBcKpCz IfcFurnitureType 600mm Depth
1aj$VJZFn2TxepZUBcKpCQ IfcFurnitureType 600mm Depth
2gRXFgjRn2HPE$YoDLX0tW IfcFurnitureType 650 x 450 mm
2gRXFgjRn2HPE$YoDLX0rd IfcFurnitureType 650 x 450 mm
1DUB3WxH5BFQb5h$$S4JfA IfcWindowStyle 750mm x 2200mm
0wkEuT1wr1kOyafLY4vyuY IfcFurnitureType 800 mm
0wkEuT1wr1kOyafLY4vy2N IfcFurnitureType 80
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# type the element, replacing the type it had
geom.assign_type(ifc.by_guid('1l0GAJtRTFv8$zmKJOH4pU'),
                 ifc.by_guid('1Jx6Wzbs17ugoFEefHo1BC'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
target = ifc.by_guid('1l0GAJtRTFv8$zmKJOH4pU')
print(target.is_a(), target.GlobalId, target.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
IfcWindow 1l0GAJtRTFv8$zmKJOH4pU M_Fixed:2800mm x 2410mm:2800mm x 2410mm:181096
model committed
```
Assistant: Finished: the window has been updated. The file on disk now holds the change.

### Example 2
User:
Assign the window on storey 'PLANTA BAJA' that stands about 8.4 m east (+X) of the window with GlobalId '2cWa1FKRT0EuVuZrnLYh$w' to the type object named '1.20x1.20 m'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

storey = by_name("IfcBuildingStorey", "PLANTA BAJA")
reference = ifc.by_guid("2cWa1FKRT0EuVuZrnLYh$w")
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
hits = [geom.find_offset(reference, "IfcWindow", storey,
                         "east", 8.4)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
named 'PLANTA BAJA' -> 0OCkzK25HA0wxSqRSYLGvE IfcBuildingStorey PLANTA BAJA
given -> 2cWa1FKRT0EuVuZrnLYh$w IfcWindow Ventana 2 hojas:1.80x1.50 m:2169923
[('3Bw42jQbz7jP5t1Eleiv0U', 'IfcWindow', 'Simple 1 hoja:traga luz 400x600 mm:2065931')]
```
Assistant tool call execute_ifc_code:
```python
options = []
for ifc_class in ("IfcWindowType", 'IfcTypeProduct'):
    try:
        options = list(ifc.by_type(ifc_class))
    except Exception:
        options = []
    if options:
        break
for product in sorted(options, key=lambda t: (t.Name or '')):
    print(product.GlobalId, product.is_a(), product.Name)
```
Tool result:
```
31BrNcu85BxOlgMHdrRfBe IfcDoorStyle 0700 x 2000 mm
31BrNcu85BxOlgMHdrRfEN IfcDoorStyle 0700 x 2000 mm
31BrNcu85BxOlgMHdrRfGg IfcDoorStyle 0800 x 2000 mm
31BrNcu85BxOlgMHdrRfHn IfcDoorStyle 0800 x 2000 mm
2aGbxcRfH7xwAj5kUAxyIi IfcWindowStyle 1.20x1.20 m
2aGbxcRfH7xwAj5kUAxy9L IfcWindowStyle 1.80x1.50 m
2cWa1FKRT0EuVuZqbLYhyP IfcWindowStyle 1.80x1.50 m 2
1O3JWq2N5BiPz3JKZh57zr IfcDoorStyle 1000 x 2000 mm
15jujQfM94gehHBvHb9_Hr IfcFurnitureType 1000mm x 380mm x 810mm
2OpkTqOTn4zw4adR6aX946 IfcBuildingElementProxyType 100A
1qYVpltiX9QxhxxjX9AONc IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AOVc IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AVdz IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AVkP IfcColumnType 100x100xSHS
15jujQfM94gehHBvHb9vsu IfcFurnitureType 1200x800x580 mm
32guoVkp9BTPap7ya3UNSU IfcFurnitureType 160 x 80 cm - Madera claro
0IHaEyVdj6jALKq0JAuysF IfcFurnitureType 2000mm x 1800mm
2GS3yY3ErEehJVLEBLdINR IfcFurnitureType 2000x1800
2RHyAzft50VP4V5IUHqEWF IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEpo IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEt7 IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqExb IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqExZ IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEuD IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEux IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEuv IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEv7 IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEvV IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEvT IfcColumnType 250 x 250 mm
```
Assistant tool call execute_ifc_code:
```python
geom.assign_type(ifc.by_guid("3Bw42jQbz7jP5t1Eleiv0U"),
                 ifc.by_guid("2aGbxcRfH7xwAj5kUAxyIi"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid("3Bw42jQbz7jP5t1Eleiv0U")
print(product.is_a(), product.GlobalId, product.Name)

commit()
print("model committed")
```
Tool result:
```
IfcWindow 3Bw42jQbz7jP5t1Eleiv0U Simple 1 hoja:traga luz 400x600 mm:2065931
model committed
```
Assistant: Done. The window now carries the values the instruction asked for, and the model has been saved.

### Example 3
User:
Please assign the door on storey 'PLANTA BAJA' that stands about 7.1 m east (+X) of the column named 'Pilar rectangular hormigón:250 x 250 mm:1969268' to the type object named '1000 x 2000 mm'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
def by_name(ifc_class, wanted):
    found = [e for e in ifc.by_type(ifc_class)
             if (e.Name or '').strip() == wanted]
    if not found:
        found = [e for e in ifc.by_type(ifc_class)
                 if (getattr(e, 'LongName', None) or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), '->', e.GlobalId, e.is_a(), e.Name)
    if len(found) != 1:
        raise ValueError('%d %s are named %r' % (len(found), ifc_class, wanted))
    return found[0]


def by_name_on_storey(ifc_class, wanted, storey):
    found = [e for e in on_storey(storey.GlobalId, ifc_class)
             if (e.Name or '').strip() == wanted]
    for e in found:
        print('named', repr(wanted), 'on', storey.Name, '->', e.GlobalId, e.is_a())
    if len(found) != 1:
        raise ValueError('%d %s on storey %r are named %r'
                         % (len(found), ifc_class, storey.Name, wanted))
    return found[0]

# find the element at the stated offset from the named neighbour
storey = by_name("IfcBuildingStorey", "PLANTA BAJA")
reference = by_name("IfcColumn", "Pilar rectangular hormigón:250 x 250 mm:1969268")
matches = [geom.find_offset(reference, "IfcDoor", storey,
                            "east", 7.1)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'PLANTA BAJA' -> 0OCkzK25HA0wxSqRSYLGvE IfcBuildingStorey PLANTA BAJA
named 'Pilar rectangular hormigón:250 x 250 mm:1969268' -> 2RHyAzft50VP4V7IUHqEpo IfcColumn Pilar rectangular hormigón:250 x 250 mm:1969268
31BrNcu85BxOlgMGprRf8B IfcDoor Simple 4 Paneles:0700 x 2000 mm:1950876
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
candidates = []
for ifc_class in ("IfcDoorType", 'IfcTypeProduct'):
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
31BrNcu85BxOlgMHdrRfBe IfcDoorStyle 0700 x 2000 mm
31BrNcu85BxOlgMHdrRfEN IfcDoorStyle 0700 x 2000 mm
31BrNcu85BxOlgMHdrRfGg IfcDoorStyle 0800 x 2000 mm
31BrNcu85BxOlgMHdrRfHn IfcDoorStyle 0800 x 2000 mm
2aGbxcRfH7xwAj5kUAxyIi IfcWindowStyle 1.20x1.20 m
2aGbxcRfH7xwAj5kUAxy9L IfcWindowStyle 1.80x1.50 m
2cWa1FKRT0EuVuZqbLYhyP IfcWindowStyle 1.80x1.50 m 2
1O3JWq2N5BiPz3JKZh57zr IfcDoorStyle 1000 x 2000 mm
15jujQfM94gehHBvHb9_Hr IfcFurnitureType 1000mm x 380mm x 810mm
2OpkTqOTn4zw4adR6aX946 IfcBuildingElementProxyType 100A
1qYVpltiX9QxhxxjX9AONc IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AOVc IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AVdz IfcColumnType 100x100xSHS
1qYVpltiX9QxhxxjX9AVkP IfcColumnType 100x100xSHS
15jujQfM94gehHBvHb9vsu IfcFurnitureType 1200x800x580 mm
32guoVkp9BTPap7ya3UNSU IfcFurnitureType 160 x 80 cm - Madera claro
0IHaEyVdj6jALKq0JAuysF IfcFurnitureType 2000mm x 1800mm
2GS3yY3ErEehJVLEBLdINR IfcFurnitureType 2000x1800
2RHyAzft50VP4V5IUHqEWF IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEpo IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEt7 IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqExb IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqExZ IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEuD IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEux IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEuv IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEv7 IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEvV IfcColumnType 250 x 250 mm
2RHyAzft50VP4V5IUHqEvT IfcColumnType 250 x 250 mm
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# type the element, replacing the type it had
geom.assign_type(ifc.by_guid("31BrNcu85BxOlgMGprRf8B"),
                 ifc.by_guid("1O3JWq2N5BiPz3JKZh57zr"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
target = ifc.by_guid("31BrNcu85BxOlgMGprRf8B")
print(target.is_a(), target.GlobalId, target.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcDoor 31BrNcu85BxOlgMGprRf8B Simple 4 Paneles:0700 x 2000 mm:1950876
model committed
```
Assistant: Done. The door has been updated, and the model has been saved.
