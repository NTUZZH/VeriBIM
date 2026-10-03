"""The task subset Stage B samples from.

Three properties are wanted at once and they pull against each other: coverage
of every operation, category and building; a bias toward the operations the
Stage A gate scores lowest; and a size that a k=6 sampling run can finish. The
selection is therefore written as code with a seed rather than described, so the
realized strata can be reported and the same subset rebuilt.

The weighting is not a free parameter. It comes from the matched-boundary gate:
create 0.669, delete 0.697, update 0.892. The two weak operations get the larger
share, because a preference pair is only informative where the model still
fails.
"""

from __future__ import annotations

import json
import random
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

#: The fields a round-robin cell is keyed on. v1 spread the quota over category
#: and building; the v2 task set carries several edit kinds inside one
#: operation, so a run that wants them evenly represented adds ``edit_kind``.
DEFAULT_CELL_KEYS = ("category", "building_id")

#: Buildings held out for E2 (post-amendment set: BLD048 was
#: swapped out of the holdout and into training, BLD042 in). Asserted rather
#: than assumed: the wave-1 generator already excludes them, and this catches a
#: regeneration that stops doing so.
E2_HOLDOUT = frozenset({
    "BLD003", "BLD018", "BLD029", "BLD031", "BLD035",
    "BLD038", "BLD040", "BLD042", "BLD044", "BLD045",
})

#: Share of the subset each operation gets. Weighted toward the operations the
#: Stage A gate scores lowest; update keeps a quarter so a preference signal
#: learned on creates and deletes cannot quietly cost the operation that already
#: works.
OPERATION_WEIGHTS = {"create": 0.40, "delete": 0.35, "update": 0.25}

#: Per-operation gate score, matched boundary, for the record.
STAGE_A_BY_OPERATION = {"create": 0.6685, "delete": 0.6970, "update": 0.8923}


def parse_weights(text: str | None,
                  default: dict[str, float] | None = None) -> dict[str, float]:
    """``create=0.45,delete=0.35,update=0.20`` into a mapping.

    An empty argument returns the pre-registered weights, so a caller that does
    not pass the flag selects exactly what v1 selected.
    """
    if not text:
        return dict(default or OPERATION_WEIGHTS)
    weights: dict[str, float] = {}
    for item in str(text).split(","):
        item = item.strip()
        if not item:
            continue
        if "=" not in item:
            raise ValueError(f"weight {item!r} is not operation=share")
        name, share = item.split("=", 1)
        weights[name.strip()] = float(share)
    if not weights:
        raise ValueError(f"no weights parsed from {text!r}")
    total = sum(weights.values())
    if abs(total - 1.0) > 1e-6:
        print(f"pool: weights sum to {total:.4f}, not 1; the quota is taken as given",
              flush=True)
    return weights


def parse_cell_keys(text: str | None) -> tuple[str, ...]:
    """``category,edit_kind,building_id`` into the round-robin cell key."""
    if not text:
        return DEFAULT_CELL_KEYS
    keys = tuple(k.strip() for k in str(text).split(",") if k.strip())
    return keys or DEFAULT_CELL_KEYS


def load_exclude_ids(files: Iterable[str | Path] | None) -> set[str]:
    """Task ids named by one or more files, as a JSON list or as JSONL rows.

    The validation split is a different file, so nothing should reach the pool
    through it; the exclusion is a defence against a task set whose split field
    and whose subset files disagree.
    """
    ids: set[str] = set()
    for item in files or ():
        path = Path(item)
        if not path.exists():
            raise FileNotFoundError(f"exclude-ids file not found: {path}")
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        if text.lstrip().startswith("["):
            for entry in json.loads(text):
                ids.add(entry if isinstance(entry, str) else entry["task_id"])
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            ids.add(entry if isinstance(entry, str) else entry["task_id"])
    return ids


def load_train_tasks(tasks_file: Path, split: str = "train",
                     exclude_ids: Iterable[str] | None = None) -> list[dict]:
    excluded = set(exclude_ids or ())
    out: list[dict] = []
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("split") == split and record["task_id"] not in excluded:
                out.append(record)
    intruders = sorted({r["building_id"] for r in out} & E2_HOLDOUT)
    if intruders:
        raise AssertionError(
            f"E2 holdout buildings present in the {split} split: {intruders}")
    return out


def select(tasks: Sequence[dict], size: int = 6000, seed: int = 20260826,
           weights: dict[str, float] | None = None,
           cell_keys: Sequence[str] = DEFAULT_CELL_KEYS) -> list[dict]:
    """A stratified, weighted subset of ``size`` tasks.

    Within an operation the walk is a round robin over its cells, so the quota
    is spread rather than drawn from whichever cell happens to be largest, and
    every cell contributes its first task before any cell contributes its
    second. ``cell_keys`` names the fields a cell is keyed on and defaults to
    the v1 pair (category, building); adding ``edit_kind`` spreads the quota
    over the edit kinds inside one operation as well.
    """
    weights = weights or OPERATION_WEIGHTS
    cell_keys = tuple(cell_keys or DEFAULT_CELL_KEYS)
    rng = random.Random(seed)
    by_operation: dict[str, dict[tuple, list[dict]]] = defaultdict(
        lambda: defaultdict(list))
    for task in sorted(tasks, key=lambda t: t["task_id"]):
        cell = tuple(task.get(key, "") for key in cell_keys)
        by_operation[task["operation"]][cell].append(task)

    picked: list[dict] = []
    shortfalls: dict[str, int] = {}
    for operation in sorted(weights):
        cells = by_operation.get(operation, {})
        available = sum(len(v) for v in cells.values())
        quota = min(int(round(size * weights[operation])), available)
        if quota < int(round(size * weights[operation])):
            shortfalls[operation] = int(round(size * weights[operation])) - quota
        keys = sorted(cells)
        rng.shuffle(keys)
        for bucket in cells.values():
            rng.shuffle(bucket)
        taken = 0
        depth = 0
        while taken < quota:
            progressed = False
            for key in keys:
                bucket = cells[key]
                if depth < len(bucket):
                    picked.append(bucket[depth])
                    taken += 1
                    progressed = True
                    if taken >= quota:
                        break
            if not progressed:
                break
            depth += 1
    picked.sort(key=lambda t: t["task_id"])
    if shortfalls:
        # A cell can simply not hold its quota. Say so rather than silently
        # returning a smaller subset than the caller asked for.
        print(f"pool: quota not met for {shortfalls} (operation short by tasks)",
              flush=True)
    return picked


def strata(tasks: Sequence[dict], weights: dict[str, float] | None = None,
           cell_keys: Sequence[str] | None = None) -> dict[str, Any]:
    """What the selection actually contains.

    The v2 task set tags every record with taxonomy families, so the report
    counts them twice: once per full tag and once per layer, the part of the tag
    before its first dot, which is the level a reader compares pools at.
    """
    cells = Counter((t["operation"], t["category"]) for t in tasks)
    families = Counter(f for t in tasks for f in (t.get("families") or ()))
    layers = Counter(f.split(".")[0] for t in tasks
                     for f in (t.get("families") or ()))
    out = {
        "n": len(tasks),
        "by_operation": dict(Counter(t["operation"] for t in tasks)),
        "by_category": dict(Counter(t["category"] for t in tasks)),
        "by_operation_category": {f"{o}/{c}": n for (o, c), n in sorted(cells.items())},
        "buildings": len({t["building_id"] for t in tasks}),
        "edit_kinds": dict(Counter(t.get("edit_kind", "") for t in tasks)),
        "by_edit_kind": dict(Counter(t.get("edit_kind", "") for t in tasks)),
        "by_family": dict(families.most_common()),
        "by_layer": dict(layers.most_common()),
        "underspecified": sum(1 for t in tasks
                              if "wording.underspecified" in (t.get("families") or ())
                              or (t.get("clarification") and t.get("expected_reply"))),
        "tiers": dict(Counter(t.get("tier", "") for t in tasks)),
        "schemas": dict(Counter((t.get("source_model") or {}).get("schema", "")
                                for t in tasks)),
    }
    if weights is not None:
        out["weights"] = dict(weights)
    if cell_keys is not None:
        out["cell_keys"] = list(cell_keys)
    return out
