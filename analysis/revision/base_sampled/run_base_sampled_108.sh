#!/bin/bash
# The untrained base model alone (no library, no note) on the 108-task subset with the model card's
# recommended sampling. ARM=sampled: non-thinking, temperature 0.7, top-p 0.8, top-k 20, presence penalty 1.5.
# ARM=thinking: thinking on, temperature 0.6, top-p 0.95, top-k 20 (the card's precise/coding setting). Seed 20261007.
set -u; cd "$(dirname "${BASH_SOURCE[0]}")/../../.."; B=runs_local/bench_v4; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
ARM="${ARM:?sampled or thinking}"; L=analysis/revision/base_sampled/run_${ARM}.log
say(){ echo "$(date '+%F %T') $*" >> $L; }
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONNOUSERSITE=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1 VERIBIM_NO_GEOM=1
unset VERIBIM_USER_NOTE_FILE VERIBIM_REQUEST_STYLE
export VERIBIM_LOCAL_TOP_K=20 VERIBIM_LOCAL_SEED=20261007
case "$ARM" in
  sampled)  export VERIBIM_LOCAL_TEMPERATURE=0.7 VERIBIM_LOCAL_TOP_P=0.8 VERIBIM_LOCAL_PRESENCE_PENALTY=1.5 VERIBIM_CHAT_TEMPLATE_KWARGS='{"enable_thinking": false}' ;;
  thinking) export VERIBIM_LOCAL_TEMPERATURE=0.6 VERIBIM_LOCAL_TOP_P=0.95 VERIBIM_CHAT_TEMPLATE_KWARGS='{"enable_thinking": true}' ;;
  *) echo "unknown ARM"; exit 2 ;;
esac
RUN=$B/results/local108_alone_${ARM}_all; [ "${LIMIT:-0}" = 0 ] || RUN=${RUN}_smoke${LIMIT}; mkdir -p $RUN
test ! -e $RUN/per_task_Qwen3.5-9B.jsonl || { say "exists; refusing"; exit 2; }
curl -s http://127.0.0.1:8000/v1/models | grep -q '"Qwen3.5-9B"' || { say "server not up"; exit 2; }
say "START base alone, $ARM sampling, 108 subset (T=$VERIBIM_LOCAL_TEMPERATURE top_p=$VERIBIM_LOCAL_TOP_P top_k=$VERIBIM_LOCAL_TOP_K pp=${VERIBIM_LOCAL_PRESENCE_PENALTY:-0} kwargs=$VERIBIM_CHAT_TEMPLATE_KWARGS)"
taskset -c 8-9 $PY -u -m stage_a.run_gate --adapters Qwen3.5-9B --limit ${LIMIT:-0} --base-url http://127.0.0.1:8000/v1 --subset $B/subset_108_hosted.v4c.json --tasks-file $B/tasks.v4c.jsonl \
   --run-dir $RUN --gold-cache $B/_gold_cache --concurrency 8 --score-workers 2 --scorer-reading family \
   --label "VeriBIM-Bench v4c hosted subset, base model alone, $ARM sampling, sandbox guard" > $RUN/Qwen3.5-9B.log 2>&1
say "END rc=$?"; bash $B/finish_read.sh $RUN Qwen3.5-9B > /dev/null; say "$(grep '^ALL' $RUN/by_version_Qwen3.5-9B.txt)"
