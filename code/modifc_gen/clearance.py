"""The clearance rule for a door or window an edit creates, copies or moves.

The overlap tests the placement rules apply ask whether a new body occupies
matter that is already there.  A doorway can pass them and still be unusable:
a partition that only butts the face of the host wall occupies none of the
host's volume, yet a door cut across the end of that partition opens into it.
The question this rule asks is therefore about the space in front of the hole,
not about the hole itself.

The zone.  The host wall's own placement gives the frame: ``a`` along the wall,
``n`` across it, ``z`` up.  The opening the door or window fills spans
``[a0, a1]`` along the wall and ``[z0, z1]`` in height; the band is that span
shrunk by ``BAND_TOLERANCE_ALONG`` at both jambs, ``BAND_TOLERANCE_BOTTOM`` at
the bottom (finish slabs, thresholds) and ``BAND_TOLERANCE_TOP`` at the head,
so matter that only touches the frame line does not count.  The host's faces
``[h0, h1]`` are read from the host's own triangles inside the band.  The zone
is the band times ``[h0 - c, h1 + c]``: the hole, carried ``c`` metres out on
both sides of the wall.

What obstructs.  Every wall, curtain wall, column and slab other than the host
and the host's own layers.  A layer is a part aggregated into the host, the
host's aggregate parent or one of its other parts, or a wall modelled on its
own alongside the host: parallel to it within ``LAYER_ANGLE``, no farther than
``LAYER_GAP`` from a host face inside the band, and running across the whole
band (a leaf of a double wall, a lining).  Spaces, openings, other doors and
windows, beams, members, coverings and furniture do not obstruct.

The distance is the clear distance along ``n`` from the host faces to the part
of the nearest obstruction that lies inside the band, zero when that part
reaches the host (a T-junction).  A door or window whose distance is below
``FILLING_ZONE_CLEARANCE`` is refused.  The value was calibrated on the doors
and windows of five source buildings (runs_local/corpus_v10/clearance_fix/
REPORT.txt).
"""

from __future__ import annotations

from typing import Any, Optional, Sequence

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.unit

from . import geomindex

# Metres of free space a door or window keeps in front of its hole, on both
# faces of the host wall.
FILLING_ZONE_CLEARANCE = 0.60

# Metres the hole's span is shrunk by before the zone is read.
BAND_TOLERANCE_ALONG = 0.02
BAND_TOLERANCE_BOTTOM = 0.10
BAND_TOLERANCE_TOP = 0.02

# Distances are measured this far out; nothing farther is looked at.
ZONE_REACH = 1.5

# A filling whose world box changed by more than this counts as moved.
MOVED_BY = 0.001

# A wall this close to a host face, and this near parallel to the host, counts
# as one of the host's layers.
LAYER_GAP = 0.05
LAYER_ANGLE = 10.0

OBSTRUCTING_CLASSES = ("IfcWall", "IfcCurtainWall", "IfcColumn", "IfcSlab")
FILLING_CLASSES = ("IfcDoor", "IfcWindow")


def obstructs(product) -> bool:
    return any(product.is_a(c) for c in OBSTRUCTING_CLASSES)


def is_filling(product) -> bool:
    return any(product.is_a(c) for c in FILLING_CLASSES)


def triangles(product) -> Optional[np.ndarray]:
    """World triangles of one product, shape (k, 3, 3), in metres."""
    try:
        shape = ifcopenshell.geom.create_shape(geomindex.geom_settings(), product)
    except Exception:
        return None
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    faces = np.asarray(shape.geometry.faces, dtype=np.int64).reshape(-1, 3)
    if verts.size == 0 or faces.size == 0:
        return None
    return verts[faces]


def host_and_opening(filling):
    for fills in getattr(filling, "FillsVoids", ()) or ():
        opening = fills.RelatingOpeningElement
        for voids in getattr(opening, "VoidsElements", ()) or ():
            return voids.RelatingBuildingElement, opening
    return None, None


def own_layers(host) -> set[str]:
    """The host's aggregate parent and every part of that aggregate."""
    out: set[str] = set()
    for relation in getattr(host, "IsDecomposedBy", ()) or ():
        out.update(p.GlobalId for p in relation.RelatedObjects)
    for relation in getattr(host, "Decomposes", ()) or ():
        parent = relation.RelatingObject
        out.add(parent.GlobalId)
        for sub in getattr(parent, "IsDecomposedBy", ()) or ():
            out.update(p.GlobalId for p in sub.RelatedObjects)
    return out


def wall_frame(model, host, host_tris: np.ndarray):
    """Origin and unit axes (along, across, up) of the host wall."""
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    matrix = np.array(ifcopenshell.util.placement.get_local_placement(
        host.ObjectPlacement), dtype=float)
    origin = matrix[:3, 3] * scale
    x = np.array(matrix[:3, 0], dtype=float)
    x[2] = 0.0
    if np.linalg.norm(x) < 1e-6:
        x = np.array([1.0, 0.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(np.array([0.0, 0.0, 1.0]), x)
    rel = host_tris.reshape(-1, 3) - origin
    # The wall runs along whichever horizontal axis its body is longer in.
    if np.ptp(rel @ x) >= np.ptp(rel @ y):
        along, across = x, y
    else:
        along, across = y, -x
    return origin, along, across, np.array([0.0, 0.0, 1.0])


def in_frame(tris: np.ndarray, frame) -> np.ndarray:
    origin, along, across, up = frame
    rel = tris - origin
    return np.stack([rel @ along, rel @ across, rel @ up], axis=-1)


def _clip(poly, axis, value, keep_above):
    out = []
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        p_in = p[axis] >= value if keep_above else p[axis] <= value
        q_in = q[axis] >= value if keep_above else q[axis] <= value
        if p_in:
            out.append(p)
        if p_in != q_in:
            t = (value - p[axis]) / (q[axis] - p[axis])
            out.append(p + t * (q - p))
    return out


def across_spans(local: np.ndarray, a_lo: float, a_hi: float,
                 z_lo: Optional[float] = None, z_hi: Optional[float] = None
                 ) -> list[tuple[float, float, float, float]]:
    """Across-wall and along-wall extent of each triangle's part in the band."""
    keep = (local[:, :, 0].max(1) > a_lo) & (local[:, :, 0].min(1) < a_hi)
    planes = [(0, a_lo, True), (0, a_hi, False)]
    if z_lo is not None:
        keep &= (local[:, :, 2].max(1) > z_lo) & (local[:, :, 2].min(1) < z_hi)
        planes += [(2, z_lo, True), (2, z_hi, False)]
    spans = []
    for tri in local[keep]:
        poly = [tri[0], tri[1], tri[2]]
        for axis, value, keep_above in planes:
            poly = _clip(poly, axis, value, keep_above)
            if len(poly) < 3:
                break
        if len(poly) >= 3:
            ns = [p[1] for p in poly]
            along = [p[0] for p in poly]
            spans.append((min(ns), max(ns), min(along), max(along)))
    return spans


def runs_parallel(local: np.ndarray, degrees: float = LAYER_ANGLE) -> bool:
    """Whether a body's plan footprint runs along the host's own axis."""
    plan = local.reshape(-1, 3)[:, :2]
    plan = plan - plan.mean(axis=0)
    if len(plan) < 3:
        return False
    values, vectors = np.linalg.eigh(plan.T @ plan)
    if values[-1] < 1.5 * max(values[0], 1e-12):
        return False
    return abs(float(vectors[0, -1])) >= np.cos(np.radians(degrees))


def clearance_of(model, filling, index: Optional[dict[str, Any]],
                 always: Sequence[str] = ()) -> dict[str, Any]:
    """Clear distance in front of one door or window, and what limits it.

    ``index`` is a geometry index (``geomindex.build``) whose boxes pick the
    candidate obstructions; ``always`` names elements tested whatever the index
    says, because the edit created or moved them.
    """
    host, opening = host_and_opening(filling)
    if host is None:
        return {"status": "no_host"}
    host_tris = triangles(host)
    hole = triangles(opening) if opening is not None else None
    if hole is None:
        hole = triangles(filling)
    if host_tris is None or hole is None:
        return {"status": "no_geometry"}
    frame = wall_frame(model, host, host_tris)
    span = in_frame(hole, frame).reshape(-1, 3)
    a0, a1 = float(span[:, 0].min()), float(span[:, 0].max())
    z0, z1 = float(span[:, 2].min()), float(span[:, 2].max())
    host_local = in_frame(host_tris, frame)
    faces = across_spans(host_local, a0, a1)
    if faces:
        h0, h1 = min(f[0] for f in faces), max(f[1] for f in faces)
    else:
        h0, h1 = float(host_local[:, :, 1].min()), float(host_local[:, :, 1].max())
    A0, A1 = a0 + BAND_TOLERANCE_ALONG, a1 - BAND_TOLERANCE_ALONG
    Z0, Z1 = z0 + BAND_TOLERANCE_BOTTOM, z1 - BAND_TOLERANCE_TOP
    if A1 <= A0 or Z1 <= Z0:
        return {"status": "degenerate_band"}
    skip = {host.GlobalId, filling.GlobalId} | own_layers(host)
    if opening is not None:
        skip.add(opening.GlobalId)
    origin, along, across, up = frame
    corners = np.array([origin + a * along + n * across + z * up
                        for a in (A0, A1)
                        for n in (h0 - ZONE_REACH, h1 + ZONE_REACH)
                        for z in (Z0, Z1)])
    lo, hi = corners.min(axis=0) - 0.01, corners.max(axis=0) + 0.01
    if index is not None:
        near = np.all(index["lo"] <= hi, axis=1) & np.all(index["hi"] >= lo, axis=1)
        candidates = [str(g) for g in index["guid"][near]]
    else:
        candidates = [e.GlobalId for c in OBSTRUCTING_CLASSES
                      for e in model.by_type(c)]
    best = None
    for guid in dict.fromkeys(candidates + list(always)):
        if guid in skip:
            continue
        try:
            element = model.by_guid(guid)
        except Exception:
            continue
        if not obstructs(element):
            continue
        tris = triangles(element)
        if tris is None:
            continue
        local = in_frame(tris, frame)
        spans = across_spans(local, A0, A1, Z0, Z1)
        if not spans:
            continue
        gaps = []
        for n_lo, n_hi, _a_lo, _a_hi in spans:
            if n_hi >= h0 and n_lo <= h1:
                gaps.append(0.0)
            elif n_hi < h0:
                gaps.append(h0 - n_hi)
            else:
                gaps.append(n_lo - h1)
        gap = min(gaps)
        if gap > ZONE_REACH:
            continue
        # A wall alongside the host, touching it across the whole band, is one
        # of the host's own layers rather than something in front of the hole.
        if element.is_a("IfcWall") and gap <= LAYER_GAP \
                and min(s[2] for s in spans) <= A0 + 0.01 \
                and max(s[3] for s in spans) >= A1 - 0.01 \
                and runs_parallel(local):
            continue
        if best is None or gap < best[0]:
            best = (gap, element)
    if best is None:
        return {"status": "ok", "distance": None}
    return {"status": "ok", "distance": round(float(best[0]), 4),
            "obstruction": best[1].GlobalId, "obstruction_class": best[1].is_a()}


def world_box(product) -> Optional[tuple[np.ndarray, np.ndarray]]:
    tris = triangles(product)
    if tris is None:
        return None
    verts = tris.reshape(-1, 3)
    return verts.min(axis=0), verts.max(axis=0)


def placed_fillings(source, gold, created: Sequence[str],
                    targets: Sequence[str]) -> list:
    """Doors and windows in the gold that the edit created or moved."""
    out = []
    for guid in created:
        try:
            element = gold.by_guid(guid)
        except Exception:
            continue
        if is_filling(element):
            out.append(element)
    for guid in dict.fromkeys(targets):
        try:
            before, after = source.by_guid(guid), gold.by_guid(guid)
        except Exception:
            continue
        if not is_filling(after):
            continue
        box0, box1 = world_box(before), world_box(after)
        if box0 is None or box1 is None:
            continue
        shift = max(float(np.abs(box1[0] - box0[0]).max()),
                    float(np.abs(box1[1] - box0[1]).max()))
        if shift > MOVED_BY:
            out.append(after)
    return out
