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
Delete only the IfcWall elements on the storey with ID 1MvMAoc2L5LRJwssbEGS7s longer than 5.50 m from the model, together with the relationships that depend on them.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# list every element the instruction's phrase covers
scope = ifc.by_guid('1MvMAoc2L5LRJwssbEGS7s')
print('given ->', scope.GlobalId, scope.is_a(), scope.Name)
options = geom.on_storey(scope, 'IfcWall')
print(len(options), 'candidate(s) in scope')
found = [e for e in options
       if (geom.measure(e, 'plan_length') or 0.0)
       > 5.5]
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 1MvMAoc2L5LRJwssbEGS7s IfcBuildingStorey First Floor
15 candidate(s) in scope
0D7wXtGvf6SwQM22Y6cJSj IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:228715
0D7wXtGvf6SwQM22Y6cJUB IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:228813
0D7wXtGvf6SwQM22Y6cSfP IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:229407
0D7wXtGvf6SwQM22Y6cSX6 IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:229888
0D7wXtGvf6SwQM22Y6cSb7 IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:230145
```
Assistant: I will check the element's class and position first.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

to_model = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    placement_matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return placement_matrix[:3, 3] * to_model

for target_guid in ('0D7wXtGvf6SwQM22Y6cJSj', '0D7wXtGvf6SwQM22Y6cJUB', '0D7wXtGvf6SwQM22Y6cSX6', '0D7wXtGvf6SwQM22Y6cSb7', '0D7wXtGvf6SwQM22Y6cSfP'):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWallStandardCase 0D7wXtGvf6SwQM22Y6cJSj Basic Wall:Retaining - 14" Concrete:228715
  origin (m): [219939.26, 907195.415, 58.191]
  openings: 0  contained in: 1
IfcWallStandardCase 0D7wXtGvf6SwQM22Y6cJUB Basic Wall:Retaining - 14" Concrete:228813
  origin (m): [219911.428, 907206.469, 58.191]
  openings: 0  contained in: 1
IfcWallStandardCase 0D7wXtGvf6SwQM22Y6cSX6 Basic Wall:Retaining - 14" Concrete:229888
  origin (m): [219935.239, 907184.988, 58.191]
  openings: 0  contained in: 1
IfcWallStandardCase 0D7wXtGvf6SwQM22Y6cSb7 Basic Wall:Retaining - 14" Concrete:230145
  origin (m): [219906.095, 907193.27, 56.54]
  openings: 0  contained in: 1
IfcWallStandardCase 0D7wXtGvf6SwQM22Y6cSfP Basic Wall:Retaining - 14" Concrete:229407
  origin (m): [219931.599, 907175.978, 56.54]
  openings: 0  contained in: 1
```
Assistant tool call execute_ifc_code:
```python
# remove the element; a door or a window it holds cannot stay without it
for target_guid in ('0D7wXtGvf6SwQM22Y6cJSj', '0D7wXtGvf6SwQM22Y6cJUB', '0D7wXtGvf6SwQM22Y6cSX6', '0D7wXtGvf6SwQM22Y6cSb7', '0D7wXtGvf6SwQM22Y6cSfP'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
# every element the phrase covers, and what is left of its class
members = ('0D7wXtGvf6SwQM22Y6cJSj', '0D7wXtGvf6SwQM22Y6cJUB', '0D7wXtGvf6SwQM22Y6cSX6', '0D7wXtGvf6SwQM22Y6cSb7', '0D7wXtGvf6SwQM22Y6cSfP',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 5 element(s)
members still in the model: []
IfcWall left in the model: 34
model committed
```
Assistant: Done. The wall has been removed, and the model has been saved.

### Example 2
User:
Delete only the IfcWall elements on storey 'T/FDN' longer than 8.00 m from the model, together with the relationships that depend on them.

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

scope = by_name('IfcBuildingStorey', 'T/FDN')
pool = geom.on_storey(scope, 'IfcWall')
print(len(pool), 'candidate(s) in scope')
found = [e for e in pool
       if (geom.measure(e, 'plan_length') or 0.0)
       > 8.0]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'T/FDN' -> 1xS3BCk291UvhgP2dvNsgp IfcBuildingStorey T/FDN
7 candidate(s) in scope
[('2O2Fr$t4X7Zf8NOew3FK80', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (417mm):140479'), ('2O2Fr$t4X7Zf8NOew3FK9N', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (417mm):140520'), ('2O2Fr$t4X7Zf8NOew3FKEr', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (417mm):140554'), ('2O2Fr$t4X7Zf8NOew3FKE5', 'IfcWallStandardCase', 'Basic Wall:Foundation - Concrete (417mm):140602')]
```
Assistant: I will check the element's class and position first.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * scale

for target_guid in ('2O2Fr$t4X7Zf8NOew3FK80', '2O2Fr$t4X7Zf8NOew3FK9N', '2O2Fr$t4X7Zf8NOew3FKE5', '2O2Fr$t4X7Zf8NOew3FKEr'):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWallStandardCase 2O2Fr$t4X7Zf8NOew3FK80 Basic Wall:Foundation - Concrete (417mm):140479
  origin (m): [0.0, -0.208, -1.25]
  openings: 0  contained in: 1
IfcWallStandardCase 2O2Fr$t4X7Zf8NOew3FK9N Basic Wall:Foundation - Concrete (417mm):140520
  origin (m): [8.592, -0.417, -1.25]
  openings: 0  contained in: 1
IfcWallStandardCase 2O2Fr$t4X7Zf8NOew3FKE5 Basic Wall:Foundation - Concrete (417mm):140602
  origin (m): [0.209, -17.383, -1.25]
  openings: 0  contained in: 1
IfcWallStandardCase 2O2Fr$t4X7Zf8NOew3FKEr Basic Wall:Foundation - Concrete (417mm):140554
  origin (m): [8.383, -17.592, -1.25]
  openings: 0  contained in: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
for target_guid in ('2O2Fr$t4X7Zf8NOew3FK80', '2O2Fr$t4X7Zf8NOew3FK9N', '2O2Fr$t4X7Zf8NOew3FKE5', '2O2Fr$t4X7Zf8NOew3FKEr'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
members = ('2O2Fr$t4X7Zf8NOew3FK80', '2O2Fr$t4X7Zf8NOew3FK9N', '2O2Fr$t4X7Zf8NOew3FKE5', '2O2Fr$t4X7Zf8NOew3FKEr',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 4 element(s)
members still in the model: []
IfcWall left in the model: 53
model committed
```
Assistant: The wall and the relationships that depended on it are gone. The edited model is committed.

### Example 3
User:
Delete only the IfcWall elements on storey 'Level 1' longer than 1.00 m from the model, together with the relationships that depend on them.

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

scope = by_name('IfcBuildingStorey', 'Level 1')
candidates = geom.on_storey(scope, 'IfcWall')
print(len(candidates), 'candidate(s) in scope')
hits = [e for e in candidates
       if (geom.measure(e, 'plan_length') or 0.0)
       > 1.0]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Level 1' -> 2dTVw6MAP9_ujUIdKX4Ska IfcBuildingStorey Level 1
4 candidate(s) in scope
3AR$8LNN18Rh_Zduon5Yd0 IfcWall Basic Wall:Generic - 225mm Masonry:207022
3AR$8LNN18Rh_Zduon5YXw IfcWall Basic Wall:Generic - 225mm Masonry:207124
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(product):
    placement = getattr(product, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale

for target_guid in ('3AR$8LNN18Rh_Zduon5YXw', '3AR$8LNN18Rh_Zduon5Yd0'):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(product, 'HasOpenings', None) or ()), ' contained in:', len(getattr(product, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWall 3AR$8LNN18Rh_Zduon5YXw Basic Wall:Generic - 225mm Masonry:207124
  origin (m): [-4.893, -15.622, 2.1]
  openings: 0  contained in: 1
IfcWall 3AR$8LNN18Rh_Zduon5Yd0 Basic Wall:Generic - 225mm Masonry:207022
  origin (m): [-8.913, -16.063, 2.1]
  openings: 0  contained in: 1
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
geom.delete_element(ifc.by_guid('3AR$8LNN18Rh_Zduon5YXw'))
geom.delete_element(ifc.by_guid('3AR$8LNN18Rh_Zduon5Yd0'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
members = ('3AR$8LNN18Rh_Zduon5YXw', '3AR$8LNN18Rh_Zduon5Yd0',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcWall', 'left in the model:', len(ifc.by_type('IfcWall')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 2 element(s)
members still in the model: []
IfcWall left in the model: 37
model committed
```
Assistant: Finished: the wall has been removed. The file on disk now holds the change.
