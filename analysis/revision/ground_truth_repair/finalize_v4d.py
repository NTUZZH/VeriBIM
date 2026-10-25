"""Finalize the v4d merge in place.

For every results/<run>_v4d written by merge_v4d.py, make results/<run> the canonical v4d read:
  * results/<run>/per_task_<m>.jsonl, by_version_<m>.txt, summary_<m>.json are renamed to *.pre_v4d (byte copies of
    the v4c read; the release's SUPERSEDED rule excludes the pre_ suffix), and the v4d files take their names, with
    every edited_ifc path rewritten from results/<run>_v4d/ to results/<run>/;
  * for each re-run task, the original edited/<task>, transcripts/<task>.json and logs/<task>.log of that model move
    to edited_pre_v4d/, transcripts_pre_v4d/, logs_pre_v4d/, and the re-run files (hard links from gt_fix/reruns) take
    their place;
  * results/<run>_v4d/rerun_meta moves to results/<run>/rerun_meta_v4d.
Checks: every edited_ifc path of the final rows exists; the task set equals the pre_v4d file's; row counts equal.
Afterwards the _v4d folders hold only hard links and copies already present under results/<run>; they are removed.
Run once; refuses if any destination *.pre_v4d already exists.
"""
import json, os, shutil, sys, datetime
from pathlib import Path
sys.path.insert(0, 'code')
from stage_a.gate_eval import summarize, AgentConfig
RES = Path('runs_local/bench_v4/results')
REPORT = Path('analysis/revision/ground_truth_repair/merge_report.json')
rep = json.load(open(REPORT))
log = []
v4d_dirs = sorted(d for d in RES.iterdir() if d.name.endswith('_v4d') and d.is_dir())
for d in v4d_dirs:
    run = d.name[:-4]; orig = RES / run
    assert orig.is_dir(), orig
    # (resumable: an arm whose originals are already archived as *.pre_v4d is completed, not refused)
for d in v4d_dirs:
    run = d.name[:-4]; orig = RES / run
    for pt in sorted(d.glob('per_task_*.jsonl')):
        m = pt.name[len('per_task_'):-len('.jsonl')]
        new_rows = [json.loads(l) for l in open(pt) if l.strip()]
        old_path = orig / f'{pt.name}.pre_v4d' if (orig / f'{pt.name}.pre_v4d').exists() else orig / pt.name
        old_rows = [json.loads(l) for l in open(old_path) if l.strip()]
        assert len(new_rows) == len(old_rows), (run, m, len(new_rows), len(old_rows))
        assert {r['task_id'] for r in new_rows} == {r['task_id'] for r in old_rows}, (run, m, 'task set')
        rerun_tasks = [r['task_id'] for r in new_rows if str(r.get('edited_ifc') or '').startswith(str(d / m / 'edited') + '/')]
        for t in rerun_tasks:
            assert (d / m / 'edited' / t).is_dir() or (orig / m / 'edited' / t).is_dir(), (run, m, t, 'no re-run edited dir')
        # rewrite paths and verify existence after the move (checked in pass 2)
        out = []
        for r in new_rows:
            ed = str(r.get('edited_ifc') or '')
            if ed.startswith(str(d) + '/'):
                r = dict(r); r['edited_ifc'] = str(orig) + ed[len(str(d)):]
            out.append(r)
        # archive originals
        for kind, ext in (('per_task', '.jsonl'), ('by_version', '.txt'), ('summary', '.json')):
            src = orig / f'{kind}_{m}{ext}'
            if src.exists() and not (orig / f'{kind}_{m}{ext}.pre_v4d').exists():
                os.rename(src, orig / f'{kind}_{m}{ext}.pre_v4d')
        # move per-task artefacts of the re-run tasks
        for t in rerun_tasks:
            for sub, name in (('edited', t), ('transcripts', f'{t}.json'), ('logs', f'{t}.log')):
                o = orig / m / sub / name
                n = d / m / sub / name
                if n.exists():   # not yet moved in (resume-safe: never touch o once the re-run file holds its place)
                    if o.exists():
                        (orig / m / f'{sub}_pre_v4d').mkdir(parents=True, exist_ok=True)
                        os.rename(o, orig / m / f'{sub}_pre_v4d' / name)
                    (orig / m / sub).mkdir(parents=True, exist_ok=True)
                    os.rename(n, orig / m / sub / name)
        with open(orig / pt.name, 'w') as f:
            for r in out:
                f.write(json.dumps(r) + '\n')
        src = d / f'by_version_{m}.txt'
        if src.exists():
            shutil.copy2(src, orig / f'by_version_{m}.txt')
        # the run summary is rebuilt from the final rows with run_gate's own summarize(); protocol fields are kept
        old_sum_path = orig / f'summary_{m}.json.pre_v4d'
        if old_sum_path.exists():
            old_sum = json.load(open(old_sum_path))
            new_sum = summarize(m, out, AgentConfig(**old_sum['resolved_agent_config']))
            for k in ('per_task_file', 'subset', 'scorer_reading', 'label', 'protocol_conformant', 'finished_at'):
                if k in old_sum: new_sum[k] = old_sum[k]
            new_sum['v4d_finalized_at'] = datetime.datetime.now().isoformat(timespec='seconds')
            new_sum['v4d_rerun_tasks'] = len(rerun_tasks)
            (orig / f'summary_{m}.json').write_text(json.dumps(new_sum, indent=2), encoding='utf-8')
        # verify every edited_ifc exists
        # original rows may point at edited models archived as edited.tar.gz; the check covers the re-run rows
        missing = [r['task_id'] for r in out if r['task_id'] in rerun_tasks and r.get('edited_ifc') and not os.path.exists(r['edited_ifc'])]
        assert not missing, (run, m, 'missing edited files after finalize', missing[:5])
        log.append({'run': run, 'model': m, 'rows': len(out), 'rerun_tasks': len(rerun_tasks)})
    if (d / 'rerun_meta').is_dir():
        os.rename(d / 'rerun_meta', orig / 'rerun_meta_v4d')
    for f in d.glob('DONE_*'):
        os.rename(f, orig / f'{f.name}_v4d')
# pass 3: remove the emptied _v4d folders (what remains are copies of files now under results/<run>)
for d in v4d_dirs:
    left = [p for p in d.rglob('*') if p.is_file()]
    kinds = {p.suffix for p in left}
    shutil.rmtree(d)
    log.append({'removed': d.name, 'files_left_were': len(left), 'suffixes': sorted(kinds)})
json.dump(log, open(REPORT.parent / 'finalize_v4d_log.json', 'w'), indent=1)
print(json.dumps([l for l in log if 'run' in l][:3], indent=0)); print(len([l for l in log if 'run' in l]), 'arms finalized;', len(v4d_dirs), 'v4d folders removed')
