"""Rebuild the gold model of every hard validation candidate and check its checksum.

Mirrors scripts/benchmark/materialize_bench_v4.py: modifc_gen.materialize.rebuild
runs the gold script on the source model and compares the result with
verification.gold_sha256; the sha256 is computed again on the bytes while they are
gzip-compressed into models/<task_id>.ifc.gz, and the uncompressed file is removed.
Disk floor: when free space falls under FLOOR_GB the run switches to verify-only
(checksum checked and recorded, model deleted); readers rebuild golds from the
script through their gold cache in either case.  Resumable via the journal.
Workers pinned to cores 8-15.
"""
import gc, gzip, hashlib, json, os, shutil, sys, time
from pathlib import Path
import multiprocessing as mp

ROOT = Path(".")
VH = ROOT / "runs_local/stage_b_v10/val_hard"
MODELS = VH / "models"
JOURNAL = VH / "work/materialize.journal.jsonl"
WORKERS = int(os.environ.get("MAT_WORKERS", "4"))
FLOOR_GB = 32


def init():
    for n in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[n] = "1"
    os.sched_setaffinity(0, set(range(8, 16)))


def free_gb():
    return shutil.disk_usage(str(ROOT)).free / 1024 ** 3


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
        if ifc.exists():
            os.remove(ifc)
        return out
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
    keep = free_gb() >= FLOOR_GB
    tmp = MODELS / f".{tid}.ifc.gz.tmp"
    if keep:
        with open(ifc, "rb") as a, gzip.open(tmp, "wb", compresslevel=6) as b:
            while True:
                chunk = a.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                b.write(chunk)
        os.replace(tmp, gz)
        out["gz_bytes"] = os.path.getsize(gz)
        out["stored"] = "gz"
    else:
        with open(ifc, "rb") as a:
            while True:
                chunk = a.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
        out["stored"] = "checksum_only"
    os.remove(ifc)
    out["gold_sha256_rebuilt"] = h.hexdigest()
    out["sha_match"] = h.hexdigest() == (t.get("verification") or {}).get("gold_sha256")
    return out


def main():
    MODELS.mkdir(parents=True, exist_ok=True)
    done = set()
    if JOURNAL.exists():
        for l in open(JOURNAL):
            d = json.loads(l)
            if d.get("ok") and (d.get("stored") == "checksum_only" or (MODELS / f"{d['task_id']}.ifc.gz").exists()):
                done.add(d["task_id"])
    tasks = [json.loads(l) for l in open(VH / "candidates_v10.jsonl") if l.strip()]
    todo = [t for t in tasks if t["task_id"] not in done]
    todo.sort(key=lambda t: -os.path.getsize(ROOT / t["input_ifc"]))
    # optional: only sources under MAT_MAX_SRC_MB, smallest first (a low-memory lane
    # while a generator run holds most of the memory allowance)
    cap = float(os.environ.get("MAT_MAX_SRC_MB", "0"))
    if cap:
        todo = [t for t in todo if os.path.getsize(ROOT / t["input_ifc"]) < cap * 1e6][::-1]
    print(f"{len(tasks)} tasks, {len(done)} done, {len(todo)} to build, {free_gb():.1f} GB free", flush=True)
    t0 = time.time()
    with mp.get_context("fork").Pool(WORKERS, initializer=init, maxtasksperchild=20) as pool, open(JOURNAL, "a") as j:
        for i, o in enumerate(pool.imap_unordered(one, todo, 1), 1):
            j.write(json.dumps(o) + "\n"); j.flush()
            if i % 100 == 0 or i == len(todo) or not o.get("ok") or not o.get("sha_match"):
                print(f"{i}/{len(todo)} {time.time()-t0:.0f}s last={o['task_id']} ok={o.get('ok')} "
                      f"sha={o.get('sha_match')} {o.get('stored')} {o.get('reason','')} free={free_gb():.1f}GB", flush=True)
    print("DONE", round(time.time() - t0, 1), flush=True)


if __name__ == "__main__":
    main()
