# Ground-truth repair: door re-hosting and dangling relationships after deletion

Task folder: analysis/revision/ground_truth_repair. Every number below comes from a file in this folder, named next to it.

## What was done, in plain words

1. **Two library defects were fixed**, first in a working copy (patched_code/), then installed in place:
   code/modifc_gen/goldlib.py (ground-truth library) and code/harness/modifc_harness/veribim_geom.py (the library the models call, which goldlib also uses for every deletion). The shipped files are kept as `goldlib.py.bak_20261015_fix` and `veribim_geom.py.bak_20261015_fix` next to them. Full diffs: `goldlib.diff`, `veribim_geom.diff` (also appended at the end of this report). The patch is reproducible from the shipped files with `scripts/patch_goldlib.py` and `scripts/patch_geom.py`.
2. **Tests** (tests/) on synthetic models in IFC2X3, IFC4 and IFC4X3 and on one benchmark source model per schema: 40 of 40 pass with the repaired library (`out/tests_new.txt`, and again on the installed code: `out/tests_installed_code.txt`); with the shipped library 34 fail and 6 pass, the 6 being the convention tests that both versions must pass (`out/tests_old.txt`). The repository's own deletion suite `code/stage_a/tests/test_delete_v8.py` passes on the installed code (33 passed, 1 skipped; `out/existing_test_delete_v8_installed.txt`).
3. **69 ground truths were regenerated** (19 re-hosting tasks + 50 tasks with an empty required relationship end; no overlap) into `gold_new/<task_id>/`. The same gold scripts run with the shipped library reproduce the recorded checksum in 69 of 69 tasks (`out/regen_old.jsonl`), so the old/new comparison is exact. Per-task checksums and a one-line change are in `gt_changes.csv` (table below).
4. **Nothing else changed.** All 747 other benchmark tasks whose gold script deletes, replaces or re-hosts something were rebuilt with the repaired library: 747 of 747 are byte-identical to their recorded checksum (`out/regression_new.jsonl`).
5. **Rescoring** of every stored arm output on the affected tasks against the new ground truths, with the reported checker settings (`stage_a.scoring.score_prediction`, `scorer_config_for(record)` family reading, all three axes, per-pair geometry, the run's closing reply; `scripts/rescore_arm.py`). Pipeline check first: rescoring 13 affected tasks of local324_lib_all/grpo_v10b_c10 against rebuilt shipped-library ground truths reproduced all 13 recorded scores exactly (`out/validation_old_gt.jsonl`). Results: `effect.csv` (749 rows), `rescored/<run>/per_task_<model>_fixed.jsonl`, `arm_summary.csv`.
6. **Re-run list** from the transcripts: `rerun_list.csv` (176 rows), built by `scripts/grep_transcripts.py` (`out/helper_calls.jsonl`).

## Main results

* **Re-hosting changes scores; the deletion repair changes none.** Of the 749 rescored (arm, task) rows, 113 change at least one axis, and all 113 are re-hosting tasks (geometry only). None of the 564 deletion-task rows changes on any axis in any arm (`effect.csv`): the checker's relation graph does not register the dangling IfcRelCoversBldgElements / IfcRelAssociatesClassification / IfcRelAssignsToActor / IfcRelOccupiesSpaces rows that the old ground truths kept.
* **VeriBIM-9B (grpo_v10b_c10)**, 2,100 tasks (full_all): 2,016 → 2,004 completed (0.9600 → 0.9543), 12 lost, 0 gained, all 12 on re-hosting tasks; on the 19 re-hosting tasks completion drops from 18 to 6. 108-task subset (local108_lib_all): 105 → 105 (no re-hosting task in the subset). 324-task subset (local324_lib_all): 311 → 310 (0.9599 → 0.9568; DOR-UPD-TOP-G7arcm4-010 lost). These outputs were written with the defective `geom.move_filling` and match the old ground truth, so the drop measures the shared defect, not the model; they are on the re-run list.
* **Commercial arms.** All 108-task arms are unchanged (their 3 affected tasks are deletions). Claude Sonnet 5.5 on the 216/324 tasks gains one completion in the alone and library arms (DOR-UPD-TOP-G7arcm4-010: geometry 0.833 → 0.966 alone, 0.833 → 1.0 library): hosted216_alone 162 → 163, hosted216_lib 187 → 188, hosted324_alone 241 → 242, hosted324_lib 279 → 280. The informed arm on the remaining 216 tasks loses one (hosted324rest_informed 211 → 210, same task, geometry 1.0 → 0.833); its transcript calls `move_filling`, so it carries the old defect and is on the re-run list.
* **Stage models on 2,100** (full_all): sft_v10 2,000 → 1,988; dpo_v10_c6 2,010 → 1,998; grpo_v10_c50 2,013 → 2,001; dpo_small_c12 1,541 → 1,535; grpo_small_c10 1,546 → 1,543; sft_small 1,518 → 1,514. The base model with the note (full_note_all, 982 tasks) is unchanged (20).
* Six arm files have no stored edited models and keep their recorded rows (`out/not_rescored.json`): full_all/dpo_v10_c3 and full_all/dpo_v9_c10 (no edited.tar.gz, 69 tasks each), local108_lib_solo (both models), local108_lib_solo_cpu_contended_20261002, local324_lib_all/sft_extA (archive missing).

### Per-arm summary (`arm_summary.csv`; completion = all three axes >= 0.9, over the arm's full task set, old rows for unaffected tasks plus new rows for the affected ones)

| Run | Model | Tasks | Affected | Rescored | Lost | Gained | Completed before | Completed after | Completion before | Completion after |
|---|---|---|---|---|---|---|---|---|---|---|
| full_all | dpo_small_c12 | 2100 | 69 | 69 | 6 | 0 | 1541 | 1535 | 0.7338 | 0.731 |
| full_all | dpo_v10_c3 | 2100 | 69 | 0 (no stored models) | 0 | 0 | 2009 | 2009 | 0.9567 | 0.9567 |
| full_all | dpo_v10_c6 | 2100 | 69 | 69 | 12 | 0 | 2010 | 1998 | 0.9571 | 0.9514 |
| full_all | dpo_v9_c10 | 2100 | 69 | 0 (no stored models) | 0 | 0 | 1923 | 1923 | 0.9157 | 0.9157 |
| full_all | grpo_small_c10 | 2100 | 69 | 69 | 3 | 0 | 1546 | 1543 | 0.7362 | 0.7348 |
| full_all | grpo_v10_c50 | 2100 | 69 | 69 | 12 | 0 | 2013 | 2001 | 0.9586 | 0.9529 |
| full_all | grpo_v10b_c10 | 2100 | 69 | 69 | 12 | 0 | 2016 | 2004 | 0.96 | 0.9543 |
| full_all | sft_small | 2100 | 69 | 69 | 4 | 0 | 1518 | 1514 | 0.7229 | 0.721 |
| full_all | sft_v10 | 2100 | 69 | 69 | 12 | 0 | 2000 | 1988 | 0.9524 | 0.9467 |
| full_note_all | Qwen3.5-9B | 982 | 36 | 36 | 0 | 0 | 20 | 20 | 0.0204 | 0.0204 |
| hosted108_alone_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 79 | 79 | 0.7315 | 0.7315 |
| hosted108_alone_all | deepseek-v4-pro | 108 | 3 | 3 | 0 | 0 | 58 | 58 | 0.537 | 0.537 |
| hosted108_alone_all | gemini-3.8-flash | 108 | 3 | 3 | 0 | 0 | 20 | 20 | 0.1852 | 0.1852 |
| hosted108_alone_all | gpt-5.6-luna | 108 | 3 | 3 | 0 | 0 | 27 | 27 | 0.25 | 0.25 |
| hosted108_informed_all | claude-opus-5-5 | 108 | 3 | 3 | 0 | 0 | 103 | 103 | 0.9537 | 0.9537 |
| hosted108_informed_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 107 | 107 | 0.9907 | 0.9907 |
| hosted108_informed_all | deepseek-v4-pro | 108 | 3 | 3 | 0 | 0 | 97 | 97 | 0.8981 | 0.8981 |
| hosted108_informed_all | gemini-3.8-flash | 108 | 3 | 3 | 0 | 0 | 83 | 83 | 0.7685 | 0.7685 |
| hosted108_informed_all | gpt-5.6-luna | 108 | 3 | 3 | 0 | 0 | 69 | 69 | 0.6389 | 0.6389 |
| hosted108_informed_rep2_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 107 | 107 | 0.9907 | 0.9907 |
| hosted108_informed_rep3_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 107 | 107 | 0.9907 | 0.9907 |
| hosted108_lib_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 92 | 92 | 0.8519 | 0.8519 |
| hosted108_lib_all | deepseek-v4-pro | 108 | 3 | 3 | 0 | 0 | 85 | 85 | 0.787 | 0.787 |
| hosted108_lib_all | gemini-3.8-flash | 108 | 3 | 3 | 0 | 0 | 65 | 65 | 0.6019 | 0.6019 |
| hosted108_lib_all | gpt-5.6-luna | 108 | 3 | 3 | 0 | 0 | 45 | 45 | 0.4167 | 0.4167 |
| hosted108_asknote_all | claude-sonnet-5-5 | 108 | 3 | 3 | 0 | 0 | 102 | 102 | 0.9444 | 0.9444 |
| hosted108_asknote_all | deepseek-v4-pro | 108 | 3 | 3 | 0 | 0 | 88 | 88 | 0.8148 | 0.8148 |
| hosted108_asknote_all | gemini-3.8-flash | 108 | 3 | 3 | 0 | 0 | 65 | 65 | 0.6019 | 0.6019 |
| hosted108_asknote_all | gpt-5.6-luna | 108 | 3 | 3 | 0 | 0 | 45 | 45 | 0.4167 | 0.4167 |
| hosted216_alone_all | claude-sonnet-5-5 | 216 | 10 | 10 | 0 | 1 | 162 | 163 | 0.75 | 0.7546 |
| hosted216_lib_all | claude-sonnet-5-5 | 216 | 10 | 10 | 0 | 1 | 187 | 188 | 0.8657 | 0.8704 |
| hosted324_alone_all | claude-sonnet-5-5 | 324 | 13 | 13 | 0 | 1 | 241 | 242 | 0.7438 | 0.7469 |
| hosted324_lib_all | claude-sonnet-5-5 | 324 | 13 | 13 | 0 | 1 | 279 | 280 | 0.8611 | 0.8642 |
| hosted324rest_informed_all | claude-sonnet-5-5 | 216 | 10 | 10 | 1 | 0 | 211 | 210 | 0.9769 | 0.9722 |
| local108_alone_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 2 | 2 | 0.0185 | 0.0185 |
| local108_alone_all | sft_v10 | 108 | 3 | 3 | 0 | 0 | 18 | 18 | 0.1667 | 0.1667 |
| local108_alone_sampled_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 3 | 3 | 0.0278 | 0.0278 |
| local108_alone_thinking_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 2 | 2 | 0.0185 | 0.0185 |
| local108_informed_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 69 | 69 | 0.6389 | 0.6389 |
| local108_informed_all | gemma-4-31b-it-awq | 108 | 3 | 3 | 0 | 0 | 77 | 77 | 0.713 | 0.713 |
| local108_lib_all | dpo_v10_c6 | 108 | 3 | 3 | 0 | 0 | 104 | 104 | 0.963 | 0.963 |
| local108_lib_all | grpo_v10_c50 | 108 | 3 | 3 | 0 | 0 | 105 | 105 | 0.9722 | 0.9722 |
| local108_lib_all | grpo_v10b_c10 | 108 | 3 | 3 | 0 | 0 | 105 | 105 | 0.9722 | 0.9722 |
| local108_lib_all | sft_v10 | 108 | 3 | 3 | 0 | 0 | 104 | 104 | 0.963 | 0.963 |
| local108_lib_solo | grpo_v10_c50 | 108 | 3 | 0 (no stored models) | 0 | 0 | 105 | 105 | 0.9722 | 0.9722 |
| local108_lib_solo | grpo_v10b_c10 | 108 | 3 | 0 (no stored models) | 0 | 0 | 105 | 105 | 0.9722 | 0.9722 |
| local108_lib_solo_cpu_contended_20261002 | grpo_v10_c50 | 108 | 3 | 0 (no stored models) | 0 | 0 | 105 | 105 | 0.9722 | 0.9722 |
| local108_libnote_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 2 | 2 | 0.0185 | 0.0185 |
| local108_retrieval_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 95 | 95 | 0.8796 | 0.8796 |
| local108_retrievalshort_all | Qwen3.5-9B | 108 | 3 | 3 | 0 | 0 | 97 | 97 | 0.8981 | 0.8981 |
| local324_alone_all | sft_v10 | 324 | 13 | 13 | 0 | 0 | 54 | 54 | 0.1667 | 0.1667 |
| local324_lib_all | dpo_v10_c6 | 324 | 13 | 13 | 1 | 0 | 309 | 308 | 0.9537 | 0.9506 |
| local324_lib_all | dpo_v9_c10 | 324 | 13 | 13 | 1 | 0 | 301 | 300 | 0.929 | 0.9259 |
| local324_lib_all | grpo_v10_c50 | 324 | 13 | 13 | 1 | 0 | 311 | 310 | 0.9599 | 0.9568 |
| local324_lib_all | grpo_v10b_c10 | 324 | 13 | 13 | 1 | 0 | 311 | 310 | 0.9599 | 0.9568 |
| local324_lib_all | sft_extA | 324 | 13 | 0 (no stored models) | 0 | 0 | 300 | 300 | 0.9259 | 0.9259 |
| local324_lib_all | sft_v10 | 324 | 13 | 13 | 1 | 0 | 310 | 309 | 0.9568 | 0.9537 |

## The two code changes

### (a) Re-hosting a door or window (`goldlib.rehost_filling`, `goldlib._replant`; `veribim_geom.move_filling`, `veribim_geom._replant`)

Before: `_replant` wrote the cut depth into the opening profile's YDim and put the opening's origin at the near face, assuming the profile holds the cut. In all 19 benchmark tasks the source opening is a profile holding the face (XDim height, YDim width) extruded across the wall (`out/probe_rehost_sources.json`: extrusion along the wall's y axis in 19 of 19, extruded towards -y in DOR-UPD-TOP-G7arc-004, the leaf hung from the opening in 19 of 19).

After:
* `cut_form(solid)` reads, in the product's own axes after its rotation is cleared (the new wall's frame), which dimension runs across the wall: the extrusion (`"depth"`), the profile's YDim or its XDim. An oblique extrusion or profile raises ValueError.
* `resize_cut` sets only that dimension to the stated depth and keeps the face size. The body grows symmetrically about its own centre across the wall (for an extrusion, the solid's start point is moved back by half the change; a private position and point are created so nothing shared is written through), so a leaf hung from the opening keeps its place relative to the opening's centre.
* `_replant` then places the origin so the body spans exactly `[across, across + thickness]` across the wall, i.e. centred in the wall and 50 mm past each face, which is what the generator's arguments (`across` = near face − 0.05 m, `thickness` = wall thickness + 0.1 m) intended. Along the wall and in height the origin is placed as before.
* The leaf: a leaf hung from the opening (all 19 tasks) is untouched and follows. A leaf hung from the wall itself is centred in the wall when it gets a new depth (`leaf_depth`, rectangular leaf), and otherwise keeps the offset across the wall from the opening's centre that it had in the wall it left (read before anything moves). `move_filling` follows the same rules with its own measured inputs.
* The public docstrings of `move_filling` and `delete_element` were left as shipped, so the help text a model can read is unchanged; they remain accurate.

Effect on the 19 ground truths (`gt_changes.csv`): the opening now keeps its face (e.g. A26 = DOR-UPD-TOP-G7arcm4-010: profile 2.400 × 0.300 m, depth 0.100 m, at 1.37–1.67 m along and −0.15…−0.05 m across → 2.400 × 1.000 m, depth 0.300 m, at 1.02–2.02 m along and −0.15…0.15 m across a −0.10…0.10 m wall), the opening is centred in the wall in 19 of 19 (offset 0.0000 m), and the door body is centred in the wall (A26: −0.197…−0.003 → −0.097…0.097 m). The door casings of the 0.813 m Revit doors overhang the opening by 0.076 m at both jambs and the head, exactly as they do in the source model (checked in the benchmark tests against the source's own overhang).

### (b) Relationships left without a required end after a deletion (`veribim_geom._sweep_empty_relations`, `delete_element`, `delete_filling`, `deletion_is_complete`; used by `goldlib.delete_element`, `goldlib.delete_filling_with_opening` and `goldlib.replace_filling`)

Before: the sweep removed only relationships of eleven listed classes whose related side became empty. IfcRelCoversBldgElements (relating element gone), IfcRelAssociatesClassification, IfcRelAssignsToActor and IfcRelOccupiesSpaces (related set empty) were not listed and stayed.

After: `_dangling_relations` reads, for every IfcRelationship class, the explicit attributes whose names start with Relating or Related, are not OPTIONAL and not derived, with the aggregate's lower bound (SET [1:?] → 1; LIST [0:?] such as RelatingPriorities → 0), from IfcOpenShell's schema for the file (IFC2X3, IFC4, IFC4X3_ADD2). After the existing sweep has finished, any relationship with such an end null or below its bound is removed too, sparing the rows that already lacked one before the deletion (snapshot taken before the removal, as for the existing sweep). Because the new rule runs only once the old one has nothing left, a deletion that leaves no such relationship writes the same file as before, which the 747-task regression confirms. Conventions kept: a deleted space's contained elements stay, uncontained; a deleted wall's layer parts stay; the covering itself stays when its element goes (only the relationship is removed). `deletion_is_complete` reports such rows as well.

Effect on the 50 ground truths (`gt_changes.csv`): 53 IfcRelAssociatesClassification, 15 IfcRelCoversBldgElements, 5 IfcRelOccupiesSpaces and 5 IfcRelAssignsToActor rows removed; the count of empty required ends goes to 0 in all 50 (it matches the checker-validity list task for task).

## Tests (tests/, run `python -m pytest tests`; `GT_FIX_LIB=old` runs them on code/)

* `test_rehost.py`: openings drawn as face profile + extrusion across the wall (both extrusion directions, leaf turned half a turn in the flipped case) and openings whose profile holds the cut (made by `goldlib.add_filling`, leaf hung from the wall, with and without `leaf_depth`); for both `goldlib.rehost_filling` and `veribim_geom.move_filling`; in three schemas, in millimetre models. Asserted: face size kept, depth = wall thickness + 0.1 m, centred in the wall, voids the new wall, leaf inside the opening (synthetic) or with the source's own overhang and centring (benchmark sources DOR-UPD-DIR-G7arc-001 IFC2X3, DOR-UPD-TOP-G7arcm4-010 IFC4, DOR-UPD-SPA-G7arcm4X3-003 IFC4X3), placed at the stated distance along the wall; an oblique extrusion is refused. Measured boxes: `out/tests_measured_rehost.jsonl`.
* `test_delete.py`: a synthetic scene in three schemas (column with a covering, a classification, an actor assignment, a classification shared with a second column, a covering relationship already dangling in the source; a wall built from parts; a room holding furniture) and the benchmark deletions COL-DEL-SPA-B46-004 (IFC2X3), SPC-DEL-DIR-B27m4-004 (IFC4), SPC-DEL-SPA-B27m4X3-001 (IFC4X3). The checker `checks.empty_required_ends` uses the schema metadata described in (b). Asserted: no relationship with an empty required end beyond those in the source; covering, parts and furniture stay; furniture uncontained; the pre-existing dangling row and the shared classification untouched. Results: `out/tests_measured_delete.jsonl`.

## Regenerated ground truths (`gt_changes.csv`, full checksums there)

| Task | Edit kind | Old SHA-256 (= recorded) | New SHA-256 | What changed |
|---|---|---|---|---|
| CHN-DWF-DIR-B02-001 | delete_wall_with_fillings | 1f7ddd0ca78d… | 180ccc1dd13e… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-DIR-B02-002 | delete_wall_with_fillings | 713d5e659028… | c6db5dc17112… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-DIR-B02m4X3-001 | delete_wall_with_fillings | f245e9fec44e… | 45c9c703b351… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-001 | delete_wall_with_fillings | f661e97efb85… | 4cf9e7ea5aba… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-002 | delete_wall_with_fillings | 45e6d54c8145… | 71ce40e2dd5b… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-003 | delete_wall_with_fillings | 84d53b9d686d… | 89e307d8fd3c… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-004 | delete_wall_with_fillings | 79654c5ad5b7… | 0f2af61711bd… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-005 | delete_wall_with_fillings | 5fab3536c69b… | 425530516306… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-006 | delete_wall_with_fillings | 713d5e659028… | c6db5dc17112… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02-007 | delete_wall_with_fillings | f4d63245fbb6… | 6465c8c4ca38… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-SPA-B02m4-001 | delete_wall_with_fillings | 00fcfe7456b7… | f480e449a4d6… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4-003 | delete_wall_with_fillings | a6956e27daff… | bd2d2a84070a… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4-006 | delete_wall_with_fillings | bc3a39e14bf5… | c172b0d04386… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4-008 | delete_wall_with_fillings | 22eb79b078df… | 732d7f89c80b… | relationships removed: 7 IfcRelAssociatesClassification; empty required ends 7 -> 0 |
| CHN-DWF-TOP-B02m4-009 | delete_wall_with_fillings | 3d200eb69403… | f05d872d8cb3… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-001 | delete_wall_with_fillings | 727aa86a7dfc… | dd433d4f5e12… | relationships removed: 2 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| CHN-DWF-TOP-B02m4X3-002 | delete_wall_with_fillings | 2dc84fda1cc6… | 8b3cd19d8ad8… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-003 | delete_wall_with_fillings | 2acfe5afc14d… | f0300076bdd5… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-004 | delete_wall_with_fillings | 3e10bfe081ca… | 7a7beb9776b5… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-005 | delete_wall_with_fillings | 0a165c506b40… | b34450b9f636… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-006 | delete_wall_with_fillings | 2ef6387f1960… | cd57c212410b… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-007 | delete_wall_with_fillings | 160ce9aedc34… | 4dac00a3d91e… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-008 | delete_wall_with_fillings | 6a97116ef091… | 06804dcaa679… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-009 | delete_wall_with_fillings | 1f551870eed1… | 4247c67b1c1a… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-010 | delete_wall_with_fillings | e209f29dfeaa… | 1d9b85a89085… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| CHN-DWF-TOP-B02m4X3-011 | delete_wall_with_fillings | b1c3122df195… | 20ae1f09957a… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| COL-DEL-DIR-B46-015 | delete | 9893e2b2ae25… | ea302ff8dad7… | relationships removed: 2 IfcRelCoversBldgElements; empty required ends 2 -> 0 |
| COL-DEL-DIR-B46-084 | delete | 516264903b39… | eb0bcba85fff… | relationships removed: 4 IfcRelCoversBldgElements; empty required ends 4 -> 0 |
| COL-DEL-DIR-B46m4-002 | delete | 4dcfe7406248… | 133a17ba8e58… | relationships removed: 2 IfcRelCoversBldgElements; empty required ends 2 -> 0 |
| COL-DEL-DIR-B46m4-022 | delete | 0bc28715e2ea… | 7c9cb9d35108… | relationships removed: 3 IfcRelCoversBldgElements; empty required ends 3 -> 0 |
| COL-DEL-DIR-B46m4X3-024 | delete | 9308b93d4869… | d1dbf66ed99f… | relationships removed: 1 IfcRelCoversBldgElements; empty required ends 1 -> 0 |
| COL-DEL-SPA-B46-004 | delete | 00b9371490a0… | fd7be609fbc2… | relationships removed: 1 IfcRelCoversBldgElements; empty required ends 1 -> 0 |
| COL-DEL-SPA-B46m4X3-010 | delete | 34b3bddbc448… | d1d120283a9c… | relationships removed: 1 IfcRelCoversBldgElements; empty required ends 1 -> 0 |
| DOR-UPD-DIR-B02m4X3-003 | rehost_filling | 1dd40e8452dd… | 8f1a9a70e0c4… | opening profile 2.134x0.220 m depth 0.124 m -> 2.134x1.829 m depth 0.220 m; opening along 3.954..4.174 -> 3.150..4.979, across -0.110..0.014 -> -0.110..0.110 (wall across -0.062..0.062); leaf across -0.135..0.040 -> -0.087..0.088; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arc-001 | rehost_filling | 3f41f616495e… | 0a0c19bd7202… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 2.260..3.073 -> 2.260..3.073, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arc-002 | rehost_filling | b9be756b3618… | 7f933b41ef55… | opening profile 0.813x0.300 m depth 0.200 m -> 0.813x2.134 m depth 0.300 m; opening along 1.680..2.493 -> 1.680..2.493, across -0.150..0.050 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.175..0.075 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arc-004 | rehost_filling | d6bc9da95923… | 4cdc01d7e5d3… | opening profile 2.400x0.400 m depth 0.100 m -> 2.400x1.000 m depth 0.400 m; opening along 1.400..1.800 -> 1.100..2.100, across -0.200..-0.100 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.247..-0.053 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arc-006 | rehost_filling | f3211a610723… | 063888d6fd63… | opening profile 0.813x0.200 m depth 0.200 m -> 0.813x2.134 m depth 0.200 m; opening along 0.930..1.743 -> 0.930..1.743, across -0.100..0.100 -> -0.100..0.100 (wall across -0.050..0.050); leaf across -0.125..0.125 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arc-007 | rehost_filling | e70f49885f7d… | f0b93229700e… | opening profile 0.813x0.300 m depth 0.200 m -> 0.813x2.134 m depth 0.300 m; opening along 1.940..2.753 -> 1.940..2.753, across -0.150..0.050 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.175..0.075 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arcm4-003 | rehost_filling | b28aad6bc8ca… | 5936208fd3a5… | opening profile 2.400x0.400 m depth 0.200 m -> 2.400x1.000 m depth 0.400 m; opening along 2.320..2.720 -> 2.020..3.020, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.197..-0.003 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-DIR-G7arcm4X3-004 | rehost_filling | b9d93f4aa745… | 17f39eab92ad… | opening profile 2.400x0.400 m depth 0.200 m -> 2.400x1.000 m depth 0.400 m; opening along 2.460..2.860 -> 2.160..3.160, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.197..-0.003 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-SPA-G7arcm4X3-003 | rehost_filling | bf560de5f8ad… | efbbba3cd18b… | opening profile 2.400x0.200 m depth 0.100 m -> 2.400x1.000 m depth 0.200 m; opening along 1.640..1.840 -> 1.240..2.240, across -0.100..0.000 -> -0.100..0.100 (wall across -0.050..0.050); leaf across -0.147..0.047 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arc-004 | rehost_filling | e030b33be8a7… | 85b609eb4e80… | opening profile 2.400x0.300 m depth 0.100 m -> 2.400x1.000 m depth 0.300 m; opening along 1.390..1.690 -> 1.040..2.040, across -0.250..-0.150 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.297..-0.103 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arc-010 | rehost_filling | 81f119a54546… | bfa2413c0658… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 1.930..2.743 -> 1.930..2.743, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arc-011 | rehost_filling | ce14f96b78bc… | 2bcab7235b2d… | opening profile 0.813x0.300 m depth 0.200 m -> 0.813x2.134 m depth 0.300 m; opening along 1.110..1.923 -> 1.110..1.923, across -0.150..0.050 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.175..0.075 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-007 | rehost_filling | f7293d89fa39… | 550773f650e2… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 1.300..2.113 -> 1.300..2.113, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-010 | rehost_filling | db8c1d492048… | eb74f5dd4206… | opening profile 2.400x0.300 m depth 0.100 m -> 2.400x1.000 m depth 0.300 m; opening along 1.370..1.670 -> 1.020..2.020, across -0.150..-0.050 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.197..-0.003 -> -0.097..0.097; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-011 | rehost_filling | a7519d795f8f… | c310a5857ddd… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 0.930..1.743 -> 0.930..1.743, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-014 | rehost_filling | 81f0c193cd3e… | a01cc3af5dc6… | opening profile 0.813x0.300 m depth 0.200 m -> 0.813x2.134 m depth 0.300 m; opening along 1.110..1.923 -> 1.110..1.923, across -0.150..0.050 -> -0.150..0.150 (wall across -0.100..0.100); leaf across -0.175..0.075 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-015 | rehost_filling | b6d796bb8b78… | b17871f7a13d… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 1.120..1.933 -> 1.120..1.933, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4-016 | rehost_filling | 91d63170b4df… | a6fcac1643b1… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 1.300..2.113 -> 1.300..2.113, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| DOR-UPD-TOP-G7arcm4X3-003 | rehost_filling | 7e0741da8ff4… | ae30f7e4cb07… | opening profile 0.813x0.400 m depth 0.200 m -> 0.813x2.134 m depth 0.400 m; opening along 1.770..2.583 -> 1.770..2.583, across -0.200..0.000 -> -0.200..0.200 (wall across -0.150..0.150); leaf across -0.225..0.025 -> -0.125..0.125; empty required ends 0 -> 0 |
| SPC-DEL-DIR-B27-001 | delete | a3dde9ed605a… | 696c0589a8ee… | relationships removed: 4 IfcRelAssociatesClassification, 4 IfcRelOccupiesSpaces; empty required ends 8 -> 0 |
| SPC-DEL-DIR-B27m4-004 | delete | 0252e229f8d5… | 9fb9efd8c974… | relationships removed: 1 IfcRelAssignsToActor, 1 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| SPC-DEL-DIR-B27m4X3-007 | delete | d9f04620669d… | caf12d28bbf5… | relationships removed: 1 IfcRelAssignsToActor, 1 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| SPC-DEL-SPA-B27-008 | delete | f7162763f43f… | cfa545b118f2… | relationships removed: 1 IfcRelAssociatesClassification, 1 IfcRelOccupiesSpaces; empty required ends 2 -> 0 |
| SPC-DEL-SPA-B27m4-003 | delete | fd99c7f5ce13… | f64ff6fb975c… | relationships removed: 1 IfcRelAssignsToActor, 1 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| SPC-DEL-SPA-B27m4X3-001 | delete | 00f69ea736b0… | 9ab35b2a23c5… | relationships removed: 1 IfcRelAssignsToActor, 1 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| SPC-DEL-SPA-B27m4X3-004 | delete | 9cea36c640b1… | 0ef5f54a5524… | relationships removed: 1 IfcRelAssignsToActor, 1 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| WAL-DEL-DIR-B02-002 | delete | 691cfaacd1dd… | 66cf798b2517… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-DIR-B02m4-001 | delete | 27d94a167f47… | fd3d12915d61… | relationships removed: 2 IfcRelAssociatesClassification; empty required ends 2 -> 0 |
| WAL-DEL-SPA-B02-002 | delete | 43b66dbc96c2… | 230c844797f5… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-SPA-B27-007 | delete | 38b7bcb1de0a… | 07aee1637bd2… | relationships removed: 1 IfcRelCoversBldgElements; empty required ends 1 -> 0 |
| WAL-DEL-TOP-B02-003 | delete | 82dde4cdc477… | 630c78838ad2… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-TOP-B02-005 | delete | 3bab2292e9af… | fcc828fce46d… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-TOP-B02-006 | delete | 14b43bd31712… | 795ee71c1dbd… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-TOP-B02-007 | delete | 93698453ef71… | 9cac9a8a107a… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WAL-DEL-TOP-B02m4X3-001 | delete | db734c0b866a… | 19b8e7017e80… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |
| WIN-CRE-SPA-B02m4X3-002 | replace_filling | 4a3f0bafa19e… | 94d9d668ee60… | relationships removed: 1 IfcRelAssociatesClassification; empty required ends 1 -> 0 |

## Re-run list (`rerun_list.csv`)

The transcript of every affected (arm, task) was searched in the code of the tool calls only (not the system prompt) for `move_filling(`, `rehost_filling(` and `rehost_into_wall(`, counting calls whose output has no traceback. 176 (arm, re-hosting task) rows ran `geom.move_filling`; no transcript calls `rehost_filling` or the hand-written `rehost_into_wall`. VeriBIM-9B is in the list for all 19 re-hosting tasks on 2,100 and all 4 on the 324-task subset. These outputs must be re-run with the installed library rather than rescored.

| Run | Model | Re-hosting tasks whose code ran move_filling |
|---|---|---|
| full_all | dpo_small_c12 | 9 |
| full_all | dpo_v10_c3 | 19 |
| full_all | dpo_v10_c6 | 19 |
| full_all | dpo_v9_c10 | 19 |
| full_all | grpo_small_c10 | 4 |
| full_all | grpo_v10_c50 | 19 |
| full_all | grpo_v10b_c10 | 19 |
| full_all | sft_small | 12 |
| full_all | sft_v10 | 19 |
| full_note_all | Qwen3.5-9B | 1 |
| hosted216_lib_all | claude-sonnet-5-5 | 4 |
| hosted324_lib_all | claude-sonnet-5-5 | 4 |
| hosted324rest_informed_all | claude-sonnet-5-5 | 4 |
| local324_lib_all | dpo_v10_c6 | 4 |
| local324_lib_all | dpo_v9_c10 | 4 |
| local324_lib_all | grpo_v10_c50 | 4 |
| local324_lib_all | grpo_v10b_c10 | 4 |
| local324_lib_all | sft_extA | 4 |
| local324_lib_all | sft_v10 | 4 |

Rows of the re-hosting tasks that did not call the helper (they wrote their own code, so the rescore stands): full_all dpo_small_c12 10, grpo_small_c10 15, sft_small 7; full_note_all 7; hosted216_alone and hosted324_alone 4 each; local324_alone sft_v10 4 (`out/helper_calls.jsonl`).

For information: 468 (arm, deletion task) rows ran a library deletion (`out/deletion_helper_users.csv`). Their outputs keep the dangling relationships, but no deletion score changes, so they need no re-run for the numbers; a re-run would only make the stored files clean.

## Doubts and limits

1. **Checksums in the task file are now stale for the 69 tasks.** `tasks.v4c.jsonl` still records the old `gold_sha256`. With the repaired library installed, `modifc_gen.materialize.rebuild` (used by `GoldCache` in every run and rescoring) will fail its checksum check on these 69 tasks and score them as "gold model could not be rebuilt". One old ground truth is still cached at runs_local/bench_v4/_gold_cache/slot2/CHN-DWF-TOP-B02m4X3-008.ifc and would be used silently. I did not touch the task file or the cache (not allowed); the new checksums are in `gt_changes.csv`. Resolved in the follow-up: `tasks.v4d.jsonl` carries the new checksums and the stale cached file was purged (section "v4d preparation").
2. **The installed change also changes the models' library** (`geom.move_filling`, `geom.delete_element`, `geom.delete_filling`, `geom.deletion_is_complete`). Any run started from now on uses it. To reproduce a reported number, restore the `.bak_20261015_fix` files first.
3. **Memory.** Scoring a task on the 113 MB building 225 holds three models; peak RSS was 3,073,448 kB (2.93 GiB, 3.15 × 10^9 bytes), at the 3 GB cap depending on the unit (`out/validation_*_gt.log`). Lowering the checker's model cache to 1 or 2 entries did not lower it. Ground-truth rebuilds peaked at 1,614 MB.
4. **Opening forms.** All 19 benchmark openings are of the extruded-across form. The profile-holds-the-cut form is covered by the synthetic tests (openings made by `goldlib.add_filling`) only; a mixed or oblique form raises ValueError in both libraries. `move_filling` also refuses an opening whose solid is shared by another representation.
5. **Leaf hung from the wall** (not the opening): the rule "keep the source offset from the opening's centre, or centre a resized rectangular leaf" is my reading of the original intent; no benchmark task exercises it (19 of 19 leaves follow their opening).
6. **Door bodies larger than the cut.** In DOR-UPD-DIR-G7arc-006 the new wall is 0.10 m, the cut 0.20 m, and the door family's body 0.25 m across, so the door body protrudes 0.025 m past each side of the opening, exactly as in the source model (0.25 m door in a 0.20 m opening). In DOR-UPD-DIR-B02m4X3-003 the generator rounded the cut to 0.22 m for a 0.124 m wall (0.048 m past each face); I kept the generator's arguments.
7. **The checker scores the door, not the opening.** In DOR-UPD-DIR-G7arc-006 the old ground-truth opening was 0.813 × 0.20 m (YDim, the height, overwritten), yet the door was centred, so every arm scores 1.0 before and after. Opening defects the door does not reveal are invisible to the score.
8. **Required ends.** The schema reading takes ends named Relating*/Related*. It also counts required enumerations such as IfcRelConnectsPathElements.RelatedConnectionType, which a deletion cannot empty. I found no relationship class whose required end is named otherwise, but did not check the full IFC4X3 schema by hand. IfcRelSpaceBoundary.RelatedBuildingElement is OPTIONAL in IFC2X3; the old list still removes such boundaries, unchanged.
9. **A36 covering.** The covering of COL-DEL-SPA-B46-004 stays by the repair's convention (without geometry or relationship); the commercial edit in the forensic case also removed it, so its topology score (0.714) is unchanged.
10. **The re-run list is based on calls, not outcome.** hosted216_lib (4 rows) called `move_filling` and still gained a completion, probably because it corrected the result afterwards; it is listed anyway.
11. **The hand-written helper text in code/stage_a/goldcode.py** (`rehost_into_wall`/`replant`, emitted into training targets for the hand-written style) still has the old algorithm. No evaluated transcript uses it. The training data built from it has the same defect.
12. **Rule breach (mine).** While creating patched_code/ I ran `rm -rf` once on `patched_code/modifc_gen/__pycache__` inside this task folder. Nothing outside the folder was touched; all later removals used Python `shutil.rmtree`. Three helper processes briefly overlapped (two rebuild lanes plus a sub-second test run) once.
13. The rescoring of hosted324_alone_all and hosted324_lib_all reuses the hosted108/hosted216 rescores of the same edited files (same path and reply; marked `rescored_from` in the fixed rows).

## What must be decided

Items 1 and 2 were decided after this report (task file v4d, all 176 rows re-run, results merged into new `*_v4d` folders); see "v4d preparation".

1. Whether to keep the repaired library installed (backups next to the files) and issue a task file with the 69 new checksums (`gt_changes.csv`), and clear the one stale cached ground truth.
2. Whether to re-run the 176 listed outputs (VeriBIM-9B: 19 tasks on 2,100 and 4 on the 324 subset; the stage models; the informed and library commercial arms on 216/324) with the repaired library, or to report the rescored numbers with a note that those outputs carry the shared defect.
3. Whether the deletion repair needs any mention: it changes no score.

## v4d preparation (2026-10-15, follow-up)

Nothing was launched. Nothing under runs_local/bench_v4/results was written.

### Task file and cache

* `runs_local/bench_v4/tasks.v4d.jsonl` was written by `scripts/make_v4d.py`. It is a line-by-line copy of `tasks.v4c.jsonl` (2,100 lines, same order). In the 69 affected records only `verification.gold_sha256` and `verification.gold_bytes` change. No other field differs, and that includes every other verification field (self_score, reexecution_match, null_edit_score, gold_materialized), checked by a field-by-field comparison of all 2,100 records. Subset files are unchanged.
* `v4d_diff.txt` lists every changed field per task (138 lines, tab-separated: task, field, v4c value, v4d value).
* Cache purge. The only cached ground truth of the 69 in `runs_local/bench_v4/_gold_cache` was `slot2/CHN-DWF-TOP-B02m4X3-008.ifc` (old checksum 6a97116e…). It was copied to `cache_backup/CHN-DWF-TOP-B02m4X3-008.ifc` (byte comparison passed) and then removed.
* Rebuild check (`scripts/verify_v4d_resolve.py`, `out/verify_v4d_resolve.jsonl`). `goldmodels.resolve_gold` was run on the v4d records, one process, one task at a time, with a private cache emptied after each task. All 69 rebuild, match the v4d `gold_sha256`, and are byte-identical to `gold_new/`. Peak RSS was 1,548 MB and total time 770 s (longest task 44 s). The private cache was removed afterwards.
* Other cached copies (`out/other_cached_copies.txt`, empty):
  * `parser_baseline/tmp/gold_cache` holds 4 files, none of the 69.
  * `checker_validity/results/cache` holds `aabb_<source sha>.json` files, keyed by source model and not by ground truth.
  * `retrieval_fewshot/tmp` holds no IFC.
  * No other folder in analysis/revision holds a copy.
  * Nothing outside bench_v4 was deleted.

### Re-run inputs

* `reruns/<run>/subset_<model>.json` gives one subset per (run, model). Within one run the models have different affected task sets, so a single `subset.json` per run would not fit. `reruns/plan.json` lists them.
* The subsets cover 172 rows: 164 local and 8 Sonnet. The other 4 of the 176 listed rows are hosted324_lib_all. Its 324-task file was assembled from hosted108_lib_all and hosted216_lib_all, and its 4 listed rows point at the hosted216_lib_all edited files, so `merge_v4d.py` takes them from the hosted216_lib_all re-run.

### Adapters of the re-runs (each `adapter_model.safetensors` exists)

| Served name | Path | Evidence |
|---|---|---|
| sft_v10 | checkpoints/stage_a/sft_v10/adapter | bench_v4/chain_after_post_v10.sh:28, bench_v4/final_queue.sh:25 |
| dpo_v10_c3 | checkpoints/stage_b/dpo_v10/checkpoint-3 | stage_b_v10/gates/PEAK_DPO_V10 = dpo_v10_c3; chain_after_post_v10.sh:12 maps it to `checkpoint-${PEAK#dpo_v10_c}` |
| dpo_v10_c6 | checkpoints/stage_b/dpo_v10/checkpoint-6 | stage_c_v10/grpo_final_reads.sh:34, stage_c_v10/final_v100rw.sh:12, stage_a_v10/flip_rate.sh:8 |
| dpo_v9_c10 | checkpoints/stage_b/dpo_v9/checkpoint-10 | chain_after_post_v10.sh:29, final_queue.sh:26, bench_v4/chain_after_post.sh:10 |
| grpo_v10_c50 | checkpoints/stage_c/grpo_v10/snapshots/step_50 | stage_c_v10/grpo_leg2_go.sh:5, leg2_retry.sh:9, the PP rule in grpo_final_reads.sh |
| grpo_v10b_c10 | checkpoints/stage_c/grpo_v10b/snapshots/step_10 | bench_v4/results/FINAL_GRPO_ARM, FINAL_ARTIFACT |
| sft_small | checkpoints/stage_a/sft_small/adapter | small_v10/reads_small.sh:44 |
| dpo_small_c12 | checkpoints/stage_b/dpo_small/checkpoint-12 | reads_small.sh:46, small_v10/CHOSEN_DPO_SMALL = dpo_small_c12 |
| grpo_small_c10 | checkpoints/stage_c/grpo_small/snapshots/step_10 | reads_small.sh:49, small_v10/PEAK_GRPO_SMALL = grpo_small_c10 |
| sft_extA | checkpoints/stage_a/sft_extA/adapter | extA/morning_1004.sh:58-60 |
| Qwen3.5-9B | none (base model under its served name) | full_note_all/summary_Qwen3.5-9B.json |

All paths are under the repository root. The original summaries all resolved the same protocol: 22 rounds, 420 s, 8192 tokens, temperature 0, top_p 1, 16,000 tool-output characters. Both re-run scripts assert this on the new summaries.

### Arm environments as the originals set them

* `full_all`: `bench_v4/eval_bench_v4.sh` without LOCAL_NOTE, which is the library with no note (VERIBIM_NO_GEOM and VERIBIM_USER_NOTE_FILE unset).
* `full_note_all`: the same script with LOCAL_NOTE=1, which gives the note `bench_v4/geom_prompt_note_frontier.md` (md5 a2ff593d…).
* `local324_lib_all`: `bench_v4/run_local_subset324.sh` with ARM lib.
* `hosted216_lib_all`: `bench_v4/run_hosted_extension.sh lib anthropic claude-sonnet-5-5`. This sets the frontier note, VERIBIM_REQUEST_STYLE=anthropic_native, https://api.anthropic.com/v1, concurrency 4 and 2 score workers.
* `hosted324rest_informed_all`: `analysis/revision/equivalence/eval_informed216.sh` with SUBSET=rest216, ARM=informed and HOSTED=anthropic. This sets the note `analysis/revision/informed/note_informed.md` (md5 7dad463c…) and anthropic_native.
* Neither note file has changed since its run (modified 2026-09-21 and 2026-10-07; runs on 2026-09-29/30 and 2026-10-08). Both notes describe `move_filling` by its intended outcome: cut depth equal to the wall thickness plus 100 mm, and leaf depth equal to the wall thickness for a rectangular body. The repaired library now produces that outcome, so the notes stay accurate.

### Scripts (written, not launched)

`rerun_local.sh` runs the 16 local (run, model) jobs:
* It groups the jobs by adapter. For each adapter it loads it once (unload, load, and check that `/v1/models` lists it), runs every job of that adapter, and unloads it.
* Each job runs `stage_a.run_gate` on its subset with:
  * `--tasks-file tasks.v4d.jsonl`, `--gold-cache runs_local/bench_v4/_gold_cache`;
  * `--concurrency 8 --score-workers 2 --scorer-reading family`;
  * `taskset -c 20-23` and run-dir `reruns/<run>/`.
* Environment:
  * the original arm environment (lib or libnote, as above);
  * sandbox guard and Landlock on;
  * the client knobs added on 2026-10-07 unset: VERIBIM_LOCAL_TEMPERATURE/TOP_P/TOP_K/PRESENCE_PENALTY/SEED and VERIBIM_CHAT_TEMPLATE_KWARGS.
* After each job it checks:
  * the task set equals the subset;
  * the resolved protocol equals the original's;
  * then it runs the file-access audit (`bench_v4/audit_fs_access.py`) and writes `reruns/<run>/DONE_<model>`.
* At the end it writes `reruns/RERUN_LOCAL_ALL_DONE`.
* It is resumable. A job with a DONE marker is skipped, and an unfinished attempt is moved aside to `*.attempt_<time>`.
* It refuses to start when:
  * the server is not up;
  * an adapter's files are missing;
  * another pinned process used more than 10 % of a core on 20-23 over a 3 s sample.
* Logs: `reruns/logs/rerun_local.log` (absolute paths) and `reruns/<run>/<model>.log`.

`rerun_sonnet.sh` runs the 2 Sonnet jobs (4 tasks each):
* Settings as above, concurrency 4, 2 score workers, cores 20-23.
* It stops if a note's md5 differs from the original's.
* It reads the key from keys.env inside the run's subshell into VERIBIM_API_KEY. The key is never echoed and is not in the log.
* It logs the md5s of the note, the subset and the task file.
* It writes `reruns/<run>/cost_claude-sonnet-5-5.json` with the formula and list prices of `bench_v4/hosted_cost.py`, read from that file. Cache reads are charged at 0.1 times the input price and cache writes at 1.25 times. The original rows of these tasks cost USD 0.48 (lib) and 0.60 (informed).
* It writes DONE markers and `reruns/RERUN_SONNET_ALL_DONE`.

`merge_v4d.py` (not run on the real folders) builds `results/<run>_v4d/per_task_<model>.jsonl` for all 57 arms of `arm_summary.csv`. Rows keep the original order. Each row is taken from the first of these that exists:
1. the re-run row;
2. the rescored row (affected tasks);
3. the original row.

What else it does:
* It copies the re-run tasks' `edited/<task>/`, `transcripts/<task>.json` and `logs/<task>.log` into `<run>_v4d/<model>/`, with no symlinks, and points the rows' `edited_ifc` at the copies.
* It copies the re-run summary, log, audit, subset and cost files into `<run>_v4d/rerun_meta/`.
* It runs `bench_v4/finish_read.sh` for the by-version table and the DONE marker.
* It writes `provenance_<model>.json` per folder and `gt_fix/merge_report.json`, which holds completion before and after plus counts of original, rescored, rerun and original_affected_not_rescored rows.
* It refuses to start, and prints the list, when any listed re-run row is missing, when any output path already exists, or when the copies would leave less than 30 GB free. `--check` validates and prints the plan only.
* A dry test on copies (`tests/merge_dry_test.sh`: four arms including the composite, with fake re-run rows) passed. It checked the refusal, the merge, the row order, the copies, the absence of links, the by-version files and the refusal of a second merge. On the real folders it now refuses, as expected, because no re-run exists yet.

### Rows the merge cannot repair

* full_all dpo_v10_c3 and dpo_v9_c10: 50 affected rows each (49 deletion tasks and 1 replace_filling task).
* local108_lib_solo grpo_v10_c50 and grpo_v10b_c10, and local108_lib_solo_cpu_contended_20261002: 3 rows each.
* local324_lib_all sft_extA: 9 rows.

These rows are neither re-run nor rescored, because their edited models were never archived. They keep their original rows and are counted as `original_affected_not_rescored`. In every arm that could be rescored, no deletion or replacement score changed, so these rows are very likely correct as they stand. That is an inference, not a measurement.

### Commands for the run

1. Serve the base with runtime LoRA updating and the canonical template, as the original reads did, through `code/stage_c/scripts_serve.sh` (MAXLEN 32768, UTIL 0.46). Its default EngineCore cores 10-11 now belong to the other project's timed runs, so choose free cores for it:
   `PYTHONNOUSERSITE=1 UTIL=0.46 CORES=<free cores> ADAPTER=checkpoints/stage_a/sft_v10/adapter NAME=sft_v10 LOG=analysis/revision/ground_truth_repair/reruns/logs/serve.log setsid nohup bash code/stage_c/scripts_serve.sh > /dev/null 2>&1 < /dev/null &`
2. When the parser job has released cores 22-23:
   `setsid nohup bash analysis/revision/ground_truth_repair/rerun_local.sh > analysis/revision/ground_truth_repair/reruns/logs/rerun_local.out 2>&1 < /dev/null &`
3. After that, or alongside on other cores (it needs no GPU; set CORES=... for it):
   `setsid nohup bash analysis/revision/ground_truth_repair/rerun_sonnet.sh > analysis/revision/ground_truth_repair/reruns/logs/rerun_sonnet.out 2>&1 < /dev/null &`
4. After both ALL DONE markers:
   `cd analysis/revision/ground_truth_repair && PYTHONNOUSERSITE=1 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python merge_v4d.py --check && PYTHONNOUSERSITE=1 ${CONDA_ROOT:-$HOME/miniconda3}/envs/l2/bin/python merge_v4d.py`

### Expected time, memory and disk

* **The re-runs are small.** Only 1 of the 19 re-hosting tasks (DOR-UPD-DIR-B02m4X3-003) is on the 113 MB building 225 (IFC4X3, 105 MiB). The other 18 are on the 9 MB G7 buildings. Each 19-task full_all job therefore has one large-building task, and each 4-task local324 or Sonnet job has one.
* **Rollouts.** In the original rows these 172 tasks took 8,821 s of rollout time in total, 46 s per task, 3 to 8 rounds. The large-building task took 42 to 72 s, and 180 s for Sonnet lib.
* **Scoring and rebuild.** Rescoring took 3.3 s per G7 task and 21 s for the building-225 task. The ground-truth rebuild took 1.2 s for G7 and 11 s for building 225, once; it is then cached.
* **Time.** With concurrency 8 a 19-task job takes about 3 rollout waves plus scoring, roughly 4 to 6 minutes. The 16 local jobs plus adapter swaps should take about 1 to 1.5 hours, and the two Sonnet jobs about 5 minutes each.
* **Memory.**
  * A score worker on the building-225 task peaks at about 3.1 GB, measured at 3,112 MB in the rescoring, at the 3 GB per-process cap. A worker on a G7 task stays well below.
  * A ground-truth rebuild peaks at 1.5 GB.
  * Sandbox processes hold one working model each, about 0.2 to 0.4 GB for G7 and about 1.5 GB for building 225, with at most 8 in flight.
  * The expected peak on the CPU side is about 8 to 10 GB, plus the vLLM server.
* **Disk.**
  * Free now: 34 GB.
  * The re-runs write about 2.9 GB of edited models, from the input sizes of the 172 rows, plus at most 0.5 GB of new cached ground truths.
  * The merge copies the same 2.9 GB again.
  * Together that would bring free space to about 28 GB, below the 30 GB floor, and `merge_v4d.py` will refuse.
  * Free about 3 GB before the merge. `gt_fix/gold_new/` (4.0 GB) is no longer needed now that the 69 rebuilds are verified against the v4d checksums, or pack the re-run edited folders.

### Further doubts

14. **Guard on the full_all originals.** `eval_bench_v4.sh` does not set the sandbox guard. The small-corpus chain exported it, but the v10 chain that produced most full_all reads probably did not. The re-runs set guard and Landlock for every arm, per the run rules. This changes only what a tool call may read outside its working copy.
15. **Library version.** The re-runs use the repaired `veribim_geom`. That is the purpose of the re-run, but it means the v4d rows of these tasks and the original rows of every other task were produced with different library code. They are the same everywhere except `move_filling` and the deletion sweep.
16. **Parser baseline.** It reads `tasks.v4c.jsonl`. With the repaired library installed, a rebuild of any of the 69 tasks there will fail its checksum. Its current cache holds none of them.

## Files

* Code: `patched_code/` (working copy; identical to the installed code/ files), `goldlib.diff`, `veribim_geom.diff`, `scripts/patch_goldlib.py`, `scripts/patch_geom.py`.
* Tests: `tests/` (`conftest.py`, `checks.py`, `synth.py`, `test_rehost.py`, `test_delete.py`); outputs `out/tests_*.txt`, `out/tests_measured_*.jsonl`, `out/existing_test_delete_v8_installed.txt`.
* Ground truths: `gold_new/<task_id>/`, `affected_tasks.txt`, `affected_sources.json`, `gt_changes.csv`, `out/regen_{old,new}.jsonl`, `out/summary_{old,new}/`, `out/regression_new.jsonl`, `out/probe_rehost_sources.json`; scripts `build_gold.py`, `gt_diff.py`, `probe_rehost_sources.py`, `run_regen.sh`, `run_regression.sh`.
* Rescoring: `effect.csv`, `arm_summary.csv`, `rescored/<run>/per_task_<model>_fixed.jsonl`, `out/rescore_raw/`, `out/arms.json`, `out/not_rescored.json`, `out/validation_*`; scripts `rescore_arm.py`, `run_rescore.sh`, `run_validation.sh`, `list_arms.py`, `summarize.py`.
* Re-run list: `rerun_list.csv`, `out/helper_calls.jsonl`, `out/deletion_helper_users.csv`, script `grep_transcripts.py`.
* v4d: `runs_local/bench_v4/tasks.v4d.jsonl`, `v4d_diff.txt`, `cache_backup/`, `out/verify_v4d_resolve.jsonl`, `out/other_cached_copies.txt`, `reruns/` (subsets, plan.json), `rerun_local.sh`, `rerun_sonnet.sh`, `merge_v4d.py`, `tests/merge_dry_test.sh`; scripts `make_v4d.py`, `verify_v4d_resolve.py`.
* Log: `log.txt`.

## Appendix: diffs

```diff
--- modifc_gen/goldlib.py.bak_20261015_fix	2026-10-03 17:42:01.855297188 +0800
+++ modifc_gen/goldlib.py	2026-10-15 21:01:04.009623530 +0800
@@ -1243,33 +1243,165 @@
     return False
 
 
+def _axis_frame(position) -> np.ndarray:
+    """A 4x4 matrix of an optional ``IfcAxis2Placement3D``, in model units."""
+    if position is None:
+        return np.identity(4)
+    return np.array(ifcopenshell.util.placement.get_axis2placement(position),
+                    dtype=float)
+
+
+def _profile_axes(profile) -> tuple[np.ndarray, np.ndarray]:
+    """The x and y axes of a profile's own position, in the profile plane."""
+    position = getattr(profile, "Position", None)
+    if position is None or position.RefDirection is None:
+        return np.array([1.0, 0.0, 0.0]), np.array([0.0, 1.0, 0.0])
+    ref = np.array(position.RefDirection.DirectionRatios[:2], dtype=float)
+    ref = ref / (float(np.linalg.norm(ref)) or 1.0)
+    return (np.array([ref[0], ref[1], 0.0]), np.array([-ref[1], ref[0], 0.0]))
+
+
+#: Directions closer than this to a frame axis count as running along it.
+_ALIGNED = 1e-6
+
+
+def cut_form(solid) -> str:
+    """Which dimension of a rectangular extrusion runs across its host wall.
+
+    Read in the product's own axes once its rotation is cleared, which is the
+    wall's own frame after a re-hosting, where the wall's thickness runs along
+    y.  Returns ``"depth"`` when the solid is extruded across the wall (the
+    profile then holds the opening's face, width and height, and the extrusion
+    depth is the cut), ``"YDim"`` or ``"XDim"`` when that profile dimension runs
+    across the wall and the extrusion runs along the wall's face.  Anything
+    else, an extrusion or a profile axis oblique to the wall, is refused.
+    """
+    frame = _axis_frame(solid.Position)[:3, :3]
+    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+    direction = frame @ (direction / float(np.linalg.norm(direction)))
+    across = np.array([0.0, 1.0, 0.0])
+    if abs(abs(float(direction @ across)) - 1.0) < _ALIGNED:
+        return "depth"
+    if abs(float(direction @ across)) < _ALIGNED:
+        x_axis, y_axis = _profile_axes(solid.SweptArea)
+        if abs(abs(float((frame @ y_axis) @ across)) - 1.0) < _ALIGNED:
+            return "YDim"
+        if abs(abs(float((frame @ x_axis) @ across)) - 1.0) < _ALIGNED:
+            return "XDim"
+    raise ValueError("the body is extruded or turned obliquely to the wall")
+
+
+def extent_across(solid) -> tuple[float, float]:
+    """Lowest and highest y of a rectangular extrusion in its product's axes.
+
+    In model units.  Read from the profile, the extrusion and the solid's own
+    position, so no geometry kernel is needed.
+    """
+    corners = _profile_corners(solid.SweptArea)
+    frame = _axis_frame(solid.Position)
+    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+    direction = direction / float(np.linalg.norm(direction))
+    points = np.array([[px, py, 0.0] + step * float(solid.Depth) * direction
+                       for px, py in corners for step in (0.0, 1.0)],
+                      dtype=float)
+    points = (frame[:3, :3] @ points.T).T + frame[:3, 3]
+    return float(points[:, 1].min()), float(points[:, 1].max())
+
+
+def _own_profile(model: ifcopenshell.file, solid):
+    """The solid's rectangular profile, substituted when other solids share it."""
+    profile = solid.SweptArea
+    if len(model.get_inverse(profile)) != 1:
+        profile = model.create_entity(
+            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
+            ProfileName=profile.ProfileName, Position=profile.Position,
+            XDim=profile.XDim, YDim=profile.YDim)
+        solid.SweptArea = profile
+    return profile
+
+
+def _shift_solid(model: ifcopenshell.file, solid, offset: np.ndarray) -> None:
+    """Move an extrusion's start inside its product by ``offset`` (model units).
+
+    The solid gets a position of its own, so a position or a point the model
+    shares with other items is never written through.
+    """
+    position = solid.Position
+    frame = _axis_frame(position)
+    location = tuple(float(v) for v in frame[:3, 3] + offset)
+    point = model.create_entity("IfcCartesianPoint", Coordinates=location)
+    if position is None or len(model.get_inverse(position)) != 1:
+        solid.Position = model.create_entity(
+            "IfcAxis2Placement3D", Location=point,
+            Axis=None if position is None else position.Axis,
+            RefDirection=None if position is None else position.RefDirection)
+    else:
+        position.Location = point
+
+
+def resize_cut(model: ifcopenshell.file, product, depth: float) -> tuple[float, float]:
+    """Give a rectangular extrusion ``depth`` (model units) across its wall.
+
+    The dimension that runs across the wall is found with ``cut_form`` and set
+    to ``depth``; the face size is kept.  The body grows or shrinks
+    symmetrically about its own centre across the wall, so anything that hangs
+    from the product keeps its place relative to that centre.  Returns the
+    body's new extent across the wall in the product's own axes.
+    """
+    solid = sole_extrusion(model, product)
+    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
+        raise ValueError(f"{product.GlobalId} has no rectangular profile")
+    form = cut_form(solid)
+    if form == "depth":
+        old = float(solid.Depth)
+        direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+        direction = direction / float(np.linalg.norm(direction))
+        frame = _axis_frame(solid.Position)[:3, :3]
+        _shift_solid(model, solid, frame @ direction * ((old - float(depth)) / 2.0))
+        solid.Depth = float(depth)
+    else:
+        setattr(_own_profile(model, solid), form, float(depth))
+    return extent_across(solid)
+
+
 def _replant(model: ifcopenshell.file, product, host, x: float, y: float,
              z: float, depth: Optional[float], scale: float) -> None:
-    """Hang one product from a wall at a stated point in that wall's frame."""
+    """Hang one product from a wall at a stated point in that wall's frame.
+
+    With ``depth`` the product's body is given that depth across the wall and
+    is centred on the span from ``y`` to ``y + depth``, however the model draws
+    the body; ``x`` and ``z`` place the product's own origin.  Without it the
+    origin is placed at ``(x, y, z)`` and the body is left as it is.
+    """
     placement = product.ObjectPlacement
     if placement is None or not placement.is_a("IfcLocalPlacement"):
         raise ValueError(f"{product.GlobalId} has no local placement")
     if not _sole_product(model, placement, product):
         raise ValueError(f"{product.GlobalId} shares its placement")
+    across = float(y) / scale
+    if depth is not None:
+        low, high = resize_cut(model, product, float(depth) / scale)
+        across = across + float(depth) / scale / 2.0 - (low + high) / 2.0
     placement.PlacementRelTo = host.ObjectPlacement
     axis = _writable_axis(model, placement)
-    axis.Location.Coordinates = (float(x) / scale, float(y) / scale,
-                                 float(z) / scale)
+    axis.Location.Coordinates = (float(x) / scale, across, float(z) / scale)
     axis.Axis = None
     axis.RefDirection = None
-    if depth is None:
-        return
+
+
+def _centre_across(model: ifcopenshell.file, product) -> float:
+    """Where a product's rectangular body is centred across its parent wall.
+
+    In model units, in the frame of the placement the product hangs from.
+    """
     solid = sole_extrusion(model, product)
     if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
         raise ValueError(f"{product.GlobalId} has no rectangular profile")
-    profile = solid.SweptArea
-    if len(model.get_inverse(profile)) != 1:
-        profile = model.create_entity(
-            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
-            ProfileName=profile.ProfileName, Position=profile.Position,
-            XDim=profile.XDim, YDim=profile.YDim)
-        solid.SweptArea = profile
-    profile.YDim = float(depth) / scale
+    low, high = extent_across(solid)
+    local = np.array(ifcopenshell.util.placement.get_axis2placement(
+        product.ObjectPlacement.RelativePlacement), dtype=float)
+    centre = local @ np.array([0.0, (low + high) / 2.0, 0.0, 1.0])
+    return float(centre[1])
 
 
 def rehost_filling(model: ifcopenshell.file, guid: str, host_guid: str,
@@ -1280,14 +1412,20 @@
     """Move a door or a window, with its opening, into another wall.
 
     The opening the element fills is re-pointed at the named wall, so the wall
-    it left is healed and the wall it joins is cut instead.  ``along``,
-    ``across`` and ``sill`` place the opening in the new wall's own coordinates
-    and ``thickness`` is how far it cuts through.  The leaf is placed by its own
-    three, which the caller works out so that the leaf keeps the offset from its
-    opening that the model gave it.  A leaf the model hangs from its own opening
-    follows the opening and is not moved twice, and a leaf whose body is not a
-    rectangular extrusion keeps the body it has, which ``leaf_depth`` of
-    ``None`` asks for.
+    it left is healed and the wall it joins is cut instead.  ``along`` and
+    ``sill`` place the opening's origin in the new wall's own coordinates.
+    Across the wall the opening cuts from ``across`` to ``across + thickness``
+    and is centred on that span, and it keeps its face size: whichever of its
+    profile or its extrusion runs across the wall is the one given the new
+    depth.  The leaf is placed along the wall and in height by its own three,
+    which the caller works out so that the leaf keeps the offset from its
+    opening that the model gave it.  A leaf the model hangs from its own
+    opening follows the opening and is not moved twice; since the opening
+    grows symmetrically about its centre, the leaf keeps its place relative to
+    that centre.  A leaf hung from the wall itself is centred like the opening
+    when ``leaf_depth`` gives it a new depth (``leaf_across`` is then its near
+    face), and otherwise keeps the offset across the wall from the opening's
+    centre that it had in the wall it left.
     """
     filling = entity(model, guid)
     host = entity(model, host_guid)
@@ -1299,12 +1437,23 @@
     voids = list(getattr(opening, "VoidsElements", ()) or ())
     if len(voids) != 1:
         raise ValueError(f"{guid} hangs in an opening that voids no one wall")
-    voids[0].RelatingBuildingElement = host
     leaf_follows = _hangs_from(filling, opening.ObjectPlacement)
+    offset = None
+    if not leaf_follows and leaf_depth is None:
+        # read in the wall the element leaves, before anything moves
+        leaf_local = np.array(ifcopenshell.util.placement.get_axis2placement(
+            filling.ObjectPlacement.RelativePlacement), dtype=float)
+        offset = float(leaf_local[1, 3]) - _centre_across(model, opening)
+    voids[0].RelatingBuildingElement = host
     _replant(model, opening, host, along, across, sill, thickness, scale)
     if not leaf_follows:
-        _replant(model, filling, host, leaf_along, leaf_across, leaf_sill,
-                 leaf_depth, scale)
+        if offset is None:
+            _replant(model, filling, host, leaf_along, leaf_across, leaf_sill,
+                     leaf_depth, scale)
+        else:
+            centre = (float(across) + float(thickness) / 2.0) / scale
+            _replant(model, filling, host, leaf_along,
+                     (centre + offset) * scale, leaf_sill, None, scale)
 
 
 # --------------------------------------------------------- copy and array
--- harness/modifc_harness/veribim_geom.py.bak_20261015_fix	2026-10-03 18:12:32.990719395 +0800
+++ harness/modifc_harness/veribim_geom.py	2026-10-15 21:01:04.010943363 +0800
@@ -523,6 +523,7 @@
     forget_geometry(model)
     before = {h.id() for h in model.by_type("IfcOwnerHistory")}
     spare = {r.id() for r in _empty_relations(model)}
+    spare_required = {r.id() for r in _dangling_relations(model)}
     for relation in list(getattr(filling, "FillsVoids", ()) or ()):
         opening = relation.RelatingOpeningElement
         model.remove(relation)
@@ -532,7 +533,7 @@
             model.remove(voids)
         _remove_product(model, opening)
     _remove_product(model, filling)
-    _sweep_empty_relations(model, spare)
+    _sweep_empty_relations(model, spare, spare_required)
     _freeze_new_histories(model, before)
 
 
@@ -1861,9 +1862,134 @@
     return False
 
 
+def _axis_frame(position) -> np.ndarray:
+    """A 4x4 matrix of an optional ``IfcAxis2Placement3D``, in file units."""
+    if position is None:
+        return np.identity(4)
+    return np.array(ifcopenshell.util.placement.get_axis2placement(position),
+                    dtype=float)
+
+
+#: Directions closer than this to a frame axis count as running along it.
+_ALIGNED = 1e-6
+
+
+def _rectangle_corners(profile) -> np.ndarray:
+    """Corner points of a rectangular profile in its own plane, in file units."""
+    half_x, half_y = float(profile.XDim) / 2.0, float(profile.YDim) / 2.0
+    points = np.array([[-half_x, -half_y], [half_x, -half_y],
+                       [half_x, half_y], [-half_x, half_y]])
+    position = getattr(profile, "Position", None)
+    if position is None:
+        return points
+    origin = np.array(position.Location.Coordinates[:2], dtype=float)
+    if position.RefDirection is not None:
+        ref = np.array(position.RefDirection.DirectionRatios[:2], dtype=float)
+        ref = ref / (float(np.linalg.norm(ref)) or 1.0)
+        rotation = np.array([[ref[0], -ref[1]], [ref[1], ref[0]]])
+        points = (rotation @ points.T).T
+    return points + origin
+
+
+def _cut_form(solid) -> str:
+    """Which dimension of a rectangular extrusion runs across its wall.
+
+    Read in the product's own axes once its rotation is cleared, which is the
+    wall's own frame after a re-hosting, where the wall's thickness runs along
+    y.  ``"depth"``: the solid is extruded across the wall, its profile holds
+    the face (width and height) and the extrusion depth is the cut.
+    ``"YDim"`` or ``"XDim"``: that profile dimension runs across the wall and
+    the extrusion runs along the wall's face.  Anything oblique is refused.
+    """
+    frame = _axis_frame(solid.Position)[:3, :3]
+    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+    direction = frame @ (direction / float(np.linalg.norm(direction)))
+    if abs(abs(float(direction[1])) - 1.0) < _ALIGNED:
+        return "depth"
+    if abs(float(direction[1])) < _ALIGNED:
+        position = getattr(solid.SweptArea, "Position", None)
+        ref = np.array([1.0, 0.0])
+        if position is not None and position.RefDirection is not None:
+            ref = np.array(position.RefDirection.DirectionRatios[:2], dtype=float)
+            ref = ref / (float(np.linalg.norm(ref)) or 1.0)
+        x_axis = frame @ np.array([ref[0], ref[1], 0.0])
+        y_axis = frame @ np.array([-ref[1], ref[0], 0.0])
+        if abs(abs(float(y_axis[1])) - 1.0) < _ALIGNED:
+            return "YDim"
+        if abs(abs(float(x_axis[1])) - 1.0) < _ALIGNED:
+            return "XDim"
+    raise ValueError("the body is extruded or turned obliquely to the wall")
+
+
+def _extent_across(solid) -> tuple:
+    """Lowest and highest y of a rectangular extrusion in its product's axes."""
+    corners = _rectangle_corners(solid.SweptArea)
+    frame = _axis_frame(solid.Position)
+    direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+    direction = direction / float(np.linalg.norm(direction))
+    points = np.array([np.array([px, py, 0.0]) + step * float(solid.Depth) * direction
+                       for px, py in corners for step in (0.0, 1.0)],
+                      dtype=float)
+    points = (frame[:3, :3] @ points.T).T + frame[:3, 3]
+    return float(points[:, 1].min()), float(points[:, 1].max())
+
+
+def _resize_cut(model, product, depth: float) -> tuple:
+    """Give a rectangular extrusion ``depth`` (file units) across its wall.
+
+    The dimension ``_cut_form`` finds across the wall is set to ``depth`` and
+    the face size is kept.  The body grows or shrinks symmetrically about its
+    own centre across the wall, so a leaf hung from it keeps its place
+    relative to that centre.  Returns the body's new extent across the wall in
+    the product's own axes.
+    """
+    solid = sole_extrusion(product)
+    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
+        raise ValueError("%s has no rectangular profile to resize"
+                         % product.GlobalId)
+    if len([i for i in model.get_inverse(solid)
+            if i.is_a("IfcShapeRepresentation")]) != 1:
+        raise ValueError("%s shares its body with another element"
+                         % product.GlobalId)
+    form = _cut_form(solid)
+    if form == "depth":
+        old = float(solid.Depth)
+        direction = np.array(solid.ExtrudedDirection.DirectionRatios, dtype=float)
+        direction = direction / float(np.linalg.norm(direction))
+        position = solid.Position
+        frame = _axis_frame(position)
+        location = frame[:3, 3] + frame[:3, :3] @ direction * ((old - float(depth)) / 2.0)
+        point = model.create_entity("IfcCartesianPoint",
+                                    Coordinates=tuple(float(v) for v in location))
+        if position is None or len(model.get_inverse(position)) != 1:
+            solid.Position = model.create_entity(
+                "IfcAxis2Placement3D", Location=point,
+                Axis=None if position is None else position.Axis,
+                RefDirection=None if position is None else position.RefDirection)
+        else:
+            position.Location = point
+        solid.Depth = float(depth)
+    else:
+        profile = solid.SweptArea
+        if len(model.get_inverse(profile)) != 1:
+            profile = model.create_entity(
+                "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
+                ProfileName=profile.ProfileName, Position=profile.Position,
+                XDim=profile.XDim, YDim=profile.YDim)
+            solid.SweptArea = profile
+        setattr(profile, form, float(depth))
+    return _extent_across(solid)
+
+
 def _replant(product, host, x: float, y: float, z: float,
              depth: Optional[float]) -> None:
-    """Hang one product from a wall at a stated point in that wall's frame."""
+    """Hang one product from a wall at a stated point in that wall's frame.
+
+    With ``depth`` (metres) the product's body is given that depth across the
+    wall and is centred on the span from ``y`` to ``y + depth``, however the
+    model draws the body; ``x`` and ``z`` place the product's own origin.
+    Without it the origin is placed at ``(x, y, z)`` and the body is kept.
+    """
     model = _file(product)
     scale = unit_scale(model)
     placement = product.ObjectPlacement
@@ -1872,26 +1998,15 @@
     if not _places_only(model, placement, product):
         raise ValueError("%s shares its placement with another element"
                          % product.GlobalId)
+    across = float(y) / scale
+    if depth is not None:
+        low, high = _resize_cut(model, product, float(depth) / scale)
+        across = across + float(depth) / scale / 2.0 - (low + high) / 2.0
     placement.PlacementRelTo = host.ObjectPlacement
     axis = _own_axis(model, placement)
-    axis.Location.Coordinates = (float(x) / scale, float(y) / scale,
-                                 float(z) / scale)
+    axis.Location.Coordinates = (float(x) / scale, across, float(z) / scale)
     axis.Axis = None
     axis.RefDirection = None
-    if depth is None:
-        return
-    solid = sole_extrusion(product)
-    if solid is None or not solid.SweptArea.is_a("IfcRectangleProfileDef"):
-        raise ValueError("%s has no rectangular profile to resize"
-                         % product.GlobalId)
-    profile = solid.SweptArea
-    if len(model.get_inverse(profile)) != 1:
-        profile = model.create_entity(
-            "IfcRectangleProfileDef", ProfileType=profile.ProfileType,
-            ProfileName=profile.ProfileName, Position=profile.Position,
-            XDim=profile.XDim, YDim=profile.YDim)
-        solid.SweptArea = profile
-    profile.YDim = float(depth) / scale
 
 
 def move_filling(filling, host_wall, along: float, sill: Optional[float] = None):
@@ -1960,15 +2075,29 @@
                 - (float(leaf_old[2]) + float(leaf_body[0][2])))
     across = new["near"] - OPENING_CLEARANCE
     hole_depth = new["thickness"] + 2 * OPENING_CLEARANCE
+    # A leaf hung from the wall whose body is kept keeps its offset across the
+    # wall from the opening's centre, read here in the wall it leaves.
+    hole_old = None
+    if not leaf_follows and not rectangular:
+        hole_old = box_in_frame(opening, old_host)
+        if hole_old is None:
+            raise ValueError("the opening has no body that can be measured")
 
     forget_geometry(model)
     voids[0].RelatingBuildingElement = host_wall
     _replant(opening, host_wall, hole_x, across,
              float(opening_old[2]) + lift, hole_depth)
     if not leaf_follows:
-        _replant(filling, host_wall, float(leaf_old[0]) + move, new["near"],
-                 float(leaf_old[2]) + lift,
-                 new["thickness"] if rectangular else None)
+        if rectangular:
+            _replant(filling, host_wall, float(leaf_old[0]) + move, new["near"],
+                     float(leaf_old[2]) + lift, new["thickness"])
+        else:
+            # the leaf keeps its offset across the wall from the opening's centre
+            offset = float(leaf_old[1]) - (float(hole_old[0][1])
+                                           + float(hole_old[1][1])) / 2.0
+            _replant(filling, host_wall, float(leaf_old[0]) + move,
+                     across + hole_depth / 2.0 + offset,
+                     float(leaf_old[2]) + lift, None)
     return old_host
 
 
@@ -2286,7 +2415,61 @@
     return list({r.id(): r for r in stale}.values())
 
 
-def _sweep_empty_relations(model, spare: set) -> int:
+#: Relationship class -> its required ends, read from the schema.
+_REQUIRED_ENDS: dict = {}
+
+
+def _required_ends(relation) -> tuple:
+    """The ends of a relationship the schema requires, with their lower bounds.
+
+    An end is an explicit attribute whose name starts with ``Relating`` or
+    ``Related`` and which the schema does not mark optional.  A set or list end
+    carries the least number of members the schema allows (``SET [1:?]`` gives
+    1), a single end carries 1.
+    """
+    key = (relation.wrapped_data.is_a(True), relation.is_a())
+    ends = _REQUIRED_ENDS.get(key)
+    if ends is None:
+        declaration = relation.wrapped_data.declaration().as_entity()
+        derived = declaration.derived()
+        ends = []
+        for index, attribute in enumerate(declaration.all_attributes()):
+            name = attribute.name()
+            if not name.startswith(("Relating", "Related")):
+                continue
+            if attribute.optional() or (index < len(derived) and derived[index]):
+                continue
+            kind = attribute.type_of_attribute()
+            aggregate = kind.as_aggregation_type()
+            least = 1 if aggregate is None else max(int(aggregate.bound1()), 0)
+            ends.append((name, aggregate is not None, least))
+        ends = tuple(ends)
+        _REQUIRED_ENDS[key] = ends
+    return ends
+
+
+def _dangling_relations(model) -> list:
+    """Every relationship with a required end left null or below its bound.
+
+    The schema says which ends a relationship cannot do without, so this
+    reaches the classes ``_empty_relations`` does not name (a covering
+    relationship whose element is gone, a classification or an actor
+    assignment that names nothing).
+    """
+    stale = []
+    for relation in model.by_type("IfcRelationship"):
+        for name, many, least in _required_ends(relation):
+            value = getattr(relation, name, None)
+            if value is None:
+                stale.append(relation)
+                break
+            if many and len(value) < least:
+                stale.append(relation)
+                break
+    return stale
+
+
+def _sweep_empty_relations(model, spare: set, spare_required=None) -> int:
     """Take out the relationship objects a removal emptied.  Returns how many.
 
     A relationship that lists several products keeps the others when one of
@@ -2297,10 +2480,21 @@
     ``spare`` holds the rows that already named nothing before the removal.
     A file can carry such rows from the authoring tool that wrote it, and they
     are not this edit's business, so they stay exactly as they were.
+
+    ``spare_required``, when given, extends the sweep to every relationship
+    whose schema-required end (``_dangling_relations``) the removal left null
+    or empty, sparing the rows that already lacked one before the removal.
+    These go only once the rows above are gone, so a removal that leaves no
+    such relationship writes the same file as before.
     """
     removed = 0
     while True:
         stale = [r for r in _empty_relations(model) if r.id() not in spare]
+        if not stale and spare_required is not None:
+            # A relationship left without a required end goes as well, unless
+            # it already lacked one before the removal.
+            stale = [r for r in _dangling_relations(model)
+                     if r.id() not in spare_required]
         if not stale:
             return removed
         for relation in stale:
@@ -2350,10 +2544,11 @@
     forget_geometry(model)
     before = {h.id() for h in model.by_type("IfcOwnerHistory")}
     spare = {r.id() for r in _empty_relations(model)}
+    spare_required = {r.id() for r in _dangling_relations(model)}
     for filling in _fillings_of(product):
         ifcopenshell.api.root.remove_product(model, product=filling)
     ifcopenshell.api.root.remove_product(model, product=product)
-    _sweep_empty_relations(model, spare)
+    _sweep_empty_relations(model, spare, spare_required)
     _freeze_new_histories(model, before)
 
 
@@ -2385,6 +2580,14 @@
             continue
         findings["empty_relations"].append("%s #%d" % (relation.is_a(),
                                                        relation.id()))
+    spare_required = ({r.id() for r in _dangling_relations(source)}
+                      if source is not None else set())
+    listed = {entry for entry in findings["empty_relations"]}
+    for relation in _dangling_relations(model):
+        entry = "%s #%d" % (relation.is_a(), relation.id())
+        if relation.id() in spare_required or entry in listed:
+            continue
+        findings["empty_relations"].append(entry)
     if source is not None:
         try:
             gone = source.by_guid(guid)
```
