"""Migrator v2 driver: re-migrate every migrated file of the v10 and benchmark pools, validate outputs (and sources not
yet in validate_schema.jsonl), and compare each output with the old migrated file at product level.

One scheduler process plus at most WORKERS step processes (steps.py), all pinned to cores 5-9, one thread each. A step
starts only when the estimated RSS of all running steps plus its own stays under BUDGET_GB and the host has that much
memory available. Resumable: a step whose output file exists is not run again.
  run_all.py plan     -> writes jobs.json
  run_all.py run [--only KEY,...]
"""
import os, sys, json, time, subprocess, pickle, collections, re, signal
ROOT = "."; HERE = f"{ROOT}/runs_local/corpus_v10/migrator_v2"; C10 = f"{ROOT}/runs_local/corpus_v10"
PY = sys.executable; CORES = "5-9"
WORKERS = 2                 # + this scheduler = 3 processes
BUDGET_GB = 7.4             # all running steps together
F_MIGRATE, F_SINGLE = 30.0, 28.0   # peak RSS per input byte (measured max 27.6 migrate, 26.9 signature)
POOLS = ["pool_v10_IFC4.json", "pool_v10_IFC4X3.json", "pool_v10_IFC4_plus.json", "pool_v10_IFC4X3_plus.json",
         "pool_bench_v10_IFC4.json", "pool_bench_v10_IFC4X3.json"]
LOG = f"{HERE}/run_all.log"


def log(*a):
    line = time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True); open(LOG, "a").write(line + "\n")


def header_schema(path):
    head = open(path, "rb").read(20000).decode("latin1")
    m = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^']+)'", head)
    return m.group(1).upper() if m else "?"


def plan():
    rel = {}
    for fn in POOLS:
        for m in json.load(open(f"{C10}/{fn}"))["models"]:
            if m.get("origin") == "migrated":
                rel.setdefault(m["relpath"], m)
    by_src = collections.defaultdict(dict)
    for r, m in rel.items():
        tgt = "IFC4X3" if r.endswith("__IFC4X3.ifc") else "IFC4"
        assert r.endswith(f"__{tgt}.ifc"), r
        by_src[m["source_relpath"]][tgt] = r
    jobs = []
    for src, outs in by_src.items():
        sch = header_schema(f"{ROOT}/{src}")
        if sch.startswith("IFC2X3"):
            assert set(outs) == {"IFC4", "IFC4X3"}, (src, outs)
            chain = ["IFC4", "IFC4X3"]
        else:
            assert sch.startswith("IFC4") and not sch.startswith("IFC4X3") and set(outs) == {"IFC4X3"}, (src, sch, outs)
            chain = ["IFC4X3"]
        key = os.path.basename(outs["IFC4X3"])[:-len("__IFC4X3.ifc")]
        o = []; prev = src
        for t in chain:
            new = f"runs_local/corpus_v10/migrator_v2/files/{os.path.basename(outs[t])}"
            o.append({"target": t, "old": outs[t], "new": new, "from": prev}); prev = new
        jobs.append({"key": key, "src": src, "schema": sch, "bytes": os.path.getsize(f"{ROOT}/{src}"), "outputs": o})
    jobs.sort(key=lambda j: j["bytes"])
    assert len({j["key"] for j in jobs}) == len(jobs)
    json.dump(jobs, open(f"{HERE}/jobs.json", "w"), indent=1)
    print(len(jobs), "jobs,", sum(len(j["outputs"]) for j in jobs), "outputs")


def source_validated(src):
    """validate_schema.jsonl record of src when complete (kinds not truncated), else None."""
    p = f"{C10}/validate_schema.jsonl"
    for l in open(p):
        try:
            r = json.loads(l)
        except Exception:
            continue
        if r.get("relpath") == src and "n_issues" in r:
            if sum(r["kinds"].values()) == r["n_issues"]:
                return r
    return None


def steps_of(job):
    """Ordered (name, argv, input bytes factor path, output path) of a job; cheap to recompute."""
    w = f"{HERE}/work/{job['key']}"
    st = []
    if source_validated(job["src"]) is None:
        st.append(("validate_source", ["validate", f"{ROOT}/{job['src']}", f"{w}/validate_source.json"],
                   F_SINGLE, f"{ROOT}/{job['src']}", f"{w}/validate_source.json"))
    for o in job["outputs"]:
        t = o["target"]
        st.append((f"migrate_{t}", ["migrate", f"{ROOT}/{o['from']}", t, f"{ROOT}/{o['new']}", f"{w}/migrate_{t}.json"],
                   F_MIGRATE, f"{ROOT}/{o['from']}", f"{w}/migrate_{t}.json"))
    for o in job["outputs"]:
        t = o["target"]
        st.append((f"validate_{t}", ["validate", f"{ROOT}/{o['new']}", f"{w}/validate_{t}.json"],
                   F_SINGLE, f"{ROOT}/{o['new']}", f"{w}/validate_{t}.json"))
        st.append((f"sigold_{t}", ["signature", f"{ROOT}/{o['old']}", f"{w}/sigold_{t}.pkl"],
                   F_SINGLE, f"{ROOT}/{o['old']}", f"{w}/sigold_{t}.pkl"))
        st.append((f"signew_{t}", ["signature", f"{ROOT}/{o['new']}", f"{w}/signew_{t}.pkl"],
                   F_SINGLE, f"{ROOT}/{o['new']}", f"{w}/signew_{t}.pkl"))
    return st


def mem_available_gb():
    for l in open("/proc/meminfo"):
        if l.startswith("MemAvailable"):
            return int(l.split()[1]) / 1e6
    return 0.0


def rss_gb(pid):
    try:
        for l in open(f"/proc/{pid}/status"):
            if l.startswith("VmRSS"):
                return int(l.split()[1]) / 1e6
    except Exception:
        pass
    return 0.0


def run(only=None):
    jobs = json.load(open(f"{HERE}/jobs.json"))
    if only:
        jobs = [j for j in jobs if j["key"] in only]
    env = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
               PYTHONPATH=f"{ROOT}/code:{ROOT}/code/harness")
    queue = collections.deque(jobs)
    active = {}     # key -> dict(job, steps, i, proc, est, name, t0)
    t_start = time.time(); peak_total = 0.0; last_wait = 0
    stats = {"steps_run": 0, "steps_failed": 0}
    while queue or active:
        # finish
        for k in list(active):
            a = active[k]
            if a["proc"] is not None and a["proc"].poll() is not None:
                rc = a["proc"].returncode; name = a["steps"][a["i"]][0]; out = a["steps"][a["i"]][4]
                ok = rc == 0 and os.path.exists(out)
                log(k, name, "rc", rc, "ok" if ok else "FAILED", f"{time.time() - a['t0']:.0f}s")
                stats["steps_run"] += 1
                if not ok:
                    stats["steps_failed"] += 1
                    open(f"{HERE}/work/{k}/FAILED_{name}", "w").write(f"rc={rc}\n")
                    a["i"] = len(a["steps"])  # abandon the job
                else:
                    a["i"] += 1
                a["proc"] = None
        # advance / retire
        for k in list(active):
            a = active[k]
            if a["proc"] is not None:
                continue
            while a["i"] < len(a["steps"]) and os.path.exists(a["steps"][a["i"]][4]):
                a["i"] += 1
            if a["i"] >= len(a["steps"]):
                try:
                    finalize(a["job"])
                except Exception as ex:
                    log(k, "finalize FAILED", repr(ex)[:300])
                del active[k]
        # admit new jobs into free slots (strict FIFO)
        while queue and len(active) < WORKERS:
            j = queue.popleft(); os.makedirs(f"{HERE}/work/{j['key']}", exist_ok=True)
            active[j["key"]] = {"job": j, "steps": steps_of(j), "i": 0, "proc": None, "est": 0.0, "t0": 0}
        # launch steps under the memory budget
        running_est = sum(a["est"] for a in active.values() if a["proc"] is not None)
        for k, a in sorted(active.items(), key=lambda kv: kv[1]["job"]["bytes"]):
            if a["proc"] is not None:
                continue
            while a["i"] < len(a["steps"]) and os.path.exists(a["steps"][a["i"]][4]):
                a["i"] += 1      # finished in an earlier run
            if a["i"] >= len(a["steps"]):
                continue
            name, argv, fac, inp, out = a["steps"][a["i"]]
            if not os.path.exists(inp):
                log(k, name, "input missing", inp); a["i"] = len(a["steps"]); continue
            est = fac * os.path.getsize(inp) / 1e9 + 0.25
            if a.get("alone"):
                est = max(est, BUDGET_GB)
            nrun = sum(1 for x in active.values() if x["proc"] is not None)
            fits = (running_est + est <= BUDGET_GB) or (nrun == 0 and est <= 8.0)
            host_ok = mem_available_gb() >= est + 1.5
            if not (fits and host_ok):
                if time.time() - last_wait > 300:
                    log("waiting:", k, name, f"est {est:.1f} GB, running est {running_est:.1f}, host avail {mem_available_gb():.1f}")
                    last_wait = time.time()
                continue
            cmd = ["taskset", "-c", CORES, PY, "scripts/corpus/migrator_v2/steps.py"] + argv
            a["proc"] = subprocess.Popen(cmd, env=env, stdout=open(f"{HERE}/work/{k}/{name}.log", "w"),
                                         stderr=subprocess.STDOUT)
            a["est"] = est; a["t0"] = time.time(); running_est += est
            log(k, name, "start", f"est {est:.2f} GB")
        tot = sum(rss_gb(a["proc"].pid) for a in active.values() if a["proc"] is not None) + rss_gb(os.getpid())
        if tot > peak_total:
            peak_total = tot
            open(f"{HERE}/peak_rss.txt", "w").write(f"{peak_total:.2f} GB total RSS of scheduler + running steps\n")
        if tot > 7.9:
            # safety valve: stop the youngest step and run it again later on its own
            young = max((a for a in active.values() if a["proc"] is not None), key=lambda a: a["t0"])
            if sum(1 for a in active.values() if a["proc"] is not None) > 1:
                log("RSS", f"{tot:.1f} GB > 7.9: stopping", young["job"]["key"], young["steps"][young["i"]][0])
                young["proc"].send_signal(signal.SIGTERM); young["proc"].wait()
                young["proc"] = None; young["est"] = 0.0; young["alone"] = True
        time.sleep(2)
    json.dump({"wall_seconds": round(time.time() - t_start, 1), "peak_total_rss_gb": round(peak_total, 2), **stats},
              open(f"{HERE}/run_stats_{int(t_start)}.json", "w"))
    log("DONE", f"{time.time() - t_start:.0f}s peak {peak_total:.2f} GB", stats)


# --------------------------------------------------------------- per-job results
FIELDS = ("class", "Name", "placement", "container", "storey", "aggregate_parent", "filling_host", "void_host")


def compare(old, new):
    op, nwp = old["products"], new["products"]
    missing = [g for g in op if g not in nwp]
    added = [g for g in nwp if g not in op]
    added_cls = collections.Counter(nwp[g][0] for g in added)
    diffs = collections.Counter(); ex = {}
    for g, a in op.items():
        b = nwp.get(g)
        if b is None:
            continue
        for i, fname in enumerate(FIELDS):
            if a[i] != b[i]:
                diffs[fname] += 1; ex.setdefault(fname, (g, a[i], b[i]))
    rep = collections.Counter(); rep_ex = {}
    for g, (r0, m0) in old["rep"].items():
        r1, m1 = new["rep"].get(g, (None, None))
        if r0 == r1:
            rep["identical"] += 1
        elif m0 == m1:
            rep["differs_only_in_restored_source_values"] += 1; rep_ex.setdefault("restored", []).append(g)
        else:
            rep["differs"] += 1; rep_ex.setdefault("differs", []).append(g)
    ms = collections.Counter(); ms_ex = []
    for g, s in old["ms_entities"].items():
        if new["ms_entities"].get(g) == s:
            ms["equal"] += 1
        else:
            ms["differ"] += 1; ms_ex.append(g)
    roots_added = len(new["ms_guids"] - old["ms_guids"]); roots_missing = len(old["ms_guids"] - new["ms_guids"])
    counts_delta = {k: new["ms_counts"].get(k, 0) - v for k, v in old["ms_counts"].items() if new["ms_counts"].get(k, 0) != v}
    ok = (not missing and set(added_cls) <= {"IfcVirtualElement"} and not diffs and rep["differs"] == 0
          and ms["differ"] == 0 and roots_missing == 0)
    return {"ok": ok, "n_products_old": len(op), "n_products_new": len(nwp), "missing_products": len(missing),
            "added_products": dict(added_cls), "field_differences": dict(diffs),
            "field_examples": {k: [str(x)[:200] for x in v] for k, v in ex.items()},
            "six_family_products": len(old["rep"]), "representation": dict(rep),
            "representation_examples": {k: v[:5] for k, v in rep_ex.items()},
            "model_signature_entities": dict(ms), "model_signature_differ_examples": ms_ex[:5],
            "roots_added": roots_added, "roots_missing": roots_missing, "topology_counts_delta": counts_delta}


def finalize(job):
    w = f"{HERE}/work/{job['key']}"
    if os.path.exists(f"{w}/DONE"):
        return
    src_rec = source_validated(job["src"])
    if src_rec is None and os.path.exists(f"{w}/validate_source.json"):
        r = json.load(open(f"{w}/validate_source.json")); r["relpath"] = job["src"]; src_rec = r
        rec = {"relpath": job["src"], "role": "source", "key": job["key"], **{k: r.get(k) for k in
               ("schema", "bytes", "n_issues", "kinds", "error", "seconds", "peak_rss_gb")}, "validated_by": "migrator_v2"}
        open(f"{HERE}/validate_v2.jsonl", "a").write(json.dumps(rec) + "\n")
    for o in job["outputs"]:
        t = o["target"]
        mig = json.load(open(f"{w}/migrate_{t}.json"))
        mig.update({"key": job["key"], "source": job["src"], "old": o["old"], "new": o["new"]})
        open(f"{HERE}/migrate_v2.jsonl", "a").write(json.dumps(mig) + "\n")
        v = json.load(open(f"{w}/validate_{t}.json"))
        rec = {"relpath": o["new"], "role": "output", "key": job["key"], "target": t, "source": job["src"],
               "old_relpath": o["old"], **{k: v.get(k) for k in ("schema", "bytes", "n_issues", "kinds", "samples", "error",
                                                                  "seconds", "peak_rss_gb")}}
        open(f"{HERE}/validate_v2.jsonl", "a").write(json.dumps(rec) + "\n")
        old = pickle.load(open(f"{w}/sigold_{t}.pkl", "rb")); new = pickle.load(open(f"{w}/signew_{t}.pkl", "rb"))
        eq = compare(old, new); eq.update({"key": job["key"], "target": t, "old": o["old"], "new": o["new"]})
        open(f"{HERE}/equivalence_v2.jsonl", "a").write(json.dumps(eq) + "\n")
    open(f"{w}/DONE", "w").close()
    log(job["key"], "finalized")


if __name__ == "__main__":
    if sys.argv[1] == "plan":
        plan()
    elif sys.argv[1] == "run":
        only = sys.argv[3].split(",") if len(sys.argv) > 3 and sys.argv[2] == "--only" else None
        run(only)
