"""Repair door and window tasks whose gold carries a predefined type the instruction never states.

From IFC4 on, IfcDoor and IfcWindow carry a ``PredefinedType``.  The generator
drew a random legal value for ``create_filling`` and ``replace_filling`` and wrote
it into the gold script and into ``edit_params.predefined_type``, but the
instruction never states it.  A reader of the instruction cannot produce that
value, so the gold is wrong for the task as written.

The rule, applied to any task file.  A task is affected when ``edit_kind`` is
``create_filling`` or ``replace_filling``, ``edit_params.predefined_type`` is not
None, and that exact token does not occur in ``instruction`` (the same substring
test ``stage_a.goldcode._stated_type`` applies).  For an affected task:

1. the single ``predefined_type='<T>'`` in ``gold_script`` becomes
   ``predefined_type=None`` (exactly one occurrence, or the task is listed as
   unrepairable and its line is copied unchanged);
2. ``edit_params.predefined_type`` becomes null;
3. the gold model is rebuilt from the edited script on the source model with
   ``modifc_gen.materialize.rebuild``; ``verification.gold_sha256`` and
   ``verification.gold_bytes`` take the new file's values, and
   ``verification.repair`` / ``verification.repair_old_gold_sha256`` record the
   repair and the old checksum;
4. nothing else in the record changes (asserted key by key).

Each repaired gold is verified before its record is written: a second rebuild
reproduces the new checksum under materialize's own check; the created or
replacing filling exists with ``PredefinedType`` unset; and the gold scores 1.0
on every axis against itself (``modifc_gen.verify.check_self_score``, i.e.
``modifc_score``).  On a deterministic sample the old gold is rebuilt from the old
script (its recorded checksum is checked) and compared with the new one by
``verify.model_signature`` over the touched guids, by a class and GlobalId census,
and by a line diff of the two STEP files.

Resumable: every finished task is appended to a journal next to the report, and
a rerun skips what the journal accounts for.  The output file is assembled from
the input and the journal only when every affected task is accounted for.

    python repair_filling_type.py --tasks IN.jsonl --out OUT.jsonl \
        --models-dir DIR --report REPORT.json [--workers 2] [--cores 8-9]
"""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
              "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ[_name] = "1"

import argparse
import copy
import gc
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

DEFAULT_ROOT = Path(".")
for _path in (DEFAULT_ROOT / "code", DEFAULT_ROOT / "code" / "harness"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from modifc_gen import materialize, verify  # noqa: E402

REPAIR_TAG = "filling_type_unstated_2026-09-26"
KINDS = ("create_filling", "replace_filling")
#: Every key path a repair may change.  The first four must change.
MUST_CHANGE = {"gold_script", "edit_params.predefined_type",
               "verification.gold_sha256", "verification.repair"}
MAY_CHANGE = MUST_CHANGE | {"verification.gold_bytes",
                            "verification.repair_old_gold_sha256"}


# ------------------------------------------------------------------ the rule


def stated_token(record: dict[str, Any]) -> Optional[str]:
    token = (record.get("edit_params") or {}).get("predefined_type")
    return None if token is None else str(token)


def is_affected(record: dict[str, Any]) -> bool:
    if record.get("edit_kind") not in KINDS:
        return False
    token = stated_token(record)
    if token is None:
        return False
    return token not in (record.get("instruction") or "")


def script_literal(token: str) -> str:
    # modifc_gen.script._literal writes a string argument with repr().
    return f"predefined_type={token!r}"


def occurrences(record: dict[str, Any]) -> int:
    return record["gold_script"].count(script_literal(stated_token(record)))


def edited(record: dict[str, Any]) -> dict[str, Any]:
    """Steps 1 and 2 of the rule; the checksum is not touched yet."""
    token = stated_token(record)
    new = copy.deepcopy(record)
    new["gold_script"] = record["gold_script"].replace(
        script_literal(token), "predefined_type=None")
    new["edit_params"]["predefined_type"] = None
    return new


def repaired(record: dict[str, Any], sha: str, size: int) -> dict[str, Any]:
    """The full repaired record, with every other key asserted unchanged."""
    new = edited(record)
    verification = new["verification"]
    old_sha = verification.get("gold_sha256")
    verification["gold_sha256"] = sha
    verification["gold_bytes"] = int(size)
    verification["repair"] = REPAIR_TAG
    verification["repair_old_gold_sha256"] = old_sha
    changed = set(diff_paths(record, new))
    assert changed <= MAY_CHANGE, sorted(changed - MAY_CHANGE)
    assert MUST_CHANGE <= changed, sorted(MUST_CHANGE - changed)
    return new


def diff_paths(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Dotted key paths at which two JSON values differ."""
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in list(old) + [k for k in new if k not in old]:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in old or key not in new:
                out.append(path)
            else:
                out.extend(diff_paths(old[key], new[key], path))
        return out
    if old != new or type(old) is not type(new):
        return [prefix]
    return []


# -------------------------------------------------------------- the sample


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def choose_samples(records: list[dict[str, Any]], root: Path, n: int,
                   max_mb: float) -> list[str]:
    """``n`` affected tasks, half per kind, spread round robin over buildings.

    Deterministic in the input alone, so a resumed run picks the same tasks.
    Sources above ``max_mb`` are left out, because the comparison parses the
    old and the new gold twice each.
    """
    chosen: list[str] = []
    per_kind = {KINDS[0]: n // 2, KINDS[1]: n - n // 2}
    for kind in KINDS:
        by_building: dict[str, list[dict]] = defaultdict(list)
        for r in records:
            if r["edit_kind"] != kind or source_mb(r, root) > max_mb:
                continue
            by_building[r.get("building_id") or r["input_ifc"]].append(r)
        for group in by_building.values():
            group.sort(key=lambda r: _h(r["task_id"]))
        order = sorted(by_building, key=_h)
        picked: list[str] = []
        depth = 0
        while len(picked) < per_kind[kind] and any(len(by_building[b]) > depth
                                                    for b in order):
            for building in order:
                if len(picked) >= per_kind[kind]:
                    break
                if len(by_building[building]) > depth:
                    picked.append(by_building[building][depth]["task_id"])
            depth += 1
        chosen.extend(picked)
    return chosen


_SIZE: dict[str, float] = {}


def source_mb(record: dict[str, Any], root: Path) -> float:
    path = record["input_ifc"]
    if path not in _SIZE:
        try:
            _SIZE[path] = (root / path).stat().st_size / 1e6
        except OSError:
            _SIZE[path] = 0.0
    return _SIZE[path]


# ------------------------------------------------------------ verification


def census(path: str) -> tuple[Counter, set]:
    """Instances per class, and every GlobalId, of one model."""
    import ifcopenshell

    model = ifcopenshell.open(path)
    classes = Counter(entity.is_a() for entity in model)
    guids = {entity.GlobalId for entity in model.by_type("IfcRoot")}
    del model
    gc.collect()
    return classes, guids


def step_line_diff(old_path: str, new_path: str, limit: int = 5) -> dict[str, Any]:
    """Lines at which two STEP files differ, compared in order."""
    differing = []
    n_old = n_new = 0
    with open(old_path, "rb") as fa, open(new_path, "rb") as fb:
        while True:
            a = fa.readline()
            b = fb.readline()
            if a:
                n_old += 1
            if b:
                n_new += 1
            if not a and not b:
                break
            if a != b:
                differing.append((a.decode("utf-8", "replace").rstrip("\n"),
                                  b.decode("utf-8", "replace").rstrip("\n")))
    return {"n_lines_old": n_old, "n_lines_new": n_new,
            "n_differing": len(differing), "pairs": differing[:limit]}


def compare_with_old(record: dict[str, Any], new_gold: Path, root: Path,
                     work: Path) -> dict[str, Any]:
    """Rebuild the old gold from the old script and compare it with the new one."""
    token = stated_token(record)
    filling = record["target"]["guids"][0]
    old_path = work / f"old_{Path(new_gold).name}"
    out: dict[str, Any] = {"ok": False}
    rebuilt = materialize.rebuild(record, root, old_path, check=True)
    out["old_rebuild"] = {"ok": rebuilt.ok, "check": rebuilt.check,
                          "reason": rebuilt.reason}
    if not rebuilt.ok:
        out["reason"] = f"old gold did not rebuild: {rebuilt.reason}"
        return out
    try:
        touched = list((record.get("edit_guids") or {}).get("touched") or ())
        sig_old = verify.model_signature(str(old_path), touched)
        sig_new = verify.model_signature(str(new_gold), touched)
        faults = []
        if sig_old["guids"] != sig_new["guids"]:
            faults.append("guid_set_differs")
        if sig_old["counts"] != sig_new["counts"]:
            faults.append("relation_counts_differ")
        for guid in touched:
            a, b = sig_old["entities"].get(guid), sig_new["entities"].get(guid)
            if guid != filling:
                if a != b:
                    faults.append(f"touched_entity_differs:{guid}")
                continue
            if a is None or b is None:
                faults.append("filling_missing")
                continue
            attrs_a, attrs_b = dict(a[1]), dict(b[1])
            if attrs_a.get("PredefinedType") != token:
                faults.append(f"old_filling_type={attrs_a.get('PredefinedType')}")
            if attrs_b.get("PredefinedType") is not None:
                faults.append(f"new_filling_type={attrs_b.get('PredefinedType')}")
            attrs_a.pop("PredefinedType", None)
            attrs_b.pop("PredefinedType", None)
            if a[0] != b[0] or a[2] != b[2] or attrs_a != attrs_b:
                faults.append("filling_differs_beyond_type")
        del sig_old, sig_new
        gc.collect()
        classes_old, guids_old = census(str(old_path))
        classes_new, guids_new = census(str(new_gold))
        if classes_old != classes_new:
            faults.append("class_census_differs")
        if guids_old != guids_new:
            faults.append("globalid_census_differs")
        out["census"] = {"n_instances": sum(classes_new.values()),
                         "n_classes": len(classes_new), "n_globalids": len(guids_new)}
        lines = step_line_diff(str(old_path), str(new_gold))
        out["line_diff"] = {k: lines[k] for k in
                            ("n_lines_old", "n_lines_new", "n_differing")}
        if lines["n_differing"] != 1 or lines["n_lines_old"] != lines["n_lines_new"]:
            faults.append(f"line_diff_{lines['n_differing']}")
            out["line_diff"]["pairs"] = [(a[:300], b[:300]) for a, b in lines["pairs"]]
        else:
            a, b = lines["pairs"][0]
            out["line_diff"]["old"] = a[:400]
            out["line_diff"]["new"] = b[:400]
            if a.replace(f".{token}.", "$", 1) != b or filling not in a:
                faults.append("differing_line_is_not_the_filling_type")
        out["faults"] = faults
        out["ok"] = not faults
        return out
    finally:
        if old_path.exists():
            old_path.unlink()


# --------------------------------------------------------------- one task


_WORKER: dict[str, Any] = {}


def _init_worker(root: str, models_dir: str, cores: list[int],
                 keep_all: bool = False) -> None:
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    from modifc_score.model_cache import MESHES, MODELS

    MODELS.capacity = 2
    MESHES.capacity_vertices = 800_000
    _WORKER.update(root=Path(root), models=Path(models_dir), keep_all=keep_all)


def repair_one(job: tuple[dict[str, Any], bool]) -> dict[str, Any]:
    record, is_sample = job
    root: Path = _WORKER["root"]
    models: Path = _WORKER["models"]
    started = time.perf_counter()
    token = stated_token(record)
    out: dict[str, Any] = {
        "task_id": record["task_id"], "edit_kind": record["edit_kind"],
        "split": record.get("split"), "building_id": record.get("building_id"),
        "input_ifc": record["input_ifc"], "token": token,
        "old_sha": (record.get("verification") or {}).get("gold_sha256"),
        "old_bytes": (record.get("verification") or {}).get("gold_bytes"),
        "sample": bool(is_sample), "ok": False,
    }
    target = models / Path(record["gold_model"]).name
    replay_dir = models / "_replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    try:
        n = occurrences(record)
        if n != 1:
            out.update(stage="script", reason=f"predefined_type_occurrences={n}")
            return out
        work = edited(record)
        built = materialize.rebuild(work, root, target, check=False)
        if not built.ok:
            out.update(stage="rebuild", reason=built.reason)
            return out
        sha = verify.sha256_of(str(target))
        size = target.stat().st_size
        out.update(new_sha=sha, new_bytes=size)
        final = repaired(record, sha, size)

        # A later rebuild (GoldCache, materialize_split) checks this checksum, so
        # the edited script has to reproduce it byte for byte.
        again = materialize.rebuild(final, root, replay_dir / target.name,
                                    check=True)
        (replay_dir / target.name).unlink(missing_ok=True)
        out["reexecution"] = {"ok": again.ok, "check": again.check,
                              "reason": again.reason}
        if not again.ok:
            out.update(stage="reexecution", reason=again.reason)
            return out

        from modifc_score.model_cache import MESHES, MODELS

        source = str(root / record["input_ifc"])
        stage = verify.check_self_score(
            record["task_id"], record["operation"], record["category"],
            record["target"]["entity_type"], record["target"]["guids"],
            source, str(target))
        axes = {k: stage.detail.get(k) for k in
                ("geometry", "semantics", "topology", "final")}
        out["self_score"] = axes
        if not stage.ok or any(v is None or float(v) < 1.0 - 1e-9
                               for v in axes.values()):
            out.update(stage="self_score", reason=stage.reason or "below_1.0")
            return out
        model = MODELS.get(str(target))
        guid = record["target"]["guids"][0]
        try:
            filling = model.by_guid(guid)
        except Exception:
            filling = None
        if filling is None:
            out.update(stage="filling", reason="filling_missing")
            return out
        out["filling"] = {"class": filling.is_a(),
                          "predefined_type": getattr(filling, "PredefinedType", None)}
        if filling.is_a() != record["target"]["entity_type"] or \
                getattr(filling, "PredefinedType", None) is not None:
            out.update(stage="filling", reason="filling_class_or_type_wrong")
            return out
        del model, filling
        MODELS.clear()
        MESHES.clear()
        gc.collect()

        if is_sample:
            comparison = compare_with_old(record, target, root, replay_dir)
            out["comparison"] = comparison
            if not comparison["ok"]:
                out.update(stage="comparison",
                           reason=";".join(comparison.get("faults") or
                                           [comparison.get("reason", "?")]))
                return out
        out.update(ok=True, stage="repaired", reason="")
        return out
    except Exception as exc:  # noqa: BLE001 - the journal is the report
        out.update(stage="exception", reason=f"{type(exc).__name__}: {exc}"[:300])
        return out
    finally:
        try:
            from modifc_score.model_cache import MESHES, MODELS

            MODELS.clear()
            MESHES.clear()
        except Exception:  # noqa: BLE001
            pass
        gc.collect()
        # The gold models are large: keep only the verification samples, unless
        # every repaired gold is wanted (a benchmark file whose golds live on disk).
        keep = out.get("ok") and (is_sample or _WORKER.get("keep_all"))
        if not keep and target.exists():
            target.unlink()
        out["kept_model"] = bool(target.exists())
        out["seconds"] = round(time.perf_counter() - started, 2)


# ------------------------------------------------------------------ driver


def read_journal(path: Path, by_id: Optional[dict[str, dict]] = None
                 ) -> dict[str, dict[str, Any]]:
    """Journal entries by task id; the last entry of a task wins.

    With ``by_id``, an entry written for a different record under the same id
    (another input file sharing the report path, or a regenerated task) is
    dropped, so the task is run again rather than given a stale checksum.
    """
    done: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            done[entry["task_id"]] = entry
    if by_id is not None:
        for task_id in list(done):
            record = by_id.get(task_id)
            if record is None:
                continue
            if (done[task_id].get("old_sha") !=
                    (record.get("verification") or {}).get("gold_sha256")
                    or done[task_id].get("token") != stated_token(record)):
                del done[task_id]
    return done


def parse_cores(text: str) -> list[int]:
    cores: list[int] = []
    for part in (text or "").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-")
            cores.extend(range(int(lo), int(hi) + 1))
        else:
            cores.append(int(part))
    return cores


def run_pool(jobs, workers, root, models_dir, cores, journal_fh, label,
             keep_all=False):
    import multiprocessing as mp

    if not jobs:
        return
    context = mp.get_context("fork")
    total = len(jobs)
    started = time.perf_counter()
    print(f"[{label}] {total} tasks on {workers} worker(s)", flush=True)
    with context.Pool(max(1, workers), initializer=_init_worker,
                      initargs=(str(root), str(models_dir), cores, keep_all),
                      maxtasksperchild=3) as pool:
        for index, result in enumerate(pool.imap_unordered(repair_one, jobs, 1), 1):
            journal_fh.write(json.dumps(result, ensure_ascii=False) + "\n")
            journal_fh.flush()
            if index % 10 == 0 or index == total or not result["ok"]:
                rate = index / max(1e-9, time.perf_counter() - started)
                print(f"[{label}] {index}/{total} {result['task_id']} "
                      f"{'ok' if result['ok'] else 'FAIL ' + result.get('reason', '')} "
                      f"{result.get('seconds')}s; {rate * 3600:.0f}/h", flush=True)


def assemble(tasks: Path, out: Path, journal: dict[str, dict[str, Any]],
             affected_ids: set[str]) -> dict[str, Any]:
    """The output file: repaired lines where the journal says so, the rest verbatim."""
    temporary = out.with_suffix(out.suffix + ".tmp")
    counts = Counter()
    with tasks.open("rb") as fin, temporary.open("wb") as fout:
        for raw in fin:
            if not raw.strip():
                fout.write(raw)
                continue
            record = json.loads(raw)
            entry = journal.get(record["task_id"])
            if record["task_id"] in affected_ids and entry and entry.get("ok"):
                new = repaired(record, entry["new_sha"], entry["new_bytes"])
                line = json.dumps(new, ensure_ascii=False) + "\n"
                fout.write(line.encode("utf-8"))
                counts["repaired"] += 1
            else:
                fout.write(raw)
                counts["unrepairable" if record["task_id"] in affected_ids
                       else "unaffected"] += 1
    os.replace(temporary, out)
    return dict(counts)


def check_output(tasks: Path, out: Path, journal: dict[str, dict[str, Any]],
                 affected_ids: set[str]) -> dict[str, Any]:
    """Re-read both files: verbatim lines are byte-identical, repaired ones differ
    only at the allowed keys, and no repaired record is still affected."""
    result = Counter()
    with tasks.open("rb") as fa, out.open("rb") as fb:
        for a, b in zip(fa, fb, strict=True):
            old = json.loads(a)
            entry = journal.get(old["task_id"])
            if old["task_id"] in affected_ids and entry and entry.get("ok"):
                new = json.loads(b)
                changed = set(diff_paths(old, new))
                assert changed <= MAY_CHANGE and MUST_CHANGE <= changed, changed
                assert not is_affected(new)
                assert new["verification"]["gold_sha256"] == entry["new_sha"]
                assert "predefined_type=None" in new["gold_script"]
                result["repaired_checked"] += 1
            else:
                assert a == b, old["task_id"]
                result["verbatim_checked"] += 1
    return dict(result)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--models-dir", required=True,
                        help="rebuilt gold models; only the verification samples stay")
    parser.add_argument("--report", required=True)
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--cores", default="8-9")
    parser.add_argument("--samples", type=int, default=30,
                        help="tasks whose old gold is rebuilt and compared")
    parser.add_argument("--sample-max-mb", type=float, default=25.0)
    parser.add_argument("--large-mb", type=float, default=40.0,
                        help="sources at least this large run one at a time")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--keep-all-models", action="store_true",
                        help="keep every repaired gold model in --models-dir, not"
                             " only the samples (for a file whose golds are"
                             " materialized on disk)")
    parser.add_argument("--task-ids", nargs="*", default=[],
                        help="restrict the repair to these ids (testing)")
    args = parser.parse_args(argv)

    if args.workers > 2:
        parser.error("at most two workers")
    started = time.perf_counter()
    root = Path(args.root).resolve()
    tasks = Path(args.tasks).resolve()
    out = Path(args.out).resolve()
    models_dir = Path(args.models_dir).resolve()
    report = Path(args.report).resolve()
    journal_path = report.with_suffix(".journal.jsonl")
    models_dir.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    cores = parse_cores(args.cores)
    if cores and hasattr(os, "sched_setaffinity"):
        os.sched_setaffinity(0, set(cores))

    records = []
    n_lines = 0
    by_kind = Counter()
    with tasks.open(encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            n_lines += 1
            record = json.loads(line)
            if is_affected(record):
                records.append(record)
                by_kind[(record["edit_kind"], record.get("split") or "")] += 1
    if args.task_ids:
        wanted = set(args.task_ids)
        records = [r for r in records if r["task_id"] in wanted]
    affected_ids = {r["task_id"] for r in records}
    samples = set(choose_samples(records, root, args.samples, args.sample_max_mb))

    by_id = {r["task_id"]: r for r in records}
    journal = read_journal(journal_path, by_id)
    if args.retry_failed:
        journal = {k: v for k, v in journal.items() if v.get("ok")}
    pending = [r for r in records if r["task_id"] not in journal]
    print(f"{n_lines} tasks, {len(records)} affected, {len(samples)} samples, "
          f"{len(records) - len(pending)} already in the journal", flush=True)

    # Largest sources last and one at a time: the self-score holds the source and
    # the gold parsed together, about 25x the file size each.
    small = [(r, r["task_id"] in samples) for r in pending
             if source_mb(r, root) < args.large_mb]
    large = [(r, r["task_id"] in samples) for r in pending
             if source_mb(r, root) >= args.large_mb]
    small.sort(key=lambda job: (job[0]["input_ifc"], job[0]["task_id"]))
    large.sort(key=lambda job: (job[0]["input_ifc"], job[0]["task_id"]))
    with journal_path.open("a", encoding="utf-8") as journal_fh:
        run_pool(small, args.workers, root, models_dir, cores, journal_fh, "small",
                 args.keep_all_models)
        run_pool(large, 1, root, models_dir, cores, journal_fh, "large",
                 args.keep_all_models)

    try:
        (models_dir / "_replay").rmdir()
    except OSError:
        pass
    journal = read_journal(journal_path, by_id)
    missing = [t for t in affected_ids if t not in journal]
    entries = [journal[t] for t in sorted(affected_ids) if t in journal]
    summary: dict[str, Any] = {
        "tasks": str(tasks), "out": str(out), "models_dir": str(models_dir),
        "journal": str(journal_path), "rule": REPAIR_TAG,
        "n_tasks": n_lines,
        "n_affected": len(affected_ids),
        "affected_by_kind_split": {f"{k}/{s}": n for (k, s), n in sorted(by_kind.items())},
        "n_accounted": len(entries), "n_missing": len(missing),
    }
    ok = [e for e in entries if e.get("ok")]
    bad = [e for e in entries if not e.get("ok")]
    summary.update({
        "n_repaired": len(ok),
        "repaired_by_kind": dict(Counter(e["edit_kind"] for e in ok)),
        "n_unrepairable": len(bad),
        "unrepairable": [{k: e.get(k) for k in ("task_id", "edit_kind", "split",
                                                "stage", "reason")} for e in bad],
        "unrepairable_reasons": dict(Counter(f"{e.get('stage')}: {e.get('reason')}"[:120]
                                             for e in bad)),
        "verification": {
            "reexecution_bytes_ok": sum(1 for e in ok
                                        if (e.get("reexecution") or {}).get("ok")),
            "self_score_all_axes_1": sum(1 for e in ok if e.get("self_score") and all(
                float(v) >= 1.0 - 1e-9 for v in e["self_score"].values())),
            "filling_type_unset": sum(1 for e in ok if (e.get("filling") or {})
                                      .get("predefined_type") is None
                                      and e.get("filling")),
            "samples_selected": len(samples),
            "samples_compared_ok": sum(1 for e in ok if e.get("sample")
                                       and (e.get("comparison") or {}).get("ok")),
            "samples_failed": [e["task_id"] for e in bad if e.get("sample")],
            "sample_ids": sorted(samples),
        },
        "types_removed": dict(Counter(e["token"] for e in ok)),
        "gold_bytes_new_total": sum(int(e.get("new_bytes") or 0) for e in ok),
        "task_seconds_total": round(sum(float(e.get("seconds") or 0) for e in entries), 1),
    })
    if not missing:
        summary["assembled"] = assemble(tasks, out, journal, affected_ids)
        summary["output_check"] = check_output(tasks, out, journal, affected_ids)
    else:
        summary["assembled"] = None
        summary["missing_ids"] = sorted(missing)[:50]
    summary["wall_seconds_this_run"] = round(time.perf_counter() - started, 1)
    report.write_text(json.dumps(summary, indent=1, ensure_ascii=False),
                      encoding="utf-8")
    print(json.dumps({k: summary[k] for k in
                      ("n_tasks", "n_affected", "n_repaired", "n_unrepairable",
                       "n_missing", "assembled", "wall_seconds_this_run")},
                     indent=1), flush=True)
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
