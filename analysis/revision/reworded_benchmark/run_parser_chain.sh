#!/bin/bash
W=analysis/revision/reworded_benchmark
L=$W/reads/parser_chain.log; say(){ echo "$(date '+%F %T') $*" >> $L; }
mkdir -p $W/reads/parser
say "START parser on reworded"
L2_PYTHON=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python bash analysis/revision/parser_baseline/run_parser.sh \
  $W/reads/parser/per_task_parser_rw.jsonl --tasks $W/tasks_bench_rw.jsonl --subset $W/subset_bench_rw.json \
  --tmp $W/reads/parser/tmp --gold-cache $W/reads/parser/gold_cache_v4d > $W/reads/parser_rw.log 2>&1; say "parser reworded rc=$?"
L2_PYTHON=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python bash analysis/revision/parser_baseline/run_parser.sh \
  $W/reads/parser/per_task_parser_original.jsonl --tasks runs_local/bench_v4/tasks.v4d.jsonl \
  --subset $W/draw_ids_200.json --tmp $W/reads/parser/tmp --gold-cache $W/reads/parser/gold_cache_v4d > $W/reads/parser_original.log 2>&1; say "parser original rc=$?"
taskset -c 16-23 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python $W/summarize_rw.py > $W/reads/summarize_rw.out 2>&1; say "summarize rc=$?"
say "=== PARSER CHAIN DONE"
