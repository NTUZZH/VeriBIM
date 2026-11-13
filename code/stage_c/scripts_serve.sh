#!/usr/bin/env bash
# Sampling server for Stage C: the pinned base behind the canonical template,
# starting from dpo_v1, with runtime LoRA updating enabled so the
# trainer can swap in the current policy each optimizer step.
#
# The memory fraction is deliberately low. Unlike Stage A and B, the trainer
# runs on the SAME card at the same time, so the server takes only what it
# needs: 18 GB of weights plus roughly 3.5 GB of KV cache. Eight of the 32
# layers use full attention, so a token of KV costs 32 KiB and 3.5 GB carries
# about 110k tokens, comfortably above 16 concurrent rollouts.
set -uo pipefail
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
ADAPTER="${ADAPTER:-$PROJECT/checkpoints/stage_b/dpo_v1/adapter}"
NAME="${NAME:-dpo_v1}"
PORT="${PORT:-8000}"
CORES="${CORES:-10-11}"
UTIL="${UTIL:-0.46}"
MAXLEN="${MAXLEN:-32768}"
LOG="${LOG:-$PROJECT/logs/stage_c_serve.log}"
export VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ALLOW_RUNTIME_LORA_UPDATING=1
export VLLM_USE_FLASHINFER_SAMPLER=0
mkdir -p "$(dirname "$LOG")"
exec taskset -c "$CORES" "$CONDA_ROOT/envs/l2vllm/bin/vllm" serve "${BASE_MODEL:-$PROJECT/models/Qwen3.5-9B}" \
  --served-model-name Qwen3.5-9B --port "$PORT" --host 127.0.0.1 \
  --max-model-len "$MAXLEN" --gpu-memory-utilization "$UTIL" \
  --max-num-seqs 64 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml \
  --chat-template "$PROJECT/code/stage_a/chat_template_veribim.jinja" \
  --language-model-only \
  --enable-lora --max-lora-rank 16 --max-loras 1 --max-cpu-loras 2 \
  --lora-modules "$NAME=$ADAPTER" >> "$LOG" 2>&1
