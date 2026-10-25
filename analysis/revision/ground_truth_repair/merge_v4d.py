"""Assemble the v4d result folders after the 2026-10-15 ground-truth fix.

For every (run, model) in gt_fix/arm_summary.csv, write
runs_local/bench_v4/results/<run>_v4d/per_task_<model>.jsonl with one row per row of the original per-task file, in
the original order. Each row comes from, in order of precedence:
  1. the re-run row (gt_fix/reruns/<run>/per_task_<model>.jsonl) when (run, model, task) is in gt_fix/rerun_list.csv;
     hosted324_lib_all takes these rows from the hosted216_lib_all re-run, because its 324-task file was assembled
     from hosted108_lib_all and hosted216_lib_all;
  2. the rescored row (gt_fix/rescored/<run>/per_task_<model>_fixed.jsonl) when the task is one of the 69 whose
     ground truth changed;
  3. the original row.
An affected task with neither a re-run nor a rescored row (the edited model was not archived) keeps its original row
and is listed under "affected_not_rescored" in the report.
The edited models, transcripts and per-task logs of the re-run tasks are hard-linked (same file system; the
_v4d tree keeps the data if gt_fix/reruns is removed later) into
<run>_v4d/<model>/{edited/<task>/, transcripts/<task>.json, logs/<task>.log}, the layout of the original runs, and the
re-run rows' edited_ifc paths point at the copies. The re-run summaries, logs and file-access audits are copied into
<run>_v4d/rerun_meta/. by_version_<model>.txt and DONE_<model> are written by runs_local/bench_v4/finish_read.sh.
provenance_<model>.json in each folder maps every task to its source; gt_fix/merge_report.json gives, per arm, the
completion before and after and the provenance counts.

Refuses to start when any listed re-run row is missing (prints the list), when an output file already exists
(nothing is overwritten), or when the copies would leave less than 30 GB free.
    python merge_v4d.py            # check, then write
    python merge_v4d.py --check    # check and print the plan only
"""
import argparse, csv, json, os, shutil, subprocess, sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(".")
# the three overrides exist only for the dry test on copies (gt_fix/tests/merge_dry_test.sh)
RES = Path(os.environ.get("V4D_RESULTS_DIR", ROOT / "runs_local/bench_v4/results"))
G = Path(os.environ.get("V4D_GT_FIX_DIR", ROOT / "analysis/revision/ground_truth_repair"))
FINISH = Path(os.environ.get("V4D_FINISH", ROOT / "runs_local/bench_v4/finish_read.sh"))
MIN_FREE_GB = 30
# composite arms whose listed rows are the rows of another run
RERUN_SOURCE = {("hosted324_lib_all", "claude-sonnet-5-5"): "hosted216_lib_all"}


def completed(r):
    sc = r.get("score") or {}
    return all(sc.get(k) is not None and sc.get(k) >= 0.9 for k in ("geometry", "semantics", "topology"))


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


def tree_bytes(p):
    if p.is_file():
        return p.stat().st_size
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="validate and print the plan; write nothing")
    args = ap.parse_args()

    arms = [(r["run"], r["model"]) for r in csv.DictReader(open(G / "arm_summary.csv"))]
    affected = {l.strip() for l in open(G / "affected_tasks.txt") if l.strip()}
    listed = defaultdict(set)
    for r in csv.DictReader(open(G / "rerun_list.csv")):
        listed[(r["run"], r["model"])].add(r["task"])
    unknown = sorted(set(listed) - set(arms))
    if unknown:
        sys.exit(f"re-run list names arms not in arm_summary.csv: {unknown}")

    # 1. every listed re-run must exist
    rerun_rows, missing = {}, []
    for (run, model), tasks in sorted(listed.items()):
        src = G / "reruns" / RERUN_SOURCE.get((run, model), run)
        pt, done = src / f"per_task_{model}.jsonl", src / f"DONE_{model}"
        rows = {r["task_id"]: r for r in read_jsonl(pt)} if pt.is_file() and done.is_file() else {}
        for t in sorted(tasks):
            if t in rows:
                rerun_rows[(run, model, t)] = (rows[t], src)
            else:
                missing.append(f"{run}/{model}/{t}" + ("" if done.is_file() else f" (no {done.name} in {src})"))
    if missing:
        print(f"{len(missing)} listed re-run rows are missing; nothing written:")
        print("\n".join(missing))
        sys.exit(1)

    # 2. plan every arm, refuse on an existing output, size the copies
    plans, copy_bytes, clashes = [], 0, []
    for run, model in arms:
        orig_p = RES / run / f"per_task_{model}.jsonl"
        out_dir = RES / f"{run}_v4d"
        for name in (f"per_task_{model}.jsonl", f"provenance_{model}.json", f"by_version_{model}.txt", f"DONE_{model}"):
            if (out_dir / name).exists():
                clashes.append(str(out_dir / name))
        if (out_dir / model).exists():
            clashes.append(str(out_dir / model))
        resc_p = G / "rescored" / run / f"per_task_{model}_fixed.jsonl"
        resc = {r["task_id"]: r for r in read_jsonl(resc_p)} if resc_p.is_file() else {}
        orig = read_jsonl(orig_p)
        ids = [r["task_id"] for r in orig]
        absent = sorted(listed.get((run, model), set()) - set(ids))
        if absent:
            sys.exit(f"{run}/{model}: listed tasks absent from the original file: {absent}")
        for t in listed.get((run, model), ()):
            src = rerun_rows[(run, model, t)][1] / model
            for part in (src / "edited" / t, src / "transcripts" / f"{t}.json", src / "logs" / f"{t}.log"):
                if part.exists():
                    copy_bytes += 0 * tree_bytes(part)   # hard links: no new blocks
        plans.append((run, model, orig, resc, out_dir))
    if clashes:
        print(f"{len(clashes)} output paths already exist; nothing written:")
        print("\n".join(clashes))
        sys.exit(1)
    st = os.statvfs(RES)
    free_gb = st.f_bavail * st.f_frsize / 2**30
    print(f"{len(plans)} arms, {len(rerun_rows)} re-run rows, copies {copy_bytes / 2**30:.2f} GB, free {free_gb:.1f} GB")
    if free_gb - copy_bytes / 2**30 < MIN_FREE_GB:
        sys.exit(f"the copies would leave less than {MIN_FREE_GB} GB free; nothing written")
    if args.check:
        for run, model, orig, resc, out_dir in plans:
            n_rr = len(listed.get((run, model), ()))
            n_rs = sum(1 for r in orig if r["task_id"] in resc and r["task_id"] not in listed.get((run, model), ()))
            print(f"  {run}/{model}: {len(orig)} rows, re-run {n_rr}, rescored {n_rs} -> {out_dir}")
        return

    # 3. write
    report = {"arms": [], "rerun_source": {f"{a}/{b}": f"{c}/{b}" for (a, b), c in RERUN_SOURCE.items()}}
    for run, model, orig, resc, out_dir in plans:
        out_dir.mkdir(parents=True, exist_ok=True)
        rr_tasks = listed.get((run, model), set())
        rows, prov, not_rescored = [], {}, []
        for r in orig:
            t = r["task_id"]
            if t in rr_tasks:
                row, src_run = rerun_rows[(run, model, t)]
                row = dict(row)
                src, dst = src_run / model, out_dir / model
                if (src / "edited" / t).exists():
                    shutil.copytree(src / "edited" / t, dst / "edited" / t, symlinks=False, copy_function=os.link)
                for sub, name in (("transcripts", f"{t}.json"), ("logs", f"{t}.log")):
                    if (src / sub / name).is_file():
                        (dst / sub).mkdir(parents=True, exist_ok=True)
                        os.link(src / sub / name, dst / sub / name)
                ed = str(row.get("edited_ifc") or "")
                if ed.startswith(str(src / "edited") + "/"):
                    row["edited_ifc"] = str(dst / "edited") + ed[len(str(src / "edited")):]
                rows.append(row); prov[t] = f"rerun:{src_run.name}"
            elif t in affected and t in resc:
                rows.append(resc[t]); prov[t] = "rescored"
            elif t in affected:
                rows.append(r); prov[t] = "original_affected_not_rescored"; not_rescored.append(t)
            else:
                rows.append(r); prov[t] = "original"
        with open(out_dir / f"per_task_{model}.jsonl", "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        (out_dir / f"provenance_{model}.json").write_text(json.dumps(prov, indent=1) + "\n")
        if rr_tasks:
            src_run = G / "reruns" / RERUN_SOURCE.get((run, model), run)
            meta = out_dir / "rerun_meta"
            meta.mkdir(exist_ok=True)
            for name in (f"summary_{model}.json", f"{model}.log", f"fs_audit_{model}.json", f"fs_audit_{model}.log",
                         f"subset_{model}.json", f"cost_{model}.json"):
                if (src_run / name).is_file():
                    shutil.copy2(src_run / name, meta / name)
        fin = subprocess.run(["bash", str(FINISH), str(out_dir), model], capture_output=True, text=True)
        if fin.returncode != 0:
            sys.exit(f"finish_read.sh failed for {out_dir} {model}: {fin.stdout}{fin.stderr}")
        counts = Counter(v.split(":")[0] for v in prov.values())
        before, after = sum(map(completed, orig)), sum(map(completed, rows))
        report["arms"].append({
            "run": run, "model": model, "out": str(out_dir / f"per_task_{model}.jsonl"), "n": len(rows),
            "completed_before": before, "completed_after": after,
            "completion_before": round(before / len(rows), 4), "completion_after": round(after / len(rows), 4),
            "provenance": {k: counts.get(k, 0) for k in ("original", "rescored", "rerun", "original_affected_not_rescored")},
            "affected_not_rescored": sorted(not_rescored)})
        a = report["arms"][-1]
        print(f"{run}/{model}: {before} -> {after} of {len(rows)}  {a['provenance']}")
    (G / "merge_report.json").write_text(json.dumps(report, indent=1) + "\n")
    print("merge report:", G / "merge_report.json")


if __name__ == "__main__":
    main()
