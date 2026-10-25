#!/bin/bash
# Download the 4-bit AWQ Gemma 4 31B instruct weights (QuantTrio/gemma-4-31B-it-AWQ, Apache 2.0, about 20 GB) for the documented-library arm.
L="${LOG:-download.out}"
echo "$(date '+%F %T') start; free $(df -h / | awk 'NR==2{print $4}')" >> $L
taskset -c 16-17 hf download QuantTrio/gemma-4-31B-it-AWQ --local-dir models/gemma-4-31B-it-AWQ >> $L 2>&1
echo "$(date '+%F %T') rc=$? ; free $(df -h / | awk 'NR==2{print $4}')" >> $L; echo DOWNLOAD_DONE >> $L
