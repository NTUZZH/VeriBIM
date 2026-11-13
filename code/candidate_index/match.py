#!/usr/bin/env python
"""Rank the indexed elements of one IFC file against a change request, deterministically.

Scoring scheme (points add up; ties are broken by GlobalId, ascending):
1. Direct identification D (an element with D >= 30 is an anchor, of weight w = D / 100):
   GlobalId written in the text 100; full Name (or a space's LongName) written in the text 80 when unique among the
   file's products, 40 + 40 / n when n products share it (a name shorter than three characters only when quoted); authoring-tool number (trailing ':NNNN' of the Name, or the
   Tag) written as a separate number 60 when unique, 30 when shared. Matched names, GlobalIds and quoted storey names
   are blanked out of the text before steps 2 to 4, so the words inside a name do not count again.
2. Class words (synonyms in CLASS_WORDS, plus literal 'IfcXxx'): the class named first gets 20, every other class
   named gets 10. When the text names any class, steps 3 and 4 only reward elements of a named class ("gate").
   Storey: an element on a storey the text names (GlobalId, quoted or plain name, 'level N' / 'Nth floor', 'ground
   floor', 'basement') gets 10.
3. Relations from each anchor a (points times w): host wall of a filling or opening and the fillings and openings of
   a host 30; elements connected to a 20 (6 when the text has no connect word); space boundary in either direction 15;
   elements inside an anchor room 15, beside it 10 (an anchor element's own room 10); aggregate parent or part 15.
   Geometry, only when the text asks for it: 'near/nearest/closest/next to/beside' gives the five gated elements with
   the smallest box gap to a 25/18/12/8/5; 'above/over/below/under/beneath' gives the three gated elements stacked on
   a (plan overlap) 25/18/12; '<d> m <compass word or +-X/Y> of' gives the three gated elements closest to a's centre
   plus that offset 30/20/12 (one direction: gap between the element's box and the line at distance d, plus 0.25 x the
   sideways gap between the two boxes, within max(1 m, d/4) and max(3 m, d/2); two directions: centre distance to the
   offset point within max(2 m, 0.35 d)); 'furthest/most/...ernmost <direction>' gives the three gated
   elements furthest in that direction (on the named storeys when any) 25/15/10, without an anchor; 'between' and two
   anchors gives the three gated elements whose centre lies between the two anchor centres, closest to the line joining
   them (within max(2 m, 0.3 x their distance)), 25/18/12 times the weaker anchor's weight.
   Second step: every non-anchor element that received R >= 10 points in step 3 passes 0.6 R to its host, fillings and
   openings, and a room passes 0.4 R to its boundary elements and the elements inside it (gated).
4. Attributes of gated elements: compass word outside an offset or movement phrase and matching the element's sector
   8 (a diagonal word such as 'north-east' 5 per matching half); each length in the text (number with m, cm or mm,
   or 'A x B' pairs) within 5 percent of one of the element's box dimensions 6, at most 18; 'wider/longer/taller/
   narrower/shorter/thicker than X' satisfied 10; 'hosts no door/window' or 'no space boundary' satisfied 10; each
   word of three or more characters from the element's Name or ObjectType that appears in the remaining text 4, at
   most 12.
An element's position in steps 3 (offset, between, furthest) is its box centre or its placement origin, whichever fits
better. Quoted text that names nothing in the file (the name of a new element), 'no door' conditions and the phrase
'the opening it fills' do not count as class words, and 'above/below' right after a length ('0.9 m above') is a
dimension, not a relation. An element is a candidate when its total is at least 10. Direction words without an axis use the index convention
(IfcProject TrueNorth, else model +Y as north); '(+X)', '(-Y)' and similar follow the model axes."""
import re, sys
import numpy as np

CLASS_WORDS = [  # checked in this order; a matched span is blanked so 'curtain wall' does not also count as 'wall'
    (r'curtain[ -]?walls?', ('IfcCurtainWall',)),
    (r'doors?|doorsets?|doorways?', ('IfcDoor',)),
    (r'windows?|glazing units?|glazing', ('IfcWindow',)),
    (r'walls?|partitions?', ('IfcWall',)),
    (r'slabs?|decks?', ('IfcSlab',)),
    (r'roofs?', ('IfcRoof', 'IfcSlab')),
    (r'columns?|posts?|pillars?|piers?', ('IfcColumn',)),
    (r'beams?|girders?|joists?|lintels?', ('IfcBeam',)),
    (r'spaces?|rooms?', ('IfcSpace',)),
    (r'openings?|holes?|voids?|penetrations?', ('IfcOpeningElement',)),
    (r'stair ?flights?|stairs?|staircases?|stairways?|steps', ('IfcStair',)),
    (r'railings?|handrails?|guardrails?|balustrades?', ('IfcRailing',)),
    (r'furniture|furnishings?|desks?|chairs?|tables?|sofas?|beds?|cabinets?|wardrobes?', ('IfcFurnishingElement', 'IfcFurniture')),
    (r'coverings?|ceilings?|claddings?', ('IfcCovering',)),
    (r'members?|mullions?|transoms?', ('IfcMember',)),
    (r'plates?|panels?', ('IfcPlate',)),
    (r'footings?|foundations?', ('IfcFooting',)),
    (r'ramps?', ('IfcRamp',)),
    (r'piles?', ('IfcPile',)),
]
STOP = {'the', 'and', 'with', 'from', 'that', 'this', 'for', 'into', 'its', 'new', 'one', 'all', 'mm', 'basic', 'generic',
        'type', 'standard', 'default', 'level', 'storey', 'floor', 'element', 'object', 'model'}
DIRS = {'north': (0, 1), 'south': (0, -1), 'east': (1, 0), 'west': (-1, 0)}
NUM = r'(\d+(?:\.\d+)?)'
UNIT = r'\s*(mm|cm|millimet(?:er|re)s?|met(?:er|re)s?|m)\b'
DIST = NUM + r'\s*(?:m|met(?:er|re)s?)\s+(?:to the\s+|towards?\s+)?(north|south|east|west)\w*(?:\s*\(([+-])\s*([xy])\))?'
OFFSET = re.compile(DIST + r'(?:\s*,?\s*and\s+' + DIST + r')?\s+(?:of|from)\b', re.I)
MOVE = re.compile(DIST, re.I)
EXTREME = re.compile(r'\b(?:furthest|farthest|most|extreme)\s+(?:to the\s+)?(north|south|east|west)\w*(?:\s*\(([+-])\s*([xy])\))?|'
                     r'\b(north|south|east|west)ernmost\b', re.I)
COMPARE = re.compile(r'\b(wider|longer|taller|higher|narrower|shorter|lower|thicker|thinner)\s+than\s+' + NUM + UNIT, re.I)
GUID = re.compile(r'(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])')
_prep, LAST = {}, {}  # LAST keeps the score parts of the latest call, for inspection


def norm(s):
    return re.sub(r'\s+', ' ', (s or '').replace('’', "'").replace('‘', "'").replace(' ', ' '))


def prepare(idx):
    """Static lookups of one index, built once."""
    key = idx['path']
    if key in _prep:
        return _prep[key]
    E = idx['elements']
    by_g = {e['g']: i for i, e in enumerate(E)}
    names, nums = {}, {}
    for i, e in enumerate(E):
        for n in {norm(e['n']), norm(e['ln'])} - {''}:
            names.setdefault(n.lower(), []).append(i)
        for n in {e['num'], e['tag'] if re.fullmatch(r'\d{4,}', e['tag'] or '') else None} - {None}:
            nums.setdefault(n, []).append(i)
    count = {n: len(set(v)) for n, v in names.items()}
    has = np.array([e['lo'] is not None for e in E])
    lo = np.array([e['lo'] or [0, 0, 0] for e in E], dtype=float).reshape(-1, 3)
    hi = np.array([e['hi'] or [0, 0, 0] for e in E], dtype=float).reshape(-1, 3)
    toks = [set(t for t in re.split(r'[^\w]+', (e['n'] + ' ' + e['ot']).lower()) if len(t) >= 3 and t not in STOP
                and not t.isdigit()) for e in E]
    inside, beside = {}, {}
    for i, e in enumerate(E):
        for g in e['rooms']:
            inside.setdefault(g, []).append(i)
        for g in e['adj']:
            beside.setdefault(g, []).append(i)
    codes = {g: k for k, g in enumerate(sorted({str(e['sg']) for e in E}))}
    cen = (lo + hi) / 2
    org = np.array([e['org'][:2] if e.get('org') else cen[i, :2] for i, e in enumerate(E)], dtype=float).reshape(-1, 2)
    p = dict(E=E, by_g=by_g, names=names, count=count, nums=nums, has=has, lo=lo, hi=hi, cen=cen, org=org, toks=toks,
             cls=[e['c'] for e in E], sg=[e['sg'] for e in E], sgc=np.array([codes[str(e['sg'])] for e in E]),
             inside=inside, beside=beside)
    _prep[key] = p
    return p


def blank(text, spans):
    t = list(text)
    for a, b in spans:
        t[a:b] = ' ' * (b - a)
    return ''.join(t)


def direction(word, sign, axis, north):
    """Unit plan vector of a compass word, or of an explicit model axis when one is written."""
    if axis:
        v = (1.0, 0.0) if axis.lower() == 'x' else (0.0, 1.0)
        return (v[0] * (1 if sign == '+' else -1), v[1] * (1 if sign == '+' else -1))
    e, n = DIRS[word.lower()]
    east = (north[1], -north[0])
    return (e * east[0] + n * north[0], e * east[1] + n * north[1])


def rank(idx, text):
    """All candidates as (score, GlobalId, element) sorted by descending score, then GlobalId."""
    p = prepare(idx)
    E, n_el = p['E'], len(p['E'])
    tx = norm(text)
    cf = tx.lower() if len(tx.lower()) == len(tx) else tx
    D = np.zeros(n_el)
    spans = []
    for m in GUID.finditer(tx):
        if m.group(0) in p['by_g']:
            D[p['by_g'][m.group(0)]] = 100
            spans.append(m.span())
        elif m.group(0) in idx['storeys']:
            spans.append(m.span())
    hits = []
    for n, ids in p['names'].items():
        if len(n) < 3 and ("'" + n + "'" in cf or '"' + n + '"' in cf):
            k = cf.find("'" + n + "'") if "'" + n + "'" in cf else cf.find('"' + n + '"')
            hits.append((k + 1, k + 1 + len(n), n))
            continue
        if len(n) < 3 or n in STOP or re.fullmatch(r'(the )?\w+s?', n) and any(re.fullmatch(w, n) for w, _ in CLASS_WORDS):
            continue
        k = cf.find(n)
        if k < 0:
            continue
        pat = (r'(?<![\w.,])' if n[0].isalnum() else '') + re.escape(n) + (r'(?![\w])' if n[-1].isalnum() else '')
        if n.replace('.', '').isdigit():
            pat += r'(?!\s*(?:mm|cm|m)\b)(?![.,]\d)'
        m = re.search(pat, cf)
        if m:
            hits.append((m.start(), m.end(), n))
    hits = [h for h in hits if not any(o[0] <= h[0] and h[1] <= o[1] and (o[1] - o[0]) > (h[1] - h[0]) for o in hits)]
    for a, b, n in hits:
        c = p['count'][n]
        for i in set(p['names'][n]):
            D[i] = max(D[i], 80 if c == 1 else 40 + 40 / c)
        spans.append((a, b))
    for m in re.finditer(r'(?<![\w$.,])(\d{4,})(?![\w$]|[.,]\d)', tx):
        ids = set(p['nums'].get(m.group(1), []))
        for i in ids:
            D[i] = max(D[i], 60 if len(ids) == 1 else 30)
    # storeys named in the text
    st_hit = set()
    for g, s in idx['storeys'].items():
        nm = norm(s['name']).lower()
        if g in tx:
            st_hit.add(g)
        elif nm and ("'" + nm + "'" in cf or '"' + nm + '"' in cf or (len(nm) >= 3 and re.search(
                r'(?<!\w)' + re.escape(nm) + r'(?!\w)', cf))):
            st_hit.add(g)
            k = cf.find(nm)
            spans.append((k, k + len(nm)))
    lv = re.findall(r'\b(?:level|floor|storey|story|etage|etasje)\s*(-?\d+)\b|\b(\d+)(?:st|nd|rd|th)\s+(?:floor|level|storey)', cf)
    for a, b in lv:
        num = (a or b).lstrip('0') or '0'
        for g, s in idx['storeys'].items():
            if re.search(r'(?<![\d.])0*' + re.escape(num) + r'(?!\d|\.\d)', s['name']):
                st_hit.add(g)
    for word, keys in (('ground', ('ground', 'eg', 'erdgeschoss', 'gf', 'level 0', 'level 00')), ('basement', ('basement', 'ug', 'kjeller', 'cellar'))):
        if re.search(r'\b' + word + r'\b', cf):
            st_hit |= {g for g, s in idx['storeys'].items() if any(re.search(r'(?<!\w)' + k + r'(?!\w)', s['name'].lower()) for k in keys)}
    rest = blank(cf, spans)
    # class words; a class written after 'new' names the element to be created, and 'no door' is a condition
    neg = [m.span() for m in re.finditer(r'\bno (?:doors?|windows?|openings?)\b(?: (?:and|or) no (?:doors?|windows?|openings?)\b)?', rest)]
    neg += [m.span() for m in re.finditer(r"(?<!\w)'[^'\n]{1,100}?'(?!\w)|\"[^\"\n]{1,100}?\"", rest)]
    neg += [m.span() for m in re.finditer(r'\b(?:the|old) openings? (?:it|they) (?:fill|fills|filled)\b', rest)]
    rest_c = blank(rest, neg)
    classes = []
    for m in sorted([(m.start(), m.end(), pref) for w, pref in CLASS_WORDS for m in re.finditer(r'\b(?:' + w + r')\b', rest_c)]
                    + [(m.start(), m.end(), ('Ifc' + m.group(1).replace('standardcase', ''),)) for m in re.finditer(r'\bifc(\w+)', rest_c)]):
        if not any(m[0] < b and a < m[1] for a, b, _ in classes) and not re.search(r'\bnew\s+(?:\w+\s+)?$', rest_c[max(0, m[0] - 20):m[0]]):
            classes.append(m)
    cls_low = [c.lower() for c in p['cls']]
    S = D.copy()
    gate = np.ones(n_el, bool)
    groups = []
    if classes:
        gate[:] = False
        cpts = np.zeros(n_el)
        for pref in dict.fromkeys(c[2] for c in classes):
            hit = np.array([any(c.startswith(x.lower()) for x in pref) for c in cls_low])
            groups.append(hit)
            gate |= hit
            cpts = np.maximum(cpts, np.where(hit, 20 if pref == classes[0][2] else 10, 0))
        S += cpts
    else:
        groups = [gate.copy()]
    S += 10 * np.array([g in st_hit for g in p['sg']])
    R = np.zeros(n_el)
    by_g, north = p['by_g'], idx['north']
    anchors = [i for i in np.argsort(-D, kind='stable') if D[i] >= 30][:40]
    connect = bool(re.search(r'connect|join|meet|abut|adjoin|attached|touch', rest))
    gidx = np.where(gate & p['has'])[0]
    lo, hi, cen = p['lo'], p['hi'], p['cen']
    def ranked(acc, pts, pool, key):
        """The first len(pts) elements of pool by ascending key, within each named class, get pts in order."""
        for hit in groups:
            sub = pool[hit[pool]]
            for k, i in enumerate(sub[np.lexsort((sub, key[hit[pool]]))][:len(pts)]):
                acc[i] = max(acc.get(i, 0), pts[k])
    spaces = [i for i in anchors if E[i]['c'] == 'IfcSpace']
    for a in anchors:
        w, e, acc = D[a] / 100, E[a], {}
        def give(g, pts):
            i = by_g.get(g, -1) if isinstance(g, str) else g
            if i >= 0 and i != a and gate[i]:
                acc[i] = max(acc.get(i, 0), pts)
        for g in e['fills'] + [e['host']] * bool(e['host']):
            give(g, 30)
        for g in e['conn']:
            give(g, 20 if connect else 6)
        for g in e['bnd']:
            give(g, 15)
        for g in e['rooms'] + e['adj'] + [e['parent']] * bool(e['parent']):
            give(g, 10 if g != e['parent'] else 15)
        for i in p['inside'].get(e['g'], []):
            give(int(i), 15)
        for i in p['beside'].get(e['g'], []):
            give(int(i), 10)
        if e['lo'] is not None and len(gidx):
            cand = gidx[gidx != a]
            same = cand[p['sgc'][cand] == p['sgc'][a]] if e['sg'] else cand
            if re.search(r'\b(near|nearest|closest|next to|beside|adjacent)\b', rest) and len(same):
                gap = np.linalg.norm(np.maximum(0, np.maximum(lo[same] - hi[a], lo[a] - hi[same])), axis=1)
                ranked(acc, [25, 18, 12, 8, 5], same, gap)
            for word, up in (('above|over|on top of', True), ('below|under|beneath|underneath', False)):
                if re.search(r'(?<!\d m )(?<!\dm )(?<!\d mm )(?<!\d metres )(?<!\d meters )\b(' + word + r')\b', rest) and len(cand):
                    ov = (np.minimum(hi[cand, 0], hi[a, 0]) > np.maximum(lo[cand, 0], lo[a, 0])) & \
                         (np.minimum(hi[cand, 1], hi[a, 1]) > np.maximum(lo[cand, 1], lo[a, 1]))
                    vg = (lo[cand, 2] - hi[a, 2]) if up else (lo[a, 2] - hi[cand, 2])
                    ok = ov & (vg > -0.5)
                    ranked(acc, [25, 18, 12], cand[ok], vg[ok])
            for m in OFFSET.finditer(rest):
                v, dist = np.zeros(2), 0.0
                for j in (0, 4):
                    if m.group(j + 1):
                        d = float(m.group(j + 1))
                        v += d * np.array(direction(m.group(j + 2), m.group(j + 3), m.group(j + 4), north))
                        dist += d
                keys = []
                for P in (cen[:, :2], p['org']):  # an element's position is its visible centre or its placement origin
                    rel = P[same] - P[a]
                    if m.group(5):  # two directions: distance to the offset point
                        dd = np.linalg.norm(rel - v, axis=1)
                        ok = dd <= max(2.0, 0.35 * dist)
                    else:  # one direction: error along it plus a quarter of the sideways distance
                        u = v / dist if dist else v
                        err, side = np.abs(rel @ u - dist), np.abs(rel @ np.array([-u[1], u[0]]))
                        dd = err + 0.25 * side
                        ok = (err <= max(1.0, 0.15 * dist)) & (side <= max(2.0, 0.4 * dist))
                    keys.append(np.where(ok, dd, np.inf))
                dd = np.minimum(*keys)
                ok = np.isfinite(dd)
                ranked(acc, [30, 20, 12], same[ok], dd[ok])
            # 'opposite X across room S' and 'on the left/right as seen from door X looking into room S'
            for s_ in spaces:
                if s_ == a or E[s_]['lo'] is None:
                    continue
                pool = np.array(sorted({by_g[g] for g in E[s_]['bnd'] if g in by_g} | set(p['inside'].get(E[s_]['g'], []))
                                       | set(p['beside'].get(E[s_]['g'], [])) - {a}), dtype=int)
                pool = pool[gate[pool] & p['has'][pool]] if len(pool) else pool
                f = cen[s_, :2] - cen[a, :2]
                if not len(pool) or not np.linalg.norm(f):
                    continue
                f = f / np.linalg.norm(f)
                rel = cen[pool, :2] - cen[s_, :2]
                if re.search(r'\bopposite\b', rest):
                    ranked(acc, [25, 15, 10], pool, -(rel @ f))
                side = re.search(r'\b(left|right)\b', rest)
                if side:
                    left = np.array([-f[1], f[0]]) * (1 if side.group(1) == 'left' else -1)
                    ranked(acc, [25, 15, 10], pool, -(rel @ left))
        for i, pts in acc.items():
            R[i] += pts * w
    if re.search(r'\bbetween\b', rest) and len(anchors) >= 2 and len(gidx):
        a, b = anchors[0], anchors[1]
        if E[a]['lo'] is not None and E[b]['lo'] is not None:
            ab = cen[b, :2] - cen[a, :2]
            L = np.linalg.norm(ab)
            pool = gidx[(gidx != a) & (gidx != b)]
            if st_hit:
                pool = pool[[p['sg'][i] in st_hit for i in pool]]
            if L > 0 and len(pool):
                keys = []
                for P in (cen[:, :2], p['org']):
                    ab = P[b] - P[a]
                    L = np.linalg.norm(ab) or 1e-9
                    u = ab / L
                    rel = P[pool] - P[a]
                    t, side = rel @ u, np.abs(rel @ np.array([-u[1], u[0]]))
                    ok = (t > 0) & (t < L) & (side <= max(2.0, 0.3 * L))
                    keys.append(np.where(ok, side + 0.1 * np.abs(t - L / 2), np.inf))
                key = np.minimum(*keys)
                ok = np.isfinite(key)
                acc = {}
                ranked(acc, [25, 18, 12], pool[ok], key[ok])
                for i, pts in acc.items():
                    R[i] += pts * min(D[a], D[b]) / 100
    for m in EXTREME.finditer(rest):
        word = m.group(1) or m.group(4)
        u = np.array(direction(word, m.group(2), m.group(3), north))
        pool = gidx[[p['sg'][i] in st_hit for i in gidx]] if st_hit else gidx
        acc = {}
        if len(pool):
            ranked(acc, [25, 15, 10], pool, -np.maximum(cen[pool, :2] @ u, p['org'][pool] @ u))
        for i, pts in acc.items():
            R[i] += pts
    # second step: elements reached through a relation pass points on to their fillings, host and room members
    R2 = np.zeros(n_el)
    for i in np.where((R >= 10) & (D < 30))[0]:
        e, r = E[i], R[i]
        for g in e['fills'] + ([e['host']] if e['host'] else []):
            j = by_g.get(g, -1)
            if j >= 0 and gate[j]:
                R2[j] += 0.6 * r
        if e['c'] == 'IfcSpace':
            for g in e['bnd']:
                j = by_g.get(g, -1)
                if j >= 0 and gate[j]:
                    R2[j] += 0.4 * r
            for j in set(p['inside'].get(e['g'], []) + p['beside'].get(e['g'], [])):
                if gate[j] and e['g'] not in E[j]['bnd']:
                    R2[j] += 0.4 * r
    S += R + R2
    # attributes
    used = [mm.span() for mm in MOVE.finditer(rest)] + [mm.span() for mm in EXTREME.finditer(rest)]
    rest2 = blank(rest, used)
    A = np.zeros(n_el)
    sec = np.array([e['sec'] or '' for e in E])
    for m in re.finditer(r'\b(north|south)?[- ]?(east|west)?(?:ern|erly)?\b', rest2):
        parts = [x for x in m.groups() if x]
        if not parts or not m.group(0).strip():
            continue
        for x in parts:
            A += np.where(gate & (sec == x), 8 if len(parts) == 1 else 5, 0)
    dims = np.abs(p['hi'] - p['lo'])
    lengths = []
    m_new = re.search(r'\bnew\b', rest2)
    for m in re.finditer(NUM + r'(?:\s*[x×]\s*' + NUM + r')?(?:\s*[x×]\s*' + NUM + r')?' + UNIT, rest2[:m_new.start()] if m_new else rest2):
        u = m.group(4).lower()
        f = 0.001 if u.startswith('mm') or u.startswith('milli') else 0.01 if u == 'cm' else 1.0
        lengths += [float(x) * f for x in m.groups()[:3] if x]
    size_pts = np.zeros(n_el)
    for L in lengths:
        if L > 0:
            size_pts += 6 * np.any(np.abs(dims - L) <= 0.05 * L, axis=1)
    A += np.where(gate & p['has'], np.minimum(size_pts, 18), 0)
    for m in COMPARE.finditer(rest):
        word, val, u = m.group(1).lower(), float(m.group(2)), m.group(3).lower()
        val *= 0.001 if u.startswith('mm') or u.startswith('milli') else 0.01 if u == 'cm' else 1.0
        plan = dims[:, :2].max(axis=1)
        q = {'wider': plan > val, 'longer': plan > val, 'narrower': plan < val, 'shorter': plan < val,
             'taller': dims[:, 2] > val, 'higher': dims[:, 2] > val, 'lower': dims[:, 2] < val,
             'thicker': dims[:, :2].min(axis=1) > val, 'thinner': dims[:, :2].min(axis=1) < val}[word]
        A += np.where(gate & p['has'] & q, 10, 0)
    if re.search(r'\bno (doors?|windows?|openings?)\b', rest):
        A += np.where(gate & np.array([not [g for g in e['fills'] if g in by_g and E[by_g[g]]['c'] != 'IfcOpeningElement'] for e in E]), 10, 0)
    if re.search(r'\bno space boundar', rest):
        A += np.where(gate & np.array([not e['bnd'] for e in E]), 10, 0)
    words = set(re.split(r'[^\w]+', rest2))
    A += np.where(gate, np.minimum(12, 4 * np.array([len(t & words) for t in p['toks']])), 0)
    S += A
    LAST.update(D=D, R=R, R2=R2, A=A, S=S, gate=gate, classes=classes, storeys=st_hit, rest=rest2)
    out = [(round(float(S[i]), 3), E[i]['g'], E[i]) for i in np.where(S >= 10)[0]]
    out.sort(key=lambda x: (-x[0], x[1]))
    return out


if __name__ == '__main__':
    # usage: match.py <ifc path> "<request text>" [k]
    import index_ifc
    for s, g, e in rank(index_ifc.load(sys.argv[1]), sys.argv[2])[:int(sys.argv[3]) if len(sys.argv) > 3 else 10]:
        print(s, g, e['c'], e['n'], e['st'])
