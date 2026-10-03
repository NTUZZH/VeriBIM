"""The candidate models and how to serve each of them with vLLM.

Every entry names the tool-call parser that matches the model's own chat
template, so tool calls are produced in the model's native format rather than
through a prompted convention. The parsers were chosen by reading each model's
``chat_template.jinja`` against the parsers registered in
``vllm.tool_parsers``:

* gemma-4-12b-it emits ``<|tool_call>call:name{...}<tool_call|>``  -> ``gemma4``
* granite-4.1-8b emits ``<tool_call>{json}</tool_call>``           -> ``granite4``
* Qwen3.5-9B emits ``<tool_call><function=...><parameter=...>``    -> ``qwen3_xml``
* Falcon-H1R-7B emits ``<tool_call>{json}</tool_call>``            -> ``hermes``

``--language-model-only`` is passed to the two checkpoints whose top-level class
is a multimodal ``ForConditionalGeneration``; the benchmark is text-only, and
the flag keeps the vision tower out of memory profiling.

Falcon-H1R-7B is a reasoning model that wraps its deliberation in ``<think>``
and ``</think>``. It is served **without** a reasoning parser: with one, a turn
that spends its whole output budget inside an unclosed ``<think>`` block yields
empty content and no tool call at all, which costs the task its trajectory.
Leaving the deliberation in the visible content keeps the tool call reachable
even when the turn is cut short, and that is the configuration the plumbing
checks proved.

gemma-4-12b-it is served from a separate conda environment because vLLM 0.27.1
reads ``head_dim`` and ``global_head_dim`` as flat config attributes, which
transformers exposes only up to 5.14.1; 5.15.0 moved them behind a per-layer
API. The environment named here pins 5.14.1 and is otherwise a clone.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Where the candidate checkpoints live. Override with MODIFC_MODELS_DIR so the
# package carries no machine-specific path.
MODELS_DIR = Path(os.environ.get("MODIFC_MODELS_DIR", "models"))

DEFAULT_SERVING_ENV = os.environ.get("MODIFC_VLLM_ENV", "l2vllm")


@dataclass
class ModelSpec:
    tag: str
    path: str
    tool_call_parser: str
    max_model_len: int = 32768
    reasoning_parser: str = ""
    #: Per-turn output cap. The default 8,192 was set from the largest single
    #: visible turn in the published runs (3,232 tokens). A reasoning model
    #: spends tokens on deliberation that never appeared in that statistic, so
    #: it needs its own, larger, budget or it can exhaust the cap mid-thought
    #: and emit no tool call at all.
    max_tokens: int = 8192
    conda_env: str = DEFAULT_SERVING_ENV
    extra_serve_args: list[str] = field(default_factory=list)
    architecture: str = ""
    notes: str = ""


MODELS: dict[str, ModelSpec] = {
    "gemma-4-12b-it": ModelSpec(
        tag="gemma-4-12b-it",
        path=str(MODELS_DIR / "gemma-4-12b-it"),
        tool_call_parser="gemma4",
        max_model_len=32768,
        conda_env=os.environ.get("MODIFC_VLLM_ENV_GEMMA", "l2vllm_gemma"),
        extra_serve_args=["--language-model-only"],
        architecture="Gemma4UnifiedForConditionalGeneration",
        notes="needs transformers <= 5.14.1; served from a pinned clone",
    ),
    "granite-4.1-8b": ModelSpec(
        tag="granite-4.1-8b",
        path=str(MODELS_DIR / "granite-4.1-8b"),
        tool_call_parser="granite4",
        max_model_len=32768,
        architecture="GraniteForCausalLM",
    ),
    "Qwen3.5-9B": ModelSpec(
        tag="Qwen3.5-9B",
        path=str(MODELS_DIR / "Qwen3.5-9B"),
        tool_call_parser="qwen3_xml",
        max_model_len=32768,
        extra_serve_args=["--language-model-only"],
        architecture="Qwen3_5ForConditionalGeneration",
    ),
    "Falcon-H1R-7B": ModelSpec(
        tag="Falcon-H1R-7B",
        path=str(MODELS_DIR / "Falcon-H1R-7B"),
        tool_call_parser="hermes",
        max_model_len=32768,
        max_tokens=16384,
        architecture="FalconH1ForCausalLM",
        notes=(
            "no reasoning parser, and a doubled per-turn cap because its visible "
            "output carries deliberation the other candidates do not produce"
        ),
    ),
}


def build_serve_command(
    spec: ModelSpec,
    gpu_memory_utilization: float,
    port: int = 8000,
    max_model_len: int | None = None,
) -> list[str]:
    """The vLLM serve invocation for one model."""
    command = [
        "vllm",
        "serve",
        spec.path,
        "--served-model-name",
        spec.tag,
        "--port",
        str(port),
        "--host",
        "127.0.0.1",
        "--max-model-len",
        str(max_model_len or spec.max_model_len),
        "--gpu-memory-utilization",
        f"{gpu_memory_utilization:.3f}",
        "--enable-auto-tool-choice",
        "--tool-call-parser",
        spec.tool_call_parser,
        "--chat-template",
        f"{spec.path}/chat_template.jinja",
    ]
    if spec.reasoning_parser:
        command += ["--reasoning-parser", spec.reasoning_parser]
    command += spec.extra_serve_args
    return command
