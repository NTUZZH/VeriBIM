#!/bin/bash
# One-task connectivity and balance check per provider for the asknote arm (directories *_smoke1_all, never reported).
cd "$(dirname "${BASH_SOURCE[0]}")/../../.."; D=analysis/revision/commercial_reruns
( LIMIT=1 SUBSET=hosted ARM=asknote HOSTED=anthropic CONC=1 SW=1 bash $D/eval_rerun.sh claude-sonnet-5-5 > $D/smoke_anthropic.out 2>&1 ) &
( LIMIT=1 SUBSET=hosted ARM=asknote HOSTED=openai VERIBIM_REASONING_EFFORT=none CONC=1 SW=1 bash $D/eval_rerun.sh gpt-5.6-luna > $D/smoke_openai.out 2>&1 ) &
( LIMIT=1 SUBSET=hosted ARM=asknote HOSTED=gemini CONC=1 SW=1 bash $D/eval_rerun.sh gemini-3.8-flash > $D/smoke_gemini.out 2>&1 ) &
( LIMIT=1 SUBSET=hosted ARM=asknote HOSTED=deepseek CONC=1 SW=1 bash $D/eval_rerun.sh deepseek-v4-pro > $D/smoke_deepseek.out 2>&1 ) &
wait; echo "$(date '+%F %T') smokes finished" >> $D/eval_rerun.log
