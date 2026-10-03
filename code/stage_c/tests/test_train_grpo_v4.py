"""The trainer's own plumbing for the v4 reward settings.

``test_reward_v4`` checks the arithmetic on synthetic trajectories. What is
checked here is that the settings in the run's configuration reach it: a batch
scored through the trainer's generation path, with the deductions off and then
on, and the counts written to the rollout log the run is read from.

It needs torch and runs on CPU against the tiny model the alignment tests
build. No server is contacted and no rollout is produced.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from stage_c.align_test import build_tiny
from stage_c.rollout import Rollout
from stage_c.tests.test_train_grpo_v3 import _StubEncoder, _trainer

TASKS = [{"task_id": "t_create", "operation": "create", "category": "spatial"},
         {"task_id": "t_update", "operation": "update", "category": "spatial"}]

#: One group per task: (reward, commits, repeat_failures, raised_calls).
#: Both groups have a spread, so neither is skipped for flatness before the
#: deductions are applied.
GROUPS = {
    "t_create": [(0.80, 1, 0, 0), (0.40, 0, 4, 2)],
    "t_update": [(0.60, 1, 6, 1), (0.20, 0, 0, 0)],
}


def _rollouts(task, k, *args, **kwargs):
    return [Rollout(index=position + 1, messages=[], stop_reason="completed",
                    tool_rounds=1, commits=commits, tool_calls=3,
                    raised_calls=raised_calls, well_formed_calls=3,
                    reward=reward, repeat_failures=repeats, repeated_codes=1)
            for position, (reward, commits, repeats, raised_calls)
            in enumerate(GROUPS[task["task_id"]])]


def _run(**settings):
    """One generation batch through the trainer, under one reward setting."""
    model, tokenizer = build_tiny()
    trainer = _trainer(model, tokenizer, rows=len(TASKS) * 2)
    trainer.veribim = {
        "tokenizer": tokenizer, "pad_id": 0, "num_generations": 2,
        "tasks": {t["task_id"]: t for t in TASKS},
        "client": None, "agent": None, "work_root": Path("."),
        "gold_cache_dir": Path("."), "tools": [], "max_seq": 4096,
        "rollout_group": _rollouts, "encode_group": _StubEncoder({}),
        **settings,
    }
    inputs = [{"task_id": t["task_id"]} for t in TASKS for _ in range(2)]
    trainer._generate_and_score_completions(inputs)
    log = list(trainer._rollout_log)
    shutil.rmtree(trainer._test_output_dir, ignore_errors=True)
    return {row["task_id"]: row for row in log if row.get("n")}


def test_the_defaults_leave_every_reward_where_the_verifier_put_it():
    groups = _run()
    rewards = {task: [s["reward"] for s in row["stats"]]
               for task, row in groups.items()}
    assert rewards == {"t_create": [0.8, 0.4], "t_update": [0.6, 0.2]}
    for row in groups.values():
        assert all(s["reward_raw"] is None for s in row["stats"])
        assert not any(s["commit_gated"] for s in row["stats"])
    print("ok   test_the_defaults_leave_every_reward_where_the_verifier_put_it")


def test_the_repeat_penalty_reaches_the_rollouts_from_the_configuration():
    groups = _run(repeat_penalty=0.05, repeat_penalty_cap=0.25,
                  commit_required="off")
    create = [s["reward"] for s in groups["t_create"]["stats"]]
    update = [s["reward"] for s in groups["t_update"]["stats"]]
    # Four repeats at 0.05 is 0.20, under the cap; six is 0.30, over it.
    assert create == [0.8, 0.2]
    assert update == [0.35, 0.2]
    assert [s["reward_raw"] for s in groups["t_update"]["stats"]] == [0.6, 0.2]
    print("ok   test_the_repeat_penalty_reaches_the_rollouts_from_the_configuration")


def test_the_commit_gate_reaches_the_rollouts_and_reads_the_operation():
    groups = _run(commit_required="create")
    create = groups["t_create"]["stats"]
    update = groups["t_update"]["stats"]
    assert [s["reward"] for s in create] == [0.8, 0.0]
    assert [s["commit_gated"] for s in create] == [False, True]
    # The update group has an uncommitted rollout too, and this scope leaves it.
    assert [s["reward"] for s in update] == [0.6, 0.2]
    assert not any(s["commit_gated"] for s in update)
    assert groups["t_create"]["commit_gated"] == 1
    assert groups["t_update"]["commit_gated"] == 0
    print("ok   test_the_commit_gate_reaches_the_rollouts_and_reads_the_operation")


def test_every_operation_can_be_gated():
    groups = _run(commit_required="all")
    assert [s["reward"] for s in groups["t_update"]["stats"]] == [0.6, 0.0]
    assert groups["t_update"]["commit_gated"] == 1
    print("ok   test_every_operation_can_be_gated")


def test_the_group_record_carries_the_repeat_counts():
    groups = _run()
    assert groups["t_create"]["repeat_failures"] == 4
    assert groups["t_update"]["repeat_failures"] == 6
    per_rollout = [s["repeat_failures"] for s in groups["t_update"]["stats"]]
    assert per_rollout == [6, 0]
    print("ok   test_the_group_record_carries_the_repeat_counts")


def test_all_three_deductions_compose_in_the_trainer():
    groups = _run(error_penalty=0.02, error_penalty_cap=0.10,
                  repeat_penalty=0.05, repeat_penalty_cap=0.25,
                  commit_required="create")
    create = groups["t_create"]["stats"]
    # The committed rollout keeps its value; the other raised twice (0.04),
    # repeated four times (0.20), and then the gate zeroes it outright.
    assert create[0]["reward"] == 0.8
    assert create[1]["reward"] == 0.0
    assert create[1]["reward_raw"] == 0.4
    update = groups["t_update"]["stats"]
    assert abs(update[0]["reward"] - (0.6 - 0.02 - 0.25)) < 1e-6
    print("ok   test_all_three_deductions_compose_in_the_trainer")


# --------------------------------------------------------------------------


def main() -> int:
    tests = [value for name, value in sorted(globals().items())
             if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - the report is the point
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}", flush=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
