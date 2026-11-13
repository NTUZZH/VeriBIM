"""What every element of a source model is called, cached per model.

A task's anchor stores the identifier the generator resolved its phrase to, but
the instruction names that element in words. Turning the identifier back into
the name the instruction quotes is what lets the trajectory look the element up
the way a reader has to, so the index is built once per source model and read at
plan time.

For each product of a class the anchors can point at, the index holds its class,
its Name, its LongName and the storey it sits on. The storey is what
disambiguates a name two elements share, and the class is what tells an opening
apart from the door that fills it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

#: The classes an anchor parameter or an edit keyword can name. Everything else
#: in a model (pipes, fittings, furniture, annotations) is left out, which is
#: what keeps the index of a two-hundred-megabyte mechanical model small.
INDEXED_CLASSES = (
    "IfcBuildingStorey",
    "IfcSpace",
    "IfcWall",
    "IfcSlab",
    "IfcDoor",
    "IfcWindow",
    "IfcColumn",
    "IfcOpeningElement",
    "IfcBuilding",
    "IfcSite",
)

#: A model written in IFC2X3 calls a plain wall ``IfcWallStandardCase``, and a
#: reader writing ``ifc.by_type('IfcWall')`` gets it anyway because the query is
#: by supertype. The lookup code the trajectory shows therefore names the
#: supertype, and uniqueness is counted over the same set.
GENERAL_CLASS = {
    "IfcWallStandardCase": "IfcWall",
    "IfcWallElementedCase": "IfcWall",
    "IfcSlabStandardCase": "IfcSlab",
    "IfcSlabElementedCase": "IfcSlab",
    "IfcDoorStandardCase": "IfcDoor",
    "IfcWindowStandardCase": "IfcWindow",
    "IfcColumnStandardCase": "IfcColumn",
    "IfcMemberStandardCase": "IfcMember",
    "IfcPlateStandardCase": "IfcPlate",
    "IfcBeamStandardCase": "IfcBeam",
}


def general_class(ifc_class: str) -> str:
    return GENERAL_CLASS.get(ifc_class, ifc_class)


def index_key(task: dict) -> str:
    """The name of one model's index file.

    The source model's own checksum is used where the task record carries one,
    so two task files that name the same model share one index and a model that
    was replaced cannot be read from a stale one.
    """
    source = task.get("source_model") or {}
    sha = source.get("sha256")
    if sha:
        return str(sha)
    relpath = task.get("input_ifc") or ""
    return "path-" + hashlib.sha256(relpath.encode("utf-8")).hexdigest()


def _storey_of(product) -> str:
    """The storey a product sits on, through containment or decomposition."""
    seen = set()
    current = product
    for _ in range(8):
        if current is None or current.id() in seen:
            return ""
        seen.add(current.id())
        if current.is_a("IfcBuildingStorey"):
            return current.GlobalId
        nxt = None
        for relation in getattr(current, "ContainedInStructure", None) or ():
            nxt = relation.RelatingStructure
            break
        if nxt is None:
            for relation in getattr(current, "Decomposes", None) or ():
                nxt = relation.RelatingObject
                break
        if nxt is None:
            for relation in getattr(current, "VoidsElements", None) or ():
                nxt = relation.RelatingBuildingElement
                break
        if nxt is None:
            for relation in getattr(current, "FillsVoids", None) or ():
                opening = relation.RelatingOpeningElement
                nxt = opening
                break
        current = nxt
    return ""


def build_index(ifc_path: Path) -> dict[str, list]:
    """Open one model and read what its elements are called."""
    import ifcopenshell

    model = ifcopenshell.open(str(ifc_path))
    entries: dict[str, list] = {}
    for ifc_class in INDEXED_CLASSES:
        try:
            products = model.by_type(ifc_class)
        except RuntimeError:
            continue
        for product in products:
            guid = getattr(product, "GlobalId", None)
            if not guid or guid in entries:
                continue
            name = (getattr(product, "Name", None) or "").strip()
            long_name = (getattr(product, "LongName", None) or "").strip()
            entries[guid] = [general_class(product.is_a()), name, long_name,
                             _storey_of(product)]
    del model
    return entries


def index_file(cache_root: Path, task: dict) -> Path:
    return Path(cache_root) / f"{index_key(task)}.json"


def write_index(cache_root: Path, task: dict, project_root: Path) -> Path:
    path = index_file(cache_root, task)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = build_index(Path(project_root) / task["input_ifc"])
    tmp = path.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return path


class NameIndex:
    """One model's index, with the queries the planner asks of it."""

    def __init__(self, entries: dict[str, list]):
        self.entries = entries
        self._by_name: dict[tuple[str, str], list[str]] = defaultdict(list)
        for guid, (ifc_class, name, long_name, _storey) in entries.items():
            for label in {name, long_name}:
                if label:
                    self._by_name[(ifc_class, label)].append(guid)

    def entry(self, guid: str) -> Optional[list]:
        return self.entries.get(guid)

    def ifc_class(self, guid: str) -> str:
        found = self.entries.get(guid)
        return found[0] if found else ""

    def labels(self, guid: str) -> list[str]:
        """The names an instruction could have used for this element.

        ``Name`` comes first: a space carries a room number in ``Name`` and a
        room function in ``LongName``, and the generator's phrase quotes the
        number.
        """
        found = self.entries.get(guid)
        if not found:
            return []
        return [label for label in (found[1], found[2]) if label]

    def storey(self, guid: str) -> str:
        found = self.entries.get(guid)
        return found[3] if found else ""

    def candidates(self, ifc_class: str, name: str) -> list[str]:
        return list(self._by_name.get((ifc_class, name), ()))

    def resolve(self, ifc_class: str, name: str) -> list[str]:
        """What a lookup by this name would find, the way the trajectory does it.

        ``Name`` is tried first and ``LongName`` only where no element of the
        class carries the name, which is the order the generated lookup uses, so
        the planner's uniqueness test and the code the model runs agree.
        """
        found = self.candidates(ifc_class, name)
        by_name = [g for g in found if self.entries[g][1] == name]
        if by_name:
            return by_name
        return [g for g in found if self.entries[g][2] == name]

    def resolve_on_storey(self, ifc_class: str, name: str,
                          storey_guid: str) -> list[str]:
        return [g for g in self.resolve(ifc_class, name)
                if self.entries[g][3] == storey_guid]


_CACHE: dict[str, NameIndex] = {}


def load(cache_root: Path, task: dict, project_root: Path,
         build_if_missing: bool = True) -> Optional[NameIndex]:
    """The index for one task's source model, built on a miss.

    One index is held in memory at a time. A synthesis worker walks a chunk of
    tasks that share a source model, so the file is parsed once per chunk rather
    than once per task, and the memory a large model's index takes is given back
    when the worker moves to the next building.
    """
    key = index_key(task)
    found = _CACHE.get(key)
    if found is not None:
        return found
    path = index_file(cache_root, task)
    if not path.exists():
        if not build_if_missing:
            return None
        write_index(cache_root, task, project_root)
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    _CACHE.clear()
    index = NameIndex(entries)
    _CACHE[key] = index
    return index


# ---------------------------------------------------------------- building

def build_all(tasks: Sequence[dict], cache_root: Path, project_root: Path,
              workers: int = 4, cores: Sequence[int] = ()) -> dict:
    """Build the index of every source model the task set uses."""
    import multiprocessing as mp

    cache_root = Path(cache_root)
    cache_root.mkdir(parents=True, exist_ok=True)
    wanted: dict[str, dict] = {}
    for task in tasks:
        wanted.setdefault(index_key(task), task)
    jobs = [(key, task["input_ifc"], (task.get("source_model") or {}).get("sha256", ""))
            for key, task in sorted(wanted.items())
            if not index_file(cache_root, task).exists()]
    if jobs:
        context = mp.get_context("spawn")
        with context.Pool(processes=max(1, workers), maxtasksperchild=1,
                          initializer=_init_builder,
                          initargs=(str(cache_root), str(project_root),
                                    tuple(cores))) as pool:
            for _ in pool.imap_unordered(_build_one, jobs, chunksize=1):
                pass
    return {"models": len(wanted), "built": len(jobs),
            "cache_root": str(cache_root)}


_BUILD: dict[str, Any] = {}


def _init_builder(cache_root: str, project_root: str,
                  cores: Sequence[int] = ()) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    _BUILD.update(cache_root=Path(cache_root), project_root=Path(project_root))


def _build_one(job: tuple[str, str, str]) -> str:
    key, relpath, sha = job
    task = {"input_ifc": relpath, "source_model": {"sha256": sha}}
    write_index(_BUILD["cache_root"], task, _BUILD["project_root"])
    return key


def main(argv: Optional[list[str]] = None) -> int:
    import argparse

    from . import paths

    parser = argparse.ArgumentParser(prog="stage-a-nameindex")
    parser.add_argument("--tasks-file", required=True, nargs="+")
    parser.add_argument("--cache-root", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--cores", default="")
    args = parser.parse_args(argv)

    from .pipeline import load_tasks
    from .sample import parse_cores

    tasks: list[dict] = []
    for path in args.tasks_file:
        tasks.extend(load_tasks(Path(path)))
    report = build_all(tasks, Path(args.cache_root), paths.PROJECT_ROOT,
                       workers=args.workers,
                       cores=parse_cores(args.cores) if args.cores else ())
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
