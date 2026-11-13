#!/usr/bin/env python3
"""Macros of the framework applied to another base model (a check on other base models, not a second proposed model).

  usage: make_macros_basemodels.py CONFIG.json OUT.tex OUT.json

CONFIG holds one entry per base model:
  {"models": [{"stem": "FourB", "label": "Qwen3.5-4B",
               "untrained": {"sub108": F, "rw": F, "prac": F, "prac_list": F},      # documented library; prac_list adds the candidate list
               "trained":   {"bench": F, "rw": F, "prac": F}}],                     # library and candidate list, after the imitation passes
   "reference": {"label": "the proposed model", "bench": F, "rw": F, "prac": F},    # the reported 9B model, same task files
   "ids": {"bench_tasks": TASKS.jsonl, "sub108": IDS.json, "rw": IDS.json, "prac": IDS.json}}
Any file may be absent ("" or missing key); its macros are then not written and the script says so.

Rules, imported from analysis/make_macros.py so that every interval is the one the proposed model's values use:
completion on the benchmark and the 108-task subset with the 95 % task-level bootstrap, on the reworded tasks and
the practitioners' requests with the Wilson rule of each set; paired differences with the task-level bootstrap, the
Tango interval, the discordant counts and the exact McNemar p. The trained model's value on the 108-task subset is
the slice of its benchmark run (said so in the macro source). Stops on a wrong task set or an unscored row.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_macros as mm

cfg = json.load(open(sys.argv[1], encoding='utf-8'))
out_tex, out_json = sys.argv[2], sys.argv[3]
I = cfg['ids']
bench_ids = [json.loads(l)['task_id'] for l in open(I['bench_tasks'], encoding='utf-8') if l.strip()]
IDS = {'bench': bench_ids, 'sub108': json.load(open(I['sub108'])), 'rw': json.load(open(I['rw'])), 'prac': json.load(open(I['prac']))}
if (len(IDS['bench']), len(IDS['sub108']), len(IDS['rw']), len(IDS['prac'])) != (2100, 108, 172, 200):
    mm.fail(f'task sets: {[len(v) for v in IDS.values()]}, wanted 2100, 108, 172, 200')
if not set(IDS['sub108']) <= set(IDS['bench']):
    mm.fail('the 108-task subset is not inside the benchmark')
TOK = {'bench': 'Bench', 'sub108': 'HundredEight', 'rw': 'Rw', 'prac': 'Prac'}
CI = {'bench': 'boot', 'sub108': 'boot', 'rw': 'wilson_rw', 'prac': 'wilson_arms'}
CIL = {'boot': '95 % task-level bootstrap', 'wilson_rw': '95 % Wilson interval', 'wilson_arms': '95 % Wilson interval'}


def load(path, kind, label):
    if not path or not os.path.exists(path):
        return None
    return mm.read_per_task(path, IDS[kind], label)


o = mm.Out()
o.section(9, 'The framework on other base models')
ref = {k: load(cfg['reference'].get(k), k, f'reference model, {k}') for k in ('bench', 'rw', 'prac')}
if ref['bench'] is not None:
    ref['sub108'] = {t: ref['bench'][t] for t in IDS['sub108']}
log = []
for m in cfg['models']:
    st, lab = 'Pm' + m['stem'], m['label']
    U = {k: load(m.get('untrained', {}).get(k), 'prac' if k == 'prac_list' else k, f'{lab} untrained, {k}') for k in ('sub108', 'rw', 'prac', 'prac_list')}
    T = {k: load(m.get('trained', {}).get(k), k, f'{lab} trained, {k}') for k in ('bench', 'rw', 'prac')}
    T['sub108'] = {t: T['bench'][t] for t in IDS['sub108']} if T['bench'] is not None else None
    for k in ('sub108', 'rw', 'prac'):
        if U[k] is not None:
            s = mm.summary(U[k], IDS[k], None, ci=CI[k])
            mm.put_summary(o, f'{st}Base{TOK[k]}', s, f'{lab} untrained with the documented library, {TOK[k]}', CIL[CI[k]])
            log.append(f'{lab} untrained, documented library, {k}: {s["done"]}/{s["n"]} = {s["comp"]:.3f}')
        else:
            o.skip(f'{lab} untrained on {k}', 'no per-task file')
    if U['prac_list'] is not None:
        s = mm.summary(U['prac_list'], IDS['prac'], None, ci='wilson_arms')
        mm.put_summary(o, f'{st}BaseListPrac', s, f'{lab} untrained with the documented library and the candidate list, Prac', CIL['wilson_arms'])
        log.append(f'{lab} untrained, documented library and list, prac: {s["done"]}/{s["n"]} = {s["comp"]:.3f}')
    for k in ('bench', 'sub108', 'rw', 'prac'):
        if T[k] is None:
            o.skip(f'{lab} trained on {k}', 'no per-task file')
            continue
        src = f'{lab} after the imitation passes, library and candidate list, {TOK[k]}' + (' (slice of the benchmark run)' if k == 'sub108' else '')
        s = mm.summary(T[k], IDS[k], None, ci=CI[k])
        mm.put_summary(o, f'{st}Trained{TOK[k]}', s, src, CIL[CI[k]])
        log.append(f'{lab} trained, {k}: {s["done"]}/{s["n"]} = {s["comp"]:.3f} [{s["lo"]:.3f}, {s["hi"]:.3f}]')
        if k != 'bench' and U.get(k) is not None:
            P = mm.paired(T[k], U[k], IDS[k], None, cluster=False)
            mm.put_paired(o, f'{st}TrainedMinusBase{TOK[k]}', P, f'{lab}, trained minus untrained with the documented library, {TOK[k]}')
            log.append(f'   trained minus untrained, {k}: {P["diff"]:+.3f} [{P["lo"]:+.3f}, {P["hi"]:+.3f}], {P["b"]} against {P["c"]}, p {P["p"]:.2g}')
        if k == 'prac' and U['prac_list'] is not None:
            P = mm.paired(T[k], U['prac_list'], IDS[k], None, cluster=False)
            mm.put_paired(o, f'{st}TrainedMinusBaseListPrac', P, f'{lab}, trained minus untrained with the documented library and the candidate list, Prac')
            log.append(f'   trained minus untrained with the list, prac: {P["diff"]:+.3f} [{P["lo"]:+.3f}, {P["hi"]:+.3f}], {P["b"]} against {P["c"]}, p {P["p"]:.2g}')
        if ref.get(k) is not None:
            P = mm.paired(ref[k], T[k], IDS[k], None, cluster=False)
            mm.put_paired(o, f'{st}RefMinusTrained{TOK[k]}', P, f'{cfg["reference"]["label"]} minus {lab} trained, {TOK[k]}')
            log.append(f'   {cfg["reference"]["label"]} minus {lab} trained, {k}: {P["diff"]:+.3f} [{P["lo"]:+.3f}, {P["hi"]:+.3f}], {P["b"]} against {P["c"]}, p {P["p"]:.2g}')
lines = ['% Generated by analysis/make_macros_basemodels.py (the framework on other base models).']
lines += [l.split('  % ')[0] for l in o.lines if l.startswith('\\newcommand')]
open(out_tex, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
json.dump({'macros': o.vals, 'skipped': o.skipped, 'summary': log}, open(out_json, 'w', encoding='utf-8'), indent=1)
print('\n'.join(log)); print(f'{len(lines) - 1} macros -> {out_tex}; skipped: {len(o.skipped)}')
