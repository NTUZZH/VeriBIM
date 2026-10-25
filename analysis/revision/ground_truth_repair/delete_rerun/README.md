# v4e deletion re-run (built 2026-10-16, nothing launched)

Re-runs, on `runs_local/bench_v4/tasks.v4d.jsonl`, every stored output whose code ran a deletion helper of the shared
library (`geom.delete_element`, `geom.delete_filling`, `geom.delete_filling_with_opening`) without a traceback on one of
the 49 deletion tasks whose ground truth was repaired (`gt_fix/rerun_list_delete_v2.csv`). The installed
`veribim_geom.py` / `goldlib.py` are the repaired versions; every script asserts their md5 against `plan.json`.

* `make_plan.py` -> `plan.json`, `subset_<run>_<model>.json`, `../rerun_delete_arms.md` (already run; rerun only if the list changes).
* `plan_tool.py` -> helpers used by the scripts (job lines, post-job check, server identification, busy cores, GPU holders, packing).
* `rerun_delete_local.sh` -> Qwen3.5-9B arms, one pass per server configuration (411 + 9 rows).
* `rerun_delete_gemma.sh` -> Gemma 4 31B arm (3 rows); starts and stops its own server.
* `rerun_delete_hosted.sh` -> commercial arms (16 jobs, 37 rows); hosted324_lib_all (4 rows) is spliced from the hosted108_lib_all and hosted216_lib_all re-runs.
* `splice_delete.py` -> replaces exactly the re-run rows in the canonical result files (after every DONE marker).
* `_drytest/build_dry.py` -> builds a small copy (4 arms, fake re-run rows) for testing the splice; see "Tests done".

Outputs: `delete_rerun/<run>/` (per_task, summary, logs, `DONE_<model>`, `CHECKED_<model>`, `<model>/edited.tar.gz`),
logs in `delete_rerun/logs/`. Markers: `RERUN_DELETE_LOCAL_9b_canonical_DONE`, `RERUN_DELETE_LOCAL_9b_owntemplate_DONE`,
`RERUN_DELETE_LOCAL_ALL_DONE`, `RERUN_DELETE_GEMMA_DONE`, `RERUN_DELETE_HOSTED_ALL_DONE`, `SPLICE_V4E_DONE`; a failure
leaves `RERUN_DELETE_<LOCAL|GEMMA|HOSTED>_FAILED` and the reason in the log.

## Checks before launch

1. **Disk.** Free now: 23 GiB. The 460 re-run edited models are about 34 GB unpacked (293 rows on the 111 MB building
   225). The scripts therefore pack each job's `edited/` into `edited.tar.gz` right after its check (`PACK_EDITED=1`,
   default; ratio about 5, so about 7 GB in total, largest job 3.35 GB unpacked while it runs). Each job refuses to
   start below its own size plus 8 GiB (`MIN_FREE_RUN_GB`). The splice refuses below 30 GiB free, so about 15 GB must be
   freed before the splice (after the runs about 16 GiB will be free). Hard links make the splice itself cost nothing.
2. **Cores 20-23** must be idle (`ps -eo pid,psr,pcpu,args`; at build time two `gt_fix/offtarget_subset.py` processes
   were busy on them). Every script refuses when another pinned process is busy there. The local and hosted scripts
   both use 20-23, so run them one after the other (or give one of them `CORES=<other free set>`).
3. **Memory.** 16 sandboxes on building 225 plus two 3 GB score workers: the local script needs 40 GB `MemAvailable`
   per job (`MIN_AVAIL_GB`), the hosted script 24 GB, the Gemma script 40 GB.
4. **GPU and peers.** The 9B server and the Gemma server (0.90 of the card) need the GPU; check the peer windows
   (BOLT, PaperX) and `runs_local/BOLT_WINDOW_OPEN`. `nvidia-smi` currently fails (driver/library mismatch), so the
   scripts check GPU holders through `/proc/*/fd`.
5. Keys: `~/.config/veribim/keys.env` must hold ANTHROPIC, OPENAI, GEMINI and DEEPSEEK keys (the hosted script checks presence only).
6. Read `../rerun_delete_arms.md` once: it names, per arm, the server, adapter, note and md5, request style, and the original launcher.

## Launch order

All commands detached; `D=analysis/revision/ground_truth_repair/delete_rerun`.

1. **9B server, canonical template** (Stage C server, as every adapter read and the libnote read used). Pick free cores for its EngineCore (not 20-23):
   `PYTHONNOUSERSITE=1 UTIL=0.46 CORES=<free> ADAPTER=checkpoints/stage_a/sft_v10/adapter NAME=sft_v10 LOG=$D/logs/serve_canonical.log setsid nohup bash code/stage_c/scripts_serve.sh > /dev/null 2>&1 < /dev/null &`
2. `setsid nohup bash $D/rerun_delete_local.sh > $D/logs/rerun_delete_local.out 2>&1 < /dev/null &`
   It recognises the canonical server and runs 22 jobs (411 rows), grouped by adapter, the two single-edit latency jobs
   (local108_lib_solo, concurrency 1) last. Those two need the GPU held by the server alone, no other gate read alive
   (the hosted script must not run then; `SOLO_RUNNING` blocks it) and idle cores; contention samples every 30 s go to
   `logs/solo_contention_<model>.log`, and any contention leaves `CONTENDED_<model>` instead of DONE.
3. Stop the server: `kill -TERM -- -<pgid>` (pgid from `python plan_tool.py server`).
4. **9B server, model's own template, 65,536 tokens** (as the 10-13 base informed read and the 10-15 retrieval reads used; flags of `analysis/revision/base_documented/serve_base.sh`, log redirected):
   `setsid nohup bash -c 'export VLLM_USE_FLASHINFER_SAMPLER=0 PYTHONNOUSERSITE=1; exec taskset -c <free> ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2vllm/bin/vllm serve ${BASE_MODEL:-models/Qwen3.5-9B} --served-model-name Qwen3.5-9B --port 8000 --host 127.0.0.1 --max-model-len 65536 --gpu-memory-utilization 0.777 --enable-auto-tool-choice --tool-call-parser qwen3_xml --chat-template ${BASE_MODEL:-models/Qwen3.5-9B}/chat_template.jinja --language-model-only --enable-lora --max-lora-rank 16 --max-loras 1' >> $D/logs/serve_owntemplate.log 2>&1 < /dev/null &`
5. Run `rerun_delete_local.sh` again (same command as 2). It recognises this server and runs the 3 base-model jobs (9 rows). Then stop the server as in 3.
6. `setsid nohup bash $D/rerun_delete_gemma.sh > $D/logs/rerun_delete_gemma.out 2>&1 < /dev/null &` (needs no server running; starts Gemma on cores 16-19 as `serve_gemma.sh`, or `GEMMA_SERVER_CORES`, and stops it with `kill -TERM -- -<pgid>`).
7. `setsid nohup bash $D/rerun_delete_hosted.sh > $D/logs/rerun_delete_hosted.out 2>&1 < /dev/null &` (any time no solo job runs and cores 20-23 are free; no GPU).
8. After all ALL_DONE markers and the checks below: free disk to at least 30 GiB, then
   `cd $D && PYTHONNOUSERSITE=1 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python splice_delete.py --check`
   and, after reading its output, `... splice_delete.py --foreign-ok` (see "Foreign reference").

Every script is resumable: rerun the same command; DONE jobs are skipped, CHECKED jobs resume at audit/pack, unfinished
attempts are moved aside to `*.attempt_<time>` (they hold unpacked models; remove them by hand once a job is DONE).

## Checks after the runs, before the splice

* Logs: every job has `START`, `END rc=0`, a `checked {...}` line (task set equal to the subset, resolved_agent_config
  equal to the arm's original summary) and `=== DONE`. Read every `NOTE ... inference errors / unscorable` line.
* `fs_audit_<model>.log` per job (file-access audit), `logs/solo_contention_*.log` (must hold no CONTENTION line).
* Env lines in the logs (`env: note ..., guard 1, landlock 1, request style ..., effort ...`) against `../rerun_delete_arms.md`.
* Hosted cost: `delete_rerun/hosted*/cost_<model>.json` and the total line at the end of `logs/rerun_delete_hosted.log`.
* Score changes: compare each re-run row with the canonical row (expected: deletion scores unchanged, as the rescoring found;
  any change is a model-behaviour difference between runs, not the repair).
* Sample a few re-run edited models (inside `edited.tar.gz`) for the four relationship classes the repair removes
  (IfcRelAssociatesClassification, IfcRelCoversBldgElements, IfcRelOccupiesSpaces, IfcRelAssignsToActor with an empty required end).

## Splice and after

* `splice_delete.py` archives `per_task_/by_version_/summary_<m>` as `*.pre_v4e`, moves the old transcripts/logs (and any
  unarchived edited dir) of the re-run tasks to `*_pre_v4e/`, hard-links the re-run files in, links a packed re-run as
  `<m>/edited_v4e.tar.gz` (rows keep the canonical `results/<run>/<m>/edited/<task>/<file>` path, a member of that
  archive), links the re-run meta files into `results/<run>/rerun_meta_v4e/`, runs `finish_read.sh` and rebuilds the
  summary (`v4e_rerun_tasks`, `v4e_finalized_at`). It verifies row counts, task order, unchanged non-re-run rows,
  re-run rows equal apart from `edited_ifc`, every edited model present (file or archive member), and hard links.
* **Foreign reference.** `local108_lib_solo_cpu_contended_20261002/per_task_grpo_v10_c50.jsonl` names paths inside
  `local108_lib_solo/grpo_v10_c50/edited/` (it was renamed from that folder without rewriting its paths). After the
  splice, three of those paths (the deletion tasks) name the re-run's archive members; the contended arm itself is not
  changed. `--check` lists such rows; the splice proceeds only with `--foreign-ok`.
* Afterwards: rebuild the tables and macros that read these arms; `summaries.json` in each run folder is not touched
  (the v4d finalize did not touch it either). The latency macros come from local108_lib_solo: three of the 108
  single-edit durations change with the splice; decide whether the latency figures are regenerated.

## Tests done (2026-10-16)

* `bash -n` on the three shell scripts; `py_compile` on the Python files.
* `splice_delete.py --check` on the real folders: lists all 43 arms (464 rows) and refuses, as expected, on the 42
  missing DONE markers and on the disk floor (23.1 GiB free); nothing written.
* Dry test on copies (`_drytest/build_dry.py`, results and re-run copies under `_drytest/`, removed afterwards):
  refusal on a foreign reference, on a missing DONE marker and on the disk floor; `--check` left every file of the copy
  byte-identical (89 entries compared); the splice of four arms (an unpacked local arm, two packed hosted arms, the
  composite) passed its own verification; a second run and a run after a simulated interruption (new per-task file and
  one transcript link removed) completed without moving any re-run file into a `*_pre_v4e` folder.
* `plan_tool.py check` and `pack` on the dry copy (protocol from the original summary, cost by `hosted_cost.py` prices).
* Note checks: md5 for the three note files, sha256 manifests for the two retrieval note folders; installed library md5
  equal to `gt_fix/patched_code/`.
