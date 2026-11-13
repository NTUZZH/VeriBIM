"""Unit test of migrator v2 on one source: migrate (via IFC4 for IFC2X3), validate source and outputs, compare keys."""
import sys, os, json, time, resource
os.environ["OMP_NUM_THREADS"] = "1"
sys.path.insert(0, "scripts/corpus/migrator_v2")
import ifcopenshell
from migrate_v2 import migrate
from vkeys import validate_keys
src, out = sys.argv[1], sys.argv[2]; os.makedirs(out, exist_ok=True)
stem = os.path.basename(src)[:-4].replace(" ", "_")
f = ifcopenshell.open(src); sch = f.schema; ks, _ = validate_keys(f); del f
print("SOURCE", sch, dict(ks))
cur = src; reps = []
if sch == "IFC2X3":
    d4 = f"{out}/{stem}__IFC4.ifc"; reps.append(migrate(cur, "IFC4", d4)); cur = d4
d43 = f"{out}/{stem}__IFC4X3.ifc"; reps.append(migrate(cur, "IFC4X3", d43))
for r in reps:
    g = ifcopenshell.open(r["dst"]); k, s = validate_keys(g, samples=1); del g
    new = {x: v for x, v in k.items() if v > ks.get(x, 0)}
    print("==", r["target"], r["seconds"], "s", "errors", r["errors"], "dropped", r["dropped_attributes"])
    print("   rules", r["rules"]); print("   carried", r["carried_nulls"], "unhandled", r["unhandled_nulls"])
    print("   issues", dict(k)); print("   NEW vs source:", new)
    for x in new: print("   sample", s[x][0][:600])
print("peak RSS GB", round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2))
