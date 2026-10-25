#!/bin/bash
# Lane 2: mutation re-read under the gate, then schema validation and clashes; one worker, cores 16-23.
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
echo "$(date '+%F %T') lane2 start mutation" >> $H/log.txt
taskset -c 16-23 $PY -u $H/mutation_gate.py --workers 1 >> $H/mutation_run.log 2>&1
echo "$(date '+%F %T') lane2 end mutation exit $?" >> $H/log.txt
for arm in veribim9b_108 sonnet_documented_108 sonnet_lib_108 sonnet_alone_108 base9b_libnote_108; do
  echo "$(date '+%F %T') lane2 start schema_clash $arm" >> $H/log.txt
  taskset -c 16-23 $PY -u $H/schema_clash.py $arm --workers 1 >> $H/schema_run.log 2>&1
  echo "$(date '+%F %T') lane2 end schema_clash $arm exit $?" >> $H/log.txt
done
echo "$(date '+%F %T') LANE2_DONE" >> $H/log.txt
