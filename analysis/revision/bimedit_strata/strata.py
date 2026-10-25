"""BIM-Edit scores stratified by the structural similarity of each scene file to the closest training student file.

Reads the per-task BIM-Edit score files of the four arms (paper's harness, published rules), the task list of the
benchmark (input_ifc -> scene file), and the scene-similarity table of the provenance report (best_train = highest
structural similarity S_struct to any training student file; 0.80 = the pre-registered 'same design' threshold).
Writes strata.json and strata.csv next to this script. The score files are those of results/bimedit/, the scene table is
bimedit_scene_similarity.json beside this script, and the BIM-Edit task file is not redistributed (see "Evaluating on
BIM-Edit" in README.md).
"""
import csv, json, os, random, collections, re
HERE=os.path.dirname(os.path.abspath(__file__)); ROOT=os.environ.get('VERIBIM_ROOT') or os.path.abspath(os.path.join(HERE, '..', '..', '..'))
E1=f'{ROOT}/results/bimedit'
ARMS={'final':f'{E1}/scores_bench_grpo_v10b_c10.csv','base':f'{E1}/scores_bench_Qwen3.5-9B.csv',
      'sonnet_alone':f'{E1}/sonnet_alone/scores_bench_claude-sonnet-5-5.csv','sonnet_lib':f'{E1}/sonnet_lib/scores_bench_claude-sonnet-5-5.csv'}
sim={d['scene']:d for d in json.load(open(f'{HERE}/bimedit_scene_similarity.json'))}
tasks={}
for l in open(f'{ROOT}/data/bimedit/BIM-Edit-Tasks/tasks.jsonl'):
    r=json.loads(l); b=os.path.basename(r['input_ifc'])
    scene=b if b in sim else None
    if scene is None:
        # realistic inputs are '<hash>-input-<task>.ifc'; the scene file is the ground truth '<hash>.ifc' or the input stem
        stem=b.split('-input')[0]
        for cand in (stem+'.ifc', b, os.path.basename(r['ground_truth_ifc'])):
            if cand in sim: scene=cand; break
    tasks[r['task_id']]={'scene':scene,'input':b,'op':r['operation'],'cat':r['category'],'type':'realistic' if '/realistic/' in r['input_ifc'] else 'simple'}
unmatched=[t for t,v in tasks.items() if v['scene'] is None]
print('tasks',len(tasks),'unmatched scenes',len(unmatched), unmatched[:5])
S={a:{r['task_id']:float(r['final_score']) for r in csv.DictReader(open(p))} for a,p in ARMS.items()}
for a in S: assert len(S[a])==324, (a,len(S[a]))
def stratum(t):
    v=tasks[t]; 
    if v['scene'] is None: return 'unmatched'
    bt=sim[v['scene']]['best_train']
    if v['type']=='simple': return 'simple (all < 0.80)'
    return 'realistic, similar (>= 0.80)' if bt>=0.80 else 'realistic, not similar (< 0.80)'
groups=collections.defaultdict(list)
for t in tasks: groups[stratum(t)].append(t)
rng=random.Random(20260929)
def boot(diffs,n=10000):
    m=len(diffs); out=[]
    for _ in range(n):
        s=[diffs[rng.randrange(m)] for _ in range(m)]; out.append(sum(s)/m)
    out.sort(); return out[int(0.025*n)], out[int(0.975*n)-1]
res={}
rows=[]
for g,ts in sorted(groups.items()):
    e={'n':len(ts),'n_scenes':len({tasks[t]['scene'] for t in ts}),'by_op':dict(collections.Counter(tasks[t]['op'] for t in ts))}
    for a in ARMS: e[a]=round(sum(S[a][t] for t in ts)/len(ts),3)
    for a,b in (('final','base'),('sonnet_alone','final'),('sonnet_lib','final')):
        d=[S[a][t]-S[b][t] for t in ts]; lo,hi=boot(d); e[f'{a}_minus_{b}']=[round(sum(d)/len(d),3),round(lo,3),round(hi,3)]
    # within-stratum per operation means for ours
    e['final_by_op']={op:round(sum(S['final'][t] for t in ts if tasks[t]['op']==op)/max(1,sum(1 for t in ts if tasks[t]['op']==op)),3) for op in ('create','update','delete')}
    res[g]=e; rows.append((g,e['n'],e['n_scenes'],e['final'],e['base'],e['sonnet_alone'],e['sonnet_lib'],*e['final_minus_base'],*e['sonnet_alone_minus_final']))
# similarity bins for realistic scenes
bins=[(0,0.6),(0.6,0.7),(0.7,0.8),(0.8,0.85),(0.85,1.01)]
res['realistic_by_bin']={}
for lo,hi in bins:
    ts=[t for t in tasks if tasks[t]['scene'] and tasks[t]['type']=='realistic' and lo<=sim[tasks[t]['scene']]['best_train']<hi]
    if ts: res['realistic_by_bin'][f'[{lo},{hi})']={'n':len(ts),'n_scenes':len({tasks[t]['scene'] for t in ts}),**{a:round(sum(S[a][t] for t in ts)/len(ts),3) for a in ARMS}}
# correlation of ours-minus-base with similarity over realistic scenes (scene-level means)
sc=collections.defaultdict(list)
for t in tasks:
    if tasks[t]['scene'] and tasks[t]['type']=='realistic': sc[tasks[t]['scene']].append(t)
pairs=[(sim[s]['best_train'], sum(S['final'][t]-S['base'][t] for t in ts)/len(ts), sum(S['final'][t] for t in ts)/len(ts)) for s,ts in sc.items()]
import statistics
def spearman(x,y):
    rx={v:i for i,v in enumerate(sorted(x))}; ry={v:i for i,v in enumerate(sorted(y))}
    n=len(x); d2=sum((rx[a]-ry[b])**2 for a,b in zip(x,y)); return 1-6*d2/(n*(n*n-1))
res['scene_level_realistic']={'n_scenes':len(pairs),'spearman_sim_vs_ours_minus_base':round(spearman([p[0] for p in pairs],[p[1] for p in pairs]),3),'spearman_sim_vs_ours':round(spearman([p[0] for p in pairs],[p[2] for p in pairs]),3)}
json.dump(res,open(f'{HERE}/strata.json','w'),indent=1)
with open(f'{HERE}/strata.csv','w',newline='') as f:
    w=csv.writer(f); w.writerow(['stratum','n_tasks','n_scenes','VeriBIM','base','sonnet_alone','sonnet_lib','ours_minus_base','lo','hi','sonnet_alone_minus_ours','lo','hi']); w.writerows(rows)
print(json.dumps(res,indent=1))
