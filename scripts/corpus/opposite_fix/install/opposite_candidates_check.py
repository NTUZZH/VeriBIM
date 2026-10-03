"""Information only (not part of the install): the bench candidates that carry an
opposite anchor and are NOT in bench v4, re-resolved with the corrected rule.

The repair policy never draws a replacement with an opposite anchor, so the
requirement-family cell ref.relative.opposite falls below its quota of 12 in v4b.
This counts how many unselected candidates would keep their gold under the corrected
rule, i.e. how far that cell could be refilled if one chose to.
Fixed modules from ../ (fixload); writes only install/out/opposite_candidates.json.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fixcommon import BENCH, GEN, INSTALL, carries_opposite, opposite_anchors, read_jsonl, reresolve, setup_code  # noqa: E402

code = setup_code('fixed')
selected = {t['task_id'] for t in read_jsonl(BENCH / 'tasks.jsonl')}
out = {}
for v in ('IFC2X3', 'IFC4', 'IFC4X3'):
    cand = [t for t in read_jsonl(GEN / f'bench_candidates_v10_{v}.jsonl')
            if t['task_id'] not in selected and opposite_anchors(t)]
    rows = reresolve(cand, code)
    by = {t['task_id']: t for t in cand}
    ok = [x for x in rows if x['class'] == 'unchanged']
    out[v] = {'unselected_with_opposite_anchor': len(rows), 'classes': dict(Counter(x['class'] for x in rows)),
              'unchanged_ids': sorted(x['task_id'] for x in ok),
              'unchanged_by_cell': dict(Counter(f"{by[x['task_id']]['tier']} {by[x['task_id']]['operation']}/"
                                                f"{by[x['task_id']]['category']} {by[x['task_id']]['edit_kind']}"
                                                for x in ok))}
    print(v, out[v]['classes'], out[v]['unchanged_by_cell'], flush=True)
json.dump(out, open(INSTALL / 'out' / 'opposite_candidates.json', 'w'), indent=1)
