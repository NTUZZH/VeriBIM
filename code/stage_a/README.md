# Stage A: supervised fine-tuning

Stage A turns generated editing tasks into full harness trajectories, filters
them with the verifier, assembles them into a chat-format training set with loss
on assistant tokens only, and trains the LoRA adapter.

A training example is not a code snippet. It is the whole conversation the
evaluation protocol produces: the frozen system prompt, the instruction and the
working file's path, then assistant turns and real tool results, ending on an
answer. That shape is what teaches the three behaviours the zero-shot probes
showed the candidate bases lack: use the pre-bound `ifc` rather than open the
file, inspect the model before editing it, and call `commit()` so something is
left on disk to score.

## Layout

```
paths.py          project paths and the two environments' interpreters
style.py          seeded surface variation: names, comments, quoting, phrasing
goldcode.py       the gold edit, rewritten as code the sandbox can run
inspection.py     inspection rounds generated from a task's anchor metadata
trajectory.py     the message format, and replay through the harness sandbox
scoring.py        the verifier as Stage A calls it (delete = removal)
synthesize.py     one task: plan, replay, verify, keep
pipeline.py       the synthesizer over a task set, and its funnel
collect.py        rejection sampling: the GPU half and the filtering half
chat_format.py    rendering and the assistant-token mask
assemble.py       the training set, its mix and its truncation rate
train_args.py     the trainer's arguments, and the asserted adapter shape
train_sft.py      the trainer
tests/            the argument, adapter and dataset checks that run on CPU
validate.py       mid-training validation against the model in memory
score_cli.py      scoring as a subprocess, for callers outside `l2`
cli.py            command line
```

## Environments

`synthesize`, `harvest` and `score_cli` open IFC models and run in **`l2`**.
`assemble` and `train` load the tokenizer and the training stack and run in
**`l2train`**. Both are named in `paths.py`; the validation hook starts the
sandbox worker and the scorer as `l2` subprocesses from inside the trainer.

```bash
export PYTHONPATH=<repository>/code
L2=$CONDA_ROOT/envs/l2/bin/python
L2TRAIN=$CONDA_ROOT/envs/l2train/bin/python
```

## The two trajectory sources

**Gold-synthesized** (`synthesize`) covers every operation. For one task the
planner reads the task's anchor metadata, generates the query that resolves the
instruction's phrase, generates the edit as plain IfcOpenShell code, and adds a
verification-and-commit round and a closing message. Every snippet is then
executed in the harness sandbox against a fresh copy of the source model, and
the trajectory is kept only if:

* no snippet raised and the sandbox stayed alive;
* every identifier any round writes was given in the instruction or printed by
  an earlier round, and one that came out of a listing of several candidates is
  tied to what the instruction names;
* the trajectory called `commit()`;
* the file left on disk scores at or above 0.98 on every axis against the gold
  model.

The second condition is what keeps the inspection rounds honest. A round that
prints nothing useful cannot pay for an identifier a later round then uses, so
the trajectory is rejected rather than quietly teaching the model to know things
it was never told. `observed.observed_identifiers_ok` is the check: it walks the
messages in order, holding the identifiers the instruction carried and every
identifier an earlier tool result printed, and names any round that writes one
outside that set. The assembler runs the same walk and drops a trajectory that
fails it, so a bad one cannot reach training through a second route.

`observed.numbers_observed_ok` is the same walk on quantities. A round may
write a number the instruction carried or an earlier tool output printed,
allowing for a sign change, a conversion between millimetres, centimetres and
metres, and the rounding every measuring round applies; anything else is a value
the trajectory produced off the record, which is what teaches a model to invent
coordinates. Numbers inside a string, constants inside a helper the round
defines, slice bounds, small integers and a float of exactly one are not
measurements and are not checked. The walk is not a filter on synthesis: it is
run over a finished trajectory file by `runs_local/stage_a_v4_dev/check_numbers.py`,
which splits its count by the purpose of the round that wrote the number.

`observed.names_observed_ok` asks the same of a name. A lookup that finds an
element by matching its `Name` has to have been given that string, in the
instruction or in an earlier tool output; the generator sometimes draws an
anchor it never writes into the sentence, and a round built from that name
quotes a string no reader could produce. Messages, attributes, class tokens,
dictionary keys, the library's own words and anything inside a helper the round
defines are not names and are not checked. The planner holds the same rule
before anything runs: an anchor the instruction does not name is dropped when
the edit does not need the element and refused when it does, and a task whose
planned lookups would match on any other unquoted string is refused.
`runs_local/stage_a_v4/check_strings.py` runs the walk over a trajectory file.

For the same reason the library style writes `predefined_type` only when the
instruction text carries the token. A gold script sets one on every filling,
drawn when the task was built, and an instruction that wants a type says so.

Having seen an identifier is not the same as having a reason for it, which is
what `observed.listing_choice_justified` adds. A round that lists every storey
in the building prints them all, so an edit that then takes one of them passes
the first check and still leaves the reader no rule. The choice counts as
readable when the instruction quotes that element's name, when the output held
only one candidate of its class, when the round uses every candidate the listing
offered, or when the line the identifier sits on also carries the element it was
reached through. An instruction that gives the storey through an element,
"on the storey that contains the column named 'X'", therefore gets
`inspection.storey_of_round`: it follows `ContainedInStructure` for an element
and `Decomposes` for a space up to the storey and prints the link, and the
storey listing is kept only where the instruction quotes the storey's own
name.

### How a create edit is written: the geometry helper

The sandbox binds a geometry helper under the name `geom` (`modifc_harness/
veribim_geom.py`). It measures a wall, reads where an existing door sits, works
out the corner a spatial wording describes, and cuts, places and relates a new
element, all in metres and all from IFC entities. A create edit is therefore
written as one call into it per gold call, carrying only what the instruction
states: the target, the class, the name, the size, the position along the wall,
the sill, the predefined type, the offsets, the count and the names.

```python
host = ifc.by_guid('1fIVuvFffDJRV_SJESOtDs')
leaf = geom.add_filling(host, 'IfcWindow', 'Glazing unit 989', width=1.2,
                        height=1.4, along=5.18, along_is_centre=True, sill=0.9)
```

A create of the Revit-export family (`goldlib.revit_*`) is written as one
placing call and one creating call: `geom.wall_between`, `geom.corner_from`,
`geom.opening_centred` and their siblings turn the instruction's relation or
offset into the box the element fills, and `geom.add_wall_box`,
`add_slab_box`, `add_column_box`, `add_space_box` or `add_opening_filling`
build the typed element with its property sets, material and relationships.
A box the instruction states is passed as its two triples, and a measuring
round calls the placing function first so the box is on the record.

`goldcode.GEOM_CALLS` lists the eleven operations written this way: the two
fillings, the three box creations, the wall span, the copy, the array, the two
relationships and the filling deletion. Everything else, a translation, a
rotation, an attribute, a property, a material, a type, a re-hosting, keeps the
hand-written helper block it always had. Four arguments come from the wording
rather than from the gold call's own numbers, because the gold call carries what
the generator worked out from the sentence:

* `along_is_centre=True` when the instruction gives the middle of the leaf, with
  the centre the instruction states rather than the near edge;
* `frame='storey'` for "in that storey's own coordinates" and `frame='world'`
  for a plain coordinate, which is the difference between the two gold calls;
* a corner stated as an offset from a named element is written as
  `geom.origin_in_frame(reference, storey)` plus the stated offsets;
* "directly on top of X" is `geom.spot_on_top_of(X)` and "inside the space,
  against the wall" is `geom.spot_beside_wall_in_space(wall, space, ...)`.

Each of those wordings also gets a round of its own before the edit, so the
number the edit uses is in the transcript: `geom.wall_box(host)` before a
filling, `geom.filling_slot(old)` before a replacement, and the matching
placement call before a box. The rounds resolve nothing new; they read elements
the instruction named or an earlier round printed, so the identifier invariant
below holds unchanged. A wall the edit is about to create itself is not measured
first, since it is not there yet.

The style is on by default and `--no-geom-lib` turns it off, which writes the
hand-written block instead. The two arms are otherwise identical, so a run of
each over one task file measures what the library is worth. A trajectory records
which arm wrote it in `style.geom_lib` and in `generator`.

### Which reading each family is graded under

The fourth condition is not one reading but a family of them, because two of the
edits the generator writes leave no trace the shipped scorer can see. A material
association hangs off the element through a relationship whose material end
carries no identifier, and a type assignment is a relationship class the
published topology graph does not read, so an untouched model scores 1.000 on a
material task and 0.942 on a type task under the published settings. A filter
built on that would keep a trajectory that changed nothing.
`scoring.scorer_config_for` therefore reads each task under the settings its
families need, and `scoring.reading_for` writes that reading into the kept
record so a later pass can tell which filter a trajectory passed.

| task | reading applied | axis the edit moves |
|---|---|---|
| material assignment (`op.update.material`) | the material's name is one more property, and the association is an edge of the relation graph | semantics |
| type assignment (`op.update.type_object`) | the type object's name is one more property, and the assignment is an edge of the relation graph | semantics |
| property-set write (`op.update.pset`) | the published settings, which already count a property-set change as a modified node | topology |
| Revit-export create (`op.create.revit`) | the type object's name and the material's name are two more properties of the created element | semantics |
| deletion (`op.delete`) | the target is scored by whether it is gone | semantics |
| instruction that leaves a value out (`wording.underspecified`) | the file has to come back unchanged and the reply has to ask for the value | the reply, and every axis carries its verdict |
| every other family, conditions and wording included | the published BIM-Edit settings | all three |

A condition or a wording variant does not change what the score can see, so a
task in millimetres, on a turned storey or written as a question is graded
exactly as the published runs grade it. Evaluation against BIM-Edit keeps the
published reading throughout, which is the reward and evaluation separation the
method section describes.

### An instruction that leaves out a value the edit needs

About one draw in forty does not say which element, which storey or what value,
and its gold model is the source model unchanged. The right answer is to change
nothing and ask, so the planner writes a trajectory that inspects, shows why the
sentence is ambiguous, calls no `commit()` and ends on the question the record
carries. Such a trajectory is kept only when the sandbox left the file untouched
and the reply passes the check in `modifc_score.clarify`: a question mark, and
one of the words the record lists for the missing value. A commit on this path
is a rejection rather than the proof it is everywhere else.

### An instruction that covers a whole set

A conditional or set-reference instruction names every element of a scope that
meets a condition, so the inspection round resolves the whole set and prints it,
the edit runs over every member, and the commit round reads back that each
member changed and that the candidates outside the set did not. Acceptance then
runs `modifc_gen.verify.check_batch_scope`, the generator's own fifth funnel
check, between the source model and the file the trajectory left behind, so the
instruction's word "all" is true of the file rather than of the plan.

### Where an identifier comes from

Every anchor kind the generator writes has a lookup here, including the nine
that 0.7.0 added: the nearest element, the one between two others, the one
directly above or below, the one facing another across a space, the one on the
named side seen through a door, the nth filling along a wall, the element that
carries none of what the sentence excludes, the element that separates two
spaces, and every element of a scope over a stated size. The relative kinds are
resolved from the centre of each candidate's world bounding box, as the
generator resolves them, because a wall's placement origin sits at one end of it
and would put "nearest" somewhere the reader cannot see.

The anchor's own parameters are found the same way. An instruction names the
elements its phrase refers to, so the resolve round looks each of them up by
that name before the predicate runs: `storey = by_name('IfcBuildingStorey',
'FLOOR 1')`, then `reference = by_name('IfcColumn', 'HSS...:788732')`, then the
distance test over the walls of that storey. The lookup prints what it found, so
the identifiers are on the record for the rounds that follow. Which name belongs
to which parameter comes from the source model's name index
(`stage_a.nameindex`, one JSON file per model under `name_index/`, GlobalId to
class, Name, LongName and storey), not from the order the instruction quotes its
names in. A name two elements of one class share is narrowed to the storey the
instruction names; a reference that is still ambiguous, or that the instruction
does not name at all, makes the planner refuse the task.

Several edits also need an identifier the instruction gives only as a name, and
each has its own round: the storey list for a create or a move into another
storey, the type-object list for a type assignment, the walls of the storey a
door already stands on for a re-hosting, the opening a filling stands in for a
replacement, the space list for a boundary the create has to record, and the
elements whose name the instruction quotes for a connection. A material is named
rather than identified, so a material assignment reads the names the model
already carries first. Where the
instruction quotes its lengths in millimetres or centimetres, one round reads
the file's own length unit and prints each stated size converted into it, and
the edit divides by that same scale rather than by a constant.

```bash
$L2 -m stage_a.cli synthesize \
    --tasks-file data/veribim_tasks_v1/tasks.jsonl \
    --out-dir data/stage_a/v1 --workers 6
```

`funnel_gold.json` reports the run family by family as well as cell by cell:
`by_family` gives attempted, kept and the leading refusals for each of the
generator's tags, and `by_anchor_kind` does the same for the phrase the
instruction used. A kept trajectory carries the task's `families`, its anchor
kind, its model conditions and its wording, so the assembler counts the training
set the same way and `--replay-cap` can mix an old set into a new one without
losing a family.

**Rejection-sampled** (`harvest`) de-templates the set. `collect.sample_run`
samples k trajectories per task from the pinned base through the harness probe
path; `harvest` then scores every sample, keeps those above the same floor,
drops near-identical solutions and caps the number kept per task.

```bash
$L2 -m stage_a.cli harvest --run-dir runs_local/stage_a_sample_Qwen3.5-9B \
    --tasks-file data/veribim_tasks_v1/tasks.jsonl \
    --out-dir data/stage_a/v1 --cap-per-task 2
```

## Assembling and training

```bash
$L2TRAIN -m stage_a.cli assemble \
    --trajectories data/stage_a/v1/trajectories_gold.jsonl \
                   data/stage_a/v1/trajectories_self.jsonl \
    --out-dir data/stage_a/v1 --max-seq 8192 --emit-token-ids

$L2TRAIN -m stage_a.cli train --run-id stage_a_v1 \
    --dataset data/stage_a/v1/sft_train.jsonl \
    --val-every 200 --val-n-tasks 100
```

The assembler renders every record through the base model's chat template **with
the tool schema attached**, because that is what the server does at evaluation
time, and computes the loss mask by taking the difference between conversation
prefixes rather than by guessing where a turn starts. Loss runs from the end of
the generation prompt (`<|im_start|>assistant\n<think>\n`) to the turn's
`<|im_end|>`; system, user and tool tokens are masked.

A trajectory longer than the sequence length is dropped, not cut: cutting one
removes its commit round and its closing turn, which are two of the three
behaviours Stage A exists to teach. The rate is reported in
`dataset_report.json`.

The trainer refuses to start if the adapter does not have exactly 43,278,336
trainable parameters, writes its resolved configuration to
`checkpoints/stage_a/<run_id>/resolved_config.json`, and diffs it against a
comparator when one is named with `--compare-config`. `--dry-run` stops after
those checks, and it loads the base model to make them, so it needs the card.

## Continuing from an adapter

`--init-adapter` starts from an adapter that already exists instead of creating
a new one, which is how the run continues `sft_v1` on the new task
families. The adapter is loaded trainable, the way Stage B loads Stage A's, and
its `adapter_config.json` must give the rank, alpha, dropout and target modules
the run would otherwise record, or the trainer aborts before reading a weight.
The parameter count is asserted on this path as it is on the fresh one. Only the
weights are inherited: the optimizer, the schedule, the warmup and the epoch
count start from step 0 on the new dataset, so this is a new run seeded from the
adapter rather than an interrupted run resumed.

`--replay-dataset` mixes a second file into the training set, and `--replay-cap`
keeps a seeded sample of it drawn with `--seed`, which is how the new families
are trained on without losing the old ones. Both files' counts, the cap and the
kept totals go into `dataset_stats.files` of the resolved configuration, next to
`init_adapter` and the adapter's own configuration, so the diff against `sft_v1`
shows the continuation and nothing else.

```bash
$L2TRAIN -m stage_a.cli train --run-id sft_v2 \
    --init-adapter checkpoints/stage_a/sft_v1/adapter \
    --dataset data/stage_a/v2/sft_train.jsonl \
    --replay-dataset data/stage_a/v1/sft_train.jsonl --replay-cap 3000 \
    --compare-config checkpoints/stage_a/sft_v1/resolved_config.json \
    --val-every 200 --val-n-tasks 100 \
    --val-max-rounds 8 --val-max-new-tokens 1024 \
    --val-task-ids-file data/stage_a/v1/val_subset_100.json
```

The three validation flags are named because their defaults have moved since
`sft_v1` ran, and a comparison of the two runs' configurations should show the
continuation rather than that drift.

The checks that need neither the card nor the base model run as

```bash
$L2TRAIN -m stage_a.tests.test_init_adapter
$L2 -m stage_a.tests.test_families
$L2 -m stage_a.tests.test_observed
$L2 -m stage_a.tests.test_geom
```

`test_geom` checks the library style: that every create call is written as a
`geom` call and none of the entities the helper builds appears in the emitted
code, that the frame and the `along_is_centre` wording carry the instruction's
own numbers, that a spatial corner is measured rather than quoted, and that the
measuring round stands before the edit. It needs no sandbox and no model.

The others run in `l2` because they read the task file and the scorer's
configuration. It checks the reading each family is graded under, that every
anchor kind compiles to a lookup, that an under-specified task plans no edit and
ends on a reply the scorer's own check accepts, that an identifier the
instruction withholds is paid for by a round, and that a length quoted in
another unit is converted against the file's own scale.

## Mid-training validation

On its cadence the trainer writes the adapter to
`checkpoints/stage_a/<run_id>/val_adapters/step_N/` and records that a
measurement is due. Scoring is a separate process:

```bash
$L2TRAIN -m stage_a.validate_checkpoint \
    --adapter checkpoints/stage_a/stage_a_v1/val_adapters/step_400 --n-tasks 100
```

It loads the base model, applies the adapter, and rolls the fixed validation
subset out through the harness's own agent loop, sandbox and scorer, reporting
the mean final score, per-operation means, schema validity, the share of tool
calls that compile, the share that run without a traceback, and the commit rate.

Rolling out from inside the training process is available as
`--val-mode inprocess` and is not the default. A 20-step smoke measured what it
costs: generation goes through Unsloth's inference path, which swaps the layer
implementations under the adapter, and the training loss stepped from 0.58 to
4.2 at the first optimizer step after the hook and stayed there. The memory the
rollout allocates is returned (21,352 MiB reserved before the hook, 18,412
after), so the cost is the model's state, not the card.

## Conventions worth knowing

*Deletion is scored by removal.* Under the reading the published runs used, a
perfect deletion scores zero on semantics, so a filter built on it would reject
every correct delete. Evaluation against BIM-Edit keeps the published reading.

*Created entities get fresh identifiers.* The gold script passes fixed
GlobalIds so that regenerating a task reproduces it byte for byte. A model
cannot know those strings, so the emitted code calls `guid.new()`; the verifier
pairs created entities geometrically, so nothing is lost.

*Assistant turns carry no deliberation.* The template opens a turn with an empty
`<think>` block, which is exactly the generation prompt the server sends, so
training text and served prompt agree token for token. Sampled trajectories have
their deliberation stripped for the same reason; `--keep-reasoning` on the
harvester keeps it for anyone who wants to measure the difference.
