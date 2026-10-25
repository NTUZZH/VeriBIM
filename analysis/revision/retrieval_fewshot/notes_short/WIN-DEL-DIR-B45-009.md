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
Remove the window hosted in the wall with GlobalId '3sKeopTv15suL376p95TY8' together with its assignment to the storey with GlobalId '15Z0v90RiHrPC20026FoKR' and the opening it fills in the wall with GlobalId '3sKeopTv15suL376p95TY8'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# follow the host's openings to what fills them
host = ifc.by_guid('3sKeopTv15suL376p95TY8')
print('given ->', host.GlobalId, host.is_a(), host.Name)
matches = []
for rel in getattr(host, 'HasOpenings', None) or ():
    hole = rel.RelatedOpeningElement
    for fills in (getattr(hole, 'HasFillings', None) or ()) if hole else ():
        unit = fills.RelatedBuildingElement
        if unit is not None and unit.is_a('IfcWindow'):
            matches.append(unit)
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3sKeopTv15suL376p95TY8 IfcWall Basic Wall:w0.2:347703
1 match(es)
0WMpbrMCj5HBFhQuc$wwVq IfcWindow Windows_Sgl_Plain:910x910mm:399345
```
Assistant: I will check the element's class and position first.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(target):
    placement = getattr(target, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * scale

for target_guid in ('0WMpbrMCj5HBFhQuc$wwVq',):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcWindow 0WMpbrMCj5HBFhQuc$wwVq Windows_Sgl_Plain:910x910mm:399345
  origin (m): [-6.427, 0.824, 5.4]
  openings: 0  contained in: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
geom.delete_filling(ifc.by_guid('0WMpbrMCj5HBFhQuc$wwVq'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('0WMpbrMCj5HBFhQuc$wwVq',) if g in present])

# save the edit
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: The window has been removed, and the edit is written to the working file.

### Example 2
User:
Remove the door hosted in the wall with GlobalId '3cyHnpwAvBz84R9Jtlw3UM' together with its assignment to the storey with GlobalId '15Z0v90RiHrPC20026FoKR' and the opening it fills in the wall with GlobalId '3cyHnpwAvBz84R9Jtlw3UM'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
host = ifc.by_guid("3cyHnpwAvBz84R9Jtlw3UM")
print('given ->', host.GlobalId, host.is_a(), host.Name)
found = []
for link in getattr(host, 'HasOpenings', None) or ():
    void = link.RelatedOpeningElement
    for fills in (getattr(void, 'HasFillings', None) or ()) if void else ():
        leaf = fills.RelatedBuildingElement
        if leaf is not None and leaf.is_a("IfcDoor"):
            found.append(leaf)
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
given -> 3cyHnpwAvBz84R9Jtlw3UM IfcWall Basic Wall:Wall-Int_12P-100Blk-12P:328570
3cyHnpwAvBz84R9Jtlw3UJ IfcDoor Doors_IntSgl:1010x2110mm:328575
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
geom.delete_filling(ifc.by_guid("3cyHnpwAvBz84R9Jtlw3UJ"))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ("3cyHnpwAvBz84R9Jtlw3UJ",) if g in present])

commit()
print("model committed")
```
Tool result:
```
still present: []
model committed
```
Assistant: Completed. The door has been removed; the model was committed.

### Example 3
User:
Remove the window with GlobalId '0H1nVTTAv6LhM6_nm3wffh' together with its assignment to storey '02 - Floor' and the opening it fills in the wall named '基本墙:Exterior - Insulation on Masonry:139857'.

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# read the element the instruction names by GlobalId
hits = [ifc.by_guid('0H1nVTTAv6LhM6_nm3wffh')]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
0H1nVTTAv6LhM6_nm3wffh IfcWindow M_Fixed:0915 x 1220mm:199217
```
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
geom.delete_filling(ifc.by_guid('0H1nVTTAv6LhM6_nm3wffh'))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# verify, then save
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('still present:', [g for g in ('0H1nVTTAv6LhM6_nm3wffh',) if g in present])

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
still present: []
model committed
```
Assistant: Finished: the window and the relationships that depended on it are gone. The file on disk now holds the change.
