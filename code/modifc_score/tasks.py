"""The benchmark task list."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


@dataclass(frozen=True)
class Task:
    task_id: str
    operation: str
    category: str
    input_ifc: str
    ground_truth_ifc: str
    prompt: str
    entity_type: str
    guids: tuple[str, ...]
    tags: tuple[str, ...]
    #: For a task whose instruction leaves out a value the edit needs: which
    #: value is missing and which words a reply that asks for it may use.  Every
    #: other task carries ``None`` and is scored exactly as before.
    clarification: Optional[dict] = None

    @property
    def scene(self) -> str:
        return self.task_id.split("-")[3]


def load_tasks(path: str | Path) -> dict[str, Task]:
    tasks: dict[str, Task] = {}
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            target = rec.get("target") or {}
            task = Task(
                task_id=rec["task_id"],
                operation=rec["operation"],
                category=rec["category"],
                input_ifc=rec["input_ifc"],
                ground_truth_ifc=rec["ground_truth_ifc"],
                prompt=rec.get("prompt", ""),
                entity_type=target.get("entity_type", ""),
                guids=tuple(target.get("guids") or ()),
                tags=tuple(rec.get("tags") or ()),
                clarification=rec.get("clarification") or None,
            )
            tasks[task.task_id] = task
    return tasks


def task_order(tasks: Sequence[Task]) -> list[Task]:
    return sorted(tasks, key=lambda t: t.task_id)
