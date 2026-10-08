#!/bin/bash
# The benchmark launcher with the documented arm (ARM=informed) and the 216 tasks of the 324-task subset outside
# the 108-task subset (SUBSET=rest216) added. The documented commercial setting ran on these tasks as
#   SUBSET=rest216 ARM=informed HOSTED=anthropic bash analysis/revision/equivalence/eval_informed216.sh claude-sonnet-5-5
# from the repository root, with the provider key in ANTHROPIC_API_KEY. The usage lines below are those of the
# original launcher, eval_bench_v4.sh.
# Score a served adapter on VeriBIM-Bench v4 (one part or all three), family reading; per-version and per-cell table.
#   PART=IFC4X3 bash eval_bench_v4.sh <adapter>      # one part (700 tasks)
#   PART=all bash eval_bench_v4.sh <adapter>         # 2,100 tasks
#   SUBSET=1 PART=all bash eval_bench_v4.sh <name>   # the 324-task subset
#   SUBSET=hosted ARM=lib   HOSTED=openai    bash eval_bench_v4.sh gpt-5.6-luna      # 108-task hosted subset, with the library
#   SUBSET=hosted ARM=alone HOSTED=deepseek  bash eval_bench_v4.sh deepseek-v4-pro   # ... the model alone (no library, no library note)
#   HOSTED = anthropic | openai | gemini | deepseek (OpenAI-compatible chat endpoints; keys from the environment variables named below)
#   ARM    = lib | alone (hosted arms only); LOCAL_NOTE=1 gives a local model the library note (run dir gets _note)
set -u; cd "$(dirname "${BASH_SOURCE[0]}")/../../.."
NAME="${1:?adapter or model}"; PART="${PART:-all}"; B=runs_local/bench_v4; OUT=$B/results; mkdir -p $OUT; L=analysis/revision/equivalence/eval_informed216.log
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1   # sandbox guard (see README.md), set inside the launcher
say(){ echo "$(date '+%F %T') $*" >> $L; }
TASKS=$B/tasks.v4c.jsonl; [ "$PART" = all ] || TASKS=$B/tasks_${PART}.v4c.jsonl
if [ "${SUBSET:-0}" = rest216 ]; then SUB=$B/subset_324_rest216.v4c.json; PART=all; TASKS=$B/tasks.v4c.jsonl; TAG=hosted324rest   # the 216 tasks of the 324-task subset outside the 108-task subset
elif [ "${SUBSET:-0}" = hosted ]; then SUB=$B/subset_108_hosted.v4c.json; PART=all; TASKS=$B/tasks.v4c.jsonl; TAG=hosted108
elif [ "${SUBSET:-0}" = 1 ]; then SUB=$B/subset_324.v4c.json; [ "$PART" = all ] || SUB=$B/subset_108_${PART}.v4c.json; TAG=subset; else
  SUB=$OUT/_ids_${PART}.json; $PY -c "import json,sys; print(json.dumps([json.loads(l)['task_id'] for l in open('$TASKS')]))" > $SUB; TAG=full; fi
MODEL="$NAME"
if [ -n "${HOSTED:-}" ]; then
  ARM="${ARM:?ARM=lib or ARM=alone is required for a hosted model}"
  case "$ARM" in
    lib)   export VERIBIM_USER_NOTE_FILE=runs_local/bench_v4/geom_prompt_note_frontier.md; unset VERIBIM_NO_GEOM ;;
    alone) export VERIBIM_NO_GEOM=1; unset VERIBIM_USER_NOTE_FILE ;;
    informed) export VERIBIM_USER_NOTE_FILE=analysis/revision/informed/note_informed.md; unset VERIBIM_NO_GEOM ;;   # documented arm: full library documentation, conventions, three worked examples
    *) say "unknown ARM=$ARM"; exit 2 ;;
  esac
  TAG="${TAG}_${ARM}"             # one run directory per arm; per-task files inside are named by the model id
  getkey(){ K="${!1:-}"; [ -n "$K" ] || { say "no key $1 in the environment"; exit 2; }; export VERIBIM_API_KEY="$K"; }
  case "$HOSTED" in
    anthropic) getkey ANTHROPIC_API_KEY; export VERIBIM_REQUEST_STYLE=anthropic_native; BASE_URL=https://api.anthropic.com/v1 ;;   # native Messages transport with prompt caching
    openai)    getkey OPENAI_API_KEY;    export VERIBIM_REQUEST_STYLE=gpt5;      BASE_URL=https://api.openai.com/v1 ;;
    gemini)    getkey GEMINI_API_KEY;    unset VERIBIM_REQUEST_STYLE;            BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai ;;
    deepseek)  getkey DEEPSEEK_API_KEY;  unset VERIBIM_REQUEST_STYLE;            BASE_URL=https://api.deepseek.com/v1 ;;
    *) say "unknown HOSTED=$HOSTED"; exit 2 ;;
  esac
else
  unset VERIBIM_NO_GEOM
  if [ "${LOCAL_NOTE:-0}" = 1 ]; then TAG="${TAG}_note"; export VERIBIM_USER_NOTE_FILE=runs_local/bench_v4/geom_prompt_note_frontier.md   # an untrained local model told that the library exists
  else unset VERIBIM_USER_NOTE_FILE; fi
  BASE_URL=http://127.0.0.1:8000/v1; curl -s $BASE_URL/models | grep -q "\"$NAME\"" || { say "not served: $NAME"; exit 2; }
fi
[ "${LIMIT:-0}" = 0 ] || TAG="${TAG}_smoke${LIMIT}"   # a bounded connectivity check never lands in a reported directory
RUN=$OUT/${TAG}_${PART}; mkdir -p $RUN
test ! -e "$RUN/per_task_${NAME}.jsonl" || { say "$RUN/per_task_${NAME}.jsonl exists; refusing"; exit 2; }
say "bench v4 $TAG $PART $NAME start"
say "bench v4 $TAG $PART $NAME (model $MODEL, base $BASE_URL, note ${VERIBIM_USER_NOTE_FILE:-none}, no_geom ${VERIBIM_NO_GEOM:-0}, guard ${VERIBIM_SANDBOX_GUARD:-0}, landlock ${VERIBIM_SANDBOX_LANDLOCK:-0}, note md5 $(md5sum ${VERIBIM_USER_NOTE_FILE:-/dev/null} | cut -c1-32), subset md5 $(md5sum $SUB | cut -c1-32))"
taskset -c ${GATE_CORES:-10-19} $PY -u -m stage_a.run_gate --adapters "$MODEL" --limit ${LIMIT:-0} --base-url "$BASE_URL" --subset "$SUB" --tasks-file "$TASKS" \
   --run-dir "$RUN" --gold-cache $B/_gold_cache --concurrency ${CONC:-16} --score-workers ${SW:-4} --scorer-reading family \
   --label "VeriBIM-Bench v4 $TAG $PART, $NAME, family reading" > "$RUN/$NAME.log" 2>&1
say "bench v4 $TAG $PART $NAME rc=$?"
$PY - "$RUN/per_task_${NAME}.jsonl" "$TASKS" > "$RUN/by_version_${NAME}.txt" <<'PY'
import json, sys, collections
P={json.loads(l)['task_id']:json.loads(l) for l in open(sys.argv[1])}
T={json.loads(l)['task_id']:json.loads(l) for l in open(sys.argv[2])}
agg=collections.defaultdict(lambda:[0,0,0.0,0.0])
def completed(r):
    sc=r.get('score') or {}; ax=[sc.get(k) for k in ('geometry','semantics','topology')]
    return all(a is not None and a>=0.9 for a in ax)
for tid,r in P.items():
    t=T.get(tid)
    if t is None: continue
    for key in (t['ifc_version'], (t['ifc_version'], t['operation']), (t['ifc_version'], t['origin']), 'ALL'):
        a=agg[key]; a[0]+=1; a[1]+=completed(r); a[2]+=float(r.get('final') or 0); a[3]+=float(r.get('tool_rounds') or 0)
for k in sorted(agg, key=str):
    n,c,s,tr=agg[k]; print(k, n, 'completion %.3f' % (c/n), 'mean %.3f' % (s/n), 'rounds %.2f' % (tr/n))
PY
say "=== BENCH_V4_${TAG}_${PART}_${NAME}_DONE"; touch "$RUN/DONE_${NAME}"
