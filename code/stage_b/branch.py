"""Construction (b): repair one turn, at the exact site of its failure.

A trajectory pair says "this whole attempt beat that one". A turn pair says
something narrower and, for the two named error classes, more useful: given
exactly this context, writing *that* raised and writing *this* did not. The
prefix is shared token for token, so the gradient lands on the turn rather than
on everything that led to it.

Producing one costs more than reading a rollout. The sandbox has to be brought
back to the state the failing turn met, which means replaying every earlier tool
call of that rollout into a fresh copy of the model; then the turn is resampled;
then, if it runs clean, the trajectory is finished so the repair can be scored
rather than merely observed not to raise. A turn that runs and still ruins the
edit is not a chosen side.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from stage_a import paths

paths.ensure_harness_on_path()

from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.prompts import TOOL_NAME, TOOL_SCHEMA  # noqa: E402
from modifc_harness.sandbox import Sandbox, SandboxCrash, SandboxTimeout, truncate  # noqa: E402


_CACHE: dict[str, Any] = {}
_LOCAL = threading.local()
_SLOT_LOCK = threading.Lock()
_SLOTS: dict[int, int] = {}


def thread_slot() -> int:
    """A small index that is this thread's for the life of the process.

    The branch pass runs its jobs on a thread pool inside one process, so a
    slot named by pid is the same directory for every job in flight, and two
    jobs rebuilding a gold model there write and delete each other's
    ``tmp*.ifc``. Handing each thread its own index separates them.
    """
    ident = threading.get_ident()
    with _SLOT_LOCK:
        if ident not in _SLOTS:
            _SLOTS[ident] = len(_SLOTS)
        return _SLOTS[ident]


def set_gold_cache(cache=None, factory: Optional[Callable[[int], Any]] = None) -> None:
    """Install the gold-model cache the repair pass scores against.

    ``factory`` takes a slot index and returns a cache; it is called once per
    worker thread, which is what keeps two threads out of one cache directory.
    A bare ``cache`` is the v1 call and stays supported: every thread then
    shares it, as it did.
    """
    _CACHE["cache"] = cache
    _CACHE["factory"] = factory


def gold_cache():
    """This thread's cache, built on first use when a factory was installed."""
    factory = _CACHE.get("factory")
    if factory is None:
        return _CACHE.get("cache")
    cache = getattr(_LOCAL, "cache", None)
    if cache is None:
        cache = factory(thread_slot())
        _LOCAL.cache = cache
    return cache


def last_assistant_reply(messages: Sequence[dict]) -> str:
    """The closing message of a trajectory.

    An under-specified task is answered by changing nothing and asking for the
    missing value, so the scorer reads this message; every other task ignores
    it.
    """
    for message in reversed(list(messages)):
        if message.get("role") == "assistant":
            return str(message.get("content") or "")
    return ""


def code_of(message: dict) -> Optional[str]:
    """The snippet an assistant turn asked to run, if any."""
    for call in message.get("tool_calls") or []:
        arguments = (call.get("function") or {}).get("arguments")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                return arguments
        if isinstance(arguments, dict) and isinstance(arguments.get("code"), str):
            return arguments["code"]
    return None


def replay_prefix(sandbox: Sandbox, prefix: Sequence[dict],
                  agent: AgentConfig) -> tuple[bool, str]:
    """Put the sandbox into the state the failing turn met."""
    for message in prefix:
        if message.get("role") != "assistant":
            continue
        code = code_of(message)
        if code is None:
            continue
        try:
            sandbox.execute(code, timeout=agent.tool_timeout)
        except (SandboxTimeout, SandboxCrash) as exc:
            return False, f"{type(exc).__name__}: {exc}"[:200]
    return True, ""


def free_gb(path: Path) -> float:
    """Free space on the filesystem holding ``path``, existing or not yet."""
    probe = Path(path)
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    return shutil.disk_usage(probe).free / 1024 ** 3


def wait_for_disk(path: Path, floor_gb: float, poll: float = 60.0,
                  limit: float = 1800.0) -> bool:
    """Hold new jobs while the disk is under ``floor_gb`` free.

    Each job copies a source model, and the pool's are up to 193 MB; a pass over
    thousands of them will fill a disk that looked comfortable when it started.
    The guard is a floor rather than a cap because the run is resumable: pausing
    costs time, running out costs the run.
    """
    waited = 0.0
    while free_gb(path) < floor_gb:
        if waited == 0.0:
            print(f"  disk at {free_gb(path):.0f} GB free, under the {floor_gb:.0f} GB "
                  "floor; pausing new branch jobs", flush=True)
        if waited >= limit:
            return False
        time.sleep(poll)
        waited += poll
    return True


def branch_one(job: dict, client, agent: AgentConfig, work_root: Path,
               project_root: Path, attempts: int = 4,
               max_finish_rounds: int = 8, disk_floor_gb: float = 30.0,
               family_reading: bool = False) -> dict:
    """Resample the failing turn, finish the ones that run, score them.

    Every attempt's sandbox directory is removed as the attempt ends, whatever
    the outcome. The first version deleted it only on success or on a sandbox
    crash, and the ordinary case for this pass is neither: a resampled turn that
    raises again returned early and left its copy of the model behind. Four
    thousand nine hundred of those filled the disk and killed the run.
    """
    from stage_a.goldmodels import resolve_gold
    from stage_a.scoring import score_prediction, scorer_config_for

    source = project_root / job["input_ifc"]
    record = {"task_id": job["task_id"], "operation": job["operation"],
              "category": job["category"], "edit_kind": job.get("edit_kind", ""),
              "building_id": job.get("building_id", ""),
              "schema": job.get("schema", ""), "turn": job["turn"],
              "error_class": job["error_class"], "sample": job["sample"],
              "attempts": [], "chosen_turn": None, "chosen_final": None}

    def run_attempt(work: Path, working: Path, outcome: dict):
        """One resample, executed and scored. Returns (turn, final)."""
        sandbox = Sandbox(input_ifc=source, working_ifc=working,
                          log_file=work / "sandbox.log")
        try:
            sandbox.start()
            ok, why = replay_prefix(sandbox, job["prefix_messages"], agent)
            if not ok:
                outcome["status"] = f"prefix replay failed: {why}"
                return None, None

            messages = list(job["prefix_messages"])
            response = client.chat(messages, tools=[TOOL_SCHEMA],
                                   temperature=agent.temperature,
                                   top_p=agent.top_p, max_tokens=agent.max_tokens)
            turn = {"role": "assistant", "content": response.content or ""}
            if response.tool_calls:
                turn["tool_calls"] = response.tool_calls
            code = code_of(turn)
            if code is None:
                outcome["status"] = "resampled turn made no tool call"
                return None, None
            snippet = sandbox.execute(code, timeout=agent.tool_timeout)
            if not snippet.ok:
                outcome["status"] = "resampled turn raised"
                outcome["error"] = (snippet.error or "").strip().split("\n")[-1][:160]
                return None, None

            # It ran. Finish the trajectory so the repair can be scored: a turn
            # that stops raising but ruins the edit is not a chosen side.
            messages = messages + [turn, {
                "role": "tool",
                "tool_call_id": (response.tool_calls or [{}])[0].get("id", ""),
                "name": TOOL_NAME,
                "content": truncate(snippet.raw_output(capture_stdout=True),
                                    agent.max_tool_output_chars)}]
            commits = snippet.commits
            rounds = 0
            while rounds < max_finish_rounds:
                nxt = client.chat(messages, tools=[TOOL_SCHEMA],
                                  temperature=agent.temperature, top_p=agent.top_p,
                                  max_tokens=agent.max_tokens)
                entry = {"role": "assistant", "content": nxt.content or ""}
                if nxt.tool_calls:
                    entry["tool_calls"] = nxt.tool_calls
                messages.append(entry)
                nxt_code = code_of(entry)
                if nxt_code is None:
                    break
                result = sandbox.execute(nxt_code, timeout=agent.tool_timeout)
                commits += result.commits
                messages.append({
                    "role": "tool",
                    "tool_call_id": (nxt.tool_calls or [{}])[0].get("id", ""),
                    "name": TOOL_NAME,
                    "content": truncate(result.raw_output(capture_stdout=True),
                                        agent.max_tool_output_chars)})
                rounds += 1
        except (SandboxCrash, SandboxTimeout) as exc:
            outcome["status"] = f"{type(exc).__name__}: {exc}"[:160]
            return None, None
        finally:
            sandbox.close()

        # The gold model is rebuilt from the task's own script when it is not on
        # disk, so the scorer needs the task record itself: `gold_model`,
        # `gold_script` and `verification` all come from it. A hand-assembled
        # stub raised `KeyError: 'gold_model'` inside the cache and, because the
        # attempt loop catches everything, turned every repair into a silent
        # failure and construction (b) into an empty file.
        task_record = job.get("task_record")
        if not task_record:
            outcome["status"] = "no task record attached; cannot rebuild the reference"
            return None, None
        gold = resolve_gold(task_record, gold_cache(), project_root)
        final = None
        if gold is not None and working.is_file():
            config = scorer_config_for(task_record) if family_reading else None
            score = score_prediction(task_record, working, project_root,
                                     gold_path=gold, config=config,
                                     reply=last_assistant_reply(messages)
                                           if family_reading else "")
            final = score.final
        outcome.update({"status": "ran", "commits": commits, "final": final,
                        "finish_rounds": rounds})
        return turn, final

    for attempt in range(1, attempts + 1):
        if not wait_for_disk(work_root, disk_floor_gb):
            record["attempts"].append({"attempt": attempt,
                                       "status": "aborted: disk below the floor"})
            break
        work = paths.require_absolute(
            work_root / f"{job['task_id']}_s{job['sample']}_t{job['turn']}_a{attempt}",
            "branch work dir")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        working = work / f"{source.stem}.ifc"
        outcome: dict[str, Any] = {"attempt": attempt}
        try:
            turn, final = run_attempt(work, working, outcome)
        except Exception as exc:  # noqa: BLE001 - one attempt must not end the job
            outcome["status"] = f"{type(exc).__name__}: {exc}"[:160]
            turn, final = None, None
        finally:
            # Unconditional: every early return above used to leak this directory.
            shutil.rmtree(work, ignore_errors=True)
        record["attempts"].append(outcome)
        if final is not None and final >= 0.90:
            record["chosen_turn"] = turn
            record["chosen_final"] = final
            break
    return record


def to_pair(job: dict, record: dict) -> Optional[dict]:
    """A single-turn preference pair, prompt shared token for token."""
    if record.get("chosen_turn") is None:
        return None
    from .pairs import canonical_prompt, normalise

    prefix = canonical_prompt(job["prefix_messages"][:2]) + \
        normalise(job["prefix_messages"][2:])
    return {
        "construction": "turn",
        "task_id": job["task_id"], "operation": job["operation"],
        "category": job["category"], "edit_kind": job.get("edit_kind", ""),
        "building_id": job.get("building_id", ""), "schema": job.get("schema", ""),
        "families": list(job.get("families") or ()),
        "underspecified": bool(job.get("underspecified")),
        "prompt_messages": prefix,
        "chosen_messages": normalise([record["chosen_turn"]]),
        "rejected_messages": normalise([job["rejected_turn"]]),
        "chosen_final": record["chosen_final"],
        "rejected_final": None,
        "reason": "branch_repair",
        "named_class": job["error_class"],
        "error_classes": {job["error_class"]: 1},
    }
