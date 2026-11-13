"""The relation graph, its edits, and the topology score.

A model is read as a typed property graph: nodes are the entities that carry a
global identifier and describe something in the building, edges are instances of
six relation classes.  The reference topology edit is the symmetric difference
between the graphs of the input model and the ground truth; the predicted
topology edit is the symmetric difference between the graphs of the input model
and the prediction.  The two edits are then compared as sets, once for nodes and
once for edges.

Entities that an edit created carry different identifiers in the ground truth
and in the prediction, so identifiers are canonicalised first: created entities
are paired by a greedy bipartite heuristic over class agreement and the distance
between their local placements, and a paired predicted entity then speaks under
its ground-truth identifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np

import ifcopenshell.util.element as element_util
import ifcopenshell.util.placement as placement_util

from .config import TOPOLOGY_RELATIONS

# Attribute pairs that carry the two ends of each relation class.  A ``*`` marks
# an attribute that holds a list.
RELATION_ENDS: dict[str, tuple[str, str, bool]] = {
    "IfcRelContainedInSpatialStructure": ("RelatingStructure", "RelatedElements", True),
    "IfcRelAggregates": ("RelatingObject", "RelatedObjects", True),
    "IfcRelSpaceBoundary": ("RelatingSpace", "RelatedBuildingElement", False),
    "IfcRelVoidsElement": ("RelatingBuildingElement", "RelatedOpeningElement", False),
    "IfcRelFillsElement": ("RelatingOpeningElement", "RelatedBuildingElement", False),
    "IfcRelConnectsElements": ("RelatingElement", "RelatedElement", False),
    # Read only when a run asks for them through ``topology_relations_extra``.
    "IfcRelDefinesByType": ("RelatingType", "RelatedObjects", True),
    "IfcRelAssociatesMaterial": ("RelatingMaterial", "RelatedObjects", True),
}

# Relation classes one of whose ends carries no global identifier.  A material
# is named rather than identified, so an edge to it is written against a label
# built from its class and its name.  Only the classes listed here may do that;
# the six the published graph reads have identified ends on both sides.
LABELLED_ENDS: tuple[str, ...] = ("IfcRelAssociatesMaterial",)

NODE_ROOT_CLASS = "IfcProduct"

# Classes that carry no structural meaning of their own and therefore do not
# take part in the node edit set.  A proxy is by definition an element whose
# role the model does not state, and an annotation or a grid describes the
# drawing rather than the building.
NON_STRUCTURAL_CLASSES: tuple[str, ...] = (
    "IfcBuildingElementProxy",
    "IfcAnnotation",
    "IfcGrid",
    "IfcVirtualElement",
)


def _guid(entity) -> str | None:
    return getattr(entity, "GlobalId", None)


def _label(entity) -> str | None:
    """A stable name for an end of a relation that carries no identifier."""
    if entity is None:
        return None
    name = getattr(entity, "Name", None)
    if name:
        return f"{entity.is_a()}:{name}"
    layers = getattr(entity, "ForLayerSet", None) or entity
    names = [getattr(getattr(layer, "Material", None), "Name", None)
             for layer in getattr(layers, "MaterialLayers", None) or ()]
    names = [n for n in names if n]
    if names:
        return f"{entity.is_a()}:{'|'.join(names)}"
    return None


def node_guids(model, node_class: str = NODE_ROOT_CLASS,
               exclude_non_structural: bool = True) -> dict[str, str]:
    """GUID -> IFC class for every node of the relation graph."""
    out: dict[str, str] = {}
    try:
        entities = model.by_type(node_class)
    except Exception:
        entities = []
    for entity in entities:
        guid = _guid(entity)
        if not guid:
            continue
        if exclude_non_structural and any(entity.is_a(cls) for cls in NON_STRUCTURAL_CLASSES):
            continue
        out[guid] = entity.is_a()
    return out


def edge_set(model, relations: Iterable[str] = TOPOLOGY_RELATIONS,
             undirected_connects: bool = False) -> set[tuple[str, str, str]]:
    """Every relation instance, as (relation class, source GUID, target GUID)."""
    edges: set[tuple[str, str, str]] = set()
    for rel_class in relations:
        if rel_class not in RELATION_ENDS:
            continue
        try:
            instances = model.by_type(rel_class)
        except Exception:
            continue
        relating_attr, related_attr, is_list = RELATION_ENDS[rel_class]
        labelled = rel_class in LABELLED_ENDS
        for rel in instances:
            source = getattr(rel, relating_attr, None)
            src = _guid(source) or (_label(source) if labelled else None)
            if not src:
                continue
            targets = getattr(rel, related_attr, None)
            if targets is None:
                continue
            if not is_list:
                targets = [targets]
            for target in targets:
                dst = _guid(target)
                if not dst:
                    continue
                if undirected_connects and rel_class == "IfcRelConnectsElements":
                    a, b = sorted((src, dst))
                    edges.add((rel_class, a, b))
                else:
                    edges.add((rel_class, src, dst))
    return edges


# --------------------------------------------------------------------------
# Entity signatures, used to decide whether a node was modified
# --------------------------------------------------------------------------

_SKIP_TYPES = ("IfcOwnerHistory",)


def entity_signature(entity, depth: int = 0, max_depth: int = 24) -> Any:
    """A value that changes when anything about the entity changes.

    References to other identified entities collapse to their identifier, so a
    signature describes one entity rather than the whole model, while anonymous
    sub-entities such as placements and representations are expanded in full.
    """
    if entity is None:
        return None
    if depth > max_depth:
        return "..."
    try:
        cls = entity.is_a()
    except Exception:
        return None
    if any(entity.is_a(skip) for skip in _SKIP_TYPES):
        return None
    if depth > 0:
        guid = getattr(entity, "GlobalId", None)
        if guid:
            return ("ref", guid)
    values = []
    for value in entity:
        values.append(_signature_value(value, depth + 1, max_depth))
    return (cls, tuple(values))


def _signature_value(value, depth: int, max_depth: int) -> Any:
    if value is None:
        return None
    if hasattr(value, "is_a"):
        return entity_signature(value, depth, max_depth)
    if isinstance(value, (list, tuple)):
        return tuple(_signature_value(v, depth + 1, max_depth) for v in value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def _psets(entity) -> dict:
    try:
        psets = element_util.get_psets(entity)
    except Exception:
        return {}
    return {name: {k: v for k, v in props.items() if k != "id"}
            for name, props in psets.items() if isinstance(props, dict)}


def full_signature(entity, include_psets: bool = True) -> Any:
    """Class, geometry and properties of one entity, as one comparable value.

    The entity's own attributes cover its class and placement, the expanded
    representation covers its geometry, and the property sets are attached
    separately because they hang off the entity through a relationship rather
    than through an attribute.
    """
    return (entity_signature(entity), _psets(entity) if include_psets else None)


def modified_guids(model_a, model_b, shared: Iterable[str],
                   include_psets: bool = True) -> set[str]:
    """GUIDs whose entity differs between the two models."""
    out: set[str] = set()
    for guid in shared:
        try:
            ea = model_a.by_guid(guid)
            eb = model_b.by_guid(guid)
        except Exception:
            continue
        if full_signature(ea, include_psets) != full_signature(eb, include_psets):
            out.add(guid)
    return out


# --------------------------------------------------------------------------
# Node deltas and alignment
# --------------------------------------------------------------------------

@dataclass
class GraphDelta:
    added: set[str] = field(default_factory=set)
    removed: set[str] = field(default_factory=set)
    modified: set[str] = field(default_factory=set)
    edges_added: set[tuple[str, str, str]] = field(default_factory=set)
    edges_removed: set[tuple[str, str, str]] = field(default_factory=set)

    @property
    def nodes(self) -> set[str]:
        return self.added | self.removed | self.modified

    @property
    def edges(self) -> set[tuple[str, str, str]]:
        return self.edges_added | self.edges_removed


def placement_origin(entity) -> np.ndarray | None:
    obj_placement = getattr(entity, "ObjectPlacement", None)
    if obj_placement is None:
        return None
    try:
        matrix = placement_util.get_local_placement(obj_placement)
    except Exception:
        return None
    return np.asarray(matrix, dtype=np.float64)[:3, 3]


def graph_delta(model_0, model_x, modified_scope: Iterable[str] | None = None,
                undirected_connects: bool = False,
                node_class: str = NODE_ROOT_CLASS,
                exclude_non_structural: bool = True,
                include_psets: bool = True,
                relations: Iterable[str] = TOPOLOGY_RELATIONS) -> GraphDelta:
    """Symmetric difference between the relation graphs of two models.

    ``modified_scope`` lists the identifiers whose entity content is compared;
    entities outside it only count when they appear or disappear.  Passing
    ``None`` compares every shared entity, which is exact but costs a full
    traversal of both models.
    """
    nodes_0 = node_guids(model_0, node_class, exclude_non_structural)
    nodes_x = node_guids(model_x, node_class, exclude_non_structural)
    added = set(nodes_x) - set(nodes_0)
    removed = set(nodes_0) - set(nodes_x)
    shared = set(nodes_0) & set(nodes_x)
    if modified_scope is None:
        scope = shared
    else:
        scope = shared & set(modified_scope)
    modified = modified_guids(model_0, model_x, scope, include_psets)
    relations = tuple(relations)
    edges_0 = edge_set(model_0, relations,
                       undirected_connects=undirected_connects)
    edges_x = edge_set(model_x, relations,
                       undirected_connects=undirected_connects)
    return GraphDelta(
        added=added,
        removed=removed,
        modified=modified,
        edges_added=edges_x - edges_0,
        edges_removed=edges_0 - edges_x,
    )


def align_new_nodes(model_ref, model_pred, ref_new: Iterable[str],
                    pred_new: Iterable[str], class_match_score: float = 5.0,
                    proximity_scale: float = 1.0,
                    min_score: float = 5.0) -> dict[str, str]:
    """Pair entities that the two edits created, greedily by class and distance.

    Returns a map from predicted GUID to the reference GUID it stands for.
    """
    ref_new = list(ref_new)
    pred_new = list(pred_new)
    if not ref_new or not pred_new:
        return {}
    ref_info = []
    for guid in ref_new:
        try:
            entity = model_ref.by_guid(guid)
        except Exception:
            continue
        ref_info.append((guid, entity.is_a(), placement_origin(entity)))
    pred_info = []
    for guid in pred_new:
        try:
            entity = model_pred.by_guid(guid)
        except Exception:
            continue
        pred_info.append((guid, entity.is_a(), placement_origin(entity)))

    candidates = []
    for rg, rcls, rpos in ref_info:
        for pg, pcls, ppos in pred_info:
            same_class = rcls == pcls
            if rpos is None or ppos is None:
                distance = float("inf")
                proximity = 0.0
            else:
                distance = float(np.linalg.norm(rpos - ppos))
                proximity = class_match_score / (1.0 + distance / proximity_scale)
            score = (class_match_score if same_class else 0.0) + proximity
            if score >= min_score:
                candidates.append((score, -distance, rg, pg))
    candidates.sort(key=lambda c: (-c[0], -c[1], c[2], c[3]))
    used_ref: set[str] = set()
    used_pred: set[str] = set()
    mapping: dict[str, str] = {}
    for _score, _negdist, rg, pg in candidates:
        if rg in used_ref or pg in used_pred:
            continue
        used_ref.add(rg)
        used_pred.add(pg)
        mapping[pg] = rg
    return mapping


def _prf(reference: set, predicted: set) -> tuple[float, float, float]:
    """Precision, recall and F1 of a predicted edit set against a reference one.

    When both sets are empty the edit agrees perfectly and all three are 1.
    When only one is empty they disagree completely and all three are 0.
    """
    inter = len(reference & predicted)
    if predicted:
        precision = inter / len(predicted)
    else:
        precision = 1.0 if not reference else 0.0
    if reference:
        recall = inter / len(reference)
    else:
        recall = 1.0 if not predicted else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def remap_guid(guid: str, mapping: dict[str, str]) -> str:
    return mapping.get(guid, guid)


def topology_rules(ref_delta: GraphDelta, pred_delta: GraphDelta,
                   mapping: dict[str, str], lambda_node: float = 0.3) -> dict[str, float]:
    ref_nodes = ref_delta.nodes
    pred_nodes = {remap_guid(g, mapping) for g in pred_delta.nodes}
    ref_edges = ref_delta.edges
    pred_edges = {
        (cls, remap_guid(a, mapping), remap_guid(b, mapping))
        for cls, a, b in pred_delta.edges
    }
    np_, nr, nf = _prf(ref_nodes, pred_nodes)
    ep, er, ef = _prf(ref_edges, pred_edges)
    return {
        "delta_node_precision": np_,
        "delta_node_recall": nr,
        "delta_node_f1": nf,
        "delta_edge_precision": ep,
        "delta_edge_recall": er,
        "delta_edge_f1": ef,
        "delta_topology_score": lambda_node * nf + (1.0 - lambda_node) * ef,
    }
