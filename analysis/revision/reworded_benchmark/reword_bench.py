"""Reword the instructions of the 200 drawn benchmark tasks (draw_200.json) with the procedure that produced the
validation set's reworded instructions (runs_local/stage_a_v10/val100_rw/rewrite_v3b.py, 2026-10-03).

Nothing of that procedure is re-implemented here: the module is imported from its file and its BRIEF, RETRY_NOTE,
check(), chat() and one() are used as they are, so the model (gpt-5.6, served as gpt-5.6-sol), the rewording prompt, the
default sampling and reasoning settings (none sent), max_completion_tokens 1600, three attempts per task with the
retry note naming the failed check, four concurrent requests, and the machine checks are those of the 85.
Added here, all outside the procedure: a spend guard (no new task starts once the list-price estimate reaches
GUARD_USD; US$4/M input, US$20/M output, bench_v4/hosted_cost.py), the bench task fields, a diagnostic count of
eight-word sequences shared with the original (not a gate for the 85, so not a gate here), and the manual audit
file audit_reject.json read by --build.

Usage: python reword_bench.py --probe | --run | --build
The API key is read by rewrite_v3b.load_key() from the user's key file and is never printed or written.
"""
import argparse, collections, concurrent.futures as cf, datetime, hashlib, importlib.util, json, os, re, sys, threading

HERE = os.path.dirname(os.path.abspath(__file__))
P = '.'
SRC = P + '/runs_local/stage_a_v10/val100_rw/rewrite_v3b.py'
SRC_SHA = hashlib.sha256(open(SRC, 'rb').read()).hexdigest()
spec = importlib.util.spec_from_file_location('rewrite_v3b', SRC)
RW = importlib.util.module_from_spec(spec); spec.loader.exec_module(RW)

TASKS = P + '/runs_local/bench_v4/tasks.v4d.jsonl'
DRAW = os.path.join(HERE, 'draw_200.json')
ATTEMPTS = os.path.join(HERE, 'reword_attempts.json')
AUDIT = os.path.join(HERE, 'audit_reject.json')
OUT_TASKS = os.path.join(HERE, 'tasks_bench_rw.jsonl')
OUT_SUB = os.path.join(HERE, 'subset_bench_rw.json')
OUT_MAP = os.path.join(HERE, 'mapping_original_to_reworded.jsonl')
OUT_CHECKS = os.path.join(HERE, 'checks_bench_rw.json')
SUFFIX = '-rw'
PRICE_IN, PRICE_OUT = 4.0, 20.0
GUARD_USD = float(os.environ.get('GUARD_USD', '2.5'))


def cost(u):
    return u.get('prompt_tokens', 0) / 1e6 * PRICE_IN + u.get('completion_tokens', 0) / 1e6 * PRICE_OUT


def ngrams(s, n=8):
    w = re.findall(r"[a-z0-9_$'.+-]+", s.lower())
    return {tuple(w[i:i + n]) for i in range(len(w) - n + 1)}


def load():
    d = json.load(open(DRAW))
    assert hashlib.sha256(open(TASKS, 'rb').read()).hexdigest() == d['tasks_file_sha256']
    T = {}
    for l in open(TASKS):
        t = json.loads(l)
        T[t['task_id']] = t
    tasks = [T[i] for i in d['task_ids']]
    assert len(tasks) == 200 and all(t['prompt'] == t['instruction'] and t.get('clarification') is None for t in tasks)
    return d, tasks


def run(tasks):
    RW.KEY = RW.load_key()
    started = datetime.datetime.now().isoformat(timespec='seconds')
    stop = threading.Event()
    results = {}

    def guarded(t):
        with RW.ULOCK:
            spent = cost(RW.USAGE)
        if spent >= GUARD_USD or stop.is_set():
            stop.set()
            return t, None, [{'attempt': 0, 'failed': ['not_started:spend_guard %.2f' % spent]}]
        return RW.one(t)

    with cf.ThreadPoolExecutor(RW.WORKERS) as ex:
        for t, new, log in ex.map(guarded, tasks):
            results[t['task_id']] = (new, log)
            print('%-34s %s attempts=%d %s | spend $%.3f' % (t['task_id'], 'REWORDED' if new else 'kept', len(log),
                  '' if new else log[-1]['failed'], cost(RW.USAGE)), flush=True)
    per_task = []
    for t in tasks:
        new, log = results[t['task_id']]
        per_task.append({'task_id': t['task_id'], 'original': t['instruction'], 'reworded': new,
                         'passed_machine_checks': bool(new), 'attempts': len(log),
                         'passed_first_attempt': bool(new) and len(log) == 1,
                         'failed_checks': [a['failed'] for a in log if a['failed']], 'attempt_log': log})
    rep = {'procedure_source': SRC, 'procedure_source_sha256': SRC_SHA, 'model': RW.MODEL, 'endpoint': RW.ENDPOINT,
           'max_completion_tokens': RW.MAX_COMPLETION_TOKENS, 'attempts_max': RW.ATTEMPTS, 'workers': RW.WORKERS,
           'reasoning_effort': 'not sent (API default), as for the 85', 'temperature': 'not sent (API default), as for the 85',
           'prompt': RW.BRIEF, 'retry_note': RW.RETRY_NOTE, 'started': started,
           'finished': datetime.datetime.now().isoformat(timespec='seconds'),
           'aborted': RW.ABORT.is_set(), 'spend_guard_hit': stop.is_set(),
           'usage': dict(RW.USAGE), 'transport_failures': dict(RW.TRANSPORT_FAILS),
           'cost_usd_list_price': round(cost(RW.USAGE), 4), 'price_usd_per_m': [PRICE_IN, PRICE_OUT],
           'per_task': per_task}
    json.dump(rep, open(ATTEMPTS, 'w'), indent=1, ensure_ascii=False)
    n = sum(p['passed_machine_checks'] for p in per_task)
    print('passed machine checks', n, 'of', len(per_task), '| first attempt', sum(p['passed_first_attempt'] for p in per_task),
          '| usage', dict(RW.USAGE), '| cost $%.3f' % cost(RW.USAGE))


def build(d, tasks):
    rep = json.load(open(ATTEMPTS))
    audit = json.load(open(AUDIT))  # {task_id: reason}; written after reading every machine-accepted pair by hand
    per = {p['task_id']: p for p in rep['per_task']}
    out, mapping, rows = [], [], []
    for t in tasks:
        p = per[t['task_id']]
        new = p['reworded']
        if new:  # re-run the machine checks of the 85 on the accepted text
            fails, _, ov = RW.check(t['instruction'], new)
            assert not fails, (t['task_id'], fails)
        rej = audit.get(t['task_id']) if new else None
        keep = bool(new) and not rej
        shared8 = sorted(' '.join(g) for g in ngrams(t['instruction']) & ngrams(new)) if new else []
        rows.append({'task_id': t['task_id'], 'reworded_task_id': t['task_id'] + SUFFIX if keep else None,
                     'family': t['family'], 'operation': t['operation'], 'building_id': t['building_id'],
                     'ifc_version': t['ifc_version'], 'attempts': p['attempts'],
                     'passed_machine_checks': p['passed_machine_checks'], 'passed_first_attempt': p['passed_first_attempt'],
                     'failed_checks_per_attempt': p['failed_checks'],
                     'word_overlap_final': round(RW.check(t['instruction'], new)[2], 3) if new else None,
                     'instruction_changed': (new is not None and new != t['instruction']),
                     'audit_rejected': rej, 'in_eval_file': keep,
                     'shared_8gram_count': len(shared8), 'shared_8grams': shared8[:5]})
        if keep:
            r = dict(t)
            r['task_id'] = t['task_id'] + SUFFIX
            r['original_task_id'] = t['task_id']
            r['instruction'] = new
            r['prompt'] = new
            r['wording_rewritten'] = True
            r['original_instruction'] = t['instruction']
            out.append(r)
            mapping.append({'original_task_id': t['task_id'], 'reworded_task_id': r['task_id'],
                            'original_instruction': t['instruction'], 'reworded_instruction': new})
    with open(OUT_TASKS, 'w') as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + '\n')
    json.dump([r['task_id'] for r in out], open(OUT_SUB, 'w'), indent=1)
    with open(OUT_MAP, 'w') as fh:
        for m in mapping:
            fh.write(json.dumps(m, ensure_ascii=False) + '\n')
    C = collections.Counter
    ev = [r for r in rows if r['in_eval_file']]
    summ = {
        'n_drawn': len(rows), 'passed_machine_checks': sum(r['passed_machine_checks'] for r in rows),
        'passed_first_attempt': sum(r['passed_first_attempt'] for r in rows),
        'attempt_histogram_passed': dict(sorted(C(r['attempts'] for r in rows if r['passed_machine_checks']).items())),
        'failed_all_attempts': [r['task_id'] for r in rows if not r['passed_machine_checks']],
        'audit_rejected': {r['task_id']: r['audit_rejected'] for r in rows if r['audit_rejected']},
        'in_eval_file': len(ev),
        'failed_check_counts_all_attempts': dict(C(f.split(':')[0] for r in rows for fs in r['failed_checks_per_attempt'] for f in fs)),
        'eval_buildings': dict(sorted(C(r['building_id'] for r in ev).items())),
        'eval_family_operation': dict(sorted(C('%s|%s' % (r['family'], r['operation']) for r in ev).items())),
        'eval_ifc_version': dict(sorted(C(r['ifc_version'] for r in ev).items())),
        'diagnostic_shared_8gram': {'eval_tasks_with_one_or_more': sum(r['shared_8gram_count'] > 0 for r in ev),
                                    'note': 'not a check of the 85 (28 of the 85 share an 8-word sequence when GlobalIds and numbers count as words); reported only'},
        'cost_usd_list_price': rep['cost_usd_list_price'], 'usage': rep['usage'],
        'output_tasks_sha256': hashlib.sha256(open(OUT_TASKS, 'rb').read()).hexdigest(),
    }
    json.dump({'summary': summ, 'per_task': rows}, open(OUT_CHECKS, 'w'), indent=1, ensure_ascii=False)
    print(json.dumps(summ, indent=1))


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument('--probe', action='store_true'); g.add_argument('--run', action='store_true'); g.add_argument('--build', action='store_true')
    a = ap.parse_args()
    d, tasks = load()
    if a.probe:
        RW.KEY = RW.load_key()
        t = tasks[0]
        new, finish, u, served = RW.chat(RW.BRIEF + t['instruction'])
        print('served model:', served, '| finish:', finish, '| usage:', json.dumps(u), '| cost $%.4f' % cost(u))
        print('ORIG:', t['instruction']); print('NEW :', new); print('check:', RW.check(t['instruction'], new)[:2])
    elif a.run:
        assert not os.path.exists(ATTEMPTS), 'attempt file exists; refusing to overwrite'
        run(tasks)
    else:
        build(d, tasks)


if __name__ == '__main__':
    main()
