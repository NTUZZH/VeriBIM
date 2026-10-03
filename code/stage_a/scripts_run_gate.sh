#!/usr/bin/env bash
# Stage A gate measurement over the fixed validation subset, under the frozen
# protocol. Detached; the server is started separately and outlives it.
set -uo pipefail
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
ADAPTERS="${ADAPTERS:-sft590 sft400 sft200}"
CORES="${CORES:-0-9}"
CONC="${CONC:-16}"
LOG="${LOG:-$PROJECT/logs/gate_eval.log}"
export PYTHONPATH="$PROJECT/code"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p "$(dirname "$LOG")"
exec taskset -c "$CORES" "$CONDA_ROOT/envs/l2/bin/python" -u -m stage_a.run_gate \
  --adapters $ADAPTERS --concurrency "$CONC" --score-workers 6 \
  >> "$LOG" 2>&1
