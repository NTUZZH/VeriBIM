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

## Full reference of the helper library (signature and documentation of every function)

### geom.add_box_element(storey, ifc_class: str, name: Optional[str], x: float, y: float, z: float, dx: float, dy: float, dz: float, predefined_type: Optional[str] = None, frame: str = storey, like=None, long_name: Optional[str] = None)
Create a box-shaped element on a storey.

``x``, ``y`` and ``z`` are the element's lowest corner and ``dx``, ``dy``
and ``dz`` its size, all in metres.  ``frame`` says which coordinates the
corner is given in: ``"storey"`` for the storey's own system, which is what
an instruction saying "in that storey's own coordinates" means, or
``"world"`` for the building's, which is what a bare coordinate means.  A
world point is converted into the storey's system here, so a storey that
sits at an elevation or at a plan offset no longer moves the element.

The element is placed relative to the storey and is contained in it; a
space is aggregated under it instead.  Returns the created element.

### geom.add_column_box(storey, origin, extents, name: Optional[str] = None, stands_on=None, bounds: Sequence = ())
Create a rectangular column that fills a box on a storey, as Revit does.

``origin`` and ``extents`` are the column's bounding box in the storey's
own coordinates, in metres.  The column is placed at the centre of its base
with a centred rectangular profile, typed by the file's column type of that
cross-section or a new "M_Concrete-Rectangular-Column:<w> x <d>mm" type,
named "<type name>:<tag>" and given Pset_ColumnCommon and
Pset_EnvironmentalImpactIndicators.  It is contained in the storey,
connected to the column it stands on when ``stands_on`` names one, and
recorded as a boundary of every room in ``bounds``.  Returns the column.

### geom.add_filling(host_wall, ifc_class: str, name: Optional[str], width: float, height: float, along: float, sill: float = 0.0, predefined_type: Optional[str] = None, along_is_centre: bool = False, depth: Optional[float] = None)
Cut an opening in a wall and fill it with a door or a window.

``along`` is the distance along the wall's own x axis, in metres, to the
near edge of the leaf; pass ``along_is_centre=True`` when the instruction
gives the position of the middle of the leaf instead, and half the width is
taken off here.  ``sill`` is the height of the leaf's base above the wall's
base.  ``width`` and ``height`` size the leaf.

What the function guarantees, so the caller never states it:

* the opening and the leaf both hang from the wall's own placement, so they
  travel with the wall;
* the leaf's near face sits on the wall's near face and the leaf is as deep
  as the wall, unless ``depth`` says otherwise;
* the opening starts 50 mm outside the near face and is 100 mm deeper than
  the wall, so it cuts past both faces;
* an ``IfcRelVoidsElement`` ties the opening to the wall, an
  ``IfcRelFillsElement`` ties the leaf to the opening, and the leaf joins
  the wall's storey;
* ``OverallWidth`` and ``OverallHeight`` are written in file units.

Returns the created leaf.

### geom.add_opening_filling(wall, ifc_class: str, origin, extents, bounds: Sequence = (), name: Optional[str] = None)
Cut an opening in a wall and fill it with a door or a window, as Revit does.

``origin`` and ``extents`` are the opening's bounding box in the coordinates
of the wall's storey, in metres; the box has to follow the wall's own axes.
The ``IfcOpeningElement`` is placed relative to the wall and voids it; the
door or window is placed at the opening's own origin, fills it and is
contained in the storey (the opening is not).  The leaf is typed by the
file's door or window type of that width and height, within ten
millimetres, or by a new "M_Door-Passage-Single-Flush:<w> x <h>mm" or
"M_Window-Fixed:<w> x <h>mm" type; its body is the type's own geometry when
that fits the opening and a box of the opening otherwise.  It is named
"<type name>:<tag>", sized by OverallWidth and OverallHeight, given
Pset_DoorCommon or Pset_WindowCommon (external when its wall is) and
Pset_EnvironmentalImpactIndicators and its type's material constituents,
and recorded as a boundary of every room in ``bounds``.  Returns the leaf.

### geom.add_revit_psets(element, kind: str, reference: Optional[str] = None, is_external: Optional[bool] = None, fire_rating: Optional[str] = None) -> list
Write the property sets a Revit export gives an element of one kind.

``kind`` is wall, slab, column, space, door or window.  ``reference`` is the
type name part of the element's type, read off the type when it is not
given.  A wall and a door or window are external as ``is_external`` says;
a slab, a column and a room are internal.  Returns the property sets.

### geom.add_slab_box(storey, origin, extents, name: Optional[str] = None, bounds: Sequence = (), connect_to: Sequence = ())
Create a floor slab that fills a box on a storey, as Revit writes one.

``origin`` and ``extents`` are the slab's bounding box in the storey's own
coordinates, in metres; the height is the slab's thickness.  The slab is
an ``IfcSlab`` of type FLOOR with a swept body, typed by the file's floor
type of that thickness or a new "Floor:Generic <mm>mm" type, with the
type's material layers, the name "<type name>:<tag>" and the property sets
Pset_SlabCommon, Pset_EnvironmentalImpactIndicators and
Pset_ReinforcementBarPitchOfSlab.  It is contained in the storey, connected
to every element in ``connect_to`` and recorded as a boundary of every room
in ``bounds``: external where nothing lies on its far side, internal
otherwise.  Returns the slab.

### geom.add_space_boundary(space, element, physical_or_virtual: str = PHYSICAL, internal_or_external: str = INTERNAL, name: Optional[str] = None)
Record that one element bounds one space, as an ``IfcRelSpaceBoundary``.

### geom.add_space_box(storey, origin, extents, name: Optional[str] = None, long_name: Optional[str] = None, bounded_by: Sequence = ())
Create a room that fills a box on a storey, as a Revit export writes it.

``origin`` and ``extents`` are the room's bounding box in the storey's own
coordinates, in metres.  The room is an ``IfcSpace`` named with the next
free room number unless ``name`` is given, with a swept body, aggregated
under the storey (a room is decomposed from its storey, not contained in
it), given Pset_SpaceCommon, and recorded as bounded by every element in
``bounded_by``.  Returns the room.

### geom.add_wall_box(storey, origin, extents, name: Optional[str] = None, connect_to: Sequence = (), bounds: Sequence = ())
Create a wall that fills a box on a storey, as a Revit export writes it.

``origin`` is the lowest corner of the wall's bounding box and ``extents``
its size along x, y and z, in metres and in the storey's own coordinates.
The wall runs along the longer of the two plan sides and is as thick as the
shorter one.  It gets an axis line and a swept body placed at the start of
that axis, the file's wall type of that thickness or a new
"Basic Wall:Generic - <mm>mm" type, the type's material layers, the name
"<type name>:<tag>" and the property sets Pset_WallCommon,
Pset_EnvironmentalImpactIndicators and Pset_ReinforcementBarPitchOfWall.
It is contained in the storey, joined to every wall in ``connect_to`` by a
path connection, and recorded as a boundary of every room in ``bounds``.
The wall is external unless the rooms it bounds stand on both its sides.
Returns the wall.

### geom.array_elements(product, count: int, dx: float, dy: float, dz: float, names: Sequence[Optional[str]] = ())
Copy one element ``count`` times at a fixed spacing.

The nth copy stands n times ``(dx, dy, dz)`` from the original, in world
metres, so the copies form an evenly spaced row and the first copy is one
spacing away rather than on top of the original.  Returns the copies in
order.

### geom.assign_material(element, name: str)
Give one element a material, named.

A material the file already carries under that name is used again rather
than duplicated, and one is created when the file has none.  An element
carries one material association, so the association it had is dropped
first.  Returns the material.

### geom.assign_type(element, type_object)
Put one element under a type object.

An element is typed once, so the type it had is dropped first.  Where the
file already records other elements under this type, the element joins that
record rather than a second one being written.  Returns the relationship
the element now sits in.

``type_object`` is either a type entity or a specification such as
``{"kind": "wall", "thickness": 0.2}``, which ``revit_type`` resolves to the
file's own type of that size or to a new one named the way Revit names it.

### geom.bounding_elements(space, ifc_class: str = ) -> list
The elements recorded as bounding one space, of one class if given.

### geom.box_in_frame(product, frame_product, disable_openings: bool = False)
``product``'s box in ``frame_product``'s own coordinate system, in metres.

Use it to read where something stands as the element that hosts it sees it:
a door's position along its wall, a slab's footprint on its storey.

### geom.centre(product)
The centre of the product's body in world metres, as a numpy array.

Falls back to the placement origin for an element whose body cannot be
measured, which is what a reader looking at the model would do.

### geom.column_in_gap(wall_a, wall_b, storey, height: Optional[float] = None) -> dict
The box of a column filling the gap between two walls in line.

The two walls run along one line with a gap between their ends; the
column fills that gap across the walls' shared thickness, stands on their
common base, and is ``height`` metres tall or as tall as the walls share.
Returns ``{"origin": corner, "extents": size}``.

### geom.column_in_room(room, storey, width: float, depth: float, height: Optional[float] = None) -> dict
The box of a column standing at the centre of a room's plan.

``width`` runs along x and ``depth`` along y; the column stands on the
room's floor and is ``height`` metres tall, or as tall as the room.
Returns ``{"origin": corner, "extents": size}``.

### geom.column_on_top(column, storey, height: float) -> dict
The box of a column standing on another, with its cross-section.

The new column's base is the named column's top face and it is
``height`` metres tall.  Returns ``{"origin": corner, "extents": size}``.

### geom.connect_elements(relating, related, name: Optional[str] = None)
Record that two elements are connected, as an ``IfcRelConnectsElements``.

### geom.connect_path(relating, related)
Record that a wall joins another, as an ``IfcRelConnectsPathElements``.

The joining wall ``relating`` is connected along its path (``ATPATH``); the
wall it meets, ``related``, is connected at the end of its axis the joining
wall stands nearer to, ``ATSTART`` or ``ATEND``.  Returns the relationship.

### geom.copy_element(product, dx: float, dy: float, dz: float, name: Optional[str] = None)
Duplicate one element at a world-axis offset given in metres.

The copy keeps the original's class, attributes, body and orientation, and
it hangs from the same parent placement and joins the same storey, so the
model holds it exactly as it holds the element it came from.  The offset is
stated along the world axes and is rotated into the parent's system here,
so a copy "0.6 m to the east" moves east whatever the parent's rotation.

### geom.corner_from(reference, storey, offset) -> tuple
A point given as an offset from the minimum corner of an element's box.

The minimum corner is read in the storey's own coordinates and ``offset``
is added to it, in metres.  Returns the point.

### geom.delete_element(product) -> None
Remove one element, everything it holds, and the relationships it empties.

An opening exists to be filled and a door exists to sit in a wall, so a
wall cannot go while the doors and windows cut into it stay: removing the
wall alone leaves them standing in mid-air with their material, their
properties and the room boundaries they used to form still recorded.  This
call removes the element, the openings cut into it, the doors and windows
those openings hold, and afterwards every relationship object left with
nothing on its related side.

A storey, a building or a site is never removed, and no element other than
the ones the removed element holds is touched: a wall connected to another
wall loses the connection and the other wall stays.

### geom.delete_filling(filling) -> None
Remove a door or a window together with the opening it filled.

An element that fills no opening is not a filling, and an instruction that
says "delete it" means the same thing whichever class it names, so such a
call is handed to ``delete_element`` instead of failing.

### geom.deletion_is_complete(model, guid: str, source=None, report: bool = False)
Whether a removal left the model whole.

Three things are asked of the model the removal produced: the element is
gone, no door or window the removed element used to hold is still in it,
and no relationship object names nothing.  ``source`` is the model as it
stood before the removal.  It is what says which doors and windows the
element held, and it is also what tells a row the removal emptied from a
row that already named nothing when the file was written, which several
files in any corpus carry; without it the orphan reading falls back to a
filling that fills no opening at all, which a file with unhosted doors
fails on its own.  With ``report`` the answer is a dictionary listing
what was found.

### geom.filling_slot(filling) -> dict
Where an existing door or window sits in its host wall, in metres.

``along`` is the near edge of the opening measured along the wall's own x
axis, ``sill`` is its base above the wall's base, and ``width`` and
``height`` size it.  These are the numbers "at the same position along the
wall" refers to, and they are read from the opening rather than from the
leaf, because the opening is what the wall was cut to.

### geom.find_above_below(reference, ifc_class: str, direction, storey=None)
The element standing directly over or under another one.

For "the column on storey S directly above the column named C": pass the
column named C, ``'IfcColumn'`` and ``'above'``.  The answer sits on the
next storey up, or down for ``'below'``, and is the element of the class
whose body centre stands closest to the reference's in plan.  Pass
``storey`` when the sentence names the storey the answer sits on, and that
storey is used instead of the neighbouring one.

### geom.find_beside_door(door, space, side: str, ifc_class: str)
The element on the left or the right, seen from a door into a room.

For "the window on the left-hand side as seen from the door named D
looking into the space S": pass the door, the space, ``'left'`` and
``'IfcWindow'``.  The reader faces into the room along the door's own host
wall, across it, and left and right follow from that.  Of the elements of
the class bounding the room, the one standing furthest to the named side of
the door is the answer.

### geom.find_between(a, b, ifc_class: str, storey)
The element of one class standing between two named elements.

For "the wall on storey S between the column named A and the column named
B": pass the two columns, ``'IfcWall'`` and the storey.  The two are
separated along one plan axis, and that axis is the one their centres
differ on most.  A candidate counts when its centre lies in the run between
theirs along that axis, clear of both ends by a twentieth of the run, since
an element standing on top of one of the two is not between them.  Of the
candidates that count, the one sitting closest to the straight line joining
the two centres is the answer.

### geom.find_bounding(space, ifc_class: str)
The one element of a class that bounds a room.

"the window that bounds the room R" is one call.  The elements a room is
bounded by are what the model records against it; this keeps those of the
class the sentence asks for and expects one.

### geom.find_extreme(ifc_class: str, storey, direction)
The element of one class that stands furthest one way on a storey.

For "the slab furthest north (+Y) on storey S": pass ``'IfcSlab'``, the
storey and ``'north'``.  Furthest is read from the placement origins, and
the element with the largest coordinate along the named direction wins.

### geom.find_filling_between(space_a, space_b, ifc_class: str)
The door or window that joins two rooms, or one room and the outside.

A door joins the rooms its host wall bounds, so the door the sentence
names is the one of that class whose wall bounds both rooms.  For "the
door that connects the room R to the outside", pass the words the sentence
uses in place of the second room: the wall is then one that the model marks
as external, or one that bounds the named room and no other.

### geom.find_host(filling)
The wall a named door or window sits in.

"the wall in which the door named D is located" is one call.  The door
fills an opening and the opening is cut into a wall, so the wall is two
hops away; this returns it, and raises ``LookupError`` when the element
fills no opening.

### geom.find_nearest(reference, ifc_class: str, storey)
The element of one class closest to another element.

For "the column nearest to the door named D on storey S": pass the door,
``'IfcColumn'`` and the storey.  Distance is measured between the centres
of the two bodies, which is where a reader looking at the model sees them
stand, and the reference itself is never the answer.

### geom.find_offset(reference, ifc_class: str, storey, direction, distance: float)
The element that stands a stated distance from another, along one axis.

For "the wall on storey S that stands about 24.1 m east (+X) of the column
named C": pass the column, ``'IfcWall'``, the storey, ``'east'`` and
``24.1``.  The sentence points at a spot, one that stands the stated
distance from the reference along the named axis.  Candidates are the
class's elements on that storey, placed by their placement origins.  One
counts when its offset along the named axis is within a tenth of the stated
distance, and never less than a quarter of a metre, of what the sentence
says; of those, the one standing closest to the spot itself is the answer.

### geom.find_opposite(reference, ifc_class: str, space)
The element facing another one across a room.

For "the wall opposite the wall named W across the space S": pass the wall
named W, ``'IfcWall'`` and the space.  The answer is an element of the
class bounding the room that runs parallel to W and stands on the other
side of the room's centre, measured along the line square to W.  A door or
a window runs along its host wall.  When several stand on the far side, the
one facing W over the longest stretch inside the room is the answer, and
between two that face it equally, the one nearer the room's centre.  A room with no parallel
element on the far side, or with two equally near, has no answer, and the
error names the elements standing nearest to where one would be.

### geom.find_ordinal(host, ifc_class: str, direction, index: int)
The nth door or window along a wall, counted from one side.

For "the first window from the south along the wall named W": pass the
wall, ``'IfcWindow'``, ``'south'`` and ``1``.  The wall's fillings of that
class are put in order by the centres of their bodies, starting at the side
the sentence counts from, and the nth of them is the answer.  ``index``
counts from one, as the sentence does.

### geom.find_under(elements_or_storey, ifc_class: str)
The slab the given walls stand on.

"the slab below the walls of the ground storey" is one call: pass the
storey and the class.  Pass a list of elements instead to name them one by
one.  The rule is the one a reader applies: of the elements of that class
whose top face lies at or just below the base of the walls, the one whose
plan outline covers most of the ground the walls stand on.

### geom.find_wall_between_rooms(room_a, room_b)
The one wall that stands between two rooms, one on each of its sides.

A wall counts when its body is thin in plan, each room's box comes within
0.15 m of one of its two long faces, the two rooms are on opposite faces,
and each room runs along the wall for at least 0.8 m.  Raises
``LookupError`` when no wall or more than one wall fits.

### geom.find_without(scope, ifc_class: str, missing)
The element of one class that nothing of the named kind is attached to.

``scope`` is the storey or the space the sentence names, ``ifc_class`` the
class it asks for, and ``missing`` the class the sentence excludes, or
several of them:

* "the wall on storey S that hosts no door and no window" is
  ``find_without(storey, 'IfcWall', ('IfcDoor', 'IfcWindow'))``;
* "the wall bounding the space S that hosts no door" is
  ``find_without(space, 'IfcWall', 'IfcDoor')``;
* "the space on storey S that no window bounds" is
  ``find_without(storey, 'IfcSpace', 'IfcWindow')``;
* "the only column on storey S that is connected to no other element" is
  ``find_without(storey, 'IfcColumn', 'connection')``, which names a
  relationship in plain words instead of a class.

What counts as attached follows from the class the sentence asks for.  A
wall carries doors and windows through the openings cut in it, so a wall is
kept when none of those is of an excluded class.  A room is bounded by the
elements recorded against it, so a room is kept when none of those is of an
excluded class; a room nothing at all bounds is not an answer, since the
model records nothing about what bounds it either way.

Returns the one element that matches, and raises ``LookupError`` naming
what it found when none does or when several do.

### geom.forget_geometry(model_or_entity=None) -> None
Drop what was read off a model, for one model or for all of them.

Call it after changing a model through plain ifcopenshell code rather than
through this module, so a later lookup reads the model again.

### geom.frame_of(product) -> np.ndarray
The product's placement as a 4x4 matrix whose translation is in metres.

### geom.guid_source(source, quiet: bool = True)
Draw created GlobalIds from ``source`` inside one block.

``source`` is a function of no arguments that returns a new GlobalId on
every call.  ``quiet`` silences the reports the creating functions print.
Both settings are restored when the block ends.

### geom.height(product)
How tall the product's body is, in metres.

### geom.host_wall_of(filling)
The wall a door or window is hosted in, or None.

### geom.hosted_in(wall, ifc_class: str = ) -> list
The doors and windows a wall hosts, through the openings it carries.

### geom.layer_thickness(type_object) -> Optional[float]
Total thickness of a type's material layers in metres, or None.

### geom.measure(product, name: str)
One measurement of an element in metres, by the name the phrase uses.

``plan_length`` is the longer plan side, ``height`` the body height and
``overall_width`` a filling's stated width.

### geom.move_filling(filling, host_wall, along: float, sill: Optional[float] = None)
Move a door or a window, with its opening, into another wall.

``along`` is the distance along the new wall's own x axis, in metres, to the
near edge of the opening, which is what "2.2 m along that wall from its
start point" states.  The wall the element came from is healed and the wall
it joins is cut instead, because the opening it fills is re-pointed rather
than rebuilt.

What the function reads off the model, so the caller never states it:

* where the opening sits across the new wall, which is 50 mm outside that
  wall's near face, and how deep it cuts, which is the wall's thickness
  plus 100 mm, both the way a new opening is cut;
* the leaf's own offset from its opening along the wall, which it keeps;
* how far the whole assembly rises or falls, which is the difference
  between the two walls' bases, so the element keeps the height above its
  wall's base that it had.  Pass ``sill`` to put the leaf's base at a
  stated height above the new wall's base instead;
* the leaf's new depth, which is the new wall's thickness where the leaf's
  body is a rectangular extrusion, and is left alone where it is not.

A leaf the model hangs from its own opening follows the opening and is not
moved twice.  Returns the wall the element left.

### geom.next_room_number(model) -> str
The number a new room takes: one past the highest room number.

### geom.next_tag(model) -> str
The next free seven-digit element number of the file, as a string.

### geom.on_storey(storey, ifc_class: str) -> list
Every element of one class the storey holds.

The walk is the benchmark's own: an element is on the storey it is
contained in, and an element that is only aggregated under a storey is on
that one.

### geom.opening_beside(filling, storey, distance: float, direction) -> dict
The box of an opening that copies another one, moved along its wall.

The new opening has the size and height of the opening ``filling`` fills,
passes through the whole thickness of the same wall, and is moved
``distance`` metres along ``direction``, such as "+x", which has to be the
way the wall runs.  Returns ``{"origin": corner, "extents": size}`` in the
storey's coordinates.

### geom.opening_centred(wall, like, storey) -> dict
The box of an opening centred along a wall, sized like another one.

The opening is as wide and as tall as the opening the door or window
``like`` fills and stands as high above this wall's base as that one
stands above its own wall's base; it is centred along the wall and passes
through its whole thickness.  Returns ``{"origin": corner, "extents":
size}`` in the storey's coordinates.

### geom.opening_of(filling)
The opening a door or window fills, or None.

### geom.opposite_ranking(reference, space, members, locate, direction, outline)
The rule behind "the element opposite R across the space S".

Shared by this library and by the task generator, which pass their own
readers: ``locate`` (element -> world centre), ``direction`` (element ->
unit plan direction) and ``outline`` (element -> plan hull); the numbers
and the tests are the same in both.

The reference's normal is its plan direction turned a quarter turn, pointed
at the side of the room's centre the reference stands on.  A member
qualifies when it runs parallel to the reference and its centre stands more
than ``OPPOSITE_MARGIN`` past the room's centre on the other side.  Of the
members that qualify, the one facing the reference over the longest stretch
wins (the stretch is measured along the reference and inside the room);
members that face it over the same stretch, within ``OPPOSITE_TIE``, are
decided by which stands nearest the room's centre, and members within
``OPPOSITE_TIE`` of that one tie with it.

Returns ``(winners, near, problem)``: ``winners`` is the list of tied best
elements (empty when nothing qualifies), ``near`` pairs every other member
with its plan distance from the reference's mirror image across the room's
centre, and ``problem`` is a sentence when the question cannot be asked at
all.

### geom.origin_in_frame(product, frame_product)
The product's placement origin, read in another product's frame, metres.

A spatial instruction that says "6 m to the east of the slab named X" is
measured from X's placement origin expressed in the storey's own system,
which is what this returns.

### geom.origin_point(product)
The product's placement origin in world metres, as a numpy array.

This is where the model files the element, not where its body sits.  A
wall's origin is at one end of it, so an instruction that measures from
element to element along an axis is read from origins and an instruction
that says "nearest" or "between" is read from body centres.

### geom.overall_width(product)
A door's or a window's ``OverallWidth``, in metres, or None.

### geom.place_in_structure(product, storey) -> None
Put a product into its storey: aggregated for a space, contained else.

### geom.plan_direction(product)
The unit plan direction an element runs along, in world axes.

A door or a window runs along its host wall.  A wall runs along its
``Axis`` curve where the file has one; otherwise, and for any other
element, along the long side of the smallest rectangle around its body's
plan; an element whose plan is close to square runs along its placement's
x axis.  The sign is fixed so that the x component is not negative, since
only the line matters.  Rotated buildings are read in their own axes, never
in world x and y.

### geom.plan_length(product)
The longer of the product's two plan sides, in metres.

This is the length an instruction means by "longer than 6.00 m" for a wall
or a slab, whichever way the element runs.

### geom.plan_outline(product)
Convex hull of the body's plan, world metres, as an (n, 2) array, or None.

The raw solid is read, before openings cut into it.

### geom.rectangular_section(product) -> Optional[tuple]
A column's rectangular cross-section in metres, sorted, or None.

### geom.replace_filling(old_filling, ifc_class: str, name: Optional[str], width: float, height: float, sill: float = 0.0, predefined_type: Optional[str] = None)
Swap a door for a window, or a window for a door, in the same wall.

The old element and the opening it filled are removed together, which
leaves the wall whole, and a new opening is cut at the position the old one
held.  "At the same position along the wall" is read from the old opening,
so the caller only states the new element's size and sill.  The new leaf is
never narrower than the hole it inherits.

Returns the created leaf.

### geom.revit_type(model, kind: str, thickness: Optional[float] = None, width: Optional[float] = None, depth: Optional[float] = None, height: Optional[float] = None)
The type a new element of one kind and size is put under.

A wall or a floor slab takes the file's own type whose material layers add
up to ``thickness`` within a millimetre; a column takes one whose elements
have the ``width`` by ``depth`` rectangular cross-section within a
millimetre; a door or a window takes one whose elements are ``width`` wide
and ``height`` tall within ten millimetres.  Where the file has none, a
type is created under the name Revit gives its generic family of that size
("Basic Wall:Generic - 200mm", "Floor:Generic 250mm",
"M_Concrete-Rectangular-Column:300 x 450mm",
"M_Door-Passage-Single-Flush:0915 x 2134mm", "M_Window-Fixed:1200 x 1500mm"),
a wall or slab type with one material layer of that thickness.  Lengths are
metres.

### geom.room_inside_walls(walls, storey, height: Optional[float] = None) -> dict
The box a room fills inside four walls that close a rectangle.

Two of the walls run along x and two along y; the room reaches from the
inner face of each to the inner face of the one opposite, stands on their
common base and is ``height`` metres tall, or as tall as the four walls
share.  Returns ``{"origin": corner, "extents": size}``.

### geom.set_property(element, pset_name: str, property_name: str, value, value_type: Optional[str] = None)
Write one property into a named property set on one element.

The set is created when the element does not carry it.  A set the model
shares between several elements is copied for this element first, so the
value never lands on an element the instruction is not about.  The value
type follows the property's name for the standard sets and from the value
otherwise; pass ``value_type`` to write it as something else.

Returns the property set the value now sits in.

### geom.slab_above(slab, storey, distance: float, thickness: float) -> dict
The box of a slab with another slab's plan, a stated distance above it.

The new slab's underside stands ``distance`` metres above the named
slab's top face and it is ``thickness`` metres thick.  Returns
``{"origin": corner, "extents": size}``.

### geom.slab_on_room(room, storey, thickness: float) -> dict
The box of a slab that covers a room's plan and rests on its top.

The slab has the plan of the room's own box, its underside is the top of
the room and it is ``thickness`` metres thick.  Returns
``{"origin": corner, "extents": size}``.

### geom.slab_over_walls(walls, storey, thickness: float) -> dict
The box of a slab that covers four walls up to their outer faces.

The slab reaches the outer face of each of the four walls around a room
and its top lies at the level of the storey above, so it closes the storey
the way a floor of the next storey would.  Returns
``{"origin": corner, "extents": size}``.

### geom.sole_extrusion(product)
The product's one extruded body, or None when it has no single one.

### geom.spot_beside(wall, space, length: float, width: float)
Where a new element stands against a wall, inside a space, touching it.

The wall's short plan axis is the one the element stands off; the element's
near face sits on the wall face that looks into the space, the element is
centred on the wall along the wall's long plan axis, and its base is the
space's own floor.  ``length`` runs along the wall and ``width`` across it.
Returns the lowest corner in world metres.

### geom.spot_beside_wall_in_space(wall, space, length: float, width: float)
Where a new element stands against a wall, inside a space, touching it.

The wall's short plan axis is the one the element stands off; the element's
near face sits on the wall face that looks into the space, the element is
centred on the wall along the wall's long plan axis, and its base is the
space's own floor.  ``length`` runs along the wall and ``width`` across it.
Returns the lowest corner in world metres.

### geom.spot_on_top_of(reference)
Where a new element stands to sit on a reference element's top face.

Returns ``(lo, size)`` in world metres: the lowest corner over the
reference's own footprint and at its top, and the footprint's plan size.
The caller states the new element's own height.

### geom.storey_above(storey)
The storey immediately above this one, or None.

### geom.storey_below(storey)
The storey immediately below this one, or None.

### geom.storey_of(product)
The building storey the product is contained in, or None.

### geom.to_file_units(metres: float, model_or_entity) -> float
A length in metres, written in the file's own length unit.

### geom.to_metres(value: float, model_or_entity) -> float
A length in the file's own unit, written in metres.

### geom.turn_element(element, degrees: float, pivot=own)
Turn one element about the vertical axis by a stated angle.

``degrees`` is measured anticlockwise seen from above.  ``pivot`` says which
vertical line the element turns about: ``'own'`` for its own placement
origin, ``'centre'`` for the middle of its plan, or a point in world metres.
The element's own placement is rewritten, so its openings and the doors and
windows they hold turn with it.

### geom.unit_scale(model_or_entity) -> float
Metres per file length unit (1.0 for metres, 0.001 for millimetres).

### geom.wall_axis(wall)
Which world axis a wall runs along, and where its centre line sits.

Returns ``(word, value)``: the direction word of the axis the wall's own
length runs along, and the coordinate of its centre line on the other plan
axis, in world metres.  This is the plane an instruction means by "the
vertical plane that follows the axis of the wall named W".

### geom.wall_between(wall_a, wall_b, storey, thickness: float, height: Optional[float] = None) -> dict
Where a wall stands that closes the gap between two facing walls.

The two walls are parallel and face each other.  The new wall runs at right
angles to both, from the face of one to the face of the other, centred on
the stretch over which they face each other, and stands on their common
base.  ``height`` defaults to the height the two share.  Returns the box as
``{"origin": corner, "extents": size}`` in the storey's coordinates.

### geom.wall_box(wall) -> dict
The wall's own body, measured in the wall's placement frame, in metres.

The keys are the ones a filling needs: ``start`` and ``end`` along the wall,
``near`` and ``far`` across it, ``base`` and ``top``, and the derived
``length``, ``thickness`` and ``height``.  A wall whose body cannot be
meshed returns ``None``.

### geom.wall_from_jamb(door, wall_a, wall_b, storey, distance: float, direction, thickness: float, height: Optional[float] = None) -> dict
Where a wall stands that starts a stated distance past a door's jamb.

The new wall spans at right angles between the facing walls ``wall_a`` and
``wall_b``.  ``direction`` is the axis the distance is counted along, such
as "+y"; the jamb is the side of the door's body facing that way, and the
new wall's near face stands ``distance`` metres beyond it.  Returns the box
as ``{"origin": corner, "extents": size}`` in the storey's coordinates.

### geom.world_box(product, disable_openings: bool = False)
The product's axis-aligned box in world metres, as ``(lo, hi)``.

``disable_openings`` reads the raw solid, before the openings cut into it,
which is what a wall's thickness and length have to be measured on.

## Conventions used by the instructions

- Positions 'along the wall from its start point' are measured along the wall's own x axis from the start of its body (geom.wall_box(wall)['start']), in metres, to the near edge of the door or window leaf; 'centred at' positions name the middle of the leaf (use along_is_centre=True).
- A sill height is measured above the base of the host wall. Widths and heights size the leaf.
- Directions such as +X, -Y, north or east are world axes of the building (+Y is north); 'in that storey's own coordinates' means the storey's placement frame (frame='storey'), a bare coordinate means the world frame.
- 'The wall opposite W across the space S' is the element bounding S that runs parallel to W (|cos| of the angle at least 0.9) and stands on the far side of the room's centre; among several, the one facing W over the longest stretch, then the one nearest the room's centre. geom.find_opposite applies this rule.
- Every length in an instruction is in metres whatever unit the file uses; the helper functions convert.
- Names are matched exactly against Name (and LongName for spaces). A GlobalId identifies one element.
- If the instruction leaves out a value or a reference the edit needs (which element, which size, which distance), do not edit and do not commit; reply with a question that names the missing value. This overrides the sentence about sensible defaults in the system message.
- Create exactly the requested element with the requested relationships (containment in the storey, the opening for a door or window, the type if named), change nothing else, and call commit() once when the edit is complete.

## Three worked examples (reference dialogues on other buildings)

### Example 1
User:
Please add a new window named 'Glazing unit 605' in the wall opposite the wall named 'Basic Wall:Party Wall - CMU Residential Unit Dimising Wall:143239' across the space 'B202', 1.2 meters wide and 1.4 meters high, 4.63 meters along the wall from its start point and with its sill 0.9 meters above the wall's base. Cut the opening it fills.

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

# find the element facing the named one across the space
space = by_name('IfcSpace', 'B202')
reference = by_name('IfcWall', 'Basic Wall:Party Wall - CMU Residential Unit Dimising Wall:143239')
hits = [geom.find_opposite(reference, 'IfcWall',
                           space)]
for e in hits:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'B202' -> 0BTBFw6f90Nfh9rP1dl_3A IfcSpace B202
named 'Basic Wall:Party Wall - CMU Residential Unit Dimising Wall:143239' -> 2O2Fr$t4X7Zf8NOew3FKau IfcWall Basic Wall:Party Wall - CMU Residential Unit Dimising Wall:143239
2O2Fr$t4X7Zf8NOew3FLOH IfcWallStandardCase Basic Wall:Exterior - Brick on Block:143534
```
Assistant: I will check the element's class and position first.
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
    matrix = np.array(
        ifcopenshell.util.placement.get_local_placement(placement), dtype=float)
    return matrix[:3, 3] * unit_scale

for target_guid in ('2O2Fr$t4X7Zf8NOew3FLOH',):
    target = ifc.by_guid(target_guid)
    print(target.is_a(), target.GlobalId, target.Name)
    point = world_point(target)
    if point is not None:
        print('  origin (m):', [round(float(v), 3) for v in point])
    print('  contained in:', [r.RelatingStructure.Name for r in getattr(target, 'ContainedInStructure', None) or ()])
```
Tool result:
```
IfcWallStandardCase 2O2Fr$t4X7Zf8NOew3FLOH Basic Wall:Exterior - Brick on Block:143534
  origin (m): [8.8, -17.591, 3.1]
  contained in: ['Level 2']
```
Assistant tool call execute_ifc_code:
```python
# the wall's length, thickness and height decide where the leaf goes
host = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FLOH')
print(host.GlobalId, host.is_a(), host.Name)
wall_box = geom.wall_box(host)
print('wall (m):', {k: round(v, 3) for k, v in wall_box.items() if not isinstance(v, str)})
```
Tool result:
```
2O2Fr$t4X7Zf8NOew3FLOH IfcWallStandardCase Basic Wall:Exterior - Brick on Block:143534
wall (m): {'start': 0.0, 'end': 8.8, 'near': -0.209, 'far': 0.209, 'base': 0.0, 'top': 2.9, 'length': 8.8, 'thickness': 0.417, 'height': 2.9}
```
Assistant tool call execute_ifc_code:
```python
# geom does the placement and the relationships
host = ifc.by_guid('2O2Fr$t4X7Zf8NOew3FLOH')
unit = geom.add_filling(host, 'IfcWindow', 'Glazing unit 605', width=1.2, height=1.4,
                        along=4.63, sill=0.9)
```
Tool result:
```
(code executed, no output)
```
Assistant: Confirming the change, then persisting it.
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
print(unit.GlobalId, unit.is_a(), unit.Name)

# save the edit
commit()
print('model committed')
```
Tool result:
```
00zY908cj1qfYMi$tAujCj IfcWindow Glazing unit 605
model committed
```
Assistant: The new window is in the model, and the edit is written to the working file.

### Example 2
User:
Can you assign the wall on storey 'Basement (Parking)' that stands about 30.0 m south (-Y) of the column named 'W-Wide Flange-Column:W10X49:242936' to the type object named 'Basic Wall:Foundation - 12" Concrete'?

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

# find the element at the stated offset from the named neighbour
storey = by_name("IfcBuildingStorey", "Basement (Parking)")
reference = by_name("IfcColumn", "W-Wide Flange-Column:W10X49:242936")
matches = [geom.find_offset(reference, "IfcWall", storey,
                            "south", 30.0)]
for e in matches:
    print(e.GlobalId, e.is_a(), e.Name)
```
Tool result:
```
named 'Basement (Parking)' -> 1MvMAoc2L5LRJwssbEGR_8 IfcBuildingStorey Basement (Parking)
named 'W-Wide Flange-Column:W10X49:242936' -> 035YSKYkr8NOOGM8TzJZ8o IfcColumn W-Wide Flange-Column:W10X49:242936
1IiP9o4hb8NBes6GXXNwHO IfcWallStandardCase Basic Wall:Retaining - 14" Concrete:215619
```
Assistant: I will list what depends on it first.
Assistant tool call execute_ifc_code:
```python
# the type objects the model already defines
candidates = []
for ifc_class in ("IfcWallType", 'IfcTypeProduct'):
    try:
        candidates = list(ifc.by_type(ifc_class))
    except Exception:
        candidates = []
    if candidates:
        break
for element in sorted(candidates, key=lambda t: (t.Name or '')):
    print(element.GlobalId, element.is_a(), element.Name)
```
Tool result:
```
1krdmuBkzDbgRKCWsf465v IfcWallType Basic Wall:Foundation - 12" Concrete
1krdmuBkzDbgRKCWsf465F IfcWallType Basic Wall:Generic - 8"
1IiP9o4hb8NBes6GXXNwR2 IfcWallType Basic Wall:Retaining - 14" Concrete
```
Assistant: This makes the change the instruction asks for.
Assistant tool call execute_ifc_code:
```python
# put the element under the type object the instruction names
geom.assign_type(ifc.by_guid("1IiP9o4hb8NBes6GXXNwHO"),
                 ifc.by_guid("1krdmuBkzDbgRKCWsf465v"))
```
Tool result:
```
(code executed, no output)
```
Assistant tool call execute_ifc_code:
```python
# confirm the edit landed before saving
element = ifc.by_guid("1IiP9o4hb8NBes6GXXNwHO")
print(element.is_a(), element.GlobalId, element.Name)

# save the edit
commit()
print("model committed")
```
Tool result:
```
IfcWallStandardCase 1IiP9o4hb8NBes6GXXNwHO Basic Wall:Retaining - 14" Concrete:215619
model committed
```
Assistant: Done. The wall now carries the values the instruction asked for, and the model has been saved.

### Example 3
User:
Can you change the fire rating of the window in Pset_WindowCommon from 'FireRating' to 'F30'?

IFC model path: <path to the working copy>
Assistant: First I need to find the element the instruction describes.
Assistant tool call execute_ifc_code:
```python
# which element the instruction means is not stated
candidates = ifc.by_type('IfcWindow')
print(len(candidates), 'IfcWindow', 'in the model')
for target in candidates[:20]:
    print(' ', target.GlobalId, target.Name)
```
Tool result:
```
24 IfcWindow in the model
  1hOSvn6df7F8_7GcBWlR72 M_Fixed:4835mm x 2420mm:4835mm x 2420mm:145788
  1hOSvn6df7F8_7GcBWlRBU M_Fixed:4835mm x 2420mm:4835mm x 2420mm:146016
  1hOSvn6df7F8_7GcBWlRLx M_Fixed:750mm x 2200mm:750mm x 2200mm:146885
  1hOSvn6df7F8_7GcBWlRRL M_Fixed:750mm x 2200mm:750mm x 2200mm:147051
  1hOSvn6df7F8_7GcBWlSXO M_Fixed:2800mm x 2410mm:2800mm x 2410mm:147686
  1hOSvn6df7F8_7GcBWlSga M_Fixed:819mm x 759mm:819mm x 759mm:147994
  1hOSvn6df7F8_7GcBWlSp1 M_Casement:819mm x 759mm:819mm x 759mm:148607
  1hOSvn6df7F8_7GcBWlSnC M_Fixed:819mm x 759mm:819mm x 759mm:148722
  1hOSvn6df7F8_7GcBWlS_W M_Fixed:2800mm x 2410mm:2800mm x 2410mm:149278
  1hOSvn6df7F8_7GcBWlS2V M_Fixed:819mm x 759mm:819mm x 759mm:149537
  1hOSvn6df7F8_7GcBWlS1M M_Casement:819mm x 759mm:819mm x 759mm:149736
  1hOSvn6df7F8_7GcBWlS4Q M_Fixed:819mm x 759mm:819mm x 759mm:149924
  1l0GAJtRTFv8$zmKJOH4$e M_Fixed:2800mm x 2410mm:2800mm x 2410mm:180318
  1l0GAJtRTFv8$zmKJOH4u1 M_Fixed:819mm x 759mm:819mm x 759mm:180663
  1l0GAJtRTFv8$zmKJOH4qs M_Fixed:819mm x 759mm:819mm x 759mm:180864
  1l0GAJtRTFv8$zmKJOH4oq M_Casement:819mm x 759mm:819mm x 759mm:180994
  1l0GAJtRTFv8$zmKJOH4pU M_Fixed:2800mm x 2410mm:2800mm x 2410mm:181096
  1l0GAJtRTFv8$zmKJOH4kJ M_Fixed:819mm x 759mm:819mm x 759mm:181285
  1l0GAJtRTFv8$zmKJOH4gQ M_Casement:819mm x 759mm:819mm x 759mm:181548
  1l0GAJtRTFv8$zmKJOH4hv M_Fixed:819mm x 759mm:819mm x 759mm:181583
```
Assistant: Which window do you mean?
