"""Generator settings a wave can change, without changing what an earlier wave did.

The first wave of VeriBIM-Tasks was generated with the defaults below.  The
difficulty audit against BIM-Edit then identified three settings worth moving,
and a second wave is generated with them changed.  Keeping them here, rather
than as constants inside the operation library, means a wave is described by the
values it ran with and an earlier wave stays reproducible.

The settings are process-global because a worker generates one shard at a time
and the planners are called deep inside a draw.  Each worker sets them once,
from the values the driver passes it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class GeneratorSettings:
    """What one wave draws differently."""

    # The tag written into every record, so a mixed set stays auditable.
    wave: str = "v1"

    # Draw a move from the element's own size rather than from a fixed ladder
    # capped at a fraction of the storey.  The audit measured the difference: a
    # move shorter than the element's own extent along the axis it moves leaves
    # the element overlapping where it was, so the unedited model still matches
    # it and a system earns most of the score for doing nothing.
    translate_relative: bool = False
    translate_extent_range: tuple[float, float] = (1.0, 4.0)

    # How often an attribute-only edit is drawn, relative to the other update
    # kinds.  Renaming, retyping and setting a door's overall size are invisible
    # to two of the score's three axes, so a set made largely of them has a high
    # floor for doing nothing.  One keeps the first wave's mix; a half halves it.
    attribute_weight: float = 1.0

    # How often a topological instruction is required to traverse two
    # relationship hops rather than one.  A value of zero takes the first
    # anchor that resolves, which is what the first wave did.
    two_hop_only_prob: float = 0.0

    # Whether deleting a door or a window also removes the opening it fills,
    # together with the relationship that voids the wall and the relationship
    # that fills the opening.  On is the convention BIM-Edit's own gold models
    # follow, and it leaves no hole in a wall with nothing in it.  Off keeps
    # the convention the first waves used, where the opening stays behind.
    delete_filling_removes_opening: bool = True

    # Whether a door or window the edit creates, copies or moves has to keep
    # the space in front of its hole free of other walls, columns and slabs
    # (modifc_gen.clearance).  On refuses a doorway cut across the end of a
    # partition that only butts the host wall's face, which the overlap tests
    # let through.  Off reproduces the waves generated before the rule.
    filling_zone_clearance: bool = True


    # --- 0.5.0: the requirement families, as weights rather than branches ---

    # How often each family group is drawn, keyed by the group's name in
    # modifc_gen.families.  A run overrides a group by name and the driver
    # passes the value through without knowing what the name means, so adding a
    # family or a group needs no change here and none in the driver.
    family_shares: dict[str, float] = field(default_factory=dict)

    # The weight of one family inside its group, keyed by the family's tag.  A
    # weight of zero switches that family off without removing it.
    family_weights: dict[str, float] = field(default_factory=dict)


SETTINGS = GeneratorSettings()

# Update kinds two of the score's three axes cannot see.
ATTRIBUTE_ONLY_KINDS = ("rename", "retype", "resize_overall")


def configure(**values: Any) -> GeneratorSettings:
    """Set the settings for this process and return them."""
    global SETTINGS
    known = {k: v for k, v in values.items() if k in GeneratorSettings.__annotations__}
    if "translate_extent_range" in known:
        known["translate_extent_range"] = tuple(known["translate_extent_range"])
    for name in ("family_shares", "family_weights"):
        if name in known:
            known[name] = {str(k): float(v) for k, v in (known[name] or {}).items()}
    SETTINGS = replace(SETTINGS, **known)
    return SETTINGS


def as_dict() -> dict[str, Any]:
    return asdict(SETTINGS)
