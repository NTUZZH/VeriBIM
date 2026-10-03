"""Which source models the generator is allowed to draw on.

The corpus manifest already records the exclusions the project agreed on:
duplicates, files IfcOpenShell cannot open, files sharing an identifier with
BIM-Edit, and the whole Schependomlaan building, which is reserved.  This module
reads that decision rather than re-deriving it, and adds only what the generator
itself needs: a file small enough to copy per task, and enough elements of the
six families to be worth probing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

from .scene import FAMILIES

# Collections and paths the generator never reads, whatever the manifest says.
FORBIDDEN_PREFIXES = ("data/bimedit", "data/corpus/schependomlaan")
FORBIDDEN_COLLECTIONS = ("schependomlaan",)


@dataclass(frozen=True)
class ModelRef:
    """One source model the generator may use."""

    key: str
    relpath: str
    sha256: str
    collection: str
    schema: str
    bytes: int
    n_products: int
    counts: dict[str, int]

    def path(self, root: Path) -> Path:
        return root / self.relpath


def _family_counts(histogram: dict[str, int]) -> dict[str, int]:
    return {
        "wall": histogram.get("IfcWall", 0) + histogram.get("IfcWallStandardCase", 0),
        "slab": histogram.get("IfcSlab", 0),
        "space": histogram.get("IfcSpace", 0),
        "door": histogram.get("IfcDoor", 0),
        "window": histogram.get("IfcWindow", 0),
        "column": histogram.get("IfcColumn", 0),
    }


def load_candidates(root: Path, max_bytes: int = 80_000_000,
                    min_families: int = 3, min_products: int = 40
                    ) -> list[ModelRef]:
    """Training-eligible models the generator can work on, largest first."""
    manifest = json.loads((root / "data" / "corpus_manifest.json").read_text())
    descriptors = json.loads(
        (root / "data" / "corpus_descriptors.json").read_text())["corpus"]
    out: list[ModelRef] = []
    for record in manifest["files"]:
        relpath = record["relpath"]
        if not record.get("training_eligible"):
            continue
        if record.get("e3_building") or record.get("e3_reserved"):
            continue
        if record.get("source_collection") in FORBIDDEN_COLLECTIONS:
            continue
        if any(relpath.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            continue
        if record["bytes"] > max_bytes:
            continue
        descriptor = descriptors.get(relpath)
        if descriptor is None:
            continue
        counts = _family_counts(descriptor["element_type_histogram"])
        if sum(1 for v in counts.values() if v > 0) < min_families:
            continue
        if record["n_products"] < min_products:
            continue
        out.append(ModelRef(
            key="", relpath=relpath, sha256=record["sha256"],
            collection=record["source_collection"], schema=record["ifc_schema"],
            bytes=record["bytes"], n_products=record["n_products"],
            counts=counts))
    out.sort(key=lambda m: (-sum(1 for v in m.counts.values() if v > 0),
                            -m.n_products, m.relpath))
    return [ModelRef(key=f"B{i + 1:02d}", relpath=m.relpath, sha256=m.sha256,
                     collection=m.collection, schema=m.schema, bytes=m.bytes,
                     n_products=m.n_products, counts=m.counts)
            for i, m in enumerate(out)]


def select(models: Sequence[ModelRef], limit: int) -> list[ModelRef]:
    """A spread of models across collections, up to ``limit`` of them."""
    by_collection: dict[str, list[ModelRef]] = {}
    for model in models:
        by_collection.setdefault(model.collection, []).append(model)
    order = sorted(by_collection, key=lambda c: -len(by_collection[c]))
    picked: list[ModelRef] = []
    index = 0
    while len(picked) < limit:
        added = False
        for collection in order:
            bucket = by_collection[collection]
            if index < len(bucket) and len(picked) < limit:
                picked.append(bucket[index])
                added = True
        if not added:
            break
        index += 1
    return picked
