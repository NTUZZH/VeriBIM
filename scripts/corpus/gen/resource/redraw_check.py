"""Redraw check: a fresh generation on the v2 file reproduces the re-sourced task.

Run with
PYTHONPATH=gen/resource/code_fixed:gen/resource/code_fixed/harness, i.e. the
installed generator plus gen/repair/generator_fix.diff.

For every sampled task: the generator settings of the run that made it
(``wave_settings`` in the run's funnel.json) are configured, the Scene is built on
the v2 file exactly as ``scale.run_shard`` builds it, and the task is drawn again
from ``random.Random(task_seed)`` with ``generate.draw_single`` or
``generate.draw_chain`` for the cell the shard recorded for the task's
``generation_task_id``.  The gold script is rendered with ``script.render_script``
under the generation id and renamed to the task id as ``scale.relabel`` renames it.
Instruction, edit parameters and gold script must equal the re-sourced record.
As a secondary read, the full record ``generate.build_record`` writes for the
redraw is compared field by field with the re-sourced record.

    python redraw_check.py sample --out SAMPLE.json --records A.jsonl B.jsonl --n 600
    python redraw_check.py run --sample SAMPLE.json --records ... --out redraw_check.json
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import argparse
import difflib
import glob
import hashlib
import json
import random
import resource
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(".")
C10 = ROOT / "runs_local/corpus_v10"
RESOURCE = C10 / "gen/resource"
FIXED = RESOURCE / "code_fixed"
os.environ.setdefault("MODIFC_GEOM_CACHE", str(RESOURCE / "geom_index"))
RUN_OF_WAVE = {"v10x3": "train_ifc4x3", "v10x4": "train_ifc4"}
MIGRATED_DIRS = ("runs_local/corpus_v10/migrated/", "runs_local/corpus_v10/heldout_4x3/")


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_records(paths):
    out = {}
    for path in paths:
        for line in open(path, encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                out[r["task_id"]] = r
    return out


def v2_entries():
    out = {}
    for path in sorted(glob.glob(str(C10 / "migrator_v2/pool_*.json"))):
        for entry in json.load(open(path))["models"]:
            if entry.get("migrator") == "v2":
                out[entry["key"]] = entry
    return out


# ------------------------------------------------------------------ sample


def cmd_sample(args) -> int:
    records = load_records(args.records)
    exclude = set()
    for path in args.exclude or ():
        for line in open(path):
            if line.strip():
                exclude.add(json.loads(line)["task_id"])
    strata = defaultdict(list)
    for r in records.values():
        if not r["input_ifc"].startswith(MIGRATED_DIRS) and \
                not (r.get("verification") or {}).get("resourced"):
            continue
        if r["task_id"] in exclude:
            continue
        version = r["source_model"]["schema"]
        strata[(version, r["tier"], r["operation"], r["category"])].append(r)
    keys = sorted(strata)
    base = args.n // len(keys)
    alloc = {k: min(base, len(strata[k])) for k in keys}
    left = args.n - sum(alloc.values())
    spare = {k: len(strata[k]) - alloc[k] for k in keys}
    total_spare = sum(spare.values())
    for k in keys:
        extra = int(left * spare[k] / total_spare) if total_spare else 0
        alloc[k] += min(extra, spare[k])
    # rounding: fill the last few from the largest spares
    for k in sorted(keys, key=lambda k: -(len(strata[k]) - alloc[k])):
        if sum(alloc.values()) >= args.n:
            break
        if alloc[k] < len(strata[k]):
            alloc[k] += 1
    chosen = []
    for k in keys:
        by_building = defaultdict(list)
        for r in strata[k]:
            by_building[r["building_id"]].append(r)
        for group in by_building.values():
            group.sort(key=lambda r: _h("redraw|" + r["task_id"]))
        order = sorted(by_building, key=lambda b: _h("redraw|" + k[0] + b))
        picked, depth = [], 0
        while len(picked) < alloc[k]:
            for b in order:
                if len(picked) < alloc[k] and len(by_building[b]) > depth:
                    picked.append(by_building[b][depth]["task_id"])
            depth += 1
        chosen.extend(picked)
    buildings = {records[t]["building_id"] for t in chosen}
    summary = {"n": len(chosen), "n_buildings": len(buildings),
               "strata": {"/".join(k): {"available": len(strata[k]), "chosen": alloc[k]}
                          for k in keys},
               "filling_repaired": sum(1 for t in chosen
                                       if (records[t].get("verification") or {}).get("repair")),
               "task_ids": chosen}
    Path(args.out).write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: v for k, v in summary.items() if k != "task_ids"}, indent=1))
    return 0


# --------------------------------------------------------------------- run


def cell_of(run: str, shard_id: str, generation_id: str, cache: dict) -> str:
    key = (run, shard_id)
    if key not in cache:
        payload = json.load(open(C10 / "gen" / run / "shards" / f"{shard_id}.json"))
        cache[key] = {o["task_id"]: o["cell"] for o in payload["outcomes"]
                      if o.get("stage") == "accepted"}
    return cache[key][generation_id]


def unified(a: str, b: str, name: str, limit: int = 40) -> list[str]:
    lines = list(difflib.unified_diff(a.splitlines(), b.splitlines(),
                                      f"record.{name}", f"redraw.{name}", lineterm="", n=1))
    return lines[:limit]


def json_diff(a, b, prefix=""):
    if isinstance(a, dict) and isinstance(b, dict):
        out = []
        for key in list(a) + [k for k in b if k not in a]:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in a or key not in b:
                out.append((path, a.get(key, "<absent>"), b.get(key, "<absent>")))
            else:
                out.extend(json_diff(a[key], b[key], path))
        return out
    if a != b:
        return [(prefix, a, b)]
    return []


def _redraw_group(payload):
    """Redraw every sampled task of one source, in a worker process."""
    run, key, members, wave, entry = payload
    sys.path[:0] = [str(FIXED), str(FIXED / "harness")]
    from modifc_gen import generate, ops, script, settings
    from modifc_gen.corpus import ModelRef
    from modifc_gen.scene import Scene
    import modifc_gen

    assert str(FIXED) in modifc_gen.__file__, modifc_gen.__file__
    if hasattr(os, "sched_setaffinity") and _CORES:
        os.sched_setaffinity(0, set(_CORES))
    wave_settings = {run: wave}
    v2 = {key: entry}
    shard_cache: dict = {}
    out = []
    settings.configure(**wave_settings[run])
    entry = v2[key]
    model = ModelRef(key=entry["key"], relpath=entry["relpath"],
                     sha256=entry["sha256"], collection=entry["collection"],
                     schema=entry["schema"], bytes=entry["bytes"],
                     n_products=entry["n_products"], counts=entry["family_counts"])
    t0 = time.perf_counter()
    scene = Scene(str(ROOT / model.relpath), model.relpath, model.sha256)
    for r in members:
        res = {"task_id": r["task_id"], "run": run, "source": model.relpath,
               "building_id": r["building_id"], "tier": r["tier"],
               "operation": r["operation"], "category": r["category"],
               "edit_kind": r["edit_kind"],
               "filling_repaired": bool((r.get("verification") or {}).get("repair"))}
        gen_id = r["generation_task_id"]
        try:
            cell = cell_of(run, r["shard_id"], gen_id, shard_cache)
            res["cell"] = cell
            ops.reset_rejections()
            ops.reset_derived()
            seed = int(r["seeds"]["task_seed"])
            rng = random.Random(seed)
            if r["tier"] == "single":
                category, operation, family = cell.split("/")
                draw, reason = generate.draw_single(scene, category, operation,
                                                    family, gen_id, rng)
            else:
                category, kind = cell.split("/")
                draw, reason = generate.draw_chain(scene, category, kind,
                                                   gen_id, rng)
        except Exception as exc:  # noqa: BLE001
            res.update(match=False, error=f"{type(exc).__name__}: {exc}"[:300])
            out.append(res)
            continue
        if draw is None:
            res.update(match=False, error=f"no_draw: {reason}")
            out.append(res)
            continue
        rendered = script.render_script(gen_id, draw.instruction, draw.plan)
        rendered = rendered.replace(gen_id, r["task_id"])
        params = json.loads(json.dumps(draw.plan.params, ensure_ascii=False))
        fields = {"instruction": draw.instruction == r["instruction"],
                  "edit_params": params == r["edit_params"],
                  "gold_script": rendered == r["gold_script"]}
        res["fields"] = fields
        res["match"] = all(fields.values())
        if not res["match"]:
            res["diff"] = {}
            if not fields["instruction"]:
                res["diff"]["instruction"] = unified(r["instruction"], draw.instruction,
                                                     "instruction")
            if not fields["edit_params"]:
                res["diff"]["edit_params"] = [
                    [p, json.dumps(a)[:300], json.dumps(b)[:300]]
                    for p, a, b in json_diff(r["edit_params"], params)][:20]
            if not fields["gold_script"]:
                res["diff"]["gold_script"] = unified(r["gold_script"], rendered,
                                                     "gold_script")
        # Secondary: the whole record the generator would write.
        try:
            full = generate.build_record(scene, model, r["task_id"], draw,
                                         r["gold_model"], seed, rendered)
            full = json.loads(json.dumps(full, ensure_ascii=False))
            skip = {"verification", "shard_id", "building_id", "split",
                    "generation_task_id", "input_ifc", "source_model"}
            diffs = [(p, a, b) for p, a, b in json_diff(
                {k: v for k, v in r.items() if k not in skip},
                {k: v for k, v in full.items() if k not in skip})]
            res["record_fields_differing"] = sorted({p for p, _a, _b in diffs})
            res["record_diff_examples"] = [[p, json.dumps(a)[:120], json.dumps(b)[:120]]
                                           for p, a, b in diffs[:6]]
            res["source_fields_match_v2"] = (
                r["input_ifc"] == model.relpath and
                r["source_model"]["sha256"] == model.sha256) if \
                (r.get("verification") or {}).get("resourced") else None
        except Exception as exc:  # noqa: BLE001
            res["record_error"] = f"{type(exc).__name__}: {exc}"[:200]
        out.append(res)
    log = (f"  {run} {key}: {len(members)} tasks, "
           f"{sum(1 for e in out if e.get('match'))} match, "
           f"{time.perf_counter() - t0:.1f}s, "
           f"peak {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6:.2f} GB")
    del scene
    return out, log


_CORES: list = []


def cmd_run(args) -> int:
    started = time.perf_counter()
    sample = json.load(open(args.sample))["task_ids"]
    records = load_records(args.records)
    v2 = v2_entries()
    wave_settings = {run: json.load(open(C10 / "gen" / run / "funnel.json"))["wave_settings"]
                     for run in RUN_OF_WAVE.values()}
    done = {}
    out_jsonl = Path(args.out).with_suffix(".jsonl")
    if out_jsonl.exists():
        for line in open(out_jsonl):
            if line.strip():
                e = json.loads(line)
                done[e["task_id"]] = e
    groups = defaultdict(list)
    for tid in sample:
        if tid in done or tid not in records:
            continue
        r = records[tid]
        entry = v2[r["source_model"]["key"]]
        groups[(RUN_OF_WAVE[r["wave"]], entry["key"])].append(r)
    payloads = [(run, key, members, wave_settings[run], v2[key])
                for (run, key), members in sorted(groups.items(),
                                                  key=lambda kv: -v2[kv[0][1]]["bytes"])]
    global _CORES
    _CORES = []
    for part in args.cores.split(","):
        lo, _, hi = part.partition("-")
        _CORES.extend(range(int(lo), int(hi or lo) + 1))
    import multiprocessing as mp

    with open(out_jsonl, "a") as fh, mp.get_context("fork").Pool(
            max(1, args.workers), maxtasksperchild=1) as pool:
        for out, log in pool.imap_unordered(_redraw_group, payloads, 1):
            for res in out:
                fh.write(json.dumps(res, ensure_ascii=False) + "\n")
            fh.flush()
            print(log, flush=True)

    results = [json.loads(l) for l in open(out_jsonl) if l.strip()]
    results = [e for e in results if e["task_id"] in set(sample)]
    n = len(results)
    n_match = sum(1 for e in results if e["match"])
    by = lambda key: {k: {"n": sum(1 for e in results if e[key] == k),  # noqa: E731
                          "match": sum(1 for e in results if e[key] == k and e["match"])}
                      for k in sorted({e[key] for e in results})}
    summary = {
        "generator": "code/modifc_gen + gen/repair/generator_fix.diff (gen/resource/code_fixed)",
        "n": n, "n_match": n_match, "match_rate": round(n_match / max(1, n), 4),
        "n_buildings": len({e["building_id"] for e in results}),
        "by_run": by("run"), "by_tier": by("tier"), "by_operation": by("operation"),
        "by_category": by("category"),
        "filling_repaired": {"n": sum(1 for e in results if e["filling_repaired"]),
                             "match": sum(1 for e in results
                                          if e["filling_repaired"] and e["match"])},
        "field_mismatch_counts": dict(Counter(f for e in results for f, ok in
                                              (e.get("fields") or {}).items() if not ok)),
        "errors": [{"task_id": e["task_id"], "error": e["error"]} for e in results
                   if e.get("error")],
        "mismatches": [{k: e.get(k) for k in ("task_id", "run", "source", "cell", "fields",
                                              "diff", "error")}
                       for e in results if not e["match"]],
        "secondary_record_fields_differing": dict(Counter(
            p for e in results for p in e.get("record_fields_differing") or ())),
        "secondary_examples": [{"task_id": e["task_id"], "diff": e["record_diff_examples"]}
                               for e in results if e.get("record_diff_examples")][:10],
        "source_fields_match_v2": dict(Counter(str(e.get("source_fields_match_v2"))
                                               for e in results)),
        "seconds_this_run": round(time.perf_counter() - started, 1),
        "peak_rss_gb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 2),
    }
    Path(args.out).write_text(json.dumps(summary, indent=1, ensure_ascii=False))
    print(json.dumps({k: summary[k] for k in ("n", "n_match", "match_rate", "n_buildings",
                                              "by_run", "by_tier", "filling_repaired",
                                              "field_mismatch_counts",
                                              "secondary_record_fields_differing")},
                     indent=1), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("sample")
    p.add_argument("--records", nargs="+", required=True)
    p.add_argument("--exclude", nargs="*", default=[])
    p.add_argument("--n", type=int, default=600)
    p.add_argument("--out", required=True)
    p = sub.add_parser("run")
    p.add_argument("--records", nargs="+", required=True)
    p.add_argument("--sample", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--cores", default="5-9")
    args = parser.parse_args()
    return cmd_sample(args) if args.cmd == "sample" else cmd_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
