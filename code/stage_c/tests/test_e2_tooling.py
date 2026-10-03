"""The E2 held-out-buildings tooling, checked on CPU in a few seconds.

Six things are worth a test. The v1 subset file has to name the 432 tasks once
each, because the whole test set is defined by that list. The gap script's
directory arguments have to default to the val-500 values, because every earlier
val-500 call omits them and must keep meaning what it meant. The do-nothing
arm's rows have to carry every field the shared summariser reads, because the
arm exists precisely so that its column and the model columns come out of the
same summariser. The gap script has to hand the verifier the trajectory's
closing assistant message and resolve the scorer settings from the record, which
is what the reward does, and it has to fall back to the published reading rather
than score a lost reply as a failure. The evaluation driver has to be able to
read each task under its own record's settings. And the E2 driver script has to
point at the v3 set without naming a data/ path.

No IFC model is opened and no server is contacted.
"""

from __future__ import annotations

import ast
import inspect
import json
import tempfile
from pathlib import Path

from stage_a import paths
from stage_a import gate_eval, scoring
from stage_a.gate_eval import summarize

paths.ensure_harness_on_path()

from modifc_harness.config import AgentConfig  # noqa: E402

from stage_c import heldout_gap, null_arm  # noqa: E402

SUBSET = paths.PROJECT_ROOT / "runs_local/e2/e2_subset_432.json"
E2_TASKS = paths.PROJECT_ROOT / "data/veribim_tasks_e2/e2_tasks.jsonl"
EVAL_E2 = paths.PROJECT_ROOT / "code/stage_c/eval_e2.sh"


def test_subset_names_the_432_tasks_once_each():
    ids = json.loads(SUBSET.read_text(encoding="utf-8"))
    assert isinstance(ids, list)
    assert len(ids) == 432
    assert len(set(ids)) == 432
    assert all(isinstance(t, str) and t for t in ids)


def test_subset_is_the_task_file_in_file_order():
    order = [json.loads(line)["task_id"]
             for line in E2_TASKS.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert json.loads(SUBSET.read_text(encoding="utf-8")) == order


def test_heldout_gap_defaults_are_the_val500_constants():
    """A call that names no directory is the val-500 measurement it always was."""
    root = paths.PROJECT_ROOT
    assert heldout_gap.RUN_DIR == root / "runs_local/stage_c_val500"
    assert heldout_gap.TASKS == root / "data/veribim_tasks_canonical/tasks.jsonl"
    assert heldout_gap.GOLD_CACHE == root / "data/stage_c/_gold_val500"

    args = heldout_gap.build_parser().parse_args(["--name", "dpo_v1"])
    assert Path(args.run_dir) == heldout_gap.RUN_DIR
    assert Path(args.tasks_file) == heldout_gap.TASKS
    assert Path(args.gold_cache) == heldout_gap.GOLD_CACHE
    assert args.workers == 6 and args.limit == 0


def test_heldout_gap_accepts_the_e2_directories():
    args = heldout_gap.build_parser().parse_args(
        ["--name", "null_edit", "--run-dir", "runs_local/e2",
         "--tasks-file", "data/veribim_tasks_e2/e2_tasks.jsonl",
         "--gold-cache", "runs_local/e2/_gold_e2"])
    assert args.run_dir == "runs_local/e2"
    assert args.gold_cache == "runs_local/e2/_gold_e2"


def _task(task_id: str, families: list[str], **fields) -> dict:
    """One task record, with the two fields an under-specified task carries."""
    record = {"task_id": task_id, "operation": "update", "category": "direct",
              "families": families, "input_ifc": "data/corpus/x/a.ifc",
              "verification": {"null_edit_score": 0.5}}
    if heldout_gap.UNDERSPECIFIED in families:
        record["clarification"] = {"slot": "element", "keywords": ["which"]}
        record["expected_reply"] = "Which column do you mean?"
    record.update(fields)
    return record


def test_the_gap_reads_the_closing_assistant_message():
    """The reply the reward scores against is the last assistant turn with content."""
    assert heldout_gap.reply_of({"reply": "Which column do you mean?"}) \
        == "Which column do you mean?"
    transcript = {"messages": [{"role": "assistant", "content": "working on it"},
                               {"role": "tool", "content": "ok"},
                               {"role": "assistant", "content": "Which storey?"},
                               {"role": "tool", "content": "unread"}]}
    assert heldout_gap.reply_of(transcript) == "Which storey?"
    assert heldout_gap.reply_of({"reply": "  "}) == ""
    assert heldout_gap.reply_of({"task_id": "T-1"}) == ""


def test_the_gap_scores_every_task_under_its_own_record():
    """The settings come from the record, not from its operation string."""
    from stage_c.reward import training_config

    material = _task("M-1", ["op.update.material"])
    under = _task("U-1", [heldout_gap.UNDERSPECIFIED])
    rows = [{"task_id": "M-1", "edited_ifc": "/work/m.ifc", "reply": ""},
            {"task_id": "U-1", "edited_ifc": "/work/u.ifc",
             "reply": "Which column do you mean?"}]
    jobs, counts = heldout_gap.build_jobs(rows, {"M-1": material, "U-1": under})

    assert [job["index"] for job in jobs] == [0, 1]
    assert [job["predicted"] for job in jobs] == ["/work/m.ifc", "/work/u.ifc"]
    assert jobs[1]["reply"] == "Which column do you mean?"
    # A material association is read as a property whether or not anything was
    # said, and an under-specified task is read against what was said.
    assert training_config(jobs[0]["task"]).properties_include_material is True
    assert training_config(jobs[1]["task"]).underspecified_mode is True
    assert counts == {"rows_without_reply": 1, "read_without_the_reply": 0}


def test_an_under_specified_row_that_kept_no_reply_falls_back_and_is_counted():
    """A lost reply is reported, because that reading would score it zero."""
    from stage_c.reward import training_config

    under = _task("U-1", [heldout_gap.UNDERSPECIFIED])
    rows = [{"task_id": "U-1", "edited_ifc": "/work/u.ifc"}]
    jobs, counts = heldout_gap.build_jobs(rows, {"U-1": under})

    assert jobs[0]["reply"] == ""
    assert training_config(jobs[0]["task"]).underspecified_mode is False
    assert counts == {"rows_without_reply": 1, "read_without_the_reply": 1}
    # The record itself is untouched, so the tool changes no task file.
    assert under["families"] == [heldout_gap.UNDERSPECIFIED]


def test_the_driver_records_the_closing_message_on_every_row():
    source = inspect.getsource(gate_eval.rollout)
    assert '"reply": result.model_output or ""' in source
    assert null_arm.null_rows("null_edit", [_task("T-1", [])],
                              paths.PROJECT_ROOT)[0]["reply"] == ""


class _StubScorer:
    """``score_prediction`` and the gold lookup replaced by stubs."""

    def __init__(self):
        self.seen: list[dict] = []
        self._saved = None

    def __enter__(self):
        from stage_a import goldmodels

        self._saved = (scoring.score_prediction, goldmodels.resolve_gold)

        def stub(record, predicted, project_root, gold_path=None, config=None,
                 reply="", **kwargs):
            self.seen.append({"config": config, "reply": reply})
            return scoring.Score(final=1.0, geometry=1.0, semantics=1.0,
                                 topology=1.0)

        scoring.score_prediction = stub
        goldmodels.resolve_gold = lambda record, cache=None, project_root=None: Path("gold.ifc")
        return self

    def __exit__(self, *exc):
        from stage_a import goldmodels

        scoring.score_prediction, goldmodels.resolve_gold = self._saved
        return False


def test_the_evaluation_driver_can_read_a_task_under_its_own_record():
    """--scorer-reading family reaches the scorer; the default is unchanged."""
    assert inspect.signature(gate_eval.score_rows).parameters[
        "family_reading"].default is False

    holder = Path(tempfile.mkdtemp(prefix="e2tooling_"))
    predicted = holder / "pred.ifc"
    predicted.write_bytes(b"ISO-10303-21;\n")
    record = _task("U-1", [heldout_gap.UNDERSPECIFIED])
    row = {"task_id": "U-1", "edited_ifc": str(predicted),
           "reply": "Which column do you mean?"}

    with _StubScorer() as stub:
        gate_eval._init_scorer(str(paths.PROJECT_ROOT), str(holder / "cache"),
                               family_reading=True)
        gate_eval._score_one((record, row))
        assert stub.seen[-1]["config"].underspecified_mode is True
        assert stub.seen[-1]["reply"] == "Which column do you mean?"

        gate_eval._init_scorer(str(paths.PROJECT_ROOT), str(holder / "cache"))
        gate_eval._score_one((record, row))
        # The published reading is the scorer's own default, which the driver
        # asks for by passing no configuration at all.
        assert stub.seen[-1]["config"] is None


def test_the_e2_script_points_at_the_v3_set_and_reads_it_by_family():
    script = EVAL_E2.read_text(encoding="utf-8")
    assert 'TASKS="runs_local/wave_v2/e2_v3/e2_tasks.jsonl"' in script
    assert 'OUT="runs_local/e2_v3"' in script
    for option in ("--tasks-file", "--run-dir", "--gold-cache", "--ref",
                   "--snapshot"):
        assert f"{option})" in script, option
    assert "--scorer-reading family" in script
    # No path under data/ outside the comments, and not the v1 run directory.
    assert "data/veribim_tasks_e2" not in script
    commands = [line for line in script.splitlines()
                if not line.lstrip().startswith("#")]
    assert not [line for line in commands if "data/" in line], commands
    assert '"runs_local/e2"' not in script
    # The protocol and the one-slot note are unchanged.
    for value in ("--concurrency 16", "--score-workers 6", "taskset -c 14-23",
                  "22 tool rounds and 8192 output tokens"):
        assert value in script, value
    assert "ground_truth_ifc" in script and "refusing to start" in script


def _keys_summarize_reads() -> set[str]:
    """Every literal row key the summariser subscripts, read off its source."""
    tree = ast.parse(inspect.getsource(summarize))
    keys = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Subscript)
                and isinstance(node.value, ast.Name)
                and node.value.id in {"r", "row"}
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, str)):
            keys.add(node.slice.value)
    assert "final" in keys and "tool_calls" in keys, keys
    return keys


def test_null_arm_rows_carry_every_field_the_summariser_reads():
    record = {"task_id": "T-1", "operation": "create", "category": "direct",
              "edit_kind": "create_wall", "input_ifc": "data/corpus/x/a.ifc"}
    rows = null_arm.null_rows("null_edit", [record], paths.PROJECT_ROOT)
    assert len(rows) == 1
    row = rows[0]
    assert row["stop_reason"] == "null"
    assert row["committed"] is True
    assert row["tool_calls"] == row["tool_rounds"] == row["well_formed_calls"] == 0
    assert row["compiling_calls"] == row["running_calls"] == 0
    assert row["edited_ifc"] == str(paths.PROJECT_ROOT / "data/corpus/x/a.ifc")

    # The scorer adds these three; everything else is the arm's own.
    scored = dict(row, score={"geometry": 1.0, "semantics": 1.0, "topology": 1.0,
                              "final": 0.14},
                  score_error=None, final=0.14)
    assert _keys_summarize_reads() <= set(scored)

    summary = summarize("null_edit", [scored], AgentConfig())
    assert summary["n_tasks"] == 1 and summary["n_scored"] == 1
    assert summary["mean_final"] == 0.14
    assert summary["by_category"] == {"direct": 0.14}
    assert summary["commit_rate"] == 1.0
    assert summary["stop_reasons"] == {"null": 1}
    # No tool call was made, so the mechanism rates have no denominator.
    assert summary["schema_validity"] is None and summary["code_run"] is None


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
        else:
            print(f"ok   {test.__name__}", flush=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
