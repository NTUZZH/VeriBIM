"""The Stage A trainer's arguments, in one place.

Kept apart from the trainer itself so the command line can be parsed, dumped and
diffed without importing the training stack, which is what the pre-launch
configuration check needs.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import paths

#: LoRA target modules. This is the set the Phase-0 dry run validated on the
#: pinned base; it is written out rather than derived so a change of library
#: default cannot silently change the adapter.
LORA_TARGET_MODULES = (
    "q_proj", "k_proj", "v_proj", "o_proj",
    "gate_proj", "up_proj", "down_proj",
    "in_proj_a", "in_proj_b", "in_proj_qkv", "in_proj_z", "out_proj",
)

#: Trainable parameter count of that adapter on Qwen3.5-9B at rank 16, measured
#: in the dry run. The trainer asserts it and refuses to start on a
#: mismatch, because a silently different adapter shape is the failure that a
#: finished run cannot be distinguished from a good one.
EXPECTED_ADAPTER_PARAMS = 43_278_336


def add_train_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True,
                        help="checkpoints land in checkpoints/stage_a/<run-id>/")
    parser.add_argument("--dataset", required=True,
                        help="assembled training file (sft_train.jsonl)")
    parser.add_argument("--replay-dataset", default="",
                        help="second training file, mixed into the first;"
                             " the old-family sample a continue run replays")
    parser.add_argument("--replay-cap", type=int, default=0,
                        help="keep at most N usable examples of the replay file,"
                             " drawn with --seed; 0 keeps all of them")
    parser.add_argument("--eval-dataset", default="",
                        help="optional held-out file for the loss-only evaluation")
    parser.add_argument("--init-adapter", default="",
                        help="continue from this LoRA adapter instead of starting"
                             " a new one; its adapter_config.json must match the"
                             " rank, alpha, dropout and target modules requested")
    parser.add_argument("--model-dir", default=str(paths.BASE_MODEL_DIR))
    parser.add_argument("--checkpoint-root", default=str(paths.CHECKPOINT_ROOT))

    parser.add_argument("--max-seq", type=int, default=8192)
    parser.add_argument("--lora-rank", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.0)
    parser.add_argument("--learning-rate", type=float, default=1e-4)
    parser.add_argument("--lr-scheduler", default="cosine")
    parser.add_argument("--warmup-ratio", type=float, default=0.03)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--per-device-batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=64,
                        help="per-device batch times this is the effective batch")
    parser.add_argument("--effective-batch", type=int, default=64,
                        help="asserted against per-device batch times accumulation")
    parser.add_argument("--weight-decay", type=float, default=0.0)
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--optim", default="adamw_8bit")
    parser.add_argument("--logging-steps", type=int, default=5)
    parser.add_argument("--save-steps", type=int, default=200)
    parser.add_argument("--save-total-limit", type=int, default=3)
    parser.add_argument("--max-steps", type=int, default=-1,
                        help="cap the run; -1 runs the requested epochs")

    parser.add_argument("--val-every", type=int, default=200,
                        help="score the validation subset every N optimizer steps;"
                             " 0 turns the hook off")
    parser.add_argument("--val-tasks-file", default=str(paths.default_tasks_file()))
    parser.add_argument("--val-task-ids-file", default="",
                        help="json list of the fixed validation task ids")
    parser.add_argument("--val-n-tasks", type=int, default=100)
    parser.add_argument("--val-mode", choices=("snapshot", "inprocess"),
                        default="snapshot",
                        help="snapshot: write the adapter and let"
                             " stage_a.validate_checkpoint score it in its own"
                             " process. inprocess: roll out from the model being"
                             " trained, which perturbs the run (see the trainer's"
                             " docstring for the measurement).")
    parser.add_argument("--val-max-rounds", type=int, default=22)
    parser.add_argument("--val-max-new-tokens", type=int, default=8192)

    parser.add_argument("--vram-ceiling-mib", type=int, default=39_599,
                        help="the budget the neighbouring process leaves us")
    parser.add_argument("--expected-adapter-params", type=int,
                        default=EXPECTED_ADAPTER_PARAMS)
    parser.add_argument("--compare-config", default="",
                        help="resolved config of the run this one is compared with;"
                             " the difference is dumped before training starts")
    parser.add_argument("--dry-run", action="store_true",
                        help="build the model and the dataset, dump the config,"
                             " assert the adapter, and stop before training")
    parser.add_argument("--notes", default="")


def sample_indices(n: int, cap: int, seed: int) -> list[int]:
    """The kept positions when a file of ``n`` examples is capped at ``cap``.

    The draw is seeded, so the same file and the same seed keep the same
    examples, and the positions come back in file order so the mixed set does
    not depend on the order the sampler happened to produce.
    """
    if cap <= 0 or n <= cap:
        return list(range(n))
    return sorted(random.Random(seed).sample(range(n), cap))


def adapter_module_names(target_modules: Any) -> set[str]:
    """The projection names a saved ``target_modules`` field refers to.

    Peft writes the field either as the list it was given or, under Unsloth, as
    one regular expression over the module paths. Both forms name the same
    modules as whole identifier tokens, so the tokens carrying ``proj`` are the
    set to compare.
    """
    if isinstance(target_modules, str):
        tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", target_modules)
    elif isinstance(target_modules, Iterable):
        tokens = [str(t) for t in target_modules]
    else:
        tokens = []
    return {t for t in tokens if "proj" in t}


def load_adapter_config(adapter_dir) -> dict:
    """The adapter's own ``adapter_config.json``, read as it was written."""
    config_file = Path(adapter_dir) / "adapter_config.json"
    if not config_file.exists():
        raise SystemExit(f"{config_file} does not exist, so {adapter_dir} is not "
                         "a LoRA adapter this run can continue")
    return json.loads(config_file.read_text(encoding="utf-8"))


def check_adapter_config(adapter_dir, rank: int, alpha: int, dropout: float,
                         target_modules: Sequence[str] = LORA_TARGET_MODULES) -> dict:
    """Refuse an adapter whose shape is not the one the run asks for.

    A continued run takes its rank, alpha, dropout and target modules from the
    adapter it loads and not from the command line, so a command line that
    disagrees with the adapter would be recorded as the configuration of a run
    that never happened. Every mismatch is reported at once, before any weights
    are read.
    """
    config = load_adapter_config(adapter_dir)
    problems: list[str] = []
    if config.get("r") != rank:
        problems.append(f"rank {config.get('r')} in the adapter, {rank} requested")
    if config.get("lora_alpha") != alpha:
        problems.append(
            f"alpha {config.get('lora_alpha')} in the adapter, {alpha} requested")
    if float(config.get("lora_dropout", 0.0)) != float(dropout):
        problems.append(f"dropout {config.get('lora_dropout')} in the adapter, "
                        f"{dropout} requested")
    if config.get("use_rslora"):
        problems.append("the adapter was trained with rslora, this run is not")
    found = adapter_module_names(config.get("target_modules"))
    wanted = set(target_modules)
    if found != wanted:
        missing = sorted(wanted - found)
        extra = sorted(found - wanted)
        problems.append(f"target modules differ: missing {missing}, extra {extra}")
    if problems:
        raise SystemExit(
            f"{adapter_dir} cannot be continued: " + "; ".join(problems) +
            ". The adapter shape is not the one this run would record, so the "
            "run would not be comparable.")
    return config


def assert_adapter_params(model, expected: int, continued: bool = False
                          ) -> tuple[int, int]:
    """Count the adapter and refuse a shape the comparison was not made against.

    The count is asserted whether the adapter was just created or loaded from an
    existing one, because a continued run whose adapter differs is as
    incomparable as a fresh one.
    """
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    if trainable != expected:
        source = "the adapter this run continues" if continued else "the adapter"
        raise SystemExit(
            f"{source} has {trainable:,} trainable parameters, expected "
            f"{expected:,}. The adapter shape is not the one the dry run "
            "validated, so this run would not be comparable.")
    return trainable, total


def diff_configs(current: dict, previous: dict, prefix: str = "") -> list[str]:
    """Every difference between two resolved configurations, flattened."""
    lines: list[str] = []
    for key in sorted(set(current) | set(previous)):
        here, there = current.get(key), previous.get(key)
        path = f"{prefix}{key}"
        if isinstance(here, dict) and isinstance(there, dict):
            lines.extend(diff_configs(here, there, prefix=f"{path}."))
        elif here != there:
            lines.append(f"{path}: {there!r} -> {here!r}")
    return lines


def base_config(args: argparse.Namespace, versions: dict, extra: dict) -> dict:
    """The resolved configuration, minus what only the training stack knows."""
    # ``func`` is the subcommand's handler, whose repr carries a memory address
    # and would show up as a spurious difference in every config diff.
    cli_args = {k: v for k, v in vars(args).items() if not callable(v)}
    return {
        "stage": "A",
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "cli_args": cli_args,
        "lora_target_modules": sorted(LORA_TARGET_MODULES),
        "versions": versions,
        **extra,
    }
