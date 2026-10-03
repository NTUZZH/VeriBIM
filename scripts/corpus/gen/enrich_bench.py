"""Benchmark candidates with the pool's origin fields (every emitted record carries origin and source_relpath).
Writes gen/bench_candidates_v10_<VER>.jsonl = gen/bench_<ver>/tasks.jsonl plus ifc_version, origin, source_relpath,
looked up by source_model.key in the pool the run used.  Ids are unchanged (candidates only; selection is later)."""
import json, sys
from collections import Counter
from pathlib import Path
C10 = Path("runs_local/corpus_v10"); G = C10 / "gen"
POOL = {"IFC2X3": C10 / "pool_bench_v10_IFC2X3.json",
        "IFC4": C10 / "migrator_v2/pool_bench_v10_IFC4.json",
        "IFC4X3": C10 / "migrator_v2/pool_bench_v10_IFC4X3.json"}
ver = sys.argv[1]
by_key = {m["key"]: m for m in json.load(open(POOL[ver]))["models"]}
rows = [json.loads(l) for l in open(G / f"bench_{ver.lower()}" / "tasks.jsonl") if l.strip()]
cnt = Counter()
with open(G / f"bench_candidates_v10_{ver}.jsonl", "w", encoding="utf-8") as h:
    for r in rows:
        e = by_key[r["source_model"]["key"]]
        assert e["building_id"] == r["building_id"]
        r["ifc_version"] = e["schema"]; r["origin"] = e["origin"]; r["source_relpath"] = e["source_relpath"]
        cnt[(r["origin"], r["operation"], r["category"])] += 1
        h.write(json.dumps(r, ensure_ascii=False) + "\n")
print(ver, len(rows), dict(Counter(r["origin"] for r in rows)), len({r["building_id"] for r in rows}), "buildings")
