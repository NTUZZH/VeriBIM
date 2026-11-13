"""Instruction rendering, layer 1: the template core.

Every instruction is written from the edit's own parameters and from an anchor
that has already been checked to single out one element, so instruction, gold
model and gold script cannot disagree.  The wording stays in the register of a
work order: what to change, to what value, and where the element is.

Directions are the model's own axes.  Saying "north (+Y)" once in the sentence
that uses a direction keeps the phrase readable and leaves no doubt about which
way the element moves, whatever the model's orientation on the ground.
"""

from __future__ import annotations

import contextvars
import dataclasses
from typing import Any, Optional

from .anchors import Anchor, reference_phrase
from .ops import EditPlan
from .scene import Scene
from .wording import PLAIN, Dialect

ARTICLE = {"wall": "wall", "slab": "slab", "space": "space", "door": "door",
           "window": "window", "column": "column"}

#: The unit the instruction being rendered states its lengths in.  Layer 7 lets
#: one requirement be written in metres, millimetres or centimetres, and the
#: length has to carry that choice wherever a template writes one, so the choice
#: travels beside the render call rather than through every signature.  A render
#: sets it and puts it back, so a template called outside one renders in metres
#: exactly as every earlier version did.
_DIALECT: contextvars.ContextVar = contextvars.ContextVar("dialect",
                                                          default=PLAIN)


def dialect() -> Dialect:
    return _DIALECT.get()


def metres(value: float) -> str:
    """A length written the way the instruction quotes it."""
    return dialect().length(value)


def point(x: float, y: float, z: float) -> str:
    """A position written as a coordinate triple with its unit."""
    current = dialect()
    return (f"({current.coordinate(x)}, {current.coordinate(y)}, "
            f"{current.coordinate(z)}) {current.word}")


def _frame_words(params: dict) -> str:
    """What frame a world coordinate is read in, said only where it matters.

    A storey whose own axes follow the world axes needs nothing said, and the
    earlier waves left the frame unstated there.  A storey drawn on a skewed
    grid does need it said, because the element is built along the storey's own
    axes and a reader given a bare point would set it out along the world ones.
    """
    turn = params.get("storey_rotation_deg")
    if not turn:
        return ""
    return (f" in world coordinates, set out along that storey's own axes, "
            f"which run {float(turn):.0f} degrees counter-clockwise from the "
            f"world axes")


def _about(value: float) -> str:
    exact = abs(float(value) - round(float(value), 2)) < 1e-9
    return metres(value) if exact else f"about {metres(value)}"


def _capitalise(text: str) -> str:
    return text[0].upper() + text[1:] if text else text


# ------------------------------------------------------------ update family


def _update_sentence(plan: EditPlan, target: str) -> str:
    kind = plan.kind
    params = plan.params
    if kind == "translate":
        if params.get("direction_form") == "axis":
            return (f"Move {target} by {metres(params['distance'])} in the "
                    f"{params['axis_word'].lower()} direction.")
        return (f"Move {target} {metres(params['distance'])} to the "
                f"{params['direction']} ({params['axis_word']}).")
    if kind in ("resize_extrusion", "resize_profile", "resize_overall"):
        return (f"Change the {params['dimension']} of {target} from "
                f"{_about(params['old'])} to {metres(params['new'])}.")
    if kind == "rename":
        return f"Rename {target} to '{params['new']}'."
    if kind == "retype":
        return (f"Set the predefined type of {target} to {params['new']}.")
    sentence = _update_sentence_v06(plan, target)
    if sentence is not None:
        return sentence
    raise ValueError(f"no update template for {kind}")


def _value_words(value: Any, value_type: str) -> str:
    """A property value as an instruction quotes it."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value_type == "IfcThermalTransmittanceMeasure":
        return f"{float(value):.2f} W/m2K"
    if isinstance(value, float):
        return f"{float(value):.2f}"
    return f"'{value}'"


def _update_sentence_v06(plan: EditPlan, target: str) -> Optional[str]:
    """The instruction for one of the operations 0.6.0 adds."""
    kind = plan.kind
    params = plan.params
    if kind == "rotate":
        pivot = ("its own placement origin" if params["pivot"] == "origin"
                 else "the centre of its plan")
        return (f"Rotate {target} by {params['degrees']:.0f} degrees "
                f"counter-clockwise about the vertical axis, turning it about "
                f"{pivot}.")
    if kind == "mirror":
        if params.get("plane_kind") == "wall_axis":
            return (f"Mirror {target} across the vertical plane that follows "
                    f"the axis of the wall named '{params['plane_wall']}'.")
        return (f"Mirror {target} across the vertical plane at "
                f"{params['plane_axis']} = {metres(params['plane_value'])}.")
    if kind == "set_pset":
        value = _value_words(params["value"], params["value_type"])
        if params.get("old") is None:
            return (f"Set the {params['property_word']} of {target} in "
                    f"{params['pset']} to {value}.")
        old = _value_words(params["old"], params["value_type"])
        return (f"Change the {params['property_word']} of {target} in "
                f"{params['pset']} from {old} to {value}.")
    if kind == "assign_material":
        if params.get("old"):
            return (f"Change the material of {target} to "
                    f"'{params['material']}'.")
        return f"Assign the material '{params['material']}' to {target}."
    if kind == "assign_type":
        return (f"Assign {target} to the type object named "
                f"'{params['type_name']}'.")
    if kind == "move_to_storey":
        if params.get("keep_world"):
            return (f"Move {target} into {params['storey_to']}, leaving it "
                    f"exactly where it stands in the building.")
        shift = abs(float(params.get("elevation_shift") or 0.0))
        way = "rises" if float(params.get("elevation_shift") or 0.0) > 0 else "drops"
        return (f"Move {target} into {params['storey_to']}, keeping the "
                f"position it has inside its storey, so it {way} by "
                f"{metres(shift)}.")
    if kind == "rehost_filling":
        return (f"Move {target} into the wall named '{params['host_to']}', "
                f"{metres(params['along'])} along that wall from its start "
                f"point, carrying the opening it fills with it and leaving the "
                f"wall it came from whole.")
    return None


#: The four shapes a delete instruction takes when it lists the relationships
#: it wants removed.  Each names the element first and the relationships after
#: it, which is the order a work order is written in.
_NAMED_RELATION_FORMS = (
    "Delete {target} from the model, and delete with it {clauses}.",
    "Remove {target} together with {clauses}.",
    "Delete {target}. Remove {clauses} as well.",
    "Take {target} out of the model, and take {clauses} with it.",
)


def _named_relation_sentence(plan: EditPlan, target: str) -> str:
    """A delete instruction that names the relationships it wants removed.

    The relationships listed are ones the element takes part in, so removing
    the element removes them; nothing else leaves the model, and in particular
    the element on the far side of a connection and the storey an assignment
    points at both stay.
    """
    clauses = [entry["text"] for entry in plan.params["named_relations"]]
    form = _NAMED_RELATION_FORMS[int(plan.params.get("named_relations_form", 0))
                                 % len(_NAMED_RELATION_FORMS)]
    return form.format(target=target, clauses=_join(clauses))


def _delete_sentence(plan: EditPlan, target: str) -> str:
    if plan.params.get("named_relations"):
        return _named_relation_sentence(plan, target)
    if plan.params.get("scope") == "batch":
        return (f"Delete {target} from the model, together with the "
                f"relationships that depend on them.")
    return (f"Delete {target} from the model, together with the relationships "
            f"that depend on it.")


def _batch_sentence(plan: EditPlan, target: str) -> str:
    """The instruction for one edit written over every member of a set."""
    kind = plan.kind
    params = plan.params
    if kind == "set_pset":
        value = _value_words(params["value"], params["value_type"])
        return (f"Set the {params['property_word']} of {target} in "
                f"{params['pset']} to {value}.")
    if kind == "assign_material":
        return f"Assign the material '{params['material']}' to {target}."
    if kind == "retype":
        return f"Set the predefined type of {target} to {params['new']}."
    if kind == "resize_extrusion":
        return (f"Change the {params['dimension']} of {target} to "
                f"{metres(params['new'])}.")
    raise ValueError(f"no batch template for {kind}")


def _with_constraint(sentence: str, plan: EditPlan) -> str:
    """Append the invariance clause the edit already satisfies, if any."""
    name = plan.params.get("constraint")
    if not name:
        return sentence
    clause = CONSTRAINT_CLAUSES.get(name)
    if not clause:
        return sentence
    stem = sentence.rstrip()
    if stem.endswith("."):
        stem = stem[:-1]
    return f"{stem}, {clause}."


#: What each invariance clause says in the instruction.  The clause states
#: something the gold edit already does, so it binds the reader rather than the
#: generator.
CONSTRAINT_CLAUSES = {
    "constraint.invariant.keep_placement": "keeping its placement fixed",
    "constraint.invariant.keep_z": "keeping its z value fixed",
    "constraint.cascade.relations_preserved":
        "preserving all of its relationships",
    "constraint.cascade.relations_consistent":
        "and make sure the other relationships stay consistent",
}


# ------------------------------------------------------------ create family


def _storey_phrase(plan: EditPlan) -> str:
    """How the instruction names the storey a created element goes on.

    The phrase is chosen by the generator, one per instruction style, and
    carried in the edit's parameters so the template does not have to guess.
    """
    return plan.params["where"]


def _size_phrase(family: str, params: dict) -> str:
    """How the instruction states a created element's size.

    A wall is long, thick and high; a slab is measured in plan and by
    thickness; a column is a square section of a given height.  Using the word
    the trade uses keeps the order readable without changing what it means.
    """
    length = metres(params["length"])
    width = metres(params["width"])
    height = metres(params["height"])
    if family == "wall":
        return f"{length} long, {width} thick and {height} high"
    if family == "slab":
        return f"{length} by {width} in plan and {height} thick"
    if family == "column":
        return f"{length} by {width} in section and {height} high"
    return f"{length} long, {width} wide and {height} high"


def _axis_size_phrase(family: str, params: dict) -> str:
    """A size stated by the world axis each dimension runs along.

    Used with the world-frame coordinate form, where the axes the numbers refer
    to are the world axes and naming them removes the last piece of guesswork.
    """
    return (f"a length in the x-direction of {metres(params['length'])}, "
            f"a width in the y-direction of {metres(params['width'])} and "
            f"a height of {metres(params['height'])}")


#: How a derived placement states the size the reader still has to be told.
#: Everything else about the size follows from the elements the position is
#: read off, and is not quoted.
def _derived_size_phrase(kind: str, family: str, params: dict) -> str:
    if kind == "fits_gap":
        # The length is the gap and is not quoted; the thickness is the one
        # the two walls leave between them, whichever plan axis that is on.
        placement = params.get("placement") or {}
        thickness = placement.get("thickness", params["width"])
        return (f"{metres(thickness)} thick and "
                f"{metres(params['height'])} high")
    if kind == "on_top_of":
        return f"{metres(params['height'])} high"
    if kind == "touching_slab_above":
        return (f"{metres(params['length'])} by {metres(params['width'])} "
                f"in section")
    # The remaining kind quotes all three sizes.  They are extents along the
    # world axes rather than along the element's own, so the axes are named
    # instead of being called length, thickness and height.
    return _axis_size_phrase(family, params)


def _derived_placement_phrase(placement: dict) -> str:
    """Where a created element goes, said in terms of the elements around it."""
    kind = placement["kind"]
    if kind == "fits_gap":
        return (f"so that it fits the gap between the "
                f"{ARTICLE[placement['a_family']]} named "
                f"'{placement['a_name']}' and the "
                f"{ARTICLE[placement['b_family']]} named "
                f"'{placement['b_name']}', closing that gap exactly")
    if kind == "on_top_of":
        return (f"so that it sits directly on top of the "
                f"{ARTICLE[placement['a_family']]} named "
                f"'{placement['a_name']}', over the same footprint")
    if kind == "adjacent_to_space":
        return (f"inside the {placement['space_label']}, standing against the "
                f"wall named '{placement['a_name']}' and touching it")
    if kind == "touching_slab_above":
        return (f"so that it rises from the floor level of that storey and its "
                f"top face touches the underside of the slab named "
                f"'{placement['a_name']}'")
    raise ValueError(f"no placement phrase for {kind}")


def _relation_clause(plan: EditPlan, use_class_name: bool) -> str:
    """What the new element has to be related to, and how."""
    relation = plan.params.get("relation")
    if not relation:
        return ""
    names = [n for n in relation["names"] if n]
    if not names:
        return ""
    family = relation["partner_family"]
    if family == "space":
        listed = _join([f"the {name}" for name in names])
    else:
        listed = _join([f"the {ARTICLE[family]} named '{name}'"
                        for name in names])
    if use_class_name:
        return (f" Add an {relation['ifc_class']} between it and {listed}.")
    if relation["kind"] == "bounds":
        return f" It bounds {listed}."
    if relation["kind"] == "bounded_by":
        verb = "bounds" if len(names) == 1 else "bound"
        return f" {_capitalise(listed)} {verb} it."
    if len(names) == 1:
        return f" Establish a connection to {listed}."
    return f" Connect it to {listed}."


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " and " + items[-1]


def _create_box_sentence(scene: Scene, plan: EditPlan, anchor: Anchor,
                         category: str) -> str:
    params = plan.params
    family = plan.family
    where = _storey_phrase(plan)
    placement = params.get("placement")
    span = params.get("span")

    if span is not None:
        start, end = span["start"], span["end"]
        head = (f"Add a new {ARTICLE[family]} named '{params['name']}' on "
                f"{where}, running from {point(start[0], start[1], start[2])} "
                f"to {point(end[0], end[1], end[2])} "
                f"with a thickness of "
                f"{metres(span['thickness'])} in the "
                f"{span['thickness_direction']} direction and a height of "
                f"{metres(span['height'])}")
    elif placement is not None:
        size = _derived_size_phrase(placement["kind"], family, params)
        head = (f"Add a new {ARTICLE[family]} named '{params['name']}' on "
                f"{where}, {size}, "
                f"{_derived_placement_phrase(placement)}")
    else:
        size = (_axis_size_phrase(family, params)
                if params.get("size_form") == "axis"
                else _size_phrase(family, params))
        head = (f"Add a new {ARTICLE[family]} named '{params['name']}' on "
                f"{where}, {size}")
        if category == "spatial" and params.get("offset"):
            offset = params["offset"]
            head += (f". Set its base corner {metres(offset['dx'])} to the "
                     f"{offset['x_word']} ({offset['x_axis']}) and "
                     f"{metres(offset['dy'])} to the {offset['y_word']} "
                     f"({offset['y_axis']}) of {anchor.phrase}")
        elif params.get("frame") == "world":
            head += (f", with its lowest corner at "
                     f"{point(params['x'], params['y'], params['z'])}"
                     f"{_frame_words(params)}")
        else:
            head += (f", with its base corner at "
                     f"{point(params['x'], params['y'], params['z'])} in that "
                     f"storey's own coordinates")
    if params.get("predefined_type"):
        head += f". Give it the predefined type {params['predefined_type']}"
    return head + "." + _relation_clause(plan, bool(params.get("relation_by_class")))


def _create_filling_sentence(scene: Scene, plan: EditPlan, anchor: Anchor,
                             category: str) -> str:
    params = plan.params
    family = plan.family
    sill = float(params["sill"])
    height = (f"with its sill {metres(sill)} above the wall's base"
              if sill > 0 else "standing on the wall's base")
    placement = params.get("placement")
    if placement is not None and placement["kind"] == "centred_on_wall":
        where = (f"with the middle of the leaf "
                 f"{metres(placement['centre_from_start'])} along the wall "
                 f"from its start")
    elif placement is not None and placement["kind"] == "above_below_filling":
        other = "below" if placement["direction"] == "above" else "above"
        where = (f"directly {placement['direction']} the "
                 f"{ARTICLE[placement['a_family']]} named "
                 f"'{placement['a_name']}' on the storey {other}")
    else:
        where = (f"{metres(params['along'])} along the wall from its start "
                 f"point")
    return (f"Add a new {ARTICLE[family]} named '{params['name']}' in "
            f"{anchor.phrase}, {metres(params['width'])} wide and "
            f"{metres(params['height'])} high, {where} and {height}. Cut the "
            f"opening it fills." + _relation_clause(
                plan, bool(params.get("relation_by_class"))))


# ------------------------------------------------------- compositional tier


def _hosted_phrase(fillings: list) -> str:
    """How many doors and windows a wall hosts, in words."""
    kinds = sorted({f["family"] for f in fillings})
    if len(fillings) == 1:
        return f"the {kinds[0]}"
    what = " and ".join(f"{k}s" for k in kinds)
    return f"the {len(fillings)} {what}"


def _chain_sentence(scene: Scene, plan: EditPlan, anchor: Anchor,
                    category: str) -> str:
    params = plan.params
    kind = plan.kind
    if kind == "move_wall_with_fillings":
        single = len(params["fillings"]) == 1
        return (f"Move {anchor.phrase} {metres(params['distance'])} to the "
                f"{params['direction']} ({params['axis_word']}), and move "
                f"{_hosted_phrase(params['fillings'])} it hosts by the same "
                f"offset so {'it stays' if single else 'they stay'} in the "
                f"wall.")
    if kind == "delete_wall_with_fillings":
        single = len(params["fillings"]) == 1
        return (f"Remove {_hosted_phrase(params['fillings'])} hosted in "
                f"{anchor.phrase}, then remove the wall itself along with the "
                f"{'opening it filled' if single else 'openings they filled'}.")
    if kind == "move_space_with_bounding_walls":
        return (f"Move {anchor.phrase} {metres(params['distance'])} to the "
                f"{params['direction']} ({params['axis_word']}), and move the "
                f"{params['n_walls']} walls that bound it by the same offset.")
    if kind == "create_wall_with_door":
        where = _storey_phrase(plan)
        return (f"Add a new wall named '{params['wall_name']}' on {where}, "
                f"{metres(params['length'])} long, "
                f"{metres(params['thickness'])} thick and "
                f"{metres(params['height'])} high, with its base corner at "
                f"{point(params['x'], params['y'], 0.0)} in that "
                f"storey's own coordinates. Then put a door named "
                f"'{params['door_name']}' in that new wall, "
                f"{metres(params['door_width'])} wide and "
                f"{metres(params['door_height'])} high, "
                f"{metres(params['along'])} along the wall from its start "
                f"point, and cut the opening it fills.")
    raise ValueError(f"no chain template for {kind}")


# ------------------------------------------------------------------ facade


def _copy_sentence(plan: EditPlan, anchor: Anchor) -> str:
    params = plan.params
    return (f"Copy {anchor.phrase} {metres(params['distance'])} to the "
            f"{params['direction']} ({params['axis_word']}), and name the copy "
            f"'{params['name']}'.")


def _array_sentence(plan: EditPlan, anchor: Anchor) -> str:
    params = plan.params
    names = _join([f"'{n}'" for n in params["names"]])
    return (f"Make {params['count']} copies of {anchor.phrase} at a spacing of "
            f"{metres(params['spacing'])} to the {params['direction']} "
            f"({params['axis_word']}), named {names} in that order.")


def _replace_sentence(plan: EditPlan, anchor: Anchor) -> str:
    params = plan.params
    family = plan.family
    sill = float(params["sill"])
    height = (f"with its sill {metres(sill)} above the wall's base"
              if sill > 0 else "standing on the wall's base")
    return (f"Replace {anchor.phrase} with a {ARTICLE[family]} named "
            f"'{params['name']}', {metres(params['width'])} wide and "
            f"{metres(params['height'])} high, at the same position along the "
            f"wall and {height}. Cut the opening it fills and take the old "
            f"opening out with the element it held.")


def render(scene: Scene, plan: EditPlan, anchor: Anchor, category: str) -> str:
    """The instruction for one planned edit."""
    if plan.kind in ("move_wall_with_fillings", "delete_wall_with_fillings",
                     "move_space_with_bounding_walls", "create_wall_with_door"):
        return _chain_sentence(scene, plan, anchor, category)
    if plan.kind == "copy_element":
        return _copy_sentence(plan, anchor)
    if plan.kind == "array_elements":
        return _array_sentence(plan, anchor)
    if plan.kind == "replace_filling":
        return _replace_sentence(plan, anchor)
    if plan.params.get("scope") == "batch" and plan.operation == "update":
        return _batch_sentence(plan, anchor.phrase)
    if plan.operation == "update":
        return _with_constraint(_update_sentence(plan, anchor.phrase), plan)
    if plan.operation == "delete":
        return _with_constraint(_delete_sentence(plan, anchor.phrase), plan)
    if plan.kind == "create_box":
        return _create_box_sentence(scene, plan, anchor, category)
    if plan.kind == "create_filling":
        return _create_filling_sentence(scene, plan, anchor, category)
    raise ValueError(f"no template for {plan.kind}")


def render_in(dialect_choice, scene: Scene, plan: EditPlan, anchor: Anchor,
              category: str) -> str:
    """Render one instruction with its lengths stated in a chosen unit."""
    token = _DIALECT.set(dialect_choice)
    try:
        return render(scene, plan, anchor, category)
    finally:
        _DIALECT.reset(token)


# ------------------------------------------------- the under-specified forms

#: A reference that names the family and nothing else, which is what an
#: instruction reads like when the writer forgot to say which element.
def _bare_phrase(family: str) -> str:
    return f"the {ARTICLE[family]}"


def _drop_value(sentence: str, value: str) -> Optional[str]:
    """The same sentence with one quoted value taken out of it."""
    if value not in sentence:
        return None
    return sentence.replace(value, "", 1)


def underspecified(scene: Scene, plan: EditPlan, anchor: Anchor,
                   category: str, slot: str) -> Optional[str]:
    """One instruction with a value the edit needs left out of it.

    Each form is written rather than cut out of a finished sentence, so the
    result is a sentence a person could have written and the value that is
    missing is exactly the one the record names.  A combination this function
    cannot write returns ``None`` and the draw keeps the complete instruction.
    """
    params = plan.params
    kind = plan.kind
    if slot == "element":
        # Which element is left out: the instruction names the family and the
        # change, and the reader cannot tell which of them is meant.
        if plan.operation not in ("update", "delete") or \
                params.get("scope") == "batch":
            return None
        bare = Anchor(kind=anchor.kind, family=plan.family,
                      phrase=_bare_phrase(plan.family), params={})
        if plan.operation == "delete":
            # The relationships a delete names (the host wall, the rooms, the
            # storey) would tell the reader which element is meant, so the
            # sentence that leaves the element out leaves them out too.
            plain = dataclasses.replace(plan, params={
                key: value for key, value in plan.params.items()
                if key not in ("named_relations", "named_relations_form")})
            return _delete_sentence(plain, bare.phrase)
        try:
            return _update_sentence(plan, bare.phrase)
        except ValueError:
            return None
    if slot == "dimension":
        if kind == "translate":
            return (f"Move {anchor.phrase} to the {params['direction']} "
                    f"({params['axis_word']}).")
        if kind in ("resize_extrusion", "resize_profile", "resize_overall"):
            return f"Change the {params['dimension']} of {anchor.phrase}."
        if kind == "rotate":
            return (f"Rotate {anchor.phrase} counter-clockwise about the "
                    f"vertical axis.")
        if kind == "rename":
            return f"Rename {anchor.phrase}."
        return None
    if slot == "storey":
        if kind != "create_box" or params.get("placement") or \
                params.get("offset") or params.get("span") or \
                params.get("frame") == "world":
            return None
        size = _size_phrase(plan.family, params)
        return (f"Add a new {ARTICLE[plan.family]} named '{params['name']}', "
                f"{size}, with its base corner at "
                f"{point(params['x'], params['y'], params['z'])} in the "
                f"storey's own coordinates.")
    return None


def underspecified_in(dialect_choice, scene: Scene, plan: EditPlan,
                      anchor: Anchor, category: str,
                      slot: str) -> Optional[str]:
    """Render one under-specified instruction in a chosen unit."""
    token = _DIALECT.set(dialect_choice)
    try:
        return underspecified(scene, plan, anchor, category, slot)
    finally:
        _DIALECT.reset(token)


def describe(plan: EditPlan) -> str:
    """A two-line note on what the edit did, for the hand-inspection pack."""
    params = plan.params
    kind = plan.kind
    if kind == "translate":
        return (f"Shifted one {plan.family} by {metres(params['distance'])} "
                f"{params['direction']} ({params['axis_word']}); no other "
                f"entity changed.")
    if kind in ("resize_extrusion", "resize_profile"):
        return (f"Rewrote the {plan.family}'s extruded body so its "
                f"{params['dimension']} went from {metres(params['old'])} to "
                f"{metres(params['new'])}.")
    if kind == "resize_overall":
        return (f"Wrote the {plan.family}'s {params['dimension']} attribute "
                f"from {metres(params['old'])} to {metres(params['new'])}; the "
                f"shape representation is unchanged.")
    if kind == "rename":
        return (f"Wrote the {plan.family}'s Name from "
                f"{params['old'] or 'an empty name'} to '{params['new']}'.")
    if kind == "retype":
        return (f"Wrote the {plan.family}'s PredefinedType from "
                f"{params['old']} to {params['new']}.")
    if kind == "delete":
        return (f"Removed one {plan.family} and every relationship that "
                f"referred to it.")
    if kind == "create_box":
        return (f"Added one {plan.family} of "
                f"{metres(params['length'])} x {metres(params['width'])} x "
                f"{metres(params['height'])} and put it in the named storey.")
    if kind == "create_filling":
        return (f"Added one {plan.family} plus its opening, and linked both to "
                f"the host wall through the voids and fills relationships.")
    if kind == "move_wall_with_fillings":
        n = len(params["fillings"])
        return (f"Shifted a wall and the {n} element{'s' if n > 1 else ''} it "
                f"hosts by {metres(params['distance'])} {params['direction']}, "
                f"keeping them in the wall.")
    if kind == "delete_wall_with_fillings":
        n = len(params["fillings"])
        return (f"Removed {n} hosted element{'s' if n > 1 else ''} and then the "
                f"wall, taking {'their openings' if n > 1 else 'its opening'} "
                f"with them.")
    if kind == "move_space_with_bounding_walls":
        return (f"Shifted a space and the {params['n_walls']} walls that bound "
                f"it by {metres(params['distance'])} {params['direction']}.")
    if kind == "create_wall_with_door":
        return (f"Added a wall on the named storey and a door hosted in that "
                f"same new wall, with the opening between them.")
    if kind == "rotate":
        return (f"Turned one {plan.family} through {params['degrees']:.0f} "
                f"degrees about the vertical axis.")
    if kind == "mirror":
        return (f"Reflected one {plan.family} across a vertical plane, "
                f"flipping its own profile so the body is the mirror image.")
    if kind == "set_pset":
        return (f"Wrote {params['property']} in {params['pset']} on "
                f"{params.get('n_members', 1)} {plan.family}(s).")
    if kind == "assign_material":
        return (f"Associated {params.get('n_members', 1)} {plan.family}(s) "
                f"with the material '{params['material']}'.")
    if kind == "assign_type":
        return (f"Assigned one {plan.family} to the type object "
                f"'{params['type_name']}'.")
    if kind == "move_to_storey":
        return (f"Moved one {plan.family} into {params['storey_to']}, "
                f"{'keeping' if params.get('keep_world') else 'shifting'} its "
                f"world position.")
    if kind == "rehost_filling":
        return (f"Moved one {plan.family} and its opening into the wall named "
                f"'{params['host_to']}'.")
    if kind == "copy_element":
        return (f"Duplicated one {plan.family} {metres(params['distance'])} "
                f"{params['direction']}.")
    if kind == "array_elements":
        return (f"Wrote {params['count']} copies of one {plan.family} at "
                f"{metres(params['spacing'])} spacing.")
    if kind == "replace_filling":
        return (f"Took one {params['replaced_family']} and its opening out and "
                f"put a {plan.family} in the same wall.")
    return f"Applied a {kind} edit to one {plan.family}."
