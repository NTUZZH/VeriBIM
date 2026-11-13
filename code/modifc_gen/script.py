"""Writing a plan out as a gold script, and running one.

The gold script is the only thing that ever edits a model.  The generator does
not apply an edit and then describe it in Python; it writes the Python first and
executes that, so the script in the task record is by construction the script
that produced the gold model.
"""

from __future__ import annotations

import inspect
import io
import os
from typing import Any, Optional

import ifcopenshell

from .ops import Call, EditPlan

HEADER = '''"""Gold edit script for task {task_id}.

{instruction}

Lengths are metres.  Run it as:  python {task_id}.py <source.ifc> <target.ifc>
"""

import sys

import ifcopenshell

from modifc_gen import goldlib


def apply_edit(model):
    """Apply the task's edit to an open model, in place."""
'''

FOOTER = '''    return model


def main(source_ifc, target_ifc):
    model = ifcopenshell.open(source_ifc)
    apply_edit(model)
    model.write(target_ifc)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
'''


def _literal(value: Any) -> str:
    if isinstance(value, float):
        text = repr(round(value, 9))
        return text
    return repr(value)


def _parameter_names(func: str) -> list[str]:
    """Names of a runtime function's arguments after the model."""
    from . import goldlib

    return list(inspect.signature(getattr(goldlib, func)).parameters)[1:]


def render_call(call: Call, width: int = 78) -> str:
    """One call, written with named arguments and wrapped to a readable width.

    Naming the arguments matters here: a gold script is read by whoever wants
    to know what a task actually did, and a row of bare literals would not tell
    them.
    """
    names = _parameter_names(call.func)
    parts = [f"{name}={_literal(value)}"
             for name, value in zip(names, call.args)]
    head = f"    goldlib.{call.func}(model, "
    lines: list[str] = []
    current = head
    for i, part in enumerate(parts):
        piece = part + ("," if i < len(parts) - 1 else ")")
        if len(current) + len(piece) > width and current.strip() != head.strip():
            lines.append(current.rstrip())
            current = " " * len(head) + piece + " "
        else:
            current += piece + " "
    lines.append(current.rstrip())
    body = "\n".join(lines)
    if call.comment:
        return f"    # {call.comment}\n{body}"
    return body


def render_script(task_id: str, instruction: str, plan: EditPlan) -> str:
    """The gold script for one planned edit."""
    body = "\n".join(render_call(call) for call in plan.calls)
    return HEADER.format(task_id=task_id, instruction=instruction) + body + "\n" + FOOTER


def execute_script(source: str, source_ifc: str, target_ifc: str) -> None:
    """Run a gold script's ``main`` on one source model.

    The script is executed in a namespace of its own rather than imported, so
    running many of them in one process cannot let one leak into the next.
    """
    namespace: dict[str, Any] = {"__name__": "modifc_gold_script"}
    compiled = compile(source, "<gold_script>", "exec")
    exec(compiled, namespace)
    namespace["main"](str(source_ifc), str(target_ifc))
