#!/bin/bash
# v4e deletion re-run, Qwen3.5-9B arms (base and adapters). Re-runs, on tasks.v4d.jsonl, every output listed in
# gt_fix/rerun_list_delete_v2.csv whose code ran a deletion helper of the shared library (geom.delete_element /
# delete_filling / delete_filling_with_opening) on one of the 49 deletion tasks whose ground truth was repaired.
# Jobs, environments and subsets come from delete_rerun/plan.json (make_plan.py); evidence in gt_fix/rerun_delete_arms.md.
#
# Two server configurations were used by the original reads, so the script runs in two passes, one per server:
#   9b_canonical   the Stage C server: code/stage_c/scripts_serve.sh (canonical template chat_template_veribim.jinja,
#                  max-model-len 32768, VLLM_ALLOW_RUNTIME_LORA_UPDATING set). Adapter arms (full_all, local108_lib_all,
#                  local324_lib_all, local108_lib_solo) and the base model's libnote arm (local108_libnote_all).
#   9b_owntemplate the base server of the 10-13/10-15 reads: the flags of analysis/revision/base_documented/serve_base.sh
#                  (the model's own chat_template.jinja, max-model-len 65536). local108_informed_all/Qwen3.5-9B and the
#                  two retrieval arms (run through retrieval_fewshot/run_gate_pertask.py with their per-task note folders).
# The script reads the running server's command line and environment and runs the jobs of the matching pass only;
# it refuses any other server. Launch it once per server (README.md).
#
# Per job: original arm environment (note file checked by md5 or by its sha256 manifest), sandbox guard and Landlock on,
# client sampling/template knobs unset, concurrency 16 (local108_lib_solo: 1, as originally), 2 score workers,
# harness pinned to cores 20-23; checks the task set and that resolved_agent_config equals the arm's original summary
# (plan_tool.py check), runs the file-access audit, packs edited/ into edited.tar.gz (PACK_EDITED=1, default: the 460
# re-run models are about 34 GB unpacked) and writes delete_rerun/<run>/DONE_<model>.
# Resumable: DONE_<model> skips a job; CHECKED_<model> without DONE resumes at the audit/pack step; an unfinished
# attempt is moved aside to *.attempt_<time> (never deleted). The lib_solo jobs (single-edit latency read) run last,
# only with the GPU held by the server alone, no other gate read alive and cores 20-23 idle; a contention sample every
# 30 s; any contention marks the job CONTENDED_<model> instead of DONE.
# Writes only under gt_fix/delete_rerun/ (plus the shared gold cache runs_local/bench_v4/_gold_cache, as every read).
# Run detached:
#   setsid nohup bash analysis/revision/ground_truth_repair/delete_rerun/rerun_delete_local.sh \
#     > analysis/revision/ground_truth_repair/delete_rerun/logs/rerun_delete_local.out 2>&1 < /dev/null &
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"; G=$P/analysis/revision/ground_truth_repair; D=$G/delete_rerun; B=$P/runs_local/bench_v4
TASKS=$B/tasks.v4d.jsonl; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; SERVER=http://127.0.0.1:8000
CORES=${CORES:-20-23}; MIN_AVAIL_GB=${MIN_AVAIL_GB:-40}; MIN_FREE_RUN_GB=${MIN_FREE_RUN_GB:-8}; PACK=${PACK_EDITED:-1}
CANON_TPL=$P/code/stage_a/chat_template_veribim.jinja; OWN_TPL=${BASE_MODEL:-models/Qwen3.5-9B}/chat_template.jinja
LOG=$D/logs/rerun_delete_local.log; mkdir -p $D/logs
export PYTHONNOUSERSITE=1
say(){ echo "$(date '+%F %T') $* (disk $(df -BG --output=avail "$HOME" | tail -1 | tr -d ' ') free, mem $(awk '/MemAvailable/ {printf "%dG", $2/1048576}' /proc/meminfo) avail)" >> $LOG; }
fail(){ say "FAILED: $*"; touch $D/RERUN_DELETE_LOCAL_FAILED; exit 1; }
cd $P
MYPGID=$(ps -o pgid= -p $$ | tr -d ' ')

# --- checks before anything runs
[ -s $TASKS ] || fail "no $TASKS"
[ "$(md5sum $TASKS | cut -c1-32)" = "$($PY -c "import json; print(json.load(open('$D/plan.json'))['tasks_file_md5'])")" ] || fail "tasks.v4d.jsonl differs from the plan's"
$PY -c "
import hashlib, json, sys
p = json.load(open('$D/plan.json'))
for k in ('geom_lib', 'goldlib'):
    if hashlib.md5(open(p[k], 'rb').read()).hexdigest() != p[k + '_md5']: sys.exit(k)
" || fail "the installed veribim_geom.py / goldlib.py is not the repaired version recorded in plan.json"
SRV=$($PY $D/plan_tool.py server) || fail "cannot read the server process"
read -r GROUP SPGID SINFO < <($PY - "$SRV" "$CANON_TPL" "$OWN_TPL" <<'PYC'
import json, sys
s = json.loads(sys.argv[1]); canon, own = sys.argv[2], sys.argv[3]
if len(s) != 1 or s[0]["model"] != "models/Qwen3.5-9B" or s[0]["served"] != "Qwen3.5-9B":
    print("none 0 servers=" + json.dumps(s).replace(" ", "")); sys.exit()
s = s[0]
info = f"pid={s['pid']},template={s['template']},max_model_len={s['max_model_len']},runtime_lora={s['runtime_lora']},cores={s['cores']}"
if s["template"] == canon and s["max_model_len"] == "32768" and s["runtime_lora"] in ("1", "True", "true") and s["lora"]:
    print("9b_canonical", s["pgid"], info)
elif s["template"] == own and s["max_model_len"] == "65536":
    print("9b_owntemplate", s["pgid"], info)
else:
    print("none", s["pgid"], info)
PYC
)
say "=== rerun_delete_local start: server $SINFO -> pass ${GROUP:-none}"
case "${GROUP:-none}" in 9b_canonical|9b_owntemplate) ;; *) fail "no matching Qwen3.5-9B server on 127.0.0.1:8000 ($SINFO)";; esac
curl -s --max-time 10 $SERVER/v1/models | $PY -c "
import sys, json
d = {m['id']: m for m in json.load(sys.stdin)['data']}
assert 'Qwen3.5-9B' in d, list(d)
want = 32768 if '$GROUP' == '9b_canonical' else 65536
assert int(d['Qwen3.5-9B'].get('max_model_len') or 0) == want, d['Qwen3.5-9B'].get('max_model_len')
" >> $LOG 2>&1 || fail "server on $SERVER does not list Qwen3.5-9B with the pass's context length"
mapfile -t ALL < <($PY $D/plan_tool.py jobs $GROUP)
[ ${#ALL[@]} -gt 0 ] || fail "no jobs for $GROUP in plan.json"
# order: non-solo jobs grouped by adapter (one load per adapter), then the solo latency jobs
mapfile -t ORDERED < <(printf '%s\n' "${ALL[@]}" | awk -F'\t' '$15==0' | sort -t$'\t' -k4,4 -k1,1; printf '%s\n' "${ALL[@]}" | awk -F'\t' '$15==1')
for l in "${ORDERED[@]}"; do IFS=$'\t' read -r _ _ _ _ APATH _ <<< "$l"
  [ "$APATH" = - ] || [ -s "$APATH/adapter_model.safetensors" ] || fail "adapter files missing: $APATH"; done

load(){ # name path
  curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\"}" || true
  curl -s -X POST $SERVER/v1/load_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\", \"lora_path\": \"$2\"}" >> $LOG 2>&1; echo >> $LOG
  curl -s $SERVER/v1/models | $PY -c "import sys,json; ids=[m['id'] for m in json.load(sys.stdin)['data']]; assert '$1' in ids, ids" >> $LOG 2>&1
}
unload(){ curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\"}" || true; }

note_ok(){ # note check
  case "$2" in
    -) [ "$1" = - ];;
    md5:*) [ "$(md5sum "$1" | cut -c1-32)" = "${2#md5:}" ];;
    manifest:*) local rest=${2#manifest:}; local man=${rest%:*} pref=${rest##*:}
      [ "$(sha256sum "$man" | cut -c1-16)" = "$pref" ] && (cd "$1" && sha256sum --quiet -c "$man") && [ "$(ls "$1"/*.md | wc -l)" = 108 ];;
    *) return 1;;
  esac
}

finish_job(){ # run model: audit, pack, DONE (resumable after CHECKED)
  local RUN=$1 MODEL=$2 RD=$D/$1
  [ -e $RD/fs_audit_$MODEL.log ] || { $PY $B/audit_fs_access.py $RD/$MODEL/transcripts >> $RD/fs_audit_$MODEL.log 2>&1 || say "file-access audit rc=$? for $RUN/$MODEL"; }
  if [ "$PACK" = 1 ]; then taskset -c $CORES $PY $D/plan_tool.py pack $RUN $MODEL >> $LOG 2>&1 || fail "packing edited/ of $RUN/$MODEL"; fi
  touch $RD/DONE_$MODEL; say "=== DONE $RUN/$MODEL"
}

run_job(){ # one plan line
  local RUN MODEL N ADAPTER APATH NOTE NCHK STYLE EFFORT BURL KEY CONC SW ENTRY SOLO EST SUB ARM
  IFS=$'\t' read -r RUN MODEL N ADAPTER APATH NOTE NCHK STYLE EFFORT BURL KEY CONC SW ENTRY SOLO EST SUB ARM <<< "$1"
  local RD=$D/$RUN; mkdir -p $RD
  [ -e $RD/DONE_$MODEL ] && { say "skip $RUN/$MODEL (DONE marker)"; return 0; }
  [ -e $RD/CONTENDED_$MODEL ] && fail "$RUN/$MODEL is marked CONTENDED; remove the marker to re-run"
  if [ -e $RD/CHECKED_$MODEL ]; then say "resume $RUN/$MODEL at audit/pack"; finish_job $RUN $MODEL; return 0; fi
  [ -s $SUB ] || fail "no subset $SUB"
  [ "$STYLE" = - ] && [ "$EFFORT" = - ] && [ "$KEY" = - ] || fail "plan line of $RUN/$MODEL is not a local job"
  note_ok "$NOTE" "$NCHK" || fail "note $NOTE fails its check $NCHK"
  local stamp; stamp=$(date +%Y%m%d_%H%M%S)
  for x in $RD/$MODEL $RD/per_task_$MODEL.jsonl $RD/summary_$MODEL.json $RD/$MODEL.log $RD/fs_audit_$MODEL.log $RD/fs_audit_$MODEL.json $RD/time_$MODEL.txt; do
    [ -e $x ] && mv $x $x.attempt_$stamp && say "moved unfinished $x aside"
  done
  # resources: cores idle, memory for 16 sandboxes on the 111 MB building plus two 3 GB score workers, disk for the edits
  $PY $D/plan_tool.py busy $CORES $MYPGID >> $LOG 2>&1 || fail "cores $CORES are in use by another pinned process (see log)"
  local avail; avail=$(awk '/MemAvailable/ {print int($2/1048576)}' /proc/meminfo)
  [ "$avail" -ge "$MIN_AVAIL_GB" ] || fail "MemAvailable ${avail} GB below ${MIN_AVAIL_GB} GB"
  local free; free=$(df -B1 --output=avail "$HOME" | tail -1)
  [ $((free - EST)) -ge $((MIN_FREE_RUN_GB * 1024 * 1024 * 1024)) ] || fail "disk: $((free / 1073741824)) GB free, job writes ~$((EST / 1073741824)) GB, floor ${MIN_FREE_RUN_GB} GB"
  if [ "$SOLO" = 1 ]; then
    for p in $(pgrep -f '^${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u (-m stage_a\.run_gate|[^ ]*run_gate_pertask\.py) '); do
      fail "solo read needs no other gate read alive; pid $p: $(tr '\0' ' ' < /proc/$p/cmdline | cut -c1-100)"; done
    $PY $D/plan_tool.py gpu-holders $SPGID >> $LOG 2>&1 || fail "solo read needs the GPU held by the server alone (see log)"
    touch $D/SOLO_RUNNING
  fi
  local MOD="-m stage_a.run_gate"; [ "$ENTRY" = stage_a.run_gate ] || MOD="$ENTRY"
  say "START $RUN/$MODEL arm $ARM, $N tasks, adapter ${APATH}, conc $CONC, sw $SW, subset md5 $(md5sum $SUB | cut -c1-32), entry $ENTRY"
  (
    export PYTHONPATH=$P/code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
    export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
    unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE VERIBIM_REQUEST_STYLE VERIBIM_API_KEY VERIBIM_REASONING_EFFORT \
          VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY VERIBIM_LOCAL_SEED \
          VERIBIM_CHAT_TEMPLATE_KWARGS VERIBIM_ANTHROPIC_THINKING VERIBIM_MODEL_CACHE VERIBIM_MESH_VERTICES
    [ "$NOTE" = - ] || export VERIBIM_USER_NOTE_FILE=$NOTE
    echo "$(date '+%F %T') $RUN/$MODEL env: note ${VERIBIM_USER_NOTE_FILE:-none} ($NCHK), no_geom ${VERIBIM_NO_GEOM:-0}, guard $VERIBIM_SANDBOX_GUARD, landlock $VERIBIM_SANDBOX_LANDLOCK, request style unset, effort unset, sampling knobs unset, chat-template kwargs unset, server $SINFO, cores $CORES" >> $LOG
    if [ "$SOLO" = 1 ]; then
      exec /usr/bin/time -v -o $RD/time_$MODEL.txt taskset -c $CORES $PY -u $MOD --adapters "$ADAPTER" --base-url $BURL --subset $SUB \
        --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW --scorer-reading family \
        --label "VeriBIM-Bench v4e re-run of $RUN ($ARM arm), $MODEL, $N deletion tasks, family reading, sandbox guard, one task at a time, exclusive cores $CORES" \
        > $RD/$MODEL.log 2>&1
    fi
    exec taskset -c $CORES $PY -u $MOD --adapters "$ADAPTER" --base-url $BURL --subset $SUB \
      --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW --scorer-reading family \
      --label "VeriBIM-Bench v4e re-run of $RUN ($ARM arm), $MODEL, $N deletion tasks, family reading, sandbox guard" \
      > $RD/$MODEL.log 2>&1
  ) &
  local GP=$!
  if [ "$SOLO" = 1 ]; then  # contention samples while the latency read runs (other busy processes on our cores, GPU holders)
    ( while kill -0 $GP 2>/dev/null; do
        s=$($PY $D/plan_tool.py busy $CORES $MYPGID 2>&1) || echo "$(date '+%T') CONTENTION cores: $s" >> $D/logs/solo_contention_$MODEL.log
        g=$($PY $D/plan_tool.py gpu-holders $SPGID 2>&1) || echo "$(date '+%T') CONTENTION gpu: $g" >> $D/logs/solo_contention_$MODEL.log
        echo "$(date '+%T') load $(cut -d' ' -f1-3 /proc/loadavg)" >> $D/logs/solo_contention_$MODEL.log
        sleep 30; done ) &
  fi
  wait $GP; local rc=$?
  [ "$SOLO" = 1 ] && { wait; rm -f $D/SOLO_RUNNING; }
  say "END $RUN/$MODEL rc=$rc"
  [ $rc -eq 0 ] || fail "run_gate rc=$rc for $RUN/$MODEL (log $RD/$MODEL.log)"
  $PY $D/plan_tool.py check $RUN $MODEL >> $LOG 2>&1 || fail "output check for $RUN/$MODEL (see log)"
  if [ "$SOLO" = 1 ] && grep -q CONTENTION $D/logs/solo_contention_$MODEL.log 2>/dev/null; then
    touch $RD/CONTENDED_$MODEL; fail "contention during the solo read of $RUN/$MODEL (logs/solo_contention_$MODEL.log); not marked DONE"
  fi
  touch $RD/CHECKED_$MODEL
  finish_job $RUN $MODEL
}

say "pass $GROUP: ${#ORDERED[@]} jobs, tasks $TASKS (md5 $(md5sum $TASKS | cut -c1-32)), cores $CORES, pack $PACK"
CUR=""
for l in "${ORDERED[@]}"; do
  IFS=$'\t' read -r RUN MODEL _ ADAPTER APATH _ <<< "$l"
  if [ -e $D/$RUN/DONE_$MODEL ]; then say "skip $RUN/$MODEL (DONE marker)"; continue; fi
  if [ "$ADAPTER" != "$CUR" ]; then
    [ -n "$CUR" ] && [ "$CUR_PATH" != - ] && unload "$CUR" && say "unloaded $CUR"
    if [ "$APATH" != - ]; then load "$ADAPTER" "$APATH" || fail "load $ADAPTER"; say "loaded $ADAPTER from $APATH"; fi
    CUR=$ADAPTER; CUR_PATH=$APATH
  fi
  run_job "$l"
done
[ -n "$CUR" ] && [ "$CUR_PATH" != - ] && unload "$CUR" && say "unloaded $CUR"
for l in "${ORDERED[@]}"; do IFS=$'\t' read -r RUN MODEL _ <<< "$l"; [ -e $D/$RUN/DONE_$MODEL ] || fail "missing DONE for $RUN/$MODEL"; done
touch $D/RERUN_DELETE_LOCAL_${GROUP}_DONE; say "=== pass $GROUP done"
if [ -e $D/RERUN_DELETE_LOCAL_9b_canonical_DONE ] && [ -e $D/RERUN_DELETE_LOCAL_9b_owntemplate_DONE ]; then
  touch $D/RERUN_DELETE_LOCAL_ALL_DONE; say "=== ALL DONE (local 9B re-runs)"
fi
