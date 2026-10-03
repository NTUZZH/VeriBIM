"""Version stamp carried by every generated task record.

0.2.0 (2026-08-25) is the first version whose gold models can be rebuilt from
their gold scripts at any later time, in any process, and come back byte for
byte.  Two things had to change for that.  A deletion used to leave the
wall-clock moment of generation in the owner history of the entities it
touched.  It also left the members of the SET-valued relationships it changed
in whatever order the removing process happened to produce, which depends on
that process's hash seed; those members are now sorted.  The version also adds
the sharded driver, the building-level split, the recorded created and removed
identifiers, and the option to discard a gold model once it is verified.

0.3.0 (2026-09-07) makes a drawn placement answer to the geometry of the model
rather than to its placement origins.  Every storey now carries a footprint
measured over the triangulated bodies of its elements, and a created box is
refused and redrawn when it would fall outside that footprint or occupy matter
another element already holds.  A new door or window is refused when the wall
is not tall enough to carry it and redrawn when it would land on a filling the
wall already has, and its sill is measured from the base of the wall's own
extrusion rather than from the wall's placement origin.  A move is bounded by
the same storey footprint and by the same collision test, a moved door or
window carries the opening it fills and stays inside its host wall, and a
target whose openings or fillings would be stranded is refused.  The leaf of a
created door or window now takes the wall's own thickness while only the
opening cuts past both faces.  The version also adds the option to remove a
deleted door's or window's opening with it, which is off by default.

0.4.0 (2026-09-07) turns that option on by default, so removing a door or a
window removes the opening it filled, the relationship that voided the wall and
the relationship that filled the opening, and leaves the wall itself intact.
The convention now matches the gold models of BIM-Edit, and a wall is no longer
left cut for a leaf that is gone.  The compositional tier removes a wall's doors
and windows the same way.

0.4.1 (2026-09-07) closes the three gaps a physical audit of the rebuilt test
split found.  A storey turned against the world axes is now compared with the
created element's own corners in world axes rather than in the storey's, so a
turned storey no longer lets an element land outside the building.  A door or a
window placed relative to its opening is moved by moving that opening, which
carries the leaf, rather than by moving both and displacing the leaf twice, and
two products that share one placement are recognised as moving together.  The
collision test reads two lattices instead of one and refuses at a smaller share,
so a body cannot slip between the points of a single lattice.

0.5.0 (2026-09-07) adds the requirement families the public benchmark's task
scope carries and the generator could not express.  A create task may now state
the relationships the new element has to carry, and the gold writes them: an
``IfcRelSpaceBoundary`` for the rooms it bounds, or the rooms a new room is
bounded by, and an ``IfcRelConnectsElements`` for the elements it connects to.
A create task may also leave the position to be read off other elements, through
six constructions: closing the gap between two walls in line with each other,
standing on the top face of a named element, standing against a named room's
boundary wall, rising to the underside of a named slab, placing a leaf by its
middle rather than its edge, and lining a leaf up with one on the storey above
or below.  A coordinate may be quoted in the world frame rather than the
storey's, with the storey's own elevation rather than zero, and a wall may be
set out as the line its faces follow.  Six anchor kinds join the nine earlier
ones: the nearest element of a family to a named one, the element between two
named ones, the element directly above or below one on the storey next door, the
wall that separates two named rooms, the element facing another across a room,
and the element on one side of a named door seen from that door looking into a
named room.  An update or a delete may carry an invariance clause the gold
already satisfies.  A relationship is only stated between ends that meet: the named room
or element has to stand within 0.15 m of the created element, measured between
their world boxes, and the same holds of the two rooms a `separates` phrase
names.  The funnel gains three checks, one that every relationship the
instruction named exists in the gold with the ends it named, one that those two
ends are not far apart, and one that a created element quoted in world
coordinates stands where those coordinates put it.  Each record now names the families it carries and the relationship classes its
gold writes, so a training set can be stratified on them.  The names are the
project's requirement taxonomy of 2026-09-07, so a tag written now and a tag
written by a later version count together, and a record carries a label for
every layer this version can settle: the operation, the reference, the
specification, the constraints, the scope and the wording.  Which families exist,
how often each is drawn and what builds it live in one registry rather than in
the planners, so adding a family is adding an entry and a function and the
driver never learns its name.  Nothing an
earlier version wrote changes: the earlier gold calls keep their signatures, a
record written before this version carries neither new field, and every check
still passes on it.

0.6.0 (2026-09-08) adds the operations of the taxonomy's first layer and the
scopes of its fifth.  An element may now be turned about the vertical axis
through a stated angle, about its own placement origin or about the centre of
its plan; reflected across the axis of a named wall or across a stated vertical
plane, which is written as a proper rotation of the element's frame together
with a flip of its own profile, so the body is the mirror image rather than an
approximation of it; given a property-set value in ``Pset_WallCommon`` and its
siblings, written as an ``IfcPropertySingleValue`` of the right type inside a
set the element owns; associated with a material; assigned to a type object;
moved into another storey, either standing where it stood or keeping the
position it had inside its old storey; and, for a door or a window, moved with
its opening into another wall, which heals the wall it left.  A create task may
now duplicate an element at an offset, write a row of copies at a fixed spacing,
or put a door where a window stood and a window where a door stood.  An
instruction may name a whole set rather than one element, by the storey its
members sit on, by the wall that hosts them or by the room they bound, and may
narrow that set by a measured condition; the gold then writes one edit over
every member, and a new funnel check compares every element the set was drawn
from between the source model and the gold, so the word "all" is true of the
file.  Two further references join the list: the place an element holds in a
row of fillings counted from a named direction, and the element that lacks
something the others have.  A door or a window moved into another wall carries
its opening with it and keeps the offset the model gave it inside that opening,
and the place it is moved to has to be free of what the storeys around it
already hold; the same rule guards the leaf a replacement writes.  A material is
drawn from what the family is plausibly made of rather than from whatever the
file happens to name, a space is never given one, and a conditional threshold is
a multiple of half a metre that keeps between a third and two thirds of the set.
Nothing an earlier version wrote changes: the
earlier gold calls keep their signatures, a record written before this version
carries no new field, and every check still passes on it.
0.7.0 (2026-09-08) makes the generator aware of the conditions the source
models themselves carry, and of the fact that one requirement can be written in
more than one way.

*The model's own conditions.*  Every record now names them, measured off the
file rather than declared: the length unit, the schema version, whether the
storey the edit touches is turned against the world axes, whether the site
stands far from the world origin, what kind of body the edited element carries,
and whether the names the instruction quotes are written in English.  A storey
drawn on a skewed grid is no longer refused a world-frame coordinate: the point
is converted through the storey's own placement, the instruction says the
numbers are world coordinates and how far the storey is turned, and the funnel
checks the created element's placement origin against the point the instruction
quoted, once from the file's own arithmetic and once from the geometry index.
The two layouts that state a size per world axis, the endpoint span and the
axis dimensions, are refused on a turned storey, because a length along a world
axis is not the length of an element built on a skewed grid.

*The wording.*  An instruction may now open with a different verb of the same
meaning, be written as a request, a question or an order with one line of
context in front of it, name the element by its IFC class rather than in plain
words, and state its lengths in millimetres or centimetres, or in metres spelled
out, where the file is written in that unit.  Every variant is an exact
substitution on the sentence the templates wrote, never a rewrite: a verb only
at the head of the sentence and a reference phrase only where the anchor's own
phrase stands, so the gold script's calls are the same under every wording.  The
funnel reads the reference back out of the finished sentence and resolves it
again.

*Instructions that leave something out.*  A small share of draws states the
change without saying which element it is meant for, which storey a new element
goes on, or what the new value is.  The gold of such a task changes nothing,
because the reader cannot know what to change, and the record carries the
question a correct answer asks.  The funnel checks that the value the record
says is missing is really missing, that more than one element fits, and that the
gold model is the source model with nothing done to it.  ``ScorerConfig`` gains
``underspecified_mode``, off by default, which scores such a task by the two
facts that decide it: the file came back unchanged, and the reply asks about the
missing value.  Every other task, and every BIM-Edit task, is read exactly as
before.

``build_canonical`` now subsamples every edit kind an unedited model can
half-answer rather than the three the first two waves named, which is what the
0.6.0 pilot found the recipe was missing.

0.7.1 (2026-09-10) records no reference where a sentence carries none.  Some
instructions never quote the phrase their anchor resolves to: a compositional
create names the storey the new element goes on and says nothing about the
element the anchor found, so 0.7.0's wording check, which reads the reference
back out of the finished sentence, refused every spatial draw of that cell.
The wording layer now writes an empty phrase into the record there, and the
check reads the record rather than the anchor, so a sentence with no reference
in it passes while one that quoted a reference and then lost it is still
refused.  A record written before this version stores no wording at all and is
still read against its anchor's own phrase.

0.7.2 (2026-09-12) adds two draw-side rules the physical audit of the v2 wave
asked for.  A resize now reads the fillings the element carries: a swept depth
grows from the base of the sweep and a rectangular profile shrinks about its
own centre, so the new span of the body is compared with each door's and each
window's own box and a draw that would leave one outside the body is refused.
Measured on the seven gold models the audit faulted for it, the rule refuses
all seven.  A move and a reflection also read the storeys a create reads, the
element's own and those of its host and of the fillings it carries, so the
three paths ask one question rather than three.

That second rule is not the cause of the three collisions the same audit
found.  Measured on all three, the wider reading adds no storey, and on the one
that moves a door the narrow reading already scores the destination full.  What
those three share is a collision with an element the test skips, the moved
element's own host or its own filling, which a reflection carries rigidly while
it reflects the body, so a wall that is not symmetric about the plane ends up
standing in its own window.  Testing that needs the geometry the skipped
elements will have after the edit, which only the physical audit rebuilds
today, and it is left open rather than guessed at.

Nothing an earlier version wrote changes: the earlier gold calls keep their
signatures, a record written before this version carries none of the new fields,
and every check still passes on it.

0.9.0 (2026-09-23) changes how an instruction writes an identifier.  Every
sentence that carries one draws its spelling from ``wording.identifier_spelling``
(twelve forms, the quoted "with GlobalId 'X'" of every earlier version kept at
40 %), and in 40 % of sentences (``wording.reference_by_id``) the reference
elements and rooms the phrase names by name are named by identifier instead,
with two of one noun side by side written as one list
(``wording.identifier_list``); a storey that is the phrase's only reference is
switched on its own 40 % draw, and one beside element references in half of the
sentences that switch them.  A ``name`` anchor switched this way is recorded as
a ``guid`` anchor.  A room may be named through two of its bounding elements
(``space_of`` with ``element_b_guid``), and a direct instruction may name a set
by listing its members' identifiers (``set`` with scope ``ids``).  The rewrite
changes words only; the anchor's predicate, the element it resolves to and the
gold script body are those the plain wording has, and the record carries what
the rewrite did under ``wording.identifiers``.  0.8.0, the complete deletion and
the five references it added, was installed without a version bump; this entry
names both.
"""

GENERATOR_VERSION = "veribim-gen/0.9.0"
