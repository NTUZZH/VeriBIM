#!/bin/bash
# Re-run, on tasks.v4d.jsonl, the local-model outputs listed in gt_fix/rerun_list.csv (the rows whose edit called
# geom.move_filling on a task whose ground truth changed in the 2026-10-15 fix). 164 rows, 16 (run, model) pairs.
# Each pair runs stage_a.run_gate on exactly its affected ids (gt_fix/reruns/<run>/subset_<model>.json) with the
# original protocol (22 tool rounds, 420 s tool timeout, 8192 output tokens, temperature 0) and the original arm
# environment, into gt_fix/reruns/<run>/. Nothing under runs_local/bench_v4/results is written; merge_v4d.py does that.
#
# Assumes a vLLM server on 127.0.0.1:8000 serving Qwen3.5-9B with --enable-lora (code/stage_a/scripts_serve_lora.sh).
# Each adapter is loaded under the name and path its original read used, every run of that adapter follows, and the
# adapter is unloaded before the next one. Resumable: a (run, model) whose DONE_<model> marker exists is skipped; an
# unfinished attempt's folder is moved aside to <model>.attempt_<time>, never deleted.
# Cores 20-23 (start only after the parser job has released 22-23); concurrency 8, two score workers.
# Run detached:
#   setsid nohup bash analysis/revision/ground_truth_repair/rerun_local.sh \
#     > analysis/revision/ground_truth_repair/reruns/logs/rerun_local.out 2>&1 < /dev/null &
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; G=$P/analysis/revision/ground_truth_repair; B=$P/runs_local/bench_v4
TASKS=$B/tasks.v4d.jsonl; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; SERVER=http://127.0.0.1:8000
CORES=${CORES:-20-23}; CONC=8; SW=2
LOG=$G/reruns/logs/rerun_local.log; mkdir -p $G/reruns/logs
say(){ echo "$(date '+%F %T') $* (disk $(df -BG --output=avail "$HOME" | tail -1 | tr -d ' ') free)" >> $LOG; }
fail(){ say "FAILED: $*"; touch $G/reruns/RERUN_LOCAL_FAILED; exit 1; }
cd $P

# adapter name -> path, as each original read loaded it (evidence in gt_fix/report.md, "Adapters of the re-runs")
declare -A AD=(
  [sft_v10]=$P/checkpoints/stage_a/sft_v10/adapter
  [dpo_v10_c3]=$P/checkpoints/stage_b/dpo_v10/checkpoint-3
  [dpo_v10_c6]=$P/checkpoints/stage_b/dpo_v10/checkpoint-6
  [dpo_v9_c10]=$P/checkpoints/stage_b/dpo_v9/checkpoint-10
  [grpo_v10_c50]=$P/checkpoints/stage_c/grpo_v10/snapshots/step_50
  [grpo_v10b_c10]=$P/checkpoints/stage_c/grpo_v10b/snapshots/step_10
  [sft_small]=$P/checkpoints/stage_a/sft_small/adapter
  [dpo_small_c12]=$P/checkpoints/stage_b/dpo_small/checkpoint-12
  [grpo_small_c10]=$P/checkpoints/stage_c/grpo_small/snapshots/step_10
  [sft_extA]=$P/checkpoints/stage_a/sft_extA/adapter
  [Qwen3.5-9B]=""
)
# jobs, grouped by model so each adapter is loaded once: "model run arm"
#   arm lib: no library note, library present (full_all via eval_bench_v4.sh; local324_lib_all via run_local_subset324.sh)
#   arm libnote: library present and the library note (full_note_all via eval_bench_v4.sh with LOCAL_NOTE=1)
JOBS=(
  "sft_v10 full_all lib" "sft_v10 local324_lib_all lib"
  "dpo_v10_c3 full_all lib"
  "dpo_v10_c6 full_all lib" "dpo_v10_c6 local324_lib_all lib"
  "dpo_v9_c10 full_all lib" "dpo_v9_c10 local324_lib_all lib"
  "grpo_v10_c50 full_all lib" "grpo_v10_c50 local324_lib_all lib"
  "grpo_v10b_c10 full_all lib" "grpo_v10b_c10 local324_lib_all lib"
  "sft_small full_all lib"
  "dpo_small_c12 full_all lib"
  "grpo_small_c10 full_all lib"
  "sft_extA local324_lib_all lib"
  "Qwen3.5-9B full_note_all libnote"
)

# the protocol settings every original read resolved (summary_<model>.json)
REF_CONFIG='{"max_tool_rounds": 22, "tool_timeout": 420.0, "temperature": 0.0, "top_p": 1.0, "max_tokens": 8192, "max_tool_output_chars": 16000, "max_recorded_output_chars": 4000, "capture_stdout": true, "max_transcript_tokens": 0, "min_turn_tokens": 256, "dup_stop": 0}'

# --- checks before anything runs
[ -s $TASKS ] || fail "no $TASKS"
curl -s --max-time 10 $SERVER/v1/models | grep -q '"Qwen3.5-9B"' || fail "no vLLM server serving Qwen3.5-9B on $SERVER"
for m in "${!AD[@]}"; do [ -z "${AD[$m]}" ] || [ -s "${AD[$m]}/adapter_model.safetensors" ] || fail "adapter files missing for $m: ${AD[$m]}"; done
# another process pinned inside $CORES and busy would slow the tools against their 420 s timeout: refuse
$PY - "$CORES" >> $LOG 2>&1 <<'PYC' || fail "cores $CORES are in use by another pinned process (see log)"
import os, sys, time
lo, hi = map(int, sys.argv[1].split('-')); mine = set(range(lo, hi + 1)); tick = os.sysconf('SC_CLK_TCK')
def cpus(s):
    out = set()
    for part in s.split(','):
        a, _, b = part.partition('-'); out.update(range(int(a), int(b or a) + 1))
    return out
def cputime(pid):
    f = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
    return (int(f[11]) + int(f[12])) / tick
cand = {}
for pid in filter(str.isdigit, os.listdir('/proc')):
    try:
        st = open(f'/proc/{pid}/status').read()
        allowed = cpus(next(l.split(':', 1)[1].strip() for l in st.splitlines() if l.startswith('Cpus_allowed_list')))
        if len(allowed) < os.cpu_count() and allowed & mine:
            cand[pid] = (sorted(allowed), open(f'/proc/{pid}/cmdline').read().replace('\0', ' ')[:120], cputime(pid))
    except Exception:
        continue
time.sleep(3)
busy = []
for pid, (allowed, cmd, t0) in cand.items():
    try: used = cputime(pid) - t0
    except Exception: continue
    if used > 0.3: busy.append((pid, allowed, round(used / 3, 2), cmd))
for b in busy: print('pinned and busy on the re-run cores (pid, cores, cpu share, command):', b)
sys.exit(1 if busy else 0)
PYC

load(){ # name path
  curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\"}" || true
  curl -s -X POST $SERVER/v1/load_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\", \"lora_path\": \"$2\"}" >> $LOG 2>&1; echo >> $LOG
  curl -s $SERVER/v1/models | $PY -c "import sys,json; ids=[m['id'] for m in json.load(sys.stdin)['data']]; assert '$1' in ids, ids" >> $LOG 2>&1
}
unload(){ curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$1\"}" || true; }

run_job(){ # model run arm
  local MODEL=$1 RUN=$2 ARM=$3 RD=$G/reruns/$2; local SUB=$RD/subset_$1.json
  [ -s $SUB ] || fail "no subset $SUB"
  [ -e $RD/DONE_$MODEL ] && { say "skip $RUN/$MODEL (DONE marker)"; return 0; }
  local stamp; stamp=$(date +%Y%m%d_%H%M%S)
  for x in $RD/$MODEL $RD/per_task_$MODEL.jsonl $RD/summary_$MODEL.json $RD/$MODEL.log; do
    [ -e $x ] && mv $x $x.attempt_$stamp && say "moved unfinished $x aside"
  done
  local N; N=$($PY -c "import json; print(len(json.load(open('$SUB'))))")
  say "START $RUN/$MODEL arm $ARM, $N tasks, subset md5 $(md5sum $SUB | cut -c1-32)"
  (
    export PYTHONPATH=$P/code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
    export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
    # sampling and template knobs added to the client on 2026-10-07; the original reads ran without them
    unset VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY \
          VERIBIM_LOCAL_SEED VERIBIM_CHAT_TEMPLATE_KWARGS VERIBIM_REQUEST_STYLE VERIBIM_API_KEY VERIBIM_REASONING_EFFORT
    case "$ARM" in
      lib)     unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE ;;
      libnote) unset VERIBIM_NO_GEOM; export VERIBIM_USER_NOTE_FILE=$B/geom_prompt_note_frontier.md ;;
      *) exit 2 ;;
    esac
    echo "$(date '+%F %T') $RUN/$MODEL env: note ${VERIBIM_USER_NOTE_FILE:-none} (md5 $(md5sum ${VERIBIM_USER_NOTE_FILE:-/dev/null} | cut -c1-32)), no_geom ${VERIBIM_NO_GEOM:-0}, guard $VERIBIM_SANDBOX_GUARD, landlock $VERIBIM_SANDBOX_LANDLOCK" >> $LOG
    exec taskset -c $CORES $PY -u -m stage_a.run_gate --adapters "$MODEL" --base-url $SERVER/v1 --subset $SUB \
      --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW \
      --scorer-reading family --label "VeriBIM-Bench v4d re-run of $RUN ($ARM arm), $MODEL, $N tasks, family reading, sandbox guard" \
      > $RD/$MODEL.log 2>&1
  )
  local rc=$?; say "END $RUN/$MODEL rc=$rc"
  [ $rc -eq 0 ] || fail "run_gate rc=$rc for $RUN/$MODEL (log $RD/$MODEL.log)"
  $PY - "$RD/per_task_$MODEL.jsonl" "$SUB" "$RD/summary_$MODEL.json" "$REF_CONFIG" >> $LOG 2>&1 <<'PYC' || fail "output check for $RUN/$MODEL"
import json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]; ids = json.load(open(sys.argv[2]))
assert sorted(r['task_id'] for r in rows) == sorted(ids), 'task set differs from the subset'
cfg = json.load(open(sys.argv[3]))['resolved_agent_config']; ref = json.loads(sys.argv[4])
assert cfg == ref, f'protocol differs from the original reads: {cfg}'
err = sum(r.get('stop_reason') == 'inference_error' for r in rows)
done = sum(all(((r.get('score') or {}).get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology')) for r in rows)
print(f'checked {sys.argv[1]}: {len(rows)} rows, {done} completed, {err} inference errors, protocol as the original reads')
PYC
  $PY $B/audit_fs_access.py $RD/$MODEL/transcripts >> $RD/fs_audit_$MODEL.log 2>&1 || say "file-access audit rc=$? for $RUN/$MODEL"
  touch $RD/DONE_$MODEL; say "=== DONE $RUN/$MODEL"
}

say "=== rerun_local start: ${#JOBS[@]} jobs, tasks $TASKS (md5 $(md5sum $TASKS | cut -c1-32)), cores $CORES"
CUR=""
for j in "${JOBS[@]}"; do
  set -- $j; MODEL=$1; RUN=$2; ARM=$3
  if [ -e $G/reruns/$RUN/DONE_$MODEL ]; then say "skip $RUN/$MODEL (DONE marker)"; continue; fi
  if [ "$MODEL" != "$CUR" ]; then
    [ -n "$CUR" ] && [ -n "${AD[$CUR]}" ] && unload "$CUR" && say "unloaded $CUR"
    if [ -n "${AD[$MODEL]}" ]; then load "$MODEL" "${AD[$MODEL]}" || fail "load $MODEL"; say "loaded $MODEL from ${AD[$MODEL]}"; fi
    CUR=$MODEL
  fi
  run_job $MODEL $RUN $ARM
done
[ -n "$CUR" ] && [ -n "${AD[$CUR]}" ] && unload "$CUR" && say "unloaded $CUR"
for j in "${JOBS[@]}"; do set -- $j; [ -e $G/reruns/$2/DONE_$1 ] || fail "missing DONE for $2/$1"; done
touch $G/reruns/RERUN_LOCAL_ALL_DONE; say "=== ALL DONE (local re-runs)"
