"""The compositional tier: several edits that depend on one another.

A chain is one work order that cannot be carried out element by element without
looking at a relationship first.  Which elements the chain touches is read from
the model, so the dependency is real rather than declared: the doors a wall
hosts, the walls that bound a space, a door that has to go into the wall the
same order creates.
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np

from . import ops, settings
from .ops import Call, EditPlan, _round, free_guid, magnitude_bucket
from .scene import AXIS_WORDS, Extent, Scene

# The scorer reads one entity class per task.  A chain that touches more than
# one class is scored against the class both sides share.
MIXED_CLASS = "IfcBuildingElement"

CHAIN_NAMES = ("move_wall_with_fillings", "delete_wall_with_fillings",
               "move_space_with_bounding_walls", "create_wall_with_door")


# The placement helpers live in the operation library, so the single-element
# tier and the compositional tier apply one rule rather than two copies of it.
placement_chain = ops.placement_chain
moves_with = ops.moves_with


def _translate_offset(scene: Scene, storey, point: np.ndarray, rng,
                      movers: Sequence[Any] = ()
                      ) -> Optional[tuple[int, int, float]]:
    extent = scene.storey_extent(storey)
    if extent is None:
        return None
    skip = [m.GlobalId for m in movers]
    for _attempt in range(ops.PLACEMENT_ATTEMPTS):
        axis = rng.choice([0, 1])
        sign = rng.choice([1, -1])
        cap = max(0.5, 0.15 * float(extent.size[axis]))
        choices = [d for d in ops.TRANSLATE_DISTANCES if d <= cap]
        if not choices:
            ops.note_rejection("translate_no_room_on_axis")
            continue
        distance = float(rng.choice(choices))
        offset = np.zeros(3)
        offset[axis] = sign * distance
        margin = np.maximum(0.1 * extent.size, 1.0)
        if not Extent(extent.lo - margin,
                      extent.hi + margin).contains(point + offset):
            ops.note_rejection("translate_origin_outside_storey")
            continue
        # Every element the chain moves has to land inside the storey and clear
        # of what already stands there, not just the one the order names.
        fault = None
        for mover in movers:
            fault = ops.destination_fault(scene, mover, offset, storey, skip)
            if fault is not None:
                break
        if fault is not None:
            ops.note_rejection(fault)
            continue
        return axis, sign, distance
    return None


def plan_move_wall_with_fillings(scene: Scene, wall, task_id: str, rng
                                 ) -> Optional[EditPlan]:
    """Move a wall and carry the doors and windows it hosts with it.

    Only used where the model places the fillings independently of the wall, so
    that moving the wall alone would leave them behind.
    """
    hosted = [scene.by_guid(g) for g in scene.hosted_by(wall)]
    hosted = [h for h in hosted if h is not None and not moves_with(h, wall)
              and scene.has_body(h)]
    if not hosted or not scene.has_body(wall):
        return None
    storey = scene.storey_of(wall)
    point = scene.point(wall)
    if storey is None or point is None:
        return None
    drawn = _translate_offset(scene, storey, point, rng, [wall] + hosted)
    if drawn is None:
        return None
    axis, sign, distance = drawn
    offset = [0.0, 0.0, 0.0]
    offset[axis] = _round(sign * distance)
    word, axis_word = AXIS_WORDS[(axis, sign)]
    calls = [Call("translate", (wall.GlobalId, offset[0], offset[1], offset[2]),
                  "move the wall")]
    for filling in hosted:
        calls.append(Call("translate",
                          (filling.GlobalId, offset[0], offset[1], offset[2]),
                          "carry the hosted element with it"))
    # An opening the wall does not already carry has to be moved as well, or the
    # wall would arrive at its new place still cut where it used to stand.
    for opening in ops.stranded_dependants(scene, wall):
        if opening.is_a("IfcOpeningElement"):
            calls.append(Call("translate",
                              (opening.GlobalId, offset[0], offset[1],
                               offset[2]),
                              "carry the opening in the wall with it"))
    guids = (wall.GlobalId,) + tuple(f.GlobalId for f in hosted)
    return EditPlan(
        kind="move_wall_with_fillings", operation="update", family="wall",
        calls=calls, target_guids=guids, touched_guids=guids,
        params={"distance": _round(distance), "direction": word,
                "axis_word": axis_word,
                "fillings": [{"guid": f.GlobalId,
                              "family": scene.family_of(f)} for f in hosted],
                "entity_type": MIXED_CLASS,
                "magnitude": magnitude_bucket(scene, distance)})


def plan_delete_wall_with_fillings(scene: Scene, wall, task_id: str, rng
                                   ) -> Optional[EditPlan]:
    """Remove the doors and windows a wall hosts, then remove the wall."""
    hosted = [scene.by_guid(g) for g in scene.hosted_by(wall)]
    hosted = [h for h in hosted if h is not None
              and scene.family_of(h) in ("door", "window")]
    if not hosted:
        return None
    # A hosted element is removed under the same convention the single-element
    # tier uses, so one work order and one edit mean the same thing.
    with_opening = settings.SETTINGS.delete_filling_removes_opening
    calls = []
    removed = []
    for filling in hosted:
        opening = ops.own_opening(filling) if with_opening else None
        if opening is None:
            calls.append(Call("delete_element", (filling.GlobalId,),
                              "remove the hosted element first"))
        else:
            calls.append(Call("delete_filling_with_opening",
                              (filling.GlobalId,),
                              "remove the hosted element and its opening first"))
            removed.append(opening.GlobalId)
    calls.append(Call("delete_element", (wall.GlobalId,),
                      "then remove the wall and its openings"))
    guids = tuple(f.GlobalId for f in hosted) + (wall.GlobalId,)
    return EditPlan(
        kind="delete_wall_with_fillings", operation="delete", family="wall",
        calls=calls, target_guids=guids, touched_guids=guids,
        removed_guids=guids + tuple(removed),
        params={"fillings": [{"guid": f.GlobalId, "family": scene.family_of(f),
                              "name": (f.Name or "").strip() or None}
                             for f in hosted],
                "entity_type": MIXED_CLASS, "magnitude": "small"})


def eligible_bounding_walls(scene: Scene, space) -> list:
    """The walls bounding a space that a move of the space carries, in order."""
    walls = []
    for guid in scene.space_elements(space):
        element = scene.by_guid(guid)
        if element is None or scene.family_of(element) != "wall":
            continue
        # Skip anything that already moves with something else in the set,
        # which would otherwise be shifted twice.
        if moves_with(element, space) or moves_with(space, element):
            continue
        if any(moves_with(element, other) or moves_with(other, element)
               for other in walls):
            continue
        if not scene.has_body(element):
            continue
        walls.append(element)
    return walls


def plan_move_space_with_bounding_walls(scene: Scene, space, task_id: str, rng
                                        ) -> Optional[EditPlan]:
    """Move a space and every wall that bounds it by the same offset."""
    # Every eligible wall moves, so "the N walls that bound it" is true; a room
    # with more than six is refused rather than cut to six.
    walls = eligible_bounding_walls(scene, space)
    if not 2 <= len(walls) <= 6 or not scene.has_body(space):
        return None
    storey = scene.storey_of(space)
    point = scene.point(space)
    if storey is None or point is None:
        return None
    drawn = _translate_offset(scene, storey, point, rng, [space] + walls)
    if drawn is None:
        return None
    axis, sign, distance = drawn
    offset = [0.0, 0.0, 0.0]
    offset[axis] = _round(sign * distance)
    word, axis_word = AXIS_WORDS[(axis, sign)]
    calls = [Call("translate", (space.GlobalId, offset[0], offset[1], offset[2]),
                  "move the space")]
    for wall in walls:
        calls.append(Call("translate",
                          (wall.GlobalId, offset[0], offset[1], offset[2]),
                          "move a wall that bounds it"))
    guids = (space.GlobalId,) + tuple(w.GlobalId for w in walls)
    return EditPlan(
        kind="move_space_with_bounding_walls", operation="update", family="space",
        calls=calls, target_guids=guids, touched_guids=guids,
        params={"distance": _round(distance), "direction": word,
                "axis_word": axis_word, "n_walls": len(walls),
                "entity_type": "IfcProduct",
                "magnitude": magnitude_bucket(scene, distance)})


def plan_create_wall_with_door(scene: Scene, storey, task_id: str, rng
                               ) -> Optional[EditPlan]:
    """Add a wall on a storey and put a door in the wall the same order adds."""
    if scene.schema not in ("IFC2X3", "IFC4"):
        return None
    length, thickness, _ = ops.CREATE_SIZES["wall"]
    height = _round(ops._storey_height(scene, storey) - 0.1)
    door_width, door_height, sill = ops.CREATE_FILLING["door"]
    # The wall the order creates has to be able to carry the door the same order
    # puts in it.
    if height < sill + door_height + ops.FILLING_HEADROOM:
        ops.note_rejection("filling_taller_than_wall")
        return None
    spot = ops.free_spot(scene, storey, (length, thickness), rng, height, 0.0)
    if spot is None:
        return None
    x, y = spot
    wall_guid = free_guid(scene, task_id, "wall")
    door_guid = free_guid(scene, task_id, "door")
    opening_guid = free_guid(scene, task_id, "opening")
    wall_name = f"Partition {rng.randint(100, 998)}"
    door_name = f"Doorset {rng.randint(100, 998)}"
    along = _round(0.5 * (length - door_width))
    like = scene.body_donor()
    calls = [
        Call("add_box_element",
             ("IfcWall", wall_guid, wall_name, storey.GlobalId,
              free_guid(scene, task_id, "containment"), x, y, 0.0,
              length, thickness, height, None, like, None),
             "create the wall and put it in the storey"),
        Call("add_filling",
             ("IfcDoor", door_guid, door_name, wall_guid, opening_guid,
              free_guid(scene, task_id, "voids"),
              free_guid(scene, task_id, "fills"),
              free_guid(scene, task_id, "door_containment"),
              along, _round(-0.05), sill, door_width, door_height,
              _round(thickness + 0.1), None, 0.0, thickness),
             "cut an opening in the new wall and fill it with the door"),
    ]
    return EditPlan(
        kind="create_wall_with_door", operation="create", family="wall",
        calls=calls, target_guids=(wall_guid, door_guid),
        created_guids=(wall_guid, door_guid, opening_guid),
        touched_guids=(wall_guid, door_guid),
        params={"x": x, "y": y, "length": length, "thickness": thickness,
                "height": height, "wall_name": wall_name, "door_name": door_name,
                "door_width": door_width, "door_height": door_height,
                "along": along, "storey_guid": storey.GlobalId,
                "entity_type": MIXED_CLASS,
                "magnitude": magnitude_bucket(scene, length)})
