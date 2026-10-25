"""Ground truths of the 69 tasks repaired on 2026-10-15 (gt_fix/affected_tasks.txt), for the v4d recompute.

Each is resolved through stage_a.goldmodels.resolve_gold with its tasks.v4d.jsonl record and a private
one-file GoldCache (tmp/gold_v4d_cache), as every run does: the gold script is re-executed with the
installed library and checked against the record's gold_sha256. The verified file is stored gzipped as
gold_v4d/<task_id>.ifc.gz, where common.gold_archive looks first; common.unpack_gold checks the
checksum again on every read. Writes gold_v4d/build_log.jsonl. One process, one model at a time.
"""
import gzip, hashlib, json, os, resource, shutil, sys, time
from pathlib import Path
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "code"))
from stage_a import goldmodels  # noqa: E402
ids = [l.strip() for l in open(ROOT / "analysis/revision/ground_truth_repair/affected_tasks.txt") if l.strip()]
recs = {}
for l in open(ROOT / "runs_local/bench_v4/tasks.v4d.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r["task_id"] in ids:
        recs[r["task_id"]] = r
OUTD = HERE / "gold_v4d"
OUTD.mkdir(exist_ok=True)
logp = OUTD / "build_log.jsonl"
cache = goldmodels.open_cache(HERE / "tmp/gold_v4d_cache", max_files=1)
for tid in ids:
    dst = OUTD / f"{tid}.ifc.gz"
    if dst.exists():
        continue
    t0 = time.perf_counter()
    path = goldmodels.resolve_gold(recs[tid], cache)
    row = {"task_id": tid, "resolved": path is not None,
           "failures": [f.reason for f in cache.failures if f.task_id == tid]}
    if path is not None:
        h = hashlib.sha256()
        with open(path, "rb") as fi:
            for b in iter(lambda: fi.read(1 << 20), b""):
                h.update(b)
        row["sha256"] = h.hexdigest()
        row["matches_v4d"] = row["sha256"] == recs[tid]["verification"]["gold_sha256"]
        if row["matches_v4d"]:
            tmp = dst.with_suffix(".gz.part")
            with open(path, "rb") as fi, gzip.open(tmp, "wb", compresslevel=6) as fo:
                shutil.copyfileobj(fi, fo, 1 << 20)
            os.replace(tmp, dst)
    row["seconds"] = round(time.perf_counter() - t0, 1)
    row["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    cache.clear()
    with open(logp, "a") as f:
        f.write(json.dumps(row) + "\n")
    print(json.dumps(row), flush=True)
print("GOLD_V4D DONE", flush=True)
