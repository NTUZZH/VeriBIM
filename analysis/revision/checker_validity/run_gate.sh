#!/bin/bash
# Analyses 1-2 driver: one arm at a time on cores 16-23, four workers.
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
for arm in "$@"; do
  echo "$(date '+%F %T') start $arm free $(df -h / | awk 'NR==2{print $4}')" >> $H/log.txt
  taskset -c 16-23 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u $H/gate_abs.py $arm --workers 4 >> $H/gate_run.log 2>&1
  echo "$(date '+%F %T') end $arm exit $?" >> $H/log.txt
done
echo "$(date '+%F %T') GATE_BATCH_DONE $*" >> $H/log.txt
