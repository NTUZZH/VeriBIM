#!/bin/bash
# Template parser on the colleague-written requests (packet A), 1 worker, cores 22-23.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)" || exit 1
H=analysis/revision/parser_baseline; C=analysis/revision/colleague_packets
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
echo "$(date '+%F %T') START parser on colleague requests"
taskset -c 22-23 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u $H/run_parser.py --tasks $C/results/rewrite_tasks.jsonl --out $C/results/parser/per_task_parser_colleague.jsonl --workers 1 --tmp $C/results/parser/tmp --gold-cache $H/tmp/gold_cache
echo "$(date '+%F %T') END rc=$?"
