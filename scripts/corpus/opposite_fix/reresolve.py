"""Re-resolve the opposite anchors of bench v4 and val-500 v3 under the fixed rule.

Writes reresolve_report.json and reresolve_report.txt next to this script.
Task files and gold models are only read.
"""
import ast, gc, hashlib, json, os, resource, time, warnings
import numpy as np
warnings.filterwarnings('ignore', category=SyntaxWarning)
import fixload
from fixload import geom, anchors, Scene, FAMILY_CLASS

ROOT = './'
HERE = os.path.dirname(os.path.abspath(__file__))
FILES = [('bench_v4', ROOT + 'runs_local/bench_v4/tasks.jsonl'),
         ('val500_v3', ROOT + 'runs_local/stage_a_v10/val_tasks_500_v3.jsonl')]


def lit(x):
    if isinstance(x, str) and x[:1] in '{[':
        try:
            return ast.literal_eval(x)
        except Exception:
            return x
    return x


def opposite_anchor(record):
    found = []

    def walk(x, path):
        x = lit(x)
        if isinstance(x, dict):
            if x.get('kind') == 'opposite' and 'params' in x:
                found.append((path, x))
            for k, v in x.items():
                walk(v, path + [k])
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, path + [i])
    walk(record, [])
    return found


def name(model, guid):
    try:
        e = model.by_guid(guid)
        if e.is_a('IfcSpace') and getattr(e, 'LongName', None):
            return [guid, e.is_a(), '%s / %s' % (e.Name, e.LongName)]
        return [guid, e.is_a(), e.Name]
    except Exception:
        return [guid, None, None]


def hosted(sc, guid):
    out = {}
    for g in sc.hosted_by(sc.by_guid(guid)) if guid else []:
        fam = sc.family_of(sc.by_guid(g))
        out[fam] = out.get(fam, 0) + 1
    return out


def consistency(sc, r, new, cls):
    """Whether the rest of the instruction still holds for the new element.

    Only the facts the instruction states about the anchored element are
    checked; the regeneration's own verification decides the rest.
    """
    if cls == 'unchanged':
        return True, 'gold unchanged'
    if cls == 'no answer':
        return False, 'no element answers the phrase; drop the task'
    ep = lit(r.get('edit_params')) or {}
    wall = sc.by_guid(new[0])
    kind = r.get('edit_kind')
    if kind == 'delete_wall_with_fillings':
        stated = sorted(f['family'] for f in ep.get('fillings', []))
        there = sorted(sc.family_of(sc.by_guid(g)) for g in sc.hosted_by(wall))
        ok = stated == there
        return ok, 'instruction names fillings %s; new wall hosts %s' % (stated, there)
    if kind == 'create_filling':
        placement = ep.get('placement') or {}
        box = geom.wall_box(wall)
        notes, ok = [], True
        if placement.get('kind') == 'centred_on_wall' and box:
            need = float(placement['centre_from_start']) + float(ep['width']) / 2
            ok = ok and need <= box['length']
            notes.append('leaf end %.2f m along, new wall %.2f m long' % (need, box['length']))
        if placement.get('kind') == 'above_below_filling':
            ref = sc.by_guid(placement['refs'][0])
            c = geom.centre(ref); bb = geom.world_box(wall)
            under = bool(np.all(c[:2] >= bb[0][:2] - 0.3) and np.all(c[:2] <= bb[1][:2] + 0.3))
            ok = ok and under
            notes.append('%s %s the new wall' % (placement.get('a_name'), 'lies under' if under else 'does not lie under'))
        rel = ep.get('relation') or {}
        if rel.get('kind') == 'bounds':
            names = {sc.by_guid(g).LongName for g in sc.bounded_spaces(wall)}
            for label in rel.get('names', []):
                want = label.split("'")[1] if "'" in label else label
                ok = ok and want in names
                notes.append('new wall %s %s' % ('bounds' if want in names else 'does not bound', want))
        return ok, '; '.join(notes) + ('; re-gold by regeneration and its verification' if ok else '')
    return True, 'no stated fact about the anchored element beyond the phrase; re-gold by regeneration and its verification'


tasks = []
for label, path in FILES:
    for line in open(path):
        if 'opposite' not in line:
            continue
        r = json.loads(line)
        found = opposite_anchor(r)
        if not found:
            continue
        assert len(found) == 1, (r['task_id'], len(found))
        tasks.append((label, r, found[0]))
tasks.sort(key=lambda t: t[1]['input_ifc'])

rows, cur, sc, t0 = [], None, None, time.time()
for label, r, (path, a) in tasks:
    src = ROOT + r['input_ifc']
    if src != cur:
        geom._READ.clear(); sc = None; gc.collect()
        sm = r.get('source_model') or {}
        sha_ok = hashlib.sha256(open(src, 'rb').read()).hexdigest() == sm.get('sha256')
        sc = Scene(src); cur = src
    A = anchors.from_record(a)
    new = A.resolve(sc)
    old = list(a.get('expected') or [])
    lib = None; lib_err = None
    try:
        lib = geom.find_opposite(sc.by_guid(a['params']['reference_guid']),
                                 FAMILY_CLASS[a['family']],
                                 sc.by_guid(a['params']['space_guid'])).GlobalId
    except LookupError as ex:
        lib_err = str(ex)[:300]
    if len(new) != 1:
        cls = 'no answer'
    elif new == old:
        cls = 'unchanged'
    else:
        cls = 'changed'
    in_instruction = 'opposite' in (r.get('instruction') or '').lower()
    row = {'split': label, 'task_id': r['task_id'], 'input_ifc': r['input_ifc'],
           'source_sha_ok': sha_ok, 'ifc_version': r.get('ifc_version'),
           'edit_kind': r.get('edit_kind'), 'family': a['family'],
           'anchor_in_instruction': in_instruction, 'anchor_path': path,
           'phrase': a['phrase'],
           'reference': name(sc.model, a['params']['reference_guid']),
           'space': name(sc.model, a['params']['space_guid']),
           'old_gold': [name(sc.model, g) for g in old],
           'new_gold': [name(sc.model, g) for g in new],
           'class': cls, 'library': lib, 'library_error': lib_err,
           'generator_library_agree': (new == [lib]) if lib else (len(new) != 1)}
    # facts the rest of the instruction states about the anchored element
    if a['family'] == 'wall':
        row['old_hosted'] = hosted(sc, old[0]) if len(old) == 1 else None
        row['new_hosted'] = hosted(sc, new[0]) if len(new) == 1 else None
    row['instruction_consistent'], row['consistency_note'] = consistency(sc, r, new, cls)
    rows.append(row)

order = {'bench_v4': 0, 'val500_v3': 1}
rows.sort(key=lambda x: (order[x['split']], x['class'], x['task_id']))
json.dump(rows, open(os.path.join(HERE, 'reresolve_report.json'), 'w'), indent=1)

lines = ['Re-resolution of the opposite anchors under the fixed rule', '']
for split in ('bench_v4', 'val500_v3'):
    sub = [x for x in rows if x['split'] == split]
    counts = {c: sum(x['class'] == c for x in sub) for c in ('unchanged', 'changed', 'no answer')}
    lines.append('%s: %d tasks with an opposite anchor (%d with "opposite" in the instruction): '
                 'unchanged %d, changed %d, no answer %d' % (
                     split, len(sub), sum(x['anchor_in_instruction'] for x in sub),
                     counts['unchanged'], counts['changed'], counts['no answer']))
for split in ('bench_v4', 'val500_v3'):
    sub = [x for x in rows if x['split'] == split and x['class'] == 'changed']
    lines.append('%s changed: %d whose instruction still holds for the new element (re-gold), '
                 '%d whose instruction contradicts it (drop or regenerate the task)' % (
                     split, sum(x['instruction_consistent'] for x in sub),
                     sum(not x['instruction_consistent'] for x in sub)))
lines.append('generator and library agree on %d of %d; source sha256 ok on %d of %d'
             % (sum(x['generator_library_agree'] for x in rows), len(rows),
                sum(bool(x['source_sha_ok']) for x in rows), len(rows)))
lines.append('')
for x in rows:
    fmt = lambda gs: ', '.join('%s (%s)' % (g[0], g[2]) for g in gs) or '-'
    lines.append('%-10s %-30s %-10s %-26s %s' % (x['split'], x['task_id'], x['class'],
                                                x['edit_kind'], '' if x['anchor_in_instruction'] else '[anchor only, not in instruction]'))
    lines.append('    reference %s (%s), space %s' % (x['reference'][0], x['reference'][2], x['space'][2]))
    lines.append('    old gold  %s' % fmt(x['old_gold']))
    lines.append('    new gold  %s' % fmt(x['new_gold']))
    if x['class'] != 'unchanged':
        lines.append('    rest of instruction holds for the new element: %s (%s)' % (
            'yes' if x['instruction_consistent'] else 'NO', x['consistency_note']))
    if x['library_error']:
        lines.append('    library: %s' % x['library_error'])
open(os.path.join(HERE, 'reresolve_report.txt'), 'w').write('\n'.join(lines) + '\n')
print('\n'.join(lines[:8]))
print(len(rows), 'tasks', round(time.time() - t0, 1), 's; maxrss MB',
      resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
