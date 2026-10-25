"""Helpers for the v4e deletion re-run scripts (rerun_delete_local.sh, rerun_delete_gemma.sh, rerun_delete_hosted.sh).
Reads plan.json; never prints an API key; writes only under gt_fix/delete_rerun/.

    python plan_tool.py jobs <group>                 one tab-separated line per job of the group
    python plan_tool.py check <run> <model>          after run_gate: task set, protocol, counts (+ cost for hosted)
    python plan_tool.py server                       the vLLM server on port 8000 as JSON (pid, pgid, template, ...)
    python plan_tool.py gpu-holders <pgid>           exit 1 if a process outside <pgid> holds /dev/nvidia*
    python plan_tool.py busy <lo-hi> [pgid]          exit 1 if another pinned process is busy on those cores (3 s sample);
                                                     processes of [pgid] (the caller's own job) are not counted
    python plan_tool.py pack <run> <model>           tar the job's edited/ into edited.tar.gz, verify, remove edited/
"""
import ast, json, os, sys, tarfile, time
from pathlib import Path

D = Path(__file__).resolve().parent
P = Path(".")
B = P / "runs_local/bench_v4"
PLAN = json.load(open(D / "plan.json"))
FIELDS = ("run", "model", "n", "adapter", "adapter_path", "note", "note_check", "style", "effort", "base_url", "key",
          "conc", "sw", "entry", "solo", "est_edited_bytes", "subset", "arm")
STD_CONFIG = {"max_tool_rounds": 22, "tool_timeout": 420.0, "temperature": 0.0, "top_p": 1.0, "max_tokens": 8192,
              "max_tool_output_chars": 16000, "max_recorded_output_chars": 4000, "capture_stdout": True,
              "max_transcript_tokens": 0, "min_turn_tokens": 256, "dup_stop": 0}


def job(run, model):
    for j in PLAN["jobs"]:
        if j["run"] == run and j["model"] == model:
            return j
    raise SystemExit(f"no job {run}/{model} in plan.json")


def cmd_jobs(group):
    for j in PLAN["jobs"]:
        if j["group"] != group:
            continue
        vals = []
        for f in FIELDS:
            v = j.get(f, "")
            if isinstance(v, bool):
                v = int(v)
            v = str(v)
            if f == "arm":
                v = v.replace(" ", "_").replace(",", "")
            vals.append(v if v != "" else "-")
            assert "\t" not in vals[-1] and " " not in vals[-1], (f, vals[-1])
        print("\t".join(vals))


def orig_config(j):
    """resolved_agent_config of the arm's original read (summary .pre_v4e/.pre_v4d/current all keep it)."""
    res = B / "results" / j["run"]
    for name in (f"summary_{j['model']}.json.pre_v4e", f"summary_{j['model']}.json.pre_v4d", f"summary_{j['model']}.json"):
        p = res / name
        if p.is_file():
            return json.load(open(p))["resolved_agent_config"], str(p)
    return None, None


def cmd_check(run, model):
    j = job(run, model)
    rd = D / run
    rows = [json.loads(l) for l in open(rd / f"per_task_{model}.jsonl") if l.strip()]
    ids = json.load(open(j["subset"]))
    assert sorted(r["task_id"] for r in rows) == sorted(ids), "task set differs from the subset"
    assert len(rows) == len(ids), "row count differs from the subset"
    cfg = json.load(open(rd / f"summary_{model}.json"))["resolved_agent_config"]
    ref, src = orig_config(j)
    assert ref is not None, f"no original summary for {run}/{model}"
    assert cfg == ref, f"protocol differs from the original read ({src}): {cfg} vs {ref}"
    assert ref == STD_CONFIG, f"original protocol is not the standard one: {ref}"
    # the working copy of every task must be where the splice expects it
    for r in rows:
        ed = str(r.get("edited_ifc") or "")
        assert ed.startswith(str(rd / model / "edited" / r["task_id"]) + "/"), (r["task_id"], ed)
    err = sum(r.get("stop_reason") == "inference_error" for r in rows)
    unsc = sum(r.get("final") is None for r in rows)
    done = sum(all(((r.get("score") or {}).get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology")) for r in rows)
    out = dict(run=run, model=model, n=len(rows), completed=done, inference_errors=err, unscorable=unsc,
               protocol_from=src, guard_rows=sum("sandbox_blocked" in r for r in rows))
    if j["group"] == "hosted":
        consts = {}
        for node in ast.parse(open(B / "hosted_cost.py").read()).body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ("PRICE", "CACHE_READ"):
                consts[node.targets[0].id] = ast.literal_eval(node.value)
        pi, po = consts["PRICE"][model]
        cr = consts["CACHE_READ"].get(model, 0.1)
        tin = sum(int(r.get("input_tokens") or 0) for r in rows)
        tout = sum(int(r.get("output_tokens") or 0) for r in rows)
        cread = sum(int(r.get("cache_read_tokens") or 0) for r in rows)
        cwrite = sum(int(r.get("cache_creation_tokens") or 0) for r in rows)
        cost = (tin - cread - cwrite) / 1e6 * pi + cread / 1e6 * pi * cr + cwrite / 1e6 * pi * 1.25 + tout / 1e6 * po
        out.update(input_tokens=tin, cache_read_tokens=cread, cache_creation_tokens=cwrite, output_tokens=tout,
                   price_usd_per_mtok=[pi, po], cache_read_fraction=cr, usd=round(cost, 4))
        (rd / f"cost_{model}.json").write_text(json.dumps(out, indent=1) + "\n")
    print("checked", json.dumps(out))
    if err or unsc:
        print(f"NOTE {run}/{model}: {err} inference errors, {unsc} unscorable rows; held for review before the splice")


def _procs():
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open(f"/proc/{pid}/cmdline", "rb").read().split(b"\0")
            yield int(pid), [a.decode(errors="replace") for a in argv if a]
        except Exception:
            continue


def cmd_server():
    found = {}
    for pid, argv in _procs():
        if "serve" not in argv or not any(a.endswith("/vllm") for a in argv):
            continue
        port = argv[argv.index("--port") + 1] if "--port" in argv else "8000"
        if port != "8000":
            continue
        def opt(name):
            return argv[argv.index(name) + 1] if name in argv else ""
        try:
            pgid = os.getpgid(pid)
            env = open(f"/proc/{pid}/environ", "rb").read().split(b"\0")
        except Exception:
            continue
        env = dict(e.decode(errors="replace").split("=", 1) for e in env if b"=" in e)
        found[pgid] = dict(pid=pid, pgid=pgid, model=argv[argv.index("serve") + 1], served=opt("--served-model-name"),
                           template=opt("--chat-template"), max_model_len=opt("--max-model-len"),
                           runtime_lora=env.get("VLLM_ALLOW_RUNTIME_LORA_UPDATING", ""),
                           lora="--enable-lora" in argv, cores=open(f"/proc/{pid}/status").read().split("Cpus_allowed_list:")[1].split()[0])
    print(json.dumps(list(found.values())))


def cmd_gpu_holders(pgid):
    pgid = int(pgid)
    bad = []
    for pid, argv in _procs():
        try:
            fds = os.listdir(f"/proc/{pid}/fd")
        except Exception:
            continue
        for fd in fds:
            try:
                tgt = os.readlink(f"/proc/{pid}/fd/{fd}")
            except Exception:
                continue
            if tgt.startswith("/dev/nvidia") and tgt[len("/dev/nvidia"):].isdigit():
                try:
                    if os.getpgid(pid) != pgid:
                        bad.append((pid, " ".join(argv)[:100]))
                except Exception:
                    pass
                break
    for b in bad:
        print("GPU held outside the server group:", b)
    sys.exit(1 if bad else 0)


def cmd_busy(cores, exclude_pgid=None):
    """exclude_pgid: processes of this group (the calling script's own job) are not counted."""
    lo, hi = map(int, cores.split("-"))
    mine = set(range(lo, hi + 1))
    tick = os.sysconf("SC_CLK_TCK")
    me = {os.getpid(), os.getppid()}

    def cpus(s):
        out = set()
        for part in s.split(","):
            a, _, b = part.partition("-")
            out.update(range(int(a), int(b or a) + 1))
        return out

    def cputime(pid):
        f = open(f"/proc/{pid}/stat").read().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / tick

    cand = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        if int(pid) in me:
            continue
        try:
            if exclude_pgid is not None and os.getpgid(int(pid)) == int(exclude_pgid):
                continue
            st = open(f"/proc/{pid}/status").read()
            allowed = cpus(next(l.split(":", 1)[1].strip() for l in st.splitlines() if l.startswith("Cpus_allowed_list")))
            if len(allowed) < os.cpu_count() and allowed & mine:
                cand[pid] = (sorted(allowed), open(f"/proc/{pid}/cmdline").read().replace("\0", " ")[:120], cputime(pid))
        except Exception:
            continue
    time.sleep(3)
    busy = []
    for pid, (allowed, cmd, t0) in cand.items():
        try:
            used = cputime(pid) - t0
        except Exception:
            continue
        if used > 0.3:
            busy.append((pid, allowed, round(used / 3, 2), cmd))
    for b in busy:
        print("pinned and busy on the re-run cores (pid, cores, cpu share, command):", b)
    sys.exit(1 if busy else 0)


def cmd_pack(run, model):
    """tar czf edited.tar.gz edited (the layout of runs_local/tools/pack_gate_edits.sh), verify, remove edited/.
    Idempotent: with edited/ gone and the archive present, only the verification runs."""
    j = job(run, model)
    md = D / run / model
    arc = md / "edited.tar.gz"
    ed = md / "edited"
    ids = json.load(open(j["subset"]))
    if ed.is_dir():
        sizes = {}
        for t in ids:
            td = ed / t
            assert td.is_dir(), f"no edited/{t}"
            for f in td.iterdir():
                sizes[f"edited/{t}/{f.name}"] = f.stat().st_size
        tmp = md / "edited.tar.gz.tmp"
        with tarfile.open(tmp, "w:gz") as tf:
            tf.add(ed, arcname="edited")
        with tarfile.open(tmp) as tf:
            mem = {m.name: m.size for m in tf.getmembers() if m.isfile()}
        missing = [k for k, v in sizes.items() if mem.get(k) != v]
        assert not missing, f"archive check failed: {missing[:5]}"
        os.replace(tmp, arc)
        import shutil
        shutil.rmtree(ed)
        print(f"packed {run}/{model}: {len(sizes)} files, {arc.stat().st_size / 2**20:.0f} MiB")
    else:
        assert arc.is_file(), f"neither edited/ nor edited.tar.gz in {md}"
        with tarfile.open(arc) as tf:
            names = {m.name for m in tf.getmembers()}
        absent = [t for t in ids if f"edited/{t}" not in names]
        assert not absent, f"archive lacks {absent[:5]}"
        print(f"archive of {run}/{model} verified ({len(ids)} tasks)")


if __name__ == "__main__":
    c, *a = sys.argv[1:]
    {"jobs": cmd_jobs, "check": cmd_check, "server": cmd_server, "gpu-holders": cmd_gpu_holders,
     "busy": cmd_busy, "pack": cmd_pack}[c](*a)
