"""Tabulate the instruction skeletons of the benchmark task file.

Reads only task_id and instruction from runs_local/bench_v4/tasks.v4c.jsonl;
quoted strings, GlobalIds and numbers are replaced by placeholders so the
remaining words show which template rendered each instruction.
"""
import json, re, sys, collections
GUID = r"[0-9A-Za-z_$]{22}"
def skeleton(s):
    s = re.sub(r"^(The client wants one change made to this model\.|The design team has agreed on one change to this model\.|The client has asked for the following change\.) ", "", s)
    s = re.sub(r"^Please (\w)", lambda m: m.group(1).upper(), s)
    s = re.sub(r"^Can you (\w)", lambda m: m.group(1).upper(), s)
    s = re.sub(r"'[^']*'(?=[ ,.;)?]|$)", "'Q'", s)
    s = re.sub(r"(?<![0-9A-Za-z_$])" + GUID + r"(?![0-9A-Za-z_$])", "G", s)
    s = re.sub(r"-?\d+(?:[.,]\d+)?", "N", s)
    return s
rows = [json.loads(l) for l in open(sys.argv[1])]
c = collections.Counter(skeleton(r["instruction"]) for r in rows)
print(len(c), "distinct skeletons")
for k, v in c.most_common():
    print(v, "|", k)
