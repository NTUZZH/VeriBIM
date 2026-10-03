#!/usr/bin/env bash
# Run the bake-off slice for every candidate model, one server at a time.
#
# Usage: scripts/run_bakeoff.sh [model-tag ...]
#
# Each model gets its own server, started and shut down by the harness, with the
# GPU checked back to its pre-launch state before the next one begins. Sandbox
# work is single-threaded on purpose: one worker at a time, thread pools capped,
# so a CPU-heavy job sharing the machine keeps its cores.
set -uo pipefail

HARNESS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$HARNESS_DIR/../.." && pwd)"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
L2_PYTHON="${L2_PYTHON:-$CONDA_ROOT/envs/l2/bin/python}"

SLICE="${SLICE:-$PROJECT_ROOT/phase0/bakeoff_slice_v1.json}"
RESULTS="${RESULTS:-$PROJECT_ROOT/runs_local}"
LOGS="${LOGS:-$PROJECT_ROOT/logs/serve}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-65536}"
HEADROOM="${HEADROOM:-3072}"

MODELS=("$@")
if [ ${#MODELS[@]} -eq 0 ]; then
  MODELS=(granite-4.1-8b Qwen3.5-9B Falcon-H1R-7B gemma-4-12b-it)
fi

mkdir -p "$LOGS"

# Be a quiet neighbour on the CPU: the sandbox is one process at a time and
# needs no thread pool of its own.
export OMP_NUM_THREADS=2
export MKL_NUM_THREADS=2
export OPENBLAS_NUM_THREADS=2

for MODEL in "${MODELS[@]}"; do
  echo "=================================================================="
  echo "$(date -Is)  starting bake-off for $MODEL"
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
  ( cd "$HARNESS_DIR" && "$L2_PYTHON" -m modifc_harness.cli bakeoff \
      --model "$MODEL" \
      --slice-file "$SLICE" \
      --results-dir "$RESULTS" \
      --max-model-len "$MAX_MODEL_LEN" \
      --headroom-mib "$HEADROOM" \
      --max-restarts 3 \
      --notes "bake-off slice v1, 40 tasks" ) 2>&1 | tee "$LOGS/bakeoff_$MODEL.log"
  STATUS=${PIPESTATUS[0]}
  echo "$(date -Is)  $MODEL finished with status $STATUS"
  nvidia-smi --query-gpu=memory.used,memory.free --format=csv,noheader
  nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader
done

echo "$(date -Is)  all models done"
