"""Shared checks for the ground-truth repair tests."""
from __future__ import annotations

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement as pu
import ifcopenshell.util.unit as uu

_ENDS: dict = {}


def required_ends(rel):
    """(name, is_aggregate, lower bound) of every required Relating*/Related* end.

    Read from the schema IfcOpenShell carries for the file: an explicit
    attribute that is not OPTIONAL and not derived; an aggregate end carries
    its declared lower bound (SET [1:?] gives 1), a single end needs a value.
    """
    key = rel.wrapped_data.is_a(True)
    if key not in _ENDS:
        decl = rel.wrapped_data.declaration().as_entity()
        derived = decl.derived()
        ends = []
        for i, attr in enumerate(decl.all_attributes()):
            name = attr.name()
            if not name.startswith(("Relating", "Related")):
                continue
            if attr.optional() or (i < len(derived) and derived[i]):
                continue
            agg = attr.type_of_attribute().as_aggregation_type()
            ends.append((name, agg is not None, 1 if agg is None else max(int(agg.bound1()), 0)))
        _ENDS[key] = tuple(ends)
    return _ENDS[key]


def empty_required_ends(model) -> dict:
    """{'Class.attribute #id': GlobalId} for every relationship with a required end null or empty."""
    out = {}
    for rel in model.by_type("IfcRelationship"):
        for name, many, least in required_ends(rel):
            value = getattr(rel, name, None)
            if value is None or (many and len(value) < least):
                out[f"{rel.is_a()}.{name} #{rel.id()}"] = rel.GlobalId
    return out


_SETTINGS = None


def box_in_frame(product, frame_product, model=None):
    """Axis box (metres) of a product's body in another product's placement frame."""
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = ifcopenshell.geom.settings()
        _SETTINGS.set("use-world-coords", True)
        _SETTINGS.set("disable-opening-subtractions", True)
    shape = ifcopenshell.geom.create_shape(_SETTINGS, product)
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    scale = float(uu.calculate_unit_scale(model if model is not None else product.file))
    frame = np.asarray(pu.get_local_placement(frame_product.ObjectPlacement), dtype=float)
    frame[:3, 3] *= scale
    inv = np.linalg.inv(frame)
    pts = (inv[:3, :3] @ verts.T).T + inv[:3, 3]
    return pts.min(axis=0), pts.max(axis=0)


def opening_and_host(filling):
    opening = filling.FillsVoids[0].RelatingOpeningElement
    host = opening.VoidsElements[0].RelatingBuildingElement
    return opening, host


def check_rehosted(filling, wall, face_width, face_height, tol=1e-3, source_relation=None):
    """The assertions both repairs must satisfy after a re-hosting.

    Returns the measured boxes for the record.
    """
    opening, host = opening_and_host(filling)
    assert host == wall, "the opening does not void the new wall"
    wlo, whi = box_in_frame(wall, wall)
    olo, ohi = box_in_frame(opening, wall)
    llo, lhi = box_in_frame(filling, wall)
    thickness = whi[1] - wlo[1]
    # face size kept
    assert abs((ohi[0] - olo[0]) - face_width) < tol, ("opening width", ohi[0] - olo[0], face_width)
    assert abs((ohi[2] - olo[2]) - face_height) < tol, ("opening height", ohi[2] - olo[2], face_height)
    # cut through the whole wall: wall thickness plus 50 mm past each face
    assert abs((ohi[1] - olo[1]) - (thickness + 0.1)) < tol, ("opening depth", ohi[1] - olo[1], thickness)
    # centred across the wall
    assert abs((ohi[1] + olo[1]) / 2 - (whi[1] + wlo[1]) / 2) < tol, ("opening centre", olo[1], ohi[1], wlo[1], whi[1])
    if source_relation is None:
        # the leaf sits inside the opening
        for axis in range(3):
            assert llo[axis] >= olo[axis] - tol and lhi[axis] <= ohi[axis] + tol, ("leaf outside opening", axis, llo, lhi, olo, ohi)
    else:
        # a door family whose casing overhangs the opening keeps the overhang it
        # had in the source, along the wall and in height, and its centring
        # across the opening
        for axis in (0, 2):
            assert abs((llo[axis] - olo[axis]) - source_relation["lo"][axis]) < tol, ("leaf vs opening lo", axis)
            assert abs((lhi[axis] - ohi[axis]) - source_relation["hi"][axis]) < tol, ("leaf vs opening hi", axis)
        centre = (llo[1] + lhi[1]) / 2 - (olo[1] + ohi[1]) / 2
        assert abs(centre - source_relation["centre_across"]) < tol, ("leaf centre across", centre)
    return {"wall": [wlo.round(4).tolist(), whi.round(4).tolist()],
            "opening": [olo.round(4).tolist(), ohi.round(4).tolist()],
            "leaf": [llo.round(4).tolist(), lhi.round(4).tolist()]}


def leaf_relation(filling, model):
    """How a leaf's body sits on its opening in the source: offsets of the box
    ends along the wall and in height, and the offset of the centres across."""
    opening, host = opening_and_host(filling)
    olo, ohi = box_in_frame(opening, host, model)
    llo, lhi = box_in_frame(filling, host, model)
    return {"lo": (llo - olo).tolist(), "hi": (lhi - ohi).tolist(),
            "centre_across": float((llo[1] + lhi[1]) / 2 - (olo[1] + ohi[1]) / 2)}
