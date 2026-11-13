"""Resolution of the file paths a task refers to.

The benchmark's task file names its scenes ``data/realistic/<file>.ifc`` and
``data/artificial/<file>.ifc``, while the released scene archive stores them
under ``complex/`` and ``simple/``.  Some run artifacts additionally carry
Windows absolute paths.  Everything here maps such a reference onto a file in a
local scene directory.
"""

from __future__ import annotations

import os
from pathlib import Path

# Directory name in the task file -> directory name in the scene archive.
SCENE_DIR_MAP = {
    "realistic": "complex",
    "artificial": "simple",
}


def normalize_reference(reference: str) -> str:
    """Turn a POSIX or Windows path reference into a POSIX one."""
    return reference.replace("\\", "/")


def reference_basename(reference: str) -> str:
    return normalize_reference(reference).rsplit("/", 1)[-1]


def reference_group(reference: str) -> str | None:
    """Return ``realistic`` / ``artificial`` if the reference names one."""
    parts = normalize_reference(reference).split("/")
    for part in reversed(parts[:-1]):
        if part in SCENE_DIR_MAP:
            return part
    return None


def resolve_scene(reference: str, scene_root: str | os.PathLike) -> Path:
    """Map a task's ``input_ifc`` / ``ground_truth_ifc`` onto a real file.

    ``scene_root`` is the directory that holds ``simple/`` and ``complex/``.
    """
    scene_root = Path(scene_root)
    name = reference_basename(reference)
    group = reference_group(reference)
    if group is not None:
        candidate = scene_root / SCENE_DIR_MAP[group] / name
        if candidate.exists():
            return candidate
    for sub in ("complex", "simple"):
        candidate = scene_root / sub / name
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"no scene file for reference {reference!r} under {scene_root}")


def resolve_reply(task_id: str, edited_root: str | os.PathLike) -> str:
    """The last thing the system said for one task, or an empty string.

    A run that answers an under-specified instruction writes its final message
    beside the model it did or did not edit, as ``<task_id>/reply.txt``.  A run
    that writes none is read as having said nothing, which is what a system that
    edited silently did.
    """
    path = Path(edited_root) / task_id / "reply.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def resolve_prediction(task_id: str, edited_root: str | os.PathLike) -> Path | None:
    """Find the edited model a run saved for one task.

    Each run stores one file per task under ``edited/<task_id>/``; the file name
    is derived from the input model, so it is discovered rather than assumed.
    Returns ``None`` when the run produced no file for the task.
    """
    folder = Path(edited_root) / task_id
    if not folder.is_dir():
        return None
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() == ".ifc")
    if not files:
        return None
    if len(files) > 1:
        # Prefer the highest-numbered ``*_<n>.ifc``, which is the last save.
        def order(p: Path) -> tuple[int, str]:
            stem = p.stem
            tail = stem.rsplit("_", 1)[-1]
            return (int(tail) if tail.isdigit() else -1, stem)

        files.sort(key=order)
    return files[-1]
