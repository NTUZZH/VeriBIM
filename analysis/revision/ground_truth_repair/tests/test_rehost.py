"""Re-hosting a door keeps the opening's face size, cuts it through the new
wall (wall thickness plus 50 mm past each face), centres it across the wall,
voids the new wall, and keeps the leaf inside the opening. Checked for both
the ground-truth library (goldlib.rehost_filling) and the library the models
call (veribim_geom.move_filling), on synthetic models in three schemas and on
one benchmark source model per schema."""
import json
from pathlib import Path

import pytest
import ifcopenshell

import checks
import synth

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = ("IFC2X3", "IFC4", "IFC4X3")
RESULTS = Path(__file__).resolve().parent / "measured_rehost.jsonl"


def _record(name, boxes):
    with open(RESULTS, "a") as handle:
        handle.write(json.dumps({"test": name, **boxes}) + "\n")


def _goldlib():
    from modifc_gen import goldlib
    return goldlib


def _geom():
    from modifc_harness import veribim_geom
    return veribim_geom


# ------------------------------------------------- opening extruded across the wall
@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("flipped", (False, True))
def test_goldlib_extruded_across(schema, flipped):
    b, wall_a, wall_b = synth.two_walls(schema)
    _opening, door = b.door_extruded_across(wall_a, 1000, 100, 900, 2100, 60, flipped)
    model = b.finish()
    origin = 1.0 + (0.9 if flipped else 0.0)     # the opening origin the generator passes
    _goldlib().rehost_filling(model, door.GlobalId, wall_b.GlobalId, along=origin,
                              across=-0.15, sill=0.0, leaf_along=origin, leaf_across=-0.1,
                              leaf_sill=0.0, thickness=0.3, leaf_depth=None)
    opening = door.FillsVoids[0].RelatingOpeningElement
    solid = opening.Representation.Representations[0].Items[0]
    assert (solid.SweptArea.XDim, solid.SweptArea.YDim) == (2100.0, 900.0)   # face kept
    assert abs(solid.Depth - 300.0) < 1e-9                                   # cut depth
    boxes = checks.check_rehosted(door, wall_b, 0.9, 2.1)
    assert abs(boxes["opening"][0][0] - 1.0) < 1e-3                          # along the wall
    leaf_centre = (boxes["leaf"][0][1] + boxes["leaf"][1][1]) / 2
    assert abs(leaf_centre) < 1e-3                                           # leaf centred
    _record(f"goldlib_extruded_across[{schema},{flipped}]", boxes)


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("flipped", (False, True))
def test_geom_extruded_across(schema, flipped):
    b, wall_a, wall_b = synth.two_walls(schema)
    _opening, door = b.door_extruded_across(wall_a, 1000, 100, 900, 2100, 60, flipped)
    b.finish()
    _geom().move_filling(door, wall_b, 1.0)
    boxes = checks.check_rehosted(door, wall_b, 0.9, 2.1)
    assert abs(boxes["opening"][0][0] - 1.0) < 1e-3
    assert abs((boxes["leaf"][0][1] + boxes["leaf"][1][1]) / 2) < 1e-3
    _record(f"geom_extruded_across[{schema},{flipped}]", boxes)


# ------------------------------------------------- opening whose profile holds the cut
def _cut_in_profile(schema):
    """An opening and door cut by goldlib.add_filling: box profile, YDim across the wall,
    leaf hung from the wall itself."""
    b, wall_a, wall_b = synth.two_walls(schema)
    model = b.finish()
    g = ifcopenshell.guid.new
    door = _goldlib().add_filling(model, "IfcDoor", g(), "D", wall_a.GlobalId, g(), g(), g(), g(),
                                  along=1.0, across=-0.1, sill=0.0, width=0.9, height=2.1,
                                  thickness=0.2, filling_across=-0.05, filling_depth=0.1)
    return model, door, wall_b


@pytest.mark.parametrize("schema", SCHEMAS)
@pytest.mark.parametrize("leaf_depth", (0.2, None))
def test_goldlib_cut_in_profile(schema, leaf_depth):
    model, door, wall_b = _cut_in_profile(schema)
    _goldlib().rehost_filling(model, door.GlobalId, wall_b.GlobalId, along=1.0, across=-0.15,
                              sill=0.0, leaf_along=1.0, leaf_across=-0.1, leaf_sill=0.0,
                              thickness=0.3, leaf_depth=leaf_depth)
    boxes = checks.check_rehosted(door, wall_b, 0.9, 2.1)
    leaf = boxes["leaf"]
    if leaf_depth is not None:
        assert abs(leaf[0][1] + 0.1) < 1e-3 and abs(leaf[1][1] - 0.1) < 1e-3   # flush with both faces
    else:
        assert abs((leaf[0][1] + leaf[1][1]) / 2) < 1e-3                      # kept its centring
    _record(f"goldlib_cut_in_profile[{schema},{leaf_depth}]", boxes)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_geom_cut_in_profile(schema):
    model, door, wall_b = _cut_in_profile(schema)
    _geom().move_filling(door, wall_b, 1.0)
    boxes = checks.check_rehosted(door, wall_b, 0.9, 2.1)
    assert abs(boxes["leaf"][0][1] + 0.1) < 1e-3 and abs(boxes["leaf"][1][1] - 0.1) < 1e-3
    _record(f"geom_cut_in_profile[{schema}]", boxes)


def test_oblique_body_refused():
    b, wall_a, wall_b = synth.two_walls("IFC4")
    opening, door = b.door_extruded_across(wall_a, 1000, 100, 900, 2100, 60)
    solid = opening.Representation.Representations[0].Items[0]
    solid.ExtrudedDirection = b.direction((0.0, 0.6, 0.8))
    model = b.finish()
    with pytest.raises(ValueError):
        _goldlib().rehost_filling(model, door.GlobalId, wall_b.GlobalId, along=1.0, across=-0.15,
                                  sill=0.0, leaf_along=1.0, leaf_across=-0.1, leaf_sill=0.0,
                                  thickness=0.3, leaf_depth=None)


# ------------------------------------------------- one benchmark source per schema
BENCH = {"IFC2X3": "DOR-UPD-DIR-G7arc-001", "IFC4": "DOR-UPD-TOP-G7arcm4-010",
         "IFC4X3": "DOR-UPD-SPA-G7arcm4X3-003"}


def _record_of(task_id):
    for line in open(ROOT / "runs_local/bench_v4/tasks.v4c.jsonl", encoding="utf-8"):
        if f'"{task_id}"' in line:
            record = json.loads(line)
            if record["task_id"] == task_id:
                return record
    raise KeyError(task_id)


def _source_face(model, record):
    door = model.by_guid(record["target"]["guids"][0])
    opening, wall = checks.opening_and_host(door)
    lo, hi = checks.box_in_frame(opening, wall, model)
    return float(hi[0] - lo[0]), float(hi[2] - lo[2]), checks.leaf_relation(door, model)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_goldlib_benchmark_source(schema):
    record = _record_of(BENCH[schema])
    model = ifcopenshell.open(str(ROOT / record["input_ifc"]))
    assert model.schema == schema
    width, height, relation = _source_face(model, record)
    namespace = {"__name__": "gold"}
    exec(compile(record["gold_script"], "<gold>", "exec"), namespace)
    namespace["apply_edit"](model)
    door = model.by_guid(record["target"]["guids"][0])
    wall = model.by_guid(record["edit_params"]["host_to_guid"])
    boxes = checks.check_rehosted(door, wall, width, height, source_relation=relation)
    assert abs(boxes["opening"][0][0] - record["edit_params"]["along"]) < 0.006
    _record(f"goldlib_benchmark[{record['task_id']}]", boxes)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_geom_benchmark_source(schema):
    record = _record_of(BENCH[schema])
    model = ifcopenshell.open(str(ROOT / record["input_ifc"]))
    width, height, relation = _source_face(model, record)
    door = model.by_guid(record["target"]["guids"][0])
    wall = model.by_guid(record["edit_params"]["host_to_guid"])
    _geom().move_filling(door, wall, record["edit_params"]["along"])
    boxes = checks.check_rehosted(door, wall, width, height, source_relation=relation)
    assert abs(boxes["opening"][0][0] - record["edit_params"]["along"]) < 0.006
    _record(f"geom_benchmark[{record['task_id']}]", boxes)
