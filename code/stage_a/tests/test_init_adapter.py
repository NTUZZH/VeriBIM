"""The continue-from-an-adapter path, checked without weights and without a card.

Nothing here loads the base model, and the training stack is replaced by stubs
before the trainer is imported, so every claim below is about argument
plumbing, arithmetic and bookkeeping. Three of the checks carry most of the
weight. An adapter whose rank, alpha, dropout or target modules differ from what
the run would record must abort before any weight is read, because a continued
run that quietly changes shape is the failure a finished run cannot be
distinguished from a good one. The capped replay sample must be the same set on
every run of the same file with the same seed, or the mix a config records is
not the mix that was trained on. And the parameter-count assertion must hold on
the continued path as well as the fresh one.

    python -m stage_a.tests.test_init_adapter
"""

from __future__ import annotations

import json
import sys
import tempfile
import types
from pathlib import Path

from stage_a import paths
from stage_a.train_args import (EXPECTED_ADAPTER_PARAMS, LORA_TARGET_MODULES,
                                adapter_module_names, add_train_arguments,
                                assert_adapter_params, base_config,
                                check_adapter_config, diff_configs,
                                sample_indices)

SFT_V1_ADAPTER = paths.CHECKPOINT_ROOT / "sft_v1/adapter"

#: The saved form Unsloth writes: one regular expression over module paths
#: rather than the list of names it was given.
UNSLOTH_REGEX = (r"(?:.*?(?:language|text).*?(?:self_attn|mlp).*?"
                 r"(?:q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj|"
                 r"in_proj_a|in_proj_b|in_proj_qkv|in_proj_z|out_proj))")


# --------------------------------------------------------------------------
# stubs

def install_training_stubs() -> None:
    """Stand in for the training stack so the trainer imports on a bare CPU."""
    if "stage_a.train_sft" in sys.modules:
        return

    class Dataset(list):
        @classmethod
        def from_list(cls, rows):
            return cls(rows)

    unsloth = types.ModuleType("unsloth")
    unsloth.__version__ = "stub"
    unsloth.FastLanguageModel = object
    torch = types.ModuleType("torch")
    torch.__version__ = "stub"
    torch.bfloat16 = "bfloat16"
    torch.cuda = types.SimpleNamespace(
        memory_reserved=lambda: 0, memory_allocated=lambda: 0,
        max_memory_reserved=lambda: 0, empty_cache=lambda: None)
    datasets = types.ModuleType("datasets")
    datasets.__version__ = "stub"
    datasets.Dataset = Dataset
    transformers = types.ModuleType("transformers")
    transformers.__version__ = "stub"
    transformers.TrainerCallback = type("TrainerCallback", (), {})
    trl = types.ModuleType("trl")
    trl.__version__ = "stub"
    trl.SFTConfig = type("SFTConfig", (), {})
    trl.SFTTrainer = type("SFTTrainer", (), {})
    peft = types.ModuleType("peft")
    peft.__version__ = "stub"
    peft.PeftModel = type("PeftModel", (), {})
    for name, module in [("unsloth", unsloth), ("torch", torch),
                         ("datasets", datasets), ("transformers", transformers),
                         ("trl", trl), ("peft", peft)]:
        sys.modules.setdefault(name, module)


class FakeParameter:
    def __init__(self, n: int, requires_grad: bool) -> None:
        self.n = n
        self.requires_grad = requires_grad

    def numel(self) -> int:
        return self.n


class FakeModel:
    """A model that is nothing but its parameter counts."""

    def __init__(self, trainable: int, frozen: int) -> None:
        self._params = [FakeParameter(trainable, True), FakeParameter(frozen, False)]

    def parameters(self):
        return list(self._params)


def write_adapter_config(directory: Path, **overrides) -> Path:
    config = {"peft_type": "LORA", "r": 16, "lora_alpha": 32, "lora_dropout": 0.0,
              "bias": "none", "use_rslora": False,
              "target_modules": UNSLOTH_REGEX}
    config.update(overrides)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "adapter_config.json").write_text(json.dumps(config), encoding="utf-8")
    return directory


def write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def example(index: int, source: str = "gold", tokens: int = 8,
            learnable: bool = True) -> dict:
    labels = [-100] * tokens
    if learnable:
        labels[-1] = index
    return {"input_ids": list(range(index, index + tokens)), "labels": labels,
            "source": source}


def parse(argv: list[str]):
    import argparse

    parser = argparse.ArgumentParser()
    add_train_arguments(parser)
    return parser.parse_args(argv)


def check(name: str, condition: bool, detail: str = "") -> None:
    if not condition:
        raise AssertionError(f"{name} failed. {detail}")
    print(f"ok  {name}")


def raises_system_exit(call, wanted: str) -> str:
    try:
        call()
    except SystemExit as exc:
        message = str(exc)
        if wanted not in message:
            raise AssertionError(f"expected {wanted!r} in {message!r}") from None
        return message
    raise AssertionError(f"no SystemExit, expected one naming {wanted!r}")


# --------------------------------------------------------------------------
# arguments

def test_arguments() -> None:
    fresh = parse(["--run-id", "r", "--dataset", "d.jsonl"])
    check("defaults leave the fresh path untouched",
          fresh.init_adapter == "" and fresh.replay_dataset == ""
          and fresh.replay_cap == 0)

    args = parse(["--run-id", "sft_v2", "--dataset", "new.jsonl",
                  "--replay-dataset", "old.jsonl", "--replay-cap", "3000",
                  "--init-adapter", str(SFT_V1_ADAPTER)])
    check("the three new options are parsed",
          args.init_adapter == str(SFT_V1_ADAPTER)
          and args.replay_dataset == "old.jsonl" and args.replay_cap == 3000)
    check("the continue run keeps every other default",
          (args.learning_rate, args.lr_scheduler, args.warmup_ratio, args.epochs,
           args.lora_rank, args.lora_alpha, args.seed, args.grad_accum)
          == (1e-4, "cosine", 0.03, 2.0, 16, 32, 42, 64))
    check("the expected parameter count is still the asserted one",
          args.expected_adapter_params == EXPECTED_ADAPTER_PARAMS == 43_278_336)


# --------------------------------------------------------------------------
# the adapter's own configuration

def test_adapter_config() -> None:
    check("the saved regular expression names the target modules",
          adapter_module_names(UNSLOTH_REGEX) == set(LORA_TARGET_MODULES))
    check("a saved list names them too",
          adapter_module_names(list(LORA_TARGET_MODULES)) == set(LORA_TARGET_MODULES))

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = write_adapter_config(root / "good")
        config = check_adapter_config(good, rank=16, alpha=32, dropout=0.0)
        check("a matching adapter is accepted and returned",
              config["r"] == 16 and config["lora_alpha"] == 32)

        cases = [
            ("rank", write_adapter_config(root / "rank", r=32), "rank 32"),
            ("alpha", write_adapter_config(root / "alpha", lora_alpha=16), "alpha 16"),
            ("dropout", write_adapter_config(root / "drop", lora_dropout=0.05),
             "dropout 0.05"),
            ("rslora", write_adapter_config(root / "rs", use_rslora=True), "rslora"),
            ("a missing module",
             write_adapter_config(root / "missing",
                                  target_modules=[m for m in LORA_TARGET_MODULES
                                                  if m != "out_proj"]),
             "missing ['out_proj']"),
            ("an extra module",
             write_adapter_config(root / "extra",
                                  target_modules=list(LORA_TARGET_MODULES)
                                  + ["cross_proj"]),
             "extra ['cross_proj']"),
        ]
        for name, directory, wanted in cases:
            raises_system_exit(
                lambda d=directory: check_adapter_config(d, rank=16, alpha=32,
                                                         dropout=0.0), wanted)
            print(f"ok  {name} aborts before training")

        raises_system_exit(
            lambda: check_adapter_config(root / "absent", rank=16, alpha=32,
                                         dropout=0.0), "does not exist")
        print("ok  a directory that is not an adapter aborts before training")

        message = raises_system_exit(
            lambda: check_adapter_config(write_adapter_config(root / "two", r=8,
                                                              lora_alpha=64),
                                         rank=16, alpha=32, dropout=0.0), "rank 8")
        check("every mismatch is reported at once", "alpha 64" in message, message)

    if (SFT_V1_ADAPTER / "adapter_config.json").exists():
        config = check_adapter_config(SFT_V1_ADAPTER, rank=16, alpha=32, dropout=0.0)
        check("the sft_v1 adapter passes the check the launch will make",
              config["r"] == 16 and config["lora_alpha"] == 32)
    else:
        print("skip sft_v1 adapter not on this machine")


# --------------------------------------------------------------------------
# the parameter count, on both paths

def test_parameter_count() -> None:
    model = FakeModel(EXPECTED_ADAPTER_PARAMS, 9_409_813_744)
    trainable, total = assert_adapter_params(model, EXPECTED_ADAPTER_PARAMS,
                                             continued=True)
    check("a continued adapter of the right shape passes",
          trainable == EXPECTED_ADAPTER_PARAMS
          and total == EXPECTED_ADAPTER_PARAMS + 9_409_813_744)

    short = FakeModel(29_602, 9_409_813_744)
    message = raises_system_exit(
        lambda: assert_adapter_params(short, EXPECTED_ADAPTER_PARAMS,
                                      continued=True), "29,602")
    check("the continued path names the adapter it was continuing",
          "continues" in message, message)
    raises_system_exit(
        lambda: assert_adapter_params(short, EXPECTED_ADAPTER_PARAMS), "29,602")
    print("ok  the fresh path keeps the same assertion")


# --------------------------------------------------------------------------
# the seeded cap

def test_sample_indices() -> None:
    check("no cap keeps the file", sample_indices(10, 0, 42) == list(range(10)))
    check("a cap above the file keeps the file",
          sample_indices(10, 25, 42) == list(range(10)))
    first = sample_indices(1000, 40, 42)
    check("a cap keeps exactly N, in file order",
          len(first) == 40 and first == sorted(first) and len(set(first)) == 40
          and max(first) < 1000)
    check("the same seed keeps the same examples",
          sample_indices(1000, 40, 42) == first)
    check("a different seed keeps different ones",
          sample_indices(1000, 40, 43) != first)


# --------------------------------------------------------------------------
# mixing the new file with the replay file

def test_dataset_mixing() -> None:
    install_training_stubs()
    from stage_a.train_sft import combine_stats, load_training_data, read_examples

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        new = write_jsonl(root / "new.jsonl",
                          [example(i, "new_family") for i in range(50)]
                          + [example(900, "new_family", learnable=False)])
        old = write_jsonl(root / "old.jsonl",
                          [example(i, "gold") for i in range(400)])

        rows, stats = read_examples(new, None, [], max_seq=8192)
        check("an example with nothing to learn from is dropped",
              stats["n"] == 51 and stats["dropped"] == 1 and stats["kept"] == 50
              and len(rows) == 50, json.dumps(stats))

        dataset, mixed = load_training_data(
            [(new, 0, "primary"), (old, 100, "replay")],
            tokenizer=None, tools=[], max_seq=8192, seed=42)
        check("the mixed set is the new file plus the capped replay sample",
              len(dataset) == 150 and mixed["kept"] == 150, json.dumps(mixed["files"]))
        check("each file's counts are recorded on their own",
              [(f["role"], f["usable"], f["cap"], f["kept"]) for f in mixed["files"]]
              == [("primary", 50, 0, 50), ("replay", 400, 100, 100)])
        check("the sources are counted across the mix",
              mixed["by_source"] == {"new_family": 50, "gold": 100})
        check("the dropped example is still reported after the mix",
              mixed["n"] == 451 and mixed["dropped"] == 1)
        check("the token counts describe the capped set, not the file",
              mixed["total_tokens"] == 150 * 8
              and mixed["assistant_tokens"] == 150)

        again, _ = load_training_data([(new, 0, "primary"), (old, 100, "replay")],
                                      tokenizer=None, tools=[], max_seq=8192, seed=42)
        check("the same seed mixes the same examples",
              [r["input_ids"] for r in again] == [r["input_ids"] for r in dataset])
        other, _ = load_training_data([(new, 0, "primary"), (old, 100, "replay")],
                                      tokenizer=None, tools=[], max_seq=8192, seed=7)
        check("another seed draws another replay sample",
              [r["input_ids"] for r in other] != [r["input_ids"] for r in dataset])

        _, uncapped = load_training_data([(new, 0, "primary"), (old, 0, "replay")],
                                         tokenizer=None, tools=[], max_seq=8192,
                                         seed=42)
        check("no cap replays the whole file", uncapped["kept"] == 450)

        single, alone = load_training_data([(new, 0, "primary")], tokenizer=None,
                                           tools=[], max_seq=8192, seed=42)
        check("one file still gives the counts the fresh run recorded",
              len(single) == 50 and alone["kept"] == 50
              and alone["by_source"] == {"new_family": 50})
        check("combining one file changes nothing",
              combine_stats([alone["files"][0]])["kept"] == 50)


# --------------------------------------------------------------------------
# what the resolved configuration records

def test_recorded_config() -> None:
    versions = {"torch": "stub"}
    fresh = base_config(parse(["--run-id", "sft_v1", "--dataset", "old.jsonl"]),
                        versions, {"init_adapter": None, "init_adapter_config": None})
    adapter_config = {"r": 16, "lora_alpha": 32}
    continued = base_config(
        parse(["--run-id", "sft_v2", "--dataset", "new.jsonl",
               "--replay-dataset", "old.jsonl", "--replay-cap", "3000",
               "--init-adapter", str(SFT_V1_ADAPTER)]),
        versions, {"init_adapter": str(SFT_V1_ADAPTER),
                   "init_adapter_config": adapter_config})
    check("the adapter and its own configuration are recorded",
          continued["init_adapter"] == str(SFT_V1_ADAPTER)
          and continued["init_adapter_config"] == adapter_config)

    # ``started_at`` is a timestamp, so it differs or not depending on which
    # second the two configurations were built in, and it is set aside here.
    differing = {line.split(":")[0] for line in diff_configs(continued, fresh)}
    differing.discard("started_at")
    expected = {"init_adapter", "init_adapter_config",
                "cli_args.run_id", "cli_args.dataset", "cli_args.init_adapter",
                "cli_args.replay_dataset", "cli_args.replay_cap"}
    check("the diff against a fresh run is the new fields and the paths alone",
          differing == expected, f"unexpected {sorted(differing - expected)}, "
          f"missing {sorted(expected - differing)}")


def main() -> int:
    for test in (test_arguments, test_adapter_config, test_parameter_count,
                 test_sample_indices, test_dataset_mixing, test_recorded_config):
        print(f"\n== {test.__name__}")
        test()
    print("\nall checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
