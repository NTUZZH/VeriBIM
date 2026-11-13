# VeriBIM

This repository holds the code, task definitions, per-task results and adapter weights of the paper
"VeriBIM: Ground-truth-first training and evaluation framework for language models in IFC model editing"
by Ziheng Zhang, Yijing Chen and Wei Zhang (manuscript under review, 2026). The framework turns real IFC building
models into editing tasks whose instruction, reference edit script and ground-truth model agree by construction, scores
an edited model against the ground truth, and uses these scores to train and evaluate a local language model,
Qwen3.5-9B by the Qwen Team [1], that edits IFC models from natural-language requests. The trained model is called
VeriBIM-9B in the paper.

The repository contains:

- the task generator, the deterministic checker that scores an edited model on geometry, semantics and topology, the
  helper library of geometry and IFC-schema functions that the model calls while it edits, and the evaluation harness;
- the candidate-element index, which appends a short list of candidate elements of the model to a request;
- the training code of the three stages (imitation, preference optimization, reinforcement learning) and the rule that
  names the reported model among the three stage models;
- the benchmark, reworded, validation and training task definitions;
- the per-task results behind the paper's numbers and the scripts that compute these numbers from them;
- the adapter weights of VeriBIM-9B (a release asset, see "Adapter weights").

VeriBIM-9B reaches a completion rate of 0.948 on the 2,100 benchmark tasks, of 0.942 on the 172 reworded
benchmark tasks and of 0.650 on the 500 requests of the second set written by practitioners. A task
counts as completed when the geometry, semantics and topology scores of the edited model all reach 0.9
(`done` in `analysis/make_macros.py`).

The practitioners' requests form two sets with 700 requests in total. The first set holds 200 requests
written by five practitioners, on which VeriBIM-9B reaches a completion rate of 0.685. The
second set holds 500 requests written afterwards by ten other practitioners, when the
model, the candidate-element index and the prompts were already fixed, and every arm ran each of these requests once.

## Layout

```
code/
  modifc_gen/        task generator
  modifc_score/      checker (geometry, semantics and topology scores)
  harness/           evaluation harness; modifc_harness/veribim_geom.py is the helper library
  corpus/            scripts that download, scan and register the source building models
  candidate_index/   candidate-element index (index, matching, appending the list to a task file, recall)
  stage_a/           stage 1, imitation (supervised fine-tuning), and the evaluation entry point run_gate
  stage_b/           stage 2, preference optimization (DPO) on pairs sampled from the stage-1 model
  stage_c/           stage 3, reinforcement learning (GRPO) with the checker as the reward
scripts/
  corpus/            schema migration, source-model pools, merging and repairs of the generated training tasks
  benchmark/         benchmark selection, ground-truth materialization, paraphrases, validation sets, audits
  validation/        the builder and the ranking step of the hard validation set
  training/          the script that collects the task records behind the imitation data
tasks/
  benchmark/         the benchmark tasks, with and without the candidate list, the two subsets, the library notes
  reworded/          the reworded benchmark tasks, with and without the candidate list
  validation/        the validation sets used during training
  val_hard/          the hard validation set and its candidates
  train/             the training task sets of the three stages
results/             per-task results (see "Rerunning the analysis")
analysis/            the scripts that compute the paper's numbers from results/, and run_all.sh
weights/             SHA-256 checksum of the adapter archive
```

The generator, the checker, the harness and the stage-1 and stage-3 packages each have a README with the details of
their design.

## Requirements

The runs used three conda environments on one workstation with one GPU.

| Environment | Used for | Main packages |
|---|---|---|
| `l2` | generator, checker, harness, evaluation, analysis | Python 3.14, IfcOpenShell 0.8.5, numpy, scipy, pandas |
| `l2train` | training | Python 3.13, PyTorch 2.11 (CUDA 13.0), transformers 5.5.0, TRL 0.24.0, PEFT 0.20.0, Unsloth 2026.8.19 |
| `l2vllm` | serving the base model with an adapter | vLLM 0.27.1 |

The scripts find the interpreters at `$CONDA_ROOT/envs/<name>/bin/python` (default `~/miniconda3`) and resolve
relative paths against the repository root, which `VERIBIM_ROOT` overrides. The base model is read from
`models/Qwen3.5-9B` unless `VERIBIM_BASE_MODEL` names another directory. Run every command below from the repository
root with

```bash
export PYTHONPATH=code:code/harness
```

## Source building models

The source building models are not redistributed. Each is available from its public source. Every task record names
its source model by a path relative to the repository root and by its SHA-256 checksum, so each downloaded file can be
checked against the record. The corpus registry `code/corpus/build_manifest.py` names the collections.

| `collection` value | Collection | Public source | Location the records expect |
|---|---|---|---|
| `auckland` | Open IFC Model Repository, University of Auckland | https://openifcmodel.cs.auckland.ac.nz/ | `data/corpus/auckland/` |
| `buildingsmart_official` | buildingSMART Certification-datasets | https://github.com/buildingSMART/Certification-datasets | `data/corpus/bs_official_repo/` |
| `buildingsmart_community` | buildingsmart-community Community-Sample-Test-Files | https://github.com/buildingsmart-community/Community-Sample-Test-Files | `data/corpus/bs_community_repo/` |
| `schependomlaan` | Schependomlaan dataset (openBIMstandards archive) | https://github.com/openBIMstandards/Archive-DataSetSchependomlaan | `data/corpus/schependomlaan_repo/` |
| `gni` | GNI BIM Dataset (Wang, Fuchs, Wu, Esser, Wrabel and Borrmann, Technical University of Munich, 2026) | https://doi.org/10.5281/zenodo.19722012 (CC BY 4.0) | `data/corpus/gni/` |

`code/corpus/auck_download.py` downloads the Auckland repository, and the GitHub collections are cloned
(`code/corpus/fetch_lfs.py` fetches files stored with Git LFS). Benchmark tasks marked `origin` = `migrated` start from
a copy of an IFC2X3 or IFC4 source model converted to IFC4 or IFC4X3 by the second version of the migrator
(`scripts/corpus/migrator_v2/`). The records expect these copies under `runs_local/corpus_v10/migrator_v2/files/` as
`<source stem>__IFC4.ifc` and `<source stem>__IFC4X3.ifc`, and the checksum in each record identifies the exact file.

## Task definitions

Every task file is in JSON lines, one task per line. Each record carries the instruction (`prompt`), the source model,
the reference edit script (`gold_script`), the checksum of the ground-truth model that script produces
(`verification.gold_sha256`) and the generator version. Ground-truth models are not distributed: the evaluation
rebuilds each one from its source model and the record's reference script and checks the rebuilt file against the
checksum. A file whose name ends in `_with_list` holds the same tasks with the candidate list appended to the
instruction, as the trained model saw them.

- `tasks/benchmark/tasks.v4d.jsonl`: the 2,100 benchmark tasks on held-out buildings. `subset_108.json` and
  `subset_324.json` list the 108-task and 324-task subsets on which the commercial
  models were run, and `subset_324_other216.json` the tasks of the larger subset outside the smaller one.
  `library_note.md` is the short description of the helper library given to models that were not trained with it,
  `library_documented.md` the full documentation of the library, and `library_note_ask.md` the short description with
  the instruction to ask for a missing value.
- `tasks/reworded/`: the 172 reworded benchmark tasks, the subset they were drawn from, the mapping from each
  original task to its reworded form and the checks every rewording passed.
- `tasks/validation/` and `tasks/val_hard/`: the validation sets used to select training snapshots, and the
  300-task hard validation set with the candidates it was ranked from.
- `tasks/train/`: the training task sets.

| File | Content |
|---|---|
| `tasks_generated.jsonl.gz` | the 51,956 generated training tasks |
| `tasks_imitation_earlier.jsonl` | 2,419 tasks of earlier generation rounds that have a reference trajectory in the imitation data but are not in the generated task file |
| `imitation_task_ids.json`, `imitation_tasks_report.json` | the tasks with a reference trajectory in the imitation data, and the counts |
| `tasks_imitation_first_pass.jsonl.gz` | the task definitions of the first imitation pass, a separate task set of the same generator: the 18,709 tasks behind its 18,862 trajectories |
| `tasks_imitation_first_pass_report.json` | rows, tasks and buildings of the first pass, and how many of its task ids also occur in `tasks_generated.jsonl.gz` with the same instruction and edit parameters |
| `preference_pool_ids.json`, `preference_pool_tasks_with_list.jsonl.gz` | the 6,000 tasks on which the stage-1 model was sampled to build the preference pairs; 750 of them carry an instruction reworded by a language model as in the third imitation pass (`reworded`), with the generator's wording kept in `wording_before_rewording` |
| `reinforcement_pool_ids.json`, `reinforcement_pool_tasks_with_list.jsonl`, `reinforcement_pool_report.json` | the tasks of stage 3 and the counts behind them; a reworded instruction carries the same two fields as in the preference pool |
| `third_pass_rewordings.jsonl.gz` | the 5,563 instructions that a language model reworded for the third imitation pass: the task id, the style of the rewording and the reworded instruction |

The first imitation pass trained on a separate task set of the same generator, and
`tasks_imitation_first_pass.jsonl.gz` holds the definitions of its tasks. Its task ids follow the same naming scheme as
those of `tasks_generated.jsonl.gz`, so some ids occur in both files for different tasks; the report next to the file
counts them. The third pass trained on the tasks listed in `imitation_task_ids.json`, with the instruction of
5,563 of them reworded; `third_pass_rewordings.jsonl.gz` holds these rewordings.

## What is not included, and why

- **Source building models and every model derived from them** (ground truths, edited models, archives of edited
  models). They remain under the terms of their publishers; the task records name each source by path and checksum.
- **The practitioners' requests and their judgments.** The requests were written by practitioners for this study and
  are not released. For every run on these requests, `results/practitioner/` (first set) and
  `results/practitioner/second_set/` (second set) keep only the request id, the scores, the stop reason and the counts
  (tool rounds, calls, tokens, seconds); every field that holds or echoes the text of a request or a model's reply is
  removed, and every string left in these rows is a short token. `request_properties_first_set.csv` and
  `request_properties_second_set.csv` in `results/practitioner/` give for every request its base task, a writer code,
  the operation, the building, the schema version, the writer's years of experience, the number of required elements,
  how the request names each of them and whether the candidate list holds them; they hold no text. The paper reports
  these results only in aggregate.
- **Transcripts, trajectories, sampled rollouts and preference pairs.** Each training stage rebuilds its own data from
  the released task sets with the commands in "Training".
- **Results of any other trained model.** The release holds the three stage models of the reported training path
  (`sft_v14`, `dpo_v14_c6` and `grpo_v14_c20`, the last of which is VeriBIM-9B), the two further seed repeats of the
  preference stage (`dpo_v14_s2_c6`, `dpo_v14_s3_c6`), the validation reads of the other snapshots of the same
  training path (`results/validation/snapshots/`) and the per-task results of Qwen3.5-4B after the imitation passes
  (`qwen4b_after_imitation/`). The adapter of that 4B model is not released.
- **The public benchmark that the paper compares with**, which its authors distribute. The manifest builder and the
  hard-validation builder read its scene files and instructions to keep them out of the generated tasks, so a local
  copy is needed to rerun those two steps.
- **The comparison of the checker with the published evaluator of that public benchmark**, reported in the
  supplement. It rests on that benchmark's published runs, which its authors distribute, so it is not part of this
  release.

## Generating tasks

The generator works from a corpus manifest, `data/corpus_manifest.json`. `code/corpus/scan_ifc.py` scans the
downloaded files (checksum, schema, parse result, GlobalIds) and `code/corpus/build_manifest.py` assembles the
manifest. The generator then runs in four steps: select the usable source models, generate tasks, write the
ground-truth models, and re-check every task from the task file alone.

```bash
python -m modifc_gen.pool --root . --out <run dir>/pool.json
python -m modifc_gen.scale --root . --out <run dir> --pool <run dir>/pool.json --n-tasks <N> --workers <W>
python -m modifc_gen.materialize --root . --tasks <run dir>/tasks.jsonl --split validation --workers <W>
python -m modifc_gen.audit --root . --tasks <run dir>/tasks.jsonl --rebuild --sample <S> --workers <W>
```

`code/modifc_gen/README.md` documents every option, the design grid and the checks a task must pass. `scripts/` holds
the scripts that built the released task sets around the generator: the schema migration and the source-model pools
(`scripts/corpus/`), the benchmark selection, materialization and paraphrases (`scripts/benchmark/`), the hard
validation set (`scripts/validation/val_hard/`) and the collection of the imitation task records
(`scripts/training/`). They are run from the repository root and write their intermediate files under `runs_local/`,
in the locations the task records name.

## Scoring an edit

`modifc_score` scores one edited model against the source model and the ground-truth model.

```bash
python -m modifc_score.selftest                    # checks of the geometric and comparison primitives
python -m modifc_score.cli --tasks <tasks.jsonl> --scenes <scene root> \
    --edited <directory of edited models> --out scores.csv --workers <W>
```

The evaluation below calls the checker for every task, with the settings the task's own families require
(`--scorer-reading family`).

## Building the candidate list

`code/candidate_index/` builds a deterministic index of the elements of an IFC model (`index_ifc.py`), ranks the
elements against the words of a request (`match.py`) and appends the best-ranked candidates to the instruction of every
record of a task file (`apply_hint.py`). Every other field of a record is left unchanged.

```bash
cd code/candidate_index
python apply_hint.py <tasks.jsonl> <tasks_with_list.jsonl>     # options --k and --max-chars, see the docstring
python eval_recall.py --help                                    # recall of the required elements in the list
python test_target_index.py                                     # tests
```

The task files ending in `_with_list` in `tasks/` were written by this script; `results/candidate_index/` holds the
recall of the list on the benchmark and the reworded tasks.

## Running the evaluation

Serve the base model with the adapter attached (see "Adapter weights" for the files):

```bash
VLLM_USE_FLASHINFER_SAMPLER=0 $CONDA_ROOT/envs/l2vllm/bin/vllm serve models/Qwen3.5-9B \
    --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 --max-model-len 65536 \
    --enable-auto-tool-choice --tool-call-parser qwen3_xml \
    --chat-template code/stage_a/chat_template_veribim.jinja --language-model-only \
    --enable-lora --max-lora-rank 16 --max-loras 1 --lora-modules grpo_v14_c20=weights/grpo_v14_c20
```

Then run the tasks. `--subset` takes a JSON list of task ids; the subset files in `tasks/benchmark/` have this form,
and the list of all benchmark ids is written by the first command.

```bash
python -c "import json; print(json.dumps([json.loads(l)['task_id'] for l in open('tasks/benchmark/tasks.v4d_with_list.jsonl')]))" > all_ids.json
python -m stage_a.run_gate --adapters grpo_v14_c20 --base-url http://127.0.0.1:8000/v1 \
    --tasks-file tasks/benchmark/tasks.v4d_with_list.jsonl --subset all_ids.json \
    --run-dir <output dir> --gold-cache <cache dir> --scorer-reading family
```

The run directory receives `per_task_<model>.jsonl` in the format of the files in `results/`. `python -m
stage_a.run_gate --help` lists the protocol settings and their defaults. The helper library is bound as `geom` in the
sandbox by default; `VERIBIM_NO_GEOM=1` removes it, `VERIBIM_USER_NOTE_FILE=tasks/benchmark/library_note.md` appends
the library description to the user turn, and `VERIBIM_SANDBOX_GUARD=1` limits the file access of the executed code to
its working directory. The commercial models are run through the same command with `--base-url` set to the provider's
endpoint, `--adapters` set to the provider's model id and the key in the environment variable `VERIBIM_API_KEY`;
`code/harness/modifc_harness/client.py` documents the request style each provider needs (`VERIBIM_REQUEST_STYLE`).

## Training

All three stages train one LoRA adapter on Qwen3.5-9B. The task sets each stage drew from are in `tasks/train/`; the
training data built from them are not distributed, and each stage rebuilds its own.

- **Stage 1, imitation.** `stage_a.cli synthesize` writes a reference trajectory for every training task and keeps it
  only when the file it leaves passes the checker; `stage_a.cli assemble` builds the chat-format training set and
  `stage_a.cli train` trains the adapter. The reported imitation model was trained in three passes; the task
  sets of the first pass and of the later passes are both in `tasks/train/`.
- **Stage 2, preference optimization.** `stage_b.cli sample` runs the stage-1 model several times per task on the
  preference pool and scores every rollout, `stage_b.pairs` and `stage_b.run_branch` build the pairs, and
  `stage_b.train_dpo` trains the adapter.
- **Stage 3, reinforcement learning.** `code/stage_c/scripts_serve.sh` starts the sampling server and
  `stage_c.train_grpo` trains from the kept stage-2 snapshot on the reinforcement pool. The reward is the checker's
  score rescaled so that leaving the model unchanged earns zero (`code/stage_c/README.md`).

The imitation passes were also repeated on Qwen3.5-4B; the per-task results of that model before and after these passes
are in the `qwen4b_*` folders under `results/`.

`python -m stage_a.cli train --help`, `python -m stage_b.train_dpo --help` and `python -m stage_c.train_grpo --help`
list every option. `analysis/validation/name_reported_model.py` applies the rule that names the reported model among
the three stage models: the highest completion on the hard validation set, ties broken by the mean score and then by
the earlier stage. Run on the released reads in `results/validation/val_hard/`, it writes
`results/validation/val_hard/reported_model_rule.txt` byte for byte.

## Adapter weights

The adapter is attached to the GitHub release of this repository as `grpo_v14_c20.tar.gz` (164 MB),
because its weight file is larger than GitHub accepts for a file in a repository. `weights/grpo_v14_c20.tar.gz.sha256`
holds the archive's SHA-256 checksum. Download the archive into `weights/`, check it and unpack it there:

```bash
cd weights
sha256sum -c grpo_v14_c20.tar.gz.sha256
tar -xzf grpo_v14_c20.tar.gz      # writes weights/grpo_v14_c20/
```

VeriBIM-9B is the adapter named `grpo_v14_c20` in the result files and the release asset. It is a LoRA adapter for
Qwen3.5-9B [1]. The directory holds `adapter_config.json`, `adapter_model.safetensors`, the tokenizer files
(`tokenizer.json`, `tokenizer_config.json`, `processor_config.json`) and two chat templates. `chat_template.jinja` is
the template used in training and evaluation, identical to `code/stage_a/chat_template_veribim.jinja`.
`adapter_config.json` names the base model as `Qwen3.5-9B` (`base_model_name_or_path`); point it at a local copy of the
base model or at `Qwen/Qwen3.5-9B` when loading the adapter outside vLLM, for example with PEFT:

```python
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
base = AutoModelForCausalLM.from_pretrained("Qwen/Qwen3.5-9B", torch_dtype="auto")
model = PeftModel.from_pretrained(base, "weights/grpo_v14_c20")
tokenizer = AutoTokenizer.from_pretrained("weights/grpo_v14_c20")
```

## Rerunning the analysis

`analysis/run_all.sh` runs the generator scripts on the released result files and writes every output to
`analysis_out/`. Each generator writes a macro file of the paper; the export of this repository runs the same steps and
checks that every macro of the paper's installed file is reproduced with the same value.

```bash
bash analysis/run_all.sh          # PYTHON=<interpreter of the l2 environment> to choose the interpreter
```

| Generator | Paper numbers | Inputs in `results/` |
|---|---|---|
| `make_macros.py` with `config.json` | every number of the proposed model and of the comparison arms on the benchmark, the subsets, the reworded tasks and the first set of practitioners' requests | all folders below except `generation_funnel/` |
| `flip_rate.py`, `make_macros_flip.py` | repeatability of two runs under identical settings | `benchmark/stage_models/`, `subset108/veribim9b/`, `subset324/veribim9b/` |
| `make_macros_seeds.py` | seed repeats of the preference stage | `subset324/preference_stage_seeds/` |
| `make_macros_nolist_subsets.py`, `make_macros_nolist_rows.py` | the proposed model without the candidate list on the two subsets | `subset108/`, `subset324/`, `relation_gate/` |
| `compare_runs.py`, `make_macros_tplcheck.py` | the chat template of training against the reported runs | `template_check/` |
| `make_macros_orphans.py` | completion without the deletion tasks the orphan rule flags | `benchmark/orphan_rule/` |
| `make_macros_genfunnel.py` | cost and yield of task generation | `generation_funnel/` |
| `make_macros_cost.py` | time and electricity per edit | `subset108/veribim9b_one_task_at_a_time/`, `subset108/timing/`, `analysis/cost_constants.tex` |
| `make_macros_gateprac.py` | relation-gated completion on the first set of practitioners' requests | `practitioner/`, `relation_gate/` |
| `prac_failures.py` | outcomes of the uncompleted requests of the first set | `practitioner/` |
| `make_macros_set2.py` | the second set of practitioners' requests, both sets together, and the two tables by request set and by practitioner | `practitioner/` and `practitioner/second_set/`, with the two property tables |
| `make_macros_basemodels.py` with `config_basemodels_q4b.json` | the imitation passes repeated on Qwen3.5-4B | the `qwen4b_*` folders and the rows of VeriBIM-9B they are compared with |
| `validation/name_reported_model.py` | the reported model | `validation/val_hard/` |

The result folders are named after the run they hold: `stage_models/` holds the three stage models, `veribim9b*/` the
reported model in one setting, `commercial_*/` and `base_*/` the comparison models in the setting the
folder names (alone, with the library note, with the documented library, and so on), and `template_parser/` and
`parser_after_*` the template parser alone and after a rewriting model. `practitioner/` holds the runs on the first set
of practitioners' requests and `practitioner/second_set/` the runs on the second set. The `qwen4b_untrained_*` and
`qwen4b_after_imitation/` folders hold Qwen3.5-4B before and after the imitation passes. Every per-task row keeps the fields of the
evaluation harness, except the path of the edited model, which is not released; the rows on the practitioners' requests
keep only the fields listed in "What is not included, and why".

Three folders hold reads that no generator above uses:

- `validation/snapshots/`: the validation reads of the other preference snapshots on the 100-task and 500-task sets
  and of the other reinforcement snapshots on the hard set, from which the kept snapshots were chosen (the reads of
  the kept snapshots are in `validation/val_100/`, `validation/val_500/` and `validation/val_hard/`);
- `subset108/commercial_documented_repeats/`: two repeats (`repeat_2/`, `repeat_3/`) of the run of one commercial model
  with the documented library, whose first run is in `subset108/commercial_documented/`;
- `benchmark/base_library_note_partial/`: the untrained base model with the library note on the
  982 benchmark tasks it read.

The scripts in `analysis/inputs_not_released/` computed the remaining numbers of the paper from inputs that are not
released: the run transcripts (`make_macros_supp.py`, `supp_gee.py`, `supp_classify_training.py`, `note_coverage.py`),
the edited models (`validity/`), and the practitioners' request files (`make_macros_pracsplit.py`,
`make_macros_north.py`, and `request_properties.py`, which writes the two property tables). They are released for their method and do not run on this repository.

## Citation

```bibtex
@unpublished{zhang2026veribim,
  title  = {VeriBIM: Ground-truth-first training and evaluation framework for language models in IFC model editing},
  author = {Zhang, Ziheng and Chen, Yijing and Zhang, Wei},
  note   = {Manuscript under review},
  year   = {2026}
}
```

## References

[1] Qwen Team. Qwen3.5: Towards Native Multimodal Agents. 2026. https://qwen.ai/blog?id=qwen3.5

## License

The code is released under the Apache License 2.0 (`LICENSE`). The adapter weights are a derivative of Qwen3.5-9B and
follow that model's license, the Apache License 2.0. The source building models and the public benchmark the paper
compares with remain under the terms of their own publishers.
