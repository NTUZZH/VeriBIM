"""Independent checks of candidates_v10.jsonl (written separately from finalize.py).

Overlap of task ids and of (building, target GlobalId, operation) triples with the
benchmark (v4b and v4), val-500 v3b, val-100 v3b and the Stage B pool (and the two
GRPO pools); benchmark and validation buildings; field-by-field schema against the
v10 records of tasks_stage_b_v10.jsonl; the three readers' loaders
(stage_b.pool.load_train_tasks, stage_a.gate_eval.load_subset,
stage_c.train_grpo.load_pool); source file checksums; eight-word runs against the
known shared set; ids unique across every task file on record.
"""
import hashlib, json, os, re, sys
from collections import Counter
from pathlib import Path

ROOT = Path(".")
RL = ROOT / "runs_local"
VH = RL / "stage_b_v10/val_hard"
sys.path[:0] = [str(ROOT / "code"), str(ROOT / "code/harness")]


def rows(p):
    with open(p, encoding="utf-8") as h:
        for l in h:
            if l.strip():
                yield json.loads(l)


def trip(r, key_fields=("target",)):
    ids = set((r.get("target") or {}).get("guids") or [])
    ids |= set((r.get("edit_guids") or {}).get("target") or [])
    return {(r["building_id"], g, r["operation"]) for g in ids}


def anchor_pairs(r):
    a = r.get("anchor") or {}
    ids = set(a.get("expected") or [])
    for v in (a.get("params") or {}).values():
        if isinstance(v, str) and len(v) == 22:
            ids.add(v)
    return {(r["building_id"], g) for g in ids}


def main():
    cand = list(rows(VH / "candidates_v10.jsonl"))
    ids = [r["task_id"] for r in cand]
    listed = json.load(open(VH / "candidates_v10_ids.json"))
    out = {"n": len(cand), "ids_unique": len(ids) == len(set(ids)), "ids_file_matches": listed == ids}
    train = list(rows(RL / "stage_b_v10/tasks_stage_b_v10.jsonl"))
    pool_ids = set(json.load(open(RL / "stage_b_v10/pool_v10.json")))
    grpo = set(json.load(open(RL / "stage_c_v10/pool_hard_v10.json"))) | set(json.load(open(RL / "stage_c_v10/pool_informative_v10.json")))
    refs = {"bench_v4b": list(rows(RL / "bench_v4/tasks.v4b.jsonl")),
            "bench_v4": list(rows(RL / "bench_v4/tasks.jsonl")),
            "val500_v3b": list(rows(RL / "stage_a_v10/val_tasks_500_v3b.jsonl")),
            "val100_v3b": list(rows(RL / "stage_a_v10/val_tasks_100_v3b.jsonl")),
            "stage_b_pool": [r for r in train if r["task_id"] in pool_ids],
            "grpo_pools": [r for r in train if r["task_id"] in grpo]}
    ct = set().union(*(trip(r) for r in cand))
    ca = set().union(*(anchor_pairs(r) for r in cand))
    cb = {r["building_id"] for r in cand}
    ov = {}
    for k, recs in refs.items():
        rt = set().union(*(trip(r) for r in recs))
        ra = set().union(*(anchor_pairs(r) for r in recs))
        ov[k] = {"n_ref": len(recs), "id_overlap": len(set(ids) & {r["task_id"] for r in recs}),
                 "triple_overlap": len(ct & rt), "building_anchor_overlap": len(ca & ra),
                 "shared_buildings": len(cb & {r["building_id"] for r in recs})}
    out["overlap"] = ov
    bench_b = {r["building_id"] for r in refs["bench_v4b"]}
    val_b = {r["building_id"] for r in refs["val500_v3b"]} | {"BLD001", "BLD006", "BLD008", "BLD011", "BLD022",
                                                             "BLD024", "BLD033", "BLD034", "BLD037", "BLD041", "BLD047"}
    train_b = {r["building_id"] for r in train}
    out["buildings"] = {"n": len(cb), "benchmark": sorted(cb & bench_b), "validation": sorted(cb & val_b),
                        "not_training": sorted(cb - train_b)}
    # ids unused anywhere
    other = set()
    for f in ["stage_b_v10/tasks_stage_b_v10.jsonl", "bench_v4/tasks.v4b.jsonl", "bench_v4/tasks.jsonl",
              "stage_a_v10/val_tasks_500_v3b.jsonl", "stage_a_v10/val_tasks_100_v3b.jsonl",
              "corpus_v10/gen/val_tasks_v10.jsonl", "corpus_v10/gen/tasks_v10_new.jsonl",
              "corpus_v10/gen/bench_candidates_v10_IFC2X3.jsonl", "corpus_v10/gen/bench_candidates_v10_IFC4.jsonl",
              "corpus_v10/gen/bench_candidates_v10_IFC4X3.jsonl", "stage_a_v9_dev/out/corpus_tasks_v9.jsonl"]:
        other |= {r["task_id"] for r in rows(RL / f)}
    out["ids_in_other_files"] = len(set(ids) & other)
    # schema: field set and value types of the v10 records of the Stage B file
    v10 = [r for r in train if r.get("v10_run")]
    ref_keys = Counter(tuple(sorted(r)) for r in v10).most_common(1)[0][0]
    types = {}
    for r in v10[:3000]:
        for k, v in r.items():
            types.setdefault(k, set()).add(type(v).__name__)
    ck = Counter(tuple(sorted(r)) for r in cand)
    bad_types = Counter()
    for r in cand:
        for k, v in r.items():
            if type(v).__name__ not in types.get(k, set()):
                bad_types[(k, type(v).__name__)] += 1
    vkeys_ref = Counter(tuple(sorted(r["verification"])) for r in v10 if r["verification"].get("null_edit_score") is not None).most_common(1)[0][0]
    out["schema"] = {"reference_keys": len(ref_keys), "candidate_key_sets": len(ck),
                     "missing_vs_reference": sorted(set(ref_keys) - set(next(iter(ck)))),
                     "extra_vs_reference": sorted(set(next(iter(ck))) - set(ref_keys)),
                     "type_mismatches": {f"{k}:{t}": n for (k, t), n in bad_types.items()},
                     "verification_keys_match": all(tuple(sorted(r["verification"])) == vkeys_ref for r in cand),
                     "null_edit_score_missing": sum(1 for r in cand if r["verification"].get("null_edit_score") is None),
                     "split": dict(Counter(r["split"] for r in cand)),
                     "generator_version": dict(Counter(r["generator_version"] for r in cand)),
                     "clearance_setting_in_funnel": {}}
    for v in ("ifc4x3", "ifc4", "ifc2x3"):
        f = json.load(open(VH / f"gen_{v}/funnel.json"))
        out["schema"]["clearance_setting_in_funnel"][v] = {"clearance_refusals": f["stages"].get("clearance", 0),
                                                           "seed": None}
    # loaders
    from stage_b.pool import load_train_tasks
    from stage_a.gate_eval import load_subset
    lt = load_train_tasks(VH / "candidates_v10.jsonl", split="train")
    ls = load_subset(VH / "candidates_v10_ids.json", VH / "candidates_v10.jsonl")
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    from stage_c.train_grpo import load_pool
    lp = load_pool(VH / "candidates_v10.jsonl", "train")
    out["loaders"] = {"stage_b.load_train_tasks": len(lt), "stage_a.load_subset": len(ls), "stage_c.load_pool": len(lp)}
    # source files
    srcs = {}
    for r in cand:
        srcs.setdefault(r["input_ifc"], r["source_model"]["sha256"])
    bad = []
    for p, sha in srcs.items():
        h = hashlib.sha256()
        with open(ROOT / p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 22), b""):
                h.update(chunk)
        if h.hexdigest() != sha:
            bad.append(p)
    out["source_files"] = {"n": len(srcs), "sha_mismatch": bad}
    # eight-word runs against the known shared set
    WORD = re.compile(r"[a-z0-9]+(?:[.'-][a-z0-9]+)*")
    known = set()
    for ex in json.load(open(RL / "stage_b_v10/overlap8_train.json")).get("examples") or []:
        known |= set(ex.get("shared") or [])

    def grams(t, n=8):
        w = WORD.findall(t.lower())
        return {" ".join(w[i:i + n]) for i in range(len(w) - n + 1)}
    out["known_shared_8grams_hits"] = sum(1 for r in cand if grams(r["prompt"]) & known or grams(r["instruction"]) & known)
    # eight-word runs against the VeriBIM benchmark instructions (same templates, so expected to be many)
    bg = set()
    for r in refs["bench_v4b"]:
        bg |= grams(r["instruction"])
    out["instructions_sharing_8gram_with_veribim_bench_v4b"] = sum(1 for r in cand if grams(r["instruction"]) & bg)
    out["identical_instruction_with_bench_or_val_or_pool"] = sum(
        1 for r in cand if r["instruction"] in {x["instruction"] for k in ("bench_v4b", "val500_v3b", "val100_v3b", "stage_b_pool") for x in refs[k]})
    out["identical_instruction_with_training_file"] = len({r["instruction"] for r in cand} & {r["instruction"] for r in train})
    out["triple_overlap_with_full_training_file_info"] = len(ct & set().union(*(trip(r) for r in train)))
    (VH / "work/verify_report.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
