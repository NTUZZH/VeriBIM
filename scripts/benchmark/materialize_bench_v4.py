"""Rebuild every gold model of VeriBIM-Bench v4 with modifc_gen.materialize.rebuild (checksum-checked), check that no
created door/window carries a PredefinedType the instruction does not state, and store the model gzip-compressed
(models/<task_id>.ifc.gz; the uncompressed set is 46 GB against 50 GB free on the disk).  The sha256 of the
uncompressed bytes is computed while compressing and compared with verification.gold_sha256.  Resumable via the
journal.  3 workers, cores 0-9."""
import gc, gzip, hashlib, json, os, sys, time
from pathlib import Path
import multiprocessing as mp

ROOT = Path(".")
OUT = ROOT / "runs_local/bench_v4"
MODELS = OUT / "models"
JOURNAL = OUT / "work/materialize.journal.jsonl"
WORKERS = 3


def init():
    for n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[n] = "1"
    os.sched_setaffinity(0, set(range(10)))


def door_window_task(t):
    k = t.get("edit_kind", "")
    return t.get("family") in ("door", "window") or "filling" in k or "door" in k or "window" in k


def one(t):
    from modifc_gen import materialize
    tid = t["task_id"]
    ifc = MODELS / f"{tid}.ifc"
    gz = MODELS / f"{tid}.ifc.gz"
    out = {"task_id": tid, "ifc_version": t["ifc_version"]}
    r = materialize.rebuild(t, ROOT, ifc, True)
    out.update(ok=r.ok, check=r.check, bytes=r.bytes, seconds=round(r.seconds, 1), reason=r.reason)
    if not r.ok:
        return out
    # created door/window PredefinedType check on the gold model itself
    created = list((t.get("edit_guids") or {}).get("created") or ())
    if created and door_window_task(t) and t["ifc_version"] != "IFC2X3":
        import ifcopenshell
        f = ifcopenshell.open(str(ifc))
        found = []
        for g in created:
            try:
                e = f.by_guid(g)
            except Exception:
                continue
            if e.is_a("IfcDoor") or e.is_a("IfcWindow"):
                pt = getattr(e, "PredefinedType", None)
                found.append([e.is_a(), pt])
                if pt is not None and pt not in (t.get("instruction") or ""):
                    out["unstated_predefined_type"] = [e.is_a(), g, pt]
        out["created_fillings"] = found
        del f
        gc.collect()
    h = hashlib.sha256()
    tmp = MODELS / f".{tid}.ifc.gz.tmp"
    with open(ifc, "rb") as a, gzip.open(tmp, "wb", compresslevel=6) as b:
        while True:
            chunk = a.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
            b.write(chunk)
    os.replace(tmp, gz)
    os.remove(ifc)
    out["gold_sha256_rebuilt"] = h.hexdigest()
    out["sha_match"] = h.hexdigest() == (t.get("verification") or {}).get("gold_sha256")
    out["gz_bytes"] = os.path.getsize(gz)
    return out


def main():
    MODELS.mkdir(parents=True, exist_ok=True)
    done = set()
    if JOURNAL.exists():
        for l in open(JOURNAL):
            d = json.loads(l)
            if d.get("ok") and (MODELS / f"{d['task_id']}.ifc.gz").exists():
                done.add(d["task_id"])
    tasks = [json.loads(l) for l in open(OUT / "tasks.jsonl") if l.strip()]
    todo = [t for t in tasks if t["task_id"] not in done]
    todo.sort(key=lambda t: -os.path.getsize(ROOT / t["input_ifc"]))
    print(f"{len(tasks)} tasks, {len(done)} done, {len(todo)} to build", flush=True)
    t0 = time.time()
    with mp.get_context("fork").Pool(WORKERS, initializer=init, maxtasksperchild=20) as pool, open(JOURNAL, "a") as j:
        for i, o in enumerate(pool.imap_unordered(one, todo, 1), 1):
            j.write(json.dumps(o) + "\n"); j.flush()
            if i % 50 == 0 or i == len(todo) or not o.get("ok"):
                print(f"{i}/{len(todo)} {time.time()-t0:.0f}s last={o['task_id']} ok={o.get('ok')} {o.get('reason','')}", flush=True)
    print("DONE", round(time.time() - t0, 1), flush=True)


if __name__ == "__main__":
    main()
