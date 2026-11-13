"""The clearance rule, checked on small models built so that it must fire.

Each test builds a storey with a floor slab and a host wall along x, adds the
fabric the case needs, cuts a door into the host with the gold library's own
call, and asks the rule.  The models are written to a temporary directory
because the funnel stage reads the gold model from a file.

Run with ``python -m modifc_gen.tests.test_clearance``.
"""

from __future__ import annotations

import os
import shutil
import tempfile

import ifcopenshell
import ifcopenshell.guid

from .. import clearance, verify
from ..scene import Scene
from .test_placement_rules import add_box, add_wall, empty_model

WORK = None

# The host wall runs along x from 0 to 6 m, 0.2 m thick (y from 0 to 0.2),
# 3 m high, on a 0.2 m floor slab whose top is at z = 0.
HOST = (0.0, 0.0, 0.0, 6.0, 0.2, 3.0)


def storey_with_host():
    model, storey = empty_model()
    add_box(model, storey, "IfcSlab", -1.0, -3.0, -0.2, 8.0, 7.0, 0.2, "Floor")
    host = add_wall(model, storey, *HOST, name="Host")
    return model, storey, host


def cut_door(model, host, along, width=0.9, height=2.1):
    guid = ifcopenshell.guid.new()
    ids = [ifcopenshell.guid.new() for _ in range(4)]
    from .. import goldlib
    goldlib.add_filling(model, "IfcDoor", guid, "Doorset", host,
                        *ids, along, -0.05, 0.0, width, height,
                        0.3, None, 0.0, 0.2)
    return guid


def distance(model, door):
    found = clearance.clearance_of(model, model.by_guid(door), None)
    assert found["status"] == "ok", found
    return found.get("distance"), found.get("obstruction")


def test_door_across_a_partition_end_is_refused():
    model, storey, host = storey_with_host()
    # A partition 0.1 m thick runs north from the host's inner face at x = 3.0.
    partition = add_box(model, storey, "IfcWall", 3.0, 0.2, 0.0, 0.1, 2.8, 3.0,
                        "Partition")
    door = cut_door(model, host, along=2.6)          # spans x = 2.6 .. 3.5
    d, what = distance(model, door)
    assert d == 0.0 and what == partition, (d, what)


def test_door_beside_a_partition_is_kept():
    model, storey, host = storey_with_host()
    add_box(model, storey, "IfcWall", 3.0, 0.2, 0.0, 0.1, 2.8, 3.0, "Partition")
    door = cut_door(model, host, along=0.8)          # spans x = 0.8 .. 1.7
    d, _ = distance(model, door)
    assert d is None, d


def test_wall_standing_close_in_front_is_refused_and_far_is_kept():
    for gap, refused in ((0.4, True), (0.9, False)):
        model, storey, host = storey_with_host()
        add_box(model, storey, "IfcWall", 0.0, 0.2 + gap, 0.0, 6.0, 0.1, 3.0,
                "Parallel")
        door = cut_door(model, host, along=2.0)
        d, _ = distance(model, door)
        assert abs(d - gap) < 1e-6, (gap, d)
        assert (d < clearance.FILLING_ZONE_CLEARANCE) == refused, (gap, d)


def test_leaf_alongside_the_host_is_a_layer():
    model, storey, host = storey_with_host()
    # A second leaf 0.03 m off the host's face, running its whole length.
    add_box(model, storey, "IfcWall", 0.0, 0.23, 0.0, 6.0, 0.1, 3.0, "Leaf")
    door = cut_door(model, host, along=2.0)
    d, _ = distance(model, door)
    assert d is None, d


def test_floor_slab_under_the_door_does_not_obstruct():
    model, _storey, host = storey_with_host()
    door = cut_door(model, host, along=2.0)
    d, _ = distance(model, door)
    assert d is None, d


def test_funnel_stage_refuses_and_passes():
    model, storey, host = storey_with_host()
    add_box(model, storey, "IfcWall", 3.0, 0.2, 0.0, 0.1, 2.8, 3.0, "Partition")
    source = os.path.join(WORK, "source.ifc")
    model.write(source)
    scene = Scene(source)
    for along, ok in ((2.6, False), (0.8, True)):
        gold_model = ifcopenshell.open(source)
        door = cut_door(gold_model, host, along)
        gold = os.path.join(WORK, f"gold_{along}.ifc")
        gold_model.write(gold)
        stage = verify.check_filling_clearance(scene, gold, (door,), (host,))
        assert stage.ok == ok, (along, stage)
        if not ok:
            assert stage.reason == "filling_clearance_obstructed"


def main():
    global WORK
    WORK = tempfile.mkdtemp(prefix="clearance_")
    from . import test_placement_rules
    test_placement_rules.WORK = WORK
    try:
        for name, func in sorted(globals().items()):
            if name.startswith("test_") and callable(func):
                func()
                print("ok", name)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)


if __name__ == "__main__":
    main()
