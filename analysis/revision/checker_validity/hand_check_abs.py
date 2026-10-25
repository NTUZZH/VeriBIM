"""Hand check of analysis 2: read the target's placement and tessellated box in the
ground truth and in the stored output, independently of gate_abs.py."""
import sys, json, tarfile, shutil
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.placement as pu, ifcopenshell.util.unit as uu

def member(arm, tid, dest):
    rows = C.per_task_rows(arm)
    named = Path(rows[tid]["edited_ifc"])
    tar = C.edited_dir(arm) / "edited.tar.gz"
    with tarfile.open(tar, "r|gz") as tf:
        for m in tf:
            if m.isfile() and Path(m.name).parts[1] == tid:
                out = dest / Path(m.name).name
                with tf.extractfile(m) as s, open(out, "wb") as d:
                    shutil.copyfileobj(s, d)
                return out

def describe(path, guid=None, name=None):
    f = ifcopenshell.open(str(path))
    e = f.by_guid(guid) if guid else [x for x in f.by_type("IfcProduct") if x.Name == name][0]
    s = ifcopenshell.geom.settings(); s.set("use-world-coords", True)
    sh = ifcopenshell.geom.create_shape(s, e)
    v = np.asarray(sh.geometry.verts).reshape(-1, 3)
    M = np.asarray(pu.get_local_placement(e.ObjectPlacement))
    sc = uu.calculate_unit_scale(f)
    attrs = {k: getattr(e, k, None) for k in ("OverallHeight", "OverallWidth")}
    print(f"  {e.is_a()} {e.GlobalId} name={e.Name!r} placement_origin_m={np.round(M[:3,3]*sc,4).tolist()} "
          f"box_lo={np.round(v.min(0),4).tolist()} box_hi={np.round(v.max(0),4).tolist()} extent={np.round(v.max(0)-v.min(0),4).tolist()} {attrs}")

if __name__ == "__main__":
    tasks = C.load_tasks()
    dest = C.TMP / "hand"; dest.mkdir(exist_ok=True)
    def kw(k):
        return {"name": k[5:]} if k.startswith("name=") else {"guid": k}
    for spec in sys.argv[1:]:
        arm, tid, gk, ok = spec.split("|")
        rec = tasks[tid]
        gold = C.unpack_gold(rec, dest)
        out = member(arm, tid, dest)
        print(tid, arm, rec["instruction"][:200])
        print(" ground truth:"); describe(gold, **kw(gk))
        print(" output:"); describe(out, **kw(ok))
        gold.unlink(); out.unlink()
