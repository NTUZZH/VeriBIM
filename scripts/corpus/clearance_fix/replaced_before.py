"""For flagged replace_filling tasks: the clearance of the door or window the edit removed, in the source."""
import json, sys, os, ifcopenshell
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import clearance_check as cc
recs = {}
for s in ['bench_v4', 'pool', 'val500', 'val100']:
    for l in open(f'{HERE}/inscope_{s}.jsonl'):
        r = json.loads(l); recs[(s, r['task_id'])] = r
out = {}
for s in ['bench_v4', 'val500', 'val100', 'pool']:
    for l in open(f'{HERE}/flagged_{s}.jsonl'):
        fr = json.loads(l)
        if fr['edit_kind'] != 'replace_filling': continue
        rec = recs[(s, fr['task_id'])]
        m = ifcopenshell.open(cc.ROOT + rec['input_ifc'])
        idx = cc.source_index(cc.ROOT + rec['input_ifc'])
        old = [g for g in rec['edit_guids']['removed'] if m.by_guid(g).is_a() in ('IfcDoor', 'IfcWindow')]
        res = [cc.check_filling(m, m.by_guid(g), idx) for g in old]
        out[f'{s}/{fr["task_id"]}'] = [{'guid': r['guid'], 'class': r['class'], 'd': r.get('d'), 'status': r['status'],
                                        'offending': (r.get('offending') or {}).get('guid')} for r in res]
        del m
json.dump(out, open(f'{HERE}/replaced_filling_before.json', 'w'), indent=1)
import collections
print(collections.Counter((k.split('/')[0], any(x['d'] is not None and x['d'] < cc.C_DEFAULT for x in v)) for k, v in out.items()))
