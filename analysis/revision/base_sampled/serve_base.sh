#!/usr/bin/env bash
# Serve the untrained Qwen3.5-9B with the model's own chat template and the Qwen3 reasoning parser,
# so one server answers both arms (thinking off / on via chat_template_kwargs). Cores 18-19,
# about 22 GB of card memory.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
LOG=analysis/revision/base_sampled/serve_base.log
export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1
exec taskset -c 18-19 "${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm/bin/vllm" serve "${BASE_MODEL:-models/Qwen3.5-9B}" \
  --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 \
  --max-model-len 32768 --gpu-memory-utilization 0.45 --max-num-seqs 32 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml --reasoning-parser qwen3 \
  --chat-template "${BASE_MODEL:-models/Qwen3.5-9B}/chat_template.jinja" \
  --language-model-only >> "$LOG" 2>&1
