"""The number walk over a trajectory file: every literal a round writes was read.

Same shape as ``check_invariant.py``, on quantities instead of identifiers. A
round may write a number that the instruction carried or that an earlier tool
output printed, allowing for a sign change, a millimetre-to-metre conversion and
the rounding every printing round applies. Anything else is a value the
trajectory produced off the record.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from stage_a.observed import numbers_observed_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--only-ids", default="",
                        help="a file of task ids, one per line, to restrict to")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    wanted = set()
    if args.only_ids:
        wanted = {line.strip() for line in
                  Path(args.only_ids).read_text(encoding="utf-8").splitlines()
                  if line.strip()}

    summary = {}
    for name in args.files:
        rows = 0
        bad = 0
        leaked = 0
        by_kind: Counter = Counter()
        by_purpose: Counter = Counter()
        examples: list[dict] = []
        with Path(name).open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if wanted and record["task_id"] not in wanted:
                    continue
                rows += 1
                found = numbers_observed_ok(
                    record.get("messages") or (),
                    record.get("instruction") or record.get("prompt") or "")
                if not found:
                    continue
                bad += 1
                leaked += sum(len(f["unobserved"]) for f in found)
                by_kind[record.get("edit_kind", "?")] += 1
                # Which round wrote it. The trajectory records one purpose per
                # planned turn, and the turns that carry code come first, so the
                # round index is the index into that list.
                purposes = list(record.get("purposes") or ())
                for entry in found:
                    index = entry["round"]
                    purpose = (purposes[index] if index < len(purposes)
                               else "unknown")
                    step = ("edit" if purpose == "edit" else
                            "commit" if purpose == "commit" else
                            "measure" if ("measure" in purpose
                                          or "sits in its wall" in purpose
                                          or "stands on" in purpose
                                          or "stands against" in purpose
                                          or "measured from" in purpose) else
                            "units" if "unit" in purpose else "lookup")
                    by_purpose[step] += len(entry["unobserved"])
                if len(examples) < 12:
                    examples.append({"task_id": record["task_id"],
                                     "edit_kind": record.get("edit_kind"),
                                     "rounds": found[:2]})
        summary[name] = {"rows": rows, "trajectories_with_an_unread_number": bad,
                         "unread_numbers": leaked,
                         "unread_numbers_by_round": dict(by_purpose),
                         "by_edit_kind": dict(by_kind), "examples": examples}
    print(json.dumps({k: {a: b for a, b in v.items() if a != "examples"}
                      for k, v in summary.items()}, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    # Exit status: a literal in an edit or unit round
    # that nothing had shown is a defect; a lookup round's own tolerances (a tenth
    # of a quoted distance, and the like) are derived from the instruction and
    # are accepted, so they do not fail the audit.
    strict = ("edit", "units")
    return 0 if all(sum(v["unread_numbers_by_round"].get(k, 0) for k in strict) == 0
                    for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
