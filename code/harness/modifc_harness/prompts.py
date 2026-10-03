"""System prompt and tool contract for the ModIFC evaluation harness.

The system prompt and the tool description are reproduced from the published
BIM-Edit run configuration so that local runs are directly comparable with the
published frontier-model runs. The prompt text lives in ``system_prompt.txt``
next to this module and its SHA-256 is checked at import time, so an accidental
edit fails loudly instead of silently changing the protocol.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_PROMPT_FILE = Path(__file__).with_name("system_prompt.txt")

# SHA-256 of the system prompt string in every one of the seven published
# BIM-Edit run configurations (data/bimedit/BIM-Edit-runs/*/config.json).
SYSTEM_PROMPT_SHA256 = "ef33ea6ce0a4c09c20fa8db19e53eb4e18acde8149d1c74cc449770e3e015b6b"

SYSTEM_PROMPT = _PROMPT_FILE.read_text(encoding="utf-8")

_actual = hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()
if _actual != SYSTEM_PROMPT_SHA256:
    raise RuntimeError(
        "system_prompt.txt does not match the published BIM-Edit system prompt: "
        f"expected SHA-256 {SYSTEM_PROMPT_SHA256}, got {_actual}"
    )

TOOL_NAME = "execute_ifc_code"

# Verbatim from the BIM-Edit paper, Appendix F.4.
TOOL_DESCRIPTION = (
    "Execute Python code against the current IFC file. Input: {code: str}. "
    "The IFC model is pre-loaded as `ifc` (`ifcopenshell.file`). Also available: "
    "`ifcopenshell`, `api` (`ifcopenshell.api`), `util` (`ifcopenshell.util`), "
    "`element_util` (`ifcopenshell.util.element`), and `guid` (`ifcopenshell.guid`). "
    "Assign to `result` to return data. Call `commit()` to save modifications."
)

TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": TOOL_DESCRIPTION,
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute against the IFC model.",
                }
            },
            "required": ["code"],
        },
    },
}


def build_user_message(prompt: str, input_ifc_path: str) -> str:
    """Assemble the single user turn.

    The model receives the natural-language instruction and the path to the IFC
    model. The model itself is never serialised into the context; the agent has
    to query it through generated code.
    """
    message = f"{prompt}\n\nIFC model path: {input_ifc_path}"
    note = _user_note()
    return f"{message}\n\n{note}" if note else message


def _user_note() -> str:
    """An optional appendix to the user turn, read from the file named by
    ``VERIBIM_USER_NOTE_FILE``.

    Unset in every headline run: the user turn is then exactly the instruction
    and the path, as published. It is set only for the control arm that tells an
    untrained model that the helper library exists, so the appendix is
    part of the arm's resolved configuration, never of the protocol.
    """
    import os
    path = os.environ.get("VERIBIM_USER_NOTE_FILE", "")
    if not path:
        return ""
    return Path(path).read_text(encoding="utf-8").strip()
