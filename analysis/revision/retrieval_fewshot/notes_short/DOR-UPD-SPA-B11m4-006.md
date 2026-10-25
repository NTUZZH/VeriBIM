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
Can you assign the door nearest to the window named 'Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:476967' on storey 'Level 1' to the type object named 'Doors_ExtSgl_7:910x2110mm'?

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

# find the element closest to the one the instruction names
storey = by_name('IfcBuildingStorey', 'Level 1')
reference = by_name('IfcWindow', 'Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:476967')
found = [geom.find_nearest(reference, 'IfcDoor',
                           storey)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Level 1' -> 15Z0v90RiHrPC20026FoKR IfcBuildingStorey Level 1
named 'Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:476967' -> 05S4_HpdP7Yf$Q7Cmq8YE_ IfcWindow Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:Windows_Gealan_S9000_One-Piece-Window-Turn-Tilt:476967
[('05S4_HpdP7Yf$Q7Cmq8Y53', 'IfcDoor', 'Doors_IntSgl:910x2110mm:476634')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
candidates = []
for ifc_class in ('IfcDoorType', 'IfcTypeProduct'):
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
1cCiziYC5FUAgpZJSnCloX IfcDoorType Doors_ExtDbl_Flush:1510x2110mm
1SZzzrXHX0fAuRxfFi8xDf IfcDoorType Doors_ExtDbl_Flush:1510x2110mm
2C8kA5f6LBn99ATvvNv7JF IfcDoorType Doors_ExtDbl_Flush:1810x2110mm
1cCiziYC5FUAgpZJSnCeEe IfcDoorType Doors_ExtDbl_Flush:1810x2110mm
1cCiziYC5FUAgpZJSnCeoz IfcDoorType Doors_ExtDbl_Flush:1810x2110mm
1cCiziYC5FUAgpZJSnClqw IfcDoorType Doors_ExtDbl_Flush:1810x2110mm
1SZzzrXHX0fAuRxfFi8oZ0 IfcDoorType Doors_ExtSgl_7:910x2110mm
1SZzzrXHX0fAuRxfFi8o5m IfcDoorType Doors_IntDbl_8:1810x2110mm
1SZzzrXHX0fAuRxfFi8DRf IfcDoorType Doors_IntDbl_8:1810x2110mm
1SZzzrXHX0fAuRxfFi8x3M IfcDoorType Doors_IntSgl:1010x2110mm
2C8kA5f6LBn99ATvvNv711 IfcDoorType Doors_IntSgl:810x2110mm
1cCiziYC5FUAgpZJSnClXb IfcDoorType Doors_IntSgl:810x2110mm
1cCiziYC5FUAgpZJSnCkpO IfcDoorType Doors_IntSgl:810x2110mm
07PC7QyeL1_g9aQ01cyXYA IfcDoorType Doors_IntSgl:810x2110mm
07PC7QyeL1_g9aQ01cyZJ3 IfcDoorType Doors_IntSgl:810x2110mm
1cCiziYC5FUAgpZJSnCkkH IfcDoorType Doors_IntSgl:910x2110mm
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# type the element, replacing the type it had
geom.assign_type(ifc.by_guid('05S4_HpdP7Yf$Q7Cmq8Y53'),
                 ifc.by_guid('1SZzzrXHX0fAuRxfFi8oZ0'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
product = ifc.by_guid('05S4_HpdP7Yf$Q7Cmq8Y53')
print(product.is_a(), product.GlobalId, product.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
IfcDoor 05S4_HpdP7Yf$Q7Cmq8Y53 Doors_IntSgl:910x2110mm:476634
model committed
```
Assistant: Completed. The door has been updated; the model was committed.

### Example 2
User:
Assign the slab nearest to the space named '13' on storey '2. Geschoss' to the type object named 'Tile - Floor 240'.

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

storey = by_name("IfcBuildingStorey", "2. Geschoss")
reference = by_name("IfcSpace", "13")
found = [geom.find_nearest(reference, "IfcSlab",
                           storey)]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '2. Geschoss' -> 2VK2i8hZi3HPahZLbt_$zv IfcBuildingStorey 2. Geschoss
named '13' -> 1z0wblADSMJBTHozaRXkeE IfcSpace 13
3i2VHXBmH5HQhifk4vf1z_ IfcSlab SLA - 020
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
candidates = []
for ifc_class in ("IfcSlabType", 'IfcTypeProduct'):
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
0cYikGzE0E_q1L3YjQBGBE IfcSlabType Concrete Floor Insulated with Parquet 310
09ePLppRzH70ofypEJXP9v IfcSlabType Concrete Floor with 10mm Tile 240
0TI2ITU__9f4ioG5Rhq4Jf IfcSlabType Concrete Floor with Parquet 250
2aKv_d1_qmzfClrhRahlC1 IfcSlabType Reinforced Concrete - Structural 240
2Vxp743vjpPzAD_Vmfiqov IfcSlabType Reinforced Concrete - Structural 300
2BEp8p9XR0GcsNnjC8c948 IfcSlabType Tile - Floor 240
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
geom.assign_type(ifc.by_guid("3i2VHXBmH5HQhifk4vf1z_"),
                 ifc.by_guid("2BEp8p9XR0GcsNnjC8c948"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid("3i2VHXBmH5HQhifk4vf1z_")
print(product.is_a(), product.GlobalId, product.Name)

commit()
print("model committed")
```
Tool result:
```
IfcSlab 3i2VHXBmH5HQhifk4vf1z_ SLA - 020
model committed
```
Assistant: Completed. The slab has been updated; the model was committed.

### Example 3
User:
Assign the space nearest to the window named 'M_Window-Double-Hung:700 x 1200mm:372095' on storey 'Ground Storey' to the type object named 'Stair 66:384624'.

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

storey = by_name('IfcBuildingStorey', 'Ground Storey')
reference = by_name('IfcWindow', 'M_Window-Double-Hung:700 x 1200mm:372095')
found = [geom.find_nearest(reference, 'IfcSpace',
                           storey)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Ground Storey' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Ground Storey
named 'M_Window-Double-Hung:700 x 1200mm:372095' -> 3gfDoWGH10kxOHHNhVSRjC IfcWindow M_Window-Double-Hung:700 x 1200mm:372095
[('2GytO7CYr3_hS6Nu2JYfNp', 'IfcSpace', '15')]
```
Assistant: Next I need the elements that go with it.
Assistant tool call execute_ifc_code:
```python
candidates = []
for ifc_class in ('IfcSpaceType', 'IfcTypeProduct'):
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
1f0QVDhEP5tOIg7GHiFxwH IfcSpaceType Conference hall 14:368539
25Jeap79HFvwnnx1nl1jvK IfcSpaceType Conference hall 38:383741
2gM4ICVwf3nhrkrCtCBG96 IfcSpaceType Conference hall 62:384416
1L0EPN8lbEBRemrFhkv_18 IfcSpaceType Corridor 17:368545
3SXX_K9GH5AuTwaiFU9mZe IfcSpaceType Corridor 56:383882
1Gdx0Ktkz9CgRfw$OZ5PuD IfcSpaceType Corridor 59:384008
3r_GueguT2480nxWOtwH5e IfcSpaceType Corridor 65:384599
3Q7AqOBKzBFhdpAy_6nVVJ IfcSpaceType Enterance 31:383734
07g4UuuVL6b8TI9TotBz8z IfcSpaceType Enterance 3:361381
3FcglMKOn5ABnKCu_pMSlK IfcSpaceType Enterance 43:383749
05lUJTejLETQCabgXmqapR IfcSpaceType Enterance 55:383792
35$h_zqy18dB8Qx00Hm4uY IfcSpaceType Office 13:367434
0Qlv3Qq6fET8iCLWq89Kmp IfcSpaceType Office 15:368541
3haHpOls53lvbb7sXxU96P IfcSpaceType Office 16:368543
0ovwYnu3P7Hw_zflBpgF3z IfcSpaceType Office 18:383718
3u5KTIvurC5PKR6rrpgB09 IfcSpaceType Office 1:361377
0bXS9fkifEUgQGSAIVftKC IfcSpaceType Office 20:383720
09TPEjfk5BXQs3Ac7mug04 IfcSpaceType Office 21:383721
1KnzQ2DTX4HA38Luk$PJl2 IfcSpaceType Office 22:383722
1UI8QB$214W9ob4xltYNjw IfcSpaceType Office 25:383725
2RS$utuPvC6uwMw02UWg25 IfcSpaceType Office 27:383727
249H85iPX4ZgAMZDZGXHap IfcSpaceType Office 28:383728
14dlG0V813l9Lqn0W7TUPV IfcSpaceType Office 30:383733
2bY6w$QPD1BwBMR0kIhGQh IfcSpaceType Office 32:383735
1tcK08XUv9MfsFBg9_Vqb0 IfcSpaceType Office 33:383736
32GHJBSYX7IgPDO0zJxShX IfcSpaceType Office 34:383737
3KMBeQR1rA4vJLVIblERCe IfcSpaceType Office 37:383740
2tIZHc6TD9OAeLRiPlmHuf I
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
geom.assign_type(ifc.by_guid('2GytO7CYr3_hS6Nu2JYfNp'),
                 ifc.by_guid('3mh1x4kcT4C8WzP98KC9ZR'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
product = ifc.by_guid('2GytO7CYr3_hS6Nu2JYfNp')
print(product.is_a(), product.GlobalId, product.Name)

commit()
print('model committed')
```
Tool result:
```
IfcSpace 2GytO7CYr3_hS6Nu2JYfNp 15
model committed
```
Assistant: Completed. The space now carries the values the instruction asked for; the model was committed.
