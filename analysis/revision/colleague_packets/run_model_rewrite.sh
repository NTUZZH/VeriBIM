#!/bin/bash
# VeriBIM-9B (grpo_v10b_c10 = checkpoints/stage_c/grpo_v10b/snapshots/step_10) on the colleague-written requests, as deployed
# (library in the sandbox, no note). Server exactly as the benchmark reads (serve_base.sh flags), cores 16-19; harness cores 20-23.
set -u; cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)" || exit 1
C=analysis/revision/colleague_packets; RUN=$C/results/model; B=runs_local/bench_v4
NAME=grpo_v10b_c10; APATH=checkpoints/stage_c/grpo_v10b/snapshots/step_10
say(){ echo "$(date '+%F %T') $*"; }
export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1
say "serve start"
setsid nohup taskset -c 16-19 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm/bin/vllm serve ${BASE_MODEL:-models/Qwen3.5-9B} \
  --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 --max-model-len 65536 --gpu-memory-utilization 0.777 \
  --enable-auto-tool-choice --tool-call-parser qwen3_xml --chat-template ${BASE_MODEL:-models/Qwen3.5-9B}/chat_template.jinja \
  --language-model-only --enable-lora --max-lora-rank 16 --max-loras 1 --lora-modules "$NAME=$APATH" \
  > $RUN/serve.log 2>&1 < /dev/null &
SPID=$!; echo $SPID > $RUN/serve.pid; say "server pid $SPID (pgid $(ps -o pgid= -p $SPID | tr -d ' '))"
for i in $(seq 1 120); do curl -s http://127.0.0.1:8000/v1/models >/dev/null 2>&1 && break; sleep 10; done
curl -s http://127.0.0.1:8000/v1/models | ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -c "import sys,json; ids=[m['id'] for m in json.load(sys.stdin)['data']]; assert '$NAME' in ids, ids; print('served', ids)" || { say "server not up / adapter missing"; exit 1; }
export PYTHONPATH=code OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
unset VERIBIM_NO_GEOM VERIBIM_USER_NOTE_FILE
say "START read"
taskset -c 20-23 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u -m stage_a.run_gate --adapters "$NAME" --base-url http://127.0.0.1:8000/v1 \
   --subset $C/results/rewrite_subset.json --tasks-file $C/results/rewrite_tasks.jsonl \
   --run-dir $RUN --gold-cache $B/_gold_cache --concurrency 16 --score-workers 2 --scorer-reading family \
   --label "colleague-written requests (packet A), as-deployed arm, local $NAME, sandbox guard" > $RUN/$NAME.log 2>&1
say "END read rc=$?"
PG=$(ps -o pgid= -p $(cat $RUN/serve.pid) | tr -d ' '); say "stopping server pgid $PG"; kill -TERM -- -$PG; sleep 20
bash $B/finish_read.sh $RUN $NAME > /dev/null 2>&1; say "$(grep '^ALL' $RUN/by_version_$NAME.txt 2>/dev/null)"; say "ALL DONE"
