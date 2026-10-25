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
Please take out columns 0GPDis$EfEDBfMOcU9bEyi, 0GPDis$EfEDBfMOcU9bEsQ, and 0GPDis$EfEDBfMOcU9bElE from the model along with any relationships that rely on them.

IFC model path: <path to the working copy>
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
for target_guid in ('0GPDis$EfEDBfMOcU9bElE', '0GPDis$EfEDBfMOcU9bEsQ', '0GPDis$EfEDBfMOcU9bEyi'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
# every element the phrase covers, and what is left of its class
members = ('0GPDis$EfEDBfMOcU9bElE', '0GPDis$EfEDBfMOcU9bEsQ', '0GPDis$EfEDBfMOcU9bEyi',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcColumn', 'left in the model:', len(ifc.by_type('IfcColumn')))

# save the edit
commit()
print('model committed')
```
Tool result:
```
the phrase covers 3 element(s)
members still in the model: []
IfcColumn left in the model: 77
model committed
```
Assistant: Completed. The column has been removed; the model was committed.

### Example 2
User:
Remove the slab on storey 1MvMAoc2L5LRJwssbEGeC7 that stands between columns 2xE5Y1_v96EvoAyJC3mqVJ and 3UPoyR0HD5gQ1Y7251gstm from the model, together with the relationships that depend on it.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# find the element standing between the two the instruction names
storey = ifc.by_guid("1MvMAoc2L5LRJwssbEGeC7")
print('given ->', storey.GlobalId, storey.is_a(), storey.Name)
first = ifc.by_guid("2xE5Y1_v96EvoAyJC3mqVJ")
print('given ->', first.GlobalId, first.is_a(), first.Name)
second = ifc.by_guid("3UPoyR0HD5gQ1Y7251gstm")
print('given ->', second.GlobalId, second.is_a(), second.Name)
hits = [geom.find_between(first, second,
                          "IfcSlab", storey)]
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 1MvMAoc2L5LRJwssbEGeC7 IfcBuildingStorey Roof TOS
given -> 2xE5Y1_v96EvoAyJC3mqVJ IfcColumn HSS-Hollow Structural Section-Column:HSS6X6X5/16:280401
given -> 3UPoyR0HD5gQ1Y7251gstm IfcColumn HSS-Hollow Structural Section-Column:HSS6X6X5/16:339204
1 match(es)
0s3QBSVtvFbPR0D2qCxg_m IfcSlab Floor:1 1/2" Metal Roof Deck:327864
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
geom.delete_element(ifc.by_guid("0s3QBSVtvFbPR0D2qCxg_m"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("0s3QBSVtvFbPR0D2qCxg_m",) if g in present])

# write the model back to disk
commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Done. The slab has been removed, and the model has been saved.

### Example 3
User:
Delete the IfcSpace on storey 'Level 0' that stands between columns 0vmSW31414wgpK5ikRoa_W and 0vmSW31414wgpK5ikRoa_Y from the model, together with the relationships that depend on it.

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

# find the element standing between the two the instruction names
storey = by_name('IfcBuildingStorey', 'Level 0')
first = ifc.by_guid('0vmSW31414wgpK5ikRoa_W')
print('given ->', first.GlobalId, first.is_a(), first.Name)
second = ifc.by_guid('0vmSW31414wgpK5ikRoa_Y')
print('given ->', second.GlobalId, second.is_a(), second.Name)
matches = [geom.find_between(first, second,
                             'IfcSpace', storey)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 0' -> 3Zu5Bv0LOHrPC10026FoQQ IfcBuildingStorey Level 0
given -> 0vmSW31414wgpK5ikRoa_W IfcColumn Column_Rectangular:400x290:448605
given -> 0vmSW31414wgpK5ikRoa_Y IfcColumn Column_Rectangular:400x290:448607
0vmSW31414wgpK5ikRoaY2 IfcSpace 7
```
Assistant: Let me read the target before changing it.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * unit_scale

for target_guid in ('0vmSW31414wgpK5ikRoaY2',):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcSpace 0vmSW31414wgpK5ikRoaY2 7
  origin (m): [0.0, 0.0, 0.855]
  openings: 0  contained in: 0
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_element(ifc.by_guid('0vmSW31414wgpK5ikRoaY2'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('0vmSW31414wgpK5ikRoaY2',) if g in present])

# save the edit
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Done. The space and the relationships that depended on it are gone, and the model has been saved.
