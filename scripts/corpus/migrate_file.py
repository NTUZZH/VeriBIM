"""Migrate one IFC file to IFC4X3 (IFC2X3 sources go through IFC4 first), with the same Migrator subclass
as probe_migrate.py. Usage: migrate_file.py <src> <dst_dir>  -> <dst_dir>/<stem>__IFC4X3.ifc (+ .json report)"""
import sys, os, json, time, collections
from pathlib import Path
sys.path.insert(0, "scripts/corpus")
os.environ["OMP_NUM_THREADS"]="1"
import ifcopenshell
# reuse the subclass by importing the probe module's namespace without running its CLI
src_code = open("scripts/corpus/probe_migrate.py").read().split("ap=argparse.ArgumentParser()")[0]
ns = {}; exec(compile(src_code, "probe_migrate_lib", "exec"), ns)
migrate_one = ns["migrate_one"]
src, dst_dir = sys.argv[1], Path(sys.argv[2]); dst_dir.mkdir(parents=True, exist_ok=True)
stem = Path(src).stem.replace(" ", "_")
f = ifcopenshell.open(src); schema = f.schema; del f
rep = [{"src": src, "schema": schema}]
cur = src
if schema == "IFC2X3":
    d4 = dst_dir / f"{stem}__IFC4.ifc"; rep.append(migrate_one(cur, "IFC4", d4)); cur = str(d4)
elif not schema.startswith("IFC4"):
    print("unsupported", schema); sys.exit(2)
d43 = dst_dir / f"{stem}__IFC4X3.ifc"; rep.append(migrate_one(cur, "IFC4X3", d43))
json.dump(rep, open(dst_dir / f"{stem}__migrate.json", "w"), indent=1)
print(stem, schema, [(r.get("target"), r.get("seconds"), r.get("n_errors")) for r in rep[1:]])
