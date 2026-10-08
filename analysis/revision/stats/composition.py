"""Composition of the 2,100-task benchmark (tasks.v4c.jsonl), per part and in total (read-only on every input).

Selection roles (core cell, requirement-family layer cell, size top-up) are not stored per task. They are rebuilt
by re-running the selection functions of runs_local/wave_v2/build_e2_v3.py (imported, nothing written) on
runs_local/bench_v4/work/<V>/candidates.jsonl with the recorded seeds 20260930/31/32 and the 64 requirement families
of work/<V>/select_report.json; the rebuilt union must equal work/<V>/selected.jsonl. The 94 v4b replacements
(REPAIR_REPORT.txt) and the 8 v4c replacements (v4c_repair/changed_ids.json) inherit the role of the task they
replace.

    taskset -c 8-9 env OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
        python analysis/revision/stats/composition.py
"""
import importlib.util, json, re, sys
from collections import Counter, defaultdict
sys.dont_write_bytecode = True
sys.path.insert(0, 'analysis/revision/stats')
from common import ROOT, BENCH, OUT, VERS, load_tasks   # noqa: E402

sys.path.insert(0, f'{ROOT}/code')
spec = importlib.util.spec_from_file_location('build_e2_v3', f'{ROOT}/runs_local/wave_v2/build_e2_v3.py')
drv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drv)
from modifc_gen.build_e2 import CATEGORIES, OPERATIONS, CELL_QUOTA, CHAIN_QUOTA, NULL_CAP, round_robin, kind  # noqa
from modifc_gen import families as F   # noqa: E402

T, S108, S324 = load_tasks()
role = {}
recon = {}
for i, v in enumerate(VERS):
    rep = json.load(open(f'{BENCH}/work/{v}/select_report.json'))
    drv.TARGET_FAMILIES = tuple(rep['family_cells'])          # the 64 families of the 0.9.0 selection
    pool = drv.load(f'{BENCH}/work/{v}/candidates.jsonl')
    seed = 20260930 + i
    keep = [t for t in pool if t.get('tier') in ('single', 'compositional')
            and not (t['tier'] == 'single' and kind(t) == 'translate' and drv.floor_of(t) > NULL_CAP)]
    cells = {f'{c}/{o}': [t for t in keep if t['tier'] == 'single' and t['category'] == c and t['operation'] == o]
             for c in CATEGORIES for o in OPERATIONS}
    chains = [t for t in keep if t['tier'] == 'compositional']
    quotas, _ = drv.attr_quota(cells, CELL_QUOTA, 9 * CELL_QUOTA + CHAIN_QUOTA)
    core = []
    for name, rws in sorted(cells.items()):
        core.extend(drv.select_cell(rws, CELL_QUOTA, quotas[name], lambda t: (t['building_id'], t['family']), seed))
    core_chains = round_robin(chains, CHAIN_QUOTA, lambda t: (t['building_id'], kind(t)), seed)
    core += core_chains
    layers, have = drv.fill_layers(keep, core, int(round(drv.ATTR_TARGET_SHARE * drv.TOTAL_MAX)), drv.TOTAL_MAX)
    filler = drv.top_up(keep, core + layers, drv.TOTAL_MIN, seed)
    sel = {json.loads(l)['task_id'] for l in open(f'{BENCH}/work/{v}/selected.jsonl') if l.strip()}
    got = [t['task_id'] for t in core + layers + filler]
    recon[v] = {'rebuilt': len(got), 'equal_to_selected': set(got) == sel and len(got) == len(sel),
                'core': len(core), 'core_chains': len(core_chains), 'layer': len(layers), 'top_up': len(filler),
                'report_core_layer_topup': [rep['n_core'], rep['n_layer_cells'], rep['n_size_top_up']]}
    for t in core:
        role[t['task_id']] = 'core_chain' if t['tier'] == 'compositional' else 'core_cell'
    for t in layers:
        role[t['task_id']] = 'layer'
    for t in filler:
        role[t['task_id']] = 'top_up'
    for t in layers:   # which target families each layer task was taken for
        role[t['task_id'] + '#families'] = sorted(drv.families_of(t) & set(drv.TARGET_FAMILIES))

# replacements inherit the role of the task they replace
rep_map = {}
for line in open(f'{BENCH}/REPAIR_REPORT.txt'):
    m = re.match(r'^\s+(\S+) -> (\S+)\s+\[', line)
    if m:
        rep_map[m.group(2)] = m.group(1)
v4c = json.load(open(f'{BENCH}/v4c_repair/changed_ids.json'))
for old, new in v4c.items():
    rep_map[new] = rep_map.get(old, old)   # a v4c replacement of a v4b replacement goes back to the v4 slot
ROLE = {}
missing = []
for t in T:
    src = t if t in role else rep_map.get(t)
    if src is None or src not in role:
        missing.append(t)
        continue
    ROLE[t] = role[src]
assert not missing, missing[:5]
fam_layer = {f.tag: f.layer for f in F.FAMILIES}
fam_group = {f.tag: f.group for f in F.FAMILIES}

out = {'source': 'runs_local/bench_v4/tasks.v4c.jsonl (2,100 tasks, the file every result was scored against)',
       'role_reconstruction': recon, 'replacements_mapped': {'v4b': sum(1 for k in rep_map if k not in v4c.values()),
                                                             'v4c': len(v4c)}, 'parts': {}}
for part in VERS + ['ALL']:
    ids = [t for t in T if part == 'ALL' or T[t]['ifc_version'] == part]
    single = [t for t in ids if T[t]['tier'] == 'single']
    chains = [t for t in ids if T[t]['tier'] == 'compositional']
    p = {'tasks': len(ids), 'single': len(single), 'chains': len(chains),
         'roles': dict(Counter(ROLE[t] for t in ids)),
         'single_by_cell_all_roles': {f'{o}/{c}': sum(1 for t in single if T[t]['operation'] == o and T[t]['category'] == c)
                                      for o in OPERATIONS for c in CATEGORIES},
         'core_by_cell': {f'{o}/{c}': sum(1 for t in single if ROLE[t] == 'core_cell' and T[t]['operation'] == o
                                          and T[t]['category'] == c) for o in OPERATIONS for c in CATEGORIES},
         'chains_by_operation': dict(Counter(T[t]['operation'] for t in chains)),
         'chains_by_cell': dict(sorted(Counter(f"{T[t]['operation']}/{T[t]['category']}" for t in chains).items())),
         'chains_by_edit_kind': dict(Counter(T[t]['edit_kind'] for t in chains)),
         'chains_by_role': dict(Counter(ROLE[t] for t in chains)),
         'operation_mix_all_tiers': dict(Counter(T[t]['operation'] for t in ids)),
         'category_mix_all_tiers': dict(Counter(T[t]['category'] for t in ids)),
         'underspecified': sum(1 for t in ids if T[t]['clarification']),
         'underspecified_by_role': dict(Counter(ROLE[t] for t in ids if T[t]['clarification'])),
         'underspecified_by_operation': dict(Counter(T[t]['operation'] for t in ids if T[t]['clarification'])),
         'origin': dict(Counter(T[t]['origin'] for t in ids)),
         'buildings': len({T[t]['building_id'] for t in ids}),
         'tasks_per_building': dict(sorted(Counter(T[t]['building_id'] for t in ids).items())),
         'origin_by_building': dict(sorted(Counter(f"{T[t]['building_id']}|{T[t]['origin']}" for t in ids).items()))}
    # layer cells: tasks per requirement-family group (layer of the taxonomy) of the families each layer task carries
    lay = [t for t in ids if ROLE[t] == 'layer']
    lg = defaultdict(set)
    lt = Counter()
    for t in lay:
        fams = set(T[t]['families'] or []) & set(fam_layer)
        lays = {fam_layer[f] for f in fams}
        for f in fams:
            lg[fam_layer[f]].add(f)
        for L in lays:
            lt[L] += 1
    p['layer_tasks'] = len(lay)
    p['layer_tasks_by_family_layer'] = {L: {'families_present': len(lg[L]), 'tasks_carrying_one': lt[L]}
                                        for L in sorted(lg)}
    p['tasks_per_target_family_whole_part'] = dict(sorted(Counter(
        f for t in ids for f in set(T[t]['families'] or []) if f in fam_layer and not f.startswith('op.create.revit')).items()))
    tgt = json.load(open(f'{BENCH}/work/IFC2X3/select_report.json'))['family_cells']
    cnt = Counter(f for t in ids for f in set(T[t]['families'] or []) if f in tgt)
    by = defaultdict(lambda: {'target_families': 0, 'present': 0, 'at_least_12_per_part': 0, 'tasks_carrying_one': 0})
    for f in tgt:
        L_ = fam_layer.get(f, 'unknown')
        by[L_]['target_families'] += 1
        by[L_]['present'] += cnt[f] > 0
        by[L_]['at_least_12_per_part'] += cnt[f] >= (12 if part != 'ALL' else 36)
    for t in ids:
        for L_ in {fam_layer.get(f) for f in set(T[t]['families'] or []) if f in tgt}:
            by[L_]['tasks_carrying_one'] += 1
    p['target_families_by_layer'] = dict(sorted(by.items()))
    if part != 'ALL':
        fc_ = json.load(open(f'{BENCH}/work/{part}/select_report.json'))['family_cells']
        p['families_below_12'] = {f: {'tasks_v4c': cnt[f], 'candidates_in_pool': fc_[f]['candidates'],
                                      'in_set_v4_selection': fc_[f]['in_set']} for f in sorted(tgt) if cnt[f] < 12}
    p['note_layer_counts'] = ('tasks_carrying_one counts every task of the part (any role) that carries at least one '
                              'target family of that taxonomy layer; a task can carry families of several layers, so '
                              'the counts overlap. at_least_12_per_part uses 36 for the total.')
    out['parts'][part] = p
# reconcile
for part in VERS:
    r = out['parts'][part]['roles']
    out['parts'][part]['reconcile'] = (f"core cells {r.get('core_cell', 0)} + core chains {r.get('core_chain', 0)} + layer "
                                       f"{r.get('layer', 0)} + top-up {r.get('top_up', 0)} = "
                                       f"{sum(r.values())}")
a = out['parts']['ALL']
out['reviewer_arithmetic'] = {
    'cells_times_36': 3 * 9 * 36, 'chains_all_parts': a['chains'],
    'remainder': 2100 - 3 * 9 * 36 - a['chains'],
    'explanation': 'The 972 core single tasks (36 per operation x category cell, 9 cells, 3 parts) and the 367 chains '
                   '(324 core chains, 108 per part, plus chains taken by the layer cells) leave 761 tasks; these are '
                   'the single tasks taken to bring each of the 64 requirement families to 12 tasks (layer cells) '
                   'and the zero-floor single tasks that bring each part to 700 (size top-up).',
    'roles_all_parts': a['roles']}
json.dump(out, open(f'{OUT}/composition.json', 'w'), indent=1)

# LaTeX table: rows = composition lines, columns = parts and total
P = out['parts']
L = [r'% Generated by analysis/revision/stats/composition.py from composition.json.',
     r'\begin{table}[htbp]', r'\centering',
     r'\caption{Composition of the 2,100-task benchmark per IFC version part.}', r'\label{tab:composition}',
     r'\footnotesize', r'\setlength{\tabcolsep}{5pt}', r'\begin{tabular}{@{}lrrrr@{}}', r'\toprule',
     r'Tasks & IFC2X3 & IFC4 & IFC4X3 & Total \\', r'\midrule']


def row(lab, f):
    return ' & '.join([lab] + [f'{f(P[k]):,}' for k in VERS + ['ALL']]) + r' \\'


L.append(r'\multicolumn{5}{@{}l}{\textit{Single tasks}} \\')
for o in OPERATIONS:
    for c in CATEGORIES:
        L.append(row(f'\\quad {o.capitalize()}, {c}', lambda p, k=f'{o}/{c}': p['single_by_cell_all_roles'][k]))
L.append(row(r'\quad of which core cell tasks (36 per cell)', lambda p: p['roles'].get('core_cell', 0)))
L.append(row(r'\quad of which requirement-family tasks', lambda p: p['roles'].get('layer', 0)
             - p['chains_by_role'].get('layer', 0)))
L.append(row(r'\quad of which size top-up tasks', lambda p: p['roles'].get('top_up', 0)))
L.append(row(r'\quad all single tasks', lambda p: p['single']))
L.append(r'\midrule')
L.append(r'\multicolumn{5}{@{}l}{\textit{Chains of dependent edits}} \\')
for o in OPERATIONS:
    L.append(row(f'\\quad {o.capitalize()}', lambda p, o=o: p['chains_by_operation'].get(o, 0)))
L.append(row(r'\quad all chains', lambda p: p['chains']))
L.append(r'\midrule')
L.append(row('Clarification tasks', lambda p: p['underspecified']))
L.append(row('Native files', lambda p: p['origin'].get('native', 0)))
L.append(row('Migrated files', lambda p: p['origin'].get('migrated', 0)))
L.append(row('Buildings', lambda p: p['buildings']))
L.append(r'\midrule')
L.append(row('All tasks', lambda p: p['tasks']))
L += [r'\bottomrule', r'\end{tabular}', r'\end{table}', '']
open(f'{OUT}/tab_composition.tex', 'w').write('\n'.join(L))
print(json.dumps(recon, indent=0))
for k in VERS + ['ALL']:
    print(k, P[k]['roles'], P[k]['chains_by_role'], P[k]['chains_by_operation'], P[k]['underspecified'], P[k]['origin'])
