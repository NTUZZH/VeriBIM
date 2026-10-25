#!/bin/bash
# The four library-note arms with the sentence that tells the model to ask (ARM=asknote), then two repeats of the documented
# claude-sonnet-5-5 run (RUNTAG=rep2, rep3). Run from anywhere; provider keys in the environment.
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."; D=analysis/revision/commercial_reruns; L=$D/run_all.log
say(){ echo "$(date '+%F %T') $*" >> $L; }
PYW=${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python
wd(){ :; }   # a stall watchdog of the workstation guarded each run; it is not part of this repository
wd_workstation(){ # watchdog for one run dir / model: idle 120 min -> TERM the gate
  local run=$1 model=$2
  setsid nohup $PYW runs_local/tools/stall_watchdog.py --watch "runs_local/bench_v4/results/$run/$model/**" --idle-min 120 --marker "$D/STALL_${run}_${model}" \
    --alive-regex "^${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u -m stage_a\.run_gate --adapters $model .*--run-dir runs_local/bench_v4/results/$run " \
    --kill-regex  "^${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python -u -m stage_a\.run_gate --adapters $model .*--run-dir runs_local/bench_v4/results/$run " >> "$D/watchdog_${run}_${model}.log" 2>&1 < /dev/null &
}
say "asknote arms start"
wd hosted108_asknote_all claude-sonnet-5-5; wd hosted108_asknote_all gpt-5.6-luna; wd hosted108_asknote_all gemini-3.8-flash; wd hosted108_asknote_all deepseek-v4-pro
( SUBSET=hosted ARM=asknote HOSTED=anthropic CONC=4 SW=2 bash $D/eval_rerun.sh claude-sonnet-5-5 > $D/launch_asknote_anthropic.out 2>&1 ) &
( SUBSET=hosted ARM=asknote HOSTED=openai VERIBIM_REASONING_EFFORT=none CONC=4 SW=2 bash $D/eval_rerun.sh gpt-5.6-luna > $D/launch_asknote_openai.out 2>&1 ) &
( SUBSET=hosted ARM=asknote HOSTED=gemini CONC=4 SW=2 bash $D/eval_rerun.sh gemini-3.8-flash > $D/launch_asknote_gemini.out 2>&1 ) &
( SUBSET=hosted ARM=asknote HOSTED=deepseek CONC=4 SW=2 bash $D/eval_rerun.sh deepseek-v4-pro > $D/launch_asknote_deepseek.out 2>&1 ) &
wait; say "asknote arms done"
for rep in rep2 rep3; do
  say "sonnet documented $rep start"; wd hosted108_informed_${rep}_all claude-sonnet-5-5
  SUBSET=hosted ARM=informed RUNTAG=$rep HOSTED=anthropic CONC=4 SW=2 bash $D/eval_rerun.sh claude-sonnet-5-5 > $D/launch_informed_${rep}.out 2>&1
  say "sonnet documented $rep done"
done
say "ALL DONE"; touch $D/ALL_DONE
