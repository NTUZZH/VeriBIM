"""World-coordinate geometry of one source model, indexed once and cached.

The placement rules ask two questions a placement origin cannot answer: how far
a storey's fabric actually reaches, and what matter already stands where a new
element is about to go.  Both need the triangulated solid rather than the
element's origin, so every element that carries a body is meshed once per source
model and reduced to its world bounding box, its class and the storey it sits
on.

Meshing a large model costs minutes, and one source model hosts many tasks
across many shards, so the index is written to a cache directory keyed by the
file's path, size and modification time.  ``MODIFC_GEOM_CACHE`` names that
directory; the default sits under the user's cache directory.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any, Optional

import numpy as np

import ifcopenshell
import ifcopenshell.geom

# Classes that carry no matter: a space is a void, an opening is a hole, and an
# annotation, a grid or a virtual element is a drawing aid.
NON_SOLID_PREFIXES = ("IfcSpace", "IfcOpening", "IfcAnnotation", "IfcVirtual",
                      "IfcGrid")

# Below this many indexed elements a storey's footprint is not trustworthy and
# the containment rules stand down rather than guess.
MIN_STOREY_ELEMENTS = 8

_SETTINGS = None


def geom_settings():
    global _SETTINGS
    if _SETTINGS is None:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        _SETTINGS = settings
    return _SETTINGS


def world_bounds(product) -> Optional[tuple[np.ndarray, np.ndarray]]:
    """Axis-aligned world bounding box of one product, in metres."""
    try:
        shape = ifcopenshell.geom.create_shape(geom_settings(), product)
    except Exception:
        return None
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    if verts.size == 0:
        return None
    return verts.min(axis=0), verts.max(axis=0)


def _storey_ancestor(structure):
    seen = 0
    while structure is not None and seen < 8:
        if structure.is_a("IfcBuildingStorey"):
            return structure
        parents = getattr(structure, "Decomposes", ()) or ()
        structure = parents[0].RelatingObject if parents else None
        seen += 1
    return None


def storey_map(model) -> dict[str, str]:
    """Storey identifier of every product that sits on one."""
    out: dict[str, str] = {}
    for relation in model.by_type("IfcRelContainedInSpatialStructure"):
        storey = _storey_ancestor(relation.RelatingStructure)
        if storey is None:
            continue
        for element in relation.RelatedElements or ():
            out[element.GlobalId] = storey.GlobalId
    for relation in model.by_type("IfcRelAggregates"):
        storey = _storey_ancestor(relation.RelatingObject)
        if storey is None:
            continue
        for child in relation.RelatedObjects or ():
            out.setdefault(child.GlobalId, storey.GlobalId)
    return out


def solid_mask(classes) -> np.ndarray:
    """Which indexed elements count as matter a new element may not occupy."""
    return np.array([not any(str(c).startswith(p) for p in NON_SOLID_PREFIXES)
                     for c in classes], dtype=bool)


def cache_dir() -> str:
    named = os.environ.get("MODIFC_GEOM_CACHE")
    if named:
        return named
    return os.path.join(os.path.expanduser("~"), ".cache", "modifc_gen",
                        "geom_index")


def cache_key(path: str) -> str:
    stat = os.stat(path)
    raw = f"{os.path.abspath(path)}|{stat.st_size}|{int(stat.st_mtime)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def _finish(payload: dict[str, Any]) -> dict[str, Any]:
    payload["solid"] = solid_mask(payload["cls"])
    payload["lookup"] = {g: i for i, g in enumerate(payload["guid"].tolist())}
    return payload


def build(path: str, model=None, directory: Optional[str] = None
          ) -> dict[str, Any]:
    """Index one model, reading the cache when it holds this exact file."""
    directory = directory or cache_dir()
    os.makedirs(directory, exist_ok=True)
    cache = os.path.join(directory, cache_key(path) + ".npz")
    if os.path.exists(cache):
        try:
            data = np.load(cache, allow_pickle=False)
            return _finish({"guid": data["guid"], "cls": data["cls"],
                            "storey": data["storey"], "lo": data["lo"],
                            "hi": data["hi"]})
        except Exception:
            pass
    if model is None:
        model = ifcopenshell.open(path)
    storeys = storey_map(model)
    products = list(model.by_type("IfcElement")) + list(model.by_type("IfcSpace"))
    guid, cls, storey, lo, hi = [], [], [], [], []
    for product in products:
        bounds = world_bounds(product)
        if bounds is None:
            continue
        guid.append(product.GlobalId)
        cls.append(product.is_a())
        storey.append(storeys.get(product.GlobalId, ""))
        lo.append(bounds[0])
        hi.append(bounds[1])
    payload = {"guid": np.array(guid, dtype=object).astype("U22"),
               "cls": np.array(cls, dtype=object).astype("U48"),
               "storey": np.array(storey, dtype=object).astype("U22"),
               "lo": np.array(lo, dtype=float).reshape(-1, 3),
               "hi": np.array(hi, dtype=float).reshape(-1, 3)}
    try:
        np.savez_compressed(cache, **payload)
    except Exception:
        pass
    return _finish(payload)
