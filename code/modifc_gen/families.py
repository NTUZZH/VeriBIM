"""The requirement families a run may draw, as one registry.

An instruction is an operation on a reference, with a specification and a set of
constraints, at some scope, against a model with its own conditions, in some
wording.  The seven layers are the author's taxonomy of 2026-09-07 and the tags
below are named after it, so a record written now and a record written by a
later version can be counted together.

Everything a family needs sits in its entry here: which layer and group it
belongs to, how often it is drawn relative to its siblings, which instruction
style or which kind of created element it applies to, and the function that
tries to build it.  Adding a family is adding an entry and a function; no driver
and no planner has to learn its name.  A run changes the mix by giving a group
or a family a different weight, which the driver passes through without knowing
what the names mean.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence

# The layers of the taxonomy, in the order an instruction is read.
LAYERS = ("operation", "reference", "specification", "constraint", "scope",
          "model_condition", "wording")


@dataclass(frozen=True)
class Family:
    """One requirement family: its name, where it belongs, and how to build it."""

    tag: str
    group: str
    layer: str
    weight: float = 1.0
    #: The instruction style a reference family may be drawn for.
    style: str = ""
    #: What a specification family may be applied to: a box or a filling.
    target: str = ""
    #: ``module:function`` inside this package, resolved on first use.
    builder: str = ""
    #: Name of a predicate in this module that says whether an edit admits it.
    applies: str = ""


# How often each group is drawn, before a member of it is chosen.  A share of
# one means the group is always attempted and a share of zero switches it off.
# A run overrides any of these by name and never by editing the code.
GROUP_SHARE: dict[str, float] = {
    # Layer 2, the references added in 0.5.0.  The earlier reference kinds are
    # what a draw falls back to, so this is a preference and not a requirement.
    "ref.new": 0.30,
    # Layer 3, where a created element goes and how the position is stated.
    "spec.element_relative": 0.40,
    "spec.world_frame": 0.40,
    "spec.world_frame.detail": 1.00,
    "spec.displacement": 1.00,
    # Layer 4, what has to hold after the edit.
    "constraint.on_edit": 0.30,
    "constraint.relation_on_create": 0.50,
    # Layer 7, whether a relationship is named by its class or in plain words.
    "wording.ifc_class": 0.20,
    # Layer 1, the operations 0.6.0 adds.  A draw that asks for one of them and
    # finds none the target can carry falls back to the earlier operations, so
    # the share is a preference and the realised count is lower.
    "op.update.new": 0.35,
    "op.create.new": 0.35,
    # Layer 5, an edit written over every member of a set, and the share of
    # those sets a measured condition narrows.
    "scope.batch": 0.15,
    "scope.conditional": 0.35,
    # Layer 7, how the same requirement is worded.  Each group is drawn once
    # per instruction, after the sentence has been written from the edit's
    # parameters, so a wording draw changes the words and never the gold.
    "wording.synonym": 0.35,
    "wording.request_form": 0.30,
    "wording.class_token": 0.15,
    "wording.unit_spelling": 0.20,
    # Layer 7, a delete instruction that names the relationships to remove
    # instead of saying "and the relationships that depend on it".  The gold
    # is the same under both wordings, so this is a wording draw.
    "wording.relationship_named": 0.30,
    # Layer 7, how an identifier is written (0.9.0).  Every instruction that
    # carries an identifier draws a spelling; the spelling every earlier
    # version wrote keeps 40 % of the draws inside the family, so the share of
    # the group itself is one.  A reference element the phrase names is named
    # by identifier instead of by name in the drawn share of instructions, and
    # two such identifiers of one noun that stand side by side are written as
    # one list in the drawn share of those.
    "wording.identifier_spelling": 1.00,
    "wording.reference_by_id": 0.40,
    "wording.identifier_list": 0.70,
    # Layer 5, a set named by the identifiers of its members (0.9.0): the share
    # of batch draws in a direct instruction, which names no set otherwise.
    "scope.id_list": 1.00,
    # An instruction that leaves out one value the edit needs.  Its gold makes
    # no change and its answer is a question, so the share is small on purpose.
    "wording.underspecified": 0.05,
    # Layer 6 is measured rather than drawn: a run cannot ask for more
    # millimetre models than the corpus holds.  The group exists so the
    # conditions are named in one place and is never drawn.
    "model.condition": 0.0,
}


FAMILIES: tuple[Family, ...] = (
    # ---- layer 2: which element the instruction points at -----------------
    Family("ref.relative.nearest", "ref.new", "reference", 1.0,
           style="spatial", builder="anchors:nearest_anchors"),
    Family("ref.relative.between", "ref.new", "reference", 1.0,
           style="spatial", builder="anchors:between_anchors"),
    Family("ref.relative.above_below", "ref.new", "reference", 1.0,
           style="spatial", builder="anchors:above_below_anchors"),
    Family("ref.relative.opposite", "ref.new", "reference", 1.0,
           style="topological", builder="anchors:opposite_anchors"),
    Family("ref.topological.separates", "ref.new", "reference", 1.0,
           style="topological", builder="anchors:separates_anchors"),
    Family("ref.viewpoint.through_door", "ref.new", "reference", 1.0,
           style="topological", builder="anchors:egocentric_anchors"),

    # ---- layer 3: where the new element goes ------------------------------
    Family("spec.element_relative.fits_gap", "spec.element_relative",
           "specification", 1.0, target="box", builder="ops:_derive_fits_gap"),
    Family("spec.element_relative.on_top_of", "spec.element_relative",
           "specification", 1.0, target="box", builder="ops:_derive_on_top_of"),
    Family("spec.element_relative.against_room_wall", "spec.element_relative",
           "specification", 1.0, target="box",
           builder="ops:_derive_adjacent_to_space"),
    Family("spec.element_relative.touching_slab_above", "spec.element_relative",
           "specification", 1.0, target="box",
           builder="ops:_derive_touching_slab_above"),
    Family("spec.element_relative.centred_on_wall", "spec.element_relative",
           "specification", 1.0, target="filling",
           builder="ops:_derive_centred_on_wall"),
    Family("spec.element_relative.aligned_with_filling", "spec.element_relative",
           "specification", 1.0, target="filling",
           builder="ops:_derive_above_below_filling"),

    # ---- layer 3: which frame the numbers are read in ---------------------
    Family("spec.world_frame", "spec.world_frame", "specification", 1.0,
           target="box", builder="ops:use_world_coordinates"),
    Family("spec.endpoints", "spec.world_frame.detail", "specification", 0.25,
           target="box", builder="ops:use_wall_span"),
    Family("spec.axis_dimensions", "spec.world_frame.detail", "specification",
           0.25, target="box", builder="ops:use_axis_dimensions"),
    Family("spec.corner", "spec.world_frame.detail", "specification", 0.50,
           target="box"),
    Family("spec.axis_displacement", "spec.displacement", "specification", 0.40),
    Family("spec.compass_displacement", "spec.displacement", "specification",
           0.60),

    # ---- layer 4: what must hold afterwards -------------------------------
    Family("constraint.invariant.keep_placement", "constraint.on_edit",
           "constraint", 1.0, applies="admits_keep_placement"),
    Family("constraint.invariant.keep_z", "constraint.on_edit", "constraint",
           1.0, applies="admits_keep_z"),
    Family("constraint.cascade.relations_preserved", "constraint.on_edit",
           "constraint", 1.0, applies="admits_relations_preserved"),
    Family("constraint.cascade.relations_consistent", "constraint.on_edit",
           "constraint", 1.0, applies="admits_relations_consistent"),
    Family("constraint.relation_on_create.space_boundary",
           "constraint.relation_on_create", "constraint", 1.0,
           builder="ops:_attach_space_boundary"),
    Family("constraint.relation_on_create.connection",
           "constraint.relation_on_create", "constraint", 1.0,
           builder="ops:_attach_connects"),

    # ---- layer 7: how the requirement is worded ---------------------------
    Family("wording.ifc_class_name", "wording.ifc_class", "wording", 1.0),

    # ---- layer 2: the references 0.6.0 adds -------------------------------
    Family("ref.ordinal", "ref.new", "reference", 1.0,
           style="spatial", builder="anchors:ordinal_anchors"),
    Family("ref.negation", "ref.new", "reference", 1.0,
           style="topological", builder="anchors:negation_anchors"),

    # ---- layer 2: the references 0.8.0 adds -------------------------------
    Family("ref.host_of_filling", "ref.new", "reference", 1.2,
           style="topological", builder="anchors:host_anchors"),
    Family("ref.joins_spaces", "ref.new", "reference", 1.2,
           style="topological", builder="anchors:joins_anchors"),
    Family("ref.bounds_space", "ref.new", "reference", 1.2,
           style="topological", builder="anchors:bounds_anchors"),
    Family("ref.under_walls", "ref.new", "reference", 1.0,
           style="spatial", builder="anchors:under_anchors"),
    Family("ref.without_relation", "ref.new", "reference", 1.0,
           style="topological", builder="anchors:without_relation_anchors"),

    # ---- layer 7: a delete instruction that names the relationships -------
    Family("wording.relationship_named", "wording.relationship_named",
           "wording", 1.0),

    # ---- layer 7: how an identifier is written (0.9.0) --------------------
    Family("wording.identifier_spelling", "wording.identifier_spelling",
           "wording", 1.0),
    Family("wording.reference_by_id", "wording.reference_by_id", "wording",
           1.0),
    Family("wording.identifier_list", "wording.identifier_list", "wording",
           1.0),
    Family("scope.id_list", "scope.id_list", "scope", 1.0),

    # ---- layer 1: the operations 0.6.0 adds -------------------------------
    Family("op.update.rotate", "op.update.new", "operation", 1.0),
    Family("op.update.mirror", "op.update.new", "operation", 0.8),
    Family("op.update.pset", "op.update.new", "operation", 1.4),
    Family("op.update.material", "op.update.new", "operation", 1.2),
    Family("op.update.type_object", "op.update.new", "operation", 1.0),
    Family("op.update.restorey", "op.update.new", "operation", 0.8),
    Family("op.update.rehost", "op.update.new", "operation", 0.6),
    Family("op.copy", "op.create.new", "operation", 1.0),
    Family("op.array", "op.create.new", "operation", 0.8),
    Family("op.replace", "op.create.new", "operation", 1.0),

    # ---- layer 5: one edit over a whole set -------------------------------
    Family("scope.batch", "scope.batch", "scope", 1.0),
    Family("ref.set", "scope.batch", "reference", 1.0),
    Family("scope.conditional", "scope.conditional", "scope", 1.0),

    # ---- layer 7: the wording variants 0.7.0 adds -------------------------
    Family("wording.synonym", "wording.synonym", "wording", 1.0),
    Family("wording.request_form", "wording.request_form", "wording", 1.0),
    Family("wording.class_token", "wording.class_token", "wording", 1.0),
    Family("wording.unit_spelling", "wording.unit_spelling", "wording", 1.0),
    Family("wording.underspecified", "wording.underspecified", "wording", 1.0),

    # ---- layer 6: the conditions the model itself carries -----------------
    # These are measurements rather than draws.  A run cannot ask for more
    # millimetre models than the corpus holds, so each family carries a weight
    # of zero and exists so that the registry, the coverage table and the
    # benchmark's reporting axes all name the condition the same way.
    Family("model.units.mm", "model.condition", "model_condition", 0.0),
    Family("model.units.imperial", "model.condition", "model_condition", 0.0),
    Family("model.schema.ifc2x3", "model.condition", "model_condition", 0.0),
    Family("model.schema.ifc4x3", "model.condition", "model_condition", 0.0),
    Family("model.placement.rotated_storey", "model.condition",
           "model_condition", 0.0),
    Family("model.placement.site_offset", "model.condition", "model_condition",
           0.0),
    Family("model.representation.brep", "model.condition", "model_condition",
           0.0),
    Family("model.representation.mapped_item", "model.condition",
           "model_condition", 0.0),
    Family("model.names.non_english", "model.condition", "model_condition",
           0.0),
)


BY_TAG: dict[str, Family] = {family.tag: family for family in FAMILIES}
BY_GROUP: dict[str, tuple[Family, ...]] = {}
for _family in FAMILIES:
    BY_GROUP[_family.group] = BY_GROUP.get(_family.group, ()) + (_family,)


# ---------------------------------------------------- layer 1 and layer 5

# Which operation each edit kind performs, in the taxonomy's own words.  These
# tags name what the earlier versions already generated, so a record carries its
# layer 1 and layer 5 label from 0.5.0 on and the later phases extend the same
# vocabulary rather than replacing it.
OPERATION_TAG = {
    "create_box": "op.create",
    "create_filling": "op.create",
    "create_wall_with_door": "op.create",
    "delete": "op.delete",
    "delete_wall_with_fillings": "op.delete",
    "translate": "op.update.geometry.translate",
    "move_wall_with_fillings": "op.update.geometry.translate",
    "move_space_with_bounding_walls": "op.update.geometry.translate",
    "resize_extrusion": "op.update.geometry.resize",
    "resize_profile": "op.update.geometry.resize",
    "rename": "op.update.attribute.name",
    "retype": "op.update.attribute.type",
    "resize_overall": "op.update.attribute.size",
    # 0.6.0
    "rotate": "op.update.rotate",
    "mirror": "op.update.mirror",
    "set_pset": "op.update.pset",
    "assign_material": "op.update.material",
    "assign_type": "op.update.type_object",
    "move_to_storey": "op.update.restorey",
    "rehost_filling": "op.update.rehost",
    "copy_element": "op.copy",
    "array_elements": "op.array",
    "replace_filling": "op.replace",
}

SCOPE_TAG = {"single": "scope.single", "compositional": "scope.chain"}


def operation_tag(edit_kind: str) -> Optional[str]:
    return OPERATION_TAG.get(edit_kind)


def scope_tag(tier: str) -> Optional[str]:
    return SCOPE_TAG.get(tier)


# --------------------------------------------------------------- the draws


def share(group: str) -> float:
    """How often a group is drawn, with the run's own override applied."""
    from . import settings

    overrides = settings.SETTINGS.family_shares or {}
    if group in overrides:
        return float(overrides[group])
    return float(GROUP_SHARE.get(group, 0.0))


def weight(family: Family) -> float:
    """A family's weight inside its group, with the run's own override applied."""
    from . import settings

    overrides = settings.SETTINGS.family_weights or {}
    return float(overrides.get(family.tag, family.weight))


def draw(group: str, rng) -> bool:
    """Whether this draw asks for the group at all."""
    value = share(group)
    return value > 0 and rng.random() < value


def candidates(group: str, style: str = "", target: str = ""
               ) -> list[Family]:
    """The members of a group that apply here, with a positive weight."""
    out = []
    for family in BY_GROUP.get(group, ()):
        if style and family.style and family.style != style:
            continue
        if target and family.target and family.target != target:
            continue
        if weight(family) <= 0:
            continue
        out.append(family)
    return out


def members(group: str, rng, style: str = "", target: str = ""
            ) -> list[Family]:
    """The members of a group in the order this draw will try them.

    Ordered by a weighted permutation, so a family with twice the weight comes
    out in front twice as often without being the only one ever tried.
    """
    pool = candidates(group, style, target)
    ordered = sorted(((rng.random() ** (1.0 / max(weight(f), 1e-9)), f.tag, f)
                      for f in pool),
                     key=lambda triple: (-triple[0], triple[1]))
    return [family for _key, _tag, family in ordered]


def choose(group: str, rng, style: str = "", target: str = ""
           ) -> Optional[Family]:
    """One member of a group, drawn in proportion to the members' weights."""
    pool = candidates(group, style, target)
    if not pool:
        return None
    total = sum(weight(f) for f in pool)
    if total <= 0:
        return None
    point = rng.random() * total
    for family in sorted(pool, key=lambda f: f.tag):
        point -= weight(family)
        if point <= 0:
            return family
    return pool[-1]


def build(family: Family) -> Optional[Callable[..., Any]]:
    """The function that tries to apply one family, or None when it has none."""
    if not family.builder:
        return None
    module_name, _, function_name = family.builder.partition(":")
    module = importlib.import_module(f".{module_name}", __package__)
    return getattr(module, function_name)


# ------------------------------------------------- which edits admit a clause


def admits_keep_placement(plan) -> bool:
    """True for an edit that leaves the element exactly where it stands."""
    return plan.kind in ("resize_extrusion", "resize_profile", "resize_overall",
                         "rename", "retype")


def admits_keep_z(plan) -> bool:
    """True for a move drawn on a horizontal axis, whose elevation is unchanged."""
    return plan.kind == "translate" and int(plan.params.get("axis", 0)) != 2


def admits_relations_preserved(plan) -> bool:
    """True for an update, which changes no relationship of its target."""
    return plan.operation == "update"


def admits_relations_consistent(plan) -> bool:
    """True for a delete, whose cascade is what the clause describes."""
    return plan.operation == "delete"


def admits(family: Family, plan) -> bool:
    if not family.applies:
        return True
    return bool(globals()[family.applies](plan))


# -------------------------------------------------------------- reporting


def tags_of_layer(layer: str) -> tuple[str, ...]:
    return tuple(f.tag for f in FAMILIES if f.layer == layer)


def layer_of(tag: str) -> str:
    family = BY_TAG.get(tag)
    if family is not None:
        return family.layer
    for prefix, layer in (("op.", "operation"), ("ref.", "reference"),
                          ("spec.", "specification"),
                          ("constraint.", "constraint"), ("scope.", "scope"),
                          ("model.", "model_condition"),
                          ("wording.", "wording")):
        if tag.startswith(prefix):
            return layer
    return "unknown"


def as_dict() -> dict[str, Any]:
    """The registry as a run writes it into its funnel, shares included."""
    return {"group_share": {g: share(g) for g in sorted(GROUP_SHARE)},
            "families": {f.tag: {"group": f.group, "layer": f.layer,
                                 "weight": weight(f)}
                         for f in FAMILIES}}
