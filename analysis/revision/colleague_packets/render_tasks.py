"""Render BEFORE / AFTER plan views (and host-wall elevations) for the rewrite tasks (packet A).

The AFTER view is the task's ground-truth model. Inputs: draw.json (sample_tasks.py, rewrite_blocks), runs_local/bench_v4/tasks.v4c.jsonl, the source models
(read-only, data/corpus/...) and the ground-truth models (runs_local/bench_v4/models_v4c,
models_v4b, models; *.ifc.gz). Gold bytes are checked against the task's recorded sha256.
Outputs under renders/<label>/: before_plan.png, after_plan.png, and for door, window and
wall-height edits before_elev.png, after_elev.png; renders/<label>/view.json (what was drawn);
render_log.jsonl (one line per task, with timing and any failure).
Run: OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONPATH=code \
     taskset -c 16-23 <l2 python> render_tasks.py [--only R1-01,R2-05] [--part 0 --parts 4]
"""
import argparse, gzip, hashlib, json, os, re, sys, time, traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import plan_render as P  # noqa: E402
import change_note as CN  # noqa: E402

ROOT = ''
B4 = ROOT + 'runs_local/bench_v4/'
OUT = os.path.join(HERE, 'renders')
GID = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")
QUOTED = re.compile(r"'([^']{2,200})'")
ASPECT = (0.98 * 3.35) / (0.88 * 2.95)


def labels_of(draw):
    """Rewrite task labels: R<block>-<position>, e.g. R3-17."""
    out = {}
    for b, ids in enumerate(draw['rewrite_blocks']):
        for i, t in enumerate(ids):
            out[t] = f'R{b + 1}-{i + 1:02d}'
    return out


def gold_path(tid, rec=None):
    if rec is not None:                      # the file the task record names, first
        for p in (ROOT + rec['ground_truth_ifc'], ROOT + rec['ground_truth_ifc'] + '.gz'):
            if os.path.exists(p):
                return p
    for d in ('models_v4c', 'models_v4b', 'models'):
        p = os.path.join(B4, d, tid + '.ifc.gz')
        if os.path.exists(p):
            return p
    raise FileNotFoundError(tid)


def gold_sha_ok(path, rec):
    want = (rec.get('verification') or {}).get('gold_sha256')
    with gzip.open(path, 'rb') as f:
        got = hashlib.sha256(f.read()).hexdigest()
    return want == got, got, want


def products(model, guids):
    out = []
    for g in guids:
        e = P.by_guid(model, g)
        if e is not None and e.is_a('IfcProduct') and not e.is_a('IfcOpeningElement') \
                and not e.is_a('IfcSpatialStructureElement') or (e is not None and e.is_a('IfcSpace')):
            out.append(g)
    return out


def element_word(cls):
    for k, w in (('IfcWall', 'wall'), ('IfcCurtainWall', 'curtain wall'), ('IfcSlab', 'slab'),
                 ('IfcColumn', 'column'), ('IfcDoor', 'door'), ('IfcWindow', 'window'), ('IfcSpace', 'space'),
                 ('IfcBeam', 'beam'), ('IfcStair', 'stair')):
        if cls.startswith(k):
            return w
    return 'element'


class Cache:
    """Keeps one source model open and its storey tessellations."""
    def __init__(self):
        self.path = None
        self.model = None
        self.storeys = {}

    def source(self, path):
        if path != self.path:
            self.model = None
            self.storeys = {}
            self.model = P.open_model(path)
            self.path = path
        return self.model

    def storey_meshes(self, storey, extra=()):
        k = storey.GlobalId
        if k not in self.storeys:
            els = P.storey_elements(self.model, storey)
            ms = P.tessellate(self.model, list(els.values()))
            self.storeys[k] = (ms, P.footprints(ms))
        ms, fps = self.storeys[k]
        miss = [g for g in extra if g not in ms]
        if miss:
            es = [P.by_guid(self.model, g) for g in miss]
            m2 = P.tessellate(self.model, [e for e in es if e is not None])
            ms = dict(ms, **m2)
            fps = dict(fps, **P.footprints(m2))
        return ms, fps


def storey_for(model, guids):
    for g in guids:
        e = P.by_guid(model, g)
        if e is None:
            continue
        if e.is_a('IfcBuildingStorey'):
            return e
        s = P.storey_of(e)
        if s is not None:
            return s
    return None


def plan_sets(rec, src, gold):
    """Which elements are red in each view, and the storeys to show."""
    eg = rec['edit_guids']
    op = rec['operation']
    if rec['clarification']:
        exp = [g for g in rec['anchor'].get('expected') or []]
        tg = products(src, exp)
        st = storey_for(src, exp)
        return dict(before_red=tg, after_red=tg, removed=[], st_before=st, st_after=st, anchor_storey=st)
    removed = products(src, eg.get('removed') or [])
    targets = list(dict.fromkeys((eg.get('target') or []) + (eg.get('created') or [])))
    after_red = products(gold, targets)
    before_red = [] if op == 'create' else products(src, eg.get('target') or [])
    before_red = list(dict.fromkeys(before_red + removed))
    st_b = storey_for(src, before_red) if before_red else None
    st_a = storey_for(gold, after_red) if after_red else None
    if st_b is None and st_a is not None:
        st_b = P.by_guid(src, st_a.GlobalId)
    if st_a is None and st_b is not None:
        st_a = P.by_guid(gold, st_b.GlobalId)
    if st_b is None:          # e.g. a storey named in edit_params
        sg = rec['edit_params'].get('storey_guid')
        if sg:
            st_b, st_a = P.by_guid(src, sg), P.by_guid(gold, sg)
    return dict(before_red=before_red, after_red=after_red, removed=removed, st_before=st_b, st_after=st_a)


def bounds(geoms):
    gs = [g for g in geoms if g is not None and not g.is_empty]
    if not gs:
        return None
    b = np.array([g.bounds for g in gs])
    return b[:, 0].min(), b[:, 1].min(), b[:, 2].max(), b[:, 3].max()


def union_bounds(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def mentioned(rec, model):
    """Elements and storeys the instruction names, as {GlobalId: text as written}."""
    text = rec['instruction']
    out = {}
    for g in GID.findall(text):
        e = P.by_guid(model, g)
        if e is not None:
            out[g] = g
    for q in QUOTED.findall(text):
        if GID.fullmatch(q):
            continue
        for cls in ('IfcBuildingStorey',) + P.DRAW_CLASSES:
            try:
                for e in model.by_type(cls):
                    if (e.Name or '') == q:
                        out[e.GlobalId] = q
            except RuntimeError:
                pass
    return out


def wrap_label(t, n=34):
    if len(t) <= n:
        return t
    parts, cur = [], ''
    for tok in re.split(r'(?<=[:\s_-])', t):
        if len(cur) + len(tok) > n and cur:
            parts.append(cur)
            cur = tok
        else:
            cur += tok
    parts.append(cur)
    return '\n'.join(p.strip() for p in parts)


def group_labels(labs, reds):
    """Three or more changed elements: one label listing their names, on the first of them."""
    rl = [(g, t) for g, t in labs if g in reds]
    if len(rl) < 3:
        return labs
    names = [t.replace('\n', '') for _, t in rl]
    text = wrap_label(', '.join(names), 40)
    return [(g, t) for g, t in labs if g not in reds] + [(rl[0][0], text)]


def render_task(label, rec, cache, kind):
    t0 = time.time()
    d = os.path.join(OUT, label)
    os.makedirs(d, exist_ok=True)
    gp = gold_path(rec['task_id'], rec)
    ok, got, want = gold_sha_ok(gp, rec)
    src = cache.source(ROOT + rec['input_ifc'])
    gold = P.open_model(gp)
    S = plan_sets(rec, src, gold)
    if S['st_before'] is None or S['st_after'] is None:
        raise RuntimeError('no storey found for the target')
    ment_src = mentioned(rec, src)
    ment_gold = mentioned(rec, gold)
    # BEFORE meshes (cached per storey), AFTER meshes: same storey elements from the gold model
    ms_b, fp_b = cache.storey_meshes(S['st_before'], extra=[g for g in S['before_red'] + S['removed']])
    # mentioned reference elements on other storeys are not drawn; they are named in the title only
    els_a = P.storey_elements(gold, S['st_after'], extra=S['after_red'])
    ms_a = P.tessellate(gold, list(els_a.values()))
    fp_a = P.footprints(ms_a)
    removed_fp = {g: fp_b[g] for g in S['removed'] if g in fp_b}
    # window: the changed elements in both views, plus named elements within 30 m
    core = union_bounds(bounds([fp_b.get(g) for g in S['before_red']]), bounds([fp_a.get(g) for g in S['after_red']]))
    core = union_bounds(core, bounds(removed_fp.values()))
    if core is None:
        # nothing red to frame (an under-specified create): frame the storey's walls
        core = bounds([fp_b[g] for g in fp_b if ms_b[g]['cls'].startswith(P.WALL_CLASSES)]) or bounds(fp_b.values())
        if core is not None:
            cx, cy = (core[0] + core[2]) / 2, (core[1] + core[3]) / 2
            core = (cx - 10, cy - 8, cx + 10, cy + 8) if (core[2] - core[0]) > 40 else core
    lab_b, lab_a = [], []
    near = []
    if kind == 'audit':
        for g, txt in ment_src.items():
            if g in fp_b:
                near.append(fp_b[g])
                lab_b.append((g, wrap_label(txt)))
        for g, txt in ment_gold.items():
            if g in fp_a:
                lab_a.append((g, wrap_label(txt)))
    else:
        ep_ref = {k: v for k, v in rec['edit_params'].items() if k not in ('batch_pool', 'batch_members')}
        refs = [rec['anchor'].get('params', {}).get('reference_guid')] + \
            list(GID.findall(json.dumps(rec['anchor'].get('params', {})))) + list(GID.findall(json.dumps(ep_ref)))
        refs = [g for g in dict.fromkeys(refs) if g and not (P.by_guid(src, g) is not None
                                                            and P.by_guid(src, g).is_a('IfcSpatialStructureElement')
                                                            and not P.by_guid(src, g).is_a('IfcSpace'))]
        for g in refs + S['before_red']:
            if g in fp_b and ms_b[g]['name']:
                if g in refs:
                    near.append(fp_b[g])
                lab_b.append((g, wrap_label(ms_b[g]['name'])))
        for g in refs + S['after_red']:
            if g in ms_a and ms_a[g]['name'] and g in fp_a:
                lab_a.append((g, wrap_label(ms_a[g]['name'])))
    lab_b = list({g: (g, t) for g, t in lab_b}.values())
    lab_a = list({g: (g, t) for g, t in lab_a}.values())
    lab_b, lab_a = group_labels(lab_b, S['before_red']), group_labels(lab_a, S['after_red'])
    if core is not None:
        from shapely.geometry import box as sbox
        from shapely.ops import nearest_points
        cb = sbox(*core)
        for fp in near:
            if fp.distance(cb) < 30:
                q = nearest_points(fp, cb)[0]
                core = union_bounds(core, (q.x - 1.5, q.y - 1.5, q.x + 1.5, q.y + 1.5))
    window = P.fit_window(core, ASPECT)
    # titles: storey name; in the audit packet also its ID when the instruction uses the ID
    def stitle(st):
        nm = st.Name or '(unnamed storey)'
        t = f"Storey '{nm}'"
        if kind == 'audit' and st.GlobalId in rec['instruction']:
            t += f' (ID {st.GlobalId})'
        return t
    tb, ta = 'BEFORE: ' + stitle(S['st_before']), 'AFTER: ' + stitle(S['st_after'])
    foot_b, foot_a = CN.property_lines(rec, src, gold, S, ms_b, ms_a)
    if foot_b or foot_a:
        import textwrap
        wb = textwrap.wrap(foot_b or '', 72) or ['']
        wa = textwrap.wrap(foot_a or '', 72) or ['']
        n = max(len(wb), len(wa))
        foot_b = '\n'.join(wb + [''] * (n - len(wb)))
        foot_a = '\n'.join(wa + [''] * (n - len(wa)))
    P.plan_view(os.path.join(d, 'before_plan.png'), fp_b, ms_b, window, tb, red_solid=S['before_red'],
                labels=lab_b, footer=foot_b)
    ghosts = {}
    if rec['operation'] == 'update' and not rec['clarification']:
        for g in S['before_red']:
            if g in fp_b and g in fp_a and fp_b[g].symmetric_difference(fp_a[g]).area > 0.02 * max(fp_b[g].area, 0.05):
                gd = fp_b[g].difference(fp_a[g])
                if not gd.is_empty and gd.area > 1e-3:
                    ghosts[g] = gd
    P.plan_view(os.path.join(d, 'after_plan.png'), fp_a, ms_a, window, ta, red_solid=S['after_red'],
                red_dashed=removed_fp, labels=lab_a, ghosts=ghosts, footer=foot_a)
    view = dict(label=label, task_id=rec['task_id'], storey_before=S['st_before'].Name,
                storey_after=S['st_after'].Name, before_red=S['before_red'], after_red=S['after_red'],
                removed=S['removed'], ghosts=list(ghosts), footer_before=foot_b, footer_after=foot_a, window=[round(v, 2) for v in window], gold=os.path.relpath(gp, ROOT),
                gold_sha256_match=ok, labels_before=[t for _, t in lab_b], labels_after=[t for _, t in lab_a],
                after_red_drawn=[g for g in S['after_red'] if g in fp_a],
                before_red_drawn=[g for g in S['before_red'] if g in fp_b])
    view['elevation'] = render_elevation(d, rec, src, gold, S, ms_b, ms_a)
    view['note'] = '' if rec['clarification'] else CN.note(rec, src, gold, S)
    view['note_has_id'] = bool(GID.search(view['note']))
    view['seconds'] = round(time.time() - t0, 1)
    json.dump(view, open(os.path.join(d, 'view.json'), 'w'), indent=1, ensure_ascii=False)
    return view


def render_elevation(d, rec, src, gold, S, ms_b, ms_a):
    fam = rec['family'] if not rec['clarification'] else None
    ek = rec['edit_kind']
    ep = rec['edit_params']
    wall_h = (fam == 'wall' and ek.startswith('resize') and 'height' in str(ep.get('dimension', '')))
    if fam not in ('door', 'window') and not wall_h:
        return None
    if wall_h:
        g = (S['before_red'] or S['after_red'])[0]
        wb, wa = P.by_guid(src, g), P.by_guid(gold, g)
        mark_b = mark_a = None
    else:
        fb = [g for g in S['before_red'] if P.by_guid(src, g) is not None and P.by_guid(src, g).is_a() in ('IfcDoor', 'IfcWindow', 'IfcDoorStandardCase', 'IfcWindowStandardCase')]
        fa = [g for g in S['after_red'] if P.by_guid(gold, g) is not None and P.by_guid(gold, g).is_a() in ('IfcDoor', 'IfcWindow', 'IfcDoorStandardCase', 'IfcWindowStandardCase')]
        mark_b = fb[0] if fb else None
        mark_a = fa[0] if fa else None
        wb = P.host_of(P.by_guid(src, mark_b)) if mark_b else None
        wa = P.host_of(P.by_guid(gold, mark_a)) if mark_a else None
        hg = ep.get('host_guid') or ep.get('host_to_guid')
        if wa is None and wb is not None:
            wa = P.by_guid(gold, wb.GlobalId)
        if wb is None:
            hb = ep.get('host_from_guid') or ep.get('host_guid') or (wa.GlobalId if wa is not None else None)
            wb = P.by_guid(src, hb) if hb else None
        if wa is None and hg:
            wa = P.by_guid(gold, hg)
    if wb is None or wa is None:
        return {'skipped': 'no host wall'}
    out = {}
    def mark_span(model, wall, mark, other_mesh=None):
        if mark is None and other_mesh is None:
            return None
        wm = P.tessellate(model, [wall]).get(wall.GlobalId)
        if wm is None:
            return None
        axis = P.wall_axis(wall)
        s0 = float((wm['verts'] @ axis).min())
        m = other_mesh if other_mesh is not None else P.tessellate(model, [P.by_guid(model, mark)]).get(mark)
        if m is None:
            return None
        q = m['verts'] @ axis - s0
        return float(q.min()), float(q.max())
    foc_b = mark_span(src, wb, mark_b)
    foc_a = mark_span(gold, wa, mark_a)
    if wb.GlobalId == wa.GlobalId:
        foc_b = foc_b or foc_a
        foc_a = foc_a or foc_b
    for tag, model, wall, mark, foc in (('before', src, wb, mark_b, foc_b), ('after', gold, wa, mark_a, foc_a)):
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
            gone = [g for g in S['removed'] if g in ms_b and ms_b[g]['cls'].startswith(('IfcDoor', 'IfcWindow'))]
            srcw = P.by_guid(src, wall.GlobalId)
            on_this = set()
            if srcw is not None:
                for rel in getattr(srcw, 'HasOpenings', None) or []:
                    for fr in rel.RelatedOpeningElement.HasFillings or []:
                        on_this.add(fr.RelatedBuildingElement.GlobalId)
            dashed = {g: ms_b[g] for g in gone if g in on_this}
        red = set(S['before_red'] if tag == 'before' else S['after_red'])
        mk = mark if mark in fm else None
        title = ('BEFORE' if tag == 'before' else 'AFTER') + ': wall seen face-on\n' + \
            (f"'{wall.Name}'" if wall.Name else '(unnamed wall)')
        P.elevation_view(os.path.join(d, f'{tag}_elev.png'), wm, axis, fm, red_solid=red, red_dashed=dashed,
                         mark=mk, wall_height_mark=wall_h, title=title,
                         red_wall=(wall_h and wall.GlobalId in red), focus=foc)
        out[tag] = dict(wall=wall.GlobalId, mark=mk, n_fillings=len(fm), dashed=list(dashed or {}))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--only', default='')
    ap.add_argument('--part', type=int, default=0)
    ap.add_argument('--parts', type=int, default=1)
    ap.add_argument('--resume', action='store_true', help='skip cases whose view.json exists')
    a = ap.parse_args()
    draw = json.load(open(os.path.join(HERE, 'draw.json')))
    lab = labels_of(draw)
    want = set(lab)
    recs = {}
    for line in open(B4 + 'tasks.v4c.jsonl'):
        r = json.loads(line)
        if r['task_id'] in want:
            recs[r['task_id']] = r
    todo = sorted(want)
    if a.only:
        sel = set(a.only.split(','))
        todo = [t for t in todo if lab[t] in sel or t in sel]
    # parts split by source model, so each worker keeps one model open at a time
    models = sorted({recs[t]['input_ifc'] for t in todo})
    load = {mdl: sum(1 for t in todo if recs[t]['input_ifc'] == mdl) for mdl in models}
    part_of, size = {}, [0] * a.parts
    for mdl in sorted(models, key=lambda x: -load[x]):
        k = min(range(a.parts), key=lambda i: size[i])
        part_of[mdl] = k
        size[k] += load[mdl]
    todo = [t for t in todo if part_of[recs[t]['input_ifc']] == a.part]
    todo.sort(key=lambda t: (recs[t]['input_ifc'], lab[t]))      # one source model open at a time
    if a.resume:
        todo = [t for t in todo if not os.path.exists(os.path.join(OUT, lab[t], 'view.json'))]
    cache = Cache()
    logp = os.path.join(HERE, 'render_log.jsonl')
    for t in todo:
        try:
            v = render_task(lab[t], recs[t], cache, 'rewrite')
            row = {'label': lab[t], 'task_id': t, 'ok': True, 'seconds': v['seconds'],
                   'gold_sha256_match': v['gold_sha256_match'],
                   'after_red_drawn': len(v['after_red_drawn']), 'before_red_drawn': len(v['before_red_drawn']),
                   'elevation': bool(v['elevation'] and 'skipped' not in v['elevation'])}
        except Exception as e:
            row = {'label': lab[t], 'task_id': t, 'ok': False, 'error': repr(e)[:400],
                   'trace': traceback.format_exc()[-1500:]}
        print(json.dumps(row), flush=True)
        with open(logp, 'a') as f:
            f.write(json.dumps(row) + '\n')


if __name__ == '__main__':
    main()
