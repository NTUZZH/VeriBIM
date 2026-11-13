"""Worker side of run_validity.py: imports the OLD per-task analysis code and runs it on one edited model.

Reused by import, unchanged (the module paths are redirected, the functions are not copied):
  (A) off-target diff    checker/offtarget_full_v4e.py   evaluate()
  (B, D) relation gate,  checker_validity/gate_abs.py      _work() -> process()
         absolute errors
  (C) schema, clashes    checker_validity/schema_clash.py  _work() -> process()

What init() redirects (module attributes the old code reads at call time):
  common.TMP, common.OUT            -> scratch (ground-truth unpacking of gate_abs and schema_clash)
  common.TASKS                      -> the task file of the config
  common.unpack_gold                -> unpack_gold() below (ground truth chosen by its SHA-256, see there)
  schema_clash.CACHE                -> scratch (the old cache under checker_validity/results/cache is never read
                                       or written; every validation of a source and a ground truth is recomputed)
  offtarget_full_v4e.SCRATCH, FP_CACHE, TASKS, unpack_gold -> scratch, the config task file, unpack_gold()
  gate_abs._W / schema_clash._W ['delete_after'] = False (the parent process deletes each unpacked file once every
                                       analysis of that file has returned)
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(".")
CVDIR = ROOT / "checker_validity"
OTDIR = ROOT / "checker"

_S: dict = {}          # worker state: config, task records, gold candidates


def _import_old():
    """Import the three old modules (sys.path order: checker_validity first, so `common` is its common.py)."""
    for p in (str(ROOT / "code"), str(OTDIR), str(CVDIR)):
        if p in sys.path:
            sys.path.remove(p)
        sys.path.insert(0, p)
    import common as C                 # noqa: E402  checker_validity/common.py
    import gate_abs as GA              # noqa: E402
    import schema_clash as SC          # noqa: E402
    import offtarget_full_v4e as OT    # noqa: E402
    assert Path(C.__file__).resolve() == CVDIR / "common.py", C.__file__
    assert Path(GA.__file__).resolve() == CVDIR / "gate_abs.py", GA.__file__
    assert Path(SC.__file__).resolve() == CVDIR / "schema_clash.py", SC.__file__
    assert Path(OT.__file__).resolve() == OTDIR / "offtarget_full_v4e.py", OT.__file__
    return C, GA, SC, OT


def gold_candidates(record: dict, gold_cfg: dict) -> list[Path]:
    """Ground-truth archives to try, in the config's order: gold.dirs_first/<task>.ifc.gz, then (gold.record_paths)
    the record's ground_truth_ifc and gold_model with .gz, then gold.dirs_after/<task>.ifc.gz. The old readers tried
    the same places in the same order (checker_validity/common.gold_archive, offtarget_full_v4e.unpack_gold)."""
    t = record["task_id"]
    out = [Path(d) / f"{t}.ifc.gz" for d in gold_cfg.get("dirs_first", [])]
    if gold_cfg.get("record_paths", True):
        for k in ("ground_truth_ifc", "gold_model"):
            if record.get(k):
                out.append(ROOT / (record[k] + ".gz"))
    out += [Path(d) / f"{t}.ifc.gz" for d in gold_cfg.get("dirs_after", [])]
    seen, uniq = set(), []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def unpack_gold(record: dict, dest_dir: Path) -> Path:
    """Parameterised copy of checker_validity/common.unpack_gold (same output name, same streaming SHA-256 check
    against the record's verification.gold_sha256). The one change: the old function took the FIRST existing
    candidate and raised on a checksum mismatch; this one tries the candidates in the same order and keeps the first
    whose checksum equals the record's, and raises only when none does. With tasks.v4d.jsonl (the stand-in) the first
    existing candidate always matches, so the choice is the old one; the task file carries the v4c checksums of
    the 69 ground truths repaired on 2026-10-15, for which the v4d archive is skipped and the v4c archive is taken."""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"{record['task_id']}.gold.ifc"
    expected = (record.get("verification") or {}).get("gold_sha256")
    tried = []
    cache = _S.setdefault("gold_choice", {})
    cands = gold_candidates(record, _S["cfg"]["gold"])
    if record["task_id"] in cache:
        cands = [cache[record["task_id"]]] + [c for c in cands if c != cache[record["task_id"]]]
    for src in cands:
        if not src.is_file():
            continue
        digest = hashlib.sha256()
        with gzip.open(src, "rb") as fi, open(out, "wb") as fo:
            for block in iter(lambda: fi.read(1 << 20), b""):
                digest.update(block)
                fo.write(block)
        if not expected or digest.hexdigest() == expected:
            cache[record["task_id"]] = src
            _S.setdefault("gold_skipped", {})[record["task_id"]] = list(tried)
            return out
        tried.append(str(src))
        out.unlink()
    raise ValueError(f"gold sha256 mismatch for {record['task_id']}: no candidate matches the record "
                     f"(tried {tried or 'none existing'})")


def init(cfg_path: str):
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    if os.environ.get("OFFTARGET_FULL_HASH", "0") == "1":
        raise RuntimeError("OFFTARGET_FULL_HASH=1 would switch the off-target diff off its checked fast path")
    sys.setrecursionlimit(20000)
    C, GA, SC, OT = _import_old()
    scratch = Path(cfg["out"]["scratch"])
    C.TMP = scratch / "cv_tmp"
    C.OUT = scratch / "cv_out"
    C.TASKS = Path(cfg["tasks_file"])
    C.unpack_gold = unpack_gold
    SC.CACHE = scratch / "schema_cache"
    OT.TASKS = Path(cfg["tasks_file"])
    OT.SCRATCH = scratch / "offtarget"
    OT.FP_CACHE = OT.SCRATCH / "fp"
    OT.unpack_gold = unpack_gold
    OT._T.clear()
    assert OT.FAST, "offtarget_full_v4e.FAST must be on (the checked fast path of the old runs)"
    GA._W["delete_after"] = False
    SC._W["delete_after"] = False
    _S.update(cfg=cfg, C=C, GA=GA, SC=SC, OT=OT,
              sc_args=argparse.Namespace(no_validate=False, no_clash=False, no_express=False))


def work(item: dict) -> dict:
    """One edited model (or none), every analysis it is needed for. item: record, row, path (or None), which (list
    of 'offtarget', 'gate', 'schema'), set (label written into the off-target row's 'arm' field)."""
    record, row, path, which = item["record"], item["row"], item["path"], item["which"]
    GA, SC, OT = _S["GA"], _S["SC"], _S["OT"]
    t0 = time.time()
    out = {"task_id": record["task_id"], "pid": os.getpid()}
    if path is not None and not Path(path).is_file():
        raise FileNotFoundError(f"edited model {path} vanished before its analysis")
    if "offtarget" in which:
        if path is None:
            out["offtarget"] = {"arm": item["set"], "task_id": record["task_id"], "status": "edited_missing",
                                "seconds": 0.0}
        else:
            out["offtarget"] = OT.evaluate((item["set"], row, str(path), False))
    if "gate" in which:
        out["gate"] = GA._work((record, row, str(path) if path else None))
    if "schema" in which:
        out["schema"] = SC._work((record, row, str(path) if path else None, _S["sc_args"]))
    t = record["task_id"]
    if t in _S.get("gold_choice", {}):
        # the ground-truth archive used, and any earlier candidate whose checksum did not match the task record
        for a in which:
            if isinstance(out.get(a), dict):
                out[a]["gold_file"] = str(_S["gold_choice"][t])
                out[a]["gold_skipped"] = _S.get("gold_skipped", {}).get(t, [])
    import resource
    out["worker_maxrss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)
    out["seconds"] = round(time.time() - t0, 1)
    return out
