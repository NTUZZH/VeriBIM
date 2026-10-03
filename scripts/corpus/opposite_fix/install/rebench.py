"""VeriBIM-Bench v4 -> v4b repair under the corrected "opposite" rule.

  --dry-run  loads the FIXED modules from ../ (fixload), plans everything and builds
             every new gold, writing only under install/dry_run/bench_v4b/.
  --real     run AFTER the install; loads code/ and asserts it
             equals the tested fixed copies (OPPOSITE_FIX_USE_INSTALLED=1), redoes
             the same work, asserts the result equals the dry-run plan (same drops,
             re-golds, replacements and gold sha256), and writes NEW files next to
             the originals: runs_local/bench_v4/{tasks.v4b.jsonl, tasks_<V>.v4b.jsonl,
             subset_108_<V>.v4b.json, subset_324.v4b.json, manifest.v4b.json,
             REPAIR_REPORT.txt} and the new directory runs_local/bench_v4/models_v4b/.
             Nothing existing is overwritten (the script refuses first).

Policy:
  * every opposite anchor of the 2,100 tasks is re-resolved with the corrected rule
    and the result must equal ../reresolve_report.json;
  * unchanged tasks keep everything;
  * a changed task whose instruction still holds for the new element is re-golded:
    re-planned on the new element with the generator's rules and passed through
    generate.produce (see regold.py); its gold goes to models_v4b/<id>.v4b.ifc.gz
    and its record's gold path becomes models_v4b/<id>.v4b.ifc, so no gold cache
    keyed on the old name can serve the old gold;
  * a task with no answer, a contradicted instruction, or a re-gold the generator's
    rules refuse is dropped and replaced by a candidate of the same cell
    (ifc_version, tier, operation, category), never one carrying an opposite anchor,
    never an excluded candidate (unstated door/window type, create_box with
    touching_slab_above / fits_gap, translate with null-edit > 0.8), never an IFC4X3
    create chain; preference order: null-edit 0, same building, same edit kind, same
    element family, most shared requirement families; ties drawn with seed 20260934;
  * a dropped task's hosted-subset slot, if any, goes to its replacement.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import random
import resource
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixcommon import (BENCH, DRY, FIXDIR, GEN, INSTALL, ROOT, Log, carries_opposite, gzip_with_sha,  # noqa: E402
                       read_jsonl, refuse_existing, reresolve, setup_code, sha256_file, sha256_gunzip,
                       write_json, write_jsonl)

VERSIONS = ('IFC2X3', 'IFC4', 'IFC4X3')
SEED = 20260934
POOLS = ROOT / 'runs_local/corpus_v10/migrator_v2'
INPUTS = ['tasks.jsonl'] + [f'tasks_{v}.jsonl' for v in VERSIONS] + \
         [f'subset_108_{v}.json' for v in VERSIONS] + ['subset_324.json', 'manifest.json']


def v4b_name(name: str) -> str:
    stem, ext = name.rsplit('.', 1)
    return f'{stem}.v4b.{ext}'


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--real', action='store_true')
    ap.add_argument('--keep-ifc', action='store_true', help='keep uncompressed golds in the work dir')
    args = ap.parse_args()
    t0 = time.time()
    log = Log()
    # INSTALL_REHEARSAL=<dir>: run the real-mode path before the install, on the
    # fixed copies, writing under <dir> instead of runs_local/ (used once to test
    # this script; not part of the install).
    reh = os.environ.get('INSTALL_REHEARSAL')
    mode = 'fixed' if (args.dry_run or reh) else 'installed_fixed'
    code = setup_code(mode)
    log(f'mode {"dry-run" if args.dry_run else "REAL"}; code {mode}: {code["anchors_file"]}, {code["geom_file"]}')

    out_dir = DRY / 'bench_v4b' if args.dry_run else (Path(reh) / 'bench_v4' if reh else BENCH)
    models_dir = out_dir / 'models_v4b'
    work = DRY / 'bench_work' if args.dry_run else (Path(reh) / 'work_bench' if reh else INSTALL / 'real_work' / 'bench')
    outputs = [out_dir / v4b_name(n) for n in INPUTS] + [out_dir / 'REPAIR_REPORT.txt']
    if args.real:
        refuse_existing(outputs + [models_dir])
        plan_dry = json.load(open(DRY / 'bench_v4b' / 'plan.json'))
    else:
        if out_dir.exists():
            shutil.rmtree(out_dir)
        if work.exists():
            shutil.rmtree(work)
    out_dir.mkdir(parents=True, exist_ok=True)
    models_dir.mkdir(parents=True, exist_ok=False if args.real else True)
    work.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------ inputs
    input_sha = {n: sha256_file(BENCH / n) for n in INPUTS}
    if args.real:
        assert input_sha == plan_dry['input_sha256'], 'bench v4 inputs changed since the dry run'
    parts = {v: read_jsonl(BENCH / f'tasks_{v}.jsonl') for v in VERSIONS}
    alltasks = read_jsonl(BENCH / 'tasks.jsonl')
    assert [t['task_id'] for t in alltasks] == [t['task_id'] for v in VERSIONS for t in parts[v]]
    by_id = {t['task_id']: t for t in alltasks}
    subsets = {v: json.load(open(BENCH / f'subset_108_{v}.json')) for v in VERSIONS}
    s324 = json.load(open(BENCH / 'subset_324.json'))
    assert s324 == subsets['IFC2X3'] + subsets['IFC4'] + subsets['IFC4X3']
    manifest = json.load(open(BENCH / 'manifest.json'))
    log(f'inputs: {len(alltasks)} tasks, subsets {[len(subsets[v]) for v in VERSIONS]} / {len(s324)}')

    # ------------------------------------------------ re-resolution, checked
    rows = reresolve(alltasks, code)
    stored = [x for x in json.load(open(FIXDIR / 'reresolve_report.json')) if x['split'] == 'bench_v4']
    mine = {x['task_id']: (x['class'], x['new_gold'], x['instruction_consistent']) for x in rows}
    theirs = {x['task_id']: (x['class'], [g[0] for g in x['new_gold']], x['instruction_consistent']) for x in stored}
    assert mine == theirs, 'the re-resolution differs from reresolve_report.json'
    assert all(x['generator_library_agree'] for x in rows)
    cls = Counter(x['class'] for x in rows)
    log(f're-resolution: {len(rows)} tasks with an opposite anchor: {dict(cls)}; equals reresolve_report.json; '
        f'generator and library agree on {len(rows)}/{len(rows)}')
    drop = {x['task_id']: ('no answer under the corrected rule' if x['class'] == 'no answer'
                           else 'instruction contradicts the new element: ' + x['consistency_note'])
            for x in rows if x['class'] == 'no answer' or (x['class'] == 'changed' and not x['instruction_consistent'])}
    regold_ids = sorted(x['task_id'] for x in rows if x['class'] == 'changed' and x['instruction_consistent'])
    new_gold = {x['task_id']: x['new_gold'][0] for x in rows if x['class'] == 'changed'}

    # --------------------------------------------------------------- re-gold
    from modifc_gen import settings
    from modifc_score.model_cache import MeshCache, ModelCache
    import regold as rg
    models_cache, meshes_cache = ModelCache(capacity=2), MeshCache()
    regolded, gz_info = {}, {}
    for tid in regold_ids:
        rec = by_id[tid]
        ws = json.load(open(GEN / f'bench_{rec["ifc_version"].lower()}' / 'funnel.json'))['wave_settings']
        settings.configure(**ws)
        t1 = time.time()
        new, gold, note = rg.regold(code, rec, new_gold[tid], work / tid, models_cache, meshes_cache)
        models_cache.clear() if hasattr(models_cache, 'clear') else None
        if new is None:
            drop[tid] = 're-gold refused by the generator rules: ' + note
            log(f're-gold {tid}: REFUSED ({note}); dropped and replaced')
            continue
        rel = f'runs_local/bench_v4/models_v4b/{tid}.v4b.ifc'
        new['ground_truth_ifc'] = rel
        new['gold_model'] = rel
        info = gzip_with_sha(gold, models_dir / f'{tid}.v4b.ifc.gz')
        assert info['sha256'] == new['verification']['gold_sha256']
        if not args.keep_ifc:
            os.remove(gold)
        regolded[tid] = new
        gz_info[tid] = dict(info, gz=f'models_v4b/{tid}.v4b.ifc.gz', check='sha256 (generator funnel)')
        v = new['verification']
        log(f're-gold {tid}: accepted in {time.time() - t1:.0f}s; target {rec["target"]["guids"]} -> '
            f'{new["target"]["guids"]}; self-score {v["self_score"]["final"]}; null-edit {v.get("null_edit_score")}; '
            f'gold {info["sha256"][:12]} ({info["bytes"] / 1e6:.1f} MB, gz {info["gz_bytes"] / 1e6:.1f} MB)'
            + (f'; {note}' if note else ''))

    # ----------------------------------------------------------- replacements
    spec = importlib.util.spec_from_file_location('select_bench_v4', ROOT / 'scripts/benchmark/select_bench_v4.py')
    sel = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sel)
    drv = sel.drv
    from modifc_gen.build_e2 import NULL_CAP
    from modifc_gen import verify, materialize
    targets = frozenset(drv.TARGET_FAMILIES) - {'ref.relative.opposite'}
    used = set(by_id)
    rng = random.Random(SEED)
    replacement, why_pick, rejected_picks = {}, {}, {}
    pools = {}
    for v in VERSIONS:
        pool = json.load(open(POOLS / f'pool_bench_v10_{v}.json'))
        origin = {m['key']: m for m in pool['models']}
        cand = read_jsonl(GEN / f'bench_candidates_v10_{v}.jsonl')
        keep = []
        for t in cand:
            if sel.unstated_type(t):
                continue
            if t.get('edit_kind') == 'create_box' and set(t.get('families') or ()) & sel.BAD_FAMILIES:
                continue
            if t.get('tier') == 'single' and drv.kind(t) == 'translate' and drv.floor_of(t) > NULL_CAP:
                continue
            if drv.floor_of(t) > NULL_CAP:
                continue
            if carries_opposite(t):
                continue
            if v == 'IFC4X3' and t.get('tier') == 'compositional' and t.get('operation') == 'create':
                continue
            keep.append(t)
        pools[v] = (keep, origin)
    dropped_sorted = sorted(drop, key=lambda i: (VERSIONS.index(by_id[i]['ifc_version']), i))
    Scene = code['Scene']
    for tid in dropped_sorted:
        d = by_id[tid]
        v = d['ifc_version']
        keep, origin = pools[v]
        dfam = set(d.get('families') or ()) & targets
        attr = drv.kind(d) in drv.ATTR
        rejected_picks[tid] = []
        while True:
            cell = [t for t in keep if t['task_id'] not in used and t['tier'] == d['tier']
                    and t['operation'] == d['operation'] and t['category'] == d['category']
                    and (drv.kind(t) in drv.ATTR) == attr]
            if not cell:
                raise SystemExit(f'no candidate left in the cell of {tid}')

            def key(t):
                return (drv.floor_of(t) > 0.0, t['building_id'] != d['building_id'], drv.kind(t) != drv.kind(d),
                        t['family'] != d['family'], -len(set(t.get('families') or ()) & dfam))
            best = min(key(t) for t in cell)
            tied = sorted((t for t in cell if key(t) == best), key=lambda t: t['task_id'])
            pick = rng.choice(tied)
            used.add(pick['task_id'])
            # checks under the loaded (corrected) code: the anchor resolves to its
            # element, and the gold rebuilds to its checksum
            problem = None
            sc = Scene(str(ROOT / pick['input_ifc']))
            try:
                from modifc_gen import anchors as anchor_lib
                if not pick.get('clarification'):
                    a = pick['anchor']
                    st = verify.check_anchor(sc, anchor_lib.from_record(a), a.get('expected') or ())
                    if not st.ok:
                        problem = 'anchor check under the corrected code: ' + st.reason
            finally:
                code['geom']._READ.clear()
                sc = None
            if problem is None:
                target = work / 'repl' / f'{pick["task_id"]}.ifc'
                rb = materialize.rebuild(pick, ROOT, target, True)
                if not rb.ok:
                    problem = f'gold rebuild: {rb.check} {rb.reason}'
                else:
                    if pick['ifc_version'] != 'IFC2X3' and sel.door_window_task(pick):
                        import ifcopenshell
                        f = ifcopenshell.open(str(target))
                        for gg in (pick.get('edit_guids') or {}).get('created') or ():
                            try:
                                e = f.by_guid(gg)
                            except Exception:
                                continue
                            if (e.is_a('IfcDoor') or e.is_a('IfcWindow')) and \
                                    getattr(e, 'PredefinedType', None) not in (None, ) and \
                                    e.PredefinedType not in (pick.get('instruction') or ''):
                                problem = 'created filling carries an unstated PredefinedType'
                        f = None
            if problem:
                rejected_picks[tid].append([pick['task_id'], problem])
                log(f'replacement for {tid}: candidate {pick["task_id"]} rejected ({problem}); drawing again')
                continue
            info = gzip_with_sha(target, models_dir / f'{pick["task_id"]}.ifc.gz')
            assert info['sha256'] == pick['verification']['gold_sha256']
            if not args.keep_ifc:
                os.remove(target)
            e = origin[pick['source_model']['key']]
            assert e['building_id'] == pick['building_id'] and e['schema'] == v == pick['ifc_version']
            assert pick.get('origin') == e['origin'], (pick['task_id'], pick.get('origin'), e['origin'])
            r = dict(pick)
            r['split'] = drv.SPLIT
            r['ifc_version'] = v
            r['origin'] = e['origin']
            r['bench_part'] = v
            replacement[tid] = r
            gz_info[r['task_id']] = dict(info, gz=f'models_v4b/{r["task_id"]}.ifc.gz', check=rb.check)
            why_pick[tid] = {'cell': f'{v} {d["tier"]} {d["operation"]}/{d["category"]}', 'cell_candidates': len(cell),
                             'tied_at_best': len(tied), 'same_building': not best[1], 'same_edit_kind': not best[2],
                             'same_family': not best[3], 'shared_requirement_families': -best[4],
                             'null_edit': drv.nes(r)}
            log(f'replacement for {tid} ({why_pick[tid]["cell"]}, {d["edit_kind"]}, {d["building_id"]}): '
                f'{r["task_id"]} ({r["edit_kind"]}, {r["building_id"]}); {len(cell)} in cell, {len(tied)} tied at best; '
                f'gold {rb.check} ok, {info["bytes"] / 1e6:.1f} MB (gz {info["gz_bytes"] / 1e6:.1f} MB)')
            break

    # --------------------------------------------------------------- assemble
    new_parts = {}
    for v in VERSIONS:
        rows_v = []
        for t in parts[v]:
            tid = t['task_id']
            if tid in replacement:
                rows_v.append(replacement[tid])
            elif tid in regolded:
                rows_v.append(regolded[tid])
            else:
                rows_v.append(t)
        rows_v.sort(key=lambda t: t['task_id'])
        new_parts[v] = rows_v
    new_all = [t for v in VERSIONS for t in new_parts[v]]
    ids = [t['task_id'] for t in new_all]
    assert len(ids) == len(set(ids)) == 2100
    assert not (set(drop) & set(ids))
    new_subsets = {v: [replacement[i]['task_id'] if i in replacement else i for i in subsets[v]] for v in VERSIONS}
    new_s324 = new_subsets['IFC2X3'] + new_subsets['IFC4'] + new_subsets['IFC4X3']
    assert len(set(new_s324)) == 324 and set(new_s324) <= set(ids)
    moved_slots = {i: replacement[i]['task_id'] for i in replacement if i in set(s324)}

    # layer (requirement-family) cells before and after, per part
    fam_before, fam_after = {}, {}
    for v in VERSIONS:
        cb = Counter(f for t in parts[v] for f in set(t.get('families') or ()) if f in drv.TARGET_FAMILIES)
        ca = Counter(f for t in new_parts[v] for f in set(t.get('families') or ()) if f in drv.TARGET_FAMILIES)
        fam_before[v], fam_after[v] = cb, ca
    changed_fam = {v: {f: [fam_before[v][f], fam_after[v][f]] for f in sorted(set(fam_before[v]) | set(fam_after[v]))
                       if fam_before[v][f] != fam_after[v][f]} for v in VERSIONS}

    # sanity: every opposite anchor left in v4b resolves to its stored gold under the loaded rule
    left = reresolve(new_all, code)
    bad_left = [x['task_id'] for x in left if x['class'] != 'unchanged']
    assert not bad_left, bad_left
    log(f'v4b: {len(left)} tasks with an opposite anchor remain, all resolve to their stored gold under the corrected rule')

    plan = {'input_sha256': input_sha,
            'dropped': {i: drop[i] for i in dropped_sorted},
            'replacements': {i: replacement[i]['task_id'] for i in dropped_sorted},
            'regolded': {i: {'old_target': by_id[i]['target']['guids'], 'new_target': regolded[i]['target']['guids'],
                             'anchor_old': by_id[i]['anchor']['expected'], 'anchor_new': regolded[i]['anchor']['expected'],
                             'old_gold_sha256': by_id[i]['verification']['gold_sha256'],
                             'new_gold_sha256': regolded[i]['verification']['gold_sha256']} for i in sorted(regolded)},
            'unchanged_opposite': sorted(x['task_id'] for x in rows if x['class'] == 'unchanged'),
            'gold_files': gz_info, 'why_pick': why_pick, 'rejected_picks': rejected_picks,
            'subset_slots_moved': moved_slots, 'layer_family_changes': changed_fam}
    if args.real:
        for k in ('dropped', 'replacements', 'regolded', 'unchanged_opposite', 'subset_slots_moved'):
            assert plan[k] == plan_dry[k], f'real run differs from the dry run in {k}'
        for k, e in plan['gold_files'].items():
            assert e['sha256'] == plan_dry['gold_files'][k]['sha256'], k

    # manifest
    mrows = {r['task_id']: r for r in manifest['tasks']}
    insub = set(new_s324)
    new_rows = []
    for t in new_all:
        tid = t['task_id']
        if tid in mrows and tid not in regolded:
            r = dict(mrows[tid])
            r['in_subset_108'] = tid in insub
        else:
            gi = gz_info[tid]
            r = {'task_id': tid, 'ifc_version': t['ifc_version'], 'bench_part': t['bench_part'],
                 'origin': t['origin'], 'building_id': t['building_id'], 'source_key': t['source_model']['key'],
                 'operation': t['operation'], 'category': t['category'], 'tier': t['tier'],
                 'edit_kind': t.get('edit_kind'), 'families': t.get('families') or [],
                 'source_file': t['input_ifc'], 'source_relpath': t['source_relpath'],
                 'source_sha256': t['source_model']['sha256'],
                 'gold_sha256': (t.get('verification') or {}).get('gold_sha256'),
                 'gold_sha256_rebuilt': gi['sha256'], 'gold_check': gi['check'].split(' ')[0],
                 'gold_model_gz': gi['gz'], 'null_edit_score': (t.get('verification') or {}).get('null_edit_score'),
                 'in_subset_108': tid in insub}
        new_rows.append(r)
    m2 = json.loads(json.dumps(manifest))
    m2['name'] = manifest['name'] + ' -- v4b repair (corrected opposite rule)'
    m2['tasks_file'] = str(BENCH / 'tasks.v4b.jsonl')
    m2['part_files'] = {v: {'path': str(BENCH / f'tasks_{v}.v4b.jsonl')} for v in VERSIONS}
    m2['subset']['files'] = [f'subset_108_{v}.v4b.json' for v in VERSIONS] + ['subset_324.v4b.json']
    m2['gold_models'] = ('models/<task_id>.ifc.gz for tasks kept from v4; models_v4b/<task_id>.ifc.gz for '
                         'replacement tasks; models_v4b/<task_id>.v4b.ifc.gz for re-golded tasks (gzip of the '
                         'checksummed gold bytes)')
    m2['buildings'] = sorted({t['building_id'] for t in new_all})
    for v in VERSIONS:
        P = new_parts[v]
        floors = [drv.nes(t) for t in P if drv.nes(t) is not None]
        p = m2['parts'][v]
        p['n'] = len(P)
        p['by_cell_all_tiers'] = {f'{o}/{c}': sum(1 for t in P if t['operation'] == o and t['category'] == c)
                                  for o in sel.OPS for c in sel.CATS}
        p['by_cell_single'] = {f'{o}/{c}': sum(1 for t in P if t['tier'] == 'single' and t['operation'] == o
                                                and t['category'] == c) for o in sel.OPS for c in sel.CATS}
        p['chains_by_cell'] = dict(sorted(Counter(f"{t['operation']}/{t['category']}" for t in P
                                                  if t['tier'] == 'compositional').items()))
        p['by_tier'] = dict(Counter(t['tier'] for t in P))
        p['by_origin'] = dict(Counter(t['origin'] for t in P))
        p['by_building'] = dict(sorted(Counter(t['building_id'] for t in P).items()))
        p['by_building_origin'] = {f'{b}/{o}': c for (b, o), c in
                                   sorted(Counter((t['building_id'], t['origin']) for t in P).items())}
        p['null_edit_floor_mean'] = round(sum(floors) / len(floors), 4)
        p['tasks_without_a_floor'] = len(P) - len(floors)
        p['null_edit_share_gt_0.8'] = round(sum(1 for x in floors if x > NULL_CAP) / len(floors), 4)
        p['high_floor_share'] = round(sum(1 for t in P if drv.kind(t) in drv.ATTR) / len(P), 4)
        p['subset_108'] = {'n': len(new_subsets[v]),
                           'by_building': dict(sorted(Counter(t['building_id'] for t in P if t['task_id'] in insub).items())),
                           'by_origin': dict(Counter(t['origin'] for t in P if t['task_id'] in insub)),
                           'by_tier': dict(Counter(t['tier'] for t in P if t['task_id'] in insub))}
        p['layer_family_cells_v4b'] = {f: fam_after[v][f] for f in drv.TARGET_FAMILIES}
    m2['tasks'] = new_rows
    m2['repair'] = {
        'version': 'v4b', 'date': time.strftime('%Y-%m-%d'), 'decision': 'corrected opposite rule',
        'rule': ('the element of the family bounding the space that runs parallel to the reference (|cos| >= 0.9; '
                 'doors and windows take their host wall direction) and whose centre lies more than 0.25 m past the '
                 'room centre on the far side along the reference normal; longest stretch facing the reference inside '
                 'the room first, then nearest; no such element means no gold'),
        'code': {'anchors.py': sha256_file(code['anchors_file']), 'veribim_geom.py': sha256_file(code['geom_file'])},
        'opposite_tasks_in_v4': len(rows), 'unchanged': len(plan['unchanged_opposite']),
        'dropped_ids': list(plan['dropped']), 'dropped_reasons': plan['dropped'],
        'replacement_ids': plan['replacements'], 'regolded_ids': sorted(regolded),
        'regolded': plan['regolded'], 'replacement_seed': SEED,
        'replacement_rule': ('same ifc_version, tier, operation, category and high-floor status; never an opposite '
                             'anchor or an excluded candidate; preference: null-edit 0, same building, same edit '
                             'kind, same element family, most shared requirement families; ties drawn with the seed'),
        'subset_slots_moved': moved_slots,
        'layer_family_changes': changed_fam,
        'v4_manifest_sha256': input_sha['manifest.json'],
    }
    sha_files = {}
    write_jsonl(out_dir / 'tasks.v4b.jsonl', new_all)
    for v in VERSIONS:
        write_jsonl(out_dir / f'tasks_{v}.v4b.jsonl', new_parts[v])
        json.dump(new_subsets[v], open(out_dir / f'subset_108_{v}.v4b.json', 'w'), indent=0)
        sha_files[f'tasks_{v}.v4b.jsonl'] = sha256_file(out_dir / f'tasks_{v}.v4b.jsonl')
    json.dump(new_s324, open(out_dir / 'subset_324.v4b.json', 'w'), indent=0)
    m2['tasks_sha256'] = sha256_file(out_dir / 'tasks.v4b.jsonl')
    for v in VERSIONS:
        m2['part_files'][v]['sha256'] = sha_files[f'tasks_{v}.v4b.jsonl']
    write_json(out_dir / 'manifest.v4b.json', m2)
    # gz files: re-read every one and check the checksum once more
    for tid, gi in gz_info.items():
        assert sha256_gunzip(out_dir / gi['gz']) == gi['sha256'], tid
    if args.dry_run:
        write_json(out_dir / 'plan.json', plan)

    # --------------------------------------------------------------- report
    L = ['VeriBIM-Bench v4b: repair of v4 under the corrected "opposite" rule',
         f'Written {time.strftime("%Y-%m-%d %H:%M")} by scripts/corpus/opposite_fix/install/rebench.py '
         f'({"dry run, fixed modules loaded from opposite_fix/" if args.dry_run else "real run, installed code checked equal to the tested fixed copies"}).',
         '', 'RULE', '  ' + m2['repair']['rule'], '',
         'RE-RESOLUTION', f'  {len(rows)} tasks carry an opposite anchor: unchanged {cls["unchanged"]}, changed '
         f'{cls["changed"]}, no answer {cls["no answer"]} (equal to reresolve_report.json).',
         f'  Kept as they are: {len(plan["unchanged_opposite"])}.',
         '', f'RE-GOLDED ({len(regolded)}); instruction, anchor phrase and seed unchanged, new gold from the generator funnel']
    for i, e in plan['regolded'].items():
        L.append(f'  {i}: target {e["old_target"]} -> {e["new_target"]}; gold {e["old_gold_sha256"][:12]} -> '
                 f'{e["new_gold_sha256"][:12]}; file {gz_info[i]["gz"]}')
    L += ['', f'DROPPED ({len(drop)}) AND REPLACED (seed {SEED})']
    for i in dropped_sorted:
        w = why_pick[i]
        L.append(f'  {i} -> {replacement[i]["task_id"]}  [{w["cell"]}; {w["cell_candidates"]} candidates, {w["tied_at_best"]} '
                 f'tied at best; same building {w["same_building"]}, same edit kind {w["same_edit_kind"]}, same family '
                 f'{w["same_family"]}, shared families {w["shared_requirement_families"]}, null-edit {w["null_edit"]}]')
        L.append(f'      reason: {drop[i]}')
        for c, p in rejected_picks[i]:
            L.append(f'      candidate {c} rejected: {p}')
    L += ['', 'HOSTED SUBSETS', f'  slots moved to a replacement: {moved_slots or "none (no dropped task was in a subset)"}',
          f'  re-golded tasks in a subset: {sorted(i for i in regolded if i in set(s324))}',
          '', 'REQUIREMENT-FAMILY (LAYER) CELLS THAT CHANGED, per part [v4, v4b]; quota 12']
    for v in VERSIONS:
        L.append(f'  {v}: {changed_fam[v]}')
    L += ['  Every family below 12 in v4b: ' + json.dumps({v: {f: n for f, n in fam_after[v].items()
                                                              if f in drv.TARGET_FAMILIES and n < drv.LAYER_QUOTA
                                                              and fam_before[v][f] >= drv.LAYER_QUOTA}
                                                          for v in VERSIONS}),
          '  (families already below 12 in v4 are not listed; they were short in the candidates)',
          '', 'FILES']
    for n in INPUTS:
        L.append(f'  {v4b_name(n)}  (from {n}, sha256 {input_sha[n][:16]}...)')
    L.append(f'  models_v4b/: {len(gz_info)} gzip gold models, sha256 of the uncompressed bytes checked after writing')
    L += ['', f'Wall time {time.time() - t0:.0f} s; peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB.']
    (out_dir / 'REPAIR_REPORT.txt').write_text('\n'.join(L) + '\n')
    (out_dir / 'rebench_run.log' if args.dry_run else work / 'rebench_real.log').write_text('\n'.join(log.lines) + '\n')
    print('\n'.join(L))


if __name__ == '__main__':
    main()
