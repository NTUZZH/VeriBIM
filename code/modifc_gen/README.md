# VeriBIM-Gen

An inverse generator of verified IFC editing tasks.  It turns a corpus of real
building models into tuples of the form (source model, instruction, gold model,
gold script), where the three parts agree by construction rather than by review.

The Python package is `modifc_gen`; the artifact it produces is VeriBIM-Tasks.

## The idea in one paragraph

A task is generated answer-first.  The generator samples a source model `M0` and
a parameterised edit from the operation library, writes the edit out as a short
Python script, and runs that script to produce the gold model `M*`.  The
instruction is then rendered from the same edit parameters.  Because the
instruction and the model both come from one set of numbers, they cannot
disagree; and because the script is written before it is run, the script in the
task record is by construction the script that produced the gold model.  A task
is only kept once four checks pass on the files themselves, and a task written
over a whole set of elements only once a fifth does.

## Install and run

Requires the `l2` environment (Python 3.14, ifcopenshell 0.8.5, numpy, scipy)
and the `modifc_score` package on the same path.

```bash
conda activate l2
export PYTHONPATH=<repository>/code

# 1. decide which source models a run may use, and which building each belongs to
python -m modifc_gen.pool --root <repository> \
    --out data/veribim_tasks_v1/pool.json \
    --exclude-buildings BLD003,BLD018,BLD029,...

# 2. generate a large task set, sharded, resumable, gold models discarded
python -m modifc_gen.scale --root <repository> --out data/veribim_tasks_v1 \
    --n-tasks 20000 --chain-share 0.16 --n-validation 1000 \
    --validation-buildings BLD001,BLD006,... \
    --workers 8 --heavy-workers 3 --cores 12-23 --seed 20260825

# 3. write the gold models of one split to disk and check each against its checksum
python -m modifc_gen.materialize --root <repository> \
    --tasks data/veribim_tasks_v1/tasks.jsonl --split validation \
    --workers 6 --cores 12-23

# 4. re-run every check from the task file alone, rebuilding gold models as needed
python -m modifc_gen.audit --root <repository> \
    --tasks data/veribim_tasks_v1/tasks.jsonl --rebuild --sample 500 \
    --workers 6 --cores 12-23
```

`modifc_gen.run` is the smaller single-pass driver used for the smoke set; it
takes the same operation library and funnel and writes every gold model to disk.

`--probe-only` stops after the yield probe, which writes `yield.json` and takes
about three minutes for the whole pool.  Workers are pinned to the cores given
by `--cores` and every numerical library is capped to one thread per worker.
Re-running the same `scale` command after an interruption resumes: a shard whose
result file is on disk is not generated again, and the run's identifiers are
namespaced per invocation so a resumed run cannot mistake a shard it still owes
for one already done.

## What a run writes

| file | contents |
|---|---|
| `pool.json` | the source models the run may use, with a building id on each |
| `tasks.jsonl` | one record per accepted task (schema below) |
| `models/<task_id>.ifc` | the gold model, for the splits that keep one on disk |
| `shards/<shard_id>.json` | one unit of work's records and outcomes, written as it finishes |
| `yield.json` | which cells of the design grid each source model can host |
| `funnel.json` | attempted, accepted, and every rejection reason |
| `outcomes.jsonl` | one line per attempt, accepted or not |

`tasks.jsonl` is directly loadable by `modifc_score.load_tasks`: the fields
`task_id`, `input_ifc`, `ground_truth_ifc`, `operation`, `category`, `prompt`
and `target` carry the meanings that package expects, and the generator's own
fields sit alongside them.

## The design grid

Three instruction styles by three operations by six element families, plus a
compositional tier.

*Styles.*  A **direct** instruction quotes the target's GlobalId and exact
dimensions.  A **spatial** instruction locates the target by geometry ("the wall
on storey 'EG' that stands about 8.5 m east (+X) of the wall named 'EG-I-2-2'").
A **topological** instruction locates it by relationships ("the door hosted in
the wall named 'EG-A-3-4'", "the wall that bounds both the space 'Kitchen' and
the space 'Hall'").

*Operations.*  **update** moves, resizes, renames or retypes one element, and,
from 0.6.0, turns it, reflects it, writes a property-set value on it, gives it a
material or a type object, moves it into another storey, or moves a door or a
window with its opening into another wall; **create** adds a wall, slab, column
or space on a storey, or a door or window hosted in a wall, with its placement,
its geometry and its relationships, and, from 0.6.0, duplicates an element,
writes a row of copies, or puts a door where a window stood; **delete** removes
an element together with everything that depended on it.

*Requirement families.*  An instruction is an operation on a reference, with a
specification and a set of constraints, at some scope.  Those layers are the
project's requirement taxonomy, and every family below is named after it, so a
record written now and a record written by a later version count together.
Beyond the three styles, an instruction may carry any of five further
requirements, and a run asks for a share of each.  A **create**
may state the relationships the new element has to carry, and may leave the
position to be read off other elements instead of quoting it.  A coordinate may
be quoted in the world frame rather than in the storey's, and a wall may be set
out as the line its faces follow.  An **update** or a **delete** may name its
target by a relative or a topological reference, and may carry an invariance
clause the gold edit already satisfies.  Each of these is a tag in the record's
`families` list, together with the operation the edit performs and the scope it
covers, so a training set can be stratified by layer.

*Conditions and wording.*  A record also names the conditions the source model
carries, from 0.7.0: its schema version, its length unit, whether the storey the
edit touches is turned against the world axes, whether the site stands far from
the world origin, what kind of body the edited element has, and whether the
names the instruction quotes are English.  The instruction itself is worded in
one of several ways drawn from the task's seed, and about one draw in twenty
leaves out a value the edit needs and expects a question rather than an edit.

*Compositional tier.*  Chains of two to seven edits with a real dependency:
delete the doors a wall hosts and then the wall, move a space and the walls that
bound it, add a wall and then a door hosted in that same new wall.  A fourth
chain, moving a wall and carrying independently placed fillings with it, is
implemented but rarely applies: the exporters in this corpus place a filling
relative to its host wall, so the wall's own move already carries it.

## Anchoring, and why it is checked

An anchor is a phrase plus a predicate.  The phrase goes into the instruction;
the predicate is run against the source model and must return the intended
element and nothing else.  A task whose anchor resolves to nothing, or to more
than one element, is rejected before it enters the dataset, which is what makes
it safe to ask for an element by its position or by its relationships.  Anchors
are stored in the record as a kind plus its parameters, so the check can be
repeated later from the record alone.

| kind | style | phrase |
|---|---|---|
| `guid` | direct | the wall with GlobalId '...' |
| `name` | direct | the wall named 'W-12' |
| `offset` | spatial | the door on storey 'EG' about 3.2 m east (+X) of the door named 'D-14' |
| `extreme` | spatial | the northernmost wall on storey 'EG' |
| `hosted` | topological | the door hosted in the wall named 'W-12' |
| `bounding` | topological | the wall that bounds both the space 'Kitchen' and the space 'Hall' |
| `space_of` | topological | the space bounded by the wall named 'W-12' |
| `connects` | topological | the column connected to the wall named 'W-12' |
| `in_storey` | topological | the only column contained in storey 'EG' |
| `nearest` (`ref.relative.nearest`) | spatial | the column nearest to the wall named 'W-12' on storey 'EG' |
| `between` (`ref.relative.between`) | spatial | the column on storey 'EG' that stands between the wall named 'A' and the wall named 'B' |
| `above_below` (`ref.relative.above_below`) | spatial | the column on storey 'OG1' directly above the column named 'C-3' |
| `separates` (`ref.topological.separates`) | topological | the wall that separates the space 'Kitchen' from the space 'Hall' |
| `opposite` (`ref.relative.opposite`) | topological | the wall opposite the wall named 'W-3' across the space 'Kitchen' |
| `egocentric` (`ref.viewpoint.through_door`) | topological | the wall on the left-hand side as seen from the door named 'D-14' looking into the space 'Kitchen' |
| `ordinal` (`ref.ordinal`) | spatial | the second door from the west along the wall named 'W-12' |
| `negation` (`ref.negation`) | topological | the space on storey 'EG' that no window bounds |
| `set` (`ref.set`) | topological | all the windows on storey 'EG' |

The word "separates" claims that the element touches both rooms, so the
relationship the source model carries is not enough on its own: the anchor is
kept only where the element's world box comes within 0.15 m of each room's, and
dropped where either body cannot be measured.

Directions are the model's own axes and the instruction says so, as in "north
(+Y)".  Positions are the elements' placement origins, except in the six kinds
above, which read the centre of the element's meshed body: a wall's origin sits
at one end of it, so a phrase like "nearest" would otherwise not mean what a
reader takes it to mean.

The last kind is egocentric.  The reader stands in a named doorway and looks
into a named room, so the direction is the door's host wall turned to face the
room and the left-hand side follows from it.  It is offered only where that
direction can be read from the model and where the predicate then returns one
element, and a target it cannot name falls back to another kind rather than
being refused.

### Where an instruction puts a new element

A create instruction either quotes the position or leaves it to be worked out.
Four kinds derive a box's position and two derive a leaf's, each with one
construction in the gold and one check in the funnel.

| family | what the instruction says |
|---|---|
| `spec.element_relative.fits_gap` | fits the gap between two named walls in line with each other, closing it exactly |
| `spec.element_relative.on_top_of` | sits directly on top of a named element, over the same footprint |
| `spec.element_relative.against_room_wall` | stands inside a named room, against a named boundary wall and touching it |
| `spec.element_relative.touching_slab_above` | rises from the storey's floor and stops at the underside of a named slab |
| `spec.element_relative.centred_on_wall` | the middle of the leaf sits a stated distance along the wall from its start |
| `spec.element_relative.aligned_with_filling` | the leaf lines up with a named door or window on the storey above or below |

A derived position is drawn only for the two styles that locate an element by
what is around it.  A direct instruction quotes numbers, and only the frame they
are read in may change.

### Which frame a coordinate is read in

| family | what the instruction says |
|---|---|
| (none) | with its base corner at (x, y, z) m in that storey's own coordinates |
| `spec.world_frame` | with its lowest corner at (x, y, z) m, no frame stated, z the storey's own elevation |
| `spec.endpoints` | running from (x1, y1, z1) to (x2, y2, z2) with a thickness of t in the -y direction and a height of h |
| `spec.axis_dimensions` | a length in the x-direction of 0.20 m and a width in the y-direction of 0.20 m |
| `spec.axis_displacement` | move it by 0.50 m in the +x direction |

The world forms change the words and not the place: `add_box_element_world`
converts the point into the storey's own system at run time, so the numbers the
work order quotes are the numbers the gold script carries.  A storey turned
against the world axes is refused rather than guessed at, because the size and
direction words would otherwise not mean what they say.

### Invariance clauses

An update or a delete may end on a clause that states something the gold edit
already does, so it binds the reader and not the generator:
`constraint.invariant.keep_placement` on a rename or a resize,
`constraint.invariant.keep_z` on a horizontal move,
`constraint.cascade.relations_preserved` on an update that changes no
relationship, and `constraint.cascade.relations_consistent` on a delete, whose
cascade is what the clause describes.  Which edits admit which clause is stated
once, beside the family in the registry.

### Relationships an instruction may require

A create may state which rooms the new element bounds, or which elements it is
connected to, and the gold script then writes the relationship.  The clause is
added only where the model can carry what it says: the rooms or elements named
have to exist on the same storey, have a name a phrase can use, and **touch the
new element**.  Contact is measured between world bounding boxes, the created
element's read from the parameters its create call will use and the partner's
from the geometry index, and a partner further than 0.15 m away is refused, as
is one whose body the index cannot measure.  Nearness is not contact: a room two
metres from a new column is not a room that column bounds, and an authoring tool
would not write the relationship.

| family | what may be required | what the gold writes |
|---|---|---|
| wall, slab, column, door, window | bounds the named rooms (`constraint.relation_on_create.space_boundary`) | `IfcRelSpaceBoundary`, the new element on the related end |
| space | the named walls bound it (`constraint.relation_on_create.space_boundary`) | `IfcRelSpaceBoundary`, the new room on the relating end |
| wall, slab, column | connected to the named elements (`constraint.relation_on_create.connection`) | `IfcRelConnectsElements` |

A boundary is written first-level and physical, and internal unless the new
element stands within half a metre of the edge of the storey's footprint.  A
minority of the clauses name the IFC class instead of saying it in plain words,
because a benchmark prompt sometimes does.  Every relationship class a task's
gold script writes is listed in the record under `requires_relations`.

## The operations of layer 1

Seven operations join the update family and three join the create family.  Each
one is a planner that refuses what the model cannot carry, a runtime function in
`goldlib.py` that writes it, and one entry in the registry.

| family | what the instruction asks for | what the gold writes |
|---|---|---|
| `op.update.rotate` | turn the element by a stated angle about the vertical axis, about its own placement origin or about the centre of its plan | the element's own frame, turned about that world point |
| `op.update.mirror` | reflect the element across the axis of a named wall, or across a vertical plane at a stated coordinate | a proper rotation of the element's frame together with a flip of its own profile |
| `op.update.pset` | set or change a value in `Pset_WallCommon` and its siblings | an `IfcPropertySingleValue` of the stated type, inside a set the element owns through an `IfcRelDefinesByProperties` |
| `op.update.material` | associate the element with a named material a building of that kind is made of | an `IfcRelAssociatesMaterial` to an `IfcMaterial` the file carries or one created for it |
| `op.update.type_object` | assign the element to a named type object | an `IfcRelDefinesByType` |
| `op.update.restorey` | move the element into another storey, either standing where it stood or keeping the position it had inside its storey | a new containment relationship and a re-hung placement |
| `op.update.rehost` | move a door or a window into another wall | the opening re-pointed at the new wall, and the opening and the leaf carried into that wall's frame by one offset |
| `op.copy` | duplicate the element at a stated offset | a new element of the same class with a copy of the body, in the same storey |
| `op.array` | write n copies at a stated spacing along an axis | n such elements, the nth at n times the offset |
| `op.replace` | put a door where a window stood, or the other way round | the element and its opening removed, then an opening cut and filled in the same wall |

A mirror is exact rather than approximate.  A reflection turns a right-handed
frame into a left-handed one, which IFC does not carry.  The edit is therefore a
proper rotation of the element's frame composed with a flip of the element's own
swept profile about that profile's centre.  The two compose to the reflection,
which the tests check against the triangulated body.  An element whose profile
cannot be flipped is refused.  That covers a profile drawn in a system of its own
and a solid swept along something other than the element's own vertical.

A copy carries the original's class, its attributes and a duplicate of its body,
and joins the storey the original sits in.  An element that hosts a door or a
window is not copied, because the copy would carry no opening while the
instruction says it is a duplicate.

A material is drawn from what the family is plausibly made of, not from what
the file happens to name.  A wall is asked for brick, concrete, aerated block,
cross-laminated timber or plasterboard; a slab for reinforced, precast or
composite construction; a column for concrete, steel or glulam; a door and a
window for timber, steel, aluminium or PVC-u.  A space is never asked, because
a room is a volume of air.  A name the model already carries is preferred, so
the instruction asks for something the building is built of, but only when that
name means the material the vocabulary asked for.  Which material a name stands
for is decided by the longest keyword it contains, in English and in the other
languages this corpus is written in, so `Stahlbeton` is reinforced concrete
rather than steel.  Where the file names nothing suitable the material is
created under the plain name, which is then the name the instruction quotes.

A re-hosting and a replacement both put a leaf somewhere it did not stand, so
both measure the ground the leaf's own body would take against what the storeys
around it already hold, and move along the wall until it is free.  A wall long
enough is not by itself a wall a leaf can stand in: a crossing wall, a radiator
or a piece of furniture may hold that ground.  The leaf and its wall are not
always recorded on the same storey, so both storeys are asked.

**Split and merge are not generated.**  The taxonomy lists them as optional and
the funnel cannot settle them.  Splitting a wall leaves two elements whose
identity, whose share of the openings and the relationships, and whose cut
position the instruction does not fix.  Several different models therefore
answer the same instruction.  The score cannot separate them either.  Created
entities are paired by the overlap of their oriented bounding boxes, and both
halves of a split overlap the original, so a cut in the wrong place scores
almost what the right one scores.

## Sets, batches and conditions

An instruction may name a whole set instead of one element.  The set is named by
the storey its members sit on, by the wall that hosts them, or by the room they
bound.  A conditional set narrows it by a measured threshold, which is an overall
width, a height read from the world box, or a plan length.  The threshold is a
multiple of half a metre, so it reads as a requirement rather than as a number
taken off the data, and it keeps between a third and two thirds of the set, so
the condition is one the reader has to weigh.  It also stands at least 0.15 m
clear of every member's measurement, so membership is a property of the building
rather than of the arithmetic.  A set whose members cannot all be measured names
nothing.

The gold then writes one edit for every member.  Five edits are written this way:
a property-set value, a material association, a predefined type, the depth of the
extruded body, and a deletion.  A batch carries at most twelve members.

A fifth funnel check follows a batch.  Every element the set was drawn from is
compared between the source model and the gold model, on its attributes, its
expanded geometry, its property sets, its material, its type object and its
spatial container.  A member that did not change is a refusal, and so is a
non-member that did, which is what makes the word "all" true of the file rather
than of the generator's intention.  The pool is the whole family where the model
holds at most a hundred and twenty of them, and the family on the members' own
storeys otherwise.

## The conditions the model itself carries

A source model is written in a schema version, in a length unit, with storeys
that may be turned against the world axes and a site that may sit on a survey
grid, with element bodies that may be a swept profile, a faceted solid or
geometry borrowed from a type object, and with names in whatever language the
office that drew it works in.  Each of those changes what an instruction can say
and what a gold script has to do, and each is a layer of the requirement
taxonomy.  `conditions.py` reads them off the file and names each one with the
tag the taxonomy gives it.

These tags are measurements and not draws.  A run cannot ask for more millimetre
models than the corpus holds, so every one of them carries a weight of zero in
the registry and is reported and stratified on rather than mixed.  The whole
pool is measured in `runs_local/gen_v07/corpus_conditions.md`, which is where
the shares below come from.

| tag | what it says about the task | pool |
|---|---|---|
| `model.units.mm` | the file is written in millimetres or centimetres | 27 of 43 models |
| `model.units.imperial` | the file is written in feet or inches | 9 of 43 |
| `model.schema.ifc2x3` | the file is IFC2X3 | 35 of 43 |
| `model.schema.ifc4x3` | the file is IFC4X3 | 1 of 43 |
| `model.placement.rotated_storey` | the storey the edit touches is turned against the world axes | 11 of 43 |
| `model.placement.site_offset` | the site stands more than a metre from the world origin | 11 of 43 |
| `model.representation.brep` | the edited element's body is a faceted or tessellated solid | 62 % of elements |
| `model.representation.mapped_item` | its body is geometry the type object owns | 18 % of elements |
| `model.names.non_english` | a name the instruction quotes is not written in English | 10 of 43 |

*Units.*  Every length a gold script passes is in metres and `goldlib` converts
it to the file's own unit, so a model in millimetres, centimetres, feet or
inches is generated against without the planners knowing.  What layer 7 varies
is the unit the **instruction** states, and it offers millimetres and
centimetres only where the file uses them, because a metre length converted to
feet is not a number a work order quotes.

*Turned storeys.*  A world-frame coordinate on a storey drawn on a skewed grid is
converted rather than refused, which is what 0.5.0 could not do.  The point is
converted through the storey's own placement, the instruction says the numbers
are world coordinates and how far the storey is turned, and the size is stated
along the element's own axes.  The funnel then reads the created element's
placement origin back and compares it with the point the instruction quoted,
once from the file's own arithmetic and once against the world box the geometry
index holds.  The two layouts that state a size per world axis, the endpoint
span and the axis dimensions, are refused on a turned storey: a length along a
world axis is not the length of an element built on a skewed grid.  A storey
whose placement is not a turn about the vertical is still refused.

*Representations.*  A translate, a rotate, a rename, a retype, a property value,
a material, a type object, a move to another storey, a delete and a copy are
written through the placement, the attributes or the relationships, so they work
on any body.  A resize and a mirror rewrite the profile itself.

| body | resize | mirror | why not |
|---|---|---|---|
| swept profile | yes | yes | |
| faceted or tessellated | no | no | no profile to resize or flip |
| boolean result | no | no | no single profile the edit could name |
| mapped item | no | no | the body belongs to the type object and is shared with every element of that type |

The refusals are counted under the body kind they were refused for, so a run
reports how much of the corpus each edit cannot reach.

*Schema versions.*  Attribute names and enumerations are read from the file's
own schema declaration rather than from a table, so an edit the schema does not
admit is refused rather than written wrongly: IFC2X3 gives a door no
`PredefinedType`, and no retype task is written for one.

## How the same requirement is worded

Two people asking for the same edit do not write the same sentence.  `wording.py`
draws one wording per instruction from the task's own seed, after the sentence
has been written from the edit's parameters, so a wording draw changes the words
and never the gold.

| tag | what changes |
|---|---|
| `wording.synonym` | the verb the sentence opens with: delete becomes remove or take out, move becomes shift or relocate, add becomes create or insert, set becomes change or update, rotate becomes turn, mirror becomes reflect, copy becomes duplicate |
| `wording.request_form` | the order becomes a request ("Please ..."), a question ("Can you ...?") or an order with one line of context in front of it ("The client wants one change made to this model.") |
| `wording.class_token` | the element is named by its IFC class rather than in plain words: "the IfcDoor hosted in the wall named 'W-12'" |
| `wording.unit_spelling` | the lengths are stated in millimetres or centimetres where the file uses them, or in metres spelled out |
| `wording.underspecified` | one value the edit needs is left out of the instruction |

Every variant is an exact substitution and never a rewrite.  A verb is replaced
only at the head of the sentence and a reference only where the anchor's own
phrase stands, so a quoted name cannot be touched.  The unit is chosen before
the sentence is built, because a length has to carry it wherever a template
writes one; a sentence the chosen unit does not change is written in metres and
carries no tag.  The funnel then reads the reference back out of the finished
sentence and resolves it again.

One length is always quoted in metres: the threshold of a conditional set
("only the walls on storey 'EG' longer than 8.00 m").  That phrase is built when
the anchor is built, before the unit is drawn, and the record stores it.

### An instruction that leaves something out

About one draw in twenty states the change without saying which element it is
meant for, which storey a new element goes on, or what the new value is.  The
gold of such a task changes nothing, because the reader cannot know what to
change, and the record carries the question a correct answer asks.

| slot | what the instruction looks like | what the answer asks |
|---|---|---|
| `element` | "Move the wall 2 m to the east (+X)." | which wall |
| `storey` | "Add a new wall named 'W-1', 4 m long, ... with its base corner at (3.00, 8.00, 0.00) m in the storey's own coordinates." | which storey |
| `dimension` | "Change the height of the wall named 'W-12'." | what the new value is |

Each form is written rather than cut out of a finished sentence, so the result
is a sentence a person could have written and the value that is missing is
exactly the one the record names.  The funnel replaces the anchor check with
three of its own: the value the record says is missing really is missing from
the sentence, more than one element or storey fits, and the gold model is the
source model with nothing done to it, compared entity by entity rather than byte
by byte.

Such a task carries no `null_edit_score`.  Doing nothing is what its gold does,
so the floor would read one and mean nothing, and `build_canonical` leaves those
tasks out of the floor and says how many it left out.

### The mixing settings

Every family lives in one registry, `families.py`, with its layer, its group,
its weight and the function that tries to build it.  A run changes the mix by
giving a group or a family a different number; the driver passes the name and
the number through without knowing what either means, so adding a family is
adding a registry entry and a function, and adding a group needs no flag of its
own.

| group | default share | what it governs |
|---|---|---|
| `ref.new` | 0.30 | update and delete anchors drawn from the six reference families above |
| `spec.element_relative` | 0.40 | create tasks whose position is read off other elements |
| `spec.world_frame` | 0.40 | coordinate-bearing create prompts stated in the world frame |
| `spec.world_frame.detail` | 1.00 | which world-frame layout is used: a corner, endpoints, or axis dimensions |
| `spec.displacement` | 1.00 | whether a move is quoted by compass word or by signed axis |
| `constraint.on_edit` | 0.30 | update and delete prompts carrying a constraint clause |
| `constraint.relation_on_create` | 0.50 | create tasks that also state a relationship |
| `wording.ifc_class` | 0.20 | relationship clauses naming the IFC class rather than saying it plainly |
| `op.update.new` | 0.35 | update draws that ask for one of the operations 0.6.0 adds before falling back |
| `op.create.new` | 0.35 | create draws that copy, array or replace an element already in the model |
| `scope.batch` | 0.15 | update and delete draws written over every member of a set |
| `scope.conditional` | 0.35 | the share of those sets a measured condition narrows |
| `wording.synonym` | 0.35 | instructions whose opening verb is swapped for one that means the same |
| `wording.request_form` | 0.30 | instructions written as a request, a question or a briefed order |
| `wording.class_token` | 0.15 | instructions that name the element by its IFC class |
| `wording.unit_spelling` | 0.20 | instructions that state their lengths in another unit or another spelling of one |
| `wording.underspecified` | 0.05 | draws whose instruction leaves out one value the edit needs |

```bash
python -m modifc_gen.scale ... \
    --family-share spec.element_relative=0.5 \
    --family-weight ref.viewpoint.through_door=0
```

`--derived-placement-prob`, `--relation-requirement-prob`, `--new-anchor-prob`,
`--world-coordinate-prob`, `--constraint-clause-prob`,
`--relation-class-name-prob`, `--new-operation-prob`, `--new-create-prob`,
`--batch-prob`, `--conditional-prob`, `--synonym-prob`, `--request-form-prob`,
`--class-token-prob`, `--unit-spelling-prob` and `--underspecified-prob` are
names for the fifteen groups a wave usually moves and write into the same
registry.  A weight of zero switches one family off
without removing it, which is how the egocentric reference is disabled.  The
share and the weight a run actually used are written into `funnel.json` under
`family_registry`.

Every share is a preference and not a requirement.  A target none of the new
reference families can name, a storey no derived placement fits, or a model with
no nameable room nearby falls back to what the earlier versions did, so no cell
of the grid loses yield to a family the model cannot support.

## The verification funnel

Every task passes all four checks, and a batch task a fifth, or is discarded and
counted.

1. **Anchor uniqueness.**  The anchor's predicate resolves to exactly the
   intended element.
2. **Re-execution.**  The gold script, run again on a fresh copy of the source
   model, reproduces the gold model.  The comparison is byte-for-byte where the
   writer is stable and otherwise compares the identifier set, the entity
   counts, and the class, attributes and world placement of every entity the
   edit touched.
3. **Re-parsing.**  The gold model opens again and holds what the edit promised:
   created entities present, removed entities gone, every relationship the
   instruction named present with the two ends it named and with those ends no
   more than half a metre apart, and, where the
   instruction quoted world coordinates or the position was derived, the created
   element's own body standing inside five centimetres of where the instruction
   put it.  That last box is read from the element's profile and placement
   rather than from a triangulation, which is exact for the boxes a create task
   writes.
4. **Self-scoring.**  ModIFC-Score, given the gold model both as reference and
   as prediction, returns 1 on all three axes.  A degenerate edit set, an update
   that changed nothing the score can see for instance, fails here rather than
   entering the dataset and rewarding an empty answer.
5. **Batch scope.**  A batch edit changed every member of the set the
   instruction named and no other element of the pool the set was drawn from.

Two more run beside them from 0.7.0 on.  The **wording** check reads the
reference back out of the finished instruction and resolves it again, so a
synonym, a request form or an IFC class token that had broken the reference is
caught here.  The reference it reads is the one the record states, and an
instruction that never quoted its anchor's phrase states none: a compositional
create names the storey its new element goes on and nothing about the element
the anchor resolves to, so from 0.7.1 the record carries an empty phrase there
and the check has nothing to read back, where 0.7.0 refused the draw.  A created
element whose position was quoted in world coordinates
**on a turned storey** has its placement origin compared with the point the
instruction quoted, once from the file's own arithmetic and once against the
world box the geometry index holds.  A task whose instruction leaves a value out
replaces the anchor check and the self-score with the three checks named above.

An update task also has to pass a cheap pre-check: every entity it leaves in the
model must be one the scorer's mesher can build a surface for, since a task
about an element with no readable geometry would score zero however correct the
answer.

### Which families the shipped score can read

Eight of the ten operations 0.6.0 adds are visible to the score as it ships.  A
rotation and a mirror move the surface, so the geometry axis reads them and the
topology axis sees the placement change.  A property-set value is already part
of the semantic property comparison and of the topology axis's notion of a
modified node.  A move to another storey and a re-hosting change relationship
edges the topology graph reads.  A copy, an array and a replacement add
entities, which the create reading pairs by overlap.

Two are invisible.  A material association hangs off the element through an
`IfcRelAssociatesMaterial` whose material end carries no global identifier, so
the semantic comparison does not read it.  A type assignment is an
`IfcRelDefinesByType`, which the published topology graph does not read.  The
unedited source model therefore scores 1.000 on a material task and on a type
task.

`ScorerConfig` gains three settings for them, all off by default, so the
published BIM-Edit reading is byte for byte what it was.

| setting | what it adds | which family needs it |
|---|---|---|
| `properties_include_material` | the associated material's name as one more semantic property | `op.update.material` |
| `properties_include_type` | the assigned type object's name as one more semantic property | `op.update.type_object` |
| `topology_relations_extra` | further relation classes in the topology graph: `IfcRelDefinesByType` for a type assignment and `IfcRelAssociatesMaterial` for a material association, whose material end is named rather than identified and is written into the graph under its class and its name | `op.update.type_object`, `op.update.material` |
| `underspecified_mode` | a task whose instruction leaves a value out is scored by whether the file came back unchanged and the reply asks for that value | `wording.underspecified` |

The semantic setting alone is not enough for a material.  It adds one key to a
property comparison a wall answers with a hundred of them, so the unedited model
still scores 0.993 and a filter at 0.98 would accept an empty answer.  With the
material edge in the topology graph as well the unedited model scores 0.817,
which is where the property-value and type-object families already sit, and the
gold still scores 1 on every axis.  A run that grades material tasks therefore
turns both on.

A fourth setting, `underspecified_mode`, is what an instruction that leaves a
value out is read under.  Scoring such a task the ordinary way says nothing: a
model nobody edited scores one against a reference nobody edited.  With the
setting on, the task is scored by the two facts that decide it and every axis
carries the same verdict: the model came back unchanged, compared entity by
entity so it survives a round trip through a writer, and the last thing the
system said holds a question mark and one of the words the record lists for the
value that is missing.  Neither half is worth anything alone, so a system that
edits a guessed element and asks a polite question scores zero, and so does one
that asks nothing.  The reply is read from `<edited>/<task_id>/reply.txt`; a run
that writes none is read as having said nothing.

What that check cannot do is judge whether the question is a good one.  A reply
in another language fails it, and a reply that asks about the wrong thing passes
it when the two share a word.  It is a floor on the behaviour rather than a
measure of it, which is why it is a flag and not the default.

The stage scorer (`stage_a/scoring.py`, `scorer_config`) may turn the material
and type settings on for those two families and the under-specified reading on
for that one.  Evaluation against BIM-Edit leaves all four off.

One setting differs between the self-check and evaluation.  Under the scorer's
shipped default a deleted entity has no counterpart to compare, so the semantics
axis of a perfect deletion is 0 by construction; the self-check therefore reads
a deletion as the benchmark paper describes it, scoring 1 when the target is
gone.  That is exactly the property the funnel tests, and evaluation is
unaffected.

## The task record

```jsonc
{
  "task_id": "WAL-UPD-SPA-B13-004",
  "input_ifc": "data/corpus/auckland/090_...ifc",
  "ground_truth_ifc": "data/modifc_tasks_smoke/models/WAL-UPD-SPA-B13-004.ifc",
  "operation": "update", "category": "spatial",
  "prompt": "Move the wall on storey 'EG' that ...",
  "target": {"entity_type": "IfcWall", "guids": ["0aam..."]},
  "source_model": {"relpath": "...", "sha256": "...", "collection": "auckland",
                   "schema": "IFC2X3", "key": "B13"},
  "element_type": "IfcWall", "family": "wall", "edit_kind": "translate",
  "tier": "single",
  "instruction": "Move the wall on storey 'EG' that ...",
  "instruction_paraphrase": null,
  "gold_script": "\"\"\"Gold edit script ... ",
  "gold_model": "data/modifc_tasks_smoke/models/WAL-UPD-SPA-B13-004.ifc",
  "anchor": {"kind": "offset", "family": "wall", "phrase": "...",
             "params": {...}, "expected": ["0aam..."]},
  "edit_params": {...},
  "difficulty": {"elements_touched": 1, "relation_chain_length": 1,
                 "anchor_ambiguity_count": 1, "anchor_candidate_pool": 28,
                 "scene_n_products": 644, "scene_n_relations": 1675,
                 "param_magnitude_bucket": "small",
                 "n_created": 0, "n_removed": 0},
  "edit_guids": {"target": ["0aam..."], "touched": ["0aam..."],
                 "created": [], "removed": [], "relations": []},
  "families": ["constraint.relation_on_create.space_boundary",
               "model.schema.ifc2x3", "model.units.mm", "op.create",
               "ref.relative.nearest", "scope.single",
               "spec.element_relative.fits_gap", "spec.world_frame",
               "wording.synonym"],
  "model_conditions": {"schema": "IFC2X3", "length_unit": "mm",
                       "unit_scale": 0.001, "site_offset": false},
  "wording": {"unit": "m", "unit_word": "m", "request_form": "imperative",
              "anchor_phrase": "the wall named 'EG-A-3-4'", "tags": []},
  "clarification": null,
  "expected_reply": null,
  "requires_relations": ["IfcRelContainedInSpatialStructure",
                         "IfcRelSpaceBoundary"],
  "seeds": {"task_seed": 1583920117},
  "generator_version": "veribim-gen/0.2.0",
  "building_id": "BLD003", "split": "train", "shard_id": "r0p0-B13-004",
  "verification": {"self_score": {...}, "gold_sha256": "...",
                   "gold_bytes": 3603639, "reexecution_match": "bytes",
                   "delete_semantics_reading": "matcher",
                   "null_edit_score": 0.835, "gold_materialized": false}
}
```

`building_id` and `split` come from the building grouping, so a split is by
building by construction and cannot be undone by reshuffling the task file.
`gold_materialized` says whether the gold model was kept on disk.

`families` lists the requirement families the task carries, named after the
project's requirement taxonomy and covering all seven layers: the operation, the
reference, the specification, the constraints, the scope, the conditions the
source model carries and the wording.  `model_conditions` says what the source
model itself is, `wording` says which variants the sentence was written in, and
`clarification` and `expected_reply` are filled only for a task whose
instruction leaves a value out; `requires_relations`
lists the relationship classes its gold script writes.  Both are read off the
calls the script makes rather than declared alongside them.  Stage A
stratifies its sample on the first and Stage C rewards the second.  A record
written before 0.5.0 carries neither, and every check still passes on it.

`edit_params` carries the numbers the instruction was rendered from.  A task
written over a set adds three keys to it: `scope`, which reads `batch`;
`batch_members`, the identifiers the set phrase resolved to; and `batch_pool`,
the elements those members were told apart from, which is what the batch funnel
check compares.

`instruction_paraphrase` is reserved for the linguistic-diversity pass, which
runs later with a local model and is not part of this package.

`null_edit_score` is a diagnostic rather than a gate: it is what the unedited
source model scores on the task, so the difficulty audit can tell a demanding
task from one a system could half-answer by doing nothing.

## Storage: the gold script is the artifact, the gold model is rebuilt

A gold model is a full copy of its source, so twenty thousand of them would need
several hundred gigabytes while twenty thousand gold scripts fit in a few tens of
megabytes.  A large run therefore writes its gold model into scratch, puts it
through the whole funnel there, records its checksum, and deletes it.  What the
dataset ships is the script and the checksum.

`modifc_gen.materialize` rebuilds one.  It offers two ways in.

`materialize_split` writes every gold model of one split into a directory and
leaves it there, which is what the validation split gets so a scorer can read
its ground truth from disk.  Each rebuilt file is checked against the checksum
recorded when the task was verified.

`GoldCache` is the training-time interface: it rebuilds on demand into a
directory bounded in both files and bytes, evicting the least recently used
entry when either bound is reached.

```python
cache = GoldCache(root, root / "runs/gold_cache",
                  max_bytes=20 << 30, max_files=400)
path = cache.path_for(record)     # rebuilds if absent, refreshes if resident
```

Both bounds are on disk and are enforced before a rebuild is written, so the
directory never exceeds them.  The cache holds no model in memory: one rebuild
parses one source model, so peak process memory during a rebuild is that model's
parsed size, roughly twenty-five times its file size for this corpus, and
nothing is retained between rebuilds.  Entries already present when the cache is
opened are adopted in modification-time order, so a restarted process reuses
what an earlier one built.

## The Revit-export creation family (0.10.0)

A create task of this family adds a wall, a slab, a column, a room, a door or a
window the way a Revit export writes one, and words it in one of three styles.

| style | category | what the instruction gives |
|---|---|---|
| box | direct | the corner of the element's bounding box and its extents, in storey coordinates |
| relation | topological | a position read off named elements: the wall that closes the gap between two facing walls, the column on top of another or in the gap between two walls in line, the room the four walls enclose, the slab over a room, the door centred in the wall between two rooms, the window beside another |
| relative | spatial | an offset from the minimum corner of a named element's bounding box, or a distance from a door's jamb |

Every instruction also states the relationships the element has to carry.  The
gold element is typed (the file's own type of that size, or a new one named
after Revit's generic family: "Basic Wall:Generic - 200mm", "Floor:Generic
250mm", "M_Concrete-Rectangular-Column:300 x 450mm",
"M_Door-Passage-Single-Flush:0915 x 2134mm", "M_Window-Fixed:1200 x 1500mm"),
named "<type>:<tag>" with the next free seven-digit tag, given the property
sets Revit writes for its class and its type's material layers, contained in
its storey (a room is aggregated), and related: path connections between
walls, an element connection to the column below, voids and fills for a door
or window, space boundaries to the rooms it bounds.

The gold script calls `goldlib.revit_wall`, `revit_slab`, `revit_column`,
`revit_space` or `revit_filling`, which build the element through the editing
sandbox's own helper library (`modifc_harness.veribim_geom`) under an
identifier sequence minted from the task, so the gold model rebuilds byte for
byte and a trajectory that calls the library with the instruction's numbers
writes the same element.  A position a relation or an offset describes is
computed at draw time by the same library function the trajectory calls.

The family's group, `op.create.revit`, has a share of zero, so a run that does
not name it draws exactly what it drew before.  `modifc_gen.revit_run` draws
the family alone, per class, style and schema version, on the buildings of one
or more pools; task identifiers carry the codes RVW, RVS, RVC, RVR, RVD and
RVN.  The family is read with the type's and the material's names as two more
semantic properties (`revit.SCORER_SETTINGS`).

## Layout

```
corpus.py     which source models the generator may use
buildings.py  grouping source files into the buildings they were exported from
pool.py       the models one run may draw on, with a building id on each
scene.py      one parsed model plus the indexes the generator reads
geomindex.py  world bounding boxes of a model's bodies, cached on disk
goldlib.py    the runtime a gold script calls; the only code that edits a model
ops.py        the edit-operation library and its feasibility guards
chains.py     the compositional tier
families.py   the requirement families, their layers, weights and builders
conditions.py the conditions a source model carries, and the tags they earn
wording.py    how one requirement is worded, and what an instruction may omit
anchors.py    anchor phrases, their predicates, and the uniqueness check
templates.py  instruction rendering, layer 1 (templates)
script.py     writing a plan out as a gold script, and running one
verify.py     the four checks
generate.py   drawing one task and turning it into a record
run.py        the single-pass driver: probe, allocate, generate
scale.py      the sharded driver: allocation by building, resume, merge, splits
materialize.py  rebuilding a gold model from its script, one or a whole split
audit.py      re-running every check from a finished task file
revit.py      the Revit-export creation family: draws, placement rules, wording
revit_run.py  the driver that draws that family per class, style and version
```

## Placement rules

A drawn placement answers to the geometry of the model rather than to its
placement origins, so a gold model is a building a person would accept.  Each
rule refuses the draw and, inside a draw loop, redraws; a draw that no attempt
satisfies is refused and counted rather than worked around.  The counts reach
the run's `funnel.json` under `placement_rejections`.

- A created wall, slab, column or space stands inside the storey's own
  footprint, which is the box over the triangulated bodies of the storey's
  elements rather than over their placement origins.
- A created element does not stand where another element already stands.  The
  test samples two lattices of points inside the new body and asks how many of
  them fall inside any one neighbour's bounding box, which bounds the share that
  can fall inside its solid, so a placement this test passes cannot collide.
- A new door or window needs a wall whose own extrusion is tall enough to carry
  the leaf, its sill and ten centimetres above the head, and its sill is
  measured from the base of that extrusion rather than from the wall's placement
  origin.
- A new door or window keeps ten centimetres of wall clear of every filling the
  wall already carries, measured along the wall.
- A moved door or window carries the opening it fills, stays within the length
  of its host wall and keeps clear of the wall's other fillings.  A leaf the
  model places relative to its own opening is moved by moving that opening
  instead, since the leaf hangs from it.  A move whose
  target hosts openings or fillings that would not move with it is refused,
  because carrying them is the compositional tier's edit.
- A move keeps the moved body inside the storey's footprint and away from what
  already stands at the destination, in the single tier and in the chains alike.

The leaf of a created door or window takes the wall's own thickness while the
opening cuts five centimetres past each face, so the leaf sits flush with the
wall.

Removing a door or a window removes the opening it filled, the
`IfcRelVoidsElement` that tied that opening to the wall and the
`IfcRelFillsElement` that tied it to the leaf, and leaves the wall itself
standing.  That is what BIM-Edit's own gold models do, and it leaves no wall cut
for a leaf that is gone.  `delete_filling_removes_opening` turns the rule off
for a run that needs the first waves' convention, where the opening stayed.

## Determinism

The generator draws from a seeded random source, and everything it writes is
derived from that draw: identifiers of created entities come from a hash of the
task identifier, no timestamp or clock reading enters a model, and the gold
script contains only literal values.  Every task's seed is a keyed hash of the
run seed, the shard the task sits in, and its index inside that shard, so adding
or removing a shard does not shift the seeds of the shards around it.

A placement rule fires before anything is written and is drawn from the same
seeded source, so a seed that produces no rejection produces exactly the model
it produced before the rules existed.

Re-running one gold script reproduces its gold model byte for byte, in any
process, at any later time.  Reaching that took two fixes beyond the seeding,
both of them in deletion, and both worth naming because the storage policy above
depends on the property.

*The clock.*  Removing a product makes IfcOpenShell stamp a fresh
`IfcOwnerHistory` with the current time, and more than one of them, identical in
content.  Both timestamps of a created history are now set to the earliest
timestamp the source model already carried, every reference to a created history
is redirected to the model's own, and the created histories are removed.  The
edit adds no ownership record, and the moment of generation is not written into
a model that will be published.

*The hash seed.*  Removing a product unassigns it from the types, materials and
property sets it shared with others, and IfcOpenShell rebuilds those SET-valued
attributes from an unordered container whose iteration order depends on the hash
seed of the process.  The members of the relationships an edit actually changed
are now sorted, which touches nothing the edit left alone.

Before those two fixes 169 of 200 smoke tasks reproduced byte for byte and the
rest agreed only structurally; after them a whole 20,000-task set rebuilds and
matches its recorded checksums.

## What the generator does not touch

Reserved content is excluded by reading the corpus manifest's own decisions
rather than re-deriving them: files that are not training-eligible, the whole
Schependomlaan building, and anything under `data/bimedit`.  Source models are
opened read-only and are never written to.
