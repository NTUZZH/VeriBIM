"""stage_a.run_gate with one user note per task.

The harness appends the text of the file named by VERIBIM_USER_NOTE_FILE to the user turn of every task
(code/harness/modifc_harness/prompts.py). This entry point adds one case and changes nothing else: when
VERIBIM_USER_NOTE_FILE names a DIRECTORY, the note of task T is read from <directory>/T.md. When the
variable names a file or is unset, the harness's own build_user_message runs unchanged.

The user turn is assembled exactly as prompts.build_user_message assembles it from a note file:
"<instruction>\\n\\nIFC model path: <path>\\n\\n<note stripped>". The task id comes from the task the
calling thread is running (set by a wrapper around run_task) and is checked against the working-copy path,
which gate_eval.rollout names <run>/<model>/edited/<task_id>/<file>.ifc.

Usage: the same arguments as `python -m stage_a.run_gate`, with PYTHONPATH=code.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from pathlib import Path

from stage_a import gate_eval, paths, run_gate

paths.ensure_harness_on_path()
import modifc_harness.agent as harness_agent  # noqa: E402

_local = threading.local()
_original_run_task = gate_eval.run_task
_original_build_user_message = harness_agent.build_user_message


def note_dir() -> Path | None:
    value = os.environ.get("VERIBIM_USER_NOTE_FILE", "")
    return Path(value) if value and os.path.isdir(value) else None


def _run_task(task, working_ifc, *args, **kwargs):
    _local.task_id = task.task_id
    try:
        return _original_run_task(task, working_ifc, *args, **kwargs)
    finally:
        _local.task_id = None


def build_user_message(prompt: str, input_ifc_path: str) -> str:
    directory = note_dir()
    if directory is None:
        return _original_build_user_message(prompt, input_ifc_path)
    task_id = getattr(_local, "task_id", None)
    if not task_id:
        raise RuntimeError("per-task note requested outside a task")
    if Path(input_ifc_path).parent.name != task_id:
        raise RuntimeError(f"working copy {input_ifc_path} does not belong to task {task_id}")
    note = (directory / f"{task_id}.md").read_text(encoding="utf-8").strip()
    message = f"{prompt}\n\nIFC model path: {input_ifc_path}"
    return f"{message}\n\n{note}" if note else message


def install() -> None:
    gate_eval.run_task = _run_task
    harness_agent.build_user_message = build_user_message


def check_notes(argv: list[str]) -> None:
    """Every task of the subset has a non-empty note before any request is sent."""
    directory = note_dir()
    if directory is None:
        return
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--subset")
    ap.add_argument("--limit", type=int, default=0)
    known, _ = ap.parse_known_args(argv)
    ids = json.loads(Path(known.subset).read_text(encoding="utf-8"))
    if known.limit:
        ids = ids[: known.limit]
    missing = [t for t in ids if not (directory / f"{t}.md").is_file()
               or not (directory / f"{t}.md").read_text(encoding="utf-8").strip()]
    if missing:
        raise SystemExit(f"no note for {len(missing)} task(s) in {directory}: {missing[:5]}")
    print(f"  per-task notes: {directory} ({len(ids)} tasks, all present)", flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    check_notes(argv)
    install()
    return run_gate.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
