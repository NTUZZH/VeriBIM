"""Turn the corpus condition scan into the table the paper carries."""

from __future__ import annotations

import collections
import json
import re
from pathlib import Path

ROOT = Path(".")
import sys
SCAN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "runs_local/wave_v2/corpus_conditions.json"
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "runs_local/wave_v2/corpus_conditions.md"

#: The exporter a header names, shortened to the tool a reader would name.
FAMILIES = (
    (r"Exporter \d|Autodesk|Revit", "Autodesk Revit"),
    (r"ARCHICAD|GRAPHISOFT", "Graphisoft Archicad"),
    (r"Tekla", "Tekla Structures"),
    (r"SDS/2", "SDS/2"),
    (r"SketchUp", "SketchUp"),
    (r"MicroStation|Bentley", "Bentley MicroStation"),
    (r"Allplan", "Allplan"),
    (r"TopSolid", "TopSolid"),
    (r"Solibri", "Solibri"),
)


def exporter_family(row: dict) -> str:
    text = f"{row.get('exporter', '')} {row.get('preprocessor', '')}"
    for pattern, name in FAMILIES:
        if re.search(pattern, text, re.I):
            return name
    return "other or unnamed"


def share_table(rows, key, order=None):
    counts = collections.Counter(key(r) for r in rows)
    items = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if order:
        items = sorted(items, key=lambda kv: order.index(kv[0])
                       if kv[0] in order else 99)
    return items


def main() -> None:
    rows = json.load(open(SCAN))
    n = len(rows)
    lines: list[str] = []
    add = lines.append

    add("# The conditions the source corpus carries (VeriBIM-Gen 0.7.2)")
    add("")
    add(f"Every one of the {n} source models the v2 wave may draw on, read once "
        "for the six conditions layer 6 of the requirement taxonomy names. The "
        "ten buildings held out for VeriBIM-Bench are not in this pool and were "
        "not opened; the eleven the canonical set keeps for validation are, "
        "because the wave draws its validation split from them. Measured by "
        "`runs_local/gen_v07/scan_conditions.py`; the per-model rows are in "
        "`corpus_conditions.json`.")
    add("")
    add("## Schema version")
    add("")
    add("| schema | models | share |")
    add("| --- | ---: | ---: |")
    for name, count in share_table(rows, lambda r: r["schema_identifier"]):
        add(f"| {name} | {count} | {count / n:.0%} |")
    add("")
    add("The corpus is mostly IFC2X3, so a family that writes entities is "
        "exercised on that schema by default rather than by design. Attribute "
        "names and enumerations are read from the file's own schema "
        "declaration, so an edit the schema does not admit is refused: IFC2X3 "
        "gives a door no `PredefinedType`, and no retype task is written for "
        "one.")
    add("")

    add("## Length unit")
    add("")
    add("| unit | metres per unit | models | share |")
    add("| --- | ---: | ---: | ---: |")
    scales = {r["unit_word"]: r["unit_scale"] for r in rows}
    for name, count in share_table(rows, lambda r: r["unit_word"],
                                   order=["mm", "cm", "m", "ft", "in"]):
        add(f"| {name} | {scales[name]:g} | {count} | {count / n:.0%} |")
    add("")
    imperial = sum(1 for r in rows if r["unit_family"] == "conversion")
    add(f"Nine models, {imperial / n:.0%} of the pool, are written in feet or "
        "inches through an `IfcConversionBasedUnit`. Every length a gold script "
        "passes is in metres and is converted to the file's own unit when it is "
        "written, so all five units are already generated against. What the "
        "wording layer varies is the unit the instruction states, and it offers "
        "millimetres and centimetres only where the file uses them: a metre "
        "length converted to feet is not a number a work order quotes.")
    add("")

    add("## Placement")
    add("")
    turned = [r for r in rows if r["has_rotated_storey"]]
    offset = [r for r in rows if r["has_site_offset"]]
    site_turn = [r for r in rows if r["has_site_rotation"]]
    mapped = [r for r in rows if r["has_map_conversion"]]
    add("| condition | models | share |")
    add("| --- | ---: | ---: |")
    add(f"| at least one storey turned against the world axes | {len(turned)} | "
        f"{len(turned) / n:.0%} |")
    add(f"| site placement more than 1 m from the world origin | {len(offset)} | "
        f"{len(offset) / n:.0%} |")
    add(f"| site placement turned against the world axes | {len(site_turn)} | "
        f"{len(site_turn) / n:.0%} |")
    add(f"| an `IfcMapConversion` in the file | {len(mapped)} | "
        f"{len(mapped) / n:.0%} |")
    add("")
    angles = sorted({round(s["degrees"], 1) for r in turned
                     for s in r["rotated_storeys"]})
    add("The turns are plan grids and not noise: " +
        ", ".join(f"{a:g} degrees" for a in angles) + ". Two models place their "
        "site on a survey grid a quarter of a million metres from the origin "
        "(219,917 E, 907,106 N), which is what a world coordinate reads on "
        "there.")
    add("")
    add("| model | turned storeys | turn | site offset, m |")
    add("| --- | ---: | ---: | --- |")
    for r in sorted(turned + [x for x in offset if not x["has_rotated_storey"]],
                    key=lambda r: r["key"]):
        turns = sorted({round(s["degrees"], 1) for s in r["rotated_storeys"]})
        site = r["site_offset_m"]
        far = site and max(abs(v) for v in site) >= 1.0
        site_text = (f"({site[0]:.0f}, {site[1]:.0f}, {site[2]:.0f})" if far
                     else "on the origin")
        add(f"| {r['key']} | {len(r['rotated_storeys'])} of {r['n_storeys']} | "
            f"{', '.join(f'{t:g}' for t in turns) or '0'} | {site_text} |")
    add("")

    add("## Representation")
    add("")
    totals: collections.Counter = collections.Counter()
    for r in rows:
        totals.update(r["representation_total"])
    grand = sum(totals.values())
    add("Every wall, slab, space, door, window and column in the pool, by the "
        "kind of body it carries.")
    add("")
    add("| body | elements | share |")
    add("| --- | ---: | ---: |")
    for kind, count in totals.most_common():
        add(f"| {kind.replace('_', ' ')} | {count:,} | {count / grand:.1%} |")
    add("")
    add("A faceted body and geometry borrowed from a type object together carry "
        f"{(totals['brep'] + totals['tessellated'] + totals['mapped_item']) / grand:.0%} "
        "of the elements, so an edit that only worked on a swept profile would "
        "reach a minority of the corpus. A translate, a rotate, a rename, a "
        "retype, a property value, a material, a type object, a move to another "
        "storey, a delete and a copy are written through the placement, the "
        "attributes or the relationships and work on any body. A resize and a "
        "mirror rewrite the profile itself, so they are undefinable on a "
        "faceted body, on a tessellated one, on a boolean result and on "
        "geometry a type object owns, and are refused there and counted.")
    add("")

    add("## Names")
    add("")
    foreign = [r for r in rows if r["names"]["non_english_share"] > 0.02]
    add(f"{len(foreign)} of the {n} models name their elements in a language "
        "other than English, judged by the rule the generator itself uses: a "
        "character outside the ASCII range, or one of a fixed list of building "
        "words. A task whose instruction quotes such a name is tagged, so the "
        "benchmark can report on it.")
    add("")
    add("| model | share of names not in English | example |")
    add("| --- | ---: | --- |")
    for r in sorted(foreign, key=lambda r: -r["names"]["non_english_share"]):
        example = (r["names"]["examples"] or [""])[0][:44]
        add(f"| {r['key']} | {r['names']['non_english_share']:.0%} | {example} |")
    add("")

    add("## Exporter")
    add("")
    add("| exporter | models |")
    add("| --- | ---: |")
    for name, count in share_table(rows, exporter_family):
        add(f"| {name} | {count} |")
    add("")
    add("The header of an IFC file names the tool that wrote it, and the "
        "conventions above follow from it: the Revit and Archicad files carry "
        "swept profiles and mapped items, the structural-steel exporters carry "
        "faceted bodies, and the imperial units come from the North American "
        "files.")
    add("")

    add("## Size")
    add("")
    byte_total = sum(r["bytes"] for r in rows)
    products = sum(r["n_products"] for r in rows)
    add(f"The pool holds {n} models, {byte_total / 1e9:.1f} GB and "
        f"{products:,} products in all, from {min(r['bytes'] for r in rows) / 1e6:.1f} MB "
        f"to {max(r['bytes'] for r in rows) / 1e6:.0f} MB.")
    add("")

    OUT.write_text("\n".join(lines) + "\n")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
