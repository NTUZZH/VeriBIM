"""Candidate model outputs for the verdict audit (packet B).

Arms, all run with the helper library and its note:
  VeriBIM-9B   runs_local/bench_v4/results/local108_lib_all/per_task_grpo_v10b_c10.jsonl (108-task subset),
               extension: local324_lib_all/per_task_grpo_v10b_c10.jsonl (the other 216 tasks of the 324 subset)
  commercial   hosted108_lib_all/per_task_claude-sonnet-5-5.jsonl (108),
               extension: hosted324_lib_all/per_task_claude-sonnet-5-5.jsonl (216 others; files in hosted216_lib_all*)
  base 9B      local108_libnote_all/per_task_Qwen3.5-9B.jsonl (108),
               extension: full_note_all/per_task_Qwen3.5-9B.jsonl (the tasks of the 324 subset it covers)
A case is completed when all three score axes are >= 0.90 (the benchmark rule).
"""
import json, os

ROOT = ''
B4 = ROOT + 'runs_local/bench_v4/'
R = B4 + 'results/'
ARMS = {
    'veribim': {'label': 'VeriBIM-9B', 'model': 'grpo_v10b_c10',
                'primary': R + 'local108_lib_all/per_task_grpo_v10b_c10.jsonl',
                'extension': R + 'local324_lib_all/per_task_grpo_v10b_c10.jsonl'},
    'commercial': {'label': 'commercial model claude-sonnet-5-5 with the library note', 'model': 'claude-sonnet-5-5',
                   'primary': R + 'hosted108_lib_all/per_task_claude-sonnet-5-5.jsonl',
                   'extension': R + 'hosted324_lib_all/per_task_claude-sonnet-5-5.jsonl'},
    'base': {'label': 'Qwen3.5-9B untrained, with the library note', 'model': 'Qwen3.5-9B',
             'primary': R + 'local108_libnote_all/per_task_Qwen3.5-9B.jsonl',
             'extension': R + 'full_note_all/per_task_Qwen3.5-9B.jsonl'},
}
AXES = ('geometry', 'semantics', 'topology')


def load_tasks():
    out = {}
    for line in open(B4 + 'tasks.v4c.jsonl'):
        r = json.loads(line)
        out[r['task_id']] = r
    return out


def candidates(tasks=None):
    """One row per (arm, task) on fully specified tasks of the 324-task subset with a score."""
    tasks = tasks or load_tasks()
    s108 = set(json.load(open(B4 + 'subset_108_hosted.v4c.json')))
    s324 = set(json.load(open(B4 + 'subset_324.v4c.json')))
    rows = []
    for arm, a in ARMS.items():
        for pool, path in (('108', a['primary']), ('324', a['extension'])):
            for line in open(path):
                r = json.loads(line)
                t = r['task_id']
                if pool == '108' and t not in s108:
                    continue
                if pool == '324' and (t in s108 or t not in s324):
                    continue
                tk = tasks[t]
                if tk['clarification']:
                    continue
                s = r.get('score') or {}
                ax = [s.get(k) for k in AXES]
                if any(v is None for v in ax):
                    continue
                completed = all(v >= 0.9 for v in ax)
                near = any(0.85 <= v <= 0.95 for v in ax)
                n_fail_axes = sum(v < 0.9 for v in ax)
                committed = bool(r.get('committed'))
                reply_only = (not committed) and r.get('stop_reason') == 'completed'
                rows.append(dict(arm=arm, pool=pool, task_id=t, operation=tk['operation'], category=tk['category'],
                                 version=tk['ifc_version'], tier=tk['tier'], edit_kind=tk['edit_kind'],
                                 building=tk.get('building_id'), family=tk['family'],
                                 scores={k: round(float(v), 4) for k, v in zip(AXES, ax)},
                                 completed=completed, near_threshold=near, n_fail_axes=n_fail_axes,
                                 committed=committed, stop_reason=r.get('stop_reason'), reply_only=reply_only,
                                 rounds=r.get('tool_rounds'), edited_ifc=r.get('edited_ifc'),
                                 input_ifc=tk['input_ifc'], per_task_file=os.path.relpath(path, ROOT)))
    return rows
