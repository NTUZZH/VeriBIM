# ModIFC-Score

A reimplementation of the BIM-Edit benchmark's three-axis score for IFC model
edits. One task supplies an input model `M0`, a ground-truth model `M*` and a
predicted model `M'`; the score says how closely the prediction's edit matches
the reference edit, on geometry, on semantics and on topology.

```
S = mean(S_geo, S_sem, S_topo),   each in [0, 1]
```

The package is built to be used twice: once to reproduce the benchmark's
published numbers, and later as the reward function of a reinforcement-learning
loop, where it is called thousands of times on the same handful of scenes. Both
uses are why the caches below are part of the design rather than an
optimisation added afterwards.

## Install and run

Requires the `l2` environment (Python 3.14, ifcopenshell 0.8.5, numpy, scipy,
pandas).

```bash
conda activate l2
export PYTHONPATH=<repository>/code
python -m modifc_score.cli \
    --tasks   .../BIM-Edit-Tasks/tasks.jsonl \
    --scenes  .../BIM-Edit \
    --edited  .../BIM-Edit-runs/<run>/edited \
    --out     scores.csv --workers 8
```

From Python:

```python
from modifc_score import load_tasks, score_task
from modifc_score.paths import resolve_scene, resolve_prediction

tasks = load_tasks(".../tasks.jsonl")
task = tasks["WAL-UPD-DIR-A-003"]
score = score_task(task,
                   resolve_scene(task.input_ifc, ".../BIM-Edit"),
                   resolve_scene(task.ground_truth_ifc, ".../BIM-Edit"),
                   resolve_prediction(task.task_id, ".../edited"))
print(score.final_score, score.geometry, score.semantics, score.topology)
```

A quick check that the geometric and comparison primitives behave:

```bash
python -m modifc_score.selftest
```

## What each axis measures

**Edit sets.** Both the reference edit and the predicted edit are diffs against
the original input model, never a diff of the prediction against the ground
truth. A create task's edit set holds the entities the model gained, an update
task's holds the target entities plus anything the edit added, and a delete
task's holds the entities the model lost. Every set is restricted to the task's
target entity type.

**Geometry.** Each reference entity is paired with its counterpart in the
prediction, points are sampled uniformly over both surfaces (4096 points per
object, 16384 in total, at least 256 per object, allocated in proportion to
surface area), and the pair's score is

```
exp( -(CD_med / D) * 5.0 )
```

where `CD_med` is the median bidirectional nearest-neighbour distance and `D`
is the diagonal of the axis-aligned box enclosing both point clouds. The task's
geometry score is the median over pairs; a reference entity with no counterpart
scores zero.

**Semantics.** Per matched pair, the mean of a class-agreement indicator and the
fraction of the reference entity's properties the candidate reproduces within a
5 % relative tolerance. `Tag`, `Description` and `LongName` are excluded. The
task score is the mean over reference entities, with unmatched ones at zero.

**Topology.** The model is read as a graph over six relation classes
(`IfcRelContainedInSpatialStructure`, `IfcRelAggregates`, `IfcRelSpaceBoundary`,
`IfcRelVoidsElement`, `IfcRelFillsElement`, `IfcRelConnectsElements`). The
reference topology edit is the symmetric difference between the graphs of `M0`
and `M*`, the predicted edit the symmetric difference between `M0` and `M'`.
Entities that an edit created carry different identifiers on the two sides, so
they are paired first by a greedy heuristic over class agreement and the
distance between local placements. Precision, recall and F1 are then computed
separately for node edits and edge edits.

## Caches

Two process-local caches, both least-recently-used and both bounded:

| cache | key | holds | bound |
|---|---|---|---|
| `ModelCache` | absolute path, mtime, size | parsed `ifcopenshell.file` | number of models (default 3-6) |
| `MeshCache` | model key, entity GUID | triangulated mesh in world coordinates | total vertices (default 4M) |

Scoring one task touches three models, so a capacity of three keeps a whole
task resident; a larger capacity keeps a scene resident across the tasks that
share it. The batch runner orders tasks by input model for exactly that reason.
Realistic scenes are large (up to 349 MB on disk, about 4.3 GB parsed), so the
runner also scores them in tiers with fewer workers.

## Configuration

`ScorerConfig` carries the benchmark's shipped settings
(`eval/resolved_defaults.json`) plus the readings that the paper and that file
leave open. Each open reading is a named field, so the alternative is one
keyword away:

| field | default | alternative |
|---|---|---|
| `topology_aggregate` | `mean_rules` (mean of the seven delta rules, as the published runs report) | `paper` (0.3·node-F1 + 0.7·edge-F1) |
| `delete_semantics` | `matcher` (same comparison as an update, as the published runs report) | `removal` (1.0 when the target is gone, as the paper describes) |
| `chamfer_reduction` | `pooled_median` | `mean_of_medians` |
| `topology_modified_scope` | `target` | `all` |
| `topology_exclude_non_structural` | `True` | `False` |
| `sampling_seed` | 0 | any integer |

`geometry_mode` on `score_task` selects `per_pair` (the default and the
published behaviour), `pooled` or `pooled_gated`.

## Layout

```
config.py       settings, relation list, property list
tasks.py        the benchmark task list
paths.py        scene and prediction path resolution
model_cache.py  parsed-model and mesh caches
geometry.py     meshing, surface sampling, chamfer, oriented bounding boxes
editset.py      diffs against the input model
properties.py   property extraction and comparison
topology.py     relation graph, graph edits, greedy node alignment
scorer.py       the three axes and the final score
batch.py        parallel scoring with pinned cores
cli.py          command line entry point
selftest.py     checks of the geometric and comparison primitives
```
