"""Splice the v4e deletion re-runs into the canonical result folders (after every DONE marker exists).

For every job of delete_rerun/plan.json, in results/<run>/ of runs_local/bench_v4:
  * per_task_<m>.jsonl, by_version_<m>.txt and summary_<m>.json are renamed to *.pre_v4e (only if no *.pre_v4e exists:
    resume-safe); per_task_<m>.jsonl is rewritten from the *.pre_v4e rows in their order, with exactly the re-run tasks'
    rows replaced by the re-run rows (delete_rerun/<run>/per_task_<m>.jsonl), whose edited_ifc paths are rewritten from
    delete_rerun/<run>/<m>/ to results/<run>/<m>/;
  * for each re-run task, the current <m>/transcripts/<task>.json, <m>/logs/<task>.log and <m>/edited/<task>/ move to
    <m>/transcripts_pre_v4e/, <m>/logs_pre_v4e/, <m>/edited_pre_v4e/ (when present), and the re-run files are hard-linked
    in their place. A packed re-run (delete_rerun/<run>/<m>/edited.tar.gz, PACK_EDITED=1) is hard-linked as
    <m>/edited_v4e.tar.gz and the rows' edited_ifc keep the canonical path results/<run>/<m>/edited/<task>/<file>, which
    is a member of that archive (the same convention as the arms whose edited/ lives in edited.tar.gz). A path that is
    already a hard link of the re-run file is left alone, so a re-run file is never moved into a *_pre_v4e folder;
  * the composite arm hosted324_lib_all takes its rows from the hosted108_lib_all / hosted216_lib_all re-runs; its rows'
    edited_ifc point at the source arm's canonical path (as the composite's original rows did), and the transcripts and
    logs are hard-linked into hosted324_lib_all/<m>/ (as the v4d finalize did);
  * the re-run's summary, log, file-access audit, subset, check and cost files are hard-linked into results/<run>/rerun_meta_v4e/;
  * runs_local/bench_v4/finish_read.sh writes by_version_<m>.txt (and touches DONE_<m>);
  * summary_<m>.json is rebuilt from the final rows with stage_a.gate_eval.summarize and the resolved agent config of the
    archived summary; per_task_file, subset, scorer_reading, label, protocol_conformant, finished_at (and the v4d
    provenance keys) are kept; v4e_rerun_tasks and v4e_finalized_at are added. An arm without a summary (the composite)
    gets none, as before.
Checks after each arm: task set and row count equal the *.pre_v4e file's; every non-re-run row is unchanged; every
re-run row equals the re-run row apart from edited_ifc; every re-run edited model exists (file or archive member);
transcripts and logs are hard links of the re-run files.
Refuses (prints the reasons, writes nothing) when any DONE marker is missing, a re-run row is missing, a destination is
occupied by something that is not the re-run file, another canonical per-task file points at a path the splice
re-assigns (unless --foreign-ok), or free disk would drop below 30 GiB.
    python splice_delete.py --check     # print the plan and every refusal reason; write nothing
    python splice_delete.py             # splice
"""
import argparse, datetime, json, os, shutil, subprocess, sys, tarfile
from pathlib import Path

D = Path(__file__).resolve().parent
P = Path(".")
B = P / "runs_local/bench_v4"
RES = Path(os.environ.get("V4E_RESULTS_DIR", B / "results"))      # override only for a dry test on copies
FINISH = Path(os.environ.get("V4E_FINISH", B / "finish_read.sh"))
MIN_FREE = int(float(os.environ.get("V4E_MIN_FREE_GIB", "30")) * 2**30)   # override only for the dry test on copies
KEEP = ("per_task_file", "subset", "scorer_reading", "label", "protocol_conformant", "finished_at",
        "v4d_finalized_at", "v4d_rerun_tasks")
sys.path.insert(0, str(P / "code"))


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def same(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def tree_same(a, b):
    """every file of the re-run edited/<task> dir is the same inode at the destination"""
    if not (a.is_dir() and b.is_dir()):
        return False
    return all(same(f, b / f.name) for f in a.iterdir()) and len(list(a.iterdir())) == len(list(b.iterdir()))


class Plan:
    def __init__(self):
        plan = json.load(open(D / "plan.json"))
        self.jobs = plan["jobs"]
        self.by = {(j["run"], j["model"]): j for j in self.jobs}

    def arms(self):
        # sources before composites, so a composite's source paths are final when it is spliced
        return sorted(self.jobs, key=lambda j: (j["group"] == "composite", j["run"], j["model"]))


def rerun_source(plan, j, task):
    """(job whose re-run holds this task's row, its delete_rerun folder)"""
    if j["group"] != "composite":
        return j, D / j["run"]
    src = next(s["run"] for s in j["sources"] if s["task"] == task)
    return plan.by[(src, j["model"])], D / src


def canonical_edit_path(row_path, src_job, model):
    """delete_rerun/<src run>/<m>/edited/... -> results/<src run>/<m>/edited/..."""
    pre = str(D / src_job["run"] / model / "edited") + "/"
    assert row_path.startswith(pre), (row_path, pre)
    return str(RES / src_job["run"] / model / "edited") + "/" + row_path[len(pre):]


def archive_names(path, cache={}):
    if path not in cache:
        with tarfile.open(path) as tf:
            cache[path] = {m.name for m in tf.getmembers()}
    return cache[path]


def prepare(plan, problems, notes):
    """Everything the splice will do, per arm, without writing. Appends refusal reasons to problems."""
    steps = []
    rerun_rows = {}
    for j in plan.jobs:
        if j["group"] == "composite":
            continue
        rd = D / j["run"]
        if not (rd / f"DONE_{j['model']}").is_file():
            problems.append(f"missing DONE marker: {rd}/DONE_{j['model']}")
            continue
        rows = {r["task_id"]: r for r in read_jsonl(rd / f"per_task_{j['model']}.jsonl")}
        miss = [t for t in j["tasks"] if t not in rows]
        extra = sorted(set(rows) - set(j["tasks"]))
        if miss or extra:
            problems.append(f"{j['run']}/{j['model']}: re-run rows missing {miss[:5]} / unexpected {extra[:5]}")
        rerun_rows[(j["run"], j["model"])] = rows
    moved_paths = set()   # canonical edited paths the splice re-assigns
    for j in plan.arms():
        run, m = j["run"], j["model"]
        res = RES / run
        cur = res / f"per_task_{m}.jsonl"
        pre = res / f"per_task_{m}.jsonl.pre_v4e"
        base = pre if pre.is_file() else cur
        if not base.is_file():
            problems.append(f"{run}/{m}: no per-task file")
            continue
        old = read_jsonl(base)
        ids = [r["task_id"] for r in old]
        absent = sorted(set(j["tasks"]) - set(ids))
        if absent:
            problems.append(f"{run}/{m}: re-run tasks absent from the canonical file: {absent[:5]}")
            continue
        links, moves, rows = [], [], []
        tasks = set(j["tasks"])
        for r in old:
            t = r["task_id"]
            if t not in tasks:
                rows.append(r)
                continue
            sj, srd = rerun_source(plan, j, t)
            rr = rerun_rows.get((sj["run"], m), {}).get(t)
            if rr is None:
                rows.append(None)
                continue
            new = dict(rr)
            new["edited_ifc"] = canonical_edit_path(str(rr["edited_ifc"]), sj, m)
            rows.append(new)
            moved_paths.add(new["edited_ifc"])
            # transcripts and logs: hard links into this arm's own folder (the composite included)
            for sub, name in (("transcripts", f"{t}.json"), ("logs", f"{t}.log")):
                n = srd / m / sub / name
                o = res / m / sub / name
                if not n.is_file():
                    problems.append(f"{run}/{m}/{t}: no re-run {sub}/{name}")
                    continue
                if same(n, o):
                    continue
                if o.exists():
                    dst = res / m / f"{sub}_pre_v4e" / name
                    if dst.exists():
                        problems.append(f"{run}/{m}/{t}: {dst} exists and {o} is not the re-run file")
                    moves.append((o, dst))
                links.append((n, o))
            # edited model: only the arm that owns it (the composite points at its source's copy)
            if j["group"] != "composite":
                n = srd / m / "edited" / t
                o = res / m / "edited" / t
                arc = srd / m / "edited.tar.gz"
                if n.is_dir():
                    if not tree_same(n, o):
                        if o.exists():
                            dst = res / m / "edited_pre_v4e" / t
                            if dst.exists():
                                problems.append(f"{run}/{m}/{t}: {dst} exists and {o} is not the re-run copy")
                            moves.append((o, dst))
                        links.append((n, o))
                elif arc.is_file():
                    if o.exists():   # an unarchived old copy at the path the row now names
                        dst = res / m / "edited_pre_v4e" / t
                        if dst.exists():
                            problems.append(f"{run}/{m}/{t}: {dst} exists and {o} is still present")
                        moves.append((o, dst))
                else:
                    problems.append(f"{run}/{m}/{t}: neither edited/{t} nor edited.tar.gz in {srd / m}")
        if j["group"] != "composite":
            arc = D / run / m / "edited.tar.gz"
            dst = res / m / "edited_v4e.tar.gz"
            if arc.is_file() and not same(arc, dst):
                if dst.exists():
                    problems.append(f"{run}/{m}: {dst} exists and is not the re-run archive")
                links.append((arc, dst))
            meta = res / "rerun_meta_v4e"
            for name in (f"summary_{m}.json", f"{m}.log", f"fs_audit_{m}.json", f"fs_audit_{m}.log", f"cost_{m}.json",
                         f"time_{m}.txt"):
                if (D / run / name).is_file() and not same(D / run / name, meta / name):
                    if (meta / name).exists():
                        problems.append(f"{meta / name} exists and is not the re-run file")
                    links.append((D / run / name, meta / name))
            sub = Path(j["subset"])
            if not same(sub, meta / f"subset_{m}.json"):
                if (meta / f"subset_{m}.json").exists():
                    problems.append(f"{meta}/subset_{m}.json exists and is not the plan's subset")
                links.append((sub, meta / f"subset_{m}.json"))
        steps.append(dict(job=j, base=base, old=old, rows=rows, links=links, moves=moves))
    # other canonical per-task files whose rows name a path the splice re-assigns
    spliced = {(RES / j["run"] / f"per_task_{j['model']}.jsonl") for j in plan.jobs}
    for f in sorted(RES.glob("*/per_task_*.jsonl")):
        if f in spliced:
            continue
        for l in open(f, encoding="utf-8"):
            if not l.strip():
                continue
            r = json.loads(l)
            if str(r.get("edited_ifc") or "") in moved_paths:
                notes.append(f"foreign reference: {f.relative_to(RES)} row {r['task_id']} names {r['edited_ifc']}")
    return steps


def bytes_to_write(steps):
    total = 0
    for s in steps:
        res = RES / s["job"]["run"]
        m = s["job"]["model"]
        for name in (f"per_task_{m}.jsonl", f"summary_{m}.json", f"by_version_{m}.txt"):
            p = res / name
            if p.is_file() and not (res / (name + ".pre_v4e")).exists():
                total += p.stat().st_size   # the archived copy keeps its blocks; the new file is about as large
    return total


def splice_arm(s, log):
    from stage_a.gate_eval import summarize, AgentConfig
    j = s["job"]
    run, m = j["run"], j["model"]
    res = RES / run
    # 1. archive the current files (only once)
    for name in (f"per_task_{m}.jsonl", f"by_version_{m}.txt", f"summary_{m}.json"):
        src, dst = res / name, res / (name + ".pre_v4e")
        if src.exists() and not dst.exists():
            os.rename(src, dst)
    # 2. move the old per-task artefacts aside, then hard-link the re-run files in
    for o, dst in s["moves"]:
        if o.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            os.rename(o, dst)
    for n, o in s["links"]:
        if same(n, o):
            continue
        o.parent.mkdir(parents=True, exist_ok=True)
        if n.is_dir():
            shutil.copytree(n, o, symlinks=False, copy_function=os.link)
        else:
            os.link(n, o)
    # 3. the per-task file
    rows = s["rows"]
    tmp = res / f".per_task_{m}.jsonl.v4e_tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, res / f"per_task_{m}.jsonl")
    # 4. by_version and the DONE marker
    fin = subprocess.run(["bash", str(FINISH), str(res), m], capture_output=True, text=True)
    if fin.returncode != 0:
        raise SystemExit(f"finish_read.sh failed for {res} {m}: {fin.stdout}{fin.stderr}")
    # 5. the summary
    old_sum_p = res / f"summary_{m}.json.pre_v4e"
    if old_sum_p.exists():
        old_sum = json.load(open(old_sum_p))
        new_sum = summarize(m, rows, AgentConfig(**old_sum["resolved_agent_config"]))
        for k in KEEP:
            if k in old_sum:
                new_sum[k] = old_sum[k]
        new_sum["v4e_rerun_tasks"] = len(j["tasks"])
        new_sum["v4e_finalized_at"] = datetime.datetime.now().isoformat(timespec="seconds")
        tmp = res / f".summary_{m}.json.v4e_tmp"
        tmp.write_text(json.dumps(new_sum, indent=2), encoding="utf-8")
        os.replace(tmp, res / f"summary_{m}.json")
    verify_arm(s)
    done = sum(all(((r.get("score") or {}).get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology")) for r in rows)
    before = sum(all(((r.get("score") or {}).get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology")) for r in s["old"])
    if j["group"] == "composite":
        edited = "source arms: " + ", ".join(sorted({x["run"] for x in j["sources"]}))
    else:
        edited = "archive edited_v4e.tar.gz" if (D / run / m / "edited.tar.gz").is_file() else "edited/<task> hard links"
    log.append(dict(run=run, model=m, rows=len(rows), rerun_tasks=len(j["tasks"]), completed_before=before,
                    completed_after=done, edited=edited))
    print(f"{run}/{m}: {len(j['tasks'])} rows replaced; completed {before} -> {done} of {len(rows)}")


def verify_arm(s):
    j = s["job"]
    run, m = j["run"], j["model"]
    res = RES / run
    new = read_jsonl(res / f"per_task_{m}.jsonl")
    old = read_jsonl(res / f"per_task_{m}.jsonl.pre_v4e")
    assert len(new) == len(old), (run, m, "row count")
    assert [r["task_id"] for r in new] == [r["task_id"] for r in old], (run, m, "task order/set")
    tasks = set(j["tasks"])
    for a, b in zip(old, new):
        t = a["task_id"]
        if t not in tasks:
            assert a == b, (run, m, t, "non-re-run row changed")
            continue
        sj, srd = rerun_source(Plan(), j, t) if j["group"] == "composite" else (j, D / run)
        rr = {r["task_id"]: r for r in read_jsonl(srd / f"per_task_{m}.jsonl")}[t]
        assert {k: v for k, v in b.items() if k != "edited_ifc"} == {k: v for k, v in rr.items() if k != "edited_ifc"}, (run, m, t)
        ed = Path(b["edited_ifc"])
        owner = RES / sj["run"] / m
        if not ed.is_file():
            arc = owner / "edited_v4e.tar.gz"
            assert arc.is_file(), (run, m, t, "no edited model and no archive")
            assert str(ed.relative_to(owner)) in archive_names(str(arc)), (run, m, t, "edited model not in the archive")
        for sub, name in (("transcripts", f"{t}.json"), ("logs", f"{t}.log")):
            assert same(srd / m / sub / name, res / m / sub / name), (run, m, t, sub)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="print the plan and the refusal reasons; write nothing")
    ap.add_argument("--foreign-ok", action="store_true", help="proceed although other per-task files name re-assigned paths")
    args = ap.parse_args()
    plan = Plan()
    problems, notes = [], []
    steps = prepare(plan, problems, notes)
    st = os.statvfs(RES)
    free = st.f_bavail * st.f_frsize
    need = bytes_to_write(steps)
    print(f"{len(plan.jobs)} arms in the plan, {sum(len(j['tasks']) for j in plan.jobs)} rows to replace; "
          f"free {free / 2**30:.1f} GiB, new files ~{need / 2**30:.2f} GiB (hard links take no space), floor 30 GiB")
    if free - need < MIN_FREE:
        problems.append(f"disk: {free / 2**30:.1f} GiB free, the splice writes ~{need / 2**30:.2f} GiB, floor {MIN_FREE / 2**30:.0f} GiB")
    for s in steps:
        j = s["job"]
        print(f"  {j['run']}/{j['model']}: {len(s['old'])} rows, replace {len(j['tasks'])}, moves {len(s['moves'])}, "
              f"links {len(s['links'])}" + (f", rows from {sorted({x['run'] for x in j['sources']})}" if j["sources"] else ""))
    for n in notes:
        print("NOTE", n)
    if notes and not args.foreign_ok:
        problems.append(f"{len(notes)} foreign reference(s) to re-assigned paths (rerun with --foreign-ok after review)")
    if problems:
        print(f"{len(problems)} reason(s) to refuse; nothing written:")
        for p in problems[:200]:
            print("  " + p)
        if len(problems) > 200:
            print(f"  ... and {len(problems) - 200} more")
        sys.exit(1)
    if args.check:
        print("check passed; nothing written")
        return
    log = []
    for s in steps:
        splice_arm(s, log)
    (D / "splice_v4e_log.json").write_text(json.dumps(log, indent=1) + "\n")
    (D / "SPLICE_V4E_DONE").touch()
    print(f"{len(log)} arms spliced; log {D / 'splice_v4e_log.json'}")


if __name__ == "__main__":
    main()
