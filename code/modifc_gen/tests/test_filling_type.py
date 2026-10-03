"""A new door or window carries no predefined type the instruction does not state.

From IFC4 on, IfcDoor and IfcWindow have a ``PredefinedType``.  The filling
planners used to draw a random legal value for it (DOOR, TRAPDOOR, SKYLIGHT, ...)
and write it into the gold script, while the instruction never names it, so the
gold held a value no reader of the sentence could produce.  Each
test builds an IFC4 model with two storeys, a door and a window, so the draw has
legal values to choose from, plans the edit, and checks that the plan, its call
and the gold script it renders all leave the type unset.

Run with ``python -m modifc_gen.tests.test_filling_type``.
"""

from __future__ import annotations

import inspect
import os
import random
import shutil
import tempfile

import ifcopenshell

from .. import goldlib, ops, script
from ..scene import Scene

WORK = None


# ------------------------------------------------------------ the fixtures


def two_storey_model():
    """Metres, one context, one building and two storeys 3.5 m apart."""
    model = ifcopenshell.file(schema="IFC4")
    metre = model.create_entity("IfcSIUnit", UnitType="LENGTHUNIT", Name="METRE")
    units = model.create_entity("IfcUnitAssignment", Units=[metre])
    context = model.create_entity(
        "IfcGeometricRepresentationContext", ContextType="Model",
        CoordinateSpaceDimension=3, Precision=1e-5,
        WorldCoordinateSystem=model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, 0.0))))
    project = model.create_entity(
        "IfcProject", GlobalId=ifcopenshell.guid.new(), Name="Test",
        UnitsInContext=units, RepresentationContexts=[context])
    origin = model.create_entity(
        "IfcAxis2Placement3D",
        Location=model.create_entity("IfcCartesianPoint",
                                     Coordinates=(0.0, 0.0, 0.0)))
    building = model.create_entity(
        "IfcBuilding", GlobalId=ifcopenshell.guid.new(), Name="Building",
        ObjectPlacement=model.create_entity("IfcLocalPlacement",
                                            RelativePlacement=origin))
    storeys = []
    for index, elevation in enumerate((0.0, 3.5)):
        placement = model.create_entity(
            "IfcAxis2Placement3D",
            Location=model.create_entity("IfcCartesianPoint",
                                         Coordinates=(0.0, 0.0, elevation)))
        storeys.append(model.create_entity(
            "IfcBuildingStorey", GlobalId=ifcopenshell.guid.new(),
            Name=f"Level {index}", Elevation=elevation,
            ObjectPlacement=model.create_entity(
                "IfcLocalPlacement", PlacementRelTo=building.ObjectPlacement,
                RelativePlacement=placement)))
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                        RelatingObject=project, RelatedObjects=[building])
    model.create_entity("IfcRelAggregates", GlobalId=ifcopenshell.guid.new(),
                        RelatingObject=building, RelatedObjects=storeys)
    return model, storeys


def add_box(model, storey, ifc_class, x, y, z, length, width, height, name):
    guid = ifcopenshell.guid.new()
    goldlib.add_box_element(model, ifc_class, guid, name, storey.GlobalId,
                            ifcopenshell.guid.new(), x, y, z, length, width,
                            height)
    return guid


def add_leaf(model, ifc_class, wall, along, sill, width, height, name):
    """A door or a window in its own opening, with no predefined type."""
    guid = ifcopenshell.guid.new()
    goldlib.add_filling(model, ifc_class, guid, name, wall,
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        ifcopenshell.guid.new(), ifcopenshell.guid.new(),
                        along, -0.05, sill, width, height, 0.3, None, 0.0, 0.2)
    return guid


def building_with_fillings():
    """Two furnished storeys; the ground floor has a door, a window and a bare wall."""
    model, storeys = two_storey_model()
    guids = {}
    for index, storey in enumerate(storeys):
        add_box(model, storey, "IfcSlab", 0.0, 0.0, -0.2, 20.0, 10.0, 0.2,
                f"Floor {index}")
        for i in range(6):
            add_box(model, storey, "IfcColumn", 1.0 + 3.0 * i, 0.5, 0.0,
                    0.4, 0.4, 3.3, f"Post {index}.{i}")
    ground = storeys[0]
    guids["door_wall"] = add_box(model, ground, "IfcWall", 2.0, 3.0, 0.0,
                                 8.0, 0.2, 3.3, "Door wall")
    guids["window_wall"] = add_box(model, ground, "IfcWall", 2.0, 5.0, 0.0,
                                   8.0, 0.2, 3.3, "Window wall")
    guids["bare_wall"] = add_box(model, ground, "IfcWall", 2.0, 7.0, 0.0,
                                 8.0, 0.2, 3.3, "Bare wall")
    add_box(model, storeys[1], "IfcWall", 2.0, 5.0, 0.0, 8.0, 0.2, 3.3,
            "Upper wall")
    guids["door"] = add_leaf(model, "IfcDoor", guids["door_wall"], 1.0, 0.0,
                             0.9, 2.1, "Old door")
    guids["window"] = add_leaf(model, "IfcWindow", guids["window_wall"], 3.0,
                               0.9, 1.2, 1.4, "Old window")
    return model, guids


def save(model, name):
    path = os.path.join(WORK, name)
    model.write(path)
    return Scene(path)


def rng_of(seed=1):
    return random.Random(seed)


def argument(call, name):
    """One named argument of a planned library call."""
    names = list(inspect.signature(getattr(goldlib, call.func)).parameters)[1:]
    return dict(zip(names, call.args))[name]


def assert_type_unset(plan, task_id):
    assert plan is not None
    assert plan.params["predefined_type"] is None, plan.params["predefined_type"]
    assert argument(plan.calls[0], "predefined_type") is None
    rendered = script.render_script(task_id, "instruction", plan)
    assert "predefined_type=None" in rendered
    assert "predefined_type='" not in rendered


# ---------------------------------------------------------------- the rules


def test_the_fixture_offers_types_to_draw_from():
    """Without legal values there would be no draw, and the tests below would
    pass on the old planners as well."""
    model, guids = building_with_fillings()
    scene = save(model, "offer.ifc")
    assert scene.schema == "IFC4"
    assert len(scene.storeys) == 2
    for family in ("door", "window"):
        assert ops.predefined_types(scene.elements(family)[0]), family


def test_a_created_door_or_window_carries_no_predefined_type():
    model, guids = building_with_fillings()
    scene = save(model, "create.ifc")
    wall = scene.by_guid(guids["bare_wall"])
    for family in ("door", "window"):
        planned = 0
        for seed in range(8):
            plan = ops.plan_create_filling(scene, family, wall,
                                           f"T-{family}-{seed}", rng_of(seed))
            if plan is None:
                continue
            assert plan.kind == "create_filling"
            assert_type_unset(plan, f"T-{family}-{seed}")
            planned += 1
        assert planned, family


def test_a_replacing_door_or_window_carries_no_predefined_type():
    model, guids = building_with_fillings()
    scene = save(model, "replace.ifc")
    for old, new_class in (("window", "IfcDoor"), ("door", "IfcWindow")):
        planned = 0
        for seed in range(8):
            plan = ops.plan_replace(scene, scene.by_guid(guids[old]),
                                    rng_of(seed), f"T-{old}-{seed}")
            if plan is None:
                continue
            assert plan.kind == "replace_filling"
            assert plan.params["entity_type"] == new_class
            assert_type_unset(plan, f"T-{old}-{seed}")
            planned += 1
        assert planned, old


# ---------------------------------------------------------------- the runner


def main() -> int:
    global WORK
    WORK = tempfile.mkdtemp(prefix="modifc_gen_tests_")
    os.environ["MODIFC_GEOM_CACHE"] = os.path.join(WORK, "geom_index")
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    try:
        for test in tests:
            ops.reset_rejections()
            try:
                test()
            except Exception as exc:  # noqa: BLE001 - the report is the point
                failed += 1
                print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}",
                      flush=True)
            else:
                print(f"ok   {test.__name__}", flush=True)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
