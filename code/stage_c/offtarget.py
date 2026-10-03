"""Off-target changes: elements a model changed outside the edit it was asked for.

The checker reads geometry and semantics only on the task's target class, and
topology only through the relation graph. A model that deletes the requested
door and also moves a wall is therefore seen only through the relations the
move alters. This module counts such changes for every task of one benchmark
read, so that each read can report how many elements outside the intended edit
the model changed.

Definition
----------
For a task with input model I, ground-truth model G and edited model E:

* ``changed(I -> X)`` is the set of IfcProduct instances, keyed by GlobalId,
  that were created in X (GlobalId absent from I), deleted from X (GlobalId
  absent from X), or whose signature differs between I and X. The signature
  of a product has three parts, each a stable content hash:

  - placement: the product's world transformation, the 4x4 matrix obtained by
    composing its ObjectPlacement with every ``PlacementRelTo`` parent. An
    element counts as moved when this matrix differs, whichever placement
    entity the edit rewrote, so rebuilding or re-parenting a placement without
    moving anything is not a change. A modification whose own relative
    placement also differs is labelled ``placement``; one that moved only
    because a parent placement moved (a door placed relative to its opening,
    an opening relative to its wall) is labelled ``placement_carried``. A
    placement chain that is not made of IfcLocalPlacement entities (grid or
    linear placement) is hashed through its entity graph instead, with each
    ``PlacementRelTo`` link read as the GlobalIds of the products the parent
    placement places;
  - representation: the product's Representation, hashed through its whole
    entity graph (shape representations, items, mapped representations,
    points);
  - attributes: every other direct attribute of the product's own entity.
    OwnerHistory is ignored everywhere, since it changes on every write. An
    entity-valued attribute that points to another IfcRoot is hashed as that
    entity's GlobalId, and any other entity reference is hashed through its
    content.

  Entity ids (``#n``) never enter a hash, so a file rewritten with new numbering
  hashes the same. Real numbers are rounded to 10 significant digits, and
  magnitudes below 1e-9 are read as zero, so a write/read round trip does not
  register as a change. Relations (containment, voids, fills, property sets,
  materials, types) are not direct attributes and are not compared; the
  checker's topology axis reads them.

* ``off_target(E) = changed(I -> E) - changed(I -> G) - covered(E)``, where
  ``covered(E)`` is the GlobalId set of the checker's own edit set,
  ``modifc_score.editset.build_edit_set(I, E, operation, entity_type,
  target_guids)``, called with the task's operation, target entity type and
  target GlobalIds exactly as the scorer calls it for the geometry pool. The
  one departure is schema naming: ``IfcBuildingElement`` does not exist in
  IFC4X3, where it is ``IfcBuiltElement``, so on an IFC4X3 model the edit set is
  built on ``IfcBuiltElement`` and the row records ``edit_set_type_aliased``.

Per task the row reports ``off_target_count``, a counter of the entity types
in it, the kind of each change (created, deleted, modified, and for a
modification which signature parts differ), and ``completed``: geometry,
semantics and topology all at least 0.9 in the read's per-task row.

A second count, ``off_target_count_net``, removes created elements that stand
for an element the ground truth also created under a different GlobalId: per
entity class, as many off-target creations as the ground truth has unmatched
creations of that class. An opening created together with a requested wall and
door is the typical case. The first count follows the definition above
literally; the second is the reading that does not charge a model for choosing
its own GlobalIds.

Because ``covered(E)`` is the checker's edit set, a create task's extra
elements of the target class are covered and never counted. The row reports
them separately as ``edit_set_surplus``: the size of the edited model's edit
set minus the size of the gold's, floored at zero.

A third count, ``off_target_count_direct``, is the net count without the
entries whose only difference is ``placement_carried``: the elements the model
changed itself, as opposed to elements a moved host carried along.

A task whose model never committed an edit has no edited model; it is
recorded with ``status = "no_edited_model"`` and left out of every share.

Run in the ``l2`` environment from the project root, pinned to its cores:

    OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 \\
    PYTHONPATH=code:code/harness taskset -c 0-7 \\
        python -m stage_c.offtarget \\
            --per-task runs_local/stage_a_v10/gates/v500/per_task_sft_v10.jsonl \\
            --tasks runs_local/stage_a_v10/val_tasks_500_v3.jsonl \\
            --edited-dir runs_local/stage_a_v10/gates/v500/sft_v10/edited \\
            --out-dir runs_local/offtarget/sft_v10_v500 --workers 3

Writes ``<out-dir>/offtarget_per_task.jsonl`` (one row per task, appended as
tasks finish, so a rerun skips tasks already written) and
``<out-dir>/offtarget_summary.json``. Input files are only read. Gold models
that are not already on disk are rebuilt into ``--gold-cache``; directories
named by ``--gold-lookup`` are searched first and only read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import resource
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Optional

PROJECT_ROOT = Path(os.environ.get("VERIBIM_ROOT", Path(__file__).resolve().parents[2]))
COMPLETED_FLOOR = 0.9
DEFAULT_GOLD_CACHE = PROJECT_ROOT / "runs_local/offtarget/_gold"
DEFAULT_GOLD_LOOKUP = (PROJECT_ROOT / "runs_local/stage_a_v10/gates/_gold_v3",)
LIST_CAP = 200          # off-target entries kept per row
SIG_DIGITS = 10
ZERO_BELOW = 1e-9

#: Class names that differ between schemas for the same concept.
SCHEMA_ALIASES = {
    "IFC4X3": {"IfcBuildingElement": "IfcBuiltElement"},
    "IFC2X3": {"IfcBuiltElement": "IfcBuildingElement"},
    "IFC4": {"IfcBuiltElement": "IfcBuildingElement"},
}


# ------------------------------------------------------------------ hashing


def _schema_key(model) -> str:
    schema = str(model.schema).upper()
    if schema.startswith("IFC4X3"):
        return "IFC4X3"
    return schema


class ProductHasher:
    """Signatures of every IfcProduct of one model, keyed by GlobalId."""

    def __init__(self, model) -> None:
        self.model = model
        self.schema = _schema_key(model)
        self._memo: dict[int, bytes] = {}
        self._names: dict[str, tuple[str, ...]] = {}
        self._placed_by: dict[int, tuple[str, ...]] = {}
        products = list(model.by_type("IfcProduct"))
        owners: dict[int, list[str]] = defaultdict(list)
        for product in products:
            placement = getattr(product, "ObjectPlacement", None)
            if placement is not None:
                owners[placement.id()].append(product.GlobalId)
        self._placed_by = {k: tuple(sorted(v)) for k, v in owners.items()}
        self._world: dict[int, Any] = {}
        self.products = products

    # -- helpers -------------------------------------------------------

    def _attr_names(self, entity) -> tuple[str, ...]:
        cls = entity.is_a()
        names = self._names.get(cls)
        if names is None:
            names = tuple(entity.wrapped_data.get_attribute_names())
            self._names[cls] = names
        return names

    @staticmethod
    def _real(value: float) -> str:
        if value != value:  # NaN
            return "nan"
        if abs(value) < ZERO_BELOW:
            return "0"
        return format(value, f".{SIG_DIGITS}g")

    def _value(self, value: Any, parent_link: bool = False) -> Any:
        """A hashable, id-free rendering of one attribute value."""
        if value is None:
            return None
        if isinstance(value, bool):
            return value
        if isinstance(value, float):
            return self._real(value)
        if isinstance(value, (int, str)):
            return value
        if isinstance(value, (tuple, list)):
            return tuple(self._value(v, parent_link) for v in value)
        # entity_instance
        try:
            is_a = value.is_a
        except AttributeError:
            return repr(value)
        if value.id() == 0:
            # A typed value such as IfcLabel('x') or IfcLengthMeasure(1.0).
            return (value.is_a(), self._value(value.wrappedValue))
        if is_a("IfcOwnerHistory"):
            return "OwnerHistory"
        if parent_link and is_a("IfcObjectPlacement"):
            placed = self._placed_by.get(value.id())
            if placed:
                return ("placement-of", placed)
        if is_a("IfcRoot"):
            return ("root", value.GlobalId)
        return self._entity(value)

    def _entity(self, entity) -> bytes:
        """Content hash of one non-rooted entity and everything it references."""
        key = entity.id()
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        names = self._attr_names(entity)
        parts: list[Any] = [entity.is_a()]
        for index, name in enumerate(names):
            try:
                raw = entity[index]
            except Exception:  # derived or unreadable attribute
                raw = "<unreadable>"
            parts.append(self._value(raw, parent_link=(name == "PlacementRelTo")))
        digest = hashlib.blake2b(repr(parts).encode("utf-8"), digest_size=16).digest()
        self._memo[key] = digest
        return digest

    def _world_matrix(self, placement):
        """World matrix of an IfcLocalPlacement chain, or None for any other kind."""
        key = placement.id()
        if key in self._world:
            return self._world[key]
        matrix = None
        if placement.is_a("IfcLocalPlacement"):
            try:
                import ifcopenshell.util.placement as util_placement
                local = util_placement.get_axis2placement(placement.RelativePlacement)
                parent = placement.PlacementRelTo
                if parent is None:
                    matrix = local
                else:
                    above = self._world_matrix(parent)
                    matrix = None if above is None else above @ local
            except Exception:
                matrix = None
        self._world[key] = matrix
        return matrix

    def _placement_hashes(self, placement) -> tuple[str, str]:
        """(world hash, own relative placement hash) of one ObjectPlacement."""
        if placement is None:
            return "-", "-"
        matrix = self._world_matrix(placement)
        if matrix is None:
            content = self._entity(placement).hex()
            return "content:" + content, content
        world = tuple(self._real(float(v)) for v in matrix[:3, :].ravel())
        world_hash = hashlib.blake2b(repr(world).encode("utf-8"), digest_size=16).hexdigest()
        relative = getattr(placement, "RelativePlacement", None)
        local = self._entity(relative).hex() if relative is not None else "-"
        return "world:" + world_hash, local

    def signature(self, product) -> tuple[str, str, str, str, str]:
        """(class, world placement, representation, attributes, own relative placement)."""
        names = self._attr_names(product)
        attrs: list[Any] = [product.is_a()]
        placement = representation = None
        for index, name in enumerate(names):
            if name in ("OwnerHistory", "GlobalId"):
                continue
            value = product[index]
            if name == "ObjectPlacement":
                placement = value
            elif name == "Representation":
                representation = value
            else:
                attrs.append((name, self._value(value)))
        h_place, h_local = self._placement_hashes(placement)
        h_repr = (self._entity(representation).hex()
                  if representation is not None else "-")
        h_attr = hashlib.blake2b(repr(attrs).encode("utf-8"), digest_size=16).hexdigest()
        return product.is_a(), h_place, h_repr, h_attr, h_local

    def signatures(self) -> tuple[dict[str, tuple[str, ...]], int]:
        """GlobalId -> signature, and the number of duplicated GlobalIds."""
        out: dict[str, tuple[str, ...]] = {}
        duplicates = 0
        for product in self.products:
            guid = product.GlobalId
            if guid in out:
                duplicates += 1
                continue
            out[guid] = self.signature(product)
        return out, duplicates


PARTS = ("placement", "representation", "attributes")


def changed(sig_0: dict, sig_x: dict) -> dict[str, dict[str, Any]]:
    """GlobalId -> {kind, class, parts} for every product X changed against I."""
    out: dict[str, dict[str, Any]] = {}
    for guid, sig in sig_x.items():
        before = sig_0.get(guid)
        if before is None:
            out[guid] = {"kind": "created", "class": sig[0], "parts": []}
            continue
        parts = [PARTS[i] for i in range(3) if before[i + 1] != sig[i + 1]]
        if "placement" in parts and before[4] == sig[4]:
            parts[parts.index("placement")] = "placement_carried"
        if before[0] != sig[0]:
            parts.insert(0, "class")
        if parts:
            out[guid] = {"kind": "modified", "class": sig[0], "parts": parts}
    for guid, sig in sig_0.items():
        if guid not in sig_x:
            out[guid] = {"kind": "deleted", "class": sig[0], "parts": []}
    return out


def schema_type(model, entity_type: str) -> tuple[str, bool]:
    """The target class under this model's schema, and whether it was renamed."""
    if not entity_type:
        return entity_type, False
    alias = SCHEMA_ALIASES.get(_schema_key(model), {}).get(entity_type)
    if alias is None:
        return entity_type, False
    try:
        model.by_type(entity_type)
        return entity_type, False
    except Exception:
        return alias, True


def off_target(sig_i: dict, sig_g: dict, sig_e: dict, covered: Iterable[str],
               target_guids: Iterable[str] = ()) -> dict[str, Any]:
    """The off-target set of one task from the three models' signatures."""
    ch_e = changed(sig_i, sig_e)
    ch_g = changed(sig_i, sig_g)
    covered = set(covered)
    targets = set(target_guids)
    rest = {g: v for g, v in ch_e.items() if g not in ch_g and g not in covered}

    # Ground-truth creations of a class that the edited model did not
    # reproduce under the same GlobalId, available to pair with off-target
    # creations of the same class.
    open_gold = Counter(v["class"] for g, v in ch_g.items()
                        if v["kind"] == "created" and g not in sig_e)
    net_drop: set[str] = set()
    for guid in sorted(rest):
        item = rest[guid]
        if item["kind"] == "created" and open_gold[item["class"]] > 0:
            open_gold[item["class"]] -= 1
            net_drop.add(guid)
    net = {g: v for g, v in rest.items() if g not in net_drop}

    def describe(items: dict) -> list[dict]:
        return [{"guid": g, "class": v["class"], "kind": v["kind"],
                 "parts": v["parts"]} for g, v in sorted(
                     items.items(), key=lambda kv: (kv[1]["class"], kv[0]))]

    return {
        "n_products_input": len(sig_i),
        "n_changed_edited": len(ch_e),
        "n_changed_gold": len(ch_g),
        "n_covered_by_edit_set": len(covered),
        "off_target_count": len(rest),
        "off_target_types": dict(Counter(v["class"] for v in rest.values())),
        "off_target_kinds": dict(Counter(v["kind"] for v in rest.values())),
        "off_target_parts": dict(Counter(p for v in rest.values() for p in v["parts"])),
        "off_target_includes_task_target": sorted(targets & set(rest)),
        "off_target": describe(rest)[:LIST_CAP],
        "off_target_count_net": len(net),
        "off_target_net_types": dict(Counter(v["class"] for v in net.values())),
        # Net entries that moved only because a parent placement moved.
        "off_target_carried": sum(1 for v in net.values()
                                  if v["parts"] == ["placement_carried"]),
        "off_target_count_direct": sum(1 for v in net.values()
                                       if v["parts"] != ["placement_carried"]),
        "off_target_direct_types": dict(Counter(
            v["class"] for v in net.values() if v["parts"] != ["placement_carried"])),
        "created_counterparts": len(net_drop),
    }


# ------------------------------------------------------------------ gold


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _verification(record: dict) -> dict:
    verification = record.get("verification") or {}
    if isinstance(verification, str):
        import ast
        try:
            verification = ast.literal_eval(verification)
        except Exception:
            verification = {}
    return verification if isinstance(verification, dict) else {}


class GoldResolver:
    """Finds or rebuilds a task's gold model without writing outside its cache."""

    def __init__(self, cache_root: Path, lookup: Iterable[Path], slot: str) -> None:
        self.cache_root = Path(cache_root)
        self.lookup = [Path(p) for p in lookup]
        self.slot = slot
        self._cache = None

    def _search(self, name: str) -> Optional[Path]:
        # The own cache first: a lookup directory may belong to a live run
        # that evicts and rebuilds its files while this one reads them.
        for root in [self.cache_root, *self.lookup]:
            if not root.is_dir():
                continue
            for candidate in [root / name, *sorted(root.glob(f"*/{name}"))]:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
        return None

    def resolve(self, record: dict, rebuild: bool = False) -> tuple[Optional[Path], str]:
        named = PROJECT_ROOT / record["ground_truth_ifc"]
        if named.is_file() and named.stat().st_size > 0:
            return named, "record_path"
        name = Path(record.get("gold_model") or record["ground_truth_ifc"]).name
        found = None if rebuild else self._search(name)
        if found is not None:
            verification = _verification(record)
            expected = verification.get("gold_sha256")
            if verification.get("reexecution_match") == "bytes" and expected:
                if _sha256(found) == expected:
                    return found, "lookup_sha256"
            else:
                return found, "lookup_unchecked"
        if self._cache is None:
            from stage_a.goldmodels import open_cache
            self._cache = open_cache(self.cache_root / self.slot,
                                     max_bytes=8 << 30, max_files=1000)
        record = dict(record)
        record["verification"] = _verification(record)
        path = self._cache.path_for(record)
        return (path, "rebuilt") if path is not None else (None, "rebuild_failed")


# ------------------------------------------------------------------ worker


_W: dict[str, Any] = {}


def _rss_mb() -> tuple[float, float]:
    current = 0.0
    try:
        with open("/proc/self/status") as fh:
            for line in fh:
                if line.startswith("VmRSS:"):
                    current = int(line.split()[1]) / 1024
                    break
    except OSError:
        pass
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    return round(current, 1), round(peak, 1)


def _init_worker(gold_cache: str, lookup: list[str], project_root: str) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    sys.setrecursionlimit(20000)
    import multiprocessing as mp
    identity = getattr(mp.current_process(), "_identity", ()) or ()
    slot = "w" + ("-".join(str(i) for i in identity) if identity else str(os.getpid()))
    _W.update(gold=GoldResolver(Path(gold_cache), [Path(p) for p in lookup], slot),
              root=Path(project_root), input_key=None, input_model=None,
              input_sig=None, input_dups=0)


def _input(path: Path):
    key = str(path)
    if _W.get("input_key") != key:
        import ifcopenshell
        _W["input_model"] = None
        _W["input_sig"] = None
        model = ifcopenshell.open(key)
        sig, dups = ProductHasher(model).signatures()
        _W.update(input_key=key, input_model=model, input_sig=sig, input_dups=dups)
    return _W["input_model"], _W["input_sig"], _W["input_dups"]


def completed_from(row: dict) -> Optional[bool]:
    score = row.get("score") or None
    if not score:
        return None
    try:
        return all(float(score[a]) >= COMPLETED_FLOOR
                   for a in ("geometry", "semantics", "topology"))
    except (KeyError, TypeError, ValueError):
        return None


def evaluate(payload: tuple[dict, dict, str]) -> dict:
    """One task: the off-target row, with its time and memory."""
    import ifcopenshell
    from modifc_score.editset import build_edit_set

    record, row, edited = payload
    started = time.perf_counter()
    target = record.get("target") or {}
    entity_type = target.get("entity_type") or record.get("element_type") or ""
    guids = tuple(target.get("guids") or ())
    score = row.get("score") or {}
    out: dict[str, Any] = {
        "task_id": record["task_id"],
        "operation": record.get("operation"),
        "category": record.get("category"),
        "edit_kind": record.get("edit_kind"),
        "ifc_version": record.get("ifc_version"),
        "underspecified": bool(record.get("clarification")),
        "entity_type": entity_type,
        "n_target_guids": len(guids),
        "committed": bool(row.get("committed")),
        "completed": completed_from(row),
        "score": {k: score.get(k) for k in ("geometry", "semantics", "topology", "final")},
        "edited_ifc": edited,
        "status": "ok",
    }
    edited_path = Path(edited)
    if not row.get("committed") or not (edited_path.is_file()
                                        and edited_path.stat().st_size > 0):
        out["status"] = "no_edited_model"
        out["seconds"] = round(time.perf_counter() - started, 2)
        out["rss_mb"], out["peak_rss_mb"] = _rss_mb()
        return out
    try:
        gold, source = _W["gold"].resolve(record)
        out["gold_source"] = source
        if gold is None:
            out["status"] = "gold_unavailable"
            return out
        model_i, sig_i, dups_i = _input(_W["root"] / record["input_ifc"])
        set_type, aliased = schema_type(model_i, entity_type)
        try:
            model_g = ifcopenshell.open(str(gold))
        except Exception:
            if not source.startswith("lookup"):
                raise
            # A looked-up file vanished or changed under a live run.
            gold, source = _W["gold"].resolve(record, rebuild=True)
            out["gold_source"] = source + "_after_lookup_failed"
            if gold is None:
                out["status"] = "gold_unavailable"
                return out
            model_g = ifcopenshell.open(str(gold))
        sig_g, dups_g = ProductHasher(model_g).signatures()
        n_gold_set = len(build_edit_set(model_i, model_g, record["operation"],
                                        set_type, guids).guids)
        del model_g
        model_e = ifcopenshell.open(str(edited_path))
        sig_e, dups_e = ProductHasher(model_e).signatures()
        edit = build_edit_set(model_i, model_e, record["operation"], set_type, guids)
        covered = list(edit.guids)
        del model_e, edit
        out.update(edit_set_type=set_type, edit_set_type_aliased=aliased,
                   n_gold_edit_set=n_gold_set,
                   # Target-class elements the edited model's edit set holds
                   # beyond the gold's: extra creations a create task hides.
                   edit_set_surplus=max(0, len(covered) - n_gold_set),
                   duplicate_guids={"input": dups_i, "gold": dups_g, "edited": dups_e})
        out.update(off_target(sig_i, sig_g, sig_e, covered, guids))
    except Exception as exc:  # noqa: BLE001 - one bad file must not stop a read
        out["status"] = "error"
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        out["seconds"] = round(time.perf_counter() - started, 2)
        out["rss_mb"], out["peak_rss_mb"] = _rss_mb()
    return out


# ------------------------------------------------------------------ summary


def _share(rows: list[dict], key: str) -> dict[str, Any]:
    counts = [int(r[key]) for r in rows]
    n = len(counts)
    if not n:
        return {"n": 0}
    positive = sum(1 for c in counts if c > 0)
    return {
        "n": n,
        "n_with_off_target": positive,
        "share_with_off_target": round(positive / n, 4),
        "mean_count": round(sum(counts) / n, 4),
        "median_count": statistics.median(counts),
        "max_count": max(counts),
        "total_count": sum(counts),
        "count_histogram": {str(k): v for k, v in sorted(Counter(
            min(c, 10) for c in counts).items())},
    }


def _types(rows: list[dict], key: str) -> dict[str, dict[str, int]]:
    tasks: Counter = Counter()
    entities: Counter = Counter()
    for r in rows:
        for cls, n in (r.get(key) or {}).items():
            tasks[cls] += 1
            entities[cls] += n
    return {cls: {"tasks": tasks[cls], "entities": entities[cls]}
            for cls, _ in tasks.most_common()}


def _block(rows: list[dict]) -> dict[str, Any]:
    block: dict[str, Any] = {}
    for key, types_key in (("off_target_count", "off_target_types"),
                           ("off_target_count_net", "off_target_net_types"),
                           ("off_target_count_direct", "off_target_direct_types")):
        block[key] = _share(rows, key)
        block[key]["by_operation"] = {
            op: _share([r for r in rows if r["operation"] == op], key)
            for op in sorted({r["operation"] for r in rows})}
        block[key]["by_category"] = {
            cat: _share([r for r in rows if r["category"] == cat], key)
            for cat in sorted({r["category"] for r in rows})}
        block[key]["types"] = _types(rows, types_key)
    block["kinds"] = dict(sum((Counter(r.get("off_target_kinds") or {}) for r in rows),
                              Counter()))
    block["parts"] = dict(sum((Counter(r.get("off_target_parts") or {}) for r in rows),
                              Counter()))
    return block


def summarize(rows: list[dict], meta: dict) -> dict[str, Any]:
    ok = [r for r in rows if r["status"] == "ok"]
    done = [r for r in ok if r.get("completed")]
    secs = sorted(r["seconds"] for r in ok) or [0.0]
    return {
        **meta,
        "definition": ("off_target(E) = changed(I->E) - changed(I->G) - "
                       "GlobalIds of build_edit_set(I, E, operation, entity_type, "
                       "target_guids); changed = IfcProducts created, deleted, or "
                       "with a different placement / representation / direct-"
                       "attribute hash (OwnerHistory ignored)"),
        "completed_rule": f"geometry, semantics and topology all >= {COMPLETED_FLOOR}",
        "n_rows": len(rows),
        "status": dict(Counter(r["status"] for r in rows)),
        "n_no_edited_model": sum(1 for r in rows if r["status"] == "no_edited_model"),
        "n_edit_set_type_aliased": sum(1 for r in ok if r.get("edit_set_type_aliased")),
        "edit_set_surplus": {
            "n_tasks": sum(1 for r in ok if r.get("edit_set_surplus")),
            "total": sum(r.get("edit_set_surplus") or 0 for r in ok),
            "by_operation": dict(Counter(r["operation"] for r in ok
                                         if r.get("edit_set_surplus")))},
        "n_underspecified": sum(1 for r in ok if r.get("underspecified")),
        "gold_source": dict(Counter(r.get("gold_source") for r in ok)),
        "all_evaluated": _block(ok),
        "completed": _block(done),
        "not_completed": _block([r for r in ok if r.get("completed") is False]),
        "timing": {
            "mean_seconds": round(sum(secs) / len(secs), 2),
            "median_seconds": statistics.median(secs),
            "p95_seconds": secs[int(0.95 * (len(secs) - 1))],
            "max_seconds": secs[-1],
            "peak_rss_mb_max": max((r.get("peak_rss_mb") or 0) for r in rows) if rows else 0,
        },
    }


# ------------------------------------------------------------------ cli


def _load_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _stat_inputs(paths: Iterable[Path]) -> dict[str, list[int]]:
    out = {}
    for p in paths:
        try:
            st = os.stat(p)
            out[str(p)] = [st.st_size, st.st_mtime_ns]
        except OSError:
            out[str(p)] = [-1, -1]
    return out


def _abs(p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else PROJECT_ROOT / path


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Count off-target changes per task.")
    ap.add_argument("--per-task", required=True)
    ap.add_argument("--tasks", required=True)
    ap.add_argument("--edited-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--gold-cache", default=str(DEFAULT_GOLD_CACHE),
                    help="where missing gold models are rebuilt")
    ap.add_argument("--gold-lookup", action="append", default=None,
                    help="directories searched read-only for a gold model first")
    args = ap.parse_args(argv)

    per_task_path, tasks_path = _abs(args.per_task), _abs(args.tasks)
    edited_dir, out_dir = _abs(args.edited_dir), _abs(args.out_dir)
    gold_cache = _abs(args.gold_cache)
    lookup = [_abs(p) for p in (args.gold_lookup or [str(p) for p in DEFAULT_GOLD_LOOKUP])]
    data_root = (PROJECT_ROOT / "data").resolve()
    for label, path in (("--out-dir", out_dir), ("--gold-cache", gold_cache)):
        if data_root in path.resolve().parents or path.resolve() == data_root:
            ap.error(f"{label} must not lie under {data_root}")
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / "offtarget_per_task.jsonl"

    records = {r["task_id"]: r for r in _load_jsonl(tasks_path)}
    read_rows = _load_jsonl(per_task_path)
    done: set[str] = set()
    if rows_path.exists():
        done = {r["task_id"] for r in _load_jsonl(rows_path)}

    payloads = []
    missing_task = 0
    for row in read_rows:
        record = records.get(row["task_id"])
        if record is None:
            missing_task += 1
            continue
        if row["task_id"] in done:
            continue
        stem = Path(record["input_ifc"]).stem
        edited = edited_dir / row["task_id"] / f"{stem}.ifc"
        payloads.append((record, row, str(edited)))
    payloads.sort(key=lambda p: (p[0]["input_ifc"], p[0]["task_id"]))
    if args.limit:
        payloads = payloads[: args.limit]

    watched = [per_task_path, tasks_path] + [Path(p[2]) for p in payloads]
    before = _stat_inputs(watched)
    print(f"{len(payloads)} tasks to evaluate, {len(done)} already written, "
          f"{missing_task} rows without a task record", flush=True)

    started = time.perf_counter()
    log_path = out_dir / "offtarget.log"
    import multiprocessing as mp
    context = mp.get_context("fork")
    with open(rows_path, "a", encoding="utf-8") as sink, \
            open(log_path, "a", encoding="utf-8") as log, \
            context.Pool(max(1, args.workers), initializer=_init_worker,
                         initargs=(str(gold_cache), [str(p) for p in lookup],
                                   str(PROJECT_ROOT)),
                         maxtasksperchild=60) as pool:
        for index, out in enumerate(pool.imap_unordered(evaluate, payloads, 1), 1):
            sink.write(json.dumps(out) + "\n")
            sink.flush()
            line = (f"{index}/{len(payloads)} {out['task_id']} {out['status']} "
                    f"off={out.get('off_target_count')} net={out.get('off_target_count_net')} "
                    f"t={out['seconds']}s rss={out.get('rss_mb')}MB "
                    f"peak={out.get('peak_rss_mb')}MB "
                    f"elapsed={time.perf_counter() - started:.0f}s")
            log.write(line + "\n")
            log.flush()
            if index % 25 == 0 or index == len(payloads):
                print(line, flush=True)

    after = _stat_inputs(watched)
    changed_inputs = sorted(p for p in before if before[p] != after.get(p))
    rows = _load_jsonl(rows_path)
    meta = {
        "per_task": str(per_task_path), "tasks": str(tasks_path),
        "edited_dir": str(edited_dir), "workers": args.workers,
        "wall_seconds_this_invocation": round(time.perf_counter() - started, 1),
        "n_evaluated_this_invocation": len(payloads),
        "inputs_checked": len(before),
        "inputs_modified": changed_inputs,
    }
    summary = summarize(rows, meta)
    (out_dir / "offtarget_summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps({k: summary[k] for k in ("n_rows", "status", "inputs_modified")},
                     indent=1))
    print(json.dumps(summary["all_evaluated"]["off_target_count"] | {"types": None}))
    return 0 if not changed_inputs else 2


if __name__ == "__main__":
    raise SystemExit(main())
