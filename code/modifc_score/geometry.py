"""Meshing, surface sampling and the geometric comparisons the scorer needs."""

from __future__ import annotations

import math
from typing import Iterable, Sequence

import numpy as np
from scipy.spatial import cKDTree

import ifcopenshell
import ifcopenshell.geom

from .model_cache import Mesh, MeshCache, MESHES

_SETTINGS_CACHE: dict[tuple[float, bool], object] = {}


def _settings(linear_deflection: float, disable_openings: bool):
    key = (linear_deflection, disable_openings)
    settings = _SETTINGS_CACHE.get(key)
    if settings is None:
        settings = ifcopenshell.geom.settings()
        settings.set("use-world-coords", True)
        settings.set("weld-vertices", True)
        settings.set("mesher-linear-deflection", linear_deflection)
        if disable_openings:
            settings.set("disable-opening-subtractions", True)
        _SETTINGS_CACHE[key] = settings
    return settings


def triangle_areas(verts: np.ndarray, faces: np.ndarray) -> np.ndarray:
    a = verts[faces[:, 0]]
    b = verts[faces[:, 1]]
    c = verts[faces[:, 2]]
    return 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1)


def build_mesh(entity, linear_deflection: float = 0.001,
               disable_openings: bool = False) -> Mesh | None:
    """Triangulate one IFC entity in world coordinates.

    Returns ``None`` when the entity carries no usable shape.
    """
    if not getattr(entity, "Representation", None):
        return None
    try:
        shape = ifcopenshell.geom.create_shape(
            _settings(linear_deflection, disable_openings), entity)
    except Exception:
        return None
    geom = getattr(shape, "geometry", shape)
    verts = np.asarray(geom.verts, dtype=np.float64).reshape(-1, 3)
    faces = np.asarray(geom.faces, dtype=np.int64).reshape(-1, 3)
    if len(verts) == 0 or len(faces) == 0:
        return None
    return Mesh(verts=verts, faces=faces, area=float(triangle_areas(verts, faces).sum()))


def mesh_for(entity, model_key, cache: MeshCache = MESHES,
             linear_deflection: float = 0.001,
             disable_openings: bool = False) -> Mesh | None:
    """Cached variant of :func:`build_mesh`, keyed by model and entity GUID."""
    guid = getattr(entity, "GlobalId", None)
    if guid is None:
        return build_mesh(entity, linear_deflection, disable_openings)
    key = (model_key, guid)
    mesh, hit = cache.get(key)
    if hit:
        return mesh
    mesh = build_mesh(entity, linear_deflection, disable_openings)
    cache.put(key, mesh)
    return mesh


def sample_surface(mesh: Mesh, n_points: int, rng: np.random.Generator) -> np.ndarray:
    """Draw ``n_points`` samples uniformly over the mesh surface."""
    areas = triangle_areas(mesh.verts, mesh.faces)
    total = float(areas.sum())
    if n_points <= 0:
        return np.zeros((0, 3), dtype=np.float64)
    if total <= 0.0:
        # Degenerate surface: fall back to the vertices themselves.
        idx = rng.integers(0, len(mesh.verts), size=n_points)
        return mesh.verts[idx]
    probs = areas / total
    tri = rng.choice(len(areas), size=n_points, p=probs)
    a = mesh.verts[mesh.faces[tri, 0]]
    b = mesh.verts[mesh.faces[tri, 1]]
    c = mesh.verts[mesh.faces[tri, 2]]
    u = rng.random((n_points, 1))
    v = rng.random((n_points, 1))
    over = (u + v) > 1.0
    u = np.where(over, 1.0 - u, u)
    v = np.where(over, 1.0 - v, v)
    return a + u * (b - a) + v * (c - a)


def allocate_samples(areas: Sequence[float], per_object_cap: int, total_budget: int,
                     min_per_object: int) -> list[int]:
    """Split a sampling budget across objects in proportion to surface area."""
    n = len(areas)
    if n == 0:
        return []
    budget = min(total_budget, per_object_cap * n)
    total_area = float(sum(areas))
    if total_area <= 0.0:
        share = [budget / n] * n
    else:
        share = [budget * (a / total_area) for a in areas]
    counts = []
    for s in share:
        c = int(round(s))
        c = max(min_per_object, min(per_object_cap, c))
        counts.append(c)
    return counts


def pooled_cloud(meshes: Iterable[Mesh], per_object_cap: int, total_budget: int,
                 min_per_object: int, rng: np.random.Generator) -> np.ndarray:
    meshes = [m for m in meshes if m is not None]
    if not meshes:
        return np.zeros((0, 3), dtype=np.float64)
    counts = allocate_samples([m.area for m in meshes], per_object_cap, total_budget,
                              min_per_object)
    clouds = [sample_surface(m, c, rng) for m, c in zip(meshes, counts)]
    return np.concatenate(clouds, axis=0)


def joint_bbox_diagonal(a: np.ndarray, b: np.ndarray) -> float:
    """Diagonal of the axis-aligned box that encloses both clouds together."""
    if len(a) == 0 and len(b) == 0:
        return 0.0
    pts = np.concatenate([p for p in (a, b) if len(p)], axis=0)
    extent = pts.max(axis=0) - pts.min(axis=0)
    return float(np.linalg.norm(extent))


def chamfer_median(a: np.ndarray, b: np.ndarray, reduction: str = "pooled_median") -> float:
    """Median bidirectional nearest-neighbour distance between two clouds."""
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    tree_a = cKDTree(a)
    tree_b = cKDTree(b)
    d_ab, _ = tree_b.query(a, k=1, workers=1)
    d_ba, _ = tree_a.query(b, k=1, workers=1)
    if reduction == "mean_of_medians":
        return 0.5 * (float(np.median(d_ab)) + float(np.median(d_ba)))
    return float(np.median(np.concatenate([d_ab, d_ba])))


def chamfer_mean(a: np.ndarray, b: np.ndarray) -> float:
    if len(a) == 0 or len(b) == 0:
        return float("inf")
    tree_a = cKDTree(a)
    tree_b = cKDTree(b)
    d_ab, _ = tree_b.query(a, k=1, workers=1)
    d_ba, _ = tree_a.query(b, k=1, workers=1)
    return 0.5 * (float(d_ab.mean()) + float(d_ba.mean()))


def exp_score(ratio: float, scale: float) -> float:
    if not math.isfinite(ratio):
        return 0.0
    return float(math.exp(-ratio * scale))


# --------------------------------------------------------------------------
# Oriented bounding boxes
# --------------------------------------------------------------------------

def oriented_bbox(verts: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (centre, half extents, rotation) of a PCA-aligned bounding box.

    The rotation matrix's columns are the box axes.
    """
    if len(verts) == 0:
        raise ValueError("empty vertex set")
    mean = verts.mean(axis=0)
    centred = verts - mean
    if len(verts) < 3:
        rot = np.eye(3)
    else:
        cov = np.cov(centred, rowvar=False)
        if not np.all(np.isfinite(cov)):
            rot = np.eye(3)
        else:
            _, vecs = np.linalg.eigh(cov)
            rot = vecs[:, ::-1]
            if np.linalg.det(rot) < 0:
                rot[:, 2] *= -1.0
    local = centred @ rot
    lo = local.min(axis=0)
    hi = local.max(axis=0)
    centre_local = 0.5 * (lo + hi)
    half = 0.5 * (hi - lo)
    centre = mean + rot @ centre_local
    return centre, half, rot


def _box_corners(centre: np.ndarray, half: np.ndarray, rot: np.ndarray) -> np.ndarray:
    signs = np.array([[sx, sy, sz] for sx in (-1, 1) for sy in (-1, 1) for sz in (-1, 1)],
                     dtype=np.float64)
    return centre + (signs * half) @ rot.T


def _inside(points: np.ndarray, centre: np.ndarray, half: np.ndarray,
            rot: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    local = (points - centre) @ rot
    return np.all(np.abs(local) <= (half + eps), axis=1)


def _signed_permutation(matrix: np.ndarray, tol: float = 1e-6):
    """If ``matrix`` maps axes onto axes, return (permutation, signs)."""
    perm = np.argmax(np.abs(matrix), axis=0)
    if len(set(perm.tolist())) != 3:
        return None
    signs = np.sign(matrix[perm, np.arange(3)])
    rebuilt = np.zeros((3, 3))
    rebuilt[perm, np.arange(3)] = signs
    if np.max(np.abs(matrix - rebuilt)) > tol:
        return None
    return perm, signs


def obb_iou(verts_a: np.ndarray, verts_b: np.ndarray, target_grid: int = 64) -> float:
    """Intersection over union of two oriented bounding boxes.

    When the two boxes share their axes, which is the ordinary case for building
    elements, the ratio is computed exactly from the overlap of their extents.
    Otherwise the boxes are rasterised onto a shared regular grid whose longest
    side holds ``target_grid`` cells and the ratio is taken over occupied cells.
    """
    if len(verts_a) == 0 or len(verts_b) == 0:
        return 0.0
    ca, ha, ra = oriented_bbox(verts_a)
    cb, hb, rb = oriented_bbox(verts_b)

    mapping = _signed_permutation(ra.T @ rb)
    if mapping is not None:
        perm, _signs = mapping
        # Extents of box B along box A's axes, and the offset between centres.
        hb_a = np.zeros(3)
        hb_a[perm] = hb
        offset = ra.T @ (cb - ca)
        lo = np.maximum(-ha, offset - hb_a)
        hi = np.minimum(ha, offset + hb_a)
        overlap = np.maximum(0.0, hi - lo)
        inter = float(np.prod(overlap))
        vol_a = float(np.prod(2 * ha))
        vol_b = float(np.prod(2 * hb))
        union = vol_a + vol_b - inter
        if union <= 0.0:
            return 1.0 if inter > 0.0 else 0.0
        return inter / union

    corners = np.concatenate([_box_corners(ca, ha, ra), _box_corners(cb, hb, rb)], axis=0)
    lo = corners.min(axis=0)
    hi = corners.max(axis=0)
    extent = hi - lo
    longest = float(extent.max())
    if longest <= 0.0:
        return 1.0
    step = longest / target_grid
    dims = np.maximum(1, np.ceil(extent / step).astype(int))
    # Cell centres.
    axes = [lo[i] + (np.arange(dims[i]) + 0.5) * step for i in range(3)]
    grid = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    in_a = _inside(grid, ca, ha, ra)
    in_b = _inside(grid, cb, hb, rb)
    inter = int(np.count_nonzero(in_a & in_b))
    union = int(np.count_nonzero(in_a | in_b))
    if union == 0:
        return 0.0
    return inter / union
