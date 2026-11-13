"""The trainer's side of the grpo_v3 changes, checked on CPU.

Nothing here loads the 9B model, contacts a server, or asks for a card. The
model is the small two-adapter one the alignment check already builds, and the
rollouts are stubs, so every claim below is about arithmetic and bookkeeping
rather than about a particular set of weights.

Three of the checks carry most of the weight. Trimming the shared left padding
must not change what the log-probabilities are, or the leak it removes would
have been traded for a different one. One optimizer step's accumulated gradient
must be a fixed multiple of the gradient of the batch's own token-level loss,
whatever fraction of the batch was real, because the defect being removed is
exactly a step size that moved with the number of surviving rollouts. And a
group that lost a rollout at encoding must be dropped whole, because training on
what survived trains on a group whose worst trajectories were removed after they
were scored.

    python -m stage_c.tests.test_train_grpo_v3
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

import torch

from stage_a import paths
from stage_c.align_test import _import_grpo_trainer, build_tiny, synthetic_batch
from stage_c.rollout import Rollout
from stage_c.train_grpo import (adapter_drift, build_grpo_config, build_parser,
                                cli, _build_trainer_class, stratified_order,
                                trim_left)

POLICY = "policy"
REFERENCE = "reference"

#: The v3 launch flags, minus the run id and the checkpoint root, which the
#: configuration check supplies so it can write into a directory of its own.
V3_FLAGS = [
    "--reference-adapter",
    str(paths.PROJECT_ROOT / "checkpoints/stage_b/dpo_v1/adapter"),
    "--max-steps", "250", "--save-steps", "50", "--effective-batch", "64",
    "--num-generations", "8", "--group-parallel", "4", "--max-seq", "12288",
    "--max-transcript-tokens", "11776", "--min-turn-tokens", "256",
    "--dup-stop", "3", "--max-tool-rounds", "10", "--max-tool-output-chars", "4000",
    "--beta", "0.04", "--learning-rate", "3e-6", "--warmup-ratio", "0.02",
    "--lr-scheduler", "constant_with_warmup", "--exclude-category", "direct",
    "--vram-ceiling-mib", "27000", "--vram-slope-steps", "30",
    "--logging-steps", "1", "--error-penalty", "0.02",
    "--error-penalty-cap", "0.10", "--drift-every", "10",
    "--notes", "grpo_v3", "--dump-config-only",
]


# --------------------------------------------------------------------------
# helpers


def _trainer(model, tokenizer, *, rows: int, accumulation: int = 0,
             beta: float = 0.0, temperature: float = 0.9,
             scale_rewards: str = "group", veribim: dict | None = None):
    """A real trainer whose accumulation count the caller chooses.

    The alignment check's own builder pins the accumulation at one, and the
    normalisation is only visible across several micro-batches, so the settings
    are repeated here rather than shared.

    The accumulation count defaults to the number of rows, because the trainer
    takes one row per micro-batch and refuses to be built any other way.
    """
    from datasets import Dataset
    from trl import GRPOConfig

    accumulation = accumulation or rows
    _import_grpo_trainer()
    trainer_class = _build_trainer_class()
    inner = getattr(getattr(model, "base_model", model), "model", model)
    if not hasattr(inner, "warnings_issued"):
        inner.warnings_issued = {}
    holder = tempfile.mkdtemp(prefix="grpo_v3_test_")
    args = GRPOConfig(
        output_dir=holder, beta=beta, temperature=temperature,
        num_generations=rows, generation_batch_size=rows,
        per_device_train_batch_size=rows // accumulation,
        gradient_accumulation_steps=accumulation,
        max_steps=1, learning_rate=1e-6, report_to=[], use_vllm=False,
        loss_type="dapo", shuffle_dataset=False, use_cpu=True,
        scale_rewards=scale_rewards,
        bf16=False, fp16=False, disable_dropout=True,
        max_completion_length=64, logging_steps=1, save_strategy="no")
    dataset = Dataset.from_dict({"prompt": ["a"] * rows})
    trainer = trainer_class(model=model, reward_funcs=[lambda **kw: [0.0]],
                            args=args, train_dataset=dataset,
                            processing_class=tokenizer, veribim=veribim or {})
    trainer._test_output_dir = holder
    # The trainer's own `_prepare_inputs` is TRL's generation buffer, which
    # would roll out rather than take the micro-batch it is handed. These
    # checks feed the micro-batches directly.
    trainer._prepare_inputs = lambda batch: batch
    trainer.current_gradient_accumulation_steps = accumulation
    return trainer


def _gradients(model) -> dict:
    return {name: parameter.grad.detach().clone()
            for name, parameter in model.named_parameters()
            if parameter.requires_grad and parameter.grad is not None}


def _flatten(grads: dict, order) -> torch.Tensor:
    return torch.cat([grads[name].reshape(-1) if name in grads
                      else torch.zeros(1) for name in order])


def _direct_gradient(trainer, batch) -> dict:
    """The gradient of the whole batch's token-level loss, in one call."""
    model = trainer.model
    model.train()
    model.zero_grad(set_to_none=True)
    ids = torch.cat([batch["prompt_ids"], batch["completion_ids"]], dim=1)
    attention = torch.cat([batch["prompt_mask"],
                           batch["attention_completion_mask"]], dim=1)
    keep = batch["completion_ids"].size(1)
    mask = batch["completion_mask"]
    logps = trainer._logps(model, ids, attention, keep)
    ratio = torch.exp(logps - logps.detach())
    advantages = batch["advantages"].unsqueeze(1)
    low = getattr(trainer, "epsilon_low", 0.2)
    high = getattr(trainer, "epsilon_high", low)
    clipped = torch.clamp(ratio, 1.0 - low, 1.0 + high)
    per_token = -torch.min(ratio * advantages, clipped * advantages)
    loss = ((per_token * mask).sum()
            / batch["num_items_in_batch"].float().clamp(min=1.0))
    loss.backward()
    grads = _gradients(model)
    model.zero_grad(set_to_none=True)
    return grads


def _accumulated_gradient(trainer, batch, accumulation: int) -> dict:
    """The gradient one optimizer step accumulates, micro-batch by micro-batch."""
    model = trainer.model
    model.train()
    model.zero_grad(set_to_none=True)
    rows = batch["prompt_ids"].size(0)
    width = rows // accumulation
    for start in range(0, rows, width):
        micro = {key: (value[start:start + width]
                       if hasattr(value, "ndim") and value.ndim >= 1 else value)
                 for key, value in batch.items()}
        trainer.training_step(model, micro)
    grads = _gradients(model)
    model.zero_grad(set_to_none=True)
    return grads


def _scale_and_alignment(accumulated: dict, direct: dict) -> tuple[float, float]:
    """How much larger the accumulated gradient is, and whether it points the
    same way."""
    order = sorted(set(direct) | set(accumulated))
    left = _flatten(accumulated, order)
    right = _flatten(direct, order)
    scale = float((left @ right) / (right @ right))
    cosine = float((left @ right) / (left.norm() * right.norm()))
    return scale, cosine


def _batch(rows: int, real_rows: int, advantages: list[float]) -> dict:
    """A generation batch with `rows - real_rows` padded zero-mask copies."""
    batch = synthetic_batch(vocab=512, rows=rows, prompt_len=24,
                            completion_len=16, pad_id=0, device="cpu")
    batch["completion_mask"][real_rows:] = 0
    batch["advantages"] = torch.tensor(advantages, dtype=torch.float32)
    batch["num_items_in_batch"] = batch["completion_mask"].sum()
    return batch


class _StubEncoder:
    """An encoder that answers from a table of per-task outcomes."""

    def __init__(self, outcomes: dict, prompt_len: int = 6,
                 completion_len: int = 8, over_tokens: int = 5000):
        self.outcomes = outcomes
        self.prompt_len = prompt_len
        self.completion_len = completion_len
        self.over_tokens = over_tokens

    def __call__(self, tokenizer, task, rollouts, tools, max_seq):
        entries = []
        for position, rollout in enumerate(rollouts):
            if position in self.outcomes.get(task["task_id"], ()):
                # The real encoder sends the length with the refusal, because
                # that length is the one the transcript budget is set from.
                entries.append({"error": "over max_seq", "index": rollout.index,
                                "tokens": self.over_tokens})
                continue
            entries.append({
                "index": rollout.index,
                "completion_ids": list(range(10, 10 + self.completion_len)),
                "completion_mask": [1] * self.completion_len,
                "reward": rollout.reward,
                "n_assistant": self.completion_len})
        return {"prompt_ids": list(range(self.prompt_len)), "rollouts": entries}


def _stub_rollouts(task, k, client, agent, work_root, project_root,
                   gold_cache_dir, heldout=False, disk_floor_gb=0.0,
                   count_tokens=None, request_logprobs=False):
    """k scored trajectories with a spread, produced without a server."""
    return [Rollout(index=index, messages=[], stop_reason="completed",
                    tool_rounds=index, commits=1, tool_calls=index,
                    raised_calls=0, well_formed_calls=index,
                    reward=0.1 * index, gold_keys_written=0.5,
                    distinct_guids=index)
            for index in range(1, k + 1)]


def _rollouts_scoring(table: dict):
    """Rollouts whose rewards are read from a table, one list per task."""

    def roll(task, k, *args, **kwargs):
        return [Rollout(index=position + 1, messages=[],
                        stop_reason="completed", tool_rounds=1, commits=1,
                        tool_calls=1, raised_calls=0, well_formed_calls=1,
                        reward=value)
                for position, value in enumerate(table[task["task_id"]])]

    return roll


# --------------------------------------------------------------------------
# 1. trimming


def test_trim_left_removes_the_common_prefix():
    ids = torch.tensor([[9, 9, 9, 1, 2, 3], [9, 9, 4, 5, 6, 7]])
    attention = torch.tensor([[0, 0, 0, 1, 1, 1], [0, 0, 1, 1, 1, 1]])
    trimmed_ids, trimmed_attention = trim_left(ids, attention)
    assert trimmed_ids.shape == (2, 4)
    assert torch.equal(trimmed_ids, ids[:, 2:])
    assert torch.equal(trimmed_attention, attention[:, 2:])
    print("ok   test_trim_left_removes_the_common_prefix")


def test_trim_left_keeps_a_batch_without_a_shared_prefix():
    ids = torch.tensor([[1, 2, 3, 4], [9, 5, 6, 7]])
    attention = torch.tensor([[1, 1, 1, 1], [0, 1, 1, 1]])
    trimmed_ids, trimmed_attention = trim_left(ids, attention)
    assert trimmed_ids is ids and trimmed_attention is attention
    print("ok   test_trim_left_keeps_a_batch_without_a_shared_prefix")


def test_trim_left_survives_a_row_with_no_real_token():
    ids = torch.tensor([[9, 9, 1, 2], [9, 9, 9, 9]])
    attention = torch.tensor([[0, 0, 1, 1], [0, 0, 0, 0]])
    trimmed_ids, trimmed_attention = trim_left(ids, attention)
    assert trimmed_ids is ids and trimmed_attention is attention
    print("ok   test_trim_left_survives_a_row_with_no_real_token")


def test_trimming_does_not_change_the_log_probabilities():
    model, tokenizer = build_tiny()
    model.eval()
    trainer = _trainer(model, tokenizer, rows=2)
    torch.manual_seed(3)
    real = torch.randint(5, 512, (1, 30))
    padded = torch.cat([torch.zeros(1, 20, dtype=torch.long), real], dim=1)
    attention = torch.cat([torch.zeros(1, 20, dtype=torch.long),
                           torch.ones(1, 30, dtype=torch.long)], dim=1)
    keep = 12
    with torch.no_grad():
        wide = trainer._logps(model, padded, attention, keep)
        narrow = trainer._logps(model, *trim_left(padded, attention), keep)
    worst = (wide - narrow).abs().max().item()
    assert worst < 1e-5, worst
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print(f"ok   test_trimming_does_not_change_the_log_probabilities "
          f"(max|d|={worst:.2e})")


# --------------------------------------------------------------------------
# 2. loss normalisation


def _measure_factor(real_rows: int, advantages: list[float],
                    accumulation: int = 4) -> tuple[float, float]:
    """One row per micro-batch, so the batch is as wide as the count."""
    rows = accumulation
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=rows, accumulation=accumulation)
    batch = _batch(rows, real_rows, advantages)
    direct = _direct_gradient(trainer, batch)
    accumulated = _accumulated_gradient(trainer, batch, accumulation)
    scale, cosine = _scale_and_alignment(accumulated, direct)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    return scale, cosine


def test_the_step_gradient_is_a_fixed_multiple_of_the_batch_gradient():
    half, cosine_half = _measure_factor(2, [0.7, -0.7, 0.0, 0.0])
    full, cosine_full = _measure_factor(4, [0.7, -0.7, 0.3, -0.3])
    for cosine in (cosine_half, cosine_full):
        assert cosine > 1 - 1e-4, cosine
    relative = abs(half - full) / abs(full)
    assert relative < 1e-4, (half, full, relative)
    expected = 1.0 / 4
    assert abs(full - expected) / expected < 1e-4, (full, expected)
    print(f"ok   test_the_step_gradient_is_a_fixed_multiple_of_the_batch_gradient "
          f"(2 of 4 rows: {half:.6f}; 4 of 4: {full:.6f}; 1/GA = {expected:.6f})")


def test_the_factor_is_the_reciprocal_of_the_accumulation_count():
    two, _ = _measure_factor(2, [0.7, -0.7], accumulation=2)
    four, _ = _measure_factor(2, [0.7, -0.7, 0.0, 0.0], accumulation=4)
    assert abs(two - 1.0 / 2) / (1.0 / 2) < 1e-4, two
    assert abs(four - 1.0 / 4) / (1.0 / 4) < 1e-4, four
    print(f"ok   test_the_factor_is_the_reciprocal_of_the_accumulation_count "
          f"(GA=2: {two:.6f}; GA=4: {four:.6f})")


def test_a_padded_micro_batch_contributes_no_gradient():
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=4, accumulation=4)
    batch = _batch(4, 2, [0.7, -0.7, 0.0, 0.0])
    micro = {key: (value[3:4] if hasattr(value, "ndim") and value.ndim >= 1
                   else value) for key, value in batch.items()}
    model.train()
    model.zero_grad(set_to_none=True)
    loss = trainer.compute_loss(model, micro)
    assert float(loss.detach()) == 0.0, float(loss.detach())
    loss.backward()
    worst = max((parameter.grad.abs().max().item()
                 for parameter in model.parameters()
                 if parameter.requires_grad and parameter.grad is not None),
                default=0.0)
    assert worst == 0.0, worst
    # The row was counted before the forward was skipped, so the step's own
    # record still says how much of it was real.
    assert trainer._metrics["train"]["real_row_share"][-1] == 0.0
    model.zero_grad(set_to_none=True)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_a_padded_micro_batch_contributes_no_gradient")


def test_the_loss_reports_an_inert_clipping_fraction():
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=4, accumulation=4)
    batch = _batch(4, 4, [0.7, -0.7, 0.3, -0.3])
    micro = {key: (value[0:1] if hasattr(value, "ndim") and value.ndim >= 1
                   else value) for key, value in batch.items()}
    model.train()
    trainer.compute_loss(model, micro)
    metrics = trainer._metrics["train"]
    assert metrics["clip_fraction"][-1] == 0.0
    assert metrics["real_row_share"][-1] == 1.0
    assert abs(metrics["mean_abs_advantage_incl_padding"][-1] - 0.7) < 1e-6
    # The step summary reports the same two quantities differently, so the two
    # streams must not share a name.
    assert "real_rows" not in metrics and "mean_abs_advantage" not in metrics
    model.zero_grad(set_to_none=True)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_the_loss_reports_an_inert_clipping_fraction")


# --------------------------------------------------------------------------
# 3. the task order


def test_stratified_order_crosses_operation_and_category():
    pool = []
    sizes = {("create", "direct"): 5, ("create", "spatial"): 3,
             ("update", "direct"): 4, ("update", "spatial"): 7,
             ("delete", "direct"): 2, ("delete", "spatial"): 6}
    for (operation, category), count in sizes.items():
        for n in range(count):
            pool.append({"task_id": f"{operation}_{category}_{n}",
                         "operation": operation, "category": category})
    ordered = stratified_order(pool, seed=42)
    assert len(ordered) == len(pool)
    head = {(t["operation"], t["category"]) for t in ordered[:6]}
    assert head == set(sizes), sorted(head)
    again = stratified_order(list(reversed(pool)), seed=42)
    assert [t["task_id"] for t in again] == [t["task_id"] for t in ordered]
    other = stratified_order(pool, seed=7)
    assert [t["task_id"] for t in other] != [t["task_id"] for t in ordered]
    print("ok   test_stratified_order_crosses_operation_and_category")


# --------------------------------------------------------------------------
# 4. the group skip


def _score_batch(outcomes: dict, tasks: list[dict], k: int, *,
                 rollouts=_stub_rollouts, scale_rewards: str = "group"):
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=len(tasks) * k,
                       scale_rewards=scale_rewards)
    trainer.veribim = {
        "tokenizer": tokenizer, "pad_id": 0, "num_generations": k,
        "tasks": {t["task_id"]: t for t in tasks},
        "client": None, "agent": None, "work_root": Path("."),
        "gold_cache_dir": Path("."), "tools": [], "max_seq": 4096,
        "rollout_group": rollouts,
        "encode_group": _StubEncoder(outcomes),
    }
    inputs = [{"task_id": t["task_id"]} for t in tasks for _ in range(k)]
    out = trainer._generate_and_score_completions(inputs)
    log = list(trainer._rollout_log)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    return out, log


def test_a_group_that_lost_a_rollout_at_encoding_is_dropped_whole():
    tasks = [{"task_id": "t_good", "operation": "update", "category": "spatial"},
             {"task_id": "t_short", "operation": "create", "category": "direct"}]
    out, log = _score_batch({"t_short": (0,)}, tasks, k=2)
    skips = [row for row in log if row.get("skipped") == "encoder error"]
    assert len(skips) == 1, log
    assert skips[0]["task_id"] == "t_short"
    assert skips[0]["errors"] == {"over max_seq": 1}
    # The length the encoder refused travels with the skip, and into the step's
    # own statistics: a summary that reported only the survivors could never
    # show a transcript longer than the sequence length, which is the one thing
    # a reader needs to see when a group is lost.
    assert skips[0]["max_transcript_tokens"] == 5000
    summary_row = [row for row in log if row.get("step_summary")][0]
    assert summary_row["max_transcript_tokens"] == 5000
    assert summary_row["no_usable_groups"] is False
    kept = [row for row in log if row.get("n") == 2]
    assert [row["task_id"] for row in kept] == ["t_good"]
    summary = [row for row in log if row.get("step_summary")]
    assert len(summary) == 1, log
    assert summary[0]["groups_skipped_encoder"] == 1
    assert summary[0]["groups_informative"] == 1
    assert summary[0]["groups_run"] == 2
    assert summary[0]["real_rows"] == 2
    assert summary[0]["padded_rows"] == 2
    # The batch is filled back to its declared width from the group that
    # survived, and the copies carry no gradient.
    assert out["completion_ids"].size(0) == 4
    assert out["completion_mask"][2:].sum().item() == 0
    assert out["num_items_in_batch"].item() == 16
    print("ok   test_a_group_that_lost_a_rollout_at_encoding_is_dropped_whole")


def test_a_batch_with_no_surviving_group_takes_a_no_op_step():
    """Dropping groups whole must cost a step, not the run.

    Every group of the batch losing a rollout at encoding leaves nothing to
    train on. Raising there would end a run that has taken hundreds of steps,
    and discard the optimizer state, over one bad batch.
    """
    tasks = [{"task_id": "t_one", "operation": "update", "category": "spatial"},
             {"task_id": "t_two", "operation": "create", "category": "direct"}]
    out, log = _score_batch({"t_one": (0,), "t_two": (1,)}, tasks, k=2)
    assert [row for row in log if row.get("skipped") == "no group carried gradient"]
    summary = [row for row in log if row.get("step_summary")][0]
    assert summary["groups_skipped_encoder"] == 2
    assert summary["groups_informative"] == 0
    assert summary["real_rows"] == 0
    assert summary["padded_rows"] == 4
    assert summary["mean_abs_advantage"] == 0.0
    assert summary["no_usable_groups"] is True
    assert out["completion_mask"].sum().item() == 0
    assert out["advantages"].abs().sum().item() == 0.0
    assert out["completion_ids"].size(0) == 4
    print("ok   test_a_batch_with_no_surviving_group_takes_a_no_op_step")


def test_a_batch_that_encodes_nothing_still_takes_a_no_op_step():
    """The no-op must not depend on this batch having encoded something.

    Two ordinary batches leave the step with no encoded row at all: one where
    the encoder refuses every rollout of every group, and one where every
    group fails at rollout, which is what a sampling server that has gone away
    looks like. Both are taken as no-op steps on a row built from the padding
    token.
    """
    tasks = [{"task_id": "t_one", "operation": "update", "category": "spatial"},
             {"task_id": "t_two", "operation": "create", "category": "direct"}]
    out, log = _score_batch({"t_one": (0, 1), "t_two": (0, 1)}, tasks, k=2)
    assert [row for row in log if row.get("skipped") == "no group carried gradient"]
    summary = [row for row in log if row.get("step_summary")][0]
    assert summary["groups_skipped_encoder"] == 2
    assert summary["no_usable_groups"] is True
    assert summary["real_rows"] == 0
    assert out["completion_mask"].sum().item() == 0
    assert out["advantages"].abs().sum().item() == 0.0
    assert out["completion_ids"].size(0) == 4

    def every_group_fails(task, k, *args, **kwargs):
        raise RuntimeError("the sampling server is not answering")

    out, log = _score_batch({}, tasks, k=2, rollouts=every_group_fails)
    summary = [row for row in log if row.get("step_summary")][0]
    assert summary["no_usable_groups"] is True
    assert summary["groups_informative"] == 0
    assert summary["real_rows"] == 0
    assert [row for row in log if row.get("skipped", "").startswith("RuntimeError")]
    assert out["completion_mask"].sum().item() == 0
    assert out["completion_ids"].size(0) == 4
    print("ok   test_a_batch_that_encodes_nothing_still_takes_a_no_op_step")


def test_three_batches_in_a_row_that_encode_nothing_stop_the_run():
    """One empty batch is a no-op; EMPTY_BATCH_LIMIT in a row is a dead server.

    The counter resets whenever a batch encodes a row, so empty batches
    separated by a working one never add up to a stop.
    """
    from stage_c.train_grpo import EMPTY_BATCH_LIMIT
    tasks = [{"task_id": "t_one", "operation": "update", "category": "spatial"},
             {"task_id": "t_two", "operation": "create", "category": "direct"}]
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=len(tasks) * 2)
    inputs = [{"task_id": t["task_id"]} for t in tasks for _ in range(2)]

    def every_group_fails(task, k, *args, **kwargs):
        raise RuntimeError("the sampling server is not answering")

    def use(rollouts, encoder):
        trainer.veribim = {
            "tokenizer": tokenizer, "pad_id": 0, "num_generations": 2,
            "tasks": {t["task_id"]: t for t in tasks},
            "client": None, "agent": None, "work_root": Path("."),
            "gold_cache_dir": Path("."), "tools": [], "max_seq": 4096,
            "rollout_group": rollouts, "encode_group": encoder,
        }

    try:
        use(every_group_fails, _StubEncoder({}))
        for _ in range(EMPTY_BATCH_LIMIT - 1):
            trainer._generate_and_score_completions(inputs)
        assert trainer._batches_encoding_nothing == EMPTY_BATCH_LIMIT - 1
        # A batch that encodes something clears the count.
        use(_stub_rollouts, _StubEncoder({}))
        trainer._generate_and_score_completions(inputs)
        assert trainer._batches_encoding_nothing == 0
        use(every_group_fails, _StubEncoder({}))
        for _ in range(EMPTY_BATCH_LIMIT - 1):
            trainer._generate_and_score_completions(inputs)
        try:
            trainer._generate_and_score_completions(inputs)
        except RuntimeError as exc:
            assert "encoded nothing" in str(exc), exc
        else:
            raise AssertionError("the third empty batch in a row did not stop the run")
    finally:
        shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_three_batches_in_a_row_that_encode_nothing_stop_the_run")


def test_the_logprob_check_asks_again_when_its_group_was_skipped():
    """A flat first group leaves the check unmade; the next batch asks again.

    The check is done once a comparison covers at least one token, and it
    gives up after LOGPROB_CHECK_ATTEMPTS batches without one.
    """
    from stage_c.train_grpo import LOGPROB_CHECK_ATTEMPTS
    tasks = [{"task_id": "t_flat", "operation": "update", "category": "spatial"},
             {"task_id": "t_mixed", "operation": "create", "category": "spatial"}]
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=len(tasks) * 2)
    inputs = [{"task_id": t["task_id"]} for t in tasks for _ in range(2)]
    asked: list[tuple[str, bool]] = []
    compared: list[str] = []

    def rollouts_from(table: dict):
        scoring = _rollouts_scoring(table)

        def roll(task, k, *args, request_logprobs=False, **kwargs):
            asked.append((task["task_id"], request_logprobs))
            return scoring(task, k, *args, **kwargs)

        return roll

    def compare(task, group, encoded):
        compared.append(task["task_id"])
        return {"task_id": task["task_id"], "n_tokens": 5}

    trainer._compare_logprobs = compare

    def use(table: dict):
        trainer.veribim = {
            "tokenizer": tokenizer, "pad_id": 0, "num_generations": 2,
            "tasks": {t["task_id"]: t for t in tasks},
            "client": None, "agent": None, "work_root": Path("."),
            "gold_cache_dir": Path("."), "tools": [], "max_seq": 4096,
            "rollout_group": rollouts_from(table),
            "encode_group": _StubEncoder({}), "logprob_check": True,
        }

    try:
        # The first task's group is flat, so it is skipped before encoding.
        use({"t_flat": (1.0, 1.0), "t_mixed": (0.0, 1.0)})
        trainer._generate_and_score_completions(inputs)
        assert asked == [("t_flat", True), ("t_mixed", False)], asked
        assert compared == []
        assert not trainer._logprob_check_done
        assert trainer._logprob_check_attempts == 1
        # The next batch asks again, this time of a group that is compared.
        asked.clear()
        use({"t_flat": (0.0, 1.0), "t_mixed": (0.0, 1.0)})
        trainer._generate_and_score_completions(inputs)
        assert asked == [("t_flat", True), ("t_mixed", False)], asked
        assert compared == ["t_flat"]
        assert trainer._logprob_check_done
        # Once done, no later batch asks.
        asked.clear()
        trainer._generate_and_score_completions(inputs)
        assert asked == [("t_flat", False), ("t_mixed", False)], asked
        assert compared == ["t_flat"]

        # Giving up: a fresh trainer whose asked-of group is flat every time.
        trainer._logprob_check_done = False
        trainer._logprob_check_attempts = 0
        compared.clear()
        use({"t_flat": (1.0, 1.0), "t_mixed": (0.0, 1.0)})
        for attempt in range(1, LOGPROB_CHECK_ATTEMPTS + 1):
            asked.clear()
            trainer._generate_and_score_completions(inputs)
            assert asked[0] == ("t_flat", True), (attempt, asked)
            assert trainer._logprob_check_done is (attempt == LOGPROB_CHECK_ATTEMPTS)
        asked.clear()
        trainer._generate_and_score_completions(inputs)
        assert asked[0] == ("t_flat", False), asked
        assert compared == []
    finally:
        shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_the_logprob_check_asks_again_when_its_group_was_skipped")


def test_the_step_summary_carries_the_step_it_describes():
    """The log writer stamps rows after the counter has moved on."""
    tasks = [{"task_id": "t_a", "operation": "update", "category": "spatial"},
             {"task_id": "t_b", "operation": "create", "category": "direct"}]
    _, log = _score_batch({"t_b": (0,)}, tasks, k=2)
    summary = [row for row in log if row.get("step_summary")][0]
    skip = [row for row in log if row.get("skipped") == "encoder error"][0]
    assert summary["step"] == skip["step"]
    print("ok   test_the_step_summary_carries_the_step_it_describes")


def test_the_step_summary_records_the_rollout_instruments():
    tasks = [{"task_id": "t_a", "operation": "update", "category": "spatial"},
             {"task_id": "t_b", "operation": "create", "category": "direct"}]
    _, log = _score_batch({}, tasks, k=2)
    summary = [row for row in log if row.get("step_summary")][0]
    assert summary["stop_reasons"] == {"completed": 4}
    assert summary["share_duplicate_loop"] == 0.0
    assert summary["share_token_budget"] == 0.0
    assert summary["share_budget_exhausted"] == 0.0
    assert summary["mean_rounds"] == 1.5
    assert summary["mean_distinct_guids"] == 1.5
    assert summary["mean_gold_keys_written"] == 0.5
    # 6 prompt tokens and 8 completion tokens per encoded rollout.
    assert summary["mean_transcript_tokens"] == 14
    assert summary["max_transcript_tokens"] == 14
    assert summary["mean_abs_advantage"] > 0
    kept = [row for row in log if row.get("n") == 2]
    assert all(stat["transcript_tokens"] == 14
               for row in kept for stat in row["stats"])
    print("ok   test_the_step_summary_records_the_rollout_instruments")


def test_unscaled_advantages_are_the_centred_rewards():
    """What --scale-rewards decides, on a group of four close rewards.

    Dividing by the group's own standard deviation turns a spread of three
    hundredths of a reward point into an advantage of about 1.34, which is the
    same size a group spanning the whole reward range would produce. Without
    the division the advantage keeps the reward's own scale.
    """
    rewards = [-0.02, -0.04, -0.06, -0.08]
    tasks = [{"task_id": "t_a", "operation": "update", "category": "spatial"}]
    roll = _rollouts_scoring({"t_a": rewards})
    mean = sum(rewards) / len(rewards)
    centred = [value - mean for value in rewards]

    unscaled, _ = _score_batch({}, tasks, k=4, rollouts=roll,
                               scale_rewards="none")
    measured = unscaled["advantages"].tolist()
    assert max(abs(a - b) for a, b in zip(measured, centred)) < 1e-6, measured
    assert abs(max(abs(a) for a in measured) - 0.03) < 1e-6, measured

    scaled, _ = _score_batch({}, tasks, k=4, rollouts=roll,
                             scale_rewards="group")
    peak = max(abs(a) for a in scaled["advantages"].tolist())
    assert abs(peak - 1.34) < 0.01, peak
    print(f"ok   test_unscaled_advantages_are_the_centred_rewards "
          f"(unscaled peak {max(abs(a) for a in measured):.4f}, "
          f"group-scaled peak {peak:.4f})")


def test_batch_scaling_divides_by_the_spread_of_the_whole_batch():
    """Two groups, one narrow and one wide, keep their relative sizes."""
    narrow = [-0.02, -0.04, -0.06, -0.08]
    wide = [0.1, 0.4, 0.7, 1.0]
    tasks = [{"task_id": "t_a", "operation": "update", "category": "spatial"},
             {"task_id": "t_b", "operation": "create", "category": "direct"}]
    out, _ = _score_batch({}, tasks, k=4,
                          rollouts=_rollouts_scoring({"t_a": narrow,
                                                      "t_b": wide}),
                          scale_rewards="batch")
    everything = narrow + wide
    mean = sum(everything) / len(everything)
    spread = (sum((v - mean) ** 2 for v in everything) / len(everything)) ** 0.5
    expected = []
    for group in (narrow, wide):
        centre = sum(group) / len(group)
        expected.extend([(v - centre) / (spread + 1e-4) for v in group])
    measured = out["advantages"].tolist()
    assert max(abs(a - b) for a, b in zip(measured, expected)) < 1e-5, measured
    assert max(abs(a) for a in measured[:4]) < max(abs(a) for a in measured[4:])
    print("ok   test_batch_scaling_divides_by_the_spread_of_the_whole_batch")


def test_the_trainer_refuses_more_than_one_row_per_micro_batch():
    """Trimming the shared padding is only exact one row at a time.

    The refusal has to arrive before the run does, so it is made twice: once
    where the flags become the trainer's configuration, and once on a trainer
    that has been given a rollout configuration and is therefore a run.
    """
    parser = build_parser()
    args = parser.parse_args(["--run-id", "x", "--per-device-batch", "2"])
    try:
        build_grpo_config(args, Path("."), generation_batch=4)
    except ValueError as exc:
        assert "one row per micro-batch" in str(exc), exc
    else:
        raise AssertionError("a two-row micro-batch was configured")

    model, tokenizer = build_tiny()
    try:
        _trainer(model, tokenizer, rows=4, accumulation=2,
                 veribim={"num_generations": 4})
    except ValueError as exc:
        assert "one row per micro-batch" in str(exc), exc
    else:
        raise AssertionError("a two-row micro-batch was accepted")
    print("ok   test_the_trainer_refuses_more_than_one_row_per_micro_batch")


# --------------------------------------------------------------------------
# 5. the one-shot comparison against the sampler


def test_the_logprob_check_compares_the_gradient_masked_positions():
    model, tokenizer = build_tiny()
    model.eval()
    holder = Path(tempfile.mkdtemp(prefix="grpo_v3_logprob_"))
    trainer = _trainer(model, tokenizer, rows=2)
    trainer.veribim = {"run_dir": holder}
    prompt = list(range(20, 26))
    completion = list(range(30, 40))
    mask = [1, 1, 1, 0, 0, 0, 0, 1, 1, 1]
    encoded = {"prompt_ids": prompt,
               "rollouts": [{"index": 1, "completion_ids": completion,
                             "completion_mask": mask, "reward": 0.5},
                            {"index": 2, "completion_ids": completion,
                             "completion_mask": mask, "reward": 0.1},
                            {"error": "over max_seq", "index": 3}]}
    ids = torch.tensor([prompt + completion])
    with torch.no_grad():
        ours = trainer._logps(model, ids, torch.ones_like(ids),
                              len(completion), temperature=1.0)
    truth = ours[0][torch.tensor(mask, dtype=torch.bool)].tolist()
    group = [
        Rollout(index=1, messages=[], stop_reason="completed", tool_rounds=1,
                commits=1, tool_calls=1, raised_calls=0, well_formed_calls=1,
                turn_logprobs=[truth[:3], truth[3:]]),
        Rollout(index=2, messages=[], stop_reason="completed", tool_rounds=1,
                commits=1, tool_calls=1, raised_calls=0, well_formed_calls=1,
                turn_logprobs=[[value - 1.0 for value in truth]]),
    ]
    report = trainer._compare_logprobs({"task_id": "t_a"}, group, encoded)
    assert report["n_tokens"] == 2 * len(truth)
    by_index = {row["index"]: row for row in report["rollouts"]}
    assert by_index[1]["compared"] == len(truth)
    assert by_index[1]["mean_abs"] < 1e-5, by_index[1]
    assert abs(by_index[2]["mean_abs"] - 1.0) < 1e-5, by_index[2]
    assert abs(report["mean_abs"] - 0.5) < 1e-5, report["mean_abs"]
    written = json.loads((holder / "logprob_check.json").read_text(encoding="utf-8"))
    assert written["task_id"] == "t_a"
    shutil.rmtree(holder, ignore_errors=True)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_the_logprob_check_compares_the_gradient_masked_positions")


def test_the_logprob_check_compares_the_common_prefix_when_the_counts_differ():
    model, tokenizer = build_tiny()
    model.eval()
    holder = Path(tempfile.mkdtemp(prefix="grpo_v3_logprob_"))
    trainer = _trainer(model, tokenizer, rows=2)
    trainer.veribim = {"run_dir": holder}
    encoded = {"prompt_ids": [20, 21, 22],
               "rollouts": [{"index": 1, "completion_ids": [30, 31, 32, 33],
                             "completion_mask": [1, 1, 1, 1], "reward": 0.5}]}
    group = [Rollout(index=1, messages=[], stop_reason="completed", tool_rounds=1,
                     commits=1, tool_calls=1, raised_calls=0,
                     well_formed_calls=1, turn_logprobs=[[-1.0, -1.0]])]
    report = trainer._compare_logprobs({"task_id": "t_b"}, group, encoded)
    assert report["rollouts"][0]["trainer_tokens"] == 4
    assert report["rollouts"][0]["server_tokens"] == 2
    assert report["rollouts"][0]["compared"] == 2
    assert report["n_tokens"] == 2
    shutil.rmtree(holder, ignore_errors=True)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    print("ok   test_the_logprob_check_compares_the_common_prefix_when_the_counts_differ")


# --------------------------------------------------------------------------
# 6. drift


def test_adapter_drift_refuses_to_report_zero_over_nothing():
    """Zero over nothing must not read as zero over every module.

    A layout this function cannot walk would otherwise report the distance a
    policy held close by a strong penalty reports, so the one instrument that
    says whether the policy is moving would look healthy while reading nothing.
    """

    class Empty(torch.nn.Module):
        pass

    for model, kwargs in ((Empty(), {}), (build_tiny()[0], {"policy": "absent"})):
        try:
            adapter_drift(model, **kwargs)
        except ValueError as exc:
            assert "no distance could be taken" in str(exc)
        else:
            raise AssertionError("a distance was reported over no pair at all")
    assert adapter_drift(build_tiny()[0])[1] > 0
    print("ok   test_adapter_drift_refuses_to_report_zero_over_nothing")


def test_adapter_drift_matches_the_closed_form():
    model, _ = build_tiny()
    assert adapter_drift(model)[0] == 0.0
    delta = 0.013
    with torch.no_grad():
        for name, tensor in model.named_parameters():
            if f"lora_B.{POLICY}" in name:
                tensor.add_(delta)
    numerator = 0.0
    denominator = 0.0
    for name, tensor in model.named_parameters():
        if f"lora_A.{REFERENCE}" in name or f"lora_B.{REFERENCE}" in name:
            denominator += float((tensor.detach().float() ** 2).sum())
        if f"lora_B.{POLICY}" in name:
            numerator += delta ** 2 * tensor.numel()
    expected = (numerator / denominator) ** 0.5
    measured, pairs = adapter_drift(model)
    assert abs(measured - expected) / expected < 1e-6, (measured, expected)
    assert pairs > 0
    print(f"ok   test_adapter_drift_matches_the_closed_form "
          f"(relL2={measured:.4e} over {pairs} pairs)")


# --------------------------------------------------------------------------
# 7. the resolved configuration


def _dumped(extra_flags: list[str]) -> dict:
    holder = Path(tempfile.mkdtemp(prefix="grpo_v3_config_"))
    try:
        code = cli(["--run-id", "grpo_v3_spec_check",
                    "--checkpoint-root", str(holder)] + V3_FLAGS + extra_flags)
        assert code == 0
        return json.loads(
            (holder / "grpo_v3_spec_check" / "resolved_config.json")
            .read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def test_the_reward_scaling_is_named_in_the_resolved_config():
    """The run's own record says what the advantage was divided by."""
    default = _dumped([])
    assert default["loss"]["scale_rewards"] == "group"
    assert "group-scaled" in default["loss"]["form"]
    assert default["grpo_config"]["scale_rewards"] == "group"

    unscaled = _dumped(["--scale-rewards", "none"])
    assert unscaled["loss"]["scale_rewards"] == "none"
    assert "unscaled (Dr. GRPO form)" in unscaled["loss"]["form"]
    assert "group-scaled" not in unscaled["loss"]["form"]
    assert unscaled["grpo_config"]["scale_rewards"] == "none"

    batched = _dumped(["--scale-rewards", "batch"])
    assert batched["loss"]["scale_rewards"] == "batch"
    assert "batch-scaled" in batched["loss"]["form"]
    print("ok   test_the_reward_scaling_is_named_in_the_resolved_config")


def test_the_v3_flags_resolve_to_the_intended_run():
    config = _dumped([])
    assert "form" in config["loss"]
    # The unread results of the last round are dropped rather than reserved
    # for, so the reserve the earlier run recorded is gone.
    assert "tool_result_reserve" not in config["rollout"]
    assert config["rollout"]["unread_tool_results_dropped"] is True
    assert config["loss"]["measured_grad_factor"]
    assert "grad_accum" not in config["cli_args"]
    assert config["excluded_categories"] == ["direct"]
    assert config["tasks_per_optimizer_step"] == 8
    assert config["generation_batch_size"] == 64
    assert config["gradient_accumulation_steps"] == 64
    assert config["rollouts_in_flight"] == 32
    assert config["rollout"]["rounds_cap"] == 10
    assert config["cli_args"]["max_transcript_tokens"] == 11776
    assert config["cli_args"]["dup_stop"] == 3
    assert config["cli_args"]["min_turn_tokens"] == 256
    assert config["cli_args"]["drift_every"] == 10
    assert config["cli_args"]["logprob_check"] is True
    assert config["grpo_config"]["loss_type"] == "dapo"
    print("ok   test_the_v3_flags_resolve_to_the_intended_run")


def test_the_removed_flag_is_gone():
    parser = build_parser()
    settings = vars(parser.parse_args(["--run-id", "x"]))
    assert "grad_accum" not in settings
    assert settings["max_transcript_tokens"] == 0
    assert settings["min_turn_tokens"] == 256
    assert settings["dup_stop"] == 0
    assert settings["drift_every"] == 10
    assert settings["logprob_check"] is True
    assert settings["scale_rewards"] == "group"
    off = vars(parser.parse_args(["--run-id", "x", "--no-logprob-check"]))
    assert off["logprob_check"] is False
    print("ok   test_the_removed_flag_is_gone")


# --------------------------------------------------------------------------


def main() -> int:
    checks = [value for name, value in sorted(globals().items())
              if name.startswith("test_") and callable(value)]
    failed: list[str] = []
    for check in checks:
        try:
            check()
        except Exception as exc:  # noqa: BLE001
            failed.append(check.__name__)
            print(f"FAIL {check.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
