"""Collect the returned answer sheets of both colleague packets and join them with the hidden key.

    python collect_answers.py <folder with the returned .xlsx files> [--out <folder>]

Every .xlsx in the folder is read. A sheet whose table header holds "Q1" is a verdict-audit sheet
(packet B); one whose header holds "Your request" is a rewrite sheet (packet A, one block). The
respondent block (initials, years of experience, main modelling tool, date) is read from the top.
The key is packet_key.json next to this script (label -> task, arm, checker scores and verdict).

Writes to --out (default: the input folder):
  rewrite_tasks.jsonl    the benchmark record of every rewritten task, once per respondent, with the
                         instruction (and prompt) replaced by the respondent's request and the task_id
                         suffixed by block and initials (<task_id>-B<block>-<initials>); every other field
                         is unchanged, so the evaluation harness reads it as it reads the benchmark
                         (--tasks-file rewrite_tasks.jsonl --subset rewrite_subset.json)
  rewrite_subset.json    the task_ids of rewrite_tasks.jsonl
  rewrite_responses.csv  one row per request (block, label, respondent, base task, request, comment)
  audit_results.csv      one row per case per respondent (answers, checker verdict, arm, scores)
  audit_agreement.csv    one row per case: answers per respondent, majority Q1 and Q3 with their
                         shares, the checker verdict, and whether the two agree
  audit_summary.json     answer distributions; Fleiss' kappa per question (variable raters per case);
                         mean pairwise Cohen's kappa; the majority Q1 judgement ("yes" = correct; "partly"
                         and "no" = not correct) against the checker verdict (completed = all three axes
                         >= 0.90): 2x2 table, observed agreement, Cohen's kappa with a bootstrap 95%
                         interval over cases, sensitivity (checker says completed when the majority says
                         correct) and specificity (checker says not completed when the majority says not
                         correct), overall and per arm; the same for each respondent alone, and for Q3.
Needs openpyxl (the base miniconda python has it).
"""
import argparse, collections, csv, glob, itertools, json, os, random, re

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = ''
KEY = os.environ.get('VERIBIM_PACKET_KEY') or os.path.join(HERE, 'packet_key.json')
TASKS = ROOT + 'runs_local/bench_v4/tasks.v4d.jsonl'
Q1_OPTS = ('yes', 'partly', 'no')
Q3_OPTS = ('yes', 'no')
BOOT, BOOT_SEED = 2000, 20261015


def norm(v, opts):
    if v is None:
        return None
    s = str(v).strip().lower().rstrip('.')
    if not s:
        return None
    for o in opts:
        if s == o:
            return o
    for o in opts:
        if s.startswith(o):
            return o
    if s in ('y', 'ja', 'true', '1'):
        return 'yes'
    if s in ('n', 'nein', 'false', '0'):
        return 'no'
    if s.startswith('part'):
        return 'partly' if 'partly' in opts else None
    return None


def initials_of(head, path):
    s = re.sub(r'[^A-Za-z0-9]', '', str(head.get('respondent initials') or '')).upper()
    if s:
        return s
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r'_([A-Za-z]{1,4})$', stem)
    return m.group(1).upper() if m else re.sub(r'[^A-Za-z0-9]', '', stem)[-4:].upper()


def read_sheet(path):
    wb = load_workbook(path, data_only=True)
    ws = wb['Answers'] if 'Answers' in wb.sheetnames else wb.worksheets[0]
    head = {}
    for r in range(1, 10):
        k = ws.cell(row=r, column=1).value
        if k and str(k).strip().lower() != 'label' and str(k).strip().lower() != 'block':
            head[str(k).strip().lower()] = ws.cell(row=r, column=2).value
        elif k and str(k).strip().lower() == 'block' and ws.cell(row=r, column=2).value not in (None, ''):
            if not str(ws.cell(row=r, column=3).value or '').startswith('Your'):
                head['block'] = ws.cell(row=r, column=2).value
    hdr_row, kind = None, None
    for r in range(1, 20):
        vals = [str(ws.cell(row=r, column=c).value or '') for c in range(1, 6)]
        low = [v.strip().lower() for v in vals]
        if 'label' in low[:2]:
            hdr_row = r
            kind = 'audit' if any(v.startswith('Q1') for v in vals) else \
                'rewrite' if any(v.startswith('Your request') for v in vals) else None
            break
    if hdr_row is None or kind is None:
        return None
    cols = [str(ws.cell(row=hdr_row, column=c).value or '').strip() for c in range(1, 8)]
    rows = []
    for r in range(hdr_row + 1, ws.max_row + 1):
        vals = {cols[c - 1]: ws.cell(row=r, column=c).value for c in range(1, 8) if cols[c - 1]}
        lab = vals.get('Label')
        if not lab or not str(lab).strip():
            continue
        rows.append(vals)
    years = head.get('years of experience in bim or construction', head.get('years of bim experience'))
    tool = head.get('main modelling tool', head.get('main authoring tool'))
    return dict(kind=kind, path=path, initials=initials_of(head, path), years=years, tool=tool,
                date=str(head.get('date') or ''), block=head.get('block'), rows=rows)


def fleiss(table):
    """Fleiss' kappa with a variable number of raters per item. table: list of {category: count}."""
    items = [t for t in table if sum(t.values()) >= 2]
    if not items:
        return None
    cats = sorted({c for t in items for c in t})
    tot = sum(sum(t.values()) for t in items)
    p = {c: sum(t.get(c, 0) for t in items) / tot for c in cats}
    Pi = [(sum(v * v for v in t.values()) - sum(t.values())) / (sum(t.values()) * (sum(t.values()) - 1))
          for t in items]
    Pbar = sum(Pi) / len(Pi)
    Pe = sum(v * v for v in p.values())
    return None if Pe >= 1 else (Pbar - Pe) / (1 - Pe)


def cohen(a, b):
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < 2:
        return None
    n = len(pairs)
    po = sum(x == y for x, y in pairs) / n
    ca, cb = collections.Counter(x for x, _ in pairs), collections.Counter(y for _, y in pairs)
    pe = sum(ca[c] * cb[c] for c in set(ca) | set(cb)) / (n * n)
    return None if pe >= 1 else (po - pe) / (1 - pe)


def binary_agreement(human, checker, boot=True):
    """human, checker: lists of True (correct / completed), False, or None (skipped)."""
    pairs = [(h, c) for h, c in zip(human, checker) if h is not None and c is not None]
    n = len(pairs)
    if not n:
        return {'n': 0}
    tab = collections.Counter(pairs)
    tp, fn = tab[(True, True)], tab[(True, False)]     # human correct: checker completed / not completed
    fp, tn = tab[(False, True)], tab[(False, False)]
    out = {'n': n,
           'table': {'human_correct_checker_completed': tp, 'human_correct_checker_not_completed': fn,
                     'human_not_correct_checker_completed': fp, 'human_not_correct_checker_not_completed': tn},
           'observed_agreement': (tp + tn) / n,
           'cohen_kappa': cohen([h for h, _ in pairs], [c for _, c in pairs]),
           'sensitivity': tp / (tp + fn) if tp + fn else None,
           'specificity': tn / (tn + fp) if tn + fp else None}
    if boot and n >= 5:
        rng = random.Random(BOOT_SEED)
        ks = []
        for _ in range(BOOT):
            s = [pairs[rng.randrange(n)] for _ in range(n)]
            k = cohen([h for h, _ in s], [c for _, c in s])
            if k is not None:
                ks.append(k)
        ks.sort()
        if ks:
            out['cohen_kappa_bootstrap_95'] = [ks[int(0.025 * len(ks))], ks[int(0.975 * len(ks)) - 1]]
            out['bootstrap_resamples_used'] = len(ks)
    return out


def majority(vals):
    """Majority answer and its share; None when tied at the top."""
    c = collections.Counter(v for v in vals if v)
    if not c:
        return None, None
    (top, n), *rest = c.most_common()
    if rest and rest[0][1] == n:
        return None, n / sum(c.values())
    return top, n / sum(c.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('folder')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()
    out = a.out or a.folder
    os.makedirs(out, exist_ok=True)
    key = json.load(open(KEY))
    sheets = [s for s in (read_sheet(p) for p in sorted(glob.glob(os.path.join(a.folder, '*.xlsx')))) if s]
    seen = collections.Counter()
    for s in sheets:                       # two respondents with the same initials stay apart
        seen[(s['kind'], s['initials'])] += 1
        if seen[(s['kind'], s['initials'])] > 1:
            s['initials'] += str(seen[(s['kind'], s['initials'])])
    report = {'sheets': [{'file': os.path.basename(s['path']), 'kind': s['kind'], 'initials': s['initials'],
                          'block': s['block'], 'rows': len(s['rows'])} for s in sheets]}

    # ---------------- packet A: rewrite
    rw = [s for s in sheets if s['kind'] == 'rewrite']
    want = {v['task_id'] for v in key['rewrite'].values()}
    recs = {}
    for line in open(TASKS):
        r = json.loads(line)
        if r['task_id'] in want:
            recs[r['task_id']] = r
    n, ids, resp_rows, unknown = 0, [], [], []
    with open(os.path.join(out, 'rewrite_tasks.jsonl'), 'w', encoding='utf-8') as f:
        for s in rw:
            for row in s['rows']:
                lab = str(row.get('Label')).strip()
                text = row.get('Your request (one to three sentences)')
                if lab not in key['rewrite']:
                    unknown.append((os.path.basename(s['path']), lab))
                    continue
                if not text or not str(text).strip():
                    continue
                k = key['rewrite'][lab]
                r = dict(recs[k['task_id']])
                r['task_id'] = f"{k['task_id']}-B{k['block']}-{s['initials']}"
                r['instruction'] = r['prompt'] = ' '.join(str(text).split())
                r['instruction_paraphrase'] = None
                comment = row.get('Comment (optional)')
                r['human_request'] = {'label': lab, 'block': k['block'], 'respondent': s['initials'],
                                      'years_experience': s['years'], 'tool': s['tool'],
                                      'comment': str(comment).strip() if comment else '',
                                      'base_task_id': k['task_id']}
                f.write(json.dumps(r, ensure_ascii=False) + '\n')
                ids.append(r['task_id'])
                resp_rows.append({'block': k['block'], 'label': lab, 'respondent': s['initials'],
                                  'years_experience': s['years'], 'tool': s['tool'], 'base_task_id': k['task_id'],
                                  'operation': k['operation'], 'category': k['category'], 'version': k['version'],
                                  'request': r['instruction'], 'comment': r['human_request']['comment'],
                                  'benchmark_instruction': k['instruction']})
                n += 1
    json.dump(ids, open(os.path.join(out, 'rewrite_subset.json'), 'w'), indent=1)
    if resp_rows:
        with open(os.path.join(out, 'rewrite_responses.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(resp_rows[0]))
            w.writeheader()
            w.writerows(resp_rows)
    cover = collections.Counter(r['label'] for r in resp_rows)
    report['rewrite'] = {'sheets': len(rw), 'requests_written': n, 'distinct_tasks_covered': len(cover),
                         'tasks_with_2_or_more_wordings': sum(1 for v in cover.values() if v >= 2),
                         'by_block': dict(collections.Counter(r['block'] for r in resp_rows)),
                         'unknown_labels': unknown}

    # ---------------- packet B: verdict audit
    aud = [s for s in sheets if s['kind'] == 'audit']
    K = key['audit']
    res = []
    for s in aud:
        for row in s['rows']:
            lab = str(row.get('Label')).strip()
            if lab not in K:
                continue
            k = K[lab]
            q1 = norm(row.get('Q1 Carries out the request correctly?'), Q1_OPTS)
            q2 = row.get('Q2 If not fully: what is wrong?')
            q3 = norm(row.get('Q3 Accept without further changes?'), Q3_OPTS)
            res.append({'label': lab, 'task_id': k['task_id'], 'arm': k['arm'], 'operation': k['operation'],
                        'category': k['category'], 'version': k['version'], 'edit_kind': k['edit_kind'],
                        'checker_verdict': k['checker_verdict'], 'geometry': k['scores']['geometry'],
                        'semantics': k['scores']['semantics'], 'topology': k['scores']['topology'],
                        'near_threshold': k['near_threshold'], 'reply_only': k['reply_only'],
                        'respondent': s['initials'], 'years_experience': s['years'], 'tool': s['tool'],
                        'q1': q1, 'q2': (str(q2).strip() if q2 else ''), 'q3': q3,
                        'q1_raw': row.get('Q1 Carries out the request correctly?'),
                        'q3_raw': row.get('Q3 Accept without further changes?')})
    summary = {'respondents': sorted({r['respondent'] for r in res}), 'n_rows': len(res),
               'unreadable_q1': sum(1 for r in res if r['q1'] is None and r['q1_raw'] not in (None, '')),
               'unreadable_q3': sum(1 for r in res if r['q3'] is None and r['q3_raw'] not in (None, '')),
               'definitions': {'checker_completed': 'all three axes >= 0.90',
                               'human_correct': 'majority Q1 answer is "yes" ("partly" and "no" count as not correct); '
                                                'a tie at the top is left out of the 2x2 table',
                               'sensitivity': 'share of the cases the majority judges correct that the checker counts '
                                              'as completed',
                               'specificity': 'share of the cases the majority judges not correct that the checker '
                                              'counts as not completed'}}
    if res:
        with open(os.path.join(out, 'audit_results.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(res[0]))
            w.writeheader()
            w.writerows(res)
        by = collections.defaultdict(list)
        for r in res:
            by[r['label']].append(r)
        resp = sorted({r['respondent'] for r in res})
        agree = []
        for lab in sorted(by):
            rs = by[lab]
            k = K[lab]
            row = {'label': lab, 'task_id': k['task_id'], 'arm': k['arm'], 'checker_verdict': k['checker_verdict'],
                   'n_respondents': len(rs)}
            for p in resp:
                x = next((r for r in rs if r['respondent'] == p), None)
                row[f'q1_{p}'] = x['q1'] if x else ''
                row[f'q3_{p}'] = x['q3'] if x else ''
            m1, s1 = majority([r['q1'] for r in rs])
            m1b, s1b = majority([None if r['q1'] is None else ('correct' if r['q1'] == 'yes' else 'not correct')
                                 for r in rs])
            m3, s3 = majority([r['q3'] for r in rs])
            row.update({'q1_majority': m1 or 'tie', 'q1_majority_share': round(s1, 3) if s1 else '',
                        'q1_correct_majority': m1b or 'tie', 'q3_majority': m3 or 'tie',
                        'q3_majority_share': round(s3, 3) if s3 else '',
                        'agrees_with_checker': '' if m1b is None else
                        (m1b == 'correct') == (k['checker_verdict'] == 'completed'),
                        'what_is_wrong': ' | '.join(f"{r['respondent']}: {r['q2']}" for r in rs if r['q2'])})
            agree.append(row)
        with open(os.path.join(out, 'audit_agreement.csv'), 'w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(agree[0]))
            w.writeheader()
            w.writerows(agree)
        labs = sorted(by)
        for q, opts in (('q1', Q1_OPTS), ('q3', Q3_OPTS)):
            summary[f'{q}_distribution'] = {o: sum(1 for r in res if r[q] == o) for o in opts}
            summary[f'{q}_distribution_by_checker_verdict'] = {
                v: {o: sum(1 for r in res if r[q] == o and r['checker_verdict'] == v) for o in opts}
                for v in ('completed', 'not completed')}
            summary[f'{q}_fleiss_kappa'] = fleiss([collections.Counter(r[q] for r in by[l] if r[q]) for l in labs])
            ks = []
            for x, y in itertools.combinations(resp, 2):
                ax = [next((r[q] for r in by[l] if r['respondent'] == x), None) for l in labs]
                bx = [next((r[q] for r in by[l] if r['respondent'] == y), None) for l in labs]
                k = cohen(ax, bx)
                if k is not None:
                    ks.append(k)
            summary[f'{q}_mean_pairwise_cohen_kappa'] = sum(ks) / len(ks) if ks else None
            summary[f'{q}_n_pairs'] = len(ks)
        summary['q1_binary_fleiss_kappa'] = fleiss([collections.Counter(('correct' if r['q1'] == 'yes' else 'not')
                                                                        for r in by[l] if r['q1']) for l in labs])
        # majority judgement against the checker, overall and per arm
        def vs_checker(field, ok_value, rows):
            hum = []
            chk = []
            for row in rows:
                m = row[field]
                hum.append(None if m == 'tie' else (m == ok_value))
                chk.append(row['checker_verdict'] == 'completed')
            return binary_agreement(hum, chk)
        summary['q1_majority_vs_checker'] = {'all': vs_checker('q1_correct_majority', 'correct', agree)}
        summary['q3_majority_vs_checker'] = {'all': vs_checker('q3_majority', 'yes', agree)}
        for arm in sorted({row['arm'] for row in agree}):
            sub = [row for row in agree if row['arm'] == arm]
            summary['q1_majority_vs_checker'][arm] = vs_checker('q1_correct_majority', 'correct', sub)
            summary['q3_majority_vs_checker'][arm] = vs_checker('q3_majority', 'yes', sub)
        summary['q1_ties_left_out'] = sum(1 for row in agree if row['q1_correct_majority'] == 'tie')
        summary['q1_each_respondent_vs_checker'] = {}
        for p in resp:
            hum = [None if row[f'q1_{p}'] in ('', None) else row[f'q1_{p}'] == 'yes' for row in agree]
            chk = [row['checker_verdict'] == 'completed' for row in agree]
            summary['q1_each_respondent_vs_checker'][p] = binary_agreement(hum, chk, boot=False)
    json.dump(summary, open(os.path.join(out, 'audit_summary.json'), 'w'), indent=1)
    report['audit'] = {'sheets': len(aud), 'rows': len(res)}
    print(json.dumps(report, indent=1, default=str))


if __name__ == '__main__':
    main()
