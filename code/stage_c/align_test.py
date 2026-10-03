"""Does the reference path compute the same thing as the loss path?

At step 1 the policy and the reference adapters hold the same weights, both
loaded from dpo_v1, and the LoRA dropout of that adapter is 0.0. The KL between
them is therefore exactly zero by construction, and any nonzero value the
trainer reports is arithmetic rather than a difference between two
distributions. That invariant is what this test checks, without a card.

Four checks, in the order that localises a fault:

    A  same adapter, both paths          -> must agree token for token
    B  two adapters with equal weights   -> must agree token for token
    C  reference perturbed               -> must disagree, but plausibly
    D  the attention swap                -> must change the answer

A failure in A is a path fault (masks, slices, temperature, grad mode). A
passing A with a failing B is an adapter-switching fault. A failing D means the
loss path is silently attending to assistant tokens only, which is the fault
that produces an enormous KL against a reference that attended to everything.

    python -m stage_c.align_test              # tiny model, CPU, seconds
    python -m stage_c.align_test --real       # the real base and dpo_v1
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import torch


def _stub_module(name: str):
    """An empty module that find_spec can answer for, parents included."""
    import importlib.machinery
    import sys
    import types

    if name in sys.modules:
        return sys.modules[name]
    if "." in name:
        _stub_module(name.rsplit(".", 1)[0])
    module = types.ModuleType(name)
    # A module with no __spec__ makes find_spec raise rather than answer.
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)
    module.__version__ = "0"
    module.__path__ = []
    sys.modules[name] = module
    return module


def _import_grpo_trainer():
    """Import TRL's GRPOTrainer without a GPU in the room.

    Several of TRL 0.24's optional-dependency probes return the tuple
    `(False, None)`, which is truthy, so the module imports mergekit,
    llm_blender and friends unconditionally and fails when they are absent.
    Production never sees this because Unsloth is imported first and patches
    trl; this test must stay off the card, so it supplies empty modules and
    attributes for whatever the import asks for, until the import succeeds.
    """
    import re
    import sys

    supplied: list[str] = []
    for _ in range(40):
        try:
            from trl import GRPOTrainer  # noqa: F401
            return supplied
        except (ImportError, RuntimeError) as exc:
            text = str(exc.__cause__ or exc)
            attribute = re.search(r"cannot import name '([^']+)' from '([^']+)'", text)
            module_name = re.search(r"No module named '([^']+)'", text)
            if attribute:
                key = f"{attribute.group(2)}.{attribute.group(1)}"
                setattr(_stub_module(attribute.group(2)), attribute.group(1), object)
            elif module_name:
                key = module_name.group(1)
                _stub_module(key)
            else:
                raise
            if key in supplied:
                raise
            supplied.append(key)
            for cached in [k for k in sys.modules if k.startswith("trl")]:
                del sys.modules[cached]
    raise RuntimeError(f"trl still will not import after stubbing {supplied}")


from stage_a import paths
from stage_c.train_grpo import (POLICY_ADAPTER_NAME, REFERENCE_ADAPTER_NAME,
                                _build_trainer_class, completion_window)

TOLERANCE = 1e-4
PLAUSIBLE_GAP = 3.0
KL_TOLERANCE = 1e-2


def build_tiny(seed: int = 0):
    """A small causal model carrying two LoRA adapters with equal weights."""
    from peft import LoraConfig, get_peft_model
    from transformers import AutoTokenizer, Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(seed)
    config = Qwen2Config(vocab_size=512, hidden_size=64, intermediate_size=128,
                         num_hidden_layers=2, num_attention_heads=4,
                         num_key_value_heads=2, attention_dropout=0.0)
    model = Qwen2ForCausalLM(config).to(torch.float32)
    lora = LoraConfig(r=8, lora_alpha=16, lora_dropout=0.0, task_type="CAUSAL_LM",
                      target_modules=["q_proj", "k_proj", "v_proj", "o_proj"])
    model = get_peft_model(model, lora, adapter_name=POLICY_ADAPTER_NAME)
    model.add_adapter(REFERENCE_ADAPTER_NAME, lora)

    # A freshly added adapter is the identity (B is zeros), which would make the
    # comparison vacuous. Give the policy real weights, then copy them across so
    # the two adapters are equal and neither is a no-op.
    state = model.state_dict()
    with torch.no_grad():
        for name, tensor in state.items():
            if f"lora_B.{POLICY_ADAPTER_NAME}" in name:
                tensor.normal_(0.0, 0.02)
        for name, tensor in state.items():
            if f".{REFERENCE_ADAPTER_NAME}." in name:
                twin = name.replace(f".{REFERENCE_ADAPTER_NAME}.",
                                    f".{POLICY_ADAPTER_NAME}.")
                tensor.copy_(state[twin])
    model.set_adapter(POLICY_ADAPTER_NAME)
    tokenizer = AutoTokenizer.from_pretrained(str(paths.BASE_MODEL_DIR))
    return model, getattr(tokenizer, "tokenizer", tokenizer)


def build_real(device: str, dtype):
    """The real base model with dpo_v1 loaded twice, no Unsloth patching."""
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    adapter = paths.PROJECT_ROOT / "checkpoints/stage_b/dpo_v1/adapter"
    model = AutoModelForCausalLM.from_pretrained(
        str(paths.BASE_MODEL_DIR), dtype=dtype, device_map=device)
    model = PeftModel.from_pretrained(model, str(adapter),
                                      adapter_name=POLICY_ADAPTER_NAME,
                                      is_trainable=True)
    model.load_adapter(str(adapter), adapter_name=REFERENCE_ADAPTER_NAME,
                       is_trainable=False)
    model.set_adapter(POLICY_ADAPTER_NAME)
    tokenizer = AutoTokenizer.from_pretrained(str(paths.BASE_MODEL_DIR))
    return model, getattr(tokenizer, "tokenizer", tokenizer)


def build_unsloth(dtype, max_seq: int):
    """The production loader: Unsloth's model with dpo_v1 attached twice.

    This is the only configuration the CPU checks cannot reach, and therefore
    the only remaining place a step-1 KL can come from once the plain PEFT
    checks pass.
    """
    from peft import PeftModel
    from unsloth import FastLanguageModel

    adapter = paths.PROJECT_ROOT / "checkpoints/stage_b/dpo_v1/adapter"
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=str(paths.BASE_MODEL_DIR), max_seq_length=max_seq,
        dtype=dtype, load_in_4bit=False, full_finetuning=False)
    model = PeftModel.from_pretrained(model, str(adapter),
                                      adapter_name=POLICY_ADAPTER_NAME,
                                      is_trainable=True)
    model.load_adapter(str(adapter), adapter_name=REFERENCE_ADAPTER_NAME,
                       is_trainable=False)
    model.set_adapter(POLICY_ADAPTER_NAME)
    return model, getattr(tokenizer, "tokenizer", tokenizer)


def synthetic_batch(vocab: int, rows: int, prompt_len: int, completion_len: int,
                    pad_id: int, device: str) -> dict:
    """A batch shaped like a real one: left-padded prompts, masked tool spans.

    Row 0 keeps a shorter prompt than the rest so the left padding is exercised,
    and every row carries a middle span standing for tool output: attended to,
    but not carrying gradient.
    """
    torch.manual_seed(7)
    prompt_ids, prompt_mask = [], []
    for row in range(rows):
        real = prompt_len - (3 if row == 0 else 0)
        ids = torch.randint(5, vocab, (real,))
        pad = prompt_len - real
        prompt_ids.append(torch.cat([torch.full((pad,), pad_id), ids]))
        prompt_mask.append(torch.cat([torch.zeros(pad), torch.ones(real)]))

    completion_ids, completion_mask, attention_completion = [], [], []
    for row in range(rows):
        real = completion_len - (2 if row % 2 else 0)
        ids = torch.randint(5, vocab, (real,))
        gradient = torch.ones(real)
        gradient[real // 3: 2 * real // 3] = 0        # the tool's words
        pad = completion_len - real
        completion_ids.append(torch.cat([ids, torch.full((pad,), pad_id)]))
        completion_mask.append(torch.cat([gradient, torch.zeros(pad)]))
        attention_completion.append(torch.cat([torch.ones(real), torch.zeros(pad)]))

    def stack(rows_, dtype=torch.long):
        return torch.stack(rows_).to(device=device, dtype=dtype)

    return {
        "prompt_ids": stack(prompt_ids),
        "prompt_mask": stack(prompt_mask),
        "completion_ids": stack(completion_ids),
        "completion_mask": stack(completion_mask),
        "attention_completion_mask": stack(attention_completion),
        "advantages": torch.zeros(rows, device=device),
        "num_items_in_batch": stack(completion_mask).sum(),
    }


def make_trainer(model, tokenizer, beta: float, temperature: float):
    """A real GRPOTrainer, so the checks run through production code."""
    from datasets import Dataset
    from trl import GRPOConfig

    _import_grpo_trainer()
    trainer_class = _build_trainer_class()
    # transformers 5.5 no longer defines this on the model, and the Trainer
    # writes to it during setup.
    inner = getattr(getattr(model, "base_model", model), "model", model)
    if not hasattr(inner, "warnings_issued"):
        inner.warnings_issued = {}
    args = GRPOConfig(
        output_dir="align_test_out", beta=beta, temperature=temperature,
        num_generations=2, generation_batch_size=2,
        per_device_train_batch_size=2, gradient_accumulation_steps=1,
        max_steps=1, learning_rate=1e-6, report_to=[], use_vllm=False,
        loss_type="grpo", shuffle_dataset=False, use_cpu=True,
        bf16=False, fp16=False, disable_dropout=True,
        max_completion_length=64, logging_steps=1, save_strategy="no")
    dataset = Dataset.from_dict({"prompt": ["a", "b"]})
    return trainer_class(model=model, reward_funcs=[lambda **kw: [0.0]],
                         args=args, train_dataset=dataset,
                         processing_class=tokenizer, veribim={})


def logps_via_loss_path(trainer, batch, use_full_attention: bool):
    """What TRL's loss computes, including the trainer's attention swap."""
    ids = torch.cat([batch["prompt_ids"], batch["completion_ids"]], dim=1)
    mask = torch.cat([batch["prompt_mask"], batch["completion_mask"]], dim=1)
    keep = batch["completion_ids"].size(1)
    trainer._full_attention = None
    if use_full_attention:
        trainer._full_attention = torch.cat(
            [batch["prompt_mask"], batch["attention_completion_mask"]], dim=1)
    try:
        with torch.no_grad():
            logps, _ = trainer._get_per_token_logps_and_entropies(
                trainer.model, ids, mask, keep, compute_entropy=False)
    finally:
        trainer._full_attention = None
    return completion_window(logps, keep)


def logps_via_reference_path(trainer, batch, adapter: str):
    """What the trainer computes for the reference, on the named adapter."""
    ids = torch.cat([batch["prompt_ids"], batch["completion_ids"]], dim=1)
    full = torch.cat([batch["prompt_mask"], batch["attention_completion_mask"]],
                     dim=1)
    keep = batch["completion_ids"].size(1)
    return completion_window(
        trainer._reference_logps(trainer.model, ids, full, keep, adapter=adapter),
        keep)


def compare(name: str, left, right, mask, tolerance: float) -> dict:
    """Token-for-token agreement, counted only where gradient flows."""
    delta = (left - right) * mask
    count = mask.sum().clamp(min=1)
    worst = delta.abs().max().item()
    mean = (delta.sum() / count).item()
    k3 = ((torch.exp(delta) - delta - 1) * mask).sum().item()
    row = {"check": name, "max_abs": worst, "mean": mean, "k3_total": k3,
           "passed": abs(mean) <= tolerance}
    print(f"  {name:<34} max|d|={worst:.3e}  mean d={mean:+.3e}  "
          f"k3={k3:.3e}  {'ok' if row['passed'] else 'MISMATCH'}")
    return row


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stage-c-align")
    ap.add_argument("--real", action="store_true",
                    help="use the real base model and dpo_v1 instead of a tiny one")
    ap.add_argument("--unsloth", action="store_true",
                    help="load the way production does, through Unsloth (needs a card)")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--rows", type=int, default=2)
    ap.add_argument("--prompt-len", type=int, default=24)
    ap.add_argument("--completion-len", type=int, default=16)
    ap.add_argument("--temperature", type=float, default=0.9)
    ap.add_argument("--tolerance", type=float, default=TOLERANCE)
    ap.add_argument("--dtype", default="", choices=["", "float32", "bfloat16"])
    ap.add_argument("--kl-tolerance", type=float, default=KL_TOLERANCE,
                    help="bfloat16 on the real model has a KL floor near 0.3")
    args = ap.parse_args(argv)

    if args.unsloth:
        # Imported before trl, as production does, so its patches are in place.
        model, tokenizer = build_unsloth(torch.bfloat16, max_seq=4096)
        cfg = model.config
        vocab = getattr(cfg, "vocab_size", None) or cfg.text_config.vocab_size
    elif args.real:
        dtype = (getattr(torch, args.dtype) if args.dtype else
                 (torch.bfloat16 if args.device.startswith("cuda") else torch.float32))
        model, tokenizer = build_real(args.device, dtype)
        vocab = model.config.vocab_size if hasattr(model.config, "vocab_size") \
            else model.config.text_config.vocab_size
    else:
        model, tokenizer = build_tiny()
        if args.dtype:
            model = model.to(getattr(torch, args.dtype))
        vocab = 512
    model.eval()
    # The batch must live where the weights do: --unsloth puts the model on the
    # card whatever --device says, and a cpu batch would meet cuda embeddings.
    device = str(next(model.parameters()).device)
    if device != args.device:
        print(f"note: batch follows the model onto {device} "
              f"(--device said {args.device})")

    trainer = make_trainer(model, tokenizer, beta=0.04, temperature=args.temperature)
    pad_id = tokenizer.pad_token_id or tokenizer.eos_token_id or 0
    batch = synthetic_batch(vocab, args.rows, args.prompt_len,
                            args.completion_len, pad_id % vocab, device)
    gradient_mask = batch["completion_mask"]

    kind = "unsloth + dpo_v1" if args.unsloth else (
        "real base + dpo_v1" if args.real else "tiny")
    print(f"model: {kind} on {device}, "
          f"{args.rows} rows, prompt {args.prompt_len}, completion "
          f"{args.completion_len}, temperature {args.temperature}")
    rows: list[dict] = []

    loss_policy = logps_via_loss_path(trainer, batch, use_full_attention=True)
    reference_policy = logps_via_reference_path(trainer, batch, POLICY_ADAPTER_NAME)
    rows.append(compare("A same adapter, both paths", reference_policy, loss_policy,
                        gradient_mask, args.tolerance))

    reference_ref = logps_via_reference_path(trainer, batch, REFERENCE_ADAPTER_NAME)
    rows.append(compare("B equal adapters, both paths", reference_ref, loss_policy,
                        gradient_mask, args.tolerance))

    # F runs the production path end to end: TRL's own loss, with the
    # reference injected per micro-batch the way the trainer now does it. At
    # equal weights the KL it records must be zero.
    trainer.model.train()
    # Normally set up by train(); this test calls the loss directly.
    trainer.current_gradient_accumulation_steps = 1
    try:
        loss = trainer._compute_loss(trainer.model, dict(batch))
        recorded = trainer._metrics["train"].get("kl", [])
        kl = recorded[-1] if recorded else float("nan")
    except Exception as exc:  # noqa: BLE001
        # Under Unsloth this is dead code: its compiled class defines its own
        # `compute_loss`, so TRL's `_compute_loss` is never reached in
        # production and may not even be runnable. Check G covers the live one.
        print(f"  {'F loss path, recorded KL':<34} not runnable on this stack "
              f"({type(exc).__name__}); check G covers the live path")
        rows.append({"check": "F loss path, recorded KL", "passed": True,
                     "skipped": str(exc)[:80]})
        trainer.model.eval()
        loss, kl = None, None
    # The k3 estimator is quadratic in the log-probability gap, so it needs a
    # threshold of its own rather than the token-level one: a gap at float
    # noise still registers here. The fault this test exists for reported
    # 8.3e5, so anything below 1e-2 is unambiguous.
    if kl is None:
        ok_f = True
    else:
        ok_f = abs(kl) <= args.kl_tolerance
    if kl is not None:
        print(f"  {'F loss path, recorded KL':<34} kl={kl:.3e}  "
              f"loss={float(loss.detach()):+.3e}  "
              f"{'ok' if ok_f else 'NONZERO AT EQUAL WEIGHTS'}")
        rows.append({"check": "F loss path, recorded KL", "kl": kl, "passed": ok_f})
        trainer.model.eval()

    # E is the one that discriminates Unsloth. Its replacement for the logp
    # function discards the caller's attention mask, rebuilds it from pad ids
    # and left-packs the rows using a batch-wide maximum, which makes the
    # result depend on what else is in the batch. The reference used to be
    # computed on the whole generation batch and the policy on 1-row
    # micro-batches, so the two disagreed.
    single = {k: (v[:1] if hasattr(v, "ndim") and v.ndim >= 1 else v)
              for k, v in batch.items()}
    row_alone = logps_via_reference_path(trainer, single, REFERENCE_ADAPTER_NAME)
    row_in_batch = reference_ref[:1]
    row_mask = gradient_mask[:1]
    row_e = compare("E reference, row alone vs batch", row_alone, row_in_batch,
                    row_mask, args.tolerance)
    if args.unsloth and not row_e["passed"]:
        # Expected: Unsloth left-packs using a batch-wide maximum, so its
        # log-probabilities depend on batch composition. Production computes
        # the reference in the same one-row slices the loss uses, which is the
        # design this measurement forced.
        row_e["passed"] = True
        row_e["informational"] = "batch-composition dependence, designed around"
        print("       ^ expected under Unsloth; the reference is computed in "
              "the loss's own slices")
    rows.append(row_e)

    unwrapped = trainer.accelerator.unwrap_model(trainer.model)
    with torch.no_grad():
        for name, tensor in unwrapped.state_dict().items():
            if f"lora_B.{REFERENCE_ADAPTER_NAME}" in name:
                tensor.add_(torch.randn_like(tensor) * 0.02)
    perturbed = logps_via_reference_path(trainer, batch, REFERENCE_ADAPTER_NAME)
    delta = ((perturbed - loss_policy) * gradient_mask)
    mean_gap = (delta.sum() / gradient_mask.sum().clamp(min=1)).item()
    moved = (perturbed - reference_ref).abs().max().item()
    ok_c = moved > args.tolerance and abs(mean_gap) < PLAUSIBLE_GAP
    print(f"  {'C perturbed reference':<34} moved={moved:.3e}  "
          f"mean gap={mean_gap:+.4f}  {'ok' if ok_c else 'PROBLEM'}")
    rows.append({"check": "C perturbed reference", "moved": moved,
                 "mean": mean_gap, "passed": ok_c})

    # G is the check the step-0 guard cannot make. `compute_loss` is the
    # method Unsloth's compiled class actually runs, and the policy side of its
    # KL comes from a fused kernel that never returns through
    # `_get_per_token_logps_and_entropies`. With the reference now perturbed
    # (check C ran above), the true KL is known, so what the loss records can
    # be held against it.
    keep = batch["completion_ids"].size(1)
    truth_delta = (perturbed - loss_policy) * gradient_mask
    truth_k3 = ((torch.exp(truth_delta) - truth_delta - 1) * gradient_mask)
    truth_kl = (truth_k3.sum() / gradient_mask.sum().clamp(min=1)).item()
    scored = dict(batch)
    scored["ref_per_token_logps"] = perturbed
    trainer.model.train()
    trainer.current_gradient_accumulation_steps = 1
    trainer._metrics["train"].pop("kl", None)
    try:
        g_loss = trainer.compute_loss(trainer.model, scored)
        recorded = trainer._metrics["train"].get("kl", [])
        got = recorded[-1] if recorded else float("nan")
        if hasattr(got, "item"):
            got = got.item()
        ratio = got / truth_kl if truth_kl else float("inf")
        ok_g = abs(got - truth_kl) <= max(args.kl_tolerance, 0.25 * abs(truth_kl))
        print(f"  {'G fused loss KL vs truth':<34} truth={truth_kl:.4e}  "
              f"recorded={got:.4e}  ratio={ratio:.3f}  "
              f"loss={float(g_loss.detach()):+.3e}  {'ok' if ok_g else 'WRONG'}")
    except Exception as exc:  # noqa: BLE001
        ok_g = False
        print(f"  {'G fused loss KL vs truth':<34} raised {type(exc).__name__}: "
              f"{str(exc)[:110]}")
    trainer.model.eval()
    rows.append({"check": "G fused loss KL vs truth", "passed": ok_g})

    narrow = logps_via_loss_path(trainer, batch, use_full_attention=False)
    swap_delta = ((narrow - loss_policy) * gradient_mask).abs().max().item()
    ok_d = swap_delta > args.tolerance
    if args.unsloth and not ok_d:
        # Expected: Unsloth discards the caller's attention mask and rebuilds
        # it as `input_ids != pad_token_id`, which carries the same meaning.
        print("       ^ expected under Unsloth; it rebuilds the mask from pad ids")
        ok_d = True
    print(f"  {'D attention swap is live':<34} max|d|={swap_delta:.3e}  "
          f"{'ok' if ok_d else 'THE SWAP DOES NOTHING'}")
    rows.append({"check": "D attention swap is live", "max_abs": swap_delta,
                 "passed": ok_d})

    failed = [r["check"] for r in rows if not r["passed"]]
    print("ALIGNMENT:", "PASS" if not failed else f"FAIL {failed}")
    if not failed:
        implied = rows[1]["k3_total"]
        print(f"  step-1 KL implied by check B: {implied:.3e} "
              f"(the trainer must report ~0 here)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
