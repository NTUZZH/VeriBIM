#!/usr/bin/env python
"""Deterministic element index of one IFC file (IFC2X3, IFC4, IFC4X3), cached under cache/<md5 of path>.json.

Per product (spaces included and flagged by their class IfcSpace, since requests also target rooms; storeys,
buildings, sites, ports and spatial zones left out, storeys listed separately with name and elevation): GlobalId, IFC class, Name, Tag,
ObjectType, PredefinedType, storey, containing room(s), compass sector, axis-aligned box (metres, rounded to 0.01),
the placement origin in world metres, the authoring-tool number (trailing ':NNNN' of the Name), and the relations a request can point through (host wall
of a filling or opening, fillings of a host, connected elements, space boundaries, aggregate parent).
Conventions: geometry is meshed with ifcopenshell.geom in world coordinates (the harness settings, use-world-coords
and weld-vertices), lengths in metres. Room: the IfcSpace on the same storey whose projected mesh (plan footprint,
exact polygon via its triangles) contains the element's plan centroid; when none does, the spaces hit by the centroid
shifted 0.5 m along +-X and +-Y are recorded as adjacent rooms (doors, windows and walls lie between rooms). Compass:
north is the IfcProject model context's TrueNorth when given, else model +Y; the sector (north/east/south/west, 90
degrees each) is the bearing of the element's plan centroid from the centre of its storey's plan box. An element whose
geometry fails takes the box of its aggregated parts when it has any, else keeps its non-geometric fields with null
geometry; the count is logged."""
import hashlib, json, math, os, re, sys, time
import numpy as np
import ifcopenshell, ifcopenshell.geom, ifcopenshell.util.element as ue, ifcopenshell.util.placement as up
import ifcopenshell.util.unit as uu

P = os.environ.get('VERIBIM_ROOT') or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
SKIP = ('IfcSite', 'IfcBuilding', 'IfcBuildingStorey', 'IfcPort', 'IfcSpatialZone', 'IfcExternalSpatialElement')
VERSION = 5


def abspath(path):
    return path if os.path.isabs(path) else os.path.join(P, path)


def cache_path(path):
    return os.path.join(HERE, 'cache', hashlib.md5(abspath(path).encode()).hexdigest() + '.json')


def tool_number(name):
    m = re.search(r':(\d{4,})$', name or '')
    return m.group(1) if m else None


def storey_of(p, depth=0):
    """The IfcBuildingStorey that holds p, walking containment, aggregation, space and host relations."""
    if p is None or depth > 8:
        return None
    if p.is_a('IfcBuildingStorey'):
        return p
    nxt = ue.get_container(p) or ue.get_aggregate(p)
    if nxt is None and p.is_a('IfcOpeningElement') and p.VoidsElements:
        nxt = p.VoidsElements[0].RelatingBuildingElement
    if nxt is None and getattr(p, 'FillsVoids', None):
        nxt = p.FillsVoids[0].RelatingOpeningElement
    return storey_of(nxt, depth + 1)


def true_north(f):
    for proj in f.by_type('IfcProject'):
        for ctx in proj.RepresentationContexts or []:
            tn = getattr(ctx, 'TrueNorth', None)
            if tn is not None and ctx.is_a('IfcGeometricRepresentationContext'):
                x, y = float(tn.DirectionRatios[0]), float(tn.DirectionRatios[1])
                n = math.hypot(x, y)
                if n > 1e-9:
                    return [x / n, y / n], 'IfcProject TrueNorth'
    return [0.0, 1.0], 'model +Y (no TrueNorth)'


def in_footprint(tris, pt):
    """True when pt (x, y) lies in any projected triangle of tris (n x 3 x 2)."""
    a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
    def cross(u, v, w):
        return (v[:, 0] - u[:, 0]) * (w[1] - u[:, 1]) - (v[:, 1] - u[:, 1]) * (w[0] - u[:, 0])
    d1, d2, d3 = cross(a, b, pt), cross(b, c, pt), cross(c, a, pt)
    neg = (d1 < -1e-9) | (d2 < -1e-9) | (d3 < -1e-9)
    pos = (d1 > 1e-9) | (d2 > 1e-9) | (d3 > 1e-9)
    return bool(np.any(~(neg & pos)))


def build(path):
    t0, c0 = time.time(), time.process_time()
    f = ifcopenshell.open(abspath(path))
    north, north_src = true_north(f)
    east = [north[1], -north[0]]
    storeys = {s.GlobalId: {'name': s.Name or '', 'elev': float(s.Elevation) if s.Elevation is not None else None}
               for s in f.by_type('IfcBuildingStorey')}
    prods = [p for p in f.by_type('IfcProduct') if not any(p.is_a(c) for c in SKIP)]
    settings = ifcopenshell.geom.settings()
    settings.set('use-world-coords', True)
    settings.set('weld-vertices', True)
    box, tris = {}, {}
    with_rep = [p for p in prods if getattr(p, 'Representation', None)]
    if with_rep:
        it = ifcopenshell.geom.iterator(settings, f, 1, include=with_rep)
        if it.initialize():
            while True:
                sh = it.get()
                v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
                if v.size:
                    box[sh.guid] = (v.min(axis=0), v.max(axis=0))
                    if f.by_guid(sh.guid).is_a('IfcSpace'):
                        fc = np.asarray(sh.geometry.faces, dtype=np.int64).reshape(-1, 3)
                        tris[sh.guid] = v[fc][:, :, :2]
                if not it.next():
                    break
    # an element with no body of its own (a wall drawn as an axis with layered parts) takes the box of its parts
    for r in f.by_type('IfcRelAggregates'):
        g = r.RelatingObject.GlobalId
        parts = [box[c.GlobalId] for c in r.RelatedObjects if c.GlobalId in box]
        if g not in box and parts and r.RelatingObject.is_a('IfcProduct'):
            box[g] = (np.min([b[0] for b in parts], axis=0), np.max([b[1] for b in parts], axis=0))
    scale = uu.calculate_unit_scale(f)
    els = {}
    for p in prods:
        st = storey_of(p)
        try:
            org = [round(float(x) * scale, 2) for x in up.get_local_placement(p.ObjectPlacement)[:3, 3]] if p.ObjectPlacement else None
        except Exception:
            org = None
        e = {'g': p.GlobalId, 'c': p.is_a(), 'n': p.Name or '', 'tag': getattr(p, 'Tag', None) or '',
             'ot': getattr(p, 'ObjectType', None) or '', 'pt': str(getattr(p, 'PredefinedType', None) or ''),
             'ln': getattr(p, 'LongName', None) or '', 'sg': st.GlobalId if st else None,
             'st': (st.Name or '') if st else '', 'num': tool_number(p.Name), 'rooms': [], 'adj': [],
             'sec': None, 'lo': None, 'hi': None, 'org': org, 'host': None, 'fills': [], 'conn': [], 'bnd': [], 'parent': None}
        if p.GlobalId in box:
            lo, hi = box[p.GlobalId]
            e['lo'], e['hi'] = [round(float(x), 2) for x in lo], [round(float(x), 2) for x in hi]
        els[p.GlobalId] = e
    # relations
    def add(lst, g):
        if g and g not in lst:
            lst.append(g)
    for r in f.by_type('IfcRelFillsElement'):
        op, fl = r.RelatingOpeningElement, r.RelatedBuildingElement
        host = op.VoidsElements[0].RelatingBuildingElement if op.VoidsElements else None
        if host is not None and fl.GlobalId in els and host.GlobalId in els:
            els[fl.GlobalId]['host'] = host.GlobalId
            add(els[host.GlobalId]['fills'], fl.GlobalId)
    for r in f.by_type('IfcRelVoidsElement'):
        h, o = r.RelatingBuildingElement, r.RelatedOpeningElement
        if h.GlobalId in els and o.GlobalId in els:
            els[o.GlobalId]['host'] = h.GlobalId
            add(els[h.GlobalId]['fills'], o.GlobalId)
    for r in f.by_type('IfcRelConnectsElements'):
        a, b = r.RelatingElement, r.RelatedElement
        if a and b and a.GlobalId in els and b.GlobalId in els:
            add(els[a.GlobalId]['conn'], b.GlobalId)
            add(els[b.GlobalId]['conn'], a.GlobalId)
    for r in f.by_type('IfcRelSpaceBoundary'):
        s, b = r.RelatingSpace, r.RelatedBuildingElement
        if s is not None and b is not None and s.GlobalId in els and b.GlobalId in els:
            add(els[s.GlobalId]['bnd'], b.GlobalId)
            add(els[b.GlobalId]['bnd'], s.GlobalId)
    for r in f.by_type('IfcRelAggregates'):
        for c in r.RelatedObjects:
            if c.GlobalId in els and r.RelatingObject.GlobalId in els:
                els[c.GlobalId]['parent'] = r.RelatingObject.GlobalId
    # rooms, compass sector
    spaces_by_storey = {}
    for g, t in tris.items():
        spaces_by_storey.setdefault(els[g]['sg'], []).append(g)
    centre = {}
    solid = {e['sg'] for e in els.values() if e['lo'] and e['c'] != 'IfcSpace'}
    for e in els.values():  # storey plan box from its non-space elements, from its spaces when it has nothing else
        if e['lo'] and (e['c'] != 'IfcSpace' or e['sg'] not in solid):
            centre.setdefault(e['sg'], []).append((e['lo'], e['hi']))
    for sg, bs in list(centre.items()):
        lo, hi = np.min([b[0] for b in bs], axis=0), np.max([b[1] for b in bs], axis=0)
        centre[sg] = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    names = ('north', 'east', 'south', 'west')
    for e in els.values():
        if not e['lo']:
            continue
        cx, cy = (e['lo'][0] + e['hi'][0]) / 2, (e['lo'][1] + e['hi'][1]) / 2
        if e['sg'] in centre:
            dx, dy = cx - centre[e['sg']][0], cy - centre[e['sg']][1]
            ang = math.degrees(math.atan2(dx * east[0] + dy * east[1], dx * north[0] + dy * north[1])) % 360
            e['sec'] = names[int(((ang + 45) % 360) // 90)]
        if e['c'] == 'IfcSpace':
            continue
        cand = spaces_by_storey.get(e['sg'], [])
        def hit(x, y):
            out = []
            for g in cand:
                lo, hi = els[g]['lo'], els[g]['hi']
                if lo[0] - 0.01 <= x <= hi[0] + 0.01 and lo[1] - 0.01 <= y <= hi[1] + 0.01 and in_footprint(tris[g], (x, y)):
                    out.append(g)
            return out
        e['rooms'] = hit(cx, cy)
        if not e['rooms'] and cand:
            for ox, oy in ((0.5, 0), (-0.5, 0), (0, 0.5), (0, -0.5)):
                for g in hit(cx + ox, cy + oy):
                    if g not in e['adj']:
                        e['adj'].append(g)
    nogeo = sum(1 for p in prods if p.GlobalId not in box)
    out = {'version': VERSION, 'path': path, 'schema': f.schema, 'north': north, 'north_source': north_src,
           'storeys': storeys, 'n_products': len(prods), 'n_without_geometry': nogeo,
           'has_space_boundaries': bool(f.by_type('IfcRelSpaceBoundary')),
           'build_seconds': round(time.time() - t0, 2), 'build_cpu_seconds': round(time.process_time() - c0, 2),
           'elements': [els[g] for g in sorted(els)]}
    return out


_mem = {}


def load(path, rebuild=False):
    cp = cache_path(path)
    if not rebuild and cp in _mem:
        return _mem[cp]
    if not rebuild and os.path.exists(cp):
        with open(cp) as fh:
            idx = json.load(fh)
        if idx.get('version') == VERSION:
            _mem[cp] = idx
            return idx
    idx = build(path)
    os.makedirs(os.path.dirname(cp), exist_ok=True)
    tmp = cp + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(idx, fh, ensure_ascii=False)
    os.replace(tmp, cp)
    _mem[cp] = idx
    print(f"indexed {path}: {idx['schema']} {idx['n_products']} products, {idx['n_without_geometry']} without geometry, "
          f"{idx['build_seconds']} s wall, {idx['build_cpu_seconds']} s cpu, north {idx['north_source']}", file=sys.stderr)
    return idx


if __name__ == '__main__':
    # usage: index_ifc.py [--rebuild] <ifc path relative to the repository root or absolute> ...
    args = [a for a in sys.argv[1:] if a != '--rebuild']
    for a in args:
        load(a, rebuild='--rebuild' in sys.argv)
