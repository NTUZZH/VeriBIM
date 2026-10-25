"""Clash and schema helpers for analysis 3.

Hard clash: two elements whose world-coordinate boxes overlap by more than
2 mm on every axis are measured on their world-coordinate tessellations
(ifcopenshell.geom, the checker's settings) with a generalised winding-number
inside test on a regular grid over the overlap of the two boxes (20 cells along
the longest side, at least 3 per axis); the pair is a hard clash when the
estimated intersection volume exceeds 1e-4 m^3.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np

VOL_MIN = 1e-4          # m^3
TOL = 0.002             # m, clash-engine penetration tolerance
GRID = 20               # cells along the longest side of the overlap box
NEIGHBOUR_MARGIN = 0.05 # m, box growth when listing candidate partners

EXCLUDE_OTHER = ("IfcFeatureElement", "IfcVirtualElement", "IfcSpatialStructureElement",
                 "IfcSpatialElement", "IfcAnnotation", "IfcGrid", "IfcPort",
                 "IfcDistributionPort")


_SETTINGS = {}


def settings():
    import ifcopenshell.geom
    s = _SETTINGS.get("s")
    if s is None:
        s = ifcopenshell.geom.settings()
        s.set("use-world-coords", True)
        s.set("weld-vertices", True)
        s.set("mesher-linear-deflection", 0.001)
        _SETTINGS["s"] = s
    return s


def mesh(entity):
    import ifcopenshell.geom
    if not getattr(entity, "Representation", None):
        return None
    try:
        sh = ifcopenshell.geom.create_shape(settings(), entity)
    except Exception:
        return None
    g = getattr(sh, "geometry", sh)
    v = np.asarray(g.verts, dtype=float).reshape(-1, 3)
    f = np.asarray(g.faces, dtype=np.int64).reshape(-1, 3)
    if len(v) == 0 or len(f) == 0:
        return None
    return v, f


def winding(points, verts, faces, chunk=None):
    """Generalised winding number of each point w.r.t. a triangle mesh."""
    out = np.zeros(len(points))
    if chunk is None:
        chunk = max(8, int(2_000_000 // max(1, len(faces))))
    A, B, Cc = verts[faces[:, 0]], verts[faces[:, 1]], verts[faces[:, 2]]
    for s in range(0, len(points), chunk):
        P = points[s:s + chunk][:, None, :]
        a, b, c = A[None] - P, B[None] - P, Cc[None] - P
        la, lb, lc = (np.linalg.norm(x, axis=2) for x in (a, b, c))
        det = np.einsum("ijk,ijk->ij", a, np.cross(b, c))
        den = (la * lb * lc + np.einsum("ijk,ijk->ij", a, b) * lc
               + np.einsum("ijk,ijk->ij", b, c) * la + np.einsum("ijk,ijk->ij", c, a) * lb)
        out[s:s + chunk] = np.arctan2(det, den).sum(axis=1) / (2 * np.pi)
    return out


def overlap_volume(ma, mb, grid=GRID):
    """Estimated intersection volume (m^3) of two meshes and the overlap box extents."""
    va, fa = ma
    vb, fb = mb
    lo = np.maximum(va.min(0), vb.min(0))
    hi = np.minimum(va.max(0), vb.max(0))
    ext = hi - lo
    if np.any(ext <= 0):
        return 0.0, ext.tolist()
    step = max(float(ext.max()) / grid, 0.005)
    n = np.maximum(3, np.ceil(ext / step).astype(int))
    cell = ext / n
    axes = [lo[i] + (np.arange(n[i]) + 0.5) * cell[i] for i in range(3)]
    pts = np.stack(np.meshgrid(*axes, indexing="ij"), -1).reshape(-1, 3)
    wa = np.abs(winding(pts, va, fa))
    keep = wa > 0.5
    if not keep.any():
        return 0.0, ext.tolist()
    wb = np.abs(winding(pts[keep], vb, fb))
    inside = int((wb > 0.5).sum())
    return float(inside * np.prod(cell)), ext.tolist()


def aabb(m):
    v = m[0]
    return v.min(0), v.max(0)


def is_other(e, target_is_space: bool) -> bool:
    if target_is_space:
        return e.is_a("IfcSpace")
    if not e.is_a("IfcElement"):
        return False
    return not any(e.is_a(c) for c in EXCLUDE_OTHER)


def excluded_pair(a, b) -> str | None:
    """Pairs that legitimately share volume: a filling and its host, parts of one element."""
    def hosts(x):
        out = set()
        for rel in getattr(x, "FillsVoids", ()) or ():
            op = rel.RelatingOpeningElement
            for v in getattr(op, "VoidsElements", ()) or () if op is not None else ():
                if v.RelatingBuildingElement is not None:
                    out.add(v.RelatingBuildingElement.id())
        return out
    if b.id() in hosts(a) or a.id() in hosts(b):
        return "filling in its host"

    def parents(x):
        out = set()
        for rel in getattr(x, "Decomposes", ()) or ():
            if rel.is_a("IfcRelAggregates") and rel.RelatingObject is not None:
                out.add(rel.RelatingObject.id())
        for rel in getattr(x, "Nests", ()) or ():
            if rel.RelatingObject is not None:
                out.add(rel.RelatingObject.id())
        return out
    pa, pb = parents(a), parents(b)
    if b.id() in pa or a.id() in pb:
        return "part of the same element"
    if pa & pb and not any(model_spatial(p, a) for p in pa & pb):
        return "parts of the same element"
    return None


def model_spatial(pid, inst):
    try:
        return inst.wrapped_data.file.by_id(pid).is_a("IfcSpatialElement")
    except Exception:
        try:
            f = inst.file
            return f.by_id(pid).is_a("IfcSpatialElement")
        except Exception:
            return False


def source_index(model) -> dict[str, list]:
    """GlobalId -> [lo, hi, class] for every element/space with a shape (one pass)."""
    import ifcopenshell.geom
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    it = ifcopenshell.geom.iterator(s, model, 1, exclude=["IfcOpeningElement"])
    out = {}
    if it.initialize():
        while True:
            sh = it.get()
            v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
            if len(v):
                out[sh.guid] = [v.min(0).tolist(), v.max(0).tolist(), sh.type]
            if not it.next():
                break
    return out


def candidates(index, lo, hi, margin=NEIGHBOUR_MARGIN):
    lo = np.asarray(lo) - margin
    hi = np.asarray(hi) + margin
    out = []
    for g, (a, b, _cls) in index.items():
        if np.all(np.asarray(a) <= hi) and np.all(np.asarray(b) >= lo):
            out.append(g)
    return out


def clashes_in_file(model, target_guids, src_index, src_guids):
    """Hard clashes between the targets and every other element near them."""
    import ifcopenshell.geom
    targets = []
    for g in target_guids:
        try:
            targets.append(model.by_guid(g))
        except Exception:
            pass
    tmesh = {t.GlobalId: mesh(t) for t in targets}
    targets = [t for t in targets if tmesh.get(t.GlobalId) is not None]
    if not targets:
        return [], {"n_targets": 0}
    tset = {t.GlobalId for t in targets}
    cand = set()
    for t in targets:
        lo, hi = aabb(tmesh[t.GlobalId])
        cand.update(candidates(src_index, lo, hi))
    # elements this file has and the source has not
    for cls in ("IfcElement", "IfcSpace"):
        for e in model.by_type(cls):
            if e.GlobalId not in src_guids:
                cand.add(e.GlobalId)
    others = []
    for g in cand:
        if g in tset:
            continue
        try:
            e = model.by_guid(g)
        except Exception:
            continue
        if not getattr(e, "Representation", None):
            continue
        others.append(e)
    rows = []
    info = {"n_targets": len(targets), "n_candidates": len(others)}
    for t in targets:
        is_space = t.is_a("IfcSpace")
        ot = [o for o in others if is_other(o, is_space)]
        tm = tmesh[t.GlobalId]
        tlo, thi = aabb(tm)
        for o in ot:
            om = mesh(o)
            if om is None:
                continue
            olo, ohi = aabb(om)
            if np.any(np.maximum(tlo, olo) >= np.minimum(thi, ohi) - TOL):
                continue  # boxes do not overlap beyond the tolerance
            why = excluded_pair(t, o)
            vol, ext = overlap_volume(tm, om)
            if vol <= VOL_MIN:
                continue
            rows.append({"target": t.GlobalId, "target_class": t.is_a(),
                         "other": o.GlobalId, "other_class": o.is_a(),
                         "other_name": getattr(o, "Name", None),
                         "volume_m3": round(vol, 6), "overlap_box_m": [round(x, 3) for x in ext],
                         "excluded": why})
    return rows, info
