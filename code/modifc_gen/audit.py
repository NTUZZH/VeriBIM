"""Re-run the whole verification funnel from a task file.

The generator checks each task as it is produced.  This runs the same checks
again afterwards, from the task records alone: it rebuilds the anchor
from the record's stored parameters, re-executes the record's stored gold
script, re-parses the gold model, and re-scores it against itself.  Passing here
also shows that a task record is self-describing, which is what a published
dataset has to be.

Where the gold model was not kept on disk, ``--rebuild`` regenerates it from
the record's gold script into scratch, checks it against the checksum the
record carries, audits it, and deletes it again.

    python -m modifc_gen.audit --root . --tasks data/modifc_tasks_smoke/tasks.jsonl
    python -m modifc_gen.audit --root . --tasks data/veribim_tasks_v1/tasks.jsonl \
        --rebuild --sample 500 --workers 6 --cores 12-23
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional, Sequence

from . import verify
from .anchors import from_record as anchor_from_record
from .run import _init_worker, parse_cores
from .scene import Scene


def audit_group(payload: tuple) -> list[dict[str, Any]]:
    """Audit every task that shares one source model."""
    root, records, scratch, rebuild_missing = payload
    root_path = Path(root)
    scratch_path = Path(scratch)
    scratch_path.mkdir(parents=True, exist_ok=True)

    from modifc_score.model_cache import MeshCache, ModelCache
    # Two entries: the source model every task of this group reuses, and the
    # gold model of the task in hand.  A third would hold a gold model that has
    # already been checked and will not be asked for again, and on the largest
    # sources that is gigabytes of resident memory per worker for nothing.
    models_cache = ModelCache(capacity=2)
    meshes_cache = MeshCache(capacity_vertices=1_500_000)

    source_relpath = records[0]["input_ifc"]
    source_path = str(root_path / source_relpath)
    results: list[dict[str, Any]] = []
    try:
        scene = Scene(source_path, source_relpath,
                      records[0]["source_model"]["sha256"])
    except Exception as exc:
        return [{"task_id": r["task_id"], "ok": False, "stage": "scene",
                 "reason": repr(exc)[:200]} for r in records]

    for record in records:
        started = time.perf_counter()
        gold_path = record["gold_model"]
        if not os.path.isabs(gold_path):
            gold_path = str(root_path / gold_path)
        result: dict[str, Any] = {"task_id": record["task_id"], "ok": True,
                                  "stage": "", "reason": ""}

        rebuilt: Optional[str] = None
        if not os.path.exists(gold_path) and rebuild_missing:
            from .materialize import rebuild as rebuild_gold

            target = scratch_path / f"{record['task_id']}.ifc"
            outcome = rebuild_gold(record, root_path, target, check=False)
            if not outcome.ok:
                results.append({**result, "ok": False, "stage": "gold_model",
                                "reason": outcome.reason or "rebuild_failed"})
                continue
            gold_path = str(target)
            rebuilt = gold_path
            result["gold_rebuilt"] = True
        if not os.path.exists(gold_path):
            results.append({**result, "ok": False, "stage": "gold_model",
                            "reason": "missing"})
            continue
        if verify.sha256_of(gold_path) != record["verification"]["gold_sha256"]:
            _drop(rebuilt)
            results.append({**result, "ok": False, "stage": "gold_model",
                            "reason": "sha256_changed"})
            continue

        # A task whose instruction leaves out a value the edit needs is proved
        # the other way round: its reference is not meant to single an element
        # out, so what is checked is that the value the record says is missing
        # is missing from the sentence and that more than one element fits.
        clarification = (record.get("edit_params") or {}).get("clarification") \
            or record.get("clarification")
        anchor = anchor_from_record(record["anchor"])
        if clarification:
            stage = verify.check_underspecified(
                scene, record.get("prompt") or record.get("instruction") or "",
                clarification, record.get("family") or "")
            if not stage.ok:
                _drop(rebuilt)
                results.append({**result, "ok": False,
                                "stage": "underspecified",
                                "reason": stage.reason})
                continue
        else:
            stage = verify.check_anchor(scene, anchor,
                                        record["anchor"]["expected"])
            if not stage.ok:
                _drop(rebuilt)
                results.append({**result, "ok": False, "stage": "anchor",
                                "reason": stage.reason})
                continue

        stage = verify.check_reexecution(
            record["gold_script"], source_path, gold_path,
            list(record["target"]["guids"]), str(scratch_path))
        if not stage.ok:
            _drop(rebuilt)
            results.append({**result, "ok": False, "stage": "reexecute",
                            "reason": stage.reason})
            continue
        result["reexecution_match"] = stage.detail.get("match")

        params = record.get("edit_params") or {}
        stage = verify.check_parse(
            gold_path, [], [],
            params.get("relation_edges") or (),
            params.get("expected_world_box"),
            (record.get("edit_guids") or {}).get("relations") or (),
            params.get("expected_world_origin"))
        if not stage.ok:
            _drop(rebuilt)
            results.append({**result, "ok": False, "stage": "parse",
                            "reason": stage.reason})
            continue

        if params.get("scope") == "batch":
            stage = verify.check_batch_scope(
                source_path, gold_path,
                params.get("batch_members") or record["target"]["guids"],
                params.get("batch_pool") or (), models_cache)
            if not stage.ok:
                _drop(rebuilt)
                results.append({**result, "ok": False, "stage": "batch_scope",
                                "reason": stage.reason})
                continue

        if clarification:
            # Scoring the gold against itself would say nothing here: a model
            # nobody edited scores one whatever the task asked for.  What has
            # to hold is that the gold is the source model with nothing done
            # to it, compared entity by entity.
            stage = verify.check_no_edit(source_path, gold_path, models_cache)
            result["no_edit"] = stage.detail
            if not stage.ok:
                _drop(rebuilt)
                results.append({**result, "ok": False, "stage": "no_edit",
                                "reason": stage.reason})
                continue
        else:
            stage = verify.check_self_score(
                record["task_id"], record["operation"], record["category"],
                record["target"]["entity_type"], record["target"]["guids"],
                source_path, gold_path, models_cache, meshes_cache)
            result["self_score"] = stage.detail
            if not stage.ok:
                _drop(rebuilt)
                results.append({**result, "ok": False, "stage": "self_score",
                                "reason": stage.reason})
                continue
        result["seconds"] = round(time.perf_counter() - started, 2)
        _drop(rebuilt)
        results.append(result)
    return results


def _drop(path: Optional[str]) -> None:
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cores", default="")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild a gold model that is not on disk, from "
                             "the record's own gold script, and delete it again")
    parser.add_argument("--sample", type=int, default=0,
                        help="audit a stratified random sample of this size "
                             "rather than every task")
    parser.add_argument("--split", default=None)
    parser.add_argument("--seed", type=int, default=20260825)
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    records = [json.loads(line) for line in
               Path(args.tasks).read_text().splitlines() if line.strip()]
    if args.split:
        records = [r for r in records if r.get("split") == args.split]
    if args.sample and args.sample < len(records):
        import random

        buckets: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for record in records:
            buckets[(record["category"], record["operation"], record["tier"])
                    ].append(record)
        rng = random.Random(args.seed)
        per_bucket = max(1, args.sample // max(1, len(buckets)))
        picked: list[dict[str, Any]] = []
        for key in sorted(buckets):
            bucket = sorted(buckets[key], key=lambda r: r["task_id"])
            rng.shuffle(bucket)
            picked.extend(bucket[:per_bucket])
        rng.shuffle(picked)
        records = picked[:args.sample]
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        groups[record["input_ifc"]].append(record)

    scratch = Path(tempfile.mkdtemp(prefix="modifc_audit_"))
    cores = parse_cores(args.cores) if args.cores else []
    payloads = [(str(root), group, str(scratch / f"g{i}"), args.rebuild)
                for i, group in enumerate(groups.values())]

    import multiprocessing as mp
    context = mp.get_context("fork")
    started = time.perf_counter()
    with context.Pool(max(1, args.workers), initializer=_init_worker,
                      initargs=(cores,)) as pool:
        results = [r for group in pool.map(audit_group, payloads) for r in group]
    elapsed = time.perf_counter() - started

    failures = [r for r in results if not r["ok"]]
    summary = {
        "tasks": args.tasks,
        "split": args.split,
        "sampled": bool(args.sample),
        "n_rebuilt": sum(1 for r in results if r.get("gold_rebuilt")),
        "n_tasks": len(results),
        "n_passed": len(results) - len(failures),
        "n_failed": len(failures),
        "failures": [{k: r[k] for k in ("task_id", "stage", "reason")}
                     for r in failures],
        "reexecution_match": dict(Counter(r.get("reexecution_match")
                                          for r in results if r["ok"])),
        "seconds": elapsed,
    }
    text = json.dumps(summary, indent=1)
    if args.out:
        Path(args.out).write_text(text)
    print(text)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
