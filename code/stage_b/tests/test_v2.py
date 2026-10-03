"""What Stage B had to learn before it could run a second round.

The v2 task set changed two things the v1 pipeline cannot see. Every task now
carries taxonomy tags, and the checker reads a task under the settings its own
tags ask for, so a material or a type assignment is only visible to it once
those settings are on and an under-specified task is decided by the closing
message rather than by the file. Stage B v1 scored with neither, which would
make an unchanged file a perfect answer for one family and a correct answer
impossible for another, and the preference pairs would then teach the opposite
of the task.

Five claims carry the weight here. The pair rules treat a task answered by
asking as one answered by asking, so its chosen side is the rollout that did
not commit. Sampling and branch repair pass the task's own scorer settings and
its closing message when the family reading is on, and pass neither when it is
off, so a v1 run still measures what it measured. Two scoring workers never
share a gold-cache directory, which is the race that lost trajectories in Stage
A. The pool spreads its quota over whatever cell the caller names and reports
the tags of what it picked. And the assembled dataset counts every pair by tag,
by layer, and by whether the task was under-specified.

Nothing here opens an IFC model, contacts a server, or loads a tokenizer's
weights: the sandbox, the client and the tokenizer are stubs, and the scorer is
replaced by a recorder that reports how it was called.

Run it in the ``l2`` environment, which carries the scorer the four scoring
tests import; ``l2train`` has the training stack and not that one.

    PYTHONPATH=code \
      python -m stage_b.tests.test_v2
"""

from __future__ import annotations

import json
import multiprocessing as mp
import sys
import tempfile
import types
from pathlib import Path

from stage_a import paths
from stage_a.chat_format import ASSISTANT_HEADER, TURN_END

paths.ensure_harness_on_path()

from stage_b import assemble as assemble_module  # noqa: E402
from stage_b import branch as branch_module  # noqa: E402
from stage_b import pairs as pairs_module  # noqa: E402
from stage_b import pool as pool_module  # noqa: E402
from stage_b import sample as sample_module  # noqa: E402
from stage_b.pairs import (chosen_candidates, classify_sample, schema_valid,
                           task_is_underspecified, trajectory_pairs)  # noqa: E402
from stage_b.pool import (load_exclude_ids, parse_cell_keys, parse_weights,
                          select, strata)  # noqa: E402
from stage_b.sample import worker_slot  # noqa: E402


# ----------------------------------------------------------------- fixtures

def tool_call(code: str, call_id: str = "c1") -> dict:
    return {"id": call_id, "type": "function",
            "function": {"name": "run_python", "arguments": json.dumps({"code": code})}}


def rollout(index: int, final: float, commits: int, codes=("print(1)",),
            raised=False, reply: str = "") -> dict:
    """One sampled trajectory, in the shape ``rollouts.jsonl`` holds."""
    messages = [{"role": "system", "content": "system"},
                {"role": "user", "content": f"do it, /sample_{index}/model.ifc"}]
    calls = []
    for turn, code in enumerate(codes):
        messages.append({"role": "assistant", "content": "",
                         "tool_calls": [tool_call(code, f"c{turn}")]})
        messages.append({"role": "tool", "tool_call_id": f"c{turn}",
                         "name": "run_python", "content": "ok"})
        calls.append({"turn": turn, "well_formed": True, "raised": raised,
                      "error_line": "AttributeError: x has no attribute y" if raised else "",
                      "code_chars": len(code)})
    messages.append({"role": "assistant", "content": reply or "done"})
    return {"sample": index, "stop_reason": "stop", "tool_rounds": len(codes),
            "commits": commits, "final": final, "reply": reply or "done",
            "score": {"final": final}, "score_error": None,
            "messages": messages, "calls": calls,
            "guid_use": [], "edited_ifc": f"/work/sample_{index}/model.ifc"}


def asking_rollout(index: int, final: float, reply: str) -> dict:
    """A trajectory that inspected the model, changed nothing and asked."""
    line = rollout(index, final, commits=0, codes=(), reply=reply)
    return line


def task_line(underspecified: bool, samples: list[dict],
              families=("op.create", "scope.single")) -> dict:
    line = {"task_id": "T-001", "operation": "create", "category": "direct",
            "edit_kind": "clarify" if underspecified else "create_box",
            "building_id": "BLD001", "schema": "IFC2X3",
            "instruction": "add a column", "input_ifc": "data/in.ifc",
            "ground_truth_ifc": "data/gold.ifc", "target": {},
            "families": list(families), "samples": samples}
    if underspecified:
        line["families"] = sorted(set(line["families"]) | {"wording.underspecified"})
        line["clarification"] = {"slot": "storey",
                                 "question": "Which storey should the column go on?"}
        line["expected_reply"] = "Which storey should the column go on?"
    else:
        line["clarification"] = None
        line["expected_reply"] = None
    return line


class Score:
    """What the recorder hands back in place of a real score."""

    def __init__(self, final: float = 0.95):
        self.final = final
        self.error = None

    def as_dict(self) -> dict:
        return {"final": self.final, "geometry": 1.0, "semantics": 1.0,
                "topology": 1.0, "n_reference": 1, "n_matched": 1,
                "gt_source": "stub", "error": None}


class Recorder:
    """A stand-in for ``score_prediction`` that reports how it was called."""

    def __init__(self, final: float = 0.95):
        self.calls: list[dict] = []
        self.final = final

    def __call__(self, record, predicted, project_root, models=None, meshes=None,
                 gold_path=None, config=None, reply=""):
        self.calls.append({"task_id": record.get("task_id"), "config": config,
                           "reply": reply, "predicted": str(predicted)})
        return Score(self.final)


class Patched:
    """Swap module attributes for the duration of a block."""

    def __init__(self, **targets):
        self.targets = targets
        self.saved: dict = {}

    def __enter__(self):
        for key, (module, name, value) in self.targets.items():
            self.saved[key] = (module, name, getattr(module, name))
            setattr(module, name, value)
        return self

    def __exit__(self, *exc):
        for module, name, value in self.saved.values():
            setattr(module, name, value)
        return False


# ------------------------------------------------------- the chosen-side rule

def test_underspecified_chosen_is_the_rollout_that_did_not_commit():
    asked = asking_rollout(1, 0.99, "Which storey should the column go on?")
    edited = rollout(2, 0.99, commits=1)
    line = task_line(True, [asked, edited])
    info = {id(s): classify_sample(s) for s in line["samples"]}
    eligible = chosen_candidates(line["samples"], info, 0.90, underspecified=True)
    assert [s["sample"] for s in eligible] == [1], [s["sample"] for s in eligible]

    # The same two rollouts on an ordinary task select the other one.
    plain = chosen_candidates(line["samples"], info, 0.90, underspecified=False)
    assert [s["sample"] for s in plain] == [2], [s["sample"] for s in plain]


def test_no_tool_call_is_schema_valid_only_where_asking_is_the_answer():
    asked = asking_rollout(1, 0.99, "Which storey?")
    assert not schema_valid(asked)
    assert schema_valid(asked, allow_no_calls=True)
    edited = rollout(2, 0.99, commits=1)
    assert schema_valid(edited) and schema_valid(edited, allow_no_calls=True)


def test_a_task_is_under_specified_by_its_tag_or_by_its_two_fields():
    assert task_is_underspecified({"families": ["wording.underspecified"]})
    assert task_is_underspecified({"clarification": {"slot": "storey"},
                                   "expected_reply": "Which storey?"})
    assert not task_is_underspecified({"families": ["op.create"]})
    assert not task_is_underspecified({"clarification": {"slot": "storey"}})
    assert not task_is_underspecified({})  # a v1 rollout line


def test_pairs_on_an_under_specified_task_prefer_asking_over_editing():
    asked = asking_rollout(1, 0.99, "Which storey should the column go on?")
    committed = rollout(2, 0.20, commits=1)
    line = task_line(True, [asked, committed])
    built, stats = trajectory_pairs([line])
    assert len(built) == 1, stats
    pair = built[0]
    assert pair["chosen_final"] == 0.99 and pair["rejected_final"] == 0.20
    assert pair["underspecified"] is True
    assert "wording.underspecified" in pair["families"]
    assert stats["underspecified_pairs"] == 1
    assert stats["tasks_underspecified"] == 1
    # The chosen completion is the asking trajectory, which made no tool call.
    assert not any(m.get("tool_calls") for m in pair["chosen_messages"])


def test_an_ordinary_task_keeps_the_v1_rule_and_carries_its_tags():
    good = rollout(1, 0.98, commits=1)
    bad = rollout(2, 0.30, commits=1)
    line = task_line(False, [good, bad])
    built, stats = trajectory_pairs([line])
    assert len(built) == 1
    pair = built[0]
    assert pair["underspecified"] is False
    assert pair["families"] == ["op.create", "scope.single"]
    assert "underspecified_pairs" not in stats
    assert pair["chosen_final"] == 0.98 and pair["reason"] == "margin"


def test_a_v1_rollout_line_without_tags_is_unchanged():
    good = rollout(1, 0.98, commits=1)
    bad = rollout(2, 0.30, commits=1)
    line = task_line(False, [good, bad])
    for field in ("families", "clarification", "expected_reply"):
        line.pop(field)
    built, _ = trajectory_pairs([line])
    assert len(built) == 1
    assert built[0]["underspecified"] is False and built[0]["families"] == []


# ------------------------------------------------------- the family reading

def run_score_task(family_reading: bool, record: dict, reply: str) -> Recorder:
    """Drive ``_score_task`` with the scorer and the gold cache replaced."""
    from stage_a import goldmodels, scoring

    recorder = Recorder()
    with tempfile.TemporaryDirectory() as tmp:
        predicted = Path(tmp) / "model.ifc"
        predicted.write_text("ISO-10303-21;")
        saved = dict(sample_module._SC)
        sample_module._SC.update(project_root=Path(tmp), cache=object(),
                                 family_reading=family_reading)
        with Patched(gold=(goldmodels, "resolve_gold",
                           lambda rec, cache, root: predicted),
                     score=(scoring, "score_prediction", recorder)):
            out = sample_module._score_task((record, [str(predicted)], [reply]))
        sample_module._SC.clear()
        sample_module._SC.update(saved)
    assert out and out[0]["score"]["final"] == 0.95, out
    return recorder


def test_sampling_passes_the_task_settings_and_the_reply_under_the_family_reading():
    record = {"task_id": "T-001", "operation": "update", "category": "direct",
              "families": ["op.update.material"], "input_ifc": "data/in.ifc",
              "ground_truth_ifc": "data/gold.ifc", "target": {}}
    recorder = run_score_task(True, record, "the wall now uses Concrete")
    call = recorder.calls[0]
    assert call["config"] is not None
    assert call["config"].properties_include_material is True
    assert "IfcRelAssociatesMaterial" in call["config"].topology_relations_extra
    assert call["reply"] == "the wall now uses Concrete"


def test_sampling_passes_neither_under_the_published_reading():
    record = {"task_id": "T-001", "operation": "update", "category": "direct",
              "families": ["op.update.material"], "input_ifc": "data/in.ifc",
              "ground_truth_ifc": "data/gold.ifc", "target": {}}
    recorder = run_score_task(False, record, "the wall now uses Concrete")
    call = recorder.calls[0]
    assert call["config"] is None, call["config"]
    assert call["reply"] == ""


def test_score_task_still_accepts_the_v1_two_field_payload():
    from stage_a import goldmodels, scoring

    record = {"task_id": "T-001", "operation": "create", "category": "direct",
              "input_ifc": "data/in.ifc", "ground_truth_ifc": "data/gold.ifc",
              "target": {}}
    recorder = Recorder()
    with tempfile.TemporaryDirectory() as tmp:
        predicted = Path(tmp) / "model.ifc"
        predicted.write_text("ISO-10303-21;")
        saved = dict(sample_module._SC)
        sample_module._SC.update(project_root=Path(tmp), cache=object(),
                                 family_reading=False)
        with Patched(gold=(goldmodels, "resolve_gold",
                           lambda rec, cache, root: predicted),
                     score=(scoring, "score_prediction", recorder)):
            out = sample_module._score_task((record, [str(predicted)]))
        sample_module._SC.clear()
        sample_module._SC.update(saved)
    assert out[0]["score"]["final"] == 0.95
    assert recorder.calls[0]["reply"] == ""


# --------------------------------------------------------- branch repair

class StubSnippet:
    def __init__(self, ok: bool = True, commits: int = 1):
        self.ok = ok
        self.commits = commits
        self.error = "" if ok else "Traceback\nAttributeError: nope"

    def raw_output(self, capture_stdout: bool = True) -> str:
        return "ok"


class StubSandbox:
    """Enough of the sandbox for the repair loop: it writes the working file."""

    def __init__(self, input_ifc, working_ifc, log_file=None):
        self.working = Path(working_ifc)
        self.executed: list[str] = []

    def start(self):
        self.working.parent.mkdir(parents=True, exist_ok=True)
        self.working.write_text("ISO-10303-21;")

    def execute(self, code, timeout=None):
        self.executed.append(code)
        return StubSnippet()

    def close(self):
        pass


class StubResponse:
    def __init__(self, content: str, code: str | None):
        self.content = content
        self.tool_calls = [tool_call(code)] if code is not None else []


class StubClient:
    """First a clean edit turn, then a closing message that ends the trajectory."""

    def __init__(self, closing: str):
        self.replies = [StubResponse("", "ifc.commit()"), StubResponse(closing, None)]

    def chat(self, messages, tools=None, temperature=None, top_p=None,
             max_tokens=None):
        return self.replies.pop(0) if self.replies else StubResponse("done", None)


def run_branch_once(family_reading: bool, closing: str) -> Recorder:
    from modifc_harness.config import AgentConfig
    from stage_a import goldmodels, scoring

    record = {"task_id": "T-001", "operation": "update", "category": "direct",
              "families": ["op.update.material"], "input_ifc": "data/in.ifc",
              "ground_truth_ifc": "data/gold.ifc", "target": {},
              "gold_script": "", "verification": {}}
    job = {"task_id": "T-001", "operation": "update", "category": "direct",
           "edit_kind": "assign_material", "building_id": "BLD001",
           "schema": "IFC2X3", "sample": 1, "turn": 1,
           "error_class": "invented_attribute", "error_line": "AttributeError",
           "prefix_messages": [{"role": "system", "content": "system"},
                               {"role": "user", "content": "do it"},
                               {"role": "assistant", "content": "",
                                "tool_calls": [tool_call("print(1)")]},
                               {"role": "tool", "tool_call_id": "c1",
                                "name": "run_python", "content": "ok"}],
           "rejected_turn": {"role": "assistant", "content": "",
                             "tool_calls": [tool_call("boom()")]},
           "input_ifc": "data/in.ifc", "ground_truth_ifc": "data/gold.ifc",
           "target": {}, "instruction": "assign the material",
           "task_record": record}
    recorder = Recorder()
    agent = AgentConfig(max_tool_rounds=4, tool_timeout=10.0, temperature=0.8,
                        top_p=0.95, max_tokens=256, max_tool_output_chars=1000)
    with tempfile.TemporaryDirectory() as tmp:
        gold = Path(tmp) / "gold.ifc"
        gold.write_text("ISO-10303-21;")
        with Patched(sandbox=(branch_module, "Sandbox", StubSandbox),
                     gold=(goldmodels, "resolve_gold",
                           lambda rec, cache, root: gold),
                     score=(scoring, "score_prediction", recorder)):
            out = branch_module.branch_one(
                job, StubClient(closing), agent, Path(tmp) / "work",
                Path(tmp), attempts=1, disk_floor_gb=0.0,
                family_reading=family_reading)
    assert out["chosen_final"] == 0.95, out
    return recorder


def test_branch_repair_passes_the_task_settings_and_the_closing_message():
    recorder = run_branch_once(True, "the wall now uses Concrete")
    call = recorder.calls[0]
    assert call["config"] is not None
    assert call["config"].properties_include_material is True
    assert call["reply"] == "the wall now uses Concrete"


def test_branch_repair_passes_neither_under_the_published_reading():
    recorder = run_branch_once(False, "the wall now uses Concrete")
    call = recorder.calls[0]
    assert call["config"] is None
    assert call["reply"] == ""


def test_the_closing_message_is_the_last_assistant_message():
    messages = [{"role": "user", "content": "do it"},
                {"role": "assistant", "content": "first"},
                {"role": "tool", "content": "ok"},
                {"role": "assistant", "content": "which storey?"}]
    assert branch_module.last_assistant_reply(messages) == "which storey?"
    assert branch_module.last_assistant_reply([{"role": "user", "content": "x"}]) == ""


# ------------------------------------------------------------ cache slots

def _slot_probe(_) -> tuple[str, int]:
    import os

    return worker_slot(), os.getpid()


def test_two_pool_workers_never_share_a_cache_slot():
    context = mp.get_context("fork")
    with context.Pool(processes=4) as pool:
        seen = pool.map(_slot_probe, range(16), chunksize=1)
    by_slot: dict[str, set] = {}
    for slot, pid in seen:
        by_slot.setdefault(slot, set()).add(pid)
    pids = {pid for _, pid in seen}
    assert len(pids) > 1, seen
    assert len(by_slot) == len(pids), (by_slot, pids)
    assert all(len(owners) == 1 for owners in by_slot.values()), by_slot
    # The main process is not a pool worker and falls back to its pid.
    assert worker_slot().startswith("slotpid")


def test_each_branch_thread_gets_its_own_cache_directory():
    import threading

    built: list[Path] = []
    branch_module.set_gold_cache(factory=lambda slot: Path(f"/cache/slot{slot}"))
    try:
        seen: list[Path] = []
        lock = threading.Lock()

        def use():
            cache = branch_module.gold_cache()
            with lock:
                seen.append(cache)
                built.append(cache)

        threads = [threading.Thread(target=use) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        assert len(set(seen)) == 4, seen
    finally:
        branch_module.set_gold_cache(None, None)
        branch_module._LOCAL.__dict__.clear()
    # A bare cache is the v1 call and every thread shares it, as it did.
    shared = object()
    branch_module.set_gold_cache(shared)
    try:
        assert branch_module.gold_cache() is shared
    finally:
        branch_module.set_gold_cache(None, None)


# ------------------------------------------------------------------- pool

def fake_tasks(n: int = 60) -> list[dict]:
    out = []
    kinds = {"create": ("create_box", "clarify"), "delete": ("delete",),
             "update": ("rename", "assign_material")}
    for index in range(n):
        operation = ("create", "delete", "update")[index % 3]
        kind = kinds[operation][index % len(kinds[operation])]
        families = [f"op.{operation}", "scope.single", "model.schema.ifc2x3"]
        record = {"task_id": f"T-{index:03d}", "operation": operation,
                  "category": ("direct", "spatial")[index % 2],
                  "building_id": f"BLD{100 + index % 4:03d}", "edit_kind": kind,
                  "tier": "single", "split": "train",
                  "source_model": {"schema": "IFC2X3"},
                  "families": families, "clarification": None,
                  "expected_reply": None}
        if kind == "clarify":
            record["families"] = families + ["wording.underspecified"]
            record["clarification"] = {"slot": "storey"}
            record["expected_reply"] = "Which storey?"
        out.append(record)
    return out


def test_weights_and_cell_keys_parse_and_default_to_the_v1_settings():
    assert parse_weights("create=0.45,delete=0.35,update=0.20") == {
        "create": 0.45, "delete": 0.35, "update": 0.20}
    assert parse_weights("") == pool_module.OPERATION_WEIGHTS
    assert parse_weights(None) == pool_module.OPERATION_WEIGHTS
    assert parse_cell_keys("category,edit_kind,building_id") == (
        "category", "edit_kind", "building_id")
    assert parse_cell_keys("") == pool_module.DEFAULT_CELL_KEYS
    try:
        parse_weights("create")
    except ValueError:
        pass
    else:
        raise AssertionError("a weight without a share was accepted")


def test_exclude_ids_read_a_json_list_and_a_jsonl_file():
    with tempfile.TemporaryDirectory() as tmp:
        first = Path(tmp) / "a.json"
        first.write_text(json.dumps(["T-001", "T-002"]))
        second = Path(tmp) / "b.jsonl"
        second.write_text('{"task_id": "T-003"}\n{"task_id": "T-004"}\n')
        third = Path(tmp) / "c.jsonl"
        third.write_text('"T-005"\n')
        ids = load_exclude_ids([first, second, third])
        assert ids == {"T-001", "T-002", "T-003", "T-004", "T-005"}, ids
        assert load_exclude_ids([]) == set()


def test_excluded_ids_do_not_reach_the_pool():
    with tempfile.TemporaryDirectory() as tmp:
        tasks_file = Path(tmp) / "tasks.jsonl"
        tasks_file.write_text("".join(json.dumps(t) + "\n" for t in fake_tasks()))
        drop = Path(tmp) / "drop.json"
        drop.write_text(json.dumps(["T-000", "T-003"]))
        kept = pool_module.load_train_tasks(tasks_file, "train",
                                            load_exclude_ids([drop]))
        assert len(kept) == 58
        assert not {"T-000", "T-003"} & {t["task_id"] for t in kept}


def test_edit_kind_in_the_cell_key_spreads_the_quota_over_edit_kinds():
    tasks = fake_tasks(120)
    weights = {"create": 0.45, "delete": 0.35, "update": 0.20}
    narrow = select(tasks, size=20, weights=weights,
                    cell_keys=("category", "building_id"))
    wide = select(tasks, size=20, weights=weights,
                  cell_keys=("category", "edit_kind", "building_id"))
    assert len(narrow) == len(wide) == 20
    clarify_narrow = sum(1 for t in narrow if t["edit_kind"] == "clarify")
    clarify_wide = sum(1 for t in wide if t["edit_kind"] == "clarify")
    assert clarify_wide >= clarify_narrow, (clarify_narrow, clarify_wide)
    # The operation quota is the same either way.
    for picked in (narrow, wide):
        counts = {}
        for task in picked:
            counts[task["operation"]] = counts.get(task["operation"], 0) + 1
        assert counts["create"] == 9 and counts["delete"] == 7, counts


def test_strata_reports_tags_layers_edit_kinds_and_the_realised_settings():
    picked = select(fake_tasks(120), size=30,
                    weights={"create": 0.45, "delete": 0.35, "update": 0.20},
                    cell_keys=("category", "edit_kind", "building_id"))
    report = strata(picked, weights={"create": 0.45, "delete": 0.35, "update": 0.20},
                    cell_keys=("category", "edit_kind", "building_id"))
    for field in ("by_family", "by_layer", "by_edit_kind", "weights", "cell_keys",
                  "underspecified"):
        assert field in report, field
    assert report["by_layer"]["op"] == report["n"]
    assert report["cell_keys"] == ["category", "edit_kind", "building_id"]
    assert report["weights"]["create"] == 0.45
    assert report["by_family"]["scope.single"] == report["n"]
    assert report["underspecified"] == sum(1 for t in picked
                                           if t["edit_kind"] == "clarify")
    # v1 callers pass neither, and the report then names neither.
    plain = strata(picked)
    assert "weights" not in plain and "cell_keys" not in plain


# --------------------------------------------------------------- assembly

class StubTokenizer:
    """A character-level tokenizer over the canonical template's structure.

    The assembler needs three things from a tokenizer: a render that grows by
    whole messages, one assistant header per assistant turn, and offsets it can
    map back to characters. One token per character gives all three exactly,
    which is what the masking assertions are checked against.
    """

    def apply_chat_template(self, messages, tools=None, tokenize=False,
                            add_generation_prompt=False, chat_template=None):
        parts = []
        for message in messages:
            if message.get("role") == "assistant":
                body = message.get("content") or ""
                for call in message.get("tool_calls") or ():
                    arguments = (call.get("function") or {}).get("arguments") or {}
                    body += "\n" + str(arguments.get("code", ""))
                parts.append(ASSISTANT_HEADER + body + TURN_END)
            else:
                parts.append(f"<|im_start|>{message['role']}\n"
                             f"{message.get('content') or ''}" + TURN_END)
        text = "".join(parts)
        return text + ASSISTANT_HEADER if add_generation_prompt else text

    def __call__(self, text, add_special_tokens=False, return_offsets_mapping=False):
        out = {"input_ids": [ord(c) % 4096 for c in text]}
        if return_offsets_mapping:
            out["offset_mapping"] = [(i, i + 1) for i in range(len(text))]
        return out


def test_the_assembled_report_counts_tags_layers_and_asking_tasks():
    asked = asking_rollout(1, 0.99, "Which storey should the column go on?")
    committed = rollout(2, 0.20, commits=1)
    under = task_line(True, [asked, committed])
    plain = task_line(False, [rollout(1, 0.98, commits=1), rollout(2, 0.30, commits=1)])
    plain["task_id"] = "T-002"
    built, _ = trajectory_pairs([under, plain])
    assert len(built) == 2

    stub = types.ModuleType("transformers")
    stub.AutoTokenizer = types.SimpleNamespace(
        from_pretrained=lambda _path: StubTokenizer())
    saved = sys.modules.get("transformers")
    sys.modules["transformers"] = stub
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pairs_file = Path(tmp) / "pairs.jsonl"
            pairs_file.write_text(
                "".join(json.dumps(p, ensure_ascii=False) + "\n" for p in built))
            report = assemble_module.assemble(pairs_file, Path(tmp) / "out",
                                              Path("/does/not/matter"), max_seq=8192)
            entries = [json.loads(line) for line
                       in (Path(tmp) / "out/dpo_pairs.jsonl").read_text().splitlines()]
    finally:
        if saved is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = saved

    assert report["kept"] == 2, report["dropped"]
    assert report["underspecified_pairs"] == 1, report["underspecified_pairs"]
    assert report["by_family"]["wording.underspecified"] == 1
    assert report["by_family"]["op.create"] == 2
    assert report["by_layer"]["op"] == 2 and report["by_layer"]["wording"] == 1
    assert all("families" in e and "underspecified" in e for e in entries)
    assert sum(e["underspecified"] for e in entries) == 1
    assert all(any(e["chosen_completion_mask"]) for e in entries)


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
        else:
            print(f"ok   {test.__name__}", flush=True)
    print(f"\n{len(tests) - failed} passed, {failed} failed", flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
