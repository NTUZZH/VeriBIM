#!/bin/bash
# Lane 1, second part: schema validation and clashes for the arms lane 2 does not take; one worker.
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
until grep -q LANE1_DONE $H/log.txt; do sleep 30; done
run(){ echo "$(date '+%F %T') lane1b start schema_clash $*" >> $H/log.txt; taskset -c 16-23 $PY -u $H/schema_clash.py "$@" --workers 1 >> $H/schema_run_b.log 2>&1; echo "$(date '+%F %T') lane1b end schema_clash $* exit $?" >> $H/log.txt; }
run veribim9b_2100 --sample 300 --take 100 --seed 20261015
run opus_documented_108
run gpt_documented_108
run gemini_documented_108
run deepseek_documented_108
echo "$(date '+%F %T') LANE1B_DONE" >> $H/log.txt
