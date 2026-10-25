#!/bin/bash
# A larger open-weight local model (Gemma 4 31B, 4-bit AWQ) with the documented library on the 108-task subset, same harness as every other arm.
# The run used
#   bash analysis/revision/gemma31b/run_gemma108.sh gemma-4-31b-it-awq "" informed
# with the model served by serve_gemma.sh. Output: runs_local/bench_v4/results/local108_informed_all/per_task_<name>.jsonl
# (results/benchmark/ in this repository).
set -u; cd "$(dirname "${BASH_SOURCE[0]}")/../../.."; NAME="$1"; APATH="$2"; ARM="$3"; B=runs_local/bench_v4; P="$PWD"
PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python; SERVER=http://127.0.0.1:8000; L="${LOG:-$P/run_gemma108.out}"
say(){ echo "$(date '+%F %T') $*" >> $L; }
true
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
case "$ARM" in
  lib)     unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE ;;
  alone)   export VERIBIM_NO_GEOM=1; unset VERIBIM_USER_NOTE_FILE ;;
  libnote) unset VERIBIM_NO_GEOM; export VERIBIM_USER_NOTE_FILE=$P/runs_local/bench_v4/geom_prompt_note_frontier.md ;;
  informed) unset VERIBIM_NO_GEOM; export VERIBIM_USER_NOTE_FILE=$P/analysis/revision/informed/note_informed.md ;;
  *) say "unknown ARM $ARM"; exit 2 ;;
esac
RUN=$B/results/local108_${ARM}_all; mkdir -p $RUN
test ! -e $RUN/per_task_${NAME}.jsonl || { say "$RUN/per_task_${NAME}.jsonl exists; refusing"; exit 2; }
curl -s $SERVER/v1/models >/dev/null || { say "server not up"; exit 2; }
if [ -n "$APATH" ]; then
  curl -s -o /dev/null -X POST $SERVER/v1/unload_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$NAME\"}" || true
  curl -s -X POST $SERVER/v1/load_lora_adapter -H 'Content-Type: application/json' -d "{\"lora_name\": \"$NAME\", \"lora_path\": \"$APATH\"}" >> $L 2>&1; echo >> $L
fi
curl -s $SERVER/v1/models | $PY -c "import sys,json; ids=[m['id'] for m in json.load(sys.stdin)['data']]; assert '$NAME' in ids, ids" || { say "not served: $NAME"; exit 1; }
say "START local 324 $ARM $NAME"
taskset -c ${GATE_CORES:-20-23} $PY -u -m stage_a.run_gate --adapters "$NAME" --base-url $SERVER/v1 --subset $B/subset_108_hosted.v4c.json --tasks-file $B/tasks.v4c.jsonl \
   --run-dir $RUN --gold-cache $B/_gold_cache --concurrency ${CONC:-8} --score-workers ${SW:-2} --scorer-reading family \
   --label "VeriBIM-Bench v4b 108-task subset, $ARM arm, local $NAME, sandbox guard" > $RUN/$NAME.log 2>&1
say "END local 324 $ARM $NAME rc=$?"; bash $B/finish_read.sh $RUN $NAME > /dev/null; say "$(grep '^ALL' $RUN/by_version_$NAME.txt)"
