#!/bin/bash
# Hybrid baseline (internal review M4, 2026-10-26): an untrained LLM rewrites each request into the generator's template wording,
# the template parser executes it, the checker scores it. Two canonicalizers (Claude Sonnet 5.5 API; untrained Qwen3.5-9B, thinking off,
# served locally on 127.0.0.1:8000) x two task sets (172 reworded benchmark tasks; 200 practitioner requests).
# Stage 1: canonicalize (four jobs in parallel). Stage 2: parser scoring, one run at a time, each with its own gold cache.
set -u
H=analysis/revision/hybrid_baseline; P="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"; PY=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
RW=$P/analysis/revision/reworded_benchmark; CP=$P/analysis/revision/colleague_packets/results
L=$H/logs/run_hybrid.log; say(){ echo "$(date '+%F %T') $*" | tee -a $L; }; fail(){ say "FAILED $*"; touch $H/HYBRID_FAILED; exit 1; }
export PYTHONPATH=$P/code PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
cd $P || fail cd
say "=== hybrid baseline start (pgid $(ps -o pgid= $$ | tr -d ' '))"
curl -s --max-time 10 http://127.0.0.1:8000/v1/models | grep -q Qwen3.5-9B || fail "no local base server"
canon(){ # name backend tasks subset
  taskset -c 18-19 $PY -u $H/canonicalize.py --backend $2 --thinking off --max-tokens ${MAXTOK:-1024} --tasks $3 --subset $4 --out $H/in/canon_$1.jsonl --conc 4 > $H/logs/canon_$1.log 2>&1; echo "$1 rc=$?" >> $L; }
say "stage 1: canonicalize"
MAXTOK=512  canon rw_local   local     $RW/tasks_bench_rw.jsonl $RW/subset_bench_rw.json &
MAXTOK=1024 canon rw_sonnet  anthropic $RW/tasks_bench_rw.jsonl $RW/subset_bench_rw.json &
MAXTOK=512  canon prac_local local     $CP/rewrite_tasks.jsonl  $CP/rewrite_subset.json &
MAXTOK=1024 canon prac_sonnet anthropic $CP/rewrite_tasks.jsonl $CP/rewrite_subset.json &
wait
for n in rw_local rw_sonnet prac_local prac_sonnet; do
  c=$(wc -l < $H/in/canon_$n.jsonl 2>/dev/null || echo 0); say "canon $n: $c rows, $(tail -1 $H/logs/canon_$n.log)"; done
[ "$(wc -l < $H/in/canon_rw_local.jsonl)" -eq 172 ] && [ "$(wc -l < $H/in/canon_rw_sonnet.jsonl)" -eq 172 ] && [ "$(wc -l < $H/in/canon_prac_local.jsonl)" -eq 200 ] && [ "$(wc -l < $H/in/canon_prac_sonnet.jsonl)" -eq 200 ] || fail "canonicalizer row counts"
say "stage 2: parser scoring (sequential, cores 20-23, 2 workers, guard + Landlock, fresh gold cache per run)"
for n in rw_sonnet rw_local prac_sonnet prac_local; do
  case $n in rw_*) SUB=$RW/subset_bench_rw.json;; prac_*) SUB=$CP/rewrite_subset.json;; esac
  mkdir -p $H/scoring/$n
  VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1 taskset -c 20-23 $PY -u $P/analysis/revision/parser_baseline/run_parser.py \
    --out $H/scoring/$n/per_task_parser.jsonl --tasks $H/in/canon_$n.jsonl --subset $SUB --workers 2 \
    --tmp $H/scoring/$n/tmp --gold-cache $H/scoring/$n/gold_cache > $H/logs/score_$n.log 2>&1; say "score $n rc=$? rows=$(wc -l < $H/scoring/$n/per_task_parser.jsonl)"
done
say "=== HYBRID_DONE"; touch $H/HYBRID_DONE
