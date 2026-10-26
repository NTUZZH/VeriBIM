"""Template catalogue for the canonicalizer: generated instructions from the TRAINING instruction files,
grouped by the parser's intent (op, target kind, clarify), up to K per group, deterministic.
No instruction equal to an original instruction of the 172 reworded tasks or the 200 practitioner tasks."""
import json, sys, random, glob, collections
sys.path.insert(0, 'analysis/revision/parser_baseline')
import grammar
K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
ROOT = ''
banned = set()
for p in ['analysis/revision/reworded_benchmark/tasks_bench_rw.jsonl',
          'analysis/revision/colleague_packets/results/rewrite_tasks.jsonl']:
    for l in open(ROOT + p):
        r = json.loads(l); banned.add(r.get('original_instruction') or ''); banned.add(r['instruction'])
        # the practitioner tasks' base generated instruction is not stored here; names differ per building anyway
groups = collections.defaultdict(list); n = 0; unrec = 0
for p in sorted(glob.glob(ROOT + 'runs_local/stage_a_v10/instructions_*.jsonl')):
    for l in open(p):
        ins = json.loads(l)['instruction']; n += 1
        if ins in banned: continue
        it = grammar.parse(ins)
        if not it.get('recognised'): unrec += 1; continue
        t = (it.get('parse') or {}).get('t'); tk = t.get('k') if isinstance(t, dict) else None
        groups[(it['op'], tk, it.get('clarify'), (it.get('form') or {}).get('request'))].append(ins)
rng = random.Random(20261026); out = []
for key in sorted(groups, key=str):
    ex = sorted(set(groups[key])); rng.shuffle(ex); out.extend(ex[:K])
print(f'{n} training instructions, {unrec} not recognised by the parser, {len(groups)} groups, {len(out)} examples', file=sys.stderr)
json.dump({'k': K, 'n_groups': len(groups), 'examples': out}, open(sys.argv[2], 'w'), indent=0, ensure_ascii=False)
