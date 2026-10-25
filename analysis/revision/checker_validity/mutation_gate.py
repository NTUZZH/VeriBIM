"""Relation rows of the mutation study (Table A.3) re-read under the relation gate.

Re-applies, with the perturbation functions of
analysis/revision/checker/mutation.py (imported, not changed), the
perturbations of the 240 sampled tasks that bear on relations, scores each
perturbed file with the same checker call (stage_a.scoring.score_prediction,
family reading, per-pair geometry), and adds the relation-gated verdict of
gate_abs.py.  Rows:

  control       ground truth written again (create/update)  -> must stay accepted
  containment   storey containment of the target removed
  filling       IfcRelFillsElement of the target removed
  wrong_host    door/window moved into the nearest other wall
  del_control   the gold deletion re-run on the source
  del_naive     new row: the targets removed with a bare file.remove() on the
                source, which leaves the relationships that named them behind

Writes results/mutation_gate.jsonl.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

MUT_PATH = C.ROOT / "analysis/revision/checker/mutation.py"
SAMPLE = C.ROOT / "analysis/revision/checker/sample.json"


def _mut():
    spec = importlib.util.spec_from_file_location("mutation_study", MUT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_task(task_id: str) -> list[dict]:
    import ifcopenshell
    import gate_abs as G
    from modifc_score.model_cache import MESHES, MODELS
    from stage_a.scoring import scorer_config_for
    M = _mut()
    tasks = C.load_tasks()
    record = tasks[task_id]
    work = C.TMP / f"mut_w{os.getpid()}"
    work.mkdir(parents=True, exist_ok=True)
    gold = C.unpack_gold(record, work / "g")
    cfg = scorer_config_for(record)
    src = C.source_path(record)
    rows = []
    op = record["operation"]
    if op == "delete":
        plan = [("del_control", None), ("del_naive", None)]
        model = ifcopenshell.open(str(src))
    else:
        plan = [("control", lambda c: {"note": "unchanged"}),
                ("containment", lambda c: M.p_drop_relation(c, "containment")),
                ("filling", lambda c: M.p_drop_relation(c, "filling")),
                ("wrong_host", M.p_wrong_host)]
        model = ifcopenshell.open(str(gold))
        ctx = M.Ctx(record, model)
    try:
        for name, builder in plan:
            row = {"task_id": task_id, "operation": op, "edit_kind": record["edit_kind"],
                   "target_class": record["target"]["entity_type"], "pert": name}
            path = work / f"{task_id}.{name}.ifc"
            try:
                model.begin_transaction()
                try:
                    if name == "del_control":
                        M.script_apply(record, model, record["gold_script"])
                        details = {"note": "gold script on the source"}
                    elif name == "del_naive":
                        gone = []
                        for g in record["target"]["guids"]:
                            try:
                                e = model.by_guid(g)
                            except Exception:
                                continue
                            model.remove(e)
                            gone.append(g)
                        details = {"removed": gone}
                    else:
                        ctx.m = model
                        details = builder(ctx)
                finally:
                    model.end_transaction()
                model.write(str(path))
                row["applied"] = True
                row["details"] = details
            except M.NotApplicable as na:
                row.update(applied=False, not_applicable=str(na))
            except Exception as exc:  # noqa: BLE001
                row.update(applied=False, build_error=f"{type(exc).__name__}: {exc}"[:300])
            finally:
                try:
                    model.undo()
                except Exception as exc:  # noqa: BLE001
                    row["undo_error"] = str(exc)[:200]
                    model = ifcopenshell.open(str(src if op == "delete" else gold))
                    if op != "delete":
                        ctx = M.Ctx(record, model)
            if row.get("applied"):
                sc = M._score(record, path, gold, cfg)
                row["score"] = sc
                row["accept_090"] = sc["accept_090"]
                row["accept_098"] = sc["accept_098"]
                fake = {"score": sc}
                g = G.process(record, fake, path, work / "gg")
                row["gate_pass"] = g.get("gate_pass")
                row["gate_reasons"] = g.get("gate_reasons")
                row["gate_strict_pass"] = g.get("gate_strict_pass")
                row["gate_strict_reasons"] = g.get("gate_strict_reasons")
                row["gated_accept_090"] = bool(sc["accept_090"] and g.get("gate_pass"))
                row["gated_strict_accept_090"] = bool(sc["accept_090"] and g.get("gate_strict_pass"))
                with MODELS._lock:
                    for key in [k for k in MODELS._store if k[0] == str(path.resolve())]:
                        MODELS._store.pop(key)
                path.unlink(missing_ok=True)
            rows.append(row)
    finally:
        gold.unlink(missing_ok=True)
        MESHES.clear()
        MODELS.clear()
    return rows


def _work(task_id):
    t0 = time.time()
    try:
        rows = run_task(task_id)
    except Exception as exc:  # noqa: BLE001
        rows = [{"task_id": task_id, "error": f"{type(exc).__name__}: {exc}"[:300],
                 "trace": traceback.format_exc()[-1500:]}]
    for r in rows:
        r["task_seconds"] = round(time.time() - t0, 1)
    return rows


def _init():
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    from modifc_score.model_cache import MESHES, MODELS
    MODELS.capacity = 3
    MESHES.capacity_vertices = 800_000


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="", help="v4d recompute: only these sampled tasks (with --v4d-out)")
    ap.add_argument("--v4d-out", default="", help="write the rows to this file instead of results/")
    args = ap.parse_args()
    import multiprocessing as mp
    ids = json.load(open(SAMPLE))["task_ids"]
    if args.ids:
        want = [i for i in args.ids.split(",") if i]
        assert set(want) <= set(ids), "not in the sample"
        ids = [i for i in ids if i in set(want)]
    out = Path(args.v4d_out) if args.v4d_out else C.OUT / "mutation_gate.jsonl"
    done = set()
    if out.exists():
        done = {json.loads(l)["task_id"] for l in open(out) if l.strip()}
    ids = [i for i in ids if i not in done]
    if args.limit:
        ids = ids[:args.limit]
    print(f"{time.strftime('%F %T')} {len(ids)} tasks", flush=True)
    with open(out, "a") as fo, mp.get_context("spawn").Pool(args.workers, initializer=_init) as pool:
        for n, rows in enumerate(pool.imap_unordered(_work, ids), 1):
            for r in rows:
                fo.write(json.dumps(r) + "\n")
            fo.flush()
            if n % 20 == 0:
                print(f"{time.strftime('%F %T')} {n}/{len(ids)}", flush=True)
    print(f"{time.strftime('%F %T')} done", flush=True)


if __name__ == "__main__":
    main()
