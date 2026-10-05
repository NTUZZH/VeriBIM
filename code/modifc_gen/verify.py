"""The self-verification funnel.

A generated task only enters the dataset once four things have been checked
against the files themselves rather than against the generator's intentions.

1. *Anchor uniqueness.*  The predicate behind the instruction's phrase resolves
   to the intended element and to nothing else.
2. *Re-execution.*  The gold script, run again on a fresh copy of the source
   model, reproduces the gold model.
3. *Re-parsing.*  The gold model opens again and still carries the entities the
   edit was supposed to leave behind.
4. *Self-scoring.*  ModIFC-Score, given the gold model both as the reference and
   as the prediction, returns 1 on all three axes.  A task whose edit set is
   degenerate, an update that changed nothing the score can see for instance,
   fails here instead of entering the dataset and rewarding an empty answer.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np

import ifcopenshell
import ifcopenshell.util.placement

from .anchors import Anchor
from .scene import TOPOLOGY_RELATIONS

# Every axis of the self-score has to reach this before a task is accepted.
SELF_SCORE_FLOOR = 0.98


def scorer_config(operation: str):
    """The scorer settings the self-check runs under.

    Deletion is the one case where the shipped default cannot reach 1.  Under
    that reading a deleted entity has no counterpart to compare, so the
    semantics axis of a perfect deletion is 0 by construction and the check
    would reject every delete task.  The self-check therefore reads a deletion
    the way the benchmark paper describes it, scoring 1 when the target is gone,
    which is exactly the property the funnel is testing: an edit that removed
    nothing still fails.  Evaluation itself is unaffected; this setting belongs
    to the generator's own check.
    """
    from modifc_score.config import DEFAULT_CONFIG

    if operation == "delete":
        return dataclasses.replace(DEFAULT_CONFIG, delete_semantics="removal")
    return DEFAULT_CONFIG


@dataclass
class StageResult:
    ok: bool
    reason: str = ""
    detail: dict[str, Any] = field(default_factory=dict)


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# ------------------------------------------------------- semantic comparison


def _plain(value: Any) -> Any:
    """A comparable form of one attribute value."""
    if isinstance(value, ifcopenshell.entity_instance):
        guid = getattr(value, "GlobalId", None)
        return f"@{guid}" if guid else f"#{value.is_a()}"
    if isinstance(value, (list, tuple)):
        return tuple(_plain(v) for v in value)
    if isinstance(value, float):
        return round(value, 9)
    return value


def entity_signature(model, guid: str) -> Optional[tuple]:
    """Class, direct attributes and world placement of one entity."""
    try:
        product = model.by_guid(guid)
    except Exception:
        return None
    info = product.get_info(recursive=False, include_identifier=False)
    info.pop("OwnerHistory", None)
    attributes = tuple(sorted((k, _plain(v)) for k, v in info.items()))
    matrix = None
    placement = getattr(product, "ObjectPlacement", None)
    if placement is not None:
        try:
            matrix = tuple(np.round(np.array(
                ifcopenshell.util.placement.get_local_placement(placement),
                dtype=float), 9).ravel().tolist())
        except Exception:
            matrix = None
    return (product.is_a(), attributes, matrix)


def model_signature(path: str, guids: Sequence[str]) -> dict[str, Any]:
    """What two runs of one gold script have to agree on."""
    model = ifcopenshell.open(path)
    roots = set()
    for entity in model.by_type("IfcRoot"):
        roots.add(entity.GlobalId)
    counts = {name: len(model.by_type(name)) for name in TOPOLOGY_RELATIONS}
    counts["IfcProduct"] = len(model.by_type("IfcProduct"))
    return {
        "guids": roots,
        "counts": counts,
        "entities": {guid: entity_signature(model, guid) for guid in guids},
    }


def signatures_agree(first: dict[str, Any], second: dict[str, Any]) -> StageResult:
    if first["guids"] != second["guids"]:
        missing = len(first["guids"] - second["guids"])
        extra = len(second["guids"] - first["guids"])
        return StageResult(False, "guid_set_differs",
                           {"missing": missing, "extra": extra})
    if first["counts"] != second["counts"]:
        return StageResult(False, "entity_counts_differ",
                           {"first": first["counts"], "second": second["counts"]})
    for guid, signature in first["entities"].items():
        if second["entities"].get(guid) != signature:
            return StageResult(False, "touched_entity_differs", {"guid": guid})
    return StageResult(True)


# ------------------------------------------------------------------ stages


def check_anchor(scene, anchor: Anchor, expected: Sequence[str]) -> StageResult:
    """Stage 1: the instruction's phrase points at the intended element."""
    resolved = anchor.resolve(scene)
    if resolved == sorted(expected):
        return StageResult(True, detail={"n_resolved": len(resolved)})
    if not resolved:
        return StageResult(False, "anchor_resolves_to_nothing",
                           {"n_resolved": 0})
    if len(resolved) > len(expected):
        return StageResult(False, "anchor_ambiguous", {"n_resolved": len(resolved)})
    return StageResult(False, "anchor_resolves_elsewhere",
                       {"n_resolved": len(resolved)})


def check_reexecution(script_source: str, source_ifc: str, gold_ifc: str,
                      guids: Sequence[str], scratch_dir: str) -> StageResult:
    """Stage 2: running the gold script again reproduces the gold model."""
    from .script import execute_script

    handle, replay = tempfile.mkstemp(suffix=".ifc", dir=scratch_dir)
    os.close(handle)
    try:
        execute_script(script_source, source_ifc, replay)
        if sha256_of(replay) == sha256_of(gold_ifc):
            return StageResult(True, detail={"match": "bytes"})
        outcome = signatures_agree(model_signature(gold_ifc, guids),
                                   model_signature(replay, guids))
        if outcome.ok:
            return StageResult(True, detail={"match": "semantic"})
        return StageResult(False, f"reexecution_{outcome.reason}", outcome.detail)
    except Exception as exc:
        return StageResult(False, "reexecution_failed", {"error": repr(exc)[:200]})
    finally:
        if os.path.exists(replay):
            os.remove(replay)


def check_meshable(source_ifc: str, guids: Sequence[str], meshes=None,
                   models=None) -> StageResult:
    """Stage 0: every entity the edit keeps has a surface the score can read.

    An entity with no representation, or one the geometry kernel cannot build,
    has no surface to compare, so a task about it would score zero however
    correct the answer is.  The check uses the scorer's own mesher, so it agrees
    with what the score will do later.
    """
    from modifc_score.geometry import mesh_for
    from modifc_score.model_cache import MESHES, model_key

    key = model_key(source_ifc)
    # Parsing the source again here would hold a second copy of a model that is
    # already resident, which on the largest files in the corpus is gigabytes.
    model = models.get(source_ifc) if models is not None \
        else ifcopenshell.open(source_ifc)
    for guid in guids:
        try:
            product = model.by_guid(guid)
        except Exception:
            return StageResult(False, "target_absent", {"guid": guid})
        if mesh_for(product, key, meshes or MESHES, 0.001, False) is None:
            return StageResult(False, "target_not_meshable", {"guid": guid})
    return StageResult(True)


# The two ends of each relation class a create task may be asked to write.
RELATION_ENDS = {
    "IfcRelSpaceBoundary": ("RelatingSpace", "RelatedBuildingElement"),
    "IfcRelConnectsElements": ("RelatingElement", "RelatedElement"),
    "IfcRelContainedInSpatialStructure": ("RelatingStructure", "RelatedElements"),
    "IfcRelAggregates": ("RelatingObject", "RelatedObjects"),
    "IfcRelVoidsElement": ("RelatingBuildingElement", "RelatedOpeningElement"),
    "IfcRelFillsElement": ("RelatingOpeningElement", "RelatedBuildingElement"),
}


def _relation_pairs(model, ifc_class: str) -> set[tuple[str, str]]:
    """Every instance of a relation class, as the pair of identifiers it ties."""
    relating, related = RELATION_ENDS[ifc_class]
    pairs: set[tuple[str, str]] = set()
    for relation in model.by_type(ifc_class):
        source = getattr(relation, relating, None)
        source_guid = getattr(source, "GlobalId", None)
        if not source_guid:
            continue
        targets = getattr(relation, related, None)
        if targets is None:
            continue
        if not isinstance(targets, (list, tuple)):
            targets = [targets]
        for target in targets:
            target_guid = getattr(target, "GlobalId", None)
            if target_guid:
                pairs.add((source_guid, target_guid))
    return pairs


def missing_relations(model, edges: Sequence[Sequence[str]]
                      ) -> list[list[str]]:
    """Which of the relationships an instruction asked for the gold does not hold."""
    cache: dict[str, set[tuple[str, str]]] = {}
    missing: list[list[str]] = []
    for edge in edges:
        ifc_class, relating, related = edge[0], edge[1], edge[2]
        if ifc_class not in RELATION_ENDS:
            missing.append(list(edge))
            continue
        if ifc_class not in cache:
            cache[ifc_class] = _relation_pairs(model, ifc_class)
        if (relating, related) not in cache[ifc_class]:
            missing.append(list(edge))
    return missing


def world_box_fault(model, expectation: dict[str, Any]) -> Optional[str]:
    """Whether a created element stands where the world coordinates said.

    The box is read from the element's own profile and placement rather than
    from a triangulation, which is exact for the boxes a create task writes and
    costs nothing.
    """
    from .goldlib import world_extent

    guid = expectation["guid"]
    try:
        bounds = world_extent(model, guid)
    except Exception:
        return "created_body_unreadable"
    if bounds is None:
        return "created_body_unreadable"
    tolerance = float(expectation.get("tolerance", 0.05))
    lo = np.array(expectation["lo"], dtype=float)
    hi = np.array(expectation["hi"], dtype=float)
    error = float(max(np.abs(bounds[0] - lo).max(), np.abs(bounds[1] - hi).max()))
    return None if error <= tolerance else f"world_box_off_by_{error:.3f}m"


def world_origin_fault(model, expectation: dict[str, Any],
                       index=None) -> Optional[str]:
    """Whether a created element's own corner stands at the world point quoted.

    On a storey turned against the world axes the element is set out along the
    storey's own axes, so the box that surrounds it in world axes is larger than
    the element and cannot be compared with the instruction's numbers.  What the
    instruction does fix is the world position of the corner it names, which is
    the element's placement origin, and that is exact.  The element's world
    bounding box, read from the geometry index, has to hold that point as well,
    which is a second reading of the same fact through a different measurement.
    """
    import ifcopenshell.util.placement

    guid = expectation["guid"]
    tolerance = float(expectation.get("tolerance", 0.05))
    wanted = np.array(expectation["point"], dtype=float)
    try:
        product = model.by_guid(guid)
        matrix = np.array(ifcopenshell.util.placement.get_local_placement(
            product.ObjectPlacement), dtype=float)
    except Exception:
        return "created_placement_unreadable"
    from .goldlib import unit_scale

    origin = matrix[:3, 3] * unit_scale(model)
    error = float(np.abs(origin - wanted).max())
    if error > tolerance:
        return f"world_origin_off_by_{error:.3f}m"
    if index is not None:
        position = index["lookup"].get(guid)
        if position is None:
            return "created_body_not_in_geometry_index"
        lo = index["lo"][position] - tolerance
        hi = index["hi"][position] + tolerance
        if bool(np.any(wanted < lo) or np.any(wanted > hi)):
            return "world_origin_outside_created_body"
    return None


# A relationship an instruction states says its two ends meet.  The draw already
# refuses a partner further than 0.15 m from the created element, measured on the
# meshed bodies; this gate reads the same distance from the profiles and catches a
# gross error, with room for the difference between the two ways of measuring.
RELATION_GAP_LIMIT = 0.5


def relation_gap_fault(model, edges: Sequence[Sequence[str]]) -> Optional[str]:
    """Whether a stated relationship joins two ends that stand apart.

    Each end's box is read from its own profile and placement.  An end whose body
    cannot be read that way is not judged, so the check reports what it can prove
    and never guesses.
    """
    from .goldlib import world_extent

    for edge in edges:
        _ifc_class, first, second = edge[0], edge[1], edge[2]
        try:
            one = world_extent(model, first)
            two = world_extent(model, second)
        except Exception:
            continue
        if one is None or two is None:
            continue
        apart = np.maximum(np.maximum(one[0] - two[1], two[0] - one[1]), 0.0)
        gap = float(np.linalg.norm(apart))
        if gap > RELATION_GAP_LIMIT:
            return f"{first}_and_{second}_apart_by_{gap:.2f}m"
    return None


def check_parse(gold_ifc: str, created: Sequence[str],
                removed: Sequence[str],
                relation_edges: Sequence[Sequence[str]] = (),
                world_box: Optional[dict[str, Any]] = None,
                relation_guids: Sequence[str] = (),
                world_origin: Optional[dict[str, Any]] = None) -> StageResult:
    """Stage 3: the gold model re-parses and holds what the edit promised.

    Beyond the entities a create adds and a delete removes, this is where the
    relationships an instruction named are checked: each one has to exist in the
    gold with the two ends the instruction said, and a created element quoted in
    world coordinates has to stand where those coordinates put it.
    """
    try:
        model = ifcopenshell.open(gold_ifc)
    except Exception as exc:
        return StageResult(False, "gold_parse_failed", {"error": repr(exc)[:200]})
    for guid in tuple(created) + tuple(relation_guids):
        try:
            model.by_guid(guid)
        except Exception:
            return StageResult(False, "created_entity_absent", {"guid": guid})
    for guid in removed:
        try:
            model.by_guid(guid)
        except Exception:
            continue
        return StageResult(False, "removed_entity_present", {"guid": guid})
    if relation_edges:
        missing = missing_relations(model, relation_edges)
        if missing:
            return StageResult(False, "required_relation_absent",
                               {"missing": missing[:4],
                                "n_missing": len(missing)})
        fault = relation_gap_fault(model, relation_edges)
        if fault is not None:
            return StageResult(False, "related_elements_apart", {"fault": fault})
    if world_box:
        fault = world_box_fault(model, world_box)
        if fault is not None:
            return StageResult(False, "world_placement_wrong", {"fault": fault})
    if world_origin:
        from . import geomindex

        try:
            index = geomindex.build(gold_ifc, model)
        except Exception:
            index = None
        fault = world_origin_fault(model, world_origin, index)
        if fault is not None:
            return StageResult(False, "world_placement_wrong", {"fault": fault})
    return StageResult(True, detail={"n_products": len(model.by_type("IfcProduct"))})


def check_filling_clearance(scene, gold_ifc: str, created: Sequence[str],
                            moved: Sequence[str], models=None) -> StageResult:
    """Stage 3b: every door or window the edit placed keeps its zone free.

    A door or window the edit created, or moved by more than a millimetre, is
    measured in the gold model: the clear distance from the host wall's faces
    to the nearest wall, column or slab standing in front of its hole
    (``modifc_gen.clearance``).  Below ``FILLING_ZONE_CLEARANCE`` the task is
    refused, because the doorway or window opens into that element.
    """
    from . import clearance, settings

    if not settings.SETTINGS.filling_zone_clearance:
        return StageResult(True, detail={"n_fillings": 0, "rule": "off"})
    try:
        gold = models.get(gold_ifc) if models is not None \
            else ifcopenshell.open(gold_ifc)
    except Exception as exc:
        return StageResult(False, "gold_parse_failed", {"error": repr(exc)[:200]})
    fillings = clearance.placed_fillings(scene.model, gold, created, moved)
    if not fillings:
        return StageResult(True, detail={"n_fillings": 0})
    try:
        index = scene.geometry_index()
    except Exception:
        index = None
    # Elements the edit created or moved are tested whatever the source's
    # index says about where they stood.
    always = tuple(dict.fromkeys(tuple(created) + tuple(moved)))
    distances = {}
    for filling in fillings:
        found = clearance.clearance_of(gold, filling, index, always)
        distance = found.get("distance")
        distances[filling.GlobalId] = distance
        if distance is not None and \
                distance < clearance.FILLING_ZONE_CLEARANCE:
            return StageResult(False, "filling_clearance_obstructed",
                               {"filling": filling.GlobalId,
                                "obstruction": found.get("obstruction"),
                                "obstruction_class":
                                    found.get("obstruction_class"),
                                "distance": distance})
    return StageResult(True, detail={"n_fillings": len(fillings),
                                     "distances": distances})


def check_wording(scene, instruction: str, anchor, wording: Optional[dict],
                  expected: Sequence[str]) -> StageResult:
    """The wording layer changed the words of the instruction and nothing else.

    The reference the sentence carries is read back out of the finished sentence
    and resolved again, so a synonym, a request form or an IFC class token that
    had broken the reference would be caught here rather than in a training run.
    A reference the resolver cannot re-read from the sentence is reported and
    not judged, which is what a set phrase and a bare identifier are.

    A record written by 0.7.1 or later states the phrase its sentence carries,
    and an empty one states that the sentence carries none, so that value is
    read as written; the anchor's own phrase is fallen back on only for a
    record from a version that stored no wording at all.
    """
    if wording is not None and "anchor_phrase" in wording:
        phrase = wording["anchor_phrase"] or ""
    else:
        phrase = getattr(anchor, "phrase", "") or ""
    if phrase and phrase not in (instruction or ""):
        return StageResult(False, "wording_lost_the_reference",
                           {"phrase": phrase})
    if not expected:
        return StageResult(True, detail={"resolved": "not_checked"})
    try:
        resolved = anchor.resolve(scene)
    except Exception as exc:
        return StageResult(False, "wording_reference_unreadable",
                           {"error": repr(exc)[:120]})
    if sorted(resolved) != sorted(expected):
        return StageResult(False, "wording_reference_moved",
                           {"resolved": resolved[:4]})
    return StageResult(True, detail={"resolved": len(resolved)})


# ------------------------------------------------ the under-specified form


def check_underspecified(scene, instruction: str, clarification: dict[str, Any],
                         family: str) -> StageResult:
    """Stage 1, for a task whose instruction leaves out a value it needs.

    Three things have to hold before such a task is worth keeping.  The value
    the record says is missing is really absent from the sentence.  The sentence
    still names what kind of element it is about, so the reader can ask a
    question rather than guess at the subject.  And the model holds more than
    one element the reduced sentence could mean, which is what makes the
    instruction ambiguous rather than merely terse.
    """
    slot = clarification.get("slot")
    text = instruction or ""
    omitted = clarification.get("omitted_phrase") or ""
    if slot == "element":
        if omitted and omitted in text:
            return StageResult(False, "underspecified_reference_still_named",
                               {"phrase": omitted})
        if len(scene.elements(family)) < 2:
            return StageResult(False, "underspecified_reference_is_unique")
    if slot == "storey":
        for storey in scene.storeys:
            label = scene.storey_label(storey)
            if label and label in text:
                return StageResult(False, "underspecified_storey_still_named",
                                   {"label": label})
        if len(scene.storeys) < 2:
            return StageResult(False, "underspecified_storey_is_unique")
    if slot == "dimension" and any(ch.isdigit() for ch in text.split(")")[-1]):
        # A dimension task may still quote an identifier or a name, so only the
        # part of the sentence after the reference is read for a number.
        return StageResult(False, "underspecified_value_still_quoted")
    if "?" not in clarification.get("question", ""):
        return StageResult(False, "underspecified_question_is_not_a_question")
    return StageResult(True, detail={"slot": slot})


def check_no_edit(source_ifc: str, gold_ifc: str, models=None) -> StageResult:
    """The gold of an under-specified task changed nothing in the model.

    The comparison is the one the batch check already uses, entity by entity
    over every product, so "unchanged" means what the score means by it rather
    than what the file's bytes happen to say after a round trip through the
    writer.
    """
    source = models.get(source_ifc) if models is not None \
        else ifcopenshell.open(source_ifc)
    gold = ifcopenshell.open(gold_ifc)
    before = {p.GlobalId for p in source.by_type("IfcProduct")}
    after = {p.GlobalId for p in gold.by_type("IfcProduct")}
    if before != after:
        return StageResult(False, "no_edit_gold_changed_the_entity_set",
                           {"added": len(after - before),
                            "removed": len(before - after)})
    changed = []
    for guid in sorted(before):
        try:
            if batch_signature(source.by_guid(guid)) != \
                    batch_signature(gold.by_guid(guid)):
                changed.append(guid)
        except Exception:
            continue
        if len(changed) > 3:
            break
    if changed:
        return StageResult(False, "no_edit_gold_changed_an_element",
                           {"guids": changed[:4]})
    return StageResult(True, detail={"n_products": len(after)})


# ------------------------------------------------------- the batch scope


def batch_signature(entity) -> Any:
    """Everything about an element a batch edit could change.

    The entity's own attributes and its expanded geometry come from the
    scorer's own signature, which the topology axis already uses; the material,
    the type object and the spatial container hang off the element through
    relationships and are read separately.
    """
    from modifc_score.topology import full_signature
    import ifcopenshell.util.element as element_util

    material = None
    try:
        associated = element_util.get_material(entity)
        material = None if associated is None else associated.id()
    except Exception:
        material = "unreadable"
    type_object = None
    try:
        assigned = element_util.get_type(entity)
        type_object = None if assigned is None else assigned.GlobalId
    except Exception:
        type_object = "unreadable"
    container = tuple(sorted(
        getattr(relation.RelatingStructure, "GlobalId", "")
        for relation in getattr(entity, "ContainedInStructure", ()) or ()))
    return (full_signature(entity), material, type_object, container)


def check_batch_scope(source_ifc: str, gold_ifc: str, members: Sequence[str],
                      pool: Sequence[str], models=None) -> StageResult:
    """Stage 5: a batch edit changed every member of the set and nothing else.

    Every element the set was drawn from is compared between the source model
    and the gold model.  A member has to differ and a non-member has to be
    identical, which is what makes the instruction's word "all" true of the file
    rather than of the generator's intention.
    """
    wanted = set(members)
    source = models.get(source_ifc) if models is not None \
        else ifcopenshell.open(source_ifc)
    gold = ifcopenshell.open(gold_ifc)
    missed: list[str] = []
    spilled: list[str] = []
    for guid in sorted(set(pool) | wanted):
        try:
            before = source.by_guid(guid)
        except Exception:
            continue
        try:
            after = gold.by_guid(guid)
        except Exception:
            after = None
        if after is None:
            if guid not in wanted:
                spilled.append(guid)
            continue
        changed = batch_signature(before) != batch_signature(after)
        if guid in wanted and not changed:
            missed.append(guid)
        elif guid not in wanted and changed:
            spilled.append(guid)
    if missed:
        return StageResult(False, "batch_member_unchanged",
                           {"guids": missed[:4], "n": len(missed)})
    if spilled:
        return StageResult(False, "batch_changed_outside_set",
                           {"guids": spilled[:4], "n": len(spilled)})
    return StageResult(True, detail={"n_members": len(wanted),
                                     "n_pool": len(set(pool) | wanted)})


def check_self_score(task_id: str, operation: str, category: str,
                     entity_type: str, guids: Sequence[str], source_ifc: str,
                     gold_ifc: str, models=None, meshes=None,
                     settings: Optional[dict] = None) -> StageResult:
    """Stage 4: the gold model scores 1 against itself.

    ``settings`` are scorer settings a family is read under on top of the
    self-check's own, as the Revit-export family reads the type and material.
    """
    from modifc_score.model_cache import MESHES, MODELS
    from modifc_score.scorer import score_task
    from modifc_score.tasks import Task

    task = Task(task_id=task_id, operation=operation, category=category,
                input_ifc=source_ifc, ground_truth_ifc=gold_ifc, prompt="",
                entity_type=entity_type, guids=tuple(guids), tags=())
    try:
        config = scorer_config(operation)
        if settings:
            config = dataclasses.replace(config, **settings)
        score = score_task(task, source_ifc, gold_ifc, gold_ifc, config,
                           models or MODELS, meshes or MESHES,
                           geometry_mode="per_pair")
    except Exception as exc:
        return StageResult(False, "self_score_failed", {"error": repr(exc)[:200]})
    axes = {"geometry": score.geometry, "semantics": score.semantics,
            "topology": score.topology, "final": score.final_score,
            "n_reference": score.n_reference, "n_matched": score.n_matched,
            "gt_source": score.gt_source, "error": score.error}
    if score.error:
        return StageResult(False, "self_score_error", axes)
    if min(score.geometry, score.semantics, score.topology) < SELF_SCORE_FLOOR:
        weakest = min(("geometry", score.geometry), ("semantics", score.semantics),
                      ("topology", score.topology), key=lambda p: p[1])[0]
        return StageResult(False, f"self_score_low_{weakest}", axes)
    return StageResult(True, detail=axes)


def null_edit_score(task_id: str, operation: str, category: str,
                    entity_type: str, guids: Sequence[str], source_ifc: str,
                    gold_ifc: str, models=None, meshes=None) -> Optional[float]:
    """What the unedited source model scores on the task.

    Not a gate.  It is the floor a system earns for doing nothing, and it is
    recorded so the difficulty audit can tell a demanding task from an easy one.
    """
    from modifc_score.model_cache import MESHES, MODELS
    from modifc_score.scorer import score_task
    from modifc_score.tasks import Task

    task = Task(task_id=task_id, operation=operation, category=category,
                input_ifc=source_ifc, ground_truth_ifc=gold_ifc, prompt="",
                entity_type=entity_type, guids=tuple(guids), tags=())
    try:
        score = score_task(task, source_ifc, gold_ifc, source_ifc,
                           scorer_config(operation),
                           models or MODELS, meshes or MESHES,
                           geometry_mode="per_pair")
    except Exception:
        return None
    return float(score.final_score)
