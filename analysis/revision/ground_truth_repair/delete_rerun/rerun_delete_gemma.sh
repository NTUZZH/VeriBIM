#!/bin/bash
# v4e deletion re-run, Gemma 4 31B (AWQ) documented-library arm: local108_informed_all/gemma-4-31b-it-awq, 3 deletion
# tasks of the 108-task subset, on tasks.v4d.jsonl. Starts the Gemma server with the flags of
# analysis/revision/gemma31b/serve_gemma.sh (checked against that file at start; only the log path differs,
# so nothing is appended to the gemma31b folder), runs the job as run_gemma108.sh did (note_informed.md, md5 7dad463c...,
# no request style, sandbox guard and Landlock on, family reading; concurrency 4 as the completed read used, 2 score
# workers, harness on cores 20-23), checks it (plan_tool.py check), packs edited/, writes DONE, and stops the server
# with kill -TERM -- -<pgid> of the setsid-started server (also on failure, through an EXIT trap).
# Preconditions: no vLLM server on port 8000 and no process holding the GPU (stop the 9B server first), no
# runs_local/BOLT_WINDOW_OPEN, server cores (GEMMA_SERVER_CORES, default 16-19 as serve_gemma.sh) and cores 20-23 idle,
# 40 GB host memory available.
# Run detached:
#   setsid nohup bash analysis/revision/ground_truth_repair/delete_rerun/rerun_delete_gemma.sh \
#     > analysis/revision/ground_truth_repair/delete_rerun/logs/rerun_delete_gemma.out 2>&1 < /dev/null &
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"; G=$P/analysis/revision/ground_truth_repair; D=$G/delete_rerun; B=$P/runs_local/bench_v4
TASKS=$B/tasks.v4d.jsonl; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; SERVER=http://127.0.0.1:8000
CORES=${CORES:-20-23}; GCORES=${GEMMA_SERVER_CORES:-16-19}; MIN_AVAIL_GB=${MIN_AVAIL_GB:-40}; MIN_FREE_RUN_GB=${MIN_FREE_RUN_GB:-8}; PACK=${PACK_EDITED:-1}
SERVE_SRC=$P/analysis/revision/gemma31b/serve_gemma.sh
LOG=$D/logs/rerun_delete_gemma.log; SLOG=$D/logs/serve_gemma.log; mkdir -p $D/logs
export PYTHONNOUSERSITE=1
say(){ echo "$(date '+%F %T') $* (disk $(df -BG --output=avail "$HOME" | tail -1 | tr -d ' ') free, mem $(awk '/MemAvailable/ {printf "%dG", $2/1048576}' /proc/meminfo) avail)" >> $LOG; }
STARTED=0; SPGID=""
stop_server(){
  [ "$STARTED" = 1 ] && [ -n "$SPGID" ] || return 0
  say "stopping the Gemma server (pgid $SPGID)"; kill -TERM -- -$SPGID 2>/dev/null
  for i in $(seq 1 60); do sleep 5; kill -0 -- -$SPGID 2>/dev/null || { say "server stopped"; STARTED=0; return 0; }; done
  say "WARNING: server group $SPGID still alive after 300 s; stop it manually (kill -TERM -- -$SPGID)"
}
trap stop_server EXIT
fail(){ say "FAILED: $*"; touch $D/RERUN_DELETE_GEMMA_FAILED; exit 1; }
cd $P
MYPGID=$(ps -o pgid= -p $$ | tr -d ' ')
RUN=local108_informed_all; MODEL=gemma-4-31b-it-awq; RD=$D/$RUN; mkdir -p $RD
[ -e $RD/DONE_$MODEL ] && { say "skip $RUN/$MODEL (DONE marker)"; touch $D/RERUN_DELETE_GEMMA_DONE; exit 0; }
LINE=$($PY $D/plan_tool.py jobs gemma); [ "$(echo "$LINE" | wc -l)" = 1 ] || fail "expected one gemma job in plan.json"
IFS=$'\t' read -r PRUN PMODEL N ADAPTER APATH NOTE NCHK STYLE EFFORT BURL KEY CONC SW ENTRY SOLO EST SUB ARM <<< "$LINE"
[ "$PRUN/$PMODEL" = "$RUN/$MODEL" ] && [ "$STYLE" = - ] && [ "$KEY" = - ] || fail "unexpected plan line: $LINE"

# the server command of serve_gemma.sh, with its log redirected here
VLLM_ARGS="${GEMMA_MODEL:-models/gemma-4-31B-it-AWQ} --served-model-name gemma-4-31b-it-awq --port 8000 --host 127.0.0.1 --max-model-len 65536 --max-num-seqs 16 --gpu-memory-utilization 0.90 --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 --language-model-only"
$PY - "$SERVE_SRC" "$VLLM_ARGS" <<'PYC' >> $LOG 2>&1 || fail "serve_gemma.sh no longer carries the flags this script uses"
import re, sys
src = open(sys.argv[1]).read().replace("\\\n", " ")
m = re.search(r"vllm serve (.*?)>>", src, re.S)
assert m and " ".join(m.group(1).split()) == " ".join(sys.argv[2].split()), (m and m.group(1))
assert "VLLM_USE_FLASHINFER_SAMPLER=0" in src and "OMP_NUM_THREADS=4" in src and "envs/l2vllm_gemma/bin/vllm" in src
print("serve_gemma.sh flags match")
PYC

if [ ! -e $RD/CHECKED_$MODEL ]; then
  [ -s $SUB ] || fail "no subset $SUB"
  [ "$(md5sum $TASKS | cut -c1-32)" = "$($PY -c "import json; print(json.load(open('$D/plan.json'))['tasks_file_md5'])")" ] || fail "tasks.v4d.jsonl differs from the plan's"
  $PY -c "
import hashlib, json, sys
p = json.load(open('$D/plan.json'))
for k in ('geom_lib', 'goldlib'):
    if hashlib.md5(open(p[k], 'rb').read()).hexdigest() != p[k + '_md5']: sys.exit(k)
" || fail "the installed veribim_geom.py / goldlib.py is not the repaired version recorded in plan.json"
  [ "$(md5sum "$NOTE" | cut -c1-32)" = "${NCHK#md5:}" ] || fail "note $NOTE differs from the one the arm used"
  [ -e $P/runs_local/BOLT_WINDOW_OPEN ] && fail "BOLT window open (runs_local/BOLT_WINDOW_OPEN); the GPU is not ours"
  curl -s --max-time 3 $SERVER/v1/models > /dev/null && fail "a server already answers on $SERVER; stop it first"
  [ "$($PY $D/plan_tool.py server)" = "[]" ] || fail "a vLLM server process exists on port 8000"
  $PY $D/plan_tool.py gpu-holders 0 >> $LOG 2>&1 || fail "another process holds the GPU (see log)"
  $PY $D/plan_tool.py busy $CORES $MYPGID >> $LOG 2>&1 || fail "cores $CORES are in use by another pinned process (see log)"
  $PY $D/plan_tool.py busy $GCORES $MYPGID >> $LOG 2>&1 || fail "server cores $GCORES are in use by another pinned process (see log)"
  avail=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo); [ "$avail" -ge "$MIN_AVAIL_GB" ] || fail "MemAvailable ${avail} GB below ${MIN_AVAIL_GB} GB"
  free=$(df -B1 --output=avail "$HOME" | tail -1)
  [ $((free - EST)) -ge $((MIN_FREE_RUN_GB * 1024 * 1024 * 1024)) ] || fail "disk: $((free / 1073741824)) GB free, floor ${MIN_FREE_RUN_GB} GB"
  stamp=$(date +%Y%m%d_%H%M%S)
  for x in $RD/$MODEL $RD/per_task_$MODEL.jsonl $RD/summary_$MODEL.json $RD/$MODEL.log $RD/fs_audit_$MODEL.log $RD/fs_audit_$MODEL.json; do
    [ -e $x ] && mv $x $x.attempt_$stamp && say "moved unfinished $x aside"
  done
  # start the server (serve_gemma.sh's environment and flags), detached as its own process group
  say "starting the Gemma server on cores $GCORES"
  setsid nohup bash -c "export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=4; exec taskset -c $GCORES ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm_gemma/bin/vllm serve $VLLM_ARGS" >> $SLOG 2>&1 < /dev/null &
  STARTED=1
  for i in $(seq 1 120); do
    sleep 10
    SPGID=$($PY $D/plan_tool.py server | $PY -c "import sys,json; s=json.load(sys.stdin); print(s[0]['pgid'] if len(s)==1 and s[0]['served']=='gemma-4-31b-it-awq' else '')")
    curl -s --max-time 5 $SERVER/v1/models | grep -q '"gemma-4-31b-it-awq"' && [ -n "$SPGID" ] && break
  done
  [ -n "$SPGID" ] && curl -s --max-time 5 $SERVER/v1/models | $PY -c "
import sys, json
d = {m['id']: m for m in json.load(sys.stdin)['data']}
assert int(d['gemma-4-31b-it-awq'].get('max_model_len') or 0) == 65536, d" >> $LOG 2>&1 || fail "Gemma server did not come up in 20 min (log $SLOG)"
  say "Gemma server up (pgid $SPGID)"
  say "START $RUN/$MODEL arm $ARM, $N tasks, conc $CONC, sw $SW, note $NOTE ($NCHK), subset md5 $(md5sum $SUB | cut -c1-32)"
  (
    export PYTHONPATH=$P/code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
    export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
    unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE VERIBIM_REQUEST_STYLE VERIBIM_API_KEY VERIBIM_REASONING_EFFORT \
          VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY VERIBIM_LOCAL_SEED \
          VERIBIM_CHAT_TEMPLATE_KWARGS VERIBIM_ANTHROPIC_THINKING VERIBIM_MODEL_CACHE VERIBIM_MESH_VERTICES
    export VERIBIM_USER_NOTE_FILE=$NOTE
    echo "$(date '+%F %T') $RUN/$MODEL env: note $VERIBIM_USER_NOTE_FILE ($NCHK), no_geom ${VERIBIM_NO_GEOM:-0}, guard $VERIBIM_SANDBOX_GUARD, landlock $VERIBIM_SANDBOX_LANDLOCK, request style unset, sampling knobs unset, chat-template kwargs unset, server gemma (pgid $SPGID, cores $GCORES), cores $CORES" >> $LOG
    exec taskset -c $CORES $PY -u -m stage_a.run_gate --adapters "$MODEL" --base-url $BURL --subset $SUB \
      --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW --scorer-reading family \
      --label "VeriBIM-Bench v4e re-run of $RUN ($ARM arm), $MODEL, $N deletion tasks, family reading, sandbox guard" \
      > $RD/$MODEL.log 2>&1
  )
  rc=$?; say "END $RUN/$MODEL rc=$rc"
  stop_server
  [ $rc -eq 0 ] || fail "run_gate rc=$rc for $RUN/$MODEL (log $RD/$MODEL.log)"
  $PY $D/plan_tool.py check $RUN $MODEL >> $LOG 2>&1 || fail "output check for $RUN/$MODEL (see log)"
  touch $RD/CHECKED_$MODEL
fi
[ -e $RD/fs_audit_$MODEL.log ] || { $PY $B/audit_fs_access.py $RD/$MODEL/transcripts >> $RD/fs_audit_$MODEL.log 2>&1 || say "file-access audit rc=$? for $RUN/$MODEL"; }
if [ "$PACK" = 1 ]; then taskset -c $CORES $PY $D/plan_tool.py pack $RUN $MODEL >> $LOG 2>&1 || fail "packing edited/ of $RUN/$MODEL"; fi
touch $RD/DONE_$MODEL; touch $D/RERUN_DELETE_GEMMA_DONE; say "=== DONE $RUN/$MODEL (Gemma)"
