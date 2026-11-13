"""Drawing tasks from one model, and the record each accepted task becomes.

One function draws an edit and its instruction for a requested cell of the
design grid; another runs the verification funnel over the result and writes the
gold model.  The batch driver in :mod:`modifc_gen.run` decides which cells each
model is asked for.
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import anchors as anchor_lib
from . import chains, conditions, families, ops, script, settings, templates
from . import verify, wording as wording_lib
from .anchors import Anchor
from .ops import EditPlan
from .scene import FAMILY_CLASS, FAMILY_CODE, Scene
from .version import GENERATOR_VERSION

CATEGORIES = ("direct", "spatial", "topological")
OPERATIONS = ("create", "update", "delete")
FAMILIES = tuple(FAMILY_CLASS)

OPERATION_CODE = {"create": "CRE", "update": "UPD", "delete": "DEL"}
CATEGORY_CODE = {"direct": "DIR", "spatial": "SPA", "topological": "TOP"}
CHAIN_CODE = {"move_wall_with_fillings": "MWF",
              "delete_wall_with_fillings": "DWF",
              "move_space_with_bounding_walls": "MSW",
              "create_wall_with_door": "CWD"}

# How many candidate targets one draw looks at before giving up on a cell.
MAX_TARGET_TRIES = 40


@dataclass
class Draw:
    """One drawn task, before it has been verified."""

    plan: EditPlan
    anchor: Anchor
    anchor_expected: tuple[str, ...]
    category: str
    instruction: str
    entity_type: str


def cell_id(category: str, operation: str, family: str) -> str:
    return f"{category}/{operation}/{family}"


def task_id_for(model_key: str, category: str, operation: str, family: str,
                index: int) -> str:
    return (f"{FAMILY_CODE[family]}-{OPERATION_CODE[operation]}-"
            f"{CATEGORY_CODE[category]}-{model_key}-{index:03d}")


def chain_task_id(model_key: str, category: str, chain_kind: str,
                  index: int) -> str:
    return (f"CHN-{CHAIN_CODE[chain_kind]}-{CATEGORY_CODE[category]}-"
            f"{model_key}-{index:03d}")


# ------------------------------------------------------------------- drawing


def _shuffled(items: Sequence[Any], rng: random.Random) -> list[Any]:
    out = list(items)
    rng.shuffle(out)
    return out


def _create_context(scene: Scene, storey, category: str, rng: random.Random
                    ) -> Optional[tuple[Anchor, str, Any]]:
    """How a create instruction names the storey it puts the element on."""
    if category == "direct":
        anchor = Anchor(kind="guid", family="storey",
                        phrase=f"the storey with GlobalId '{storey.GlobalId}'",
                        params={"guid": storey.GlobalId})
        return anchor, anchor.phrase, None
    label = scene.storey_label(storey)
    if label is None:
        return None
    for family in _shuffled(("wall", "column", "slab", "space"), rng):
        for element in _shuffled(scene.elements(family), rng)[:60]:
            if scene.storey_guid_of(element) != storey.GlobalId:
                continue
            name = scene.unique_name(element)
            if not name:
                continue
            anchor = Anchor(
                kind="name", family=family,
                phrase=f"the {anchor_lib.ARTICLE[family]} named '{name}'",
                params={"name": name})
            if anchor.resolve(scene) != [element.GlobalId]:
                continue
            if category == "spatial":
                return anchor, label, element
            # A space belongs to a storey through aggregation; everything else
            # is contained in one.  The phrase follows the model's own relation.
            phrase = (f"the storey that {anchor.phrase} belongs to"
                      if family == "space"
                      else f"the storey that contains {anchor.phrase}")
            return anchor, phrase, element
    return None



# ------------------------------------------------ the 0.5.0 create pipeline


def _name_anchor(scene: Scene, guid: str) -> Optional[Anchor]:
    """A name anchor for one element, or None when its name is not its own."""
    element = scene.by_guid(guid)
    if element is None:
        return None
    family = scene.family_of(element)
    name = scene.unique_name(element)
    if family is None or not name:
        return None
    anchor = Anchor(kind="name", family=family,
                    phrase=f"the {anchor_lib.ARTICLE[family]} named '{name}'",
                    params={"name": name})
    return anchor if anchor.resolve(scene) == [guid] else None


def _dress_create(scene: Scene, plan, storey, category: str, task_id: str,
                  rng: random.Random) -> None:
    """Give a create task its coordinate form and its relationship clause.

    Called once the position is settled.  Which of the two forms the position is
    quoted in changes the words and not the place, and the relationship clause
    is only added where the model can carry what it says.
    """
    if plan.kind == "create_box" and not plan.params.get("placement") \
            and not plan.params.get("offset") \
            and families.draw("spec.world_frame", rng):
        if ops.use_world_coordinates(scene, plan, storey):
            # How the world-frame numbers are laid out is a second draw, over
            # the forms the registry lists rather than over a fixed pair.
            detail = families.choose("spec.world_frame.detail", rng,
                                     target="box")
            builder = families.build(detail) if detail is not None else None
            if builder is not None:
                builder(scene, plan, storey, rng)
    if families.draw("constraint.relation_on_create", rng):
        if ops.attach_relations(scene, plan, storey, task_id, rng):
            if families.draw("wording.ifc_class", rng):
                plan.params["relation_by_class"] = True
                ops.tag(plan, "wording.ifc_class_name")


# --------------------------------------------- layer 7: how it is worded


def worded(scene: Scene, plan: EditPlan, anchor: Anchor, category: str,
           rng: random.Random, render=None) -> str:
    """Render one instruction and draw the wording it is written in.

    The unit the lengths are stated in has to be chosen before the sentence is
    built, so it is drawn first and the sentence is rendered in it; everything
    else the wording layer varies is an exact substitution on the finished
    sentence.  A sentence the drawn unit does not change is written in metres
    and carries no unit tag, because an instruction with no length in it states
    no length in millimetres either.  The wording is recorded on the plan, so
    the record says which variants the task carries and the funnel can read the
    sentence back out of it.
    """
    if render is None:
        def render(chosen_dialect):
            return templates.render_in(chosen_dialect, scene, plan, anchor,
                                       category)
    dialect, drawn = wording_lib.draw_dialect(scene, rng)
    plain = render(wording_lib.PLAIN)
    text = render(dialect) if drawn else plain
    if drawn and text == plain:
        dialect, drawn = wording_lib.PLAIN, False
    text, chosen = wording_lib.apply(text, scene, plan, anchor, rng, dialect,
                                     drawn)
    plan.params["wording"] = chosen.as_record()
    for name in chosen.tags:
        ops.tag(plan, name)
    return text


#: Which value an under-specified instruction may leave out, in the order a
#: draw tries them.  The order is fixed so the draw is reproducible from the
#: seed and does not depend on which slot happens to be tried first.
UNDERSPECIFIED_SLOTS = ("element", "dimension", "storey")


def underspecify(scene: Scene, drawn: Draw, rng: random.Random) -> Optional[Draw]:
    """Turn one complete task into an instruction that leaves a value out.

    The gold of such a task makes no change to the model, because the reader
    cannot know what to change, and the answer the record expects is one
    question naming the value that is missing.  A task the reduced form would
    not actually leave ambiguous is refused rather than written: a model with
    one wall in it does not make "move the wall" a question.
    """
    plan = drawn.plan
    if plan.params.get("scope") == "batch" or plan.kind in chains.CHAIN_NAMES:
        return None
    slots = list(UNDERSPECIFIED_SLOTS)
    rng.shuffle(slots)
    for slot in slots:
        if slot == "element" and len(scene.elements(plan.family)) < 2:
            continue
        if slot == "storey" and len(scene.storeys) < 2:
            continue
        def render(chosen_dialect, slot=slot):
            return templates.underspecified_in(chosen_dialect, scene, plan,
                                               drawn.anchor, drawn.category,
                                               slot)

        if render(wording_lib.PLAIN) is None:
            continue
        subject = {"element": plan.family,
                   "storey": plan.family,
                   "dimension": plan.params.get("dimension") or "value"
                   }[slot]
        reduced = ops.EditPlan(
            kind="clarify", operation=plan.operation, family=plan.family,
            calls=[], target_guids=(), touched_guids=(),
            params={"magnitude": "small",
                    "families": ["wording.underspecified"],
                    "intended_edit_kind": plan.kind,
                    "clarification": {
                        "slot": slot,
                        "subject": subject,
                        "question": wording_lib.clarification_question(
                            slot, subject),
                        "keywords": list(
                            wording_lib.MISSING_SLOTS[slot]["keywords"]),
                        "omitted_phrase": drawn.anchor.phrase
                        if slot == "element" else "",
                    }})
        # An instruction that leaves the element or the storey out must not
        # have either put back by the wording layer, and must not record a
        # reference the sentence no longer carries.  Only the form that drops a
        # dimension still names its element, so only that one keeps its phrase.
        naming = drawn.anchor if slot == "dimension" else Anchor(
            kind=drawn.anchor.kind, family=plan.family, phrase="", params={})
        text = worded(scene, reduced, naming, drawn.category, rng,
                      render=render)
        return Draw(reduced, drawn.anchor, drawn.anchor_expected,
                    drawn.category, text, drawn.entity_type)
    return None


# ------------------------------------------------ the 0.6.0 layer 5 scopes


def batch_pool(scene: Scene, family: str, members: Sequence[str]) -> list[str]:
    """Every element the reader would weigh against the set the phrase names.

    The funnel checks that the gold changed the members of the set and no other
    element of this pool.  The pool is the whole family where the model is small
    enough to compare entity by entity, and the family on the members' own
    storeys otherwise, which is the part of it a reader could confuse.
    """
    everything = [e.GlobalId for e in scene.elements(family)]
    if len(everything) <= 120:
        return sorted(everything)
    storeys = {scene.storey_guid_of(scene.by_guid(g)) for g in members}
    near = [e.GlobalId for e in scene.elements(family)
            if scene.storey_guid_of(e) in storeys]
    return sorted(set(near) | set(members))


def draw_batch(scene: Scene, category: str, operation: str, family: str,
               task_id: str, rng: random.Random) -> Optional[Draw]:
    """One edit written over every element a set phrase names.

    A set phrase names a storey, a host wall or a room, so it is a topological
    reference; a conditional set adds a measurement and is a spatial one.  A
    direct instruction names a set by listing its members' identifiers.
    """
    id_list = False
    if category == "direct":
        # A direct instruction names a set by listing its members'
        # identifiers (0.9.0), and by nothing else.
        if not families.draw("scope.id_list", rng):
            return None
        id_list, conditional = True, False
    else:
        conditional = families.draw("scope.conditional", rng)
    if category == "spatial" and not conditional:
        return None
    for anchor in anchor_lib.set_anchors(scene, family, rng,
                                         conditional=conditional,
                                         id_list=id_list):
        guids = anchor.resolve(scene)
        if not 2 <= len(guids) <= ops.MAX_BATCH:
            continue
        members = [scene.by_guid(g) for g in guids]
        if any(m is None for m in members):
            continue
        plan = ops.plan_batch(scene, members, rng, task_id,
                              pool=batch_pool(scene, family, guids),
                              conditional=conditional, operation=operation)
        if plan is None:
            continue
        instruction = worded(scene, plan, anchor, category, rng)
        return Draw(plan, anchor, tuple(guids), category, instruction,
                    FAMILY_CLASS[family])
    return None


def draw_create_new(scene: Scene, category: str, family: str, task_id: str,
                    rng: random.Random) -> Optional[Draw]:
    """A create task that copies, arrays or replaces an element already there."""
    source_family = ops.REPLACEMENT.get(family, family)
    if family == "space":
        return None
    for source in _shuffled(scene.elements(source_family), rng)[:MAX_TARGET_TRIES]:
        anchor = anchor_lib.build_anchor(scene, source, category, rng)
        if anchor is None:
            continue
        plan = ops.plan_create_new(scene, family, source, rng, task_id)
        if plan is None:
            continue
        instruction = worded(scene, plan, anchor, category, rng)
        return Draw(plan, anchor, (source.GlobalId,), category, instruction,
                    FAMILY_CLASS[family])
    return None


def draw_single(scene: Scene, category: str, operation: str, family: str,
                task_id: str, rng: random.Random) -> tuple[Optional[Draw], str]:
    """Draw one non-compositional task, under-specified in a small share of draws.

    An under-specified instruction is written from a complete one, so the value
    it leaves out is a value the model could have supplied and the record knows
    exactly which one it is.  A draw the reduction cannot be written for keeps
    the complete instruction rather than being refused, so the share is a
    preference and the realised count is lower.
    """
    drawn, reason = _draw_complete(scene, category, operation, family, task_id,
                                   rng)
    if drawn is None:
        return None, reason
    if families.draw("wording.underspecified", rng):
        reduced = underspecify(scene, drawn, rng)
        if reduced is not None:
            return reduced, ""
    return drawn, ""


def _draw_complete(scene: Scene, category: str, operation: str, family: str,
                   task_id: str, rng: random.Random
                   ) -> tuple[Optional[Draw], str]:
    """Draw one non-compositional task, or say why the model cannot host it."""
    reasons: list[str] = []
    if operation in ("update", "delete"):
        if families.draw("scope.batch", rng):
            drawn = draw_batch(scene, category, operation, family, task_id, rng)
            if drawn is not None:
                return drawn, ""
            reasons.append("no_editable_set")
        candidates = _shuffled(scene.elements(family), rng)[:MAX_TARGET_TRIES]
        if not candidates:
            return None, "no_element_of_family"
        for target in candidates:
            anchor = anchor_lib.build_anchor(scene, target, category, rng)
            if anchor is None:
                reasons.append("no_unique_anchor")
                continue
            plan = (ops.plan_update(scene, target, rng, task_id)
                    if operation == "update"
                    else ops.plan_delete(scene, target, rng))
            if plan is None:
                reasons.append("no_feasible_edit")
                continue
            instruction = worded(scene, plan, anchor, category, rng)
            return Draw(plan, anchor, (target.GlobalId,), category, instruction,
                        FAMILY_CLASS[family]), ""
        return None, _dominant(reasons)

    if families.draw("op.create.revit", rng):
        from . import revit

        style = {v: k for k, v in revit.STYLE_CATEGORY.items()}[category]
        drawn, reason = revit.draw(scene, family, style, task_id, rng)
        if drawn is not None:
            return drawn, ""
        reasons.append(reason)

    if families.draw("op.create.new", rng):
        drawn = draw_create_new(scene, category, family, task_id, rng)
        if drawn is not None:
            return drawn, ""
        reasons.append("no_new_create_operation")

    if family in ("door", "window"):
        walls = _shuffled(scene.elements("wall"), rng)[:MAX_TARGET_TRIES]
        if not walls:
            return None, "no_host_wall"
        for wall in walls:
            if category == "direct":
                anchor = anchor_lib.guid_anchor(scene, wall)
            else:
                anchor = anchor_lib.build_anchor(scene, wall, category, rng)
            if anchor is None or anchor.resolve(scene) != [wall.GlobalId]:
                reasons.append("no_unique_anchor")
                continue
            plan = ops.plan_create_filling(scene, family, wall, task_id, rng)
            if plan is None:
                reasons.append("wall_cannot_host_opening")
                continue
            if category != "direct" and \
                    families.draw("spec.element_relative", rng):
                ops.derive_filling_placement(scene, plan, wall, rng)
            storey = scene.storey_of(wall)
            if storey is not None:
                _dress_create(scene, plan, storey, category, task_id, rng)
            instruction = worded(scene, plan, anchor, category, rng)
            return Draw(plan, anchor, (wall.GlobalId,), category, instruction,
                        FAMILY_CLASS[family]), ""
        return None, _dominant(reasons)

    storeys = _shuffled(scene.storeys, rng)
    if not storeys:
        return None, "no_storey"
    for storey in storeys:
        context = _create_context(scene, storey, category, rng)
        if context is None:
            reasons.append("no_unique_storey_reference")
            continue
        anchor, where, reference = context
        plan = ops.plan_create_box(scene, family, storey, task_id, rng)
        if plan is None:
            reasons.append("no_room_on_storey")
            continue
        derived = False
        # A position read off the model belongs to the two styles that locate an
        # element by what is around it.  A direct instruction quotes numbers, so
        # it keeps them and only the frame they are read in may change.
        if category != "direct" and \
                families.draw("spec.element_relative", rng):
            derived = ops.derive_box_placement(scene, plan, storey, rng)
        if derived:
            # The instruction now names the elements the position was read off,
            # so the record's anchor names one of them instead of the neighbour
            # the storey phrase happened to use.
            replacement = _name_anchor(
                scene, plan.params["placement"]["anchor_guid"])
            if replacement is None:
                reasons.append("derived_reference_not_nameable")
                continue
            anchor, reference = replacement, scene.by_guid(
                plan.params["placement"]["anchor_guid"])
            if category == "topological":
                where = scene.storey_label(storey) or where
        elif category == "spatial":
            if not ops.respot_from_reference(scene, plan, storey, reference, rng):
                reasons.append("storey_not_axis_aligned")
                continue
        plan.params["where"] = where
        _dress_create(scene, plan, storey, category, task_id, rng)
        instruction = worded(scene, plan, anchor, category, rng)
        expected = (reference.GlobalId if reference is not None
                    else storey.GlobalId,)
        return Draw(plan, anchor, expected, category, instruction,
                    FAMILY_CLASS[family]), ""
    return None, _dominant(reasons)


def draw_chain(scene: Scene, category: str, chain_kind: str, task_id: str,
               rng: random.Random) -> tuple[Optional[Draw], str]:
    """Draw one compositional task, or say why the model cannot host it."""
    reasons: list[str] = []
    if chain_kind == "create_wall_with_door":
        for storey in _shuffled(scene.storeys, rng):
            context = _create_context(scene, storey, category, rng)
            if context is None:
                reasons.append("no_unique_storey_reference")
                continue
            anchor, where, reference = context
            plan = chains.plan_create_wall_with_door(scene, storey, task_id, rng)
            if plan is None:
                reasons.append("no_room_on_storey")
                continue
            plan.params["where"] = where
            instruction = worded(scene, plan, anchor, category, rng)
            expected = (reference.GlobalId if reference is not None
                        else storey.GlobalId,)
            return Draw(plan, anchor, expected, category, instruction,
                        plan.params["entity_type"]), ""
        return None, _dominant(reasons)

    if chain_kind == "move_space_with_bounding_walls":
        family, planner = "space", chains.plan_move_space_with_bounding_walls
    elif chain_kind == "move_wall_with_fillings":
        family, planner = "wall", chains.plan_move_wall_with_fillings
    else:
        family, planner = "wall", chains.plan_delete_wall_with_fillings

    candidates = _shuffled(scene.elements(family), rng)[:MAX_TARGET_TRIES]
    if not candidates:
        return None, "no_element_of_family"
    for target in candidates:
        anchor = anchor_lib.build_anchor(scene, target, category, rng)
        if anchor is None:
            reasons.append("no_unique_anchor")
            continue
        plan = planner(scene, target, task_id, rng)
        if plan is None:
            reasons.append("no_feasible_chain")
            continue
        instruction = worded(scene, plan, anchor, category, rng)
        return Draw(plan, anchor, (target.GlobalId,), category, instruction,
                    plan.params["entity_type"]), ""
    return None, _dominant(reasons)


def _dominant(reasons: list[str]) -> str:
    if not reasons:
        return "no_candidate"
    counts: dict[str, int] = {}
    for reason in reasons:
        counts[reason] = counts.get(reason, 0) + 1
    return max(counts, key=lambda r: counts[r])


# ----------------------------------------------------------------- recording


def anchor_pool(scene: Scene, anchor: Anchor) -> int:
    """How many elements the anchor had to be told apart from."""
    storey_guid = anchor.params.get("storey_guid")
    if storey_guid is not None:
        return len(scene.on_storey(anchor.family, storey_guid))
    return len(scene.elements(anchor.family))


def _anchor_record(draw: Draw) -> dict[str, Any]:
    """The anchor as the record carries it, after the identifier rewrite.

    The rewrite of 0.9.0 may respell the phrase, and it turns a ``name``
    anchor whose sentence now quotes the element's identifier into a ``guid``
    anchor.  The predicate the funnel checked resolves to the same element
    either way, so only the words and, for that one case, the kind change.
    """
    record = dict(draw.anchor.as_record(), expected=list(draw.anchor_expected))
    rewrite = (draw.plan.params.get("wording") or {}).get("anchor_rewrite")
    if rewrite:
        record["phrase"] = rewrite.get("phrase", record["phrase"])
        if rewrite.get("kind"):
            record["kind"] = rewrite["kind"]
            record["params"] = dict(rewrite.get("params") or {})
    return record


def build_record(scene: Scene, model_ref, task_id: str, draw: Draw,
                 gold_relpath: str, seed: int, script_source: str
                 ) -> dict[str, Any]:
    plan = draw.plan
    return {
        # The five fields ModIFC-Score reads, so this file loads as a task list.
        "task_id": task_id,
        "input_ifc": model_ref.relpath,
        "ground_truth_ifc": gold_relpath,
        "operation": plan.operation,
        "category": draw.category,
        "prompt": draw.instruction,
        "target": {"entity_type": draw.entity_type,
                   "guids": list(plan.target_guids)},
        # The generator's own record.
        "source_model": {"relpath": model_ref.relpath, "sha256": model_ref.sha256,
                         "collection": model_ref.collection,
                         "schema": model_ref.schema, "key": model_ref.key},
        "element_type": draw.entity_type,
        "family": plan.family,
        "edit_kind": plan.kind,
        "tier": "compositional" if plan.kind in chains.CHAIN_NAMES else "single",
        "instruction": draw.instruction,
        "instruction_paraphrase": None,
        "gold_script": script_source,
        "gold_model": gold_relpath,
        "anchor": _anchor_record(draw),
        "edit_params": plan.params,
        "difficulty": {
            "elements_touched": plan.elements_touched,
            "relation_chain_length": draw.anchor.chain_length,
            "anchor_ambiguity_count": len(draw.anchor.resolve(scene)),
            "anchor_candidate_pool": anchor_pool(scene, draw.anchor),
            "scene_n_products": scene.n_products,
            "scene_n_relations": scene.n_relations,
            "param_magnitude_bucket": plan.params.get("magnitude", "unknown"),
            "n_created": len(plan.created_guids),
            "n_removed": len(plan.removed_guids),
        },
        "edit_guids": {"target": list(plan.target_guids),
                       "touched": list(plan.touched_guids),
                       "created": list(plan.created_guids),
                       "removed": list(plan.removed_guids),
                       "relations": list(plan.relation_guids)},
        # What Stage A stratifies on and Stage C rewards: which of the
        # requirement families this task carries, and which relationship
        # classes its gold script writes.
        "families": sorted(set(ops.family_tags(
            plan, draw.anchor.kind,
            tier="compositional" if plan.kind in chains.CHAIN_NAMES
            else "single")) | set(conditions.model_tags(
                scene, plan, draw.anchor, expected=draw.anchor_expected))),
        "requires_relations": ops.required_relations(plan),
        # Layer 6 as the record carries it: what the source model itself is,
        # measured rather than declared, so a benchmark can report per
        # condition and an audit can recompute every tag from the record.
        "model_conditions": {
            "schema": scene.schema,
            "length_unit": conditions.unit_word(scene.unit_scale),
            "unit_scale": scene.unit_scale,
            "site_offset": bool(conditions.has_site_offset(scene)),
        },
        # Layer 7 as the record carries it: which wording variants the sentence
        # was written in, and, for an instruction that leaves a value out, what
        # is missing and what a correct answer asks.
        "wording": plan.params.get("wording"),
        "clarification": plan.params.get("clarification"),
        "expected_reply": (plan.params.get("clarification") or {}).get("question"),
        "seeds": {"task_seed": seed},
        "generator_version": GENERATOR_VERSION,
        "wave": settings.SETTINGS.wave,
    }


# ---------------------------------------------------------------- production


@dataclass
class Outcome:
    """What happened to one attempted task."""

    task_id: str
    stage: str
    reason: str = ""
    record: Optional[dict[str, Any]] = None
    detail: dict[str, Any] = field(default_factory=dict)


def produce(scene: Scene, model_ref, task_id: str, draw: Draw, root: Path,
            out_dir: Path, scratch: Path, models=None, meshes=None,
            seed: int = 0, want_null_baseline: bool = True,
            keep_gold: bool = True) -> Outcome:
    """Write and verify one drawn task.

    With ``keep_gold`` false the gold model is written into the scratch
    directory, verified there, and deleted; the record still names the path the
    model would occupy and carries its checksum, which is what lets the
    materialisation utility rebuild it and prove it rebuilt the same file.
    """
    nominal_path = out_dir / "models" / f"{task_id}.ifc"
    try:
        gold_relpath = str(nominal_path.relative_to(root))
    except ValueError:
        gold_relpath = str(nominal_path)
    if keep_gold:
        gold_dir = out_dir / "models"
    else:
        gold_dir = scratch / "gold"
    gold_dir.mkdir(parents=True, exist_ok=True)
    gold_path = gold_dir / f"{task_id}.ifc"
    source_path = str(root / model_ref.relpath)

    script_source = script.render_script(task_id, draw.instruction, draw.plan)

    clarification = draw.plan.params.get("clarification")
    if clarification:
        # An under-specified instruction is kept for the opposite reason to
        # every other task: its reference is not meant to single an element out,
        # so the anchor check is replaced by one that the value the record says
        # is missing really is missing and that more than one element fits.
        stage = verify.check_underspecified(scene, draw.instruction,
                                            clarification, draw.plan.family)
        if not stage.ok:
            return Outcome(task_id, "underspecified", stage.reason,
                           detail=stage.detail)
    else:
        stage = verify.check_anchor(scene, draw.anchor, draw.anchor_expected)
        if not stage.ok:
            return Outcome(task_id, "anchor", stage.reason, detail=stage.detail)
        stage = verify.check_wording(scene, draw.instruction, draw.anchor,
                                     draw.plan.params.get("wording"),
                                     draw.anchor_expected)
        if not stage.ok:
            return Outcome(task_id, "wording", stage.reason,
                           detail=stage.detail)

    # An update leaves its targets in the model, so they have to be readable as
    # surfaces before the edit is worth writing out.
    if draw.plan.operation == "update" and not clarification:
        stage = verify.check_meshable(source_path, draw.plan.target_guids,
                                      meshes, models)
        if not stage.ok:
            return Outcome(task_id, "meshable", stage.reason, detail=stage.detail)

    try:
        script.execute_script(script_source, source_path, str(gold_path))
    except Exception as exc:
        _unlink(gold_path)
        return Outcome(task_id, "apply", "gold_script_failed",
                       detail={"error": repr(exc)[:200]})

    stage = verify.check_parse(str(gold_path), draw.plan.created_guids,
                               draw.plan.removed_guids,
                               draw.plan.params.get("relation_edges") or (),
                               draw.plan.params.get("expected_world_box"),
                               draw.plan.relation_guids,
                               draw.plan.params.get("expected_world_origin"))
    if not stage.ok:
        _unlink(gold_path)
        return Outcome(task_id, "parse", stage.reason, detail=stage.detail)

    # A door or window the edit placed must not open into a wall, a column or
    # a slab edge, which the overlap tests of the planners cannot see when the
    # obstruction only touches the host wall's face.
    stage = verify.check_filling_clearance(
        scene, str(gold_path), draw.plan.created_guids,
        tuple(draw.plan.target_guids) + tuple(draw.plan.touched_guids), models)
    if not stage.ok:
        _unlink(gold_path)
        return Outcome(task_id, "clearance", stage.reason, detail=stage.detail)

    if draw.plan.params.get("scope") == "batch":
        stage = verify.check_batch_scope(
            source_path, str(gold_path),
            draw.plan.params.get("batch_members") or draw.plan.target_guids,
            draw.plan.params.get("batch_pool") or (), models)
        if not stage.ok:
            _unlink(gold_path)
            return Outcome(task_id, "batch_scope", stage.reason,
                           detail=stage.detail)

    stage = verify.check_reexecution(script_source, source_path, str(gold_path),
                                     list(draw.plan.touched_guids), str(scratch))
    if not stage.ok:
        _unlink(gold_path)
        return Outcome(task_id, "reexecute", stage.reason, detail=stage.detail)
    reexecution_match = stage.detail.get("match")

    if clarification:
        # The gold of an under-specified task is the model with nothing done to
        # it, so what has to be proved is that nothing was done rather than that
        # the right thing was.  Scoring it against itself would say nothing: the
        # score of a model against itself is one whatever the task asked for.
        stage = verify.check_no_edit(source_path, str(gold_path), models)
        if not stage.ok:
            _unlink(gold_path)
            return Outcome(task_id, "no_edit", stage.reason,
                           detail=stage.detail)
        stage = verify.StageResult(True, detail={"geometry": 1.0,
                                                 "semantics": 1.0,
                                                 "topology": 1.0, "final": 1.0})
    else:
        family_settings = None
        if "op.create.revit" in (draw.plan.params.get("families") or ()):
            from .revit import SCORER_SETTINGS as family_settings
        stage = verify.check_self_score(task_id, draw.plan.operation,
                                        draw.category, draw.entity_type,
                                        draw.plan.target_guids, source_path,
                                        str(gold_path), models, meshes,
                                        family_settings)
        if not stage.ok:
            _unlink(gold_path)
            return Outcome(task_id, "self_score", stage.reason,
                           detail=stage.detail)

    record = build_record(scene, model_ref, task_id, draw, gold_relpath, seed,
                          script_source)
    record["verification"] = {
        "self_score": {k: stage.detail.get(k) for k in
                       ("geometry", "semantics", "topology", "final")},
        "gold_sha256": verify.sha256_of(str(gold_path)),
        "gold_bytes": gold_path.stat().st_size,
        "reexecution_match": reexecution_match,
        "delete_semantics_reading": ("removal" if draw.plan.operation == "delete"
                                     else "matcher"),
    }
    if want_null_baseline and not clarification:
        record["verification"]["null_edit_score"] = verify.null_edit_score(
            task_id, draw.plan.operation, draw.category, draw.entity_type,
            draw.plan.target_guids, source_path, str(gold_path), models, meshes)
    record["verification"]["gold_materialized"] = bool(keep_gold)
    if not keep_gold:
        # The caches key on path, modification time and size, so an entry for a
        # deleted file is never hit again and both caches are bounded anyway.
        _unlink(gold_path)
    return Outcome(task_id, "accepted", record=record)


def _unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass
