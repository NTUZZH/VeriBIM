"""Collect the lane results into flagged_<set>.jsonl, flagged_pool_ids.json and summary.json."""
import json, glob, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
SETS = ('bench_v4', 'val500', 'val100', 'pool')
res = {}
for f in glob.glob(HERE + '/results_*.jsonl'):
    for l in open(f):
        r = json.loads(l)
        res[(r['set'], r['task_id'])] = r
summary = {}
for s in SETS:
    recs = [json.loads(l) for l in open(HERE + f'/inscope_{s}.jsonl')]
    missing = [r['task_id'] for r in recs if (s, r['task_id']) not in res]
    rows = []
    for rec in recs:
        r = res.get((s, rec['task_id']))
        if r is None:
            continue
        rows.append((rec, r))
    err = [rec['task_id'] for rec, r in rows if r['status'] != 'ok']
    ok = [(rec, r) for rec, r in rows if r['status'] == 'ok']
    with_f = [(rec, r) for rec, r in ok if r['n_fillings'] > 0]
    flagged = [(rec, r) for rec, r in ok if r['flag']]
    def by(key, sub):
        return dict(sorted(collections.Counter(key(rec) for rec, _ in sub).items()))
    kind = lambda rec: f"{rec['edit_kind']}/{rec['family']}"
    bld = lambda rec: f"{rec['building_id']} ({rec['source_model']['key']}, {os.path.basename(rec['input_ifc'])})"
    fstat = collections.Counter(f['status'] for rec, r in ok for f in r['fillings'])
    summary[s] = {
        'in_scope': len(recs), 'screened': len(ok), 'errors': err, 'not_run': missing,
        'with_a_created_or_moved_filling': len(with_f), 'fillings_measured': sum(r['n_fillings'] for _, r in ok),
        'filling_status': dict(fstat), 'flagged': len(flagged),
        'screened_by_version': by(lambda rec: rec['ifc_version'], with_f),
        'flagged_by_version': by(lambda rec: rec['ifc_version'], flagged),
        'screened_by_kind': by(kind, with_f), 'flagged_by_kind': by(kind, flagged),
        'screened_by_building': by(lambda rec: rec['building_id'], with_f),
        'flagged_by_building': by(bld, flagged),
        'flagged_by_obstruction_class': dict(collections.Counter(
            f['offending']['class'] for _, r in flagged for f in r['fillings'] if f.get('flag'))),
        'flagged_parallel_obstruction': sum(1 for _, r in flagged if any(
            f.get('flag') and f['offending']['parallel_to_host'] for f in r['fillings'])),
        'flagged_d_zero': sum(1 for _, r in flagged if r['min_d'] == 0.0),
        'unflagged_with_an_uncut_host_layer': sum(1 for _, r in ok if not r['flag'] and any(
            f.get('layer') for f in r['fillings'])),
        'd_histogram_fillings': dict(sorted(collections.Counter(
            ('none' if f.get('d') is None else ('0' if f['d'] == 0 else f"{min(int(f['d'] / 0.3) * 0.3, 1.2):.1f}+"))
            for _, r in ok for f in r['fillings']).items())),
        'moved_flagged_already_before_edit': sum(1 for _, r in flagged if any(
            f.get('flag') and f.get('how') == 'moved' and f.get('d_before_edit') is not None
            and f['d_before_edit'] < 0.6 for f in r['fillings'])),
    }
    with open(HERE + f'/flagged_{s}.jsonl', 'w') as h:
        for rec, r in sorted(flagged, key=lambda x: (x[1]['min_d'], x[0]['task_id'])):
            h.write(json.dumps({
                'task_id': rec['task_id'], 'set': s, 'ifc_version': rec['ifc_version'], 'origin': rec.get('origin'),
                'building_id': rec['building_id'], 'source_key': rec['source_model']['key'],
                'input_ifc': rec['input_ifc'], 'edit_kind': rec['edit_kind'], 'family': rec['family'],
                'tier': rec['tier'], 'operation': rec['operation'], 'category': rec['category'],
                'min_distance_m': r['min_d'],
                'fillings': [{'guid': f['guid'], 'class': f['class'], 'name': f.get('name'), 'how': f.get('how'),
                              'host': f.get('host'), 'distance_m': f.get('d'), 'flag': f.get('flag'),
                              'd_before_edit_m': f.get('d_before_edit'), 'band': f.get('band'),
                              'offending': f.get('offending'), 'host_layer': f.get('layer')} for f in r['fillings']],
            }, default=str) + '\n')
    if s == 'pool':
        json.dump(sorted(rec['task_id'] for rec, _ in flagged), open(HERE + '/flagged_pool_ids.json', 'w'), indent=0)
    print(s, {k: v for k, v in summary[s].items() if not isinstance(v, dict)})
json.dump(summary, open(HERE + '/summary.json', 'w'), indent=1)
