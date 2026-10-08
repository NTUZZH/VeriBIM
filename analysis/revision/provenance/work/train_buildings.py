import json, collections, sys
sys.path.insert(0,'code/corpus')
import numpy as np, similarity as sim
ROOT='.'
bt=collections.Counter(); src=collections.Counter()
for l in open(ROOT+'/runs_local/stage_b_v10/tasks_stage_b_v10.jsonl'):
    t=json.loads(l); bt[t['building_id']]+=1
    src[t.get('source_relpath') or t.get('input_ifc')]+=1
pool=json.load(open(ROOT+'/runs_local/corpus_v10/pool_v10_all.json'))
tb=set(bt)
print('training building ids in task file',len(tb), 'GNI', sum(1 for b in tb if b.startswith('GNI')), 'public', sum(1 for b in tb if not b.startswith('GNI')))
pub=[m for m in pool['models'] if m['collection']!='gni' and m['origin']=='native' and m['in_run'] and m['building_id'] in tb]
gni=[m for m in pool['models'] if m['collection']=='gni' and m['origin']=='native' and m['in_run'] and m['building_id'] in tb]
print('native public files on training buildings',len(pub),'buildings',len({m['building_id'] for m in pub}))
print('native GNI files on training buildings',len(gni),'buildings',len({m['building_id'] for m in gni}))
vb=sorted({m['building_id'] for m in pool['models'] if m['in_run'] and m['building_id'] not in tb})
print('in-run buildings with no training task (validation buildings):',vb)
desc=json.load(open(ROOT+'/data/corpus_descriptors.json'))['corpus']
P=[(m['key'],desc[m['relpath']]) for m in pub]
voc=sorted({t for _,v in P for t in v['element_type_histogram']})
S=sim.score(P,P,voc)[0]
def comps(S,n,thr):
    par=list(range(n))
    def f(i):
        while par[i]!=i: par[i]=par[par[i]]; i=par[i]
        return i
    for a in range(n):
        for b in range(a+1,n):
            if S[a,b]>=thr: par[f(a)]=f(b)
    g=collections.defaultdict(list)
    for i in range(n): g[f(i)].append(i)
    return sorted(g.values(),key=len,reverse=True)
c=comps(S,len(P),0.80)
print('public training files clusters at 0.80 (single linkage):',len(c),[len(x) for x in c][:8])
print('largest public clusters:',[[P[i][0]+':'+pub[i]['building_id'] for i in x] for x in c[:4]])
# tasks per GNI file set
gt=collections.Counter()
for b,n in bt.items():
    if b.startswith('GNI'): gt['GNI-project' if 'project' in b else 'GNI-fundamentals']+=n
    else: gt['public']+=n
print('training tasks by source', dict(gt), sum(gt.values()))
