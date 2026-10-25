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
Update the external flag of the window in Pset_WindowCommon from true to false.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
options = ifc.by_type("IfcWindow")
print(len(options), "IfcWindow", 'in the model')
for product in options[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
15 IfcWindow in the model
  0e$SWHp1zE7vA9ZmBiPLlU JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:170x80:947938
  0e$SWHp1zE7vA9ZmBiPLKT JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:170x80:948257
  0e$SWHp1zE7vA9ZmBiPLLn JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:170x80:948301
  0e$SWHp1zE7vA9ZmBiPLLg JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948310
  0e$SWHp1zE7vA9ZmBiPLLZ JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948319
  0e$SWHp1zE7vA9ZmBiPLLK JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948328
  0e$SWHp1zE7vA9ZmBiPLLD JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:230x80:948337
  0e$SWHp1zE7vA9ZmBiPLNp JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:80x60:948431
  0e$SWHp1zE7vA9ZmBiPLNk JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:948434
  0e$SWHp1zE7vA9ZmBiPLGo JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:948494
  0e$SWHp1zE7vA9ZmBiPLGP JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:948517
  0e$SWHp1zE7vA9ZmBiPLHe JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:948564
  1zFS51Ee113hu9jw9MK0j0 JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:1024257
  1zFS51Ee113hu9jw9MK0ib JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:60X60:1024356
  37Kxv_DU15jwxebZpIl90B JANELA - MAXIMO AR - 1 FOLHA - ALUMÍNIO:170x45:1165590
```
Assistant: Which window do you mean?

### Example 2
User:
Can you change the external flag of the window in Pset_WindowCommon from true to false?

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type('IfcWindow')
print(len(pool), 'IfcWindow', 'in the model')
for product in pool[:20]:
    print(' ', product.GlobalId, product.Name)
```
Tool result:
```
49 IfcWindow in the model
  0_CJ6FjXD118MUZNG8Gu7I M_Window-Sliding-Four:1650 x 600mm:418988
  0_CJ6FjXD118MUZNG8Gv50 M_Window-Sliding-Four:1650 x 600mm:422974
  0_CJ6FjXD118MUZNG8Gu0l M_Window-Sliding-Four:1650 x 600mm:419153
  0_CJ6FjXD118MUZNG8GvAv M_Window-Sliding-Four:1650 x 600mm:423879
  0_CJ6FjXD118MUZNG8Gt0o M_Instance-Window-Fixed:0610 x 1220mm:431436
  0_CJ6FjXD118MUZNG8GtCn M_Instance-Window-Fixed:0610 x 1220mm:431695
  0_CJ6FjXD118MUZNG8GtQ$ M_Instance-Window-Fixed:0610 x 1220mm:431041
  0_CJ6FjXD118MUZNG8GtUa M_Instance-Window-Fixed:0610 x 1220mm:430810
  0_CJ6FjXD118MUZNG8GtJF M_Instance-Window-Fixed:0610 x 1220mm:430513
  0_CJ6FjXD118MUZNG8GtS6 M_Instance-Window-Fixed:0610 x 1220mm:430712
  0_CJ6FjXD118MUZNG8Gshs M_Instance-Window-Fixed:0610 x 1220mm:429960
  0_CJ6FjXD118MUZNG8GqOM M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:435048
  0_CJ6FjXD118MUZNG8GqGB M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:434549
  0_CJ6FjXD118MUZNG8GqJK M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:434602
  0_CJ6FjXD118MUZNG8GqI0 M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:434686
  0_CJ6FjXD118MUZNG8GqSS M_Window-Casement-Multi-Sash-Horizontal:1800 x 1350mm:434786
  0_CJ6FjXD118MUZNG8GroX M_Window-Sliding-Four:1650 x 600mm:440799
  0_CJ6FjXD118MUZNG8Groc M_Window-Sliding-Four:1650 x 600mm:440792
  0_CJ6FjXD118MUZNG8GroA M_Window-Sliding-Four:1650 x 600mm:440820
  0_CJ6FjXD118MUZNG8GroO M_Window-Sliding-Four:1650 x 600mm:440806
```
Assistant: Which window do you mean?

### Example 3
User:
Change the external flag of the window hosted in the wall named 'Basic Wall:Wall-Ret_300Con:346750' in Pset_WindowCommon from true to false.

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

# follow the host's openings to what fills them
host = by_name("IfcWall", "Basic Wall:Wall-Ret_300Con:346750")
found = []
for link in getattr(host, 'HasOpenings', None) or ():
    opening = link.RelatedOpeningElement
    for fills in (getattr(opening, 'HasFillings', None) or ()) if opening else ():
        leaf = fills.RelatedBuildingElement
        if leaf is not None and leaf.is_a("IfcWindow"):
            found.append(leaf)
print(len(found), 'match(es)')
for e in found:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basic Wall:Wall-Ret_300Con:346750' -> 3SWWD2QabFXf7BgMy8H7kn IfcWall Basic Wall:Wall-Ret_300Con:346750
1 match(es)
3SWWD2QabFXf7BgMy8H7km IfcWindow Windows_Sgl_Plain:1810x1210mm:346751
```
Assistant: Let me read the target before changing it.
Assistant tool call execute_ifc_code:
```python
# read the target before editing it
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

for target_guid in ("3SWWD2QabFXf7BgMy8H7km",):
    element = ifc.by_guid(target_guid)
    print(element.is_a(), element.GlobalId, element.Name)
    point = world_point(element)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(element, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWindow 3SWWD2QabFXf7BgMy8H7km Windows_Sgl_Plain:1810x1210mm:346751
  origin (m): [-11.317, 3.29, 4.2]
  contained in: ['1st Floor (3.3m)']
```
Assistant: Applying the change.
Assistant tool call execute_ifc_code:
```python
# set the property the instruction names, creating the set if it is absent
geom.set_property(ifc.by_guid("3SWWD2QabFXf7BgMy8H7km"), "Pset_WindowCommon",
                  "IsExternal", False)
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# read the result back before persisting it
element = ifc.by_guid("3SWWD2QabFXf7BgMy8H7km")
print(element.is_a(), element.GlobalId, element.Name)

# persist the edited model
commit()
print("model committed")
```
Tool result:
```
IfcWindow 3SWWD2QabFXf7BgMy8H7km Windows_Sgl_Plain:1810x1210mm:346751
model committed
```
Assistant: The window has been updated. The edited model is committed.
