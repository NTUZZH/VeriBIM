"""Rebuild a benchmark read's per-task file from what the rollouts left on disk.

A read whose driver died after every trajectory had finished, but before the
scorer wrote ``per_task_<adapter>.jsonl``, still has everything the rows are
made of: one transcript per task and the edited model each trajectory left
behind. This module turns those back into the rows ``gate_eval.rollout`` and
``gate_eval.score_rows`` would have written, and the summary ``run_gate``
would have written next to them. Scoring goes through ``gate_eval._score_one``
itself, with the same gold resolution and the same scorer reading, so a score
here is the harness's score and not a second implementation of it.

Not every row field is in the transcript. What is recovered, and how:

* stop_reason, finish_reasons, tool_rounds, tool_calls, well_formed_calls,
  compiling_calls, running_calls, reply and sandbox_blocked are read exactly.
* input_tokens and output_tokens are the sums over the recorded rounds plus
  the closing model turn. The closing turn (the answer without a tool call, or
  the tool request refused at the round budget) has no round record, so its
  usage is not in the transcript. For a model served by the local vLLM server
  it is rebuilt exactly with the server's own ``/tokenize`` endpoint, which
  renders the same chat template the request was rendered with; each task's
  last recorded round is re-tokenized as a check. For a hosted model it cannot
  be rebuilt and only the recorded rounds are counted (``--final-turn-tokens
  none``); the same holds for cache_read_tokens and cache_creation_tokens.
* commits is the number of ``commit()`` calls a trajectory made, which the
  sandbox reports per call but the transcript does not keep. It is estimated
  from the code of every well-formed call: each ``commit()`` call site counts
  once, and a call site at or after the line a snippet failed on does not
  count. committed is ``commits > 0``.
* duration_seconds was measured in memory. It is rebuilt from file times: the
  transcript is written the moment a trajectory returns, and the edited
  model's directory and the sandbox log are created within milliseconds of its
  start.
* error is exact for every stop reason whose message is fixed or recorded
  (completed, budget_exhausted, output_truncated, tool_timeout and
  sandbox_crash after a tool call). A context overflow from the local server
  carries a fixed message for a fixed request cap and model length, which is
  rebuilt. An inference error or a sandbox that failed at start-up leaves no
  message and is written as ``None``.

Every row whose value was estimated or could not be rebuilt is listed in the
notes file written next to the output.
"""

from __future__ import annotations

import argparse
import ast
import json
import multiprocessing as mp
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_CODE = Path(__file__).resolve().parent.parent
if str(_CODE) not in sys.path:
    sys.path.insert(0, str(_CODE))

from stage_a import paths  # noqa: E402

paths.ensure_harness_on_path()

from stage_a import gate_eval  # noqa: E402
from stage_a.gate_eval import _valid_python, as_task, load_subset, summarize  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.prompts import TOOL_SCHEMA  # noqa: E402

# The worker's own frame opens every traceback a snippet raises, so this marks
# an error reply even when the snippet printed before it failed.
_ERROR_MARK = re.compile(
    r'Traceback \(most recent call last\):\n  File "[^"\n]*sandbox_worker\.py", '
    r'line \d+, in run_snippet')
_FAIL_LINE = re.compile(r'File "<execute_ifc_code>", line (\d+)')

#: The message vLLM returns when prompt plus requested output exceed the model
#: length; it names the lower bound of the prompt, not its size, so for one
#: request cap and one model length it is the same text for every overflow.
_VLLM_OVERFLOW = (
    '{{"error":{{"message":"This model\'s maximum context length is {max_len} '
    'tokens. However, you requested {max_tokens} output tokens and your prompt '
    'contains at least {floor} input tokens, for a total of at least {total} '
    'tokens. Please reduce the length of the input prompt or the number of '
    'requested output tokens. (parameter=input_tokens, value={floor})",'
    '"type":"BadRequestError","param":"input_tokens","code":400}}}}')


# --------------------------------------------------------------- transcripts

def _btime(path: Path) -> Optional[float]:
    """Creation time of a file, or None where the file system has none."""
    try:
        out = subprocess.run(["stat", "-c", "%.9W", str(path)], capture_output=True,
                             text=True, check=True).stdout.strip()
        value = float(out)
        return value if value > 0 else None
    except (subprocess.CalledProcessError, ValueError, OSError):
        return None


def commit_count(calls: list[dict]) -> tuple[int, list[str]]:
    """``commit()`` calls made by the well-formed calls of one trajectory.

    Returns the count and the reasons it may be off: a call site inside a loop
    or a function may have run any number of times, one inside a branch may
    not have run at all, and a failed snippet whose failing line was cut out of
    the recorded output cannot be placed.
    """
    total = 0
    doubts: list[str] = []
    for call in calls:
        if not call.get("ok"):
            continue
        code = (call.get("args") or {}).get("code")
        if not isinstance(code, str):
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        sites = []
        guarded = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While, ast.AsyncFor, ast.FunctionDef,
                                 ast.AsyncFunctionDef, ast.Lambda, ast.If, ast.Try,
                                 ast.With, ast.comprehension, ast.ListComp,
                                 ast.GeneratorExp, ast.IfExp, ast.BoolOp)):
                for inner in ast.walk(node):
                    if inner is not node:
                        guarded.add(id(inner))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "commit"):
                sites.append(node)
        if not sites:
            continue
        output = str(call.get("output", ""))
        mark = None
        for mark in _ERROR_MARK.finditer(output):
            pass
        fail_line = None
        if mark is not None:
            found = _FAIL_LINE.search(output, mark.end())
            if found:
                fail_line = int(found.group(1))
            else:
                doubts.append("failed snippet with commit(), failing line not recorded")
        for node in sites:
            if mark is not None and (fail_line is None or node.lineno >= fail_line):
                continue
            total += 1
            if id(node) in guarded:
                doubts.append("commit() inside a loop, branch or function")
    return total, doubts


def _tokenize(url: str, model: str, messages: list[dict], generation: bool) -> list[int]:
    body = {"model": model, "messages": messages, "tools": [TOOL_SCHEMA],
            "add_generation_prompt": generation}
    request = urllib.request.Request(f"{url.rstrip('/')}/tokenize",
                                     data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return list(json.loads(response.read())["tokens"])


class TurnCounter:
    """Prompt and completion tokens of one model turn, from the server's template."""

    def __init__(self, url: str, model: str) -> None:
        self.url, self.model = url, model
        end = _tokenize(url, model, [{"role": "user", "content": "x"},
                                     {"role": "assistant", "content": "y"}], False)
        # The rendered assistant turn closes with the end-of-turn token and a
        # newline; the model generates the first and never the second.
        self.end_of_turn, self.newline = end[-2], end[-1]

    def turn(self, messages: list[dict], index: int, finish_reason: str) -> tuple[int, int, str]:
        before = _tokenize(self.url, self.model, messages[:index], True)
        after = _tokenize(self.url, self.model, messages[:index + 1], False)
        note = ""
        if after[:len(before)] != before:
            note = "rendered turn is not an extension of its prompt"
        generated = len(after) - len(before)
        if after[-1:] == [self.newline]:
            generated -= 1
        if finish_reason == "length":
            # Cut off at the cap: the end-of-turn token was never generated.
            generated -= 1
            note = note or "closing turn hit the output cap"
        return len(before), generated, note

    def prompt(self, messages: list[dict], index: int) -> int:
        return len(_tokenize(self.url, self.model, messages[:index], True))


def build_row(record: dict, transcript: dict, *, adapter: str, run_dir: Path,
              edited_path: Path, style: str, guard: bool,
              counter: Optional[TurnCounter], agent: AgentConfig,
              model_len: int) -> tuple[dict, dict]:
    """One row as ``gate_eval.rollout`` writes it, and the notes on its fields."""
    notes: dict[str, Any] = {}
    task = as_task(record, paths.PROJECT_ROOT)
    working = run_dir / adapter / "edited" / record["task_id"] / f"{task.input_ifc.stem}.ifc"
    iterations = transcript.get("iterations") or []
    messages = transcript.get("messages") or []
    finish_reasons = transcript.get("finish_reasons") or []
    stop = transcript["stop_reason"]

    calls = [c for r in iterations for c in r["tool_calls"]]
    well_formed = [c for c in calls if c.get("ok")]
    compiles = [c for c in well_formed if _valid_python(c["args"].get("code", ""))]
    ran = [c for c in well_formed
           if not str(c.get("output", "")).startswith("Traceback")]

    commits, doubts = commit_count(calls)
    if doubts:
        notes["commits_doubt"] = sorted(set(doubts))

    input_tokens = sum(int(r.get("input_tokens") or 0) for r in iterations)
    output_tokens = sum(int(r.get("output_tokens") or 0) for r in iterations)
    cache_read = sum(int(r.get("cache_read_tokens") or 0) for r in iterations)
    cache_creation = sum(int(r.get("cache_creation_tokens") or 0) for r in iterations)
    assistant_at = [i for i, m in enumerate(messages) if m.get("role") == "assistant"]
    unrecorded = len(finish_reasons) - len(iterations)
    if unrecorded not in (0, 1) or len(assistant_at) != len(finish_reasons):
        notes["turn_mismatch"] = {"finish_reasons": len(finish_reasons),
                                  "rounds": len(iterations),
                                  "assistant_messages": len(assistant_at)}
    if unrecorded == 1 and assistant_at:
        if counter is None:
            notes["closing_turn_tokens"] = "not in transcript, not counted"
            if style == "anthropic_native":
                notes["closing_turn_cache_tokens"] = "not in transcript, not counted"
        else:
            final = assistant_at[-1]
            prompt, generated, note = counter.turn(messages, final, finish_reasons[-1])
            input_tokens += prompt
            output_tokens += generated
            notes["closing_turn_tokens"] = {"input": prompt, "output": generated,
                                            "source": "server tokenizer"}
            if note:
                notes["closing_turn_doubt"] = note
            if iterations and len(assistant_at) >= 2:
                check = counter.prompt(messages, assistant_at[len(iterations) - 1])
                recorded = int(iterations[-1].get("input_tokens") or 0)
                if check != recorded:
                    notes["tokenizer_check_failed"] = {"recorded": recorded, "rebuilt": check}

    error = None
    if stop == "output_truncated":
        error = "model turn reached the output token cap without a tool call"
    elif stop in ("tool_timeout", "sandbox_crash") and calls:
        last = str(calls[-1].get("output", ""))
        prefix = f"{stop}: "
        if last.startswith(prefix) and not calls[-1].get("ok"):
            error = last[len(prefix):]
        else:
            notes["error"] = "message not in transcript"
    elif stop == "context_overflow" and counter is not None:
        floor = model_len - agent.max_tokens + 1
        error = _VLLM_OVERFLOW.format(max_len=model_len, max_tokens=agent.max_tokens,
                                      floor=floor, total=floor + agent.max_tokens)
        notes["error"] = "fixed server message, rebuilt"
    elif stop in ("context_overflow", "inference_error", "sandbox_crash",
                  "token_budget", "duplicate_loop"):
        notes["error"] = "message not in transcript"

    reply = ""
    for message in messages:
        if message.get("role") == "assistant" and message.get("content"):
            reply = message["content"]

    duration = None
    ended = None
    transcript_file = run_dir / adapter / "transcripts" / f"{record['task_id']}.json"
    try:
        ended = transcript_file.stat().st_mtime
    except OSError:
        pass
    starts = [t for t in (_btime(working.parent), _btime(working),
                          _btime(run_dir / adapter / "logs" / f"{record['task_id']}.log"))
              if t is not None]
    if ended is not None and starts:
        duration = max(0.0, ended - min(starts))
        notes["duration"] = "from file times"
    else:
        duration = 0.0
        notes["duration"] = "not recoverable, written as 0.0"

    row = {
        "adapter": adapter,
        "task_id": record["task_id"],
        "operation": record["operation"],
        "category": record["category"],
        "edit_kind": record.get("edit_kind", ""),
        "stop_reason": stop,
        # Recorded per round by the agent loop; zero for a transcript written
        # before crash recovery existed.
        "sandbox_crashes": sum(int(r.get("sandbox_crashes") or 0) for r in iterations),
        "tool_rounds": len(iterations),
        "tool_calls": len(calls),
        "well_formed_calls": len(well_formed),
        "compiling_calls": len(compiles),
        "running_calls": len(ran),
        "commits": commits,
        "committed": commits > 0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "finish_reasons": finish_reasons,
        "duration_seconds": round(duration, 2),
        "error": error,
        "reply": reply or "",
        "edited_ifc": str(working),
        "edited_exists": edited_path.is_file(),
    }
    if style == "anthropic_native":
        row["cache_read_tokens"] = cache_read
        row["cache_creation_tokens"] = cache_creation
    if guard:
        row["sandbox_blocked"] = sum(len(c.get("blocked") or []) for c in calls)
    return row, notes


# ------------------------------------------------------------------- scoring

def _init_worker(project_root: str, cache_root: str, family: bool) -> None:
    gate_eval._init_scorer(project_root, cache_root, family)


def _score(payload: tuple[dict, dict]) -> dict:
    """``gate_eval._score_one``, with the task's gold model dropped afterwards.

    No two tasks share a gold model, so a resident one is never asked for again
    and only holds disk.
    """
    try:
        return gate_eval._score_one(payload)
    except Exception as exc:  # noqa: BLE001 - retried once at the end of the run
        return {"task_id": payload[1]["task_id"], "score": None,
                "score_error": f"{_RETRY_TAG}{type(exc).__name__}: {exc}"}
    finally:
        cache = gate_eval._CTX.get("cache")
        if cache is not None:
            try:
                cache.clear()
            except Exception:  # noqa: BLE001
                pass


_RETRY_TAG = "rescore exception, "
#: Score errors that say nothing about the prediction, only about this machine
#: at the time (a gold rebuild that failed for want of disk, a worker error).
_TRANSIENT = ("gold model could not be rebuilt from its script", _RETRY_TAG)


def _wait_for_disk(where: Path, need_gb: float, log) -> None:
    """Hold new work while the disk is nearly full.

    A gold model rebuilt onto a full disk fails, and the scorer records that
    as an unscorable task; waiting keeps a full disk from turning into scores.
    """
    warned = False
    while shutil.disk_usage(where).free < need_gb * 1024 ** 3:
        if not warned:
            log(f"  free disk under {need_gb} GB at {where}; waiting")
            warned = True
        time.sleep(30)
    if warned:
        log("  disk free again; resuming")


class RssWatch(threading.Thread):
    """Resident memory of this process and all its descendants, sampled."""

    def __init__(self, every: float = 2.0) -> None:
        super().__init__(daemon=True)
        self.every = every
        self.peak_kb = 0
        self.current_kb = 0
        self._stop = threading.Event()

    @staticmethod
    def _tree_kb(root: int) -> int:
        children: dict[int, list[int]] = {}
        rss: dict[int, int] = {}
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open(f"/proc/{entry}/stat") as fh:
                    parts = fh.read().rsplit(")", 1)[1].split()
                ppid = int(parts[1])
                with open(f"/proc/{entry}/status") as fh:
                    for line in fh:
                        if line.startswith("VmRSS:"):
                            rss[int(entry)] = int(line.split()[1])
                            break
                children.setdefault(ppid, []).append(int(entry))
            except (OSError, IndexError, ValueError):
                continue
        total, stack = 0, [root]
        while stack:
            pid = stack.pop()
            total += rss.get(pid, 0)
            stack.extend(children.get(pid, []))
        return total

    def run(self) -> None:
        while not self._stop.is_set():
            self.current_kb = self._tree_kb(os.getpid())
            self.peak_kb = max(self.peak_kb, self.current_kb)
            self._stop.wait(self.every)

    def stop(self) -> None:
        self._stop.set()


def score_all(records: list[dict], rows: list[dict], score_paths: dict[str, Path],
              workers: int, cache_root: Path, family: bool, archive: Optional[Path],
              extract_dir: Path, recycle: int, log,
              min_free_gb: float = 3.0, large_mb: float = 40.0,
              hold_rss_mb: float = 5500.0, watch=None) -> dict[str, dict]:
    """Score every row through the harness's scorer, committed or not."""
    by_id = {r["task_id"]: r for r in records}
    context = mp.get_context("spawn")
    scored: dict[str, dict] = {}
    pending: dict[str, Any] = {}
    extracted: dict[str, Path] = {}
    started = time.monotonic()
    slots = threading.BoundedSemaphore(workers + 1)

    def settle(block: bool) -> None:
        for task_id in list(pending):
            result = pending[task_id]
            if block or result.ready():
                out = result.get()
                scored[out["task_id"]] = out
                del pending[task_id]
                path = extracted.pop(task_id, None)
                if path is not None:
                    shutil.rmtree(path.parent, ignore_errors=True)
                slots.release()
                if len(scored) % 25 == 0:
                    log(f"  scored {len(scored)}/{len(rows)} "
                        f"({(time.monotonic() - started) / 60:.1f} min)")

    large: dict[str, bool] = {}

    def submit(pool, row: dict, predicted: Path) -> None:
        while not slots.acquire(timeout=0.5):
            settle(False)
        _wait_for_disk(cache_root, min_free_gb, log)
        # A scoring worker holding a large model (its prediction, its gold and
        # their meshes) reaches several gigabytes, so two large models are
        # never scored at the same time; the order of the rows is unaffected.
        try:
            is_large = predicted.stat().st_size >= large_mb * 1e6
        except OSError:
            is_large = False
        while is_large and any(large.get(t) for t in pending):
            settle(False)
            time.sleep(0.2)
        while watch is not None and pending and watch.current_kb > hold_rss_mb * 1024:
            settle(False)
            time.sleep(0.5)
        large[row["task_id"]] = is_large
        payload_row = dict(row)
        payload_row["edited_ifc"] = str(predicted)
        pending[row["task_id"]] = pool.apply_async(
            _score, ((by_id[row["task_id"]], payload_row),))

    with context.Pool(processes=max(1, workers), maxtasksperchild=max(1, recycle),
                      initializer=_init_worker,
                      initargs=(str(paths.PROJECT_ROOT), str(cache_root), family)) as pool:
        wanted = {r["task_id"]: r for r in rows}
        if archive is not None:
            done_ids: set[str] = set()
            with tarfile.open(archive, "r:gz") as tar:
                for member in tar:
                    if not member.isfile():
                        continue
                    parts = Path(member.name).parts
                    if len(parts) != 3 or parts[0] != "edited" or parts[1] not in wanted:
                        continue
                    task_id = parts[1]
                    row = wanted[task_id]
                    if Path(row["edited_ifc"]).name != parts[2] or task_id in done_ids:
                        continue
                    target = extract_dir / task_id / parts[2]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with tar.extractfile(member) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst, 1 << 20)
                    extracted[task_id] = target
                    done_ids.add(task_id)
                    submit(pool, row, target)
            for task_id, row in wanted.items():
                if task_id not in done_ids:
                    submit(pool, row, extract_dir / task_id / "absent.ifc")
        else:
            for row in rows:
                submit(pool, row, score_paths[row["task_id"]])
        while pending:
            settle(False)
            time.sleep(0.2)
        # One more attempt for anything that failed for a reason of the
        # machine rather than of the prediction; an archive read keeps its
        # models packed, so those are retried from the same archive order.
        again = [wanted[t] for t, o in scored.items()
                 if str(o.get("score_error") or "").startswith(_TRANSIENT)]
        if again and archive is None:
            log(f"  retrying {len(again)} tasks: "
                + ", ".join(r["task_id"] for r in again[:5]))
            for row in again:
                submit(pool, row, score_paths[row["task_id"]])
            while pending:
                settle(False)
                time.sleep(0.2)
        elif again:
            log(f"  {len(again)} tasks failed for a transient reason and were "
                "not retried from the archive: "
                + ", ".join(r["task_id"] for r in again[:5]))
    return scored


# ---------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rescore-run", description=__doc__.split("\n\n")[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--tasks-file", required=True)
    ap.add_argument("--subset", required=True)
    ap.add_argument("--gold-cache", required=True,
                    help="root of the per-worker gold caches; give a directory no "
                         "live read is using")
    ap.add_argument("--scorer-reading", choices=("published", "family"), default="published")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--recycle-after", type=int, default=10,
                    help="tasks a scoring worker takes before it is replaced")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="",
                    help="per-task output; the summary is written next to it. "
                         "Without it the harness's own paths are used and an "
                         "existing file is never overwritten")
    ap.add_argument("--notes", default="",
                    help="per-task reconstruction notes (default: next to the output)")
    ap.add_argument("--label", default="")
    ap.add_argument("--edited-archive", default="",
                    help="edited.tar.gz of a packed read; models are extracted one "
                         "at a time under --extract-dir and removed after scoring")
    ap.add_argument("--extract-dir", default="")
    ap.add_argument("--final-turn-tokens", choices=("auto", "tokenize", "none"),
                    default="auto",
                    help="auto: use the server tokenizer when --tokenize-url serves "
                         "the adapter, otherwise count recorded rounds only")
    ap.add_argument("--tokenize-url", default="http://127.0.0.1:8000")
    ap.add_argument("--model-len", type=int, default=32768,
                    help="the local server's --max-model-len, for the overflow message")
    ap.add_argument("--request-style", default=None,
                    help="VERIBIM_REQUEST_STYLE of the read (default: this environment's)")
    ap.add_argument("--sandbox-guard", choices=("0", "1"), default=None,
                    help="VERIBIM_SANDBOX_GUARD of the read (default: this environment's)")
    # The protocol values of the read, as run_gate takes them.
    ap.add_argument("--max-tool-rounds", type=int, default=22)
    ap.add_argument("--tool-timeout", type=float, default=420.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-tool-output-chars", type=int, default=16000)
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--top-p", type=float, default=1.0)
    ap.add_argument("--min-free-gb", type=float, default=3.0,
                    help="hold new scoring work while the disk has less free")
    ap.add_argument("--large-mb", type=float, default=40.0,
                    help="edited models this size or larger are scored one at a time")
    ap.add_argument("--hold-rss-mb", type=float, default=5500.0,
                    help="hold new scoring work while the process tree is this large")
    ap.add_argument("--rows-only", action="store_true",
                    help="rebuild the trajectory fields and skip scoring (a check)")
    ap.add_argument("--allow-missing", action="store_true",
                    help="skip tasks without a transcript instead of stopping")
    args = ap.parse_args(argv)

    started = time.monotonic()
    watch = RssWatch()
    watch.start()

    def log(text: str) -> None:
        print(f"{datetime.now():%H:%M:%S} {text}", flush=True)

    run_dir = paths.require_absolute(args.run_dir, "run_dir")
    adapter = args.adapter
    if args.out:
        out = Path(args.out)
        summary_path = out.parent / f"summary_{adapter}.json"
    else:
        out = Path(args.run_dir) / f"per_task_{adapter}.jsonl"
        summary_path = Path(args.run_dir) / f"summary_{adapter}.json"
        for existing in (out, summary_path):
            if existing.exists():
                log(f"{existing} exists; refusing to overwrite (give --out)")
                return 2
    notes_path = Path(args.notes) if args.notes else out.parent / f"rescore_notes_{adapter}.json"
    style = args.request_style if args.request_style is not None else \
        os.environ.get("VERIBIM_REQUEST_STYLE", "")
    guard = (args.sandbox_guard if args.sandbox_guard is not None else
             os.environ.get("VERIBIM_SANDBOX_GUARD", "")) == "1"
    agent = AgentConfig(max_tool_rounds=args.max_tool_rounds, tool_timeout=args.tool_timeout,
                        temperature=args.temperature, top_p=args.top_p,
                        max_tokens=args.max_tokens,
                        max_tool_output_chars=args.max_tool_output_chars)

    counter = None
    if args.final_turn_tokens != "none":
        served = {}
        try:
            with urllib.request.urlopen(f"{args.tokenize_url.rstrip('/')}/v1/models",
                                        timeout=20) as response:
                served = {m["id"]: m for m in json.loads(response.read())["data"]}
        except Exception as exc:  # noqa: BLE001
            if args.final_turn_tokens == "tokenize":
                log(f"tokenizer server unreachable: {exc}")
                return 2
        if adapter in served:
            # The tokenizer of an adapter is its base model's.
            base = served[adapter].get("parent") or adapter
            counter = TurnCounter(args.tokenize_url, base)
        elif args.final_turn_tokens == "tokenize":
            log(f"{adapter} is not served at {args.tokenize_url}")
            return 2
    log(f"closing-turn tokens: {'server tokenizer' if counter else 'recorded rounds only'}; "
        f"request style {style or 'default'}; sandbox guard {guard}")

    records = load_subset(Path(args.subset), Path(args.tasks_file))
    if args.limit:
        records = records[: args.limit]

    rows: list[dict] = []
    all_notes: dict[str, dict] = {}
    score_paths: dict[str, Path] = {}
    missing_transcripts = []
    for i, record in enumerate(records, 1):
        task_id = record["task_id"]
        tfile = run_dir / adapter / "transcripts" / f"{task_id}.json"
        if not tfile.is_file():
            missing_transcripts.append(task_id)
            continue
        transcript = json.loads(tfile.read_text(encoding="utf-8"))
        task = as_task(record, paths.PROJECT_ROOT)
        harness_path = run_dir / adapter / "edited" / task_id / f"{task.input_ifc.stem}.ifc"
        if args.edited_archive:
            probe = Path(args.extract_dir or notes_path.parent / "_extract") / "never.ifc"
        else:
            probe = harness_path
        row, notes = build_row(record, transcript, adapter=adapter, run_dir=run_dir,
                               edited_path=probe, style=style, guard=guard,
                               counter=counter, agent=agent, model_len=args.model_len)
        score_paths[task_id] = harness_path
        rows.append(row)
        if notes:
            all_notes[task_id] = notes
        if i % 200 == 0:
            log(f"  rows {i}/{len(records)}")
    if missing_transcripts and not args.allow_missing:
        log(f"{len(missing_transcripts)} transcripts missing, e.g. {missing_transcripts[:3]}")
        return 2
    log(f"{len(rows)} rows rebuilt from transcripts; scoring with {args.workers} workers")

    if args.rows_only:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        notes_path.write_text(json.dumps(all_notes, indent=1, ensure_ascii=False),
                              encoding="utf-8")
        watch.stop()
        log(f"rows only: wrote {out} and {notes_path}")
        return 0

    archive = Path(args.edited_archive) if args.edited_archive else None
    extract_dir = Path(args.extract_dir) if args.extract_dir else notes_path.parent / "_extract"
    if archive is not None:
        with tarfile.open(archive, "r:gz") as tar:
            inside = {m.name for m in tar.getmembers() if m.isfile()}
        for row in rows:
            name = f"edited/{row['task_id']}/{Path(row['edited_ifc']).name}"
            row["edited_exists"] = name in inside
    scored = score_all(records, rows, score_paths, args.workers, Path(args.gold_cache),
                       args.scorer_reading == "family", archive, extract_dir,
                       args.recycle_after, log, args.min_free_gb,
                       args.large_mb, args.hold_rss_mb, watch)

    merged = []
    for row in rows:
        entry = scored.get(row["task_id"], {})
        row = dict(row)
        row["score"] = entry.get("score")
        row["score_error"] = entry.get("score_error")
        row["final"] = (entry.get("score") or {}).get("final")
        merged.append(row)

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".partial")
    with tmp.open("w", encoding="utf-8") as fh:
        for row in merged:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    tmp.replace(out)

    summary = summarize(adapter, merged, agent)
    summary["per_task_file"] = str(out)
    summary["subset"] = str(args.subset)
    summary["scorer_reading"] = args.scorer_reading
    summary["label"] = args.label
    summary["protocol_conformant"] = (args.max_tool_rounds >= 22 and args.max_tokens >= 8192
                                      and args.tool_timeout >= 420.0
                                      and args.temperature == 0.0)
    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    watch.stop()
    summary["rebuilt_offline"] = {
        "script": "code/stage_a/rescore_run.py",
        "closing_turn_tokens": "server tokenizer" if counter else "recorded rounds only",
        "estimated_fields": ["commits", "committed", "duration_seconds"],
        "notes_file": str(notes_path),
        "missing_transcripts": missing_transcripts,
        "wall_seconds": round(time.monotonic() - started, 1),
        "peak_rss_mb": round(watch.peak_kb / 1024, 1),
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    notes_path.write_text(json.dumps(all_notes, indent=1, ensure_ascii=False), encoding="utf-8")
    log(json.dumps({k: summary[k] for k in ("adapter", "n_scored", "mean_final",
                                            "commit_rate", "stop_reasons")}))
    log(f"wrote {out}, {summary_path}, {notes_path}; "
        f"{summary['rebuilt_offline']['wall_seconds']} s, peak RSS "
        f"{summary['rebuilt_offline']['peak_rss_mb']} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
