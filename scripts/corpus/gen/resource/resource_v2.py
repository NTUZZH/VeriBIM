"""Move tasks generated on v1 migrated files onto the v2 files and re-run the funnel.

For every task whose source is a v1 migrated file (``runs_local/corpus_v10/migrated/``
or ``heldout_4x3/``):

1. the source fields (``input_ifc``, ``source_model.relpath``, ``source_model.sha256``)
   point at the v2 file of the same pool key (``migrator_v2/pool_*.json``);
2. tasks on B54/B69/B70 IFC4X3 that name one of the 27 column bodies migrator v2
   changed are dropped (any occurrence of the GlobalId anywhere in the record);
3. the generator's acceptance checks run again on the v2 source, from the record,
   with the generator's own functions and in the order ``generate.produce`` runs
   them: under-specified check or anchor + wording check, meshability for an
   update, apply (``materialize.rebuild``), parse / created / removed / relation
   edges / world placement, batch scope, re-execution, no-edit or self-score, and
   the null-edit score.  A task failing any check is dropped with the reason;
4. a passing task gets the new gold checksum and size, the re-execution match
   and null-edit score of the v2 run, the v2 scene counts in ``difficulty``, and
   ``verification.resourced`` plus ``verification.resourced_old`` (every replaced
   value).  Nothing else changes (asserted per record).

Tasks on native sources are copied unchanged (the filling repair has already been
applied to the input file by ``gen/repair/repair_filling_type.py``).

``--control-v1`` runs the same checks on the v1 source instead and writes only a
journal: it calibrates the checks, since every task passed them on v1 when it was
generated.

Resumable through the journal in ``--work``.  Two pools: sources of at least
``--large-mb`` go to a one-worker pool, the rest to the other pool.
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import copy
import gc
import glob
import json
import pickle
import resource
import shutil
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

sys.dont_write_bytecode = True
ROOT = Path(".")
C10 = ROOT / "runs_local/corpus_v10"
RESOURCE = C10 / "gen/resource"
for _path in (ROOT / "code", ROOT / "code" / "harness"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
os.environ.setdefault("MODIFC_GEOM_CACHE", str(RESOURCE / "geom_index"))

TAG = "migrator_v2_2026-09-26"
MIGRATED_DIRS = ("runs_local/corpus_v10/migrated/", "runs_local/corpus_v10/heldout_4x3/")
CHANGED_FILES = {"B54__IFC4X3.ifc": "B54", "B69__IFC4X3.ifc": "B69",
                 "B70__IFC4X3.ifc": "B70"}
#: Key paths a re-sourced record may differ at.
MAY_CHANGE = {"input_ifc", "source_model.relpath", "source_model.sha256",
              "verification.gold_sha256", "verification.gold_bytes",
              "verification.reexecution_match", "verification.null_edit_score",
              "verification.self_score.geometry", "verification.self_score.semantics",
              "verification.self_score.topology", "verification.self_score.final",
              "difficulty.scene_n_products", "difficulty.scene_n_relations",
              "verification.resourced", "verification.resourced_old"}


# ------------------------------------------------------------------ inputs


def v2_entries() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(glob.glob(str(C10 / "migrator_v2/pool_*.json"))):
        for entry in json.load(open(path))["models"]:
            if entry.get("migrator") != "v2":
                continue
            prior = out.get(entry["key"])
            assert prior is None or (prior["relpath"], prior["sha256"]) == \
                (entry["relpath"], entry["sha256"]), entry["key"]
            out[entry["key"]] = entry
    return out


def changed_columns() -> dict[str, set[str]]:
    """The column bodies v2 changed, read from the migrator's own signatures."""
    out: dict[str, set[str]] = {}
    for key in ("B54", "B69", "B70"):
        old = pickle.load(open(C10 / f"migrator_v2/work/{key}/sigold_IFC4X3.pkl", "rb"))
        new = pickle.load(open(C10 / f"migrator_v2/work/{key}/signew_IFC4X3.pkl", "rb"))
        out[key] = {g for g, (raw, _masked) in old["rep"].items()
                    if new["rep"].get(g, (None, None))[0] != raw}
    listed = set()
    for line in open(C10 / "migrator_v2/equivalence_v2.jsonl"):
        entry = json.loads(line)
        for guids in (entry.get("representation_examples") or {}).values():
            listed.update(guids)
    union = set().union(*out.values())
    assert len(union) == 27, len(union)
    assert listed <= union, listed - union
    return out


def is_migrated(record: dict) -> bool:
    return record["input_ifc"].startswith(MIGRATED_DIRS)


def mentions(record: dict, guids: set[str]) -> list[str]:
    """Top-level fields of the record that mention one of the GlobalIds."""
    hits = []
    for key, value in record.items():
        text = json.dumps(value, ensure_ascii=False)
        found = sorted(g for g in guids if g in text)
        if found:
            hits.append(f"{key}:{','.join(found)}")
    return hits


def diff_paths(old: Any, new: Any, prefix: str = "") -> list[str]:
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in list(old) + [k for k in new if k not in old]:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in old or key not in new:
                out.append(path)
            else:
                out.extend(diff_paths(old[key], new[key], path))
        return out
    if old != new or type(old) is not type(new):
        return [prefix]
    return []


# --------------------------------------------------------------- the checks


_W: dict[str, Any] = {}


def _init_worker(cores: list[int]) -> None:
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass


def _peak_gb() -> float:
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 3)


def check_chunk(payload: tuple) -> dict[str, Any]:
    """Every check of ``generate.produce``, from the records, for tasks sharing a source."""
    source_rel, source_sha, records, scratch_dir, chunk_id = payload
    from modifc_gen import materialize, verify
    from modifc_gen.anchors import from_record as anchor_from_record
    from modifc_gen.scene import Scene
    from modifc_score.model_cache import MeshCache, ModelCache

    started = time.perf_counter()
    scratch = Path(scratch_dir) / chunk_id
    scratch.mkdir(parents=True, exist_ok=True)
    source_path = str(ROOT / source_rel)
    results: dict[str, dict] = {r["task_id"]: {"task_id": r["task_id"], "ok": True,
                                               "stage": "", "reason": "",
                                               "source": source_rel}
                                for r in records}
    try:
        scene = Scene(source_path, source_rel, source_sha)
    except Exception as exc:  # noqa: BLE001
        for res in results.values():
            res.update(ok=False, stage="scene", reason=repr(exc)[:200])
        return {"chunk": chunk_id, "results": list(results.values()),
                "seconds": time.perf_counter() - started, "peak_gb": _peak_gb()}
    scene_counts = {"scene_n_products": scene.n_products,
                    "scene_n_relations": scene.n_relations}

    # Stage 1, the checks that read the scene.
    for record in records:
        res = results[record["task_id"]]
        res["scene_counts"] = scene_counts
        instruction = record.get("instruction") or record.get("prompt") or ""
        params = record.get("edit_params") or {}
        clarification = params.get("clarification") or record.get("clarification")
        try:
            anchor = anchor_from_record(record["anchor"])
            expected = list(record["anchor"].get("expected") or ())
            if clarification:
                stage = verify.check_underspecified(scene, instruction, clarification,
                                                    record.get("family") or "")
                name = "underspecified"
            else:
                stage = verify.check_anchor(scene, anchor, expected)
                name = "anchor"
                if stage.ok:
                    stage = verify.check_wording(scene, instruction, anchor,
                                                 record.get("wording"), expected)
                    name = "wording"
        except Exception as exc:  # noqa: BLE001
            res.update(ok=False, stage="scene_checks", reason=repr(exc)[:200])
            continue
        if not stage.ok:
            res.update(ok=False, stage=name, reason=stage.reason,
                       detail=json.loads(json.dumps(stage.detail, default=str)))
    del scene
    gc.collect()

    # Stage 2, the checks that read the files.
    models = ModelCache(capacity=2)
    meshes = MeshCache(capacity_vertices=1_500_000)
    for record in records:
        res = results[record["task_id"]]
        if not res["ok"]:
            continue
        t0 = time.perf_counter()
        params = record.get("edit_params") or {}
        guids = record.get("edit_guids") or {}
        clarification = params.get("clarification") or record.get("clarification")
        gold = scratch / f"{record['task_id']}.ifc"
        work = dict(record, input_ifc=source_rel)
        try:
            if record["operation"] == "update" and not clarification:
                stage = verify.check_meshable(source_path, record["target"]["guids"],
                                              meshes, models)
                if not stage.ok:
                    res.update(ok=False, stage="meshable", reason=stage.reason)
                    continue
            built = materialize.rebuild(work, ROOT, gold, check=False)
            if not built.ok:
                res.update(ok=False, stage="apply", reason=built.reason)
                continue
            stage = verify.check_parse(str(gold), guids.get("created") or (),
                                       guids.get("removed") or (),
                                       params.get("relation_edges") or (),
                                       params.get("expected_world_box"),
                                       guids.get("relations") or (),
                                       params.get("expected_world_origin"))
            if not stage.ok:
                res.update(ok=False, stage="parse", reason=stage.reason,
                           detail=json.loads(json.dumps(stage.detail, default=str)))
                continue
            if params.get("scope") == "batch":
                stage = verify.check_batch_scope(
                    source_path, str(gold),
                    params.get("batch_members") or record["target"]["guids"],
                    params.get("batch_pool") or (), models)
                if not stage.ok:
                    res.update(ok=False, stage="batch_scope", reason=stage.reason)
                    continue
            stage = verify.check_reexecution(record["gold_script"], source_path,
                                             str(gold), list(guids.get("touched") or ()),
                                             str(scratch))
            if not stage.ok:
                res.update(ok=False, stage="reexecute", reason=stage.reason)
                continue
            res["reexecution_match"] = stage.detail.get("match")
            if clarification:
                stage = verify.check_no_edit(source_path, str(gold), models)
                if not stage.ok:
                    res.update(ok=False, stage="no_edit", reason=stage.reason)
                    continue
                res["self_score"] = {"geometry": 1.0, "semantics": 1.0,
                                     "topology": 1.0, "final": 1.0}
            else:
                stage = verify.check_self_score(
                    record["task_id"], record["operation"], record["category"],
                    record["target"]["entity_type"], record["target"]["guids"],
                    source_path, str(gold), models, meshes)
                if not stage.ok:
                    res.update(ok=False, stage="self_score", reason=stage.reason,
                               detail=json.loads(json.dumps(stage.detail, default=str)))
                    continue
                res["self_score"] = {k: stage.detail.get(k) for k in
                                     ("geometry", "semantics", "topology", "final")}
            if (record.get("verification") or {}).get("repair"):
                leaf = models.get(str(gold)).by_guid(record["target"]["guids"][0])
                if getattr(leaf, "PredefinedType", None) is not None:
                    res.update(ok=False, stage="filling_type",
                               reason=f"PredefinedType={leaf.PredefinedType}")
                    continue
                res["filling_type_unset"] = True
            if "null_edit_score" in (record.get("verification") or {}) and \
                    not clarification:
                res["null_edit_score"] = verify.null_edit_score(
                    record["task_id"], record["operation"], record["category"],
                    record["target"]["entity_type"], record["target"]["guids"],
                    source_path, str(gold), models, meshes)
            res["gold_sha256"] = verify.sha256_of(str(gold))
            res["gold_bytes"] = gold.stat().st_size
        except Exception as exc:  # noqa: BLE001
            res.update(ok=False, stage="exception", reason=f"{type(exc).__name__}: {exc}"[:300])
        finally:
            res["seconds"] = round(time.perf_counter() - t0, 2)
            if gold.exists():
                gold.unlink()
            meshes.clear()
    shutil.rmtree(scratch, ignore_errors=True)
    return {"chunk": chunk_id, "results": list(results.values()),
            "seconds": round(time.perf_counter() - started, 1), "peak_gb": _peak_gb()}


def build_index(payload: tuple) -> dict[str, Any]:
    """Build (or reuse) the geometry index of one v2 source in the shared cache."""
    source_rel, source_sha, v1_rel = payload
    from modifc_gen import geomindex, verify

    started = time.perf_counter()
    path = str(ROOT / source_rel)
    target = Path(geomindex.cache_dir()) / (geomindex.cache_key(path) + ".npz")
    how = "cached"
    if not target.exists():
        # A v2 file byte-identical to its v1 file has the v1 file's index; the
        # generator's cache holds it under the v1 path's key.
        v1_path = str(ROOT / v1_rel) if v1_rel else ""
        v1_cache = (C10 / "gen/geom_index" / (geomindex.cache_key(v1_path) + ".npz")
                    if v1_path and os.path.exists(v1_path) else None)
        if v1_cache is not None and v1_cache.exists() and \
                verify.sha256_of(v1_path) == source_sha:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(v1_cache, str(target) + ".tmp")
            os.replace(str(target) + ".tmp", target)
            how = "copied_from_identical_v1"
        else:
            from modifc_gen.scene import Scene

            scene = Scene(path, source_rel, source_sha)
            scene.geometry_index()
            how = "built"
    return {"source": source_rel, "how": how,
            "seconds": round(time.perf_counter() - started, 1), "peak_gb": _peak_gb()}


# ------------------------------------------------------------------ driver


def read_journal(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        for line in open(path, encoding="utf-8"):
            if line.strip():
                entry = json.loads(line)
                out[entry["task_id"]] = entry
    return out


def run_two_pools(items_small, items_large, func, small_workers, cores, on_result):
    import multiprocessing as mp

    context = mp.get_context("fork")
    lock = threading.Lock()

    def consume(items, workers):
        if not items:
            return
        with context.Pool(workers, initializer=_init_worker, initargs=(cores,),
                          maxtasksperchild=1) as pool:
            for out in pool.imap_unordered(func, items, 1):
                with lock:
                    on_result(out)

    threads = [threading.Thread(target=consume, args=(items_small, small_workers)),
               threading.Thread(target=consume, args=(items_large, 1))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--work", required=True)
    parser.add_argument("--small-workers", type=int, default=2)
    parser.add_argument("--cores", default="8-9")
    parser.add_argument("--large-mb", type=float, default=30.0)
    parser.add_argument("--chunk", type=int, default=40)
    parser.add_argument("--control-v1", action="store_true")
    parser.add_argument("--task-ids", nargs="*", default=[])
    parser.add_argument("--index-only", action="store_true")
    args = parser.parse_args()
    # A later allowance (2026-09-27: cores 5-9 and 20-23, up to
    # six worker processes, 12 GB) is read at launch, so a run the launcher starts
    # after it was granted uses it.
    allowance = RESOURCE / "allowance.json"
    if allowance.exists():
        granted = json.load(open(allowance))
        args.small_workers = int(granted.get("small_workers", args.small_workers))
        args.cores = str(granted.get("cores", args.cores))
        print(f"allowance: {granted}", flush=True)

    cores = []
    for part in args.cores.split(","):
        lo, _, hi = part.partition("-")
        cores.extend(range(int(lo), int(hi or lo) + 1))
    os.sched_setaffinity(0, set(cores))
    started = time.perf_counter()
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    journal_path = work / ("journal_control_v1.jsonl" if args.control_v1 else "journal.jsonl")
    index_log = work / "geom_index.jsonl"

    v2 = v2_entries()
    columns = changed_columns()
    lines = open(args.tasks, "rb").read().splitlines(keepends=True)
    records = [json.loads(l) for l in lines]
    wanted = set(args.task_ids)

    plan: dict[str, dict] = {}          # task id -> what happens to it
    groups: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        tid = record["task_id"]
        if not is_migrated(record):
            plan[tid] = {"action": "native"}
            continue
        entry = v2.get(record["source_model"]["key"])
        if entry is None:
            plan[tid] = {"action": "drop", "reason": "no_v2_entry"}
            continue
        assert Path(entry["relpath"]).name == Path(record["input_ifc"]).name, tid
        building = CHANGED_FILES.get(Path(entry["relpath"]).name)
        if building is not None:
            hits = mentions(record, columns[building])
            if hits:
                plan[tid] = {"action": "drop", "reason": "changed_column",
                             "detail": hits}
                continue
        plan[tid] = {"action": "resource", "v2_relpath": entry["relpath"],
                     "v2_sha256": entry["sha256"]}
        if wanted and tid not in wanted:
            continue
        source = record["input_ifc"] if args.control_v1 else entry["relpath"]
        sha = record["source_model"]["sha256"] if args.control_v1 else entry["sha256"]
        groups[(source, sha, record["input_ifc"])].append(record)
    counts = Counter(p["action"] for p in plan.values())
    print(f"{len(records)} tasks: {dict(counts)}; {len(groups)} sources to check", flush=True)

    # Phase 0: the geometry index of every source, one process per source, so no
    # two processes write one cache file.
    done_index = {json.loads(l)["source"] for l in open(index_log)} if index_log.exists() else set()
    idx_items = [(src, sha, v1) for (src, sha, v1) in groups if src not in done_index]
    size = lambda rel: (ROOT / rel).stat().st_size / 1e6  # noqa: E731
    with open(index_log, "a") as fh:
        def on_index(out):
            fh.write(json.dumps(out) + "\n"); fh.flush()
            print(f"  index {out['how']} {out['source']} {out['seconds']}s {out['peak_gb']} GB", flush=True)
        run_two_pools([i for i in idx_items if size(i[0]) < args.large_mb],
                      sorted([i for i in idx_items if size(i[0]) >= args.large_mb],
                             key=lambda i: -size(i[0])),
                      build_index, args.small_workers, cores, on_index)
    if args.index_only:
        return 0

    # Phase 1: the checks, in chunks of one source.
    journal = read_journal(journal_path)
    items_small, items_large = [], []
    for (src, sha, v1), members in groups.items():
        pending = [r for r in members if r["task_id"] not in journal]
        # Sources whose bytes changed first: their checks carry the information.
        changed = sha != members[0]["source_model"]["sha256"]
        for i in range(0, len(pending), args.chunk):
            chunk = pending[i:i + args.chunk]
            item = (src, sha, chunk, str(work / "scratch"),
                    f"{Path(src).stem}-{i // args.chunk:03d}")
            (items_large if size(src) >= args.large_mb else items_small).append(
                (0 if changed else 1, -size(src), item))
    items_small = [x[2] for x in sorted(items_small, key=lambda x: (x[0], x[1]))]
    items_large = [x[2] for x in sorted(items_large, key=lambda x: (x[0], x[1]))]
    # Balance: the one-worker pool takes its large sources first and then small
    # chunks from the tail of the small list, until it carries its share of the
    # estimated load (source megabytes times tasks).
    load = lambda item: size(item[0]) * len(item[2]) + 1.2 * len(item[2])  # noqa: E731
    total = sum(load(i) for i in items_small + items_large)
    share = total / (args.small_workers + 1)
    carried = sum(load(i) for i in items_large)
    while items_small and carried + load(items_small[-1]) <= share:
        carried += load(items_small[-1])
        items_large.append(items_small.pop())
    n_pending = sum(len(i[2]) for i in items_small + items_large)
    print(f"{n_pending} tasks to check in {len(items_small)} + {len(items_large)} chunks", flush=True)
    progress = {"n": 0, "failed": 0, "peak": 0.0}
    with open(journal_path, "a", encoding="utf-8") as fh:
        def on_chunk(out):
            for res in out["results"]:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
                progress["n"] += 1
                progress["failed"] += 0 if res["ok"] else 1
            fh.flush()
            progress["peak"] = max(progress["peak"], out["peak_gb"])
            rate = progress["n"] / max(1e-9, time.perf_counter() - started) * 3600
            print(f"  {out['chunk']}: {len(out['results'])} tasks, {out['seconds']}s, "
                  f"{out['peak_gb']} GB | {progress['n']}/{n_pending}, "
                  f"{progress['failed']} failed, {rate:.0f}/h", flush=True)
        run_two_pools(items_small, items_large, check_chunk, args.small_workers,
                      cores, on_chunk)

    if args.control_v1 or wanted or not args.out:
        return 0

    # Assembly.
    journal = read_journal(journal_path)
    out_path = Path(args.out)
    tmp = out_path.with_suffix(".tmp")
    dropped = []
    stats = Counter()
    with open(tmp, "wb") as fout:
        for raw, record in zip(lines, records):
            tid = record["task_id"]
            step = plan[tid]
            if step["action"] == "native":
                fout.write(raw)
                stats["native_unchanged"] += 1
                continue
            if step["action"] == "drop":
                dropped.append({"task_id": tid, "reason": step["reason"],
                                "detail": step.get("detail")})
                stats[f"dropped:{step['reason']}"] += 1
                continue
            res = journal[tid]
            if not res["ok"]:
                dropped.append({"task_id": tid, "reason": f"check_failed:{res['stage']}",
                                "detail": res.get("reason")})
                stats[f"dropped:check_failed:{res['stage']}"] += 1
                continue
            new = copy.deepcopy(record)
            ver = new["verification"]
            old = {"input_ifc": record["input_ifc"],
                   "source_sha256": record["source_model"]["sha256"],
                   "gold_sha256": ver["gold_sha256"], "gold_bytes": ver["gold_bytes"]}
            new["input_ifc"] = step["v2_relpath"]
            new["source_model"]["relpath"] = step["v2_relpath"]
            new["source_model"]["sha256"] = step["v2_sha256"]
            ver["gold_sha256"] = res["gold_sha256"]
            ver["gold_bytes"] = res["gold_bytes"]
            if res.get("reexecution_match") != ver.get("reexecution_match"):
                old["reexecution_match"] = ver.get("reexecution_match")
                ver["reexecution_match"] = res.get("reexecution_match")
            if "null_edit_score" in res and res["null_edit_score"] != ver.get("null_edit_score"):
                old["null_edit_score"] = ver.get("null_edit_score")
                ver["null_edit_score"] = res["null_edit_score"]
            if res.get("self_score") and res["self_score"] != ver.get("self_score"):
                old["self_score"] = ver.get("self_score")
                ver["self_score"] = res["self_score"]
            for key, value in res["scene_counts"].items():
                if new["difficulty"].get(key) != value:
                    old[key] = new["difficulty"].get(key)
                    new["difficulty"][key] = value
            ver["resourced"] = TAG
            ver["resourced_old"] = old
            changed = set(diff_paths(record, new))
            assert changed <= MAY_CHANGE, (tid, sorted(changed - MAY_CHANGE))
            fout.write((json.dumps(new, ensure_ascii=False) + "\n").encode("utf-8"))
            stats["resourced"] += 1
            for key in old:
                stats[f"changed:{key}"] += 1
    os.replace(tmp, out_path)
    (work / "dropped.jsonl").write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in dropped))
    summary = {"tasks": args.tasks, "out": str(out_path), "n_input": len(records),
               "n_output": len(records) - len(dropped), "counts": dict(stats),
               "plan": dict(counts),
               "checks": {"passed": sum(1 for r in journal.values() if r["ok"]),
                          "failed_by_stage": dict(Counter(r["stage"] for r in journal.values()
                                                          if not r["ok"])),
                          "reexecution_match": dict(Counter(r.get("reexecution_match")
                                                            for r in journal.values() if r["ok"])),
                          "filling_type_unset": sum(1 for r in journal.values()
                                                    if r.get("filling_type_unset"))},
               "wall_seconds_this_run": round(time.perf_counter() - started, 1)}
    (work / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
