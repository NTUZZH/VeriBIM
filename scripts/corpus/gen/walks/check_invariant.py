"""Two checks over a trajectory file or an assembled one.

The first asks whether every identifier a round writes was given in the
instruction or printed earlier. The second asks whether an identifier that came
out of a listing of several candidates can be tied to what the instruction
names, since a round may hold the first rule and still leave the reader no way
to tell which of the listed candidates was meant. Exits non-zero when either
finds anything, so it can gate a pipeline stage.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from stage_a.observed import listing_choice_justified, observed_identifiers_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--report", default="")
    parser.add_argument("--skip-listing", action="store_true",
                        help="run the identifier walk alone")
    args = parser.parse_args()

    summary = {}
    total_bad = 0
    for name in args.files:
        rows = 0
        bad = 0
        unjustified = 0
        by_kind: Counter = Counter()
        by_edit_kind: Counter = Counter()
        examples: list[str] = []
        listing_examples: list[str] = []
        with Path(name).open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                record = json.loads(line)
                rows += 1
                messages = record.get("messages") or ()
                instruction = (record.get("instruction")
                               or record.get("prompt") or "")
                found = observed_identifiers_ok(messages, instruction)
                if found:
                    bad += 1
                    by_kind[record.get("anchor_kind") or "none"] += 1
                    if len(examples) < 5:
                        examples.append(f"{record.get('task_id')}: {found[:2]}")
                if args.skip_listing:
                    continue
                listed = listing_choice_justified(messages, instruction)
                if listed:
                    unjustified += 1
                    by_edit_kind[record.get("edit_kind") or "none"] += 1
                    if len(listing_examples) < 5:
                        listing_examples.append(
                            f"{record.get('task_id')}: {listed[:2]}")
        summary[name] = {
            "rows": rows,
            "identifier_never_observed": bad,
            "identifier_by_anchor_kind": dict(sorted(by_kind.items())),
            "identifier_examples": examples,
            "listing_choice_unjustified": unjustified,
            "listing_by_edit_kind": dict(sorted(by_edit_kind.items())),
            "listing_examples": listing_examples,
        }
        total_bad += bad + unjustified
    print(json.dumps(summary, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return 1 if total_bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
