"""Rebuilding a task's gold model from its gold script, on demand and in bulk.

The canonical artifact of a generated task is its gold script, not its gold
model: a gold model is a full copy of its source, so twenty thousand of them
would need hundreds of gigabytes, while twenty thousand scripts fit in a few
tens of megabytes.  A gold model is therefore rebuilt when something needs it,
and the rebuild is checked against the checksum recorded when the task was
verified.

Two ways in.

``GoldCache`` rebuilds one task's gold model and keeps it in a directory bounded
in both files and bytes, evicting the least recently used entry when either
bound is reached.  This is what a training loop uses: it holds a working set of
gold models without ever growing without bound.

    cache = GoldCache(root, root / "runs/gold_cache", max_bytes=20 << 30,
                      max_files=400)
    path = cache.path_for(record)      # rebuilds if absent, refreshes if not
    score_against(path)

The bounds are on DISK, and both are enforced before a rebuild is written, so
the directory never exceeds them.  Process memory is not what the cache holds:
one rebuild parses one source model, so peak memory during a rebuild is that
model's parsed size (about 25x its file size for this corpus, so up to roughly
4 GB for the largest file in the pool and a few hundred megabytes typically),
and nothing is retained between rebuilds.

``materialize_split`` writes every gold model of one split into a directory and
leaves it there.  This is what the validation split gets, so that a scorer can
read its ground truth from disk without rebuilding anything.

Run it as::

    python -m modifc_gen.materialize --root . \
        --tasks data/veribim_tasks_v1/tasks.jsonl --split validation \
        --workers 6 --cores 12-23
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import script as script_lib
from . import verify

DEFAULT_MAX_BYTES = 20 << 30      # 20 GiB of gold models on disk
DEFAULT_MAX_FILES = 400


@dataclass
class Rebuild:
    """What one rebuild produced and how it was checked."""

    task_id: str
    path: str
    bytes: int
    seconds: float
    check: str          # "sha256", "structure", or "unchecked"
    ok: bool
    reason: str = ""


def _record_gold_name(record: dict[str, Any]) -> str:
    return Path(record["gold_model"]).name


def rebuild(record: dict[str, Any], root: Path, target: Path,
            check: bool = True) -> Rebuild:
    """Run one task's gold script on its source model and check the result.

    A gold script that reproduced its model byte for byte when it was verified
    has to do so again, and its checksum is compared.  The minority whose
    re-execution agreed structurally rather than byte for byte (the IFC schema
    leaves the order of a set-valued attribute free, and IfcOpenShell rebuilds
    such sets from an unordered container) are checked by re-parsing and
    confirming that the entities the edit created are present and the ones it
    removed are gone.
    """
    started = time.perf_counter()
    source = root / record["input_ifc"]
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(suffix=".ifc", dir=str(target.parent))
    os.close(handle)
    try:
        script_lib.execute_script(record["gold_script"], str(source), temporary)
    except Exception as exc:
        os.path.exists(temporary) and os.remove(temporary)
        return Rebuild(record["task_id"], str(target), 0,
                       time.perf_counter() - started, "unchecked", False,
                       f"gold_script_failed: {exc!r}"[:200])

    verification = record.get("verification") or {}
    mode = "unchecked"
    ok = True
    reason = ""
    if check:
        if verification.get("reexecution_match") == "bytes" and \
                verification.get("gold_sha256"):
            mode = "sha256"
            digest = verify.sha256_of(temporary)
            ok = digest == verification["gold_sha256"]
            if not ok:
                reason = "checksum_mismatch"
        else:
            mode = "structure"
            guids = record.get("edit_guids") or {}
            created = list(guids.get("created") or ())
            removed = list(guids.get("removed") or ())
            stage = verify.check_parse(temporary, created, removed)
            ok = stage.ok
            if not ok:
                reason = stage.reason
    if not ok:
        os.remove(temporary)
        return Rebuild(record["task_id"], str(target), 0,
                       time.perf_counter() - started, mode, False, reason)
    size = os.path.getsize(temporary)
    os.replace(temporary, target)
    return Rebuild(record["task_id"], str(target), size,
                   time.perf_counter() - started, mode, True)


class GoldCache:
    """Gold models rebuilt on demand, in a directory bounded in files and bytes.

    ``max_bytes`` and ``max_files`` bound the directory, not the process.  A
    rebuild that would breach either bound evicts least-recently-used entries
    first, so the directory is never larger than the bounds allow.  Entries
    already present when the cache is opened are adopted, ordered by their
    modification time, so a restarted process reuses what the previous one
    built.
    """

    def __init__(self, root: str | os.PathLike, cache_dir: str | os.PathLike,
                 max_bytes: int = DEFAULT_MAX_BYTES,
                 max_files: int = DEFAULT_MAX_FILES, check: bool = True) -> None:
        self.root = Path(root)
        self.dir = Path(cache_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.max_bytes = int(max_bytes)
        self.max_files = int(max_files)
        self.check = check
        self._entries: OrderedDict[str, int] = OrderedDict()
        self._bytes = 0
        self.hits = 0
        self.misses = 0
        self.rebuild_seconds = 0.0
        self.failures: list[Rebuild] = []
        existing = sorted((p for p in self.dir.glob("*.ifc")),
                          key=lambda p: p.stat().st_mtime)
        for path in existing:
            size = path.stat().st_size
            self._entries[path.name] = size
            self._bytes += size
        self._evict()

    # ----------------------------------------------------------------- api

    def path_for(self, record: dict[str, Any]) -> Optional[Path]:
        """The gold model of one task, rebuilding it if it is not resident."""
        name = _record_gold_name(record)
        path = self.dir / name
        if name in self._entries and path.exists():
            self._entries.move_to_end(name)
            os.utime(path, None)
            self.hits += 1
            return path
        self.misses += 1
        self._evict(room_for=1)
        outcome = rebuild(record, self.root, path, self.check)
        self.rebuild_seconds += outcome.seconds
        if not outcome.ok:
            self.failures.append(outcome)
            return None
        self._entries[name] = outcome.bytes
        self._entries.move_to_end(name)
        self._bytes += outcome.bytes
        self._evict()
        return path

    def stats(self) -> dict[str, Any]:
        return {"resident": len(self._entries), "bytes": self._bytes,
                "max_bytes": self.max_bytes, "max_files": self.max_files,
                "hits": self.hits, "misses": self.misses,
                "rebuild_seconds": round(self.rebuild_seconds, 1),
                "failures": len(self.failures)}

    def clear(self) -> None:
        for name in list(self._entries):
            self._drop(name)

    # ------------------------------------------------------------ internal

    def _evict(self, room_for: int = 0) -> None:
        while self._entries and (
                len(self._entries) + room_for > self.max_files
                or self._bytes > self.max_bytes):
            self._drop(next(iter(self._entries)))

    def _drop(self, name: str) -> None:
        size = self._entries.pop(name, 0)
        self._bytes -= size
        try:
            (self.dir / name).unlink()
        except OSError:
            pass


# ------------------------------------------------------------------- bulk


_WORKER: dict[str, Any] = {}


def _init_worker(cores: Sequence[int], root: str, out_dir: str,
                 check: bool) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[name] = "1"
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    _WORKER.update({"root": Path(root), "out": Path(out_dir), "check": check})


def _rebuild_one(record: dict[str, Any]) -> dict[str, Any]:
    target = _WORKER["out"] / _record_gold_name(record)
    outcome = rebuild(record, _WORKER["root"], target, _WORKER["check"])
    return {"task_id": outcome.task_id, "ok": outcome.ok, "check": outcome.check,
            "bytes": outcome.bytes, "seconds": round(outcome.seconds, 2),
            "reason": outcome.reason}


def materialize_split(root: Path, tasks_path: Path, split: str, out_dir: Path,
                      workers: int = 6, cores: Sequence[int] = (),
                      check: bool = True) -> dict[str, Any]:
    """Write every gold model of one split into ``out_dir`` and keep it there."""
    records = [json.loads(line) for line in
               tasks_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    wanted = [r for r in records if split in ("all", r.get("split"))]
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    import multiprocessing as mp

    context = mp.get_context("fork")
    results: list[dict[str, Any]] = []
    with context.Pool(max(1, workers), initializer=_init_worker,
                      initargs=(list(cores), str(root), str(out_dir), check)) as pool:
        for index, outcome in enumerate(pool.imap_unordered(_rebuild_one, wanted, 4), 1):
            results.append(outcome)
            if index % 100 == 0 or index == len(wanted):
                print(f"  {index}/{len(wanted)} rebuilt", flush=True)
    ok = [r for r in results if r["ok"]]
    summary = {
        "split": split, "n_tasks": len(wanted), "n_rebuilt": len(ok),
        "n_failed": len(results) - len(ok),
        "checks": {mode: sum(1 for r in ok if r["check"] == mode)
                   for mode in ("sha256", "structure", "unchecked")},
        "bytes": sum(r["bytes"] for r in ok),
        "seconds": round(time.perf_counter() - started, 1),
        "failures": [r for r in results if not r["ok"]][:200],
        "out_dir": str(out_dir),
    }
    return summary


def main(argv: Optional[Sequence[str]] = None) -> int:
    from .run import parse_cores

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--tasks", default="data/veribim_tasks_v1/tasks.jsonl")
    parser.add_argument("--split", default="validation")
    parser.add_argument("--out", default=None,
                        help="default: the models/ directory the records name")
    parser.add_argument("--report", default=None)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--cores", default="")
    parser.add_argument("--no-check", action="store_true")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    tasks_path = Path(args.tasks) if os.path.isabs(args.tasks) else root / args.tasks
    out_dir = (Path(args.out) if args.out else tasks_path.parent / "models")
    if not out_dir.is_absolute():
        out_dir = root / out_dir
    summary = materialize_split(root, tasks_path, args.split, out_dir,
                                args.workers, parse_cores(args.cores)
                                if args.cores else (), not args.no_check)
    report = Path(args.report) if args.report else out_dir.parent / "materialize.json"
    if not report.is_absolute():
        report = root / report
    report.write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in
                      ("split", "n_tasks", "n_rebuilt", "n_failed", "checks",
                       "bytes", "seconds")}, indent=1))
    return 0 if summary["n_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
