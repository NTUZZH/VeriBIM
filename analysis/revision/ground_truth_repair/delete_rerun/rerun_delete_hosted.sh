#!/bin/bash
# v4e deletion re-run, commercial arms. Re-runs, on tasks.v4d.jsonl, the hosted outputs of gt_fix/rerun_list_delete_v2.csv
# (deletion helper of the shared library ran without error on a deletion task whose ground truth was repaired): 16 jobs,
# 37 rows, in hosted108_informed_all (5 models), hosted108_informed_rep2_all / rep3_all, hosted108_lib_all (Claude Sonnet,
# Gemini, DeepSeek), hosted108_asknote_all (4 models), hosted216_lib_all and hosted324rest_informed_all (Claude Sonnet).
# hosted324_lib_all needs no run: its 4 rows are the hosted108_lib_all and hosted216_lib_all rows (composite arm);
# splice_delete.py takes them from those two re-runs.
# Settings per job from delete_rerun/plan.json, as the original launchers set them (eval_bench_v4.sh, eval_informed.sh,
# eval_informed4.sh, eval_rerun.sh, eval_informed216.sh, run_hosted_extension.sh): note file (md5 checked), request style
# (Claude anthropic_native, GPT gpt5 with VERIBIM_REASONING_EFFORT=none, Gemini and DeepSeek unset), base URL. Sandbox
# guard and Landlock on, protocol 22 rounds / 420 s / 8192 tokens / temperature 0, family reading, concurrency 4
# (HOSTED_CONC, 4 to 8), 2 score workers, harness on cores 20-23.
# The API key is read from ~/.config/veribim/keys.env into VERIBIM_API_KEY inside each job's subshell; it is never
# printed or logged. Output: delete_rerun/<run>/per_task_<model>.jsonl, cost_<model>.json (list prices of
# runs_local/bench_v4/hosted_cost.py), DONE_<model>; RERUN_DELETE_HOSTED_ALL_DONE at the end. Resumable as the local script.
# Refuses to start a job while the local script's single-edit latency read runs (delete_rerun/SOLO_RUNNING).
# Run detached:
#   setsid nohup bash analysis/revision/ground_truth_repair/delete_rerun/rerun_delete_hosted.sh \
#     > analysis/revision/ground_truth_repair/delete_rerun/logs/rerun_delete_hosted.out 2>&1 < /dev/null &
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"; G=$P/analysis/revision/ground_truth_repair; D=$G/delete_rerun; B=$P/runs_local/bench_v4
TASKS=$B/tasks.v4d.jsonl; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; KEYS=$HOME/.config/veribim/keys.env
CORES=${CORES:-20-23}; CONC=${HOSTED_CONC:-4}; SW=2; MIN_AVAIL_GB=${MIN_AVAIL_GB:-24}; MIN_FREE_RUN_GB=${MIN_FREE_RUN_GB:-8}; PACK=${PACK_EDITED:-1}
LOG=$D/logs/rerun_delete_hosted.log; mkdir -p $D/logs
export PYTHONNOUSERSITE=1
say(){ echo "$(date '+%F %T') $* (disk $(df -BG --output=avail "$HOME" | tail -1 | tr -d ' ') free, mem $(awk '/MemAvailable/ {printf "%dG", $2/1048576}' /proc/meminfo) avail)" >> $LOG; }
fail(){ say "FAILED: $*"; touch $D/RERUN_DELETE_HOSTED_FAILED; exit 1; }
cd $P
MYPGID=$(ps -o pgid= -p $$ | tr -d ' ')
[ "$CONC" -ge 4 ] && [ "$CONC" -le 8 ] || fail "HOSTED_CONC must be 4 to 8"
[ -s $TASKS ] || fail "no $TASKS"
[ "$(md5sum $TASKS | cut -c1-32)" = "$($PY -c "import json; print(json.load(open('$D/plan.json'))['tasks_file_md5'])")" ] || fail "tasks.v4d.jsonl differs from the plan's"
$PY -c "
import hashlib, json, sys
p = json.load(open('$D/plan.json'))
for k in ('geom_lib', 'goldlib'):
    if hashlib.md5(open(p[k], 'rb').read()).hexdigest() != p[k + '_md5']: sys.exit(k)
" || fail "the installed veribim_geom.py / goldlib.py is not the repaired version recorded in plan.json"
mapfile -t JOBS < <($PY $D/plan_tool.py jobs hosted)
[ ${#JOBS[@]} -gt 0 ] || fail "no hosted jobs in plan.json"
for l in "${JOBS[@]}"; do IFS=$'\t' read -r _ _ _ _ _ _ _ _ _ _ KEY _ <<< "$l"
  grep -q "^$KEY=." $KEYS || fail "no $KEY in keys.env"; done   # presence only; the value is never read here

run_job(){ # one plan line
  local RUN MODEL N ADAPTER APATH NOTE NCHK STYLE EFFORT BURL KEY PCONC SW_ ENTRY SOLO EST SUB ARM
  IFS=$'\t' read -r RUN MODEL N ADAPTER APATH NOTE NCHK STYLE EFFORT BURL KEY PCONC SW_ ENTRY SOLO EST SUB ARM <<< "$1"
  local RD=$D/$RUN; mkdir -p $RD
  [ -e $RD/DONE_$MODEL ] && { say "skip $RUN/$MODEL (DONE marker)"; return 0; }
  if [ -e $RD/CHECKED_$MODEL ]; then
    say "resume $RUN/$MODEL at audit/pack"
  else
    [ -s $SUB ] || fail "no subset $SUB"
    [ "$APATH" = - ] && [ "$ENTRY" = stage_a.run_gate ] && [ "$KEY" != - ] || fail "plan line of $RUN/$MODEL is not a hosted job"
    case "$NCHK" in md5:*) [ "$(md5sum "$NOTE" | cut -c1-32)" = "${NCHK#md5:}" ] || fail "note $NOTE differs from the one $RUN used";; *) fail "hosted job without a checked note file";; esac
    [ -e $D/SOLO_RUNNING ] && fail "the single-edit latency read is running (delete_rerun/SOLO_RUNNING); start this script after it"
    local stamp; stamp=$(date +%Y%m%d_%H%M%S)
    for x in $RD/$MODEL $RD/per_task_$MODEL.jsonl $RD/summary_$MODEL.json $RD/$MODEL.log $RD/cost_$MODEL.json $RD/fs_audit_$MODEL.log $RD/fs_audit_$MODEL.json; do
      [ -e $x ] && mv $x $x.attempt_$stamp && say "moved unfinished $x aside"
    done
    $PY $D/plan_tool.py busy $CORES $MYPGID >> $LOG 2>&1 || fail "cores $CORES are in use by another pinned process (see log)"
    local avail; avail=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)
    [ "$avail" -ge "$MIN_AVAIL_GB" ] || fail "MemAvailable ${avail} GB below ${MIN_AVAIL_GB} GB"
    local free; free=$(df -B1 --output=avail "$HOME" | tail -1)
    [ $((free - EST)) -ge $((MIN_FREE_RUN_GB * 1024 * 1024 * 1024)) ] || fail "disk: $((free / 1073741824)) GB free, job writes ~$((EST / 1073741824)) GB, floor ${MIN_FREE_RUN_GB} GB"
    say "START $RUN/$MODEL arm $ARM, $N tasks, base $BURL, note $NOTE ($NCHK), subset md5 $(md5sum $SUB | cut -c1-32), tasks md5 $(md5sum $TASKS | cut -c1-32)"
    (
      export PYTHONPATH=$P/code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
      export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
      unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE VERIBIM_REQUEST_STYLE VERIBIM_API_KEY VERIBIM_REASONING_EFFORT \
            VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY VERIBIM_LOCAL_SEED \
            VERIBIM_CHAT_TEMPLATE_KWARGS VERIBIM_ANTHROPIC_THINKING VERIBIM_MODEL_CACHE VERIBIM_MESH_VERTICES
      export VERIBIM_USER_NOTE_FILE=$NOTE
      [ "$STYLE" = - ] || export VERIBIM_REQUEST_STYLE=$STYLE
      [ "$EFFORT" = - ] || export VERIBIM_REASONING_EFFORT=$EFFORT
      echo "$(date '+%F %T') $RUN/$MODEL env: note $VERIBIM_USER_NOTE_FILE ($NCHK), no_geom ${VERIBIM_NO_GEOM:-0}, guard $VERIBIM_SANDBOX_GUARD, landlock $VERIBIM_SANDBOX_LANDLOCK, request style ${VERIBIM_REQUEST_STYLE:-unset}, effort ${VERIBIM_REASONING_EFFORT:-unset}, thinking unset, base $BURL, key from keys.env ($KEY), conc $CONC, sw $SW, cores $CORES" >> $LOG
      K=$(grep "^$KEY=" $KEYS | cut -d= -f2-)
      [ -n "$K" ] || { echo "$(date '+%F %T') no $KEY in keys.env" >> $LOG; exit 2; }
      export VERIBIM_API_KEY="$K"; unset K
      exec taskset -c $CORES $PY -u -m stage_a.run_gate --adapters "$MODEL" --base-url "$BURL" --subset $SUB \
        --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW \
        --scorer-reading family --label "VeriBIM-Bench v4e re-run of $RUN ($ARM arm), $MODEL, $N deletion tasks, family reading, sandbox guard" \
        > $RD/$MODEL.log 2>&1
    )
    local rc=$?; say "END $RUN/$MODEL rc=$rc"
    [ $rc -eq 0 ] || fail "run_gate rc=$rc for $RUN/$MODEL (log $RD/$MODEL.log)"
    $PY $D/plan_tool.py check $RUN $MODEL >> $LOG 2>&1 || fail "output check for $RUN/$MODEL (see log)"
    touch $RD/CHECKED_$MODEL
  fi
  [ -e $RD/fs_audit_$MODEL.log ] || { $PY $B/audit_fs_access.py $RD/$MODEL/transcripts >> $RD/fs_audit_$MODEL.log 2>&1 || say "file-access audit rc=$? for $RUN/$MODEL"; }
  if [ "$PACK" = 1 ]; then taskset -c $CORES $PY $D/plan_tool.py pack $RUN $MODEL >> $LOG 2>&1 || fail "packing edited/ of $RUN/$MODEL"; fi
  touch $RD/DONE_$MODEL; say "=== DONE $RUN/$MODEL"
}

say "=== rerun_delete_hosted start: ${#JOBS[@]} jobs, tasks $TASKS (md5 $(md5sum $TASKS | cut -c1-32)), conc $CONC, cores $CORES, pack $PACK"
for l in "${JOBS[@]}"; do run_job "$l"; done
for l in "${JOBS[@]}"; do IFS=$'\t' read -r RUN MODEL _ <<< "$l"; [ -e $D/$RUN/DONE_$MODEL ] || fail "missing DONE for $RUN/$MODEL"; done
$PY - $D <<'PYC' >> $LOG 2>&1
import glob, json, sys
c = [json.load(open(p)) for p in sorted(glob.glob(sys.argv[1] + "/hosted*/cost_*.json"))]
print("hosted re-run cost at list price: USD %.2f over %d jobs, %d rows" % (sum(x["usd"] for x in c), len(c), sum(x["n"] for x in c)))
PYC
touch $D/RERUN_DELETE_HOSTED_ALL_DONE; say "=== ALL DONE (hosted re-runs)"
