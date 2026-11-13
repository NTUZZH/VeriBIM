#!/usr/bin/env python
"""eval_recall.py <tasks.jsonl> <out.json> [--max-chars 1200]

Recall of the candidate list on tasks whose required elements are known. A task counts at K when every required
element is among the first K ranked candidates ('ranked'), and, for the hint itself, when every required element is
among the lines apply_hint.py actually writes at K = 10 under the length cap ('hint'). A required storey (a create
task placed by coordinates on a storey) counts as listed when a listed element stands on that storey; its rank is that
of the first such element. Tasks with no required element (requests that call for a clarification) are counted and
left out. Also reports, per operation, reference category and generator anchor kind, the mean rank of the required
elements (1 = first; elements never ranked are counted separately)."""
import collections, json, sys, time
import index_ifc, match, apply_hint

KS = (5, 10, 20)


def required_guids(task):
    """The elements a request must resolve, as make_descriptor_split.py derives them: the targets of a delete or an
    update; for a create, the replaced filling, else the copy source and the host wall, else the storey."""
    if task['operation'] == 'create':
        ep = task.get('edit_params') or {}
        guids = [ep['replaced_guid']] if ep.get('replaced_guid') else [g for g in (ep.get('source_guid'), ep.get('host_guid')) if g]
        if not guids and ep.get('storey_guid'):
            guids = [ep['storey_guid']]
        return guids
    return list(task['target']['guids'])


def positions(ranked, req, storeys):
    """1-based rank of each required element in the ranked list (None when absent)."""
    pos = {}
    for r in req:
        if r in storeys:
            pos[r] = next((k + 1 for k, (_, _, e) in enumerate(ranked) if e['sg'] == r), None)
        else:
            pos[r] = next((k + 1 for k, (_, g, _) in enumerate(ranked) if g == r), None)
    return pos


def summarise(rows):
    out = {'n': len(rows)}
    for k in KS:
        out[f'recall@{k}'] = round(sum(r['worst'] is not None and r['worst'] <= k for r in rows) / len(rows), 3) if rows else None
    out['hint_recall@10'] = round(sum(r['in_hint'] for r in rows) / len(rows), 3) if rows else None
    found = [p for r in rows for p in r['pos'] if p is not None]
    out['mean_rank'] = round(sum(found) / len(found), 2) if found else None
    out['required_never_ranked'] = sum(p is None for r in rows for p in r['pos'])
    out['required_total'] = sum(len(r['pos']) for r in rows)
    return out


def main(argv):
    mx = 1200
    if '--max-chars' in argv:
        i = argv.index('--max-chars')
        mx = int(argv[i + 1])
        argv = argv[:i] + argv[i + 2:]
    src, dst = argv
    tasks = [json.loads(l) for l in open(src) if l.strip()]
    rows, skipped, t0 = [], collections.Counter(), time.time()
    for t in sorted(tasks, key=lambda t: t['input_ifc']):
        req = required_guids(t)
        if not req:
            skipped[t['operation']] += 1
            continue
        idx = index_ifc.load(t['input_ifc'])
        text = apply_hint.request_text(t)
        ranked = match.rank(idx, text)
        app, listed = apply_hint.hint(idx, text, 10, mx, ranked)
        pos = positions(ranked, req, idx['storeys'])
        lst = [e['sg'] for _, g, e in ranked if g in set(listed)]
        in_hint = all((r in listed) if r not in idx['storeys'] else (r in lst) for r in req)
        worst = None if any(v is None for v in pos.values()) else max(pos.values())
        rows.append({'task_id': t['task_id'], 'operation': t['operation'], 'category': t['category'],
                     'anchor': (t.get('anchor') or {}).get('kind'), 'edit_kind': t.get('edit_kind'),
                     'n_required': len(req), 'pos': list(pos.values()), 'worst': worst, 'in_hint': in_hint,
                     'hint_lines': len(listed), 'hint_chars': len(app), 'storey_target': any(r in idx['storeys'] for r in req)})
    res = {'task_file': src, 'max_chars': mx, 'n_tasks': len(tasks), 'skipped_no_required': dict(skipped),
           'overall': summarise(rows), 'seconds': round(time.time() - t0, 1)}
    for key in ('operation', 'category'):
        res['by_' + key] = {v: summarise([r for r in rows if r[key] == v]) for v in sorted({r[key] for r in rows})}
    res['by_operation_category'] = {f'{o}/{c}': summarise([r for r in rows if r['operation'] == o and r['category'] == c])
                                    for o in sorted({r['operation'] for r in rows}) for c in sorted({r['category'] for r in rows})}
    res['create_storey_target'] = summarise([r for r in rows if r['storey_target']])
    fam = collections.defaultdict(list)
    for r in rows:
        fam[f"{r['operation']}/{r['edit_kind']}/{r['anchor']}"].append(r)
    res['by_family'] = {k: summarise(v) for k, v in sorted(fam.items())}
    res['worst_families'] = sorted(((k, v['n'], v['recall@10'], v['hint_recall@10']) for k, v in res['by_family'].items() if v['n'] >= 5),
                                   key=lambda x: (x[3], x[2], x[0]))[:5]
    hl = [r['hint_lines'] for r in rows]
    res['hint_lines_distribution'] = dict(sorted(collections.Counter(hl).items()))
    res['hint_chars_max'] = max(r['hint_chars'] for r in rows)
    res['rows'] = rows
    json.dump(res, open(dst, 'w'), indent=1)
    print(json.dumps({k: v for k, v in res.items() if k not in ('rows', 'by_family')}, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
