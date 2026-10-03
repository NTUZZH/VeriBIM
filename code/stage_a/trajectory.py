"""The shape of a training trajectory, and how it is replayed.

A trajectory is the eval protocol written down: the BIM-Edit system prompt, the
task instruction and the working file's path, then alternating assistant turns
and tool results, ending on an assistant turn that carries no tool call. Loss
falls on assistant turns only, which is recorded per message rather than derived
later, so the assembler and the trainer cannot disagree about it.

Replay executes the assistant turns' snippets in the harness sandbox, against a
fresh copy of the task's source model, through the same worker, the same output
rendering and the same truncation rule the evaluation harness uses. What the
tool returns is therefore what the model will see at evaluation time, and the
file left on disk is the artifact the verifier scores.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from . import paths

paths.ensure_harness_on_path()

from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.prompts import (  # noqa: E402
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_SHA256,
    TOOL_NAME,
    TOOL_SCHEMA,
    build_user_message,
)
from modifc_harness.sandbox import Sandbox, SandboxCrash, SandboxTimeout, truncate  # noqa: E402


@dataclass
class Turn:
    """One assistant turn: a tool call, or the closing message."""

    code: Optional[str] = None
    content: str = ""
    purpose: str = ""


@dataclass
class ReplayResult:
    ok: bool
    messages: list[dict] = field(default_factory=list)
    loss_on: list[bool] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    commits: int = 0
    tool_rounds: int = 0
    failure: str = ""
    failed_round: int = -1


def tool_call_message(code: str, content: str = "", call_id: str = "call_1") -> dict:
    """An assistant turn that asks for one execution.

    ``arguments`` is a mapping rather than a JSON string. The chat template
    iterates the arguments to render the XML tool-call envelope, so a mapping is
    what it needs; the server hands back a JSON string on the way in, which the
    harness parses before it reaches here.
    """
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": {"code": code}},
            }
        ],
    }


def tool_result_message(output: str, call_id: str = "call_1") -> dict:
    return {"role": "tool", "tool_call_id": call_id, "name": TOOL_NAME, "content": output}


def replay(turns: Sequence[Turn], input_ifc: Path, working_ifc: Path,
           log_file: Path, instruction: str,
           agent: AgentConfig | None = None) -> ReplayResult:
    """Run a planned trajectory through the harness sandbox.

    The turns are executed in order. A snippet that raises does not end the
    replay in itself, because a traceback is a legitimate tool result; what ends
    it is a sandbox that times out or dies, and a trajectory whose snippet
    raised is rejected afterwards by the caller.
    """
    agent = agent or AgentConfig()
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_message(instruction, str(working_ifc))},
    ]
    loss_on: list[bool] = [False, False]
    outputs: list[str] = []
    commits = 0
    rounds = 0

    sandbox = Sandbox(input_ifc=input_ifc, working_ifc=working_ifc, log_file=log_file)
    try:
        sandbox.start()
    except (SandboxCrash, SandboxTimeout) as exc:
        return ReplayResult(ok=False, failure=f"sandbox_start: {exc}"[:2000])

    try:
        for index, turn in enumerate(turns):
            if turn.code is None:
                messages.append({"role": "assistant", "content": turn.content})
                loss_on.append(True)
                continue
            call_id = f"call_{rounds + 1}"
            messages.append(tool_call_message(turn.code, turn.content, call_id))
            loss_on.append(True)
            try:
                snippet = sandbox.execute(turn.code, timeout=agent.tool_timeout)
            except (SandboxTimeout, SandboxCrash) as exc:
                return ReplayResult(
                    ok=False, messages=messages, loss_on=loss_on, outputs=outputs,
                    commits=commits, tool_rounds=rounds,
                    failure=f"{type(exc).__name__}: {exc}"[:300], failed_round=index,
                )
            commits += snippet.commits
            raw = snippet.raw_output(capture_stdout=agent.capture_stdout)
            output = truncate(raw, agent.max_tool_output_chars)
            outputs.append(output)
            messages.append(tool_result_message(output, call_id))
            loss_on.append(False)
            rounds += 1
            if not snippet.ok:
                return ReplayResult(
                    ok=False, messages=messages, loss_on=loss_on, outputs=outputs,
                    commits=commits, tool_rounds=rounds,
                    failure="snippet_raised", failed_round=index,
                )
    finally:
        sandbox.close()

    return ReplayResult(ok=True, messages=messages, loss_on=loss_on, outputs=outputs,
                        commits=commits, tool_rounds=rounds)


def trajectory_record(task: dict, messages: list[dict], loss_on: list[bool],
                      source: str, score, extra: dict[str, Any]) -> dict:
    """One line of the trajectory file."""
    return {
        "task_id": task["task_id"],
        "source": source,
        "operation": task["operation"],
        "category": task["category"],
        "element_type": task.get("element_type", ""),
        "family": task.get("family", ""),
        "edit_kind": task.get("edit_kind", ""),
        "tier": task.get("tier", "single"),
        # The generator's own tags, carried through so the training set can be
        # stratified by family and the dataset report can count per family.
        "families": list(task.get("families") or ()),
        "anchor_kind": (task.get("anchor") or {}).get("kind", ""),
        "model_conditions": task.get("model_conditions") or {},
        "wording": task.get("wording") or {},
        "instruction": task.get("instruction") or task.get("prompt", ""),
        "input_ifc": task["input_ifc"],
        "ground_truth_ifc": task["ground_truth_ifc"],
        "messages": messages,
        "loss_on": loss_on,
        "tool_rounds": sum(1 for m in messages if m.get("role") == "tool"),
        "score": score.as_dict() if score is not None else None,
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "tool_name": TOOL_NAME,
        **extra,
    }


def tools_schema() -> list[dict]:
    """The tool list every record is rendered with, at training and at eval."""
    return [TOOL_SCHEMA]
