#!/usr/bin/env python
"""Count rows without a score in per-task result files.
Usage: check_unscored.py PATH [PATH ...]   PATH = a per-task .jsonl file or a folder searched recursively
for per_task_*.jsonl. Prints one line per file and exits 1 when any row has no score."""
import glob, json, os, sys

def main():
    bad = 0
    for root in sys.argv[1:]:
        if os.path.isfile(root):
            files = [root]
        else:
            files = sorted(glob.glob(os.path.join(root, '**', 'per_task_*.jsonl'), recursive=True))
        if not files:
            print(f'   no per-task file under {root}')
        for f in files:
            n = none = 0
            errs = {}
            with open(f, encoding='utf-8') as fh:
                for line in fh:
                    if not line.strip():
                        continue
                    r = json.loads(line)
                    n += 1
                    if r.get('score') is None:
                        none += 1
                        e = str(r.get('score_error'))[:70]
                        errs[e] = errs.get(e, 0) + 1
            print(f'{none:5d} / {n:5d}  {f}' + (f'   {errs}' if none else ''))
            bad += none
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
