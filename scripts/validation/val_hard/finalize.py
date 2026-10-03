"""Hard validation candidates: merge the three generator runs, check, select.

Per version: the generator's tasks.jsonl gets the v10 merge treatment
(scripts/corpus/gen/merge_v10.py): one id suffix per run (-vh3, -vh4,
-vh2), the gold paths renamed with it, and ifc_version, origin, source_relpath,
topup_round, v10_run and v10_task_file added from the run's pool.  Then:
  - tasks whose (building, target GlobalId, operation) triple is in the benchmark,
    val-500, val-100 or the Stage B pool are dropped;
  - tasks whose instruction contains one of the eight-word runs known to be shared
    with the external benchmark (overlap8_train.json) are dropped;
  - every record must have split train, a null-edit score, a training building, and
    an id unused by any task file on record.
Selection: 1,000 per version, spread evenly over the nine operation x category
cells, with the compositional share of the Stage B pool inside each cell, and a
round robin over buildings inside a cell (seed 20260930).
Writes candidates_v10.jsonl, candidates_v10_ids.json and work/finalize_report.json.
"""
import json, random, re, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
RL = ROOT / "runs_local"
VH = RL / "stage_b_v10/val_hard"
VERSIONS = {"IFC4X3": "vh3", "IFC4": "vh4", "IFC2X3": "vh2"}
VALIDATION = {"BLD001", "BLD006", "BLD008", "BLD011", "BLD022", "BLD024",
              "BLD033", "BLD034", "BLD037", "BLD041", "BLD047"}
PER_VERSION = 1000
SEED = 20260930
OPS = ("create", "delete", "update")
CATS = ("direct", "spatial", "topological")
#: every task file whose ids the new set must not reuse
ID_FILES = [RL / "stage_b_v10/tasks_stage_b_v10.jsonl", RL / "bench_v4/tasks.v4b.jsonl",
            RL / "bench_v4/tasks.jsonl", RL / "stage_a_v10/val_tasks_500_v3b.jsonl",
            RL / "stage_a_v10/val_tasks_100_v3b.jsonl", RL / "corpus_v10/gen/val_tasks_v10.jsonl",
            RL / "corpus_v10/gen/tasks_v10_new.jsonl",
            RL / "corpus_v10/gen/bench_candidates_v10_IFC2X3.jsonl",
            RL / "corpus_v10/gen/bench_candidates_v10_IFC4.jsonl",
            RL / "corpus_v10/gen/bench_candidates_v10_IFC4X3.jsonl",
            RL / "stage_a_v9_dev/out/corpus_tasks_v9.jsonl"]
WORD = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")


def rows(path):
    with open(path, encoding="utf-8") as h:
        for line in h:
            if line.strip():
                yield json.loads(line)


def triples(r):
    ids = set((r.get("target") or {}).get("guids") or [])
    ids |= set((r.get("edit_guids") or {}).get("target") or [])
    return {(r["building_id"], g, r["operation"]) for g in ids}


def grams(text, n=8):
    t = WORD.findall(text.lower())
    return {" ".join(t[i:i + n]) for i in range(len(t) - n + 1)}


def known_shared_grams():
    out = set()
    for name in ("overlap8_train.json",):
        d = json.load(open(RL / "stage_b_v10" / name))
        for ex in d.get("examples") or []:
            out |= set(ex.get("shared") or [])
    return out


def select(recs, n, chain_share, rng):
    """n tasks spread evenly over the nine cells, chain share per cell, round robin over buildings."""
    by_cell = defaultdict(list)
    for r in recs:
        by_cell[(r["operation"], r["category"])].append(r)
    cells = [(o, c) for o in OPS for c in CATS]
    quota = {cell: n // 9 + (1 if i < n % 9 else 0) for i, cell in enumerate(cells)}
    # a cell short of its quota gives the rest to the others, evenly
    while True:
        short = {c: quota[c] - len(by_cell[c]) for c in cells if len(by_cell[c]) < quota[c]}
        if not short:
            break
        spare = sum(short.values())
        for c in short:
            quota[c] = len(by_cell[c])
        open_cells = [c for c in cells if len(by_cell[c]) > quota[c]]
        if not open_cells:
            break
        for i in range(spare):
            quota[open_cells[i % len(open_cells)]] += 1

    def round_robin(pool, k):
        by_b = defaultdict(list)
        for r in sorted(pool, key=lambda r: r["task_id"]):
            by_b[r["building_id"]].append(r)
        for v in by_b.values():
            rng.shuffle(v)
        keys = sorted(by_b)
        rng.shuffle(keys)
        out, depth = [], 0
        while len(out) < k:
            added = False
            for b in keys:
                if depth < len(by_b[b]) and len(out) < k:
                    out.append(by_b[b][depth]); added = True
            if not added:
                break
            depth += 1
        return out

    picked = []
    for c in cells:
        pool = by_cell[c]
        chains = [r for r in pool if r["tier"] != "single"]
        singles = [r for r in pool if r["tier"] == "single"]
        want_chain = min(len(chains), round(quota[c] * chain_share))
        want_single = quota[c] - want_chain
        if want_single > len(singles):
            want_chain = min(len(chains), quota[c] - len(singles))
            want_single = quota[c] - want_chain
        picked += round_robin(chains, want_chain) + round_robin(singles, want_single)
    return picked, quota


def main():
    excl = json.load(open(VH / "work/exclusions.json"))
    bench_buildings = set(excl["bench_buildings"])
    ex_triples = {k: {tuple(t.split("|")) for t in v} for k, v in excl["triples"].items()}
    ex_ids = set().union(*map(set, excl["ids"].values()))
    known_ids = set(ex_ids)
    #: instruction texts already used by a task the model trained on or is read on
    #: (training file incl. the Stage B pool, benchmark, val-500, val-100)
    known_instructions = set()
    for f in ID_FILES:
        if f.exists():
            for r in rows(f):
                known_ids.add(r["task_id"])
                if f.name in ("tasks_stage_b_v10.jsonl", "tasks.v4b.jsonl", "val_tasks_500_v3b.jsonl",
                              "val_tasks_100_v3b.jsonl"):
                    known_instructions.add(r["instruction"])
    shared8 = known_shared_grams()
    pool_ids = set(json.load(open(RL / "stage_b_v10/pool_v10.json")))
    pool_tier = Counter(r["tier"] for r in rows(RL / "stage_b_v10/tasks_stage_b_v10.jsonl")
                        if r["task_id"] in pool_ids)
    chain_share = pool_tier["compositional"] / sum(pool_tier.values())

    report = {"chain_share_target": round(chain_share, 4), "stage_b_pool_tiers": dict(pool_tier),
              "known_shared_8grams": sorted(shared8), "versions": {}}
    selected_all, generated_all, clarify_side = [], [], []
    rng = random.Random(SEED)
    for ver, suffix in VERSIONS.items():
        run = f"gen_{ver.lower()}"
        tasks = VH / run / "tasks.jsonl"
        if not tasks.exists():
            report["versions"][ver] = {"missing": str(tasks)}
            continue
        pool = json.load(open(VH / "pools" / f"pool_valhard_{ver}.json"))
        by_key = {m["key"]: m for m in pool["models"]}
        recs, drops = [], Counter()
        drop_examples = defaultdict(list)
        for r in rows(tasks):
            old = r["task_id"]; new = f"{old}-{suffix}"
            r["task_id"] = new
            for field in ("gold_model", "ground_truth_ifc"):
                v = r.get(field)
                if v:
                    assert v.endswith(f"/{old}.ifc"), (field, old, v)
                    r[field] = v[: -len(f"{old}.ifc")] + f"{new}.ifc"
            entry = by_key[r["source_model"]["key"]]
            assert entry["building_id"] == r["building_id"], new
            assert entry["relpath"] == r["input_ifc"] and entry["sha256"] == r["source_model"]["sha256"], new
            r["topup_round"] = "main"
            r["v10_run"] = f"val_hard_{ver.lower()}"
            r["v10_task_file"] = str(tasks.relative_to(ROOT))
            r["ifc_version"] = entry["schema"]
            r["origin"] = entry["origin"]
            r["source_relpath"] = entry["source_relpath"]
            generated_all.append(r)
            hit = [k for k, s in ex_triples.items() if triples(r) & s]
            reason = None
            if r["building_id"] in bench_buildings or r["building_id"] in VALIDATION:
                reason = "not_a_training_building"
            elif r.get("split") != "train":
                reason = "split_not_train"
            elif new in known_ids:
                reason = "id_in_use"
            elif hit:
                reason = "triple_overlap:" + ",".join(sorted(hit))
            elif grams(r["prompt"]) & shared8 or grams(r["instruction"]) & shared8:
                reason = "shared_8gram"
            elif (r.get("verification") or {}).get("null_edit_score") is None:
                # the generator computes no null-edit score for a clarification task
                # (its gold changes nothing); load_pool refuses a record without one
                if r.get("edit_kind") == "clarify":
                    reason = "clarify_no_null_edit_score"
                    clarify_side.append(r)
                else:
                    reason = "no_null_edit_score"
            if reason:
                drops[reason] += 1
                if len(drop_examples[reason]) < 5:
                    drop_examples[reason].append(new)
                continue
            recs.append(r)
        ids = [r["task_id"] for r in recs]
        assert len(ids) == len(set(ids)), ver
        picked, quota = select(recs, PER_VERSION, chain_share, rng)
        # Second stage, kept apart so the first-stage draw stays as it was: a pick whose
        # instruction text is identical to one already used (on another model, e.g. a
        # sibling schema copy of the same building or a student model built from the same
        # template) is replaced by an unpicked eligible task of the same cell and tier,
        # from the building with the fewest picks in that cell.
        chosen = {r["task_id"] for r in picked}
        flagged = [r for r in picked if r["instruction"] in known_instructions]
        replaced = []
        for r in flagged:
            cell = (r["operation"], r["category"], r["tier"])
            spare = [x for x in recs if x["task_id"] not in chosen
                     and (x["operation"], x["category"], x["tier"]) == cell
                     and x["instruction"] not in known_instructions]
            if not spare:  # same cell, either tier
                spare = [x for x in recs if x["task_id"] not in chosen
                         and (x["operation"], x["category"]) == cell[:2]
                         and x["instruction"] not in known_instructions]
            picked = [x for x in picked if x["task_id"] != r["task_id"]]
            chosen.discard(r["task_id"])
            if spare:
                load = Counter(x["building_id"] for x in picked
                               if (x["operation"], x["category"]) == cell[:2])
                spare.sort(key=lambda x: (load[x["building_id"]], x["task_id"]))
                picked.append(spare[0]); chosen.add(spare[0]["task_id"])
                replaced.append([r["task_id"], spare[0]["task_id"]])
            else:
                replaced.append([r["task_id"], None])
        selected_all += picked
        report["versions"][ver] = {
            "generated": sum(1 for r in generated_all if r["ifc_version"] == ver),
            "dropped": dict(drops), "drop_examples": dict(drop_examples),
            "eligible": len(recs), "selected": len(picked),
            "identical_instruction_replaced": replaced,
            "eligible_cells": {f"{o}/{c}": sum(1 for r in recs if (r["operation"], r["category"]) == (o, c))
                               for o in OPS for c in CATS},
            "selected_cells": {f"{o}/{c}": sum(1 for r in picked if (r["operation"], r["category"]) == (o, c))
                               for o in OPS for c in CATS},
            "selected_tiers": dict(Counter(r["tier"] for r in picked)),
            "selected_cells_by_tier": {f"{o}/{c}": dict(Counter(r["tier"] for r in picked
                                                               if (r["operation"], r["category"]) == (o, c)))
                                       for o in OPS for c in CATS},
            "selected_buildings": len({r["building_id"] for r in picked}),
            "selected_models": len({r["input_ifc"] for r in picked}),
            "selected_origin": dict(Counter(r["origin"] for r in picked)),
            "selected_edit_kinds": dict(Counter(r["edit_kind"] for r in picked).most_common()),
            "eligible_buildings": len({r["building_id"] for r in recs}),
        }
    selected_all.sort(key=lambda r: (r["ifc_version"], r["task_id"]))
    out = VH / "candidates_v10.jsonl"
    with out.open("w", encoding="utf-8") as h:
        for r in selected_all:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    (VH / "candidates_v10_ids.json").write_text(json.dumps([r["task_id"] for r in selected_all], indent=1))
    # the generated (unselected) records too, for reference
    with (VH / "work/generated_all.jsonl").open("w", encoding="utf-8") as h:
        for r in generated_all:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    with (VH / "work/clarify_eligible.jsonl").open("w", encoding="utf-8") as h:
        for r in clarify_side:
            h.write(json.dumps(r, ensure_ascii=False) + "\n")
    report["clarify_side_file"] = {"path": "work/clarify_eligible.jsonl", "n": len(clarify_side),
                                   "note": "clarification tasks, no null-edit score; not in candidates"}
    report["n_selected"] = len(selected_all)
    report["buildings_selected"] = sorted({r["building_id"] for r in selected_all})
    report["n_buildings_selected"] = len(report["buildings_selected"])
    (VH / "work/finalize_report.json").write_text(json.dumps(report, indent=1))
    print(json.dumps({k: v for k, v in report.items() if k != "buildings_selected"}, indent=1)[:6000])


if __name__ == "__main__":
    main()
