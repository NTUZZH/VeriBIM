#!/bin/bash
# Serve Gemma 4 31B instruct (4-bit AWQ, QuantTrio/gemma-4-31B-it-AWQ) for the documented-library arm.
# Served from the l2vllm_gemma environment (transformers 5.14.1, the version whose Gemma 4 config vLLM 0.27.1 reads), with the NVML workaround plugin installed there too.
export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1 OMP_NUM_THREADS=4
exec taskset -c 16-19 "${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm_gemma/bin/vllm" serve "${GEMMA_MODEL:-models/gemma-4-31B-it-AWQ}" \
  --served-model-name gemma-4-31b-it-awq --port 8000 --host 127.0.0.1 --max-model-len 65536 --max-num-seqs 16 --gpu-memory-utilization 0.90 \
  --enable-auto-tool-choice --tool-call-parser gemma4 --reasoning-parser gemma4 --language-model-only \
  >> "${LOG:-serve_gemma.out}" 2>&1
