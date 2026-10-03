"""Small checks that the geometric primitives behave as intended.

Run with ``python -m modifc_score.selftest``.
"""

from __future__ import annotations

import numpy as np

from .config import ScorerConfig
from .geometry import (allocate_samples, chamfer_median, exp_score, joint_bbox_diagonal,
                       obb_iou, oriented_bbox, sample_surface, triangle_areas)
from .model_cache import Mesh
from .properties import values_match
from .topology import _prf


def unit_box(size=(1.0, 1.0, 1.0), offset=(0.0, 0.0, 0.0)) -> Mesh:
    sx, sy, sz = size
    ox, oy, oz = offset
    corners = np.array([[x, y, z] for x in (0, sx) for y in (0, sy) for z in (0, sz)],
                       dtype=float) + np.array([ox, oy, oz], dtype=float)
    faces = np.array([
        [0, 1, 3], [0, 3, 2], [4, 7, 5], [4, 6, 7],
        [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],
        [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],
    ])
    return Mesh(verts=corners, faces=faces,
                area=float(triangle_areas(corners, faces).sum()))


def main() -> int:
    cfg = ScorerConfig()
    failures = []

    def check(name, condition):
        if not condition:
            failures.append(name)

    box = unit_box()
    check("box surface area", abs(box.area - 6.0) < 1e-9)

    # Identical boxes overlap perfectly; a box moved by its own width does not.
    check("obb identical", abs(obb_iou(box.verts, box.verts) - 1.0) < 1e-9)
    check("obb disjoint", obb_iou(box.verts, unit_box(offset=(2.0, 0, 0)).verts) == 0.0)
    half = unit_box(size=(1.0, 1.0, 0.5))
    check("obb nested", abs(obb_iou(box.verts, half.verts) - 0.5) < 1e-6)

    centre, extent, _rot = oriented_bbox(box.verts)
    check("obb centre", np.allclose(centre, [0.5, 0.5, 0.5]))
    check("obb extent", np.allclose(np.sort(extent), [0.5, 0.5, 0.5]))

    # The same surface sampled with the same seed gives the same points, so a
    # perfect prediction has distance zero and score one.
    a = sample_surface(box, 2048, np.random.default_rng(0))
    b = sample_surface(box, 2048, np.random.default_rng(0))
    check("sampling reproducible", np.array_equal(a, b))
    check("chamfer zero", chamfer_median(a, b) == 0.0)
    check("score of zero error", abs(exp_score(0.0, cfg.chamfer_scale) - 1.0) < 1e-12)

    diag = joint_bbox_diagonal(a, b)
    check("diagonal of unit box", abs(diag - np.sqrt(3.0)) < 0.05)

    # Sampling budget: one object takes the per-object cap, many objects share
    # the total budget without falling below the floor.
    check("one object budget", allocate_samples([6.0], 4096, 16384, 256) == [4096])
    counts = allocate_samples([1.0] * 100, 4096, 16384, 256)
    check("floor respected", min(counts) >= 256)
    check("cap respected", max(counts) <= 4096)

    # Property comparison: 5 % relative tolerance, exact for text and booleans.
    check("tolerance inside", values_match(1.0, 1.04, 0.05))
    check("tolerance outside", not values_match(1.0, 1.2, 0.05))
    check("text exact", values_match("Basic Wall", "Basic Wall", 0.05))
    check("text differs", not values_match("Basic Wall", "Other Wall", 0.05))
    check("missing value", not values_match("Basic Wall", None, 0.05))

    # Edit-set comparison, including the empty-against-empty case.
    check("prf equal", _prf({1, 2}, {1, 2}) == (1.0, 1.0, 1.0))
    check("prf empty both", _prf(set(), set()) == (1.0, 1.0, 1.0))
    check("prf empty reference", _prf(set(), {1}) == (0.0, 0.0, 0.0))
    check("prf half", _prf({1, 2}, {1})[0] == 1.0 and _prf({1, 2}, {1})[1] == 0.5)

    if failures:
        print("FAILED: " + ", ".join(failures))
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
