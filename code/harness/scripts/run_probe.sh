#!/usr/bin/env bash
# Bootstrap probe: sample k trajectories per task from each base model.
#
# Usage: scripts/run_probe.sh [model-tag ...]
#
# One server at a time, started and shut down by the harness, with the card
# checked back to its pre-launch state between models. Sampling is on, so the
# question is not what the model does deterministically but whether it produces
# anything usable at all when given several attempts.
set -uo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$HARNESS_DIR/../.." && pwd)"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
L2_PYTHON="${L2_PYTHON:-$CONDA_ROOT/envs/l2/bin/python}"

RESULTS="${RESULTS:-$PROJECT_ROOT/runs_local}"
LOGS="${LOGS:-$PROJECT_ROOT/logs/serve}"
K="${K:-8}"
TEMPERATURE="${TEMPERATURE:-0.8}"
TOP_P="${TOP_P:-0.95}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-65536}"
HEADROOM="${HEADROOM:-3072}"

MODELS=("$@")
if [ ${#MODELS[@]} -eq 0 ]; then
  MODELS=(Qwen3.5-9B granite-4.1-8b)
fi

mkdir -p "$LOGS"
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2

for MODEL in "${MODELS[@]}"; do
  echo "=================================================================="
  echo "$(date -Is)  starting probe for $MODEL"
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
  ( cd "$HARNESS_DIR" && "$L2_PYTHON" -m modifc_harness.cli probe \
      --model "$MODEL" \
      --k "$K" \
      --temperature "$TEMPERATURE" \
      --top-p "$TOP_P" \
      --results-dir "$RESULTS" \
      --max-model-len "$MAX_MODEL_LEN" \
      --headroom-mib "$HEADROOM" \
      --max-restarts 3 \
      --notes "Stage-A bootstrap probe, k=$K at T=$TEMPERATURE" ) 2>&1 | tee "$LOGS/probe_$MODEL.log"
  echo "$(date -Is)  $MODEL probe finished with status ${PIPESTATUS[0]}"
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
  nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
done

echo "$(date -Is)  all probes done"
