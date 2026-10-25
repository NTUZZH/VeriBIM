#!/bin/bash
# Analyses 1-2, lane 1: one worker, cores 16-23 (memory limit: one ~3 GB worker per lane).
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
run(){ echo "$(date '+%F %T') lane1 start $*" >> $H/log.txt; taskset -c 16-23 $PY -u $H/gate_abs.py "$@" --workers 1 >> $H/gate_run.log 2>&1; echo "$(date '+%F %T') lane1 end $* exit $?" >> $H/log.txt; }
run sonnet_alone_108 --ids $(cat $H/work/redo_sonnet_alone_108.txt)
run sonnet_lib_108 --ids $(cat $H/work/redo_sonnet_lib_108.txt)
run opus_documented_108
run gemini_documented_108
run deepseek_documented_108
run veribim9b_2100
echo "$(date '+%F %T') LANE1_DONE" >> $H/log.txt
