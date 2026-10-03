"""Scan IFC files: hash, schema, parse, product count, GlobalId set, descriptor.

Usage: scan_ifc.py <filelist.tsv> <out.jsonl> [workers]
filelist.tsv: <collection>\t<abs path>\t<relpath> per line.
GlobalId lists are written to GUIDDIR/<sha256>.txt.gz (shared by identical files).
"""
import gzip
import hashlib
import json
import os
import re
import sys
import traceback
from collections import Counter
from multiprocessing import Pool

for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[v] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUIDDIR = os.path.join(ROOT, "data", "corpus_guids")
os.makedirs(GUIDDIR, exist_ok=True)
SCHEMA_RE = re.compile(rb"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", re.I)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def header_schema(path):
    with open(path, "rb") as fh:
        head = fh.read(4096)
    m = SCHEMA_RE.search(head)
    return m.group(1).decode("ascii", "replace") if m else None


def describe(model):
    """Element-type histogram, storey count, placement bbox (spatial-layout summary)."""
    import ifcopenshell.util.placement as up

    hist = Counter()
    xs, ys, zs = [], [], []
    products = model.by_type("IfcProduct")
    for p in products:
        hist[p.is_a()] += 1
        pl = getattr(p, "ObjectPlacement", None)
        if pl is None or not pl.is_a("IfcLocalPlacement"):
            continue
        try:
            m4 = up.get_local_placement(pl)
        except Exception:
            continue
        xs.append(float(m4[0][3])); ys.append(float(m4[1][3])); zs.append(float(m4[2][3]))
    storeys = model.by_type("IfcBuildingStorey")
    elevs = []
    for s in storeys:
        e = getattr(s, "Elevation", None)
        if e is not None:
            try:
                elevs.append(round(float(e), 4))
            except Exception:
                pass
    bbox = None
    if xs:
        bbox = [round(min(xs), 3), round(min(ys), 3), round(min(zs), 3),
                round(max(xs), 3), round(max(ys), 3), round(max(zs), 3)]
    return dict(
        element_type_histogram=dict(sorted(hist.items())),
        n_products=len(products),
        storey_count=len(storeys),
        storey_elevations=sorted(elevs),
        placement_bbox=bbox,
        n_placements=len(xs),
        n_buildings=len(model.by_type("IfcBuilding")),
        n_sites=len(model.by_type("IfcSite")),
        n_spaces=len(model.by_type("IfcSpace")),
        n_entities=len(model.wrapped_data.entity_names()),
    )


def work(job):
    collection, path, rel = job
    rec = dict(relpath=rel, source_collection=collection,
               bytes=os.path.getsize(path), parse_ok=False, error=None)
    try:
        rec["sha256"] = sha256_of(path)
        rec["ifc_schema_header"] = header_schema(path)
    except Exception as e:
        rec["error"] = "hash/header: %s" % e
        return rec, None
    gpath = os.path.join(GUIDDIR, rec["sha256"] + ".txt.gz")
    try:
        import ifcopenshell
        model = ifcopenshell.open(path)
        rec["ifc_schema"] = model.schema
        rec["ifc_schema_identifier"] = getattr(model, "schema_identifier", None)
        roots = model.by_type("IfcRoot")
        guids = sorted({r.GlobalId for r in roots if getattr(r, "GlobalId", None)})
        rec["n_roots"] = len(roots)
        rec["n_guids"] = len(guids)
        rec["guid_set_sha256"] = hashlib.sha256("\n".join(guids).encode()).hexdigest()
        d = describe(model)
        rec.update({k: d[k] for k in ("n_products", "storey_count", "n_entities")})
        rec["parse_ok"] = True
        if not os.path.exists(gpath):
            with gzip.open(gpath, "wt") as fh:
                fh.write("\n".join(guids))
        del model
        return rec, dict(sha256=rec["sha256"], relpath=rel, source_collection=collection, **d)
    except Exception as e:
        rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:300])
        rec["traceback_head"] = traceback.format_exc().splitlines()[-1][:200]
        return rec, None


def main():
    jobs = []
    for line in open(sys.argv[1]):
        c, p, r = line.rstrip("\n").split("\t")
        jobs.append((c, p, r))
    nw = int(sys.argv[3]) if len(sys.argv) > 3 else 5
    # big files last-in-first-out to balance
    jobs.sort(key=lambda j: -os.path.getsize(j[1]))
    out = open(sys.argv[2], "w")
    desc = open(sys.argv[2] + ".desc.jsonl", "w")
    done = 0
    with Pool(nw, maxtasksperchild=1) as pool:
        for rec, d in pool.imap_unordered(work, jobs, chunksize=1):
            out.write(json.dumps(rec) + "\n"); out.flush()
            if d:
                desc.write(json.dumps(d) + "\n"); desc.flush()
            done += 1
            print("%d/%d %s %s" % (done, len(jobs), "ok " if rec["parse_ok"] else "FAIL",
                                   rec["relpath"][:90]), flush=True)
    out.close(); desc.close()


if __name__ == "__main__":
    main()
