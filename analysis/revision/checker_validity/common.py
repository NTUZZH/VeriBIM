"""Shared readers for the checker-validity analyses.

Inputs (read only): runs_local/bench_v4/tasks.v4d.jsonl (tasks.v4c.jsonl until the 2026-10-16 v4d
recompute; the two differ only in the gold checksums of the 69 tasks repaired on 2026-10-15), the 108-task subset
runs_local/bench_v4/subset_108_hosted.v4c.json, the gold archives
runs_local/bench_v4/models_v4c|models_v4b|models/<task_id>.ifc.gz (checked
against the record's gold_sha256, the same file the evaluation rebuilt into
_gold_cache; for the 69 repaired tasks, gold_v4d/<task_id>.ifc.gz, resolved through
stage_a.goldmodels.resolve_gold by build_gold_v4d.py), the per-task score files and the edited models of each run.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import shutil
import sys
import tarfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]          # project root
BENCH = ROOT / "runs_local/bench_v4"
RES = BENCH / "results"
HERE = Path(__file__).resolve().parent
TMP = HERE / "tmp"
OUT = HERE / "results"
TASKS = BENCH / "tasks.v4d.jsonl"
GOLD_V4D = HERE / "gold_v4d"
SUBSET108 = BENCH / "subset_108_hosted.v4c.json"
GOLD_DIRS = ("models_v4c", "models_v4b", "models")

sys.path.insert(0, str(ROOT / "code"))

# arm label -> (run folder, model folder)
ARMS = {
    "veribim9b_108": ("local108_lib_all", "grpo_v10b_c10"),
    "base9b_libnote_108": ("local108_libnote_all", "Qwen3.5-9B"),
    "sonnet_alone_108": ("hosted108_alone_all", "claude-sonnet-5-5"),
    "sonnet_lib_108": ("hosted108_lib_all", "claude-sonnet-5-5"),
    "sonnet_documented_108": ("hosted108_informed_all", "claude-sonnet-5-5"),
    "gpt_documented_108": ("hosted108_informed_all", "gpt-5.6-luna"),
    "gemini_documented_108": ("hosted108_informed_all", "gemini-3.8-flash"),
    "deepseek_documented_108": ("hosted108_informed_all", "deepseek-v4-pro"),
    "opus_documented_108": ("hosted108_informed_all", "claude-opus-5-5"),
    "veribim9b_2100": ("full_all", "grpo_v10b_c10"),
}

FILLINGS = ("IfcDoor", "IfcWindow")


def load_tasks() -> dict[str, dict]:
    with open(TASKS, encoding="utf-8") as fh:
        return {r["task_id"]: r for r in (json.loads(l) for l in fh if l.strip())}


def subset108() -> list[str]:
    return list(json.load(open(SUBSET108)))


def per_task_rows(arm: str) -> dict[str, dict]:
    run, model = ARMS[arm]
    path = RES / run / f"per_task_{model}.jsonl"
    rows = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                r = json.loads(line)
                rows[r["task_id"]] = r
    return rows


def completed(row: dict) -> bool:
    """The paper's rule: every axis at least 0.9 (manuscript make_tables_rev.py)."""
    s = row.get("score") or {}
    return all((s.get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology"))


def gold_archive(record: dict) -> Path:
    p = GOLD_V4D / f"{record['task_id']}.ifc.gz"
    if p.is_file():
        return p
    for k in ("ground_truth_ifc", "gold_model"):
        if record.get(k):
            p = ROOT / (record[k] + ".gz")
            if p.is_file():
                return p
    for d in GOLD_DIRS:
        p = BENCH / d / f"{record['task_id']}.ifc.gz"
        if p.is_file():
            return p
    raise FileNotFoundError(record["task_id"])


def unpack_gold(record: dict, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{record['task_id']}.gold.ifc"
    digest = hashlib.sha256()
    with gzip.open(gold_archive(record), "rb") as fi, open(out, "wb") as fo:
        for block in iter(lambda: fi.read(1 << 20), b""):
            digest.update(block)
            fo.write(block)
    expected = (record.get("verification") or {}).get("gold_sha256")
    if expected and digest.hexdigest() != expected:
        out.unlink()
        raise ValueError(f"gold sha256 mismatch for {record['task_id']}")
    return out


def source_path(record: dict) -> Path:
    return ROOT / record["input_ifc"]


def edited_dir(arm: str) -> Path:
    run, model = ARMS[arm]
    return RES / run / model


def extract_arm(arm: str, task_ids=None, min_free_gb: float = 36, archive: str = "edited.tar.gz") -> Path:
    """Unpack an arm's edited models into tmp/<arm>/ (or point at edited/).

    archive: the archive inside <run>/<model>/ to read (v4e recompute: edited_v4e.tar.gz,
    which holds the deletion re-runs of 2026-10-16 under edited/<task>/<file>)."""
    base = edited_dir(arm)
    tar = base / archive
    if not tar.is_file():
        if (base / "edited").is_dir():
            return base / "edited"
        raise FileNotFoundError(tar)
    free = shutil.disk_usage("/").free / 1e9
    if free < min_free_gb:
        raise RuntimeError(f"only {free:.1f} GB free; not extracting")
    dest = TMP / arm
    dest.mkdir(parents=True, exist_ok=True)
    wanted = set(task_ids) if task_ids is not None else None
    with tarfile.open(tar, "r|gz") as tf:
        for m in tf:
            if not m.isfile():
                continue
            parts = Path(m.name).parts
            if len(parts) < 3:
                continue
            if wanted is not None and parts[1] not in wanted:
                continue
            target = dest / parts[1] / parts[-1]
            target.parent.mkdir(parents=True, exist_ok=True)
            with tf.extractfile(m) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)
    return dest


def remove_arm(arm: str) -> None:
    dest = TMP / arm
    if dest.exists():
        shutil.rmtree(dest)


def edited_file(arm_root: Path, row: dict, arm: str | None = None,
                on_disk_first: bool = False) -> Path | None:
    """The edited model the row was scored on.

    A row re-read in another run folder (crash re-reads) names that folder in
    edited_ifc; such a file is read where it lies (read only).  With
    on_disk_first (v4d recompute), a row whose edited_ifc exists on disk is read
    there: the 2026-10-15 re-runs sit in <run>/<model>/edited/<task>/ while the
    arm's edited.tar.gz still holds the superseded file under the same name.
    """
    named = Path(row.get("edited_ifc") or "")
    if on_disk_first and str(named) and named.is_file() and named.stat().st_size > 0:
        return named
    if arm is not None and str(named):
        own = edited_dir(arm)
        if not str(named).startswith(str(own) + "/"):
            return named if named.is_file() and named.stat().st_size > 0 else None
    name = named.name
    p = arm_root / row["task_id"] / name
    if name and p.is_file() and p.stat().st_size > 0:
        return p
    d = arm_root / row["task_id"]
    if d.is_dir():
        files = [f for f in d.iterdir() if f.suffix.lower() == ".ifc" and f.stat().st_size > 0]
        if len(files) == 1:
            return files[0]
    return None


# ------------------------------------------------------------ relations

def is_filling(e) -> bool:
    return any(e.is_a(c) for c in FILLINGS)


def guid(e):
    return getattr(e, "GlobalId", None) if e is not None else None


def spatial_parents(e) -> set[str]:
    """GlobalIds of the spatial containers / aggregate parents of an element."""
    out = set()
    for rel in getattr(e, "ContainedInStructure", ()) or ():
        g = guid(rel.RelatingStructure)
        if g:
            out.add(g)
    for rel in getattr(e, "Decomposes", ()) or ():
        if rel.is_a("IfcRelAggregates"):
            g = guid(rel.RelatingObject)
            if g:
                out.add(g)
    return out


def fill_hosts(e) -> list[tuple[str | None, list[str]]]:
    """For a filling: [(opening GlobalId, [host GlobalIds the opening voids])]."""
    out = []
    for rel in getattr(e, "FillsVoids", ()) or ():
        op = rel.RelatingOpeningElement
        hosts = []
        if op is not None:
            for v in getattr(op, "VoidsElements", ()) or ():
                h = guid(v.RelatingBuildingElement)
                if h:
                    hosts.append(h)
        out.append((guid(op), hosts))
    return out


_OPT_CACHE: dict = {}


def _required_rel_ends(model, cls: str) -> list[str]:
    key = (model.schema, cls)
    if key in _OPT_CACHE:
        return _OPT_CACHE[key]
    import ifcopenshell.ifcopenshell_wrapper as w
    decl = w.schema_by_name(model.schema).declaration_by_name(cls)
    names = []
    for a in decl.all_attributes():
        n = a.name()
        if (n.startswith("Relating") or n.startswith("Related")) and not a.optional():
            names.append(n)
    _OPT_CACHE[key] = names
    return names


def dangling_relations(model) -> dict[str, str]:
    """Relationship GlobalId -> 'Class.attribute' for every required end that is empty."""
    out = {}
    for rel in model.by_type("IfcRelationship"):
        for n in _required_rel_ends(model, rel.is_a()):
            try:
                v = getattr(rel, n)
            except Exception:
                v = None
            if v is None or (isinstance(v, (tuple, list)) and len(v) == 0):
                out[rel.GlobalId or f"#{rel.id()}"] = f"{rel.is_a()}.{n}"
                break
    return out


def orphan_openings(model) -> set[str]:
    out = set()
    for op in model.by_type("IfcOpeningElement"):
        if not (getattr(op, "VoidsElements", ()) or ()):
            out.add(op.GlobalId)
    return out


def unit_scale(model) -> float:
    import ifcopenshell.util.unit as u
    return float(u.calculate_unit_scale(model))


def placement_world_m(e, scale: float):
    import ifcopenshell.util.placement as pu
    p = getattr(e, "ObjectPlacement", None)
    if p is None:
        return None
    try:
        M = np.asarray(pu.get_local_placement(p), dtype=float)
    except Exception:
        return None
    return M[:3, 3] * scale


# ------------------------------------------------------------ geometry

def plan_rect(verts: np.ndarray) -> tuple[float, float]:
    """Sides (long, short) of the minimum-area rectangle around the plan view."""
    from scipy.spatial import ConvexHull
    xy = np.unique(np.round(verts[:, :2], 6), axis=0)
    if len(xy) < 3:
        ext = xy.max(axis=0) - xy.min(axis=0) if len(xy) else np.zeros(2)
        return float(max(ext)), float(min(ext))
    try:
        hull = xy[ConvexHull(xy).vertices]
    except Exception:
        ext = xy.max(axis=0) - xy.min(axis=0)
        return float(max(ext)), float(min(ext))
    best = None
    for i in range(len(hull)):
        d = hull[(i + 1) % len(hull)] - hull[i]
        n = math.hypot(*d)
        if n < 1e-12:
            continue
        u = d / n
        v = np.array([-u[1], u[0]])
        a = hull @ u
        b = hull @ v
        s1, s2 = a.max() - a.min(), b.max() - b.min()
        area = s1 * s2
        if best is None or area < best[0]:
            best = (area, max(s1, s2), min(s1, s2))
    return float(best[1]), float(best[2])


def mesh_stats(mesh) -> dict | None:
    if mesh is None:
        return None
    v = mesh.verts
    lo, hi = v.min(axis=0), v.max(axis=0)
    L, W = plan_rect(v)
    return {"centre": ((lo + hi) / 2).tolist(), "L": L, "W": W, "H": float(hi[2] - lo[2]),
            "aabb_lo": lo.tolist(), "aabb_hi": hi.tolist()}


DIM_NAMES = {
    "IfcWall": ("length", "thickness", "height"),
    "IfcDoor": ("width", "depth", "height"),
    "IfcWindow": ("width", "depth", "height"),
    "IfcSlab": ("length", "width", "thickness"),
    "IfcColumn": ("section_long", "section_short", "height"),
    "IfcSpace": ("length", "width", "height"),
}


def dim_names(cls: str):
    for k, v in DIM_NAMES.items():
        if cls.startswith(k):
            return v
    return ("plan_long", "plan_short", "vertical")


def pct(values, q):
    return float(np.percentile(values, q)) if len(values) else None
