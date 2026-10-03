"""Re-score the stored val-500 edits of each model against val-500 v3b.

The scorer is the gate's own: stage_a.gate_eval._score_one, reproduced line for
line (gold from stage_a.goldmodels.resolve_gold through a GoldCache, settings
from stage_a.scoring.scorer_config_for under the family reading, the stored
closing reply passed in, MESHES cleared after each task, MODELS capacity 3,
MESHES 800,000 vertices, one gold cache directory per worker).  The rollout
fields of every row are taken from the stored per_task file; only score,
score_error and final are recomputed.

Passes (each runs in its own process, because the code state differs):
  --pass reproduce   code/ as installed now, the v3 tasks, all 500 stored edits;
                     asserts every row's score, score_error and final equal the
                     stored per_task_<model>.jsonl and the by_version table equals
                     the stored by_version_<model>.txt byte for byte.
  --pass v3b         the corrected rule (dry run: fixed modules from ../;
                     real: code/ checked equal to them), the v3b tasks; the
                     replacement task has no stored edit and is reported as not
                     read; writes per_task_<model>.v3b.jsonl and
                     by_version_<model>.v3b.txt.

  --dry-run   runs both passes; outputs under install/out/ (v3b tasks from
              install/dry_run/val_v3b/).
  --real      after the install and after reval.py --real: pass v3b only (add
              --also-reproduce to repeat the reproduction on the installed code);
              writes the two new files per model next to the originals in
              runs_local/stage_a_v10/gates/v500/; refuses if they exist.
"""
from __future__ import annotations

import argparse
import collections
import json
import multiprocessing as mp
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from fixcommon import DRY, INSTALL, PY, ROOT, STAGE_A, read_jsonl, refuse_existing, setup_code, write_jsonl  # noqa: E402

V500 = STAGE_A / 'gates/v500'
MODELS_DEFAULT = ('sft_v10', 'dpo_v9_c10')
_CTX = {}


def _init(mode, cache_root):
    for n in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ[n] = '1'
    setup_code(mode)
    from modifc_score.model_cache import MESHES, MODELS
    MODELS.capacity = 3
    MESHES.capacity_vertices = 800_000
    from stage_a.goldmodels import open_cache
    _CTX.update(cache=open_cache(Path(cache_root) / f'slotpid{os.getpid()}'))


def _score_one(payload):
    """stage_a.gate_eval._score_one with family_reading=True."""
    from stage_a.goldmodels import resolve_gold
    from stage_a.scoring import score_prediction, scorer_config_for
    record, row = payload
    out = {'task_id': row['task_id'], 'score': None, 'score_error': None}
    predicted = Path(row['edited_ifc'])
    if not (predicted.is_file() and predicted.stat().st_size > 0):
        out['score_error'] = 'prediction missing'
        return out
    gold = resolve_gold(record, _CTX['cache'], ROOT)
    if gold is None:
        out['score_error'] = 'gold model could not be rebuilt from its script'
        return out
    config = scorer_config_for(record)
    t = time.time()
    score = score_prediction(record, predicted, ROOT, gold_path=gold, config=config,
                             reply=str(row.get('reply') or ''))
    from modifc_score.model_cache import MESHES
    MESHES.clear()
    out['score'] = score.as_dict()
    out['score_error'] = score.error
    out['_seconds'] = round(time.time() - t, 2)
    return out


def by_version_text(P: dict, T: dict) -> str:
    """The gate_v3.sh table, same code, same output."""
    agg = collections.defaultdict(lambda: [0, 0, 0.0])

    def completed(r):
        sc = r.get('score') or {}
        ax = [sc.get(k) for k in ('geometry', 'semantics', 'topology')]
        return all(a is not None and a >= 0.9 for a in ax)
    for tid, t in T.items():
        r = P.get(tid)
        if r is None:
            continue
        for key in (t['ifc_version'], (t['ifc_version'], t['operation']), 'ALL'):
            a = agg[key]
            a[0] += 1
            a[1] += completed(r)
            a[2] += float(r.get('final') or 0)
    lines = []
    for k in sorted(agg, key=str):
        n, c, s = agg[k]
        lines.append(f'{k} {n} completion {c / n:.3f} mean {s / n:.3f}')
    return '\n'.join(lines) + '\n'


def run_pass(which, mode, tasks_file, subset_file, out_dir, cache_root, models, workers, limit, real):
    code = setup_code(mode)
    print(f'pass {which}: code {mode} ({code["anchors_file"]}); tasks {tasks_file}', flush=True)
    wanted = json.load(open(subset_file))
    T = {t['task_id']: t for t in read_jsonl(tasks_file)}
    assert list(T) == wanted
    results = {}
    for model in models:
        stored = read_jsonl(V500 / f'per_task_{model}.jsonl')
        by = {r['task_id']: r for r in stored}
        order = [tid for tid in wanted if tid in by]
        pending = [tid for tid in wanted if tid not in by]
        if limit:
            order = order[:limit]
        payloads = [(T[tid], by[tid]) for tid in order]
        t0 = time.time()
        scored = {}
        ctx = mp.get_context('spawn')
        with ctx.Pool(processes=max(1, workers), initializer=_init, initargs=(mode, str(cache_root))) as pool:
            for i, out in enumerate(pool.imap_unordered(_score_one, payloads, chunksize=1), 1):
                scored[out['task_id']] = out
                if i % 50 == 0 or i == len(payloads):
                    print(f'  {model}: {i}/{len(payloads)} scored, {time.time() - t0:.0f}s', flush=True)
        rows = []
        for tid in order:
            row = dict(by[tid])
            e = scored[tid]
            row['score'] = e['score']
            row['score_error'] = e['score_error']
            row['final'] = (e['score'] or {}).get('final')
            rows.append(row)
        secs = sorted((scored[t].get('_seconds') or 0.0) for t in order)
        info = {'n_scored': len(rows), 'pending': pending, 'wall_seconds': round(time.time() - t0, 1),
                'score_seconds_median': secs[len(secs) // 2] if secs else None,
                'score_seconds_max': secs[-1] if secs else None}
        if which == 'reproduce':
            bad = [r['task_id'] for r in rows
                   if (r['score'], r['score_error'], r['final']) !=
                   (by[r['task_id']]['score'], by[r['task_id']]['score_error'], by[r['task_id']]['final'])]
            info['mismatch'] = bad
            if not limit:
                assert not pending, pending
                text = by_version_text({r['task_id']: r for r in rows}, T)
                info['by_version_equal'] = text == open(V500 / f'by_version_{model}.txt').read()
                info['rows_equal_stored_file'] = rows == [by[t] for t in order] and order == [r['task_id'] for r in stored]
            out_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(out_dir / f'per_task_{model}.reproduce.jsonl', rows)
            print(f'  {model}: reproduction {len(rows) - len(bad)}/{len(rows)} rows equal; '
                  f'by_version equal: {info.get("by_version_equal")}; whole file equal: {info.get("rows_equal_stored_file")}',
                  flush=True)
            assert not bad, f'{model}: {len(bad)} rows differ, e.g. {bad[:5]}'
            if not limit:
                assert info['by_version_equal'] and info['rows_equal_stored_file']
        else:
            changed = [r['task_id'] for r in rows
                       if (r['score'], r['score_error'], r['final']) !=
                       (by[r['task_id']]['score'], by[r['task_id']]['score_error'], by[r['task_id']]['final'])]
            info['changed_vs_v3'] = changed
            ptxt = out_dir / f'per_task_{model}.v3b.jsonl'
            btxt = out_dir / f'by_version_{model}.v3b.txt'
            if real:
                refuse_existing([ptxt, btxt])
            text = by_version_text({r['task_id']: r for r in rows}, T)
            for tid in pending:
                t = T[tid]
                text += (f'PENDING {tid} ({t["ifc_version"]}, {t["operation"]}): replacement task added in v3b, no stored '
                         f'edit, not read\n')
            n_ver = collections.Counter(T[t]['ifc_version'] for t in order)
            p_ver = collections.Counter(T[t]['ifc_version'] for t in pending)
            text += ('READ n=%d read + %d pending; ' % (len(order), len(pending))
                     + ', '.join(f'{v} {n_ver[v]} read + {p_ver[v]} pending' for v in sorted(n_ver)) + '\n')
            out_dir.mkdir(parents=True, exist_ok=True)
            write_jsonl(ptxt, rows)
            btxt.write_text(text)
            print(f'  {model}: wrote {ptxt.name}, {btxt.name}; {len(rows)} read, pending {pending}; '
                  f'scores that differ from v3: {changed}', flush=True)
        info['by_version_v3b'] = None if which == 'reproduce' else text
        results[model] = info
    return results


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--dry-run', action='store_true')
    g.add_argument('--real', action='store_true')
    ap.add_argument('--pass', dest='which', choices=('reproduce', 'v3b'), help='internal: run one pass')
    ap.add_argument('--models', nargs='+', default=list(MODELS_DEFAULT))
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--limit', type=int, default=0, help='score only the first N tasks (timing probe)')
    ap.add_argument('--also-reproduce', action='store_true')
    args = ap.parse_args()
    for m in args.models:
        assert (V500 / f'per_task_{m}.jsonl').is_file(), m
        assert (V500 / m / 'edited').is_dir(), m

    if args.which:
        reh = os.environ.get('INSTALL_REHEARSAL')   # see rebench.py; test of the real path only
        if args.which == 'reproduce':
            mode = 'installed' if args.dry_run else ('installed' if reh else 'installed_fixed')
            tasks, subset = STAGE_A / 'val_tasks_500_v3.jsonl', STAGE_A / 'val_subset_500_v3.json'
            out = INSTALL / 'out' / ('reproduce' if args.dry_run else 'reproduce_real')
        else:
            mode = 'fixed' if (args.dry_run or reh) else 'installed_fixed'
            src = DRY / 'val_v3b' if args.dry_run else (Path(reh) / 'stage_a_v10' if reh else STAGE_A)
            tasks, subset = src / 'val_tasks_500_v3b.jsonl', src / 'val_subset_500_v3b.json'
            out = INSTALL / 'out' if args.dry_run else (Path(reh) / 'v500' if reh else V500)
        cache = (DRY if args.dry_run else (Path(reh) if reh else INSTALL / 'real_work')) / 'gold_cache_rescore' / args.which
        res = run_pass(args.which, mode, tasks, subset, out, cache, args.models, args.workers, args.limit, args.real)
        summary = (Path(reh) if (reh and not args.dry_run) else INSTALL / 'out') / \
            f'rescore_{args.which}_{"dry" if args.dry_run else "real"}{"_limit" if args.limit else ""}.json'
        summary.parent.mkdir(parents=True, exist_ok=True)
        json.dump(res, open(summary, 'w'), indent=1)
        return

    passes = ['reproduce', 'v3b'] if args.dry_run else (['reproduce', 'v3b'] if args.also_reproduce else ['v3b'])
    for p in passes:
        cmd = [PY, os.path.abspath(__file__), '--dry-run' if args.dry_run else '--real', '--pass', p,
               '--workers', str(args.workers), '--models', *args.models] + (['--limit', str(args.limit)] if args.limit else [])
        print('+', ' '.join(cmd), flush=True)
        rc = subprocess.call(cmd)
        if rc != 0:
            raise SystemExit(f'pass {p} failed (rc {rc})')


if __name__ == '__main__':
    main()
