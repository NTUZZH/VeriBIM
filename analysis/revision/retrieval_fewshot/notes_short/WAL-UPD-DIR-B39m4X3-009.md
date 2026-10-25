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
Assign the wall to the type object named 'Basic Wall:Generic - 300mm'.

IFC model path: <path to the working copy>
Assistant: Let me locate that element in the model.
Assistant tool call execute_ifc_code:
```python
options = ifc.by_type('IfcWall')
print(len(options), 'IfcWall', 'in the model')
for target in options[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
150 IfcWall in the model
  342RYvdvn4_fN$Ahqhg90Z Basic Wall:External_Wall_300:365844
  342RYvdvn4_fN$Ahqhg91X Basic Wall:External_Wall_300:365910
  342RYvdvn4_fN$Ahqhg92e Basic Wall:External_Wall_300:365983
  342RYvdvn4_fN$Ahqhg9Ca Basic Wall:External_Wall_300:366099
  342RYvdvn4_fN$Ahqhg9C9 Basic Wall:External_Wall_300:366142
  342RYvdvn4_fN$Ahqhg9Ea Basic Wall:External_Wall_300:366227
  342RYvdvn4_fN$Ahqhg9E9 Basic Wall:External_Wall_300:366270
  342RYvdvn4_fN$Ahqhg9FD Basic Wall:External_Wall_300:366330
  342RYvdvn4_fN$Ahqhg99E Basic Wall:External_Wall_300:366457
  342RYvdvn4_fN$Ahqhg9AI Basic Wall:External_Wall_300:366501
  342RYvdvn4_fN$Ahqhg9Yq Basic Wall:Generic - 300mm:368003
  342RYvdvn4_fN$Ahqhg9Zx Basic Wall:Generic - 300mm:368076
  342RYvdvn4_fN$Ahqhg9kp Basic Wall:Generic - 300mm:368260
  342RYvdvn4_fN$Ahqhg9lw Basic Wall:Generic - 300mm:368333
  342RYvdvn4_fN$Ahqhg9g0 Basic Wall:Generic - 200mm:368567
  342RYvdvn4_fN$Ahqhg9hU Basic Wall:Generic - 200mm:368617
  342RYvdvn4_fN$AhqhgAKm Basic Wall:Generic - 200mm:368647
  342RYvdvn4_fN$AhqhgALn Basic Wall:Generic - 200mm:368710
  342RYvdvn4_fN$AhqhgAHL Basic Wall:Generic - 200mm:368994
  342RYvdvn4_fN$AhqhgAIc Basic Wall:Generic - 200mm:369041
```
Assistant: Which wall do you mean?

### Example 2
User:
Assign the wall to the type object named 'Basic Wall:Wall-_250Con'.

IFC model path: <path to the working copy>
Assistant: I will resolve the description to a single element.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
options = ifc.by_type("IfcWall")
print(len(options), "IfcWall", 'in the model')
for target in options[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
51 IfcWall in the model
  3hDb8uQe53_uWuZwnVsDq0 Basic Wall:Wall-Partn_12P-75Std-12P:350195
  3hDb8uQe53_uWuZwnVsDqE Basic Wall:Wall-Partn_12P-75Std-12P:350205
  3hDb8uQe53_uWuZwnVsDqD Basic Wall:Wall-Partn_12P-75Std-12P:350206
  3hDb8uQe53_uWuZwnVsDqK Basic Wall:Wall-Partn_12P-75Std-12P:350183
  3hDb8uQe53_uWuZwnVsDqR Basic Wall:Wall-Partn_12P-75Std-12P:350184
  3hDb8uQe53_uWuZwnVsDq1 Basic Wall:Wall-Partn_12P-75Std-12P:350194
  34tTXKSOL3lwpRQy_xj1Uj Basic Wall:Wall-Partn_12P-75Std-12P:343120
  3hDb8uQe53_uWuZwnVsDY$ Basic Wall:Wall-Partn_12P-75Std-12P:348748
  3hDb8uQe53_uWuZwnVsDdt Basic Wall:Wall-Partn_12P-75Std-12P:348932
  34tTXKSOL3lwpRQy_xj1hK Basic Wall:Wall-Ext_150Bwk:340265
  34tTXKSOL3lwpRQy_xj1ZH Basic Wall:Wall-Ext_150Bwk:340780
  34tTXKSOL3lwpRQy_xjTjO Basic Wall:Wall-Int_12P-100Blk-12P:323749
  34tTXKSOL3lwpRQy_xjTjR Basic Wall:Wall-Int_12P-100Blk-12P:323750
  34tTXKSOL3lwpRQy_xjTjQ Basic Wall:Wall-Int_12P-100Blk-12P:323751
  34tTXKSOL3lwpRQy_xjTjL Basic Wall:Wall-Int_12P-100Blk-12P:323752
  34tTXKSOL3lwpRQy_xjTjK Basic Wall:Wall-Int_12P-100Blk-12P:323753
  34tTXKSOL3lwpRQy_xjTjN Basic Wall:Wall-Int_12P-100Blk-12P:323754
  34tTXKSOL3lwpRQy_xjTjM Basic Wall:Wall-Int_12P-100Blk-12P:323755
  34tTXKSOL3lwpRQy_xj0AY Basic Wall:Wall-Ext_150Bwk:338271
  34tTXKSOL3lwpRQy_xj093 Basic Wall:Wall-Ext_150Bwk:338366
```
Assistant: Which wall do you mean?

### Example 3
User:
Assign the wall to the type object named 'Basic Wall:MVW 20.0'.

IFC model path: <path to the working copy>
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
pool = ifc.by_type("IfcWall")
print(len(pool), "IfcWall", 'in the model')
for target in pool[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
260 IfcWall in the model
  0GBmcIjyj81gfl5yhXgtFK Basic Wall:DPW 24.0:321065
  2QI$4JkrPAyPE0QyoZyiOF Basic Wall:DPW 24.0:316302
  0dymqXIi17hwYya$Yhu3em Basic Wall:DPW 24.0:297268
  058byadMj8QOKMXiyfDP7a Basic Wall:DPW 24.0:191852
  3CW$HpPK59rwhT_MFieloz Basic Wall:DPW 24.0:157136
  2ibOUgR2fCfhVel6emmGIC Basic Wall:GK 10.0:332481
  0UjJlP$K93C993NPofiVrL Basic Wall:DPW 24.0:326774
  0lUIXDaS5A3RRHnF8or_mC Basic Wall:DPW 24.0:328606
  3vrDpqKBX8GeU5MX4E1Gkn Basic Wall:DPW 24.0:329908
  2J3ol7zZH9bfJgRfdMNEwl Basic Wall:GK 10.0:332219
  2cOzR8t8n0tvaLWn51f89Q Basic Wall:GK 10.0:213846
  2cOzR8t8n0tvaLWn51f89I Basic Wall:GK 10.0:213854
  11xbKIfbf3yPnam1nzu1HS Basic Wall:DPW 24.0:216021
  2jKJUApzzCSu7P2Ns6NP8V Basic Wall:DPW 24.0:325837
  3IMs$QhqzAMBfVnvIui_K1 Basic Wall:DPW 24.0:175620
  3yqBfpNBT3cuOCFJ61S0Fa Basic Wall:MVW 20.0:180941
  0ydMOiQEXCROp$DsMUeDdD Basic Wall:GK 10.0:193792
  20V7HwHxvAuBtwkT9tgKbH Basic Wall:GK 10.0:211580
  3CW$HpPK59rwhT_MFielys Basic Wall:DPW 24.0:157275
  0R3eNR_Gv5IOTmARicA7vG Basic Wall:DPW 24.0:158547
```
Assistant: Which wall do you mean?
