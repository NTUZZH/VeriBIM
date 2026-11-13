"""Extract naming fingerprints per model: IfcTypeObject names, storey names, project name.

Element counts and bounding boxes change a great deal when a scene is derived from a
source model by extracting part of it. Library and family names survive that, so the
overlap of type-object names is an independent check on shared provenance.
"""
import json
import os
import sys
from multiprocessing import Pool

for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[v] = "1"

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT = os.path.join(ROOT, "data", "corpus_build", "names.jsonl")


def work(rel):
    import ifcopenshell
    rec = dict(relpath=rel, type_names=[], storey_names=[], project_name=None,
               application=None, error=None)
    try:
        m = ifcopenshell.open(os.path.join(ROOT, rel))
        rec["type_names"] = sorted({n for o in m.by_type("IfcTypeObject")
                                    if (n := getattr(o, "Name", None))})
        rec["storey_names"] = sorted({n for s in m.by_type("IfcBuildingStorey")
                                      if (n := getattr(s, "Name", None))})
        pr = m.by_type("IfcProject")
        rec["project_name"] = getattr(pr[0], "Name", None) if pr else None
        ap = m.by_type("IfcApplication")
        rec["application"] = ap[0].ApplicationFullName if ap else None
        del m
    except Exception as e:
        rec["error"] = "%s: %s" % (type(e).__name__, str(e)[:120])
    return rec


def main():
    rels = [l.strip() for l in open(sys.argv[1]) if l.strip()]
    print("extracting names for", len(rels), "files")
    with open(OUT, "w") as fh, Pool(5, maxtasksperchild=1) as p:
        for i, r in enumerate(p.imap_unordered(work, rels, chunksize=1)):
            fh.write(json.dumps(r) + "\n")
            fh.flush()
            if (i + 1) % 50 == 0:
                print(i + 1, flush=True)
    print("done ->", OUT)


if __name__ == "__main__":
    main()
