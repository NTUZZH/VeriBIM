#!/bin/bash
# v4d recompute (2026-10-16): only the rows that depend on a repaired ground truth (gt_fix/affected_tasks.txt)
# or on a re-run output (gt_fix/rerun_list.csv); one worker, cores 16-19; rows go to tmp/v4d/ and are merged
# into results/ afterwards by replace_rows_v4d.py. Settings otherwise as run_gate.sh / run_lane2.sh / run_schema_lanes.sh.
H=analysis/revision/checker_validity
export PYTHONPATH=code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
L=$H/recompute_v4d.log
O=$H/tmp/v4d
mkdir -p $O
until grep -q "GOLD_V4D DONE" $H/tmp/build_gold_v4d.out; do sleep 20; done
echo "$(date '+%F %T') gold_v4d built: $(ls $H/gold_v4d/*.ifc.gz | wc -l) archives" >> $L
A108=CHN-DWF-SPA-B02-004,COL-DEL-DIR-B46m4-002,CHN-DWF-TOP-B02m4X3-008
A2100=$(paste -sd, analysis/revision/ground_truth_repair/affected_tasks.txt),DOR-UPD-DIR-B16-011
step(){ echo "$(date '+%F %T') start $*" >> $L; taskset -c 16-19 $PY -u "$@" >> $O/run.log 2>&1; echo "$(date '+%F %T') end $1 $2 exit $?" >> $L; }
# 1. relation gate and absolute errors
for arm in veribim9b_108 base9b_libnote_108 sonnet_alone_108 sonnet_lib_108 sonnet_documented_108 gpt_documented_108 gemini_documented_108 deepseek_documented_108 opus_documented_108; do
  step $H/gate_abs.py $arm --ids $A108 --workers 1 --v4d-out $O/gate_$arm.jsonl
done
step $H/gate_abs.py veribim9b_2100 --ids $A2100 --workers 1 --v4d-out $O/gate_veribim9b_2100.jsonl
# 2. mutation study: the five sampled tasks among the 69
step $H/mutation_gate.py --ids COL-DEL-DIR-B46m4X3-024,COL-DEL-SPA-B46-004,DOR-UPD-DIR-B02m4X3-003,DOR-UPD-TOP-G7arcm4-015,SPC-DEL-DIR-B27-001 --workers 1 --v4d-out $O/mutation_gate.jsonl
# 3. schema validation and clashes: the affected tasks present in each arm's file (sources <= 60 MB)
for arm in veribim9b_108 base9b_libnote_108 sonnet_alone_108 sonnet_lib_108 sonnet_documented_108 gpt_documented_108 gemini_documented_108 deepseek_documented_108 opus_documented_108; do
  step $H/schema_clash.py $arm --ids COL-DEL-DIR-B46m4-002 --workers 1 --max-src-mb 60 --v4d-out $O/schema_clash_$arm.jsonl
done
step $H/schema_clash.py veribim9b_2100 --ids COL-DEL-DIR-B46m4-022,DOR-UPD-TOP-G7arc-011,SPC-DEL-SPA-B27m4X3-001 --workers 1 --max-src-mb 60 --v4d-out $O/schema_clash_veribim9b_2100.jsonl
echo "$(date '+%F %T') V4D_RECOMPUTE_DONE" >> $L
