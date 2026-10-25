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
Add a new door named 'Doorset 839' in the wall on storey '01 - Entry Level' that stands about 19.7 m south (-Y) of wall 2UMN_OQKrAshZl3dHPul$r, 0.9 metres wide and 2.1 metres high, 0.81 metres along the wall from its start point and standing on the wall's base. Cut the opening it fills. Add an IfcRelSpaceBoundary between it and the space '7'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
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
storey = by_name('IfcBuildingStorey', '01 - Entry Level')
reference = ifc.by_guid('2UMN_OQKrAshZl3dHPul$r')
print('given ->', reference.GlobalId, reference.is_a(), reference.Name)
found = [geom.find_offset(reference, 'IfcWall', storey,
                          'south', 19.7)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named '01 - Entry Level' -> 298uW9PODAmgWwAQB0IyQ0 IfcBuildingStorey 01 - Entry Level
given -> 2UMN_OQKrAshZl3dHPul$r IfcWallStandardCase 基本墙:Interior - 138mm Partition (1-hr):149189
[('2UMN_OQKrAshZl3dHPukZL', 'IfcWallStandardCase', '基本墙:Interior - 138mm Partition (1-hr):152037')]
```
Assistant: Let me read the related elements before editing.
Assistant tool call execute_ifc_code:
```python
# the instruction names a space; find which one it is
for product in ifc.by_type('IfcSpace'):
    print(product.GlobalId, repr(product.Name), repr(getattr(product, 'LongName', None)))
```
Tool result:
```
1GE3M13VHAWxhxwcp39Emh '101' 'Vest.'
1GE3M13VHAWxhxwcp39EiJ '102' 'Lobby'
1GE3M13VHAWxhxwcp39EiI '121' 'Cafeteria'
1GE3M13VHAWxhxwcp39EiH '122' 'Prep/Dish'
1GE3M13VHAWxhxwcp39EiG '124' 'Dry Storage'
1GE3M13VHAWxhxwcp39EiN '125' 'Electrical'
1GE3M13VHAWxhxwcp39EiM '123' 'Conference'
1GE3M13VHAWxhxwcp39EiL '127' 'Office'
1GE3M13VHAWxhxwcp39EiK '126' 'Admin'
1GE3M13VHAWxhxwcp39Eih '128' 'Storage'
1GE3M13VHAWxhxwcp39Eig '129' 'Toilet'
1GE3M13VHAWxhxwcp39Eif '130' 'Stair'
1GE3M13VHAWxhxwcp39Eie '131' 'Corridor'
1GE3M13VHAWxhxwcp39Eil '119' 'Sprinkler'
1GE3M13VHAWxhxwcp39Eik '118' 'Electrical'
1GE3M13VHAWxhxwcp39Eij '117' 'Instruction'
1GE3M13VHAWxhxwcp39Eii '120' 'Lounge'
1GE3M13VHAWxhxwcp39EiZ '116' 'Conference'
1GE3M13VHAWxhxwcp39EiY '115' 'Instruction'
1GE3M13VHAWxhxwcp39EiX '114' 'Stair'
1GE3M13VHAWxhxwcp39Eid '112' 'Electrical'
1GE3M13VHAWxhxwcp39Eic '111' 'Lounge'
1GE3M13VHAWxhxwcp39Eib '110' 'Men'
1GE3M13VHAWxhxwcp39Eix '109' 'Women'
1GE3M13VHAWxhxwcp39Eiw '107' 'Corridor'
1GE3M13VHAWxhxwcp39Eiv '108' 'Instruction'
1GE3M13VHAWxhxwcp39Eiu '106' 'Instruction'
1GE3M13VHAWxhxwcp39Ei$ '105' 'Instruction'
1GE3M13VHAWxhxwcp39Ei_ '104' 'Instruction'
1GE3M13VHAWxhxwcp39Eiz '103' 'Conference'
1GE3M13VHAWxhxwcp39Eiy '132' 'Stair'
0L6PAa8RD5WhJxVZAT8X5Y '1' 'Service'
0L6PAa8RD5WhJxVZAT8X5a '2' 'Administration'
06NqO8bQX07hzFUDJa89ab '3' 'Cirrculation'
06NqO8bQX07hzFUDJa89a_ '4' 'Service'
06NqO8bQX07hzFUDJa89ay '5' 'Service'
06NqO8bQX07hzFUDJa89aw '6' 'Instruction'
06NqO8bQX07hzFUDJa89a
```
Assistant: Let me read the file's own length unit before I size anything.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1), (0.81, 0.81),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.9 metres = 0.9 m = 900.0 file units
2.1 metres = 2.1 m = 2100.0 file units
0.81 metres = 0.81 m = 810.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
host = ifc.by_guid('2UMN_OQKrAshZl3dHPukZL')
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
2UMN_OQKrAshZl3dHPukZL IfcWallStandardCase 基本墙:Interior - 138mm Partition (1-hr):152037
wall (m): {'start': 0.0, 'end': 2.315, 'near': -0.069, 'far': 0.069, 'base': 0.0, 'top': 3.8, 'length': 2.315, 'thickness': 0.139, 'height': 3.8}
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
host = ifc.by_guid('2UMN_OQKrAshZl3dHPukZL')
filling = geom.add_filling(host, 'IfcDoor', 'Doorset 839', width=0.9, height=2.1,
                           along=0.81, sill=0.0)
geom.add_space_boundary(ifc.by_guid('06NqO8bQX07hzFUDJa89au'), filling)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
print(filling.GlobalId, filling.is_a(), filling.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
1l2mWubL9BUuJTotN_ztA9 IfcDoor Doorset 839
model committed
```
Assistant: Done. The door has been created and placed on its storey, and the model has been saved.

### Example 2
User:
Add a new door named 'Doorset 928' in the IfcWall 1yxOhPF9554907YvC6JwH_, 0.9 metres wide and 2.1 metres high, 6.97 metres along the wall from its start point and standing on the wall's base. Cut the opening it fills. Add an IfcRelSpaceBoundary between it and the space '43'.

IFC model path: <path to the working copy>
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction names a space; find which one it is
for element in ifc.by_type('IfcSpace'):
    print(element.GlobalId, repr(element.Name), repr(getattr(element, 'LongName', None)))
```
Tool result:
```
1ipPmRMaj8p8GkkENAmcDO '40' 'Confernce Room'
1EiCkqOln11Ax5HRL1Y7Ep '41' 'Kitchen'
1EiCkqOln11Ax5HRL1Y7Es '42' 'Service Room'
1EiCkqOln11Ax5HRL1Y7E_ '43' 'Hallway'
0FJGhu$Db0Ow2TxdsN_PyR '44' 'Bedroom-04'
0FJGhu$Db0Ow2TxdsN_PyO '45' 'W.I.C'
0FJGhu$Db0Ow2TxdsN_PyT '46' 'Bath'
0FJGhu$Db0Ow2TxdsN_PyI '47' 'Bath'
0FJGhu$Db0Ow2TxdsN_PyN '48' 'Bedroom-05'
0FJGhu$Db0Ow2TxdsN_PyK '49' 'Bath'
0FJGhu$Db0Ow2TxdsN_Pyf '50' 'Bedroom-06'
0FJGhu$Db0Ow2TxdsN_PyZ '51' 'Bath'
0FJGhu$Db0Ow2TxdsN_PyW '52' 'W.I.C'
0FJGhu$Db0Ow2TxdsN_Pyb '53' 'Bedroom-01'
0FJGhu$Db0Ow2TxdsN_Pyw '54' 'Bath'
0FJGhu$Db0Ow2TxdsN_Py$ '55' 'Bedroom-02'
0FJGhu$Db0Ow2TxdsN_Pyy '56' 'Bath'
0FJGhu$Db0Ow2TxdsN_Pyn '57' 'Bedroom-03'
0FJGhu$Db0Ow2TxdsN_Pys '58' 'Restaurant'
1GjejW8Xn4SugeTM2GVNj3 '59' 'W.I.C'
1GjejW8Xn4SugeTM2GVNjC '60' 'Bath'
1GjejW8Xn4SugeTM2GVNj9 '61' 'Bedroom-07'
1GjejW8Xn4SugeTM2GVNjA '62' 'Bath'
1GjejW8Xn4SugeTM2GVNjN '63' 'W.I.C'
1GjejW8Xn4SugeTM2GVNjG '64' 'Bedroom-08'
1GjejW8Xn4SugeTM2GVNjT '65' 'W.I.C'
1GjejW8Xn4SugeTM2GVNjU '66' 'Bathroom'
1GjejW8Xn4SugeTM2GVNjR '67' 'Bedroom-09'
1GjejW8Xn4SugeTM2GVNja '68' 'Bath'
1GjejW8Xn4SugeTM2GVNjX '69' 'Bedroom-10'
1GjejW8Xn4SugeTM2GVNjY '70' 'Bath'
1GjejW8Xn4SugeTM2GVNjl '71' 'Bedroom-11'
2QcJCEEbz6n8$8xJ1QTAy5 '72' 'Bedroom-12'
2QcJCEEbz6n8$8xJ1QTAy6 '73' 'Bath'
2QcJCEEbz6n8$8xJ1QTAyx '74' 'Bedroom-13'
2QcJCEEbz6n8$8xJ1QTAyy '75' 'Bath'
2QcJCEEbz6n8$8xJ1QTAyn '76' 'Hallway'
2QcJCEEbz6n8$8xJ1QTAyo '77' 'Bath'
2QcJCEEbz6n8$8xJ1QTAyt '78' 'Bedroom-16'
2QcJCEEbz
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
# measure the wall before placing anything in it
host = ifc.by_guid("1yxOhPF9554907YvC6JwH_")
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
1yxOhPF9554907YvC6JwH_ IfcWallStandardCase Basic Wall:Exterior Load Bearing wall:536933
wall (m): {'start': 0.0, 'end': 14.688, 'near': -0.156, 'far': 0.156, 'base': 0.0, 'top': 18.4, 'length': 14.688, 'thickness': 0.312, 'height': 18.4}
```
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
host = ifc.by_guid("1yxOhPF9554907YvC6JwH_")
unit = geom.add_filling(host, "IfcDoor", "Doorset 928", width=0.9, height=2.1,
                        along=6.97, sill=0.0)
geom.add_space_boundary(ifc.by_guid("1EiCkqOln11Ax5HRL1Y7E_"), unit)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
print(unit.GlobalId, unit.is_a(), unit.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
2eQ_6nLhz3huXvka1ioq19 IfcDoor Doorset 928
model committed
```
Assistant: Completed. The new door is in the model; the model was committed.

### Example 3
User:
Please add a new door named 'Doorset 779' in the wall that bounds both the space '228' and the space '215', 0.9 metres wide and 2.1 metres high, 3.16 metres along the wall from its start point and standing on the wall's base. Cut the opening it fills. Add an IfcRelSpaceBoundary between it and the space '215'.

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

# find the element that bounds both named spaces
space_a = by_name('IfcSpace', '228')
space_b = by_name('IfcSpace', '215')
bounded = {}
for rel in ifc.by_type('IfcRelSpaceBoundary'):
    room = rel.RelatingSpace
    target = rel.RelatedBuildingElement
    if room is None or target is None:
        continue
    bounded.setdefault(target.GlobalId, set()).add(room.GlobalId)
matches = [e for e in ifc.by_type('IfcWall')
       if {space_a.GlobalId, space_b.GlobalId}
       <= bounded.get(e.GlobalId, set())]
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '228' -> 1NY$xO1fr0auJM3pbqEvCA IfcSpace 228
named '215' -> 1NY$xO1fr0auJM3pbqEvCX IfcSpace 215
1 match(es)
2_odAVP0X7VQL2u8kfZf5s IfcWallStandardCase Basic Wall:Interior - 4 1/4" Partition TYPE 10:1220333
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the instruction names a space; find which one it is
for target in ifc.by_type('IfcSpace'):
    print(target.GlobalId, repr(target.Name), repr(getattr(target, 'LongName', None)))
```
Tool result:
```
3Fn2p_WCD6zAmQfptzPOC0 'B1' 'MENS LOCKER ROOM'
3Fn2p_WCD6zAmQfptzPOC3 'B2' 'WOMENS LOCKER ROOM'
3Fn2p_WCD6zAmQfptzPOCT 'B3' 'ELEV LOBBY'
3Fn2p_WCD6zAmQfptzPOCV 'B5' 'RECYCLING ROOM'
3Fn2p_WCD6zAmQfptzPOCR 'B4' 'RECYCLING'
3Fn2p_WCD6zAmQfptzPOCL 'B6' 'ELEV MACHINE ROOM'
1dkawGn6z3dgzZrXi7BcO$ '1' 'Area'
3z6gbc2IbE5wjHjjHnCkeu '201' 'Room'
1NY$xO1fr0auJM3pbqEv2Q '149' 'Room'
1NY$xO1fr0auJM3pbqEv2M '150' 'Room'
1NY$xO1fr0auJM3pbqEv2I '151' 'Room'
1NY$xO1fr0auJM3pbqEv2C '152' 'Room'
1NY$xO1fr0auJM3pbqEv28 '153' 'Room'
1NY$xO1fr0auJM3pbqEv2A '154' 'Room'
1NY$xO1fr0auJM3pbqEv24 '155' 'Room'
1NY$xO1fr0auJM3pbqEv26 '156' 'Room'
1NY$xO1fr0auJM3pbqEv20 '157' 'Room'
1NY$xO1fr0auJM3pbqEv22 '158' 'Kitchen'
1NY$xO1fr0auJM3pbqEvDy '159' 'Room'
1NY$xO1fr0auJM3pbqEvD_ '160' 'Room'
1NY$xO1fr0auJM3pbqEvDu '161' 'Room'
1NY$xO1fr0auJM3pbqEvDw '162' 'Main Lobby'
1NY$xO1fr0auJM3pbqEvDq '163' 'Lift Lobby'
1NY$xO1fr0auJM3pbqEvDs '164' 'Room'
1NY$xO1fr0auJM3pbqEvDm '165' 'Room'
1NY$xO1fr0auJM3pbqEvDo '166' 'Room'
1NY$xO1fr0auJM3pbqEvDi '167' 'Room'
1NY$xO1fr0auJM3pbqEvDk '168' 'Room'
1NY$xO1fr0auJM3pbqEvDe '169' 'Room'
1NY$xO1fr0auJM3pbqEvDg '170' 'Room'
1NY$xO1fr0auJM3pbqEvDa '171' 'Room'
1NY$xO1fr0auJM3pbqEvDc '172' 'Room'
1NY$xO1fr0auJM3pbqEvDW '173' 'Room'
1NY$xO1fr0auJM3pbqEvDY '174' 'Exit Stairway 2'
1NY$xO1fr0auJM3pbqEvDS '175' 'Room'
1NY$xO1fr0auJM3pbqEvDU '176' 'Room'
1NY$xO1fr0auJM3pbqEvDO '177' 'Room'
1NY$xO1fr0auJM3pbqEvDQ '178' 'Room'
1NY$xO1fr0auJM3pbqEvDK '179' 'Room'
1NY$xO1fr0auJM3pbq
```
Assistant: I will convert the stated sizes into the file's unit first.
Assistant tool call execute_ifc_code:
```python
# the file's own length unit, and what the stated sizes are in it
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1), (3.16, 3.16),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.3048 metres
0.9 metres = 0.9 m = 2.952756 file units
2.1 metres = 2.1 m = 6.889764 file units
3.16 metres = 3.16 m = 10.367454 file units
```
Assistant tool call execute_ifc_code:
```python
# read the wall's own size, so the leaf is not guessed
host = ifc.by_guid('2_odAVP0X7VQL2u8kfZf5s')
print(host.GlobalId, host.is_a(), host.Name)
wall = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall.items() if not isinstance(v, str)})
```
Tool result:
```
2_odAVP0X7VQL2u8kfZf5s IfcWallStandardCase Basic Wall:Interior - 4 1/4" Partition TYPE 10:1220333
wall (m): {'start': 0.0, 'end': 9.601, 'near': -0.054, 'far': 0.054, 'base': 0.0, 'top': 3.6, 'length': 9.601, 'thickness': 0.108, 'height': 3.6}
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
host = ifc.by_guid('2_odAVP0X7VQL2u8kfZf5s')
unit = geom.add_filling(host, 'IfcDoor', 'Doorset 779', width=0.9, height=2.1,
                        along=3.16, sill=0.0)
geom.add_space_boundary(ifc.by_guid('1NY$xO1fr0auJM3pbqEvCX'), unit)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(unit.GlobalId, unit.is_a(), unit.Name)

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
2vGXhpww15s9zG1NAwWYyb IfcDoor Doorset 779
model committed
```
Assistant: Completed. The new door is in the model; the model was committed.
