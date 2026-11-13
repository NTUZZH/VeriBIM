"""Which taxonomy layer each task of a wave belongs to, and what the wave holds.

The wave is weighted by layer: the original grid 40 %, the 0.5.0 references,
specifications and constraints 25 %, the 0.6.0 operations and scopes 25 %, and
the 0.7.0 wording 10 %, of which the instructions that leave a value out are
about half.  A task can carry tags of more than one layer, so the four shares
are read as a partition under one precedence: the newest layer a task DRAWS
from names it.  Layer 6 is measured rather than drawn and every task carries
some model condition, so it names no task here and is reported on its own.

Run it on a task file to get the partition, the per-family counts and the
counts of the families a wave has to reach a floor on.
"""

from __future__ import annotations

import argparse
import collections
import json

#: Layer 7 as a family that takes a slot in the partition.  Only two forms do.
#: An instruction that leaves a value out changes what the task asks for: its
#: gold makes no edit and its answer is a question.  A create whose coordinates
#: are quoted in the world frame on a storey turned against the world axes
#: changes what the reader has to work out before editing.  Both are drawn.
V07 = ("wording.underspecified",)

#: The second slot-taking form, which is a pair of tags rather than one.
V07_PAIR = ("spec.world_frame", "model.placement.rotated_storey")

#: The wording variants that are a render-time substitution on a sentence the
#: gold script does not see.  They sit on top of whatever family a task belongs
#: to and take no slot, so they are counted as an overlay and not in the
#: partition (2026-09-10).  ``wording.ifc_class_name`` is a 0.5.0
#: family that says how a relationship clause is phrased and is counted there.
OVERLAY = ("wording.synonym", "wording.request_form", "wording.class_token",
           "wording.unit_spelling")

#: Layer 1 and layer 5 as 0.6.0 added them, and the two references it added.
V06 = ("op.update.rotate", "op.update.mirror", "op.update.pset",
       "op.update.material", "op.update.type_object", "op.update.restorey",
       "op.update.rehost", "op.copy", "op.array", "op.replace",
       "scope.batch", "scope.conditional", "ref.set",
       "ref.ordinal", "ref.negation")

#: The families a wave has to reach a floor on, with the floor the wave plan sets.
FLOORS = {"op.update.mirror": 150, "op.update.rotate": 300,
          "op.update.rehost": 300,
          "spec.element_relative.fits_gap": 100,
          "spec.element_relative.on_top_of": 100,
          "spec.element_relative.against_room_wall": 100,
          "spec.element_relative.touching_slab_above": 100,
          "spec.element_relative.centred_on_wall": 100,
          "spec.element_relative.aligned_with_filling": 100}


def is_v05(tag: str) -> bool:
    """A 0.5.0 family: a reference, a specification or a constraint it added."""
    if tag in V06:
        return False
    return (tag.startswith("ref.relative.")
            or tag in ("ref.topological.separates", "ref.viewpoint.through_door")
            or tag.startswith("spec.")
            or tag.startswith("constraint.")
            or tag == "wording.ifc_class_name")


def is_v07(tags: set) -> bool:
    return bool(tags & set(V07)) or set(V07_PAIR) <= tags


def layer_of(tags: set) -> str:
    if is_v07(tags):
        return "v07"
    if tags & set(V06):
        return "v06"
    if any(is_v05(t) for t in tags):
        return "v05"
    return "grid"


def read(path):
    for line in open(path, encoding="utf-8"):
        if line.strip():
            yield json.loads(line)


def measure(path) -> dict:
    layers = collections.Counter()
    content = collections.Counter()
    tags = collections.Counter()
    kinds = collections.Counter()
    cells = collections.Counter()
    splits = collections.Counter()
    buildings = collections.Counter()
    overlay = collections.Counter()
    n = 0
    for record in read(path):
        n += 1
        families = set(record.get("families") or ())
        for tag in families:
            tags[tag] += 1
        layers[layer_of(families)] += 1
        content[layer_of(families - set(V07) - set(V07_PAIR))] += 1
        if families & set(OVERLAY):
            overlay["any"] += 1
        for tag in set(OVERLAY) & families:
            overlay[tag] += 1
        kinds[record.get("edit_kind", "?")] += 1
        splits[record.get("split", "?")] += 1
        buildings[record.get("building_id", "?")] += 1
        if record.get("tier") == "single":
            cells[f"{record.get('category')}/{record.get('operation')}"] += 1
        else:
            cells["compositional"] += 1
    return {
        "tasks": path, "n": n,
        "layer_partition": {k: layers[k] for k in ("grid", "v05", "v06", "v07")},
        "layer_share": {k: round(layers[k] / max(1, n), 4)
                        for k in ("grid", "v05", "v06", "v07")},
        "content_partition": {k: content[k] for k in ("grid", "v05", "v06")},
        "content_share": {k: round(content[k] / max(1, n), 4)
                          for k in ("grid", "v05", "v06")},
        "wording_overlay": dict(overlay),
        "wording_overlay_share": {k: round(v / max(1, n), 4)
                                  for k, v in sorted(overlay.items())},
        "families": dict(sorted(tags.items(), key=lambda kv: -kv[1])),
        "floors": {tag: {"count": tags.get(tag, 0), "floor": floor,
                         "reached": tags.get(tag, 0) >= floor}
                   for tag, floor in sorted(FLOORS.items())},
        "edit_kinds": dict(sorted(kinds.items(), key=lambda kv: -kv[1])),
        "cells": dict(sorted(cells.items())),
        "splits": dict(sorted(splits.items())),
        "n_buildings": len(buildings),
        "buildings": dict(sorted(buildings.items())),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", required=True)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    report = measure(args.tasks)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
    print(f"{report['n']} tasks in {report['tasks']}")
    print("layer partition (precedence v07 > v06 > v05 > grid):")
    for name in ("grid", "v05", "v06", "v07"):
        print(f"  {name:5s} {report['layer_partition'][name]:6d} "
              f"{100 * report['layer_share'][name]:5.1f} %")
    print(f"wording overlay, at least one variant: {report['wording_overlay'].get('any', 0)}"
          f" ({100 * report['wording_overlay_share'].get('any', 0):.1f} %)")
    for tag in OVERLAY:
        print(f"  {tag:28s} {report['wording_overlay'].get(tag, 0):6d} "
              f"{100 * report['wording_overlay_share'].get(tag, 0):5.1f} %")
    print("content only (every layer 7 form ignored):")
    for name in ("grid", "v05", "v06"):
        print(f"  {name:5s} {report['content_partition'][name]:6d} "
              f"{100 * report['content_share'][name]:5.1f} %")
    print("floors:")
    for tag, row in report["floors"].items():
        print(f"  {tag:45s} {row['count']:6d} / {row['floor']:5d} "
              f"{'ok' if row['reached'] else 'SHORT'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
