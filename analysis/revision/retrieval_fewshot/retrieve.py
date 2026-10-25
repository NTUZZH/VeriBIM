"""Retrieve k = 3 training trajectories per benchmark task by TF-IDF cosine over the masked instruction.

Reads index/ (built by build_index.py). Writes results/retrieval.json and results/retrieval_exclusions.json.

Rules, in order:
  1. A training row whose instruction is verbatim identical to the benchmark instruction (after
     collapsing whitespace) is excluded; the next candidate takes its place.
  2. A training row from the benchmark task's own building is excluded (none exist: build_index.py
     asserts that training and benchmark buildings are disjoint; the count is recorded anyway).
  3. Candidates are ranked by cosine similarity; ties are broken by a fixed hash of the pair of task
     ids, so the choice is reproducible and favours no building or wording.
  4. At most one row per training task id: a gold trajectory and its reworded copies share the task
     id and the tool calls, so they count as one example.
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

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_index import terms  # noqa: E402

K = 3


def norm_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def tie_key(qid: str, tid: str, row: int) -> str:
    return hashlib.sha256(f"{qid}|{tid}|{row}".encode()).hexdigest()


def main() -> int:
    mat = sparse.load_npz(os.path.join(HERE, "index", "tfidf.npz")).tocsr()
    voc = json.load(open(os.path.join(HERE, "index", "vocab.json")))
    vocab, idf = voc["vocab"], np.array(voc["idf"])
    rows = [json.loads(l) for l in gzip.open(os.path.join(HERE, "index", "rows.jsonl.gz"), "rt", encoding="utf-8")]
    queries = json.load(open(os.path.join(HERE, "index", "queries.json")))
    raw_index = collections.defaultdict(list)
    for i, r in enumerate(rows):
        raw_index[norm_ws(r["instruction"])].append(i)

    out, excl = [], []
    for q in queries:
        tf = collections.Counter(t for t in terms(q["masked"]) if t in vocab)
        cols = sorted(vocab[t] for t in tf)
        inv = {vocab[t]: t for t in tf}
        vals = np.array([(1.0 + math.log(tf[inv[j]])) * idf[j] for j in cols])
        vals = vals / (np.linalg.norm(vals) or 1.0)
        qv = sparse.csr_matrix((vals, (np.zeros(len(cols), dtype=int), np.array(cols, dtype=int))),
                               shape=(1, mat.shape[1]))
        sims = np.asarray((mat @ qv.T).todense()).ravel()
        verbatim = set(raw_index.get(norm_ws(q["instruction"]), []))
        same_building = {i for i, r in enumerate(rows) if r["building_id"] == q["building_id"]}
        assert not same_building, (q["task_id"], len(same_building))
        order = sorted(range(len(rows)), key=lambda i: (-round(float(sims[i]), 9),
                                                        tie_key(q["task_id"], rows[i]["task_id"], i)))
        picked, seen, skipped = [], set(), []
        for i in order:
            if i in verbatim or i in same_building:
                skipped.append(i)
                continue
            if rows[i]["task_id"] in seen:
                continue
            seen.add(rows[i]["task_id"])
            picked.append(i)
            if len(picked) == K:
                break
        top = round(float(sims[order[0]]), 6)
        n_top = int(np.sum(np.round(sims, 6) >= top))
        out.append({
            "task_id": q["task_id"], "cell": q["cell"], "edit_kind": q["edit_kind"],
            "clarification": q["clarification"], "building_id": q["building_id"],
            "instruction": q["instruction"], "masked": q["masked"],
            "n_rows_at_top_similarity": n_top, "top_similarity": top,
            "excluded_verbatim_rows": sorted(verbatim), "excluded_same_building_rows": len(same_building),
            "retrieved": [{
                "row": rows[i]["row"], "task_id": rows[i]["task_id"], "source": rows[i]["source"],
                "cell": rows[i]["cell"], "edit_kind": rows[i]["edit_kind"], "answer": rows[i]["answer"],
                "building_id": rows[i]["building_id"], "input_ifc": rows[i]["input_ifc"],
                "similarity": round(float(sims[i]), 6), "instruction": rows[i]["instruction"],
                "masked": rows[i]["masked"], "n_messages": rows[i]["n_messages"],
            } for i in picked],
        })
        if verbatim:
            excl.append({"task_id": q["task_id"], "instruction": q["instruction"],
                         "excluded": [{"row": rows[i]["row"], "task_id": rows[i]["task_id"],
                                       "source": rows[i]["source"]} for i in sorted(verbatim)]})
        assert len(picked) == K
        for p in out[-1]["retrieved"]:
            assert p["building_id"] != q["building_id"]
            assert norm_ws(p["instruction"]) != norm_ws(q["instruction"])
    json.dump(out, open(os.path.join(HERE, "results", "retrieval.json"), "w"), indent=1, ensure_ascii=False)
    json.dump(excl, open(os.path.join(HERE, "results", "retrieval_exclusions.json"), "w"), indent=1, ensure_ascii=False)
    n_ex = len(out) * K
    same_cell = sum(p["cell"] == o["cell"] for o in out for p in o["retrieved"])
    same_kind = sum(p["edit_kind"] == o["edit_kind"] for o in out for p in o["retrieved"])
    sims = [p["similarity"] for o in out for p in o["retrieved"]]
    print(json.dumps({
        "tasks": len(out), "examples": n_ex,
        "tasks_with_verbatim_training_instruction": len(excl),
        "verbatim_rows_excluded": sum(len(e["excluded"]) for e in excl),
        "examples_same_cell": same_cell, "examples_same_edit_kind": same_kind,
        "similarity_min": min(sims), "similarity_median": float(np.median(sims)), "similarity_max": max(sims),
        "examples_at_similarity_1": sum(s >= 0.999999 for s in sims),
        "clarification_tasks": sum(o["clarification"] for o in out),
        "clarification_tasks_with_a_clarify_example": sum(
            o["clarification"] and any(p["answer"] == "clarify" for p in o["retrieved"]) for o in out),
        "non_clarification_tasks_with_a_clarify_example": sum(
            (not o["clarification"]) and any(p["answer"] == "clarify" for p in o["retrieved"]) for o in out),
        "examples_from_reworded_rows": sum(p["source"] == "gold_paraphrase" for o in out for p in o["retrieved"]),
    }, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
