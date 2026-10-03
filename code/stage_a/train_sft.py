"""Stage A SFT: LoRA on the pinned base, over full harness trajectories.

Three things are checked before a step is taken, because each of them is a
failure a finished run cannot be distinguished from a good one.

*The adapter shape.* The trainable parameter count is asserted against the
figure the Phase-0 dry run measured. A flag that silently changes the target
module set changes the model being compared, and the count catches it in
seconds rather than hours.

*The resolved configuration.* Everything the trainer actually resolved, library
versions included, is written to the run directory and, when a comparator is
named, diffed against it. Defaults are invisible on a command line and visible
in a diff.

*The data.* The training file records its own sequence lengths and the mask it
was built with; the trainer re-checks that no example exceeds the sequence
length and that every example has assistant tokens to learn from.

The validation hook runs the evaluation protocol against the model in memory
every N optimizer steps and writes the scored result to the run directory.

A run can also start from an adapter that already exists. ``--init-adapter``
loads it trainable instead of creating a new one, after checking that its rank,
alpha, dropout and target modules are the ones this run would record. Only the
weights are inherited: the optimizer, the schedule, the warmup and the epoch
count all start from step 0 on the new dataset. ``--replay-dataset`` mixes a
second file into the training set, with ``--replay-cap`` keeping a seeded sample
of it, which is how the new families are trained on without losing the old ones.
"""

from __future__ import annotations

import argparse
import dataclasses
import gc
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# The rollout hook allocates and frees several gigabytes on every call, so the
# allocator is asked for expandable segments before anything touches the card.
os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

import unsloth  # noqa: F401  # must precede trl/transformers/peft imports
from unsloth import FastLanguageModel

import torch
from datasets import Dataset
from transformers import TrainerCallback
from trl import SFTConfig, SFTTrainer

from . import paths
from .chat_format import encode
from .train_args import (LORA_TARGET_MODULES, add_train_arguments,
                         assert_adapter_params, base_config, check_adapter_config,
                         diff_configs, sample_indices)


def gpu_used_mib() -> tuple[int, int]:
    """(card used, this process's share), from nvidia-smi rather than torch."""
    def query(fields: str) -> str:
        return subprocess.run(
            ["nvidia-smi", f"--query-{fields}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, check=False).stdout.strip()

    total = 0
    first = query("gpu=memory.used").split("\n")[0]
    if first.isdigit():
        total = int(first)
    mine = 0
    for line in query("compute-apps=pid,used_memory").split("\n"):
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == os.getpid():
            mine = int(parts[1])
    return total, mine


def read_examples(path: Path, tokenizer, tools, max_seq: int, cap: int = 0,
                  seed: int = 42) -> tuple[list[dict], dict]:
    """One training file as token ids and labels, with the mask it was built with.

    ``cap`` keeps a seeded sample of the usable examples, and the counts it
    reports are taken after the sample, so the token statistics describe the set
    the trainer is handed rather than the file it came from.
    """
    usable: list[dict] = []
    sources: list[str] = []
    stats = {"path": str(path), "n": 0, "reused_token_ids": 0, "encoded_here": 0,
             "dropped": 0, "usable": 0, "cap": int(cap), "kept": 0,
             "max_tokens": 0, "assistant_tokens": 0, "total_tokens": 0,
             "by_source": {}}
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            stats["n"] += 1
            if "input_ids" in record and "labels" in record:
                input_ids, labels = record["input_ids"], record["labels"]
                stats["reused_token_ids"] += 1
            else:
                encoded = encode(tokenizer, record["messages"], record["loss_on"],
                                 record.get("tools") or tools, max_seq=max_seq)
                if encoded.error:
                    stats["dropped"] += 1
                    continue
                input_ids, labels = encoded.input_ids, encoded.labels
                stats["encoded_here"] += 1
            if len(input_ids) > max_seq:
                stats["dropped"] += 1
                continue
            if all(label == -100 for label in labels):
                stats["dropped"] += 1
                continue
            usable.append({"input_ids": input_ids, "labels": labels})
            sources.append(record.get("source", "unknown"))
    stats["usable"] = len(usable)
    selected = sample_indices(len(usable), cap, seed)
    rows = [usable[i] for i in selected]
    stats["kept"] = len(rows)
    for i in selected:
        labels = usable[i]["labels"]
        stats["max_tokens"] = max(stats["max_tokens"], len(usable[i]["input_ids"]))
        stats["total_tokens"] += len(usable[i]["input_ids"])
        stats["assistant_tokens"] += sum(1 for label in labels if label != -100)
        source = sources[i]
        stats["by_source"][source] = stats["by_source"].get(source, 0) + 1
    return rows, stats


def combine_stats(per_file: list[dict]) -> dict:
    """The mixed set's counts, with each file's own counts kept underneath."""
    combined = {"n": 0, "reused_token_ids": 0, "encoded_here": 0, "dropped": 0,
                "kept": 0, "max_tokens": 0, "assistant_tokens": 0,
                "total_tokens": 0, "by_source": {}}
    for stats in per_file:
        for key in ("n", "reused_token_ids", "encoded_here", "dropped", "kept",
                    "assistant_tokens", "total_tokens"):
            combined[key] += stats[key]
        combined["max_tokens"] = max(combined["max_tokens"], stats["max_tokens"])
        for source, count in stats["by_source"].items():
            combined["by_source"][source] = combined["by_source"].get(source, 0) + count
    combined["files"] = per_file
    return combined


def load_dataset(path: Path, tokenizer, tools, max_seq: int, cap: int = 0,
                 seed: int = 42) -> tuple[Dataset, dict]:
    """One file as a dataset, refusing a file that yields nothing to learn from."""
    rows, stats = read_examples(path, tokenizer, tools, max_seq, cap=cap, seed=seed)
    if not rows:
        raise ValueError(f"no usable examples in {path}")
    return Dataset.from_list(rows), stats


def load_training_data(specs: list[tuple[Path, int, str]], tokenizer, tools,
                       max_seq: int, seed: int) -> tuple[Dataset, dict]:
    """The training set, mixed from one file or from a new file and a replay file.

    Each spec is a path, the cap on that file and the name the counts are
    recorded under. The trainer shuffles with its own data seed, so the order
    the files are concatenated in does not reach the optimizer.
    """
    rows: list[dict] = []
    per_file: list[dict] = []
    for path, cap, role in specs:
        file_rows, stats = read_examples(path, tokenizer, tools, max_seq,
                                         cap=cap, seed=seed)
        if not file_rows:
            raise ValueError(f"no usable examples in {path}")
        stats["role"] = role
        rows.extend(file_rows)
        per_file.append(stats)
    return Dataset.from_list(rows), combine_stats(per_file)


class ValidationCallback(TrainerCallback):
    """Take the validation subset's measurement on the training cadence.

    Two modes, and the default is the safe one.

    ``snapshot`` writes the adapter to ``val_adapters/step_N`` and records that a
    measurement is due. ``stage_a.validate_checkpoint`` then rolls the subset out
    against that adapter in a process of its own, through the same agent loop,
    the same sandbox and the same scorer. Nothing about the training run is
    disturbed, and the measurement is taken on exactly the artifact a later stage
    would load.

    ``inprocess`` rolls out from the model being trained. It is available, and it
    is not the default: a 20-step smoke on 2026-08-25 measured what it costs.
    Generation runs through Unsloth's inference path, which swaps the layer
    implementations under the adapter, and the training loss stepped from 0.58
    to 4.2 at the first optimizer step after the hook and stayed there. The
    memory the rollout allocates is returned (21,352 MiB reserved before, 18,412
    after), so the cost is not memory; it is the model's own state. Use it only
    when a rollout is worth more than the run.
    """

    def __init__(self, model, tokenizer, tasks, tools, out_dir: Path,
                 every: int, max_rounds: int, max_new_tokens: int,
                 work_root: Path, mode: str = "snapshot",
                 trainer=None) -> None:
        self.model = model
        self.tokenizer = tokenizer
        self.tasks = tasks
        self.tools = tools
        self.out_dir = Path(out_dir)
        self.every = every
        self.max_rounds = max_rounds
        self.max_new_tokens = max_new_tokens
        self.work_root = Path(work_root)
        self.mode = mode
        self.trainer = trainer
        self.history: list[dict] = []
        self._last_step = -1

    # -- snapshot mode --------------------------------------------------
    def _snapshot(self, step: int) -> dict:
        target = self.out_dir / "val_adapters" / f"step_{step}"
        target.mkdir(parents=True, exist_ok=True)
        from .chat_format import save_adapter

        save_adapter(self.model, self.tokenizer, target)
        return {"step": step, "mode": "snapshot", "adapter": str(target),
                "status": "pending",
                "command": (f"python -m stage_a.validate_checkpoint --adapter {target} "
                            f"--n-tasks {len(self.tasks)}")}

    # -- in-process mode ------------------------------------------------
    def _rollout(self, step: int) -> dict:
        from .validate import run_validation

        was_training = self.model.training
        config = getattr(self.model, "config", None)
        cached = getattr(config, "use_cache", None) if config is not None else None
        before_mib = int(torch.cuda.memory_reserved() / 2**20)
        FastLanguageModel.for_inference(self.model)
        if config is not None:
            config.use_cache = True
        work = self.work_root / f"step_{step}"
        try:
            report = run_validation(
                self.model, self.tokenizer, self.tasks, self.tools,
                work_root=work, max_rounds=self.max_rounds,
                max_new_tokens=self.max_new_tokens)
        except Exception as exc:  # noqa: BLE001 - a failed hook must not end a run
            report = {"summary": {"error": f"{type(exc).__name__}: {exc}"[:300]},
                      "tasks": []}
        finally:
            if config is not None and cached is not None:
                config.use_cache = cached
            FastLanguageModel.for_training(self.model)
            if was_training:
                self.model.train()
            gc.collect()
            torch.cuda.empty_cache()
            shutil.rmtree(work, ignore_errors=True)
        after_mib = int(torch.cuda.memory_reserved() / 2**20)
        with (self.out_dir / "validation.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"step": step, **report}) + "\n")
        return {"step": step, "mode": "inprocess",
                "reserved_before_mib": before_mib, "reserved_after_mib": after_mib,
                **report["summary"]}

    def _run(self, step: int) -> None:
        if step == self._last_step:
            return
        self._last_step = step
        entry = self._snapshot(step) if self.mode == "snapshot" else self._rollout(step)
        self.history.append(entry)
        with (self.out_dir / "validation_index.jsonl").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        print(f"[validation] step {step}: {json.dumps(entry)}", flush=True)

    def on_step_end(self, args, state, control, **kwargs):
        if self.every and state.global_step and state.global_step % self.every == 0:
            self._run(state.global_step)
        return control

    def on_train_end(self, args, state, control, **kwargs):
        if self.every:
            self._run(state.global_step)
        return control


class MemoryCallback(TrainerCallback):
    """Record the card's occupancy, so a run's VRAM claim is a measurement."""

    def __init__(self, out_file: Path, every: int = 10, ceiling_mib: int = 0) -> None:
        self.out_file = Path(out_file)
        self.every = every
        self.ceiling_mib = ceiling_mib
        self.rows: list[dict] = []
        self.started = time.monotonic()

    def on_step_end(self, args, state, control, **kwargs):
        step = state.global_step
        if not step or step % self.every:
            return control
        total, mine = gpu_used_mib()
        row = {
            "step": step,
            "seconds": round(time.monotonic() - self.started, 1),
            "card_used_mib": total,
            "our_mib": mine,
            "torch_reserved_mib": int(torch.cuda.memory_reserved() / 2**20),
            "torch_allocated_mib": int(torch.cuda.memory_allocated() / 2**20),
            "loss": (state.log_history or [{}])[-1].get("loss"),
        }
        self.rows.append(row)
        with self.out_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
        return control


def resolved_config(args: argparse.Namespace, extra: dict) -> dict:
    import datasets
    import peft
    import transformers
    import trl

    versions = {
        "torch": torch.__version__,
        "transformers": transformers.__version__,
        "trl": trl.__version__,
        "peft": peft.__version__,
        "datasets": datasets.__version__,
        "unsloth": getattr(unsloth, "__version__", "unknown"),
        "python": sys.version.split()[0],
    }
    return base_config(args, versions, extra)


def main(args: argparse.Namespace) -> int:
    run_dir = Path(args.checkpoint_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.replay_cap and not args.replay_dataset:
        raise SystemExit("--replay-cap caps --replay-dataset, which was not given")

    if args.per_device_batch * args.grad_accum != args.effective_batch:
        raise SystemExit(
            f"effective batch {args.effective_batch} does not equal "
            f"{args.per_device_batch} x {args.grad_accum}")

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_dir,
        max_seq_length=args.max_seq,
        dtype=torch.bfloat16,
        load_in_4bit=False,
        full_finetuning=False,
    )
    if args.init_adapter:
        # Continue the adapter that exists instead of creating a new one, which
        # is what ``is_trainable`` does, and the way Stage B continues Stage A.
        # Its shape is checked first, because the rank, alpha, dropout and
        # target modules come from the adapter and not from this command line.
        adapter_config = check_adapter_config(
            args.init_adapter, rank=args.lora_rank, alpha=args.lora_alpha,
            dropout=args.lora_dropout)
        from peft import PeftModel

        model = PeftModel.from_pretrained(model, args.init_adapter,
                                          is_trainable=True)
    else:
        adapter_config = None
        model = FastLanguageModel.get_peft_model(
            model,
            r=args.lora_rank,
            target_modules=list(LORA_TARGET_MODULES),
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            use_gradient_checkpointing="unsloth",
            random_state=args.seed,
            use_rslora=False,
        )

    trainable, total = assert_adapter_params(model, args.expected_adapter_params,
                                             continued=bool(args.init_adapter))

    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    paths.ensure_harness_on_path()
    from modifc_harness.prompts import TOOL_SCHEMA

    tools = [TOOL_SCHEMA]
    specs: list[tuple[Path, int, str]] = [(Path(args.dataset), 0, "primary")]
    if args.replay_dataset:
        specs.append((Path(args.replay_dataset), args.replay_cap, "replay"))
    train_dataset, data_stats = load_training_data(specs, text_tokenizer, tools,
                                                   args.max_seq, args.seed)
    eval_dataset = None
    if args.eval_dataset:
        eval_dataset, _ = load_dataset(Path(args.eval_dataset), text_tokenizer,
                                       tools, args.max_seq)

    config = SFTConfig(
        output_dir=str(run_dir),
        per_device_train_batch_size=args.per_device_batch,
        gradient_accumulation_steps=args.grad_accum,
        num_train_epochs=args.epochs,
        max_steps=args.max_steps,
        learning_rate=args.learning_rate,
        lr_scheduler_type=args.lr_scheduler,
        warmup_ratio=args.warmup_ratio,
        weight_decay=args.weight_decay,
        max_grad_norm=args.max_grad_norm,
        optim=args.optim,
        bf16=True,
        fp16=False,
        logging_steps=args.logging_steps,
        save_strategy="steps",
        save_steps=args.save_steps,
        save_total_limit=args.save_total_limit,
        save_only_model=True,
        seed=args.seed,
        data_seed=args.seed,
        report_to=[],
        max_length=args.max_seq,
        packing=False,
        completion_only_loss=False,
        assistant_only_loss=False,
        dataset_num_proc=1,
        gradient_checkpointing=True,
        eval_strategy="no",
    )

    trainer = SFTTrainer(
        model=model,
        args=config,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        processing_class=tokenizer,
    )

    callbacks: list[TrainerCallback] = [
        MemoryCallback(run_dir / "vram.jsonl", every=max(1, args.logging_steps),
                       ceiling_mib=args.vram_ceiling_mib)
    ]
    validation = None
    if args.val_every:
        from .validate import pick_tasks

        tasks = pick_tasks(Path(args.val_tasks_file), args.val_n_tasks,
                           args.val_task_ids_file)
        (run_dir / "validation_task_ids.json").write_text(
            json.dumps([t["task_id"] for t in tasks], indent=1), encoding="utf-8")
        validation = ValidationCallback(
            model=model, tokenizer=tokenizer, tasks=tasks, tools=tools,
            out_dir=run_dir, every=args.val_every, max_rounds=args.val_max_rounds,
            max_new_tokens=args.val_max_new_tokens, mode=args.val_mode,
            work_root=Path(args.checkpoint_root).parent / "_val_work" / args.run_id)
        callbacks.append(validation)
    for callback in callbacks:
        trainer.add_callback(callback)

    card_used, ours = gpu_used_mib()
    config_dump = resolved_config(args, {
        "run_dir": str(run_dir),
        "init_adapter": args.init_adapter or None,
        "init_adapter_config": adapter_config,
        "adapter_trainable_params": trainable,
        "model_total_params": total,
        "trainable_fraction": round(trainable / total, 6),
        "dataset_stats": data_stats,
        "n_train_examples": len(train_dataset),
        "n_eval_examples": len(eval_dataset) if eval_dataset is not None else 0,
        "sft_config": dataclasses.asdict(config) if dataclasses.is_dataclass(config)
                      else config.to_dict(),
        "gpu_at_launch": {"card_used_mib": card_used, "our_mib": ours,
                          "ceiling_mib": args.vram_ceiling_mib},
    })
    config_file = run_dir / "resolved_config.json"
    config_file.write_text(json.dumps(config_dump, indent=2, default=str),
                           encoding="utf-8")

    if args.compare_config:
        previous = json.loads(Path(args.compare_config).read_text(encoding="utf-8"))
        differences = diff_configs(config_dump, previous)
        (run_dir / "config_diff.txt").write_text("\n".join(differences) + "\n",
                                                 encoding="utf-8")
        print(f"config differences against {args.compare_config}: "
              f"{len(differences)}", flush=True)

    print(json.dumps({
        "run_id": args.run_id,
        "init_adapter": args.init_adapter or None,
        "adapter_trainable_params": trainable,
        "model_total_params": total,
        "n_train_examples": len(train_dataset),
        "examples_per_file": {stats["path"]: stats["kept"]
                              for stats in data_stats["files"]},
        "max_tokens_in_set": data_stats["max_tokens"],
        "assistant_token_share": round(
            data_stats["assistant_tokens"] / max(1, data_stats["total_tokens"]), 4),
        "effective_batch": args.per_device_batch * args.grad_accum,
        "resolved_config": str(config_file),
    }, indent=2), flush=True)

    if args.dry_run:
        print("dry run: configuration dumped and adapter asserted, not training",
              flush=True)
        return 0

    result = trainer.train()
    trainer.save_model(str(run_dir / "adapter"))
    from .chat_format import save_adapter, assert_saved_template

    save_adapter(model, tokenizer, run_dir / "adapter")
    print("adapter template:", json.dumps(assert_saved_template(run_dir / "adapter")),
          flush=True)

    card_after, ours_after = gpu_used_mib()
    outcome = {
        "run_id": args.run_id,
        "metrics": dict(result.metrics),
        "log_history": trainer.state.log_history,
        "validation": validation.history if validation else [],
        "adapter_dir": str(run_dir / "adapter"),
        "peak_torch_reserved_mib": int(torch.cuda.max_memory_reserved() / 2**20),
        "gpu_after": {"card_used_mib": card_after, "our_mib": ours_after},
        "finished_at": datetime.now().isoformat(timespec="seconds"),
    }
    (run_dir / "outcome.json").write_text(json.dumps(outcome, indent=2, default=str),
                                          encoding="utf-8")
    print(json.dumps({k: v for k, v in outcome.items() if k != "log_history"},
                     indent=2, default=str), flush=True)
    return 0


def cli(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage-a-train")
    add_train_arguments(parser)
    return main(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(cli())
