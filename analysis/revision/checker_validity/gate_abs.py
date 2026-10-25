"""Analyses 1 and 2: relation-gated verdict and absolute position/dimension errors.

For every task of an arm, reads the source model, the ground truth and the
stored edited model, pairs each ground-truth target with its counterpart in the
edited model exactly as modifc_score.scorer.score_task pairs them (identity for
update tasks, one-to-one oriented-box overlap for create tasks), and records:

  * the relation gate: storey/spatial container and opening-filling host of
    every created or kept target, and new dangling relationships for deletions;
  * the absolute centre, placement and dimension errors of every paired target.

The checker itself is not changed; its pairing helpers are imported.
Writes results/gate_<arm>.jsonl (one row per task).

Usage: python gate_abs.py <arm> [--workers 4] [--completed-only]
       python gate_abs.py <arm> --ids a,b --v4d-out tmp/<file>.jsonl   (v4d recompute of the listed rows:
       written to the given file, not appended to results/; each row's edited_ifc is read where it lies
       when it exists on disk, the rest is unpacked from edited.tar.gz for the listed tasks only)
"""
from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import tarfile
import threading
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402

_W: dict = {}


def _open(path):
    import ifcopenshell
    return ifcopenshell.open(str(path))


def _source(record):
    p = str(C.source_path(record))
    if _W.get("src_path") != p:
        _W["src"] = None
        _W["src"] = _open(p)
        _W["src_path"] = p
        _W["src_dangling"] = None
        _W["src_orphans"] = None
    return _W["src"]


def pair_targets(record, model_0, model_gt, model_pred):
    """[(gt entity, pred entity or None, how)] as the checker pairs them."""
    from modifc_score import editset, scorer
    from modifc_score.config import DEFAULT_CONFIG as cfg
    from modifc_score.model_cache import MeshCache
    from modifc_score.tasks import Task
    from modifc_score import geometry as geo
    target = record.get("target") or {}
    task = Task(task_id=record["task_id"], operation=record["operation"],
                category=record["category"], input_ifc="", ground_truth_ifc="",
                prompt="", entity_type=target.get("entity_type", ""),
                guids=tuple(target.get("guids") or ()), tags=())
    refs, _src = editset.reference_entities(model_0, model_gt, task.operation,
                                            task.entity_type, task.guids)
    out = []
    if task.guids and task.operation == "update":
        for r in refs:
            p = editset.by_guid(model_pred, r.GlobalId)
            out.append((r, p, "identity"))
        return out
    meshes = MeshCache()
    ref_meshes = [geo.build_mesh(e, 0.001, False) for e in refs]
    cands = scorer.candidate_entities(task, model_0, model_pred, cfg)
    cands = scorer._limit_candidates(refs, cands, cfg.match_candidate_limit)
    cand_meshes = [geo.build_mesh(e, 0.001, False) for e in cands]
    iou = scorer._iou_matrix(ref_meshes, cand_meshes, cfg.obb_target_grid)
    assign = scorer._assign(iou, cfg.match_min_iou)
    for i, r in enumerate(refs):
        j = assign.get(i)
        out.append((r, cands[j] if j is not None else None, "obb"))
    return out


def gate_nondelete(pairs, model_0):
    """Relation gate for created / kept targets.  Returns (pass, reasons, detail)."""
    src_guids = set()
    reasons, detail = [], []
    gmap = {r.GlobalId: (p.GlobalId if p is not None else None) for r, p, _ in pairs}
    for r, p, _how in pairs:
        d = {"gt_guid": r.GlobalId, "class": r.is_a(),
             "pred_guid": p.GlobalId if p is not None else None}
        if p is None:
            d["status"] = "no counterpart"
            detail.append(d)
            reasons.append(f"{r.is_a()} {r.GlobalId}: no counterpart in the edited model")
            continue
        # (ii) spatial container
        gp, pp = C.spatial_parents(r), C.spatial_parents(p)
        d["gt_container"], d["pred_container"] = sorted(gp), sorted(pp)
        if gp:
            exp = set()
            for g in gp:
                exp.add(g if _exists(model_0, g) else gmap.get(g, g))
            if not pp:
                reasons.append(f"{r.is_a()}: not contained in any spatial structure "
                               f"(ground truth: {sorted(gp)})")
            elif pp != exp:
                reasons.append(f"{r.is_a()}: contained in {sorted(pp)}, ground truth {sorted(exp)}")
        # (i) opening filling
        if C.is_filling(r):
            gh = C.fill_hosts(r)
            d["gt_fills"] = gh
            if gh:
                ph = C.fill_hosts(p)
                d["pred_fills"] = ph
                exp_hosts = set()
                for _op, hosts in gh:
                    for h in hosts:
                        exp_hosts.add(h if _exists(model_0, h) else gmap.get(h, h))
                pred_hosts = {h for _op, hosts in ph for h in hosts}
                if not ph:
                    reasons.append(f"{r.is_a()}: fills no opening (no IfcRelFillsElement)")
                elif not pred_hosts:
                    reasons.append(f"{r.is_a()}: its opening voids no element (no IfcRelVoidsElement)")
                elif pred_hosts != exp_hosts:
                    reasons.append(f"{r.is_a()}: hosted in {sorted(pred_hosts)}, ground truth {sorted(exp_hosts)}")
        detail.append(d)
    return (not reasons), reasons, detail


def _exists(model, g):
    try:
        model.by_guid(g)
        return True
    except Exception:
        return False


def dangling_check(model_0, model_gt, model_pred, record):
    """New dangling relationships / orphan openings relative to the source."""
    if _W.get("src_dangling") is None:
        _W["src_dangling"] = C.dangling_relations(model_0)
        _W["src_orphans"] = C.orphan_openings(model_0)
    sd, so = _W["src_dangling"], _W["src_orphans"]
    gd, pd = C.dangling_relations(model_gt), C.dangling_relations(model_pred)
    go, po = C.orphan_openings(model_gt), C.orphan_openings(model_pred)
    new_gt = {k: v for k, v in gd.items() if k not in sd}
    new_pred = {k: v for k, v in pd.items() if k not in sd}
    orph_gt = sorted(go - so)
    orph_pred = sorted(po - so)
    # openings tied to a target in the source that the ground truth removed
    targets = set((record.get("target") or {}).get("guids") or ())
    tied = set()
    for g in targets:
        try:
            e = model_0.by_guid(g)
        except Exception:
            continue
        for rel in getattr(e, "HasOpenings", ()) or ():
            if rel.RelatedOpeningElement is not None:
                tied.add(rel.RelatedOpeningElement.GlobalId)
        for rel in getattr(e, "FillsVoids", ()) or ():
            if rel.RelatingOpeningElement is not None:
                tied.add(rel.RelatingOpeningElement.GlobalId)
    left = sorted(g for g in tied if not _exists(model_gt, g) and _exists(model_pred, g))
    return {"new_dangling_gt": new_gt, "new_dangling_pred": new_pred,
            "new_orphan_openings_gt": orph_gt, "new_orphan_openings_pred": orph_pred,
            "openings_left_behind": left}


def abs_errors(pairs, model_gt, model_pred, cfg):
    from modifc_score import geometry as geo
    from modifc_score import scorer
    sg, sp = C.unit_scale(model_gt), C.unit_scale(model_pred)
    rows = []
    for r, p, how in pairs:
        if p is None:
            continue
        mr = geo.build_mesh(r, 0.001, False)
        mp = geo.build_mesh(p, 0.001, False)
        a, b = C.mesh_stats(mr), C.mesh_stats(mp)
        row = {"gt_guid": r.GlobalId, "pred_guid": p.GlobalId, "class": r.is_a(),
               "pairing": how}
        if a is None or b is None:
            row["mesh_missing"] = True
            rows.append(row)
            continue
        ca, cb = np.array(a["centre"]), np.array(b["centre"])
        row["pos_err_m"] = float(np.linalg.norm(cb - ca))
        row["pos_err_xy_m"] = float(np.linalg.norm((cb - ca)[:2]))
        row["pos_err_z_m"] = float(abs((cb - ca)[2]))
        pa, pb = C.placement_world_m(r, sg), C.placement_world_m(p, sp)
        if pa is not None and pb is not None:
            row["placement_err_m"] = float(np.linalg.norm(pb - pa))
        names = C.dim_names(r.is_a())
        errs = {}
        for key, nm in zip(("L", "W", "H"), names):
            errs[nm] = float(abs(b[key] - a[key]))
            row[f"gt_{nm}_m"] = a[key]
        row["dim_err_m"] = errs
        row["dim_err_max_m"] = max(errs.values())
        value, det = scorer._pooled_geometry([mr], [mp], cfg)
        row["checker_geometry"] = value
        row["checker_cd_m"] = det.get("cd")
        row["checker_diag_m"] = det.get("bbox_diag")
        rows.append(row)
    return rows


def process(record, row, pred_path, gold_dir):
    from stage_a.scoring import scorer_config_for
    out = {"task_id": record["task_id"], "operation": record["operation"],
           "edit_kind": record["edit_kind"], "target_class": record["target"]["entity_type"],
           "completed": C.completed(row), "score": row.get("score"),
           "clarification": bool(record.get("clarification"))}
    if record.get("clarification"):
        out["gate"] = "n/a (clarification task)"
        out["gate_pass"] = True
        return out
    if pred_path is None:
        out["gate"] = "no edited model"
        out["gate_pass"] = False
        return out
    gold = C.unpack_gold(record, gold_dir)
    try:
        m0 = _source(record)
        mg = _open(gold)
        mp = _open(pred_path)
        cfg = scorer_config_for(record)
        dang = dangling_check(m0, mg, mp, record)
        out["dangling"] = dang
        if record["operation"] == "delete":
            new_gt = sorted(dang["new_dangling_gt"].values())
            new_pred = sorted(dang["new_dangling_pred"].values())
            extra = list(new_pred)
            for v in new_gt:
                if v in extra:
                    extra.remove(v)
            extra_orph = [o for o in dang["new_orphan_openings_pred"]]
            reasons = []
            if extra:
                reasons.append(f"new dangling relationship(s): {extra}")
            if len(extra_orph) > len(dang["new_orphan_openings_gt"]):
                reasons.append(f"orphan opening(s) voiding nothing: {extra_orph}")
            out["gate_pass"] = not reasons
            out["gate_reasons"] = reasons
            strict = list(reasons)
            if dang["openings_left_behind"]:
                strict.append(f"opening(s) the ground truth removed left in place: "
                              f"{dang['openings_left_behind']}")
            out["gate_strict_pass"] = not strict
            out["gate_strict_reasons"] = strict
        else:
            pairs = pair_targets(record, m0, mg, mp)
            ok, reasons, detail = gate_nondelete(pairs, m0)
            out["gate_pass"] = ok
            out["gate_reasons"] = reasons
            out["gate_detail"] = detail
            out["gate_strict_pass"] = ok
            out["gate_strict_reasons"] = reasons
            out["abs"] = abs_errors(pairs, mg, mp, cfg)
    finally:
        try:
            gold.unlink()
        except FileNotFoundError:
            pass
    return out


def _work(args):
    record, row, pred = args
    gold_dir = C.TMP / f"gold_w{os.getpid()}"
    t0 = time.time()
    try:
        out = process(record, row, Path(pred) if pred else None, gold_dir)
    except Exception as exc:  # noqa: BLE001
        out = {"task_id": record["task_id"], "error": f"{type(exc).__name__}: {exc}"[:400],
               "trace": traceback.format_exc()[-1500:], "completed": C.completed(row)}
    out["seconds"] = round(time.time() - t0, 1)
    if pred and _W.get("delete_after"):
        try:
            Path(pred).unlink()
        except FileNotFoundError:
            pass
    return out


def _init(delete_after=False):
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    _W["delete_after"] = delete_after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arm")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--completed-only", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--ids", default="")
    ap.add_argument("--v4d-out", default="")
    ap.add_argument("--archive", default="edited.tar.gz",
                    help="with --v4d-out: archive in <run>/<model>/ to unpack the listed tasks from "
                         "(v4e recompute: edited_v4e.tar.gz)")
    ap.add_argument("--min-free-gb", type=float, default=15.0)
    args = ap.parse_args()
    v4d = bool(args.v4d_out)
    if v4d and not args.ids:
        sys.exit("--v4d-out needs --ids")
    import multiprocessing as mp
    tasks = C.load_tasks()
    rows = C.per_task_rows(args.arm)
    ids = sorted(rows)
    if args.ids:
        ids = [i for i in args.ids.split(",") if i]
    if args.completed_only:
        ids = [i for i in ids if C.completed(rows[i])]
    # group by source model so a worker reuses the parsed source
    ids.sort(key=lambda i: (tasks[i]["input_ifc"], i))
    if args.limit:
        ids = ids[:args.limit]
    out_path = Path(args.v4d_out) if v4d else C.OUT / f"gate_{args.arm}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["task_id"] for l in open(out_path) if l.strip()}
    ids = [i for i in ids if i not in done]
    print(f"{time.strftime('%F %T')} {args.arm}: {len(ids)} tasks to do", flush=True)
    streaming = args.arm == "veribim9b_2100" and not v4d
    ctx = mp.get_context("spawn")
    with open(out_path, "a") as fo:
        if not streaming:
            if v4d:
                on_disk = {i for i in ids if rows[i].get("edited_ifc") and Path(rows[i]["edited_ifc"]).is_file()}
                rest = [i for i in ids if i not in on_disk]
                root = C.extract_arm(args.arm, rest, min_free_gb=args.min_free_gb, archive=args.archive) if rest else C.TMP / args.arm
                print(f"{len(on_disk)} edited models read in place, {len(rest)} from the archive", flush=True)
            else:
                root = C.extract_arm(args.arm, ids)
            payload = []
            for i in ids:
                p = C.edited_file(root, rows[i], args.arm, on_disk_first=v4d)
                payload.append((tasks[i], rows[i], str(p) if p else None))
            with ctx.Pool(args.workers, initializer=_init) as pool:
                for n, res in enumerate(pool.imap_unordered(_work, payload, chunksize=2), 1):
                    fo.write(json.dumps(res) + "\n")
                    fo.flush()
                    if n % 20 == 0:
                        print(f"{time.strftime('%F %T')} {n}/{len(payload)}", flush=True)
            if root.is_relative_to(C.TMP):
                C.remove_arm(args.arm)
        else:
            want = set(ids)
            dest = C.TMP / args.arm
            dest.mkdir(parents=True, exist_ok=True)
            tar = C.edited_dir(args.arm) / "edited.tar.gz"
            q: queue.Queue = queue.Queue(maxsize=16)

            def feeder():
                with tarfile.open(tar, "r|gz") as tf:
                    for m in tf:
                        if not m.isfile():
                            continue
                        parts = Path(m.name).parts
                        if len(parts) < 3 or parts[1] not in want:
                            continue
                        target = dest / parts[1] / parts[-1]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tf.extractfile(m) as s, open(target, "wb") as d:
                            import shutil
                            shutil.copyfileobj(s, d, 1 << 20)
                        q.put((tasks[parts[1]], rows[parts[1]], str(target)))
                q.put(None)
            th = threading.Thread(target=feeder, daemon=True)
            th.start()

            slots = threading.Semaphore(8)

            def gen():
                while True:
                    slots.acquire()
                    item = q.get()
                    if item is None:
                        return
                    yield item
            seen = 0
            with ctx.Pool(args.workers, initializer=_init, initargs=(True,)) as pool:
                for res in pool.imap_unordered(_work, gen(), chunksize=1):
                    slots.release()
                    seen += 1
                    fo.write(json.dumps(res) + "\n")
                    fo.flush()
                    if seen % 50 == 0:
                        print(f"{time.strftime('%F %T')} {seen}/{len(want)}", flush=True)
            th.join()
            # tasks with no edited file in the archive
            for i in sorted(want):
                if not (dest / i).exists():
                    res = _work((tasks[i], rows[i], None))
                    fo.write(json.dumps(res) + "\n")
            import shutil
            shutil.rmtree(dest, ignore_errors=False)
    print(f"{time.strftime('%F %T')} {args.arm}: done", flush=True)


if __name__ == "__main__":
    main()
