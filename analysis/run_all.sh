#!/bin/bash
# Rerun the released generator scripts on the released result files. Every output goes to analysis_out/;
# the README lists which installed macro file of the paper each step reproduces.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
PY="${PYTHON:-python}"
mkdir -p analysis_out/template_check analysis_out/slices
$PY analysis/check_unscored.py results
$PY analysis/make_macros.py --config analysis/config.json --out-tex analysis_out/macros_pm_main.tex --out-json analysis_out/values_pm_main.json --fragments-prefix analysis_out/main_
$PY analysis/flip_rate.py results/benchmark/stage_models/per_task_grpo_v14_c20.jsonl results/subset108/veribim9b/per_task_grpo_v14_c20.jsonl --subset tasks/benchmark/subset_108.json --out analysis_out/flip_rate_108.json
$PY analysis/flip_rate.py results/benchmark/stage_models/per_task_grpo_v14_c20.jsonl results/subset324/veribim9b/per_task_grpo_v14_c20.jsonl --subset tasks/benchmark/subset_324.json --out analysis_out/flip_rate_324.json
$PY analysis/make_macros_flip.py analysis_out/flip_rate_324.json analysis_out/flip_rate_108.json analysis_out/macros_pm_flip.tex
$PY analysis/make_macros_seeds.py tasks/benchmark/subset_324.json results/subset324/preference_stage_seeds/per_task_dpo_v14_c6.jsonl results/subset324/preference_stage_seeds/per_task_dpo_v14_s2_c6.jsonl results/subset324/preference_stage_seeds/per_task_dpo_v14_s3_c6.jsonl analysis_out/macros_pm_seeds.tex analysis_out/values_seeds.json
$PY analysis/make_macros_nolist_subsets.py --with108 results/subset108/veribim9b/per_task_grpo_v14_c20.jsonl --without108 results/subset108/veribim9b_without_list/per_task_grpo_v14_c20.jsonl --with324 results/subset324/veribim9b/per_task_grpo_v14_c20.jsonl --without324 results/subset324/veribim9b_without_list/per_task_grpo_v14_c20.jsonl --subset108 tasks/benchmark/subset_108.json --subset324 tasks/benchmark/subset_324.json --out-tex analysis_out/macros_pm_nolist_sub.tex --out-json analysis_out/values_nolist_sub.json
$PY analysis/make_macros_nolist_rows.py analysis/config.json results/subset108/veribim9b/per_task_grpo_v14_c20.jsonl results/subset108/veribim9b_without_list/per_task_grpo_v14_c20.jsonl results/subset324/veribim9b/per_task_grpo_v14_c20.jsonl results/subset324/veribim9b_without_list/per_task_grpo_v14_c20.jsonl results/relation_gate/gate_sub108_nolist.jsonl analysis_out/macros_pm_nolist_rows.tex analysis_out/values_nolist_rows.json
$PY analysis/compare_runs.py stock_template results/subset108/veribim9b/per_task_grpo_v14_c20.jsonl training_template results/template_check/subset108/per_task_grpo_v14_c20.jsonl --out analysis_out/template_check/compare_sub108.json
$PY analysis/compare_runs.py stock_template results/reworded/stage_models/per_task_grpo_v14_c20.jsonl training_template results/template_check/reworded/per_task_grpo_v14_c20.jsonl --out analysis_out/template_check/compare_rw.json
$PY analysis/compare_runs.py stock_template results/practitioner/stage_models/per_task_grpo_v14_c20.jsonl training_template results/template_check/practitioner/per_task_grpo_v14_c20.jsonl --out analysis_out/template_check/compare_prac.json
$PY analysis/make_macros_tplcheck.py analysis_out/macros_pm_tplcheck.tex analysis_out/values_tplcheck.json
$PY analysis/make_macros_orphans.py analysis/config.json analysis_out/macros_pm_orphans.tex analysis_out/values_orphans.json
$PY analysis/make_macros_genfunnel.py analysis_out/macros_pm_genfunnel.tex analysis_out/values_genfunnel.json
$PY analysis/make_macros_cost.py --solo results/subset108/veribim9b_one_task_at_a_time/per_task_grpo_v14_c20.jsonl --sixteen results/subset108/veribim9b/per_task_grpo_v14_c20.jsonl --log results/subset108/timing/contention_snapshots.txt --markers results/subset108/timing --out-tex analysis_out/macros_pm_cost.tex --out-json analysis_out/values_cost.json
$PY analysis/make_macros_gateprac.py analysis_out/macros_pm_gateprac.tex analysis_out/values_gateprac.json
$PY analysis/prac_failures.py results/practitioner/stage_models/per_task_grpo_v14_c20.jsonl analysis_out/macros_pm_pracfail
$PY analysis/validation/name_reported_model.py results/validation/val_hard results/validation/val_hard dpo_v14_c6 grpo_v14_c20 analysis_out/reported_model_rule.txt
$PY analysis/slice_subset.py results/benchmark/stage_models/per_task_sft_v14.jsonl tasks/benchmark/subset_108.json analysis_out/slices/per_task_sft_v14_sub108.jsonl
$PY analysis/slice_subset.py results/benchmark/stage_models/per_task_sft_v14.jsonl tasks/benchmark/subset_324.json analysis_out/slices/per_task_sft_v14_sub324.jsonl
$PY analysis/make_macros_set2.py --config analysis/config.json --props1 results/practitioner/request_properties_first_set.csv --props2 results/practitioner/request_properties_second_set.csv --a2 results/practitioner/second_set/veribim9b/per_task_grpo_v14_c20.jsonl --b2 results/practitioner/second_set/veribim9b_without_list/per_task_grpo_v14_c20.jsonl --c2 results/practitioner/second_set/base_documented/per_task_Qwen3.5-9B.jsonl --out-tex analysis_out/macros_pm_set2.tex --out-json analysis_out/values_set2.json --out-tables analysis_out/set2_tables
$PY analysis/make_macros_basemodels.py analysis/config_basemodels_q4b.json analysis_out/macros_pm_basemodels.tex analysis_out/values_basemodels.json
