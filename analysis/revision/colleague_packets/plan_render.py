"""plan_render: storey plan views and host-wall elevations of IFC models for the human-study packets.

Adapted from writing/figures/fig11_showcase/render_ifc.py (storey lookup, ifcopenshell.geom
tessellation in world coordinates); the drawing is 2D (plan footprints and wall elevations)
in matplotlib, with shapely for footprint unions.

Plan conventions: walls grey fill (the part of the wall below a 1.2 m cut above its base, so
door openings show as gaps), slabs light grey outline, columns dark grey, doors and windows thin
white marks with a dark outline, spaces dashed outlines with their names; changed elements in
red (solid: present in this view; dashed: removed by the edit). North arrow (+Y) and a scale
bar. Elevation: the host wall seen face-on, its openings and fillings, sill and head heights
of the marked filling measured from the wall base.
"""
from __future__ import annotations

import gzip
import os

import numpy as np
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as ue
import ifcopenshell.util.placement as up
import shapely
from shapely.geometry import Polygon, MultiPolygon, box as sbox

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import PathPatch, Rectangle, FancyArrow  # noqa: E402
from matplotlib.path import Path  # noqa: E402

plt.rcParams.update({
    'font.family': ['Liberation Serif', 'Noto Serif CJK SC'],
    'font.size': 6.5,
    'axes.linewidth': 0.4,
    'savefig.facecolor': 'white',
    'figure.facecolor': 'white',
})

RED = '#C0392B'
WALL_FILL = '#BFC3C8'
WALL_EDGE = '#6B7178'
COL_FILL = '#5F666E'
SLAB_EDGE = '#C9CDD2'
SPACE_EDGE = '#8A9098'
FILL_EDGE = '#3A3F45'
GHOST_FILL = '#F4B6AE'
CUT_HEIGHT = 1.2

WALL_CLASSES = ('IfcWall', 'IfcCurtainWall')
DRAW_CLASSES = ('IfcWall', 'IfcCurtainWall', 'IfcSlab', 'IfcColumn', 'IfcDoor', 'IfcWindow', 'IfcSpace',
                'IfcStair', 'IfcStairFlight')


# --------------------------------------------------------------------------- models
def open_model(path):
    if path.endswith('.gz'):
        with gzip.open(path, 'rb') as f:
            return ifcopenshell.file.from_string(f.read().decode('utf-8', errors='replace'))
    return ifcopenshell.open(path)


def storey_of(el):
    """The storey an element belongs to (container, aggregate parent, or a filling's host's storey)."""
    e = el
    for _ in range(8):
        if e is None:
            return None
        if e.is_a('IfcBuildingStorey'):
            return e
        c = ue.get_container(e)
        if c is not None:
            if c.is_a('IfcBuildingStorey'):
                return c
            e = c
            continue
        fills = getattr(e, 'FillsVoids', None)
        if fills:
            e = fills[0].RelatingOpeningElement.VoidsElements[0].RelatingBuildingElement
        else:
            e = ue.get_aggregate(e)
    return None


def host_of(filling):
    fv = getattr(filling, 'FillsVoids', None)
    if not fv:
        return None
    op = fv[0].RelatingOpeningElement
    if not op.VoidsElements:
        return None
    return op.VoidsElements[0].RelatingBuildingElement


def by_guid(model, g):
    try:
        return model.by_guid(g)
    except RuntimeError:
        return None


def storey_elements(model, storey, extra=()):
    """Drawable elements whose storey is `storey`, plus `extra` GlobalIds."""
    out = {}
    for cls in DRAW_CLASSES:
        try:
            els = model.by_type(cls)
        except RuntimeError:
            continue
        for e in els:
            if e.GlobalId in out:
                continue
            s = storey_of(e)
            if s is not None and s.GlobalId == storey.GlobalId:
                out[e.GlobalId] = e
    for g in extra:
        e = by_guid(model, g)
        if e is not None and not e.is_a('IfcOpeningElement') and e.is_a('IfcProduct'):
            out[g] = e
    return out


def tessellate(model, elements):
    """{GlobalId: dict(cls, name, verts, faces)} in world metres. An element with no body of its own
    (a layered wall exported as an axis plus building element parts) takes the merged geometry of its
    parts."""
    res = _tessellate(model, elements)
    missing = [e for e in elements if e is not None and e.GlobalId not in res]
    parent = {}
    for e in missing:
        for p in ue.get_decomposition(e) or []:
            if getattr(p, 'Representation', None) is not None and not p.is_a('IfcOpeningElement'):
                parent[p.id()] = e
    if parent:
        parts = _tessellate(model, [model.by_id(i) for i in parent])
        merged = {}
        for pg, m in parts.items():
            e = parent[model.by_guid(pg).id()]
            mm = merged.setdefault(e.GlobalId, dict(cls=e.is_a(), name=e.Name or '', verts=[], faces=[], n=0))
            mm['faces'].append(m['faces'] + mm['n'])
            mm['verts'].append(m['verts'])
            mm['n'] += len(m['verts'])
        for g, mm in merged.items():
            res[g] = dict(cls=mm['cls'], name=mm['name'], verts=np.vstack(mm['verts']), faces=np.vstack(mm['faces']))
    return res


def _tessellate(model, elements):
    els = [e for e in elements if e is not None and getattr(e, 'Representation', None) is not None]
    res = {}
    if not els:
        return res
    s = ifcopenshell.geom.settings()
    s.set('use-world-coords', True)
    it = ifcopenshell.geom.iterator(s, model, 1, include=els)
    if it.initialize():
        while True:
            sh = it.get()
            e = model.by_id(sh.id)
            g = sh.geometry
            v = np.asarray(g.verts, float).reshape(-1, 3)
            f = np.asarray(g.faces, int).reshape(-1, 3)
            if len(f):
                res[e.GlobalId] = dict(cls=e.is_a(), name=e.Name or '', verts=v, faces=f)
            if not it.next():
                break
    return res


# --------------------------------------------------------------------------- footprints
def _tri_union(P):
    """Union of 2D triangles P (n,3,2); degenerate ones are dropped."""
    if not len(P):
        return None
    a = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1])
                     - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
    P = P[a > 1e-7]
    if not len(P):
        return None
    polys = shapely.polygons(np.concatenate([P, P[:, :1]], axis=1))
    u = shapely.union_all(polys, grid_size=1e-4)
    if u.is_empty:
        return None
    return u


def plan_footprint(m):
    V, F = m['verts'], m['faces']
    T = V[F]
    if m['cls'].startswith(WALL_CLASSES):
        zmin = V[:, 2].min()
        keep = T[:, :, 2].max(1) <= zmin + CUT_HEIGHT + 1e-6
        if keep.sum() >= 2:
            fp = _tri_union(T[keep][:, :, :2])
            if fp is not None and fp.area > 1e-4:
                return fp
    return _tri_union(T[:, :, :2])


def footprints(meshes):
    out = {}
    for g, m in meshes.items():
        try:
            fp = plan_footprint(m)
        except Exception:
            fp = None
        if fp is not None:
            out[g] = fp
    return out


# --------------------------------------------------------------------------- drawing helpers
def _geom_path(geom):
    polys = [geom] if isinstance(geom, Polygon) else [p for p in getattr(geom, 'geoms', []) if isinstance(p, Polygon)]
    verts, codes = [], []
    for p in polys:
        for ring in [p.exterior] + list(p.interiors):
            c = np.asarray(ring.coords)
            if len(c) < 3:
                continue
            verts.append(c)
            codes += [Path.MOVETO] + [Path.LINETO] * (len(c) - 2) + [Path.CLOSEPOLY]
    if not verts:
        return None
    return Path(np.concatenate(verts), codes)


def draw_geom(ax, geom, fc='none', ec='k', lw=0.4, ls='-', z=1, alpha=1.0):
    if geom is None or geom.is_empty:
        return
    if not isinstance(geom, (Polygon, MultiPolygon)):
        geom = shapely.GeometryCollection([g for g in getattr(geom, 'geoms', []) if isinstance(g, (Polygon, MultiPolygon))])
        geom = shapely.union_all(list(geom.geoms)) if not geom.is_empty else geom
        if geom.is_empty:
            return
    p = _geom_path(geom)
    if p is None:
        return
    ax.add_patch(PathPatch(p, facecolor=fc, edgecolor=ec, lw=lw, ls=ls, zorder=z, alpha=alpha,
                           joinstyle='round'))


def _hole_kept(h):
    if h.area < 1.0:
        return False
    c = np.asarray(h.minimum_rotated_rectangle.exterior.coords)
    sides = np.hypot(*np.diff(c, axis=0).T)
    return sides.min() >= 0.4


def red_outline(ax, geom, dashed=False):
    if geom is None or geom.is_empty:
        return
    # small holes (wall pockets, shafts under 1 m2) are not outlined; a small element (door, column) is
    # outlined slightly outside its edge so the red line stays visible
    polys = [geom] if isinstance(geom, Polygon) else [p for p in getattr(geom, 'geoms', []) if isinstance(p, Polygon)]
    polys = [Polygon(p.exterior, [r for r in p.interiors if _hole_kept(Polygon(r))]) for p in polys]
    g = shapely.union_all(polys) if polys else geom
    if not dashed and g.area < 4.0:
        g = g.buffer(0.05, join_style=2)
    draw_geom(ax, g, fc='none', ec=RED, lw=1.5 if not dashed else 1.3, ls=(0, (3, 1.6)) if dashed else '-', z=20)


def scale_bar(ax, x0, y0, width):
    big, small = (5, 1) if width <= 32 else (10, 2) if width <= 65 else (25, 5) if width <= 160 else (50, 10)
    h = width * 0.012
    ax.add_patch(Rectangle((x0 - 0.015 * width, y0 - 0.015 * width), big + 0.05 * width, h + 0.075 * width,
                           facecolor='white', edgecolor='none', alpha=0.9, zorder=29))
    ax.add_patch(Rectangle((x0, y0), small, h, facecolor='k', edgecolor='k', lw=0.4, zorder=30))
    ax.add_patch(Rectangle((x0 + small, y0), big - small, h, facecolor='white', edgecolor='k', lw=0.4, zorder=30))
    for v in (0, small, big):
        ax.text(x0 + v, y0 + 2.2 * h, f'{v} m' if v == big else f'{v}', ha='center', va='bottom', fontsize=6,
                zorder=30, bbox=dict(facecolor='white', edgecolor='none', pad=0.3, alpha=0.85))


def place_labels(ax, fig, labels, fps, red_dashed, red_solid, window):
    """Labels next to their elements: a small dot on the element, a short thin leader, and a boxed
    name placed where it overlaps no other label and no red outline."""
    from shapely.ops import nearest_points
    from shapely.geometry import Point
    x0, y0, x1, y1 = window
    W = x1 - x0
    inner = sbox(x0 + 0.03 * W, y0 + 0.03 * W, x1 - 0.03 * W, y1 - 0.03 * W)
    keep_free = [sbox(x1 - 0.1 * W, y1 - 0.16 * W, x1, y1),            # north arrow
                 sbox(x0, y0, x0 + 0.42 * W, y0 + 0.09 * W)]             # scale bar
    reds = [fps[g] for g in red_solid if g in fps] + list((red_dashed or {}).values())
    red_u = shapely.union_all([r.buffer(0.02 * W) for r in reds]) if reds else None
    ren = fig.canvas.get_renderer()
    inv = ax.transData.inverted()
    placed = []
    centre = Point((x0 + x1) / 2, (y0 + y1) / 2)
    for where, text in labels:
        fp = fps.get(where) if isinstance(where, str) else None
        if fp is None and isinstance(where, str):
            fp = (red_dashed or {}).get(where)
        if fp is None:
            continue
        vis = fp.intersection(inner)
        if vis.is_empty:
            continue
        anchor = nearest_points(vis, centre)[0] if not vis.contains(centre) else centre
        if vis.area > 0 and vis.area < 0.01 * W * W:
            anchor = vis.centroid if vis.contains(vis.centroid) else anchor
        t = ax.text(0, 0, text, fontsize=6, ha='left', va='bottom',
                    bbox=dict(facecolor='white', edgecolor='#30353A', lw=0.3, pad=0.8))
        bb = t.get_window_extent(ren)
        t.remove()
        (ax0, ay0), (ax1, ay1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]])
        bw, bh = abs(ax1 - ax0) * 1.08, abs(ay1 - ay0) * 1.15
        best = None
        for dist in (0.035, 0.07, 0.11, 0.16):
            for ang in (45, 135, -45, -135, 90, -90, 0, 180):
                ca, sa = np.cos(np.radians(ang)), np.sin(np.radians(ang))
                cx, cy = anchor.x + ca * dist * W, anchor.y + sa * dist * W
                bx = cx if ca > 0.3 else cx - bw if ca < -0.3 else cx - bw / 2
                by = cy if sa > 0.3 else cy - bh if sa < -0.3 else cy - bh / 2
                cand = sbox(bx, by, bx + bw, by + bh)
                cost = 0.0
                if not cand.within(sbox(x0, y0, x1, y1)):
                    cost += 1000
                cost += sum(cand.intersection(p).area for p in placed) * 50 / (bw * bh)
                cost += sum(cand.intersection(k).area for k in keep_free) * 20 / (bw * bh)
                if red_u is not None:
                    cost += cand.intersection(red_u).area * 10 / (bw * bh)
                cost += dist * 2
                if best is None or cost < best[0]:
                    best = (cost, cand)
        cand = best[1]
        placed.append(cand)
        tx, ty = cand.bounds[0], cand.bounds[1]
        p_box = nearest_points(cand, anchor)[0]
        ax.plot([anchor.x, p_box.x], [anchor.y, p_box.y], color='#30353A', lw=0.45, zorder=39)
        ax.plot([anchor.x], [anchor.y], marker='o', ms=2.2, color='#30353A', zorder=41)
        ax.text(tx + 0.04 * bw, ty + 0.07 * bh, text, ha='left', va='bottom', fontsize=6, zorder=40,
                bbox=dict(facecolor='white', edgecolor='#30353A', lw=0.3, pad=0.8, alpha=0.95))


def north_arrow(ax, x, y, size):
    ax.add_patch(FancyArrow(x, y - size * 0.5, 0, size, width=size * 0.08, head_width=size * 0.35,
                            head_length=size * 0.35, length_includes_head=True, color='k', zorder=30))
    ax.text(x, y + size * 0.62, 'N', ha='center', va='bottom', fontsize=7, fontweight='bold', zorder=30)


def fit_window(core, aspect, min_w=14.0, margin=3.0, limit=None):
    """Window (x0, y0, x1, y1) around the bounds `core` with a margin, at width/height = aspect."""
    x0, y0, x1, y1 = core
    x0, y0, x1, y1 = x0 - margin, y0 - margin, x1 + margin, y1 + margin
    w, h = x1 - x0, y1 - y0
    w = max(w, min_w, h * aspect)
    h = w / aspect
    cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
    return cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2


def plan_view(path_png, fps, meshes, window, title, red_solid=(), red_dashed=None, labels=(),
              figsize=(3.35, 2.95), dpi=150, ghosts=None, footer=None):
    """Draw one plan view.

    fps: {guid: footprint}; meshes: {guid: mesh} (for class and name); red_solid: guids outlined in
    red; red_dashed: {guid: footprint} of removed elements; labels: [(guid or (x, y), text)]."""
    fw, fh = figsize
    fpad = 0.0
    if footer:
        fpad = 0.13 * (footer.count('\n') + 1) + 0.06
    fig = plt.figure(figsize=(fw, fh + fpad), dpi=dpi)
    H = fh + fpad
    ax = fig.add_axes([0.01, (0.01 * fh + fpad) / H, 0.98, 0.88 * fh / H])
    if footer:
        fig.text(0.02, (fpad - 0.03) / H, footer, ha='left', va='top', fontsize=6.5)
    x0, y0, x1, y1 = window
    win = sbox(x0, y0, x1, y1)
    order = {'IfcSlab': 0, 'IfcSpace': 1, 'IfcStair': 2, 'IfcStairFlight': 2, 'IfcWall': 3, 'IfcCurtainWall': 3,
             'IfcColumn': 4, 'IfcDoor': 5, 'IfcWindow': 5}
    def rank(g):
        c = meshes[g]['cls']
        for k, v in order.items():
            if c.startswith(k):
                return v
        return 3
    space_names = []
    for g in sorted(fps, key=rank):
        fp = fps[g]
        if not fp.intersects(win):
            continue
        c = meshes[g]['cls']
        if c.startswith('IfcSlab'):
            draw_geom(ax, fp, fc='none', ec=SLAB_EDGE, lw=0.6, z=1)
        elif c.startswith('IfcSpace'):
            draw_geom(ax, fp, fc='none', ec=SPACE_EDGE, lw=0.45, ls=(0, (3, 2)), z=2)
            nm = (meshes[g]['name'] or '').strip()
            if nm:
                rp = fp.intersection(win).representative_point() if fp.intersection(win).area > 0 else None
                if rp is not None:
                    space_names.append((rp.x, rp.y, nm, fp.intersection(win).area))
        elif c.startswith('IfcStair'):
            draw_geom(ax, fp, fc='none', ec=SPACE_EDGE, lw=0.4, z=2)
        elif c.startswith(WALL_CLASSES):
            draw_geom(ax, fp, fc=WALL_FILL, ec=WALL_EDGE, lw=0.35, z=3)
        elif c.startswith('IfcColumn'):
            draw_geom(ax, fp, fc=COL_FILL, ec='#30353A', lw=0.35, z=4)
        elif c.startswith(('IfcDoor', 'IfcWindow')):
            draw_geom(ax, fp, fc='white', ec=FILL_EDGE, lw=0.4, z=5)
        else:
            draw_geom(ax, fp, fc='#DADDE1', ec=WALL_EDGE, lw=0.35, z=3)
    for g, fp in (ghosts or {}).items():       # where a moved or reshaped element was before the edit
        draw_geom(ax, fp, fc=GHOST_FILL, ec='none', lw=0, z=19)
    for g in red_solid:
        if g in fps:
            red_outline(ax, fps[g])
    for g, fp in (red_dashed or {}).items():
        red_outline(ax, fp, dashed=True)
    # space names: largest rooms first, skip names that would overlap a placed one
    W = x1 - x0
    placed = []
    for x, y, nm, a in sorted(space_names, key=lambda t: -t[3]):
        if any(abs(x - px) < W * 0.14 and abs(y - py) < W * 0.035 for px, py in placed):
            continue
        if a < (W * 0.04) ** 2:
            continue
        shown = nm if len(nm) <= 26 else nm[:25] + '…'
        hw = len(shown) * 5.2 * 0.5 / 72 / 2 * W / (0.98 * fw)      # half the text width in metres
        if x - hw < x0 or x + hw > x1 or y - 0.02 * W < y0 or y + 0.02 * W > y1:
            continue                                                 # a name cut by the frame is left out
        placed.append((x, y))
        ax.text(x, y, nm if len(nm) <= 26 else nm[:25] + '…', ha='center', va='center', fontsize=5.2,
                color='#30353A', zorder=8, clip_on=True)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect('equal')
    place_labels(ax, fig, labels, fps, red_dashed, red_solid, (x0, y0, x1, y1))
    north_arrow(ax, x1 - W * 0.05, y1 - W * 0.09, W * 0.06)
    scale_bar(ax, x0 + W * 0.04, y0 + W * 0.03, W)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect('equal')
    ax.set_xticks([]); ax.set_yticks([])
    for s in ax.spines.values():
        s.set_color('#9AA0A6'); s.set_linewidth(0.4)
    if len(title) > 50:                                  # long storey names wrap onto a second line
        import textwrap
        title = '\n'.join(textwrap.wrap(title.replace(' (ID ', '\n(ID ') if '(ID ' in title else title, 58)
                           if '(ID ' not in title else title.replace(' (ID ', '\n(ID ').split('\n'))
    fig.text(0.5, 1 - 0.05 * fh / H, title, ha='center', va='center', fontsize=7.5 if '\n' not in title else 6.8,
             fontweight='bold', linespacing=1.1)
    fig.savefig(path_png, dpi=dpi)
    plt.close(fig)


# --------------------------------------------------------------------------- elevation
def wall_axis(wall):
    M = np.asarray(up.get_local_placement(wall.ObjectPlacement), float)
    a = M[:3, 0].copy()
    a[2] = 0.0
    n = np.linalg.norm(a)
    return a / n if n > 1e-9 else np.array([1.0, 0.0, 0.0])


def elevation_view(path_png, wall_mesh, axis, fillings, red_solid=(), red_dashed=None, mark=None,
                   wall_height_mark=False, title='', figsize=(3.35, 1.45), dpi=150, frame=None, red_wall=False,
                   focus=None, span=9.0):
    """Face-on view of a wall. fillings: {guid: mesh}; red_dashed: {guid: mesh} from the other model;
    mark: guid of the filling whose sill and head are dimensioned; frame: (s0, z0) to reuse."""
    V = wall_mesh['verts']
    s = V @ axis
    if frame is None:
        frame = (float(s.min()), float(V[:, 2].min()))
    s0, z0 = frame
    T = V[wall_mesh['faces']]
    P = np.stack([T @ axis - s0, T[:, :, 2] - z0], axis=-1)
    geom = _tri_union(P)
    fig = plt.figure(figsize=figsize, dpi=dpi)
    ax = fig.add_axes([0.02, 0.03, 0.96, 0.72])
    draw_geom(ax, geom, fc=WALL_FILL, ec=RED if red_wall else WALL_EDGE, lw=1.4 if red_wall else 0.4, z=1)
    L = float((s - s0).max())
    Hw = float(V[:, 2].max() - z0)

    def rect(m):
        q = m['verts']
        ss = q @ axis - s0
        zz = q[:, 2] - z0
        return float(ss.min()), float(zz.min()), float(ss.max()), float(zz.max())
    rects = {}
    for g, m in fillings.items():
        r = rect(m)
        rects[g] = r
        red = g in red_solid
        ax.add_patch(Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], facecolor='white',
                               edgecolor=RED if red else FILL_EDGE, lw=1.4 if red else 0.45, zorder=5))
    for g, m in (red_dashed or {}).items():
        r = rect(m)
        rects[g] = r
        ax.add_patch(Rectangle((r[0], r[1]), r[2] - r[0], r[3] - r[1], facecolor='none',
                               edgecolor=RED, lw=1.2, ls=(0, (3, 1.6)), zorder=6))
    ax.plot([-0.05 * L, 1.05 * L], [0, 0], color='k', lw=0.6, zorder=2)
    if mark in rects:
        a, b, c, d = rects[mark]
        u = min(max(L, 3), span)
        xd = c + 0.04 * u
        for zz in (b, d):
            ax.plot([c, xd + 0.02 * u], [zz, zz], color='k', lw=0.35, zorder=7)
        ax.annotate('', xy=(xd, 0), xytext=(xd, d), arrowprops=dict(arrowstyle='<->', lw=0.4, shrinkA=0, shrinkB=0),
                    zorder=7)
        ax.text(xd + 0.03 * u, d, f'head {d:.2f} m', ha='left', va='center', fontsize=6, zorder=8,
                bbox=dict(facecolor='white', edgecolor='none', pad=0.3, alpha=0.9))
        ax.text(xd + 0.03 * u, max(b, 0.0) + (0.12 * Hw if b < 0.05 else 0), f'sill {b:.2f} m',
                ha='left', va='center', fontsize=6, zorder=8,
                bbox=dict(facecolor='white', edgecolor='none', pad=0.3, alpha=0.9))
    if wall_height_mark:
        xd = L + 0.04 * max(L, 3)
        ax.annotate('', xy=(xd, 0), xytext=(xd, Hw), arrowprops=dict(arrowstyle='<->', lw=0.4, shrinkA=0, shrinkB=0))
        ax.text(xd + 0.02 * max(L, 3), Hw / 2, f'height {Hw:.2f} m', ha='left', va='center', fontsize=6)
    if focus is None and len(rects):
        rs = np.array(list(rects.values()))
        focus = (rs[:, 0].min(), rs[:, 2].max())
    if L > span and focus is not None:
        c = (focus[0] + focus[1]) / 2
        lo = min(max(c - span / 2, -0.3), L + 0.3 - span)
        ax.set_xlim(lo, lo + span * 1.25)
    else:
        pad = 0.06 * max(L, 3)
        ax.set_xlim(-pad, L + pad + 0.30 * max(L, 3))
    ax.set_ylim(-0.25, Hw + 0.35)
    ax.set_aspect('equal')
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_visible(False)
    xl = ax.get_xlim()
    if xl[0] <= 0.0 <= xl[1]:
        ax.text(0.0, Hw + 0.08, 'wall start', ha='left', va='bottom', fontsize=5.5)
        ax.plot([0, 0], [0, Hw], color='k', lw=0.8, zorder=3)
    # 1 m bar under the wall
    xl = ax.get_xlim()
    bx = xl[0] + 0.03 * (xl[1] - xl[0])
    ax.plot([bx, bx + 1.0], [-0.17, -0.17], color='k', lw=1.2, solid_capstyle='butt')
    ax.text(bx + 1.08, -0.17, '1 m', ha='left', va='center', fontsize=5.5)
    fig.text(0.5, 0.92, title, ha='center', va='center', fontsize=6.5, linespacing=1.15)
    fig.savefig(path_png, dpi=dpi)
    plt.close(fig)
    return frame
