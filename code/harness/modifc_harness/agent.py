"""The agent loop: one task, one trajectory, one edited IFC file.

Budget semantics follow the published BIM-Edit runs rather than their config
file. Those runs set ``max_tool_calls: 20`` but enforced it through a LangGraph
recursion limit of 45 super-steps, which admits 23 model turns and 22 executed
tool rounds. The loop below reproduces that exactly:

* at most ``max_tool_rounds`` (22) tool rounds are executed;
* one further model turn is taken after the last of them, so the model gets the
  chance to answer instead of calling the tool again;
* if that turn asks for another tool call, the run stops as budget exhausted and
  the requested call is not executed.

A run also ends as soon as the model answers without a tool call. Either way the
file on disk at that moment is the artifact, and nothing is written to it after
the loop returns.

Two further stops exist for training and are off at their defaults, so an
evaluation run takes neither of them. A transcript budget in tokens stops a
trajectory before it grows past the length the trainer can encode, because a
trajectory discarded after it was rolled out and scored takes the reward spread
of its group with it. A repeat stop ends a trajectory that has settled into
sending the same code and reading the same answer, because those rounds teach
nothing and spend the budget the trajectory needs to recover.

The transcript budget bounds the returned transcript, and the bound is worth
stating exactly. It rests on the exact token counter the caller supplies, which
measures the transcript the way the trainer renders it, so the budget cannot be
switched on without one: a run that sets a budget and passes no counter is
refused before it starts. Before every request the transcript holds at most
``max_transcript_tokens - min_turn_tokens`` tokens, because a larger transcript
stops the run instead of sending the request, and the request itself is capped
at the tokens that are left inside the budget. The transcript therefore never
exceeds ``max_transcript_tokens`` at the end of any model turn. What is
appended after a turn is the result of the calls that turn asked for, and when
the run stops there those results are read by nobody: no model turn is
conditioned on them, and only assistant tokens carry gradient. They are removed
from the transcript that is returned, so the returned transcript is at most
``max_transcript_tokens`` plus the few tokens of the assistant turn's own
header and end marker. At ``--max-seq 12288`` and ``--max-transcript-tokens
11776`` that leaves a margin of 512 tokens.

A snippet can kill the worker process outright. The IFC library is compiled
code, and touching an entity after it was removed (``ifc.remove`` or
``root.remove_product``, then reading an attribute or calling ``is_a`` or
``id`` on the old handle) ends the worker with SIGSEGV instead of raising a
Python exception. Such a crash costs the model the in-memory state and nothing
more, the same for every model: the loop starts a fresh worker on the file as
the last ``commit()`` left it (or on a fresh copy of the input model when that
file is missing or incomplete), returns a fixed message as the tool output,
counts the round as used, and continues. The third crash in one trajectory
still ends it as ``sandbox_crash``. A tool timeout still ends the trajectory
at once.
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .client import ChatClient, ContextOverflow, TransportError
from .config import AgentConfig
from .prompts import SYSTEM_PROMPT, TOOL_NAME, TOOL_SCHEMA, build_user_message
from .sandbox import Sandbox, SandboxCrash, SandboxTimeout, has_step_trailer, truncate
from .tasks import Task

STOP_COMPLETED = "completed"
STOP_BUDGET = "budget_exhausted"
STOP_TOOL_TIMEOUT = "tool_timeout"
STOP_SANDBOX_CRASH = "sandbox_crash"
STOP_INFERENCE_ERROR = "inference_error"
STOP_CONTEXT_OVERFLOW = "context_overflow"
STOP_OUTPUT_TRUNCATED = "output_truncated"
STOP_TOKEN_BUDGET = "token_budget"
STOP_DUPLICATE_LOOP = "duplicate_loop"

#: The crash that ends a trajectory: the first two are recovered, the third
#: stops the run as ``sandbox_crash``.
MAX_SANDBOX_CRASHES = 3

#: What the model reads back as the tool output after a recovered crash.
CRASH_MESSAGE_LAST_COMMIT = (
    "The sandbox process crashed while running this code (a segmentation "
    "fault in the IFC library, usually from touching an entity after removing it). A fresh sandbox was started on the last committed model; every "
    "in-memory change since the last commit is lost. Re-inspect the model "
    "before continuing.")
CRASH_MESSAGE_INPUT = (
    "The sandbox process crashed while running this code (a segmentation "
    "fault in the IFC library, usually from touching an entity after removing it). The last committed file could not be read, so a fresh sandbox "
    "was started on the original input model; every change made so far is "
    "lost. Re-inspect the model before continuing.")
#: The reply to a further tool call of the same turn, which is not run.
CRASH_SKIPPED_MESSAGE = (
    "Not executed: the sandbox crashed on an earlier tool call of this turn "
    "and was restarted. Send this code again if it is still needed.")


@dataclass
class TrajectoryResult:
    task_id: str
    stop_reason: str
    model_output: str
    messages: list[dict]
    iterations: list[dict]
    tool_rounds: int
    tool_calls: int
    llm_calls: int
    commits: int
    prompt_tokens: int
    completion_tokens: int
    duration_seconds: float
    copy_seconds: float
    finish_reasons: list[str] = field(default_factory=list)
    truncated_tool_outputs: int = 0
    reasoning_chars: int = 0
    error: str | None = None
    error_type: str | None = None
    extra: dict = field(default_factory=dict)
    #: Prompt tokens read from and written to the provider's prompt cache,
    #: summed over the trajectory. Part of ``prompt_tokens``; zero on every
    #: endpoint that does not report a cache.
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    #: File, process and network attempts the sandbox guard refused, summed
    #: over the trajectory; zero when the guard is off.
    sandbox_blocked: int = 0
    #: Worker crashes in this trajectory, recovered ones included.
    sandbox_crashes: int = 0


def _file_signature(path: Path) -> tuple[int, int] | None:
    try:
        st = Path(path).stat()
    except OSError:
        return None
    return (st.st_size, st.st_mtime_ns)


def _restart_after_crash(sandbox: Sandbox, working_ifc: Path) -> dict:
    """Replace a crashed worker with a fresh one; return what was done.

    The fresh worker opens the working file as the last ``commit()`` left it
    when that file ends on the STEP trailer and opens; otherwise the input
    model is copied over it first, as at the start of the task. Raises
    SandboxCrash or SandboxTimeout when neither start succeeds.
    """
    t0 = time.monotonic()
    sandbox.close()
    info: dict = {"returncode": sandbox.last_returncode}
    source = "last_commit"
    if not has_step_trailer(working_ifc):
        source = "input"
        info["fallback_reason"] = "working file missing, empty or without the STEP trailer"
    else:
        try:
            sandbox.start(copy_input=False)
        except (SandboxCrash, SandboxTimeout) as exc:
            sandbox.close()
            source = "input"
            # The last line of the worker's start-up traceback names the
            # error without the machine's paths.
            lines = [line for line in str(exc).splitlines() if line.strip()]
            last = lines[-1].strip() if lines else type(exc).__name__
            info["fallback_reason"] = f"working file did not open: {last[:300]}"
    if source == "input":
        sandbox.start(copy_input=True)
    info["restarted_from"] = source
    info["restart_seconds"] = round(time.monotonic() - t0, 3)
    return info


def _bad_arguments_message(raw: str) -> str:
    return (
        "The tool call could not be parsed. Its `code` argument was not valid: "
        f"{raw[:400]}. Send the Python source as a plain string in the `code` argument."
    )


def run_task(
    task: Task,
    working_ifc: Path,
    client: ChatClient,
    agent_config: AgentConfig,
    log_file: Path,
    python_executable: str | None = None,
    count_tokens: Optional[Callable[[list[dict]], int]] = None,
    request_logprobs: bool = False,
) -> TrajectoryResult:
    """One task, one trajectory.

    ``count_tokens`` returns the exact token length of the next request's
    prompt for the messages it is given, rendered with the tool schema and the
    generation prompt. It is used only when ``agent_config`` sets a transcript
    budget, and it is required there: the budget's bound on the returned
    transcript is only as good as the count it stops on, so a budget with no
    counter raises instead of running on a guess.

    ``request_logprobs`` asks the server for the log-probability of every
    generated token and keeps them per model turn. It is off by default, so the
    request the server receives is unchanged.
    """
    if agent_config.max_transcript_tokens > 0 and count_tokens is None:
        raise ValueError(
            "a transcript budget needs the token counter that measures the "
            "transcript: max_transcript_tokens is "
            f"{agent_config.max_transcript_tokens} and count_tokens is None")
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(task.prompt, str(working_ifc))},
    ]
    iterations: list[dict] = []
    tool_rounds = 0
    tool_calls = 0
    llm_calls = 0
    commits = 0
    prompt_tokens = 0
    completion_tokens = 0
    cache_read_tokens = 0
    cache_creation_tokens = 0
    model_output = ""
    finish_reasons: list[str] = []
    truncated_tool_outputs = 0
    reasoning_chars = 0
    stop_reason = STOP_COMPLETED
    error: str | None = None
    error_type: str | None = None
    sandbox_blocked = 0
    sandbox_crashes = 0

    budget_on = agent_config.max_transcript_tokens > 0
    dup_on = agent_config.dup_stop > 0
    # What the counter last reported for the transcript, which is what the
    # budget is spent against.
    token_budget_estimate = 0
    repeats: Counter = Counter()
    turn_logprobs: list[list[float]] = []

    started = time.monotonic()
    sandbox = Sandbox(
        input_ifc=task.input_ifc,
        working_ifc=working_ifc,
        log_file=log_file,
        python_executable=python_executable,
    )
    try:
        sandbox.start()
    except (SandboxCrash, SandboxTimeout) as exc:
        return TrajectoryResult(
            task_id=task.task_id,
            stop_reason=STOP_SANDBOX_CRASH,
            model_output="",
            messages=messages,
            iterations=[],
            tool_rounds=0,
            tool_calls=0,
            llm_calls=0,
            commits=0,
            prompt_tokens=0,
            completion_tokens=0,
            duration_seconds=time.monotonic() - started,
            copy_seconds=sandbox.copy_seconds,
            error=str(exc),
            error_type=type(exc).__name__,
        )

    try:
        while True:
            request_max_tokens = agent_config.max_tokens
            if budget_on:
                token_budget_estimate = int(count_tokens(messages))
                reserve = (agent_config.max_transcript_tokens
                           - token_budget_estimate)
                if reserve < agent_config.min_turn_tokens:
                    # The file as it stands on disk is the artifact, exactly as
                    # it is when the round budget runs out.
                    stop_reason = STOP_TOKEN_BUDGET
                    error = (f"transcript at {token_budget_estimate} tokens of "
                             f"{agent_config.max_transcript_tokens}")
                    error_type = "TokenBudget"
                    break
                request_max_tokens = min(agent_config.max_tokens, reserve)

            extra_request: dict = {"logprobs": True} if request_logprobs else {}
            try:
                response = client.chat(
                    messages,
                    tools=[TOOL_SCHEMA],
                    temperature=agent_config.temperature,
                    top_p=agent_config.top_p,
                    max_tokens=request_max_tokens,
                    **extra_request,
                )
            except ContextOverflow as exc:
                stop_reason, error, error_type = STOP_CONTEXT_OVERFLOW, str(exc), "ContextOverflow"
                break
            except TransportError as exc:
                stop_reason, error, error_type = STOP_INFERENCE_ERROR, str(exc), "TransportError"
                break

            llm_calls += 1
            prompt_tokens += response.prompt_tokens
            completion_tokens += response.completion_tokens
            cache_read_tokens += getattr(response, "cache_read_tokens", 0)
            cache_creation_tokens += getattr(response, "cache_creation_tokens", 0)
            finish_reasons.append(response.finish_reason)
            reasoning_chars += len(response.reasoning_content)
            if response.content:
                model_output = response.content
            if request_logprobs:
                turn_logprobs.append(list(response.token_logprobs))

            assistant_message: dict = {"role": "assistant", "content": response.content or ""}
            if response.tool_calls:
                assistant_message["tool_calls"] = response.tool_calls
            messages.append(assistant_message)

            if not response.tool_calls:
                # No tool call can mean two different things. If the turn ran to
                # its natural end the model is declaring the task done. If it was
                # cut off at the output cap, it never got to say anything, and
                # recording that as a completion would overstate the run.
                if response.finish_reason == "length":
                    stop_reason = STOP_OUTPUT_TRUNCATED
                    error = "model turn reached the output token cap without a tool call"
                    error_type = "OutputTruncated"
                else:
                    stop_reason = STOP_COMPLETED
                break

            if tool_rounds >= agent_config.max_tool_rounds:
                # The budget is spent. The requested calls are not executed and
                # the file as it stands on disk is the artifact.
                stop_reason = STOP_BUDGET
                break

            round_record: dict = {
                "tool_calls": [],
                "input_tokens": response.prompt_tokens,
                "output_tokens": response.completion_tokens,
                "finish_reason": response.finish_reason,
                "reasoning_chars": len(response.reasoning_content),
            }
            if getattr(response, "cache_read_tokens", 0) or getattr(
                    response, "cache_creation_tokens", 0):
                round_record["cache_read_tokens"] = response.cache_read_tokens
                round_record["cache_creation_tokens"] = response.cache_creation_tokens
            if request_logprobs:
                round_record["logprobs"] = list(response.token_logprobs)
            round_started = time.monotonic()
            fatal: tuple[str, str, str] | None = None

            crashed_this_turn = False

            for call in response.tool_calls:
                function = call.get("function") or {}
                name = function.get("name") or ""
                raw_arguments = function.get("arguments")
                code = None
                if isinstance(raw_arguments, dict):
                    code = raw_arguments.get("code")
                elif isinstance(raw_arguments, str):
                    try:
                        code = (json.loads(raw_arguments) or {}).get("code")
                    except json.JSONDecodeError:
                        code = None

                if crashed_this_turn:
                    # A later call of a turn whose earlier call crashed the
                    # worker is not run: it was written against the state
                    # the crash threw away. It still needs a reply, because
                    # every tool call of a turn must have one.
                    round_record.setdefault("skipped_calls", []).append(
                        {"name": name,
                         "args": {"code": code} if isinstance(code, str) else {"raw": str(raw_arguments)},
                         "output": CRASH_SKIPPED_MESSAGE})
                    messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                     "name": name, "content": CRASH_SKIPPED_MESSAGE})
                    continue

                if name != TOOL_NAME:
                    output = f"Unknown tool '{name}'. The only available tool is {TOOL_NAME}."
                    recorded = output
                elif not isinstance(code, str):
                    output = _bad_arguments_message(str(raw_arguments))
                    recorded = output
                else:
                    tool_calls += 1
                    signature_before = _file_signature(working_ifc)
                    try:
                        snippet = sandbox.execute(code, timeout=agent_config.tool_timeout)
                    except SandboxTimeout as exc:
                        fatal = (STOP_TOOL_TIMEOUT, str(exc), type(exc).__name__)
                        # Keep the snippet that ended the run in the transcript.
                        round_record["tool_calls"].append(
                            {
                                "name": name,
                                "args": {"code": code},
                                "output": f"{STOP_TOOL_TIMEOUT}: {exc}",
                                "ok": False,
                            }
                        )
                        break
                    except SandboxCrash as exc:
                        sandbox_crashes += 1
                        round_record["sandbox_crashes"] = round_record.get("sandbox_crashes", 0) + 1
                        crash: dict = {
                            "crash": sandbox_crashes,
                            "error": str(exc),
                            # A commit() that finished inside the crashed
                            # snippet changed the file although its reply,
                            # and with it the commit count, never arrived.
                            "working_file_changed": _file_signature(working_ifc) != signature_before,
                        }
                        record = {"name": name, "args": {"code": code}, "ok": False,
                                  "sandbox_crash": crash}
                        restart_error = None
                        if sandbox_crashes < MAX_SANDBOX_CRASHES:
                            try:
                                crash.update(_restart_after_crash(sandbox, working_ifc))
                            except (SandboxCrash, SandboxTimeout) as rexc:
                                restart_error = rexc
                                crash["restart_error"] = f"{type(rexc).__name__}: {rexc}"
                        else:
                            sandbox.close()
                            crash["returncode"] = sandbox.last_returncode
                        if sandbox_crashes >= MAX_SANDBOX_CRASHES or restart_error is not None:
                            detail = str(exc) if restart_error is None else (
                                f"{exc}; sandbox restart failed: {restart_error}")
                            fatal = (STOP_SANDBOX_CRASH, detail, type(exc).__name__)
                            # Keep the snippet that ended the run in the transcript.
                            record["output"] = f"{STOP_SANDBOX_CRASH}: {exc}"
                            round_record["tool_calls"].append(record)
                            break
                        output = (CRASH_MESSAGE_LAST_COMMIT
                                  if crash["restarted_from"] == "last_commit"
                                  else CRASH_MESSAGE_INPUT)
                        record.update({"output": output, "output_chars": len(output),
                                       "output_capped": False})
                        round_record["tool_calls"].append(record)
                        messages.append({"role": "tool", "tool_call_id": call.get("id", ""),
                                         "name": name, "content": output})
                        if dup_on:
                            repeats[(code, output)] += 1
                        crashed_this_turn = True
                        continue
                    commits += snippet.commits
                    raw = snippet.raw_output(capture_stdout=agent_config.capture_stdout)
                    output = truncate(raw, agent_config.max_tool_output_chars)
                    if len(output) < len(raw):
                        truncated_tool_outputs += 1
                    recorded = truncate(output, agent_config.max_recorded_output_chars)

                round_record["tool_calls"].append(
                    {
                        "name": name,
                        "args": {"code": code} if isinstance(code, str) else {"raw": str(raw_arguments)},
                        "output": recorded,
                        "output_chars": len(raw) if isinstance(code, str) else len(output),
                        "output_capped": isinstance(code, str) and len(output) < len(raw),
                        "ok": name == TOOL_NAME and isinstance(code, str),
                    }
                )
                if name == TOOL_NAME and isinstance(code, str) and snippet.blocked:
                    # Only present when the sandbox guard refused something,
                    # so a run without the guard records exactly what it did.
                    round_record["tool_calls"][-1]["blocked"] = snippet.blocked
                    sandbox_blocked += len(snippet.blocked)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "name": name,
                        "content": output,
                    }
                )
                if dup_on and name == TOOL_NAME and isinstance(code, str):
                    # Only a call that ran counts. An unknown tool or an
                    # unparseable argument gets a fixed reply, so repeating one
                    # would trip the stop on the harness's own words rather
                    # than on the model going in circles.
                    repeats[(code, output)] += 1

            round_record["duration_seconds"] = round(time.monotonic() - round_started, 3)
            if round_record["tool_calls"]:
                iterations.append(round_record)
                tool_rounds += 1
            if fatal is not None:
                stop_reason, error, error_type = fatal
                break
            if dup_on and repeats and max(repeats.values()) >= agent_config.dup_stop:
                seen = max(repeats.values())
                stop_reason = STOP_DUPLICATE_LOOP
                error = f"the same tool call and output repeated {seen} times"
                error_type = "DuplicateLoop"
                break
    finally:
        sandbox.close()

    extra: dict = {}
    if budget_on:
        extra["token_budget_estimate"] = token_budget_estimate
        # A run that stops after a tool round ends on tool messages no model
        # turn ever saw: nothing was generated from them, and training scores
        # assistant tokens only, so they add length to the sequence and
        # nothing else. They are removed from the transcript that is returned
        # and kept in `iterations`, which is what the reward and the log read.
        unread = 0
        while messages and messages[-1].get("role") == "tool":
            messages.pop()
            unread += 1
        extra["unread_tool_results"] = unread
    if dup_on:
        extra["dup_max_count"] = max(repeats.values()) if repeats else 0
    if request_logprobs:
        extra["turn_logprobs"] = turn_logprobs

    return TrajectoryResult(
        task_id=task.task_id,
        stop_reason=stop_reason,
        model_output=model_output,
        messages=messages,
        iterations=iterations,
        tool_rounds=tool_rounds,
        tool_calls=tool_calls,
        llm_calls=llm_calls,
        commits=commits,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_seconds=time.monotonic() - started,
        copy_seconds=sandbox.copy_seconds,
        finish_reasons=finish_reasons,
        truncated_tool_outputs=truncated_tool_outputs,
        reasoning_chars=reasoning_chars,
        error=error,
        error_type=error_type,
        extra=extra,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        sandbox_blocked=sandbox_blocked,
        sandbox_crashes=sandbox_crashes,
    )
