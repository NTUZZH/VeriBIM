#!/usr/bin/env bash
# Run run_validity.py detached on cores 8-9 with two worker processes.
#   usage: run_validity.sh CONFIG.json [--preflight-only]
# The log goes next to the config's JSON output (<json>.log); the exit code is appended as "exit N".
set -u
CFG=$(readlink -f "$1"); shift
PY=python
HERE=analysis/validity
LOG=$($PY -c "import json,sys; print(json.load(open(sys.argv[1]))['out']['json'] + '.log')" "$CFG") || exit 2
mkdir -p "$(dirname "$LOG")"
setsid nohup taskset -c 8-9 env OMP_NUM_THREADS=2 MKL_NUM_THREADS=2 PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 \
  bash -c "$PY -u $HERE/run_validity.py --config '$CFG' $* ; echo \"exit \$?\"" > "$LOG" 2>&1 < /dev/null &
echo "started pid $! ; log $LOG"
