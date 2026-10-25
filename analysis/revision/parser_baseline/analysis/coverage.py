"""Parse every benchmark instruction and report the ones the grammar does not read.

Reads task_id and instruction only, from runs_local/bench_v4/tasks.v4c.jsonl.
"""
import json, sys, collections, time
sys.path.insert(0, "analysis/revision/parser_baseline")
import grammar
rows = [json.loads(l) for l in open("runs_local/bench_v4/tasks.v4c.jsonl")]
subset = None
if len(sys.argv) > 1:
    subset = set(json.load(open(sys.argv[1])))
bad = []
ops = collections.Counter()
t0 = time.time()
for r in rows:
    if subset and r["task_id"] not in subset:
        continue
    it = grammar.parse(r["instruction"])
    if not it["recognised"]:
        bad.append((r["task_id"], r["instruction"]))
    else:
        ops[it["op"] + ("/" + it["clarify"] if it["clarify"] else "")] += 1
print("parsed", sum(ops.values()), "unrecognised", len(bad), "in %.1fs" % (time.time() - t0))
print(ops.most_common())
for tid, ins in bad[:80]:
    print(tid, "|", ins)
