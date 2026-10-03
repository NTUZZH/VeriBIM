"""ModIFC evaluation harness.

A minimal agent harness that reproduces the BIM-Edit interaction protocol: one
sandboxed code-execution tool, one multi-turn trajectory per task, and one
edited IFC file as the artifact.
"""

from .config import AgentConfig, RetryConfig, RunConfig, ServerConfig
from .prompts import SYSTEM_PROMPT, SYSTEM_PROMPT_SHA256, TOOL_DESCRIPTION, TOOL_SCHEMA
from .tasks import Task, load_slice_ids, load_tasks

__all__ = [
    "AgentConfig",
    "RetryConfig",
    "RunConfig",
    "ServerConfig",
    "SYSTEM_PROMPT",
    "SYSTEM_PROMPT_SHA256",
    "TOOL_DESCRIPTION",
    "TOOL_SCHEMA",
    "Task",
    "load_slice_ids",
    "load_tasks",
]
