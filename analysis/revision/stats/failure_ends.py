"""How each run on the 108-task subset ended, per arm, from the per-task rows (read-only on every input).

Classes (first match wins): completed (all axes >= 0.9); wrong commit (committed a file, not completed); then, for
runs without a commit: sandbox crash (stop_reason sandbox_crash), tool timeout (stop_reason tool_timeout), model turn
truncated (stop_reason output_truncated, or last finish reason 'length'), context limit (stop_reason
context_overflow), round budget exhausted (stop_reason budget_exhausted), provider error (any other non-empty error),
reply without commit (stop_reason completed). A malformed tool call never ends a run in this harness (no stop reason
for it exists); malformed, non-compiling and failing calls are counted per run instead.

    taskset -c 8-9 env OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
        python analysis/revision/stats/failure_ends.py
"""
import json, sys
from collections import Counter
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
import numpy as np
from common import *          # noqa: F401,F403

T, S108, S324 = load_tasks()
rows, sets = load_all(T, S108, S324)
UND = {t for t in T if T[t]['clarification']}
CLS = ['completed', 'wrong_commit', 'round_budget', 'tool_timeout', 'turn_truncated', 'context_limit',
       'sandbox_crash', 'provider_error', 'reply_no_commit', 'other']


def end_class(r):
    if done(r):
        return 'completed'
    if r.get('committed'):
        return 'wrong_commit'
    sr = r.get('stop_reason')
    fin = r.get('finish_reasons') or []
    if sr == 'sandbox_crash':
        return 'sandbox_crash'
    if sr == 'tool_timeout':
        return 'tool_timeout'
    if sr == 'output_truncated' or (fin and fin[-1] == 'length'):
        return 'turn_truncated'
    if sr == 'context_overflow':
        return 'context_limit'
    if sr == 'budget_exhausted':
        return 'round_budget'
    if r.get('error'):
        return 'provider_error'
    if sr == 'completed':
        return 'reply_no_commit'
    return 'other'


ARMS = [('Final model, with library', (108, 'ours')), ('Imitation, with library', (108, 'sft', 'lib')),
        ('Imitation, alone', (108, 'sft', 'alone')), ('Preference stage, with library', (108, 'dpo', 'lib')),
        ('Untrained, alone', (108, 'base', 'alone')), ('Untrained, library note', (108, 'base', 'libnote'))]
for mid, nm, _ in COMMERCIAL:
    ARMS += [(f'{nm}, with library', (108, mid, 'lib')), (f'{nm}, alone', (108, mid, 'alone'))]
ARMS.append(('Final model, 2,100-task benchmark', (2100, 'ours')))
out = {'rule': __doc__.split('\n\n')[1].strip(), 'arms': {}}
ids108 = sorted(S108)
for lab, k in ARMS:
    ids = ids108 if k[0] == 108 else sorted(T)
    R_ = rows[k]
    c = Counter(end_class(R_[t]) for t in ids)
    fail = [t for t in ids if not done(R_[t])]
    tc = np.array([R_[t].get('tool_calls') or 0 for t in ids])
    wf = np.array([R_[t].get('well_formed_calls') or 0 for t in ids])
    cc = np.array([R_[t].get('compiling_calls') or 0 for t in ids])
    rc = np.array([R_[t].get('running_calls') or 0 for t in ids])
    e = {'source': arm_paths()[k][0].replace(ROOT + '/', ''), 'n': len(ids),
         'classes': {x: c.get(x, 0) for x in CLS},
         'wrong_commit_on_clarification_task': sum(1 for t in fail if end_class(R_[t]) == 'wrong_commit' and t in UND),
         'wrong_commit_on_edit_task': sum(1 for t in fail if end_class(R_[t]) == 'wrong_commit' and t not in UND),
         'reply_no_commit_on_clarification_task': sum(1 for t in fail if end_class(R_[t]) == 'reply_no_commit' and t in UND),
         'round_budget_on_clarification_task': sum(1 for t in fail if end_class(R_[t]) == 'round_budget' and t in UND),
         'wrong_commit_score_mean': (float(np.mean([R_[t].get('final') or 0 for t in fail if end_class(R_[t]) == 'wrong_commit']))
                                     if c.get('wrong_commit') else None),
         'mean_tool_rounds_all': round(float(np.mean([R_[t].get('tool_rounds') or 0 for t in ids])), 2),
         'mean_tool_rounds_failed': (round(float(np.mean([R_[t].get('tool_rounds') or 0 for t in fail])), 2) if fail else None),
         'mean_tool_rounds_completed': round(float(np.mean([R_[t].get('tool_rounds') or 0 for t in ids if done(R_[t])])), 2)
         if any(done(R_[t]) for t in ids) else None,
         'tool_calls': int(tc.sum()), 'malformed_calls': int((tc - wf).sum()),
         'runs_with_malformed_call': int(((tc - wf) > 0).sum()),
         'non_compiling_calls': int((wf - cc).sum()), 'calls_failing_at_run_time': int((cc - rc).sum()),
         'share_of_calls_failing_at_run_time': round(float((cc - rc).sum() / max(1, tc.sum())), 4),
         'runs_with_blocked_file_access': sum(1 for t in ids if (R_[t].get('sandbox_blocked') or 0) > 0),
         'blocked_file_access_events': int(sum(R_[t].get('sandbox_blocked') or 0 for t in ids)),
         'rows_reread_after_sandbox_crash': sum(1 for t in ids if R_[t].get('replaced_stop_reason') == 'sandbox_crash'),
         'stop_reason_counts': dict(Counter(R_[t].get('stop_reason') for t in ids)),
         'committed_by_stop_reason_on_failures': dict(Counter(f"{bool(R_[t].get('committed'))}|{R_[t].get('stop_reason')}"
                                                             for t in fail)),
         'tool_rounds_histogram': dict(sorted(Counter(int(R_[t].get('tool_rounds') or 0) for t in ids).items()))}
    assert sum(e['classes'].values()) == len(ids)
    out['arms'][lab] = e
out['distinguishable'] = ('Every class above is read from fields on the row. Two requested classes cannot occur as a run '
                          "end in these files: 'malformed tool call / format error' (the harness answers a malformed call "
                          "with an error message and the run goes on; such calls are counted per run) and 'provider "
                          "error' (no row of the reported files carries an API error other than the context-length error, "
                          'which is the context-limit class; rows whose sandbox crashed were re-read after the '
                          '2026-09-30 repair and carry the re-read outcome, counted in rows_reread_after_sandbox_crash).')
json.dump(out, open(f'{OUT}/failure_ends.json', 'w'), indent=1)

TAB = [a for a in ARMS if a[1][0] == 108 and (a[1][-1] == 'lib' or a[1] in ((108, 'ours'), (108, 'base', 'libnote')))]
TAB = [a for a in TAB if a[1] != (108, 'dpo', 'lib')]
HEAD = {'completed': 'Completed', 'wrong_commit': r'\begin{tabular}[b]{@{}c@{}}Wrong\\commit\end{tabular}',
        'round_budget': r'\begin{tabular}[b]{@{}c@{}}Round\\budget\end{tabular}',
        'tool_timeout': r'\begin{tabular}[b]{@{}c@{}}Tool\\timeout\end{tabular}',
        'turn_truncated': r'\begin{tabular}[b]{@{}c@{}}Truncated\\turn\end{tabular}',
        'context_limit': r'\begin{tabular}[b]{@{}c@{}}Context\\limit\end{tabular}',
        'sandbox_crash': r'\begin{tabular}[b]{@{}c@{}}Sandbox\\crash\end{tabular}',
        'provider_error': r'\begin{tabular}[b]{@{}c@{}}Provider\\error\end{tabular}',
        'reply_no_commit': r'\begin{tabular}[b]{@{}c@{}}Reply,\\no commit\end{tabular}', 'other': 'Other'}
used = [x for x in CLS if any(out['arms'][l]['classes'][x] for l, _ in TAB)]
L = [r'% Generated by analysis/revision/stats/failure_ends.py from failure_ends.json.',
     r'\begin{table}[htbp]', r'\centering',
     r'\caption{How each run on the 108-task subset ended. Wrong commit: an edited file that the checker does not count '
     r'as completed, including an edit on a clarification task. Rounds: mean tool rounds per task.}',
     r'\label{tab:failureends}', r'\footnotesize', r'\setlength{\tabcolsep}{3.5pt}',
     r'\begin{tabular}{@{}l' + 'r' * (len(used) + 1) + r'@{}}', r'\toprule',
     'Model and arm & ' + ' & '.join(HEAD[x] for x in used) + r' & Rounds \\', r'\midrule']
for lab, k in TAB:
    e = out['arms'][lab]
    L.append(' & '.join([lab.replace(', with library', ', with library')] + [str(e['classes'][x]) for x in used] +
                        [f"{e['mean_tool_rounds_all']:.2f}"]) + r' \\')
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
open(f'{OUT}/tab_failure_ends.tex', 'w').write('\n'.join(L))
for lab, _ in ARMS:
    e = out['arms'][lab]
    print(f"{lab:<36}", {k: v for k, v in e['classes'].items() if v}, 'wc_clar', e['wrong_commit_on_clarification_task'],
          'rounds', e['mean_tool_rounds_all'], e['mean_tool_rounds_failed'], 'malf', e['malformed_calls'],
          e['runs_with_malformed_call'], 'runfail', e['calls_failing_at_run_time'], 'blocked', e['runs_with_blocked_file_access'],
          'reread', e['rows_reread_after_sandbox_crash'])
