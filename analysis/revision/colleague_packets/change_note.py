"""One factual change note per task, in plain words, from edit_params and the two models.

The note names elements by their model names (never by GlobalId) and says what changed, with
the dimensions the ground-truth edit uses. Used in the rewrite packet."""
import re

import numpy as np

import plan_render as P

GID = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")


def word(e):
    c = e.is_a() if e is not None else ''
    for k, w in (('IfcWall', 'wall'), ('IfcCurtainWall', 'curtain wall'), ('IfcSlab', 'slab'),
                 ('IfcColumn', 'column'), ('IfcDoor', 'door'), ('IfcWindow', 'window'), ('IfcSpace', 'space'),
                 ('IfcBeam', 'beam'), ('IfcStair', 'stair')):
        if c.startswith(k):
            return w
    return 'element'


def m(v):
    return f'{float(v):.2f} m'


def nm(e):
    if e is None:
        return 'the highlighted element'
    n = (e.Name or '').strip()
    return f"the {word(e)} '{n}'" if n else f'the highlighted {word(e)}'


def names_list(els):
    ns = [nm(e) for e in els]
    if len(ns) <= 1:
        return ''.join(ns)
    if len(ns) <= 4:
        return ', '.join(ns[:-1]) + ' and ' + ns[-1]
    return f'{len(ns)} {word(els[0])}s (outlined in red)'


def compass(v):
    """8-point compass word of a horizontal direction (+Y = north)."""
    ang = (np.degrees(np.arctan2(v[1], v[0])) + 360) % 360
    words = ['east', 'north-east', 'north', 'north-west', 'west', 'south-west', 'south', 'south-east']
    return words[int(((ang + 22.5) % 360) // 45)]


def start_end(wall):
    a = P.wall_axis(wall)
    return compass(-a)


def storey_name(st):
    return f"'{st.Name}'" if st is not None and st.Name else 'the storey shown'


def sill_words(sill):
    return "standing on the wall's base" if abs(sill) < 1e-6 else f"with its sill {m(sill)} above the wall's base"


def g(model, guid):
    return P.by_guid(model, guid) if guid else None


def note(rec, src, gold, S):
    s = _note(rec, src, gold, S)
    return s[:1].upper() + s[1:]


def _note(rec, src, gold, S):
    ep = rec['edit_params']
    ek = rec['edit_kind']
    eg = rec['edit_guids']
    st_b, st_a = S['st_before'], S['st_after']
    on = f"On storey {storey_name(st_b)}, "
    tgt_src = [g(src, x) for x in (eg.get('target') or []) if g(src, x) is not None]
    t0 = tgt_src[0] if tgt_src else None
    if ek in ('create_box',):
        e = g(gold, (eg.get('created') or eg.get('target'))[0])
        w = word(e)
        if w == 'element':
            w = rec['family']
        s = f"A new {w} named '{ep['name']}' is added on storey {storey_name(st_a)}. "
        if w in ('column',):
            s += f"It is {m(ep['length'])} by {m(ep['width'])} in section and {m(ep['height'])} high"
        elif w == 'slab':
            s += f"It is {m(ep['length'])} by {m(ep['width'])} in plan and {m(ep['height'])} thick"
        else:
            s += (f"It is {m(ep['length'])} long in the east-west (x) direction, {m(ep['width'])} wide in the "
                  f"north-south (y) direction and {m(ep['height'])} high")
        pl, off = ep.get('placement'), ep.get('offset')
        if isinstance(pl, dict) and pl.get('kind') == 'on_top_of':
            s += f", and sits directly on top of the {pl.get('a_family', 'element')} '{pl.get('a_name')}', over the same footprint."
        elif isinstance(pl, dict) and pl.get('kind') == 'adjacent_to_space':
            s += (f", stands inside the {pl.get('space_label', 'space')} and touches the {pl.get('a_family', 'element')} "
                  f"'{pl.get('a_name')}'.")
        elif isinstance(off, dict):
            ref = g(src, off.get('reference_guid'))
            s += (f", with its base corner {m(off['dx'])} to the {off['x_word']} and {m(off['dy'])} to the "
                  f"{off['y_word']} of {nm(ref)}.")
        else:
            frame = "the storey's own coordinates" if 'own coordinates' in rec['instruction'] else 'model coordinates'
            s += (f", with its lowest corner at x = {ep['x']:.2f}, y = {ep['y']:.2f}, z = {ep['z']:.2f} m "
                  f"({frame}).")
        if ep.get('predefined_type'):
            s += f" Its predefined type is {ep['predefined_type']}."
        rel = ep.get('relation')
        if isinstance(rel, dict):
            ns = ', '.join(rel.get('names') or [])
            if rel['kind'] == 'bounds':
                s += f" It is recorded as bounding the {ns}." if not ns.startswith(('space', 'room')) else f" It is recorded as bounding the {ns}."
            elif rel['kind'] == 'bounded_by':
                s += f" The {rel.get('partner_family', 'element')} '{ns}' is recorded as bounding it."
            elif rel['kind'] == 'connects':
                s += f" It is recorded as connected to the {rel.get('partner_family', 'element')} '{ns}'."
        return s
    if ek == 'copy_element':
        srcel = g(src, ep['source_guid'])
        return (f"{on}a copy of {nm(srcel)} is placed {m(ep['distance'])} to the {ep['direction']} of it "
                f"and named '{ep['name']}'.")
    if ek == 'array_elements':
        srcel = g(src, ep['source_guid'])
        names = ep['names']
        nl = ', '.join(f"'{x}'" for x in names[:-1]) + f" and '{names[-1]}'"
        return (f"{on}{ep['count']} copies of {nm(srcel)} are placed in a row to the {ep['direction']} of it, "
                f"{m(ep['spacing'])} apart, named {nl} in that order.")
    if ek in ('create_filling', 'replace_filling'):
        host = g(gold, ep.get('host_guid'))
        new = g(gold, (eg.get('created') or eg.get('target'))[0])
        fam = word(new) if new is not None else ('door' if ep.get('entity_type', '') == 'IfcDoor' else 'window')
        if ek == 'replace_filling':
            old = g(src, ep['replaced_guid'])
            s = (f"{on}{nm(old)} in {nm(host)} is replaced by a {fam} named '{ep['name']}', {m(ep['width'])} wide "
                 f"and {m(ep['height'])} high, at the same position along the wall and {sill_words(ep['sill'])}. "
                 f"The old opening is removed and a new opening is cut for the {fam}.")
        else:
            pl = ep.get('placement')
            se = start_end(host) if host is not None else 'start'
            if isinstance(pl, dict) and pl.get('kind') == 'centred_on_wall':
                where = f"centred on the wall, its middle {m(pl['centre_from_start'])} from the wall's {se} end"
            else:
                where = f"its near edge {m(ep['along'])} along the wall from the wall's {se} end"
            s = (f"{on}a new {fam} named '{ep['name']}', {m(ep['width'])} wide and {m(ep['height'])} high, is added "
                 f"to {nm(host)}, {where}, {sill_words(ep['sill'])}. An opening is cut in the wall for it.")
            rel = ep.get('relation')
            if isinstance(rel, dict) and rel.get('kind') == 'bounds':
                s += f" It is recorded as bounding the {', '.join(rel.get('names') or [])}."
        return s
    if ek == 'delete':
        els = [g(src, x) for x in (eg.get('removed') or eg.get('target') or [])]
        els = [e for e in els if e is not None and not e.is_a('IfcOpeningElement')]
        verb = 'is' if len(els) == 1 else 'are'
        return f"{on}{names_list(els)} {verb} removed from the model, with the relationships that depend on {'it' if len(els) == 1 else 'them'}."
    if ek == 'translate':
        s = f"{on}{nm(t0)} is moved {m(ep['distance'])} to the {ep['direction']}"
        if ep.get('n_openings_carried'):
            s += ', and its doors and windows move with it'
        return s + '.'
    if ek == 'rotate':
        d = ep['degrees']
        sense = 'counter-clockwise' if d > 0 else 'clockwise'
        piv = 'the centre of its plan' if ep.get('pivot') == 'centre' else 'its insertion point (placement origin)'
        return f"{on}{nm(t0)} is turned {abs(d):g} degrees {sense} (seen from above) about {piv}."
    if ek == 'mirror':
        if ep.get('plane_kind') == 'wall_axis':
            pw = ep.get('plane_wall')
            pwe = g(src, pw) if pw and GID.fullmatch(str(pw)) else None
            pwn = nm(pwe) if pwe is not None else f"the wall '{pw}'"
            return f"{on}{nm(t0)} is mirrored across the centre line of {pwn}."
        return (f"{on}{nm(t0)} is mirrored across the vertical plane {ep['plane_axis']} = {ep['plane_value']:.2f} m "
                f"(model coordinates).")
    if ek == 'move_to_storey':
        fr = ep['storey_from'].replace('storey ', '')
        to = ep['storey_to'].replace('storey ', '')
        return f"{nm(t0)} is reassigned from storey {fr} to storey {to}. It stays exactly where it is in the building."
    if ek == 'assign_material':
        els = [g(src, x) for x in (eg.get('target') or [])]
        s = f"{on}the material of {names_list([e for e in els if e is not None])} is set to '{ep['material']}'"
        if ep.get('old'):
            s += f" (it was '{ep['old']}')"
        return s + '.'
    if ek == 'assign_type':
        s = f"{on}{nm(t0)} is assigned to the type '{ep['type_name']}'"
        if ep.get('old'):
            s += f" (it was of type '{ep['old']}')"
        return s + '.'
    if ek == 'set_pset':
        val = ep['value']
        vs = ('true' if val else 'false') if isinstance(val, bool) else (f"'{val}'" if isinstance(val, str) else f'{val:g}')
        unit = ' W/m2K' if 'Thermal' in ep.get('value_type', '') else ''
        s = f"{on}the {ep['property_word']} ({ep['property']} in {ep['pset']}) of {nm(t0)} is set to {vs}{unit}"
        if ep.get('old') is not None:
            ov = ep['old']
            ovs = ('true' if ov else 'false') if isinstance(ov, bool) else (f"'{ov}'" if isinstance(ov, str) else f'{ov:g}')
            s += f" (it was {ovs}{unit})"
        return s + '.'
    if ek == 'rename':
        return f"{on}the {word(t0)} '{ep['old']}' is renamed to '{ep['new']}'. Its position does not change."
    if ek == 'retype':
        s = f"{on}the predefined type of {nm(t0)} is set to {ep['new']}"
        if ep.get('old'):
            s += f" (it was {ep['old']})"
        return s + '. Its position does not change.'
    if ek.startswith('resize'):
        els = [g(src, x) for x in (eg.get('target') or [])]
        els = [e for e in els if e is not None]
        s = f"{on}the {ep['dimension']} of {names_list(els)} is changed"
        if ep.get('old') is not None:
            s += f" from {m(ep['old'])}"
        return s + f" to {m(ep['new'])}. Its placement stays fixed."
    if ek == 'rehost_filling':
        hf, ht = g(src, ep['host_from_guid']), g(gold, ep['host_to_guid'])
        se = start_end(ht) if ht is not None else 'start'
        return (f"{on}{nm(t0)} is moved out of {nm(hf)} into {nm(ht)}, its near edge {m(ep['along'])} along that "
                f"wall from its {se} end, {sill_words(ep.get('sill_above_base', 0.0))}. Its opening moves with it, "
                f"and the old wall is closed where the {word(t0)} was.")
    return ''


# --------------------------------------------------------------------------- property lines
def _unit(model):
    import ifcopenshell.util.unit as uu
    return uu.calculate_unit_scale(model)


def _prop(model, e, rec, mesh):
    import ifcopenshell.util.element as ue
    ek, ep = rec['edit_kind'], rec['edit_params']
    if e is None:
        return None
    if ek == 'assign_material':
        mat = ue.get_material(e, should_skip_usage=True)
        if mat is None:
            return 'material: none'
        if mat.is_a('IfcMaterial'):
            return f"material: '{mat.Name}'"
        ms = ue.get_materials(e)
        return 'material: ' + ', '.join(f"'{x.Name}'" for x in ms) if ms else f"material: '{getattr(mat, 'Name', '')}'"
    if ek == 'assign_type':
        t = ue.get_type(e)
        return f"type: '{t.Name}'" if t is not None else 'type: none'
    if ek == 'set_pset':
        v = ue.get_pset(e, ep['pset'], ep['property'])
        return f"{ep['property_word']} ({ep['pset']}): " + ('not set' if v is None else (f"'{v}'" if isinstance(v, str) else f'{v}'))
    if ek == 'rename':
        return f"name: '{e.Name}'"
    if ek == 'retype':
        pt = getattr(e, 'PredefinedType', None)
        return f'predefined type: {pt if pt else "not set"}'
    if ek == 'resize_overall':
        attr = 'OverallHeight' if 'height' in ep['dimension'] else 'OverallWidth'
        v = getattr(e, attr, None)
        return f"{ep['dimension']}: " + ('not set' if v is None else m(v * _unit(model)))
    if ek in ('resize_extrusion', 'resize_profile') and mesh is not None:
        V = mesh['verts']
        dim = ep['dimension']
        if dim in ('thickness', 'height'):
            return f'{dim} (measured on the drawn element): {m(V[:, 2].max() - V[:, 2].min())}'
        if dim == 'length' and word(e) == 'wall':
            a = P.wall_axis(e)
            q = V @ a
            return f'length (measured on the drawn element): {m(q.max() - q.min())}'
    return None


def property_lines(rec, src, gold, S, ms_b, ms_a):
    """Footer lines under the plan views for edits a plan cannot show (material, type, property,
    name, predefined type, size not seen in plan). Values are read from each model."""
    if rec['edit_kind'] not in ('assign_material', 'assign_type', 'set_pset', 'rename', 'retype', 'resize_overall',
                                'resize_extrusion', 'resize_profile'):
        return None, None
    out = []
    for model, reds, ms in ((src, S['before_red'], ms_b), (gold, S['after_red'], ms_a)):
        vals = []
        for gid in reds:
            e = P.by_guid(model, gid)
            vals.append(_prop(model, e, rec, ms.get(gid)))
        vals = [v for v in vals if v]
        if not vals:
            out.append(None)
            continue
        if len(set(vals)) == 1:
            pre = 'Red element' if len(reds) == 1 else f'Each of the {len(reds)} red elements'
            out.append(f'{pre}: {vals[0]}')
        else:
            out.append('Red elements: ' + '; '.join(vals))
    return out[0], out[1]
