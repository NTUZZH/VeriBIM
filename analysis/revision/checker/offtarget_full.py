"""Comprehensive off-target diff of completed edits against the ground truth.

For every completed edit (C = 1: geometry, semantics and topology all >= 0.9 in
the run's own per-task record) of one arm, the edited model E is compared with
the ground-truth model G over all entities, with the source model I as the
reference for what the ground truth itself changes.

What is compared (entities matched by GlobalId):
  objects     every IfcObjectDefinition (products, type objects, groups, ...):
              presence, world placement, representation (products), and every
              direct attribute (Name, ObjectType, PredefinedType, Tag and the rest)
  relations   every IfcRelationship except IfcRelDefinesByProperties, read as
              edges (relation class, relating end, related end, other attributes);
              an end that has no GlobalId (a material, a layer set) is read
              through its content; relationship GlobalIds are not compared
  properties  every property set, quantity set and property-set definition
              attached through IfcRelDefinesByProperties or a type's
              HasPropertySets, read per element as (set name, property name) ->
              value; property-set GlobalIds are not compared
  listed only header (FILE_NAME, FILE_DESCRIPTION), owner histories, and
              relationship / property-set GlobalIds that differ while the content
              is equal; these are reported and never counted

Off-target, per class:
  geometry/placement  a product outside the exclusion set that E adds, removes,
                      or places or shapes differently from G
  attribute           an object outside the exclusion set with a direct attribute
                      that differs between E and G
  relation            a relation edge present in only one of E and G, that the
                      ground truth did not itself change, with no end in the
                      exclusion set and no end that E added or removed (those
                      edges are attributed to the added or removed object)
  property            an element outside the exclusion set whose property map
                      differs between E and G
  other objects       a non-product object (type object, group) E adds or removes

Exclusion set: the task's target GlobalIds and edit_guids (target, touched,
created, removed) from the task record, every object the ground truth creates,
deletes or modifies (placement, representation, attribute), and for the
property class every element whose properties the ground truth changes.

Objects E creates are paired with objects G creates, by class family (StandardCase
and ElementedCase suffixes dropped) and nearest placement origin, and then
speak under G's GlobalId; a pairing with a target that E removed and re-created
under a new GlobalId is listed as 'target re-identified' and not counted.
Any other changed GlobalId is a removal plus an addition.

Usage:
  python offtarget_full.py validate            # five gold-vs-source pairs and injected controls
  python offtarget_full.py run --arm <name>    # one arm, appends offtarget_full.jsonl
  python offtarget_full.py summarize
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import os
import pickle
import re
import shutil
import statistics
import sys
import tarfile
import threading
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("VERIBIM_ROOT", "."))
BENCH = ROOT / "runs_local/bench_v4"
RES = BENCH / "results"
OUT = ROOT / "analysis/revision/checker"
SCRATCH = Path(os.environ.get("VERIBIM_SCRATCH", "work/checker"))   # working copies of the models
TASKS = BENCH / "tasks.v4c.jsonl"
GOLD_DIRS = ("models_v4c", "models_v4b", "models")
ROWS = Path(os.environ.get("OFFTARGET_ROWS", str(OUT / "offtarget_full.jsonl")))
FP_CACHE = SCRATCH / "fp"
LIST_CAP = 60
MIN_FREE_GB = 32.0
FAST = os.environ.get("OFFTARGET_FULL_HASH", "0") != "1"

ARMS = {
    "final_full": ("full_all/per_task_grpo_v10b_c10.jsonl", "full_all/grpo_v10b_c10/edited.tar.gz"),
    "final_108": ("local108_lib_all/per_task_grpo_v10b_c10.jsonl",
                  "local108_lib_all/grpo_v10b_c10/edited.tar.gz"),
    "imitation_108": ("local108_lib_all/per_task_sft_v10.jsonl", "local108_lib_all/sft_v10/edited.tar.gz"),
    "claude-sonnet-5-5_108": ("hosted108_lib_all/per_task_claude-sonnet-5-5.jsonl",
                              "hosted108_lib_all/claude-sonnet-5-5/edited.tar.gz"),
    "gpt-5.6-luna_108": ("hosted108_lib_all/per_task_gpt-5.6-luna.jsonl",
                         "hosted108_lib_all/gpt-5.6-luna/edited.tar.gz"),
    "gemini-3.8-flash_108": ("hosted108_lib_all/per_task_gemini-3.8-flash.jsonl",
                             "hosted108_lib_all/gemini-3.8-flash/edited.tar.gz"),
    "deepseek-v4-pro_108": ("hosted108_lib_all/per_task_deepseek-v4-pro.jsonl",
                            "hosted108_lib_all/deepseek-v4-pro/edited.tar.gz"),
}

NAMED_ATTRS = ("Name", "ObjectType", "PredefinedType", "Tag")
SKIP_ATTRS = {"GlobalId", "OwnerHistory", "ObjectPlacement", "Representation",
              "HasPropertySets", "RepresentationMaps"}
REL_SKIP = {"GlobalId", "OwnerHistory", "Name", "Description"}

sys.path.insert(0, str(ROOT / "code"))


# ---------------------------------------------------------------- inputs


def load_tasks() -> dict[str, dict]:
    with open(TASKS, encoding="utf-8") as fh:
        return {r["task_id"]: r for r in (json.loads(l) for l in fh if l.strip())}


def completed(row: dict) -> bool:
    s = row.get("score") or {}
    try:
        return all(s.get(k) is not None and float(s[k]) >= 0.9
                   for k in ("geometry", "semantics", "topology"))
    except (TypeError, ValueError):
        return False


def mem_available_gb() -> float:
    with open("/proc/meminfo") as fh:
        for line in fh:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1e6
    return 99.0


def free_gb() -> float:
    st = os.statvfs("/home")
    return st.f_bavail * st.f_frsize / 1e9


def unpack_gold(record: dict, dest: Path) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    named = [ROOT / (str(record.get(k) or "") + ".gz") for k in ("ground_truth_ifc", "gold_model")]
    cands = [p for p in named if record.get("ground_truth_ifc") and p.is_file()] + \
        [BENCH / d / f"{record['task_id']}.ifc.gz" for d in GOLD_DIRS]
    src = next(p for p in cands if p.is_file())
    out = dest / f"{record['task_id']}.gold.ifc"
    h = hashlib.sha256()
    with gzip.open(src, "rb") as fi, open(out, "wb") as fo:
        for block in iter(lambda: fi.read(1 << 20), b""):
            h.update(block)
            fo.write(block)
    exp = (record.get("verification") or {}).get("gold_sha256")
    if exp and h.hexdigest() != exp:
        out.unlink()
        raise ValueError("gold sha256 mismatch")
    return out


# ---------------------------------------------------------------- fingerprint


def _family(cls: str) -> str:
    return re.sub(r"(StandardCase|ElementedCase)$", "", cls)


def fingerprint(model, obj_guids: set | None = None, rel_ids: set | None = None,
                elem_guids: set | None = None) -> dict:
    """Everything the diff compares, with no entity ids (#n) in it.

    With the three restriction sets left out, every object, relationship and
    property map is read (the full fingerprint, used for the source model and
    for validation).  With them given, only those objects (by GlobalId), those
    relationships (by entity id) and the property maps of those elements are
    read; the caller passes every entity whose serialised graph differs between
    the models compared, so nothing outside the sets can differ.  Both modes run
    the same code for each item they read.
    """
    from stage_c.offtarget import ProductHasher
    hz = ProductHasher(model)
    objs: dict[str, dict] = {}
    all_guids: set = set()
    dup = 0
    for o in model.by_type("IfcObjectDefinition"):
        g = o.GlobalId
        if g in all_guids:
            dup += 1
            continue
        all_guids.add(g)
        if obj_guids is not None and g not in obj_guids:
            continue
        names = hz._attr_names(o)
        attrs = {}
        place = repr_ = local = "-"
        origin = None
        for i, n in enumerate(names):
            if n in SKIP_ATTRS:
                continue
            try:
                attrs[n] = hz._value(o[i])
            except Exception:
                attrs[n] = "<unreadable>"
        if o.is_a("IfcProduct"):
            _cls, place, repr_, _ah, local = hz.signature(o)
            pl = getattr(o, "ObjectPlacement", None)
            if pl is not None:
                M = hz._world_matrix(pl)
                if M is not None:
                    origin = tuple(float(x) for x in M[:3, 3])
        elif o.is_a("IfcTypeProduct") and getattr(o, "RepresentationMaps", None):
            repr_ = hashlib.blake2b(repr([hz._entity(x) for x in o.RepresentationMaps]).encode(),
                                    digest_size=16).hexdigest()
        objs[g] = {"cls": o.is_a(), "product": o.is_a("IfcProduct"), "place": place,
                   "local": local, "repr": repr_, "attrs": attrs, "origin": origin,
                   "name": getattr(o, "Name", None)}

    def key(x):
        if x is None:
            return None
        try:
            if x.is_a("IfcRoot"):
                return ("g", x.GlobalId)
        except Exception:
            return ("v", repr(x))
        return ("c", x.is_a(), hz._entity(x).hex())

    def rel_edges(rel) -> list:
        names = hz._attr_names(rel)
        relating, related, extra = [], [], []
        for i, n in enumerate(names):
            if n in REL_SKIP:
                continue
            v = rel[i]
            vals = v if isinstance(v, (list, tuple)) else [v]
            # an end is an entity; priorities and connection types are attributes
            is_end = bool(vals) and all(hasattr(x, "is_a") and hasattr(x, "id") and x.id() != 0
                                        for x in vals)
            if is_end and n.startswith("Relating"):
                relating.extend(vals)
            elif is_end and n.startswith("Related"):
                related.extend(vals)
            else:
                extra.append((n, hz._value(v)))
        xh = hashlib.blake2b(repr(extra).encode(), digest_size=8).hexdigest() if extra else "-"
        out = []
        for a in relating or [None]:
            for b in related or [None]:
                out.append((rel.is_a(), key(a), key(b), xh))
        return out

    def is_prop_rel(rel) -> bool:
        return rel.is_a("IfcRelDefinesByProperties") or rel.is_a("IfcRelDefinesByTemplate")

    edges: collections.Counter = collections.Counter()
    rel_edges_by_id: dict[int, list] = {}
    rel_guids: dict[str, str] = {}
    pset_guids: dict[str, str] = {}
    for rel in model.by_type("IfcRelationship"):
        rel_guids[rel.GlobalId] = rel.is_a()
        if rel.is_a("IfcRelDefinesByProperties"):
            defs = rel.RelatingPropertyDefinition
            for d in (list(defs) if isinstance(defs, (list, tuple)) else [defs]):
                if d is not None:
                    pset_guids[d.GlobalId] = d.is_a()
        if is_prop_rel(rel):
            continue
        if rel_ids is not None and rel.id() not in rel_ids:
            continue
        es = rel_edges(rel)
        if rel_ids is None:
            rel_edges_by_id[rel.id()] = es
        for e in es:
            edges[e] += 1
    for t in model.by_type("IfcTypeObject"):
        for d in t.HasPropertySets or ():
            pset_guids[d.GlobalId] = d.is_a()

    def pset_items(d) -> dict:
        out = {}
        if d.is_a("IfcPropertySet"):
            for p in d.HasProperties or ():
                if p.is_a("IfcPropertySingleValue"):
                    val = hz._value(p.NominalValue)
                else:
                    val = hz._entity(p).hex()
                out[(d.Name or "", p.Name or "")] = val
        elif d.is_a("IfcElementQuantity"):
            for q in d.Quantities or ():
                out[(d.Name or "", q.Name or "")] = hz._entity(q).hex()
        else:
            names = hz._attr_names(d)
            vals = [(n, hz._value(d[i])) for i, n in enumerate(names) if n not in ("GlobalId", "OwnerHistory")]
            out[(d.is_a(), "*")] = hashlib.blake2b(repr(vals).encode(), digest_size=16).hexdigest()
        return out

    def merge(parts: list) -> dict:
        """(order key, items) pairs merged in a fixed order, duplicates kept as a pair."""
        out: dict = {}
        for _k, items in sorted(parts, key=lambda x: x[0]):
            for k, v in items.items():
                out[k] = v if k not in out else repr(sorted([out[k], v], key=repr))
        return out

    def element_props(o) -> dict:
        parts = []
        for rel in getattr(o, "IsDefinedBy", None) or ():
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            defs = rel.RelatingPropertyDefinition
            items = {}
            for d in (list(defs) if isinstance(defs, (list, tuple)) else [defs]):
                if d is None:
                    continue
                for k, v in pset_items(d).items():
                    items[k] = v if k not in items else repr(sorted([items[k], v], key=repr))
            parts.append(((0, rel.id()), items))
        if o.is_a("IfcTypeObject"):
            for n, d in enumerate(o.HasPropertySets or ()):
                parts.append(((1, n), pset_items(d)))
        return merge(parts)

    props: dict[str, dict] = {}
    if elem_guids is None:
        seen = set()
        for rel in model.by_type("IfcRelDefinesByProperties"):
            for o in rel.RelatedObjects or ():
                seen.add(o.id())
        for t in model.by_type("IfcTypeObject"):
            if t.HasPropertySets:
                seen.add(t.id())
        for i in sorted(seen):
            o = model.by_id(i)
            if o.GlobalId in props:
                continue
            m = element_props(o)
            if m:
                props[o.GlobalId] = m
    else:
        for g in sorted(elem_guids):
            try:
                o = model.by_guid(g)
            except Exception:
                continue
            props[g] = element_props(o)

    hdr = model.header
    try:
        header = repr((tuple(hdr.file_description.description), hdr.file_name.name,
                       hdr.file_name.time_stamp, tuple(hdr.file_name.author),
                       tuple(hdr.file_name.organization), hdr.file_name.preprocessor_version,
                       hdr.file_name.originating_system, hdr.file_name.authorization))
    except Exception:
        header = "<unreadable>"
    oh = sorted(hz._entity(h).hex() for h in model.by_type("IfcOwnerHistory"))
    return {"objs": objs, "all_guids": all_guids, "edges": edges, "rel_edges_by_id": rel_edges_by_id,
            "props": props, "rel_guids": rel_guids,
            "pset_guids": pset_guids, "header": header,
            "owner_histories": hashlib.blake2b(repr(oh).encode(), digest_size=16).hexdigest(),
            "n_owner_histories": len(oh), "dup_guids": dup, "schema": str(model.schema),
            "restricted": None if obj_guids is None else {"rel_ids": set(rel_ids or ()),
                                                          "obj_guids": set(obj_guids),
                                                          "elem_guids": set(elem_guids or ())}}


def fp_file(path: Path) -> dict:
    import ifcopenshell
    m = ifcopenshell.open(str(path))
    try:
        return fingerprint(m)
    finally:
        del m


def fp_cached(kind: str, key: str, path_fn) -> dict:
    """A fingerprint from the scratch cache, computed on a miss."""
    FP_CACHE.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(f"{kind}:{key}".encode()).hexdigest()[:20]
    p = FP_CACHE / f"{kind}_{name}.pkl"
    if p.is_file():
        with open(p, "rb") as fh:
            return pickle.load(fh)
    fp = fp_file(path_fn())
    tmp = p.with_suffix(f".tmp{os.getpid()}")
    with open(tmp, "wb") as fh:
        pickle.dump(fp, fh, protocol=pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, p)
    return fp


# ---------------------------------------------------------------- diff


def obj_changed(a: dict, b: dict) -> list[str]:
    parts = []
    if _family(a["cls"]) != _family(b["cls"]):
        parts.append("class")
    if a["place"] != b["place"]:
        parts.append("placement" if a["local"] != b["local"] else "placement_carried")
    if a["repr"] != b["repr"]:
        parts.append("representation")
    for n in sorted(set(a["attrs"]) | set(b["attrs"])):
        if a["attrs"].get(n) != b["attrs"].get(n):
            parts.append("attr:" + n)
    return parts


def changed_by(fi: dict, fx: dict) -> dict:
    """Objects, edges and property maps X changed relative to I (I is a full fingerprint)."""
    oi, ox = fi["objs"], fx["objs"]
    created = fx["all_guids"] - fi["all_guids"]
    deleted = fi["all_guids"] - fx["all_guids"]
    modified = {g for g in ox if g in oi and obj_changed(oi[g], ox[g])}
    R = fx.get("restricted")
    if R is None:
        ei, ex = fi["edges"], fx["edges"]
        pkeys = set(fi["props"]) | set(fx["props"])
    else:
        # the source's edges of exactly the relationships read in X
        ei = collections.Counter()
        for i in R["rel_ids"]:
            for e in fi["rel_edges_by_id"].get(i, ()):
                ei[e] += 1
        ex = fx["edges"]
        pkeys = R["elem_guids"]
    dedges = set((ei - ex) + (ex - ei))
    pi, px = fi["props"], fx["props"]
    dprops = {g for g in pkeys if pi.get(g, {}) != px.get(g, {})}
    return {"created": created, "deleted": deleted, "modified": modified,
            "edges": dedges, "props": dprops}


def pair_created(fe: dict, fg: dict, cre_e: set, cre_g: set, missing_targets: set) -> tuple[dict, dict]:
    """E GlobalId -> G GlobalId for created objects, and re-identified targets."""
    oe, og = fe["objs"], fg["objs"]

    def cost(e, g):
        a, b = oe[e]["origin"], og[g]["origin"]
        if a is None or b is None:
            return 0.0 if (oe[e].get("name") == og[g].get("name")) else 1e9
        return float(np.linalg.norm(np.array(a) - np.array(b)))

    mapping, reid = {}, {}
    for pool, out in ((cre_g, mapping), (missing_targets, reid)):
        cands = []
        for e in cre_e:
            if e in mapping or e in reid or e not in oe:
                continue
            for g in pool:
                if g not in og:
                    continue
                if _family(oe[e]["cls"]) == _family(og[g]["cls"]):
                    cands.append((cost(e, g), e, g))
        cands.sort()
        used_e, used_g = set(), set()
        for c, e, g in cands:
            if e in used_e or g in used_g or c >= 1e9:
                continue
            used_e.add(e)
            used_g.add(g)
            out[e] = g
    return mapping, reid


def canon_edges(edges: collections.Counter, mp: dict) -> collections.Counter:
    def k(x):
        if x and x[0] == "g" and x[1] in mp:
            return ("g", mp[x[1]])
        return x
    out = collections.Counter()
    for (cls, a, b, xh), n in edges.items():
        out[(cls, k(a), k(b), xh)] += n
    return out


def diff_task(fi: dict, fg: dict, fe: dict, record: dict | None) -> dict:
    """The comprehensive off-target set of E against G, with I as the reference."""
    targets = set()
    if record is not None:
        targets |= set((record.get("target") or {}).get("guids") or ())
        eg = record.get("edit_guids") or {}
        for k in ("target", "touched", "created", "removed"):
            targets |= set(eg.get(k) or ())
    cg = changed_by(fi, fg)
    ce = changed_by(fi, fe)
    x_obj = targets | cg["created"] | cg["deleted"] | cg["modified"]
    x_prop = x_obj | cg["props"]
    oi, og, oe = fi["objs"], fg["objs"], fe["objs"]
    ag, ae = fg["all_guids"], fe["all_guids"]
    missing_targets = {g for g in targets if g in ag and g not in ae}
    mp, reid = pair_created(fe, fg, ce["created"], cg["created"], missing_targets)
    allmap = dict(mp)
    allmap.update(reid)

    def c(g):
        return allmap.get(g, g)

    oe_c = {c(g): v for g, v in oe.items()}
    pe_c = {c(g): v for g, v in fe["props"].items()}
    ee_c = canon_edges(fe["edges"], allmap)

    geo, attr, other, prop, rel = [], [], [], [], []
    ae_c = {c(g) for g in ae}
    added = ae_c - ag
    removed = ag - ae_c
    unknown = {"cls": "?", "product": True, "name": None}
    for g in sorted(added - x_obj):
        v = oe_c.get(g, unknown)
        item = {"guid": g, "class": v["cls"], "kind": "added", "name": v.get("name")}
        (geo if v["product"] else other).append(item)
    for g in sorted(removed - x_obj):
        v = og.get(g, unknown)
        item = {"guid": g, "class": v["cls"], "kind": "removed", "name": v.get("name")}
        (geo if v["product"] else other).append(item)
    for g in sorted(set(og) & set(oe_c) - x_obj):
        parts = obj_changed(og[g], oe_c[g])
        if not parts:
            continue
        gparts = [p for p in parts if not p.startswith("attr:")]
        aparts = [p[5:] for p in parts if p.startswith("attr:")]
        if gparts:
            geo.append({"guid": g, "class": og[g]["cls"], "kind": "modified", "parts": gparts,
                        "name": og[g].get("name")})
        if aparts:
            attr.append({"guid": g, "class": og[g]["cls"], "attrs": aparts,
                         "named": [a for a in aparts if a in NAMED_ATTRS],
                         "name": og[g].get("name")})
    for g in sorted((set(fg["props"]) | set(pe_c)) - x_prop):
        if g not in ag or g not in ae_c:
            continue
        a, b = fg["props"].get(g, {}), pe_c.get(g, {})
        if a != b:
            keys = sorted({k for k in set(a) | set(b) if a.get(k) != b.get(k)})
            v = og.get(g) or oe_c.get(g) or unknown
            prop.append({"guid": g, "class": v["cls"], "n_keys": len(keys),
                         "keys": [f"{k[0]}.{k[1]}" for k in keys[:8]], "name": v.get("name")})
    eg_ = fg["edges"]
    dE = set((ee_c - eg_) + (eg_ - ee_c))
    gone_or_new = added | removed
    edges_of_added_removed = 0
    for e in sorted(dE, key=repr):
        cls, a, b, xh = e
        if e in cg["edges"]:
            continue
        ends = [x[1] for x in (a, b) if x and x[0] == "g"]
        if any(g in x_obj for g in ends):
            continue
        if any(g in gone_or_new for g in ends):
            edges_of_added_removed += 1
            continue
        side = "in edited only" if ee_c[e] > eg_[e] else "in ground truth only"
        rel.append({"relation": cls, "relating": a[1] if a and a[0] == "g" else (a[1] if a else None),
                    "related": b[1] if b and b[0] == "g" else (b[1] if b else None),
                    "side": side})
    out = {
        "n_geometry": len(geo), "n_attribute": len(attr), "n_relation": len(rel),
        "n_property": len(prop), "n_other_objects": len(other),
        "n_attribute_named": sum(1 for a in attr if a["named"]),
        "edges_of_added_removed": edges_of_added_removed,
        "geometry": geo[:LIST_CAP], "attribute": attr[:LIST_CAP], "relation": rel[:LIST_CAP],
        "property": prop[:LIST_CAP], "other_objects": other[:LIST_CAP],
        "n_created_paired": len(mp), "target_reidentified": sorted(reid.items()),
        "n_excluded_objects": len(x_obj),
        # listed only, never counted
        "header_differs": fg["header"] != fe["header"],
        "owner_history_differs": fg["owner_histories"] != fe["owner_histories"],
        "relationship_ids_only": _ids_only(fg["rel_guids"], fe["rel_guids"], fi["rel_guids"]),
        "property_set_ids_only": _ids_only(fg["pset_guids"], fe["pset_guids"], fi["pset_guids"]),
        "dup_guids": {"I": fi["dup_guids"], "G": fg["dup_guids"], "E": fe["dup_guids"]},
    }
    out["n_any"] = out["n_geometry"] + out["n_attribute"] + out["n_relation"] + \
        out["n_property"] + out["n_other_objects"]
    return out


def _ids_only(g: dict, e: dict, i: dict) -> dict:
    """Relationship or set GlobalIds of the source that one side dropped or renewed."""
    gi = set(g) & set(i)
    return {"in_ground_truth_not_edited": len(gi - set(e)),
            "in_edited_not_ground_truth": len(set(e) - set(g))}


def raw_diff(fa: dict, fb: dict) -> dict:
    """Everything that differs from A to B, nothing excluded (for validation)."""
    ch = changed_by(fa, fb)
    oa, ob = fa["objs"], fb["objs"]
    return {
        "created": sorted((ob[g]["cls"], ob[g].get("name"), g) for g in ch["created"]),
        "deleted": sorted((oa[g]["cls"], oa[g].get("name"), g) for g in ch["deleted"]),
        "modified": sorted((ob[g]["cls"], ob[g].get("name"), g, tuple(obj_changed(oa[g], ob[g])))
                           for g in ch["modified"]),
        "edges_added": sorted([repr(e) for e in (fb["edges"] - fa["edges"])]),
        "edges_removed": sorted([repr(e) for e in (fa["edges"] - fb["edges"])]),
        "props_changed": sorted(
            (g, sorted(f"{k[0]}.{k[1]}" for k in set(fa['props'].get(g, {})) | set(fb['props'].get(g, {}))
                       if fa['props'].get(g, {}).get(k) != fb['props'].get(g, {}).get(k)))
            for g in ch["props"]),
        "header_differs": fa["header"] != fb["header"],
        "owner_history_differs": fa["owner_histories"] != fb["owner_histories"],
    }


# ---------------------------------------------------------------- per task


_T: dict = {}


def _tasks() -> dict:
    if "tasks" not in _T:
        _T["tasks"] = load_tasks()
        _T["sub108"] = set(json.load(open(BENCH / "subset_108_hosted.v4c.json")))
    return _T["tasks"]


def _init() -> None:
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    sys.setrecursionlimit(20000)


def gold_fp(record: dict) -> dict:
    work = SCRATCH / f"g{os.getpid()}"

    def make() -> Path:
        return unpack_gold(record, work)

    if record["task_id"] in _T["sub108"]:
        FP_CACHE.mkdir(parents=True, exist_ok=True)
        name = hashlib.sha1(f"gold:{record['task_id']}".encode()).hexdigest()[:20]
        p = FP_CACHE / f"gold_{name}.pkl"
        if p.is_file():
            with open(p, "rb") as fh:
                return pickle.load(fh)
    path = make()
    try:
        fp = fp_file(path)
    finally:
        path.unlink(missing_ok=True)
    if record["task_id"] in _T["sub108"]:
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        with open(tmp, "wb") as fh:
            pickle.dump(fp, fh, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, p)
    return fp


def source_fp(record: dict) -> dict:
    return fp_cached("src", record["input_ifc"], lambda: ROOT / record["input_ifc"])


def source_roundtrip(record: dict) -> Path:
    """The source model written once by IfcOpenShell (same serialisation as G and E)."""
    import ifcopenshell
    d = SCRATCH / "roundtrip"
    d.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(record["input_ifc"].encode()).hexdigest()[:20] + ".ifc"
    p = d / name
    if not p.is_file():
        m = ifcopenshell.open(str(ROOT / record["input_ifc"]))
        tmp = p.with_suffix(f".tmp{os.getpid()}")
        m.write(str(tmp))
        os.replace(tmp, p)
    return p


def textmap(path: Path) -> dict:
    """Entity id -> serialised line of the DATA section."""
    with open(path, "rb") as fh:
        data = fh.read()
    a = data.find(b"\nDATA;")
    b = data.find(b"\nENDSEC;", a)
    out = {}
    for line in data[a + 6:b].split(b";\n"):
        line = line.strip()
        if line.startswith(b"#"):
            i = line.find(b"=")
            out[int(line[1:i])] = line[i + 1:]
    return out


def dirty(ta: dict, tb: dict) -> set:
    ids = set(ta) | set(tb)
    return {i for i in ids if ta.get(i) != tb.get(i)}


def upward(models: list, seeds: set) -> set:
    """Every entity that references a seed, directly or through other entities."""
    seen = set(seeds)
    stack = list(seeds)
    while stack:
        i = stack.pop()
        for m in models:
            try:
                e = m.by_id(i)
            except Exception:
                continue
            for inv in m.get_inverse(e):
                j = inv.id()
                if j not in seen:
                    seen.add(j)
                    stack.append(j)
    return seen


def fast_fps(record: dict, gold: Path, edited: Path, fi: dict) -> tuple[dict, dict, dict]:
    """Restricted fingerprints of G and E.

    The three files share IfcOpenShell's serialisation and keep the source's
    entity ids, so an entity whose line and whose referenced entities' lines are
    identical in two files is identical in content.  Every entity whose line
    differs between the source and G or between G and E, and every entity that
    references one of those (directly or through others), is read; nothing else
    can differ.
    """
    import ifcopenshell
    t_i = textmap(source_roundtrip(record))
    t_g = textmap(gold)
    t_e = textmap(edited)
    d_ig = dirty(t_i, t_g)
    d_ge = dirty(t_g, t_e)
    del t_i, t_g, t_e
    mg = ifcopenshell.open(str(gold))
    me = ifcopenshell.open(str(edited))
    A = upward([mg, me], d_ig | d_ge)
    obj_g, rel_ids, elem_g = set(), set(), set()
    for m in (mg, me):
        for i in A:
            try:
                e = m.by_id(i)
            except Exception:
                continue
            if e.is_a("IfcObjectDefinition"):
                obj_g.add(e.GlobalId)
            elif e.is_a("IfcRelationship"):
                rel_ids.add(i)
                if e.is_a("IfcRelDefinesByProperties"):
                    for o in e.RelatedObjects or ():
                        elem_g.add(o.GlobalId)
    elem_g |= obj_g
    obj_g |= elem_g
    fg = fingerprint(mg, obj_g, rel_ids, elem_g)
    fe = fingerprint(me, obj_g, rel_ids, elem_g)
    info = {"dirty_source_vs_gt": len(d_ig), "dirty_gt_vs_edited": len(d_ge),
            "affected_entities": len(A), "objects_read": len(obj_g),
            "relationships_read": len(rel_ids), "elements_read": len(elem_g)}
    del mg, me
    return fg, fe, info


def evaluate(payload: tuple) -> dict:
    arm, row, edited, delete_after = payload
    t0 = time.time()
    tasks = _tasks()
    record = tasks[row["task_id"]]
    out = {"arm": arm, "task_id": row["task_id"],
           **{k: record.get(k) for k in ("operation", "category", "ifc_version", "edit_kind",
                                         "building_id", "origin", "tier")},
           "clarification": bool(record.get("clarification")),
           "committed": bool(row.get("committed")),
           "score": {k: (row.get("score") or {}).get(k) for k in ("geometry", "semantics", "topology", "final")},
           "edited_source": "archive" if delete_after else "disk",
           "status": "ok"}
    gold = None
    try:
        fi = source_fp(record)
        if FAST:
            gold = unpack_gold(record, SCRATCH / f"g{os.getpid()}")
            fg, fe, info = fast_fps(record, gold, Path(edited), fi)
            out["fast_path"] = info
        else:
            fg = gold_fp(record)
            fe = fp_file(Path(edited))
        out.update(diff_task(fi, fg, fe, record))
    except Exception as exc:  # noqa: BLE001
        out["status"] = "error"
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        out["trace"] = traceback.format_exc()[-1200:]
    finally:
        if gold is not None:
            gold.unlink(missing_ok=True)
        if delete_after:
            Path(edited).unlink(missing_ok=True)
    out["seconds"] = round(time.time() - t0, 1)
    return out


# ---------------------------------------------------------------- driver


def arm_todo(arm: str) -> list[dict]:
    per_task, _tar = ARMS[arm]
    rows = [json.loads(l) for l in open(RES / per_task) if l.strip()]
    return [r for r in rows if completed(r)]


def run_arm(arm: str, workers: int, limit: int = 0) -> None:
    import multiprocessing as mp
    _tasks()
    todo = arm_todo(arm)
    done = set()
    if ROWS.exists():
        for l in open(ROWS):
            d = json.loads(l)
            if d["arm"] == arm and d["status"] == "ok":
                done.add(d["task_id"])
    todo = [r for r in todo if r["task_id"] not in done]
    if limit:
        todo = todo[:limit]
    on_disk = [r for r in todo if r.get("edited_ifc") and Path(r["edited_ifc"]).is_file()]
    disk_ids = {r["task_id"] for r in on_disk}
    in_tar = {r["task_id"]: r for r in todo if r["task_id"] not in disk_ids}
    print(f"[{arm}] {len(todo)} completed edits to diff: {len(on_disk)} on disk, "
          f"{len(in_tar)} in the archive", flush=True)
    queue = SCRATCH / "queue" / arm
    queue.mkdir(parents=True, exist_ok=True)
    started = time.time()
    lock = threading.Lock()
    pending = threading.Semaphore(2 * workers)
    n_done = [0]
    sink = open(ROWS, "a")

    def on_done(res: dict) -> None:
        with lock:
            sink.write(json.dumps(res, default=str) + "\n")
            sink.flush()
            n_done[0] += 1
            if n_done[0] % 10 == 0 or res["status"] != "ok":
                print(f"[{arm}] {n_done[0]}/{len(todo)} {res['task_id']} {res['status']} "
                      f"any={res.get('n_any')} t={res['seconds']}s free={free_gb():.0f}GB "
                      f"elapsed={time.time() - started:.0f}s", flush=True)
        pending.release()

    def on_error(exc) -> None:
        print(f"[{arm}] worker error {exc}", flush=True)
        pending.release()

    ctx = mp.get_context("fork")
    with ctx.Pool(workers, initializer=_init, maxtasksperchild=25) as pool:
        for r in on_disk:
            pending.acquire(timeout=3600)
            pool.apply_async(evaluate, ((arm, r, r["edited_ifc"], False),),
                             callback=on_done, error_callback=on_error)
        if in_tar:
            tar_path = RES / ARMS[arm][1]
            want = {(tid, Path(r["edited_ifc"]).name): r for tid, r in in_tar.items()}
            seen = set()
            with tarfile.open(tar_path, "r|gz") as tf:
                for m in tf:
                    if not m.isfile():
                        continue
                    parts = m.name.split("/")
                    if len(parts) < 3:
                        continue
                    key = (parts[-2], parts[-1])
                    if key not in want:
                        continue
                    if not pending.acquire(timeout=3600):
                        print(f"[{arm}] no result for an hour; continuing", flush=True)
                    while free_gb() < MIN_FREE_GB or mem_available_gb() < 8.0:
                        time.sleep(5)
                    dest = queue / key[0]
                    dest.mkdir(parents=True, exist_ok=True)
                    target = dest / key[1]
                    src = tf.extractfile(m)
                    with open(target, "wb") as fo:
                        shutil.copyfileobj(src, fo, 1 << 20)
                    seen.add(key)
                    pool.apply_async(evaluate, ((arm, want[key], str(target), True),),
                                     callback=on_done, error_callback=on_error)
                    if len(seen) == len(want):
                        break
            for key, r in want.items():
                if key not in seen:
                    on_done({"arm": arm, "task_id": r["task_id"], "status": "edited_missing",
                             "seconds": 0.0})
                    pending.acquire()
        pool.close()
        pool.join()
    returned = set()
    for l in open(ROWS):
        d = json.loads(l)
        if d["arm"] == arm:
            returned.add(d["task_id"])
    for r in todo:
        if r["task_id"] not in returned:
            sink.write(json.dumps({"arm": arm, "task_id": r["task_id"], "status": "lost",
                                   "seconds": 0.0}) + "\n")
    sink.close()
    shutil.rmtree(queue, ignore_errors=True)
    print(f"[{arm}] done in {time.time() - started:.0f}s", flush=True)


def prep_sources(arms: list[str], workers: int) -> None:
    import multiprocessing as mp
    tasks = _tasks()
    srcs = {}
    for arm in arms:
        for r in arm_todo(arm):
            rec = tasks[r["task_id"]]
            srcs[rec["input_ifc"]] = rec
    recs = sorted(srcs.values(), key=lambda r: r["input_ifc"])
    print(f"{len(recs)} source models to fingerprint", flush=True)
    ctx = mp.get_context("fork")
    with ctx.Pool(workers, initializer=_init, maxtasksperchild=4) as pool:
        for k, (name, secs) in enumerate(pool.imap_unordered(_prep_one, recs), 1):
            print(f"src {k}/{len(recs)} {name} {secs}s free={free_gb():.0f}GB", flush=True)


def _prep_one(rec: dict):
    t = time.time()
    source_fp(rec)
    return rec["input_ifc"].rsplit("/", 1)[-1], round(time.time() - t, 1)


ARM_LABELS = {
    "final_full": "Proposed model, all 2,100 tasks",
    "final_108": "Proposed model, 108-task subset",
    "imitation_108": "Imitation-only model, 108-task subset",
    "claude-sonnet-5-5_108": "Claude Sonnet 5.5 with the library",
    "gpt-5.6-luna_108": "GPT-5.6 Luna with the library",
    "gemini-3.8-flash_108": "Gemini 3.8 Flash with the library",
    "deepseek-v4-pro_108": "DeepSeek V4 Pro with the library",
}
CLASSES = ("geometry", "relation", "property", "attribute", "other_objects")


def _arm_summary(rows: list[dict], n_completed: int) -> dict:
    ok = [r for r in rows if r["status"] == "ok"]
    aff = [r for r in ok if r["n_any"] > 0]
    out = {"n_completed": n_completed, "n_evaluated": len(ok),
           "status": dict(collections.Counter(r["status"] for r in rows)),
           "n_with_any": len(aff), "share_with_any": round(len(aff) / len(ok), 4) if ok else None,
           "median_count_per_affected_file": statistics.median([r["n_any"] for r in aff]) if aff else None,
           "max_count": max([r["n_any"] for r in aff]) if aff else 0,
           "by_class": {}}
    for c in CLASSES:
        sel = [r for r in ok if r[f"n_{c}"] > 0]
        out["by_class"][c] = {"n_files": len(sel), "n_items": sum(r[f"n_{c}"] for r in ok),
                              "median_per_affected_file": statistics.median([r[f"n_{c}"] for r in sel]) if sel else None}
    out["by_class"]["attribute"]["n_files_named"] = sum(1 for r in ok if r.get("n_attribute_named", 0) > 0)
    out["listed_not_counted"] = {
        "header_differs": sum(1 for r in ok if r.get("header_differs")),
        "owner_history_differs": sum(1 for r in ok if r.get("owner_history_differs")),
        "relationship_ids_only": sum(1 for r in ok if (r.get("relationship_ids_only") or {}).get("in_ground_truth_not_edited")),
        "property_set_ids_only": sum(1 for r in ok if (r.get("property_set_ids_only") or {}).get("in_ground_truth_not_edited")),
        "target_reidentified": sum(1 for r in ok if r.get("target_reidentified")),
        "edges_of_added_removed_files": sum(1 for r in ok if r.get("edges_of_added_removed")),
    }
    out["by_operation"] = {op: {"n": len([r for r in ok if r["operation"] == op]),
                                "n_with_any": len([r for r in aff if r["operation"] == op])}
                           for op in ("create", "update", "delete")}
    rel_cls = collections.Counter(e["relation"] for r in ok for e in r.get("relation") or [])
    geo_cls = collections.Counter((e["class"], e["kind"]) for r in ok for e in r.get("geometry") or [])
    att = collections.Counter(a for r in ok for e in r.get("attribute") or [] for a in e["attrs"])
    pk = collections.Counter(k.split(".")[0] for r in ok for e in r.get("property") or [] for k in e["keys"])
    out["what_changed"] = {"relation_classes": dict(rel_cls.most_common(10)),
                           "geometry_class_kind": {f"{a}/{b}": n for (a, b), n in geo_cls.most_common(10)},
                           "attributes": dict(att.most_common(10)),
                           "property_sets": dict(pk.most_common(10))}
    out["affected_tasks"] = [{"task_id": r["task_id"], "edit_kind": r["edit_kind"], "n_any": r["n_any"],
                              **{f"n_{c}": r[f"n_{c}"] for c in CLASSES}} for r in aff][:200]
    return out


def summarize() -> None:
    rows = [json.loads(l) for l in open(ROWS)]
    latest = {}
    for r in rows:
        latest[(r["arm"], r["task_id"])] = r
    summary = {"definition": __doc__.split("Usage:")[0].strip(),
               "completed_rule": "geometry, semantics and topology all >= 0.9 in the run's per-task record",
               "arms": {}}
    for arm in ARMS:
        n_completed = len(arm_todo(arm))
        rs = [r for (a, _t), r in latest.items() if a == arm]
        if not rs:
            continue
        summary["arms"][arm] = {"label": ARM_LABELS[arm], **_arm_summary(rs, n_completed)}
    (OUT / "offtarget_summary.json").write_text(json.dumps(summary, indent=1, default=str))

    def cell(n, d):
        return "--" if d is None else f"{n}"
    lines = [r"\begin{tabular}{lrrrrrrr}", r"\toprule",
             r" & Completed & \multicolumn{5}{c}{Edits with an off-target change} & Median changes \\",
             r"\cmidrule(lr){3-7}",
             r"Arm & edits & Any & Geometry or placement & Relation & Property & Attribute & per affected edit \\",
             r"\midrule"]
    for arm, a in summary["arms"].items():
        bc = a["by_class"]
        med = a["median_count_per_affected_file"]
        lines.append(f"{a['label']} & {a['n_evaluated']} & {a['n_with_any']} & "
                     f"{bc['geometry']['n_files']} & {bc['relation']['n_files']} & {bc['property']['n_files']} & "
                     f"{bc['attribute']['n_files']} & {'--' if med is None else med} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "tab_offtarget_full.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps({arm: (a["n_completed"], a["n_evaluated"], a["n_with_any"],
                            {c: a["by_class"][c]["n_files"] for c in CLASSES})
                      for arm, a in summary["arms"].items()}, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("validate", "prep", "run", "summarize"))
    ap.add_argument("--arm", action="append")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    if a.cmd == "prep":
        prep_sources(a.arm or list(ARMS), a.workers)
    elif a.cmd == "run":
        for arm in a.arm or list(ARMS):
            run_arm(arm, a.workers, a.limit)
    elif a.cmd == "validate":
        from validate_offtarget import main as vmain
        vmain()
    else:
        summarize()
