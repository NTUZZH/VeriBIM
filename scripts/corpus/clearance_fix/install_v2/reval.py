"""val-500 v3 -> v3b repair under the corrected "opposite" rule.

  --dry-run  fixed modules loaded from ../ (fixload); writes only under install/dry_run/val_v3b/.
  --real     after the install; code/ is checked equal to the tested fixed copies; the plan
             must equal the dry run's; writes NEW files next to the originals in
             runs_local/stage_a_v10/: val_tasks_500_v3b.jsonl, val_subset_500_v3b.json,
             val_tasks_100_v3b.jsonl, val_subset_100_v3b.json, val_v3b_repair.json.
             Refuses if any of them exists.

What it does:
  1. re-resolves every opposite anchor of the 500 tasks with the loaded rule and lists
     every task whose gold changes (class changed / no answer);
  2. a task that loses its gold (no answer, or the instruction contradicts the new
     element) is replaced from the pool build_val_v3.py drew its version from
     (IFC2X3: canonical v2 validation split, IFC2X3 sources; IFC4 / IFC4X3:
     gen/val_tasks_v10.jsonl), same stratum (operation, category, tier) as
     build_val_v3.py stratifies, no opposite anchor, no unstated door/window type,
     not already in val-500; preference: same building, same edit kind, same
     element family; ties drawn with seed 20260935.  The replacement's anchor is
     checked with the loaded code and its gold is rebuilt to its checksum;
  3. the replacement takes the dropped task's position in val-500 (and in val-100 if
     the dropped task was there).
  4. filling clearance: every val-500 task the clearance screen flagged
     (clearance_fix/flagged_val500.jsonl; the one flagged val-100 task is among them) is
     dropped and replaced the same way, after the opposite drops so their draws are
     unchanged; a candidate whose edit places a door or window is accepted only if
     clearance_fix/clearance_check.py passes it on the gold rebuilt here.  A changed task whose instruction still holds would
     be reported for re-golding; there is none in val-500 v3 (the script stops if one
     appears, since no re-gold path is prepared for val).
"""
from __future__ import annotations

import argparse
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
from fixcommon import (CLEAR, DRY, FIXDIR, GEN, INSTALL, ROOT, STAGE_A, Log, carries_opposite, read_jsonl,  # noqa: E402
                       refuse_existing, reresolve, setup_code, sha256_file, write_json, write_jsonl)
import importlib.util  # noqa: E402


def load_clearance():
    spec = importlib.util.spec_from_file_location('clearance_check', ROOT / 'scripts/corpus/clearance_fix/clearance_check.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

SEED = 20260935
NAMES = {'t500': 'val_tasks_500_v3.jsonl', 's500': 'val_subset_500_v3.json',
         't100': 'val_tasks_100_v3.jsonl', 's100': 'val_subset_100_v3.json'}


def affected(t):
    """build_val_v3.py's filter, verbatim."""
    if t.get('edit_kind') not in ('create_filling', 'replace_filling'):
        return False
    p = (t.get('edit_params') or {}).get('predefined_type')
    return p is not None and p not in (t.get('instruction') or '')


def stratum(t):
    return (t['operation'], t['category'], t.get('tier', 'single'))


def pool_for(version):
    """The pool build_val_v3.py drew this version from, with its field additions."""
    out = []
    if version == 'IFC2X3':
        for l in open(ROOT / 'runs_local/wave_v2/canonical_v2/tasks_validation.jsonl'):
            t = json.loads(l)
            if (t.get('source_model') or {}).get('schema') == 'IFC2X3' and not affected(t):
                t['ifc_version'] = 'IFC2X3'
                t['origin'] = 'native'
                out.append(t)
    else:
        for l in open(GEN / 'val_tasks_v10.jsonl'):
            t = json.loads(l)
            if t['ifc_version'] == version and not affected(t):
                out.append(t)
    return out


def v3b(name):
    return name.replace('_v3.', '_v3b.')


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--real', action='store_true')
    args = ap.parse_args()
    t0 = time.time()
    log = Log()
    reh = os.environ.get('INSTALL_REHEARSAL')   # see rebench.py; test of the real path only
    mode = 'fixed' if (args.dry_run or reh) else 'installed_fixed'
    code = setup_code(mode)
    log(f'mode {"dry-run" if args.dry_run else "REAL"}; code {mode}: {code["anchors_file"]}, {code["geom_file"]}')
    out_dir = DRY / 'val_v3b' if args.dry_run else (Path(reh) / 'stage_a_v10' if reh else STAGE_A)
    work = DRY / 'val_work' if args.dry_run else (Path(reh) / 'work_val' if reh else INSTALL / 'real_work' / 'val')
    outputs = [out_dir / v3b(n) for n in NAMES.values()] + [out_dir / 'val_v3b_repair.json']
    if args.real:
        refuse_existing(outputs)
        plan_dry = json.load(open(DRY / 'val_v3b' / 'val_v3b_repair.json'))
    else:
        for d in (out_dir, work):
            if d.exists():
                shutil.rmtree(d)
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)

    input_sha = {n: sha256_file(STAGE_A / n) for n in NAMES.values()}
    input_sha['clearance_drops_val500'] = sha256_file(CLEAR / 'flagged_val500.jsonl')
    input_sha['clearance_drops_val100'] = sha256_file(CLEAR / 'flagged_val100.jsonl')
    input_sha['clearance_check.py'] = sha256_file(ROOT / 'scripts/corpus/clearance_fix/clearance_check.py')
    cc = load_clearance()
    if args.real:
        assert input_sha == plan_dry['input_sha256'], 'val v3 inputs changed since the dry run'
    t500, t100 = read_jsonl(STAGE_A / NAMES['t500']), read_jsonl(STAGE_A / NAMES['t100'])
    s500, s100 = json.load(open(STAGE_A / NAMES['s500'])), json.load(open(STAGE_A / NAMES['s100']))
    assert [t['task_id'] for t in t500] == s500 and [t['task_id'] for t in t100] == s100
    by_id = {t['task_id']: t for t in t500}
    assert all(by_id[t['task_id']] == t for t in t100), 'val-100 records differ from val-500 records'

    # 1. every opposite anchor, re-resolved
    rows = reresolve(t500, code)
    cls = Counter(x['class'] for x in rows)
    stored = {x['task_id']: x['class'] for x in json.load(open(FIXDIR / 'reresolve_report.json'))
              if x['split'] == 'val500_v3'}
    assert {x['task_id']: x['class'] for x in rows} == stored, 'differs from reresolve_report.json'
    assert all(x['generator_library_agree'] for x in rows)
    log(f'val-500 v3: {len(rows)} tasks carry an opposite anchor: {dict(cls)} (equals reresolve_report.json)')
    for x in rows:
        log(f'  {x["task_id"]:30s} {x["class"]:9s} old {x["old_gold"]} new {x["new_gold"]}'
            + ('' if x['class'] == 'unchanged' else f'; instruction holds: {x["instruction_consistent"]} ({x["consistency_note"]})')
            + ('' if x['anchor_in_instruction'] else '  [anchor only, not in the instruction]'))
    changed = [x for x in rows if x['class'] != 'unchanged']
    regold = [x['task_id'] for x in changed if x['class'] == 'changed' and x['instruction_consistent']]
    if regold:
        raise SystemExit(f'val tasks that would need a re-gold (no path prepared): {regold}')
    drop = {x['task_id']: ('no answer under the corrected rule' if x['class'] == 'no answer'
                           else 'instruction contradicts the new element: ' + x['consistency_note']) for x in changed}
    opposite_order = sorted(drop)
    # filling clearance
    flag500 = {r['task_id']: r for r in read_jsonl(CLEAR / 'flagged_val500.jsonl')}
    flag100 = {r['task_id'] for r in read_jsonl(CLEAR / 'flagged_val100.jsonl')}
    assert set(flag500) <= set(s500) and flag100 <= set(s100) and flag100 <= set(flag500)
    clearance_dropped = []
    for tid, fr in sorted(flag500.items()):
        if tid in drop:
            continue
        f = next(x for x in fr['fillings'] if x.get('flag'))
        o = f['offending']
        drop[tid] = (f'filling clearance: {f["class"]} {f["guid"]} ({f["how"]}) opens into {o["class"]} '
                     f'{o["guid"]} ({o.get("name")}) at {f["distance_m"]} m')
        clearance_dropped.append(tid)
    log(f'filling clearance: {len(flag500)} flagged val-500 tasks ({len(flag100)} of them in val-100), '
        f'{len(clearance_dropped)} dropped for clearance')
    drop_order = opposite_order + sorted(clearance_dropped)

    # 2. replacements
    from modifc_gen import anchors as anchor_lib, materialize, verify
    rng = random.Random(SEED)
    used = set(s500)
    replacement, why, rejected = {}, {}, {}
    Scene = code['Scene']
    for tid in drop_order:
        d = by_id[tid]
        pool = [t for t in pool_for(d['ifc_version']) if stratum(t) == stratum(d) and not carries_opposite(t)]
        rejected[tid] = []
        while True:
            cand = [t for t in pool if t['task_id'] not in used]
            if not cand:
                raise SystemExit(f'no candidate left for {tid}')

            def key(t):
                return (t['building_id'] != d['building_id'], t.get('edit_kind') != d.get('edit_kind'),
                        t.get('family') != d.get('family'))
            best = min(key(t) for t in cand)
            tied = sorted((t for t in cand if key(t) == best), key=lambda t: t['task_id'])
            pick = rng.choice(tied)
            used.add(pick['task_id'])
            problem = None
            sc = Scene(str(ROOT / pick['input_ifc']))
            try:
                if not pick.get('clarification'):
                    st = verify.check_anchor(sc, anchor_lib.from_record(pick['anchor']),
                                             pick['anchor'].get('expected') or ())
                    if not st.ok:
                        problem = 'anchor check under the corrected code: ' + st.reason
            finally:
                code['geom']._READ.clear()
                sc = None
            if problem is None:
                target = work / f'{pick["task_id"]}.ifc'
                rb = materialize.rebuild(pick, ROOT, target, True)
                if not rb.ok:
                    problem = f'gold rebuild: {rb.check} {rb.reason}'
                else:
                    rebuilt = {'check': rb.check, 'bytes': rb.bytes, 'seconds': round(rb.seconds, 1)}
                    if cc.in_scope(pick):
                        cres = cc.check_task(pick, gold_path=str(target))
                        rebuilt['clearance_min_d'] = cres['min_d']
                        if cres['flag']:
                            bad = next(x for x in cres['fillings'] if x.get('flag'))
                            problem = (f'filling clearance: {bad["class"]} {bad["guid"]} opens into '
                                       f'{bad["offending"]["class"]} {bad["offending"]["guid"]} at {bad["d"]} m')
                    os.remove(target)
            if problem:
                rejected[tid].append([pick['task_id'], problem])
                log(f'replacement for {tid}: candidate {pick["task_id"]} rejected ({problem})')
                continue
            replacement[tid] = pick
            why[tid] = {'stratum': list(stratum(d)), 'ifc_version': d['ifc_version'], 'candidates': len(cand),
                        'tied_at_best': len(tied), 'same_building': not best[0], 'same_edit_kind': not best[1],
                        'same_family': not best[2], 'gold_rebuild': rebuilt,
                        'source': 'canonical_v2/tasks_validation.jsonl' if d['ifc_version'] == 'IFC2X3'
                        else 'corpus_v10/gen/val_tasks_v10.jsonl'}
            log(f'replacement for {tid} ({d["ifc_version"]} {"/".join(stratum(d))}, {d.get("edit_kind")}, '
                f'{d["building_id"]}): {pick["task_id"]} ({pick.get("edit_kind")}, {pick["building_id"]}); '
                f'{len(cand)} candidates, {len(tied)} tied at best; anchor ok; gold {rb.check} ok')
            break

    # the opposite replacements are drawn first, so they equal the dry run's
    v1 = json.load(open(FIXDIR / 'install/dry_run/val_v3b/val_v3b_repair.json'))
    for tid in opposite_order:
        assert replacement[tid]['task_id'] == v1['replacements'][tid], (tid, replacement[tid]['task_id'])
    log(f'opposite replacements equal the dry run: {[(t, v1["replacements"][t]) for t in opposite_order]}')

    # 3. assemble
    new500 = [replacement[t['task_id']] if t['task_id'] in replacement else t for t in t500]
    new100 = [replacement[t['task_id']] if t['task_id'] in replacement else t for t in t100]
    ids5 = [t['task_id'] for t in new500]
    assert len(set(ids5)) == 500 and all(t['task_id'] in set(ids5) for t in new100)
    for name, rows_ in (('500', new500), ('100', new100)):
        before = Counter((t['ifc_version'], t['operation'], t['category'], t.get('tier', 'single'))
                         for t in (t500 if name == '500' else t100))
        after = Counter((t['ifc_version'], t['operation'], t['category'], t.get('tier', 'single')) for t in rows_)
        assert before == after, f'val-{name} strata changed'
    left = reresolve(new500, code)
    assert all(x['class'] == 'unchanged' for x in left)
    assert not (set(flag500) & set(ids5)), 'a clearance-flagged task is still in val-500'
    screened_clean = set()
    for f in ('results_big.jsonl', 'results_s0.jsonl', 'results_s1.jsonl'):
        for line in open(CLEAR / f):
            x = json.loads(line)
            if x['set'] == 'val500' and x['status'] == 'ok' and not x['flag']:
                screened_clean.add(x['task_id'])
    new_ids = {v['task_id'] for v in replacement.values()}
    unscreened = [t['task_id'] for t in new500 if cc.in_scope(t) and t['task_id'] not in new_ids
                  and t['task_id'] not in screened_clean]
    assert not unscreened, ('kept val tasks the clearance screen did not pass', unscreened[:5])
    plan = {'input_sha256': input_sha, 'code_sha256': {'anchors.py': sha256_file(code['anchors_file']),
                                                       'veribim_geom.py': sha256_file(code['geom_file'])},
            'opposite_tasks': [{k: x[k] for k in ('task_id', 'class', 'old_gold', 'new_gold', 'instruction_consistent',
                                                  'consistency_note', 'anchor_in_instruction')} for x in rows],
            'gold_changes': [x['task_id'] for x in changed],
            'dropped': drop, 'replacements': {k: v['task_id'] for k, v in replacement.items()},
            'why': why, 'rejected_candidates': rejected, 'seed': SEED,
            'in_val_100': sorted(t for t in drop if t in set(s100)),
            'clearance_flagged': sorted(flag500), 'clearance_dropped': sorted(clearance_dropped),
            'drop_order': drop_order,
            'positions': {k: s500.index(k) for k in drop}}
    if args.real:
        for k in ('gold_changes', 'dropped', 'replacements', 'in_val_100', 'positions', 'clearance_dropped'):
            assert plan[k] == plan_dry[k], f'real run differs from the dry run in {k}'
    write_jsonl(out_dir / v3b(NAMES['t500']), new500)
    write_jsonl(out_dir / v3b(NAMES['t100']), new100)
    json.dump(ids5, open(out_dir / v3b(NAMES['s500']), 'w'), indent=1)
    json.dump([t['task_id'] for t in new100], open(out_dir / v3b(NAMES['s100']), 'w'), indent=1)
    plan['output_sha256'] = {v3b(n): sha256_file(out_dir / v3b(n)) for n in NAMES.values()}
    write_json(out_dir / 'val_v3b_repair.json', plan)
    log(f'wrote {[v3b(n) for n in NAMES.values()]} in {out_dir}; val-100 {"unchanged" if not plan["in_val_100"] else "changed"}')
    log(f'wall {time.time() - t0:.0f} s; peak RSS {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB')
    (out_dir / 'reval_run.log' if args.dry_run else work / 'reval_real.log').write_text('\n'.join(log.lines) + '\n')


if __name__ == '__main__':
    main()
