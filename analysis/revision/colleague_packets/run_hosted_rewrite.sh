#!/bin/bash
# A commercial model on the 200 practitioner-written requests (packet A), same harness and settings as the benchmark's
# documented arm (eval_rerun.sh ARM=informed). API only: no GPU, little memory; cores 20-23.
#   HOSTED=anthropic bash run_hosted_rewrite.sh claude-sonnet-5-5
#   HOSTED=openai    bash run_hosted_rewrite.sh gpt-5.6-luna
# Not launched without the author's budget decision. Keys only in ~/.config/veribim/keys.env.
set -u; cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
NAME="${1:?model id}"; HOSTED="${HOSTED:?anthropic|openai|gemini|deepseek}"; ARM="${ARM:-informed}"
C=analysis/revision/colleague_packets; B=runs_local/bench_v4
RUN=$C/results/hosted_${ARM}; mkdir -p $RUN; L=$C/results/hosted_rewrite.log
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
say(){ echo "$(date '+%F %T') $*" | tee -a $L; }
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1
export VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
case "$ARM" in
  informed) export VERIBIM_USER_NOTE_FILE=analysis/revision/informed/note_informed.md; unset VERIBIM_NO_GEOM ;;
  lib)      export VERIBIM_USER_NOTE_FILE=runs_local/bench_v4/geom_prompt_note_frontier.md; unset VERIBIM_NO_GEOM ;;
  *) say "unknown ARM=$ARM"; exit 2 ;;
esac
getkey(){ K=$(grep "^$1=" ~/.config/veribim/keys.env | cut -d= -f2-); [ -n "$K" ] || { say "no key $1"; exit 2; }; export VERIBIM_API_KEY="$K"; }
case "$HOSTED" in
  anthropic) getkey ANTHROPIC_API_KEY; export VERIBIM_REQUEST_STYLE=anthropic_native; BASE_URL=https://api.anthropic.com/v1 ;;
  openai)    getkey OPENAI_API_KEY;    export VERIBIM_REQUEST_STYLE=gpt5;      BASE_URL=https://api.openai.com/v1 ;;
  gemini)    getkey GEMINI_API_KEY;    unset VERIBIM_REQUEST_STYLE;            BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai ;;
  deepseek)  getkey DEEPSEEK_API_KEY;  unset VERIBIM_REQUEST_STYLE;            BASE_URL=https://api.deepseek.com/v1 ;;
  *) say "unknown HOSTED=$HOSTED"; exit 2 ;;
esac
test ! -e "$RUN/per_task_${NAME}.jsonl" || { say "$RUN/per_task_${NAME}.jsonl exists; refusing"; exit 2; }
say "practitioner requests, $ARM arm, $NAME start (note $VERIBIM_USER_NOTE_FILE)"
taskset -c ${GATE_CORES:-20-23} $PY -u -m stage_a.run_gate --adapters "$NAME" --limit ${LIMIT:-0} --base-url "$BASE_URL" \
   --subset $C/results/rewrite_subset.json --tasks-file $C/results/rewrite_tasks.jsonl \
   --run-dir "$RUN" --gold-cache $B/_gold_cache --concurrency ${CONC:-8} --score-workers ${SW:-2} --scorer-reading family \
   --label "practitioner-written requests (packet A), $ARM arm, $NAME, family reading, sandbox guard" > "$RUN/$NAME.log" 2>&1
say "$NAME rc=$?"; touch "$RUN/DONE_${NAME}"
