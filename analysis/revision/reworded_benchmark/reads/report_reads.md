# Reads on the 172 reworded benchmark instructions (2026-10-19)

Every number below comes from `reads/pairing_summary.json`, which `summarize_rw.py` writes. The inputs are listed under `files` in that JSON.
- Completion rule: geometry, semantics and topology are all ≥ 0.90 under the family reading.
- Statistics: an exact two-sided McNemar test on the discordant pairs, and Wilson 95% intervals.
- Generated-wording rows: the same 172 tasks taken from the stored full benchmark reads (`bench_v4/results/full_all/per_task_<model>.jsonl`, v4d/v4e state).
- Parser generated wording: this folder's v4d run on the 200 drawn tasks.

## Pairing table (172 tasks)

| Arm | Reworded | Wilson 95% | Generated wording | Wilson 95% | Both | Generated only | Reworded only | Neither | McNemar p |
|---|---|---|---|---|---|---|---|---|---|
| grpo_v10b_c10 (final) | 158 (0.9186) | 0.868–0.951 | 163 (0.9477) | 0.904–0.972 | 156 | 7 | 2 | 7 | 0.180 |
| dpo_v10_c6 | 158 (0.9186) | 0.868–0.951 | 164 (0.9535) | 0.911–0.976 | 157 | 7 | 1 | 7 | 0.070 |
| sft_v10 | 159 (0.9244) | 0.875–0.955 | 164 (0.9535) | 0.911–0.976 | 159 | 5 | 0 | 8 | 0.0625 |
| template parser | 0 (0.000) | 0.000–0.022 | 172 (1.000) | 0.978–1.000 | 0 | 172 | 0 | 0 | <0.0001 |

- The parser recognised 0 of the 172 reworded instructions.
- On all 200 drawn tasks in generated wording, the parser completed 200 of 200 (Wilson 0.981–1.000) and recognised all 200.
- For the three models, the reworded minus generated-wording difference is −0.029 (final model), −0.035 (dpo) and −0.029 (sft). No model's difference is significant at 0.05.

## By operation and category (n: generated → reworded completed; McNemar p)

| Slice | n | grpo_v10b_c10 | dpo_v10_c6 | sft_v10 | parser |
|---|---|---|---|---|---|
| create | 65 | 63 → 61 (p 0.50) | 63 → 60 (p 0.25) | 63 → 61 (p 0.50) | 65 → 0 |
| delete | 66 | 65 → 64 (p 1.0) | 65 → 64 (p 1.0) | 65 → 64 (p 1.0) | 66 → 0 |
| update | 41 | 35 → 33 (p 0.69) | 36 → 34 (p 0.63) | 36 → 34 (p 0.50) | 41 → 0 |
| direct | 48 | 47 → 48 (p 1.0) | 48 → 48 (p 1.0) | 48 → 48 (p 1.0) | 48 → 0 |
| spatial | 51 | 46 → 44 (p 0.63) | 46 → 44 (p 0.63) | 46 → 44 (p 0.50) | 51 → 0 |
| topological | 73 | 70 → 66 (p 0.125) | 70 → 66 (p 0.125) | 70 → 67 (p 0.25) | 73 → 0 |

Wilson intervals and the version and family slices are in the JSON (`by_slice`).

## Final model (grpo_v10b_c10): failed tasks

**Fails on the reworded instruction: 14.** Stop reasons: 11 completed, 3 budget_exhausted. "Also fails generated" is yes for the 7 overlap tasks.

| Task | Family / operation / category | Edit | Stop reason | Also fails generated |
|---|---|---|---|---|
| COL-CRE-TOP-G7structure-002 | column / create / topological | create_box | completed | yes |
| DOR-CRE-TOP-B16m4X3-002 | door / create / topological | replace_filling | budget_exhausted | yes |
| DOR-DEL-SPA-B16m4-005 | door / delete / spatial | delete | completed | no |
| DOR-UPD-TOP-G7arc-011 | door / update / topological | rehost_filling | budget_exhausted | no |
| SLB-UPD-SPA-B46m4-041 | slab / update / spatial | translate | completed | yes |
| SLB-UPD-SPA-B46m4-024 | slab / update / spatial | mirror | completed | yes |
| SLB-UPD-TOP-G7structurem4-009 | slab / update / topological | move_to_storey | completed | no |
| SPC-CRE-SPA-B02m4-002 | space / create / spatial | create_box | completed | no |
| CHN-MSW-TOP-B25m4-036 | space / update / topological | move_space_with_bounding_walls | completed | no |
| CHN-CWD-SPA-B27-005 | wall / create / spatial | create_wall_with_door | completed | no |
| WAL-UPD-TOP-B39m4X3-008 | wall / update / topological | move_to_storey | completed | no |
| WAL-UPD-TOP-B02m4X3-001 | wall / update / topological | assign_type | budget_exhausted | yes |
| WIN-DEL-SPA-B02m4-001 | window / delete / spatial | delete | completed | yes |
| WIN-UPD-SPA-B02-002 | window / update / spatial | assign_type | completed | yes |

**Fails in generated wording: 9.** Stop reasons: 6 completed, 2 budget_exhausted, 1 context_overflow.

| Task | Family / operation / category | Edit | Stop reason | Also fails reworded |
|---|---|---|---|---|
| COL-CRE-TOP-G7structure-002 | column / create / topological | create_box | completed | yes |
| DOR-CRE-TOP-B16m4X3-002 | door / create / topological | replace_filling | budget_exhausted | yes |
| DOR-UPD-DIR-G7arc-002 | door / update / direct | rehost_filling | completed | no |
| SLB-UPD-SPA-B46m4-013 | slab / update / spatial | translate | completed | no |
| SLB-UPD-SPA-B46m4-041 | slab / update / spatial | translate | completed | yes |
| SLB-UPD-SPA-B46m4-024 | slab / update / spatial | mirror | budget_exhausted | yes |
| WAL-UPD-TOP-B02m4X3-001 | wall / update / topological | assign_type | completed | yes |
| WIN-DEL-SPA-B02m4-001 | window / delete / spatial | delete | completed | yes |
| WIN-UPD-SPA-B02-002 | window / update / spatial | assign_type | context_overflow | yes |

**How the two lists relate**
- **Overlap: 7** tasks fail in both wordings, so the rewording did not cause those failures.
- **Lost on rewording: 7.** DOR-DEL-SPA-B16m4-005, DOR-UPD-TOP-G7arc-011, SLB-UPD-TOP-G7structurem4-009, SPC-CRE-SPA-B02m4-002, CHN-MSW-TOP-B25m4-036, CHN-CWD-SPA-B27-005 and WAL-UPD-TOP-B39m4X3-008. They are mostly topological or spatial anchors and long multi-part requests.
- **Gained on rewording: 2** (DOR-UPD-DIR-G7arc-002 and SLB-UPD-SPA-B46m4-013).
- **Example of a loss.** DOR-DEL-SPA-B16m4-005's rewording lists the wall, spaces and storey before the door. The model then looked for the door "on storey 1glSrs9VT1vP3cEqsjVbyl", which is the wall's id (transcript `reads/model/grpo_v10b_c10/transcripts/DOR-DEL-SPA-B16m4-005-rw.json`).
- Scores and tool rounds for each task are in `final_model_failures` in the JSON.

## Reads: settings, wall-clock and sandbox
**Settings**
- Command family: `stage_a.run_gate`, the library arm, family reading, concurrency 16, 2 score workers, harness on cores 20–23.
- Server: the Stage C canonical-template server.
- Gold models: rebuilt from v4d into fresh caches in this folder.
- Protocol: `resolved_agent_config` is identical for the three models and equals the benchmark reads' protocol (22 tool rounds, 420 s tool timeout, 8,192 output tokens, temperature 0). The read script asserted this.
- Inference errors: 0 in every read.

**Wall-clock** (elapsed time between the START and END lines in `reads/read_model_rw.log`)
- grpo_v10b_c10: 16.5 min (14:40:29–14:56:59).
- sft_v10: 20.0 min (15:14:58–15:34:59).
- dpo_v10_c6: 21.0 min (15:35:46–15:56:46).
- The `wall_seconds` field in each summary is the sum of per-task durations under concurrency 16, not elapsed time.
- Parser: 13.2 min on the reworded 172 (14:58:40–15:11:50) and 21.9 min on the 200 originals (15:11:50–15:33:43). Both used 2 workers on cores 16–23.
- These are accuracy reads, not timing measurements. The parser's original-wording run (cores 16–23) overlapped the sft_v10 read (cores 20–23). No tool call in any read hit the tool timeout: 0 transcripts mention a sandbox timeout, and there were 0 sandbox crashes.

**Sandbox**
- Every model read ran with `VERIBIM_SANDBOX_GUARD=1` and `VERIBIM_SANDBOX_LANDLOCK=1`. The parser runs set the same variables in `run_parser.sh`.
- File-access audit (`bench_v4/audit_fs_access.py` over every transcript): **0 flagged of 172** for each model (`reads/model/fs_audit_<model>.log/.json`).
- The guard's `sandbox_blocked` counter is nonzero on a few tasks: grpo 6 events on 5 tasks, sft 3, dpo 2.
  - The inspected event is an `open` of `<unknown>` raised inside the shared library's error path when an anchor lookup fails. No file was read.
  - The same counter is 67 events on 27 tasks in the stored full read of the final model.
  - The parser has no transcripts; its program text is generated from templates.
