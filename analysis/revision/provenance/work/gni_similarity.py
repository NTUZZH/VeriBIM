"""Describe the 79 admitted native GNI student files with the corpus descriptor
(code/corpus/scan_ifc.describe + the metric footprint of code/corpus/extract_units.py), score every pair with
code/corpus/similarity.score (S_struct = 0.6 S_type + 0.4 S_layout), cluster at 0.80, and score the public
training files the same way from data/corpus_descriptors.json. Read-only on data/; no BIM-Edit file is opened."""
import json, os, sys, collections
for v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"): os.environ[v] = "1"
ROOT = '.'
sys.path.insert(0, ROOT + '/code/corpus')
import numpy as np
from scan_ifc import describe, sha256_of
import similarity as sim
OUT = ROOT + '/analysis/revision/provenance'
CACHE = OUT + '/work/gni_descriptors.jsonl'

pool = json.load(open(ROOT + '/runs_local/corpus_v10/pool_v10_all.json'))
gni = [m for m in pool['models'] if m['collection'] == 'gni' and m['origin'] == 'native']
done = {}
if os.path.exists(CACHE):
    for l in open(CACHE):
        r = json.loads(l); done[r['relpath']] = r
import ifcopenshell, ifcopenshell.util.unit as uu
with open(CACHE, 'a') as fh:
    for m in sorted(gni, key=lambda m: m['bytes']):
        rel = m['relpath']
        if rel in done: continue
        f = ifcopenshell.open(os.path.join(ROOT, rel))
        d = describe(f); s = float(uu.calculate_unit_scale(f)); del f
        bb = d.get('placement_bbox')
        if bb:
            mb = [round(v * s, 4) for v in bb]; dx, dy = mb[3] - mb[0], mb[4] - mb[1]
            d.update(placement_bbox_m=mb, footprint_m2=round(dx * dy, 4),
                     footprint_aspect=(round(max(dx, dy) / min(dx, dy), 4) if min(dx, dy) > 1e-9 else None))
        else:
            d.update(placement_bbox_m=None, footprint_m2=None, footprint_aspect=None)
        d.update(relpath=rel, key=m['key'], building_id=m['building_id'], schema=m['schema'], in_run=m['in_run'],
                 held_out=m['held_out'], unit_scale_to_m=s, sha256=m['sha256'])
        fh.write(json.dumps(d) + '\n'); fh.flush(); done[rel] = d
        print('described', m['key'], m['bytes'] // 1000000, 'MB', flush=True)

recs = [(done[m['relpath']]['key'], done[m['relpath']]) for m in sorted(gni, key=lambda m: m['key'])]
vocab = sorted({t for _, v in recs for t in v['element_type_histogram']})
S, st, sl, subs = sim.score(recs, recs, vocab)
keys = [k for k, _ in recs]; inrun = np.array([v['in_run'] for _, v in recs]); held = ~inrun

def components(S, idx, thr):
    idx = list(idx); parent = {i: i for i in idx}
    def find(i):
        while parent[i] != i: parent[i] = parent[parent[i]]; i = parent[i]
        return i
    for a in idx:
        for b in idx:
            if a < b and S[a, b] >= thr: parent[find(a)] = find(b)
    groups = collections.defaultdict(list)
    for i in idx: groups[find(i)].append(i)
    return sorted(groups.values(), key=len, reverse=True)

def greedy_leaders(S, idx, thr):
    """Leader clustering (complete coverage, each member >= thr to its leader), as a second, stricter count."""
    left = list(idx); leaders = []
    while left:
        # leader = the file with most neighbours >= thr among those left
        best = max(left, key=lambda i: sum(S[i, j] >= thr for j in left))
        members = [j for j in left if j == best or S[best, j] >= thr]
        leaders.append((best, members)); left = [j for j in left if j not in members]
    return leaders

tr = [i for i in range(len(keys)) if inrun[i]]
comp = components(S, tr, 0.80); lead = greedy_leaders(S, tr, 0.80)
fund = [i for i in tr if 'BIMfundamentals' in recs[i][1]['relpath']]
proj = [i for i in tr if 'BIMprojects' in recs[i][1]['relpath']]
iu = np.triu_indices(len(tr), 1); Str = S[np.ix_(tr, tr)][iu]
res = dict(
    measure='S_struct = 0.6*S_type + 0.4*S_layout (code/corpus/similarity.py score())',
    n_admitted_native=len(keys), n_training=int(inrun.sum()), n_held_out=int(held.sum()),
    training_by_set=dict(fundamentals=len(fund), projects=len(proj)),
    training_buildings=len({recs[i][1]['building_id'] for i in tr}),
    training_pairwise=dict(n_pairs=int(len(Str)), min=round(float(Str.min()), 4), median=round(float(np.median(Str)), 4),
                           max=round(float(Str.max()), 4), share_ge_080=round(float((Str >= 0.8).mean()), 4)),
    clusters_at_080_single_linkage=dict(n=len(comp), sizes=[len(c) for c in comp],
                                        members=[[keys[i] for i in c] for c in comp]),
    clusters_at_080_leader=dict(n=len(lead), sizes=[len(m) for _, m in lead],
                                members=[[keys[i] for i in m] for _, m in lead]),
    fundamentals_internal=dict(n=len(fund), **({} if len(fund) < 2 else dict(
        min=round(float(S[np.ix_(fund, fund)][np.triu_indices(len(fund), 1)].min()), 4),
        median=round(float(np.median(S[np.ix_(fund, fund)][np.triu_indices(len(fund), 1)])), 4)))),
)
heldout = {}
for h in [i for i in range(len(keys)) if held[i]]:
    j = max(tr, key=lambda j: S[h, j])
    heldout[keys[h]] = dict(relpath=recs[h][1]['relpath'], building_id=recs[h][1]['building_id'],
                            max_S_struct_to_training_student_file=round(float(S[h, j]), 4), nearest=keys[j],
                            S_type=round(float(st[h, j]), 4), S_layout=round(float(sl[h, j]), 4),
                            n_training_files_ge_080=int(sum(S[h, t] >= 0.8 for t in tr)))
res['held_out_vs_training_students'] = heldout
per_proj = collections.defaultdict(float)
for k, v in heldout.items(): per_proj[v['building_id']] = max(per_proj[v['building_id']], v['max_S_struct_to_training_student_file'])
res['held_out_project_max'] = dict(per_proj)

# public training files, same measure, from the corpus descriptors (no BIM-Edit entries used)
desc = json.load(open(ROOT + '/data/corpus_descriptors.json'))['corpus']
pub = [m for m in pool['models'] if m['collection'] != 'gni' and m['origin'] == 'native' and m['in_run']]
P = [(m['key'], desc[m['relpath']]) for m in pub if m['relpath'] in desc]
miss = [m['relpath'] for m in pub if m['relpath'] not in desc]
vocabP = sorted({t for _, v in P for t in v['element_type_histogram']})
SP = sim.score(P, P, vocabP)[0]
cP = components(SP, range(len(P)), 0.80); lP = greedy_leaders(SP, range(len(P)), 0.80)
res['public_training_files'] = dict(n_files=len(P), missing_descriptor=miss, buildings=len({m['building_id'] for m in pub}),
    clusters_at_080_single_linkage=dict(n=len(cP), sizes=[len(c) for c in cP]),
    clusters_at_080_leader=dict(n=len(lP), sizes=[len(m) for _, m in lP]))
# student vs public cross (max)
vocabX = sorted(set(vocab) | set(vocabP))
SX = sim.score([recs[i] for i in tr], P, vocabX)[0]
res['training_students_vs_public_training_max'] = round(float(SX.max()), 4)
json.dump(res, open(OUT + '/work/gni_similarity_result.json', 'w'), indent=1)

feat = dict(
    description=('Descriptor of every admitted native GNI student file (75 in the training pool, 4 held out: GNI projects 7 '
                 'and 8), as consumed by code/corpus/similarity.py score(): element_type_histogram, storey_count, '
                 'footprint_m2, footprint_aspect, n_products (plus the metric placement box). S_struct between any two '
                 'records = 0.6 * cosine(type histograms over the union vocabulary) + 0.4 * mean of the defined symmetric '
                 'ratios min/max of (storey_count+1), footprint_m2, footprint_aspect, n_products. pairwise_S_struct is the '
                 'matrix over the 79 files in the order of "files".'),
    files=[dict(key=k, relpath=v['relpath'], building_id=v['building_id'], schema=v['schema'], in_training=bool(v['in_run']),
                held_out=bool(v['held_out']), sha256=v['sha256'],
                element_type_histogram=v['element_type_histogram'], n_products=v['n_products'],
                storey_count=v['storey_count'], footprint_m2=v['footprint_m2'], footprint_aspect=v['footprint_aspect'],
                placement_bbox_m=v['placement_bbox_m'], unit_scale_to_m=v['unit_scale_to_m']) for k, v in recs],
    pairwise_S_struct=[[round(float(x), 4) for x in row] for row in S])
json.dump(feat, open(OUT + '/student_features.json', 'w'), indent=1)
print(json.dumps({k: v for k, v in res.items() if k not in ('clusters_at_080_single_linkage', 'clusters_at_080_leader')}, indent=1)[:4000])
print('single-linkage', res['clusters_at_080_single_linkage']['n'], res['clusters_at_080_single_linkage']['sizes'])
print('leader', res['clusters_at_080_leader']['n'], res['clusters_at_080_leader']['sizes'])
