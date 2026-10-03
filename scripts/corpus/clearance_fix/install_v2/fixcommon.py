"""Shared helpers for the install scripts (rebench.py, reval.py, rescore_val.py).

Code selection (setup_code):
  'fixed'           the corrected anchors.py / veribim_geom.py, loaded from
                    ../anchors_fixed.py and ../veribim_geom_fixed.py by ../fixload.py
                    under the installed module names, inside this process only.
                    Nothing under code/ is read-modified or written.
  'installed'       whatever code/ holds now (before the install: the old rule).
  'installed_fixed' code/ after the install; ../fixload.py (OPPOSITE_FIX_USE_INSTALLED=1)
                    asserts the installed files equal the tested fixed copies byte for byte.
Every mode points the geometry-index cache at install_v2/geom_cache, so nothing is
written to ~/.cache or to the opposite_fix folder.
"""
from __future__ import annotations

import ast
import gc
import gzip
import hashlib
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True

ROOT = Path('.')
# the opposite fix (fixed modules, fixload.py, reresolve_report.json) stays where it is;
# this copy of the install package (opposite rule + filling clearance) writes only
# under clearance_fix/install_v2/
FIXDIR = ROOT / 'scripts/corpus/opposite_fix'
CLEAR = ROOT / 'runs_local/corpus_v10/clearance_fix'
INSTALL = CLEAR / 'install_v2'
DRY = INSTALL / 'dry_run'
GEOM_CACHE = INSTALL / 'geom_cache'
BENCH = ROOT / 'runs_local/bench_v4'
STAGE_A = ROOT / 'runs_local/stage_a_v10'
GEN = ROOT / 'runs_local/corpus_v10/gen'
PY = sys.executable

_CODE = {}
# files generator_clearance.diff writes (checked in real mode)
CLEARANCE_FILES = ('clearance.py', 'generate.py', 'verify.py', 'settings.py', 'tests/test_clearance.py')


def setup_code(mode: str) -> dict:
    """Import the generator and library in the requested state; see the module doc."""
    if _CODE:
        assert _CODE['mode'] == mode, (_CODE['mode'], mode)
        return _CODE
    for p in (str(ROOT / 'code/harness'), str(ROOT / 'code')):
        if p not in sys.path:
            sys.path.insert(0, p)
    for n in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS'):
        os.environ.setdefault(n, '1')
    if mode in ('fixed', 'installed_fixed'):
        if mode == 'installed_fixed':
            os.environ['OPPOSITE_FIX_USE_INSTALLED'] = '1'
            # The generator's clearance stage must be installed as tested
            for rel in CLEARANCE_FILES:
                mine = sha256_file(CLEAR / 'patch/b/modifc_gen' / rel)
                there = sha256_file(ROOT / 'code/modifc_gen' / rel)
                assert mine == there, f'code/modifc_gen/{rel} differs from the tested copy clearance_fix/patch/b'
        else:
            os.environ.pop('OPPOSITE_FIX_USE_INSTALLED', None)
        if str(FIXDIR) not in sys.path:
            sys.path.insert(0, str(FIXDIR))
        import fixload  # noqa: F401  (shadows or checks the two modules)
        geom, anchors = fixload.geom, fixload.anchors
    elif mode == 'installed':
        from modifc_harness import veribim_geom as geom
        from modifc_gen import anchors
    else:
        raise ValueError(mode)
    # fixload points the cache at its own folder; keep every write under install/.
    os.environ['MODIFC_GEOM_CACHE'] = str(GEOM_CACHE)
    from modifc_gen.scene import Scene, FAMILY_CLASS
    from modifc_gen import goldlib
    assert goldlib._geom() is geom
    _CODE.update(mode=mode, geom=geom, anchors=anchors, Scene=Scene,
                 FAMILY_CLASS=FAMILY_CLASS,
                 geom_file=geom.__file__, anchors_file=anchors.__file__)
    return _CODE


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def sha256_gunzip(path) -> str:
    h = hashlib.sha256()
    with gzip.open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def gzip_with_sha(src, dst) -> dict:
    """gzip src to dst (via a tmp name); sha256 of the uncompressed bytes."""
    h = hashlib.sha256()
    tmp = Path(str(dst) + '.tmp')
    with open(src, 'rb') as a, gzip.open(tmp, 'wb', compresslevel=6) as b:
        for chunk in iter(lambda: a.read(1 << 20), b''):
            h.update(chunk)
            b.write(chunk)
    os.replace(tmp, dst)
    return {'sha256': h.hexdigest(), 'bytes': os.path.getsize(src), 'gz_bytes': os.path.getsize(dst)}


def read_jsonl(path) -> list:
    return [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]


def write_jsonl(path, rows) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as h:
        for r in rows:
            h.write(json.dumps(r, ensure_ascii=False) + '\n')
    os.replace(tmp, path)


def write_json(path, obj, indent=1) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + '.tmp')
    with open(tmp, 'w', encoding='utf-8') as h:
        json.dump(obj, h, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def refuse_existing(paths) -> None:
    """Real mode never overwrites: stop before writing anything if a target exists."""
    there = [str(p) for p in paths if Path(p).exists()]
    if there:
        raise SystemExit('refusing to overwrite existing output(s):\n  ' + '\n  '.join(there))


# ------------------------------------------------------------ opposite anchors

def lit(x):
    if isinstance(x, str) and x[:1] in '{[':
        try:
            return ast.literal_eval(x)
        except Exception:
            return x
    return x


def opposite_anchors(record) -> list:
    """Every (path, anchor dict) with kind 'opposite' anywhere in the record."""
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


def carries_opposite(record) -> bool:
    """Any opposite anchor, the opposite family tag, or the word in the instruction."""
    if opposite_anchors(record):
        return True
    if 'ref.relative.opposite' in (record.get('families') or ()):
        return True
    text = ' '.join(str(record.get(k) or '') for k in ('instruction', 'prompt')).lower()
    return ' opposite ' in f' {text} '


def _consistency(code, sc, r, new, cls):
    """Whether the rest of the instruction still holds for the new element.

    Copied from ../reresolve.py (the same checks), so the install scripts
    re-derive the drop / re-gold split instead of trusting the stored report.
    """
    import numpy as np
    geom = code['geom']
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
        return stated == there, 'instruction names fillings %s; new wall hosts %s' % (stated, there)
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
            c = geom.centre(ref)
            bb = geom.world_box(wall)
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
        return ok, '; '.join(notes)
    return True, 'no stated fact about the anchored element beyond the phrase'


def reresolve(records, code, log=print) -> list:
    """Resolve every opposite anchor of the records with the loaded rule.

    Returns one row per record that carries an opposite anchor: class
    unchanged / changed / no answer, old and new gold, the library's answer,
    and whether the rest of the instruction holds for the new element.
    """
    Scene, anchors, geom, FC = code['Scene'], code['anchors'], code['geom'], code['FAMILY_CLASS']
    todo = []
    for r in records:
        found = opposite_anchors(r)
        if found:
            assert len(found) == 1, (r['task_id'], len(found))
            todo.append((r, found[0]))
    todo.sort(key=lambda t: (t[0]['input_ifc'], t[0]['task_id']))
    rows, cur, sc = [], None, None
    for r, (path, a) in todo:
        src = ROOT / r['input_ifc']
        if src != cur:
            geom._READ.clear()
            sc = None
            gc.collect()
            sc = Scene(str(src))
            cur = src
        new = anchors.from_record(a).resolve(sc)
        old = list(a.get('expected') or [])
        lib, lib_err = None, None
        try:
            lib = geom.find_opposite(sc.by_guid(a['params']['reference_guid']),
                                     FC[a['family']],
                                     sc.by_guid(a['params']['space_guid'])).GlobalId
        except LookupError as ex:
            lib_err = str(ex)[:300]
        cls = 'no answer' if len(new) != 1 else ('unchanged' if new == old else 'changed')
        ok, note = _consistency(code, sc, r, new, cls)
        rows.append({'task_id': r['task_id'], 'input_ifc': r['input_ifc'], 'class': cls,
                     'old_gold': old, 'new_gold': new, 'library': lib,
                     'library_error': lib_err, 'anchor_path': path,
                     'generator_library_agree': (new == [lib]) if lib else (len(new) != 1),
                     'instruction_consistent': ok, 'consistency_note': note,
                     'anchor_in_instruction': 'opposite' in (r.get('instruction') or '').lower()})
    geom._READ.clear()
    sc = None
    gc.collect()
    return rows


class Log:
    """Print and keep every line, so the report can quote the run."""

    def __init__(self):
        self.lines = []

    def __call__(self, *parts):
        line = ' '.join(str(p) for p in parts)
        print(line, flush=True)
        self.lines.append(line)
