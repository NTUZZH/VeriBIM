#!/usr/bin/env bash
# Stage A gold trajectory synthesis over a task file's train split.
#
# Resumable: restarting with the same command skips every task the outcomes
# file already accounts for, so an interruption costs only the tasks that were
# in flight.
set -uo pipefail

PROJECT="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONDA_ROOT="${CONDA_ROOT:-$HOME/miniconda3}"
L2_PYTHON="${L2_PYTHON:-$CONDA_ROOT/envs/l2/bin/python}"

TASKS="${TASKS:-$PROJECT/data/veribim_tasks_v1/tasks.jsonl}"
OUT_DIR="${OUT_DIR:-$PROJECT/data/stage_a/v1}"
SCRATCH="${SCRATCH:-$PROJECT/data/stage_a/_work_v1}"
GOLD_CACHE="${GOLD_CACHE:-$PROJECT/data/stage_a/_gold_v1}"
WORKERS="${WORKERS:-6}"
CORES="${CORES:-0-5,8-9}"
SPLIT="${SPLIT:-train}"
LOG="${LOG:-$PROJECT/logs/synthesis_v1.log}"

mkdir -p "$(dirname "$LOG")" "$OUT_DIR" "$SCRATCH" "$GOLD_CACHE"
export PYTHONPATH="$PROJECT/code"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

exec taskset -c "$CORES" "$L2_PYTHON" -u -m stage_a.cli synthesize \
    --tasks-file "$TASKS" --split "$SPLIT" \
    --out-dir "$OUT_DIR" --scratch "$SCRATCH" --gold-cache "$GOLD_CACHE" \
    --workers "$WORKERS" --cores "$CORES" >> "$LOG" 2>&1
