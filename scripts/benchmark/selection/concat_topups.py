"""Put the top-up rounds into one task file with identifiers that stay unique.

Each round runs in its own directory, so two rounds can number two different
tasks the same way.  Every round therefore carries a one-letter suffix on its
identifier and on the two fields that name its gold model by that identifier,
which is what ``build_canonical`` already does for a second wave.  The gold
script is never touched, so no gold model and no checksum moves.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", action="append", default=[],
                        help="suffix=path, one per round, in order")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)

    rows = []
    seen = set()
    counts = {}
    for spec in args.round:
        suffix, _, path = spec.partition("=")
        n = 0
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            record = json.loads(line)
            old = record["task_id"]
            new = f"{old}-{suffix}"
            record["task_id"] = new
            record["topup_round"] = suffix
            for field in ("gold_model", "ground_truth_ifc"):
                value = record.get(field)
                if value:
                    if not value.endswith(f"/{old}.ifc"):
                        raise AssertionError(
                            f"{field} of {old} is not named by its id: {value}")
                    record[field] = value[: -len(f"{old}.ifc")] + f"{new}.ifc"
            if new in seen:
                raise AssertionError(f"duplicate task id after the suffix: {new}")
            seen.add(new)
            rows.append(record)
            n += 1
        counts[suffix] = n

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(json.dumps({"rounds": counts, "total": len(rows), "out": str(out)},
                     indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
