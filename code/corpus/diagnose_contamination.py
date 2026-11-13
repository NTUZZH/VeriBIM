"""Classify every GlobalId shared between the corpus and the BIM-Edit scene files.

The literal rule (any shared GlobalId drops a corpus building) is applied in
build_manifest.py. This script says WHAT is shared, so the contamination evidence
distinguishes a real content overlap from a deterministic exporter GUID.
"""
import gzip
import json
import os
from collections import Counter, defaultdict

import ifcopenshell

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "data", "corpus_build")
GD = os.path.join(ROOT, "data/corpus_guids")
os.chdir(ROOT)
man = json.load(open("data/corpus_manifest.json"))


def gset(sha):
    return set(gzip.open(os.path.join(GD, sha + ".txt.gz"), "rt").read().split("\n")) - {""}

be_union = set()
be_count = Counter()
for r in man["bimedit_reference"]:
    g = gset(r["sha256"])
    be_union |= g
    for x in g:
        be_count[x] += 1

hits = [r for r in man["files"] if r["contamination"]["n_shared_guids"]]
shared_all = set()
per_file = {}
for r in hits:
    s = gset(r["sha256"]) & be_union
    per_file[r["relpath"]] = sorted(s)
    shared_all |= s
print("distinct shared GlobalIds:", len(shared_all))

# class of each shared GUID on the corpus side
corpus_class = {}
for r in hits:
    f = ifcopenshell.open(os.path.join(ROOT, r["relpath"]))
    for g in per_file[r["relpath"]]:
        try:
            corpus_class.setdefault(g, set()).add(f.by_guid(g).is_a())
        except Exception:
            pass
    del f

# class of each shared GUID on the BIM-Edit side
be_class = {}
remaining = set(shared_all)
for r in man["bimedit_reference"]:
    if not remaining:
        break
    g = gset(r["sha256"]) & remaining
    if not g:
        continue
    f = ifcopenshell.open(os.path.join(ROOT, r["relpath"]))
    for x in list(g):
        try:
            e = f.by_guid(x)
            be_class.setdefault(x, set()).add(e.is_a())
        except Exception:
            pass
    del f
    remaining -= set(be_class)

def is_element(classes, schema="IFC4"):
    """True if any class is a placed physical element (not a type, relation or spatial slot)."""
    for c in classes:
        try:
            decl = ifcopenshell.ifcopenshell_wrapper.schema_by_name("IFC4").declaration_by_name(c)
        except Exception:
            continue
        sup = set()
        d = decl
        while d is not None:
            sup.add(d.name())
            d = d.supertype() if hasattr(d, "supertype") else None
        if "IfcElement" in sup:
            return True
    return False

diag = dict(distinct_shared_globalids=len(shared_all), guids={}, per_file={})
for g in sorted(shared_all):
    cc = sorted(corpus_class.get(g, []))
    bc = sorted(be_class.get(g, []))
    diag["guids"][g] = dict(corpus_entity=cc, bimedit_entity=bc,
                            n_bimedit_files=be_count[g],
                            physical_element_both=is_element(cc) and is_element(bc))
for r in hits:
    gs = per_file[r["relpath"]]
    cls = Counter()
    for g in gs:
        cls[";".join(sorted(corpus_class.get(g, ["?"])))] += 1
    diag["per_file"][r["relpath"]] = dict(
        n_shared=len(gs), n_guids_in_file=r["n_guids"],
        shared_fraction=round(len(gs) / max(1, r["n_guids"]), 6),
        corpus_entity_classes=dict(cls),
        n_shared_physical_elements=sum(
            1 for g in gs if diag["guids"][g]["physical_element_both"]),
        max_bimedit_files_per_shared_guid=max((be_count[g] for g in gs), default=0))

cls_all = Counter()
for g, d in diag["guids"].items():
    cls_all[";".join(d["corpus_entity"]) or "?"] += 1
diag["shared_guid_class_histogram"] = dict(cls_all.most_common())
diag["n_shared_physical_element_guids"] = sum(
    1 for d in diag["guids"].values() if d["physical_element_both"])
diag["files_with_shared_physical_elements"] = [
    k for k, v in diag["per_file"].items() if v["n_shared_physical_elements"]]

json.dump(diag, open(os.path.join(WORK, "contam_diag.json"), "w"), indent=1)
print(json.dumps({k: v for k, v in diag.items() if k not in ("guids", "per_file")}, indent=1))
