"""Record each model's length unit and its scale to metres.

descriptors' placement_bbox is expressed in each file's own length unit, so any
area comparison across files needs this factor. Adds the unit fields, a metric
bounding box, footprint area in m2 and footprint aspect ratio to
data/corpus_descriptors.json in place.
"""
import json
import os
from multiprocessing import Pool

for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESC = os.path.join(ROOT, "data", "corpus_descriptors.json")


def work(rel):
    import ifcopenshell
    import ifcopenshell.util.unit as uu
    out = dict(relpath=rel, unit_scale_to_m=None, length_unit=None, error=None)
    try:
        m = ifcopenshell.open(os.path.join(ROOT, rel))
        out["unit_scale_to_m"] = float(uu.calculate_unit_scale(m))
        for ua in m.by_type("IfcUnitAssignment"):
            for u in ua.Units:
                if getattr(u, "UnitType", None) == "LENGTHUNIT":
                    if u.is_a("IfcSIUnit"):
                        out["length_unit"] = "%s%s" % (u.Prefix or "", u.Name)
                    else:
                        out["length_unit"] = getattr(u, "Name", u.is_a())
                    break
        del m
    except Exception as e:
        out["error"] = "%s: %s" % (type(e).__name__, str(e)[:150])
    return out


def main():
    d = json.load(open(DESC))
    rels = sorted(set(d["corpus"]) | set(d["bimedit"]))
    print("resolving units for", len(rels), "files")
    res = {}
    with Pool(5, maxtasksperchild=1) as p:
        for i, r in enumerate(p.imap_unordered(work, rels, chunksize=1)):
            res[r["relpath"]] = r
            if (i + 1) % 50 == 0:
                print(i + 1, flush=True)
    n_ok = 0
    for section in ("corpus", "bimedit"):
        for rel, rec in d[section].items():
            u = res.get(rel, {})
            s = u.get("unit_scale_to_m")
            rec["length_unit"] = u.get("length_unit")
            rec["unit_scale_to_m"] = s
            bb = rec.get("placement_bbox")
            if bb and s:
                mb = [round(v * s, 4) for v in bb]
                dx, dy, dz = mb[3] - mb[0], mb[4] - mb[1], mb[5] - mb[2]
                rec["placement_bbox_m"] = mb
                rec["footprint_m2"] = round(dx * dy, 4)
                rec["footprint_aspect"] = (round(max(dx, dy) / min(dx, dy), 4)
                                           if min(dx, dy) > 1e-9 else None)
                rec["height_m"] = round(dz, 4)
                n_ok += 1
            else:
                rec["placement_bbox_m"] = None
                rec["footprint_m2"] = None
                rec["footprint_aspect"] = None
                rec["height_m"] = None
    d["note_units"] = ("length_unit / unit_scale_to_m come from IfcUnitAssignment via "
                       "ifcopenshell.util.unit.calculate_unit_scale; placement_bbox_m, "
                       "footprint_m2, footprint_aspect and height_m are the metric form of "
                       "placement_bbox.")
    json.dump(d, open(DESC, "w"), indent=1)
    print("metric bbox available for %d of %d files" % (n_ok, len(rels)))
    bad = [r for r in res.values() if r["error"]]
    print("unit resolution errors:", len(bad))
    for r in bad[:5]:
        print("  ", r["relpath"][-70:], r["error"][:90])


if __name__ == "__main__":
    main()
