#!/bin/bash
# Deletion re-run campaign chain (v4e), 2026-10-16: hosted (API) first on cores 20-23, then the 9B canonical server pass,
# the 9B own-template pass, then Gemma. Each stage is the agent-built script; this chain only orders them and runs the servers.
P="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"; D=$P/analysis/revision/ground_truth_repair/delete_rerun; L=$D/logs/chain_delete.log
say(){ echo "$(date '+%F %T') $*" >> $L; }
say "chain start"
setsid nohup bash $D/rerun_delete_hosted.sh > $D/logs/rerun_delete_hosted.out 2>&1 < /dev/null &
HP=$!; say "hosted launched pid $HP"
while kill -0 $HP 2>/dev/null; do sleep 30; done; say "hosted finished: $(ls $D | grep -o 'RERUN_DELETE_HOSTED_[A-Z_]*' | paste -sd' ')"
# pass 1: canonical 9B server (Stage C serve script: veribim template, 32768 ctx, runtime LoRA)
PYTHONNOUSERSITE=1 UTIL=0.46 CORES=16-19 ADAPTER=$P/checkpoints/stage_a/sft_v10/adapter NAME=sft_v10 LOG=$D/logs/serve_canonical.log setsid nohup bash $P/code/stage_c/scripts_serve.sh > /dev/null 2>&1 < /dev/null &
SP=$!; PG=$(ps -o pgid= -p $SP | tr -d ' '); say "canonical server pid $SP pgid $PG"
for i in $(seq 1 90); do curl -s http://127.0.0.1:8000/v1/models | grep -q '"Qwen3.5-9B"' && break; sleep 10; done
curl -s http://127.0.0.1:8000/v1/models | grep -q '"Qwen3.5-9B"' || { say "canonical server not up"; kill -TERM -- -$PG; exit 1; }
say "START local pass 1"; bash $D/rerun_delete_local.sh > $D/logs/rerun_delete_local_pass1.out 2>&1; say "END local pass 1 rc=$? markers: $(ls $D | grep -o 'RERUN_DELETE_LOCAL_[A-Za-z0-9_]*' | paste -sd' ')"
say "stopping canonical server pgid $PG"; kill -TERM -- -$PG; sleep 40
# pass 2: own-template server (flags of analysis/revision/base_documented/serve_base.sh)
setsid nohup bash -c 'export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1 VLLM_ALLOW_RUNTIME_LORA_UPDATING=1; exec taskset -c 16-19 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm/bin/vllm serve ${BASE_MODEL:-models/Qwen3.5-9B} --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 --max-model-len 65536 --gpu-memory-utilization 0.777 --enable-auto-tool-choice --tool-call-parser qwen3_xml --chat-template ${BASE_MODEL:-models/Qwen3.5-9B}/chat_template.jinja --language-model-only --enable-lora --max-lora-rank 16 --max-loras 1' >> $D/logs/serve_owntemplate.log 2>&1 < /dev/null &
SP=$!; PG=$(ps -o pgid= -p $SP | tr -d ' '); say "own-template server pid $SP pgid $PG"
for i in $(seq 1 90); do curl -s http://127.0.0.1:8000/v1/models | grep -q '"Qwen3.5-9B"' && break; sleep 10; done
curl -s http://127.0.0.1:8000/v1/models | grep -q '"Qwen3.5-9B"' || { say "own-template server not up"; kill -TERM -- -$PG; exit 1; }
say "START local pass 2"; bash $D/rerun_delete_local.sh > $D/logs/rerun_delete_local_pass2.out 2>&1; say "END local pass 2 rc=$? markers: $(ls $D | grep -o 'RERUN_DELETE_LOCAL_[A-Za-z0-9_]*' | paste -sd' ')"
say "stopping own-template server pgid $PG"; kill -TERM -- -$PG; sleep 40
say "START gemma"; bash $D/rerun_delete_gemma.sh > $D/logs/rerun_delete_gemma.out 2>&1; say "END gemma rc=$? markers: $(ls $D | grep -o 'RERUN_DELETE_GEMMA_[A-Z_]*' | paste -sd' ')"
say "CHAIN DONE"
