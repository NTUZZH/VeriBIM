"""Mutation study of the completion verdict (false acceptance).

For a stratified sample of 240 single-tier benchmark tasks (seed 20261007,
80 per operation), the ground-truth model is perturbed in ways a reviewer would
call wrong, and each perturbed copy is scored against the ground truth with the
same checker call the benchmark runs use for an edited file
(stage_a.scoring.score_prediction with the task's family reading,
geometry_mode per_pair).  The verdict is C = 1[min(geometry, semantics,
topology) >= threshold], read at 0.90 (the reported rule) and at 0.98.

Usage (from the project root, pinned, single-threaded):
  python mutation.py sample            # writes sample.json
  python mutation.py run [--workers 2] # appends mutation_results.jsonl (resumable)
  python mutation.py summarize         # writes mutation_summary.json, tab_mutation.tex

Only files under this directory and the scratch directory are written.  Inputs
(task records, gold archives, source models) are read only.
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import math
import os
import random
import re
import shutil
import statistics
import sys
import time
import traceback
from pathlib import Path

import numpy as np

ROOT = Path(os.environ.get("VERIBIM_ROOT", "."))
BENCH = ROOT / "runs_local/bench_v4"
OUT = ROOT / "analysis/revision/checker"
SCRATCH = Path(os.environ.get("VERIBIM_SCRATCH", "work/checker"))   # working copies of the models
# The task file the reported runs were scored against (eval_bench_v4.sh); the
# manifest names the v4 file, which differs from v4c in 103 records.
TASKS = BENCH / "tasks.v4c.jsonl"
GOLD_DIRS = ("models_v4c", "models_v4b", "models")
SEED = 20261007
N_PER_OP = 80
RESULTS = OUT / "mutation_results.jsonl"
SAMPLE = OUT / "sample.json"

SHIFT_FRACTIONS = (0.05, 0.10, 0.20, 0.50)
SCALE_FACTORS = (0.98, 0.95, 0.90, 0.80)
FILLINGS = ("IfcDoor", "IfcWindow")

sys.path.insert(0, str(ROOT / "code"))


# ---------------------------------------------------------------- records


def load_tasks() -> dict[str, dict]:
    with open(TASKS, encoding="utf-8") as fh:
        return {r["task_id"]: r for r in (json.loads(l) for l in fh if l.strip())}


def gold_archive(task_id: str, record: dict | None = None) -> Path:
    # a re-golded record names its own archive (models_v4b/<id>.v4b.ifc)
    for k in ("ground_truth_ifc", "gold_model"):
        if record is not None and record.get(k):
            p = ROOT / (record[k] + ".gz")
            if p.is_file():
                return p
    for d in GOLD_DIRS:
        p = BENCH / d / f"{task_id}.ifc.gz"
        if p.is_file():
            return p
    raise FileNotFoundError(task_id)


def unpack_gold(record: dict, dest_dir: Path) -> Path:
    """Gunzip the task's ground truth into scratch and check its sha256."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = gold_archive(record["task_id"], record)
    out = dest_dir / f"{record['task_id']}.gold.ifc"
    digest = hashlib.sha256()
    with gzip.open(src, "rb") as fi, open(out, "wb") as fo:
        for block in iter(lambda: fi.read(1 << 20), b""):
            digest.update(block)
            fo.write(block)
    expected = (record.get("verification") or {}).get("gold_sha256")
    if expected and digest.hexdigest() != expected:
        out.unlink()
        raise ValueError(f"gold sha256 mismatch for {record['task_id']}")
    return out


# ---------------------------------------------------------------- sample


def build_sample() -> list[str]:
    tasks = load_tasks()
    rng = random.Random(SEED)
    pool = [r for r in tasks.values()
            if r["tier"] == "single" and not r.get("clarification")
            and (r.get("target") or {}).get("guids")]
    chosen: list[str] = []
    for op in ("create", "update", "delete"):
        rows = sorted((r for r in pool if r["operation"] == op), key=lambda r: r["task_id"])
        cells = sorted({(r["ifc_version"], r["category"]) for r in rows})
        base, extra = divmod(N_PER_OP, len(cells))
        bonus = set(rng.sample(range(len(cells)), extra))
        quota = {c: base + (1 if i in bonus else 0) for i, c in enumerate(cells)}
        used_b: collections.Counter = collections.Counter()
        used_k: collections.Counter = collections.Counter()
        for cell in cells:
            cand = [r for r in rows if (r["ifc_version"], r["category"]) == cell]
            rng.shuffle(cand)
            for _ in range(quota[cell]):
                # spread over buildings first, then over edit kinds and classes
                best = min(cand, key=lambda r: (
                    used_b[r["building_id"]],
                    used_k[(r["edit_kind"], r["target"]["entity_type"])]))
                cand.remove(best)
                used_b[best["building_id"]] += 1
                used_k[(best["edit_kind"], best["target"]["entity_type"])] += 1
                chosen.append(best["task_id"])
    return chosen


# ---------------------------------------------------------------- geometry


def mesh(entity):
    from modifc_score.geometry import build_mesh
    return build_mesh(entity, 0.001, False)


def horiz_axis(verts: np.ndarray) -> np.ndarray:
    xy = verts[:, :2] - verts[:, :2].mean(axis=0)
    if len(xy) < 2:
        return np.array([1.0, 0.0, 0.0])
    cov = np.cov(xy, rowvar=False)
    vals, vecs = np.linalg.eigh(cov)
    v = vecs[:, int(np.argmax(vals))]
    u = np.array([v[0], v[1], 0.0])
    n = np.linalg.norm(u)
    u = u / n if n else np.array([1.0, 0.0, 0.0])
    # canonical sign, so the axis is reproducible
    if u[0] < -1e-9 or (abs(u[0]) <= 1e-9 and u[1] < 0):
        u = -u
    return u


def span(verts: np.ndarray, u: np.ndarray) -> tuple[float, float]:
    p = verts @ u
    return float(p.min()), float(p.max())


def filled_opening(product):
    for rel in getattr(product, "FillsVoids", ()) or ():
        return rel.RelatingOpeningElement
    return None


def host_of(product):
    opening = filled_opening(product)
    if opening is None:
        return None
    for rel in getattr(opening, "VoidsElements", ()) or ():
        return rel.RelatingBuildingElement
    return None


def placement_ancestors(product) -> list:
    out = []
    p = getattr(product, "ObjectPlacement", None)
    p = getattr(p, "PlacementRelTo", None) if p is not None else None
    while p is not None:
        out.append(p.id())
        p = getattr(p, "PlacementRelTo", None)
    return out


def movers(product) -> list:
    """The product plus its filled opening, minus members carried by another."""
    group = [product]
    opening = filled_opening(product)
    if opening is not None:
        group.append(opening)
    own = {m.id(): m.ObjectPlacement.id() for m in group if m.ObjectPlacement is not None}
    keep = []
    for m in group:
        anc = set(placement_ancestors(m))
        if any(own.get(o.id()) in anc for o in group if o is not m):
            continue
        keep.append(m)
    return keep


def ensure_own_placement(model, product) -> None:
    placement = product.ObjectPlacement
    users = [i for i in model.get_inverse(placement)
             if i.is_a("IfcProduct") and i.id() != product.id()]
    if users:
        product.ObjectPlacement = model.create_entity(
            "IfcLocalPlacement", PlacementRelTo=placement.PlacementRelTo,
            RelativePlacement=placement.RelativePlacement)


def translate_world(model, product, vec_m) -> None:
    from modifc_gen import goldlib
    ensure_own_placement(model, product)
    goldlib.translate(model, product.GlobalId, float(vec_m[0]), float(vec_m[1]),
                      float(vec_m[2]))


def transform_world(model, product, T_m: np.ndarray) -> None:
    """Apply a world transform given in metres to a product's frame."""
    from modifc_gen import goldlib
    ensure_own_placement(model, product)
    scale = goldlib.unit_scale(model)
    T = np.array(T_m, dtype=float).copy()
    T[:3, 3] = T[:3, 3] / scale
    W = goldlib._placement_matrix(product.ObjectPlacement)
    goldlib._write_world_frame(model, product, goldlib._clean(T @ W))


# ---------------------------------------------------------------- task context


class Ctx:
    def __init__(self, record: dict, model) -> None:
        from modifc_gen import goldlib
        self.r = record
        self.m = model
        self.scale = goldlib.unit_scale(model)
        self.targets = []
        for g in record["target"]["guids"]:
            try:
                self.targets.append(model.by_guid(g))
            except Exception:
                pass
        self.meshes = {t.GlobalId: mesh(t) for t in self.targets}
        self.axes = {}
        for t in self.targets:
            self.axes[t.GlobalId] = self._axis(t)

    def _axis(self, t):
        """(unit axis, lo, hi) of the target's long axis in world metres."""
        m = self.meshes.get(t.GlobalId)
        if m is None:
            return None
        if t.is_a("IfcColumn"):
            u = np.array([0.0, 0.0, 1.0])
        elif t.is_a() in FILLINGS or any(t.is_a(c) for c in FILLINGS):
            host = host_of(t)
            hm = mesh(host) if host is not None else None
            u = horiz_axis(hm.verts if hm is not None else m.verts)
        else:
            u = horiz_axis(m.verts)
        lo, hi = span(m.verts, u)
        return u, lo, hi

    def width_axis(self, t):
        m = self.meshes.get(t.GlobalId)
        if m is None:
            return None
        if any(t.is_a(c) for c in FILLINGS):
            return self.axes[t.GlobalId][0]
        return horiz_axis(m.verts)


def is_filling(t) -> bool:
    return any(t.is_a(c) for c in FILLINGS)


# ---------------------------------------------------------------- perturbations
# Each returns a details dict when applied, or raises NotApplicable(reason).


class NotApplicable(Exception):
    pass


def p_shift(ctx: Ctx, frac: float | None = None, metres: float | None = None):
    moved = []
    for t in ctx.targets:
        ax = ctx.axes.get(t.GlobalId)
        if ax is None:
            raise NotApplicable("target has no geometry")
        u, lo, hi = ax
        if metres is not None:
            if not is_filling(t):
                raise NotApplicable("absolute 0.30 m shift is for doors and windows")
            d = metres
        else:
            d = frac * (hi - lo)
        for mv in movers(t):
            translate_world(ctx.m, mv, u * d)
        moved.append({"guid": t.GlobalId, "class": t.is_a(), "axis": [round(x, 4) for x in u],
                      "extent_m": round(hi - lo, 4), "shift_m": round(d, 4)})
    return {"moved": moved}


def wrap_scaled(model, product, anchor_world_m, axes_world, scales) -> None:
    """Replace the product's Body by a mapped copy scaled about an anchor.

    ``axes_world`` = (e1, e3): the first scaling axis and the vertical, in
    world axes; ``scales`` = (s1, s2, s3) along e1, e2 = e3 x e1, e3.
    """
    from modifc_gen import goldlib
    body = goldlib.body_representation(product)
    if body is None:
        raise NotApplicable("no Body representation")
    W = goldlib._placement_matrix(product.ObjectPlacement)
    R = W[:3, :3]
    scale = goldlib.unit_scale(model)
    anchor_file = np.asarray(anchor_world_m, dtype=float) / scale
    a_loc = np.linalg.inv(W) @ np.append(anchor_file, 1.0)
    e1 = R.T @ np.asarray(axes_world[0], float)
    e3 = R.T @ np.asarray(axes_world[1], float)
    e1 = e1 - e3 * float(e1 @ e3)
    e1 /= np.linalg.norm(e1)
    e3 /= np.linalg.norm(e3)
    e2 = np.cross(e3, e1)

    def d(v):
        return model.create_entity("IfcDirection", DirectionRatios=tuple(float(x) for x in v))

    def pt(v):
        return model.create_entity("IfcCartesianPoint", Coordinates=tuple(float(x) for x in v[:3]))

    # IfcOpenShell composes a mapped item as Target(Origin(x)) (checked on a
    # test element: the extent along e1 scales by s1 about the anchor and the
    # other extents are unchanged), so the origin carries U^T(x - c).
    U = np.column_stack([e1, e2, e3])
    Ut = U.T
    origin = model.create_entity("IfcAxis2Placement3D", Location=pt(-(Ut @ a_loc[:3])),
                                 Axis=d(Ut[:, 2]), RefDirection=d(Ut[:, 0]))
    rmap = model.create_entity("IfcRepresentationMap", MappingOrigin=origin,
                               MappedRepresentation=body)
    op = model.create_entity("IfcCartesianTransformationOperator3DnonUniform",
                             Axis1=d(e1), Axis2=d(e2), LocalOrigin=pt(a_loc),
                             Scale=float(scales[0]), Axis3=d(e3),
                             Scale2=float(scales[1]), Scale3=float(scales[2]))
    item = model.create_entity("IfcMappedItem", MappingSource=rmap, MappingTarget=op)
    rep = model.create_entity("IfcShapeRepresentation", ContextOfItems=body.ContextOfItems,
                              RepresentationIdentifier="Body",
                              RepresentationType="MappedRepresentation", Items=[item])
    old = product.Representation
    reps = [rep if r == body else r for r in (old.Representations or ())]
    product.Representation = model.create_entity(
        "IfcProductDefinitionShape", Name=old.Name, Description=old.Description,
        Representations=reps)


def p_scale(ctx: Ctx, dim: str, s: float):
    done = []
    for t in ctx.targets:
        m = ctx.meshes.get(t.GlobalId)
        if m is None:
            raise NotApplicable("target has no geometry")
        z = np.array([0.0, 0.0, 1.0])
        if dim == "width":
            u = ctx.width_axis(t)
            lo, hi = span(m.verts, u)
            centre = m.verts.mean(axis=0)
            anchor = centre + u * (lo - float(centre @ u))  # start of the element
            wrap_scaled(ctx.m, t, anchor, (u, z), (s, 1.0, 1.0))
            attr = "OverallWidth"
            extent = hi - lo
        else:
            u = ctx.width_axis(t)
            centre = m.verts.mean(axis=0)
            zlo = float(m.verts[:, 2].min())
            anchor = np.array([centre[0], centre[1], zlo])  # stands on its base
            wrap_scaled(ctx.m, t, anchor, (u, z), (1.0, 1.0, s))
            attr = "OverallHeight"
            extent = float(np.ptp(m.verts[:, 2]))
        # the wrapped body must have exactly the intended extent
        after = mesh(t)
        if after is None:
            raise RuntimeError("scaled body does not mesh")
        if dim == "width":
            lo2, hi2 = span(after.verts, u)
            ok = abs((hi2 - lo2) - s * extent) <= 2e-3 + 1e-3 * extent and abs(lo2 - lo) <= 2e-3
            z_ok = abs(float(np.ptp(after.verts[:, 2])) - float(np.ptp(m.verts[:, 2]))) <= 2e-3
            ok = ok and z_ok
        else:
            h2 = float(np.ptp(after.verts[:, 2]))
            ok = abs(h2 - s * extent) <= 2e-3 + 1e-3 * extent \
                and abs(float(after.verts[:, 2].min()) - zlo) <= 2e-3
        if not ok:
            raise RuntimeError("scaled body does not have the intended extent")
        changed_attr = None
        if is_filling(t) and getattr(t, attr, None) is not None:
            setattr(t, attr, float(getattr(t, attr)) * s)
            changed_attr = attr
        done.append({"guid": t.GlobalId, "class": t.is_a(), "extent_m": round(extent, 4),
                     "attribute_scaled": changed_attr})
    return {"scaled": done}


GOLD_CALL = re.compile(r"goldlib\.(\w+)\((.*?)\)\n", re.S)


def gold_calls(record: dict) -> list[tuple[str, dict]]:
    """(function, keyword arguments) of every goldlib call in the gold script."""
    import ast
    out = []
    src = record.get("gold_script") or ""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == "goldlib":
            kw = {}
            for k in node.keywords:
                try:
                    kw[k.arg] = ast.literal_eval(k.value)
                except Exception:
                    kw[k.arg] = None
            out.append((node.func.attr, kw))
    return out


def p_opposite(ctx: Ctx):
    r, kind = ctx.r, ctx.r["edit_kind"]
    calls = gold_calls(r)
    if r["operation"] == "update" and kind == "translate":
        c = [kw for f, kw in calls if f == "translate"]
        if not c:
            raise NotApplicable("no translate call in the gold script")
        out = []
        for kw in c:
            t = ctx.m.by_guid(kw["guid"])
            v = np.array([kw.get("dx", 0.0), kw.get("dy", 0.0), kw.get("dz", 0.0)], float)
            translate_world(ctx.m, t, -2.0 * v)
            out.append({"guid": kw["guid"], "gold_offset_m": v.round(4).tolist()})
        return {"opposite_translation": out}
    if r["operation"] == "update" and kind == "rotate":
        from modifc_gen import goldlib
        c = [kw for f, kw in calls if f == "rotate"]
        if not c:
            raise NotApplicable("no rotate call in the gold script")
        for kw in c:
            ensure_own_placement(ctx.m, ctx.m.by_guid(kw["guid"]))
            goldlib.rotate(ctx.m, kw["guid"], -2.0 * float(kw["degrees"]),
                           kw["pivot_x"], kw["pivot_y"])
        return {"opposite_rotation_deg": [-float(kw["degrees"]) for kw in c]}
    if r["operation"] == "create" and kind in ("copy_element", "array_elements"):
        src = ctx.r["edit_params"].get("source_guid")
        try:
            sm = mesh(ctx.m.by_guid(src))
        except Exception:
            sm = None
        if sm is None:
            raise NotApplicable("source element has no geometry")
        c0 = sm.verts.mean(axis=0)
        out = []
        for t in ctx.targets:
            m = ctx.meshes.get(t.GlobalId)
            v = m.verts.mean(axis=0) - c0
            translate_world(ctx.m, t, -2.0 * v)
            out.append({"guid": t.GlobalId, "offset_from_source_m": v.round(4).tolist()})
        return {"copy_on_other_side": out}
    if r["operation"] == "create" and kind == "create_box":
        off = ctx.r["edit_params"].get("offset")
        if not off:
            raise NotApplicable("box placed by absolute coordinates; no side to mirror")
        sx = -1.0 if str(off.get("x_axis", "+X")).startswith("-") else 1.0
        sy = -1.0 if str(off.get("y_axis", "+Y")).startswith("-") else 1.0
        v = np.array([sx * float(off.get("dx", 0.0)), sy * float(off.get("dy", 0.0)), 0.0])
        for t in ctx.targets:
            translate_world(ctx.m, t, -2.0 * v)
        return {"mirrored_offset_from_reference_m": v.round(4).tolist()}
    if kind in ("create_filling", "rehost_filling"):
        out = []
        for t in ctx.targets:
            host = host_of(t)
            hm = mesh(host) if host is not None else None
            if hm is None:
                raise NotApplicable("no host geometry")
            u = ctx.axes[t.GlobalId][0]
            a0, a1 = span(hm.verts, u)
            c = float(ctx.meshes[t.GlobalId].verts.mean(axis=0) @ u)
            d = a0 + a1 - 2.0 * c
            for mv in movers(t):
                translate_world(ctx.m, mv, u * d)
            out.append({"guid": t.GlobalId, "shift_m": round(d, 4),
                        "along_from_start_m": round(c - a0, 4), "host_length_m": round(a1 - a0, 4)})
        return {"measured_from_other_end": out}
    raise NotApplicable(f"no direction to reverse for {r['operation']}/{kind}")


def _storey_of(product):
    from modifc_gen import goldlib
    return goldlib._containing_storey(product)


def p_wrong_host(ctx: Ctx):
    r = ctx.r
    if r["edit_kind"] not in ("create_filling", "replace_filling", "rehost_filling"):
        raise NotApplicable("not a hosted door or window edit")
    out = []
    for t in ctx.targets:
        if not is_filling(t):
            raise NotApplicable("target is not a door or window")
        host = host_of(t)
        opening = filled_opening(t)
        if host is None or opening is None:
            raise NotApplicable("filling has no host wall")
        tm = ctx.meshes[t.GlobalId]
        p = tm.verts.mean(axis=0)
        width = span(tm.verts, ctx.axes[t.GlobalId][0])
        width = width[1] - width[0]
        zlo, zhi = float(tm.verts[:, 2].min()), float(tm.verts[:, 2].max())
        storey = _storey_of(host)
        walls = []
        for cls in ("IfcWall",):
            for w in ctx.m.by_type(cls):
                if w.id() == host.id():
                    continue
                if storey is not None and _storey_of(w) is not None and _storey_of(w).id() != storey.id():
                    continue
                walls.append(w)
        # nearest by placement origin first, then by the wall's centreline
        from modifc_gen import goldlib

        def origin(w):
            M = goldlib._placement_matrix(w.ObjectPlacement)
            return M[:3, 3] * ctx.scale
        walls.sort(key=lambda w: float(np.linalg.norm((origin(w) - p)[:2])))
        best = None
        for w in walls[:25]:
            wm = mesh(w)
            if wm is None:
                continue
            u = horiz_axis(wm.verts)
            t0, t1 = span(wm.verts, u)
            if t1 - t0 < width + 0.1:
                continue
            wz0, wz1 = float(wm.verts[:, 2].min()), float(wm.verts[:, 2].max())
            overlap = max(0.0, min(zhi, wz1) - max(zlo, wz0))
            if overlap < 0.5 * (zhi - zlo):
                continue
            c = wm.verts.mean(axis=0)
            n = np.array([-u[1], u[0], 0.0])
            tp = float(np.clip(p @ u, t0 + width / 2 + 0.05, t1 - width / 2 - 0.05))
            q = c + u * (tp - float(c @ u))
            q[2] = p[2]
            dist = float(np.linalg.norm((q - p)[:2]))
            if best is None or dist < best[0]:
                best = (dist, w, u, q)
        if best is None:
            raise NotApplicable("no other wall on the storey can take the filling")
        dist, w, u2, q = best
        u1 = ctx.axes[t.GlobalId][0]
        if float(u1 @ u2) < 0:
            u2 = -u2
        theta = math.atan2(u1[0] * u2[1] - u1[1] * u2[0], float(u1 @ u2))
        Rz = np.identity(4)
        Rz[0, 0], Rz[0, 1], Rz[1, 0], Rz[1, 1] = math.cos(theta), -math.sin(theta), math.sin(theta), math.cos(theta)
        Tq, Tp = np.identity(4), np.identity(4)
        Tq[:3, 3] = q
        Tp[:3, 3] = -p
        T = Tq @ Rz @ Tp
        for mv in movers(t):
            transform_world(ctx.m, mv, T)
        for rel in opening.VoidsElements or ():
            rel.RelatingBuildingElement = w
        out.append({"guid": t.GlobalId, "new_host": w.GlobalId, "new_host_name": w.Name,
                    "move_m": round(dist, 3), "turn_deg": round(math.degrees(theta), 2)})
    return {"rehosted": out}


def p_drop_relation(ctx: Ctx, which: str):
    removed = []
    for t in ctx.targets:
        if which == "containment":
            rels = [r for r in (getattr(t, "ContainedInStructure", ()) or ())]
            rels += [r for r in (getattr(t, "Decomposes", ()) or ()) if r.is_a("IfcRelAggregates")]
            for rel in rels:
                rel_cls = rel.is_a()
                attr = "RelatedElements" if rel_cls == "IfcRelContainedInSpatialStructure" else "RelatedObjects"
                rest = [x for x in getattr(rel, attr) if x != t]
                if rest:
                    setattr(rel, attr, tuple(rest))
                    removed.append(rel_cls)
                else:
                    ctx.m.remove(rel)
                    removed.append(rel_cls + " (relationship removed)")
        elif which == "filling":
            rels = list(getattr(t, "FillsVoids", ()) or ())
            for rel in rels:
                ctx.m.remove(rel)
                removed.append("IfcRelFillsElement")
        elif which == "type":
            rels = [r for r in (getattr(t, "IsTypedBy", ()) or ())]
            rels += [r for r in (getattr(t, "IsDefinedBy", ()) or ()) if r.is_a("IfcRelDefinesByType")]
            for rel in rels:
                rest = [x for x in rel.RelatedObjects if x != t]
                if rest:
                    rel.RelatedObjects = tuple(rest)
                else:
                    ctx.m.remove(rel)
                removed.append("IfcRelDefinesByType")
    if not removed:
        raise NotApplicable(f"target has no {which} relation in the ground truth")
    return {"removed": removed}


def _enum_items(model, entity, attr):
    import ifcopenshell
    schema = ifcopenshell.ifcopenshell_wrapper.schema_by_name(model.schema_identifier
                                                              if hasattr(model, "schema_identifier")
                                                              else model.schema)
    decl = schema.declaration_by_name(entity.is_a())
    for a in decl.all_attributes():
        if a.name() == attr:
            t = a.type_of_attribute()
            while hasattr(t, "declared_type"):
                t = t.declared_type()
            if hasattr(t, "enumeration_items"):
                return list(t.enumeration_items())
    return []


def p_attribute(ctx: Ctx, attr: str):
    changed = []
    for t in ctx.targets:
        if not hasattr(t, attr):
            raise NotApplicable(f"{t.is_a()} has no {attr} in this schema")
        old = getattr(t, attr)
        if old is None:
            raise NotApplicable(f"{attr} is empty in the ground truth")
        if attr == "PredefinedType":
            items = [i for i in sorted(_enum_items(ctx.m, t, attr))
                     if i not in (old, "USERDEFINED", "NOTDEFINED")]
            if not items:
                raise NotApplicable("no other predefined type")
            new = items[0]
        else:
            new = f"{old} B"
        setattr(t, attr, new)
        changed.append({"guid": t.GlobalId, "old": str(old), "new": str(new)})
    return {"changed": changed}


def _numeric(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def p_property(ctx: Ctx):
    """One numeric property (or quantity) value of each target scaled by 1.2."""
    from modifc_gen import goldlib
    model = ctx.m
    changed = []
    for t in ctx.targets:
        options = []
        for rel in getattr(t, "IsDefinedBy", ()) or ():
            if not rel.is_a("IfcRelDefinesByProperties"):
                continue
            ps = rel.RelatingPropertyDefinition
            if ps is None:
                continue
            if ps.is_a("IfcPropertySet"):
                for prop in ps.HasProperties or ():
                    if prop.is_a("IfcPropertySingleValue") and prop.NominalValue is not None \
                            and _numeric(prop.NominalValue.wrappedValue) \
                            and prop.NominalValue.wrappedValue != 0:
                        options.append((0, ps.Name or "", prop.Name or "", rel, ps, prop))
            elif ps.is_a("IfcElementQuantity"):
                for q in ps.Quantities or ():
                    vals = [i for i, n in enumerate(q.wrapped_data.get_attribute_names())
                            if n.endswith("Value") and _numeric(q[i]) and q[i] != 0]
                    if vals:
                        options.append((1, ps.Name or "", q.Name or "", rel, ps, q))
        if not options:
            raise NotApplicable("target has no numeric property or quantity of its own")
        options.sort(key=lambda o: (o[0], o[1], o[2]))
        kind, psname, pname, rel, ps, prop = options[0]
        # a shared set is split off first, so no other element changes
        members = list(rel.RelatedObjects or ())
        if len(members) > 1 or len(model.get_inverse(ps)) > 1:
            rel.RelatedObjects = tuple(x for x in members if x != t) or rel.RelatedObjects
            import ifcopenshell.guid
            if kind == 0:
                newprops = [goldlib._copy_property(model, p) for p in ps.HasProperties]
                ps = model.create_entity("IfcPropertySet", GlobalId=ifcopenshell.guid.new(),
                                         OwnerHistory=ps.OwnerHistory, Name=ps.Name,
                                         Description=ps.Description, HasProperties=newprops)
                prop = [p for p in newprops if p.Name == pname][0]
            else:
                newq = [model.create_entity(q.is_a(), *list(q)) for q in ps.Quantities]
                ps = model.create_entity("IfcElementQuantity", GlobalId=ifcopenshell.guid.new(),
                                         OwnerHistory=ps.OwnerHistory, Name=ps.Name,
                                         Description=ps.Description, MethodOfMeasurement=ps.MethodOfMeasurement,
                                         Quantities=newq)
                prop = [q for q in newq if q.Name == pname][0]
            model.create_entity("IfcRelDefinesByProperties", GlobalId=ifcopenshell.guid.new(),
                                OwnerHistory=rel.OwnerHistory, Name=None, Description=None,
                                RelatedObjects=[t], RelatingPropertyDefinition=ps)
        if kind == 0:
            nv = prop.NominalValue
            old = nv.wrappedValue
            new = (int(round(old * 1.2)) if isinstance(old, int) else old * 1.2)
            if new == old:
                new = old + 1
            fresh = model.create_entity(prop.is_a(), Name=prop.Name,
                                        NominalValue=model.create_entity(nv.is_a(), new),
                                        Unit=prop.Unit)
            ps.HasProperties = tuple(fresh if p == prop else p for p in ps.HasProperties)
        else:
            idx = [i for i, n in enumerate(prop.wrapped_data.get_attribute_names())
                   if n.endswith("Value") and _numeric(prop[i]) and prop[i] != 0][0]
            old = prop[idx]
            new = old * 1.2
            vals = list(prop)
            vals[idx] = new
            fresh = model.create_entity(prop.is_a(), *vals)
            ps.Quantities = tuple(fresh if q == prop else q for q in ps.Quantities)
        changed.append({"guid": t.GlobalId, "set": psname, "property": pname,
                        "old": old, "new": new})
    return {"changed": changed}


def p_offtarget(ctx: Ctx):
    """An unrelated element of the target class, the nearest one, moved 0.5 m."""
    from modifc_gen import goldlib
    tset = {t.GlobalId for t in ctx.targets}
    t0 = ctx.targets[0]
    c0 = ctx.meshes[t0.GlobalId].verts.mean(axis=0) if ctx.meshes.get(t0.GlobalId) else None
    if c0 is None:
        raise NotApplicable("target has no geometry")
    cls = "IfcWall" if t0.is_a("IfcWall") else t0.is_a()
    cands = []
    for e in ctx.m.by_type(cls):
        if e.GlobalId in tset or e.ObjectPlacement is None:
            continue
        M = goldlib._placement_matrix(e.ObjectPlacement)
        cands.append((float(np.linalg.norm(M[:3, 3] * ctx.scale - c0)), e))
    cands.sort(key=lambda x: x[0])
    for _, e in cands[:10]:
        em = mesh(e)
        if em is None:
            continue
        if is_filling(e):
            h = host_of(e)
            hm = mesh(h) if h is not None else None
            u = horiz_axis(hm.verts if hm is not None else em.verts)
        else:
            u = horiz_axis(em.verts)
        for mv in movers(e):
            translate_world(ctx.m, mv, u * 0.5)
        return {"moved": e.GlobalId, "class": e.is_a(), "distance_to_target_m": round(_, 3)}
    raise NotApplicable("no other element of the target class")


# delete tasks: perturbations rebuilt from the gold script on the source model

def script_apply(record: dict, model, src: str) -> None:
    ns: dict = {}
    exec(compile(src, f"<gold {record['task_id']}>", "exec"), ns)
    ns["apply_edit"](model)


def delete_neighbours(record: dict, model, n: int, exclude: set) -> list[str]:
    """The n nearest elements of the targets' class, not targets, by placement origin."""
    from modifc_gen import goldlib
    scale = goldlib.unit_scale(model)
    targets = [model.by_guid(g) for g in record["target"]["guids"]]
    cls = "IfcWall" if targets[0].is_a("IfcWall") else targets[0].is_a()
    origins = [goldlib._placement_matrix(t.ObjectPlacement)[:3, 3] * scale for t in targets
               if t.ObjectPlacement is not None]
    cands = []
    for e in model.by_type(cls):
        if e.GlobalId in exclude or e.ObjectPlacement is None or not e.Representation:
            continue
        o = goldlib._placement_matrix(e.ObjectPlacement)[:3, 3] * scale
        cands.append((min(float(np.linalg.norm(o - x)) for x in origins), e.GlobalId))
    cands.sort()
    return [g for _, g in cands[:n]]


# ---------------------------------------------------------------- self score


def self_geometry(ctx_meshes: list, cfg) -> list[float]:
    """Geometry of each reference mesh against itself, re-sampled with another seed."""
    from modifc_score import geometry as geo
    out = []
    for m in ctx_meshes:
        if m is None:
            continue
        a = geo.pooled_cloud([m], cfg.pooled_samples_per_object, cfg.pooled_max_total_samples,
                             cfg.pooled_min_samples_per_object, np.random.default_rng(0))
        b = geo.pooled_cloud([m], cfg.pooled_samples_per_object, cfg.pooled_max_total_samples,
                             cfg.pooled_min_samples_per_object, np.random.default_rng(1))
        diag = geo.joint_bbox_diagonal(a, b)
        cd = geo.chamfer_median(a, b, cfg.chamfer_reduction)
        out.append(geo.exp_score(cd / diag, cfg.chamfer_scale) if diag > 0 else 1.0)
    return out


# ---------------------------------------------------------------- worker


def plan(record: dict) -> list[tuple[str, str, object]]:
    """(class, magnitude, builder) for every perturbation of one task."""
    items: list = []
    if record["operation"] == "delete":
        return [("control", "gold script re-run", "del_control"),
                ("g_wrong_element", "nearest same-class element deleted instead", "del_wrong"),
                ("g_partial", "one of several targets left", "del_partial"),
                ("g_extra", "target and nearest same-class element deleted", "del_extra")]
    items.append(("control", "round trip", lambda c: {"note": "unchanged"}))
    for f in SHIFT_FRACTIONS:
        items.append(("a_shift", f"{int(f * 100)} %", lambda c, f=f: p_shift(c, frac=f)))
    items.append(("a_shift", "0.30 m", lambda c: p_shift(c, metres=0.30)))
    for dim in ("width", "height"):
        for s in SCALE_FACTORS:
            items.append((f"b_{dim}", f"x{s:.2f}", lambda c, dim=dim, s=s: p_scale(c, dim, s)))
    items.append(("c_direction", "opposite", p_opposite))
    items.append(("d_wrong_host", "nearest other wall", p_wrong_host))
    for which in ("containment", "filling", "type"):
        items.append(("e_relation", which, lambda c, w=which: p_drop_relation(c, w)))
    for attr in ("Name", "ObjectType", "PredefinedType"):
        items.append(("f_attribute", attr, lambda c, a=attr: p_attribute(c, a)))
    items.append(("f_attribute", "property value x1.2", p_property))
    items.append(("x_offtarget", "nearest same-class element moved 0.5 m", p_offtarget))
    return items


_W: dict = {}


def _init() -> None:
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    from modifc_score.model_cache import MESHES, MODELS
    MODELS.capacity = 3
    MESHES.capacity_vertices = 800_000


def _score(record, path, gold, cfg) -> dict:
    from stage_a.scoring import score_prediction
    s = score_prediction(record, Path(path), ROOT, gold_path=gold, config=cfg)
    d = s.as_dict()
    axes = [d["geometry"], d["semantics"], d["topology"]]
    d["accept_090"] = (d["error"] is None) and min(axes) >= 0.9
    d["accept_098"] = (d["error"] is None) and min(axes) >= 0.98
    return d


def run_task(task_id: str, skip: frozenset = frozenset(), emit=None) -> list[dict]:
    import ifcopenshell
    from modifc_score.model_cache import MESHES, MODELS
    from modifc_score.properties import property_score
    from stage_a.scoring import scorer_config_for
    tasks = _W.get("tasks") or load_tasks()
    _W["tasks"] = tasks
    record = tasks[task_id]
    work = SCRATCH / f"w{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    base = {k: record.get(k) for k in ("task_id", "operation", "category", "ifc_version",
                                       "building_id", "edit_kind", "origin")}
    base["target_class"] = record["target"]["entity_type"]
    base["n_targets"] = len(record["target"]["guids"])
    rows = []
    t_start = time.time()

    def add(row):
        row["task_seconds_so_far"] = round(time.time() - t_start, 1)
        rows.append(row)
        if emit is not None:
            emit(row)
    gold = unpack_gold(record, work)
    cfg = scorer_config_for(record)
    src_path = ROOT / record["input_ifc"]
    try:
        # null edit: the unedited source model
        if -2 not in skip:
            row = dict(base, pi=-2, pert="null_edit", magnitude="source model", applied=True)
            row.update(_score(record, src_path, gold, cfg))
            add(row)
        model = ifcopenshell.open(str(src_path if record["operation"] == "delete" else gold))
        if record["operation"] == "delete":
            ref_entities = [model.by_guid(g) for g in record["target"]["guids"]]
        else:
            ref_entities = [model.by_guid(g) for g in record["target"]["guids"]]
        start = work / f"{task_id}.start.ifc"
        model.write(str(start))
        start_sha = _sha(start)
        start.unlink(missing_ok=True)
        base_info = {}
        if record["operation"] != "delete":
            ctx = Ctx(record, model)
            meshes = [ctx.meshes.get(t.GlobalId) for t in ctx.targets]
            base_info["n_semantic_keys"] = [
                property_score(t, t, cfg.properties_tolerance, cfg.properties_ignore,
                               cfg.properties_include_material, cfg.properties_include_type)["n_keys"]
                for t in ctx.targets]
            base_info["target_extent_m"] = [round(ax[2] - ax[1], 3) if ax else None
                                            for ax in (ctx.axes.get(t.GlobalId) for t in ctx.targets)]
        else:
            ctx = None
            meshes = [mesh(e) for e in ref_entities]
        sg = self_geometry(meshes, cfg)
        if -1 not in skip:
            add(dict(base, pi=-1, pert="self_score", magnitude="re-sampled ground truth",
                         applied=True, geometry=float(np.median(sg)) if sg else None,
                         self_geometry_per_target=sg))
        for pi, (cls, mag, builder) in enumerate(plan(record)):
            if pi in skip:
                continue
            row = dict(base, pi=pi, pert=cls, magnitude=mag, **base_info)
            path = work / f"{task_id}.pert.ifc"
            try:
                model.begin_transaction()
                try:
                    if record["operation"] == "delete":
                        details = build_delete(record, model, builder)
                    else:
                        ctx.m = model
                        details = builder(ctx)
                finally:
                    model.end_transaction()
                model.write(str(path))
                row["applied"] = True
                row["details"] = details
            except NotApplicable as na:
                row.update(applied=False, not_applicable=str(na))
            except Exception as exc:  # noqa: BLE001
                row.update(applied=False, build_error=f"{type(exc).__name__}: {exc}"[:300])
            finally:
                try:
                    model.undo()
                except Exception as exc:  # noqa: BLE001
                    row["undo_error"] = str(exc)[:200]
                    model = ifcopenshell.open(str(src_path if record["operation"] == "delete" else gold))
                    if ctx is not None:
                        ctx = Ctx(record, model)
            if row.get("applied"):
                row.update(_score(record, path, gold, cfg))
                # keep the source and the ground truth resident; drop the perturbed copy
                with MODELS._lock:
                    for key in [k for k in MODELS._store if k[0] == str(path.resolve())]:
                        MODELS._store.pop(key)
                for key in [k for k in list(MESHES._store) if k[0][0] == str(path.resolve())]:
                    MESHES._store.pop(key, None)
                path.unlink(missing_ok=True)
            add(row)
        # the transaction log must have restored the starting model exactly
        check = work / f"{task_id}.after_undo.ifc"
        model.write(str(check))
        add(dict(base, pi=999, pert="undo_check", magnitude="transaction log restored the start model",
                 applied=True, undo_clean=_sha(check) == start_sha))
        check.unlink(missing_ok=True)
    finally:
        gold.unlink(missing_ok=True)
        MESHES.clear()
        MODELS.clear()
    secs = round(time.time() - t_start, 1)
    for r in rows:
        r["task_seconds"] = secs
    return rows


def _sha(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def build_delete(record: dict, model, which: str):
    src = record["gold_script"]
    targets = list(record["target"]["guids"])
    if which == "del_control":
        script_apply(record, model, src)
        return {"note": "gold script applied to the source model"}
    if which == "del_wrong":
        repl = delete_neighbours(record, model, len(targets), set(targets))
        if len(repl) < len(targets):
            raise NotApplicable("not enough other elements of the class")
        s2 = src
        for a, b in zip(targets, repl):
            if a not in s2:
                raise NotApplicable("target id not in the gold script")
            s2 = s2.replace(f"'{a}'", f"'{b}'")
        script_apply(record, model, s2)
        return {"deleted_instead": repl}
    if which == "del_partial":
        if len(targets) < 2:
            raise NotApplicable("single-target delete")
        keep = sorted(targets)[-1]
        lines = src.split("\n")
        out, skip = [], False
        for ln in lines:
            if f"'{keep}'" in ln and "goldlib." in ln:
                continue
            out.append(ln)
        s2 = "\n".join(out)
        if s2 == src:
            raise NotApplicable("could not isolate the call for one target")
        script_apply(record, model, s2)
        return {"left_in_place": keep}
    if which == "del_extra":
        extra = delete_neighbours(record, model, 1, set(targets))
        if not extra:
            raise NotApplicable("no other element of the class")
        script_apply(record, model, src)
        fn = [f for f, kw in gold_calls(record) if kw.get("guid") in targets]
        fn = fn[0] if fn else "delete_element"
        from modifc_gen import goldlib
        getattr(goldlib, fn)(model, guid=extra[0])
        return {"also_deleted": extra[0], "function": fn}
    raise ValueError(which)


# ---------------------------------------------------------------- driver


def cmd_sample() -> None:
    ids = build_sample()
    tasks = load_tasks()
    rows = [tasks[i] for i in ids]
    meta = {
        "seed": SEED, "tasks_file": str(TASKS), "n": len(ids), "task_ids": ids,
        "by_operation": dict(collections.Counter(r["operation"] for r in rows)),
        "by_version_category": {f"{k[0]}/{k[1]}/{k[2]}": v for k, v in sorted(collections.Counter(
            (r["operation"], r["ifc_version"], r["category"]) for r in rows).items())},
        "n_buildings": len({r["building_id"] for r in rows}),
        "by_building": dict(collections.Counter(r["building_id"] for r in rows)),
        "by_edit_kind": {f"{k[0]}/{k[1]}/{k[2]}": v for k, v in sorted(collections.Counter(
            (r["operation"], r["edit_kind"], r["target"]["entity_type"]) for r in rows).items())},
        "rule": "tier single, no clarification task, target GlobalIds given; per operation 80 tasks "
                "over the 9 (version, category) cells (8 or 9 each, extra slots by seeded draw); "
                "inside a cell, seeded shuffle then the least-used building, then the least-used "
                "(edit kind, class)",
    }
    SAMPLE.write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("n", "by_operation", "n_buildings")}))


def cmd_run(workers: int, limit: int) -> None:
    """Each task runs in its own child process, so a crash in the geometry
    kernel costs one perturbation, which is recorded, and never the run."""
    import subprocess
    import threading
    from concurrent.futures import ThreadPoolExecutor
    ids = json.loads(SAMPLE.read_text())["task_ids"]
    done = set()
    if RESULTS.exists():
        for l in open(RESULTS):
            done.add(json.loads(l)["task_id"])
    todo = [i for i in ids if i not in done]
    if limit:
        todo = todo[:limit]
    print(f"{len(todo)} tasks to run, {len(done)} done", flush=True)
    lock = threading.Lock()
    started = time.time()
    counter = [0]
    tasks = load_tasks()

    def one(task_id: str) -> None:
        partial = SCRATCH / "partial" / f"{task_id}.jsonl"
        partial.parent.mkdir(parents=True, exist_ok=True)
        partial.unlink(missing_ok=True)
        skip: set = set()
        crashes = []
        n_plan = len(plan(tasks[task_id]))
        for attempt in range(8):
            cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "child", "--task", task_id,
                   "--partial", str(partial), "--skip", ",".join(str(x) for x in sorted(skip))]
            proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            rows = [json.loads(l) for l in open(partial)] if partial.exists() else []
            got = {r["pi"] for r in rows}
            if proc.returncode == 0:
                break
            order = [-2, -1] + list(range(n_plan)) + [999]
            nxt = next((x for x in order if x not in got and x not in skip), None)
            crashes.append({"task_id": task_id, "pi": nxt, "pert": "crash",
                            "returncode": proc.returncode, "tail": proc.stdout[-600:]})
            skip = set(got) | set(skip) | ({nxt} if nxt is not None else set())
        rows = [json.loads(l) for l in open(partial)] if partial.exists() else []
        if proc.returncode != 0:
            crashes.append({"task_id": task_id, "pert": "task_error", "returncode": proc.returncode,
                            "tail": proc.stdout[-600:]})
        with lock:
            with open(RESULTS, "a") as sink:
                for r in rows + crashes:
                    sink.write(json.dumps(r, default=str) + "\n")
            counter[0] += 1
            secs = max([r.get("task_seconds_so_far") or 0 for r in rows] or [0])
            print(f"{counter[0]}/{len(todo)} {task_id} rows={len(rows)} crashes={len(crashes)} "
                  f"t={secs}s elapsed={time.time() - started:.0f}s", flush=True)
        partial.unlink(missing_ok=True)

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, todo))
    print(f"run finished in {time.time() - started:.0f}s", flush=True)


def cmd_child(task_id: str, partial: str, skip: str) -> None:
    _init()
    skip_set = frozenset(int(x) for x in skip.split(",") if x.strip())
    with open(partial, "a") as fh:
        def emit(row):
            fh.write(json.dumps(row, default=str) + "\n")
            fh.flush()
        try:
            run_task(task_id, skip_set, emit)
        except Exception as exc:  # noqa: BLE001
            emit({"task_id": task_id, "pi": -99, "pert": "task_error",
                  "error": f"{type(exc).__name__}: {exc}"[:400],
                  "trace": traceback.format_exc()[-1500:]})


LABELS = [
    ("control", "round trip", "Correct edit (ground truth written again)"),
    ("control", "gold script re-run", "Delete: correct deletion re-run on the source"),
    ("null_edit", "source model", "No edit (unedited source model)"),
    ("a_shift", "5 %", "Shift along the element axis, 5\\,\\% of its length"),
    ("a_shift", "10 %", "Shift along the element axis, 10\\,\\%"),
    ("a_shift", "20 %", "Shift along the element axis, 20\\,\\%"),
    ("a_shift", "50 %", "Shift along the element axis, 50\\,\\%"),
    ("a_shift", "0.30 m", "Door or window shifted 0.30\\,m along its wall"),
    ("c_direction", "opposite", "Opposite direction or other side"),
    ("b_width", "x0.98", "Width $\\times$0.98"),
    ("b_width", "x0.95", "Width $\\times$0.95"),
    ("b_width", "x0.90", "Width $\\times$0.90"),
    ("b_width", "x0.80", "Width $\\times$0.80"),
    ("b_height", "x0.98", "Height $\\times$0.98"),
    ("b_height", "x0.95", "Height $\\times$0.95"),
    ("b_height", "x0.90", "Height $\\times$0.90"),
    ("b_height", "x0.80", "Height $\\times$0.80"),
    ("d_wrong_host", "nearest other wall", "Door or window in the nearest other wall"),
    ("e_relation", "containment", "Storey containment removed"),
    ("e_relation", "filling", "Opening filling relation removed"),
    ("e_relation", "type", "Type assignment removed"),
    ("f_attribute", "Name", "Name changed"),
    ("f_attribute", "ObjectType", "Object type changed"),
    ("f_attribute", "PredefinedType", "Predefined type changed"),
    ("f_attribute", "property value x1.2", "One property value raised by 20\\,\\%"),
    ("x_offtarget", "nearest same-class element moved 0.5 m", "Unrelated element of the same class moved 0.5\\,m"),
    ("g_wrong_element", "nearest same-class element deleted instead", "Delete: nearest other element deleted instead"),
    ("g_partial", "one of several targets left", "Delete: one of several targets left in place"),
    ("g_extra", "target and nearest same-class element deleted", "Delete: target and an unrelated neighbour deleted"),
]


def _rate(rows, key):
    vals = [bool(r.get(key)) for r in rows]
    return round(sum(vals) / len(vals), 4) if vals else None


def _med(rows, key):
    vals = [float(r[key]) for r in rows if r.get(key) is not None]
    return round(statistics.median(vals), 4) if vals else None


def cmd_summarize() -> None:
    rows = [json.loads(l) for l in open(RESULTS)]
    ids = json.loads(SAMPLE.read_text())["task_ids"]
    by = collections.defaultdict(list)
    for r in rows:
        by[(r.get("pert"), r.get("magnitude"))].append(r)
    summary = {"n_tasks_sampled": len(ids),
               "n_tasks_with_rows": len({r["task_id"] for r in rows}),
               "verdict_rule": "C = 1[min(geometry, semantics, topology) >= t], t = 0.90 (reported) and 0.98",
               "crashes": [r for r in rows if r.get("pert") in ("crash", "task_error")],
               "undo_clean": dict(collections.Counter(str(r.get("undo_clean")) for r in rows
                                                     if r.get("pert") == "undo_check")),
               "perturbations": []}
    for cls, mag, label in LABELS:
        rs = by.get((cls, mag), [])
        applied = [r for r in rs if r.get("applied") and r.get("error") is None and "accept_090" in r]
        entry = {"class": cls, "magnitude": mag, "label": label,
                 "n_rows": len(rs), "n_applied": len(applied),
                 "n_not_applicable": sum(1 for r in rs if r.get("not_applicable")),
                 "n_build_error": sum(1 for r in rs if r.get("build_error")),
                 "n_score_error": sum(1 for r in rs if r.get("applied") and r.get("error")),
                 "accept_090": _rate(applied, "accept_090"), "accept_098": _rate(applied, "accept_098"),
                 "median_geometry": _med(applied, "geometry"), "median_semantics": _med(applied, "semantics"),
                 "median_topology": _med(applied, "topology"), "median_final": _med(applied, "final"),
                 "by_operation": {}}
        for op in ("create", "update", "delete"):
            a = [r for r in applied if r.get("operation") == op]
            if a:
                entry["by_operation"][op] = {"n": len(a), "accept_090": _rate(a, "accept_090"),
                                             "accept_098": _rate(a, "accept_098"),
                                             "median_geometry": _med(a, "geometry"),
                                             "median_semantics": _med(a, "semantics"),
                                             "median_topology": _med(a, "topology")}
        na = collections.Counter(r.get("not_applicable") for r in rs if r.get("not_applicable"))
        entry["not_applicable_reasons"] = dict(na.most_common(6))
        be = collections.Counter((r.get("build_error") or "")[:80] for r in rs if r.get("build_error"))
        entry["build_error_reasons"] = dict(be.most_common(6))
        summary["perturbations"].append(entry)
    # noise floor of the geometry axis: a reference surface against itself, re-sampled
    ss = [r["geometry"] for r in rows if r.get("pert") == "self_score" and r.get("geometry") is not None]
    summary["self_score"] = {"n": len(ss), "median": _med([{"g": x} for x in ss], "g"),
                             "min": min(ss) if ss else None, "max": max(ss) if ss else None,
                             "share_below_0.98": round(sum(x < 0.98 for x in ss) / len(ss), 4) if ss else None,
                             "share_below_0.90": round(sum(x < 0.90 for x in ss) / len(ss), 4) if ss else None,
                             "by_operation": {op: _med([r for r in rows if r.get("pert") == "self_score"
                                                        and r.get("operation") == op], "geometry")
                                              for op in ("create", "update", "delete")}}
    # the semantic mechanism: how many keys the reference element carries
    keys = {}
    for r in rows:
        if r.get("n_semantic_keys") and r["task_id"] not in keys:
            keys[r["task_id"]] = min(r["n_semantic_keys"])
    kv = list(keys.values())
    summary["semantic_keys"] = {
        "n_tasks": len(kv), "median": statistics.median(kv) if kv else None,
        "share_ge_5": round(sum(k >= 5 for k in kv) / len(kv), 4) if kv else None,
        "share_ge_25": round(sum(k >= 25 for k in kv) / len(kv), 4) if kv else None,
        "rule": "one wrong key among n gives semantics 0.5*(1 + (n-1)/n); >= 0.90 iff n >= 5, >= 0.98 iff n >= 25"}
    fa = [r for r in rows if r.get("pert") == "f_attribute" and r.get("applied") and "accept_090" in r]
    bins = [(1, 4), (5, 9), (10, 24), (25, 10 ** 6)]
    summary["attribute_by_keys"] = []
    for lo, hi in bins:
        sel = [r for r in fa if r.get("n_semantic_keys") and lo <= min(r["n_semantic_keys"]) <= hi]
        summary["attribute_by_keys"].append({"keys": f"{lo}-{hi if hi < 10 ** 6 else 'more'}", "n": len(sel),
                                             "accept_090": _rate(sel, "accept_090"),
                                             "accept_098": _rate(sel, "accept_098")})
    (OUT / "mutation_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    # table
    def pct(x):
        return "--" if x is None else f"{100 * x:.0f}"
    def num(x):
        return "--" if x is None else f"{x:.3f}"
    lines = [r"\begin{tabular}{lrrrrr}", r"\toprule",
             r"Change applied to the ground truth & Tasks & \multicolumn{2}{c}{Accepted (\%)} & \multicolumn{2}{c}{Median score} \\",
             r"\cmidrule(lr){3-4}\cmidrule(lr){5-6}",
             r" & & at 0.90 & at 0.98 & Geometry & Semantics \\", r"\midrule"]
    groups = {"control": "Reference", "null_edit": "Reference", "a_shift": "Position",
              "b_width": "Dimension", "b_height": "Dimension", "c_direction": "Position",
              "d_wrong_host": "Relation", "e_relation": "Relation", "f_attribute": "Attribute",
              "x_offtarget": "Outside the target", "g_wrong_element": "Deletion",
              "g_partial": "Deletion", "g_extra": "Deletion"}
    last = None
    for e in summary["perturbations"]:
        g = groups[e["class"]]
        if g != last:
            if last is not None:
                lines.append(r"\addlinespace")
            lines.append(rf"\multicolumn{{6}}{{l}}{{\textit{{{g}}}}} \\")
            last = g
        lines.append(f"{e['label']} & {e['n_applied']} & {pct(e['accept_090'])} & {pct(e['accept_098'])} & "
                     f"{num(e['median_geometry'])} & {num(e['median_semantics'])} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (OUT / "tab_mutation.tex").write_text("\n".join(lines) + "\n")
    print(json.dumps({e["label"][:50]: (e["n_applied"], e["accept_090"], e["accept_098"]) for e in summary["perturbations"]}, indent=0))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("sample", "run", "summarize", "one", "child"))
    ap.add_argument("--partial", default=None)
    ap.add_argument("--skip", default="")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--task", default=None)
    a = ap.parse_args()
    if a.cmd == "sample":
        cmd_sample()
    elif a.cmd == "run":
        cmd_run(a.workers, a.limit)
    elif a.cmd == "child":
        cmd_child(a.task, a.partial, a.skip)
    elif a.cmd == "one":
        _init()
        for r in run_task(a.task):
            print(json.dumps({k: r.get(k) for k in ("pert", "magnitude", "applied", "geometry", "semantics",
                                                    "topology", "accept_090", "accept_098", "not_applicable",
                                                    "build_error", "details", "n_semantic_keys")}, default=str)[:600])
    else:
        cmd_summarize()
