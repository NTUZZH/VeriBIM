"""Summarise the parser baseline's per-task scores.

Reads results/per_task_parser.jsonl (this folder), the subset lists
runs_local/bench_v4/subset_108_hosted.v4c.json and subset_324.v4c.json, and,
for the side-by-side column, the trained model's per-task file of the same
benchmark read (runs_local/bench_v4/results/full_all/per_task_grpo_v10b_c10.jsonl,
completion recomputed with the same rule).  Writes results/summary.json.
"""

from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def completed(row: dict) -> bool:
    sc = row.get("score") or {}
    axes = [sc.get(k) for k in ("geometry", "semantics", "topology")]
    return all(a is not None and a >= 0.9 for a in axes)


def cell(rows: list[dict], key=completed) -> dict:
    n = len(rows)
    k = sum(1 for r in rows if key(r))
    return {"n": n, "completed": k, "rate": round(k / n, 4) if n else None}


def main(path: str = "results/per_task_parser.jsonl",
         out: str = "results/summary.json") -> int:
    rows = [json.loads(l) for l in (HERE / path).open(encoding="utf-8")]
    by_id = {r["task_id"]: r for r in rows}
    s108 = json.loads((ROOT / "runs_local/bench_v4/subset_108_hosted.v4c.json")
                      .read_text())
    s324 = json.loads((ROOT / "runs_local/bench_v4/subset_324.v4c.json")
                      .read_text())
    model_file = ROOT / ("runs_local/bench_v4/results/full_all/"
                         "per_task_grpo_v10b_c10.jsonl")
    model = {}
    if model_file.exists():
        for line in model_file.open(encoding="utf-8"):
            r = json.loads(line)
            model[r["task_id"]] = completed(r)

    def group(field):
        out = {}
        groups = collections.defaultdict(list)
        for r in rows:
            groups[str(r.get(field))].append(r)
        for name in sorted(groups):
            c = cell(groups[name])
            if model:
                ids = [r["task_id"] for r in groups[name] if r["task_id"] in model]
                c["veribim_9b_rate_same_tasks"] = round(
                    sum(model[i] for i in ids) / len(ids), 4) if ids else None
            out[name] = c
        return out

    def subset(ids):
        sub = [by_id[i] for i in ids if i in by_id]
        c = cell(sub)
        c["missing"] = len([i for i in ids if i not in by_id])
        return c

    rest = [r for r in rows if r["task_id"] not in set(s108)]
    summary = {
        "source": path,
        "completion_rule": "geometry, semantics and topology all >= 0.90 "
                           "(family reading)",
        "overall": cell(rows),
        "subset_108": subset(s108),
        "subset_324": subset(s324),
        "outside_108_development_subset": cell(rest),
        "by_operation": group("operation"),
        "by_category": group("category"),
        "by_ifc_version": group("ifc_version"),
        "by_tier": group("tier"),
        "by_specification": {
            "fully_specified": cell([r for r in rows if not r["underspecified"]]),
            "under_specified": cell([r for r in rows if r["underspecified"]]),
        },
        "by_parsed_operation": {},
        "by_target_reference_kind": {},
        "parser": {
            "recognised": sum(1 for r in rows if r.get("recognised")),
            "asked_a_question": sum(1 for r in rows if r.get("asked")),
            "asked_on_underspecified": sum(1 for r in rows
                                           if r.get("asked") and r["underspecified"]),
            "asked_on_fully_specified": sum(1 for r in rows if r.get("asked")
                                            and not r["underspecified"]),
            "program_written": sum(1 for r in rows if r.get("program_written")),
            "program_raised": sum(1 for r in rows if r.get("program_written")
                                  and r.get("error")),
            "program_committed": sum(1 for r in rows if r.get("commits")),
            "score_errors": sum(1 for r in rows if r.get("score_error")),
        },
    }
    ops = collections.defaultdict(list)
    kinds = collections.defaultdict(list)
    for r in rows:
        intent = r.get("intent") or {}
        ops[str(intent.get("op"))].append(r)
        if intent.get("target_kind"):
            kinds[str(intent.get("target_kind"))].append(r)
    for name in sorted(ops):
        c = cell(ops[name])
        c["raised"] = sum(1 for r in ops[name] if r.get("error"))
        summary["by_parsed_operation"][name] = c
    for name in sorted(kinds):
        c = cell(kinds[name])
        c["raised"] = sum(1 for r in kinds[name] if r.get("error"))
        summary["by_target_reference_kind"][name] = c
    if model:
        ids = [r["task_id"] for r in rows if r["task_id"] in model]
        both = collections.Counter((completed(by_id[i]), model[i]) for i in ids)
        summary["versus_veribim_9b_full_read"] = {
            "file": str(model_file.relative_to(ROOT)),
            "n_common": len(ids),
            "veribim_9b_rate": round(sum(model[i] for i in ids) / len(ids), 4),
            "parser_rate": round(sum(completed(by_id[i]) for i in ids) / len(ids), 4),
            "both_completed": both[(True, True)],
            "parser_only": both[(True, False)],
            "model_only": both[(False, True)],
            "neither": both[(False, False)],
        }
    (HERE / out).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ("overall", "subset_108",
                                              "subset_324")}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
