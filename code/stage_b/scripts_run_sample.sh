#!/usr/bin/env bash
# Stage B on-policy sampling over the wave-1 subset. Resumable: restarting with
# the same command skips every task already written to rollouts.jsonl.
set -uo pipefail
PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
CORES="${CORES:-0-9}"
CONC="${CONC:-14}"
SCORERS="${SCORERS:-4}"
K="${K:-6}"
RUN_DIR="${RUN_DIR:-$PROJECT/runs_local/stage_b_sample_v1}"
LOG="${LOG:-$PROJECT/logs/stage_b_sample.log}"
export PYTHONPATH="$PROJECT/code" OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
mkdir -p "$(dirname "$LOG")"
exec taskset -c "$CORES" "$CONDA_ROOT/envs/l2/bin/python" -u -m stage_b.cli sample \
  --k "$K" --concurrency "$CONC" --score-workers "$SCORERS" \
  --large-concurrency "${LARGE_CONC:-3}" --run-dir "$RUN_DIR" --gold-cache "$PROJECT/data/stage_b/_gold" >> "$LOG" 2>&1
