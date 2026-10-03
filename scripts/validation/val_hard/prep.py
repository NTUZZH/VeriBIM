"""Inputs of the hard validation generation.

1. Three pools, one per IFC version, holding only the in-run models of the 100
   training buildings: the v10 training pools with the eleven validation
   buildings removed (the twelve benchmark buildings are already excluded or
   out of the run in those pools).
2. A slim instruction file (source model key and instruction) of every task
   already drawn: the training file (which contains the Stage B pool), val-500,
   val-100 and the benchmark, passed to the generator as --seed-instructions so
   that no instruction is drawn twice on one model.
3. The exclusion sets used after generation: task ids, and (building, target
   GlobalId, operation) triples, of the benchmark, val-500, val-100 and the
   Stage B pool (the GRPO pools are subsets of the Stage B pool, checked).
"""
import json
from pathlib import Path

ROOT = Path(".")
RL = ROOT / "runs_local"
OUT = RL / "stage_b_v10/val_hard"
VALIDATION = {"BLD001", "BLD006", "BLD008", "BLD011", "BLD022", "BLD024",
              "BLD033", "BLD034", "BLD037", "BLD041", "BLD047"}
POOLS = {"IFC2X3": RL / "corpus_v10/pool_v10_IFC2X3.json",
         "IFC4": RL / "corpus_v10/migrator_v2/pool_v10_IFC4_plus.json",
         "IFC4X3": RL / "corpus_v10/migrator_v2/pool_v10_IFC4X3_plus.json"}
TRAIN = RL / "stage_b_v10/tasks_stage_b_v10.jsonl"
BENCH = RL / "bench_v4/tasks.v4b.jsonl"
VAL500 = RL / "stage_a_v10/val_tasks_500_v3b.jsonl"
VAL100 = RL / "stage_a_v10/val_tasks_100_v3b.jsonl"
STAGE_B_POOL = RL / "stage_b_v10/pool_v10.json"
GRPO_POOLS = [RL / "stage_c_v10/pool_hard_v10.json", RL / "stage_c_v10/pool_informative_v10.json"]


def rows(path):
    with open(path, encoding="utf-8") as h:
        for line in h:
            if line.strip():
                yield json.loads(line)


def triples(r):
    ids = set((r.get("target") or {}).get("guids") or [])
    ids |= set((r.get("edit_guids") or {}).get("target") or [])
    return {(r["building_id"], g, r["operation"]) for g in ids}


def main():
    bench_buildings = set()
    for r in rows(BENCH):
        bench_buildings.add(r["building_id"])
    report = {"pools": {}}
    for ver, path in POOLS.items():
        pool = json.load(open(path))
        keep = [m for m in pool["models"]
                if m["in_run"] and m["building_id"] not in VALIDATION
                and m["building_id"] not in bench_buildings]
        assert all(m["schema"] == ver for m in keep), ver
        new = dict(pool)
        new["models"] = keep
        new["n_models"] = new["n_models_in_run"] = len(keep)
        new["n_buildings"] = new["n_buildings_in_run"] = len({m["building_id"] for m in keep})
        new["buildings"] = [b for b in (pool.get("buildings") or [])
                            if (b.get("building_id") if isinstance(b, dict) else b)
                            in {m["building_id"] for m in keep}]
        new["derived_from"] = str(path.relative_to(ROOT))
        new["derivation"] = ("in-run models of the training buildings only: validation buildings "
                             f"{sorted(VALIDATION)} and benchmark buildings removed")
        out = OUT / "pools" / f"pool_valhard_{ver}.json"
        out.write_text(json.dumps(new, indent=1))
        report["pools"][ver] = {"source": str(path.relative_to(ROOT)), "models": len(keep),
                                "buildings": new["n_buildings"],
                                "origin": {o: sum(1 for m in keep if m["origin"] == o)
                                           for o in sorted({m["origin"] for m in keep})}}

    # instructions already drawn, per source model key
    n = 0
    with open(OUT / "work/seed_instructions.jsonl", "w", encoding="utf-8") as h:
        for path in (TRAIN, VAL500, VAL100, BENCH):
            for r in rows(path):
                h.write(json.dumps({"source_model": {"key": r["source_model"]["key"]},
                                    "instruction": r["instruction"]}, ensure_ascii=False) + "\n")
                n += 1
    report["seed_instructions"] = n

    pool_ids = set(json.load(open(STAGE_B_POOL)))
    for p in GRPO_POOLS:
        assert set(json.load(open(p))) <= pool_ids, p
    excl_ids, excl_triples = {}, {}
    pool_rows = [r for r in rows(TRAIN) if r["task_id"] in pool_ids]
    assert len(pool_rows) == len(pool_ids)
    for name, recs in (("bench_v4b", list(rows(BENCH))), ("val500_v3b", list(rows(VAL500))),
                       ("val100_v3b", list(rows(VAL100))), ("stage_b_pool", pool_rows)):
        excl_ids[name] = sorted(r["task_id"] for r in recs)
        excl_triples[name] = sorted({"|".join(t) for r in recs for t in triples(r)})
    (OUT / "work/exclusions.json").write_text(json.dumps(
        {"ids": excl_ids, "triples": excl_triples,
         "bench_buildings": sorted(bench_buildings)}, indent=0))
    report["exclusions"] = {k: {"ids": len(excl_ids[k]), "triples": len(excl_triples[k])} for k in excl_ids}
    report["bench_buildings"] = sorted(bench_buildings)
    (OUT / "work/prep_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
