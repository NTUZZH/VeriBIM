"""Loading BIM-Edit tasks and resolving the IFC paths they point at.

Two path quirks have to be handled:

* the task file names its scene directories ``data/realistic/`` and
  ``data/artificial/``, while the published scene repository ships them as
  ``complex/`` and ``simple/``;
* paths recorded inside the published run artifacts use Windows separators.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Directory names in the task file mapped to the directory names on disk.
SCENE_DIR_MAP = {
    "realistic": "complex",
    "artificial": "simple",
}


def normalise_path(raw: str) -> str:
    """Turn a possibly Windows-style path into a POSIX-style relative path."""
    return raw.replace("\\", "/")


@dataclass
class Task:
    task_id: str
    operation: str
    category: str
    prompt: str
    input_ifc: Path
    ground_truth_ifc: Path
    target: dict
    tags: list[str]

    @property
    def scene(self) -> str:
        """``R`` for a realistic (complex) scene, ``A`` for an artificial one."""
        return self.task_id.split("-")[3]


def resolve_scene_path(raw: str, scenes_dir: Path) -> Path:
    """Map a task-file IFC reference onto the scene repository layout."""
    rel = normalise_path(raw)
    parts = rel.split("/")
    mapped = [SCENE_DIR_MAP.get(p, p) for p in parts]
    # Drop the leading "data" element; the scene repository has no such level.
    if mapped and mapped[0] == "data":
        mapped = mapped[1:]
    return scenes_dir / Path(*mapped)


def load_tasks(tasks_file: str | Path, scenes_dir: str | Path) -> dict[str, Task]:
    tasks_file = Path(tasks_file)
    scenes_dir = Path(scenes_dir)
    out: dict[str, Task] = {}
    with tasks_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            task = Task(
                task_id=rec["task_id"],
                operation=rec["operation"],
                category=rec["category"],
                prompt=rec["prompt"],
                input_ifc=resolve_scene_path(rec["input_ifc"], scenes_dir),
                ground_truth_ifc=resolve_scene_path(rec["ground_truth_ifc"], scenes_dir),
                target=rec.get("target") or {},
                tags=rec.get("tags") or [],
            )
            out[task.task_id] = task
    return out


def load_slice_ids(slice_file: str | Path) -> list[str]:
    """Read the ordered task-id list out of a bake-off slice description."""
    data = json.loads(Path(slice_file).read_text(encoding="utf-8"))
    return list(data["task_ids"])


def load_corpus_tasks(tasks_file: str | Path, base_dir: str | Path) -> dict[str, Task]:
    """Load ModIFC-generated tasks, whose IFC paths are already project-relative.

    These records name their source and gold models directly, so none of the
    BIM-Edit scene-directory rewriting applies. Fields the generator adds
    (family, tier, edit kind) ride along in ``tags`` so a run directory keeps
    them without needing a second schema.
    """
    tasks_file = Path(tasks_file)
    base_dir = Path(base_dir)
    out: dict[str, Task] = {}
    with tasks_file.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tags = [
                f"family:{rec.get('family')}",
                f"tier:{rec.get('tier')}",
                f"edit_kind:{rec.get('edit_kind')}",
                f"element_type:{rec.get('element_type')}",
            ]
            task = Task(
                task_id=rec["task_id"],
                operation=rec["operation"],
                category=rec["category"],
                prompt=rec["prompt"],
                input_ifc=base_dir / normalise_path(rec["input_ifc"]),
                ground_truth_ifc=base_dir / normalise_path(rec["ground_truth_ifc"]),
                target=rec.get("target") or {},
                tags=tags,
            )
            out[task.task_id] = task
    return out
