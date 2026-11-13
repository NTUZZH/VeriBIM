#!/usr/bin/env bash
# Stage A rejection-sampling harvest on the wave-1 train split.
#
# The sampler hands the card back itself when the budget is spent.
set -uo pipefail

PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
L2_PYTHON="${L2_PYTHON:-$CONDA_ROOT/envs/l2/bin/python}"

RUN_DIR="${RUN_DIR:-$PROJECT/runs_local/stage_a_sample_v1_wave1}"
TASKS="${TASKS:-$PROJECT/data/veribim_tasks_v1/tasks.jsonl}"
HOURS="${HOURS:-8}"
K="${K:-8}"
CONCURRENCY="${CONCURRENCY:-24}"
ROUNDS="${ROUNDS:-16}"
MAX_SOURCE_MB="${MAX_SOURCE_MB:-40}"
SANDBOX_CORES="${SANDBOX_CORES:-0-5}"
SERVER_CORES="${SERVER_CORES:-6-7}"
LOG="${LOG:-$PROJECT/logs/harvest_wave1.log}"

mkdir -p "$(dirname "$LOG")" "$RUN_DIR"
export PYTHONPATH="$PROJECT/code"
export VLLM_USE_FLASHINFER_SAMPLER=0
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

exec taskset -c "$SANDBOX_CORES" "$L2_PYTHON" -u -c "
import json, sys
sys.path.insert(0, '$PROJECT/code')
from pathlib import Path
from stage_a.sample import harvest_sampling_run

outcome = harvest_sampling_run(
    model_tag='Qwen3.5-9B',
    tasks_file=Path('$TASKS'),
    run_dir=Path('$RUN_DIR'),
    hours=$HOURS,
    k=$K,
    concurrency=$CONCURRENCY,
    max_tool_rounds=$ROUNDS,
    max_source_mb=$MAX_SOURCE_MB,
    sandbox_cores='$SANDBOX_CORES',
    server_cores='$SERVER_CORES',
)
print(json.dumps(outcome, indent=2), flush=True)
" >> "$LOG" 2>&1
