"""The training set: chat records, loss masks, mix accounting, truncation rate.

The assembler reads the trajectory files the two sources wrote, renders each one
through the base model's chat template with the tool schema attached, computes
the assistant-token mask, and writes the training file. Nothing is silently
dropped: every record that does not make it is counted under the reason it
failed, and the realized mix and the length distribution are written next to the
data so the training report quotes measurements rather than intentions.

A trajectory longer than the training sequence length is dropped rather than cut.
Cutting one removes its commit round and its closing turn, which are two of the
three behaviours Stage A exists to teach, so a truncated example teaches the
opposite of what it is for. The rate is reported; ``--truncate`` keeps them,
shortened, for anyone who wants to measure the difference.
"""

from __future__ import annotations

import json
import random
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import paths
from .chat_format import encode
from .observed import listing_choice_justified, observed_identifiers_ok


def _load(path: Path) -> list[dict]:
    records = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _percentile(values: Sequence[int], fraction: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


def assemble(sources: Sequence[Path], out_dir: Path, model_dir: Path,
             max_seq: int = 8192, val_fraction: float = 0.0,
             seed: int = 20260824, emit_token_ids: bool = False,
             truncate: bool = False, require_observed: bool = True,
             out_name: str = "sft_train") -> dict:
    from transformers import AutoTokenizer

    paths.ensure_harness_on_path()
    from modifc_harness.prompts import SYSTEM_PROMPT_SHA256, TOOL_SCHEMA

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    tools = [TOOL_SCHEMA]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    records: list[dict] = []
    for source in sources:
        records.extend(_load(Path(source)))

    # A gold trajectory is one per task by construction, so a repeated task id
    # in the gold stream is a duplicate rather than a variant: a run that was
    # killed between writing a trajectory and writing its outcome could once
    # redo the task on resume and append it twice. The writer no longer allows
    # that; this is the safety net, and it counts what it removes.
    seen_gold: set[str] = set()
    deduped: list[dict] = []
    duplicates = 0
    for record in records:
        if record.get("source") == "gold":
            if record["task_id"] in seen_gold:
                duplicates += 1
                continue
            seen_gold.add(record["task_id"])
        deduped.append(record)
    records = deduped

    kept: list[dict] = []
    dropped: Counter = Counter()
    lengths: list[int] = []
    assistant_lengths: list[int] = []
    over_length = 0

    unobserved = 0
    unjustified = 0
    for record in records:
        if record.get("system_prompt_sha256") not in (None, SYSTEM_PROMPT_SHA256):
            dropped["system prompt does not match the frozen one"] += 1
            continue
        # A trajectory that writes an identifier nothing showed it teaches the
        # model to invent identifiers, which is the failure the evaluation then
        # reports on every spatial and topological task. It never reaches the
        # training file.
        instruction = record.get("instruction") or record.get("prompt") or ""
        if require_observed and observed_identifiers_ok(
                record.get("messages") or (), instruction):
            unobserved += 1
            dropped["uses an identifier it never observed"] += 1
            continue
        # And one it observed only as an entry in a list of candidates, with
        # nothing in the transcript saying which entry the instruction meant.
        if require_observed and listing_choice_justified(
                record.get("messages") or (), instruction):
            unjustified += 1
            dropped["picks one listed candidate without a reason"] += 1
            continue
        encoded = encode(tokenizer, record["messages"], record["loss_on"], tools,
                         max_seq=max_seq, truncate=truncate)
        if encoded.error == "over max_seq":
            over_length += 1
            lengths.append(encoded.n_tokens)
            dropped["longer than max_seq"] += 1
            continue
        if encoded.error:
            dropped[encoded.error] += 1
            continue
        lengths.append(encoded.n_tokens)
        assistant_lengths.append(encoded.n_assistant_tokens)
        entry = {
            "task_id": record["task_id"],
            "source": record["source"],
            "operation": record["operation"],
            "category": record["category"],
            "edit_kind": record.get("edit_kind", ""),
            "tier": record.get("tier", "single"),
            "families": list(record.get("families") or ()),
            "anchor_kind": record.get("anchor_kind", ""),
            "score": (record.get("score") or {}).get("final"),
            "messages": record["messages"],
            "loss_on": record["loss_on"],
            "tools": tools,
            "n_tokens": encoded.n_tokens,
            "n_assistant_tokens": encoded.n_assistant_tokens,
        }
        if emit_token_ids:
            entry["input_ids"] = encoded.input_ids
            entry["labels"] = encoded.labels
        kept.append(entry)

    rng = random.Random(seed)
    rng.shuffle(kept)
    n_val = int(round(val_fraction * len(kept))) if val_fraction > 0 else 0
    held_out, train = kept[:n_val], kept[n_val:]

    train_file = out_dir / f"{out_name}.jsonl"
    with train_file.open("w", encoding="utf-8") as fh:
        for entry in train:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    eval_file = out_dir / f"{out_name}_eval.jsonl"
    if held_out:
        with eval_file.open("w", encoding="utf-8") as fh:
            for entry in held_out:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    mix = Counter(entry["source"] for entry in kept)
    cells = Counter((entry["operation"], entry["category"]) for entry in kept)
    total = len(kept) or 1
    report = {
        "sources": [str(s) for s in sources],
        "trajectories_in": len(records),
        "duplicate_gold_trajectories_removed": duplicates,
        "require_observed": require_observed,
        "dropped_unobserved_identifier": unobserved,
        "dropped_unjustified_listing_choice": unjustified,
        "kept": len(kept),
        "train": len(train),
        "eval": len(held_out),
        "dropped": dict(dropped),
        "mix": {name: {"n": n, "share": round(n / total, 4)}
                for name, n in sorted(mix.items())},
        "mix_target": {"gold": 0.70, "self": 0.30},
        "by_cell": {f"{op}/{cat}": n for (op, cat), n in sorted(cells.items())},
        "by_operation": dict(Counter(e["operation"] for e in kept)),
        # One trajectory carries several of the generator's tags, so these
        # counts sum to more than the number kept; they are what a stratified
        # mix is checked against.
        "by_family": dict(sorted(Counter(
            family for entry in kept for family in entry.get("families") or ()
        ).items())),
        "by_anchor_kind": dict(sorted(Counter(
            entry.get("anchor_kind", "") for entry in kept).items())),
        "max_seq": max_seq,
        "truncation": {
            "over_max_seq": over_length,
            "rate": round(over_length / (len(records) or 1), 6),
            "policy": "truncated" if truncate else "dropped",
        },
        "sequence_tokens": {
            "mean": round(statistics.fmean(lengths), 1) if lengths else 0,
            "median": _percentile(lengths, 0.5),
            "p90": _percentile(lengths, 0.90),
            "p95": _percentile(lengths, 0.95),
            "p99": _percentile(lengths, 0.99),
            "max": max(lengths) if lengths else 0,
        },
        "assistant_tokens": {
            "mean": round(statistics.fmean(assistant_lengths), 1) if assistant_lengths else 0,
            "median": _percentile(assistant_lengths, 0.5),
            "share_of_sequence": round(
                sum(assistant_lengths) / sum(lengths), 4) if lengths else 0,
        },
        "system_prompt_sha256": SYSTEM_PROMPT_SHA256,
        "train_file": str(train_file),
        "eval_file": str(eval_file) if held_out else "",
        "tokenizer": str(model_dir),
    }
    report_name = ("dataset_report.json" if out_name == "sft_train"
                   else f"dataset_report_{out_name}.json")
    (out_dir / report_name).write_text(json.dumps(report, indent=2),
                                       encoding="utf-8")
    return report
