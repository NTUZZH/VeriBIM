"""The source models one generation run is allowed to draw on, and their buildings.

The corpus manifest decides which files may be used at all.  This module adds
the two things a generation run needs on top of that decision: whether a file
carries enough of the six element families to host any task, and which building
it belongs to, so that a split can be made by building rather than by file.

Run it to write the pool file a generation run pins itself to::

    python -m modifc_gen.pool --root . --out data/veribim_tasks_v1/pool.json
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Optional, Sequence

from . import buildings, corpus

POOL_VERSION = "pool-v1"

# The generator copies a source model twice per task, so a very large file costs
# minutes of wall clock per task.  The cap keeps the tail out; the models it
# excludes are named in the pool file rather than dropped silently.
DEFAULT_MAX_BYTES = 200_000_000
DEFAULT_MIN_FAMILIES = 1
DEFAULT_MIN_PRODUCTS = 40


def size_tier(byte_count: int) -> str:
    if byte_count < 5_000_000:
        return "small"
    if byte_count < 25_000_000:
        return "medium"
    if byte_count < 80_000_000:
        return "large"
    return "very_large"


def build_pool(root: Path, max_bytes: int = DEFAULT_MAX_BYTES,
               min_families: int = DEFAULT_MIN_FAMILIES,
               min_products: int = DEFAULT_MIN_PRODUCTS,
               exclude_buildings: Sequence[str] = ()) -> dict[str, Any]:
    """The models a run may use, with a building id on each."""
    root = Path(root)
    models = corpus.load_candidates(root, max_bytes=max_bytes,
                                    min_families=min_families,
                                    min_products=min_products)
    manifest = json.loads((root / "data" / "corpus_manifest.json").read_text())
    by_relpath = {record["relpath"]: record for record in manifest["files"]}
    names = buildings.load_names(root)

    records = [by_relpath[model.relpath] for model in models]
    grouping = buildings.group(root, records)

    excluded = set(exclude_buildings)
    entries: list[dict[str, Any]] = []
    for model in models:
        group = grouping[model.relpath]
        name_record = names.get(model.relpath, {})
        entries.append({
            "key": model.key,
            "relpath": model.relpath,
            "sha256": model.sha256,
            "building_id": group["building_id"],
            "building_label": group["label"],
            "collection": model.collection,
            "schema": model.schema,
            "bytes": model.bytes,
            "size_tier": size_tier(model.bytes),
            "n_products": model.n_products,
            "family_counts": model.counts,
            "n_families": sum(1 for v in model.counts.values() if v > 0),
            "exporter": name_record.get("application"),
            "project_name": name_record.get("project_name"),
            "in_run": group["building_id"] not in excluded,
            "held_out": group["building_id"] in excluded,
        })

    by_building: dict[str, list[str]] = defaultdict(list)
    for entry in entries:
        by_building[entry["building_id"]].append(entry["key"])
    return {
        "pool_version": POOL_VERSION,
        "thresholds": {"max_bytes": max_bytes, "min_families": min_families,
                       "min_products": min_products},
        "excluded_buildings": sorted(excluded),
        "n_models": len(entries),
        "n_buildings": len(by_building),
        "n_models_in_run": sum(1 for e in entries if e["in_run"]),
        "n_buildings_in_run": len({e["building_id"] for e in entries
                                   if e["in_run"]}),
        "buildings": {bid: sorted(keys) for bid, keys in sorted(by_building.items())},
        "models": entries,
    }


def load_pool(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def model_refs(pool: dict[str, Any], only_in_run: bool = True
               ) -> list[corpus.ModelRef]:
    """The pool's entries as the refs the generator works with."""
    out: list[corpus.ModelRef] = []
    for entry in pool["models"]:
        if only_in_run and not entry["in_run"]:
            continue
        out.append(corpus.ModelRef(
            key=entry["key"], relpath=entry["relpath"], sha256=entry["sha256"],
            collection=entry["collection"], schema=entry["schema"],
            bytes=entry["bytes"], n_products=entry["n_products"],
            counts=entry["family_counts"]))
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--out", default="data/veribim_tasks_v1/pool.json")
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--min-families", type=int, default=DEFAULT_MIN_FAMILIES)
    parser.add_argument("--min-products", type=int, default=DEFAULT_MIN_PRODUCTS)
    parser.add_argument("--exclude-buildings", default="",
                        help="comma-separated building ids held out entirely")
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    excluded = [b.strip() for b in args.exclude_buildings.split(",") if b.strip()]
    pool = build_pool(root, args.max_bytes, args.min_families,
                      args.min_products, excluded)
    out = Path(args.out)
    if not out.is_absolute():
        out = root / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pool, indent=1, ensure_ascii=False))
    print(f"{pool['n_models']} models over {pool['n_buildings']} buildings "
          f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
