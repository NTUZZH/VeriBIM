#!/usr/bin/env python3
"""How each imitation-training row writes its edit: one library edit call, several, raw IfcOpenShell code, or none.

  usage: supp_classify_training.py TRAIN.jsonl[.gz] OUT.jsonl [--start N --stop M]
         supp_classify_training.py --concat OUT.jsonl PART1.jsonl PART2.jsonl ...

The rule is that of round4/traj_accounting/scripts/scan_sft.py: the code of every
execute_ifc_code call of the row (all calls, in order) is classified by classify.classify_codes of the same folder,
imported unchanged. One compact line per row (task id, source, operation, category, edit kind, class, whether any
library function is called); no instruction or code text is written. A sidecar OUT.meta.json holds the training
file, its SHA-256 and the row count, which make_macros_supp.py checks against OUT.jsonl.

With --start/--stop only rows start <= i < stop are classified (a part); --concat joins parts in the given order,
checks that they cover the rows 0 .. n-1 of one training file without gap or overlap, and writes OUT.meta.json.
"""
import argparse
import gzip
import hashlib
import json
import os
import sys

sys.dont_write_bytecode = True
CLASSIFY_DIR = 'round4/traj_accounting/scripts'
sys.path.insert(0, CLASSIFY_DIR)
from classify import classify_codes, calls_with_outputs   # noqa: E402


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 22), b''):
            h.update(chunk)
    return h.hexdigest()


def opener(path):
    return gzip.open(path, 'rt', encoding='utf-8') if path.endswith('.gz') else open(path, encoding='utf-8')


def classify_file(train, out, start, stop):
    if os.path.exists(out):
        sys.exit(f'supp_classify_training: {out} exists; remove it first')
    n = 0
    with opener(train) as f, open(out, 'w', encoding='utf-8') as w:
        for i, line in enumerate(f):
            if i < start:
                continue
            if stop is not None and i >= stop:
                break
            r = json.loads(line)
            codes = [c for c, _ in calls_with_outputs(r['messages'])]
            c = classify_codes(codes)
            w.write(json.dumps({'row': i, 'task_id': r.get('task_id'), 'source': r.get('source'),
                                'operation': r.get('operation'), 'category': r.get('category'),
                                'edit_kind': r.get('edit_kind'), 'cls': c['cls'], 'any_geom': c['any_geom'],
                                'lib_sites': c['lib_sites'], 'n_calls': len(codes)}) + '\n')
            n += 1
    meta = {'training_file': os.path.abspath(train), 'rows': n, 'start': start, 'stop': stop,
            'classify_py': os.path.join(CLASSIFY_DIR, 'classify.py'),
            'classify_py_sha256': sha256(os.path.join(CLASSIFY_DIR, 'classify.py'))}
    if start == 0 and stop is None:
        meta['training_file_sha256'] = sha256(train)
        meta['part'] = False
    else:
        meta['part'] = True
    json.dump(meta, open(out[:-len('.jsonl')] + '.meta.json' if out.endswith('.jsonl') else out + '.meta.json', 'w'), indent=1)
    print(f'supp_classify_training: {n} rows classified from {train} (rows {start} to {start + n - 1})')


def concat(out, parts):
    if os.path.exists(out):
        sys.exit(f'supp_classify_training: {out} exists; remove it first')
    metas = [json.load(open(p[:-len('.jsonl')] + '.meta.json')) for p in parts]
    train = {m['training_file'] for m in metas}
    if len(train) != 1:
        sys.exit(f'supp_classify_training: the parts come from different training files {train}')
    expect, n = 0, 0
    with open(out, 'w', encoding='utf-8') as w:
        for p in parts:
            for line in open(p, encoding='utf-8'):
                r = json.loads(line)
                if r['row'] != expect:
                    sys.exit(f'supp_classify_training: {p} holds row {r["row"]}, expected {expect} (gap or overlap)')
                w.write(line)
                expect += 1
                n += 1
    tf = train.pop()
    with opener(tf) as f:
        total = sum(1 for _ in f)
    if total != n:
        sys.exit(f'supp_classify_training: the parts hold {n} rows, the training file {total}')
    meta = {'training_file': tf, 'training_file_sha256': sha256(tf), 'rows': n, 'start': 0, 'stop': None,
            'part': False, 'parts': [os.path.abspath(p) for p in parts], 'classify_py': metas[0]['classify_py'],
            'classify_py_sha256': metas[0]['classify_py_sha256']}
    json.dump(meta, open(out[:-len('.jsonl')] + '.meta.json', 'w'), indent=1)
    print(f'supp_classify_training: {n} rows joined from {len(parts)} parts')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--concat', action='store_true')
    ap.add_argument('--start', type=int, default=0)
    ap.add_argument('--stop', type=int, default=None)
    ap.add_argument('paths', nargs='+')
    a = ap.parse_args()
    if a.concat:
        concat(a.paths[0], a.paths[1:])
    else:
        if len(a.paths) != 2 or not a.paths[1].endswith('.jsonl'):
            sys.exit('usage: supp_classify_training.py TRAIN.jsonl[.gz] OUT.jsonl [--start N --stop M]')
        classify_file(a.paths[0], a.paths[1], a.start, a.stop)


if __name__ == '__main__':
    main()
