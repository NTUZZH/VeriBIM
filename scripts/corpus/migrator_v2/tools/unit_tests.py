"""Unit tests of the migrator-v2 rules, each on the smallest pool source that shows the issue.
For each case: migrate (IFC2X3 via IFC4), validate source and outputs with the pipeline's validator, require that no
issue key exceeds its source count, that the rule fired, and a rule-specific property. Output: unit/UNIT_TESTS.txt."""
import os, sys, json, collections
os.environ["OMP_NUM_THREADS"] = "1"
HERE = "runs_local/corpus_v10/migrator_v2"; ROOT = "."
sys.path.insert(0, "scripts/corpus/migrator_v2")
import numpy as np
import ifcopenshell, ifcopenshell.util.placement as P
from migrate_v2 import migrate
from vkeys import validate_keys
OUT = f"{HERE}/unit"; os.makedirs(OUT, exist_ok=True)
lines = []


def say(*a):
    s = " ".join(str(x) for x in a); print(s, flush=True); lines.append(s)


def run_case(name, src, rule_prefixes, check):
    src = f"{ROOT}/{src}"; stem = os.path.basename(src)[:-4].replace(" ", "_")
    f = ifcopenshell.open(src); sch = f.schema; ks, _ = validate_keys(f); del f
    cur = src; reps = []
    if sch == "IFC2X3":
        d4 = f"{OUT}/{stem}__IFC4.ifc"; reps.append(migrate(cur, "IFC4", d4)); cur = d4
    reps.append(migrate(cur, "IFC4X3", f"{OUT}/{stem}__IFC4X3.ifc"))
    ok = True; fired = collections.Counter()
    for r in reps:
        g = ifcopenshell.open(r["dst"]); k, _ = validate_keys(g); del g
        added = {x: v - ks.get(x, 0) for x, v in k.items() if v > ks.get(x, 0)}
        if added or r["unhandled_nulls"]:
            ok = False
        for x, v in r["rules"].items():
            fired[x] += v
        say(f"  {r['target']}: issues {sum(k.values())} (source {sum(ks.values())}), added {added or 0}, "
            f"unhandled {r['unhandled_nulls'] or 0}, rules {r['rules']}")
    for p in rule_prefixes:
        if not any(x.startswith(p) for x in fired):
            ok = False; say(f"  rule {p} did not fire")
    try:
        msg = check(src, [r["dst"] for r in reps])
    except AssertionError as ex:
        ok = False; msg = f"check failed: {ex}"
    say(f"  property: {msg}")
    say(f"{'PASS' if ok else 'FAIL'} {name}  ({os.path.basename(src)}, {sch})\n")
    return ok


def chk_axis(src, dsts):
    f = ifcopenshell.open(dsts[-1]); kinds = collections.Counter(); worst = 0.0
    for m in f.by_type("IfcStructuralCurveMember"):
        ax = np.array(m.Axis.DirectionRatios, dtype=float); R = np.array(P.get_local_placement(m.ObjectPlacement))[:3, :3]
        e = [i for r in m.Representation.Representations for i in r.Items][0]
        d = np.array(e.EdgeEnd.VertexGeometry.Coordinates) - np.array(e.EdgeStart.VertexGeometry.Coordinates)
        d /= np.linalg.norm(d); worst = max(worst, abs(float(ax @ d)))
        assert abs(np.linalg.norm(ax) - 1) < 1e-9
        dw = R @ d; aw = np.round(R @ ax, 9)
        if np.hypot(dw[0], dw[1]) < 1e-3:
            assert np.allclose(aw, [1, 0, 0]); kinds["vertical->(1,0,0)"] += 1
        elif abs(dw[2]) < 1e-9:
            assert np.allclose(aw, [0, 0, 1]); kinds["horizontal->(0,0,1)"] += 1
        else:
            assert aw[2] > 0 and abs(aw[1] * dw[0] - aw[0] * dw[1]) < 1e-6; kinds["inclined->vertical plane"] += 1
    assert worst < 1e-9
    return f"{dict(kinds)}; max |axis . edge| = {worst:.1e}"


def chk_virtual(src, dsts):
    out = []
    for d in dsts:
        f = ifcopenshell.open(d); n = 0
        for b in f.by_type("IfcRelSpaceBoundary"):
            ve = b.RelatedBuildingElement
            assert ve is not None
            if ve.is_a("IfcVirtualElement"):
                n += 1
                assert b.PhysicalOrVirtualBoundary == "VIRTUAL" and ve.Representation is None and ve.ObjectPlacement is None
                cont = ve.ContainedInStructure[0].RelatingStructure
                node = b.RelatingSpace
                while not node.is_a("IfcBuildingStorey"):
                    node = node.Decomposes[0].RelatingObject
                assert cont == node
        out.append(f"{f.schema}: {n} virtual boundaries, each with its own IfcVirtualElement in the space's storey")
    return "; ".join(out)


def chk_doorwin(src, dsts):
    f = ifcopenshell.open(dsts[-1]); s = ifcopenshell.open(src if not dsts[0].endswith("__IFC4.ifc") else dsts[0])
    ops = {w.GlobalId: w.OperationType for w in s.by_type("IfcWindowStyle")}
    enum = {"SINGLE_PANEL", "DOUBLE_PANEL_VERTICAL", "DOUBLE_PANEL_HORIZONTAL", "TRIPLE_PANEL_VERTICAL", "TRIPLE_PANEL_BOTTOM",
            "TRIPLE_PANEL_TOP", "TRIPLE_PANEL_LEFT", "TRIPLE_PANEL_RIGHT", "TRIPLE_PANEL_HORIZONTAL", "USERDEFINED", "NOTDEFINED"}
    for w in f.by_type("IfcWindowType"):
        assert w.PredefinedType == "WINDOW"
        op = ops.get(w.GlobalId)
        if op is not None:
            assert w.PartitioningType == (op if op in enum else "NOTDEFINED"), (op, w.PartitioningType)
    for d in f.by_type("IfcDoorType"):
        assert d.PredefinedType == "DOOR"
    return f"{len(f.by_type('IfcWindowType'))} window types WINDOW with PartitioningType from OperationType, {len(f.by_type('IfcDoorType'))} door types DOOR"


def chk_curvefont(src, dsts):
    f = ifcopenshell.open(dsts[-1]); n = 0
    for c in f.by_type("IfcCurveStyleFontAndScaling"):
        assert c.CurveStyleFont is not None and c.CurveStyleFont.is_a("IfcCurveStyleFont"); n += 1
    return f"{n} IfcCurveStyleFontAndScaling keep their IfcCurveStyleFont"


def chk_enum(cls):
    def c(src, dsts):
        f = ifcopenshell.open(dsts[0]); v = collections.Counter(x.PredefinedType for x in f.by_type(cls))
        assert None not in v
        return f"{cls}.PredefinedType values {dict(v)}"
    return c


def chk_wrap(src, dsts):
    f = ifcopenshell.open(dsts[-1]); s = ifcopenshell.open(src)
    a = [(x.StartParam, x.EndParam) for x in s.by_type("IfcSurfaceCurveSweptAreaSolid")]
    b = [(x.StartParam.wrappedValue if x.StartParam is not None else None, x.EndParam.wrappedValue if x.EndParam is not None else None)
         for x in f.by_type("IfcSurfaceCurveSweptAreaSolid")]
    assert a == b, (a[:3], b[:3])
    return f"{len(b)} IfcSurfaceCurveSweptAreaSolid keep StartParam/EndParam as IfcParameterValue, equal to the source"


def chk_surface(src, dsts):
    f = ifcopenshell.open(dsts[-1]); n = 0
    for sf in f.by_type("IfcSurfaceFeature"):
        rel = sf.AdheresToElement
        rel = rel[0] if isinstance(rel, tuple) else rel
        assert rel.RelatingElement.ObjectPlacement == sf.ObjectPlacement.PlacementRelTo; n += 1
    return f"{n} surface features adhere to the element they are placed relative to"


def chk_port(src, dsts):
    s = ifcopenshell.open(src); f = ifcopenshell.open(dsts[-1])
    bad = {r.GlobalId: (r.RelatingPort.GlobalId, r.RelatedElement.GlobalId) for r in s.by_type("IfcRelConnectsPortToElement")
           if not r.RelatedElement.is_a("IfcDistributionElement")}
    for g, (port, el) in bad.items():
        n = f.by_guid(g); assert n.is_a("IfcRelNests") and n.RelatingObject.GlobalId == el and [p.GlobalId for p in n.RelatedObjects] == [port]
    keep = len(s.by_type("IfcRelConnectsPortToElement")) - len(bad)
    assert len(f.by_type("IfcRelConnectsPortToElement")) == keep
    return f"{len(bad)} port relations to non-distribution elements became IfcRelNests (same GlobalId, element, port); {keep} others unchanged"


def chk_bspline(src, dsts):
    s = ifcopenshell.open(src); f = ifcopenshell.open(dsts[-1]); n = 0
    for x, y in zip(s.by_type("IfcBSplineSurface"), f.by_type("IfcBSplineSurface")):
        assert [[p.Coordinates for p in r] for r in x.ControlPointsList] == [[p.Coordinates for p in r] for r in y.ControlPointsList]; n += 1
    return f"{n} B-spline surfaces keep all control points, equal to the source"


cases = [
    ("IfcStructuralCurveMember.Axis", "data/corpus/auckland/146_171210CADstudio_brep.ifc", ["structural_axis:"], chk_axis),
    ("IfcRelSpaceBoundary.RelatedBuildingElement (VIRTUAL)", "data/corpus/bs_community_repo/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_Electrical_20121207.ifc",
     ["virtual_boundary_element", "virtual_boundary_containment"], chk_virtual),
    ("IfcWindowType/IfcDoorType PredefinedType, PartitioningType", "data/corpus/bs_community_repo/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc",
     ["enum_default:IfcDoorType", "enum_default:IfcWindowType.PredefinedType", "enum_default:IfcWindowType.PartitioningType"], chk_doorwin),
    ("IfcCurveStyleFontAndScaling.CurveStyleFont", "data/corpus/auckland/094_261110Allplan-2008-Institute-Var-2-IFC.ifc",
     ["rename:IfcCurveStyleFontAndScaling.CurveStyleFont"], chk_curvefont),
    ("IfcMechanicalFastenerType.PredefinedType + StartParam/EndParam", "data/corpus/auckland/141_171210AISC_Sculpture_param.ifc",
     ["enum_default:IfcMechanicalFastenerType", "wrap_select:"], lambda s, d: chk_enum("IfcMechanicalFastenerType")(s, d) + "; " + chk_wrap(s, d)),
    ("IfcDiscreteAccessoryType.PredefinedType", "data/corpus/auckland/236_20220402MODEL LED SCREED 29032022.ifc",
     ["enum_default:IfcDiscreteAccessoryType"], chk_enum("IfcDiscreteAccessoryType")),
    ("IfcSurfaceFeature.AdheresToElement", "data/corpus/bs_official_repo/IFC 4.0.2.1 (IFC 4)/PCERT-Sample-Scene/Infra-Road.ifc",
     ["surface_feature_adheres"], chk_surface),
    ("IfcRelConnectsPortToElement.RelatedElement", "data/corpus/gni/IFC-models/2025_BIMfundamentals/model_189.ifc",
     ["port_nests:"], chk_port),
    ("IfcRationalBSplineSurfaceWithKnots.ControlPointsList", "data/corpus/auckland/246_53d36e5826174834880a795286fa40b1.ifc",
     ["nested_aggregate:"], chk_bspline),
]
res = []
for c in cases:
    say(f"-- {c[0]}")
    res.append(run_case(*c))
say(f"{sum(res)}/{len(res)} cases pass")
open(f"{OUT}/UNIT_TESTS.txt", "w").write("\n".join(lines) + "\n")
