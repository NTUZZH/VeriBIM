"""ModIFC-Score: the three-axis score for one BIM editing task."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np
from scipy.optimize import linear_sum_assignment

from . import editset, geometry as geo, topology as topo
from .config import DEFAULT_CONFIG, ScorerConfig
from .model_cache import MESHES, MODELS, MeshCache, ModelCache, model_key
from .properties import property_score
from .tasks import Task


@dataclass
class TaskScore:
    task_id: str
    operation: str
    category: str
    geometry: float = 0.0
    semantics: float = 0.0
    topology: float = 0.0
    final_score: float = 0.0
    gt_source: str = ""
    class_match: bool = False
    best_match_guid: str | None = None
    n_reference: int = 0
    n_matched: int = 0
    semantics_breakdown: dict[str, float] = field(default_factory=dict)
    topology_breakdown: dict[str, float] = field(default_factory=dict)
    geometry_breakdown: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    error: str | None = None

    def as_row(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "operation": self.operation,
            "category": self.category,
            "geometry": self.geometry,
            "semantics": self.semantics,
            "topology": self.topology,
            "final_score": self.final_score,
            "gt_source": self.gt_source,
            "class_match": self.class_match,
            "best_match_guid": self.best_match_guid,
            "n_reference": self.n_reference,
            "n_matched": self.n_matched,
            "error": self.error,
        }


def _entity_vertices(entity, key, meshes: MeshCache, cfg: ScorerConfig):
    mesh = geo.mesh_for(entity, key, meshes, cfg.mesher_linear_deflection,
                        cfg.disable_opening_subtractions)
    return mesh


def _iou_matrix(ref_meshes, cand_meshes, target_grid: int) -> np.ndarray:
    matrix = np.zeros((len(ref_meshes), len(cand_meshes)), dtype=np.float64)
    for i, rm in enumerate(ref_meshes):
        if rm is None:
            continue
        for j, cm in enumerate(cand_meshes):
            if cm is None:
                continue
            matrix[i, j] = geo.obb_iou(rm.verts, cm.verts, target_grid)
    return matrix


def _assign(iou: np.ndarray, min_iou: float) -> dict[int, int]:
    if iou.size == 0:
        return {}
    rows, cols = linear_sum_assignment(-iou)
    return {int(r): int(c) for r, c in zip(rows, cols) if iou[r, c] >= min_iou}


def candidate_entities(task: Task, model_0, model_pred, cfg: ScorerConfig) -> list[Any]:
    """Entities in the prediction that may stand for a reference entity."""
    if task.operation == "create" or not task.guids:
        edit = editset.build_edit_set(model_0, model_pred, "create", task.entity_type, ())
        return list(edit.entities)
    if cfg.update_strict_candidates:
        out = []
        for guid in task.guids:
            entity = editset.by_guid(model_pred, guid)
            if entity is not None:
                out.append(entity)
        return out
    edit = editset.build_edit_set(model_0, model_pred, task.operation, task.entity_type,
                                 task.guids)
    return list(edit.entities)


def _limit_candidates(references: Sequence[Any], candidates: list[Any],
                      limit: int) -> list[Any]:
    """Keep the candidates nearest the reference entities when there are many."""
    if limit <= 0 or len(candidates) <= limit or not references:
        return candidates
    origins = [topo.placement_origin(r) for r in references]
    origins = [o for o in origins if o is not None]
    if not origins:
        return candidates[:limit]

    def distance(entity) -> float:
        pos = topo.placement_origin(entity)
        if pos is None:
            return float("inf")
        return min(float(np.linalg.norm(pos - o)) for o in origins)

    ranked = sorted(candidates, key=distance)
    return ranked[:limit]


def _pooled_geometry(ref_meshes, pred_meshes,
                     cfg: ScorerConfig) -> tuple[float, dict[str, Any]]:
    detail: dict[str, Any] = {
        "n_gt_pool": sum(1 for m in ref_meshes if m is not None),
        "n_edited_pool": sum(1 for m in pred_meshes if m is not None),
    }
    if detail["n_gt_pool"] == 0:
        detail["skipped"] = "gt_pool_empty"
        return 1.0, detail
    if detail["n_edited_pool"] == 0:
        detail["skipped"] = "edited_pool_empty"
        return 0.0, detail
    # Each cloud is drawn from a freshly seeded generator, so two identical
    # surfaces yield identical point sets and their distance is exactly zero.
    cloud_ref = geo.pooled_cloud(ref_meshes, cfg.pooled_samples_per_object,
                                 cfg.pooled_max_total_samples,
                                 cfg.pooled_min_samples_per_object,
                                 np.random.default_rng(cfg.sampling_seed))
    cloud_pred = geo.pooled_cloud(pred_meshes, cfg.pooled_samples_per_object,
                                  cfg.pooled_max_total_samples,
                                  cfg.pooled_min_samples_per_object,
                                  np.random.default_rng(cfg.sampling_seed))
    diag = geo.joint_bbox_diagonal(cloud_ref, cloud_pred)
    cd = geo.chamfer_median(cloud_ref, cloud_pred, cfg.chamfer_reduction)
    detail.update({"cd": cd, "bbox_diag": diag, "chamfer_scale": cfg.chamfer_scale})
    if diag <= 0.0:
        return 1.0 if cd == 0.0 else 0.0, detail
    return geo.exp_score(cd / diag, cfg.chamfer_scale), detail


def score_task(task: Task, input_path: str | os.PathLike, gt_path: str | os.PathLike,
               pred_path: str | os.PathLike | None,
               cfg: ScorerConfig = DEFAULT_CONFIG,
               models: ModelCache = MODELS, meshes: MeshCache = MESHES,
               geometry_mode: str = "pooled_gated",
               reply: str = "") -> TaskScore:
    """Score one prediction against its task.

    ``geometry_mode`` selects how the geometry axis reduces the edit sets:

    ``pooled``        pooled point clouds of the two edit sets;
    ``pooled_gated``  the same, but zero when no reference entity found a match;
    ``per_pair``      one chamfer per matched entity pair, median across pairs.

    ``reply`` is the last thing the system said, which only a task whose
    instruction leaves out a value it needs is read against, and only when
    ``cfg.underspecified_mode`` is on.
    """
    result = TaskScore(task_id=task.task_id, operation=task.operation,
                       category=task.category)
    try:
        model_0 = models.get(input_path)
        model_gt = models.get(gt_path)
    except Exception as exc:  # pragma: no cover - inputs are fixed benchmark files
        result.error = f"input_parse_error: {exc}"
        return result

    if pred_path is None or not os.path.exists(pred_path):
        result.error = "prediction_missing"
        result.final_score = 0.0
        return result
    try:
        model_pred = models.get(pred_path)
    except Exception as exc:
        result.error = f"ifc_parse_error: {exc}"
        return result

    if cfg.underspecified_mode and task.clarification:
        # The task asks for an edit without saying which element, which storey
        # or what value, so the answer is to change nothing and ask.  Both
        # halves are read here and every axis carries the same verdict, because
        # neither half is worth anything without the other.
        from . import clarify

        value, detail = clarify.score(model_0, model_pred, task.clarification,
                                      reply)
        result.geometry = value
        result.semantics = value
        result.topology = value
        result.final_score = value
        result.n_reference = 0
        result.n_matched = 0
        result.gt_source = "underspecified"
        result.geometry_breakdown = detail
        result.semantics_breakdown = {"underspecified": value}
        result.topology_breakdown = {"underspecified": value}
        return result

    key_0 = model_key(input_path)
    key_gt = model_key(gt_path)
    key_pred = model_key(pred_path)

    # ---- reference entities -------------------------------------------
    references, gt_source = editset.reference_entities(
        model_0, model_gt, task.operation, task.entity_type, task.guids)
    result.gt_source = gt_source
    result.n_reference = len(references)
    ref_key = key_0 if task.operation == "delete" else key_gt

    # ---- pair every reference entity with its counterpart ---------------
    # A task that pins its target identifiers is paired by identity: the
    # prediction's entity under the same identifier is the counterpart, and a
    # deletion counts as paired exactly when that identifier is gone.  A create
    # task pins nothing, so its counterparts are found by oriented-bounding-box
    # overlap under a one-to-one assignment.
    pairs: list[Any] = [None] * len(references)   # geometric counterpart
    semantic_pairs: list[Any] = [None] * len(references)
    ref_meshes = [_entity_vertices(e, ref_key, meshes, cfg) for e in references]
    candidates: list[Any] = []
    cand_meshes: list[Any] = []

    if task.guids and task.operation in ("update", "delete"):
        for i, ref in enumerate(references):
            guid = getattr(ref, "GlobalId", "")
            present = editset.by_guid(model_pred, guid)
            if task.operation == "delete":
                pairs[i] = "removed" if present is None else None
                semantic_pairs[i] = present
            elif present is None:
                pairs[i] = None
                semantic_pairs[i] = None
            else:
                # The identifier alone is not enough: an entity moved far
                # enough that its box no longer meets the reference's counts as
                # no match, exactly as for an entity found by overlap.
                mesh = _entity_vertices(present, key_pred, meshes, cfg)
                overlap = 0.0
                if mesh is not None and ref_meshes[i] is not None:
                    overlap = geo.obb_iou(ref_meshes[i].verts, mesh.verts,
                                          cfg.obb_target_grid)
                if overlap >= cfg.match_min_iou:
                    pairs[i] = present
                    semantic_pairs[i] = present
        result.n_matched = sum(1 for p in pairs if p is not None)
        if task.operation == "delete":
            result.class_match = bool(references) and result.n_matched == len(references)
        else:
            first = next((i for i, p in enumerate(pairs) if p is not None), None)
            if first is not None:
                result.best_match_guid = getattr(pairs[first], "GlobalId", None)
                result.class_match = references[first].is_a() == pairs[first].is_a()
    else:
        candidates = candidate_entities(task, model_0, model_pred, cfg)
        candidates = _limit_candidates(references, candidates, cfg.match_candidate_limit)
        cand_meshes = [_entity_vertices(e, key_pred, meshes, cfg) for e in candidates]
        iou = _iou_matrix(ref_meshes, cand_meshes, cfg.obb_target_grid)
        assignment = _assign(iou, cfg.match_min_iou)
        for i, j in assignment.items():
            pairs[i] = candidates[j]
            semantic_pairs[i] = candidates[j]
        result.n_matched = len(assignment)
        if assignment:
            first = sorted(assignment)[0]
            result.best_match_guid = getattr(candidates[assignment[first]], "GlobalId", None)
            result.class_match = references[first].is_a() == candidates[assignment[first]].is_a()

    # ---- geometry ------------------------------------------------------
    if not references:
        geometry = 1.0
        geo_detail: dict[str, Any] = {"skipped": "no_reference"}
    elif geometry_mode == "per_pair":
        per_pair = []
        for i, ref in enumerate(references):
            partner = pairs[i]
            if partner is None:
                per_pair.append(0.0)
            elif isinstance(partner, str):
                # The prediction removed exactly the entity the reference
                # removed, so the two edits describe the same surface.
                per_pair.append(1.0)
            else:
                mesh = _entity_vertices(partner, key_pred, meshes, cfg)
                value, _detail = _pooled_geometry([ref_meshes[i]], [mesh], cfg)
                per_pair.append(value)
        geometry = float(np.median(per_pair)) if per_pair else 0.0
        geo_detail = {"per_pair": per_pair}
    else:
        gt_pool = editset.build_edit_set(model_0, model_gt, task.operation,
                                         task.entity_type, task.guids)
        pred_pool = editset.build_edit_set(model_0, model_pred, task.operation,
                                           task.entity_type, task.guids)
        gt_pool_key = key_0 if task.operation == "delete" else key_gt
        pred_pool_key = key_0 if task.operation == "delete" else key_pred
        gt_pool_meshes = [_entity_vertices(e, gt_pool_key, meshes, cfg)
                          for e in gt_pool.entities]
        pred_pool_meshes = [_entity_vertices(e, pred_pool_key, meshes, cfg)
                            for e in pred_pool.entities]
        geometry, geo_detail = _pooled_geometry(gt_pool_meshes, pred_pool_meshes, cfg)
        if geometry_mode == "pooled_gated" and result.n_matched == 0:
            geometry = 0.0
            geo_detail["gated"] = "no_match"
    geo_detail.update({"n_gt": len(references), "n_matched": result.n_matched})
    result.geometry = float(min(1.0, max(0.0, geometry)))
    result.geometry_breakdown = geo_detail

    # ---- semantics -----------------------------------------------------
    class_scores: list[float] = []
    prop_scores: list[float] = []
    if task.operation == "delete" and cfg.delete_semantics == "removal":
        for ref in references:
            removed = editset.by_guid(model_pred, ref.GlobalId) is None
            class_scores.append(1.0 if removed else 0.0)
            prop_scores.append(1.0 if removed else 0.0)
    else:
        for i, ref in enumerate(references):
            candidate = semantic_pairs[i]
            if candidate is None:
                class_scores.append(0.0)
                prop_scores.append(0.0)
                continue
            class_scores.append(1.0 if ref.is_a() == candidate.is_a() else 0.0)
            prop_scores.append(property_score(
                ref, candidate, cfg.properties_tolerance, cfg.properties_ignore,
                cfg.properties_include_material,
                cfg.properties_include_type)["score"])
    if class_scores:
        class_mean = float(np.mean(class_scores))
        prop_mean = float(np.mean(prop_scores))
        result.semantics_breakdown = {"class_match": class_mean, "properties": prop_mean}
        result.semantics = 0.5 * (class_mean + prop_mean)
    else:
        result.semantics_breakdown = {"class_match": 0.0, "properties": 0.0}
        result.semantics = 0.0

    # ---- topology ------------------------------------------------------
    scope = None if cfg.topology_modified_scope == "all" else task.guids
    relations = tuple(topo.TOPOLOGY_RELATIONS) + tuple(cfg.topology_relations_extra)
    ref_delta = topo.graph_delta(model_0, model_gt, modified_scope=scope,
                                 undirected_connects=cfg.topology_delta_undirected_connects,
                                 node_class=cfg.topology_node_class,
                                 exclude_non_structural=cfg.topology_exclude_non_structural,
                                 include_psets=cfg.topology_modified_include_psets,
                                 relations=relations)
    pred_delta = topo.graph_delta(model_0, model_pred, modified_scope=scope,
                                  undirected_connects=cfg.topology_delta_undirected_connects,
                                  node_class=cfg.topology_node_class,
                                  exclude_non_structural=cfg.topology_exclude_non_structural,
                                  include_psets=cfg.topology_modified_include_psets,
                                  relations=relations)
    mapping = topo.align_new_nodes(model_gt, model_pred, ref_delta.added,
                                   pred_delta.added,
                                   class_match_score=cfg.topology_class_match_score,
                                   proximity_scale=cfg.topology_proximity_scale,
                                   min_score=cfg.topology_delta_min_match_score)
    rules = topo.topology_rules(ref_delta, pred_delta, mapping,
                                cfg.topology_delta_lambda_node)
    if cfg.topology_gate_on_match and references and result.n_matched == 0:
        rules = {name: 0.0 for name in rules}
    result.topology_breakdown = rules
    if cfg.topology_aggregate == "paper":
        result.topology = rules["delta_topology_score"]
    else:
        result.topology = float(np.mean([rules[r] for r in cfg.topology_rules]))

    weights = cfg.axis_weights()
    total = sum(weights)
    result.final_score = (
        weights[0] * result.geometry + weights[1] * result.semantics
        + weights[2] * result.topology) / total
    return result
