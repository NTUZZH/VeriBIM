#!/bin/bash
# Analysis 3 driver: one lane (one worker) per call, source models above 60 MB left out.
# usage: run_schema_lanes.sh <lane name> <arm spec> [<arm spec> ...]; an arm spec is "arm[:extra args]"
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
lane=$1; shift
for spec in "$@"; do
  arm=${spec%%:*}; extra=""; [ "$spec" != "$arm" ] && extra=${spec#*:}
  echo "$(date '+%F %T') $lane start schema_clash $arm $extra" >> $H/log.txt
  taskset -c 16-23 $PY -u $H/schema_clash.py $arm --workers 1 --max-src-mb 60 $extra >> $H/schema_run_$lane.log 2>&1
  echo "$(date '+%F %T') $lane end schema_clash $arm exit $?" >> $H/log.txt
done
echo "$(date '+%F %T') ${lane}_DONE" >> $H/log.txt
