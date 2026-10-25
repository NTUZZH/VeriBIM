"""Run the template-inversion parser over benchmark tasks and score each one.

For every task: the parser reads the instruction (and nothing else from the
task record), writes a program or a question, the program runs in the
harness's own sandbox worker (modifc_harness.sandbox.Sandbox, with the guard
and the Landlock ruleset switched on by the environment) against a working copy
of the source model, and the file the sandbox leaves is scored by
stage_a.gate_eval._score_one under the family reading, which is the scoring
path the benchmark runs use (run_gate --scorer-reading family).  The task
record is passed to the scorer only.

Usage (from the project root, PYTHONPATH=code):
  python analysis/revision/parser_baseline/run_parser.py \
      --out results/per_task_parser.jsonl [--subset <ids.json>] [--workers 2]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import shutil
import sys
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "code"))
sys.path.insert(0, str(ROOT / "code" / "harness"))

TASKS = ROOT / "runs_local/bench_v4/tasks.v4c.jsonl"
SUB108 = ROOT / "runs_local/bench_v4/subset_108_hosted.v4c.json"
SUB324 = ROOT / "runs_local/bench_v4/subset_324.v4c.json"

_W: dict = {}


def _init(gold_cache: str, tmp: str) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    from stage_a import gate_eval
    gate_eval._init_scorer(str(ROOT), gold_cache, family_reading=True)
    _W["tmp"] = Path(tmp)


def _intent_summary(intent: dict) -> dict:
    """What the parser read, without the program text."""
    out = {"recognised": intent.get("recognised", False),
           "op": intent.get("op"), "clarify": intent.get("clarify")}
    if intent.get("recognised"):
        parse = dict(intent.get("parse") or {})
        out["parse"] = parse
        t = parse.get("t")
        if isinstance(t, dict):
            out["target_kind"] = t.get("k")
            out["target_family"] = t.get("fam")
    out["request_form"] = (intent.get("form") or {}).get("request")
    return out


def run_one(payload: tuple[dict, bool]) -> dict:
    record, keep = payload
    import grammar
    import codegen
    from modifc_harness.sandbox import Sandbox, SandboxCrash, SandboxTimeout
    from stage_a import gate_eval

    tid = record["task_id"]
    started = time.monotonic()
    row = {"task_id": tid, "operation": record["operation"],
           "category": record["category"], "ifc_version": record["ifc_version"],
           "tier": record.get("tier"), "origin": record.get("origin"),
           "underspecified": bool(record.get("clarification")),
           "instruction": record["instruction"]}
    # ---- the parser sees the instruction text only
    try:
        intent = grammar.parse(record["instruction"])
    except Exception as exc:  # noqa: BLE001
        intent = {"recognised": False, "error": repr(exc)}
    row["intent"] = _intent_summary(intent)
    row["recognised"] = bool(intent.get("recognised"))
    code = None
    if not intent.get("recognised"):
        reply = "I could not read this instruction, so I made no change."
    elif intent.get("clarify"):
        reply = codegen.question(intent)
    else:
        try:
            code = codegen.program(intent)
            reply = "The edit is done and the model is saved."
        except Exception as exc:  # noqa: BLE001
            row["codegen_error"] = f"{type(exc).__name__}: {exc}"
            reply = "I could not write a program for this instruction."
    row["asked"] = bool(intent.get("clarify")) and code is None \
        and bool(intent.get("recognised"))
    row["reply"] = reply
    row["program_written"] = code is not None
    if code is not None:
        row["program_body"] = codegen.body(intent)

    # ---- run in the harness sandbox, on a working copy of the source model
    source = ROOT / record["input_ifc"].replace("\\", "/")
    work = _W["tmp"] / "edited" / tid
    working = work / f"{source.stem}.ifc"
    log = _W["tmp"] / "logs" / f"{tid}.log"
    row["error"] = None
    row["commits"] = 0
    sandbox = Sandbox(input_ifc=source, working_ifc=working, log_file=log)
    t0 = time.monotonic()
    try:
        sandbox.start()
        if code is not None:
            result = sandbox.execute(code, timeout=420.0)
            row["commits"] = result.commits
            row["stdout"] = (result.stdout or "")[-2000:]
            if result.error:
                row["error"] = result.error[-3000:]
            if result.blocked:
                row["sandbox_blocked"] = result.blocked
    except (SandboxCrash, SandboxTimeout) as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        sandbox.close()
    row["run_seconds"] = round(time.monotonic() - t0, 2)
    row["edited_ifc"] = str(working)

    # ---- score with the benchmark's own path
    t0 = time.monotonic()
    try:
        scored = gate_eval._score_one((record, row))
    except Exception:  # noqa: BLE001
        scored = {"score": None, "score_error": traceback.format_exc()[-1500:]}
    row["score_seconds"] = round(time.monotonic() - t0, 2)
    row["score"] = scored.get("score")
    row["score_error"] = scored.get("score_error")
    sc = row["score"] or {}
    axes = [sc.get(k) for k in ("geometry", "semantics", "topology")]
    row["final"] = sc.get("final")
    row["completed"] = all(a is not None and a >= 0.9 for a in axes)
    row["seconds"] = round(time.monotonic() - started, 2)
    if not keep:
        shutil.rmtree(work, ignore_errors=True)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--tasks", default=str(TASKS),
                    help="task file (default: the 2,100-task benchmark)")
    ap.add_argument("--subset", default="")
    ap.add_argument("--ids", default="", help="comma-separated task ids")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--keep", default="", help="json list of ids whose edited "
                    "file is kept under tmp/edited")
    ap.add_argument("--tmp", default=str(HERE / "tmp"))
    ap.add_argument("--gold-cache", default=str(HERE / "tmp" / "gold_cache"))
    args = ap.parse_args(argv)

    records = [json.loads(line) for line in
               Path(args.tasks).open(encoding="utf-8")]
    if args.subset:
        wanted = json.loads(Path(args.subset).read_text())
        order = {t: i for i, t in enumerate(wanted)}
        records = sorted((r for r in records if r["task_id"] in order),
                         key=lambda r: order[r["task_id"]])
    if args.ids:
        wanted = set(args.ids.split(","))
        records = [r for r in records if r["task_id"] in wanted]
    keep = set(json.loads(Path(args.keep).read_text())) if args.keep else set()
    out = Path(args.out)
    if not out.is_absolute():
        out = HERE / out
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        for line in out.open(encoding="utf-8"):
            done.add(json.loads(line)["task_id"])
    todo = [(r, r["task_id"] in keep) for r in records if r["task_id"] not in done]
    print(f"{len(records)} tasks, {len(done)} already scored, {len(todo)} to run",
          flush=True)
    ctx = mp.get_context("spawn")
    started = time.monotonic()
    n = 0
    with ctx.Pool(processes=max(1, args.workers), initializer=_init,
                  initargs=(args.gold_cache, args.tmp),
                  ) as pool, \
            out.open("a", encoding="utf-8") as fh:
        for row in pool.imap_unordered(run_one, todo, chunksize=1):
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
            n += 1
            if n % 10 == 0 or n == len(todo):
                print(f"{time.strftime('%F %T')} {n}/{len(todo)} "
                      f"({(time.monotonic() - started) / 60:.1f} min)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
