#!/bin/bash
W=analysis/revision/reworded_benchmark; P="${PROJECT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
L=$W/reads/stage_reads.log; say(){ echo "$(date '+%F %T') $*" >> $L; }
say "START stage reads"
NAME=sft_v10 AP=$P/checkpoints/stage_a/sft_v10/adapter bash $W/read_model_rw_adapter.sh >> $W/reads/stage_reads.out 2>&1; say "sft_v10 rc=$?"
NAME=dpo_v10_c6 AP=$P/checkpoints/stage_b/dpo_v10/checkpoint-6 bash $W/read_model_rw_adapter.sh >> $W/reads/stage_reads.out 2>&1; say "dpo_v10_c6 rc=$?"
say "=== STAGE READS DONE"
