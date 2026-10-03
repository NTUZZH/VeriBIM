"""Stage B: DPO on the Stage A adapter, with the logprob masked to assistant
tokens.

Two departures from a stock DPO run, both required by the spec and both worth
stating because they change what the loss means.

*The logprob is over assistant tokens only.* A trajectory's completion contains
tool results the model did not write. Counting them would reward a trajectory
for the sandbox's output and would systematically prefer whichever side read
more, which is not a preference about behaviour. `concatenated_forward` is
overridden to sum only where the assistant mask is set.

*The reference is the Stage A adapter, not the bare base.* With PEFT, TRL's
default reference is the policy with the adapter switched off, which would make
the reference the untrained base model and the KL term would pull the policy
back toward something Stage A deliberately moved away from. The reference here
is base+sft590 with gradients off, and its logprobs are computed once in a
separate pass and cached, so only one 9B model is resident during training.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import unsloth  # noqa: F401  # must precede trl/transformers/peft imports
from unsloth import FastLanguageModel

import torch
import torch.nn.functional as F
from datasets import Dataset
from trl import DPOConfig, DPOTrainer

from stage_a import paths
from stage_a.train_args import EXPECTED_ADAPTER_PARAMS, LORA_TARGET_MODULES

STAGE_A_ADAPTER = paths.CHECKPOINT_ROOT / "sft_v1/val_adapters/step_590"


# --------------------------------------------------------------- data

def load_pairs(path: Path, max_seq: int) -> tuple[Dataset, dict]:
    rows: list[dict] = []
    stats = {"read": 0, "dropped_long": 0, "dropped_unmasked": 0}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            stats["read"] += 1
            chosen, rejected = record["chosen_input_ids"], record["rejected_input_ids"]
            cm, rm = record["chosen_completion_mask"], record["rejected_completion_mask"]
            if max(len(chosen), len(rejected)) > max_seq:
                stats["dropped_long"] += 1
                continue
            if not any(cm) or not any(rm):
                stats["dropped_unmasked"] += 1
                continue
            rows.append({"chosen_input_ids": chosen, "chosen_assistant_mask": cm,
                         "rejected_input_ids": rejected, "rejected_assistant_mask": rm})
    if not rows:
        raise ValueError(f"no usable pairs in {path}")
    return Dataset.from_list(rows), stats


def collate(examples: Sequence[dict], pad_id: int) -> dict:
    """Right-pad both sides; the mask says which tokens the loss may see."""
    out: dict[str, torch.Tensor] = {}
    for side in ("chosen", "rejected"):
        ids = [torch.tensor(e[f"{side}_input_ids"]) for e in examples]
        mask = [torch.tensor(e[f"{side}_assistant_mask"]) for e in examples]
        width = max(t.numel() for t in ids)
        out[f"{side}_input_ids"] = torch.stack(
            [F.pad(t, (0, width - t.numel()), value=pad_id) for t in ids])
        out[f"{side}_attention_mask"] = torch.stack(
            [F.pad(torch.ones_like(t), (0, width - t.numel()), value=0) for t in ids])
        out[f"{side}_assistant_mask"] = torch.stack(
            [F.pad(t, (0, width - t.numel()), value=0) for t in mask])
    for key in ("ref_chosen_logps", "ref_rejected_logps"):
        if key in examples[0]:
            out[key] = torch.tensor([e[key] for e in examples], dtype=torch.float32)
    return out


def masked_logps(model, input_ids: torch.Tensor, attention_mask: torch.Tensor,
                 assistant_mask: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Summed logprob over assistant tokens, the mean logit for logging, and the token count."""
    logits = model(input_ids=input_ids, attention_mask=attention_mask,
                   use_cache=False).logits
    logits = logits[:, :-1]
    targets = input_ids[:, 1:]
    keep = assistant_mask[:, 1:].bool() & attention_mask[:, 1:].bool()
    logps = torch.gather(logits.log_softmax(-1), dim=2,
                         index=targets.unsqueeze(2)).squeeze(2)
    return (logps * keep).sum(-1), logits[keep].mean() if keep.any() else logits.mean(), keep.sum(-1)


class MaskedDPOTrainer(DPOTrainer):
    """DPO whose logprob is restricted to the tokens the model actually wrote."""

    def _prepare_dataset(self, dataset, processing_class, args, dataset_name):
        # The pair file arrives tokenized, masked, and with reference logprobs
        # attached; TRL's text-column pipeline would look for raw `chosen`/
        # `rejected` strings that do not exist here.
        return dataset

    def concatenated_forward(self, model, batch, is_ref_model: bool = False) -> dict:
        chosen_logps, chosen_logits, chosen_tokens = masked_logps(
            model, batch["chosen_input_ids"], batch["chosen_attention_mask"],
            batch["chosen_assistant_mask"])
        rejected_logps, rejected_logits, _ = masked_logps(
            model, batch["rejected_input_ids"], batch["rejected_attention_mask"],
            batch["rejected_assistant_mask"])
        # Mean negative log-likelihood of the chosen assistant tokens. TRL adds
        # rpo_alpha times this to the DPO loss when rpo_alpha is set (the RPO
        # term of Pang et al. 2024), which keeps the chosen likelihood from
        # falling while the rejected one is pushed down.
        nll_loss = (-chosen_logps / chosen_tokens.clamp(min=1)).mean()
        return {
            "chosen_logps": chosen_logps,
            "rejected_logps": rejected_logps,
            "mean_chosen_logits": chosen_logits,
            "mean_rejected_logits": rejected_logits,
            "nll_loss": nll_loss,
        }

    def compute_ref_log_probs(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        if "ref_chosen_logps" in batch:
            return batch["ref_chosen_logps"], batch["ref_rejected_logps"]
        raise RuntimeError(
            "reference logprobs were not precomputed; Stage B does not use the "
            "adapter-disabled reference, so they must be cached beforehand")


@torch.no_grad()
def precompute_reference(model, dataset: Dataset, pad_id: int,
                         batch_size: int = 1) -> Dataset:
    """Reference logprobs from base+sft590 with gradients off.

    Run once, before the policy is made trainable, so the two models are never
    resident at the same time.
    """
    model.eval()
    chosen_out: list[float] = []
    rejected_out: list[float] = []
    for start in range(0, len(dataset), batch_size):
        rows = [dataset[i] for i in range(start, min(start + batch_size, len(dataset)))]
        batch = collate(rows, pad_id)
        batch = {k: v.to(model.device) for k, v in batch.items()}
        c, _, _ = masked_logps(model, batch["chosen_input_ids"],
                            batch["chosen_attention_mask"],
                            batch["chosen_assistant_mask"])
        r, _, _ = masked_logps(model, batch["rejected_input_ids"],
                            batch["rejected_attention_mask"],
                            batch["rejected_assistant_mask"])
        chosen_out.extend(c.float().cpu().tolist())
        rejected_out.extend(r.float().cpu().tolist())
        if (start // max(1, batch_size)) % 50 == 0:
            print(f"  reference pass {start}/{len(dataset)}", flush=True)
    return dataset.add_column("ref_chosen_logps", chosen_out).add_column(
        "ref_rejected_logps", rejected_out)


# --------------------------------------------------------------- main

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stage-b-train")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--pairs", required=True)
    ap.add_argument("--model-dir", default=str(paths.BASE_MODEL_DIR))
    ap.add_argument("--adapter", default=str(STAGE_A_ADAPTER))
    ap.add_argument("--checkpoint-root", default=str(paths.PROJECT_ROOT / "checkpoints/stage_b"))
    # Spec §3.
    ap.add_argument("--beta", type=float, default=0.1)
    ap.add_argument("--rpo-alpha", type=float, default=None,
                    help="weight of the chosen-side mean NLL added to the DPO loss (TRL rpo_alpha); off by default")
    ap.add_argument("--learning-rate", type=float, default=5e-6)
    ap.add_argument("--lr-scheduler", default="cosine")
    ap.add_argument("--warmup-ratio", type=float, default=0.03)
    ap.add_argument("--epochs", type=float, default=1.0)
    ap.add_argument("--per-device-batch", type=int, default=1)
    ap.add_argument("--grad-accum", type=int, default=32)
    ap.add_argument("--effective-batch", type=int, default=32)
    ap.add_argument("--max-seq", type=int, default=8192)
    ap.add_argument("--optim", default="adamw_8bit")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--logging-steps", type=int, default=5)
    ap.add_argument("--save-steps", type=int, default=200)
    ap.add_argument("--max-steps", type=int, default=-1)
    ap.add_argument("--expected-adapter-params", type=int, default=EXPECTED_ADAPTER_PARAMS)
    ap.add_argument("--compare-config", default=str(paths.CHECKPOINT_ROOT
                                                    / "sft_v1/resolved_config.json"))
    ap.add_argument("--dry-run", action="store_true",
                    help="load, assert, precompute nothing, dump config, stop")
    ap.add_argument("--precompute-only", action="store_true")
    ap.add_argument("--notes", default="")
    return ap


def diff_configs(current: dict, previous: dict, prefix: str = "") -> list[str]:
    lines: list[str] = []
    for key in sorted(set(current) | set(previous)):
        here, there = current.get(key), previous.get(key)
        path = f"{prefix}{key}"
        if isinstance(here, dict) and isinstance(there, dict):
            lines.extend(diff_configs(here, there, prefix=f"{path}."))
        elif here != there:
            lines.append(f"{path}: {there!r} -> {here!r}")
    return lines


def main(args: argparse.Namespace) -> int:
    from peft import PeftModel

    run_dir = Path(args.checkpoint_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if args.per_device_batch * args.grad_accum != args.effective_batch:
        raise SystemExit(
            f"effective batch {args.effective_batch} != "
            f"{args.per_device_batch} x {args.grad_accum}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_dir, max_seq_length=args.max_seq,
        dtype=torch.bfloat16, load_in_4bit=False, full_finetuning=False)
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    pad_id = text_tokenizer.pad_token_id or text_tokenizer.eos_token_id

    dataset, data_stats = load_pairs(Path(args.pairs), args.max_seq)

    # The Stage A adapter, loaded as the policy and continued. `is_trainable`
    # is what makes this a continuation rather than a fresh adapter.
    model = PeftModel.from_pretrained(model, args.adapter, is_trainable=True)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if trainable != args.expected_adapter_params:
        raise SystemExit(
            f"adapter has {trainable:,} trainable parameters, expected "
            f"{args.expected_adapter_params:,}: this is not the Stage A adapter "
            "continued, so the run would not be comparable")

    config = DPOConfig(
        output_dir=str(run_dir), beta=args.beta,
        per_device_train_batch_size=args.per_device_batch,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs, max_steps=args.max_steps,
        learning_rate=args.learning_rate, lr_scheduler_type=args.lr_scheduler,
        warmup_ratio=args.warmup_ratio, optim=args.optim, bf16=True, fp16=False,
        max_length=args.max_seq, logging_steps=args.logging_steps,
        save_strategy="steps", save_steps=args.save_steps, save_only_model=True,
        seed=args.seed, data_seed=args.seed, report_to=[],
        gradient_checkpointing=True, remove_unused_columns=False,
        precompute_ref_log_probs=False, rpo_alpha=args.rpo_alpha)

    dumped = {
        "stage": "B", "run_id": args.run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "cli_args": {k: v for k, v in vars(args).items() if not callable(v)},
        "policy": f"base + {args.adapter} (continued)",
        "reference": f"base + {args.adapter}, gradients off, logprobs precomputed",
        "adapter_trainable_params": trainable, "model_total_params": total,
        "lora_target_modules": sorted(LORA_TARGET_MODULES),
        "n_pairs": len(dataset), "data_stats": data_stats,
        "dpo_config": config.to_dict() if hasattr(config, "to_dict")
                      else dataclasses.asdict(config),
        "versions": {"torch": torch.__version__,
                     "python": sys.version.split()[0]},
        "notes": args.notes,
    }
    (run_dir / "resolved_config.json").write_text(
        json.dumps(dumped, indent=2, default=str), encoding="utf-8")
    if args.compare_config and Path(args.compare_config).exists():
        previous = json.loads(Path(args.compare_config).read_text(encoding="utf-8"))
        differences = diff_configs(dumped, previous)
        (run_dir / "config_diff_vs_stage_a.txt").write_text(
            "\n".join(differences) + "\n", encoding="utf-8")
        print(f"config differences against Stage A: {len(differences)}", flush=True)

    print(json.dumps({"run_id": args.run_id, "pairs": len(dataset),
                      "adapter_trainable_params": trainable,
                      "effective_batch": args.per_device_batch * args.grad_accum,
                      "resolved_config": str(run_dir / "resolved_config.json")},
                     indent=2), flush=True)
    if args.dry_run:
        print("dry run: model loaded, adapter asserted, config dumped; not training",
              flush=True)
        return 0

    ref_cache = run_dir / "pairs_with_ref_logps.jsonl"
    if ref_cache.exists() and sum(1 for _ in open(ref_cache)) == len(dataset):
        print(f"reference pass: reusing {ref_cache}", flush=True)
        dataset = Dataset.from_json(str(ref_cache))
    else:
        print("reference pass (base + sft590, gradients off)", flush=True)
        FastLanguageModel.for_inference(model)
        dataset = precompute_reference(model, dataset, pad_id)
        FastLanguageModel.for_training(model)
        gc.collect()
        torch.cuda.empty_cache()
        dataset.to_json(str(ref_cache))
    if args.precompute_only:
        print("precompute only: reference logprobs cached, not training", flush=True)
        return 0

    trainer = MaskedDPOTrainer(
        model=model, ref_model=None, args=config, train_dataset=dataset,
        processing_class=tokenizer,
        data_collator=lambda examples: collate(examples, pad_id))
    result = trainer.train()
    trainer.save_model(str(run_dir / "adapter"))
    from stage_a.chat_format import assert_saved_template, save_adapter

    save_adapter(model, tokenizer, run_dir / "adapter")
    print("adapter template:", json.dumps(assert_saved_template(run_dir / "adapter")),
          flush=True)
    (run_dir / "outcome.json").write_text(
        json.dumps({"metrics": dict(result.metrics),
                    "log_history": trainer.state.log_history}, indent=2, default=str),
        encoding="utf-8")
    return 0


def cli(argv: list[str] | None = None) -> int:
    return main(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(cli())
