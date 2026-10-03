#!/usr/bin/env bash
# Serve the pinned base with the Stage A artifact attached, behind the template
# it was trained with.
set -uo pipefail
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
ADAPTER="${ADAPTER:-$PROJECT/checkpoints/stage_a/sft_v1/val_adapters/step_590}"
NAME="${NAME:-sft590}"
PORT="${PORT:-8000}"
CORES="${CORES:-10-11}"
LOG="${LOG:-$PROJECT/logs/stage_b_serve.log}"
export VLLM_USE_FLASHINFER_SAMPLER=0
mkdir -p "$(dirname "$LOG")"
exec taskset -c "$CORES" "$CONDA_ROOT/envs/l2vllm/bin/vllm" serve "${BASE_MODEL:-$PROJECT/models/Qwen3.5-9B}" \
  --served-model-name Qwen3.5-9B --port "$PORT" --host 127.0.0.1 \
  --max-model-len 65536 --gpu-memory-utilization 0.777 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --chat-template "$PROJECT/code/stage_a/chat_template_veribim.jinja" \
  --language-model-only \
  --enable-lora --max-lora-rank 16 --max-loras 1 \
  --lora-modules "$NAME=$ADAPTER" >> "$LOG" 2>&1
