"""Install regenerated tables while keeping the hand-edited labels and captions of the installed copies.

Usage: python install_tables.py NAME=INSTALLED_PATH ... [--apply]
OLD = macros/out_v4d_20261016/<NAME>.tex (previous generator output, from which the installed copy descends),
NEW = macros/out/<NAME>.tex, INST = the installed copy. Data rows (lines containing '&' and ending in '\\\\') are
matched by position; INST keeps its first cell (label) and takes the remaining cells from NEW. Asserts: equal
data-row counts in the three files, equal cell counts per row, generator label unchanged, and INST's number cells
equal to OLD's (nothing hand-edited in a number cell is overwritten silently). Non-data lines of INST are kept.
Prints every changed cell; writes only with --apply (backup <file>.pre_v4e_install).
"""
import sys, shutil
from pathlib import Path
MAC = Path('analysis/revision/macros')
apply = '--apply' in sys.argv
def rows(txt):
    return [(i, l) for i, l in enumerate(txt.split('\n')) if '&' in l and l.rstrip().endswith('\\\\') and not l.lstrip().startswith('%')]
def cells(l):
    return [c.strip() for c in l.rstrip()[:-2].split('&')]
for arg in [a for a in sys.argv[1:] if not a.startswith('--')]:
    name, inst = arg.split('=')[0], Path(arg.split('=')[1])
    old = (MAC / 'out_v4d_20261016' / f'{name}.tex').read_text(); new = (MAC / 'out' / f'{name}.tex').read_text(); it = inst.read_text()
    ro, rn, ri = rows(old), rows(new), rows(it)
    assert len(ro) == len(rn) == len(ri), (name, len(ro), len(rn), len(ri))
    lines = it.split('\n'); changed = 0
    for (io, lo), (inn, ln), (ii, li) in zip(ro, rn, ri):
        co, cn, ci = cells(lo), cells(ln), cells(li)
        assert len(co) == len(cn) == len(ci), (name, lo, ln, li)
        assert co[0] == cn[0] or cn[0] == ci[0], (name, 'generator label changed', co[0], cn[0], ci[0])   # a generator label may move to the installed wording
        if co[1:] == cn[1:] or cn[1:] == ci[1:]:
            continue          # row unchanged by the generator, or INST already equal to NEW (header rows, rows whose numbers did not move)
        assert ci[1:] == co[1:], (name, 'installed number cells differ from the previous generator output', li, lo)
        if cn[1:] != ci[1:]:
            for k, (a, b) in enumerate(zip(ci[1:], cn[1:]), 1):
                if a != b: print(f'{name}: row "{ci[0][:45]}" cell {k}: {a} -> {b}'); changed += 1
            lines[ii] = li[:len(li) - len(li.lstrip())] + ' & '.join([ci[0]] + cn[1:]) + ' \\\\'
    print(f'{name}: {changed} cells changed' + ('' if apply else ' (dry run)'))
    if apply and changed:
        bak = inst.with_name(inst.name + '.pre_v4e_install')
        if not bak.exists(): shutil.copy2(inst, bak)
        inst.write_text('\n'.join(lines))
