"""Accuracy check of the two-level quadrature (building and task random intercepts): refit three comparisons with
grids twice as fine in both dimensions (801 x 801 points) and compare beta1, its standard error, the variances and
the likelihood-ratio p with the 401 x 401 fit stored in results/all_results.json."""
import json, math, sys
from multiprocessing import Pool
from pathlib import Path
import numpy as np
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_stats as RS, glmm_ml as G, common as C

IDS = ('2100_dpo_vs_sft', 'valhard_ours_vs_dpo', '108_ours_vs_Sonnet_note')
NAME = 'building and task random intercepts (ML, quadrature)'
KEYS = ('beta1', 'se_beta1', 'lr_p', 'var_building', 'var_task', 'loglik')


def job(a):
    cid, ya, yb, bl = a
    for nm, n in (('ZU', 801), ('ZB', 801)):
        z = np.linspace(-8, 8, n)
        w = -0.5 * z ** 2 - 0.5 * math.log(2 * math.pi) + math.log(z[1] - z[0])
        w[[0, -1]] += math.log(0.5)
        setattr(G, nm, z)
        setattr(G, 'LWU' if nm == 'ZU' else 'LWB', w)
    f = G.fit_building_task(np.array(ya), np.array(yb), bl)
    return cid, {k: f[k] for k in KEYS}


if __name__ == '__main__':
    D = RS.load_data()
    comps = {c['id']: c for c in RS.comparisons(D)}
    A = json.load(open(HERE / 'results/all_results.json'))['comparisons']
    jobs = []
    for cid in IDS:
        c = comps[cid]
        ya = [int(C.done(c['a'][t])) for t in c['ids']]; yb = [int(C.done(c['b'][t])) for t in c['ids']]
        jobs.append((cid, ya, yb, [D['CL'][t] for t in c['ids']]))
    out = {}
    with Pool(3) as p:
        for cid, fine in p.imap_unordered(job, jobs):
            coarse = next(m for m in A[cid]['models'] if m.get('model') == NAME)
            out[cid] = {'grid_401x401': {k: coarse[k] for k in KEYS}, 'grid_801x801': fine}
            print(cid, json.dumps(out[cid]), flush=True)
    json.dump(out, open(HERE / 'results/grid_check.json', 'w'), indent=1)
