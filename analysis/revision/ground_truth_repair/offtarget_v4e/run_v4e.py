"""Driver of the v4e off-target recompute (2026-10-16).

For every folder in FOLDERS: prepare_v4e.py (plan), then each planned task in its own invocation of
gt_fix/offtarget_subset.py (the v4d subset copy of code/stage_c/offtarget.py, unchanged) with one
worker, so only one edited model and one ground truth per slot are on disk at a time:
  * the edited model is streamed out of the archive the plan names into
    gt_fix/offtarget_tmp_v4e/s<slot>/edited/<task>/<file> and passed through --edited-map
    (the row records the final per-task edited_ifc);
  * for the repaired tasks the ground truth is unpacked from checker_validity/gold_v4d/<task>.ifc.gz
    (built through resolve_gold and checked against tasks.v4d.jsonl) into a per-slot --gold-lookup
    directory searched before runs_local/bench_v4/_gold_cache; the tool checks its sha256 against the
    task record again (gold_source "lookup_sha256").
Both are deleted after the task. Rows go to offtarget_v4e/<run>__<model>/rows_<list>_s<slot>/.
Concurrency: the number in offtarget_v4e/SLOTS (1 or 2), re-read before every launch; slot 0 runs on
core 22, slot 1 on core 23. Waits while the disk has less than 29 GiB free.
"""
import gzip, json, os, shutil, subprocess, sys, tarfile, time
from pathlib import Path

ROOT = Path(".")
R = ROOT / "runs_local/bench_v4/results"
G = ROOT / "analysis/revision/ground_truth_repair"
D = G / "offtarget_v4e"
TMP = G / "offtarget_tmp_v4e"
GOLD_V4D = ROOT / "analysis/revision/checker_validity/gold_v4d"
PY = "python"
LOG = G / "refresh_v4e.log"
FOLDERS = ["full_all:grpo_v10b_c10", "hosted108_lib_all:claude-sonnet-5-5", "hosted108_lib_all:deepseek-v4-pro",
           "hosted108_lib_all:gemini-3.8-flash", "full_all:sft_v10", "full_all:dpo_v10_c6",
           "full_all:grpo_v10_c50", "full_all:dpo_v9_c10", "full_all:sft_small", "full_all:dpo_v10_c3"]
ENV = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
           PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
           PYTHONPATH="code:code/harness")


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%F %T')} [B] {msg}\n")


def free_gib():
    st = os.statvfs("/")
    return st.f_bavail * st.f_frsize / 2**30


def slots():
    try:
        return max(1, min(2, int((D / "SLOTS").read_text().strip())))
    except Exception:
        return 1


def extract(archive, member, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r|gz") as tf:
        for m in tf:
            if m.name == member and m.isfile():
                part = target.with_suffix(".ifc.part")
                with tf.extractfile(m) as s, open(part, "wb") as d:
                    shutil.copyfileobj(s, d, 1 << 20)
                part.rename(target)
                return True
    return False


def main():
    log(f"driver start pid {os.getpid()}")
    jobs = []
    for f in FOLDERS:
        run, model = f.split(":")
        F = D / f"{run}__{model}"
        if not (F / "plan.json").is_file():
            cmd = ["taskset", "-c", "22", PY, str(D / "prepare_v4e.py"), run, model, "--controls", "1"]
            log("RUN " + " ".join(cmd))
            r = subprocess.run(cmd, env=ENV, capture_output=True, text=True)
            log(f"END prepare {run}/{model} rc={r.returncode} {r.stdout.strip()} {r.stderr.strip()[-400:]}")
            if r.returncode:
                sys.exit(1)
        plan = json.loads((F / "plan.json").read_text())
        ed = json.loads((R / run / f"offtarget_{model}" / "offtarget_summary.json").read_text())["edited_dir"]
        for t, it in plan["items"].items():
            jobs.append((run, model, t, it, ed))
    done_marker = lambda run, model, t: D / f"{run}__{model}" / "jobs" / f"{t}.done"
    jobs = [j for j in jobs if not done_marker(*j[:3]).exists()]
    log(f"{len(jobs)} jobs to run")
    running = {}  # slot -> (Popen, job, started)
    started_all = time.time()
    n_done = 0
    while jobs or running:
        for s, (p, job, t0) in list(running.items()):
            rc = p.poll()
            if rc is None:
                continue
            run, model, t, it, _ = job
            shutil.rmtree(TMP / f"s{s}", ignore_errors=True)
            n_done += 1
            log(f"END {run}/{model} {t} ({it['list']}) slot {s} rc={rc} {time.time() - t0:.0f}s "
                f"[{n_done} done, {len(jobs)} queued, free {free_gib():.1f} GiB]")
            if rc == 0:
                done_marker(run, model, t).touch()
            del running[s]
        free_slots = [s for s in range(slots()) if s not in running]
        if jobs and free_slots:
            if free_gib() < 29:
                log(f"disk {free_gib():.1f} GiB free < 29; waiting")
                time.sleep(60)
                continue
            s = free_slots[0]
            run, model, t, it, ed = job = jobs.pop(0)
            F = D / f"{run}__{model}"
            (F / "jobs").mkdir(exist_ok=True)
            base = TMP / f"s{s}"
            shutil.rmtree(base, ignore_errors=True)
            (base / "goldlookup").mkdir(parents=True)
            emap = {}
            if "archive" in it:
                target = base / "edited" / t / Path(it["member"]).name
                if not extract(it["archive"], it["member"], target):
                    log(f"MISSING {it['member']} in {it['archive']}; job skipped")
                    continue
                emap[t] = {"read": str(target), "record": it["record"]}
                if it["repaired_gold"]:
                    with gzip.open(GOLD_V4D / f"{t}.ifc.gz", "rb") as fi, \
                            open(base / "goldlookup" / it["gold_name"], "wb") as fo:
                        shutil.copyfileobj(fi, fo, 1 << 20)
            (F / "jobs" / f"{t}.only").write_text(t + "\n")
            (F / "jobs" / f"{t}.map.json").write_text(json.dumps(emap, indent=1))
            cmd = ["taskset", "-c", str(22 + s), PY, str(G / "offtarget_subset.py"),
                   "--per-task", str(R / run / f"per_task_{model}.jsonl"),
                   "--tasks", str(ROOT / "runs_local/bench_v4/tasks.v4d.jsonl"),
                   "--edited-dir", ed, "--out-dir", str(F / f"rows_{it['list']}_s{s}"), "--workers", "1",
                   "--gold-cache", str(base / "goldcache"),
                   "--gold-lookup", str(base / "goldlookup"),
                   "--gold-lookup", str(ROOT / "runs_local/bench_v4/_gold_cache"),
                   "--only-tasks", str(F / "jobs" / f"{t}.only"),
                   "--edited-map", str(F / "jobs" / f"{t}.map.json")]
            log(f"RUN slot {s}: " + " ".join(cmd))
            out = open(F / "jobs" / f"{t}.out", "w")
            running[s] = (subprocess.Popen(cmd, env=ENV, stdout=out, stderr=subprocess.STDOUT,
                                           cwd=str(ROOT)), job, time.time())
            continue
        time.sleep(3)
    log(f"driver done in {time.time() - started_all:.0f}s")
    (D / "ALL_DONE").touch()


if __name__ == "__main__":
    main()
