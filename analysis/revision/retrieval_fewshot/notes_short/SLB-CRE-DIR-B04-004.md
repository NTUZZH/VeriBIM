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
The client wants one change made to this model. Make 2 copies of the column nearest to the column named 'Columns_Rectangular:300x300mm:325813' on storey 'Ground Floor' at a spacing of 1 m to the south (-Y), named 'Post 420' and 'Post 421' in that order.

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

# find the element closest to the one the instruction names
storey = by_name("IfcBuildingStorey", "Ground Floor")
reference = by_name("IfcColumn", "Columns_Rectangular:300x300mm:325813")
hits = [geom.find_nearest(reference, "IfcColumn",
                          storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Ground Floor' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Ground Floor
named 'Columns_Rectangular:300x300mm:325813' -> 2Sw4U2s6bAdRSu3_Og4Aef IfcColumn Columns_Rectangular:300x300mm:325813
1 match(es)
3zlz432$53WQEASK7uO$25 IfcColumn Columns_Rectangular:300x300mm:332609
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
product = ifc.by_guid("3zlz432$53WQEASK7uO$25")
new_element = geom.array_elements(product, 2, 0.0, -1.0, 0.0, ["Post 420", "Post 421"])
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(new_element[0].GlobalId, new_element[0].is_a(), new_element[0].Name)
print(new_element[1].GlobalId, new_element[1].is_a(), new_element[1].Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
3HjmvlF5nBOONYVOmT56zm IfcColumn Post 420
1maKvbPZ99JwRzT6zelRbJ IfcColumn Post 421
model committed
```
Assistant: Completed. The column has been created and placed on its storey; the model was committed.

### Example 2
User:
The client wants one change made to this model. Make 3 copies of the slab with GlobalId '3sditPiPD6hBidP6ic9iGV' at a spacing of 4.46 m to the east (+X), named 'Deck 398', 'Deck 399' and 'Deck 400' in that order.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
found = [ifc.by_guid('3sditPiPD6hBidP6ic9iGV')]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
1 match(es)
3sditPiPD6hBidP6ic9iGV IfcSlab Floor:Floor-Grnd-Susp_65Scr-80Ins-100Blk-75PC:347719
```
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((4.46, 4.46),):
    print(stated, 'm', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
4.46 m = 4.46 m = 4460.0 file units
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# add the element, placed relative to the storey
product = ifc.by_guid('3sditPiPD6hBidP6ic9iGV')
added = geom.array_elements(product, 3, 4.46, 0.0, 0.0,
                            ['Deck 398', 'Deck 399', 'Deck 400'])
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(added[0].GlobalId, added[0].is_a(), added[0].Name)
print(added[1].GlobalId, added[1].is_a(), added[1].Name)
print(added[2].GlobalId, added[2].is_a(), added[2].Name)

# persist the edited model
commit()
print('model committed')
```
Tool result:
```
2tTllcMu57_94v8hhRgpRt IfcSlab Deck 398
330jtWK7TDOwdT5VrkJ_hC IfcSlab Deck 399
1BOOIBZfnC_OZC$6ETSx2C IfcSlab Deck 400
model committed
```
Assistant: Completed. The new slab is in the model; the model was committed.

### Example 3
User:
The client wants one change made to this model. Make 2 copies of the wall with GlobalId '1Veobsv750OAC9cFcolESP' at a spacing of 5.19 metres to the north (+Y), named 'Partition 476' and 'Partition 477' in that order.

IFC model path: <path to the working copy>
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# create the element and place it in the storey
element = ifc.by_guid('1Veobsv750OAC9cFcolESP')
created = geom.array_elements(element, 2, 0.0, 5.19, 0.0,
                              ['Partition 476', 'Partition 477'])
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(created[0].GlobalId, created[0].is_a(), created[0].Name)
print(created[1].GlobalId, created[1].is_a(), created[1].Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
3olZXhJTTAAfqZyV1urgud IfcWallStandardCase Partition 476
3LSvR47PL1Ov5eGakpZAe6 IfcWallStandardCase Partition 477
model committed
```
Assistant: Finished: the wall has been created and placed on its storey. The file on disk now holds the change.
