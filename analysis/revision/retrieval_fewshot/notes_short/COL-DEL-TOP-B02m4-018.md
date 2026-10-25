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
Please remove all the columns on storey '5th Floor (16.5m)' from the model, together with the relationships that depend on them.

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

# list every element the instruction's phrase covers
scope = by_name('IfcBuildingStorey', '5th Floor (16.5m)')
pool = geom.on_storey(scope, 'IfcColumn')
print(len(pool), 'candidate(s) in scope')
matches = list(pool)
print(len(matches), 'match(es)')
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '5th Floor (16.5m)' -> 22AcfDWMf4lvxlckJ6lX4k IfcBuildingStorey 5th Floor (16.5m)
8 candidate(s) in scope
8 match(es)
3RmcqzOSL01x21FQSRSvDU IfcColumn Columns_Rectangular:COL 50x50cm:334614
3RmcqzOSL01x21FQSRSvDV IfcColumn Columns_Rectangular:COL 50x50cm:334615
3RmcqzOSL01x21FQSRSvDG IfcColumn Columns_Rectangular:COL 50x50cm:334616
3RmcqzOSL01x21FQSRSvDH IfcColumn Columns_Rectangular:COL 50x50cm:334617
3RmcqzOSL01x21FQSRSvDI IfcColumn Columns_Rectangular:COL 50x120cm:334618
3RmcqzOSL01x21FQSRSvDJ IfcColumn Columns_Rectangular:COL 50x120cm:334619
3RmcqzOSL01x21FQSRSvDK IfcColumn Columns_Rectangular:COL 50x120cm:334620
3RmcqzOSL01x21FQSRSvDL IfcColumn Columns_Rectangular:COL 50x120cm:334621
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# remove the element and the relationships that depend on it
for target_guid in ('3RmcqzOSL01x21FQSRSvDG', '3RmcqzOSL01x21FQSRSvDH', '3RmcqzOSL01x21FQSRSvDI', '3RmcqzOSL01x21FQSRSvDJ', '3RmcqzOSL01x21FQSRSvDK', '3RmcqzOSL01x21FQSRSvDL', '3RmcqzOSL01x21FQSRSvDU', '3RmcqzOSL01x21FQSRSvDV'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
# verify, then save
# every element the phrase covers, and what is left of its class
members = ('3RmcqzOSL01x21FQSRSvDG', '3RmcqzOSL01x21FQSRSvDH', '3RmcqzOSL01x21FQSRSvDI', '3RmcqzOSL01x21FQSRSvDJ', '3RmcqzOSL01x21FQSRSvDK', '3RmcqzOSL01x21FQSRSvDL', '3RmcqzOSL01x21FQSRSvDU', '3RmcqzOSL01x21FQSRSvDV',)
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
the phrase covers 8 element(s)
members still in the model: []
IfcColumn left in the model: 80
model committed
```
Assistant: The column and the relationships that depended on it are gone. The edited model is committed.

### Example 2
User:
Please remove all the columns on storey '1° PAVIMENTO - TÉRREO (N.A)' from the model, together with the relationships that depend on them.

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

scope = by_name('IfcBuildingStorey', '1° PAVIMENTO - TÉRREO (N.A)')
options = geom.on_storey(scope, 'IfcColumn')
print(len(options), 'candidate(s) in scope')
hits = list(options)
print(len(hits), 'match(es)')
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named '1° PAVIMENTO - TÉRREO (N.A)' -> 31MO7odvv0cAeswhRbsHyC IfcBuildingStorey 1° PAVIMENTO - TÉRREO (N.A)
4 candidate(s) in scope
4 match(es)
17bNRqTtr0OArtuGEocULC IfcColumn P8:P6:1109723
17bNRqTtr0OArtuGEocUNr IfcColumn P7:P3:1109602
17bNRqTtr0OArtuGEocUN1 IfcColumn P5:P2:1109590
17bNRqTtr0OArtuGEocUNT IfcColumn P4:P1:1109578
```
Assistant: Let me read the target before changing it.
Assistant tool call execute_ifc_code:
```python
import numpy as np
import ifcopenshell.util.placement
import ifcopenshell.util.unit

scale = ifcopenshell.util.unit.calculate_unit_scale(ifc)


def world_point(element):
    placement = getattr(element, 'ObjectPlacement', None)
    if placement is None:
        return None
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * scale

for target_guid in ('17bNRqTtr0OArtuGEocULC', '17bNRqTtr0OArtuGEocUN1', '17bNRqTtr0OArtuGEocUNT', '17bNRqTtr0OArtuGEocUNr'):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(element, 'HasOpenings', None) or ()), ' contained in:', len(getattr(element, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcColumn 17bNRqTtr0OArtuGEocULC P8:P6:1109723
  origin (m): [14.733, 33.756, 0.0]
  openings: 0  contained in: 1
IfcColumn 17bNRqTtr0OArtuGEocUN1 P5:P2:1109590
  origin (m): [14.733, 33.756, 0.0]
  openings: 0  contained in: 1
IfcColumn 17bNRqTtr0OArtuGEocUNT P4:P1:1109578
  origin (m): [14.733, 33.756, 0.0]
  openings: 0  contained in: 1
IfcColumn 17bNRqTtr0OArtuGEocUNr P7:P3:1109602
  origin (m): [26.166, 27.877, 0.0]
  openings: 0  contained in: 1
```
Assistant: Now I can apply the edit.
Assistant tool call execute_ifc_code:
```python
for target_guid in ('17bNRqTtr0OArtuGEocULC', '17bNRqTtr0OArtuGEocUN1', '17bNRqTtr0OArtuGEocUNT', '17bNRqTtr0OArtuGEocUNr'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant: Now I verify the edit and commit.
Assistant tool call execute_ifc_code:
```python
members = ('17bNRqTtr0OArtuGEocULC', '17bNRqTtr0OArtuGEocUN1', '17bNRqTtr0OArtuGEocUNT', '17bNRqTtr0OArtuGEocUNr',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcColumn', 'left in the model:', len(ifc.by_type('IfcColumn')))

commit()
print('model committed')
```
Tool result:
```
the phrase covers 4 element(s)
members still in the model: []
IfcColumn left in the model: 24
model committed
```
Assistant: Finished: the column and the relationships that depended on it are gone. The file on disk now holds the change.

### Example 3
User:
Remove all the columns on storey '3. Story' from the model, together with the relationships that depend on them.

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

# list every element the instruction's phrase covers
scope = by_name('IfcBuildingStorey', '3. Story')
pool = geom.on_storey(scope, 'IfcColumn')
print(len(pool), 'candidate(s) in scope')
hits = list(pool)
result = [(e.GlobalId, e.is_a(), e.Name) for e in hits]
```
Tool result:
```
named '3. Story' -> 0Xs8bhxcAqHAzgPkVKwF0S IfcBuildingStorey 3. Story
10 candidate(s) in scope
[('3nRzLuxq$0JhutXH1uRtX6', 'IfcColumn', 'CRE - 001'), ('16ORyXs3lDGOa9Gb9h6TDp', 'IfcColumn', 'CRE - 001'), ('0Gq1jfc_ELG8NfJ6Vbwecg', 'IfcColumn', 'CRE - 001'), ('06EFDcUse2JeKa4jfYahR6', 'IfcColumn', 'CRE - 001'), ('2$ZkFbLcZzGRrlvW_$1KYH', 'IfcColumn', 'CRE - 001'), ('28Uf9z8sr6HB5hyIiNZ34C', 'IfcColumn', 'CRE - 001'), ('0s9A9e45HMHPk7YqZ4iqOv', 'IfcColumn', 'CRE - 001'), ('0sjcTm0_IwGhm0IO6hc_ig', 'IfcColumn', 'CRE - 001'), ('3eWlfdh_PDIhbZTwfKBfCD', 'IfcColumn', 'CRE - 001'), ('0RcweWp6y9I8NTuIT5x01R', 'IfcColumn', 'CRE - 001')]
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
    world = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return world[:3, 3] * scale

for target_guid in ('06EFDcUse2JeKa4jfYahR6', '0Gq1jfc_ELG8NfJ6Vbwecg', '0RcweWp6y9I8NTuIT5x01R', '0s9A9e45HMHPk7YqZ4iqOv', '0sjcTm0_IwGhm0IO6hc_ig', '16ORyXs3lDGOa9Gb9h6TDp', '2$ZkFbLcZzGRrlvW_$1KYH', '28Uf9z8sr6HB5hyIiNZ34C', '3eWlfdh_PDIhbZTwfKBfCD', '3nRzLuxq$0JhutXH1uRtX6'):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  openings:', len(getattr(target, 'HasOpenings', None) or ()), ' contained in:', len(getattr(target, 'ContainedInStructure', None) or ()))
```
Tool result:
```
IfcColumn 06EFDcUse2JeKa4jfYahR6 CRE - 001
  origin (m): [4.75, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 0Gq1jfc_ELG8NfJ6Vbwecg CRE - 001
  origin (m): [3.55, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 0RcweWp6y9I8NTuIT5x01R CRE - 001
  origin (m): [9.55, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 0s9A9e45HMHPk7YqZ4iqOv CRE - 001
  origin (m): [13.15, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 0sjcTm0_IwGhm0IO6hc_ig CRE - 001
  origin (m): [11.95, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 16ORyXs3lDGOa9Gb9h6TDp CRE - 001
  origin (m): [5.95, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 2$ZkFbLcZzGRrlvW_$1KYH CRE - 001
  origin (m): [7.15, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 28Uf9z8sr6HB5hyIiNZ34C CRE - 001
  origin (m): [14.35, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 3eWlfdh_PDIhbZTwfKBfCD CRE - 001
  origin (m): [10.75, 31.2, 9.6]
  openings: 0  contained in: 1
IfcColumn 3nRzLuxq$0JhutXH1uRtX6 CRE - 001
  origin (m): [8.35, 31.2, 9.6]
  openings: 0  contained in: 1
```
Assistant tool call execute_ifc_code:
```python
# drop the element together with its placement, geometry and relations
for target_guid in ('06EFDcUse2JeKa4jfYahR6', '0Gq1jfc_ELG8NfJ6Vbwecg', '0RcweWp6y9I8NTuIT5x01R', '0s9A9e45HMHPk7YqZ4iqOv', '0sjcTm0_IwGhm0IO6hc_ig', '16ORyXs3lDGOa9Gb9h6TDp', '2$ZkFbLcZzGRrlvW_$1KYH', '28Uf9z8sr6HB5hyIiNZ34C', '3eWlfdh_PDIhbZTwfKBfCD', '3nRzLuxq$0JhutXH1uRtX6'):
    geom.delete_element(ifc.by_guid(target_guid))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
# every element the phrase covers, and what is left of its class
members = ('06EFDcUse2JeKa4jfYahR6', '0Gq1jfc_ELG8NfJ6Vbwecg', '0RcweWp6y9I8NTuIT5x01R', '0s9A9e45HMHPk7YqZ4iqOv', '0sjcTm0_IwGhm0IO6hc_ig', '16ORyXs3lDGOa9Gb9h6TDp', '2$ZkFbLcZzGRrlvW_$1KYH', '28Uf9z8sr6HB5hyIiNZ34C', '3eWlfdh_PDIhbZTwfKBfCD', '3nRzLuxq$0JhutXH1uRtX6',)
present = {e.GlobalId for e in ifc.by_type('IfcProduct')}
print('the phrase covers', len(members), 'element(s)')
print('members still in the model:', [g for g in members if g in present])
print('IfcColumn', 'left in the model:', len(ifc.by_type('IfcColumn')))

# write the model back to disk
commit()
print('model committed')
```
Tool result:
```
the phrase covers 10 element(s)
members still in the model: []
IfcColumn left in the model: 40
model committed
```
Assistant: Completed. The column has been removed; the model was committed.
