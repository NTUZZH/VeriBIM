# ModIFC evaluation harness

An agent harness that reproduces the BIM-Edit interaction protocol for locally
served models. A model receives one natural-language editing instruction and one
tool, executes Python against a sandboxed copy of the IFC model, and the edited
file it leaves on disk is the only artifact the scorer sees.

The output directory has the same shape as the published BIM-Edit run folders,
so one loader reads both.

## Layout

```
modifc_harness/
    prompts.py          system prompt (SHA-256 checked) and the tool contract
    tasks.py            task loading and IFC path resolution
    sandbox.py          parent side of the code sandbox
    sandbox_worker.py   the subprocess that holds one open IFC model
    client.py           OpenAI-compatible chat client, stdlib only
    agent.py            the agent loop and the budget rule
    runner.py           runs a task list and writes the run directory
    models.py           the candidate models and their serve invocations
    serve.py            starting, sizing, supervising and stopping the server
    bakeoff.py          one model end to end: serve, run a slice, shut down
    cli.py              command line entry points
scripts/
    serve_model.sh      start one vLLM server by hand
    run_bakeoff.sh      run every candidate in turn, one server at a time
    smoke_test.py       three-task plumbing check for one model
```

## Environments

Two conda environments, because vLLM and IfcOpenShell cannot share one pin set.

* `l2vllm` runs the inference server (`vllm serve`, one model at a time).
* `l2` runs the harness client and the sandbox (Python 3.14, IfcOpenShell 0.8.5).

They talk over HTTP on localhost using the OpenAI tool-calling API.

## Running

The usual path is one command per model, which starts the server, runs the
tasks and shuts down again:

```bash
python -m modifc_harness.cli bakeoff --model granite-4.1-8b \
    --slice-file ../../phase0/bakeoff_slice_v1.json --max-model-len 65536
```

`scripts/run_bakeoff.sh` does that for every candidate in turn. To drive a
server by hand instead, `scripts/serve_model.sh <tag>` starts one and
`python -m modifc_harness.cli run --model <tag> ...` runs tasks against it.
`scripts/smoke_test.py` runs the three-task plumbing check and prints a per-task
verdict.

**Resuming.** A run skips a task only when its transcript records a stop reason
*and* its edited model is on disk and non-empty, because the file is what the
scorer reads. Anything else is run again, so an interrupted run picks up where
it stopped without inheriting a half-written artifact.

**A server that dies is restarted.** The supervisor checks health after any task
that ends in `inference_error`, restarts the server up to three times per model,
waits for the card to give the memory back before relaunching, and gives the
task one clean attempt afterwards. Every start, death and refusal is appended to
`server_events.jsonl` in the run directory.

**Memory.** The pool is sized against free memory at launch, not the card's
capacity: `--gpu-memory-utilization = (free - headroom) / total`, with a
3,072 MiB default headroom. Two launches of the same model can differ by several
hundred MiB of real occupancy, which is what the headroom is for.

## The protocol

**One tool.** `execute_ifc_code(code: str) -> str`, with the tool description
copied verbatim from the published run. The sandbox namespace pre-binds `ifc`
(the opened model), `ifcopenshell`, `api`, `util`, `element_util`, `guid`,
`commit()` and `result`.

**System prompt.** Byte-identical to the published one. Its SHA-256,
`ef33ea6c…e015b6b`, is the same in all seven published run configurations and is
asserted when `modifc_harness.prompts` is imported.

**Sampling.** Temperature 0, top-p 1.0, non-streaming. One retry after 30 s on a
transport failure, so at most two attempts per inference call.

**Sandbox.** One worker process per task, started with a fresh copy of the input
model; the source data is never opened for writing. The worker lives for the
whole task, so an object bound in one tool call is still bound in the next.
Anything the snippet prints is captured, `result` is appended if it was assigned,
and an exception is returned to the model as its traceback text rather than
retried. The per-call timeout is 420 s.

**Budget.** At most 22 executed tool rounds. See below.

**Reasoning models.** A model that deliberates inside `<think>` tags is served
with a reasoning parser, so the deliberation arrives in its own field and is not
replayed into the next turn. Its size is still recorded per turn as
`reasoning_chars`. Hosted reasoning models behave the same way, so this keeps
the local runs comparable with the published ones.

**End of run.** A run ends when the model answers without a tool call, or when
the budget is spent, or on a sandbox timeout or crash. Nothing is written to the
edited file after that point.

## The budget rule, and why it is 22 and not 20

The published run configuration sets `max_tool_calls: 20`, but that number was
not what stopped the agents. The runs were built on a LangGraph agent whose
recursion limit was 45 super-steps (the paper states the limit as
`20 x 2 + 5 = 45`), and the graph alternates a model turn with a tool turn. A
limit of 45 super-steps therefore admits 23 model turns and 22 executed tool
rounds, and the 23rd tool round is what raises `GraphRecursionError`.

The cached transcripts confirm this rather than the configured 20:

| Run | tasks | max tool rounds recorded | tasks at exactly 22 | recursion errors |
|---|---:|---:|---:|---:|
| claude-sonnet | 324 | 32 | 125 | 149 |
| qwen3.6-plus | 323 | 22 | 39 | 57 |
| gemini-flash-3.0 | 324 | 22 | 26 | 43 |
| gemma4-31B | 324 | 22 | 8 | 27 |
| deepseek-v3.2 | 324 | 21 | 0 | 0 |
| gpt-5.4 | 324 | 10 | 0 | 0 |
| gpt-5.4-mini | 324 | 10 | 0 | 0 |

No run ever finished cleanly at 22 rounds, no run under a working framework ever
exceeded 22, and there is no accumulation at 20. The recursion-error count per
model also matches the "budget exhausted" column of the paper's runtime-failure
table exactly, so budget exhaustion and the recursion limit are the same event.

This harness implements the equivalent rule directly:

* at most 22 tool rounds are executed;
* one further model turn is taken after the 22nd, so a model that is ready to
  answer still can;
* if that turn asks for another tool call, the run stops as `budget_exhausted`
  and the requested call is not executed.

An assistant turn carrying several tool calls counts as one round, which is how
the LangGraph tool node behaved.

## Deliberate departures from the published runs

Each of these is a decision, not an accident.

1. **Tool output includes captured standard output.** The published tool
   description only mentions `result`, but 4,652 of the 5,342 cached snippets in
   the claude-sonnet run call `print` and never assign `result`, and the models
   act on what they printed. Stdout must have been returned. This harness
   returns captured stdout, then `str(result)` if it was assigned, then the
   traceback if the snippet raised.
2. **Tool output is capped** at 16,000 characters by default, head and tail kept
   with a marker in between. The published runs served models with very large
   context windows and one call reached 95,000 input tokens; a locally served
   7B-12B model cannot absorb that. The cap is a configuration value.
3. **No task-level retry.** The published harness retried a whole task after a
   `GraphRecursionError`, which handed roughly one task in fifteen a second full
   budget. Retrying is kept for transport failures on a single inference call
   only, so every task gets exactly one budget.
4. **A per-call output cap of 8,192 tokens.** The published runs left
   `max_tokens` unset; the largest single model turn in the claude-sonnet cache
   is 3,232 output tokens, so the cap is not binding in practice and it keeps a
   local model from running away.
5. **Non-streaming requests.** This removes the streaming-timeout failure mode
   that the published runs recorded for two of their models.
6. **Timeout of 420 s per tool call**, which is what the shipped configuration
   used for five of the seven published runs. The paper says 120 s; the two
   OpenAI runs used that value.

## Task and path handling

The task file names its scenes `data/realistic/...` and `data/artificial/...`
while the scene repository ships `complex/` and `simple/`; the mapping is applied
in `tasks.py`. Paths recorded inside the published artifacts use Windows
separators and are normalised on read.

## Environment notes

* Every server launch exports `VLLM_USE_FLASHINFER_SAMPLER=0`. FlashInfer
  JIT-builds its sampling kernels with the CUDA 13.3 `nvcc` bundled in the
  serving environment against that tree's CUDA 13.0 runtime headers, and CCCL's
  compatibility check rejects the mismatch, so the engine dies during warm-up.
  vLLM's own top-p/top-k sampler is used instead.
* `--disable-log-requests` was removed in vLLM 0.27.1; request logging is off by
  default and turned on with `--enable-log-requests`.
* `gemma-4-12b-it` needs `transformers <= 5.14.1` and is served from its own
  environment (`l2vllm_gemma`, a clone of the serving environment with that pin;
  override with `MODIFC_VLLM_ENV_GEMMA`). The checkpoint is heterogeneous, 40
  sliding-attention layers at head_dim 256 and 8 full-attention layers at 512,
  and vLLM 0.27.1 reads `head_dim` and `global_head_dim` as flat config
  attributes. transformers 5.15.0 moved them behind a per-layer API and raises
  on any global read, so the server dies in argument parsing before a single
  weight is read. 5.14.1 is the newest release that still exposes them flat.
* Machine-specific paths come from `MODIFC_MODELS_DIR` and `CONDA_ROOT`, with
  `models/` and `~/miniconda3` as defaults.
