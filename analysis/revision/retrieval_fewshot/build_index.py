"""Index of the imitation-training trajectories for the retrieval few-shot baseline.

Reads (all paths relative to the project root):
  runs_local/stage_a_v10/sft_train.jsonl.gz              the 75,953 rows the imitation stage trained on
  runs_local/stage_a_v10/trajectories_v10_final.jsonl.gz  the same trajectories with their input model path
  runs_local/corpus_v10/migrator_v2/pool_v10_all.json     training building registry (model key -> building id)
  runs_local/corpus_v10/migrator_v2/pool_bench_v10_all.json  benchmark building registry
  runs_local/corpus_v10/migrator_v2/jobs.json             migrated copies -> their source model
  runs_local/bench_v4/tasks.v4c.jsonl, subset_108_hosted.v4c.json

Writes into this folder:
  index/rows.jsonl.gz     one line per training row: row number, task id, source, cell, building, raw and masked instruction
  index/tfidf.npz         L2-normalised TF-IDF matrix of the masked training instructions (scipy CSR)
  index/vocab.json        term -> column, and the idf vector
  index/queries.json      the 108 benchmark tasks: raw and masked instruction, cell, building
  results/leakage_checks.json  building, path and content-hash disjointness of training and benchmark models

Similarity is computed on the instruction with every GlobalId, quoted name and number replaced by a
placeholder, so that two requests match when they ask for the same kind of edit with the same kind of
reference, whatever the building, the element names or the values.
"""
from __future__ import annotations

import collections
import gzip
import hashlib
import json
import math
import os
import re
import sys

import numpy as np
from scipy import sparse

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))
HERE = os.path.dirname(os.path.abspath(__file__))
V10 = os.path.join(ROOT, "runs_local/stage_a_v10")
MIG = os.path.join(ROOT, "runs_local/corpus_v10/migrator_v2")
BENCH = os.path.join(ROOT, "runs_local/bench_v4")
PATH_SPLIT = "\n\nIFC model path:"

# --- masking -------------------------------------------------------------------------------
GUID = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")
SQUOTE = re.compile(r"(?<![0-9A-Za-z])'[^'\n]*'(?![0-9A-Za-z])")
DQUOTE = re.compile(r"(?<![0-9A-Za-z])\"[^\"\n]*\"(?![0-9A-Za-z])")
CURLY = re.compile(r"[‘“][^’”\n]*[’”]")
NUMBER = re.compile(r"[-+−]?\d+(?:[.,]\d+)*")


def mask(text: str) -> str:
    """Replace GlobalIds, quoted names and numbers with placeholders.

    Order matters: a GlobalId inside quotes becomes <name> through the quote rule only if it
    was not already caught, and digits inside names disappear with the name.
    """
    t = GUID.sub(" GUIDTOKEN ", text)
    t = SQUOTE.sub(" NAMETOKEN ", t)
    t = DQUOTE.sub(" NAMETOKEN ", t)
    t = CURLY.sub(" NAMETOKEN ", t)
    t = NUMBER.sub(" NUMTOKEN ", t)
    return re.sub(r"\s+", " ", t).strip()


TOKEN = re.compile(r"[a-z]+")


def terms(masked: str) -> list[str]:
    words = TOKEN.findall(masked.lower())
    return words + [a + " " + b for a, b in zip(words, words[1:])]


# --- buildings -----------------------------------------------------------------------------
def building_resolver():
    pool = json.load(open(os.path.join(MIG, "pool_v10_all.json")))
    bench_pool = json.load(open(os.path.join(MIG, "pool_bench_v10_all.json")))
    jobs = json.load(open(os.path.join(MIG, "jobs.json")))
    by_path = {m["relpath"]: m for m in pool["models"]}
    by_key = {m["key"]: m for m in pool["models"]}
    job_src = {j["key"]: j["src"] for j in jobs}
    migrated = re.compile(r"^runs_local/corpus_v10/migrator_v2/files/(?P<key>[^_/]+)__IFC4(?:X3)?\.ifc$")

    def train_building(path: str) -> tuple[str, str]:
        if path in by_path:
            return by_path[path]["building_id"], path
        m = migrated.match(path)
        if m and m.group("key") in by_key:
            src = by_key[m.group("key")]
            if m.group("key") in job_src:
                assert job_src[m.group("key")] == src["relpath"], (path, job_src[m.group("key")], src["relpath"])
            return src["building_id"], src["relpath"]
        raise KeyError(f"training model without a building: {path}")

    bench_by_path = {m["relpath"]: m for m in bench_pool["models"]}
    return train_building, bench_by_path, pool, bench_pool


def sha256(path: str, cache: dict) -> str:
    if path in cache:
        return cache[path]
    h = hashlib.sha256()
    with open(os.path.join(ROOT, path), "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    cache[path] = h.hexdigest()
    return cache[path]


def main() -> int:
    os.makedirs(os.path.join(HERE, "index"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    train_building, bench_by_path, pool, bench_pool = building_resolver()

    # input model and answer kind per training task id
    meta = {}
    for line in gzip.open(os.path.join(V10, "trajectories_v10_final.jsonl.gz"), "rt", encoding="utf-8"):
        r = json.loads(line)
        prev = meta.get(r["task_id"])
        cur = (r["input_ifc"], r.get("answer"), r.get("family"))
        assert prev is None or prev[0] == cur[0], (r["task_id"], prev, cur)
        meta[r["task_id"]] = cur

    rows = []
    for n, line in enumerate(gzip.open(os.path.join(V10, "sft_train.jsonl.gz"), "rt", encoding="utf-8")):
        r = json.loads(line)
        msgs = r["messages"]
        assert msgs[0]["role"] == "system" and msgs[1]["role"] == "user", r["task_id"]
        user = msgs[1]["content"]
        assert user.count(PATH_SPLIT) == 1, r["task_id"]
        instruction = user.split(PATH_SPLIT)[0].strip()
        input_ifc, answer, family = meta[r["task_id"]]
        bld, src = train_building(input_ifc)
        rows.append({"row": n, "task_id": r["task_id"], "source": r["source"],
                     "operation": r["operation"], "category": r["category"],
                     "cell": f"{r['operation']}/{r['category']}", "edit_kind": r.get("edit_kind"),
                     "family": family, "answer": answer, "input_ifc": input_ifc,
                     "source_model": src, "building_id": bld,
                     "n_messages": len(msgs), "instruction": instruction, "masked": mask(instruction)})
    print("training rows", len(rows), "task ids", len({r["task_id"] for r in rows}), flush=True)

    # benchmark side: all 2,100 tasks for the building check, the 108 for the queries
    bench = [json.loads(l) for l in open(os.path.join(BENCH, "tasks.v4c.jsonl"), encoding="utf-8")]
    subset = json.load(open(os.path.join(BENCH, "subset_108_hosted.v4c.json")))
    by_id = {t["task_id"]: t for t in bench}
    for t in bench:
        m = bench_by_path[t["input_ifc"]]
        assert m["building_id"] == t["building_id"], (t["task_id"], m["building_id"], t["building_id"])

    # leakage: buildings, paths and file contents of the two sides must be disjoint
    train_paths = sorted({r["input_ifc"] for r in rows})
    train_sources = sorted({r["source_model"] for r in rows})
    train_blds = sorted({r["building_id"] for r in rows})
    bench_paths = sorted({t["input_ifc"] for t in bench})
    bench_sources = sorted({t["source_relpath"] for t in bench})
    bench_blds = sorted({t["building_id"] for t in bench})
    cache_file = os.path.join(HERE, "index", "sha256_cache.json")
    cache = json.load(open(cache_file)) if os.path.exists(cache_file) else {}
    train_sha = {p: sha256(p, cache) for p in train_paths + train_sources}
    bench_sha = {p: sha256(p, cache) for p in bench_paths + bench_sources}
    json.dump(cache, open(cache_file, "w"), indent=0)
    pool_sha_ok = all(bench_sha[m["relpath"]] == m["sha256"] for m in bench_pool["models"] if m["relpath"] in bench_sha)
    checks = {
        "training_rows": len(rows),
        "training_task_ids": len({r["task_id"] for r in rows}),
        "training_model_files": len(train_paths),
        "training_source_models": len(train_sources),
        "training_buildings": len(train_blds),
        "benchmark_model_files": len(bench_paths),
        "benchmark_source_models": len(bench_sources),
        "benchmark_buildings": len(bench_blds),
        "benchmark_buildings_in_108": sorted({by_id[t]["building_id"] for t in subset}),
        "shared_building_ids": sorted(set(train_blds) & set(bench_blds)),
        "shared_model_paths": sorted(set(train_paths + train_sources) & set(bench_paths + bench_sources)),
        "shared_file_sha256": sorted(set(train_sha.values()) & set(bench_sha.values())),
        "benchmark_sha256_matches_registry": pool_sha_ok,
        "training_pool_excluded_buildings": pool["excluded_buildings"],
    }
    assert not checks["shared_building_ids"], checks["shared_building_ids"]
    assert not checks["shared_model_paths"], checks["shared_model_paths"]
    assert not checks["shared_file_sha256"], checks["shared_file_sha256"]
    assert pool_sha_ok
    json.dump(checks, open(os.path.join(HERE, "results", "leakage_checks.json"), "w"), indent=1)
    print("leakage checks passed:", {k: v for k, v in checks.items() if not isinstance(v, list)}, flush=True)

    # TF-IDF over the masked training instructions (smooth idf, sublinear tf, unigrams and bigrams)
    vocab: dict[str, int] = {}
    df = collections.Counter()
    docs = []
    for r in rows:
        tf = collections.Counter(terms(r["masked"]))
        docs.append(tf)
        df.update(tf.keys())
    for term in sorted(df):
        vocab[term] = len(vocab)
    n_docs = len(rows)
    idf = np.zeros(len(vocab))
    for term, j in vocab.items():
        idf[j] = math.log((1 + n_docs) / (1 + df[term])) + 1.0
    indptr, indices, data = [0], [], []
    for tf in docs:
        cols = sorted(vocab[t] for t in tf)
        inv = {vocab[t]: t for t in tf}
        vals = np.array([(1.0 + math.log(tf[inv[j]])) * idf[j] for j in cols])
        vals = vals / (np.linalg.norm(vals) or 1.0)
        indices.extend(cols)
        data.extend(vals.tolist())
        indptr.append(len(indices))
    mat = sparse.csr_matrix((np.array(data), np.array(indices), np.array(indptr)), shape=(n_docs, len(vocab)))
    sparse.save_npz(os.path.join(HERE, "index", "tfidf.npz"), mat)
    json.dump({"vocab": vocab, "idf": idf.tolist(), "n_docs": n_docs}, open(os.path.join(HERE, "index", "vocab.json"), "w"))
    with gzip.open(os.path.join(HERE, "index", "rows.jsonl.gz"), "wt", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    queries = []
    for tid in subset:
        t = by_id[tid]
        instruction = (t.get("instruction") or t["prompt"]).strip()
        queries.append({"task_id": tid, "instruction": instruction, "masked": mask(instruction),
                        "cell": f"{t['operation']}/{t['category']}", "operation": t["operation"],
                        "category": t["category"], "edit_kind": t.get("edit_kind"), "family": t.get("family"),
                        "clarification": bool(t.get("clarification")), "building_id": t["building_id"],
                        "input_ifc": t["input_ifc"], "ifc_version": t.get("ifc_version")})
    json.dump(queries, open(os.path.join(HERE, "index", "queries.json"), "w"), indent=1, ensure_ascii=False)
    print("vocab", len(vocab), "queries", len(queries), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
