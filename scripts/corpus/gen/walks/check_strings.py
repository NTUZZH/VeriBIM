"""The name walk over a trajectory file: every name a round matches on was given.

The identifier walk asks where a GlobalId came from and the number walk asks
where a quantity came from. This asks the same of a name: a lookup that finds an
element by comparing its ``Name`` with a string has to have been given that
string, in the instruction or in an earlier tool output. A name the generator
drew when it built the task, and never wrote into the sentence, is one the model
cannot produce.

Strings that are not names of anything in the model are left out: a message a
round prints, an attribute, an IFC class token, a dictionary key, an identifier,
and anything inside a helper the round defines.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from stage_a.observed import names_observed_ok


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("files", nargs="+")
    parser.add_argument("--only-ids", default="")
    parser.add_argument("--report", default="")
    args = parser.parse_args()

    wanted = set()
    if args.only_ids:
        wanted = set(json.loads(Path(args.only_ids).read_text(encoding="utf-8"))) \
            if args.only_ids.endswith(".json") else {
                line.strip() for line in
                Path(args.only_ids).read_text(encoding="utf-8").splitlines()
                if line.strip()}

    summary = {}
    for name in args.files:
        rows = bad = leaked = 0
        by_kind: Counter = Counter()
        examples: list[dict] = []
        with Path(name).open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if wanted and record["task_id"] not in wanted:
                    continue
                rows += 1
                found = names_observed_ok(
                    record.get("messages") or (),
                    record.get("instruction") or record.get("prompt") or "")
                if not found:
                    continue
                bad += 1
                leaked += sum(len(f["unnamed"]) for f in found)
                by_kind[record.get("edit_kind", "?")] += 1
                if len(examples) < 12:
                    examples.append({"task_id": record["task_id"],
                                     "edit_kind": record.get("edit_kind"),
                                     "rounds": found[:2]})
        summary[name] = {"rows": rows, "trajectories_with_an_unknown_name": bad,
                         "unknown_names": leaked, "by_edit_kind": dict(by_kind),
                         "examples": examples}
    print(json.dumps({k: {a: b for a, b in v.items() if a != "examples"}
                      for k, v in summary.items()}, indent=2))
    if args.report:
        Path(args.report).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0 if all(v["trajectories_with_an_unknown_name"] == 0
                    for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
