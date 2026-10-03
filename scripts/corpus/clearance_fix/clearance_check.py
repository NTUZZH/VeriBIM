"""Clearance rule for created or moved doors and windows.

RULE.  A door or window that an edit creates, copies or moves keeps a clearance
zone free of other building fabric.

  Frame.  The host wall's own placement: `a` runs along the wall (the local
  horizontal axis in which the host body is longer), `n` is the horizontal
  normal, `z` is up.  All lengths in metres (ifcopenshell geometry, world
  coordinates, openings subtracted).

  Filling band.  From the body of the opening the filling fills (the hole cut
  in the host; the filling's own body when it has no opening): [a0, a1] along
  the wall and [z0, z1] in height.  The band is shrunk by TOL_A = 0.02 m at both jambs, by
  TOL_Z_BOTTOM = 0.10 m at the bottom (floor finish slabs, thresholds) and by
  TOL_Z_TOP = 0.02 m at the head, so fabric that only touches the frame line is
  not an obstruction.

  Host faces.  [h0, h1] = the host body's extent along `n`, read from the host
  triangles that lie inside [a0, a1] (the full host extent when none do).

  Zone Z(c) = band x [h0 - c, h1 + c]: the filling's footprint through the wall,
  extended by the clearance c beyond both faces of the host.

  Obstructions.  Every IfcWall (and subtypes), IfcCurtainWall, IfcColumn and
  IfcSlab element in the model after the edit, except: the host itself; the
  filling and its own opening; the host's own layers, which are (i) parts
  aggregated into the host and the host's aggregate parent and its other parts,
  and (ii) a wall modelled separately alongside the host: within 10 degrees of
  parallel to it, its part inside the band no farther than LAYER_GAP = 0.05 m
  from a host face (or inside the host thickness), and running across the whole
  band along the wall (a leaf of a double wall, a lining).  Layer walls are
  reported in the field 'layer' but do not count.  Spaces, openings, doors, windows, beams, members, coverings,
  proxies and furniture are not obstructions.

  Distance.  d(F) = min over obstructions of the clear distance, along n, from
  the host faces to the part of the obstruction that lies inside the band
  (0 when that part reaches into the host thickness, as at a T-junction where a
  partition butts the host face).  d = inf when nothing lies in the band within
  CMAX = 1.5 m of either face.

  Flag.  F is flagged when d(F) < c.  C_DEFAULT is the calibrated value (see
  REPORT.txt); it is a module constant and a command-line option.

Usage.
  python clearance_check.py task --tasks FILE.jsonl --id TASK_ID [--c 0.6]
  python clearance_check.py task --record RECORD.json [--gold GOLD.ifc] [--c 0.6]
  python clearance_check.py ifc --ifc MODEL.ifc --fillings GUID[,GUID...] [--c 0.6]
The task mode rebuilds the gold in memory by running the record's gold script
on its source model (nothing is written) and checks every door or window the
edit created, or moved by more than 1 mm.  The ifc mode checks the named
fillings of a model as it is.  Both print one JSON object: {"flag": bool,
"fillings": [{"guid", "class", "host", "d", "offending": {...}}...]}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from typing import Any, Optional

import numpy as np

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.placement
import ifcopenshell.util.unit

ROOT = './'
C_DEFAULT = 0.60          # calibrated clearance, metres (REPORT.txt)
CMAX = 1.5                # distances are measured up to this far from the faces
TOL_A = 0.02
TOL_Z_BOTTOM = 0.10
TOL_Z_TOP = 0.02
MOVE_EPS = 0.001
LAYER_GAP = 0.05
LAYER_ANGLE = 10.0
OBSTRUCTION_CLASSES = ('IfcWall', 'IfcCurtainWall', 'IfcColumn', 'IfcSlab')
FILLING_CLASSES = ('IfcDoor', 'IfcWindow')
# Source-model AABB caches written by the generator (modifc_gen.geomindex), read only.
# The cache key holds the file's path, size and modification time, so a hit is
# the index of exactly this file.
INDEX_DIRS = [ROOT + 'runs_local/' + d for d in (
    'corpus_v10/gen/geom_index', 'corpus_v10/gen/geom_index_bench', 'corpus_v10/gen/resource/geom_index',
    'wave_v2/geom_index', 'wave_v2/geom_index_e2', 'gen_v07/geom_index', 'gen_v06/geom_index',
    'gen_v05/geom_index', 'bench/geom_index')] + [os.path.expanduser('~/.cache/modifc_gen/geom_index')]
OWN_CACHE = ROOT + 'runs_local/corpus_v10/clearance_fix/geom_cache'

_SETTINGS = None


def settings():
    global _SETTINGS
    if _SETTINGS is None:
        s = ifcopenshell.geom.settings()
        s.set('use-world-coords', True)
        _SETTINGS = s
    return _SETTINGS


def is_obstruction_class(e) -> bool:
    return any(e.is_a(c) for c in OBSTRUCTION_CLASSES)


def mesh(e) -> Optional[np.ndarray]:
    """World triangles (k, 3, 3) of one product, or None."""
    try:
        sh = ifcopenshell.geom.create_shape(settings(), e)
    except Exception:
        return None
    v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
    f = np.asarray(sh.geometry.faces, dtype=np.int64).reshape(-1, 3)
    if len(v) == 0 or len(f) == 0:
        return None
    return v[f]


# ------------------------------------------------------------------ index
def cache_key(path: str) -> str:
    st = os.stat(path)
    raw = f"{os.path.abspath(path)}|{st.st_size}|{int(st.st_mtime)}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def source_index(path: str, model=None) -> dict:
    """Obstruction-class AABBs of a source model: the generator's cache when it
    holds this exact file, else an own cache built once by meshing."""
    key = cache_key(path)
    for d in INDEX_DIRS + [OWN_CACHE]:
        p = os.path.join(d, key + '.npz')
        if os.path.exists(p):
            z = np.load(p, allow_pickle=False)
            cls = z['cls']
            keep = np.array([str(c).startswith(OBSTRUCTION_CLASSES) for c in cls], dtype=bool)
            return {'guid': z['guid'][keep], 'cls': cls[keep], 'lo': z['lo'][keep], 'hi': z['hi'][keep],
                    'from': p}
    if model is None:
        model = ifcopenshell.open(path)
    guid, cls, lo, hi = [], [], [], []
    for c in OBSTRUCTION_CLASSES:
        for e in model.by_type(c):
            t = mesh(e)
            if t is None:
                continue
            v = t.reshape(-1, 3)
            guid.append(e.GlobalId); cls.append(e.is_a()); lo.append(v.min(0)); hi.append(v.max(0))
    os.makedirs(OWN_CACHE, exist_ok=True)
    out = {'guid': np.array(guid, dtype='U22'), 'cls': np.array(cls, dtype='U48'),
           'lo': np.array(lo, dtype=float).reshape(-1, 3), 'hi': np.array(hi, dtype=float).reshape(-1, 3)}
    np.savez_compressed(os.path.join(OWN_CACHE, key + '.npz'), **out)
    out['from'] = 'built'
    return out


# ------------------------------------------------------------------ geometry
def host_frame(model, host, host_tris: np.ndarray):
    """(origin, A, N, Z) unit axes of the host wall frame in world coordinates."""
    scale = ifcopenshell.util.unit.calculate_unit_scale(model)
    M = np.array(ifcopenshell.util.placement.get_local_placement(host.ObjectPlacement), dtype=float)
    R = M[:3, :3] / np.linalg.norm(M[:3, :3], axis=0)
    o = M[:3, 3] * scale
    x = R[:, 0].copy(); x[2] = 0.0
    if np.linalg.norm(x) < 1e-6:
        x = np.array([1.0, 0.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(np.array([0.0, 0.0, 1.0]), x)
    v = host_tris.reshape(-1, 3) - o
    ex, ey = np.ptp(v @ x), np.ptp(v @ y)
    A, N = (x, y) if ex >= ey else (y, -x)
    return o, A, N, np.array([0.0, 0.0, 1.0])


def to_local(tris: np.ndarray, frame) -> np.ndarray:
    o, A, N, Z = frame
    v = tris - o
    return np.stack([v @ A, v @ N, v @ Z], axis=-1)


def _clip(poly, axis, value, keep_greater):
    out = []
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        pin = p[axis] >= value if keep_greater else p[axis] <= value
        qin = q[axis] >= value if keep_greater else q[axis] <= value
        if pin:
            out.append(p)
        if pin != qin:
            t = (value - p[axis]) / (q[axis] - p[axis])
            out.append(p + t * (q - p))
    return out


def band_n_ranges(tri_local: np.ndarray, a_lo, a_hi, z_lo=None, z_hi=None, with_a=False) -> list:
    """n-intervals of the triangles clipped to the band a in [a_lo, a_hi]
    (and z in [z_lo, z_hi] when given); with_a adds each part's a-interval."""
    t = tri_local
    m = (t[:, :, 0].max(1) > a_lo) & (t[:, :, 0].min(1) < a_hi)
    if z_lo is not None:
        m &= (t[:, :, 2].max(1) > z_lo) & (t[:, :, 2].min(1) < z_hi)
    out = []
    for tri in t[m]:
        poly = [tri[0], tri[1], tri[2]]
        for axis, val, g in ((0, a_lo, True), (0, a_hi, False)) + \
                (((2, z_lo, True), (2, z_hi, False)) if z_lo is not None else ()):
            poly = _clip(poly, axis, val, g)
            if len(poly) < 3:
                break
        if len(poly) >= 3:
            ns = [p[1] for p in poly]
            if with_a:
                as_ = [p[0] for p in poly]
                out.append((min(ns), max(ns), min(as_), max(as_)))
            else:
                out.append((min(ns), max(ns)))
    return out


def parallel_to_host(tris: np.ndarray, frame, angle: float = 10.0) -> bool:
    """Whether an obstruction's plan footprint runs parallel to the host."""
    v = to_local(tris, frame).reshape(-1, 3)[:, :2]
    v = v - v.mean(0)
    if len(v) < 3:
        return False
    w, U = np.linalg.eigh(v.T @ v)
    main = U[:, -1]
    if w[-1] < 1.5 * max(w[0], 1e-12):     # squarish (column): no direction
        return False
    return abs(main[0]) >= math.cos(math.radians(angle))


def own_layers(host) -> set:
    """GlobalIds of the host's aggregate parent and every part in that aggregate."""
    out = set()
    for rel in getattr(host, 'IsDecomposedBy', ()) or ():
        out.update(p.GlobalId for p in rel.RelatedObjects)
    for rel in getattr(host, 'Decomposes', ()) or ():
        parent = rel.RelatingObject
        out.add(parent.GlobalId)
        for r2 in getattr(parent, 'IsDecomposedBy', ()) or ():
            out.update(p.GlobalId for p in r2.RelatedObjects)
    return out


def host_of(filling):
    for rel in getattr(filling, 'FillsVoids', ()) or ():
        op = rel.RelatingOpeningElement
        for r2 in getattr(op, 'VoidsElements', ()) or ():
            return r2.RelatingBuildingElement, op
    return None, None


def check_filling(model, filling, index: Optional[dict], extra_candidates=(),
                  c: float = C_DEFAULT, mesh_cache: Optional[dict] = None) -> dict:
    """Clearance distance of one door or window in `model` (the model after the edit).

    `index` gives source AABBs used to pick candidate obstructions (None: every
    obstruction-class element of the model is a candidate); `extra_candidates`
    are GlobalIds always tested (elements the edit created or touched)."""
    mesh_cache = {} if mesh_cache is None else mesh_cache
    res = {'guid': filling.GlobalId, 'class': filling.is_a(), 'name': filling.Name}
    host, opening = host_of(filling)
    if host is None:
        res.update(status='no_host', d=None, flag=False)
        return res
    res['host'] = host.GlobalId
    ft = mesh(filling)
    ht = mesh(host)
    if ft is None or ht is None:
        res.update(status='no_geometry', d=None, flag=False)
        return res
    frame = host_frame(model, host, ht)
    # The band is the hole cut in the host (the opening's body); a leaf's own
    # body can carry casings and trims that lap past the hole onto the wall face.
    ot = mesh(opening) if opening is not None else None
    res['band_from'] = 'opening' if ot is not None else 'filling'
    fl = to_local(ot if ot is not None else ft, frame).reshape(-1, 3)
    a0, a1 = fl[:, 0].min(), fl[:, 0].max()
    z0, z1 = fl[:, 2].min(), fl[:, 2].max()
    hl = to_local(ht, frame)
    hr = band_n_ranges(hl, a0, a1)
    if hr:
        h0, h1 = min(r[0] for r in hr), max(r[1] for r in hr)
    else:
        h0, h1 = hl[:, :, 1].min(), hl[:, :, 1].max()
    A0, A1, Z0, Z1 = a0 + TOL_A, a1 - TOL_A, z0 + TOL_Z_BOTTOM, z1 - TOL_Z_TOP
    res.update(band={'a': [round(a0, 3), round(a1, 3)], 'z': [round(z0, 3), round(z1, 3)],
                     'host_n': [round(h0, 3), round(h1, 3)]})
    if A1 <= A0 or Z1 <= Z0:
        res.update(status='degenerate_band', d=None, flag=False)
        return res
    excluded = {host.GlobalId, filling.GlobalId} | own_layers(host)
    if opening is not None:
        excluded.add(opening.GlobalId)
    # candidate obstructions: world AABB of the zone at CMAX
    o, A, N, Z = frame
    corners = np.array([o + a * A + n * N + z * Z for a in (A0, A1) for n in (h0 - CMAX, h1 + CMAX)
                        for z in (Z0, Z1)])
    wlo, whi = corners.min(0) - 0.01, corners.max(0) + 0.01
    cands = []
    if index is not None:
        m = np.all(index['lo'] <= whi, axis=1) & np.all(index['hi'] >= wlo, axis=1)
        cands = [str(g) for g in index['guid'][m]]
    else:
        cands = [e.GlobalId for cl in OBSTRUCTION_CLASSES for e in model.by_type(cl)]
    cands = list(dict.fromkeys(cands + list(extra_candidates)))
    best = None
    layer = None
    for g in cands:
        if g in excluded:
            continue
        try:
            e = model.by_guid(g)
        except Exception:
            continue                      # removed by the edit
        if not is_obstruction_class(e):
            continue
        if g in mesh_cache:
            tris = mesh_cache[g]
        else:
            tris = mesh(e)
            mesh_cache[g] = tris
        if tris is None:
            continue
        rng = band_n_ranges(to_local(tris, frame), A0, A1, Z0, Z1, with_a=True)
        if not rng:
            continue
        gaps = []
        for lo_n, hi_n, _a, _b in rng:
            if hi_n >= h0 and lo_n <= h1:
                gaps.append((0.0, 'through' if (lo_n < h0 and hi_n > h1) else 'in_host'))
            elif hi_n < h0:
                gaps.append((h0 - hi_n, 'n-'))
            else:
                gaps.append((lo_n - h1, 'n+'))
        gap, side = min(gaps)
        if gap > CMAX:
            continue
        # a wall alongside the host, touching it and running across the whole band,
        # is one of the host's own layers
        if e.is_a('IfcWall') and gap <= LAYER_GAP and \
                min(r[2] for r in rng) <= A0 + 0.01 and max(r[3] for r in rng) >= A1 - 0.01 and \
                parallel_to_host(tris, frame, LAYER_ANGLE):
            if layer is None or gap < layer['gap']:
                layer = {'guid': e.GlobalId, 'class': e.is_a(), 'name': e.Name, 'gap': round(float(gap), 4),
                         'side': side}
            continue
        if best is None or gap < best[0]:
            best = (gap, side, e, tris)
    res['layer'] = layer
    if best is None:
        res.update(status='ok', d=None, flag=False, offending=None)
        return res
    gap, side, e, tris = best
    res.update(status='ok', d=round(float(gap), 4), flag=bool(gap < c),
               offending={'guid': e.GlobalId, 'class': e.is_a(), 'name': e.Name, 'side': side,
                          'parallel_to_host': bool(parallel_to_host(tris, frame))})
    return res


# ------------------------------------------------------------------ task mode
MOVE_KINDS = ('translate', 'copy_element', 'array_elements', 'mirror', 'rotate', 'rehost_filling',
              'move_space_with_bounding_walls', 'move_wall_with_fillings')
CREATE_KINDS = ('create_filling', 'replace_filling', 'create_wall_with_door')


def in_scope(rec: dict) -> bool:
    k = rec.get('edit_kind')
    if k in CREATE_KINDS or k == 'rehost_filling':
        return True
    if k in ('translate', 'copy_element', 'array_elements', 'mirror', 'rotate') and \
            rec.get('family') in ('door', 'window'):
        return True
    if k in ('move_space_with_bounding_walls', 'move_wall_with_fillings'):
        return True
    return 'create' in str(k) and 'fill' in str(k)


def _box(tris):
    v = tris.reshape(-1, 3)
    return v.min(0), v.max(0)


def check_task(rec: dict, c: float = C_DEFAULT, index: Optional[dict] = None,
               gold_path: Optional[str] = None) -> dict:
    """Check every door or window the task's edit created or moved.

    The gold is rebuilt in memory by running the record's gold script on its
    source model; with `gold_path` the gold is read from that file instead (the
    source is then opened too, to tell which fillings moved)."""
    src = ROOT + rec['input_ifc']
    if index is None:
        index = source_index(src)
    eg = rec.get('edit_guids') or {}
    created = list(eg.get('created') or ())
    maybe_moved = list(dict.fromkeys(list(eg.get('target') or ()) + list(eg.get('touched') or ())))
    gold = None
    if gold_path is not None:
        # read the gold first; the source is opened only when a door or window of the
        # target/touched list exists, to tell whether it moved (keeps one model in memory
        # for the create kinds)
        gold = ifcopenshell.open(gold_path)
        need_source = False
        for g in maybe_moved:
            try:
                e = gold.by_guid(g)
            except Exception:
                continue
            if e.is_a('IfcDoor') or e.is_a('IfcWindow'):
                need_source = True
        model = ifcopenshell.open(src) if need_source else None
    else:
        model = ifcopenshell.open(src)
    before, d_before = {}, {}
    for g in (maybe_moved if model is not None else ()):
        try:
            e = model.by_guid(g)
        except Exception:
            continue
        if e.is_a('IfcDoor') or e.is_a('IfcWindow'):
            t = mesh(e)
            if t is not None:
                before[g] = _box(t)
                # the same measure at the filling's place in the source model
                d_before[g] = check_filling(model, e, index, (), c).get('d')
    if gold_path is not None:
        del model
        model = gold
    else:
        ns = {'__name__': 'clearance_gold'}
        exec(compile(rec['gold_script'], '<gold_script>', 'exec'), ns)
        ns['apply_edit'](model)
    todo = []
    for g in created:
        try:
            e = model.by_guid(g)
        except Exception:
            continue
        if e.is_a('IfcDoor') or e.is_a('IfcWindow'):
            todo.append((e, 'created'))
    for g, (lo, hi) in before.items():
        try:
            e = model.by_guid(g)
        except Exception:
            continue
        t = mesh(e)
        if t is None:
            continue
        lo2, hi2 = _box(t)
        if max(np.abs(lo2 - lo).max(), np.abs(hi2 - hi).max()) > MOVE_EPS:
            todo.append((e, 'moved'))
    extra = []
    for g in created + maybe_moved + list(eg.get('removed') or ()):
        try:
            e = model.by_guid(g)
        except Exception:
            continue
        if is_obstruction_class(e):
            extra.append(g)
    mc = {}
    out = []
    for e, how in todo:
        r = check_filling(model, e, index, extra, c, mc)
        r['how'] = how
        if how == 'moved':
            r['d_before_edit'] = d_before.get(e.GlobalId)
        out.append(r)
    del model
    ds = [r['d'] for r in out if r.get('d') is not None]
    return {'task_id': rec['task_id'], 'flag': any(r['flag'] for r in out),
            'min_d': (min(ds) if ds else None), 'fillings': out, 'n_fillings': len(out)}


def check_ifc(path: str, guids, c: float = C_DEFAULT, source: Optional[str] = None) -> dict:
    model = ifcopenshell.open(path)
    index = source_index(source) if source else None
    out = [check_filling(model, model.by_guid(g), index, (), c) for g in guids]
    return {'ifc': path, 'flag': any(r['flag'] for r in out), 'fillings': out}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = ap.add_subparsers(dest='mode', required=True)
    t = sub.add_parser('task')
    t.add_argument('--tasks')
    t.add_argument('--id')
    t.add_argument('--record')
    t.add_argument('--gold', help='read the gold from this file instead of rebuilding it')
    t.add_argument('--c', type=float, default=C_DEFAULT)
    i = sub.add_parser('ifc')
    i.add_argument('--ifc', required=True)
    i.add_argument('--fillings', required=True)
    i.add_argument('--source', help='source model whose AABB cache may pick candidates')
    i.add_argument('--c', type=float, default=C_DEFAULT)
    a = ap.parse_args(argv)
    if a.mode == 'task':
        if a.record:
            rec = json.load(open(a.record))
        else:
            rec = next(r for r in map(json.loads, open(a.tasks)) if r['task_id'] == a.id)
        res = check_task(rec, a.c, gold_path=a.gold)
    else:
        res = check_ifc(a.ifc, a.fillings.split(','), a.c, a.source)
    print(json.dumps(res, indent=1, default=str))
    return 1 if res['flag'] else 0


if __name__ == '__main__':
    sys.exit(main())
