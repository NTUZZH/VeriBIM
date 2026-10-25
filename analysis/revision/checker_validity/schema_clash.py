"""Analysis 3: schema validation and hard-clash counts, source vs ground truth vs output.

For every task of an arm: ifcopenshell.validate.validate (attribute types and
cardinalities, inverse cardinalities, GlobalId format and uniqueness, abstract
entities, header; with express_rules=True also the schema's global rules, type
where-rules and entity where-rules), on the source model, the ground truth and
the edited model; and hard clashes (clashlib.py) between the edited elements
and every other element near them.  Source results are cached per source file
and ground-truth results per task, under results/cache/.

Writes results/schema_clash_<arm>.jsonl.
Usage: python schema_clash.py <arm> [--workers 4] [--ids a,b] [--sample N --seed S]
       [--no-validate] [--no-clash] [--no-express]
       [--v4d-out tmp/<file>.jsonl]   (with --ids: v4d recompute of the listed rows, written to the given
       file; edited models read in place when on disk, the rest unpacked for the listed tasks only)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import random
import re
import sys
import tarfile
import threading
import queue
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C  # noqa: E402
import clashlib as K  # noqa: E402

CACHE = C.OUT / "cache"
_W: dict = {}

_INST = re.compile(r"#\d+=(Ifc\w+)\('([0-9A-Za-z_$]{22})'")
_INST_NOGUID = re.compile(r"#\d+=(Ifc\w+)\(")
_RULE = re.compile(r"Rule ([\w.]+):")


def _norm(st: dict) -> dict:
    msg = str(st.get("message", ""))
    typ = st.get("type") or "schema"
    inst = st.get("instance")
    cls = gid = None
    if inst is not None and hasattr(inst, "is_a"):
        try:
            cls = inst.is_a()
            gid = getattr(inst, "GlobalId", None)
        except Exception:
            pass
    if cls is None:
        m = _INST.search(msg)
        if m:
            cls, gid = m.group(1), m.group(2)
        else:
            m = _INST_NOGUID.search(msg)
            if m:
                cls = m.group(1)
    if typ == "schema":
        rule = st.get("attribute") or ""
        first = re.sub(r"#\d+", "#", msg.split("\n")[0])[:160]
        if first.startswith("On instance") or first.startswith("For instance"):
            # text logger style; keep the rule line
            lines = [l for l in msg.split("\n") if l and not l.startswith(" ")]
            first = re.sub(r"#\d+", "#", " | ".join(lines[1:3]))[:160]
        what = first
    else:
        m = _RULE.search(msg)
        rule = m.group(1) if m else (st.get("attribute") or "")
        what = rule
    return {"level": st.get("level"), "type": typ, "rule": rule, "what": what,
            "cls": cls, "guid": gid}


def validate_file(path: Path, express: bool) -> dict:
    import ifcopenshell
    import ifcopenshell.validate as V
    t0 = time.time()
    logger = V.json_logger()
    err = None
    try:
        V.validate(str(path), logger, express_rules=express)
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"[:300]
    items = [_norm(s) for s in logger.statements if s.get("level") in ("error", "warning")]
    return {"items": items, "seconds": round(time.time() - t0, 1), "error": err,
            "express": express}


def _key(it):
    return (it["type"], it["rule"], it["what"], it["cls"], it["guid"])


def new_items(base: list, other: list) -> list:
    cnt = collections.Counter(_key(i) for i in base)
    out = []
    for i in other:
        k = _key(i)
        if cnt[k] > 0:
            cnt[k] -= 1
        else:
            out.append(i)
    return out


def _cache_json(name: str, fn):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / name
    if p.exists():
        try:
            return json.load(open(p))
        except Exception:
            pass
    val = fn()
    tmp = p.with_suffix(".tmp%d" % os.getpid())
    json.dump(val, open(tmp, "w"))
    os.replace(tmp, p)
    return val


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()[:16]


def _src(record):
    import ifcopenshell
    p = str(C.source_path(record))
    if _W.get("src_path") != p:
        _W["src"] = None
        _W["src"] = ifcopenshell.open(p)
        _W["src_path"] = p
        _W["src_sha"] = _sha(Path(p))
        _W["src_guids"] = {e.GlobalId for e in _W["src"].by_type("IfcRoot")}
    return _W["src"]


def edited_elements(model, src_guids, target_guids):
    out = list(target_guids)
    for cls in ("IfcElement", "IfcSpace"):
        for e in model.by_type(cls):
            if e.GlobalId not in src_guids and not any(e.is_a(c) for c in K.EXCLUDE_OTHER):
                if e.GlobalId not in out:
                    out.append(e.GlobalId)
    return out


def clash_block(record, m0, mg, mp, pairs):
    """Clashes of the edited elements in source, ground truth and output, and the new ones."""
    sg = _W["src_guids"]
    index = _cache_json(f"aabb_{_W['src_sha']}.json", lambda: K.source_index(m0))
    targets = list((record.get("target") or {}).get("guids") or ())
    out = {}
    # source: the targets as they stood before the edit (update/delete)
    src_t = [g for g in targets if g in sg]
    rows0, _ = K.clashes_in_file(m0, src_t, index, sg)
    out["source"] = rows0
    gt_set = edited_elements(mg, sg, [g for g in targets if C.guid(_safe(mg, g))])
    rows_g, info_g = K.clashes_in_file(mg, gt_set, index, sg)
    out["gt"], out["gt_info"] = rows_g, info_g
    pred_t = [p.GlobalId for _r, p, _h in pairs if p is not None] if pairs else \
        [g for g in targets if C.guid(_safe(mp, g))]
    pr_set = edited_elements(mp, sg, pred_t)
    rows_p, info_p = K.clashes_in_file(mp, pr_set, index, sg)
    out["pred"], out["pred_info"] = rows_p, info_p
    before = {(r["target"], r["other"]) for r in rows0 if not r["excluded"]}
    before |= {(b, a) for a, b in before}

    def new(rows):
        seen, res = set(), []
        for r in rows:
            if r["excluded"]:
                continue
            k = tuple(sorted((r["target"], r["other"])))
            if (r["target"], r["other"]) in before or k in seen:
                continue
            seen.add(k)
            res.append(r)
        return res
    out["new_gt"] = new(rows_g)
    out["new_pred"] = new(rows_p)
    return out


def _safe(model, g):
    try:
        return model.by_guid(g)
    except Exception:
        return None


def process(record, row, pred_path, args):
    import ifcopenshell
    import gate_abs as G
    out = {"task_id": record["task_id"], "operation": record["operation"],
           "edit_kind": record["edit_kind"], "target_class": record["target"]["entity_type"],
           "completed": C.completed(row), "clarification": bool(record.get("clarification")),
           "has_output": pred_path is not None}
    gold_dir = C.TMP / f"sc_gold_w{os.getpid()}"
    gold = C.unpack_gold(record, gold_dir)
    try:
        m0 = _src(record)
        express = not args.no_express
        if not args.no_validate:
            tag = "x" if express else "s"
            vs = _cache_json(f"val{tag}_src_{_W['src_sha']}.json",
                             lambda: validate_file(C.source_path(record), express))
            vg = _cache_json(f"val{tag}_gt_{record['task_id']}.json",
                             lambda: validate_file(gold, express))
            out["val_src_n"] = len(vs["items"])
            out["val_gt_n"] = len(vg["items"])
            out["val_src_seconds"], out["val_gt_seconds"] = vs["seconds"], vg["seconds"]
            ng = new_items(vs["items"], vg["items"])
            out["val_new_gt"] = ng
            if pred_path is not None:
                vp = validate_file(pred_path, express)
                out["val_pred_n"] = len(vp["items"])
                out["val_pred_seconds"] = vp["seconds"]
                out["val_pred_error"] = vp["error"]
                out["val_new_pred"] = new_items(vs["items"], vp["items"])
        if not args.no_clash and pred_path is not None and not record.get("clarification"):
            mg = ifcopenshell.open(str(gold))
            mp = ifcopenshell.open(str(pred_path))
            pairs = None
            if record["operation"] != "delete":
                pairs = G.pair_targets(record, m0, mg, mp)
            out["clash"] = clash_block(record, m0, mg, mp, pairs)
        elif not args.no_clash and pred_path is None and not record.get("clarification"):
            out["clash"] = None
    finally:
        gold.unlink(missing_ok=True)
    return out


def _work(item):
    record, row, pred, args = item
    t0 = time.time()
    try:
        out = process(record, row, Path(pred) if pred else None, args)
    except Exception as exc:  # noqa: BLE001
        out = {"task_id": record["task_id"], "error": f"{type(exc).__name__}: {exc}"[:400],
               "trace": traceback.format_exc()[-2000:]}
    out["seconds"] = round(time.time() - t0, 1)
    if pred and _W.get("delete_after"):
        Path(pred).unlink(missing_ok=True)
    return out


def _init(delete_after=False):
    for k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[k] = "1"
    _W["delete_after"] = delete_after


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arm")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--ids", default="")
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=20261015)
    ap.add_argument("--take", type=int, default=0)
    ap.add_argument("--no-validate", action="store_true")
    ap.add_argument("--no-clash", action="store_true")
    ap.add_argument("--no-express", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--max-src-mb", type=float, default=0.0,
                    help="leave out tasks whose source model is larger than this (0: no cap)")
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
    if args.sample:
        ids = random.Random(args.seed).sample(ids, args.sample)
        if args.take:
            ids = ids[:args.take]   # the first draws of the seeded sample
        ids = sorted(ids)
    if args.ids:
        ids = [i for i in args.ids.split(",") if i]
    if args.max_src_mb:
        big = [i for i in ids if C.source_path(tasks[i]).stat().st_size > args.max_src_mb * 1e6]
        print(f"{len(big)} tasks left out: source model > {args.max_src_mb} MB", flush=True)
        ids = [i for i in ids if i not in set(big)]
    ids.sort(key=lambda i: (tasks[i]["input_ifc"], i))
    out_path = Path(args.v4d_out) if v4d else C.OUT / f"schema_clash_{args.arm}{args.tag}.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(l)["task_id"] for l in open(out_path) if l.strip()}
    ids = [i for i in ids if i not in done]
    print(f"{time.strftime('%F %T')} {args.arm}: {len(ids)} tasks", flush=True)
    ctx = mp.get_context("spawn")
    streaming = args.arm == "veribim9b_2100" and not v4d
    with open(out_path, "a") as fo:
        if not streaming:
            if v4d:
                on_disk = {i for i in ids if rows[i].get("edited_ifc") and Path(rows[i]["edited_ifc"]).is_file()}
                rest = [i for i in ids if i not in on_disk]
                root = C.extract_arm(args.arm, rest, min_free_gb=args.min_free_gb, archive=args.archive) if rest else C.TMP / args.arm
                print(f"{len(on_disk)} edited models read in place, {len(rest)} from the archive", flush=True)
            else:
                root = C.extract_arm(args.arm, ids)
            payload = [(tasks[i], rows[i], (str(p) if (p := C.edited_file(root, rows[i], args.arm, on_disk_first=v4d)) else None), args)
                       for i in ids]
            with ctx.Pool(args.workers, initializer=_init) as pool:
                for n, res in enumerate(pool.imap_unordered(_work, payload, chunksize=1), 1):
                    fo.write(json.dumps(res, default=str) + "\n")
                    fo.flush()
                    if n % 10 == 0:
                        print(f"{time.strftime('%F %T')} {n}/{len(payload)}", flush=True)
            if root.is_relative_to(C.TMP):
                C.remove_arm(args.arm)
        else:
            want = set(ids)
            dest = C.TMP / args.arm
            dest.mkdir(parents=True, exist_ok=True)
            tar = C.edited_dir(args.arm) / "edited.tar.gz"
            q: queue.Queue = queue.Queue()
            slots = threading.Semaphore(3)
            got = set()

            def feeder():
                import shutil
                with tarfile.open(tar, "r|gz") as tf:
                    for m in tf:
                        parts = Path(m.name).parts
                        if not m.isfile() or len(parts) < 3 or parts[1] not in want:
                            continue
                        slots.acquire()
                        target = dest / parts[1] / parts[-1]
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tf.extractfile(m) as s, open(target, "wb") as d:
                            shutil.copyfileobj(s, d, 1 << 20)
                        got.add(parts[1])
                        q.put((tasks[parts[1]], rows[parts[1]], str(target), args))
                q.put(None)
            th = threading.Thread(target=feeder, daemon=True)
            th.start()

            def gen():
                while True:
                    item = q.get()
                    if item is None:
                        return
                    yield item
            with ctx.Pool(args.workers, initializer=_init, initargs=(True,)) as pool:
                for n, res in enumerate(pool.imap_unordered(_work, gen(), chunksize=1), 1):
                    slots.release()
                    fo.write(json.dumps(res, default=str) + "\n")
                    fo.flush()
                    if n % 10 == 0:
                        print(f"{time.strftime('%F %T')} {n}/{len(want)}", flush=True)
            th.join()
            for i in sorted(want - got):
                res = _work((tasks[i], rows[i], None, args))
                fo.write(json.dumps(res, default=str) + "\n")
            import shutil
            shutil.rmtree(dest)
    print(f"{time.strftime('%F %T')} {args.arm}: done", flush=True)


if __name__ == "__main__":
    main()
