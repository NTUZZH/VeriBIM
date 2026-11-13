#!/usr/bin/env python
"""request_properties.py TASKS.jsonl OUT.csv [--check-first-set]

Properties of each practitioner request that the analyses of the second request set need, computed by fixed rules
from the request file and the input IFC files. The output holds task ids, counts and class labels only; no request
text and no element name is written.

  base task, writer, the writer's years of experience, operation, building, schema version   from the task record
  group       'identified' when the request gives, for every element it must resolve, a GlobalId, a Name that is
              unique in the file, or the trailing authoring-tool number of a Name when that number is unique;
              otherwise 'described'. The rule is the body of
              practitioner_requests/make_descriptor_split.py (2026-10-25), copied unchanged.
  holds       1 when every required element is among the first ten ranked candidates of the candidate-element index
              (the rule of analysis/prac_failures.py: 'worst' <= 10 in the rows of target_index/eval_recall.py);
  in_list     1 when every required element is in the list that apply_hint.py writes at K = 10 under the cap of
              2,000 characters (eval_recall.py 'in_hint' with --max-chars 2000).

--check-first-set: runs on the first set's request file and compares with the stored results (descriptor_split.csv
and recall_prac.json); exits 1 on any difference.
"""
import collections, csv, json, os, re, subprocess, sys, tempfile

P = '.'
TI = f'{P}/target_index'
FIRST = f'{P}/practitioner_requests/results/rewrite_tasks.jsonl'
FIRST_SPLIT = f'{P}/practitioner_requests/results/descriptor_split.csv'
FIRST_RECALL = f'{P}/local_arms/hint/recall_prac.json'
cache = {}


def index(path):
    """make_descriptor_split.index, unchanged."""
    import ifcopenshell
    if path not in cache:
        f = ifcopenshell.open(f'{P}/{path}')
        name_of, count = {}, collections.Counter()
        for p in f.by_type('IfcProduct'):
            n = p.Name or ''
            name_of[p.GlobalId] = n
            if n: count[n] += 1
        tagcount = collections.Counter()
        for n in count:
            m = re.search(r':(\d{4,})$', n)
            if m: tagcount[m.group(1)] += count[n]
        cache[path] = (name_of, count, tagcount)
    return cache[path]


def classify(t):
    """The loop body of make_descriptor_split.py, unchanged: (n_required, how per element, group)."""
    name_of, count, tagcount = index(t['input_ifc'])
    text = t['instruction']
    norm = lambda s: re.sub(r'\s+', ' ', s.replace('’', "'").replace(' ', ' '))
    tx = norm(text)
    hows = []
    if t['operation'] == 'create':
        ep = t.get('edit_params') or {}
        guids = [ep['replaced_guid']] if ep.get('replaced_guid') else [g for g in (ep.get('source_guid'), ep.get('host_guid')) if g]
        if not guids and ep.get('storey_guid'): guids = [ep['storey_guid']]
    else:
        guids = list(t['target']['guids'])
    for g in guids:
        n = name_of.get(g, '')
        how = None
        if g in text: how = 'globalid'
        elif n and (re.search(r'(?<![\w])' + re.escape(norm(n)) + r'(?![\w])', tx) if len(n) < 4 else norm(n) in tx) and count[n] == 1: how = 'unique_name'
        else:
            m = re.search(r':(\d{4,})$', n)
            if m and re.search(r'(?<!\d)' + m.group(1) + r'(?!\d)', text) and tagcount[m.group(1)] == 1: how = 'unique_tag'
            elif n and norm(n) in tx: how = 'shared_name'
            elif not n: how = 'unnamed'
        hows.append(how or 'description')
    group = 'identified' if all(h in ('globalid', 'unique_name', 'unique_tag') for h in hows) else 'described'
    return len(guids), ';'.join(hows), group


def recall_rows(tasks_path):
    """Rows of target_index/eval_recall.py at the list settings of the reads (--max-chars 2000)."""
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, 'recall.json')
        r = subprocess.run([sys.executable, 'eval_recall.py', tasks_path, out, '--max-chars', '2000'], cwd=TI,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise SystemExit('eval_recall.py failed: ' + r.stderr[-400:])
        return {x['task_id']: x for x in json.load(open(out))['rows']}


def properties(tasks_path):
    tasks = [json.loads(l) for l in open(tasks_path, encoding='utf-8') if l.strip()]
    rec = recall_rows(tasks_path)
    if set(rec) != {t['task_id'] for t in tasks}:
        raise SystemExit(f'recall rows cover {len(rec)} of {len(tasks)} requests (a request without a required element?)')
    rows = []
    for t in tasks:
        n, how, group = classify(t)
        v = rec[t['task_id']]
        rows.append({'task_id': t['task_id'], 'base_task_id': t['human_request']['base_task_id'], 'writer': t['human_request']['respondent'], 'operation': t['operation'],
                     'building_id': t['building_id'], 'ifc_version': t['ifc_version'],
                     'years_experience': t['human_request'].get('years_experience'), 'n_required': n, 'how': how,
                     'group': group, 'holds': int(v['worst'] is not None and v['worst'] <= 10), 'in_list': int(bool(v['in_hint']))})
    return rows


def main(argv):
    if argv == ['--check-first-set']:
        rows = properties(FIRST)
        old = {r['task_id']: r for r in csv.DictReader(open(FIRST_SPLIT, encoding='utf-8'))}
        rec = {r['task_id']: r for r in json.load(open(FIRST_RECALL))['rows']}
        bad_g = [r['task_id'] for r in rows if old[r['task_id']]['group'] != r['group'] or old[r['task_id']]['how'] != r['how']]
        bad_h = [r['task_id'] for r in rows if int(rec[r['task_id']]['worst'] is not None and rec[r['task_id']]['worst'] <= 10) != r['holds']]
        diff_list = sum(r['holds'] != r['in_list'] for r in rows)
        g = collections.Counter(r['group'] for r in rows)
        print(f"first set: {len(rows)} requests; groups {dict(g)}; holds {sum(r['holds'] for r in rows)}; "
              f"in the written list {sum(r['in_list'] for r in rows)}; holds differs from in_list on {diff_list}")
        print(f'group or how differs from descriptor_split.csv on {len(bad_g)} requests; holds differs from recall_prac.json on {len(bad_h)}')
        sys.exit(1 if bad_g or bad_h or len(rows) != 200 else 0)
    src, dst = argv
    rows = properties(src)
    with open(dst, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys())); w.writeheader(); w.writerows(rows)
    g = collections.Counter(r['group'] for r in rows)
    print(f"wrote {len(rows)} rows to {dst}; groups {dict(g)}; holds {sum(r['holds'] for r in rows)}; "
          f"in the written list {sum(r['in_list'] for r in rows)}; writers {len({r['writer'] for r in rows})}")


if __name__ == '__main__':
    main(sys.argv[1:])
