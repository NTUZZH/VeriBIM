# VeriBIM

This repository holds the code, task definitions, per-task results and adapter weights of the paper
"VeriBIM: a ground-truth-first framework for generating, training and testing language-model edits of IFC building models" by Ziheng
Zhang and Wei Zhang, Singapore Institute of Technology (manuscript under review, 2026). The work trains a local
language model, Qwen3.5-9B by the Qwen Team [1], to edit IFC building models from natural-language
instructions. The repository contains:

- a task generator that turns real IFC models into editing tasks whose instruction, reference edit script
  and ground-truth model agree by construction;
- a deterministic checker that scores an edited model against the reference edit on geometry, semantics
  and topology;
- a helper library of geometry and IFC-schema functions that the model calls while it edits;
- the evaluation harness (sandbox, agent loop, chat client, model serving);
- the training code of the three stages (imitation, preference optimisation, reinforcement learning);
- the scripts that built the source-model pools, the benchmark and the validation sets;
- the trained adapter, the training, benchmark and validation task definitions, and the per-task results of
  every reported run.

## Layout

```
code/
  modifc_gen/       task generator
  modifc_score/     checker (geometry, semantics and topology scores)
  harness/          evaluation harness; modifc_harness/veribim_geom.py is the helper library
  corpus/           scripts that download, scan and register the source building models
  stage_a/          stage 1, imitation (supervised fine-tuning), and the evaluation entry point run_gate
  stage_b/          stage 2, preference optimisation (DPO) on pairs sampled from the stage-1 model
  stage_c/          stage 3, reinforcement learning (GRPO) with the checker as the reward
  tables/           script that rebuilds the paper's result tables, macros and figures from results/
scripts/
  corpus/           schema migration (two versions), source-model pools, training-task merging and repairs,
                    the clearance screen and the corrected reading of "opposite" references
  benchmark/        benchmark selection (with the selection driver in selection/), ground-truth
                    materialisation, paraphrases, the 500-task validation set, audits
  validation/       the builder and the ranking step of the 300-task hard validation set
  training/         the script that collects the task records behind the imitation data
tasks/
  train/            the training task sets of the three stages (see "Training task sets")
  benchmark/        the 2,100-task benchmark, the 108-task and 324-task subsets, the library note
  val_hard/         the 300-task hard validation set used to select training snapshots, with its candidates
                    and their ranking
  val_500/          the 500-task validation set and its 100-task subset
results/
  benchmark/        per-task results of every reported run on the benchmark and its subsets
  val_hard/         per-task results and selection curves on the hard validation set
  val_500/          selection curve of the preference stage on the 500-task validation set
  repeatability/    changed outcomes between two identical runs of the same model
  training/         counts of the preference-pair construction
  bimedit/          per-task BIM-Edit scores of the trained models, of the untrained base model, and of
                    Claude Sonnet 5.5 in two arms (sonnet_alone/, sonnet_lib/)
analysis/
  revision/         scripts and outputs of the analyses added in releases v1.1.0 to v1.1.5 (see "Release v1.1.0"
                    to "Release v1.1.5")
weights/            adapter of the final model (see "Adapter weights")
```

The generator, the checker, the harness and the stage-1 and stage-3 packages each have a README with the
details of their design.

## Results summary

The values below are the paper's headline results, computed from the files in `results/`. A task counts
as completed when its geometry, semantics and topology scores are all at least 0.9. Intervals are 95 %
percentile bootstrap intervals over tasks (10,000 resamples, seed 20260929).

| Task set | Model | Result |
|---|---|---|
| 2,100-task benchmark | VeriBIM-9B | completion 0.957 (0.948 to 0.965), 2,010 tasks completed, mean score 0.961 |
| 108-task subset | VeriBIM-9B | completion 0.972 (0.935 to 1.000), 105 of 108 |
| 108-task subset | Claude Sonnet 5.5, documented setting | completion 0.991, VeriBIM-9B minus this setting -0.019 (-0.056 to 0.019) |
| 108-task subset | Claude Opus 5.5, documented setting | completion 0.954, VeriBIM-9B minus this setting 0.019 (-0.028 to 0.074) |
| 108-task subset | DeepSeek V4, documented setting | completion 0.898, VeriBIM-9B minus this setting 0.074 (0.019 to 0.130) |
| 108-task subset | Gemini 3.8 Flash, documented setting | completion 0.750, VeriBIM-9B minus this setting 0.222 (0.148 to 0.306) |
| 108-task subset | GPT-5.6, documented setting | completion 0.639, VeriBIM-9B minus this setting 0.333 (0.250 to 0.426) |
| 108-task subset | Qwen3.5-9B (untrained base), documented library | completion 0.648, VeriBIM-9B minus this setting 0.324 (0.241 to 0.407) |
| 108-task subset | Gemma 4 31B (4-bit AWQ), documented setting | completion 0.704, 76 of 108 |
| 108-task subset | Qwen3.5-9B (untrained base), documented library note with three retrieved training trajectories | completion 0.880, 95 of 108 |
| 108-task subset | Qwen3.5-9B (untrained base), short library note with three retrieved training trajectories | completion 0.898, 97 of 108 |
| 108-task subset | best commercial model: Claude Sonnet 5.5, with the library and its short note | completion 0.852, 92 of 108 |
| 108-task subset | Claude Sonnet 5.5, library note and the instruction to ask for a missing value | completion 0.954, 103 of 108 |
| 108-task subset | DeepSeek V4, library note and the instruction to ask for a missing value | completion 0.815, 88 of 108 |
| 108-task subset | Gemini 3.8 Flash, library note and the instruction to ask for a missing value | completion 0.583, 63 of 108 |
| 108-task subset | GPT-5.6, library note and the instruction to ask for a missing value | completion 0.417, 45 of 108 |
| 2,100-task benchmark | rule-based template parser (no language model) | completion 0.999, 2,098 of 2,100 |
| rewritten-wording set, 85 reworded instructions | rule-based template parser | 0 of 85 completed; VeriBIM-9B completes 82 of 85 |
| 324-task subset | VeriBIM-9B | completion 0.960 (0.938 to 0.978), 311 of 324 |
| 324-task subset | Claude Sonnet 5.5, documented setting | completion 0.981, VeriBIM-9B minus this setting -0.022 (-0.046 to 0.003) |
| BIM-Edit, 324 tasks | VeriBIM-9B | mean score 0.411, under the benchmark's own scoring rules, in this paper's test setup |
| BIM-Edit, 324 tasks | Qwen3.5-9B (untrained base) | mean score 0.291, this arm minus VeriBIM-9B -0.119 (-0.151 to -0.089), under the benchmark's own scoring rules, in this paper's test setup |
| BIM-Edit, 324 tasks | Claude Sonnet 5.5, alone | mean score 0.731, this arm minus VeriBIM-9B 0.320 (0.280 to 0.361), under the benchmark's own scoring rules, in this paper's test setup |
| BIM-Edit, 324 tasks | Claude Sonnet 5.5, with the library and its short note | mean score 0.735, this arm minus VeriBIM-9B 0.324 (0.285 to 0.362), under the benchmark's own scoring rules, in this paper's test setup |

The documented setting gives a model the helper library with its full documentation (see "Release v1.1.0",
"Release v1.1.3" and "Release v1.1.4"). In its rows, the difference is the completion of VeriBIM-9B minus that of
the setting, paired over tasks, with its 95 % interval. The intervals of Claude Sonnet 5.5 and Claude Opus 5.5
contain zero, so neither of these differences is statistically significant, and the intervals of the other three
commercial models and of the untrained base model lie above zero. A pre-specified test on the 216 tasks of the 324-task subset outside the 108-task subset does not establish
equivalence within 5 percentage points. On these tasks VeriBIM-9B completes 0.954 and Claude Sonnet 5.5
in the documented setting 0.977, and the 90 % interval of the difference runs from -0.051 to 0.005 (`analysis/revision/equivalence/equiv_216.json`).

The documented Claude Sonnet 5.5 run was repeated twice with the same note and settings
(`results/benchmark/hosted108_informed_rep2_all/` and `hosted108_informed_rep3_all/`). The three runs complete
107, 107 and 107 of the 108 tasks, and 3 tasks change outcome between runs. The rule-based parser reads
instructions by inverting the generator's sentence templates, so its benchmark result measures how far the
template wording can be read mechanically; on instructions reworded outside the templates it completes
0 of 85 (see "Release v1.1.5").

In the BIM-Edit rows, the difference has the opposite sign: it is the mean score of the arm minus that of
VeriBIM-9B, paired over the 324 tasks, with its 95 % interval. All four BIM-Edit arms ran in this paper's test setup
(at most 22 tool rounds, 8,192 output tokens per turn, 420 s per tool call) and were scored by the published
BIM-Edit rules (`analysis/revision/bimedit_arms/bimedit_arms.json`).

At list prices, the 2,052 commercial task runs reported in the paper cost about US$230.
`analysis/revision/spend/spend_reported.py` computes this cost from the token counts in the per-task result files
and the prices in `code/tables/hosted_cost.py`. All commercial-model calls of the study, including connectivity
tests, repeated runs and runs during development, cost about US$363. Some of these calls have no
released records, so this total cannot be recomputed from the repository.

VeriBIM-9B is the reinforcement-stage snapshot, named `grpo_v10b_c10` in the result files and the release asset.
The other runs in the paper
(the untrained base model, the stage-1 and stage-2 models, a stage-2 model trained on an earlier task corpus,
and four commercial models with and without the helper library) are in `results/benchmark/`, one directory
per run and one `per_task_<model>.jsonl` file per model.

Two further sets of runs support Sections 5.2 and 5.3 of the paper. A chain trained by the same recipe on ten
training buildings (`results/val_hard/ten_building_chain/buildings_small.json`) gives `per_task_sft_small.jsonl`,
`per_task_dpo_small_c12.jsonl` and `per_task_grpo_small_c10.jsonl` in `results/benchmark/full_all/` (completion
0.723, 0.734 and 0.736 on the 2,100 tasks) and the hard-validation-set reads of every snapshot in
`results/val_hard/ten_building_chain/`. A diagnostic continuation of VeriBIM-9B on a creation family that follows
Revit-export conventions (`sft_extA`) gives `per_task_sft_extA.jsonl` in `results/benchmark/local324_lib_all/`
(completion 0.926 on the 324-task subset); its BIM-Edit records are not redistributed, as for every other model.

## Release v1.1.0

Release v1.1.0 adds the runs and analyses below.

- The documented commercial setting gives the strongest commercial model the library note, the documentation of
  every library function, the task conventions and three worked examples. Its per-task results on the 108-task
  subset are in `results/benchmark/hosted108_informed_all/`. The note is
  `analysis/revision/informed/note_informed.md`, written by `build_informed_note.py`, and `eval_informed.sh` is
  the launcher (`ARM=informed`).
- The untrained Qwen3.5-9B was run alone on the 108-task subset with the sampling settings that its model card
  recommends, once without reasoning (`results/benchmark/local108_alone_sampled_all/`) and once with reasoning
  (`results/benchmark/local108_alone_thinking_all/`). `code/harness/modifc_harness/client.py` reads these
  settings from `VERIBIM_LOCAL_TEMPERATURE`, `VERIBIM_LOCAL_TOP_P`, `VERIBIM_LOCAL_TOP_K`,
  `VERIBIM_LOCAL_PRESENCE_PENALTY`, `VERIBIM_LOCAL_SEED` and `VERIBIM_CHAT_TEMPLATE_KWARGS`. A run that sets none
  of them sends the same request as before. The launchers are in `analysis/revision/base_sampled/`.
- Two further seeds of the preference stage (20261007 and 20261008) were trained on the same pairs to the same
  step as the reported seed and read on the 324-task subset with the library. Their per-task results are
  `per_task_dpo_v10_s2_c6.jsonl` and `per_task_dpo_v10_s3_c6.jsonl` in `results/benchmark/local324_lib_all/`, next
  to `per_task_dpo_v10_c6.jsonl` of the reported seed. `analysis/revision/dpo_seeds/` holds the launchers and the
  check of each seed's training configuration against the reported run.
- `analysis/revision/stats/` holds the building-level bootstrap intervals of the reported completion intervals,
  completion at four verdict thresholds and per building, the split between fully specified tasks and tasks that
  need a clarification, the way each run on the 108-task subset ended, and the composition of the benchmark.
- The mutation study writes controlled errors into the ground-truth models of 240 benchmark tasks and scores each
  copy with the reported checker call. `analysis/revision/checker/mutation.py` runs it, and `sample.json`,
  `mutation_results.jsonl` and `mutation_summary.json` hold the sample, the rows and the summary.
- The whole-model off-target diff covers the completed edits of the final model, the imitation model and the four
  commercial models with the library. It compares each edited model with its ground-truth model over all objects,
  relations and property sets. `analysis/revision/checker/offtarget_full.py` runs it, `validate_offtarget.py` and
  `fastpath_check.py` check it, and `offtarget_full.jsonl` and `offtarget_summary.json` hold the rows and the
  summary.
- `analysis/revision/provenance/` holds the structural descriptors of the 79 native student files of the GNI
  dataset in the source-model pool (75 in the training pool, 4 held out) and the scripts that computed them.

The scripts in `analysis/revision/` are released as they were run, with paths relative to the project's working
layout. In that layout, `runs_local/bench_v4/results/` corresponds to `results/benchmark/` and
`runs_local/bench_v4/tasks.v4c.jsonl` to `tasks/benchmark/tasks.v4c.jsonl` in this repository. As for every other
run, the transcripts and the edited models of the new runs are not released.

## Release v1.1.1

Release v1.1.1 adds one run and its analysis.

- The documented commercial setting of release v1.1.0 was also run on the 216 tasks of the 324-task subset that
  the 108-task subset does not contain. `tasks/benchmark/subset_324_rest216.v4c.json` lists these tasks, and their
  per-task results are in `results/benchmark/hosted324rest_informed_all/`. These results and the 108-task results
  in `results/benchmark/hosted108_informed_all/` cover the whole 324-task subset.
- The analysis tests whether VeriBIM-9B and the documented setting are equivalent in completion on these 216 tasks.
  The equivalence margin of 5 percentage points was fixed before the run. The two count as equivalent when the
  90 % paired bootstrap interval of their difference in completion lies within this margin.
  `analysis/revision/equivalence/analyze_216.py` computes the test and its secondary comparisons, and
  `equiv_216.json` holds the output. `eval_informed216.sh` in the same folder is the launcher of the run
  (`SUBSET=rest216 ARM=informed`). Both scripts use the paths of the project's working layout, as described
  under "Release v1.1.0".

## Release v1.1.5

Release v1.1.5 adds the training task sets, the ranking step of the hard validation set, six sets of runs on the
108-task subset, a rule-based parser as a baseline, and the analyses of the revised paper.

- The training task sets of the three stages are in `tasks/train/` (see "Training task sets").
- The hard validation set comes with its 2,996 candidates (`tasks/val_hard/val_hard_candidates.jsonl`, in the
  order of `val_hard_candidate_ids.json`) and their ranking (`val_hard_ranking.jsonl`).
  `scripts/validation/val_hard/rank_val_hard.py` is the ranking step that wrote the set (see "Construction scripts").
- The four commercial models were run again with the library and its short note, followed by one sentence that
  tells the model to ask a question instead of editing when the instruction leaves out a value or a reference the
  edit needs. The sentence overrides the sentence of the system prompt that asks for sensible defaults. The per-task
  results are in `results/benchmark/hosted108_asknote_all/`. `analysis/revision/commercial_reruns/` holds the note
  (`note_lib_override.md`), the launcher (`eval_rerun.sh`, `ARM=asknote`), the sequence of runs (`run_all.sh`) and
  the one-task connectivity checks that preceded them (`smoke_all.sh`, never reported). In the released
  `run_all.sh`, the stall watchdog of the workstation is replaced by a function that does nothing.
- The documented Claude Sonnet 5.5 run of release v1.1.0 was repeated twice with the same note and settings
  (`results/benchmark/hosted108_informed_rep2_all/` and `hosted108_informed_rep3_all/`, `RUNTAG=rep2` and `rep3`
  of `eval_rerun.sh`).
- Gemma 4 31B, a larger open-weight model that fits the same 48 GB card in its 4-bit AWQ version
  (`QuantTrio/gemma-4-31B-it-AWQ`), was run in the documented setting. Its per-task results are
  `per_task_gemma-4-31b-it-awq.jsonl` in `results/benchmark/local108_informed_all/`. `analysis/revision/gemma31b/`
  holds the download, the server (vLLM 0.27.1 with the Gemma 4 tool-call and reasoning parsers and a 65,536-token
  context, from a separate conda environment with transformers 5.14.1) and the launcher.
- The untrained Qwen3.5-9B was run with three training trajectories as worked examples: for each task, the three
  imitation-training rows whose instructions are nearest by TF-IDF cosine, with identifiers, names and numbers
  masked, taken from training buildings only. With the documented library note in which they replace the three
  fixed examples, the per-task results are in `results/benchmark/local108_retrieval_all/`; with the short library
  note, in `results/benchmark/local108_retrievalshort_all/`. `analysis/revision/retrieval_fewshot/` holds the index
  builder (`build_index.py`), the retrieval (`retrieve.py`), the note writer (`build_notes.py`), the 108 notes of
  each arm (`notes/`, `notes_short/`, with SHA-256 manifests in `results/`), the harness entry point that reads one
  note per task (`run_gate_pertask.py`), the launcher and the file-access audit it runs. `results/leakage_checks.json`
  records that the training rows and the 108 tasks share no building, model file or file content. The index needs
  the imitation rows, which are not released, so the notes are the released input of these runs.
- `analysis/revision/parser_baseline/` is a rule-based parser without a language model. It inverts the generator's
  sentence templates and reference phrases (`grammar.py`, `parser.py`), finds the elements with the helper library,
  and writes a program that performs the edit with the generator's own edit functions (`codegen.py`,
  `prelude_src.py` and `code/modifc_gen/goldlib.py`). It asks a question when the instruction leaves out a value.
  `run_parser.py` scores it with the benchmark's checker and completion rule (`run_parser.sh` is the launcher), and
  `summarize.py` writes `results/summary.json`; `results/rewritten/` holds the run on the rewritten-wording set. The
  grammar was extended against the 2,100 benchmark instructions, with the 108-task subset as the development set.
  The tools in `analysis/` list the instruction skeletons and the reasons an instruction was not read.
- `analysis/revision/checker_validity/` adds hard checks for storey containment and opening filling to the checker's
  verdict, measures the absolute position and dimension errors of completed edits, and runs IFC schema validation
  and clash checks on outputs and ground truths. The summaries and the per-element tables are in `results/`; the
  per-task rows are not released.
- `analysis/revision/stats/` adds `run_stats.py` and its modules (`paired_methods.py`, `glmm_ml.py`): exact McNemar
  tests, score intervals for paired differences, Holm adjustment and mixed-effects models of the paired
  comparisons, with the outputs in `analysis/revision/stats/results/`. The run first reproduces the reported
  bootstrap values from the per-task rows (`results/reproduction.csv`).
- `analysis/revision/bimedit_strata/` splits the BIM-Edit scores of `results/bimedit/` by how similar each scene is to
  the closest training model (`bimedit_scene_similarity.json`); it needs the BIM-Edit task file.
- `analysis/revision/colleague_packets/` holds the scripts that drew and rendered the packets of a study with
  colleagues and that collect their answers. The packets, the rendered pages, the answer key and the answers are
  not released.
- `analysis/revision/macros/` holds the script that computes the values and tables of the revised paper from the
  files above, and its output.

The scripts in these folders use the paths of the project's working layout, as described under "Release v1.1.0".

## Release v1.1.4

Release v1.1.4 adds two sets of runs and their analyses.

- The untrained Qwen3.5-9B was run on the 108-task subset in the documented setting of release v1.1.0, with the
  helper library and its full documentation. Its per-task results are in
  `results/benchmark/local108_informed_all/`. `analysis/revision/base_documented/analyze_base_informed.py`
  computes the completion with its interval, the split between fully specified and under-specified tasks, the
  completion at the 0.98 threshold, the rounds, and the paired differences from VeriBIM-9B, from the base model with
  the short library note, from the base model alone and from the documented Claude Sonnet 5.5 run.
  `base_informed.json` holds its output. `run_local108_informed.sh` is the launcher; it takes the served model name,
  an adapter path (empty for the base model) and the arm, and the run used `Qwen3.5-9B "" informed`. Both scripts
  use the paths of the project's working layout, as described under "Release v1.1.0".
- Three further arms ran on all 324 BIM-Edit tasks in this paper's test setup (at most 22 tool rounds, 8,192
  output tokens per turn, 420 s per tool call) and were scored by the published BIM-Edit rules. Claude Sonnet 5.5
  ran alone and with the library and its short note, and its per-task scores are in `results/bimedit/sonnet_alone/`
  and `results/bimedit/sonnet_lib/`. The untrained base model was run again in the same setup, and its
  `scores_bench_Qwen3.5-9B.csv` and `summary_bench_Qwen3.5-9B.json` in `results/bimedit/` replace the files of the
  earlier run. `analysis/revision/bimedit_arms/analyze_bimedit_arms.py` computes, for each arm, the mean score by
  operation and category, the full solves, the rounds and the list-price cost, and a paired task-level bootstrap of
  the arm minus VeriBIM-9B (10,000 resamples, seed 20260929). Its output is `bimedit_arms.json` in the same folder,
  and `bimedit_ids_324.json` lists the task ids in the order the bootstrap uses. The script reads the repository
  layout. It needs the per-task BIM-Edit records, which are not redistributed, so it documents the computation and
  its output file holds the result. `write_summary_bench.py` writes the `summary_bench_<model>.json` file of an arm.

## Release v1.1.3

Release v1.1.3 adds the documented setting of release v1.1.0 for every commercial model on the 108-task subset:
GPT-5.6, DeepSeek V4 and Gemini 3.8 Flash, which had run alone and with the library, and Claude Opus 5.5, which
runs in the documented setting only. Their per-task results are in `results/benchmark/hosted108_informed_all/`
next to the Claude Sonnet 5.5 file. `analysis/revision/documented/analyze_informed4.py` computes, for every
documented run, the completion with its interval, the split between fully specified and under-specified tasks, the
completion at the 0.98 threshold, the rounds, the list-price cost, and the paired differences from VeriBIM-9B and
from the documented Claude Sonnet 5.5 run at task and building level. `informed4.json` holds its output, and
`eval_informed4.sh` is the launcher (`SUBSET=hosted ARM=informed`). The GPT-5.6 run sets
`VERIBIM_REASONING_EFFORT=none`, because its chat-completions endpoint refuses function tools unless reasoning is
off. `analysis/revision/spend/` and the "Results summary" cover these runs.

## Release v1.1.2

Release v1.1.2 adds no run. `analysis/revision/spend/` computes the list-price cost of the reported commercial
runs, and `spend_reported.json` holds the cost per run. The README adds the documented setting and the
equivalence test to "Results summary" and maps the output files of the table script to the paper's tables and
figures in "Reproducing the paper's tables".

## Requirements

The paper's runs used three conda environments on one workstation with one 48 GB GPU.

| Environment | Used for | Main packages |
|---|---|---|
| `l2` | generator, checker, harness, evaluation, result tables | Python 3.14, IfcOpenShell 0.8.5, numpy, scipy, pandas, matplotlib |
| `l2train` | training | Python 3.13, PyTorch 2.11 (CUDA 13.0), transformers 5.5.0, TRL 0.24.0, PEFT 0.20.0, Unsloth 2026.8.19 |
| `l2vllm` | serving the base model with an adapter | vLLM 0.27.1 |

The scripts find the interpreters at `$CONDA_ROOT/envs/<name>/bin/python` (default `~/miniconda3`) and
resolve relative paths against the repository root, which `VERIBIM_ROOT` overrides. The base model is read
from `models/Qwen3.5-9B` unless `VERIBIM_BASE_MODEL` names another directory. Run every command below from
the repository root with

```bash
export PYTHONPATH=code:code/harness
```

## Source building models

The source building models are not redistributed. Each is available from its public source. Every task
record names its source model by a path relative to the repository root and by its SHA-256 checksum
(`source_model.relpath`, `source_model.sha256`), so each downloaded file can be checked against the record.
The corpus registry `code/corpus/build_manifest.py` names the collections as follows.

| `collection` value | Collection | Public source | Location the records expect |
|---|---|---|---|
| `auckland` | Open IFC Model Repository, University of Auckland | https://openifcmodel.cs.auckland.ac.nz/ | `data/corpus/auckland/` |
| `buildingsmart_official` | buildingSMART Certification-datasets | https://github.com/buildingSMART/Certification-datasets | `data/corpus/bs_official_repo/` |
| `buildingsmart_community` | buildingsmart-community Community-Sample-Test-Files | https://github.com/buildingsmart-community/Community-Sample-Test-Files | `data/corpus/bs_community_repo/` |
| `schependomlaan` | Schependomlaan dataset (openBIMstandards archive) | https://github.com/openBIMstandards/Archive-DataSetSchependomlaan | `data/corpus/schependomlaan_repo/` |
| `gni` | GNI BIM Dataset (Wang, Fuchs, Wu, Esser, Wrabel and Borrmann, Technical University of Munich, 2026) | https://doi.org/10.5281/zenodo.19722012 (CC BY 4.0) | `data/corpus/gni/` |

The released benchmark and validation tasks use the `auckland`, `buildingsmart_community` and `gni`
collections. The Schependomlaan collection is registered in the corpus manifest but reserved: the generator
never reads it. `code/corpus/auck_download.py` downloads the Auckland repository, and the GitHub collections
are cloned (`code/corpus/fetch_lfs.py` fetches files stored with Git LFS).

Of the 2,100 benchmark tasks, 1,183 start from a migrated copy (`origin` = `migrated`): an IFC2X3 or IFC4
source model converted to IFC4 or IFC4X3, with IFC2X3 sources converted through IFC4. The conversion uses
IfcOpenShell's schema migrator (`ifcopenshell.util.schema.Migrator`) extended with the IFC4 to IFC4X3 class
renames it lacks. The migrated files the records name were written by the second version of the migrator
(`scripts/corpus/migrator_v2/`), which adds no schema violation beyond those the source file already
carries. The records expect these copies under `runs_local/corpus_v10/migrator_v2/files/` as
`<source stem>__IFC4.ifc` and `<source stem>__IFC4X3.ifc`, and the checksum in each record identifies the
exact file.

## Task definitions

`tasks/benchmark/tasks.v4c.jsonl` defines the 2,100 benchmark tasks: 700 per IFC version (IFC2X3, IFC4,
IFC4X3), over create, update and delete operations and direct, spatial and topological instructions. Each
record carries the instruction (`prompt`), the source model, the reference edit script (`gold_script`), the
checksum of the ground-truth model that script produces (`verification.gold_sha256`) and the generator
version. `subset_108_hosted.v4c.json` lists the 108-task subset (36 tasks per IFC version) on which all four
commercial models were run. `subset_324.v4c.json` lists the 324-task subset that contains it, on which
VeriBIM-9B and the strongest commercial model were also run.
`subset_324_rest216.v4c.json` lists the 216 tasks of the 324-task subset that are not in the 108-task subset.
`library_note.md` is the description of the helper library given to models that were not trained with it.

Ground-truth models are not distributed. The evaluation rebuilds each one from its source model and the
record's reference script, and checks the rebuilt file against the checksum in the record.

## Training task sets

`tasks/train/` holds the tasks the three training stages drew from, in the record format of the benchmark. All of
them start from source models of the training buildings.

| File | Content |
|---|---|
| `tasks_stage_b_v10.jsonl.gz` | the 51,956 generated training tasks (gzip-compressed JSON lines) |
| `tasks_imitation_earlier.jsonl` | 2,419 tasks of earlier generation rounds that have a reference trajectory in the imitation data but are not in the training task file: 890 from an earlier task wave and 1,529 from an earlier imitation set; records unchanged |
| `imitation_task_ids.json` | the 37,865 tasks with a reference trajectory in the imitation data, 35,446 from the training task file and 2,419 from the earlier rounds |
| `imitation_tasks_report.json` | the counts, written by `scripts/training/collect_imitation_tasks.py` |
| `preference_pool_ids.json` | the 6,000 tasks of the training task file on which the stage-1 model was sampled six times to build the stage-2 preference pairs (`stage_b.pool`, seed 20260928) |
| `reinforcement_pool_ids.json`, `reinforcement_pool_tasks.jsonl` | the 64 tasks of stage 3 |
| `reinforcement_pool_report.json` | the counts behind the stage-3 pool |

The imitation stage trained on 75,953 rows: one reference trajectory for each of the 37,865 tasks, and
copies of these trajectories with a paraphrased instruction. A trajectory may word the reference to an element
differently from its record (for example, a GlobalId without quotes), because the synthesis varies the wording; the
target and the reference edit are those of the record. Of the 6,000 sampled tasks, 158 were not
completed in all six samples after the exclusions listed in the report: 61 were completed in some samples
and 97 in none. Stage 3 trained on the 61 partly completed tasks and the 3 never
completed tasks whose six sample scores differ by more than 0.05, because a group of rollouts that all score alike
gives no learning signal. The trajectories, the sampled rollouts and the preference pairs are not distributed; each
stage rebuilds them with the commands in "Training".

## Regenerating tasks

The generator works from a corpus manifest, `data/corpus_manifest.json`. `code/corpus/scan_ifc.py` scans
the downloaded files (checksum, schema, parse result, GlobalIds) and `code/corpus/build_manifest.py`
assembles the manifest. The manifest builder removes duplicates and drops any corpus building that shares a
GlobalId with a BIM-Edit scene file, so it needs a local copy of BIM-Edit (see "Evaluating on BIM-Edit").

The generator then runs in four steps: select the usable source models, generate tasks, write the
ground-truth models, and re-check every task from the task file alone.

```bash
python -m modifc_gen.pool --root . --out <run dir>/pool.json
python -m modifc_gen.scale --root . --out <run dir> --pool <run dir>/pool.json --n-tasks <N> --workers 8
python -m modifc_gen.materialize --root . --tasks <run dir>/tasks.jsonl --split validation --workers 6
python -m modifc_gen.audit --root . --tasks <run dir>/tasks.jsonl --rebuild --sample 500 --workers 6
```

`code/modifc_gen/README.md` documents every option, the design grid and the checks a task must pass. The
released tasks were generated with generator version 0.9.0 (`generator_version`).

## Construction scripts

`scripts/` holds the scripts that built the released task sets around the generator, in the order they ran.
They are run from the repository root, read the corpus under `data/corpus/`, and write their intermediate
files under `runs_local/`, in the locations the task records name.

1. **Migrate.** The first version of the migration is `scripts/corpus/migrate_all.py`, which converts every
   source model of the training pool and every admitted GNI file to IFC4 and IFC4X3 with the migrator of
   `probe_migrate.py` (`migrate_large.py` runs the files over 100 MB, `migrate_file.py` converts one file).
   `validate_schema.py` validates every migrated file and every native source against its schema. The second
   version, `scripts/corpus/migrator_v2/`, produced the migrated files that the released task records name:
   `migrate_v2.py` holds the migration rules, `run_all.py` re-migrates every migrated file of the training and
   benchmark pools one step at a time (`steps.py`), validates each output (`vkeys.py`) and compares it with the
   first-version file product by product, `make_report.py` summarises the run and `tools/unit_tests.py` tests
   each rule on the smallest source that shows its issue.
2. **Build pools.** `scripts/corpus/build_pool_v10.py` writes one training pool per IFC version, with the
   building id of each source and its origin (native or migrated); `build_pool_plus.py` adds the migrated
   copies of six large sources for the top-up rounds; `build_pool_bench_v10.py` writes the benchmark
   pools from the held-out buildings only. `scripts/corpus/migrator_v2/build_pools_v2.py` points the migrated
   entries of every pool at the second-version files.
3. **Generate and merge.** `modifc_gen.scale --pool` generates the tasks of each pool.
   `scripts/corpus/gen/enrich_bench.py` adds the origin fields to the benchmark candidates,
   `gen/merge_v10.py` merges the training runs into one task file and `gen/finalize_v10.py` collects the
   training trajectories and validation tasks of the merge. Two repairs ran on the generated tasks:
   `gen/repair/` removes door and window types that the instruction never states (`repair_filling_type.py`,
   checked by `replay_check.py`), and `gen/resource/` moves the tasks generated on first-version migrated
   files onto the second-version files and runs the generator's checks again (`resource_v2.py`, with
   `rerender.py`, `redraw_check.py`, `native_rebuild_check.py` and `make_report.py`). `gen/walks/` checks
   training trajectories for identifiers, numbers and names that the instruction or an earlier tool output
   did not supply.
4. **Select the benchmark.** `scripts/benchmark/select_bench_v4.py` applies the exclusion rules and runs the
   selection driver `scripts/benchmark/selection/build_e2_v3.py` once per IFC version. The driver selects from
   the candidates on the held-out buildings: 36 tasks per operation-by-category cell, the chain tasks and one
   cell per requirement family, taken by a round robin over buildings and element families. The result is
   700 tasks per IFC version with the 108-task and 324-task subsets. `selection/` also holds the tools of the
   earlier task waves that the driver and the merge rules come from (`concat_topups.py`, `build_wave_all.py`,
   `partition.py`, `drop_defects.py`, `e2_manifest.py`, `build_val_subset_v2.py`, `list_outside_canonical.py`,
   `write_conditions_md.py`).
5. **Materialise.** `scripts/benchmark/materialize_bench_v4.py` rebuilds every ground-truth model from its
   reference script and checks it against the recorded checksum.
6. **Finalise and revise.** `scripts/benchmark/finalize_bench_v4.py` runs the sanity checks and writes the
   manifest and report of the benchmark. Two later revisions produced the released file.
   - The first corrected the reading of "opposite" references and added a clearance rule for created or
     moved doors and windows. `scripts/corpus/opposite_fix/` holds the corrected modules
     (`anchors_fixed.py`, `veribim_geom_fixed.py`, with the modules before the fix in `orig/`), `fixload.py`,
     which loads them in place of the installed ones inside one process, `reresolve.py`, which re-resolves
     every "opposite" reference of the benchmark and the 500-task validation set, `run_fixed.py`, the tests in
     `test_opposite_fix.py`, and the first revision package `install/`, which applies the corrected reading
     alone. `scripts/corpus/clearance_fix/` holds the clearance checker `clearance_check.py`, the screen
     (`select_inscope.py`, `prebuild_index.py`, `run_screen.py`, `summarize.py`, and `train_screen/` for the
     training set) and the second revision package `install_v2/`, which applies both rules:
     `rebench.py` for the benchmark, `reval.py` and `rescore_val.py` for the validation set, `regold.py` for
     tasks whose reference element changed.
   - The second revision replaced eight tasks; `scripts/benchmark/merge_v4c.py` replaces their rows in a
     per-task result file by the rows of the replacements.
7. **Paraphrase.** `scripts/benchmark/paraphrase_v10.py` and `paraphrase_styles_v10.py` rewrite the
   training instructions with the locally served base model; a rewrite that loses a number, a name, an
   identifier or the requested operation is retried, and the original is kept after three failed attempts.
8. **Build validation sets.** `scripts/benchmark/build_val_v3.py` draws the 500-task validation set and its
   100-task subset, stratified by operation, category and tier within each IFC version.
   `scripts/validation/val_hard/` builds the 300-task hard validation set. `prep.py` writes one pool per IFC
   version from the training buildings, without the validation buildings, and lists every instruction already
   drawn. The generator then runs on these pools, and `finalize.py` merges the three runs, drops every task
   that overlaps the benchmark, the validation sets or the stage-2 pool and every instruction that shares an
   eight-word run with BIM-Edit, and keeps 1,000 candidates per IFC version. `materialize.py` rebuilds every candidate's ground-truth model against its checksum,
   `verify_candidates.py` repeats the overlap and schema checks independently, `assert_same_selection.py`
   checks that a resumed run left the other versions unchanged, and `sample20.py` and
   `work/sample8_ifc2x3.py` print candidates for reading by hand. The stage-1 model was then sampled six times on
   each of the 2,996 candidates, and `rank_val_hard.py` ranks them by failed samples, then by mean sampled
   score, and keeps every candidate with a failed sample (82) and the 218 lowest-scoring completed
   ones, 300 tasks (`tasks/val_hard/val_hard_build_report.json`). `val_hard_ranking.jsonl` lists every
   candidate in ranking order with the two numbers the ranking reads; the sampled rollouts are not released.
   Run on these rollouts, the released script writes the four released files of `tasks/val_hard/` byte for byte.

`scripts/benchmark/hosted_table.py` computes the 108-task comparison with the commercial models, and
`audit_fs_access.py` and `audit_strict.py` check model trajectories for file-system or process access beyond
the working copy.

## Running the checker

`modifc_score` scores one edited model against the source model and the ground-truth model. Its defaults
reproduce the evaluator published with BIM-Edit.

```bash
python -m modifc_score.selftest                    # checks of the geometric and comparison primitives
python -m modifc_score.cli --tasks <tasks.jsonl> --scenes <scene root> \
    --edited <directory of edited models> --out scores.csv --workers 8
```

On the released task files, the evaluation below calls the checker for every task, with the settings the
task's own families require (`--scorer-reading family`).

## Running the evaluation

Serve the base model with the adapter attached (see "Adapter weights" for the files):

```bash
VLLM_USE_FLASHINFER_SAMPLER=0 $CONDA_ROOT/envs/l2vllm/bin/vllm serve models/Qwen3.5-9B \
    --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 --max-model-len 65536 \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --chat-template code/stage_a/chat_template_veribim.jinja --language-model-only \
    --enable-lora --max-lora-rank 16 --max-loras 1 --lora-modules grpo_v10b_c10=weights/grpo_v10b_c10
```

Then run the tasks. `--subset` takes a JSON list of task ids; the subset files in `tasks/benchmark/` have
this form, and the list of all 2,100 ids is written by the first command.

```bash
python -c "import json; print(json.dumps([json.loads(l)['task_id'] for l in open('tasks/benchmark/tasks.v4c.jsonl')]))" > all_ids.json
python -m stage_a.run_gate --adapters grpo_v10b_c10 --base-url http://127.0.0.1:8000/v1 \
    --tasks-file tasks/benchmark/tasks.v4c.jsonl --subset all_ids.json \
    --run-dir <output dir> --gold-cache <cache dir> --scorer-reading family \
    --concurrency 16 --score-workers 4
```

The run directory receives `per_task_<model>.jsonl` in the format of the files in `results/benchmark/`. The
defaults match the paper's protocol: at most 22 tool rounds, 8,192 output tokens per turn, a 420 s limit
per tool call, tool output capped at 16,000 characters, temperature 0. The helper library is bound as
`geom` in the sandbox by default. `VERIBIM_NO_GEOM=1` removes it (the "alone" runs), and
`VERIBIM_USER_NOTE_FILE=tasks/benchmark/library_note.md` appends the library description to the user turn
(the runs of models not trained with the library). `VERIBIM_SANDBOX_GUARD=1` limits the file access of the
executed code to its working directory and refuses new processes and sockets, and `VERIBIM_SANDBOX_LANDLOCK=1`
adds a kernel file-system ruleset under the same guard.

The commercial models are run through the same command with `--base-url` set to the provider's endpoint,
`--adapters` set to the provider's model id and the key in the environment variable `VERIBIM_API_KEY`.
`code/harness/modifc_harness/client.py` documents the request style each provider needs
(`VERIBIM_REQUEST_STYLE`). `code/tables/hosted_cost.py` holds the list prices used for the cost comparison.

## Evaluating on BIM-Edit

BIM-Edit is not redistributed. Obtain the benchmark from its authors (Nithyanantham, B. K., Kujat, C.,
Sesterhenn, T., Telgmann, S., Nedungadi, A., Plönnigs, J., Bartelt, C., Lüdtke, S. (2026). BIM-Edit: Benchmarking Large Language Models for IFC-Based Building Information Modeling. arXiv:2606.20146, https://arxiv.org/abs/2606.20146) and place it under `data/bimedit/`, with the task file at
`data/bimedit/BIM-Edit-Tasks/tasks.jsonl` and the scenes at `data/bimedit/BIM-Edit/` (folders `simple/` and
`complex/`). No script from the paper's own BIM-Edit runs is shipped; the procedure below uses only the
released code. `analysis/revision/bimedit_arms/analyze_bimedit_arms.py` is an analysis script, not a run script: it
compares the BIM-Edit arms from per-task records that are not redistributed, and `bimedit_arms.json` holds its output.

1. Write a copy of the task file whose IFC paths point at the local scenes, with the harness's own path
   mapping, and a list of the 324 task ids:

   ```bash
   python - <<'EOF'
   import json
   from pathlib import Path
   from modifc_harness.tasks import resolve_scene_path
   ids = []
   with open("data/bimedit/BIM-Edit-Tasks/tasks.jsonl") as src, open("bimedit_tasks.jsonl", "w") as out:
       for line in src:
           r = json.loads(line)
           for key in ("input_ifc", "ground_truth_ifc"):
               r[key] = str(resolve_scene_path(r[key], Path("data/bimedit/BIM-Edit")))
           out.write(json.dumps(r) + "\n")
           ids.append(r["task_id"])
   json.dump(ids, open("bimedit_ids.json", "w"))
   EOF
   ```

2. Run the model on the tasks with the published scoring rules. `--scorer-reading published`, the default
   of `stage_a.run_gate`, keeps the settings of the published BIM-Edit runs for the scores written during
   the run. The protocol defaults (22 tool rounds, 8,192 output tokens per turn, 420 s per tool call,
   temperature 0) follow the published runs; `code/harness/README.md` lists where and why they depart from
   them.

   ```bash
   python -m stage_a.run_gate --adapters grpo_v10b_c10 --base-url http://127.0.0.1:8000/v1 \
       --tasks-file bimedit_tasks.jsonl --subset bimedit_ids.json --scorer-reading published \
       --run-dir <output dir> --gold-cache <cache dir>
   ```

3. Score the edited models with the checker under its default settings, which reproduce the evaluator
   published with BIM-Edit (per-pair geometry, deletions compared by the matcher, topology as the mean of
   the seven edit rules). These are the BIM-Edit scores the paper reports:

   ```bash
   python -m modifc_score.cli --tasks data/bimedit/BIM-Edit-Tasks/tasks.jsonl --scenes data/bimedit/BIM-Edit \
       --edited <output dir>/grpo_v10b_c10/edited --out scores_bench_grpo_v10b_c10.csv --workers 6
   ```

4. Compare with `results/bimedit/scores_bench_<model>.csv`, the per-task scores of the trained models and
   of the untrained base model from the same two steps; `summary_bench_<model>.json` holds their means. The
   subfolders `sonnet_alone/` and `sonnet_lib/` hold the scores and means of Claude Sonnet 5.5, alone and with the
   library and its short note, in the same test setup.

## Training

All three stages train one LoRA adapter (rank 16, alpha 32) on Qwen3.5-9B. The task sets each stage drew from are
in `tasks/train/` (see "Training task sets"); the training data built from them (trajectories, sampled rollouts,
preference pairs) are not distributed, and each stage rebuilds its own with the commands below. The values given are
those of the final runs.

**Stage 1, imitation** (`l2` for synthesis, `l2train` for training). `stage_a.cli synthesize` writes a
reference trajectory for every generated training task and keeps it only when the file it leaves scores at
least 0.98 on every axis. `stage_a.cli assemble` builds the chat-format training set with the loss on the
assistant tokens, and `stage_a.cli train` trains the adapter: learning rate 1e-4 (cosine), one epoch,
effective batch 64, sequences up to 8,192 tokens. The final stage-1 run continued from the adapter of an
earlier stage-1 run on the first task corpus. `code/stage_a/README.md` describes the filters.

**Stage 2, preference optimisation.** `stage_b.cli sample` runs the stage-1 model six times per task on a
pool of training tasks and scores every rollout. `stage_b.pairs.trajectory_pairs` pairs a completed rollout
with a failed one of the same task, `python -m stage_b.run_branch` adds turn-level pairs from repaired
branches of failed rollouts, and `stage_b.assemble.assemble` writes the pair dataset.
`python -m stage_b.train_dpo` then trains with beta 0.1, learning rate 5e-6, effective batch 32 and four
epochs, saving a snapshot every 3 steps. The
snapshot with the highest completion on the hard validation set is kept, with ties broken by the mean score
and then by the later step (`results/val_hard/preference_stage/`).

**Stage 3, reinforcement learning.** `code/stage_c/scripts_serve.sh` starts the sampling server, which
shares the GPU with the trainer, and `python -m stage_c.train_grpo` trains from the kept stage-2 snapshot:
8 rollouts per task, effective batch 64, beta 0.04, learning rate 3e-6, two runs of 60 steps with a snapshot
every 10. The second run continues from the first run's step-50 snapshot with a shorter sequence cap (10,240
instead of 12,288 tokens). The reward is the checker's score rescaled so that leaving the model unchanged earns
zero (`code/stage_c/README.md`). Over the twelve snapshots, the one with the highest completion on the hard
validation set is the final model, with ties broken by the mean score and then by the later step
(`results/val_hard/reinforcement_stage/`, `CURVE_BOTH_LEGS.txt` lists every snapshot with its step counted
along the path of the model).

`python -m stage_a.cli train --help`, `python -m stage_b.train_dpo --help` and
`python -m stage_c.train_grpo --help` list every option.

## Reproducing the paper's tables

`code/tables/make_results_exhibits.py` rebuilds the tables and figures of the main runs, the results macro file
and the figure data from the released result files.

```bash
python code/tables/make_results_exhibits.py            # writes exhibits/tables and exhibits/figures
```

The script reads every input from the repository layout above; `VERIBIM_ROOT` overrides the repository root
and `VERIBIM_EXHIBITS_DIR` the output directory. `results/benchmark/FINAL_ARTIFACT` names the final model.
`exhibits/tables/REPORT.txt` lists every input read and every value left pending. With the released files
the script reproduces its tables and figures exactly. Three groups of macro values need inputs
outside the released tree: the data-separation counts of Appendix E need the training task file, released
gzip-compressed, so decompress `tasks/train/tasks_stage_b_v10.jsonl.gz` in place (or point `VERIBIM_TRAIN_TASKS` at
a decompressed copy); the split of wall-clock time between the model and the tools needs the run transcripts; and
the number of tasks in flight during the 108-task run needs its run log. The last two are not distributed. The figures use the Liberation Serif fonts in
`/usr/share/fonts/truetype/liberation`. This copy of the script differs from the one used for the paper only
in its input and output paths and in treating the manuscript's macro file as optional.

The names of the output files do not follow the paper's numbering. The table below gives the source of every
table and figure of the paper that reports a result of this repository. Files without a folder are written by the
script into `exhibits/tables/` or `exhibits/figures/`.

| Paper | Content | Source |
|---|---|---|
| Table 3 | 108-task subset | `tab3_main.tex`; the documented settings from `results/benchmark/hosted108_informed_all/` and `analysis/revision/documented/informed4.json`; the untrained base model in the documented setting from `results/benchmark/local108_informed_all/` and `analysis/revision/base_documented/base_informed.json`; completion on fully specified and under-specified tasks from `analysis/revision/stats/clarification.json`; intervals over buildings from `analysis/revision/stats/cluster_boot.json` |
| Table 4 | how each run on the 108-task subset ended | `analysis/revision/stats/failure_ends.json` |
| Table 5 | 324-task subset | `tab3b_324.tex`; the documented setting from `results/benchmark/hosted108_informed_all/` and `hosted324rest_informed_all/`, compared in `analysis/revision/equivalence/equiv_216.json`; the two analysis files of Table 3 |
| Table 6 | training chain on the 2,100-task benchmark | `tab4_ablation.tex` |
| Table 7 | chain trained on ten buildings | `results/val_hard/ten_building_chain/` and the `*_small*` files in `results/benchmark/full_all/` |
| Table 8 | outcome of every benchmark task | `tab5_failures.tex` |
| Table 9 | BIM-Edit | `results/bimedit/scores_bench_grpo_v10b_c10.csv` for VeriBIM-9B, `scores_bench_Qwen3.5-9B.csv` for the untrained base model and `sonnet_alone/` and `sonnet_lib/` for Claude Sonnet 5.5, compared in `analysis/revision/bimedit_arms/bimedit_arms.json`; `results/benchmark/local324_lib_all/per_task_sft_extA.jsonl` for the continued model on the 324-task subset |
| Table 10 | cost of an edit | `tab6_cost.tex` |
| Fig. 7 | main result | `fig08_main/fig08_main_B.pdf` |
| Fig. 8 | hard-validation curves of the last two stages | `fig10_curve/fig10_curve.pdf` |
| Fig. 9 | time and price per task | `fig_cost/fig_cost.pdf` |
| Table A.3 | mutation study | `analysis/revision/checker/mutation_summary.json` |
| Table B.1 | composition of the benchmark | `analysis/revision/stats/composition.json` |
| Table F.1 | completion per held-out building | `analysis/revision/stats/per_building.json` |
| Table F.2 | completion at four verdict thresholds | `analysis/revision/stats/threshold.json`; the untrained base model in the documented setting from `results/benchmark/local108_informed_all/` |
| Table F.3 | changes outside the ground-truth edit | `analysis/revision/checker/offtarget_summary.json` |

## Adapter weights

The adapter weights are attached to the GitHub release of this repository as `grpo_v10b_c10.tar.gz` (164 MB),
because the weight file is larger than the 100 MB that GitHub accepts for a file in a repository.
`weights/grpo_v10b_c10.tar.gz.sha256` holds its SHA-256 checksum. Download the archive into `weights/`, check it
and unpack it there:

```bash
cd weights
sha256sum -c grpo_v10b_c10.tar.gz.sha256
tar -xzf grpo_v10b_c10.tar.gz      # writes weights/grpo_v10b_c10/
```

VeriBIM-9B is the adapter named `grpo_v10b_c10` in the result files and the release asset.
The adapter is a LoRA adapter for Qwen3.5-9B [1]. The directory holds `adapter_config.json`,
`adapter_model.safetensors`, the tokenizer files (`tokenizer.json`, `tokenizer_config.json`,
`processor_config.json`) and two chat templates. `chat_template.jinja` is the template used in training and
evaluation, identical to `code/stage_a/chat_template_veribim.jinja`. `chat_template.stock.jinja` differs from
it only in the line that opens the reasoning block. `adapter_config.json` names the base model as
`Qwen3.5-9B` (`base_model_name_or_path`); point it at a local copy of the base model or at
`Qwen/Qwen3.5-9B` when loading the adapter outside vLLM.

## Citation

```bibtex
@unpublished{zhang2026veribim,
  title  = {VeriBIM: a ground-truth-first framework for generating, training and testing language-model edits of IFC building models},
  author = {Zhang, Ziheng and Zhang, Wei},
  note   = {Manuscript under review. Singapore Institute of Technology},
  year   = {2026}
}
```

## References

[1] Qwen Team. Qwen3.5: Towards Native Multimodal Agents. 2026. https://qwen.ai/blog?id=qwen3.5

## License

The code is released under the Apache License 2.0 (`LICENSE`). The adapter weights are a derivative of
Qwen3.5-9B and follow that model's license, the Apache License 2.0. The source building models and BIM-Edit
remain under the terms of their own publishers.
