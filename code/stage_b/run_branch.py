"""Runner for construction (b): select branch jobs, repair them, emit turn pairs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from stage_a import paths
from stage_a.goldmodels import open_cache

from .branch import branch_one, set_gold_cache, to_pair
from .pairs import branch_jobs, observed_class_shares, select_branch_jobs

paths.ensure_harness_on_path()


def main(argv=None) -> int:
    from concurrent.futures import ThreadPoolExecutor

    from modifc_harness.client import ChatClient
    from modifc_harness.config import AgentConfig

    ap = argparse.ArgumentParser(prog="stage-b-branch")
    ap.add_argument("--rollouts", required=True)
    ap.add_argument("--tasks-file",
                    default=str(paths.PROJECT_ROOT / "data/veribim_tasks_v1/tasks.jsonl"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--report", required=True)
    ap.add_argument("--work-root", default=str(paths.PROJECT_ROOT / "data/stage_b/_branch"))
    ap.add_argument("--gold-cache", default=str(paths.PROJECT_ROOT / "data/stage_b/_gold_branch"))
    ap.add_argument("--adapter", default="sft590")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--cap", type=int, default=2000)
    ap.add_argument("--attempts", type=int, default=4)
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--max-tool-rounds", type=int, default=12)
    ap.add_argument("--temperature", type=float, default=0.8)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--scorer-reading", choices=("published", "family"),
                    default="published",
                    help="'family' grades each repaired trajectory under the "
                         "settings its own taxonomy tags ask for and reads its "
                         "closing message; 'published' is the v1 reading")
    args = ap.parse_args(argv)
    family_reading = args.scorer_reading == "family"

    rollouts = [json.loads(l) for l in Path(args.rollouts).open(encoding="utf-8") if l.strip()]

    # Resume: a job already attempted is not attempted again. Results are
    # appended as each job finishes, because the first version of this pass
    # accumulated everything in memory and wrote at the end, so five hours of
    # work went with the process that died.
    out_path, records_path = Path(args.out), Path(args.out).with_suffix(".records.jsonl")
    already: set[tuple] = set()
    if records_path.exists():
        with records_path.open(encoding="utf-8") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                    already.add((rec["task_id"], rec["turn"]))
                except (json.JSONDecodeError, KeyError):
                    continue

    # Only the tasks the rollouts mention are held: the v2 task file carries a
    # gold script per row, and keeping all of them resident costs a few hundred
    # megabytes for nothing.
    wanted = {row["task_id"] for row in rollouts}
    tasks = {}
    with Path(args.tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                record = json.loads(line)
                if record["task_id"] in wanted:
                    tasks[record["task_id"]] = record

    jobs = branch_jobs(rollouts)
    for job in jobs:
        record = tasks.get(job["task_id"])
        if record is not None:
            job["task_record"] = record
    skipped = sum(1 for j in jobs if "task_record" not in j)
    if skipped:
        print(f"  {skipped} jobs have no task record and are skipped", flush=True)
    jobs = [j for j in jobs if "task_record" in j]
    weights = observed_class_shares(rollouts)
    selected, allocation = select_branch_jobs(jobs, cap=args.cap, weights=weights,
                                              already=already)
    allocation["measured_shares"] = {k: round(v, 4) for k, v in weights.items()}
    print(json.dumps(allocation, indent=1), flush=True)

    # One cache directory per worker thread. A single shared directory lets two
    # jobs rebuilding a gold model at once delete each other's temporary file,
    # which is how the Stage A synthesis pass lost trajectories.
    gold_root = Path(args.gold_cache)
    set_gold_cache(factory=lambda slot: open_cache(gold_root / f"slot{slot}"))
    agent = AgentConfig(max_tool_rounds=args.max_tool_rounds, tool_timeout=420.0,
                        temperature=args.temperature, top_p=args.top_p,
                        max_tokens=8192, max_tool_output_chars=16000)
    client = ChatClient(base_url=args.base_url, model=args.adapter,
                        request_timeout=1800.0, max_attempts=2, retry_delay=30.0)
    work_root = paths.require_absolute(args.work_root, "work_root")
    work_root.mkdir(parents=True, exist_ok=True)

    done = 0
    pairs: list = []
    records: list = []
    import threading
    write_lock = threading.Lock()
    pair_fh = out_path.open("a" if already else "w", encoding="utf-8")
    rec_fh = records_path.open("a" if already else "w", encoding="utf-8")

    def run(job):
        nonlocal done
        try:
            rec = branch_one(job, client, agent, work_root, paths.PROJECT_ROOT,
                             attempts=args.attempts,
                             family_reading=family_reading)
        except Exception as exc:  # noqa: BLE001 - one job must not end the pass
            rec = {"task_id": job["task_id"], "turn": job["turn"],
                   "error_class": job["error_class"], "attempts": [],
                   "chosen_turn": None, "chosen_final": None,
                   "failure": str(exc)[:200]}
        done += 1
        if done % 25 == 0:
            print(f"  branch {done}/{len(selected)}", flush=True)
        return job, rec

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for job, rec in pool.map(run, selected):
            summary = {k: rec[k] for k in
                       ("task_id", "turn", "error_class", "chosen_final")
                       if k in rec}
            summary.setdefault("turn", job["turn"])
            pair = to_pair(job, rec)
            with write_lock:
                records.append(summary)
                rec_fh.write(json.dumps(summary) + "\n")
                rec_fh.flush()
                if pair is not None:
                    pairs.append(pair)
                    pair_fh.write(json.dumps(pair, ensure_ascii=False) + "\n")
                    pair_fh.flush()
    pair_fh.close()
    rec_fh.close()
    from collections import Counter
    report = {
        "candidates": len(jobs), "selected": len(selected),
        "allocation": allocation, "repaired": len(pairs),
        "repair_rate": round(len(pairs) / len(selected), 4) if selected else None,
        "by_error_class": dict(Counter(p["named_class"] for p in pairs)),
        "by_operation": dict(Counter(p["operation"] for p in pairs)),
        "attempts_per_job": args.attempts,
        "scorer_reading": args.scorer_reading,
        "pairs_file": str(args.out),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    Path(args.report).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
