"""Score a saved adapter on the fixed validation subset, in a process of its own.

This is the safe half of the mid-training measurement. The trainer writes an
adapter on its validation cadence; this module loads the base model, applies that
adapter, and rolls the subset out through the harness's own agent loop, sandbox
and scorer. Because it runs on its own, nothing it does can reach the training
state, and the artifact it measures is exactly the one a later stage would load.

Usage:

    python -m stage_a.validate_checkpoint \\
        --adapter checkpoints/stage_a/<run_id>/val_adapters/step_400 \\
        --n-tasks 100 --out checkpoints/stage_a/<run_id>/validation_step_400.json
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

from . import paths
from .train_args import LORA_TARGET_MODULES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stage-a-validate")
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--model-dir", default=str(paths.BASE_MODEL_DIR))
    parser.add_argument("--tasks-file", default=str(paths.default_tasks_file()))
    parser.add_argument("--task-ids-file", default="")
    parser.add_argument("--n-tasks", type=int, default=100)
    parser.add_argument("--max-seq", type=int, default=8192)
    parser.add_argument("--max-rounds", type=int, default=22)
    parser.add_argument("--max-new-tokens", type=int, default=8192)
    parser.add_argument("--work-root", default="")
    parser.add_argument("--out", default="")
    parser.add_argument("--keep-work", action="store_true")
    args = parser.parse_args(argv)

    import unsloth  # noqa: F401  # must precede peft/transformers imports
    from unsloth import FastLanguageModel

    import torch
    from peft import PeftModel

    from .validate import pick_tasks, run_validation

    paths.ensure_harness_on_path()
    from modifc_harness.prompts import TOOL_SCHEMA

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.model_dir,
        max_seq_length=args.max_seq,
        dtype=torch.bfloat16,
        load_in_4bit=False,
        full_finetuning=False,
    )
    model = PeftModel.from_pretrained(model, args.adapter)
    FastLanguageModel.for_inference(model)
    model.eval()
    if getattr(model, "config", None) is not None:
        model.config.use_cache = True

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    adapter_params = sum(p.numel() for name, p in model.named_parameters()
                         if "lora_" in name)

    tasks = pick_tasks(Path(args.tasks_file), args.n_tasks, args.task_ids_file)
    work_root = Path(args.work_root or (paths.PROJECT_ROOT / "data/stage_a/_val_work"
                                        / Path(args.adapter).name))
    report = run_validation(model, tokenizer, tasks, [TOOL_SCHEMA],
                            work_root=work_root, max_rounds=args.max_rounds,
                            max_new_tokens=args.max_new_tokens)
    report["adapter"] = str(args.adapter)
    report["adapter_params"] = adapter_params
    report["trainable_params_reported"] = trainable
    report["n_tasks_requested"] = args.n_tasks
    report["lora_target_modules"] = sorted(LORA_TARGET_MODULES)
    report["finished_at"] = datetime.now().isoformat(timespec="seconds")

    out = Path(args.out or (Path(args.adapter) / "validation.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not args.keep_work:
        shutil.rmtree(work_root, ignore_errors=True)
    print(json.dumps({"adapter": str(args.adapter), "out": str(out),
                      **report["summary"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
