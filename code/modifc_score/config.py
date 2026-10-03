"""Scorer configuration.

The defaults reproduce the configuration that the BIM-Edit benchmark shipped
with its published runs (``eval/resolved_defaults.json``).  Fields whose value
the published configuration does not pin are grouped under "interpretive
options"; each of those is a decision we had to take, and each is documented in
the validation report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

# Relation classes that take part in the topology graph, in the order the paper
# lists them.
TOPOLOGY_RELATIONS: tuple[str, ...] = (
    "IfcRelContainedInSpatialStructure",
    "IfcRelAggregates",
    "IfcRelSpaceBoundary",
    "IfcRelVoidsElement",
    "IfcRelFillsElement",
    "IfcRelConnectsElements",
)

# Direct attributes of an IFC entity that take part in the property comparison,
# before the ignore list is applied.  The list is fixed rather than derived from
# the entity's schema: the published runs compare exactly these and, for
# instance, never compare a space's CompositionType or a door's OperationType.
CANDIDATE_ATTRIBUTES: tuple[str, ...] = (
    "Name",
    "Description",
    "ObjectType",
    "Tag",
    "PredefinedType",
    "LongName",
    "OverallHeight",
    "OverallWidth",
)

TOPOLOGY_RULES: tuple[str, ...] = (
    "delta_node_precision",
    "delta_node_recall",
    "delta_node_f1",
    "delta_edge_precision",
    "delta_edge_recall",
    "delta_edge_f1",
    "delta_topology_score",
)


@dataclass(frozen=True)
class ScorerConfig:
    # ---- axis weights -------------------------------------------------
    geometry_weight: float = 1.0
    semantics_weight: float = 1.0
    topology_weight: float = 1.0

    # ---- entity matching ----------------------------------------------
    match_method: str = "obb"
    match_min_iou: float = 0.05
    # Upper bound on how many candidate entities are meshed for one reference
    # entity.  An edit that adds hundreds of entities would otherwise cost one
    # shape build per entity; the ones kept are those whose placement sits
    # closest to the reference, and an entity far from the reference cannot
    # overlap it anyway.
    match_candidate_limit: int = 48
    candidate_entity_type_filter: bool = True
    update_strict_candidates: bool = True

    # ---- geometry ------------------------------------------------------
    chamfer_scale: float = 5.0
    pooled_samples_per_object: int = 4096
    pooled_max_total_samples: int = 16384
    pooled_min_samples_per_object: int = 256
    obb_target_grid: int = 64

    # ---- semantics -----------------------------------------------------
    properties_tolerance: float = 0.05
    properties_ignore: Sequence[str] = ("Tag", "Description", "LongName")
    semantic_checks: Sequence[str] = ("class_match", "properties")

    # ---- topology ------------------------------------------------------
    topology_delta_lambda_node: float = 0.3
    topology_delta_min_match_score: float = 5.0
    topology_delta_undirected_connects: bool = False
    topology_rules: Sequence[str] = TOPOLOGY_RULES

    # ---- interpretive options (not pinned by the published config) ------
    # How the topology axis turns the seven delta rules into one number.
    # "mean_rules"  -> arithmetic mean of the seven rule values (reproduces the
    #                  published per-task topology column);
    # "paper"       -> 0.3 * node_f1 + 0.7 * edge_f1 as printed in the paper.
    topology_aggregate: str = "mean_rules"

    # How delete tasks earn their semantic score.
    # "matcher"  -> run the same class/property comparison as update tasks, so a
    #               successfully deleted entity has no counterpart and scores 0
    #               (this is what the published runs did);
    # "removal"  -> 1.0 when the target is absent from the prediction, else 0.0
    #               (this is what the paper describes).
    delete_semantics: str = "matcher"

    # Chamfer reduction over the two directed nearest-neighbour distance sets.
    # "pooled_median" -> median over the concatenation of both directions;
    # "mean_of_medians" -> average of the two per-direction medians.
    chamfer_reduction: str = "pooled_median"

    # Which entities the node-edit set is drawn from.
    topology_node_class: str = "IfcProduct"

    # Whether a task whose reference entity found no counterpart scores zero on
    # topology as well.  The published runs behave this way: identities in the
    # node edit set are canonicalised through the entity match, so a reference
    # entity with no counterpart leaves nothing to compare.
    topology_gate_on_match: bool = True

    # Whether proxies, annotations and grids are dropped from the node set.
    topology_exclude_non_structural: bool = True

    # Whether a node counts as modified when only its property sets changed.
    topology_modified_include_psets: bool = True

    # ---- 0.6.0 readings, all off by default -----------------------------
    # Two of the operations the 0.6.0 task generator writes leave no trace the
    # shipped reading can see.  A material association hangs off the element
    # through an IfcRelAssociatesMaterial, whose material end carries no global
    # identifier, so it is neither an attribute nor an edge of the relation
    # graph; a type assignment is an IfcRelDefinesByType, which the published
    # topology graph does not read.  Each option below adds one of them, and
    # each defaults to off, so the published BIM-Edit reading is unchanged.

    # Compare the name of the material each entity is associated with, as one
    # more key of the semantic property comparison.
    properties_include_material: bool = False

    # Compare the type object each entity is assigned to, by its name, as one
    # more key of the semantic property comparison.
    properties_include_type: bool = False

    # Relation classes added to the topology graph beyond the six above.
    # "IfcRelDefinesByType" and "IfcRelAssociatesMaterial" are the two the
    # 0.6.0 families need.  A material carries no global identifier, so an edge
    # to it is written against its class and its name.
    topology_relations_extra: Sequence[str] = ()

    # Which shared entities are checked for content changes when building a node
    # edit set.  "target" checks the task's target entities only, which is cheap
    # and reproduces the published runs; "all" checks every shared entity.
    topology_modified_scope: str = "target"

    # Weight of the class-agreement term in the greedy topology node matcher.
    # A pair is admissible when its score reaches topology_delta_min_match_score.
    topology_class_match_score: float = 5.0
    topology_proximity_scale: float = 1.0

    # Random seed for surface sampling, so a score is reproducible.
    sampling_seed: int = 0

    # ---- 0.7.0 reading, off by default ----------------------------------
    # An under-specified task asks for an edit without saying which element,
    # which storey or what value, so the only correct answer is to change
    # nothing and ask.  Scoring that the ordinary way says nothing: a model
    # nobody edited scores one against a reference nobody edited.  With this
    # option on, such a task is scored by the two facts that decide it, and
    # every other task is scored exactly as before.  It defaults to off, so the
    # published BIM-Edit reading is byte for byte what it was.
    underspecified_mode: bool = False

    # ---- geometry meshing ----------------------------------------------
    mesher_linear_deflection: float = 0.001
    disable_opening_subtractions: bool = False

    def axis_weights(self) -> tuple[float, float, float]:
        return (self.geometry_weight, self.semantics_weight, self.topology_weight)


DEFAULT_CONFIG = ScorerConfig()
