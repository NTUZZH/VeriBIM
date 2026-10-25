#!/bin/bash
# v4e recompute (2026-10-16): rows of the deletion tasks whose outputs were re-run with the repaired
# library (gt_fix/rerun_list_delete_v2.csv, geom_call_ran_clean=1), per arm restricted to the tasks each
# analysis file holds (gt_fix/v4e_work/tmp_v4e_checker_ids.json). One task per invocation, so only one
# edited model (from <run>/<model>/edited_v4e.tar.gz) and one ground truth are unpacked at a time;
# one worker, cores 20-21. Rows go to tmp/v4e/ and are merged into results/ by replace_rows_v4e.py.
# mutation_gate.py rows do not read model outputs (ground truths and the gold script only), so the
# v4e outputs leave them unchanged and they are not recomputed.
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
L=$H/recompute_v4e.log
GL=analysis/revision/ground_truth_repair/refresh_v4e.log
O=$H/tmp/v4e
IDS=analysis/revision/ground_truth_repair/v4e_work/tmp_v4e_checker_ids.json
mkdir -p $O
log(){ echo "$(date '+%F %T') $*" >> $L; echo "$(date '+%F %T') [A] $*" >> $GL; }
guard(){ while [ $(df -BG --output=avail / | tail -1 | tr -dc 0-9) -lt 29 ]; do log "disk below 29 GiB free, waiting"; sleep 60; done; }
step(){ guard; log "start $*"; taskset -c 20-21 $PY -u "$@" >> $O/run.log 2>&1; local rc=$?; log "end $1 $2 $3 exit $rc"; }
ids(){ $PY -c "import json,sys; print(' '.join(json.load(open('$IDS'))['$1']['$2']))"; }
log "v4e recompute start (pid $$)"
# control: an unaffected row through the patched script with the default archive
step $H/gate_abs.py veribim9b_108 --ids WAL-UPD-DIR-G8structure-005 --workers 1 --v4d-out $O/control_gate_veribim9b_108.jsonl --min-free-gb 30.5
for arm in veribim9b_108 base9b_libnote_108 sonnet_lib_108 sonnet_documented_108 gpt_documented_108 gemini_documented_108 deepseek_documented_108 opus_documented_108 veribim9b_2100; do
  for t in $(ids $arm gate); do
    step $H/gate_abs.py $arm --ids $t --workers 1 --v4d-out $O/gate_$arm.jsonl --archive edited_v4e.tar.gz --min-free-gb 30.5
  done
done
for arm in veribim9b_108 sonnet_documented_108 deepseek_documented_108 opus_documented_108 veribim9b_2100; do
  for t in $(ids $arm schema); do
    step $H/schema_clash.py $arm --ids $t --workers 1 --max-src-mb 60 --v4d-out $O/schema_clash_$arm.jsonl --archive edited_v4e.tar.gz --min-free-gb 30.5
  done
done
log "V4E_RECOMPUTE_DONE"
