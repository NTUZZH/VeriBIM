"""Re-gold one bench task whose opposite anchor moved to a new element.

The instruction, the anchor phrase, the seed and every stated value stay as the
record holds them.  Only the element the phrase names changes, so the edit is
re-planned on the new element with the generator's own planning rules and then
passed through the generator's own verification funnel (generate.produce:
anchor, wording, parse, re-execution, self-score, null-edit score).

Each planner below is first run on the OLD element and must reproduce the stored
gold script's arguments exactly; only then is it trusted on the new element.
A task the rules refuse on the new element is returned as a failure, and the
caller treats it as dropped (and replaced).
"""
from __future__ import annotations

import ast
import random
import re
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from fixcommon import ROOT


def parse_calls(script_source: str):
    """The gold script's calls as (func, kwargs in order, comment)."""
    tree = ast.parse(script_source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'apply_edit')
    lines = script_source.splitlines()
    out = []
    for stmt in fn.body:
        if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call)):
            continue
        call = stmt.value
        func = call.func.attr
        kwargs = {k.arg: ast.literal_eval(k.value) for k in call.keywords}
        prev = lines[stmt.lineno - 2].strip() if stmt.lineno >= 2 else ''
        comment = prev[2:] if prev.startswith('# ') else ''
        out.append((func, kwargs, comment))
    return out


def calls_from(parsed):
    from modifc_gen.ops import Call
    from modifc_gen.script import _parameter_names
    calls = []
    for func, kwargs, comment in parsed:
        names = _parameter_names(func)
        used = [n for n in names if n in kwargs]
        assert used == list(kwargs), (func, list(kwargs), names)
        assert names[:len(used)] == used, (func, used, names)
        calls.append(Call(func, tuple(kwargs[n] for n in used), comment))
    return calls


def check_roundtrip(record) -> None:
    from modifc_gen.ops import EditPlan
    from modifc_gen.script import render_script
    plan = EditPlan(kind='x', operation='x', family='x', calls=calls_from(parse_calls(record['gold_script'])))
    again = render_script(record['task_id'], record['instruction'], plan)
    assert again == record['gold_script'], record['task_id'] + ': gold script does not round-trip'


# --------------------------------------------------------------- planners

def _plan_delete(sc, rec, new_guid, old_guid):
    from modifc_gen import ops, families
    ep = rec['edit_params']
    old_plan = ops.plan_delete(sc, sc.by_guid(old_guid), random.Random(0))
    assert list(old_plan.removed_guids) == list(rec['edit_guids']['removed']), 'delete planner does not reproduce the stored removal set'
    fresh = ops.plan_delete(sc, sc.by_guid(new_guid), random.Random(0))
    if fresh is None:
        return None, 'plan_delete refuses the new element'
    params = {k: v for k, v in fresh.params.items()
              if k not in ('constraint', 'families', 'named_relations', 'named_relations_form')}
    for key in ('constraint', 'named_relations', 'named_relations_form', 'families', 'wording'):
        if key in ep:
            params[key] = ep[key]
    if params.get('named_relations'):
        return None, 'the instruction names relationships of the old element'
    if 'constraint' in params:
        fam = families.BY_TAG[params['constraint']]
        if not families.admits(fam, fresh):
            return None, 'constraint clause not admitted for the new plan'
    fresh.params = params
    return fresh, ''


def _plan_copy(sc, rec, new_guid, old_guid):
    from modifc_gen import ops
    from modifc_gen.ops import Call, EditPlan
    ep = rec['edit_params']
    (func, kw, comment), = parse_calls(rec['gold_script'])
    assert func == 'copy_element' and kw['guid'] == old_guid

    def fault(guid):
        product = sc.by_guid(guid)
        if not ops._copyable(sc, product):
            hosted = [sc.family_of(sc.by_guid(x)) for x in sc.hosted_by(product)]
            return 'not copyable under the generator rule ops._copyable (hosts %s; stranded dependants %d; body %s)' % (
                hosted or 'nothing', len(ops.stranded_dependants(sc, product)),
                bool(sc.has_body(product) and sc.own_frame_box(product) is not None))
        storey, matrix, box = sc.storey_of(product), sc.matrix(product), sc.own_frame_box(product)
        if storey is None or matrix is None or box is None:
            return 'no storey, frame or body'
        offset = np.zeros(3)
        offset[int(ep['axis'])] = int(ep['sign']) * float(ep['distance'])
        moved = np.array(matrix, dtype=float).copy()
        moved[:3, 3] = moved[:3, 3] + offset
        return ops.transform_fault(sc, product, moved, storey, [product.GlobalId], box)

    assert fault(old_guid) is None, 'copy rules refuse the stored (old) copy'
    why = fault(new_guid)
    if why:
        return None, 'copy of the new element refused: %s' % why
    assert ops.free_guid(sc, rec['task_id'], 'copy') == kw['new_guid']
    assert ops.free_guid(sc, rec['task_id'], 'containment') == kw['relation_guid']
    kw = dict(kw, guid=new_guid)
    calls = calls_from([(func, kw, comment)])
    params = dict(ep, source_guid=new_guid)
    g = rec['edit_guids']
    return EditPlan(kind='copy_element', operation='create', family=rec['family'], calls=calls,
                    target_guids=tuple(g['target']), created_guids=tuple(g['created']),
                    touched_guids=tuple(g['touched']), relation_guids=tuple(g['relations']),
                    params=params), ''


def _slot_at(sc, wall, width, height, sill, along):
    """wall_opening_slot with the along position fixed instead of drawn."""
    from modifc_gen import ops
    extent = sc.local_extent(wall)
    if extent is None:
        return None, 'wall extent unreadable'
    body = sc.box_in_frame(wall, sc.matrix(wall))
    if body is None:
        return None, 'wall body unreadable'
    if float(np.abs(np.concatenate([body.lo - extent.lo, body.hi - extent.hi])).max()) > 0.1:
        return None, 'wall_body_disagrees_with_profile'
    extent = body
    length = float(extent.hi[0] - extent.lo[0])
    thickness = float(extent.hi[1] - extent.lo[1])
    if length < width + 1.0 or not 0.05 <= thickness <= 1.5:
        return None, 'wall too short or thickness out of range (length %.2f, thickness %.3f)' % (length, thickness)
    if float(extent.hi[2] - extent.lo[2]) < sill + height + ops.FILLING_HEADROOM:
        return None, 'filling_taller_than_wall'
    across = ops._round(float(extent.lo[1]) - 0.05)
    base = float(extent.lo[2])
    if along + width > float(extent.hi[0]) - 0.2:
        return None, 'filling_past_wall_end (leaf end %.2f m, limit %.2f m from the wall start)' % (
            along + width - float(extent.lo[0]), float(extent.hi[0]) - 0.2 - float(extent.lo[0]))
    if along < float(extent.lo[0]) + 0.2:
        return None, 'filling_before_wall_start'
    for low, high in ops.filling_spans(sc, wall):
        if along < high + ops.FILLING_CLEARANCE and along + width > low - ops.FILLING_CLEARANCE:
            return None, 'filling_overlaps_filling'
    return (along, across, ops._round(thickness + 0.1), ops._round(base + sill)), ''


def _plan_filling(sc, rec, new_guid, old_guid):
    from modifc_gen import ops
    from modifc_gen.ops import EditPlan
    ep = rec['edit_params']
    placement = ep.get('placement') or {}
    if placement.get('kind') != 'centred_on_wall':
        return None, 'placement kind %r is not re-planned' % placement.get('kind')
    parsed = parse_calls(rec['gold_script'])
    assert parsed[0][0] == 'add_filling' and parsed[0][1]['host_guid'] == old_guid
    width, height, sill = float(ep['width']), float(ep['height']), float(ep['sill'])
    centre = float(placement['centre_from_start'])

    def slot(guid):
        wall = sc.by_guid(guid)
        lo = float(sc.local_extent(wall).lo[0])
        along = ops._round(centre + lo - width / 2.0)
        if ops._round(along + width / 2.0 - lo) != centre:
            return None, 'centre does not round-trip', along
        got, why = _slot_at(sc, wall, width, height, sill, along)
        return got, why, along

    kw0 = parsed[0][1]
    # the stored slot is checked without the overlap rule's own filling (none yet)
    got, why, along = slot(old_guid)
    assert got is not None, 'filling rules refuse the stored (old) slot: ' + why
    a, across, thick, base = got
    assert (a, across, thick, base) == (kw0['along'], kw0['across'], kw0['thickness'], kw0['sill']), (
        'slot replication differs from the stored call', got, kw0)
    assert kw0['filling_across'] == ops._round(across + 0.05) and kw0['filling_depth'] == ops._round(thick - 0.1)
    got, why, along = slot(new_guid)
    if got is None:
        return None, 'filling on the new wall refused: ' + why
    a, across, thick, base = got
    kw = dict(kw0, host_guid=new_guid, along=a, across=across, sill=base, thickness=thick,
              filling_across=ops._round(across + 0.05), filling_depth=ops._round(thick - 0.1))
    new_parsed = [(parsed[0][0], kw, parsed[0][2])] + list(parsed[1:])
    wall = sc.by_guid(new_guid)
    params = {}
    for key, value in ep.items():
        if key == 'along':
            value = a
        elif key == 'host_guid':
            value = new_guid
        elif key == 'placement':
            value = dict(value, refs=[new_guid], a_name=sc.unique_name(wall))
        params[key] = value
    g = rec['edit_guids']
    touched = tuple(new_guid if x == old_guid else x for x in g['touched'])
    plan = EditPlan(kind='create_filling', operation='create', family=rec['family'],
                    calls=calls_from(new_parsed), target_guids=tuple(g['target']),
                    created_guids=tuple(g['created']), touched_guids=touched,
                    relation_guids=tuple(g['relations']), params=params)
    # a stated relationship: the named space has to touch the new leaf, as
    # _near_named requires at generation time; the same test on the old plan
    # must pass, which checks the replication.
    rel = ep.get('relation') or {}
    if rel:
        if rel.get('kind') != 'bounds':
            return None, 'relation kind %r is not re-planned' % rel.get('kind')
        storey = sc.storey_of(wall)

        def touches(p):
            world = ops._created_world_box(sc, p, storey)
            box = None
            if world is None:
                return False, 'created box unknown'
            for edge in p.params.get('relation_edges') or ():
                space = sc.by_guid(edge[1])
                if space not in sc.on_storey('space', storey.GlobalId):
                    return False, 'named space not on the storey'
                other = sc.world_box(space)
                centre = (world[0] + world[1]) / 2.0
                gap = ops._box_gap(world, (other.lo, other.hi))
                dist = float(np.linalg.norm(centre - sc.centre(space)))
                if gap > ops.RELATION_TOUCH or dist > ops.RELATION_REACH:
                    return False, 'named space %s does not touch the leaf (gap %.2f m)' % (space.LongName or space.Name, gap)
            return True, ''
        old_params = dict(ep)
        old_plan = EditPlan(kind='create_filling', operation='create', family=rec['family'], calls=[],
                            params=old_params)
        ok, why = touches(old_plan)
        assert ok, 'relation check refuses the stored (old) plan: ' + why
        for call in plan.calls[1:]:
            assert call.func == 'add_space_boundary' and call.args[4] == 'INTERNAL'
        ok, why = touches(plan)
        if not ok:
            return None, why
    return plan, ''


PLANNERS = {'delete': _plan_delete, 'copy_element': _plan_copy, 'create_filling': _plan_filling}


def regold(code, rec, new_guid, workdir: Path, models, meshes):
    """Returns (new_record, gold_ifc_path, note) or (None, None, reason)."""
    from modifc_gen import anchors as anchor_lib, generate, settings
    from modifc_gen.generate import Draw
    check_roundtrip(rec)
    kind = rec['edit_kind']
    if kind not in PLANNERS:
        return None, None, 'edit kind %s is not re-planned' % kind
    old_guid = rec['anchor']['expected'][0]
    Scene = code['Scene']
    sm = rec['source_model']
    sc = Scene(str(ROOT / rec['input_ifc']), rec['input_ifc'], sm['sha256'])
    plan, why = PLANNERS[kind](sc, rec, new_guid, old_guid)
    if plan is None:
        return None, None, why
    anchor_rec = {k: v for k, v in rec['anchor'].items() if k != 'expected'}
    anchor = anchor_lib.from_record(anchor_rec)
    draw = Draw(plan=plan, anchor=anchor, anchor_expected=(new_guid,), category=rec['category'],
                instruction=rec['instruction'], entity_type=rec['target']['entity_type'])
    model_ref = SimpleNamespace(relpath=rec['input_ifc'], sha256=sm['sha256'], collection=sm['collection'],
                                schema=sm['schema'], key=sm['key'])
    assert settings.SETTINGS.wave == rec['wave'], (settings.SETTINGS.wave, rec['wave'])
    (workdir / 'scratch').mkdir(parents=True, exist_ok=True)
    outcome = generate.produce(sc, model_ref, rec['task_id'], draw, ROOT, workdir, workdir / 'scratch',
                               models, meshes, seed=rec['seeds']['task_seed'], want_null_baseline=True,
                               keep_gold=True)
    if outcome.stage != 'accepted':
        return None, None, 'generator funnel refused at %s: %s %s' % (outcome.stage, outcome.reason, outcome.detail)
    new = outcome.record
    gold = workdir / 'models' / (rec['task_id'] + '.ifc')
    assert gold.is_file()
    out = dict(rec)
    for key in ('target', 'gold_script', 'anchor', 'edit_params', 'difficulty', 'edit_guids',
                'families', 'requires_relations', 'verification'):
        out[key] = new[key]
    # produce() marks the gold as materialised because it was kept for gzip; the
    # bench records carry the generation-time value, so keep it.
    out['verification'] = dict(new['verification'],
                               gold_materialized=rec['verification'].get('gold_materialized'))
    for key in ('instruction', 'prompt', 'operation', 'category', 'edit_kind', 'family', 'tier',
                'wording', 'clarification', 'expected_reply', 'model_conditions', 'generator_version', 'wave'):
        assert new[key] == rec[key], (rec['task_id'], key, new[key], rec[key])
    changed_anchor = {k for k in set(new['anchor']) | set(rec['anchor']) if new['anchor'].get(k) != rec['anchor'].get(k)}
    assert changed_anchor == {'expected'}, changed_anchor
    note = []
    if set(new['families']) != set(rec['families']):
        note.append('families %s -> %s' % (sorted(set(rec['families']) - set(new['families'])),
                                            sorted(set(new['families']) - set(rec['families']))))
    sc = None
    return out, gold, '; '.join(note)
