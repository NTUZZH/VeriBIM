"""Paired comparison of two val-100 runs: mean delta with a bootstrap CI.

Both runs must cover the same task ids (the same fixed subset, the same
server, the same protocol); the script refuses otherwise. Tasks are paired by
id, the statistic is the mean per-task difference, and the interval is a
percentile bootstrap over tasks (seeded, so a re-run reproduces it).

    python -m stage_c.paired_val --a per_task_c97.jsonl --b per_task_dpo_v1.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def load(path: Path) -> dict[str, dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["task_id"]: row for row in rows}


def final_of(row: dict) -> float:
    if row.get("final") is not None:
        return float(row["final"])
    score = row.get("score") or {}
    return float(score.get("final", 0.0) or 0.0)


def rate(rows: list[dict], key) -> float:
    return sum(1.0 for r in rows if key(r)) / max(1, len(rows))


def bootstrap(deltas: list[float], n: int, seed: int) -> tuple[float, float]:
    rng = random.Random(seed)
    k = len(deltas)
    means = []
    for _ in range(n):
        means.append(sum(deltas[rng.randrange(k)] for _ in range(k)) / k)
    means.sort()
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="candidate per_task jsonl")
    ap.add_argument("--b", required=True, help="reference per_task jsonl")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20260902)
    args = ap.parse_args()
    a, b = load(Path(args.a)), load(Path(args.b))
    if set(a) != set(b):
        raise SystemExit(f"task sets differ: {len(set(a) ^ set(b))} ids not shared")
    ids = sorted(a)
    deltas = [final_of(a[t]) - final_of(b[t]) for t in ids]
    mean_a = sum(final_of(a[t]) for t in ids) / len(ids)
    mean_b = sum(final_of(b[t]) for t in ids) / len(ids)
    lo, hi = bootstrap(deltas, args.n, args.seed)
    wins = sum(1 for d in deltas if d > 1e-9)
    losses = sum(1 for d in deltas if d < -1e-9)
    out = {
        "n": len(ids), "mean_a": round(mean_a, 4), "mean_b": round(mean_b, 4),
        "delta": round(mean_a - mean_b, 4), "ci95": [round(lo, 4), round(hi, 4)],
        "wins": wins, "losses": losses, "ties": len(ids) - wins - losses,
        "by_operation": {},
    }
    for op in sorted({a[t]["operation"] for t in ids}):
        sub = [t for t in ids if a[t]["operation"] == op]
        d = [final_of(a[t]) - final_of(b[t]) for t in sub]
        out["by_operation"][op] = {
            "n": len(sub),
            "a": round(sum(final_of(a[t]) for t in sub) / len(sub), 4),
            "b": round(sum(final_of(b[t]) for t in sub) / len(sub), 4),
            "delta": round(sum(d) / len(d), 4)}
    rows_a = [a[t] for t in ids]
    rows_b = [b[t] for t in ids]
    out["code_run_a"] = round(sum(r["running_calls"] for r in rows_a) / max(1, sum(r["tool_calls"] for r in rows_a)), 4)
    out["code_run_b"] = round(sum(r["running_calls"] for r in rows_b) / max(1, sum(r["tool_calls"] for r in rows_b)), 4)
    out["commit_a"] = round(rate(rows_a, lambda r: r.get("committed")), 4)
    out["commit_b"] = round(rate(rows_b, lambda r: r.get("committed")), 4)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
