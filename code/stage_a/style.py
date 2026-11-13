"""Seeded surface variation for a synthesized trajectory.

A backbone built from one template teaches the template. Every synthesized
trajectory therefore draws its identifier names, its comment wording, its quote
character, the phrasing of what an inspection round prints and the wording of
the closing message from small pools, seeded by the task's own generator seed so
the choice is reproducible and the same task always looks the same.

Nothing here changes what the code does. The variation is over names and text
only, which is why a trajectory can be re-derived from its task id and still
match the trajectory that was scored.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

#: Identifier pools. Each name is ordinary Python that reads naturally in the
#: position it is used, so no variant looks like generated filler.
NAME_POOLS: dict[str, tuple[str, ...]] = {
    "scale": ("scale", "unit_scale", "to_model"),
    "product": ("product", "element", "target"),
    "storey": ("storey", "level", "floor"),
    "history": ("history", "owner", "owner_history"),
    "context": ("context", "body_context", "geom_context"),
    "shape_fn": ("box_shape", "make_box", "build_box"),
    "place_fn": ("local_placement", "place_at", "make_placement"),
    "contain_fn": ("contain_in_storey", "add_to_storey", "put_in_storey"),
    "aggregate_fn": ("aggregate_into_storey", "nest_in_storey", "add_under_storey"),
    "context_fn": ("body_context_of", "context_for", "pick_context"),
    "sole_owner_fn": ("is_sole_owner", "only_user", "used_once"),
    "extrusion_fn": ("sole_extrusion", "single_extrusion", "body_extrusion"),
    "body_fn": ("body_of", "body_representation", "find_body"),
    "storey_fn": ("containing_storey", "storey_of", "host_storey"),
    "move_fn": ("move_element", "translate_element", "shift"),
    "matrix": ("matrix", "placement_matrix", "world"),
    "rotation": ("rotation", "basis", "parent_rotation"),
    "offset": ("offset", "delta", "shift_vector"),
    "point": ("point", "origin", "location"),
    "axis": ("axis", "axis_placement", "relative"),
    "solid": ("solid", "extrusion", "swept"),
    "profile": ("profile", "section", "swept_area"),
    "created": ("created", "new_element", "added"),
    "opening": ("opening", "void", "hole"),
    "filling": ("filling", "leaf", "unit"),
    "relation": ("relation", "rel", "link"),
    "matches": ("matches", "found", "hits"),
    "candidates": ("candidates", "pool", "options"),
    # The geometry library's results. The wall's measurements, the corner a
    # placement rule returns and the reference the rule is measured from each
    # get a name of their own, so two of them never collide in one snippet.
    "wall_box": ("wall", "wall_box", "host_box"),
    "slot": ("slot", "old_slot", "opening_slot"),
    "corner": ("corner", "base_corner", "lowest_corner"),
    "footprint": ("footprint", "plan_size", "base_size"),
    "reference": ("reference", "neighbour", "anchor_element"),
    "room": ("room", "enclosing_space", "space_around"),
}

#: Comment wording. The key is what the comment is about, not where it goes.
COMMENT_POOLS: dict[str, tuple[str, ...]] = {
    "units": (
        "lengths in the instruction are metres; the model may use other units",
        "convert metres to the model's own length unit",
        "the file's length unit decides what a metre is worth here",
    ),
    "move": (
        "move the element by a world-axis offset",
        "shift the element, keeping whatever is placed relative to it",
        "apply the offset in the coordinate system the placement is written in",
    ),
    "copy_on_write": (
        "the placement may share its point with others, so give it its own",
        "do not move anything else that happens to share this point",
        "substitute a private point before writing coordinates",
    ),
    "delete": (
        "remove the element and the relationships that depend on it",
        "drop the element together with its placement, geometry and relations",
        "delete the element, its openings and whatever those openings hold",
        "remove the element; a door or a window it holds cannot stay without it",
    ),
    "create": (
        "create the element and place it in the storey",
        "build the new element and hang it under the storey",
        "add the element, placed relative to the storey",
    ),
    "filling": (
        "cut the opening and fill it",
        "void the host and put the filling in the void",
        "add the opening in the host wall, then the filling that occupies it",
    ),
    "attribute": (
        "write the attribute the instruction names",
        "set the attribute on the target",
        "update the attribute",
    ),
    "geometry": (
        "resize the extruded body",
        "change the extrusion so the element takes its new size",
        "edit the swept solid that gives the element its shape",
    ),
    "context": (
        "reuse the representation context an existing body is written in",
        "created geometry goes into the same context as the model's own",
        "find the context to write the new geometry into",
    ),
    "measure": (
        "measure the wall before placing anything in it",
        "read the wall's own size, so the leaf is not guessed",
        "the wall's length, thickness and height decide where the leaf goes",
    ),
    "place": (
        "compute the corner the instruction describes",
        "work the position out from the element the instruction refers to",
        "the position is measured off the reference, not assumed",
    ),
    "library": (
        "geom cuts the opening, places the leaf and writes the relations",
        "geom does the placement and the relationships",
        "the geometry helper does the placement arithmetic",
    ),
    "material": (
        "give the element the material the instruction names",
        "associate the element with that material, replacing the one it had",
        "the element carries one material, so the old association goes first",
    ),
    "type": (
        "put the element under the type object the instruction names",
        "type the element, replacing the type it had",
        "the element is typed once, so the type it had goes first",
    ),
    "absence": (
        "the phrase names the element by what it does not carry",
        "find the one element of that class carrying none of what is excluded",
        "look for the element the excluded class is absent from",
    ),
    "rehost": (
        "move the element, with its opening, into the wall the instruction names",
        "re-host the element in the named wall and heal the one it leaves",
        "the opening travels with the element into the other wall",
    ),
    "turn": (
        "turn the element about the point the instruction names",
        "rotate the element about the vertical axis through that point",
        "the turn is about the point the instruction gives, not the world origin",
    ),
    "property": (
        "write the value into the property set the instruction names",
        "set the property the instruction names, creating the set if it is absent",
        "the value goes into the named property set on this element",
    ),
    "commit": (
        "persist the edited model",
        "write the model back to disk",
        "save the edit",
    ),
    "check": (
        "confirm the edit landed before saving",
        "read the result back before persisting it",
        "verify, then save",
    ),
}

#: Closing messages. ``{what}`` is filled with a short description of the edit.
CLOSING_TEMPLATES: tuple[str, ...] = (
    "Done. {what}, and the model has been saved.",
    "{what}. The edited model is committed.",
    "Finished: {what}. The file on disk now holds the change.",
    "{what}, and the edit is written to the working file.",
    "Completed. {what}; the model was committed.",
)

#: How an inspection round reports what it found.
REPORT_STYLES: tuple[str, ...] = ("print", "result", "print_rows")


@dataclass
class Style:
    """One trajectory's surface choices."""

    seed: int
    rng: random.Random = field(repr=False, default=None)
    quote: str = "'"
    report: str = "print"
    comments: bool = True
    #: Whether a create-type edit is written as calls into the sandbox's
    #: geometry helper (``geom``) rather than as a hand-written helper block.
    #: The surface variation above still applies; the library's own call
    #: signatures do not vary.
    geom_lib: bool = False
    _names: dict = field(default_factory=dict, repr=False)
    _comments: dict = field(default_factory=dict, repr=False)

    @classmethod
    def for_seed(cls, seed: int, geom_lib: bool = False) -> "Style":
        rng = random.Random(seed)
        style = cls(seed=seed, rng=rng, geom_lib=geom_lib)
        style.quote = rng.choice(("'", '"'))
        style.report = rng.choice(REPORT_STYLES)
        style.comments = rng.random() < 0.75
        style._names = {key: rng.choice(pool) for key, pool in NAME_POOLS.items()}
        style._comments = {key: rng.choice(pool) for key, pool in COMMENT_POOLS.items()}
        return style

    # -- naming ---------------------------------------------------------
    def name(self, key: str) -> str:
        return self._names.get(key, key)

    def comment(self, key: str, indent: str = "") -> str:
        """A comment line for ``key``, or an empty string when comments are off."""
        if not self.comments:
            return ""
        text = self._comments.get(key)
        return f"{indent}# {text}\n" if text else ""

    # -- literals -------------------------------------------------------
    def string(self, value: str) -> str:
        """A string literal in this trajectory's quote character."""
        if value is None:
            return "None"
        quote = self.quote
        if quote in value:
            quote = '"' if quote == "'" else "'"
        if quote in value:
            return repr(value)
        escaped = value.replace("\\", "\\\\")
        return f"{quote}{escaped}{quote}"

    def choice(self, options):
        return self.rng.choice(list(options))

    def chance(self, probability: float) -> bool:
        return self.rng.random() < probability

    def closing(self, what: str) -> str:
        text = self.rng.choice(CLOSING_TEMPLATES).format(what=what)
        # ``what`` is a clause, so it lands mid-sentence in some templates and at
        # a sentence start in others; capitalise where a sentence actually begins.
        return re.sub(r"(?:^|(?<=\. ))([a-z])", lambda m: m.group(1).upper(), text, count=0)
