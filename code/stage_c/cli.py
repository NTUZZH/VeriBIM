"""Offline checks for the Stage C pieces, so none of them needs the card.

    python -m stage_c.cli reward     # the normalisation, against known values
    python -m stage_c.cli masks      # gradient masks over real transcripts
    python -m stage_c.cli pool       # the task pool and its batch composition
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from stage_a import paths


def check_reward(_: argparse.Namespace) -> int:
    from stage_c.reward import (REWARD_CEILING, REWARD_FLOOR, heldout_config,
                                normalise, training_config)

    cases = [(0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.5, 0.0, 0.5),
             (0.162, 0.162, 0.0), (1.0, 0.162, 1.0), (0.0, 0.5, -0.2),
             (0.9, 0.8427, 0.364)]
    bad = []
    for final, null, want in cases:
        got = normalise(final, null)
        if abs(got - want) > 5e-3:
            bad.append((final, null, want, got))
    print(f"normalisation: {len(cases) - len(bad)}/{len(cases)} cases agree")
    for null in (0.0, 0.1, 0.5, 0.8427):
        got = normalise(null, null)
        print(f"  an unchanged file at null={null}: r={got:+.4f}")
        if got != 0.0:
            bad.append(("no-op", null, 0.0, got))
    print(f"clip range: [{REWARD_FLOOR}, {REWARD_CEILING}]")
    for operation in ("create", "update", "delete"):
        train, held = training_config(operation), heldout_config(operation)
        differences = {f: (getattr(train, f), getattr(held, f)) for f in vars(train)
                       if getattr(train, f) != getattr(held, f)}
        print(f"  {operation}: held-out verifier differs in {differences}")
        if set(differences) != {"sampling_seed", "pooled_max_total_samples",
                                "pooled_min_samples_per_object"}:
            bad.append(("heldout", operation, sorted(differences)))
    print("REWARD:", "PASS" if not bad else f"FAIL {bad}")
    return 1 if bad else 0


def check_masks(args: argparse.Namespace) -> int:
    from transformers import AutoTokenizer

    paths.ensure_harness_on_path()
    from modifc_harness.prompts import TOOL_SCHEMA
    from stage_c.rollout import Rollout, encode_group

    tokenizer = AutoTokenizer.from_pretrained(str(paths.BASE_MODEL_DIR))
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    source = Path(args.rollouts)
    bad: list[str] = []
    with source.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if line_no > args.tasks:
                break
            task = json.loads(line)
            group = [
                Rollout(index=i, messages=s["messages"], stop_reason=s["stop_reason"],
                        tool_rounds=s["tool_rounds"], commits=s["commits"],
                        tool_calls=len(s["calls"]),
                        raised_calls=sum(1 for c in s["calls"] if c["raised"]),
                        well_formed_calls=sum(1 for c in s["calls"] if c["well_formed"]),
                        reward=0.0)
                for i, s in enumerate(task["samples"][:args.per_task], start=1)]
            encoded = encode_group(tokenizer, task, group, [TOOL_SCHEMA], args.max_seq)
            for row in encoded["rollouts"]:
                if "error" in row:
                    bad.append(f"task {line_no} rollout {row['index']}: {row['error']}")
                    continue
                ids, mask = row["completion_ids"], row["completion_mask"]
                spans, start = [], None
                for i, flag in enumerate(mask):
                    if flag and start is None:
                        start = i
                    elif not flag and start is not None:
                        spans.append((start, i))
                        start = None
                if start is not None:
                    spans.append((start, len(mask)))
                for a, b in spans:
                    text = tokenizer.decode(ids[a:b])
                    if not text.startswith("</think>"):
                        bad.append(f"task {line_no} rollout {row['index']}: span opens on "
                                   f"{text[:20]!r}, not the assistant turn")
                    if not text.rstrip().endswith("<|im_end|>"):
                        bad.append(f"task {line_no} rollout {row['index']}: span does not "
                                   "close on the turn boundary")
                    if "<tool_response>" in text:
                        bad.append(f"task {line_no} rollout {row['index']}: tool output "
                                   "carries gradient")
                print(f"task {line_no} rollout {row['index']}: {len(ids)} tokens, "
                      f"{sum(mask)} assistant, {len(spans)} spans")
    print("MASKS:", "PASS" if not bad else "FAIL")
    for problem in bad[:10]:
        print("  ", problem)
    return 1 if bad else 0


def check_pool(args: argparse.Namespace) -> int:
    from collections import Counter

    from stage_c.train_grpo import load_pool, stratified_order

    tasks = load_pool(Path(args.tasks_file), args.split)
    ordered = stratified_order(tasks, args.seed)
    print(f"pool: {len(tasks)} tasks, {len(ordered)} ordered")
    print("overall mix:", dict(Counter(t["operation"] for t in tasks)))
    for start in (0, 32, 64):
        window = ordered[start:start + 32]
        print(f"  batch at {start}: {dict(Counter(t['operation'] for t in window))}")
    nulls = [t["verification"]["null_edit_score"] for t in tasks]
    print(f"null-edit mean {sum(nulls) / len(nulls):.4f} over {len(nulls)} tasks")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stage-c")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("reward").set_defaults(func=check_reward)
    masks = sub.add_parser("masks")
    masks.add_argument("--rollouts",
                       default=str(paths.PROJECT_ROOT
                                   / "runs_local/stage_b_sample_v1/rollouts.jsonl"))
    masks.add_argument("--tasks", type=int, default=3)
    masks.add_argument("--per-task", type=int, default=4)
    masks.add_argument("--max-seq", type=int, default=8192)
    masks.set_defaults(func=check_masks)
    pool = sub.add_parser("pool")
    pool.add_argument("--tasks-file",
                      default=str(paths.PROJECT_ROOT
                                  / "data/veribim_tasks_canonical/tasks.jsonl"))
    pool.add_argument("--split", default="train")
    pool.add_argument("--seed", type=int, default=42)
    pool.set_defaults(func=check_pool)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
