#!/usr/bin/env bash
# Serve the pinned base with the Stage A LoRA snapshots attached.
#
# Same serve flags as the harvest run (tool parser, chat template, text-only),
# plus LoRA.
set -uo pipefail
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
CK="${CK:-$PROJECT/checkpoints/stage_a/sft_v1/val_adapters}"
PORT="${PORT:-8000}"
LOG="${LOG:-$PROJECT/logs/serve_lora.log}"
MAXLEN="${MAXLEN:-65536}"
UTIL="${UTIL:-0.777}"
CORES="${CORES:-10-15}"

export VLLM_USE_FLASHINFER_SAMPLER=0
mkdir -p "$(dirname "$LOG")"
exec taskset -c "$CORES" "$CONDA_ROOT/envs/l2vllm/bin/vllm" serve "${BASE_MODEL:-$PROJECT/models/Qwen3.5-9B}" \
  --served-model-name Qwen3.5-9B \
  --port "$PORT" --host 127.0.0.1 \
  --max-model-len "$MAXLEN" \
  --gpu-memory-utilization "$UTIL" \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --chat-template "${CHAT_TEMPLATE:-${BASE_MODEL:-$PROJECT/models/Qwen3.5-9B}/chat_template.jinja}" \
  --language-model-only \
  --enable-lora --max-lora-rank 16 --max-loras 1 \
  --lora-modules "sft200=$CK/step_200" "sft400=$CK/step_400" "sft590=$CK/step_590" \
  >> "$LOG" 2>&1
