"""Run configuration for the ModIFC evaluation harness."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentConfig:
    """Agent loop and sandbox settings.

    ``max_tool_rounds`` is the number of tool rounds the agent may actually
    execute. The published BIM-Edit runs configured ``max_tool_calls: 20`` but
    enforced the budget through a LangGraph recursion limit of 45 graph steps,
    which lets 22 tool rounds run before the graph aborts. Reproducing the
    published traces therefore needs 22, not 20; see the harness README.
    """

    max_tool_rounds: int = 22
    tool_timeout: float = 420.0
    temperature: float = 0.0
    top_p: float = 1.0
    max_tokens: int = 8192
    # Model-visible cap on one tool result. The published runs ran against
    # frontier models with very large context windows and did not need one;
    # locally served 7B-12B models do.
    max_tool_output_chars: int = 16000
    # Cap on the tool output stored in the transcript file.
    max_recorded_output_chars: int = 4000
    capture_stdout: bool = True
    #: Training-side budget on the whole transcript, in tokens. Zero is off,
    #: which is the evaluation protocol: a benchmark run stops on the round
    #: budget alone. Training needs the second limit because a transcript that
    #: does not fit the training sequence length is thrown away after it has
    #: been rolled out and scored, and throwing it away censors the group it
    #: belonged to (the discarded trajectories are the long ones, which carry
    #: most of the reward spread).
    max_transcript_tokens: int = 0
    #: A request is not sent when fewer than this many tokens are left inside
    #: the transcript budget, because a turn that short cannot finish a tool
    #: call and would only spend the remainder on a truncated one.
    min_turn_tokens: int = 256
    #: Stop once one (code, output) pair has been produced this many times.
    #: Zero is off, which is the evaluation protocol. A repeat count of three
    #: separates a stuck trajectory from a working one: on the 500-task
    #: validation set it caught 40 of the 43 trajectories that exhausted the
    #: round budget in a loop and none of the 294 that passed.
    dup_stop: int = 0


@dataclass
class RetryConfig:
    """Transport-level retry for a single inference call."""

    max_attempts: int = 2
    delay_seconds: float = 30.0


@dataclass
class ServerConfig:
    """Where the OpenAI-compatible inference server is."""

    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = "EMPTY"
    served_model_name: str = ""
    request_timeout: float = 1800.0


@dataclass
class RunConfig:
    model_tag: str
    model_path: str = ""
    results_dir: str = "runs_local"
    tasks_file: str = "data/bimedit/BIM-Edit-Tasks/tasks.jsonl"
    scenes_dir: str = "data/bimedit/BIM-Edit"
    task_ids: list[str] = field(default_factory=list)
    #: "bimedit" for the published scene layout, "corpus" for our generated
    #: tasks, whose IFC paths are already project-relative.
    task_source: str = "bimedit"
    num_samples: int = 1
    agent: AgentConfig = field(default_factory=AgentConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    serve_command: list[str] = field(default_factory=list)
    tool_call_parser: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)
