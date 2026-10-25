"""Render the verdict-audit cases (packet B): BEFORE = the source model, AFTER = the stored model output.

Inputs: draw.json (audit_cases, from sample_tasks.py), tmp/outputs/<label>.ifc.gz (fetch_outputs.py),
the source models (read-only) and, only to pick the storey of a case whose output changed nothing,
the ground-truth model of the task. Nothing about the ground truth is drawn.

What changed is read from the two files: elements added, removed and modified (the checker's own
entity comparison, modifc_score.topology.full_signature, over every element), and the relationships
added or removed (the checker's six relation classes plus type and material assignments). Changed
elements are outlined in red in both views. A list of the differences, with sizes and positions
measured on the output geometry, is written to view.json for the page text.

Outputs under renders_audit/<label>/: before_plan.png, after_plan.png, and when a door or window
changed (or a wall's height) before_elev.png, after_elev.png; view.json; render_audit_log.jsonl.
Run: OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONPATH=code taskset -c 16-23 <l2 python> render_audit.py [--only A01,A02]
"""
import argparse, collections, json, os, re, sys, time, traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_render as P  # noqa: E402
import render_tasks as RT  # noqa: E402
import ifcopenshell.util.element as ue  # noqa: E402
import ifcopenshell.util.placement as up  # noqa: E402
import ifcopenshell.util.unit as uu  # noqa: E402
from modifc_score import topology as TP  # noqa: E402
from modifc_score.config import TOPOLOGY_RELATIONS  # noqa: E402

ROOT = ''
OUT = os.path.join(HERE, 'renders_audit')
OUTPUTS = os.path.join(HERE, 'tmp', 'outputs')
GID = RT.GID
RELS = tuple(TOPOLOGY_RELATIONS) + ('IfcRelDefinesByType', 'IfcRelAssociatesMaterial')
SKIP = ('IfcOpeningElement', 'IfcAnnotation', 'IfcGrid', 'IfcVirtualElement', 'IfcSite', 'IfcBuilding',
        'IfcBuildingStorey', 'IfcProject', 'IfcFacility', 'IfcFacilityPart')
WORDS = (('IfcCurtainWall', 'curtain wall'), ('IfcWall', 'wall'), ('IfcSlab', 'slab'), ('IfcColumn', 'column'),
         ('IfcDoor', 'door'), ('IfcWindow', 'window'), ('IfcSpace', 'space'), ('IfcBeam', 'beam'),
         ('IfcStairFlight', 'stair flight'), ('IfcStair', 'stair'), ('IfcCovering', 'covering'),
         ('IfcBuildingElementPart', 'wall layer part'), ('IfcFlowFitting', 'MEP fitting'),
         ('IfcFlowTerminal', 'MEP terminal'), ('IfcFlowController', 'MEP controller'),
         ('IfcFlowSegment', 'MEP segment'), ('IfcFurnishingElement', 'furniture item'),
         ('IfcFurniture', 'furniture item'), ('IfcBuildingElementProxy', 'generic element'),
         ('IfcMember', 'member'), ('IfcPlate', 'plate'), ('IfcRailing', 'railing'), ('IfcRoof', 'roof'),
         ('IfcFooting', 'footing'), ('IfcRamp', 'ramp'), ('IfcOpeningElement', 'opening'))


def word(e_or_cls):
    c = e_or_cls if isinstance(e_or_cls, str) else e_or_cls.is_a()
    for k, w in WORDS:
        if c.startswith(k):
            return w
    return re.sub(r'(?<!^)(?=[A-Z])', ' ', c[3:]).lower() if c.startswith('Ifc') else c


def plural(w, n):
    if n == 1:
        return w
    if w.endswith('ss') or w.endswith('ch'):
        return w + 'es'
    if w.endswith('y') and not w.endswith(('ay', 'ey', 'oy')):
        return w[:-1] + 'ies'
    return w + 's'


def m(v):
    return f'{v:.2f} m'


def products(model):
    out = {}
    for e in model.by_type('IfcProduct'):
        if any(e.is_a(s) for s in SKIP) or (e.is_a('IfcSpatialStructureElement') and not e.is_a('IfcSpace')):
            continue
        g = getattr(e, 'GlobalId', None)
        if g:
            out[g] = e
    return out


def rel_sig(e):
    """Container, host, type and material of an element, as one comparable value."""
    try:
        c = ue.get_container(e)
    except Exception:
        c = None
    host = P.host_of(e) if hasattr(e, 'FillsVoids') else None
    try:
        t = ue.get_type(e)
    except Exception:
        t = None
    try:
        mats = tuple(sorted(x.Name or '' for x in ue.get_materials(e)))
    except Exception:
        mats = ()
    agg = ue.get_aggregate(e)
    return (c.GlobalId if c is not None else None, host.GlobalId if host is not None else None,
            t.Name if t is not None else None, mats, agg.GlobalId if agg is not None else None)


def _lines(model):
    return {e.id(): str(e) for e in model}


def _affected(model, ids):
    """Products reached from the entities `ids` by walking up inverse references; a relationship
    passes on to the products it references."""
    out, seen = set(), set()
    stack = [model.by_id(i) for i in ids]
    while stack:
        e = stack.pop()
        if e is None or e.id() in seen:
            continue
        seen.add(e.id())
        if e.is_a('IfcProduct'):
            g = getattr(e, 'GlobalId', None)
            if g:
                out.add(g)
            continue
        if e.is_a('IfcRelationship'):
            for v in e:
                for x in (v if isinstance(v, (list, tuple)) else [v]):
                    if hasattr(x, 'is_a') and x.is_a('IfcProduct') and getattr(x, 'GlobalId', None):
                        out.add(x.GlobalId)
            continue
        stack.extend(model.get_inverse(e))
    return out


def candidate_guids(src, out):
    """Shared products that may differ: those reached from entities whose STEP line differs between
    the two files (both files keep the source's entity numbers when an edit is written back). None
    when the numbering does not match, so that every shared product is compared."""
    a, b = _lines(src), _lines(out)
    common = set(a) & set(b)
    if not common:
        return None
    changed = [i for i in common if a[i] != b[i]]
    if len(changed) > 0.3 * len(common):
        return None
    only_a = [i for i in a if i not in b]
    only_b = [i for i in b if i not in a]
    # a line that names an entity of the other file by number is matched by its text, so look at the
    # entities referenced by changed lines too
    return _affected(src, changed + only_a) | _affected(out, changed + only_b)


def diff_models(src, out):
    ps, po = products(src), products(out)
    added = [g for g in po if g not in ps]
    removed = [g for g in ps if g not in po]
    shared = [g for g in ps if g in po]
    cand = candidate_guids(src, out)
    if cand is not None:
        shared_cmp = [g for g in shared if g in cand]
    else:
        shared_cmp = shared
    modified = []
    for g in shared_cmp:
        a, b = ps[g], po[g]
        if TP.full_signature(a) != TP.full_signature(b) or rel_sig(a) != rel_sig(b):
            modified.append(g)
    e0, e1 = TP.edge_set(src, RELS), TP.edge_set(out, RELS)
    return dict(added=added, removed=removed, modified=modified, edges_added=sorted(e1 - e0),
                edges_removed=sorted(e0 - e1), n_shared=len(shared), n_compared=len(shared_cmp),
                prefilter=cand is not None)


# --------------------------------------------------------------------------- measurements
def mesh_of(model, e, cache):
    if e is None:
        return None
    g = e.GlobalId
    if g not in cache:
        cache[g] = P.tessellate(model, [e]).get(g)
    return cache[g]


def axis_of(e):
    try:
        return P.wall_axis(e)
    except Exception:
        return np.array([1.0, 0.0, 0.0])


def extents(mesh, axis):
    V = mesh['verts']
    perp = np.array([-axis[1], axis[0], 0.0])
    a, b = V @ axis, V @ perp
    return float(a.max() - a.min()), float(b.max() - b.min()), float(V[:, 2].max() - V[:, 2].min())


def centre(mesh):
    V = mesh['verts']
    return (V.min(0) + V.max(0)) / 2


def storey_frame(model, storey):
    M = np.asarray(up.get_local_placement(storey.ObjectPlacement), float)
    s = uu.calculate_unit_scale(model)
    R = M[:3, :3].copy()
    t = M[:3, 3] * s
    return R, t


def compass(v):
    ang = (np.degrees(np.arctan2(v[1], v[0])) + 360) % 360
    words = ['east', 'north-east', 'north', 'north-west', 'west', 'south-west', 'south', 'south-east']
    return words[int(((ang + 22.5) % 360) // 45)]


def ref_name(e, ment):
    """How a page names an element: the words the instruction uses for it, else its name."""
    if e is None:
        return 'an element'
    g = e.GlobalId
    w = word(e)
    nm = (getattr(e, 'Name', None) or '').strip()
    if g in ment and ment[g] == g:
        return f"the {w} with ID {g}" + (f" ('{nm}')" if nm else '')
    if nm:
        return f"the {w} '{nm}'"
    return f'an unnamed {w}'


def storey_word(st):
    return f"'{st.Name}'" if st is not None and st.Name else '(unnamed storey)'


def filling_measure(model, e, cache):
    """Width, height and sill of a door or window measured on its geometry and its host wall."""
    mm = mesh_of(model, e, cache)
    if mm is None:
        return None
    host = P.host_of(e)
    ax = axis_of(host) if host is not None else axis_of(e)
    w, _, h = extents(mm, ax)
    if host is not None:
        hm = mesh_of(model, host, cache)
        base = float(hm['verts'][:, 2].min()) if hm is not None else float(mm['verts'][:, 2].min())
    else:
        base = None
    sill = float(mm['verts'][:, 2].min()) - base if base is not None else None
    along = None
    if host is not None:
        hm = mesh_of(model, host, cache)
        if hm is not None:
            s0 = float((hm['verts'] @ ax).min())
            along = float((mm['verts'] @ ax).min()) - s0
    return dict(width=w, height=h, sill=sill, host=host, along=along)


def ment_src_ids(ment):
    return set(ment)


def describe_added(e, model, st_model, rec, ment, cache):
    w = word(e)
    nm = (e.Name or '').strip()
    head = f"New {w}" + (f" '{nm}'" if nm else ' (no name)')
    parts = []
    mm = mesh_of(model, e, cache)
    if e.is_a('IfcDoor') or e.is_a('IfcWindow'):
        fm = filling_measure(model, e, cache)
        if fm is None:
            parts.append('has no geometry')
        else:
            parts.append(f"{m(fm['width'])} wide and {m(fm['height'])} high")
            if fm['host'] is not None:
                parts.append(f"sill {m(fm['sill'])} above the {word(fm['host'])}'s base" if fm['sill'] is not None else '')
                parts.append(f"in {ref_name(fm['host'], ment)}, its near edge {m(fm['along'])} from the "
                             f"{word(fm['host'])}'s start"
                             if fm['along'] is not None else f"in {ref_name(fm['host'], ment)}")
            else:
                parts.append('not placed in any wall')
    elif mm is None:
        parts.append('has no geometry')
    else:
        ax = axis_of(e)
        L, W, H = extents(mm, ax)
        if e.is_a('IfcSlab'):
            parts.append(f'{m(L)} by {m(W)} in plan and {m(H)} thick')
        elif e.is_a('IfcColumn'):
            parts.append(f'{m(L)} by {m(W)} in section and {m(H)} high')
        elif e.is_a('IfcWall'):
            parts.append(f'{m(L)} long, {m(W)} thick and {m(H)} high')
        else:
            parts.append(f'{m(L)} long, {m(W)} wide and {m(H)} high')
        st = P.storey_of(e)
        ins = rec['instruction']
        if st is not None and ('own coordinates' in ins or 'world coordinates' in ins):
            R, t = storey_frame(st_model, st)
            loc = (mm['verts'] - t) @ R
            lo = loc.min(0)
            if 'world coordinates' in ins:
                wc = t + R @ lo
                parts.append(f'lowest corner at ({wc[0]:.2f}, {wc[1]:.2f}, {wc[2]:.2f}) m in world coordinates')
            else:
                parts.append(f"lowest corner at ({lo[0]:.2f}, {lo[1]:.2f}, {lo[2]:.2f}) m in the storey's own coordinates")
    # a copy: where it stands relative to a named element of the same kind
    if mm is not None and not (e.is_a('IfcDoor') or e.is_a('IfcWindow')) and \
            re.search(r'\b(cop(y|ies)|duplicate)', rec['instruction'], re.I):
        for g, txt in ment.items():
            r = model.by_guid(g) if g else None
            if r is None or r.GlobalId == e.GlobalId or word(r) != word(e) or r.GlobalId not in ment_src_ids(ment):
                continue
            rm = mesh_of(model, r, cache)
            if rm is None:
                continue
            dv = centre(mm) - centre(rm)
            bits = []
            if abs(dv[0]) >= 0.005:
                bits.append(f"{m(abs(dv[0]))} to the {'east' if dv[0] > 0 else 'west'}")
            if abs(dv[1]) >= 0.005:
                bits.append(f"{m(abs(dv[1]))} to the {'north' if dv[1] > 0 else 'south'}")
            if abs(dv[2]) >= 0.005:
                bits.append(f"{m(abs(dv[2]))} {'higher' if dv[2] > 0 else 'lower'}")
            if bits:
                parts.append(f"measured from the centre of {ref_name(r, ment)}, its centre is "
                             f"{', '.join(bits[:-1]) + ' and ' + bits[-1] if len(bits) > 1 else bits[0]}")
            else:
                parts.append(f'its centre is at the centre of {ref_name(r, ment)}')
            break
    pt = getattr(e, 'PredefinedType', None)
    if pt and pt not in ('NOTDEFINED', 'USERDEFINED'):
        parts.append(f'predefined type {pt}')
    return head, [p for p in parts if p]


def pset_changes(a, b):
    try:
        pa, pb = ue.get_psets(a, should_inherit=False), ue.get_psets(b, should_inherit=False)
    except Exception:
        return []
    out = []
    for ps in sorted(set(pa) | set(pb), key=str):
        da = {k: v for k, v in (pa.get(ps) or {}).items() if k != 'id'}
        db = {k: v for k, v in (pb.get(ps) or {}).items() if k != 'id'}
        for k in sorted(set(da) | set(db), key=str):
            if da.get(k) != db.get(k):
                fa = 'not set' if k not in da else repr(da[k]) if isinstance(da[k], str) else f'{da[k]}'
                fb = 'removed' if k not in db else repr(db[k]) if isinstance(db[k], str) else f'{db[k]}'
                out.append(f'{k} ({ps}) {fa} -> {fb}')
    return out


def describe_modified(g, src, out, ment, cache_s, cache_o):
    a, b = src.by_guid(g), out.by_guid(g)
    parts = []
    na, nb = (a.Name or '').strip(), (b.Name or '').strip()
    if na != nb:
        parts.append(f"renamed from '{na}' to '{nb}'")
    ma, mb = mesh_of(src, a, cache_s), mesh_of(out, b, cache_o)
    if ma is not None and mb is not None:
        if a.is_a('IfcDoor') or a.is_a('IfcWindow'):
            fa, fb = filling_measure(src, a, cache_s), filling_measure(out, b, cache_o)
            for key, lab in (('width', 'width'), ('height', 'height'), ('sill', 'sill')):
                if fa and fb and fa[key] is not None and fb[key] is not None and abs(fa[key] - fb[key]) > 0.005:
                    parts.append(f'{lab} {m(fa[key])} -> {m(fb[key])}')
        else:
            ax_a, ax_b = axis_of(a), axis_of(b)
            ea, eb = extents(ma, ax_a), extents(mb, ax_b)
            names = ('slab', 'column')
            labs = ('length', 'width', 'thickness' if word(a) in names[:1] else 'height')
            for i in range(3):
                if abs(ea[i] - eb[i]) > 0.005:
                    parts.append(f'{labs[i]} {m(ea[i])} -> {m(eb[i])}')
        d = centre(mb) - centre(ma)
        dh = float(np.hypot(d[0], d[1]))
        if dh > 0.005:
            parts.append(f'moved {m(dh)} to the {compass(d)}')
        if abs(d[2]) > 0.005:
            parts.append(f"moved {m(abs(d[2]))} {'up' if d[2] > 0 else 'down'}")
        aa, ab = axis_of(a), axis_of(b)
        ang = float(np.degrees(np.arctan2(aa[0] * ab[1] - aa[1] * ab[0], aa @ ab)))
        if abs(ang) > 0.5:
            parts.append(f"turned {abs(ang):.0f} degrees {'counter-clockwise' if ang > 0 else 'clockwise'}")
    elif (ma is None) != (mb is None):
        parts.append('geometry removed' if mb is None else 'geometry added')
    ra, rb = rel_sig(a), rel_sig(b)
    asg_a, asg_b = ra[0] or ra[4], rb[0] or rb[4]       # spatial container, else the aggregate parent
    if asg_a != asg_b:
        ca, cb = (src.by_guid(asg_a) if asg_a else None), (out.by_guid(asg_b) if asg_b else None)
        def cw(c):
            if c is None:
                return 'no storey or space'
            return (f'storey {storey_word(c)}' if c.is_a('IfcBuildingStorey') else f"{word(c)} '{c.Name or ''}'")
        parts.append(f'now assigned to {cw(cb)} (was {cw(ca)})')
        if not any(p.startswith(('moved', 'turned')) for p in parts):
            parts.append('its position is unchanged')
    if ra[1] != rb[1]:
        ha, hb = (src.by_guid(ra[1]) if ra[1] else None), (out.by_guid(rb[1]) if rb[1] else None)
        parts.append(f"now in {ref_name(hb, ment) if hb is not None else 'no wall'} "
                     f"(was in {ref_name(ha, ment) if ha is not None else 'no wall'})")
    if ra[2] != rb[2]:
        parts.append(f"type '{ra[2] or 'none'}' -> '{rb[2] or 'none'}'")
    if ra[3] != rb[3]:
        parts.append(f"material {', '.join(repr(x) for x in ra[3]) or 'none'} -> {', '.join(repr(x) for x in rb[3]) or 'none'}")
    pa, pb = getattr(a, 'PredefinedType', None), getattr(b, 'PredefinedType', None)
    if pa != pb:
        parts.append(f'predefined type {pa or "not set"} -> {pb or "not set"}')
    pc = pset_changes(a, b)
    parts += pc[:3]
    if len(pc) > 3:
        parts.append(f'{len(pc) - 3} more property values changed')
    if not parts:
        parts.append('stored data changed, with no visible effect on its size, position, name, type, material or properties')
    return ref_name(a, ment)[0].upper() + ref_name(a, ment)[1:], parts


def describe_edges(D, src, out, explained):
    """Relationship changes not already described with an element (space boundaries, connections)."""
    lines = []
    for sign, edges, model in (('+', D['edges_added'], out), ('-', D['edges_removed'], src)):
        cnt = collections.Counter()
        for cls, a, b in edges:
            if a in explained or b in explained:
                continue
            if cls not in ('IfcRelSpaceBoundary', 'IfcRelConnectsElements'):
                continue
            ea, eb = P.by_guid(model, a), P.by_guid(model, b)
            if ea is None or eb is None:
                continue
            if cls == 'IfcRelSpaceBoundary':
                txt = f"{ref_name(eb, {})} bounds {ref_name(ea, {})}"
            else:
                txt = f"{ref_name(ea, {})} is connected to {ref_name(eb, {})}"
            cnt[txt] += 1
        for txt in sorted(cnt):
            lines.append(('New relationship: ' if sign == '+' else 'Relationship removed: ') + txt[0].upper() + txt[1:] + '.')
    return lines


def element_rel_lines(g, D, model, ment):
    """For an added element: the boundaries and connections recorded for it."""
    bits = []
    for cls, a, b in D['edges_added']:
        if g not in (a, b):
            continue
        other = P.by_guid(model, b if a == g else a)
        if other is None:
            continue
        if cls == 'IfcRelSpaceBoundary':
            bits.append(f"bounds {ref_name(other, ment)}" if a != g else f"bounded by {ref_name(other, ment)}")
        elif cls == 'IfcRelConnectsElements':
            bits.append(f'connected to {ref_name(other, ment)}')
    return sorted(set(bits))


def facts(D, src, out, rec, ment, st_shown_after, cache_s, cache_o, same_file):
    lines = []
    if same_file:
        return ['The AFTER model file is identical to the BEFORE model. Nothing was changed.']
    if not (D['added'] or D['removed'] or D['modified'] or D['edges_added'] or D['edges_removed']):
        return ['No element and no relationship differs between the BEFORE and AFTER models.']
    explained = set(D['added']) | set(D['removed']) | set(D['modified'])
    # removed
    if D['removed']:
        els = [src.by_guid(g) for g in D['removed']]
        named = [e for e in els if not e.is_a('IfcOpeningElement')]
        named.sort(key=lambda e: (e.is_a('IfcBuildingElementPart'), word(e), e.Name or ''))
        main_ = [e for e in named if not e.is_a('IfcBuildingElementPart')]
        parts_ = [e for e in named if e.is_a('IfcBuildingElementPart')]
        if len(main_) <= 4:
            txt = '; '.join([ref_name(e, ment) for e in main_] +
                            ([f"{len(parts_)} {plural('wall layer part', len(parts_))} of it"
                              if len(main_) == 1 else f"{len(parts_)} {plural('wall layer part', len(parts_))}"]
                             if len(parts_) > 1 else [ref_name(e, ment) for e in parts_]))
        else:
            cnt = collections.Counter(word(e) for e in named)
            txt = ', '.join(f'{n} {plural(w, n)}' for w, n in sorted(cnt.items(), key=lambda x: -x[1]))
        lines.append(f'Removed: {txt}.')
    # added
    for g in D['added'][:4]:
        e = out.by_guid(g)
        head, parts = describe_added(e, out, out, rec, ment, cache_o)
        parts += element_rel_lines(g, D, out, ment)
        st = P.storey_of(e)
        if st is not None and st_shown_after is not None and st.GlobalId != st_shown_after.GlobalId:
            parts.append(f'on storey {storey_word(st)} (not the storey shown)')
        lines.append(head + (': ' + '; '.join(parts) if parts else '') + '.')
    if len(D['added']) > 4:
        cnt = collections.Counter(word(out.by_guid(g)) for g in D['added'][4:])
        lines.append('Also new: ' + ', '.join(f'{n} {plural(w, n)}' for w, n in cnt.items()) + '.')
    # modified
    rank = ('IfcSpace', 'IfcWall', 'IfcSlab', 'IfcColumn', 'IfcBeam', 'IfcDoor', 'IfcWindow')
    def mrank(g):
        e = src.by_guid(g)
        k = next((i for i, c in enumerate(rank) if e.is_a(c)), len(rank))
        return (g not in ment, k, e.Name or '')
    mods = sorted(D['modified'], key=mrank)
    groups = collections.OrderedDict()
    for g in mods:
        head, parts = describe_modified(g, src, out, ment, cache_s, cache_o)
        key = tuple(re.sub(r"'[^']*'", "''", p) for p in parts)
        groups.setdefault(key, []).append((g, head, parts))
    shown = 0
    for key, items in groups.items():
        if len(items) <= 2 or shown < 3:
            for g, head, parts in items[:3]:
                lines.append(f"{head}: {'; '.join(parts)}.")
                shown += 1
            if len(items) > 3:
                cnt = collections.Counter(word(src.by_guid(g)) for g, _, _ in items[3:])
                lines.append(f"{len(items) - 3} more ({', '.join(f'{n} {plural(w, n)}' for w, n in cnt.items())}) changed "
                             f"in the same way.")
        else:
            cnt = collections.Counter(word(src.by_guid(g)) for g, _, _ in items)
            lines.append(f"{len(items)} more elements ({', '.join(f'{n} {plural(w, n)}' for w, n in cnt.items())}) "
                         f"changed: {'; '.join(items[0][2])}.")
    lines += describe_edges(D, src, out, explained)
    # identical lines (e.g. two new elements with the same name and size) are written once
    out_lines, cnt, seen_lines = [], collections.Counter(lines), set()
    for ln in lines:
        if ln in seen_lines:
            continue
        seen_lines.add(ln)
        n = cnt[ln]
        if n > 1:
            ln = ln.replace("': ", f"' ({n} such elements): ", 1) if "': " in ln else ln + f' ({n} such elements)'
        out_lines.append(ln)
    return out_lines


# --------------------------------------------------------------------------- views
def majority_storey(model, guids):
    c = collections.Counter()
    obj = {}
    for g in guids:
        e = P.by_guid(model, g)
        if e is None:
            continue
        s = e if e.is_a('IfcBuildingStorey') else P.storey_of(e)
        if s is not None:
            c[s.GlobalId] += 1
            obj[s.GlobalId] = s
    if not c:
        return None
    return obj[c.most_common(1)[0][0]]


def render_case(case, rec, cache):
    t0 = time.time()
    lab = case['label']
    d = os.path.join(OUT, lab)
    os.makedirs(d, exist_ok=True)
    src = cache.source(ROOT + rec['input_ifc'])
    out = P.open_model(os.path.join(OUTPUTS, lab + '.ifc.gz'))
    fl = json.load(open(os.path.join(OUTPUTS, 'fetch_log.json')))[lab]
    same = bool(fl.get('unchanged'))
    D = diff_models(src, out) if not same else dict(added=[], removed=[], modified=[], edges_added=[],
                                                     edges_removed=[], n_shared=None)
    t_diff = time.time() - t0
    drawable = lambda model, gs: [g for g in gs if P.by_guid(model, g) is not None
                                  and getattr(P.by_guid(model, g), 'Representation', None) is not None]
    red_b = drawable(src, D['modified'] + D['removed'])
    red_a = drawable(out, D['modified'] + D['added'])
    removed = drawable(src, D['removed'])
    st_b = majority_storey(src, red_b) if red_b else None
    st_a = majority_storey(out, red_a) if red_a else None
    if st_a is None and st_b is not None:
        st_a = P.by_guid(out, st_b.GlobalId)
    if st_b is None and st_a is not None:
        st_b = P.by_guid(src, st_a.GlobalId)
    if st_b is None:          # nothing changed: the storey the request is about
        gold = P.open_model(RT.gold_path(rec['task_id'], rec))
        S = RT.plan_sets(rec, src, gold)
        st = S['st_before']
        st_b = st
        st_a = P.by_guid(out, st.GlobalId) if st is not None else None
        anchor = [g for g in S['before_red'] if P.by_guid(src, g) is not None]
        if not anchor and S['after_red']:
            anchor = []
        del gold
    else:
        anchor = []
    if st_b is None or st_a is None:
        raise RuntimeError('no storey found')
    ment_src = RT.mentioned(rec, src)
    ment_out = RT.mentioned(rec, out)
    ms_b, fp_b = cache.storey_meshes(st_b, extra=red_b)
    els_a = P.storey_elements(out, st_a, extra=red_a)
    ms_a = P.tessellate(out, list(els_a.values()))
    fp_a = P.footprints(ms_a)
    red_b_on = [g for g in red_b if g in fp_b and (P.storey_of(src.by_guid(g)) or st_b).GlobalId == st_b.GlobalId]
    red_a_on = [g for g in red_a if g in fp_a and (P.storey_of(out.by_guid(g)) or st_a).GlobalId == st_a.GlobalId]
    removed_fp = {g: fp_b[g] for g in removed if g in fp_b and g in red_b_on}
    core = RT.union_bounds(RT.bounds([fp_b.get(g) for g in red_b_on]), RT.bounds([fp_a.get(g) for g in red_a_on]))
    core = RT.union_bounds(core, RT.bounds(removed_fp.values()))
    near = []
    if core is None:
        # nothing changed on this storey: frame the element the request names, else the storey's walls
        foc = [fp_b[g] for g in anchor if g in fp_b] + [fp_b[g] for g in ment_src if g in fp_b]
        core = RT.bounds(foc) if foc else None
        if core is None:
            core = RT.bounds([fp_b[g] for g in fp_b if ms_b[g]['cls'].startswith(P.WALL_CLASSES)]) or RT.bounds(fp_b.values())
            if core is not None:
                cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
                core = (cx - 10, cy - 8, cx + 10, cy + 8) if (core[2] - core[0]) > 40 else core
    lab_b, lab_a = [], []
    for g, txt in ment_src.items():
        if g in fp_b:
            near.append(fp_b[g])
            lab_b.append((g, RT.wrap_label(txt)))
    for g, txt in ment_out.items():
        if g in fp_a:
            lab_a.append((g, RT.wrap_label(txt)))
    # changed elements carry their name when there are at most three of them in the view
    if len(red_b_on) <= 3:
        lab_b += [(g, RT.wrap_label(ms_b[g]['name'])) for g in red_b_on if ms_b.get(g, {}).get('name') and g not in ment_src]
    if len(red_a_on) <= 3:
        lab_a += [(g, RT.wrap_label(ms_a[g]['name'])) for g in red_a_on if ms_a.get(g, {}).get('name') and g not in ment_out]
    lab_b = list({g: (g, t) for g, t in lab_b}.values())
    lab_a = list({g: (g, t) for g, t in lab_a}.values())
    if core is not None:
        from shapely.geometry import box as sbox
        from shapely.ops import nearest_points
        cb = sbox(*core)
        for fp in near:
            if fp.distance(cb) < 30:
                q = nearest_points(fp, cb)[0]
                core = RT.union_bounds(core, (q.x - 1.5, q.y - 1.5, q.x + 1.5, q.y + 1.5))
    window = P.fit_window(core, RT.ASPECT)

    def stitle(st):
        nm = st.Name or '(unnamed storey)'
        t = f"Storey '{nm}'"
        if st.GlobalId in rec['instruction']:
            t += f' (ID {st.GlobalId})'
        return t
    # removed elements are red (solid) in BEFORE and dashed red in AFTER
    P.plan_view(os.path.join(d, 'before_plan.png'), fp_b, ms_b, window, 'BEFORE: ' + stitle(st_b),
                red_solid=red_b_on, labels=lab_b)
    ghosts = {}
    for g in red_b_on:
        if g in fp_a and g in fp_b and fp_b[g].symmetric_difference(fp_a[g]).area > 0.02 * max(fp_b[g].area, 0.05):
            gd = fp_b[g].difference(fp_a[g])
            if not gd.is_empty and gd.area > 1e-3:
                ghosts[g] = gd
    P.plan_view(os.path.join(d, 'after_plan.png'), fp_a, ms_a, window, 'AFTER: ' + stitle(st_a),
                red_solid=red_a_on, red_dashed=removed_fp, labels=lab_a, ghosts=ghosts)
    cache_s, cache_o = {g: ms_b[g] for g in ms_b}, {g: ms_a[g] for g in ms_a}
    ment_all = dict(ment_src, **ment_out)
    lines = facts(D, src, out, rec, ment_all, st_a, cache_s, cache_o, same)
    elev = render_elevation(d, src, out, D, red_b, red_a, cache_s, cache_o)
    view = dict(label=lab, task_id=rec['task_id'], storey_before=st_b.Name, storey_after=st_a.Name,
                red_before=red_b, red_after=red_a, red_before_drawn=red_b_on, red_after_drawn=red_a_on,
                removed=D['removed'], added=D['added'], modified=D['modified'],
                n_edges_added=len(D['edges_added']), n_edges_removed=len(D['edges_removed']),
                ghosts=list(ghosts), window=[round(v, 2) for v in window], unchanged_file=same,
                labels_before=[t for _, t in lab_b], labels_after=[t for _, t in lab_a], facts=lines,
                elevation=elev, seconds=round(time.time() - t0, 1), diff_seconds=round(t_diff, 1))
    json.dump(view, open(os.path.join(d, 'view.json'), 'w'), indent=1, ensure_ascii=False)
    return view


def placeholder(path, title, text):
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(3.35, 1.45), dpi=150)
    fig.text(0.5, 0.92, title, ha='center', va='center', fontsize=6.5)
    fig.text(0.5, 0.45, text, ha='center', va='center', fontsize=6.5)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def render_elevation(d, src, out, D, red_b, red_a, cache_s, cache_o):
    """Face-on view of the host wall of a changed door or window, or of a wall whose height changed."""
    is_fill = lambda e: e is not None and (e.is_a('IfcDoor') or e.is_a('IfcWindow'))
    fa = [g for g in red_a if is_fill(P.by_guid(out, g))]
    fb = [g for g in red_b if is_fill(P.by_guid(src, g))]
    wall_h = None
    if not fa and not fb:
        for g in D['modified']:
            a, b = src.by_guid(g), out.by_guid(g)
            if a.is_a('IfcWall') and b is not None:
                ma, mb = mesh_of(src, a, cache_s), mesh_of(out, b, cache_o)
                if ma is not None and mb is not None and abs(np.ptp(ma['verts'][:, 2]) - np.ptp(mb['verts'][:, 2])) > 0.005:
                    wall_h = g
                    break
        if wall_h is None:
            return None
        wb, wa = src.by_guid(wall_h), out.by_guid(wall_h)
        mark_b = mark_a = None
    else:
        mark_a = fa[0] if fa else None
        mark_b = (mark_a if mark_a in fb else None) or (fb[0] if fb else None)
        if mark_a is None and mark_b in red_a:
            mark_a = mark_b
        wb = P.host_of(src.by_guid(mark_b)) if mark_b else None
        wa = P.host_of(out.by_guid(mark_a)) if mark_a else None
        if wa is None and wb is not None:
            wa = P.by_guid(out, wb.GlobalId)
        if wb is None and wa is not None:
            wb = P.by_guid(src, wa.GlobalId)
    if wb is None and wa is not None:
        placeholder(os.path.join(d, 'before_elev.png'), 'BEFORE: wall seen face-on',
                    'This wall does not exist in the BEFORE model.')
        res = {'before': {'wall': None, 'note': 'wall absent'}}
        tags = (('after', out, wa, mark_a, set(red_a)),)
    elif wb is None or wa is None:
        return {'skipped': 'no host wall in one of the models'}
    else:
        res = {}
        tags = (('before', src, wb, mark_b, set(red_b)), ('after', out, wa, mark_a, set(red_a)))
    for tag, model, wall, mark, red in tags:
        wm = P.tessellate(model, [wall]).get(wall.GlobalId)
        if wm is None:
            return {'skipped': 'host wall has no geometry'}
        axis = P.wall_axis(wall)
        fills = []
        for rel in getattr(wall, 'HasOpenings', None) or []:
            for fr in rel.RelatedOpeningElement.HasFillings or []:
                fills.append(fr.RelatedBuildingElement)
        fm = P.tessellate(model, fills)
        dashed = None
        if tag == 'after':
            srcw = P.by_guid(src, wall.GlobalId)
            on_this = set()
            if srcw is not None:
                for rel in getattr(srcw, 'HasOpenings', None) or []:
                    for fr in rel.RelatedOpeningElement.HasFillings or []:
                        on_this.add(fr.RelatedBuildingElement.GlobalId)
            gone = [g for g in on_this if g not in fm and (g in D['removed'] or g in D['modified'])]
            dashed = {}
            for g in gone:
                e = src.by_guid(g)
                mm = P.tessellate(src, [e]).get(g)
                if mm is not None:
                    dashed[g] = mm
        foc = None
        if mark in fm:
            q = fm[mark]['verts'] @ axis - float((wm['verts'] @ axis).min())
            foc = (float(q.min()), float(q.max()))
        title = ('BEFORE' if tag == 'before' else 'AFTER') + ': wall seen face-on\n' + \
            (f"'{wall.Name}'" if wall.Name else '(unnamed wall)')
        P.elevation_view(os.path.join(d, f'{tag}_elev.png'), wm, axis, fm, red_solid=red, red_dashed=dashed,
                         mark=mark if mark in fm else None, wall_height_mark=wall_h is not None, title=title,
                         red_wall=(wall_h is not None), focus=foc)
        res[tag] = dict(wall=wall.GlobalId, mark=mark if mark in fm else None, n_fillings=len(fm),
                        dashed=list(dashed or {}))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--part', type=int, default=0)
    ap.add_argument('--parts', type=int, default=1)
    ap.add_argument('--resume', action='store_true', help='skip cases whose view.json exists')
    a = ap.parse_args()
    draw = json.load(open(os.path.join(HERE, 'draw.json')))
    cases = draw['audit_cases']
    if a.only:
        sel = set(a.only.split(','))
        cases = [c for c in cases if c['label'] in sel]
    tasks = {}
    want = {c['task_id'] for c in cases}
    for line in open(ROOT + 'runs_local/bench_v4/tasks.v4c.jsonl'):
        r = json.loads(line)
        if r['task_id'] in want:
            tasks[r['task_id']] = r
    # parts split by source model (heaviest first), so each worker keeps one model open at a time
    load = collections.Counter(tasks[c['task_id']]['input_ifc'] for c in cases)
    part_of, size = {}, [0] * a.parts
    for mdl, n in sorted(load.items(), key=lambda x: (-x[1], x[0])):
        k = min(range(a.parts), key=lambda i: size[i])
        part_of[mdl] = k
        size[k] += n
    cases = [c for c in cases if part_of[tasks[c['task_id']]['input_ifc']] == a.part]
    cases.sort(key=lambda c: (tasks[c['task_id']]['input_ifc'], c['label']))
    if a.resume:
        cases = [c for c in cases if not os.path.exists(os.path.join(OUT, c['label'], 'view.json'))]
    cache = RT.Cache()
    logp = os.path.join(HERE, 'render_audit_log.jsonl')
    for c in cases:
        try:
            v = render_case(c, tasks[c['task_id']], cache)
            row = {'label': c['label'], 'task_id': c['task_id'], 'ok': True, 'seconds': v['seconds'],
                   'diff_seconds': v['diff_seconds'], 'n_added': len(v['added']), 'n_removed': len(v['removed']),
                   'n_modified': len(v['modified']), 'red_after_drawn': len(v['red_after_drawn']),
                   'red_before_drawn': len(v['red_before_drawn']),
                   'elevation': bool(v['elevation'] and 'skipped' not in v['elevation'])}
        except Exception as e:
            row = {'label': c['label'], 'task_id': c['task_id'], 'ok': False, 'error': repr(e)[:400],
                   'trace': traceback.format_exc()[-1500:]}
        print(json.dumps(row), flush=True)
        with open(logp, 'a') as f:
            f.write(json.dumps(row) + '\n')


if __name__ == '__main__':
    main()
