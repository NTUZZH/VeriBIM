"""Stage C: GRPO against the verifier, on the eval protocol's own rollouts.

Three things here are not stock TRL, and each exists for a reason the earlier
stages paid for.

*Rollouts are trajectories, not completions.* `_generate_and_score_completions`
is replaced: a group is k multi-turn episodes against an external vLLM server,
each with its own sandbox, scored by the verifier. TRL's own generation path is
never entered.

*Attention and gradient use different masks.* A completion contains tool results
the sandbox wrote. They must be attended to, or the assistant tokens after them
are scored without their context; they must not carry gradient, or the policy is
trained on the environment's words. TRL uses one `completion_mask` for both, so
the gradient mask goes in `completion_mask` (where all of TRL's loss and metric
code already reads it) and the attention mask travels alongside as an extra
tensor, which `split_tensor_dict` slices correctly for accumulation.

*The reference is dpo_v1, not the base.* With PEFT, TRL's default reference is
the policy with its adapter switched off, which is the untrained base model —
the KL would pull against everything Stages A and B did. The reference here is a
second, frozen copy of the same adapter, held under its own PEFT adapter name;
it costs 173 MB rather than a second 9B model, which is what makes it fit beside
the rollout server at all.
"""

from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Sequence

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from stage_a import paths
from stage_a.train_args import EXPECTED_ADAPTER_PARAMS, LORA_TARGET_MODULES

from .reward import COMMIT_REQUIRED_CHOICES

DPO_ADAPTER = paths.PROJECT_ROOT / "checkpoints/stage_b/dpo_v1/adapter"
POLICY_ADAPTER_NAME = "policy"
REFERENCE_ADAPTER_NAME = "reference"

#: What one optimizer step's accumulated gradient works out to, relative to the
#: gradient of the same batch's token-level loss taken in a single call. The
#: loss returned here is divided exactly once on its way to the backward pass,
#: inside the accelerator; the Trainer's own division for the accumulation count
#: does not run, because TRL disables it by leaving a placeholder loss function
#: on the trainer. Measured on CPU at two accumulation counts and two real-row
#: counts in stage_c/tests/test_train_grpo_v3.py.
MEASURED_GRAD_FACTOR = "1 / gradient_accumulation_steps"

#: How many generation batches in a row may encode nothing before the run
#: stops. One such batch is taken as a no-op step; this many in a row, at the
#: better part of an hour each, is the sampling server gone away.
EMPTY_BATCH_LIMIT = 3

#: How many generation batches the sampler-versus-trainer log-probability
#: check may ask before it gives up. It asks one group per batch; a group that
#: scores flat is skipped before encoding and cannot be compared, which is
#: what happened on the first batch of grpo_v3 and left that run without the
#: reading. Asking again costs the server nothing but the log-probability
#: payload on one group.
LOGPROB_CHECK_ATTEMPTS = 5

#: How the run's configuration names what the advantage is divided by, one
#: phrase per value of --scale-rewards. Dividing by the group's own standard
#: deviation is standard GRPO; dividing by nothing is the form Dr. GRPO argues
#: for, because the division makes a group with a narrow reward spread take as
#: large a step as a group with a wide one.
_ADVANTAGE_SCALING = {
    "group": "group-scaled",
    "batch": "batch-scaled (divided by the spread of the whole batch)",
    "none": "unscaled (Dr. GRPO form)",
}


def _shaping_phrase(args: argparse.Namespace) -> str:
    """What was taken off the verifier's value, in the run's own record.

    Every clause names a deduction that was on. A run with all three off says
    so, which is the sentence the reward/evaluation separation rests on.
    """
    parts: list[str] = []
    if args.error_penalty:
        parts.append(f"minus {args.error_penalty} per tool call that raised, "
                     f"capped at {args.error_penalty_cap}")
    if args.repeat_penalty:
        parts.append(f"minus {args.repeat_penalty} per tool call resending code "
                     f"that already raised, capped at {args.repeat_penalty_cap} "
                     "")
    if args.commit_required != "off":
        parts.append("zero when a trajectory of "
                     f"{'any operation' if args.commit_required == 'all' else 'a create task'}"
                     " never called commit()")
    if not parts:
        return "none beyond the unreadable-file penalty"
    return "; ".join(parts)


def resolved_config(args: argparse.Namespace, extra: dict) -> dict:
    """Everything the run resolved, dumped before anything touches the card."""
    versions: dict[str, str] = {"python": sys.version.split()[0]}
    for name in ("torch", "transformers", "trl", "peft", "datasets"):
        try:
            versions[name] = __import__(name).__version__
        except Exception:  # noqa: BLE001 - a dry run may lack the training stack
            versions[name] = "unavailable"
    return {
        "stage": "C",
        "run_id": args.run_id,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "cli_args": {k: v for k, v in vars(args).items() if not callable(v)},
        "policy": "base + dpo_v1 (continued)",
        "reference": "base + dpo_v1, frozen, held as a second PEFT adapter",
        "reward": {
            "definition": "(final - null_edit) / (1 - null_edit), clipped [-0.2, 1]",
            "delete_semantics": "removal",
            "scorer_reading": ("per record, stage_a.scoring.scorer_config_for: "
                               "material, type-object and under-specified "
                               "families get the settings their edit is visible "
                               "under, every other task the published reading"),
            "unreadable_final_file": -0.2,
            "shaping": _shaping_phrase(args),
            "error_penalty": args.error_penalty,
            "error_penalty_cap": args.error_penalty_cap,
            "repeat_penalty": args.repeat_penalty,
            "repeat_penalty_cap": args.repeat_penalty_cap,
            "commit_required": args.commit_required,
            "completion_bonus": args.completion_bonus,
        },
        "rollout": {
            "server": "external vLLM, canonical template, LoRA hot-loaded",
            "protocol": "multi-turn, single execute_ifc_code tool, sandbox per trajectory",
            "rounds_cap": args.max_tool_rounds,
            "temperature": args.temperature,
            "top_p": args.top_p,
            "rollouts_per_task_step": args.num_generations,
            "max_transcript_tokens": args.max_transcript_tokens,
            "min_turn_tokens": args.min_turn_tokens,
            # A run that stops after a tool round ends on tool messages no
            # model turn was conditioned on. They are dropped from the
            # transcript the trainer encodes, so the encoded length is the
            # budget plus one assistant turn's header and end marker.
            "unread_tool_results_dropped": True,
            "duplicate_call_stop": args.dup_stop,
        },
        "loss": {
            "form": ("token-level over the real completion tokens of the "
                     "generation batch (TRL 'dapo' normalisation), advantages "
                     f"group-centred and {_ADVANTAGE_SCALING[args.scale_rewards]}"
                     ", k3 KL to the frozen dpo_v1 adapter at beta"),
            "scale_rewards": args.scale_rewards,
            "importance_ratio": ("identically 1: one optimizer pass per "
                                 "generation batch, so PPO clipping is inert"),
            "measured_grad_factor": MEASURED_GRAD_FACTOR,
        },
        "lora_target_modules": sorted(LORA_TARGET_MODULES),
        "expected_adapter_params": args.expected_adapter_params,
        "versions": versions,
        "notes": args.notes,
        **extra,
    }


TRAINER_CONFIG_KEYS = ("grpo_config", "dpo_config", "sft_config", "trainer_config")


def _normalise(config: dict) -> dict:
    """Give the trainer's own config one name in both dumps.

    Stage B wrote it as `dpo_config` and Stage C writes `grpo_config`, so an
    unnormalised diff reports one enormous line instead of the per-setting
    differences that make the comparison worth running.
    """
    out = dict(config)
    for key in TRAINER_CONFIG_KEYS:
        if key in out and key != "trainer_config":
            out["trainer_config"] = out.pop(key)
            break
    return out


def diff_configs(current: dict, previous: dict, prefix: str = "") -> list[str]:
    if not prefix:
        current, previous = _normalise(current), _normalise(previous)
    lines: list[str] = []
    for key in sorted(set(current) | set(previous)):
        here, there = current.get(key), previous.get(key)
        path = f"{prefix}{key}"
        if isinstance(here, dict) and isinstance(there, dict):
            lines.extend(diff_configs(here, there, prefix=f"{path}."))
        elif here != there:
            lines.append(f"{path}: {there!r} -> {here!r}")
    return lines


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="stage-c-train")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--tasks-file",
                    default=str(paths.PROJECT_ROOT / "data/veribim_tasks_canonical/tasks.jsonl"))
    ap.add_argument("--split", default="train")
    ap.add_argument("--exclude-category", action="append", default=[],
                    help="drop every task of this instruction category from the "
                         "pool (repeatable). grpo_v3 drops 'direct': 81.7%% of "
                         "those groups scored flat, so they carry no gradient "
                         "")
    ap.add_argument("--model-dir", default=str(paths.BASE_MODEL_DIR))
    ap.add_argument("--adapter", default=str(DPO_ADAPTER))
    ap.add_argument("--reference-adapter", default="",
                    help="KL anchor; empty = same as --adapter. A continuation "
                         "run passes the ORIGINAL dpo_v1 here so the anchor "
                         "does not silently move to the restart point")
    ap.add_argument("--checkpoint-root",
                    default=str(paths.PROJECT_ROOT / "checkpoints/stage_c"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--served-adapter", default="dpo_v1")
    # Spec §3-4.
    ap.add_argument("--num-generations", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--top-p", type=float, default=0.95)
    ap.add_argument("--max-tool-rounds", type=int, default=12)
    ap.add_argument("--tool-timeout", type=float, default=420.0)
    ap.add_argument("--max-tokens", type=int, default=8192)
    ap.add_argument("--max-tool-output-chars", type=int, default=16000)
    ap.add_argument("--max-transcript-tokens", type=int, default=0,
                    help="stop a trajectory once its transcript reaches this "
                         "many tokens (0 = off, which is the evaluation "
                         "protocol). Set it below --max-seq so a trajectory is "
                         "stopped while it still encodes, instead of being "
                         "thrown away after it has been rolled out and scored")
    ap.add_argument("--min-turn-tokens", type=int, default=256,
                    help="a request is not sent when fewer than this many "
                         "tokens are left inside the transcript budget")
    ap.add_argument("--dup-stop", type=int, default=0,
                    help="stop once one tool call and its output have repeated "
                         "this many times (0 = off). Three separates a stuck "
                         "trajectory from a working one on the validation set")
    ap.add_argument("--max-seq", type=int, default=12288,
                    help="8192 dropped the 12-round transcripts at encoding, "
                         "and those carry the reward spread")
    ap.add_argument("--learning-rate", type=float, default=1e-6)
    ap.add_argument("--lr-scheduler", default="constant_with_warmup")
    ap.add_argument("--warmup-ratio", type=float, default=0.03)
    ap.add_argument("--beta", type=float, default=0.04)
    ap.add_argument("--error-penalty", type=float, default=0.0,
                    help="Reward deducted per tool call that raised "
                         "(0 = the verifier's value alone, the v1 pilot design)")
    ap.add_argument("--error-penalty-cap", type=float, default=0.10,
                    help="most a trajectory can lose to --error-penalty; below "
                         "it a partly correct edit still outranks a no-op")
    ap.add_argument("--repeat-penalty", type=float, default=0.0,
                    help="Reward deducted each time a tool call "
                         "resends code that already raised earlier in the same "
                         "trajectory, whitespace ignored (0 = off, which is "
                         "every run up to grpo_v3; 0.05 is the designed value)")
    ap.add_argument("--repeat-penalty-cap", type=float, default=0.25,
                    help="most a trajectory can lose to --repeat-penalty; it "
                         "binds only when --repeat-penalty is above zero")
    ap.add_argument("--commit-required", default="off",
                    choices=list(COMMIT_REQUIRED_CHOICES),
                    help="which operations score zero when the trajectory "
                         "never called commit(): none ('off', the behaviour of "
                         "every run up to grpo_v3), create tasks only, or all "
                         "of them. An uncommitted create already scores at the "
                         "no-op floor through the file; 'create' makes the rule "
                         "exact and records when it fired")
    ap.add_argument("--per-device-batch", type=int, default=1)
    ap.add_argument("--effective-batch", type=int, default=32)
    ap.add_argument("--max-steps", type=int, default=300)
    ap.add_argument("--skip-tasks", type=int, default=0,
                    help="task rows dropped from the head of the stratified "
                         "order. A continuation run passes (steps already "
                         "trained x tasks per step) so it resumes the task "
                         "sequence instead of restarting it from row 0")
    ap.add_argument("--optim", default="adamw_8bit")
    ap.add_argument("--loss-type", default="dapo",
                    choices=["grpo", "bnpo", "dapo", "dr_grpo"],
                    help="informational only: the loss here is computed by this "
                         "module's own compute_loss, which normalises over the "
                         "real completion tokens of the generation batch "
                         "whatever this says. It is recorded so the run's "
                         "configuration names the form that was used")
    ap.add_argument("--scale-rewards", default="group",
                    choices=["group", "batch", "none"],
                    help="what a centred reward is divided by before it becomes "
                         "an advantage: the standard deviation of its own group, "
                         "the standard deviation of the whole generation batch, "
                         "or nothing. 'none' is the Dr. GRPO form, which keeps a "
                         "group with a narrow reward spread from taking as large "
                         "a step as a group with a wide one")
    ap.add_argument("--task-ids-file", default="",
                    help="JSON list of task ids: keep only these tasks of the split "
                         "(after --exclude-category). grpo_v9 trains on the tasks the "
                         "Stage B artifact still gets wrong or only sometimes right, "
                         "because groups whose eight rollouts agree carry no gradient")
    ap.add_argument("--completion-bonus", type=float, default=0.0,
                    help="added to the normalised reward when every checker axis is "
                         ">= 0.9 (the completion verdict); 0 keeps the "
                         "reward of grpo_v3/v4. Reaches the scorer subprocess through "
                         "VERIBIM_COMPLETION_BONUS")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--logging-steps", type=int, default=1)
    ap.add_argument("--save-steps", type=int, default=50)
    ap.add_argument("--rollout-workers", type=int, default=16)
    ap.add_argument("--group-parallel", type=int, default=1,
                    help="task groups rolled out concurrently; 1 keeps the "
                         "sequential behaviour the smoke runs measured. Each "
                         "group holds --num-generations rollouts, so the "
                         "in-flight request count is the product of the two")
    ap.add_argument("--gold-cache",
                    default=str(paths.PROJECT_ROOT / "data/stage_c/_gold"))
    ap.add_argument("--work-root",
                    default=str(paths.PROJECT_ROOT / "data/stage_c/_rollouts"))
    ap.add_argument("--sync-every", type=int, default=1,
                    help="push the policy to the sampling server every N optimizer "
                         "steps; 0 samples from a frozen adapter (off-policy)")
    ap.add_argument("--serve-root", default="",
                    help="where pushed adapters are written (default: run dir)")
    ap.add_argument("--logit-chunk", type=int, default=512,
                    help="positions per output-projection chunk in the loss; "
                         "lower buys VRAM margin at some speed")
    ap.add_argument("--vram-ceiling-mib", type=int, default=25_000,
                    help="ceiling on THIS process; the sampling server holds the "
                         "rest of the card, so the Stage A/B figure does not apply")
    ap.add_argument("--vram-slope-steps", type=int, default=50)
    ap.add_argument("--drift-every", type=int, default=10,
                    help="every N steps, report how far the policy adapter has "
                         "travelled from the frozen anchor (0 = never)")
    ap.add_argument("--logprob-check", action=argparse.BooleanOptionalAction,
                    default=True,
                    help="on the first generation batch only, hold the sampling "
                         "server's per-token log-probabilities against the "
                         "trainer's own for one group")
    ap.add_argument("--expected-adapter-params", type=int,
                    default=EXPECTED_ADAPTER_PARAMS)
    ap.add_argument("--compare-config",
                    default=str(paths.PROJECT_ROOT
                                / "checkpoints/stage_b/dpo_v1/resolved_config.json"))
    ap.add_argument("--dump-config-only", action="store_true",
                    help="resolve and dump the configuration without touching the card")
    ap.add_argument("--dry-run", action="store_true",
                    help="load the model, assert the adapter, dump config, stop")
    ap.add_argument("--notes", default="")
    return ap


def assert_one_row_per_micro_batch(per_device_batch: int) -> None:
    """One row per micro-batch, which the left-padding trim depends on.

    ``trim_left`` drops the columns that are padding in every row it is given.
    With one row that is the whole of that row's padded prefix; with more rows
    it is only the part they share, and the padding left behind is read into
    the state of the recurrent-attention layers, which zero it only for a batch
    of more than one row. The loss would then score the real tokens after a
    prefix of padding.
    """
    if int(per_device_batch) != 1:
        raise ValueError(
            "this trainer needs one row per micro-batch: "
            f"per_device_train_batch_size is {per_device_batch}. Dropping the "
            "left padding a micro-batch shares removes the whole padded prefix "
            "only when there is one row, and the recurrent-attention layers "
            "read what is left into the state the real tokens are scored from.")


def build_grpo_config(args: argparse.Namespace, run_dir: Path,
                      generation_batch: int):
    """The trainer's own configuration. Pure Python, so a dump needs no card."""
    from trl import GRPOConfig

    assert_one_row_per_micro_batch(args.per_device_batch)
    config = GRPOConfig(
        output_dir=str(run_dir), beta=args.beta,
        num_generations=args.num_generations,
        generation_batch_size=generation_batch,
        per_device_train_batch_size=args.per_device_batch,
        gradient_accumulation_steps=generation_batch // args.per_device_batch,
        learning_rate=args.learning_rate, lr_scheduler_type=args.lr_scheduler,
        warmup_ratio=args.warmup_ratio, optim=args.optim, bf16=True, fp16=False,
        max_steps=args.max_steps, temperature=args.temperature, top_p=args.top_p,
        scale_rewards=args.scale_rewards,
        logging_steps=args.logging_steps, save_strategy="no",
        seed=args.seed, data_seed=args.seed, report_to=[],
        gradient_checkpointing=True, remove_unused_columns=False,
        use_vllm=False, log_completions=False,
        # Three TRL defaults would quietly change the run and are pinned here.
        # loss_type is recorded rather than obeyed: `compute_loss` below is this
        # module's own and normalises over the real completion tokens of the
        # generation batch, which is what "dapo" names.
        loss_type=args.loss_type,
        # max_completion_length defaults to 256 tokens, an eighth of a typical
        # rollout, and truncation flags feed off it.
        max_completion_length=args.max_seq,
        # shuffle_dataset defaults to True, which would undo the stratified
        # order that gives each batch its balance of create/update/delete.
        shuffle_dataset=False, num_train_epochs=1.0,
        # Stage B trained with dropout off. The model's own dropout is 0.0 and
        # so is the adapter's, so this changes no arithmetic; it removes a
        # class of nondeterminism between the reference pass and the policy
        # pass rather than leaving it to a default.
        disable_dropout=True)
    if hasattr(config, "unsloth_grpo_mini_batch"):
        # Only present once Unsloth has patched the config class. Unsloth
        # autotunes a chunk count from the sequence length and then computes
        # `total_rows // B`, which is zero for the one-row calls this trainer
        # makes for the reference and the policy, so long sequences crashed on
        # a division by zero. Pinning the chunk to one row keeps that division
        # meaningful at any length.
        config.unsloth_grpo_mini_batch = 1
    return config


def dump_config(args: argparse.Namespace, extra: dict | None = None) -> dict:
    run_dir = Path(args.checkpoint_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    config = resolved_config(args, extra or {})
    (run_dir / "resolved_config.json").write_text(
        json.dumps(config, indent=2, default=str), encoding="utf-8")
    if args.compare_config and Path(args.compare_config).exists():
        previous = json.loads(Path(args.compare_config).read_text(encoding="utf-8"))
        differences = diff_configs(config, previous)
        (run_dir / "config_diff_vs_dpo_v1.txt").write_text(
            "\n".join(differences) + "\n", encoding="utf-8")
        config["config_differences_vs_dpo_v1"] = len(differences)
    return config


# ------------------------------------------------------------------ trainer

def trim_left(input_ids, attention):
    """Drop the columns that are padding in every row of the micro-batch.

    With one row per micro-batch the left padding of that row is pure waste,
    and it is not harmless waste: 24 of this architecture's 32 layers use
    recurrent linear attention, and the transformers implementation only zeroes
    the padded positions of their state when the batch holds more than one row.
    A padded prefix therefore leaks into the state the real tokens are read
    from. Removing the shared prefix is exact for the standard-attention layers
    and removes the leak for the others. The completion sits at the end of the
    row, so the number of positions the loss keeps does not change.
    """
    if attention.ndim < 2 or attention.size(1) == 0:
        return input_ids, attention
    # A row with no real token at all has no first real column; argmax already
    # answers 0 for it, which is the answer that keeps every column.
    first = int(attention.argmax(dim=1).min())
    if first <= 0:
        return input_ids, attention
    return input_ids[:, first:], attention[:, first:]


def adapter_drift(model, policy: str = POLICY_ADAPTER_NAME,
                  reference: str = REFERENCE_ADAPTER_NAME
                  ) -> tuple[float, int]:
    """How far the policy adapter has travelled from the frozen anchor.

    The relative L2 distance over every LoRA module, taking the two factors
    together: the square root of the summed squared differences of A and B,
    divided by the summed squared norms of the anchor's own A and B. It is the
    same quantity a comparison of two saved adapters reports, computed from the
    live parameters so a run can watch it without writing a snapshot first.

    The number of factor pairs the distance was taken over is returned with it.
    Finding none raises, because a layout this function cannot read would
    otherwise report a distance of zero, which is exactly what a policy held
    close by a strong penalty reports, and the one instrument that says whether
    the policy is moving would look healthy while measuring nothing.
    """
    import torch

    numerator = 0.0
    denominator = 0.0
    pairs = 0
    with torch.no_grad():
        for module in model.modules():
            for holder in (getattr(module, "lora_A", None),
                           getattr(module, "lora_B", None)):
                if holder is None:
                    continue
                try:
                    moved = holder[policy].weight
                    anchor = holder[reference].weight
                except (KeyError, AttributeError, TypeError):
                    continue
                moved = moved.detach().float()
                anchor = anchor.detach().float()
                numerator += float(((moved - anchor) ** 2).sum())
                denominator += float((anchor ** 2).sum())
                pairs += 1
    if not pairs or denominator <= 0:
        raise ValueError(
            f"no distance could be taken: {pairs} LoRA factor pairs carried "
            f"both a '{policy}' and a '{reference}' weight, and their summed "
            f"squared norm is {denominator}. A reading of zero here would be "
            "indistinguishable from a policy that has not moved")
    return math.sqrt(numerator / denominator), pairs


def _build_trainer_class():
    """Imported lazily so a config dump does not need the training stack."""
    import torch
    from trl import GRPOTrainer

    from .rollout import encode_group, rollout_group

    class VeriBIMGRPOTrainer(GRPOTrainer):
        """GRPO whose rollouts are harness trajectories and whose gradient is
        restricted to assistant tokens."""

        def __init__(self, *pargs, veribim=None, **kwargs):
            self.veribim = veribim or {}
            self._full_attention = None
            self._rollout_log: list[dict] = []
            self._synced_step = -1
            self._alignment_divergence_seen = False
            self._trunk_module = None
            self._logprob_check_done = False
            self._logprob_check_attempts = 0
            # One encoded row kept from an earlier step, so a step whose own
            # batch encoded nothing still has a row to take a no-op on.
            self._last_encoded_row: Optional[tuple] = None
            # How many generation batches in a row encoded nothing. One is a
            # bad batch; EMPTY_BATCH_LIMIT in a row is a sampling server that
            # has gone away, and the run stops rather than spend its remaining
            # steps on no-ops.
            self._batches_encoding_nothing = 0
            super().__init__(*pargs, **kwargs)
            # Asserted for a trainer that will roll out, which is what a run
            # is. Built without a rollout configuration it is a probe for
            # comparing two forward paths, and those comparisons want several
            # rows on purpose.
            if self.veribim:
                assert_one_row_per_micro_batch(
                    self.args.per_device_train_batch_size)

        def _logps(self, model, input_ids, attention_mask, keep,
                   temperature: Optional[float] = None):
            """Per-token log-probabilities for the last `keep` positions.

            One route, used by the policy, the reference and the guard alike,
            so all three quantities come from the same arithmetic.

            Unsloth's own log-probability function is not usable here: it
            left-packs the batch and so depends on batch composition, and it
            computes under no_grad, which is why its trainer takes the policy
            term from a fused kernel instead. This forward has neither
            property.

            The output projection runs in chunks under checkpointing. A full
            completion's logits are vocabulary-sized in float32 and reached
            6.8 GB on one rollout, which is the cost Unsloth's fused kernel
            exists to avoid; recomputing each chunk in the backward pass keeps
            the peak at one chunk instead.

            ``temperature`` divides the logits, as sampling did. It defaults to
            the run's own value; the one place that passes something else is the
            comparison against the sampling server, which reports its
            log-probabilities before any temperature is applied.
            """
            from torch.utils.checkpoint import checkpoint
            from trl.trainer.utils import selective_log_softmax

            scale = self.temperature if temperature is None else float(temperature)
            trunk = self._trunk(model)
            hidden = trunk(input_ids=input_ids, attention_mask=attention_mask,
                           use_cache=False).last_hidden_state
            # The position before a token is the one that predicts it.
            hidden = hidden[:, :-1, :][:, -keep:, :]
            targets = input_ids[:, -keep:]
            head = self.accelerator.unwrap_model(model).get_output_embeddings()
            chunk = max(1, int(self.veribim.get("logit_chunk", 512)))

            def piece(states, wanted):
                logits = head(states).float() / scale
                return selective_log_softmax(logits, wanted)

            out = []
            for start in range(0, keep, chunk):
                states = hidden[:, start:start + chunk, :]
                wanted = targets[:, start:start + chunk]
                if torch.is_grad_enabled() and states.requires_grad:
                    out.append(checkpoint(piece, states, wanted,
                                          use_reentrant=False))
                else:
                    out.append(piece(states, wanted))
            return torch.cat(out, dim=1)

        def _trunk(self, model):
            """The transformer under the causal-LM head, whatever wraps it."""
            if self._trunk_module is None:
                base = self.accelerator.unwrap_model(model)
                base = getattr(base, "get_base_model", lambda: base)()
                # The wrapper nests differently by architecture: this base is
                # a vision-language model, so the text trunk sits at
                # .model.language_model rather than .model.model.
                node = base
                for _ in range(6):
                    if hasattr(node, "embed_tokens"):
                        break
                    inner = None
                    for name in ("language_model", "text_model", "model"):
                        candidate = getattr(node, name, None)
                        if candidate is not None and hasattr(candidate, "forward"):
                            inner = candidate
                            break
                    if inner is None:
                        break
                    node = inner
                if not hasattr(node, "embed_tokens"):
                    raise AssertionError(
                        "could not find the transformer trunk under "
                        f"{type(base).__name__}; the chunked head needs its "
                        "last hidden state")
                self._trunk_module = node
            return self._trunk_module

        # -- attention uses every real token; gradient uses assistant tokens --
        def _get_per_token_logps_and_entropies(self, model, input_ids,
                                               attention_mask, logits_to_keep,
                                               *pargs, **kwargs):
            if (self._full_attention is not None
                    and self._full_attention.shape == attention_mask.shape):
                attention_mask = self._full_attention
            logps, entropies = super()._get_per_token_logps_and_entropies(
                model, input_ids, attention_mask, logits_to_keep, *pargs, **kwargs)
            # Hold every consumer to one width. Unsloth's replacement returns
            # `logits_to_keep + max_left_pad` positions, and its own fused loss
            # infers that offset from the reference tensor's shape, so a caller
            # that mixes the two widths subtracts misaligned windows.
            return (completion_window(logps, logits_to_keep),
                    completion_window(entropies, logits_to_keep))

        def _compute_loss(self, model, inputs):
            full = inputs.get("attention_completion_mask")
            if full is not None:
                self._full_attention = torch.cat([inputs["prompt_mask"], full], dim=1)
            try:
                if self.beta != 0.0 and "ref_per_token_logps" not in inputs:
                    inputs = dict(inputs)
                    inputs["ref_per_token_logps"] = self._micro_batch_reference(
                        model, inputs)
                return super()._compute_loss(model, inputs)
            finally:
                self._full_attention = None

        def _micro_batch_reference(self, model, inputs):
            """Reference log-probabilities for exactly this micro-batch."""
            ids = torch.cat([inputs["prompt_ids"], inputs["completion_ids"]], dim=1)
            mask = self._full_attention
            if mask is None:
                mask = torch.cat([inputs["prompt_mask"],
                                  inputs["completion_mask"]], dim=1)
            keep = inputs["completion_ids"].size(1)
            reference = completion_window(
                self._reference_logps(model, ids, mask, keep), keep)
            if not self._alignment_divergence_seen:
                self._assert_alignment(model, ids, mask, keep, reference,
                                       inputs["completion_mask"])
            return reference

        # -- the reference is dpo_v1, held as a frozen second adapter ---------
        def _reference_logps(self, model, input_ids, attention_mask, logits_to_keep,
                             adapter: str = REFERENCE_ADAPTER_NAME):
            base = self.accelerator.unwrap_model(model)
            base.set_adapter(adapter)
            try:
                with torch.no_grad():
                    logps = self._logps(model, input_ids, attention_mask,
                                        logits_to_keep)
            finally:
                base.set_adapter(POLICY_ADAPTER_NAME)
            return logps

        # -- rollouts ---------------------------------------------------------
        def _generate_and_score_completions(self, inputs):
            import torch.nn.functional as F

            cfg = self.veribim
            device = self.accelerator.device
            tokenizer = cfg["tokenizer"]
            pad_id = cfg["pad_id"]
            k = cfg["num_generations"]

            sync = cfg.get("sync")
            due = (self._synced_step < 0
                   or self.state.global_step % max(1, cfg.get("sync_every", 1)) == 0)
            if sync is not None and due and self.state.global_step != self._synced_step:
                pushed = sync.push(self.accelerator.unwrap_model(self.model),
                                   self.processing_class, self.state.global_step)
                self._synced_step = self.state.global_step
                cfg["client"].model = pushed["name"]
                print(f"[sync] step {self.state.global_step} -> {pushed['name']} "
                      f"({pushed['seconds']}s, template "
                      f"{'ok' if pushed.get('template_matches') else 'MISMATCH'})",
                      flush=True)

            unique: list[dict] = []
            seen: set[str] = set()
            for row in inputs:
                if row["task_id"] in seen:
                    continue
                seen.add(row["task_id"])
                unique.append(cfg["tasks"][row["task_id"]])

            # Groups may run concurrently against the server. Ordering is
            # preserved because `map` returns in input order, and only the
            # rollouts are parallel: encoding and the advantage bookkeeping
            # stay sequential, where order decides which reward belongs to
            # which group.
            parallel = max(1, int(cfg.get("group_parallel", 1)))
            roll = cfg.get("rollout_group") or rollout_group
            encode = cfg.get("encode_group") or encode_group
            count_tokens = cfg.get("count_tokens")
            # One group of the batch is asked for the server's own
            # log-probabilities, so the trainer's arithmetic can be held against
            # the sampler's once. When that group cannot be compared (it scored
            # flat and was skipped, or nothing of it encoded) the next batch
            # asks again, up to LOGPROB_CHECK_ATTEMPTS times.
            check_logprobs = (bool(cfg.get("logprob_check"))
                              and not self._logprob_check_done and bool(unique))
            first_task_id = unique[0]["task_id"] if unique else None

            def produce(task):
                try:
                    return task, roll(
                        task, k, cfg["client"], cfg["agent"], cfg["work_root"],
                        paths.PROJECT_ROOT, cfg["gold_cache_dir"],
                        count_tokens=count_tokens,
                        request_logprobs=(check_logprobs
                                          and task["task_id"] == first_task_id)), None
                except Exception as exc:  # noqa: BLE001
                    # One group failing must not discard the others' rollouts,
                    # which cost minutes each.
                    return task, None, f"{type(exc).__name__}: {exc}"[:160]

            if parallel > 1 and len(unique) > 1:
                with ThreadPoolExecutor(
                        max_workers=min(parallel, len(unique))) as pool:
                    produced = list(pool.map(produce, unique))
            else:
                produced = [produce(task) for task in unique]

            # A small deduction per tool call that raised, so that among
            # trajectories reaching the same file the cleaner one ranks higher.
            # It is applied after the verifier scored, and the verifier's own
            # value is kept on the rollout for the log.
            penalty = float(cfg.get("error_penalty") or 0.0)
            if penalty > 0:
                for _, g, f in produced:
                    for r in (g or []):
                        r.apply_error_penalty(penalty, cfg["error_penalty_cap"])

            # Off unless the run asked for it. The repeat
            # deduction is applied after the per-error one because they measure
            # different things and both are meant to bind; the commit gate is
            # applied last because it overrides the value rather than reducing
            # it. Each keeps the verifier's own number on `reward_raw`, so the
            # skip rule below still reads the verifier and not the shaping.
            repeat_penalty = float(cfg.get("repeat_penalty") or 0.0)
            commit_required = str(cfg.get("commit_required") or "off")
            if repeat_penalty > 0 or commit_required != "off":
                for task_row, g, f in produced:
                    for r in (g or []):
                        if repeat_penalty > 0:
                            r.apply_repeat_penalty(
                                repeat_penalty, cfg["repeat_penalty_cap"])
                        r.apply_commit_gate(task_row.get("operation", ""),
                                            commit_required)

            # A group whose rollouts all scored the same contributes no
            # gradient and is skipped. When EVERY group in the batch is flat
            # there is nothing left to skip to, so they are kept: the step
            # becomes a no-op through the centred advantages, which is what it
            # would have been anyway, and the trainer keeps its footing
            # instead of failing on an empty batch.
            live = [g for _, g, f in produced if f is None and g]

            def flat(group) -> bool:
                if max(r.reward for r in group) - min(r.reward for r in group) < 1e-9:
                    return True
                # With the deduction on, a group the verifier scored flat at
                # or below the no-op level carries no information about the
                # task; training it would only reward doing less. It stays
                # skipped. A group flat at a positive level is trained on the
                # deduction alone (solve it, and solve it cleanly).
                raw = [r.reward_raw if r.reward_raw is not None else r.reward for r in group]
                return max(raw) - min(raw) < 1e-9 and max(raw) <= 0.0

            every_group_flat = bool(live) and all(flat(g) for g in live)
            if every_group_flat:
                print("[skip] every group in this batch is flat; keeping them "
                      "so the step is a no-op rather than an empty batch",
                      flush=True)
                # A kept group the verifier scored flat must stay flat, or the
                # no-op step would train on the deduction of a group the rule
                # above excludes.
                for g in live:
                    raw = [r.reward_raw if r.reward_raw is not None else r.reward for r in g]
                    if max(raw) - min(raw) < 1e-9:
                        for r in g:
                            if r.reward_raw is not None:
                                r.reward = r.reward_raw

            prompts, completions, masks, attn, rewards = [], [], [], [], []
            group_sizes: list[int] = []
            groups_flat = 0
            groups_skipped_encoder = 0
            logprob_material: Optional[tuple] = None
            # One encoded row, kept in case every group of the batch is
            # skipped. See the no-op step below.
            spare_row: Optional[tuple] = None
            for task, group, failure in produced:
                if failure is not None:
                    self._rollout_log.append({"step": self.state.global_step,
                                              "task_id": task["task_id"],
                                              "skipped": failure})
                    print(f"[rollout] {task['task_id']} failed: {failure}",
                          flush=True)
                    continue
                spread = [r.reward for r in group]
                if spread and flat(group) and not every_group_flat:
                    # Advantages are centred within a group, so a group whose
                    # rollouts all scored the same contributes exactly zero
                    # gradient. Skipping it before encoding saves the work and
                    # makes the batch's real yield visible in the log.
                    self._rollout_log.append({
                        "step": self.state.global_step, "task_id": task["task_id"],
                        "skipped": "zero reward variance",
                        "reward": round(spread[0], 6), "n": len(spread),
                        "reward_raw": round(group[0].reward_raw, 6)
                        if group[0].reward_raw is not None else None})
                    print(f"[skip] {task['task_id']}: all {len(spread)} rollouts "
                          f"scored {spread[0]:.4f}, no gradient in this group",
                          flush=True)
                    groups_flat += 1
                    continue
                encoded = encode(tokenizer, task, group, cfg["tools"],
                                 cfg["max_seq"])
                if check_logprobs and task["task_id"] == first_task_id:
                    logprob_material = (task, group, encoded)
                usable = [e for e in encoded["rollouts"] if "error" not in e]
                dropped = [e["error"] for e in encoded["rollouts"] if "error" in e]
                # Lengths are recorded here, before any decision to skip, so
                # the step's length statistics describe the batch that ran
                # rather than the batch that survived. A group dropped for a
                # rollout the encoder could not take is exactly the group whose
                # length the transcript budget has to be set from, and filling
                # the lengths after the skip would leave that group blank.
                by_index = {r.index: r for r in group}
                for entry in encoded["rollouts"]:
                    rollout = by_index.get(entry.get("index"))
                    if rollout is None:
                        continue
                    rollout.transcript_tokens = (
                        entry.get("tokens") if "error" in entry
                        else len(encoded["prompt_ids"]) + len(entry["completion_ids"]))
                if spare_row is None and encoded["prompt_ids"] and usable:
                    spare_row = (encoded["prompt_ids"], usable[0]["completion_ids"])
                    self._last_encoded_row = spare_row
                    self._batches_encoding_nothing = 0
                if dropped:
                    # Which rollouts the encoder threw away, and why. Without
                    # this a group that yields 3 of 16 looks like a group that
                    # only ran 3, and the rollouts lost are the long ones,
                    # which are the ones carrying the reward spread.
                    print(f"[encode] {task['task_id']}: kept {len(usable)} of "
                          f"{len(encoded['rollouts'])}, dropped "
                          f"{dict(Counter(dropped))}", flush=True)
                    # And then the whole group goes, not just the rollouts the
                    # encoder lost. Training on what survived would train on a
                    # group whose worst trajectories were removed after they
                    # were scored, which shifts every advantage in it; the
                    # transcript budget is what stops this happening at all, so
                    # a healthy run reports zero here.
                    lengths = [r.transcript_tokens for r in group
                               if r.transcript_tokens is not None]
                    self._rollout_log.append({
                        "step": self.state.global_step, "task_id": task["task_id"],
                        "skipped": "encoder error", "errors": dict(Counter(dropped)),
                        "max_transcript_tokens": max(lengths) if lengths else None})
                    print(f"[skip] {task['task_id']}: {len(dropped)} of "
                          f"{len(encoded['rollouts'])} rollouts did not encode, "
                          f"longest {max(lengths) if lengths else 'unknown'} "
                          "tokens, dropping the whole group", flush=True)
                    groups_skipped_encoder += 1
                    continue
                if len(usable) < 2:
                    # A group with fewer than two usable rollouts has no spread
                    # for an advantage to be computed from.
                    self._rollout_log.append({"step": self.state.global_step,
                                              "task_id": task["task_id"],
                                              "skipped": "fewer than two usable rollouts",
                                              "encoded": len(usable)})
                    continue
                group_rewards = [e["reward"] for e in usable]
                if (max(group_rewards) - min(group_rewards) < 1e-9
                        and not every_group_flat):
                    # A guard rather than a rule: with every rollout of the
                    # group encoded, this is the same spread the check above
                    # already made. It stays because the two would part company
                    # again the moment encoding could drop a rollout.
                    self._rollout_log.append({
                        "step": self.state.global_step, "task_id": task["task_id"],
                        "skipped": "flat after encoding",
                        "reward": round(group_rewards[0], 6), "n": len(usable)})
                    print(f"[skip] {task['task_id']}: all {len(usable)} encoded "
                          f"rollouts scored {group_rewards[0]:.4f}", flush=True)
                    groups_flat += 1
                    continue
                for entry in usable:
                    prompts.append(encoded["prompt_ids"])
                    completions.append(entry["completion_ids"])
                    masks.append(entry["completion_mask"])
                    attn.append([1] * len(entry["completion_ids"]))
                    rewards.append(entry["reward"])
                group_sizes.append(len(usable))
                self._rollout_log.append({
                    "step": self.state.global_step,
                    "task_id": task["task_id"], "operation": task["operation"],
                    "n": len(usable),
                    "dropped": len(encoded["rollouts"]) - len(usable),
                    "reward_mean": sum(group_rewards) / len(group_rewards),
                    "reward_max": max(group_rewards),
                    "reward_raw_mean": (sum(r.reward_raw for r in group) / len(group)
                                        if group[0].reward_raw is not None else None),
                    "commit_rate": sum(1 for r in group if r.commits > 0) / len(group),
                    "raised_calls": sum(r.raised_calls for r in group),
                    "repeat_failures": sum(r.repeat_failures for r in group),
                    "commit_gated": sum(1 for r in group if r.commit_gated),
                    "tool_calls": sum(r.tool_calls for r in group),
                    "mean_rounds": sum(r.tool_rounds for r in group) / len(group),
                    "stats": [r.stats() for r in group],
                })
            noop_step = not prompts
            if noop_step:
                # Every group was skipped. Dropping a whole group on an encoder
                # error made this reachable in ordinary running: a batch of flat
                # groups and lost groups leaves nothing to train on, and ending
                # the run here would throw away the optimizer state and every
                # rollout of the step over one bad batch. The step is taken as a
                # no-op instead, on one encoded row whose gradient mask is zero,
                # which is the same nothing the flat-batch path already takes.
                # The row comes from this batch when the batch encoded
                # anything, from an earlier step when it did not, and from the
                # padding token when no step has encoded yet. A batch can leave
                # nothing behind for two ordinary reasons: every rollout of
                # every group was refused by the encoder, and every group
                # failed at rollout, which is what a sampling server that has
                # gone away looks like. Neither is worth ending the run for
                # once, and `no_usable_groups` in the step summary says it
                # happened. EMPTY_BATCH_LIMIT such batches in a row is the
                # server staying away, and the run stops there.
                if spare_row is None:
                    self._batches_encoding_nothing += 1
                    if self._batches_encoding_nothing >= EMPTY_BATCH_LIMIT:
                        raise RuntimeError(
                            f"{EMPTY_BATCH_LIMIT} generation batches in a row "
                            "encoded nothing; the sampling server has not "
                            "answered, stopping the run")
                    spare_row = self._last_encoded_row or ([pad_id], [pad_id])
                print("[skip] no group in this batch carried gradient; the "
                      "step is a no-op", flush=True)
                self._rollout_log.append(
                    {"step": self.state.global_step,
                     "skipped": "no group carried gradient"})
                prompts.append(list(spare_row[0]))
                completions.append(list(spare_row[1]))
                masks.append([0] * len(spare_row[1]))
                attn.append([1] * len(spare_row[1]))
                rewards.append(0.0)
                group_sizes.append(1)

            def pad_left(rows, value):
                width = max(len(r) for r in rows)
                return torch.tensor([[value] * (width - len(r)) + list(r) for r in rows],
                                    device=device)

            def pad_right(rows, value):
                width = max(len(r) for r in rows)
                return torch.tensor([list(r) + [value] * (width - len(r)) for r in rows],
                                    device=device)

            prompt_ids = pad_left(prompts, pad_id)
            prompt_mask = pad_left([[1] * len(p) for p in prompts], 0)
            completion_ids = pad_right(completions, pad_id)
            completion_mask = pad_right(masks, 0)          # gradient: assistant only
            attention_completion = pad_right(attn, 0)      # attention: every real token

            reward_t = torch.tensor(rewards, dtype=torch.float32, device=device)
            # Advantages are computed inside each task's own group, which is what
            # GRPO compares: a rollout is good or bad relative to its siblings on
            # the same task, never against a different task's difficulty.
            advantages = torch.zeros_like(reward_t)
            # What the centred reward is divided by. Its own group's spread is
            # standard GRPO. The batch's spread keeps the relative sizes of the
            # groups, so a group whose rollouts barely differ takes a smaller
            # step than one whose rollouts differ a lot. Dividing by nothing is
            # the Dr. GRPO form and leaves the reward's own scale in place.
            scaling = self.scale_rewards
            batch_std = reward_t.std(unbiased=False) if scaling == "batch" else None
            start = 0
            for size in group_sizes:
                chunk = reward_t[start:start + size]
                centred = chunk - chunk.mean()
                if scaling in (True, "group"):
                    centred = centred / (chunk.std(unbiased=False) + 1e-4)
                elif scaling == "batch":
                    centred = centred / (batch_std + 1e-4)
                advantages[start:start + size] = centred
                start += size
            assert start == len(rewards), "group sizes do not cover the batch"

            # TRL slices the prepared batch back into micro-batches by fixed
            # arithmetic; fewer usable rollouts than the generation batch size
            # yields an EMPTY final slice (bsz=0 inside the compiled loss).
            # Pad with zero-gradient copies: advantage 0 AND completion_mask 0,
            # so they satisfy the arithmetic and contribute nothing.
            expected = len(inputs)
            n_real = len(prompts)
            if n_real < expected:
                pad = expected - n_real
                for j in range(pad):
                    src = j % n_real
                    prompts.append(prompts[src])
                    completions.append(completions[src])
                    masks.append([0] * len(masks[src]))
                    attn.append(attn[src])
                    rewards.append(0.0)
                advantages = torch.cat(
                    [advantages, torch.zeros(pad, device=device)])
                prompt_ids = pad_left(prompts, pad_id)
                prompt_mask = pad_left([[1] * len(p) for p in prompts], 0)
                completion_ids = pad_right(completions, pad_id)
                completion_mask = pad_right(masks, 0)
                attention_completion = pad_right(attn, 0)
                self._rollout_log.append({"step": self.state.global_step,
                                          "padded_zero_gradient": pad,
                                          "real": 0 if noop_step else n_real,
                                          "expected": expected})

            informative = 0 if noop_step else len(group_sizes)
            real = 0 if noop_step else n_real
            self._rollout_log.append(self._step_summary(
                produced, groups_flat, groups_skipped_encoder, informative,
                real, max(0, expected - real), advantages[:real],
                no_usable_groups=noop_step))

            if check_logprobs:
                # The check is a reading, not a gate: an exception is printed
                # and the step goes on. It is done once a comparison has been
                # made over at least one token, or once LOGPROB_CHECK_ATTEMPTS
                # batches have failed to produce a comparable group.
                self._logprob_check_attempts += 1
                compared = False
                if logprob_material is not None:
                    try:
                        report = self._compare_logprobs(*logprob_material)
                        compared = bool(report.get("n_tokens"))
                    except Exception as exc:  # noqa: BLE001 - a check, not a gate
                        print(f"[logprob-check] not completed: "
                              f"{type(exc).__name__}: {exc}", flush=True)
                else:
                    print("[logprob-check] the group it was asked of did not "
                          "survive to the comparison", flush=True)
                exhausted = self._logprob_check_attempts >= LOGPROB_CHECK_ATTEMPTS
                self._logprob_check_done = compared or exhausted
                if not compared:
                    print("[logprob-check] " + (
                        f"giving up after {self._logprob_check_attempts} batches"
                        if exhausted else "asking again on the next batch"),
                        flush=True)

            out = {
                "prompt_ids": prompt_ids,
                "prompt_mask": prompt_mask,
                "completion_ids": completion_ids,
                "completion_mask": completion_mask,
                "attention_completion_mask": attention_completion,
                "advantages": advantages,
                # 0-dim tensor: TRL's split_tensor_dict calls .ndim on every
                # value and passes 0-dim entries through whole.
                "num_items_in_batch": completion_mask.sum().to(device),
            }
            # The reference has to travel in this dict. Unsloth's compiled
            # trainer defines its own `compute_loss`, which supersedes TRL's
            # `_compute_loss`, and it reads the reference from
            # `inputs["ref_per_token_logps"]` and nowhere else. It is still
            # computed one micro-batch at a time, because Unsloth's
            # log-probability function left-packs the rows using a batch-wide
            # maximum and so gives a different answer for a 32-row call than
            # for the 1-row call the loss will make.
            if self.beta != 0.0:
                out["ref_per_token_logps"] = self._reference_per_micro_batch(
                    prompt_ids, prompt_mask, completion_ids,
                    attention_completion, completion_mask)
            return out

        def _step_summary(self, produced, groups_flat, groups_skipped_encoder,
                          groups_informative, real_rows, padded_rows,
                          advantages, no_usable_groups: bool = False) -> dict:
            """One row per step saying what the generation batch actually gave.

            The per-group rows say what each task produced; this says what the
            step as a whole produced, which is the number that decides whether
            the run is worth continuing: how many groups carried gradient, how
            the trajectories stopped, and how long they ran. The lengths cover
            every rollout the encoder measured, the ones it then refused
            included, because those are the lengths the transcript budget has
            to be set from.
            """
            rollouts = [r for _, group, failure in produced
                        if failure is None and group for r in group]
            stops = Counter(r.stop_reason for r in rollouts)
            n = len(rollouts) or 1
            lengths = [r.transcript_tokens for r in rollouts
                       if r.transcript_tokens is not None]
            gold = [r.gold_keys_written for r in rollouts
                    if r.gold_keys_written is not None]
            return {
                # Stamped here rather than by the log writer, which runs after
                # the step counter has already moved on: without it this row
                # would carry the next step's number while the skip rows of the
                # same batch carry this one's.
                "step": self.state.global_step,
                "step_summary": True,
                "groups_run": len(produced),
                "groups_informative": groups_informative,
                "groups_flat": groups_flat,
                "groups_skipped_encoder": groups_skipped_encoder,
                # True when the step trained on nothing because every group was
                # flat, lost at encoding, or failed to roll out. The step is
                # still taken, on one row whose gradient mask is zero.
                "no_usable_groups": bool(no_usable_groups),
                "real_rows": real_rows,
                "padded_rows": padded_rows,
                "mean_abs_advantage": (float(advantages.abs().mean().item())
                                       if advantages.numel() else 0.0),
                "stop_reasons": dict(stops),
                "mean_rounds": (sum(r.tool_rounds for r in rollouts) / n
                                if rollouts else 0.0),
                "share_duplicate_loop": stops.get("duplicate_loop", 0) / n,
                "share_token_budget": stops.get("token_budget", 0) / n,
                "share_budget_exhausted": stops.get("budget_exhausted", 0) / n,
                "mean_transcript_tokens": (sum(lengths) / len(lengths)
                                           if lengths else None),
                "max_transcript_tokens": max(lengths) if lengths else None,
                "mean_gold_keys_written": (sum(gold) / len(gold) if gold else None),
                "mean_distinct_guids": (sum(r.distinct_guids for r in rollouts) / n
                                        if rollouts else 0.0),
            }

        def _compare_logprobs(self, task, group, encoded) -> dict:
            """Hold the sampling server's log-probabilities against our own.

            The server reports them before temperature and top-p are applied, so
            the comparison is made at temperature 1. Anything but a small
            difference means the trainer is scoring a different rendering of the
            transcript than the one the tokens were sampled from, which no loss
            curve would show. It runs once, on one group of the first batch.
            """
            prompt_ids = encoded["prompt_ids"]
            by_index = {r.index: r for r in group}
            rows: list[dict] = []
            gaps: list[float] = []
            for entry in encoded["rollouts"]:
                if "error" in entry:
                    continue
                rollout = by_index.get(entry["index"])
                if rollout is None or not rollout.turn_logprobs:
                    continue
                ids = torch.tensor([list(prompt_ids) + list(entry["completion_ids"])],
                                   device=self.accelerator.device)
                attention = torch.ones_like(ids)
                keep = len(entry["completion_ids"])
                with torch.no_grad():
                    ours = completion_window(
                        self._logps(self.model, ids, attention, keep,
                                    temperature=1.0), keep)
                mask = torch.tensor(entry["completion_mask"],
                                    device=ours.device, dtype=torch.bool)
                mine = ours[0][mask].float().tolist()
                theirs = [value for turn in rollout.turn_logprobs for value in turn]
                shared = min(len(mine), len(theirs))
                deltas = [abs(a - b) for a, b in zip(mine[:shared], theirs[:shared])]
                gaps.extend(deltas)
                rows.append({"index": entry["index"], "trainer_tokens": len(mine),
                             "server_tokens": len(theirs), "compared": shared,
                             "mean_abs": (sum(deltas) / len(deltas)) if deltas else None})
                if len(mine) != len(theirs):
                    print(f"[logprob-check] rollout {entry['index']}: "
                          f"{len(mine)} trainer tokens against {len(theirs)} from "
                          "the server; comparing the common prefix", flush=True)
            ordered = sorted(gaps)
            mean_gap = (sum(gaps) / len(gaps)) if gaps else None
            p99 = ordered[min(len(ordered) - 1, int(0.99 * len(ordered)))] if ordered else None
            report = {"task_id": task["task_id"], "temperature": 1.0,
                      "n_tokens": len(gaps), "mean_abs": mean_gap,
                      "p99_abs": p99, "rollouts": rows}
            if mean_gap is None:
                print("[logprob-check] no rollout carried the server's "
                      "log-probabilities", flush=True)
            else:
                print(f"[logprob-check] mean|d| = {mean_gap:.4f} nats "
                      f"(warn > 0.05), p99|d| = {p99:.4f}, over {len(gaps)} "
                      "tokens", flush=True)
                if mean_gap > 0.05:
                    print("[logprob-check] the sampler and the trainer disagree "
                          "by more than 0.05 nats per token; the transcript the "
                          "trainer encodes is not the one that was sampled",
                          flush=True)
            run_dir = self.veribim.get("run_dir")
            if run_dir is not None:
                (Path(run_dir) / "logprob_check.json").write_text(
                    json.dumps(report, indent=2), encoding="utf-8")
            return report

        def compute_loss(self, model, inputs, return_outputs=False,
                         num_items_in_batch=None):
            """The GRPO loss, computed on the route the guard validates.

            Unsloth's compiled trainer supplies its own `compute_loss` whose
            policy term comes from a fused kernel that never returns through
            `_get_per_token_logps_and_entropies`. That kernel is not wrong
            about the reference (measured: it reproduces a known KL to within
            12%), but the log-probabilities underneath it shift by more than a
            nat with batch composition, and the guard cannot see them. Since
            the reference, the policy and the guard must agree for the KL to
            mean anything, all three are computed here by one route.

            The arithmetic is standard GRPO: a clipped importance ratio against
            the sampling policy, the group-centred advantage, and the k3 KL
            against the frozen reference. The ratio is identically 1 here,
            because there is one optimizer pass per generation batch and the
            sampling log-probabilities are never carried in, so the clipping is
            inert and `clip_fraction` is logged to prove it.

            The normalisation is token level over the whole generation batch:
            the summed loss of this micro-batch divided by the number of tokens
            the batch as a whole gives gradient to. Dividing per row instead
            made a step's size depend on how many rollouts happened to survive
            encoding, so two batches with the same gradient per token took
            different-sized steps.
            """
            if return_outputs:
                raise ValueError("Stage C does not return outputs from the loss")
            prompt_ids, prompt_mask = inputs["prompt_ids"], inputs["prompt_mask"]
            completion_ids = inputs["completion_ids"]
            gradient_mask = inputs["completion_mask"]
            attention_completion = inputs.get("attention_completion_mask",
                                              gradient_mask)
            mode = "train" if self.model.training else "eval"
            metrics = self._metrics[mode]
            real_rows = float((gradient_mask.sum(dim=1) > 0).sum().item())
            # Counted per micro-batch and averaged by the logger, so with one
            # row per micro-batch this reads as the share of micro-batches in
            # the step that carried a real rollout rather than a padded copy.
            # The step summary reports the same two quantities over the step as
            # a whole, as a count and over the real rows only; the names differ
            # here so that a run record cannot be read as if they agreed.
            metrics.setdefault("real_row_share", []).append(real_rows)
            metrics.setdefault("mean_abs_advantage_incl_padding", []).append(
                inputs["advantages"].abs().mean().item())
            if real_rows == 0:
                # A padded copy. Its summed loss is exactly zero under the
                # token-level normalisation and so is its gradient, so the
                # forward buys nothing. Every trainable parameter still enters
                # the returned value, at weight zero, so the backward pass has
                # a graph to walk.
                zero = sum(p.sum() for p in model.parameters() if p.requires_grad)
                return zero * 0.0

            keep = completion_ids.size(1)
            input_ids = torch.cat([prompt_ids, completion_ids], dim=1)
            attention = torch.cat([prompt_mask, attention_completion], dim=1)
            input_ids, attention = trim_left(input_ids, attention)

            logps = self._logps(model, input_ids, attention, keep)
            entropies = None

            old = inputs.get("old_per_token_logps")
            old = logps.detach() if old is None else completion_window(old, keep)
            advantages = inputs["advantages"].unsqueeze(1)
            ratio = torch.exp(logps - old)
            low = getattr(self, "epsilon_low", getattr(self, "epsilon", 0.2))
            high = getattr(self, "epsilon_high", low)
            clipped = torch.clamp(ratio, 1.0 - low, 1.0 + high)
            per_token_loss = -torch.min(ratio * advantages, clipped * advantages)

            mean_kl = None
            if self.beta != 0.0:
                reference = completion_window(inputs["ref_per_token_logps"], keep)
                gap = reference - logps
                per_token_kl = torch.exp(gap) - gap - 1
                per_token_loss = per_token_loss + self.beta * per_token_kl
                mean_kl = ((per_token_kl * gradient_mask).sum()
                           / gradient_mask.sum().clamp(min=1.0))

            # The denominator is the whole generation batch's real token count,
            # the same number for every micro-batch of the step, so the summed
            # micro-batch losses reconstruct the batch's token-level loss
            # exactly. Padded rows contribute nothing to it.
            num_items = inputs.get("num_items_in_batch")
            if num_items is None:
                num_items = gradient_mask.sum()
            num_items = torch.as_tensor(num_items, dtype=per_token_loss.dtype,
                                        device=per_token_loss.device)
            loss = ((per_token_loss * gradient_mask).sum()
                    / num_items.clamp(min=1.0))

            clipped_tokens = (((ratio < 1.0 - low) | (ratio > 1.0 + high))
                              & (gradient_mask > 0))
            # Averaged over the micro-batches that carried a real rollout: a
            # padded copy returns above, and it has no masked token to clip.
            metrics.setdefault("clip_fraction", []).append(
                (clipped_tokens.sum() / gradient_mask.sum().clamp(min=1)).item())
            if mean_kl is not None:
                metrics.setdefault("kl", []).append(
                    self.accelerator.gather(mean_kl).nanmean().item())
            if entropies is not None:
                entropies = completion_window(entropies, keep)
                masked_entropy = ((entropies * gradient_mask).sum()
                                  / gradient_mask.sum().clamp(min=1.0))
                metrics.setdefault("entropy", []).append(
                    self.accelerator.gather(masked_entropy).nanmean().item())
            metrics.setdefault("completion_length", []).append(
                gradient_mask.sum(dim=1).float().mean().item())
            # Returned undivided. The accelerator divides it by the accumulation
            # count inside `backward`, and nothing else does, so one step's
            # accumulated gradient is the batch's own token-level gradient times
            # MEASURED_GRAD_FACTOR. That constant is the same for every batch,
            # which is the property the per-row mean did not have, and Adam
            # removes it from the step size.
            return loss

        def _reference_per_micro_batch(self, prompt_ids, prompt_mask,
                                       completion_ids, attention_completion,
                                       gradient_mask):
            """Reference log-probabilities, in the slices the loss will use."""
            keep = completion_ids.size(1)
            micro = max(1, int(self.args.per_device_train_batch_size))
            pieces = []
            for start in range(0, prompt_ids.size(0), micro):
                stop = start + micro
                ids = torch.cat([prompt_ids[start:stop],
                                 completion_ids[start:stop]], dim=1)
                mask = torch.cat([prompt_mask[start:stop],
                                  attention_completion[start:stop]], dim=1)
                # Trimmed in the same slices the loss will use, so both
                # forwards see the same input and their difference stays a KL
                # rather than a difference in how much padding each was given.
                ids, mask = trim_left(ids, mask)
                # The width is a contract, not a detail. Unsloth's fused loss
                # reads `max_left_pad = ref_logps.shape[1] - logits_to_keep`,
                # so a reference `keep` wide pins its window to the completion
                # exactly. The original fault was a reference computed on all
                # 32 rows, which came back `keep + 3` wide and told the loss to
                # score a window starting three tokens inside the prompt.
                piece = completion_window(
                    self._reference_logps(self.model, ids, mask, keep), keep)
                pieces.append(piece)
                if not self._alignment_divergence_seen and start == 0:
                    # Checked every step until the policy has actually moved,
                    # not only at step 0. While the two adapters hold the same
                    # weights any fault in a third quantity is invisible,
                    # because two of three being equal makes the difference
                    # zero; that is what let a wrong KL survive to step 3.
                    self._assert_alignment(self.model, ids, mask, keep, piece,
                                           gradient_mask[start:stop])
            reference = torch.cat(pieces, dim=0)
            if reference.shape != completion_ids.shape:
                raise AssertionError(
                    f"reference log-probabilities came back {tuple(reference.shape)}, "
                    f"but the completions are {tuple(completion_ids.shape)}; the "
                    "loss would subtract misaligned tensors")
            return reference

        def _assert_alignment(self, model, ids, full, keep, reference, gradient_mask):
            """At the first step the two adapters are the same weights.

            Both are loaded from dpo_v1 and its LoRA dropout is 0.0, so the KL
            between them is zero by construction and any other value is an
            arithmetic fault rather than a difference between two
            distributions. Checking it here costs one forward pass once, and
            turns a wrong KL into an immediate abort instead of a loss curve
            nobody can interpret.
            """
            # Gate on the mean, not the maximum. On this architecture (24 of
            # the 32 layers use recurrent linear attention) a bfloat16 forward
            # depends slightly on batch size, which puts the maximum over a
            # single low-probability token at a few nats even when everything
            # is correct; the measured mean floor is about 0.1. The fault this
            # guards against was about 13 nats per token.
            tolerance = self.veribim.get("alignment_tolerance", 1.0)
            with torch.no_grad():
                policy = self._logps(model, ids, full, keep)
            delta = (reference - policy) * gradient_mask
            worst = delta.abs().max().item()
            count = gradient_mask.sum().clamp(min=1)
            mean = (delta.sum() / count).item()
            moved = worst > 1e-9
            print(f"[alignment] reference vs policy at step "
                  f"{self.state.global_step}: max|d|={worst:.3e} mean={mean:+.3e}"
                  f"{' (policy has moved)' if moved else ' (weights still equal)'}",
                  flush=True)
            if moved:
                # The first step that separates the two adapters is the only
                # one that can expose a fault in how the loss consumes the
                # reference. After it, stop paying for the extra forward.
                self._alignment_divergence_seen = True
            if abs(mean) > tolerance:
                raise RuntimeError(
                    "the reference and the policy disagree at the first step, "
                    f"by {abs(mean):.3f} nats per token on average, up to "
                    f"{worst:.3f} (tolerance "
                    f"{tolerance}). They are the same weights here, so this is "
                    "a computation misalignment, not a KL. Run "
                    "`python -m stage_c.align_test` to localise it.")

    return VeriBIMGRPOTrainer


# --------------------------------------------------------------- callbacks

def _build_callbacks():
    import subprocess

    import torch
    from transformers import TrainerCallback

    class VramSlopeCallback(TrainerCallback):
        """Assert the dry run's finding still holds: memory must not creep.

        The dry run cleared Unsloth issue #3864 over 500 steps. A positive slope in
        the opening steps means it has come back, and a run that dies of it at
        step 250 wastes far more than one that refuses at step 50.
        """

        def __init__(self, out_file: Path, window: int, ceiling_mib: int,
                     abort_on_creep: bool = True) -> None:
            self.out_file = Path(out_file)
            self.window = window
            self.ceiling_mib = ceiling_mib
            self.abort_on_creep = abort_on_creep
            self.rows: list[dict] = []

        def _used(self) -> int:
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-compute-apps=pid,used_memory",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, check=False).stdout
                for line in out.strip().split("\n"):
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) == 2 and parts[0].isdigit() and int(parts[0]) == os.getpid():
                        return int(parts[1])
            except Exception:  # noqa: BLE001
                pass
            return int(torch.cuda.memory_reserved() / 2 ** 20)

        def _device_used(self) -> int:
            """Whole-card usage: the trainer shares it with the sampling server."""
            try:
                out = subprocess.run(
                    ["nvidia-smi", "--query-gpu=memory.used",
                     "--format=csv,noheader,nounits"],
                    capture_output=True, text=True, check=False).stdout
                return int(out.strip().split("\n")[0])
            except Exception:  # noqa: BLE001
                return -1

        def on_step_end(self, args, state, control, **kwargs):
            step = state.global_step
            if not step:
                return control
            row = {"step": step, "our_mib": self._used(),
                   "device_mib": self._device_used(),
                   "torch_reserved_mib": int(torch.cuda.memory_reserved() / 2 ** 20)}
            self.rows.append(row)
            with self.out_file.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            if row["our_mib"] > self.ceiling_mib:
                print(f"VRAM {row['our_mib']} MiB over the {self.ceiling_mib} ceiling",
                      flush=True)
                control.should_training_stop = True
            if step == self.window and len(self.rows) >= 10:
                # Fit the steady state only: the first steps ramp as caches
                # and buffers fill, and including them reports a positive
                # slope on a run that has long since flattened (this guard
                # false-stopped grpo_v1 at step 50 on +3.57 MiB/step while
                # steps 48-50 sat at identical readings).
                steady = [r for r in self.rows if r["step"] > self.window // 3]
                xs = [r["step"] for r in steady]
                ys = [r["torch_reserved_mib"] for r in steady]
                n = len(xs)
                mx, my = sum(xs) / n, sum(ys) / n
                sxx = sum((x - mx) ** 2 for x in xs)
                slope = (sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
                         if sxx else 0.0)
                print(f"VRAM slope over the first {self.window} steps: "
                      f"{slope:+.2f} MiB/step", flush=True)
                if slope > 1.0:
                    # Warn only. Reserved memory rises in stochastic STAIRS as
                    # longer batches set new high-water marks, then plateaus —
                    # a slope fit reads the stair edge as creep and has now
                    # false-stopped two runs. The absolute
                    # ceiling check above is the real leak protection.
                    print("VRAM slope positive; warning only — the ceiling "
                          "check is the binding guard", flush=True)
            return control

    class SnapshotCallback(TrainerCallback):
        """Write an adapter every N steps, with its template asserted.

        It also reports how far the policy has moved from the anchor, on its own
        interval. The distance is the reason a KL coefficient is set at all, and
        reading it from the live parameters means it is available on every step
        rather than only where a snapshot happens to land.
        """

        def __init__(self, model, tokenizer, out_dir: Path, every: int,
                     drift_every: int = 0) -> None:
            self.model = model
            self.tokenizer = tokenizer
            self.out_dir = Path(out_dir)
            self.every = every
            self.drift_every = drift_every
            self.written: list[str] = []

        def _write(self, step: int) -> None:
            from stage_a.chat_format import save_adapter

            target = self.out_dir / "snapshots" / f"step_{step}"
            save_adapter(self.model, self.tokenizer, target,
                         adapter_name=POLICY_ADAPTER_NAME)
            self.written.append(str(target))
            print(f"[snapshot] step {step} -> {target}", flush=True)

        def _drift(self, step: int) -> None:
            row: dict = {"step": step}
            try:
                value, pairs = adapter_drift(self.model)
            except ValueError as exc:
                # An instrument that cannot read the adapters is reported as
                # unreadable and does not end a run that is otherwise fine.
                row.update({"drift_rel_l2": None, "lora_pairs": 0,
                            "error": str(exc)})
                print(f"[drift] step {step} unreadable: {exc}", flush=True)
            else:
                row.update({"drift_rel_l2": value, "lora_pairs": pairs})
                print(f"[drift] step {step} relL2={value:.4e} over {pairs} "
                      "adapter pairs", flush=True)
            with (self.out_dir / "drift.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")

        def on_step_end(self, args, state, control, **kwargs):
            step = state.global_step
            if self.every and step and step % self.every == 0:
                self._write(step)
            if self.drift_every and step and step % self.drift_every == 0:
                self._drift(step)
            return control

        def on_train_end(self, args, state, control, **kwargs):
            self._write(state.global_step)
            return control

    class RolloutLogCallback(TrainerCallback):
        """Stream the per-group rollout statistics the monitoring section asks for."""

        def __init__(self, trainer, out_file: Path) -> None:
            self.trainer = trainer
            self.out_file = Path(out_file)

        def on_step_end(self, args, state, control, **kwargs):
            rows = getattr(self.trainer, "_rollout_log", [])
            if rows:
                # The counter has already moved on by the time this runs, so a
                # row that stamped its own step keeps it. Every row written
                # during a step does, which is what makes the file joinable.
                with self.out_file.open("a", encoding="utf-8") as fh:
                    for row in rows:
                        fh.write(json.dumps({"step": state.global_step, **row}) + "\n")
                self.trainer._rollout_log = []
            return control

    return VramSlopeCallback, SnapshotCallback, RolloutLogCallback


def completion_window(logps, keep: int):
    """The `keep` completion positions, whichever backend produced the tensor.

    Unsloth left-packs the rows before the forward using a maximum taken over
    the batch, so the width it returns depends on how much prompt padding the
    call carried. The completion always sits at the end, because packing only
    moves prompt padding, so the last `keep` positions are the ones the
    completion mask describes.
    """
    if logps is None or logps.ndim < 2 or logps.size(1) == keep:
        return logps
    if logps.size(1) < keep:
        raise AssertionError(
            f"the backend returned {logps.size(1)} positions, fewer than the "
            f"{keep} completion tokens; the window cannot be recovered")
    return logps[:, -keep:]


def load_pool(tasks_file: Path, split: str) -> list[dict]:
    """The canonical train split, with the E2 holdout asserted absent."""
    from stage_b.pool import E2_HOLDOUT

    out: list[dict] = []
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                record = json.loads(line)
                if record.get("split") == split:
                    out.append(record)
    intruders = sorted({r["building_id"] for r in out} & E2_HOLDOUT)
    if intruders:
        raise AssertionError(f"E2 holdout buildings in the {split} split: {intruders}")
    missing = [r["task_id"] for r in out
               if (r.get("verification") or {}).get("null_edit_score") is None]
    if missing:
        raise AssertionError(
            f"{len(missing)} tasks carry no null_edit_score; the reward needs it "
            f"(first: {missing[:3]})")
    # Tasks are looked up by id at rollout time and the gold cache names files
    # by id, so a repeated id would silently train on one record for both.
    ids = [r["task_id"] for r in out]
    if len(set(ids)) != len(ids):
        raise AssertionError(f"{len(ids) - len(set(ids))} repeated task ids in the {split} split")
    return out


def stratified_order(tasks: Sequence[dict], seed: int) -> list[dict]:
    """Round robin over operation and instruction category together.

    Cycling over the operation alone let one category fill a batch, and the
    categories are not interchangeable: the share of groups whose rollouts all
    score the same runs from a fifth to over four fifths across them, so a batch
    drawn from one category can carry almost no gradient. Crossing the two keeps
    every batch mixed on both.
    """
    import random

    from collections import defaultdict

    buckets: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for task in sorted(tasks, key=lambda t: t["task_id"]):
        buckets[(task["operation"], task.get("category") or "")].append(task)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    keys = sorted(buckets)
    ordered: list[dict] = []
    depth = 0
    while True:
        added = False
        for key in keys:
            if depth < len(buckets[key]):
                ordered.append(buckets[key][depth])
                added = True
        if not added:
            break
        depth += 1
    return ordered


# -------------------------------------------------------------------- main

def main(args: argparse.Namespace) -> int:
    run_dir = Path(args.checkpoint_root) / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    tasks = load_pool(Path(args.tasks_file), args.split)
    n_pool = len(tasks)
    if args.exclude_category:
        known = {t["category"] for t in tasks}
        unknown = sorted(set(args.exclude_category) - known)
        if unknown:
            raise SystemExit(f"--exclude-category {unknown}: not a category of the "
                             f"pool ({sorted(known)})")
        tasks = [t for t in tasks if t["category"] not in args.exclude_category]
        if not tasks:
            raise SystemExit("--exclude-category leaves no tasks")
    # The completion verdict reaches the scoring subprocess through the
    # environment; set before any rollout is scored.
    os.environ["VERIBIM_COMPLETION_BONUS"] = str(float(args.completion_bonus))
    n_before_ids = len(tasks)
    if args.task_ids_file:
        wanted = set(json.loads(Path(args.task_ids_file).read_text(encoding="utf-8")))
        tasks = [t for t in tasks if t["task_id"] in wanted]
        missing = wanted - {t["task_id"] for t in tasks}
        if not tasks:
            raise SystemExit(f"--task-ids-file {args.task_ids_file} keeps no task of the pool")
        if missing:
            print(f"  task ids not in the pool (after exclusions): {len(missing)}", flush=True)
    ordered = stratified_order(tasks, args.seed)
    if args.skip_tasks:
        if args.skip_tasks >= len(ordered):
            raise SystemExit(f"--skip-tasks {args.skip_tasks} leaves no tasks of {len(ordered)}")
        ordered = ordered[args.skip_tasks:]

    tasks_per_step = max(1, args.effective_batch // args.num_generations)
    generation_batch = tasks_per_step * args.num_generations
    extra = {
        "n_tasks": len(tasks),
        "n_tasks_in_split": n_pool,
        "excluded_categories": sorted(args.exclude_category),
        "skip_tasks": args.skip_tasks,
        "first_task": ordered[0]["task_id"],
        "task_ids_file": args.task_ids_file or None,
        "n_tasks_before_task_ids": n_before_ids,
        "completion_bonus": args.completion_bonus,
        "tasks_per_optimizer_step": tasks_per_step,
        "generation_batch_size": generation_batch,
        "gradient_accumulation_steps": generation_batch // args.per_device_batch,
        "trajectories_per_optimizer_step": generation_batch,
        "rollouts_in_flight": args.group_parallel * args.num_generations,
        "trajectories_total_at_max_steps": generation_batch * max(0, args.max_steps),
    }
    try:
        extra["grpo_config"] = build_grpo_config(
            args, run_dir, generation_batch).to_dict()
    except Exception as exc:  # noqa: BLE001 - a dump outside the training env
        extra["grpo_config_error"] = f"{type(exc).__name__}: {exc}"

    if args.dump_config_only:
        config = dump_config(args, extra)
        print(json.dumps({k: config[k] for k in
                          ("run_id", "policy", "reference", "reward", "rollout",
                           "n_tasks", "tasks_per_optimizer_step",
                           "trajectories_per_optimizer_step",
                           "trajectories_total_at_max_steps",
                           "config_differences_vs_dpo_v1")
                          if k in config}, indent=2))
        print(f"config dumped to {run_dir / 'resolved_config.json'} (no GPU touched)")
        return 0

    import torch
    from datasets import Dataset
    from peft import PeftModel
    import unsloth  # noqa: F401
    from unsloth import FastLanguageModel

    paths.ensure_harness_on_path()
    from modifc_harness.client import ChatClient
    from modifc_harness.config import AgentConfig
    from modifc_harness.prompts import TOOL_SCHEMA
    from stage_a.chat_format import assert_boundary_matches
    from stage_c.rollout import make_count_tokens
    from stage_c.weights import AdapterSync

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_dir, max_seq_length=args.max_seq,
        dtype=torch.bfloat16, load_in_4bit=False, full_finetuning=False)
    text_tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    pad_id = text_tokenizer.pad_token_id or text_tokenizer.eos_token_id

    # Policy and reference are the same weights at step 0; the reference simply
    # never receives a gradient. Holding it as a second adapter costs 173 MB
    # instead of a second copy of the base model.
    model = PeftModel.from_pretrained(model, args.adapter,
                                      adapter_name=POLICY_ADAPTER_NAME,
                                      is_trainable=True)
    model.load_adapter(args.reference_adapter or args.adapter,
                       adapter_name=REFERENCE_ADAPTER_NAME,
                       is_trainable=False)
    model.set_adapter(POLICY_ADAPTER_NAME)
    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    if trainable != args.expected_adapter_params:
        raise SystemExit(
            f"policy adapter has {trainable:,} trainable parameters, expected "
            f"{args.expected_adapter_params:,}: this is not dpo_v1 continued")

    agent = AgentConfig(max_tool_rounds=args.max_tool_rounds,
                        tool_timeout=args.tool_timeout,
                        temperature=args.temperature, top_p=args.top_p,
                        max_tokens=args.max_tokens,
                        max_tool_output_chars=args.max_tool_output_chars,
                        max_transcript_tokens=args.max_transcript_tokens,
                        min_turn_tokens=args.min_turn_tokens,
                        dup_stop=args.dup_stop)
    client = ChatClient(base_url=args.base_url, model=args.served_adapter,
                        request_timeout=1800.0, max_attempts=2, retry_delay=30.0)

    dataset = Dataset.from_list([{"prompt": t.get("instruction") or t["prompt"],
                                  "task_id": t["task_id"]} for t in ordered])
    config = build_grpo_config(args, run_dir, generation_batch)

    trainer_class = _build_trainer_class()
    veribim = {
        "tokenizer": text_tokenizer, "pad_id": pad_id, "client": client,
        "agent": agent, "tools": [TOOL_SCHEMA], "max_seq": args.max_seq,
        "num_generations": args.num_generations,
        "tasks": {t["task_id"]: t for t in tasks},
        "work_root": paths.require_absolute(args.work_root, "work_root"),
        "gold_cache_dir": paths.require_absolute(args.gold_cache, "gold_cache"),
        "sync_every": args.sync_every,
        "error_penalty": args.error_penalty,
        "error_penalty_cap": args.error_penalty_cap,
        "repeat_penalty": args.repeat_penalty,
        "repeat_penalty_cap": args.repeat_penalty_cap,
        "commit_required": args.commit_required,
        "group_parallel": args.group_parallel,
        "logit_chunk": args.logit_chunk,
        # The transcript budget is only worth having if it measures what the
        # encoder will measure, so the counter renders the prompt exactly as
        # `encode_group` does, with the same template and the same tool schema.
        "count_tokens": make_count_tokens(text_tokenizer, [TOOL_SCHEMA]),
        "logprob_check": args.logprob_check,
        "run_dir": run_dir,
    }
    veribim["work_root"].mkdir(parents=True, exist_ok=True)
    veribim["gold_cache_dir"].mkdir(parents=True, exist_ok=True)
    if args.sync_every:
        serve_root = paths.require_absolute(
            args.serve_root or (run_dir / "serve_adapters"), "serve_root")
        serve_root.mkdir(parents=True, exist_ok=True)
        veribim["sync"] = AdapterSync(base_url=args.base_url, serve_root=serve_root)

    trainer = trainer_class(model=model, args=config, train_dataset=dataset,
                            processing_class=tokenizer,
                            reward_funcs=[], veribim=veribim)

    VramSlope, Snapshot, RolloutLog = _build_callbacks()
    trainer.add_callback(VramSlope(run_dir / "vram.jsonl", args.vram_slope_steps,
                                   args.vram_ceiling_mib))
    trainer.add_callback(Snapshot(model, tokenizer, run_dir, args.save_steps,
                                  args.drift_every))
    trainer.add_callback(RolloutLog(trainer, run_dir / "rollouts.jsonl"))

    # The boundary claim, asserted here as well as at serving.
    sample = ordered[0]
    boundary = assert_boundary_matches(
        text_tokenizer,
        [{"role": "system", "content": "x"}, {"role": "user", "content": "y"},
         {"role": "assistant", "content": "z"}], [TOOL_SCHEMA])
    dumped = dump_config(args, {**extra, "boundary_check": boundary,
                                "adapter_trainable_params": trainable})
    print(json.dumps({"run_id": args.run_id, "tasks": len(tasks),
                      "adapter_trainable_params": trainable,
                      "tasks_per_optimizer_step": tasks_per_step,
                      "trajectories_per_optimizer_step": generation_batch,
                      "boundary_token_prefix": boundary["token_prefix"],
                      "config_differences_vs_dpo_v1":
                          dumped.get("config_differences_vs_dpo_v1")}, indent=2),
          flush=True)
    if args.dry_run:
        print("dry run: model loaded, adapters asserted, config dumped; not training",
              flush=True)
        return 0

    result = trainer.train()
    from stage_a.chat_format import save_adapter

    save_adapter(model, tokenizer, run_dir / "adapter",
                 adapter_name=POLICY_ADAPTER_NAME)
    (run_dir / "outcome.json").write_text(
        json.dumps({"metrics": dict(result.metrics),
                    "log_history": trainer.state.log_history}, indent=2, default=str),
        encoding="utf-8")
    return 0


def cli(argv: list[str] | None = None) -> int:
    return main(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(cli())
