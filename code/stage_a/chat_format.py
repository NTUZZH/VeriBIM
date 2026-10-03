"""Turning a trajectory into tokens, with loss on assistant tokens only.

The rendering must be the one the model meets at evaluation time, or the
training signal is written in a dialect the served model never speaks. Two
things follow from that and are enforced here.

*The tool list is part of the prompt.* The server is called with the tool schema
attached, so the chat template prepends the tool preamble to the system message.
Rendering training text without it would train on a prompt shorter than the one
the model is later given.

*The loss starts where generation starts.* The template opens an assistant turn
with ``<|im_start|>assistant\\n<think>\\n``, which is exactly the generation
prompt the server sends. Everything from there to the turn's ``<|im_end|>`` is
the model's own output and carries loss; the system turn, the user turn and
every tool result are masked.

Spans are computed by rendering each conversation prefix and taking the
difference, so the mask follows the template rather than a guess about it. If a
prefix ever fails to be a prefix of the whole, the record is refused instead of
being masked approximately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

ASSISTANT_HEADER = "<|im_start|>assistant\n<think>\n"
TURN_END = "<|im_end|>\n"

#: The template a VeriBIM adapter is trained with and must be served with.
#: It differs from the stock Qwen template in one place: the generation prompt
#: ends `<think>\n\n` rather than `<think>\n`, so that the prompt the server
#: sends is a *token* prefix of the text the trainer supervised.
CANONICAL_TEMPLATE = Path(__file__).with_name("chat_template_veribim.jinja")


def canonical_template() -> str:
    return CANONICAL_TEMPLATE.read_text(encoding="utf-8")


def assert_boundary_matches(tokenizer, messages: Sequence[dict],
                            tools: Sequence[dict],
                            template: str | None = None) -> dict:
    """The serve-time prompt must be a token prefix of the train-time render.

    This is the check that was missing. The original rendering was verified at
    the character level, where it passes: the training text does begin with the
    generation prompt's characters. It fails at the token level, because the
    tokenizer merges the newline that ends the generation prompt with the one
    that follows it into a single token, so the model is asked to continue from
    a token it never saw in that position. Every boundary claim is now made in
    token ids, in both directions, and a mismatch raises instead of shipping.
    """
    template = template if template is not None else canonical_template()
    first_assistant = next((i for i, m in enumerate(messages)
                            if m.get("role") == "assistant"), None)
    if first_assistant is None:
        raise ValueError("conversation has no assistant turn")
    full = tokenizer.apply_chat_template(list(messages), tools=list(tools),
                                         tokenize=False, chat_template=template)
    prompt = tokenizer.apply_chat_template(list(messages[:first_assistant]),
                                           tools=list(tools), tokenize=False,
                                           add_generation_prompt=True,
                                           chat_template=template)
    full_ids = tokenizer(full, add_special_tokens=False)["input_ids"]
    prompt_ids = tokenizer(prompt, add_special_tokens=False)["input_ids"]
    common = 0
    for a, b in zip(prompt_ids, full_ids):
        if a != b:
            break
        common += 1
    ok = common == len(prompt_ids)
    if not ok:
        raise AssertionError(
            "serve-time prompt is not a token prefix of the training render: "
            f"{common} of {len(prompt_ids)} tokens agree; prompt ends with "
            f"{prompt_ids[common:common + 2]!r}, training has "
            f"{full_ids[common:common + 2]!r}")
    return {"prompt_tokens": len(prompt_ids), "common_prefix_tokens": common,
            "first_generated_token": full_ids[len(prompt_ids)],
            "token_prefix": ok}


@dataclass
class Encoded:
    input_ids: list[int]
    labels: list[int]
    n_tokens: int
    n_assistant_tokens: int
    n_chars: int
    error: Optional[str] = None


def _render(tokenizer, messages: Sequence[dict], tools: Sequence[dict]) -> str:
    return tokenizer.apply_chat_template(list(messages), tools=list(tools),
                                         tokenize=False,
                                         chat_template=canonical_template())


def assistant_spans(tokenizer, messages: Sequence[dict], loss_on: Sequence[bool],
                    tools: Sequence[dict]) -> tuple[str, list[tuple[int, int]], Optional[str]]:
    """The rendered conversation and the character spans loss falls on."""
    full = _render(tokenizer, messages, tools)
    spans: list[tuple[int, int]] = []
    prefix_lengths: dict[int, int] = {}
    for index in range(2, len(messages) + 1):
        rendered = _render(tokenizer, messages[:index], tools)
        if not full.startswith(rendered[: len(rendered)]) or not full.startswith(rendered):
            return full, [], f"prefix mismatch at message {index}"
        prefix_lengths[index] = len(rendered)

    for index, message in enumerate(messages):
        if not (index >= 2 and loss_on[index] and message.get("role") == "assistant"):
            continue
        start = prefix_lengths[index]
        end = prefix_lengths[index + 1]
        header = full[start:start + len(ASSISTANT_HEADER)]
        if header != ASSISTANT_HEADER:
            return full, [], f"unexpected assistant header at message {index}"
        start += len(ASSISTANT_HEADER)
        if full[end - len(TURN_END):end] == TURN_END:
            end -= 1  # keep <|im_end|>, drop the separator newline after it
        spans.append((start, end))
    return full, spans, None


def encode(tokenizer, messages: Sequence[dict], loss_on: Sequence[bool],
           tools: Sequence[dict], max_seq: int | None = None,
           truncate: bool = False) -> Encoded:
    """Token ids and labels for one trajectory."""
    full, spans, error = assistant_spans(tokenizer, messages, loss_on, tools)
    if error is not None:
        return Encoded([], [], 0, 0, len(full), error=error)
    encoding = tokenizer(full, add_special_tokens=False,
                         return_offsets_mapping=True)
    input_ids = list(encoding["input_ids"])
    offsets = list(encoding["offset_mapping"])
    labels = [-100] * len(input_ids)
    for position, (begin, stop) in enumerate(offsets):
        if stop <= begin:
            continue
        for span_start, span_end in spans:
            if begin >= span_start and stop <= span_end:
                labels[position] = input_ids[position]
                break
    n_assistant = sum(1 for label in labels if label != -100)
    if not n_assistant:
        return Encoded(input_ids, labels, len(input_ids), 0, len(full),
                       error="no assistant tokens carry loss")
    if max_seq is not None and len(input_ids) > max_seq:
        if not truncate:
            return Encoded(input_ids, labels, len(input_ids), n_assistant, len(full),
                           error="over max_seq")
        input_ids = input_ids[:max_seq]
        labels = labels[:max_seq]
        n_assistant = sum(1 for label in labels if label != -100)
    return Encoded(input_ids, labels, len(input_ids), n_assistant, len(full))


def assert_saved_template(adapter_dir: "Path | str") -> dict:
    """The template written beside an adapter must be the one it was trained with.

    `save_pretrained` writes the tokenizer's own chat template, which is the
    stock one unless something replaced it. An adapter shipped with the stock
    template is not broken in any visible way: it loads, it serves, and it
    quietly reverts to open-ended deliberation because the generation prompt no
    longer matches the boundary it was trained on. That happened to
    dpo_v1 and was caught by a checksum before serving, not by the code.
    """
    import hashlib

    directory = Path(adapter_dir)
    written = directory / "chat_template.jinja"
    canonical = canonical_template()
    want = hashlib.md5(canonical.encode("utf-8")).hexdigest()
    if not written.exists():
        raise AssertionError(f"{written} is missing: an adapter must ship its template")
    got = hashlib.md5(written.read_text(encoding="utf-8").encode("utf-8")).hexdigest()
    return {"path": str(written), "md5": got, "canonical_md5": want, "matches": got == want}


def save_adapter(model, tokenizer, adapter_dir: "Path | str",
                 adapter_name: "str | None" = None) -> dict:
    """Save an adapter and leave the canonical template beside it, asserted.

    The stock template is kept as `chat_template.stock.jinja` rather than
    deleted, so what the tokenizer would have written stays visible.

    `adapter_name` selects one adapter from a model that carries several (Stage
    C holds a trainable policy and a frozen reference). PEFT writes a selected
    adapter into a subdirectory named after it; the weights are lifted back to
    `adapter_dir` so the result is a directory a server can load directly.
    """
    directory = Path(adapter_dir)
    directory.mkdir(parents=True, exist_ok=True)
    if adapter_name is None:
        model.save_pretrained(str(directory))
    else:
        model.save_pretrained(str(directory), selected_adapters=[adapter_name])
        nested = directory / adapter_name
        if nested.is_dir():
            for item in nested.iterdir():
                target = directory / item.name
                if target.exists():
                    target.unlink()
                item.rename(target)
            nested.rmdir()
    try:
        tokenizer.save_pretrained(str(directory))
    except Exception:  # noqa: BLE001 - the adapter weights are what matter
        pass
    written = directory / "chat_template.jinja"
    if written.exists():
        stock = directory / "chat_template.stock.jinja"
        current = written.read_text(encoding="utf-8")
        if current != canonical_template() and not stock.exists():
            stock.write_text(current, encoding="utf-8")
    written.write_text(canonical_template(), encoding="utf-8")
    checked = assert_saved_template(directory)
    if not checked["matches"]:
        raise AssertionError(f"canonical template did not land in {directory}")
    return checked
