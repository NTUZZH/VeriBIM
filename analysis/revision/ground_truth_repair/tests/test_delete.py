"""After a deletion no relationship is left with a required end null or empty
(beyond the ones the source model already had), while the disclosed
conventions hold: a deleted space's contained elements stay, uncontained; a
deleted wall's parts stay; a covering stays when its element goes."""
import json
from pathlib import Path

import pytest
import ifcopenshell

import checks
import synth

ROOT = Path(__file__).resolve().parents[4]
SCHEMAS = ("IFC2X3", "IFC4", "IFC4X3")
RESULTS = Path(__file__).resolve().parent / "measured_delete.jsonl"


def _goldlib():
    from modifc_gen import goldlib
    return goldlib


def _record(name, data):
    with open(RESULTS, "a") as handle:
        handle.write(json.dumps({"test": name, **data}) + "\n")


def _scene(schema):
    b = synth.Builder(schema)
    f = b.f
    columns = []
    for x in (0, 3000):
        column = b.root("IfcColumn", Name=f"C{x}", ObjectPlacement=b.placement(
            b.storey.ObjectPlacement, (x, 0, 0)))
        column.Representation = b.shape(b.rect_solid(300, 300, 3000, (0, 0)))
        b.contain(column)
        columns.append(column)
    c1, c2 = columns
    cover = b.root("IfcCovering", Name="cladding")
    b.root("IfcRelCoversBldgElements", RelatingBuildingElement=c1, RelatedCoverings=[cover])
    # a relationship that already lacks its element in the source stays as it is
    stray = b.root("IfcCovering", Name="stray")
    ghost = b.root("IfcColumn", Name="ghost")
    pre = b.root("IfcRelCoversBldgElements", RelatingBuildingElement=ghost, RelatedCoverings=[stray])
    reference = f.create_entity("IfcClassificationReference", Name="Uniclass Pr_20")
    b.root("IfcRelAssociatesClassification", RelatedObjects=[c1], RelatingClassification=reference)
    shared = f.create_entity("IfcClassificationReference", Name="shared")
    b.root("IfcRelAssociatesClassification", RelatedObjects=[c1, c2], RelatingClassification=shared)
    person = f.create_entity("IfcPerson", FamilyName="Owner")
    actor = b.root("IfcActor", TheActor=person)
    b.root("IfcRelAssignsToActor", RelatedObjects=[c1], RelatingActor=actor)
    # a wall built from parts
    wall = b.wall((0, 2000, 0), 4000, 200, name="Wpart")
    parts = []
    for i in range(2):
        part = b.root("IfcBuildingElementPart", Name=f"P{i}", ObjectPlacement=b.placement(
            wall.ObjectPlacement, (0, -100 + 100 * i, 0)))
        part.Representation = b.shape(b.rect_solid(4000, 100, 3000, (2000, 50)))
        parts.append(part)
    b.root("IfcRelAggregates", RelatingObject=wall, RelatedObjects=parts)
    # a room holding furniture
    space = b.root("IfcSpace", Name="R1", ObjectPlacement=b.placement(
        b.storey.ObjectPlacement, (0, 5000, 0)))
    space.Representation = b.shape(b.rect_solid(3000, 3000, 2500, (1500, 1500)))
    if hasattr(space, "CompositionType"):
        space.CompositionType = "ELEMENT"
    b.root("IfcRelAggregates", RelatingObject=b.storey, RelatedObjects=[space])
    furniture = b.root("IfcFurnishingElement", Name="table", ObjectPlacement=b.placement(
        space.ObjectPlacement, (500, 500, 0)))
    b.root("IfcRelContainedInSpatialStructure", RelatingStructure=space, RelatedElements=[furniture])
    model = b.finish()
    model.remove(ghost)                         # leaves `pre` dangling before any edit
    return model, {"c1": c1.GlobalId, "c2": c2.GlobalId, "cover": cover.GlobalId,
                   "stray": stray.GlobalId, "pre": pre.GlobalId, "wall": wall.GlobalId,
                   "parts": [p.GlobalId for p in parts], "space": space.GlobalId,
                   "furniture": furniture.GlobalId}


def _new_empty_ends(before, model):
    after = checks.empty_required_ends(model)
    return {k: v for k, v in after.items() if v not in set(before.values())}


@pytest.mark.parametrize("schema", SCHEMAS)
def test_delete_column_with_covering(schema):
    model, ids = _scene(schema)
    before = checks.empty_required_ends(model)
    assert list(before.values()) == [ids["pre"]]
    _goldlib().delete_element(model, ids["c1"])
    new = _new_empty_ends(before, model)
    assert not new, new
    assert model.by_guid(ids["cover"])                   # the covering itself stays
    assert model.by_guid(ids["pre"])                     # the source's own dangling row stays
    c2 = model.by_guid(ids["c2"])
    assert any(r.is_a("IfcRelAssociatesClassification") for r in c2.HasAssociations)
    _record(f"delete_column[{schema}]", {"empty_before": before,
                                         "empty_after": checks.empty_required_ends(model)})


@pytest.mark.parametrize("schema", SCHEMAS)
def test_delete_wall_keeps_parts(schema):
    model, ids = _scene(schema)
    before = checks.empty_required_ends(model)
    _goldlib().delete_element(model, ids["wall"])
    assert not _new_empty_ends(before, model)
    for guid in ids["parts"]:
        assert model.by_guid(guid)


@pytest.mark.parametrize("schema", SCHEMAS)
def test_delete_space_leaves_contents_uncontained(schema):
    model, ids = _scene(schema)
    before = checks.empty_required_ends(model)
    _goldlib().delete_element(model, ids["space"])
    assert not _new_empty_ends(before, model)
    furniture = model.by_guid(ids["furniture"])
    assert not (furniture.ContainedInStructure or ())


BENCH = {"IFC2X3": "COL-DEL-SPA-B46-004", "IFC4": "SPC-DEL-DIR-B27m4-004",
         "IFC4X3": "SPC-DEL-SPA-B27m4X3-001"}


@pytest.mark.parametrize("schema", SCHEMAS)
def test_benchmark_deletion(schema):
    task_id = BENCH[schema]
    for line in open(ROOT / "runs_local/bench_v4/tasks.v4c.jsonl", encoding="utf-8"):
        if f'"{task_id}"' in line:
            record = json.loads(line)
            if record["task_id"] == task_id:
                break
    model = ifcopenshell.open(str(ROOT / record["input_ifc"]))
    assert model.schema == schema
    before = checks.empty_required_ends(model)
    namespace = {"__name__": "gold"}
    exec(compile(record["gold_script"], "<gold>", "exec"), namespace)
    namespace["apply_edit"](model)
    new = _new_empty_ends(before, model)
    _record(f"benchmark_delete[{task_id}]", {"empty_in_source": len(before), "new_after_edit": new})
    assert not new, new
