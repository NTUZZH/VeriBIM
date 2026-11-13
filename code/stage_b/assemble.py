"""Turning preference pairs into tokens, with the DPO logprob masked to
assistant tokens.

Three properties are asserted rather than assumed, because each of them is a
way the training signal can be quietly wrong.

*The prompt is shared.* DPO compares two continuations of one prompt. Here the
prompt's tokens must be a prefix of both sides, in ids, and the assertion fails
the pair rather than trimming it.

*The boundary is the serve-time one.* Rendering goes through the canonical
template, so the token the model is asked to produce first is the token
it was trained to produce, in this stage as in Stage A.

*Only assistant tokens count.* A trajectory's completion contains tool results,
which the model did not write. Leaving them in the DPO logprob would reward a
trajectory for the sandbox's output, which it does not control, and would make
the longer trajectory look preferred for having read more.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from stage_a import paths
from stage_a.chat_format import ASSISTANT_HEADER, TURN_END, canonical_template


def _render(tokenizer, messages: Sequence[dict], tools: Sequence[dict],
            generation_prompt: bool = False) -> str:
    return tokenizer.apply_chat_template(
        list(messages), tools=list(tools), tokenize=False,
        add_generation_prompt=generation_prompt,
        chat_template=canonical_template())


def _assistant_spans(tokenizer, messages: Sequence[dict], tools: Sequence[dict],
                     start_index: int) -> tuple[str, list[tuple[int, int]], Optional[str]]:
    """Character spans of the assistant turns from ``start_index`` onward."""
    full = _render(tokenizer, messages, tools)
    lengths: dict[int, int] = {}
    for index in range(start_index, len(messages) + 1):
        rendered = _render(tokenizer, messages[:index], tools)
        if not full.startswith(rendered):
            return full, [], f"prefix mismatch at message {index}"
        lengths[index] = len(rendered)
    spans: list[tuple[int, int]] = []
    for index, message in enumerate(messages):
        if index < start_index or message.get("role") != "assistant":
            continue
        begin, end = lengths[index], lengths[index + 1]
        if full[begin:begin + len(ASSISTANT_HEADER)] != ASSISTANT_HEADER:
            return full, [], f"unexpected assistant header at message {index}"
        begin += len(ASSISTANT_HEADER)
        if full[end - len(TURN_END):end] == TURN_END:
            end -= 1
        spans.append((begin, end))
    return full, spans, None


def encode_side(tokenizer, prompt_messages: Sequence[dict],
                completion: Sequence[dict], tools: Sequence[dict]) -> dict:
    """Token ids for prompt+completion, with the assistant mask over completion."""
    messages = list(prompt_messages) + list(completion)
    start = len(prompt_messages)
    full, spans, error = _assistant_spans(tokenizer, messages, tools, start)
    if error:
        return {"error": error}
    encoding = tokenizer(full, add_special_tokens=False, return_offsets_mapping=True)
    ids = list(encoding["input_ids"])
    offsets = list(encoding["offset_mapping"])
    mask = [0] * len(ids)
    for position, (begin, stop) in enumerate(offsets):
        if stop <= begin:
            continue
        for span_start, span_end in spans:
            if begin >= span_start and stop <= span_end:
                mask[position] = 1
                break
    prompt_text = _render(tokenizer, prompt_messages, tools, generation_prompt=True)
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]
    common = 0
    for a, b in zip(prompt_ids, ids):
        if a != b:
            break
        common += 1
    if common != len(prompt_ids):
        return {"error": f"prompt is not a token prefix ({common}/{len(prompt_ids)})"}
    if not any(mask):
        return {"error": "no assistant tokens in the completion"}
    return {"input_ids": ids, "completion_mask": mask,
            "prompt_len": len(prompt_ids), "n_assistant": sum(mask)}


def assemble(pairs_file: Path, out_dir: Path, model_dir: Path,
             max_seq: int = 8192, emit_token_ids: bool = True) -> dict:
    from transformers import AutoTokenizer

    paths.ensure_harness_on_path()
    from modifc_harness.prompts import TOOL_SCHEMA

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    tools = [TOOL_SCHEMA]
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    kept: list[dict] = []
    dropped: Counter = Counter()
    lengths: list[int] = []
    chosen_assistant: list[int] = []
    rejected_assistant: list[int] = []

    with Path(pairs_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            pair = json.loads(line)
            chosen = encode_side(tokenizer, pair["prompt_messages"],
                                 pair["chosen_messages"], tools)
            if "error" in chosen:
                dropped[f"chosen: {chosen['error']}"] += 1
                continue
            rejected = encode_side(tokenizer, pair["prompt_messages"],
                                   pair["rejected_messages"], tools)
            if "error" in rejected:
                dropped[f"rejected: {rejected['error']}"] += 1
                continue
            if chosen["prompt_len"] != rejected["prompt_len"]:
                dropped["prompt lengths differ between sides"] += 1
                continue
            longest = max(len(chosen["input_ids"]), len(rejected["input_ids"]))
            if longest > max_seq:
                dropped["longer than max_seq"] += 1
                lengths.append(longest)
                continue
            lengths.append(longest)
            chosen_assistant.append(chosen["n_assistant"])
            rejected_assistant.append(rejected["n_assistant"])
            entry = {k: pair[k] for k in
                     ("construction", "task_id", "operation", "category",
                      "edit_kind", "building_id", "schema", "reason",
                      "named_class", "chosen_final", "rejected_final",
                      "families", "underspecified")
                     if k in pair}
            entry["prompt_len"] = chosen["prompt_len"]
            entry["chosen_tokens"] = len(chosen["input_ids"])
            entry["rejected_tokens"] = len(rejected["input_ids"])
            entry["chosen_assistant_tokens"] = chosen["n_assistant"]
            entry["rejected_assistant_tokens"] = rejected["n_assistant"]
            if emit_token_ids:
                entry["chosen_input_ids"] = chosen["input_ids"]
                entry["chosen_completion_mask"] = chosen["completion_mask"]
                entry["rejected_input_ids"] = rejected["input_ids"]
                entry["rejected_completion_mask"] = rejected["completion_mask"]
            kept.append(entry)

    train_file = out_dir / "dpo_pairs.jsonl"
    with train_file.open("w", encoding="utf-8") as fh:
        for entry in kept:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def pct(values, fraction):
        if not values:
            return 0
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]

    report = {
        "pairs_file": str(pairs_file),
        "pairs_in": sum(dropped.values()) + len(kept),
        "kept": len(kept),
        "dropped": dict(dropped),
        "by_construction": dict(Counter(p["construction"] for p in kept)),
        "by_reason": dict(Counter(p.get("reason", "") for p in kept)),
        "by_named_class": dict(Counter(p.get("named_class", "") or "none" for p in kept)),
        "by_operation": dict(Counter(p["operation"] for p in kept)),
        "by_category": dict(Counter(p["category"] for p in kept)),
        # The v2 task set tags each task with taxonomy families. A pair is
        # counted once per tag it carries, and once per layer, the part of the
        # tag before its first dot. A v1 pair carries no tag and both counts
        # are empty.
        "by_family": dict(Counter(
            f for p in kept for f in (p.get("families") or ())).most_common()),
        "by_layer": dict(Counter(
            f.split(".")[0] for p in kept
            for f in (p.get("families") or ())).most_common()),
        "underspecified_pairs": sum(1 for p in kept if p.get("underspecified")),
        "buildings": len({p["building_id"] for p in kept}),
        "max_seq": max_seq,
        "sequence_tokens": {
            "mean": round(statistics.fmean(lengths), 1) if lengths else 0,
            "median": pct(lengths, 0.5), "p95": pct(lengths, 0.95),
            "max": max(lengths) if lengths else 0,
        },
        "assistant_tokens": {
            "chosen_mean": round(statistics.fmean(chosen_assistant), 1) if chosen_assistant else 0,
            "rejected_mean": round(statistics.fmean(rejected_assistant), 1) if rejected_assistant else 0,
        },
        "score_margin_mean": round(statistics.fmean(
            [p["chosen_final"] - p["rejected_final"] for p in kept
             if p.get("chosen_final") is not None
             and p.get("rejected_final") is not None]), 4) if kept else None,
        "train_file": str(train_file),
        "template": str(canonical_template.__module__),
    }
    (out_dir / "pairs_report.json").write_text(json.dumps(report, indent=2),
                                               encoding="utf-8")
    return report
