#!/bin/bash
# Score the template-inversion parser on benchmark tasks.
#   run_parser.sh <out.jsonl relative to this folder> [extra run_parser.py args]
# Runs from the project root on cores 16-23 with two worker processes, the
# sandbox guard and the Landlock ruleset switched on.  Resumable: tasks already
# in <out> are skipped.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
PY="${L2_PYTHON:-python}"
OUT="${1:-results/per_task_parser.jsonl}"
shift || true
cd "$ROOT" || exit 1
export PYTHONPATH="$ROOT/code" PYTHONNOUSERSITE=1 OMP_NUM_THREADS=1 \
       MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
       VERIBIM_SANDBOX_GUARD=1 VERIBIM_SANDBOX_LANDLOCK=1
echo "$(date '+%F %T') start $OUT $*"
taskset -c 16-23 "$PY" -u "$HERE/run_parser.py" --out "$OUT" --workers 2 "$@"
rc=$?
echo "$(date '+%F %T') exit $rc"
exit $rc
