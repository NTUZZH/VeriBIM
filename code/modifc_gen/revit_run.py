"""The driver for the Revit-export creation family.

Draws a requested number of tasks per element class, instruction style and
schema version on the training buildings of one or more pools, verifies each
through the generator's funnel, and writes the accepted records.  The work is
split into one shard per source model, so a model is parsed once per pass, and
a second pass gives the cells that fell short to the models that already
yielded them.  A shard whose result file is on disk is not run again, so
re-running the same command resumes.

    python -m modifc_gen.revit_run --root <repository> --out runs_local/extA \\
        --pools pool_v10_IFC4X3.json,pool_v10_IFC4.json,pool_v10_IFC2X3.json \\
        --exclude-buildings BLD001,... --quota wall=364,slab=364,... \\
        --version-share IFC4X3=1,IFC4=1,IFC2X3=1 --total 2000 --workers 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import os
import random
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .version import GENERATOR_VERSION

#: Which families a model has to carry before a class is drawn on it.
NEEDS = {"wall": ("wall",), "slab": ("space", "slab"), "column": ("column", "space", "wall"),
         "space": ("wall",), "door": ("wall",), "window": ("wall",)}


def _seed(run_seed: int, shard_id: str, index: int) -> int:
    material = f"{run_seed}|{shard_id}|{index}".encode("utf-8")
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(),
                          "big") % (2 ** 31 - 1)


def _parse_map(text: str, cast=float) -> dict:
    out = {}
    for part in (text or "").split(","):
        if part.strip():
            key, _, value = part.partition("=")
            out[key.strip()] = cast(value)
    return out


def load_models(root: Path, pools: list[str], exclude: set, max_mb: dict) -> list[dict]:
    from . import revit  # noqa: F401  (fails early when the family is missing)

    models = []
    for pool in pools:
        data = json.loads((root / pool).read_text())
        for entry in data["models"]:
            if not entry.get("in_run", True) or entry["building_id"] in exclude:
                continue
            if entry["relpath"].startswith(("data/bimedit", "runs_local/e1")):
                continue
            cap = max_mb.get(entry["schema"], 30.0) * 1e6
            if entry["bytes"] > cap:
                continue
            models.append(entry)
    return models


def eligible(entry: dict, family: str) -> bool:
    counts = entry.get("family_counts") or {}
    return any(counts.get(name, 0) > 0 for name in NEEDS[family])


def allocate(models: list[dict], targets: dict, overdraw: float, rng: random.Random,
             favour: dict | None = None) -> dict[str, list]:
    """Requests per model: ``{model key: [(family, style, count), ...]}``."""
    from . import revit

    shards: dict[str, list] = defaultdict(list)
    for (version, family, style), wanted in sorted(targets.items()):
        if wanted <= 0:
            continue
        pool = [m for m in models if m["schema"] == version and eligible(m, family)]
        if favour:
            liked = [m for m in pool if favour.get((m["key"], family, style))]
            pool = liked + [m for m in pool if m not in liked]
        else:
            rng.shuffle(pool)
        if not pool:
            continue
        attempts = int(math.ceil(wanted * overdraw))
        per = defaultdict(int)
        for index in range(attempts):
            per[pool[index % len(pool)]["key"]] += 1
        for key, count in per.items():
            shards[key].append((family, style, count))
    assert revit.STYLES
    return shards


def run_shard(payload: tuple) -> dict[str, Any]:
    (shard_id, entry, requests, root, out_dir, scratch, run_seed, index_base) = payload
    from modifc_score.model_cache import MeshCache, ModelCache

    from . import generate, ops, revit
    from .corpus import ModelRef
    from .scene import Scene

    ops.reset_rejections()
    root_path, out_path = Path(root), Path(out_dir)
    scratch_path = Path(scratch) / shard_id
    scratch_path.mkdir(parents=True, exist_ok=True)
    result_path = out_path / "shards" / f"{shard_id}.json"
    started = time.perf_counter()
    model = ModelRef(key=entry["key"], relpath=entry["relpath"], sha256=entry["sha256"],
                     collection=entry["collection"], schema=entry["schema"],
                     bytes=entry["bytes"], n_products=entry.get("n_products", 0),
                     counts=entry.get("family_counts") or {})
    records, outcomes = [], []
    try:
        scene = Scene(str(root_path / model.relpath), model.relpath, model.sha256)
    except Exception as exc:  # noqa: BLE001
        outcomes.append({"stage": "scene", "reason": "scene_build_failed",
                         "detail": {"error": repr(exc)[:200]}})
        _write(result_path, shard_id, entry, records, outcomes, started)
        return {"shard_id": shard_id, "accepted": 0}
    models_cache = ModelCache(capacity=2)
    meshes_cache = MeshCache(capacity_vertices=1_500_000)
    seen: set[str] = set()
    index = index_base
    for family, style, wanted in requests:
        accepted = attempts = 0
        cell = f"{family}/{style}"
        budget = wanted * 2 + 1
        while accepted < wanted and attempts < budget:
            attempts += 1
            index += 1
            seed = _seed(run_seed, shard_id, index)
            rng = random.Random(seed)
            task_id = revit.task_id_for(model.key, family, style, index)
            t0 = time.perf_counter()
            try:
                draw, reason = revit.draw(scene, family, style, task_id, rng)
            except Exception as exc:  # noqa: BLE001
                outcomes.append({"task_id": task_id, "cell": cell, "stage": "draw",
                                 "reason": "draw_failed",
                                 "detail": {"error": repr(exc)[:300]}})
                continue
            if draw is None:
                outcomes.append({"task_id": task_id, "cell": cell, "stage": "draw",
                                 "reason": reason,
                                 "seconds": round(time.perf_counter() - t0, 2)})
                continue
            key = hashlib.blake2b(draw.instruction.encode(), digest_size=12).hexdigest()
            if key in seen:
                outcomes.append({"task_id": task_id, "cell": cell, "stage": "duplicate",
                                 "reason": "identical_instruction"})
                continue
            try:
                outcome = generate.produce(scene, model, task_id, draw, root_path,
                                           out_path, scratch_path, models_cache,
                                           meshes_cache, seed, False, False)
            except Exception as exc:  # noqa: BLE001
                outcomes.append({"task_id": task_id, "cell": cell, "stage": "produce",
                                 "reason": "produce_failed",
                                 "detail": {"error": repr(exc)[:300]}})
                continue
            outcomes.append({"task_id": task_id, "cell": cell, "stage": outcome.stage,
                             "reason": outcome.reason, "detail": outcome.detail,
                             "seconds": round(time.perf_counter() - t0, 2)})
            if outcome.stage == "accepted" and outcome.record is not None:
                record = outcome.record
                record["shard_id"] = shard_id
                record["building_id"] = entry["building_id"]
                record["split"] = "train"
                record["ifc_version"] = entry["schema"]
                record["origin"] = entry.get("origin", "native")
                record["source_relpath"] = entry.get("source_relpath", entry["relpath"])
                record["wave"] = "extA"
                records.append(record)
                seen.add(key)
                accepted += 1
    _write(result_path, shard_id, entry, records, outcomes, started,
           ops.rejection_counts())
    try:
        import shutil

        shutil.rmtree(scratch_path, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass
    return {"shard_id": shard_id, "accepted": len(records),
            "seconds": round(time.perf_counter() - started, 1)}


def _write(path: Path, shard_id: str, entry: dict, records, outcomes, started,
           rejections=None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(".partial")
    partial.write_text(json.dumps({
        "shard_id": shard_id, "key": entry["key"], "schema": entry["schema"],
        "building_id": entry["building_id"],
        "seconds": round(time.perf_counter() - started, 2),
        "generator_version": GENERATOR_VERSION, "records": records,
        "outcomes": outcomes, "placement_rejections": rejections or {}}))
    os.replace(partial, path)


def _init_worker() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")


def collect(out_dir: Path) -> tuple[list[dict], list[dict]]:
    records, outcomes = [], []
    for path in sorted((out_dir / "shards").glob("*.json")):
        data = json.loads(path.read_text())
        records.extend(data["records"])
        for outcome in data["outcomes"]:
            outcome = dict(outcome)
            outcome["schema"] = data["schema"]
            outcomes.append(outcome)
    return records, outcomes


def counts_of(records: list[dict]) -> Counter:
    from . import revit

    out: Counter = Counter()
    for record in records:
        style = (record.get("edit_params") or {}).get("revit", {}).get("style")
        out[(record["ifc_version"], record["family"], style)] += 1
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--pools", required=True)
    parser.add_argument("--exclude-buildings", default="")
    parser.add_argument("--quota", required=True,
                        help="family=count over all versions and styles")
    parser.add_argument("--version-share", default="IFC4X3=1,IFC4=1,IFC2X3=1")
    parser.add_argument("--max-mb", default="IFC4X3=30,IFC4=30,IFC2X3=45")
    parser.add_argument("--overdraw", type=float, default=1.6)
    parser.add_argument("--passes", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261003)
    parser.add_argument("--limit-models", type=int, default=0)
    parser.add_argument("--index-offset", type=int, default=0,
                        help="added to every task index, so two runs over the same "
                             "models write different task identifiers")
    args = parser.parse_args(argv)

    from . import revit

    root = Path(args.root).resolve()
    out_dir = Path(args.out)
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    scratch = out_dir / "_scratch"
    exclude = {b for b in args.exclude_buildings.split(",") if b}
    max_mb = _parse_map(args.max_mb)
    models = load_models(root, [p for p in args.pools.split(",") if p], exclude, max_mb)
    rng = random.Random(args.seed)
    if args.limit_models:
        rng.shuffle(models)
        models = models[:args.limit_models]
    quota = _parse_map(args.quota, int)
    shares = _parse_map(args.version_share)
    total_share = sum(shares.values())
    targets = {}
    for family, count in quota.items():
        for version, share in shares.items():
            for style in revit.STYLES:
                targets[(version, family, style)] = int(round(
                    count * share / total_share / len(revit.STYLES)))
    by_key = {m["key"]: m for m in models}
    plan_path = out_dir / "plan.json"
    plan_path.write_text(json.dumps({
        "models": len(models), "targets": {"|".join(k): v for k, v in targets.items()},
        "args": vars(args)}, indent=1))
    favour = None
    for number in range(1, args.passes + 1):
        records, _outcomes = collect(out_dir)
        have = counts_of(records)
        deficit = {cell: max(0, wanted - have.get(cell, 0))
                   for cell, wanted in targets.items()}
        if not any(deficit.values()):
            break
        overdraw = args.overdraw if number == 1 else args.overdraw * 1.5
        shards = allocate(models, deficit, overdraw, rng, favour)
        jobs = []
        for key, requests in sorted(shards.items()):
            shard_id = f"p{number}-{key}"
            if (out_dir / "shards" / f"{shard_id}.json").exists():
                continue
            jobs.append((shard_id, by_key[key], requests, str(root), str(out_dir),
                         str(scratch), args.seed, args.index_offset + number * 10000))
        # Larger models first, so the long shards do not finish last.
        jobs.sort(key=lambda job: -job[1]["bytes"])
        print(f"pass {number}: {len(jobs)} shards, deficit {sum(deficit.values())}",
              flush=True)
        started = time.time()
        with mp.get_context("fork").Pool(args.workers, initializer=_init_worker,
                                         maxtasksperchild=3) as pool:
            for done, result in enumerate(pool.imap_unordered(run_shard, jobs), 1):
                print(f"  {done}/{len(jobs)} {result['shard_id']} accepted "
                      f"{result['accepted']} {result.get('seconds', '')}s "
                      f"elapsed {time.time() - started:.0f}s", flush=True)
        records, outcomes = collect(out_dir)
        favour = {}
        for record in records:
            style = record["edit_params"]["revit"]["style"]
            favour[(record["source_model"]["key"], record["family"], style)] = True
    records, outcomes = collect(out_dir)
    have = counts_of(records)
    kept = []
    for record in sorted(records, key=lambda r: r["task_id"]):
        kept.append(record)
    with (out_dir / "tasks_extA_all.jsonl").open("w") as handle:
        for record in kept:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    funnel = Counter((o.get("stage"), o.get("reason")) for o in outcomes)
    (out_dir / "funnel.json").write_text(json.dumps({
        "accepted": len(kept),
        "by_cell": {"|".join(str(x) for x in k): v for k, v in sorted(have.items())},
        "targets": {"|".join(k): v for k, v in targets.items()},
        "outcomes": {f"{s}|{r}": n for (s, r), n in funnel.most_common()}},
        indent=1))
    print(f"accepted {len(kept)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
