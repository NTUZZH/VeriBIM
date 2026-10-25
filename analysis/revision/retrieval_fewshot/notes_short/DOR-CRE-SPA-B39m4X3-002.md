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
Add a new door named 'Doorset 644' in the wall on storey '1° PAVIMENTO - TÉRREO (N.O)' that stands about 10.9 m south (-Y) of the wall named 'Basic Wall:PAR - EXT - ALV - 10 - ACAB.EXT BASE - ACAB.INT BASE:886139', 0.9 metres wide and 2.1 metres high, with the middle of the leaf 1.47 metres along the wall from its start and standing on the wall's base. Cut the opening it fills.

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

storey = by_name('IfcBuildingStorey', '1° PAVIMENTO - TÉRREO (N.O)')
reference = by_name('IfcWall', 'Basic Wall:PAR - EXT - ALV - 10 - ACAB.EXT BASE - ACAB.INT BASE:886139')
hits = [geom.find_offset(reference, 'IfcWall', storey,
                         'south', 10.9)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '1° PAVIMENTO - TÉRREO (N.O)' -> 31MO7odvv0cAeswhRbr4Rh IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.O)
named 'Basic Wall:PAR - EXT - ALV - 10 - ACAB.EXT BASE - ACAB.INT BASE:886139' -> 1l5YQX3P17wemsuk3NHPB8 IfcWallStandardCase Basic Wall:PAR - EXT - ALV - 10 - ACAB.EXT BASE - ACAB.INT BASE:886139
1l5YQX3P17wemsuk3NHM5K IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882407
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * to_model

for target_guid in ('1l5YQX3P17wemsuk3NHM5K',):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(target, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWallStandardCase 1l5YQX3P17wemsuk3NHM5K Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882407
  origin (m): [7.108, 33.572, -0.05]
  contained in: ['1° PAVIMENTO - TÉRREO (N.O)']
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', to_model, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1), (1.47, 1.47),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / to_model, 6), 'file units')
```
Tool result:
```
one file length unit is 0.01 metres
0.9 metres = 0.9 m = 90.0 file units
2.1 metres = 2.1 m = 210.0 file units
1.47 metres = 1.47 m = 147.0 file units
```
Assistant: Before I place anything I need the numbers off the model.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('1l5YQX3P17wemsuk3NHM5K')
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
1l5YQX3P17wemsuk3NHM5K IfcWallStandardCase Basic Wall:PLACA - INT - PLACA CIMENTÍCIA ANTI FOGO TRF 24 HRS - 10 - ACAB.INT BASE:882407
wall (m): {'start': 0.0, 'end': 2.708, 'near': -0.05, 'far': 0.05, 'base': 0.0, 'top': 3.25, 'length': 2.708, 'thickness': 0.1, 'height': 3.25}
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('1l5YQX3P17wemsuk3NHM5K')
wall_box = geom.wall_box(host)
unit = geom.add_filling(host, 'IfcDoor', 'Doorset 644', width=0.9, height=2.1,
                        along=wall_box['start'] + 1.47, along_is_centre=True, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(unit.GlobalId, unit.is_a(), unit.Name)

commit()
print('model committed')
```
Tool result:
```
2SiRdaRWv5reBnj2uNsYS9 IfcDoor Doorset 644
model committed
```
Assistant: Finished: the new door is in the model. The file on disk now holds the change.

### Example 2
User:
Add a new door named 'Doorset 102' in the wall on storey 'Level 0' that stands about 20.5 m south (-Y) of the wall named 'Basic Wall:Exterior Load Bearing wall:323620', 0.9 metres wide and 2.1 metres high, with the middle of the leaf 8.17 metres along the wall from its start and standing on the wall's base. Cut the opening it fills.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
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

storey = by_name("IfcBuildingStorey", "Level 0")
reference = by_name("IfcWall", "Basic Wall:Exterior Load Bearing wall:323620")
found = [geom.find_offset(reference, "IfcWall", storey,
                          "south", 20.5)]
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 0' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Level 0
named 'Basic Wall:Exterior Load Bearing wall:323620' -> 3mC5rj4wL5ZfT78mw_nlsg IfcWallStandardCase Basic Wall:Exterior Load Bearing wall:323620
1 match(es)
3mC5rj4wL5ZfT78mw_nlqT IfcWallStandardCase Basic Wall:Exterior Load Bearing wall:323731
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3mC5rj4wL5ZfT78mw_nlqT")
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
3mC5rj4wL5ZfT78mw_nlqT IfcWallStandardCase Basic Wall:Exterior Load Bearing wall:323731
wall (m): {'start': 0.0, 'end': 13.992, 'near': -0.156, 'far': 0.156, 'base': 0.0, 'top': 9.4, 'length': 13.992, 'thickness': 0.312, 'height': 9.4}
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3mC5rj4wL5ZfT78mw_nlqT")
wall_box = geom.wall_box(host)
filling = geom.add_filling(host, "IfcDoor", "Doorset 102", width=0.9, height=2.1,
                           along=wall_box["start"] + 8.17, along_is_centre=True,
                           sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
print(filling.GlobalId, filling.is_a(), filling.Name)

commit()
print("model committed")
```
Tool result:
```
0iVLJ$IMfBs9f1mzqPaXG3 IfcDoor Doorset 102
model committed
```
Assistant: Finished: the door has been created and placed on its storey. The file on disk now holds the change.

### Example 3
User:
Please add a new door named 'Doorset 992' in the wall on storey 'Level 2' that stands about 4.3 m south (-Y) of the wall named 'Basic Wall:RC 300mm:466892', 0.9 metres wide and 2.1 metres high, with the middle of the leaf 3.11 metres along the wall from its start and standing on the wall's base. Cut the opening it fills.

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

storey = by_name('IfcBuildingStorey', 'Level 2')
reference = by_name('IfcWall', 'Basic Wall:RC 300mm:466892')
found = [geom.find_offset(reference, 'IfcWall', storey,
                          'south', 4.3)]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Level 2' -> 316DwlO2f6Muoj3Y_RU6Ed IfcBuildingStorey Level 2
named 'Basic Wall:RC 300mm:466892' -> 0GPDis$EfEDBfMOcU9bEXz IfcWall Basic Wall:RC 300mm:466892
[('0GPDis$EfEDBfMOcU9bEXy', 'IfcWall', 'Basic Wall:RC 300mm:466893')]
```
Assistant tool call execute_ifc_code:
```python
import ifcopenshell.util.unit
unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)
print('one file length unit is', unit_scale, 'metres')
for stated, metres in ((0.9, 0.9), (2.1, 2.1), (3.11, 3.11),):
    print(stated, 'metres', '=', round(metres, 6), 'm', '=', round(metres / unit_scale, 6), 'file units')
```
Tool result:
```
one file length unit is 0.001 metres
0.9 metres = 0.9 m = 900.0 file units
2.1 metres = 2.1 m = 2100.0 file units
3.11 metres = 3.11 m = 3110.0 file units
```
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('0GPDis$EfEDBfMOcU9bEXy')
print(host.GlobalId, host.is_a(), host.Name)
host_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in host_box.items() if not isinstance(v, str)})
```
Tool result:
```
0GPDis$EfEDBfMOcU9bEXy IfcWall Basic Wall:RC 300mm:466893
wall (m): {'start': 0.0, 'end': 4.7, 'near': -0.15, 'far': 0.15, 'base': 0.0, 'top': 3.78, 'length': 4.7, 'thickness': 0.3, 'height': 3.78}
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid('0GPDis$EfEDBfMOcU9bEXy')
host_box = geom.wall_box(host)
unit = geom.add_filling(host, 'IfcDoor', 'Doorset 992', width=0.9, height=2.1,
                        along=host_box['start'] + 3.11, along_is_centre=True, sill=0.0)
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
print(unit.GlobalId, unit.is_a(), unit.Name)

commit()
print('model committed')
```
Tool result:
```
3$IRWQcTj32xP1tHKMZtdF IfcDoor Doorset 992
model committed
```
Assistant: Completed. The new door is in the model; the model was committed.
