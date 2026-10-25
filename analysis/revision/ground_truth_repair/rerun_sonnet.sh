#!/bin/bash
# Re-run, on tasks.v4d.jsonl, the Claude Sonnet 5.5 outputs listed in gt_fix/rerun_list.csv: 4 tasks in each of two
# runs. hosted324_lib_all needs no run of its own: its 4 listed rows are the hosted216_lib_all rows (the 324-task file
# was assembled from hosted108_lib_all and hosted216_lib_all), so merge_v4d.py takes them from this script's
# hosted216_lib_all re-run.
#   hosted216_lib_all           settings of runs_local/bench_v4/run_hosted_extension.sh (ARM lib, HOSTED anthropic)
#   hosted324rest_informed_all  settings of analysis/revision/equivalence/eval_informed216.sh (ARM informed)
# Both: model claude-sonnet-5-5, VERIBIM_REQUEST_STYLE=anthropic_native, https://api.anthropic.com/v1, sandbox guard
# and Landlock on, protocol 22 rounds / 420 s / 8192 tokens / temperature 0, family reading, two score workers.
# The API key is read from ~/.config/veribim/keys.env into VERIBIM_API_KEY inside the run's subshell and never printed.
# Output: gt_fix/reruns/<run>/per_task_claude-sonnet-5-5.jsonl and cost_claude-sonnet-5-5.json; the original runs'
# rows are not touched. Resumable through DONE_claude-sonnet-5-5 per run. Cores 20-23.
# Run detached:
#   setsid nohup bash analysis/revision/ground_truth_repair/rerun_sonnet.sh \
#     > analysis/revision/ground_truth_repair/reruns/logs/rerun_sonnet.out 2>&1 < /dev/null &
set -u
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"; G=$P/analysis/revision/ground_truth_repair; B=$P/runs_local/bench_v4
TASKS=$B/tasks.v4d.jsonl; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
MODEL=claude-sonnet-5-5; BASE_URL=https://api.anthropic.com/v1; CORES=${CORES:-20-23}; CONC=4; SW=2
LOG=$G/reruns/logs/rerun_sonnet.log; mkdir -p $G/reruns/logs
say(){ echo "$(date '+%F %T') $* (disk $(df -BG --output=avail "$HOME" | tail -1 | tr -d ' ') free)" >> $LOG; }
fail(){ say "FAILED: $*"; touch $G/reruns/RERUN_SONNET_FAILED; exit 1; }
cd $P
REF_CONFIG='{"max_tool_rounds": 22, "tool_timeout": 420.0, "temperature": 0.0, "top_p": 1.0, "max_tokens": 8192, "max_tool_output_chars": 16000, "max_recorded_output_chars": 4000, "capture_stdout": true, "max_transcript_tokens": 0, "min_turn_tokens": 256, "dup_stop": 0}'
declare -A NOTE=(
  [hosted216_lib_all]=$B/geom_prompt_note_frontier.md
  [hosted324rest_informed_all]=$P/analysis/revision/informed/note_informed.md
)
declare -A NOTE_MD5=(   # the md5 each original run used (unchanged since: files last modified 2026-09-21 and 2026-10-07)
  [hosted216_lib_all]=a2ff593d
  [hosted324rest_informed_all]=7dad463c
)
declare -A ARMNAME=([hosted216_lib_all]=lib [hosted324rest_informed_all]=informed)
[ -s $TASKS ] || fail "no $TASKS"

run_job(){ # run
  local RUN=$1 RD=$G/reruns/$1; local SUB=$RD/subset_$MODEL.json NF=${NOTE[$1]}
  [ -s $SUB ] || fail "no subset $SUB"
  [ -e $RD/DONE_$MODEL ] && { say "skip $RUN (DONE marker)"; return 0; }
  case "$(md5sum $NF | cut -c1-32)" in ${NOTE_MD5[$RUN]}*) ;; *) fail "note $NF differs from the one $RUN used";; esac
  local stamp; stamp=$(date +%Y%m%d_%H%M%S)
  for x in $RD/$MODEL $RD/per_task_$MODEL.jsonl $RD/summary_$MODEL.json $RD/$MODEL.log; do
    [ -e $x ] && mv $x $x.attempt_$stamp && say "moved unfinished $x aside"
  done
  local N; N=$($PY -c "import json; print(len(json.load(open('$SUB'))))")
  say "START $RUN/$MODEL arm ${ARMNAME[$RUN]}, $N tasks, base $BASE_URL, note $NF (md5 $(md5sum $NF | cut -c1-32)), subset md5 $(md5sum $SUB | cut -c1-32), tasks md5 $(md5sum $TASKS | cut -c1-32)"
  (
    export PYTHONPATH=$P/code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
    export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
    unset VERIBIM_LOCAL_TEMPERATURE VERIBIM_LOCAL_TOP_P VERIBIM_LOCAL_TOP_K VERIBIM_LOCAL_PRESENCE_PENALTY \
          VERIBIM_LOCAL_SEED VERIBIM_CHAT_TEMPLATE_KWARGS VERIBIM_REASONING_EFFORT VERIBIM_NO_GEOM
    export VERIBIM_USER_NOTE_FILE=$NF VERIBIM_REQUEST_STYLE=anthropic_native
    K=$(grep '^ANTHROPIC_API_KEY=' ~/.config/veribim/keys.env | cut -d= -f2-)
    [ -n "$K" ] || { echo "$(date '+%F %T') no ANTHROPIC_API_KEY in keys.env" >> $LOG; exit 2; }
    export VERIBIM_API_KEY="$K"; unset K
    exec taskset -c $CORES $PY -u -m stage_a.run_gate --adapters "$MODEL" --base-url "$BASE_URL" --subset $SUB \
      --tasks-file $TASKS --run-dir $RD --gold-cache $B/_gold_cache --concurrency $CONC --score-workers $SW \
      --scorer-reading family --label "VeriBIM-Bench v4d re-run of $RUN (${ARMNAME[$RUN]} arm), $MODEL, $N tasks, family reading, sandbox guard" \
      > $RD/$MODEL.log 2>&1
  )
  local rc=$?; say "END $RUN/$MODEL rc=$rc"
  [ $rc -eq 0 ] || fail "run_gate rc=$rc for $RUN (log $RD/$MODEL.log)"
  # row check, protocol check, and the cost by the formula and list prices of runs_local/bench_v4/hosted_cost.py
  $PY - "$RD/per_task_$MODEL.jsonl" "$SUB" "$RD/summary_$MODEL.json" "$REF_CONFIG" "$B/hosted_cost.py" "$RD/cost_$MODEL.json" >> $LOG 2>&1 <<'PYC' || fail "output check for $RUN"
import ast, json, sys
rows = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]; ids = json.load(open(sys.argv[2]))
assert sorted(r['task_id'] for r in rows) == sorted(ids), 'task set differs from the subset'
cfg = json.load(open(sys.argv[3]))['resolved_agent_config']; ref = json.loads(sys.argv[4])
assert cfg == ref, f'protocol differs from the original reads: {cfg}'
consts = {}
for node in ast.parse(open(sys.argv[5]).read()).body:
    if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in ('PRICE', 'CACHE_READ'):
        consts[node.targets[0].id] = ast.literal_eval(node.value)
model = rows[0]['adapter']; pi, po = consts['PRICE'][model]; cr = consts['CACHE_READ'].get(model, 0.1)
tin = sum(int(r.get('input_tokens') or 0) for r in rows); tout = sum(int(r.get('output_tokens') or 0) for r in rows)
cread = sum(int(r.get('cache_read_tokens') or 0) for r in rows); cwrite = sum(int(r.get('cache_creation_tokens') or 0) for r in rows)
cost = (tin - cread - cwrite) / 1e6 * pi + cread / 1e6 * pi * cr + cwrite / 1e6 * pi * 1.25 + tout / 1e6 * po
done = sum(all(((r.get('score') or {}).get(k) or 0) >= 0.9 for k in ('geometry', 'semantics', 'topology')) for r in rows)
err = sum(r.get('stop_reason') == 'inference_error' for r in rows)
out = dict(model=model, n=len(rows), completed=done, inference_errors=err, input_tokens=tin, cache_read_tokens=cread,
           cache_creation_tokens=cwrite, output_tokens=tout, price_usd_per_mtok=[pi, po], cache_read_fraction=cr, usd=round(cost, 4))
json.dump(out, open(sys.argv[6], 'w'), indent=1); print('checked', sys.argv[1], json.dumps(out))
PYC
  $PY $B/audit_fs_access.py $RD/$MODEL/transcripts >> $RD/fs_audit_$MODEL.log 2>&1 || say "file-access audit rc=$? for $RUN"
  touch $RD/DONE_$MODEL; say "=== DONE $RUN/$MODEL"
}

say "=== rerun_sonnet start"
for RUN in hosted216_lib_all hosted324rest_informed_all; do run_job $RUN; done
touch $G/reruns/RERUN_SONNET_ALL_DONE; say "=== ALL DONE (Sonnet re-runs)"
