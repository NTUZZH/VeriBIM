#!/bin/bash
# Refresh the 2026-10-07 statistics inputs of make_macros_rev.py after the v4d/v4e ground-truth repairs (cores 16-19).
cd "$(dirname "${BASH_SOURCE[0]}")/../../../.."
L=analysis/revision/ground_truth_repair/v4e_work/D_logs2
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
E="env OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1"
for s in cluster_boot failure_ends subset_stats extend_fully_specified; do
  echo "$(date '+%F %T') START $s"
  taskset -c 16-19 $E $PY analysis/revision/stats/$s.py > $L/s_$s.log 2>&1; echo "$(date '+%F %T') END $s rc=$?"
done
echo "$(date '+%F %T') START small_chain"
taskset -c 16-19 $E $PY runs_local/small_v10/small_chain_macros.py dpo_small_c12 grpo_small_c10 > analysis/revision/ground_truth_repair/v4e_work/macros_small_chain.new.tex 2> $L/s_small_chain.err; echo "$(date '+%F %T') END small_chain rc=$?"
echo "$(date '+%F %T') ALL DONE"
