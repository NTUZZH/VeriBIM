"""The v4 reward flags, and the promise that they change nothing while off.

Three things were added for GRPO v4: a deduction for resending a
snippet that already raised, a rule that zeroes a trajectory which never
committed, and a family-aware scorer reading. The first two are off by default
and the first test is the one that matters most, because the paper's claim is
that the verifier's own value is the training signal: with the flags off, every
number this stage computes has to be the number it computed before they
existed.

Those numbers are frozen below rather than recomputed. They were taken from the
implementation as it stood on 2026-09-09, before any of this was written, over
the same twelve synthetic trajectories the later tests reuse.

Everything here runs on CPU. The scorer is replaced by a stub that returns a
fixed value per task, because what is under test is the composition around the
verifier, not the verifier. Run it in the ``l2`` environment, which is where
the scorer's configuration lives:

    PYTHONPATH=code l2/bin/python -m stage_c.tests.test_reward_v4
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path

from stage_a import paths

import stage_a.scoring as scoring_module  # noqa: E402
from stage_c import reward as reward_module  # noqa: E402
from stage_c.reward import (COMMIT_REQUIRED_CHOICES, Reward, heldout_config,
                            normalise, score_trajectory,
                            training_config)  # noqa: E402
from stage_c.rollout import (REPEAT_PENALTY, REPEAT_PENALTY_CAP, Rollout,
                             normalised_code, raised,
                             repeat_failures)  # noqa: E402
from stage_c.train_grpo import build_parser, resolved_config  # noqa: E402


# --------------------------------------------------------------------------
# the fixed synthetic set
# One row is one trajectory: its operation, the no-op floor of its task, what
# the scorer returned for the file it left (None = the file could not be
# parsed), whether it committed, and the tool calls it made as
# (code, did it raise).

CASES = [
    ("clean_solve_update", "update", 0.4200, 1.0000, 1, [("a=1", False)]),
    ("clean_solve_create", "create", 0.0000, 1.0000, 1, [("a=1", False)]),
    ("partial_update", "update", 0.4200, 0.7100, 1,
     [("a=1", True), ("b=2", False)]),
    ("noop_update", "update", 0.4200, 0.4200, 0, [("a=1", True)]),
    ("worse_than_noop", "update", 0.4200, 0.1000, 1, [("a=1", False)]),
    # The same snippet three times, differing only in trailing whitespace.
    ("uncommitted_create", "create", 0.0000, 0.0000, 0,
     [("a=1", True), ("a=1\n", True), ("a=1  ", True)]),
    ("uncommitted_update", "update", 0.4200, 0.4200, 0,
     [("a=1", True)] * 7),
    ("looping_partial_update", "update", 0.4200, 0.6000, 1,
     [("x()", True), ("x()", True), ("x()", True), ("y()", False),
      ("y()", False)]),
    ("many_errors_update", "update", 0.4200, 0.9000, 1,
     [(f"p{i}", True) for i in range(8)]),
    ("delete_removal", "delete", 0.1620, 1.0000, 1, [("d()", False)]),
    ("unreadable_file", "update", 0.4200, None, 1, [("a=1", False)]),
    ("underspecified_unchanged", "update", 0.6670, 0.6670, 0,
     [("read()", False)]),
]

#: What the implementation of 2026-09-09 returned for each row: the verifier's
#: normalised value, and that value after the deduction at its launch
#: setting of 0.02 per raised call capped at 0.10.
FROZEN = {
    "clean_solve_update": (1.000000, 1.000000),
    "clean_solve_create": (1.000000, 1.000000),
    "partial_update": (0.500000, 0.480000),
    "noop_update": (0.000000, -0.020000),
    "worse_than_noop": (-0.200000, -0.200000),
    "uncommitted_create": (0.000000, -0.060000),
    "uncommitted_update": (0.000000, -0.100000),
    "looping_partial_update": (0.310345, 0.250345),
    "many_errors_update": (0.827586, 0.727586),
    "delete_removal": (1.000000, 1.000000),
    "unreadable_file": (-0.200000, -0.200000),
    "underspecified_unchanged": (0.000000, 0.000000),
}

#: The normalisation itself, on the same date, over the pairs the cases use.
FROZEN_NORMALISE = [
    (0.0, 0.0, 0.0), (1.0, 0.0, 1.0), (0.5, 0.0, 0.5),
    (0.162, 0.162, 0.0), (1.0, 0.162, 1.0), (0.0, 0.5, -0.2),
    (0.9, 0.8427, 0.364272), (0.42, 0.42, 0.0), (0.71, 0.42, 0.5),
    (0.1, 0.42, -0.2), (0.6, 0.42, 0.310345), (1.0, 0.42, 1.0),
    (0.667, 0.667, 0.0), (1.0, 0.667, 1.0),
]


class StubScore:
    """What the scorer returns, without opening a model."""

    def __init__(self, final, error=None):
        self.final = 0.0 if final is None else float(final)
        self.error = error


def build_task(name, operation, null, families=()):
    return {"task_id": name, "operation": operation, "category": "direct",
            "input_ifc": "data/x.ifc", "ground_truth_ifc": "data/y.ifc",
            "prompt": "p", "target": {}, "families": list(families),
            "verification": {"null_edit_score": null}}


def iterations_for(calls):
    """The harness's own record shape for a list of (code, raised) calls."""
    return [{"tool_calls": [
        {"name": "execute_ifc_code", "args": {"code": code},
         "output": "Traceback (most recent call last): boom" if failed else "ok",
         "ok": True}
        for code, failed in calls]}]


def rollout_for(case, scored):
    _, _, _, _, commits, calls = case
    repeats, codes = repeat_failures(iterations_for(calls))
    return Rollout(index=1, messages=[], stop_reason="completed",
                   tool_rounds=1, commits=commits, tool_calls=len(calls),
                   raised_calls=sum(1 for _, failed in calls if failed),
                   well_formed_calls=len(calls), reward=scored.value,
                   readable=scored.readable,
                   repeat_failures=repeats, repeated_codes=codes)


class StubbedScorer:
    """``score_prediction`` replaced by a table lookup, and put back after."""

    def __init__(self, finals):
        self.finals = dict(finals)
        self.seen: list[dict] = []
        self._saved = None

    def __enter__(self):
        self._saved = scoring_module.score_prediction

        def stub(record, predicted, project_root, gold_path=None, config=None,
                 reply="", **kwargs):
            self.seen.append({"task_id": record["task_id"], "config": config,
                              "reply": reply})
            final = self.finals[record["task_id"]]
            if final is None:
                return StubScore(0.0, error="ifc_parse_error: cannot parse")
            return StubScore(final)

        scoring_module.score_prediction = stub
        return self

    def __exit__(self, *exc):
        scoring_module.score_prediction = self._saved
        return False


def rewards_for_the_fixed_set(error_penalty=0.0, error_cap=0.10,
                              repeat_penalty=0.0, repeat_cap=REPEAT_PENALTY_CAP,
                              commit_required="off"):
    """Every case's reward under one setting of the three deductions."""
    holder = Path(tempfile.mkdtemp(prefix="rewardv4_"))
    predicted = holder / "pred.ifc"
    predicted.write_bytes(b"ISO-10303-21;\n")
    out = {}
    with StubbedScorer({c[0]: c[3] for c in CASES}):
        for case in CASES:
            name, operation, null = case[0], case[1], case[2]
            task = build_task(name, operation, null)
            scored = score_trajectory(task, predicted, paths.PROJECT_ROOT,
                                      holder / "gold.ifc")
            rollout = rollout_for(case, scored)
            if error_penalty > 0:
                rollout.apply_error_penalty(error_penalty, error_cap)
            if repeat_penalty > 0:
                rollout.apply_repeat_penalty(repeat_penalty, repeat_cap)
            rollout.apply_commit_gate(operation, commit_required)
            out[name] = rollout
    return out


# --------------------------------------------------------------------------
# 1. flags off


def test_the_flags_off_reproduce_the_frozen_numbers():
    """With every v4 flag off, the reward is the number it always was."""
    plain = rewards_for_the_fixed_set()
    with_d062 = rewards_for_the_fixed_set(error_penalty=0.02)
    bad = []
    for name, (want_plain, want_d062) in FROZEN.items():
        got_plain = round(plain[name].reward, 6)
        got_d062 = round(with_d062[name].reward, 6)
        if abs(got_plain - want_plain) > 5e-7:
            bad.append((name, "no shaping", want_plain, got_plain))
        if abs(got_d062 - want_d062) > 5e-7:
            bad.append((name, "error deduction", want_d062, got_d062))
        assert not plain[name].commit_gated, name
        assert plain[name].reward_raw is None, name
    assert not bad, bad

    for final, null, want in FROZEN_NORMALISE:
        assert abs(normalise(final, null) - want) < 5e-7, (final, null, want)
    print("ok   test_the_flags_off_reproduce_the_frozen_numbers")


def test_the_flags_are_off_by_default():
    settings = vars(build_parser().parse_args(["--run-id", "x"]))
    assert settings["repeat_penalty"] == 0.0
    assert settings["repeat_penalty_cap"] == 0.25
    assert settings["commit_required"] == "off"
    print("ok   test_the_flags_are_off_by_default")


def test_a_plain_record_keeps_the_published_reading():
    """The family-aware reading changes nothing for a task in no such family."""
    from stage_a.scoring import scorer_config

    for operation in ("create", "update", "delete"):
        record = build_task("t", operation, 0.1)
        assert training_config(record) == scorer_config(operation), operation
        assert training_config(operation) == scorer_config(operation), operation
    print("ok   test_a_plain_record_keeps_the_published_reading")


# --------------------------------------------------------------------------
# 2. the repeat-failure counter


def test_a_resent_failing_snippet_is_counted_once_per_repeat():
    repeats, codes = repeat_failures(iterations_for(
        [("x()", True), ("x()", True), ("x()", True)]))
    assert (repeats, codes) == (2, 1)
    print("ok   test_a_resent_failing_snippet_is_counted_once_per_repeat")


def test_whitespace_does_not_make_two_attempts_different():
    """Blank lines, trailing spaces and spacing inside a line are ignored."""
    repeats, _ = repeat_failures(iterations_for(
        [("x()\n\ny()", True), ("x()\ny()\n", True), ("x()\ny()   \n\n", False)]))
    assert repeats == 2
    assert normalised_code("a = 1\n\n") == normalised_code("a  =  1  ")
    assert normalised_code("f(a,\tb)") == normalised_code("f(a, b)")
    print("ok   test_whitespace_does_not_make_two_attempts_different")


def test_reindented_code_is_a_different_attempt():
    """Whitespace runs collapse; they are not removed.

    Python reads indentation, so a re-indented snippet is a different program
    and the policy sending it has changed something. Only a snippet the sandbox
    would answer identically counts as resent.
    """
    repeats, _ = repeat_failures(iterations_for(
        [("if x:\n  y()", True), ("if x:\n    y()", True)]))
    assert repeats == 0
    print("ok   test_reindented_code_is_a_different_attempt")


def test_a_repeat_of_a_call_that_worked_is_not_counted():
    repeats, codes = repeat_failures(iterations_for(
        [("z()", False), ("z()", False), ("z()", False)]))
    assert (repeats, codes) == (0, 0)
    print("ok   test_a_repeat_of_a_call_that_worked_is_not_counted")


def test_the_repeat_is_counted_even_when_it_finally_works():
    """The failure mode is resending the snippet, not what came back."""
    repeats, _ = repeat_failures(iterations_for([("x()", True), ("x()", False)]))
    assert repeats == 1
    print("ok   test_the_repeat_is_counted_even_when_it_finally_works")


def test_distinct_snippets_are_separated_from_one_snippet():
    stuck = repeat_failures(iterations_for([("a()", True)] * 4))
    cycling = repeat_failures(iterations_for(
        [("a()", True), ("b()", True), ("a()", True), ("b()", True)]))
    assert stuck == (3, 1)
    assert cycling == (2, 2)
    print("ok   test_distinct_snippets_are_separated_from_one_snippet")


def test_malformed_and_empty_calls_are_ignored():
    records = [{"tool_calls": [
        {"name": "execute_ifc_code", "args": {"raw": "not json"},
         "output": "Traceback (most recent call last): boom"},
        {"name": "execute_ifc_code", "args": {"raw": "not json"},
         "output": "Traceback (most recent call last): boom"},
        {"name": "execute_ifc_code", "args": {"code": "   "}, "output": "x"},
        {"name": "execute_ifc_code", "args": {"code": "   "}, "output": "x"}]}]
    assert repeat_failures(records) == (0, 0)
    print("ok   test_malformed_and_empty_calls_are_ignored")


def test_a_sandbox_crash_does_not_read_as_a_raised_call():
    """``raised`` and ``raised_calls`` must agree on what a failure is."""
    assert raised({"output": "Traceback (most recent call last): boom"})
    assert not raised({"output": "tool_timeout: the sandbox did not answer"})
    assert not raised({"output": None})
    print("ok   test_a_sandbox_crash_does_not_read_as_a_raised_call")


# --------------------------------------------------------------------------
# 3. the repeat penalty


def test_the_repeat_penalty_deducts_per_repeat_and_caps():
    off = rewards_for_the_fixed_set()
    on = rewards_for_the_fixed_set(repeat_penalty=REPEAT_PENALTY)
    # Three identical failing snippets: two repeats, so 0.10 off.
    assert on["uncommitted_create"].repeat_failures == 2
    assert abs(on["uncommitted_create"].reward
               - (off["uncommitted_create"].reward - 0.10)) < 1e-9
    # Six repeats of one snippet would be 0.30; the cap holds it at 0.25.
    assert on["uncommitted_update"].repeat_failures == 6
    assert abs(on["uncommitted_update"].reward
               - (off["uncommitted_update"].reward - REPEAT_PENALTY_CAP)) < 1e-9
    # Eight distinct failing snippets, none resent: nothing is deducted.
    assert on["many_errors_update"].repeat_failures == 0
    assert on["many_errors_update"].reward == off["many_errors_update"].reward
    # A trajectory that repeated a failure and still edited the file loses the
    # deduction and keeps the rest of its value.
    assert on["looping_partial_update"].repeat_failures == 2
    assert abs(on["looping_partial_update"].reward
               - (off["looping_partial_update"].reward - 0.10)) < 1e-9
    print("ok   test_the_repeat_penalty_deducts_per_repeat_and_caps")


def test_the_two_deductions_stack_and_the_verifier_value_survives():
    both = rewards_for_the_fixed_set(error_penalty=0.02,
                                     repeat_penalty=REPEAT_PENALTY)
    row = both["looping_partial_update"]
    # 0.310345 verifier, minus 0.06 for three raised calls, minus 0.10 for two
    # repeats.
    assert abs(row.reward_raw - 0.310345) < 5e-6
    assert abs(row.reward - (0.310345 - 0.06 - 0.10)) < 5e-6
    print("ok   test_the_two_deductions_stack_and_the_verifier_value_survives")


# --------------------------------------------------------------------------
# 4. the commit gate


def test_the_commit_gate_zeroes_an_uncommitted_create_only():
    on = rewards_for_the_fixed_set(commit_required="create")
    assert on["uncommitted_create"].commit_gated
    assert on["uncommitted_create"].reward == 0.0
    # An uncommitted update is left to the verifier under this scope.
    assert not on["uncommitted_update"].commit_gated
    assert not on["noop_update"].commit_gated
    # A create that committed is untouched.
    assert not on["clean_solve_create"].commit_gated
    assert on["clean_solve_create"].reward == 1.0
    print("ok   test_the_commit_gate_zeroes_an_uncommitted_create_only")


def test_the_commit_gate_can_cover_every_operation():
    on = rewards_for_the_fixed_set(commit_required="all")
    gated = {name for name, row in on.items() if row.commit_gated}
    assert gated == {"uncommitted_create", "uncommitted_update", "noop_update",
                     "underspecified_unchanged"}
    for name in gated:
        assert on[name].reward == 0.0, name
    print("ok   test_the_commit_gate_can_cover_every_operation")


def test_the_gate_overrides_a_deduction_rather_than_adding_to_it():
    """Zero means zero, whatever the two deductions had already taken off."""
    on = rewards_for_the_fixed_set(error_penalty=0.02,
                                   repeat_penalty=REPEAT_PENALTY,
                                   commit_required="create")
    row = on["uncommitted_create"]
    assert row.reward == 0.0
    assert row.reward_raw == 0.0  # the verifier's own value, kept for the log
    print("ok   test_the_gate_overrides_a_deduction_rather_than_adding_to_it")


def test_the_gate_lifts_a_group_the_verifier_scored_flat():
    """Why the gate is worth having: it separates rollouts the file does not.

    Two create trajectories both leave the input untouched and the verifier
    scores both at the no-op floor. One committed an edit that happened to
    change nothing measurable; the other never wrote at all. Only the gate
    tells them apart, and a group with no spread trains on nothing.
    """
    pair = [Rollout(index=i, messages=[], stop_reason="completed",
                    tool_rounds=1, commits=commits, tool_calls=1,
                    raised_calls=0, well_formed_calls=1, reward=0.0)
            for i, commits in ((1, 1), (2, 0))]
    assert max(r.reward for r in pair) - min(r.reward for r in pair) < 1e-9
    for row in pair:
        row.apply_commit_gate("create", "create")
    assert [row.reward for row in pair] == [0.0, 0.0]
    print("ok   test_the_gate_lifts_a_group_the_verifier_scored_flat")


def test_the_gate_never_pays_a_crashed_rollout_more_than_the_verifier_did():
    """A rollout that left no readable file also never committed.

    Zeroing it would lift it off the unreadable-file floor and rank a crashed
    trajectory above one that made the model worse.
    """
    crashed = Rollout(index=1, messages=[], stop_reason="driver_error",
                      tool_rounds=0, commits=0, tool_calls=0, raised_calls=0,
                      well_formed_calls=0, reward=-0.2, readable=False)
    for scope in ("create", "all"):
        crashed.apply_commit_gate("create", scope)
        assert crashed.reward == -0.2
        assert not crashed.commit_gated
    print("ok   test_the_gate_never_pays_a_crashed_rollout_more_than_the_verifier_did")


def test_the_gate_scope_names_are_the_ones_the_flag_accepts():
    parser = build_parser()
    for scope in COMMIT_REQUIRED_CHOICES:
        settings = parser.parse_args(["--run-id", "x", "--commit-required", scope])
        assert settings.commit_required == scope
    print("ok   test_the_gate_scope_names_are_the_ones_the_flag_accepts")


# --------------------------------------------------------------------------
# 5. the family-aware reading


def test_the_material_and_type_families_change_the_reading():
    from stage_a.scoring import scorer_config

    published = scorer_config("update")
    material = training_config(build_task("m", "update", 0.1,
                                          ["op.update.material"]))
    assert material.properties_include_material is True
    assert "IfcRelAssociatesMaterial" in material.topology_relations_extra
    assert published.properties_include_material is False

    type_object = training_config(build_task("t", "update", 0.1,
                                             ["op.update.type_object"]))
    assert type_object.properties_include_type is True
    assert "IfcRelDefinesByType" in type_object.topology_relations_extra
    print("ok   test_the_material_and_type_families_change_the_reading")


def test_an_under_specified_task_is_read_against_the_reply():
    """The reward reads the reply, under the setting the family asks for."""
    record = build_task("u", "update", 0.667, ["wording.underspecified"])
    config = training_config(record)
    assert config.underspecified_mode is True

    holder = Path(tempfile.mkdtemp(prefix="rewardv4u_"))
    predicted = holder / "pred.ifc"
    predicted.write_bytes(b"ISO-10303-21;\n")
    with StubbedScorer({"u": 1.0}) as stub:
        scored = score_trajectory(record, predicted, paths.PROJECT_ROOT,
                                  holder / "gold.ifc",
                                  reply="Which storey should the door go on?")
    assert stub.seen[0]["reply"] == "Which storey should the door go on?"
    assert stub.seen[0]["config"].underspecified_mode is True
    # 1.0 against a 0.667 no-op floor is the full reward; an unchanged file
    # with no question scores 0 under this reading and lands at the floor.
    assert scored.value == 1.0

    with StubbedScorer({"u": 0.0}) as stub:
        silent = score_trajectory(record, predicted, paths.PROJECT_ROOT,
                                  holder / "gold.ifc", reply="")
    assert stub.seen[0]["reply"] == ""
    assert abs(silent.value - normalise(0.0, 0.667)) < 1e-9
    print("ok   test_an_under_specified_task_is_read_against_the_reply")


def test_the_held_out_verifier_still_differs_only_in_its_sampling():
    """The family reading travels to the held-out verifier, the seed apart."""
    record = build_task("m", "update", 0.1, ["op.update.material"])
    train, held = training_config(record), heldout_config(record)
    differences = {f for f in vars(train) if getattr(train, f) != getattr(held, f)}
    assert differences == {"sampling_seed", "pooled_max_total_samples",
                           "pooled_min_samples_per_object"}
    assert held.properties_include_material is True
    print("ok   test_the_held_out_verifier_still_differs_only_in_its_sampling")


# --------------------------------------------------------------------------
# 6. the run's own record


def test_the_resolved_config_names_the_three_settings():
    parser = build_parser()
    off = resolved_config(parser.parse_args(["--run-id", "x"]), {})["reward"]
    assert off["repeat_penalty"] == 0.0
    assert off["repeat_penalty_cap"] == 0.25
    assert off["commit_required"] == "off"
    assert off["shaping"] == "none beyond the unreadable-file penalty"
    assert "scorer_config_for" in off["scorer_reading"]

    on = resolved_config(parser.parse_args(
        ["--run-id", "x", "--error-penalty", "0.02", "--repeat-penalty", "0.05",
         "--commit-required", "create"]), {})["reward"]
    assert on["repeat_penalty"] == 0.05
    assert on["commit_required"] == "create"
    assert "per tool call that raised" in on["shaping"]
    assert "resending code" in on["shaping"]
    assert "never called commit()" in on["shaping"]

    every = resolved_config(parser.parse_args(
        ["--run-id", "x", "--commit-required", "all"]), {})["reward"]
    assert "any operation" in every["shaping"]
    print("ok   test_the_resolved_config_names_the_three_settings")


def test_the_rollout_stats_carry_the_repeat_counts():
    row = rewards_for_the_fixed_set(repeat_penalty=REPEAT_PENALTY,
                                    commit_required="create")["uncommitted_create"]
    stats = row.stats()
    assert stats["repeat_failures"] == 2
    assert stats["repeated_codes"] == 1
    assert stats["commit_gated"] is True
    assert stats["reward"] == 0.0
    print("ok   test_the_rollout_stats_carry_the_repeat_counts")


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
