"""Tests for the fixed "opposite" rule, run against the fixed copies.

Run:  python test_opposite_fix.py
(or with pytest from this directory).  The fixed anchors.py and veribim_geom.py
are loaded by fixload.py under the installed module names, inside this process
only.  The source models are read; nothing under code/ or data/ is written.

1. On all 678 audited tasks, the generator rule (anchors._resolve_opposite) and
   the library rule (veribim_geom.find_opposite) return the same element, or
   both return no answer.
2. On every DISAGREE-PERPENDICULAR row, the fixed answer is the audit's
   geometric (parallel far-side) wall.
3. CHN-DWF-TOP-B16-033 (gold right, old library wrong): the fixed answer is the
   gold.
4. On every AGREE row whose gold is parallel and on the far side, the fixed
   answer is the gold.
5. Synthetic room (the generator's own unit-test fixture), axis-aligned and
   rotated: the builder names the north wall through the south wall, both
   rules agree, and a door's opposite reads its host wall.
6. On four real source models (one rotated), every anchor the fixed builder
   writes resolves to its target in the generator rule and in the library, and
   its reference runs parallel to the target.
"""
import gc
import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import fixload  # noqa: E402  (must come before any modifc_gen/modifc_harness import)
from fixload import geom, anchors, Scene, FAMILY_CLASS  # noqa: E402

import ifcopenshell  # noqa: E402
import numpy as np  # noqa: E402

ROOT = './'
AUDIT = ROOT + 'runs_local/stage_a_v10/gates/v500/analysis/opposite_audit/audit.jsonl'
_RESULTS = None


def results():
    """Run both fixed rules on every audited task once, keyed by (file, task_id)."""
    global _RESULTS
    if _RESULTS is not None:
        return _RESULTS
    rows = [json.loads(line) for line in open(AUDIT)]
    rows.sort(key=lambda r: r['input_ifc'])
    out, current, scene = {}, None, None
    for r in rows:
        src = ROOT + r['input_ifc']
        if src != current:
            geom._READ.clear(); scene = None; gc.collect()
            scene = Scene(src); current = src
        params = {'reference_guid': r['reference'][0], 'space_guid': r['space'][0],
                  'axis': r['axis'], 'min_offset': 0.25}
        anchor = anchors.Anchor(kind='opposite', family=r['family'], phrase=r['phrase'],
                                params=params)
        gen = anchor.resolve(scene)
        try:
            lib = geom.find_opposite(scene.by_guid(r['reference'][0]),
                                     FAMILY_CLASS[r['family']],
                                     scene.by_guid(r['space'][0])).GlobalId
            err = None
        except LookupError as ex:
            lib, err = None, str(ex)
        out[(r['file'], r['task_id'])] = {'audit': r, 'gen': gen, 'lib': lib, 'err': err}
    _RESULTS = out
    return out


def answer(res):
    return res['gen'][0] if len(res['gen']) == 1 else None


def test_1_generator_and_library_agree():
    res = results()
    assert len(res) == 678
    bad = [k for k, x in res.items()
           if not ((len(x['gen']) == 1 and x['gen'] == [x['lib']])
                   or (len(x['gen']) != 1 and x['lib'] is None))]
    assert not bad, bad[:10]


def test_2_disagree_perpendicular_rows_get_the_parallel_far_wall():
    res = results()
    rows = [x for x in res.values() if x['audit']['class'] == 'DISAGREE-PERPENDICULAR']
    assert len(rows) == 132
    bad = [(x['audit']['task_id'], x['gen'], x['audit']['geometric'][0])
           for x in rows if answer(x) != x['audit']['geometric'][0]]
    assert not bad, bad[:10]


def test_3_reverse_case_gets_the_gold():
    x = results()[('bench_v4', 'CHN-DWF-TOP-B16-033')]
    assert answer(x) == x['audit']['gold'][0] == '0xh_Oubh588AQqRwTYTkzU'
    assert x['lib'] == x['audit']['gold'][0]


def test_4_parallel_agree_rows_keep_their_gold():
    res = results()
    rows = [x for x in res.values()
            if x['audit']['class'] == 'AGREE' and x['audit']['gold_is_parallel_far']]
    assert len(rows) == 221
    bad = [(x['audit']['task_id'], x['gen'], x['audit']['gold'][0])
           for x in rows if answer(x) != x['audit']['gold'][0]]
    assert not bad, bad[:10]


# ------------------------------------------------------------ synthetic room


def _room(tmpname, degrees):
    """The generator's own two-storey fixture, optionally turned about the origin."""
    from modifc_gen.tests import test_families_v05 as fx
    model, ground, upper, guids = fx.two_storey_model()
    if degrees:
        turn = math.radians(degrees)
        for storey in (ground, upper):
            placement = storey.ObjectPlacement.RelativePlacement
            placement.Axis = model.create_entity('IfcDirection', DirectionRatios=(0.0, 0.0, 1.0))
            placement.RefDirection = model.create_entity(
                'IfcDirection', DirectionRatios=(math.cos(turn), math.sin(turn), 0.0))
    work = os.path.join(HERE, 'fixtures')
    os.makedirs(work, exist_ok=True)
    path = os.path.join(work, tmpname)
    model.write(path)
    return Scene(path), guids


def _check_room(degrees):
    import random
    scene, g = _room('room_%d.ifc' % degrees, degrees)
    run = geom.plan_direction(scene.by_guid(g['south']))
    # The wall's own x axis in world terms (the fixture's placements share one
    # placement entity, so the world turn can be a multiple of ``degrees``).
    want = geom.frame_of(scene.by_guid(g['south']))[:2, 0]
    if degrees:
        assert 0.1 < abs(float(want[0])) < 0.99, want  # really not axis-aligned
    assert abs(abs(float(np.dot(run, want))) - 1.0) < 1e-6, run
    built = anchors.opposite_anchors(scene, scene.by_guid(g['north']), random.Random(7))
    assert built, 'no opposite anchor for the north wall'
    assert built[0].params['reference_guid'] == g['south']
    assert built[0].resolve(scene) == [g['north']]
    lib = geom.find_opposite(scene.by_guid(g['south']), 'IfcWall', scene.by_guid(g['kitchen']))
    assert lib.GlobalId == g['north']
    # East and west swap the same way.
    for a, b in (('east', 'west'), ('west', 'east'), ('north', 'south')):
        anchor = anchors.Anchor(kind='opposite', family='wall', phrase='',
                                params={'reference_guid': g[a], 'space_guid': g['kitchen'],
                                        'axis': 0, 'min_offset': 0.25})
        assert anchor.resolve(scene) == [g[b]], (a, anchor.resolve(scene))
    # A door runs along its host (the south wall), so the far side is north;
    # the room has no other door, so there is no answer in either rule.
    door = anchors.Anchor(kind='opposite', family='door', phrase='',
                          params={'reference_guid': g['door'], 'space_guid': g['kitchen'],
                                  'axis': 1, 'min_offset': 0.25})
    assert door.resolve(scene) == []
    try:
        geom.find_opposite(scene.by_guid(g['door']), 'IfcDoor', scene.by_guid(g['kitchen']))
        raise AssertionError('find_opposite answered for a room with one door')
    except LookupError:
        pass
    run_door = geom.plan_direction(scene.by_guid(g['door']))
    assert abs(abs(float(np.dot(run_door, want))) - 1.0) < 1e-6


def test_5_synthetic_room_axis_aligned():
    _check_room(0)


def test_5_synthetic_room_rotated():
    _check_room(30)


# ------------------------------------------------ builder on real source models

BUILDER_MODELS = [
    'data/corpus/auckland/090_231110AC-11-Smiley-West-04-07-2007.ifc',
    'data/corpus/auckland/088_231110AC11-FZK-Haus-IFC.ifc',
    "data/corpus/auckland/161_20160125Trapelo - Existing-Trapelo_Design_Intent.ifc",
    'data/corpus/bs_community_repo/IFC 2.3.0.1 (IFC 2x3)/Duplex Apartment/Duplex_A_20110907.ifc',
]
_BUILDER = None


def builder_results(per_model=120):
    """Every anchor the fixed builder writes, checked against both rules.

    Returns rows (model, family, target, anchor-or-None, library answer) and the
    old builder's yield on the same products, for comparison.
    """
    global _BUILDER
    if _BUILDER is not None:
        return _BUILDER
    import importlib.util
    import random
    spec = importlib.util.spec_from_file_location('modifc_gen.anchors_orig',
                                                  os.path.join(HERE, 'orig', 'anchors.py'))
    old = importlib.util.module_from_spec(spec)
    sys.modules['modifc_gen.anchors_orig'] = old
    spec.loader.exec_module(old)
    rows = []
    for rel in BUILDER_MODELS:
        geom._READ.clear(); gc.collect()
        scene = Scene(ROOT + rel)
        products = [e for fam in ('wall', 'door', 'window') for e in scene.elements(fam)
                    if scene.bounded_spaces(e)]
        random.Random(0).shuffle(products)
        for product in products[:per_model]:
            fam = scene.family_of(product)
            built = anchors.opposite_anchors(scene, product, random.Random(1), limit=1)
            before = old.opposite_anchors(scene, product, random.Random(1), limit=1)
            before = [a for a in before if old.unique_anchor([a], scene, product.GlobalId)]
            row = {'model': rel, 'family': fam, 'target': product.GlobalId,
                   'anchor': built[0].as_record() if built else None,
                   'old_yield': bool(before)}
            if built:
                a = built[0]
                row['gen'] = a.resolve(scene)
                try:
                    row['lib'] = geom.find_opposite(scene.by_guid(a.params['reference_guid']),
                                                    FAMILY_CLASS[fam],
                                                    scene.by_guid(a.params['space_guid'])).GlobalId
                except LookupError as ex:
                    row['lib'] = None; row['lib_error'] = str(ex)
                ref_dir = geom.plan_direction(scene.by_guid(a.params['reference_guid']))
                tgt_dir = geom.plan_direction(product)
                row['cos'] = abs(float(np.dot(ref_dir, tgt_dir)))
            rows.append(row)
    _BUILDER = rows
    return rows


def test_6_builder_anchors_resolve_to_their_target_in_both_rules():
    rows = builder_results()
    built = [r for r in rows if r['anchor']]
    assert built, 'the builder wrote no anchor at all'
    bad = [(r['model'][-30:], r['target'], r['gen'], r['lib']) for r in built
           if not (r['gen'] == [r['target']] and r['lib'] == r['target'])]
    assert not bad, bad[:10]
    assert all(r['cos'] >= 0.9 for r in built)


if __name__ == '__main__':
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith('test_') and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print('PASS', name)
        except AssertionError as ex:
            failed += 1
            print('FAIL', name, str(ex)[:600])
    res = results()
    n_no = sum(answer(x) is None for x in res.values())
    n_tie = sum(len(x['gen']) > 1 for x in res.values())
    b = builder_results()
    print('builder: %d products tried, %d anchors written (old builder: %d unique anchors)' % (
        len(b), sum(bool(r['anchor']) for r in b), sum(r['old_yield'] for r in b)))
    print('rows %d; no answer %d (ties %d); generator/library agree %d' % (
        len(res), n_no, n_tie,
        sum((len(x['gen']) == 1 and x['gen'] == [x['lib']]) or (len(x['gen']) != 1 and x['lib'] is None)
            for x in res.values())))
    sys.exit(1 if failed else 0)
