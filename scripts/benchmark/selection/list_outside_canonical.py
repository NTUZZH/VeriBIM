"""The tasks of the imitation pool that the canonical set does not hold.

The canonical set subsamples the edit kinds an unedited model half-answers, so
about seven thousand accepted tasks sit in the imitation pool and in no audit.
This names them so the physical audit can read them and the pool can be cleaned
the same way the canonical set was.
"""

from __future__ import annotations

import json
from pathlib import Path

CANON = Path("runs_local/wave_v2/canonical_v2/tasks.jsonl")
POOL = Path("runs_local/wave_v2/wave_all_accepted.jsonl")
OUT = Path("runs_local/wave_v2/wave_all_not_in_canonical.jsonl")


def main() -> int:
    held = set()
    for line in CANON.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            held.add(record.get("wave_task_id") or record["task_id"])
    n = 0
    with OUT.open("w", encoding="utf-8") as handle:
        for line in POOL.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line)["task_id"] not in held:
                handle.write(line + "\n")
                n += 1
    print(f"{n} tasks outside the canonical set -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
