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
Delete the slab on storey 'Level 3' recorded with no space boundary from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

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

# find the element that takes part in no such relationship
storey = by_name('IfcBuildingStorey', 'Level 3')
found = [geom.find_without(storey, 'IfcSlab',
                           'space boundary')]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named 'Level 3' -> 316DwlO2f6Muoj3Y_RU68B IfcBuildingStorey Level 3
[('2olCKedQb1tR9AF9tUIAqs', 'IfcSlab', 'Floor:Hybrid slab 220 mm:481813')]
```
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(product):
    placement = getattr(product, 'ObjectPlacement', None)
    if placement is None:
        return None
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * scale

for target_guid in ('2olCKedQb1tR9AF9tUIAqs',):
    product = ifc.by_guid(target_guid)
    print(product.is_a(), product.GlobalId, product.Name)
    point = world_point(product)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(product, 'HasOpenings', None) or ()), ' contained in:', len(getattr(product, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcSlab 2olCKedQb1tR9AF9tUIAqs Floor:Hybrid slab 220 mm:481813
  origin (m): [0.0, 0.0, 12.0]
  openings: 2  contained in: 1
```
Assistant tool call execute_ifc_code:
```python
# delete the element, its openings and whatever those openings hold
geom.delete_element(ifc.by_guid('2olCKedQb1tR9AF9tUIAqs'))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('2olCKedQb1tR9AF9tUIAqs',) if g in present])

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The slab and the relationships that depended on it are gone, and the edit is written to the working file.

### Example 2
User:
Delete the slab on storey 'Level 1' recorded with no space boundary from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

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

storey = by_name("IfcBuildingStorey", "Level 1")
matches = [geom.find_without(storey, "IfcSlab",
                             "space boundary")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in matches]
```
Tool result:
```
named 'Level 1' -> 15Z0v90RiHrPC20026FoKR IfcBuildingStorey Level 1
[('0bFEppYQz6Igv5f$hgdX_5', 'IfcSlab', 'Floor:Floor-Grnd-Susp_65Scr-80Ins-100Blk-75PC:326526')]
```
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

unit_scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale

for target_guid in ("0bFEppYQz6Igv5f$hgdX_5",):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcSlab 0bFEppYQz6Igv5f$hgdX_5 Floor:Floor-Grnd-Susp_65Scr-80Ins-100Blk-75PC:326526
  origin (m): [0.0, 0.0, 4.555]
  openings: 0  contained in: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
geom.delete_element(ifc.by_guid("0bFEppYQz6Igv5f$hgdX_5"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("0bFEppYQz6Igv5f$hgdX_5",) if g in present])

commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the slab has been removed. The file on disk now holds the change.

### Example 3
User:
Delete the slab on storey '2.Second Floor' recorded with no space boundary from the model, together with the relationships that depend on it, and make sure the other relationships stay consistent.

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

storey = by_name("IfcBuildingStorey", "2.Second Floor")
found = [geom.find_without(storey, "IfcSlab",
                           "space boundary")]
result = [(e.GlobalId, e.is_a(), e.Name) for e in found]
```
Tool result:
```
named '2.Second Floor' -> 1DD4OqS2zCVAGEH7hc4z7J IfcBuildingStorey 2.Second Floor
[('3Kb8uaX718lesovqKDrDdn', 'IfcSlab', 'Floor:Generic 200mm:444032')]
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
geom.delete_element(ifc.by_guid("3Kb8uaX718lesovqKDrDdn"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Checking the result and saving the model.
Assistant tool call execute_ifc_code:
```python
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("3Kb8uaX718lesovqKDrDdn",) if g in present])

commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the slab has been removed. The file on disk now holds the change.
