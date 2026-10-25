"""Copy the edited model of every audit case (draw.json) into tmp/outputs/<label>.ifc.gz.

The per-task record names the edited file (<run>/<model>/edited/<task_id>/<file>). When the run's edited/
folder is packed, the single member is read from <run>/<model>/edited.tar.gz (one archive at a time;
nothing else is unpacked). Records the SHA-256 of the output and of the source model, so a case whose
output equals its input ("no edit") is known. Writes tmp/outputs/fetch_log.json.
Run: taskset -c 16-23 python fetch_outputs.py
"""
import collections, gzip, hashlib, json, os, shutil, tarfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = ''
OUT = os.path.join(HERE, 'tmp', 'outputs')


def sha_file(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    os.makedirs(OUT, exist_ok=True)
    draw = json.load(open(os.path.join(HERE, 'draw.json')))
    logp = os.path.join(OUT, 'fetch_log.json')
    log = json.load(open(logp)) if os.path.exists(logp) else {}
    todo = collections.defaultdict(list)
    for c in draw['audit_cases']:
        if c['label'] in log and log[c['label']].get('task_id') == c['task_id'] and \
                os.path.exists(os.path.join(OUT, c['label'] + '.ifc.gz')):
            continue
        p = c['edited_ifc']
        task_dir = os.path.dirname(p)
        model_dir = os.path.dirname(os.path.dirname(task_dir))
        todo[model_dir].append((c, p))
    for model_dir, items in todo.items():
        tar = os.path.join(model_dir, 'edited.tar.gz')
        need = {}
        for c, p in items:
            if os.path.exists(p):
                need[c['label']] = ('file', p, c)
            else:
                need[c['label']] = ('tar', 'edited/' + c['task_id'] + '/' + os.path.basename(p), c)
        members = {m: lab for lab, (k, m, c) in need.items() if k == 'tar'}
        if members:
            with tarfile.open(tar, 'r:gz') as tf:
                for ti in tf:
                    if ti.name in members:
                        lab = members[ti.name]
                        src = tf.extractfile(ti)
                        with gzip.open(os.path.join(OUT, lab + '.ifc.gz'), 'wb', compresslevel=4) as g:
                            shutil.copyfileobj(src, g)
                        need[lab] = ('done', ti.name, need[lab][2])
        for lab, (k, m, c) in need.items():
            if k == 'file':
                with open(m, 'rb') as f, gzip.open(os.path.join(OUT, lab + '.ifc.gz'), 'wb', compresslevel=4) as g:
                    shutil.copyfileobj(f, g)
            elif k == 'tar':
                log[lab] = {'task_id': c['task_id'], 'error': 'member not found: ' + m}
                continue
            h = hashlib.sha256()
            with gzip.open(os.path.join(OUT, lab + '.ifc.gz'), 'rb') as g:
                for chunk in iter(lambda: g.read(1 << 20), b''):
                    h.update(chunk)
            out_sha = h.hexdigest()
            src_sha = sha_file(ROOT + c['input_ifc'])
            log[lab] = {'task_id': c['task_id'], 'arm': c['arm'], 'source': os.path.relpath(m, ROOT) if k == 'file'
                        else os.path.relpath(tar, ROOT) + ':' + m, 'output_sha256': out_sha, 'input_sha256': src_sha,
                        'unchanged': out_sha == src_sha}
            print(lab, c['task_id'], c['arm'], 'unchanged' if out_sha == src_sha else 'changed', flush=True)
        json.dump(log, open(logp, 'w'), indent=1)


if __name__ == '__main__':
    main()
