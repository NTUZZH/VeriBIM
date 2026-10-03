"""Structural similarity between every training-eligible corpus building and every
BIM-Edit scene file (contamination protocol, step 2).

Score, for a pair (a = corpus building, b = BIM-Edit scene):

  S_type   = cosine of the IfcProduct element-type count vectors over the union of
             class names. Cosine is scale-invariant, so it compares the MIX of
             element types rather than the size of the model.
  S_layout = mean of the defined sub-scores below, each the symmetric ratio
             r(x, y) = min(x, y) / max(x, y) in (0, 1]:
               s_storey = r(storeys_a + 1, storeys_b + 1)   (+1 keeps 0 storeys defined)
               s_area   = r(footprint_m2_a, footprint_m2_b) (metric; unit scale applied)
               s_aspect = r(aspect_a, aspect_b), aspect = max(dx, dy)/min(dx, dy) >= 1
               s_prod   = r(n_products_a, n_products_b)
             A sub-score is undefined when either input is missing or non-positive,
             and is then left out of the mean.
  S_struct = 0.6 * S_type + 0.4 * S_layout

The 0.6 / 0.4 split is a stated convention, not a tuned parameter: element
composition is the primary structural fingerprint and the layout ratios corroborate
it. Both components are reported separately for every pair.

This script does NOT choose a threshold. It reports the distribution, the natural
breaks in the tail, the count excluded at each candidate cut, and a positive control
built from the corpus files that contamination check #1 already dropped.
"""
import json
import os
from collections import Counter

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DESC = os.path.join(ROOT, "data", "corpus_descriptors.json")
MANIFEST = os.path.join(ROOT, "data", "corpus_manifest.json")
OUT = os.path.join(ROOT, "data", "corpus_build")

SUBS = ("s_storey", "s_area", "s_aspect", "s_prod")


def ratio(x, y):
    """Symmetric ratio in (0, 1]; nan where undefined."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    bad = ~(np.isfinite(x) & np.isfinite(y)) | (x <= 0) | (y <= 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.minimum(x, y) / np.maximum(x, y)
    return np.where(bad, np.nan, r)


def col(recs, key, off=0.0):
    return np.array([(r[1].get(key) if r[1].get(key) is not None else np.nan) + off
                     for r in recs], dtype=float)


def score(A, B, vocab):
    idx = {t: i for i, t in enumerate(vocab)}

    def mat(recs):
        m = np.zeros((len(recs), len(vocab)))
        for i, (_, v) in enumerate(recs):
            for t, c in v["element_type_histogram"].items():
                m[i, idx[t]] = c
        n = np.linalg.norm(m, axis=1, keepdims=True)
        n[n == 0] = 1.0
        return m / n

    s_type = mat(A) @ mat(B).T
    subs = {}
    for name, key, off in [("s_storey", "storey_count", 1.0), ("s_area", "footprint_m2", 0.0),
                           ("s_aspect", "footprint_aspect", 0.0), ("s_prod", "n_products", 0.0)]:
        subs[name] = ratio(col(A, key, off)[:, None], col(B, key, off)[None, :])
    stack = np.stack([subs[k] for k in SUBS])
    with np.errstate(invalid="ignore"):
        s_layout = np.nanmean(stack, axis=0)
    s_layout = np.where(np.sum(~np.isnan(stack), axis=0) == 0, 0.0, np.nan_to_num(s_layout))
    return 0.6 * s_type + 0.4 * s_layout, s_type, s_layout, subs


def corroborate(A, B):
    """Evidence a pair is literally the same building, independent of the score."""
    def dims(recs):
        out = np.full((len(recs), 3), np.nan)
        for i, (_, v) in enumerate(recs):
            bb = v.get("placement_bbox_m")
            if bb:
                out[i] = [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]]
        return out

    da, db = dims(A), dims(B)
    with np.errstate(invalid="ignore", divide="ignore"):
        rel = np.abs(da[:, None, :] - db[None, :, :]) / np.maximum(
            np.abs(da)[:, None, :], np.abs(db)[None, :, :])
    bbox_match = np.all(rel < 0.01, axis=2) & np.all(np.isfinite(rel), axis=2)
    return dict(bbox_match=bbox_match,
                histA=[Counter(v["element_type_histogram"]) for _, v in A],
                histB=[Counter(v["element_type_histogram"]) for _, v in B],
                elevA=[tuple(v.get("storey_elevations") or ()) for _, v in A],
                elevB=[tuple(v.get("storey_elevations") or ()) for _, v in B])


def top_pairs(A, B, S, s_type, s_layout, subs, corr, n=60):
    pairs = []
    for f in np.argsort(S.ravel())[::-1][:n]:
        i, j = divmod(int(f), S.shape[1])
        va, vb = A[i][1], B[j][1]
        sub = {k: (None if np.isnan(subs[k][i, j]) else round(float(subs[k][i, j]), 4))
               for k in SUBS}
        pairs.append(dict(
            rank=len(pairs) + 1, corpus=A[i][0], bimedit=B[j][0],
            S_struct=round(float(S[i, j]), 4), S_type=round(float(s_type[i, j]), 4),
            S_layout=round(float(s_layout[i, j]), 4), **sub,
            corpus_products=va["n_products"], bimedit_products=vb["n_products"],
            corpus_storeys=va["storey_count"], bimedit_storeys=vb["storey_count"],
            corpus_footprint_m2=va.get("footprint_m2"), bimedit_footprint_m2=vb.get("footprint_m2"),
            corpus_top_types=[t for t, _ in corr["histA"][i].most_common(4)],
            bimedit_top_types=[t for t, _ in corr["histB"][j].most_common(4)],
            bbox_dims_match_within_1pct=bool(corr["bbox_match"][i, j]),
            identical_type_histogram=bool(corr["histA"][i] == corr["histB"][j]),
            identical_storey_elevations=bool(corr["elevA"][i] and
                                             corr["elevA"][i] == corr["elevB"][j]),
            corpus_collection=va["source_collection"]))
    return pairs


def main():
    d = json.load(open(DESC))
    man = json.load(open(MANIFEST))
    contaminated = {r["relpath"] for r in man["files"] if r["contamination"]["n_shared_guids"]}

    A = [(k, v) for k, v in sorted(d["corpus"].items()) if v.get("training_eligible")]
    B = sorted(d["bimedit"].items())
    C = [(k, v) for k, v in sorted(d["corpus"].items()) if k in contaminated]
    print("pairs: %d corpus x %d BIM-Edit = %d; positive control %d files"
          % (len(A), len(B), len(A) * len(B), len(C)))

    vocab = sorted({t for _, v in A + B + C for t in v["element_type_histogram"]})
    print("element-type vocabulary:", len(vocab))

    S, s_type, s_layout, subs = score(A, B, vocab)
    corr = corroborate(A, B)

    res = dict(
        n_corpus=len(A), n_bimedit=len(B), n_pairs=int(S.size), vocabulary_size=len(vocab),
        mean=round(float(S.mean()), 4), std=round(float(S.std()), 4),
        percentiles={str(p): round(float(np.percentile(S, p)), 4)
                     for p in (0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 100)},
        histogram={"bin_edges": [round(x, 2) for x in np.arange(0, 1.05, 0.05).tolist()],
                   "counts": np.histogram(S, bins=np.arange(0, 1.05, 0.05))[0].tolist()},
    )

    cands = []
    for t in [0.60, 0.65, 0.70, 0.75, 0.78, 0.80, 0.825, 0.85, 0.875, 0.90, 0.95]:
        hit = S >= t
        cands.append(dict(threshold=t, pairs_above=int(hit.sum()),
                          pct_of_pairs=round(100.0 * hit.sum() / S.size, 4),
                          corpus_buildings_excluded=int(hit.any(axis=1).sum()),
                          corpus_buildings_remaining=int(len(A) - hit.any(axis=1).sum()),
                          bimedit_models_involved=int(hit.any(axis=0).sum()),
                          excluded_buildings=[A[i][0] for i in np.where(hit.any(axis=1))[0]]))
    res["candidate_thresholds"] = cands

    flat = np.sort(S.ravel())[::-1][:400]
    gaps = sorted(((round(float(flat[i] - flat[i + 1]), 4), round(float(flat[i + 1]), 4), i + 1)
                   for i in range(len(flat) - 1)), reverse=True)[:8]
    res["largest_gaps_in_top_400"] = [dict(gap=g, score_below_gap=s, pairs_above_gap=r)
                                      for g, s, r in gaps]
    res["top_pairs"] = top_pairs(A, B, S, s_type, s_layout, subs, corr, n=60)
    res["distinct_corpus_buildings_in_top_60"] = sorted({p["corpus"] for p in res["top_pairs"]})
    res["provenance_corroboration"] = dict(
        pairs_with_bbox_dims_within_1pct=int(corr["bbox_match"].sum()),
        pairs_with_identical_type_histogram=int(sum(
            1 for i in range(len(A)) for j in range(len(B))
            if corr["histA"][i] == corr["histB"][j])),
        note=("Checks that would indicate a literally shared model rather than a coincidence "
              "of composition. GlobalId overlap is zero across all training-eligible buildings "
              "by construction: the 14 files with any shared GlobalId were dropped in "
              "contamination check #1."))

    if C:
        Sc, sct, scl, subc = score(C, B, vocab)
        corrc = corroborate(C, B)
        res["positive_control"] = dict(
            note=("The corpus files contamination check #1 dropped for sharing GlobalIds with "
                  "BIM-Edit, scored against the same 151 scenes. They are the only corpus files "
                  "with independent evidence of shared provenance, so their scores calibrate "
                  "what a genuine match looks like on this scale."),
            n_files=len(C), max=round(float(Sc.max()), 4), mean=round(float(Sc.mean()), 4),
            per_file_max={k: round(float(Sc[i].max()), 4) for i, (k, _) in enumerate(C)},
            top_pairs=top_pairs(C, B, Sc, sct, scl, subc, corrc, n=10))

    os.makedirs(OUT, exist_ok=True)
    json.dump(res, open(os.path.join(OUT, "similarity_results.json"), "w"), indent=1)
    np.save(os.path.join(OUT, "similarity_matrix.npy"), S.astype(np.float32))
    json.dump(dict(corpus=[k for k, _ in A], bimedit=[k for k, _ in B],
                   positive_control=[k for k, _ in C]),
              open(os.path.join(OUT, "similarity_axes.json"), "w"), indent=1)
    print("max %.4f  median %.4f  99th %.4f" % (S.max(), np.median(S), np.percentile(S, 99)))
    if C:
        print("positive control max %.4f" % Sc.max())


if __name__ == "__main__":
    main()
