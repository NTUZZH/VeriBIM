# Preference-stage seed replication, 324-task subset, with the library, completion = all three axes >= 0.9

| Model | Seed | Completion | Minus imitation (paired, 10,000 resamples, seed 20260929) | Tasks gained / lost |
|---|---|---|---|---|
| Imitation model (sft_v10) | 20260929 | 0.9568 | | |
| Preference snapshot c6, reported (dpo_v10_c6) | 20260929 | 0.9537 | -0.0031 [-0.0093, 0.0000] | 0 / 1 |
| Preference snapshot c6, seed 2 (dpo_v10_s2_c6) | 20261007 | 0.9630 | +0.0062 [0.0000, +0.0154] | 2 / 0 |
| Preference snapshot c6, seed 3 (dpo_v10_s3_c6) | 20261008 | 0.9568 | 0.0000 [-0.0093, +0.0093] | 1 / 1 |

Three-seed mean 0.9578 against 0.9568 for the imitation model; 321 of 324 tasks receive the same verdict from all three seeds. Same pairs file (133 pairs, md5 fb53da53...), same recipe and step (6); only the random seed differs (comparator VERDICT OK at dry run, mid-run and end). The 2,100-task reads were skipped for disk space (32 GB free; a read needs about 43 GB).
