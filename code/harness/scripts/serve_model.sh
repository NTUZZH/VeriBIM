#!/usr/bin/env bash
# Start one vLLM server for a candidate model.
#
# Usage: scripts/serve_model.sh <model-tag> [port] [max-model-len] [headroom-mib]
#
# The memory pool is sized against the memory free on the card at launch, so a
# process belonging to somebody else is never squeezed. The conda environment
# comes from the model's own entry, because one candidate needs a pinned
# transformers version and therefore its own environment.
set -euo pipefail

MODEL="${1:?usage: serve_model.sh <model-tag> [port] [max-model-len] [headroom-mib]}"
PORT="${2:-8000}"
MAX_LEN="${3:-32768}"
HEADROOM="${4:-3072}"

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
L2_PYTHON="${L2_PYTHON:-$CONDA_ROOT/envs/l2/bin/python}"

CMD=$(cd "$HARNESS_DIR" && "$L2_PYTHON" -m modifc_harness.cli serve-command \
        --model "$MODEL" --port "$PORT" --max-model-len "$MAX_LEN" \
        --headroom-mib "$HEADROOM" 2>/dev/null)
ENV_NAME=$(cd "$HARNESS_DIR" && "$L2_PYTHON" -m modifc_harness.cli serve-env --model "$MODEL")

echo "environment:   $ENV_NAME"
echo "serve command: $CMD"

source "$CONDA_ROOT/etc/profile.d/conda.sh"
conda activate "$ENV_NAME"

# FlashInfer builds its sampling kernels with the CUDA 13.3 nvcc bundled in this
# environment against CUDA 13.0 runtime headers, and the CCCL header check
# rejects the mismatch, so the engine dies during warm-up. The sampler is
# optional; vLLM's own implementation is used instead.
export VLLM_USE_FLASHINFER_SAMPLER="${VLLM_USE_FLASHINFER_SAMPLER:-0}"

exec $CMD
