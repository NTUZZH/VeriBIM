"""The agent loop's training-only stops, and the rollout's instruments.

Everything here runs on CPU against a scripted client and a stub sandbox. No
inference server is contacted, no IFC model is opened, and the base model's
weights are never loaded; the last test reads the tokenizer alone, which it
needs because the transcript budget is only worth having if it counts what the
encoder counts.

The first test is the one that matters most. Every new setting defaults to off,
so an evaluation run must take exactly the path it took before the settings
existed: the same requests, the same transcript, the same stop. It is checked
twice, against a frozen expectation and, when the earlier revision of the module
is reachable, against that revision run through the same fakes.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from stage_a import paths

paths.ensure_harness_on_path()

import modifc_harness  # noqa: E402,F401  (the package the reference module needs)
from modifc_harness import agent as agent_module  # noqa: E402
from modifc_harness.client import ChatClient, ChatResponse  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.prompts import TOOL_NAME, TOOL_SCHEMA  # noqa: E402
from modifc_harness.tasks import Task  # noqa: E402

from stage_c.rollout import (assistant_code, code_indicators, counting_messages,
                             gold_resolution_keys, make_count_tokens)  # noqa: E402

#: Where an earlier revision of ``agent.py`` can be found, for the differential
#: half of the defaults check. Unset is normal and the check still runs.
REFERENCE_AGENT_ENV = "VERIBIM_REFERENCE_AGENT"

GUID_A = "1JzwEp1_mQDupWlAuQRqBS"
GUID_B = "3$f9rYNXRt6nBcyBanb7Ua"
GUID_C = "0ELnodLOr8mQ4vsWfSh2UY"


# --------------------------------------------------------------------------
# fakes


class ScriptedClient:
    """A client that answers from a list and records what it was asked."""

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0.0, top_p=1.0,
             max_tokens=None, **extra):
        self.calls.append({"messages": copy.deepcopy(messages),
                           "tools": copy.deepcopy(tools),
                           "temperature": temperature, "top_p": top_p,
                           "max_tokens": max_tokens, "extra": dict(extra)})
        if not self.script:
            raise AssertionError("the scripted client ran out of responses")
        return copy.deepcopy(self.script.pop(0))


class StubSnippet:
    def __init__(self, text: str, commits: int = 0):
        self.text = text
        self.commits = commits
        self.total_commits = commits

    def raw_output(self, capture_stdout: bool = True) -> str:
        return self.text


def make_sandbox(responder):
    """A stand-in for the sandbox whose output one function decides."""

    class StubSandbox:
        def __init__(self, input_ifc, working_ifc, log_file,
                     python_executable=None):
            self.copy_seconds = 0.0
            self.executed: list[str] = []

        def start(self) -> None:
            return None

        def execute(self, code, timeout):
            self.executed.append(code)
            return responder(code, len(self.executed))

        def close(self) -> None:
            return None

    return StubSandbox


def tool_call(call_id: str, code: str, name: str = TOOL_NAME) -> dict:
    """A tool call in the shape the server returns one, arguments as a string."""
    return {"id": call_id, "type": "function",
            "function": {"name": name,
                         "arguments": json.dumps({"code": code})}}


def response(content="", calls=None, finish="stop", prompt=100, completion=20,
             logprobs=None) -> ChatResponse:
    return ChatResponse(content=content, tool_calls=list(calls or []),
                        finish_reason=finish, prompt_tokens=prompt,
                        completion_tokens=completion,
                        token_logprobs=list(logprobs or []))


def a_task(task_id: str = "CHN-CWD-DIR-B03-001") -> Task:
    root = paths.PROJECT_ROOT
    return Task(task_id=task_id, operation="create", category="direct",
                prompt="Add a wall.", input_ifc=root / "in.ifc",
                ground_truth_ifc=root / "gold.ifc", target={}, tags=[])


def run(module, config: AgentConfig, script, responder, **kwargs):
    """One trajectory through ``module``, with the fakes in place."""
    client = ScriptedClient(script)
    saved = module.Sandbox
    module.Sandbox = make_sandbox(responder)
    try:
        result = module.run_task(task=a_task(), working_ifc=paths.PROJECT_ROOT / "w.ifc",
                                 client=client, agent_config=config,
                                 log_file=paths.PROJECT_ROOT / "sandbox.log",
                                 **kwargs)
    finally:
        module.Sandbox = saved
    return client, result


def echo(code: str, call_index: int) -> StubSnippet:
    return StubSnippet(f"ran: {code}", commits=1 if "commit()" in code else 0)


# --------------------------------------------------------------------------
# 1. defaults change nothing


def default_episode():
    """Three tool rounds and a closing answer, covering every call shape."""
    return [
        response(calls=[tool_call("c1", "print(1)")], finish="tool_calls",
                 prompt=100, completion=20),
        response(calls=[tool_call("c2", "commit()"),
                        tool_call("c3", "print(3)", name="other_tool")],
                 finish="tool_calls", prompt=200, completion=30),
        response(calls=[{"id": "c4", "type": "function",
                         "function": {"name": TOOL_NAME, "arguments": "not json"}}],
                 finish="tool_calls", prompt=300, completion=40),
        response(content="done", finish="stop", prompt=400, completion=50),
    ]


def observed(client: ScriptedClient, result) -> dict:
    """Everything about a run that must not move, with the timings dropped."""
    iterations = copy.deepcopy(result.iterations)
    for record in iterations:
        record.pop("duration_seconds", None)
    return {
        "requests": client.calls,
        "stop_reason": result.stop_reason,
        "model_output": result.model_output,
        "messages": copy.deepcopy(result.messages),
        "iterations": iterations,
        "tool_rounds": result.tool_rounds,
        "tool_calls": result.tool_calls,
        "llm_calls": result.llm_calls,
        "commits": result.commits,
        "prompt_tokens": result.prompt_tokens,
        "completion_tokens": result.completion_tokens,
        "finish_reasons": list(result.finish_reasons),
        "truncated_tool_outputs": result.truncated_tool_outputs,
        "reasoning_chars": result.reasoning_chars,
        "error": result.error,
        "error_type": result.error_type,
        "extra": copy.deepcopy(result.extra),
    }


def load_reference_agent():
    """The earlier revision of the agent module, when one is reachable.

    It is loaded under a name inside the harness package so that its relative
    imports resolve to the package's own client, config and sandbox modules.
    """
    location = os.environ.get(REFERENCE_AGENT_ENV, "")
    if not location or not Path(location).is_file():
        return None
    name = "modifc_harness._reference_agent"
    spec = importlib.util.spec_from_file_location(name, location)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_defaults_are_unchanged():
    config = AgentConfig(max_tool_rounds=22, max_tokens=8192,
                         max_tool_output_chars=4000)
    client, result = run(agent_module, config, default_episode(), echo)
    seen = observed(client, result)

    assert seen["stop_reason"] == "completed"
    assert seen["tool_rounds"] == 3
    assert seen["llm_calls"] == 4
    assert seen["tool_calls"] == 2
    assert seen["commits"] == 1
    assert seen["extra"] == {}, "no new field is on, so nothing is recorded"

    # Every request carries the configured output cap and nothing beyond the
    # four parameters the protocol has always sent.
    assert len(seen["requests"]) == 4
    for call in seen["requests"]:
        assert call["max_tokens"] == 8192
        assert call["temperature"] == 0.0 and call["top_p"] == 1.0
        assert call["tools"] == [TOOL_SCHEMA]
        assert call["extra"] == {}

    roles = [m["role"] for m in seen["messages"]]
    assert roles == ["system", "user",
                     "assistant", "tool",
                     "assistant", "tool", "tool",
                     "assistant", "tool",
                     "assistant"]
    assert seen["messages"][3]["content"] == "ran: print(1)"
    assert seen["messages"][5]["content"] == "ran: commit()"
    assert seen["messages"][6]["content"].startswith("Unknown tool 'other_tool'")
    assert seen["messages"][8]["content"].startswith(
        "The tool call could not be parsed.")
    assert [c["ok"] for r in seen["iterations"] for c in r["tool_calls"]] == \
        [True, True, False, False]

    reference = load_reference_agent()
    if reference is None:
        return
    ref_client, ref_result = run(reference, config, default_episode(), echo)
    assert observed(ref_client, ref_result) == seen, (
        "the defaults do not reproduce the earlier revision's run")


# --------------------------------------------------------------------------
# 2. the transcript budget


def test_token_budget_caps_the_request_and_stops():
    config = AgentConfig(max_tokens=400, max_transcript_tokens=1000,
                         min_turn_tokens=200, max_tool_output_chars=100)
    counts = [100, 700, 900]
    seen: list[int] = []

    def count_tokens(messages):
        seen.append(len(messages))
        return counts[len(seen) - 1]

    script = [response(calls=[tool_call(f"c{i}", f"print({i})")],
                       finish="tool_calls") for i in range(1, 4)]
    client, result = run(agent_module, config, script, echo,
                         count_tokens=count_tokens)

    # 900 tokens are left inside the budget and then 300; the cap is the
    # configured one until what is left falls below it.
    assert [c["max_tokens"] for c in client.calls] == [400, 300]
    assert result.stop_reason == "token_budget"
    assert result.error_type == "TokenBudget"
    assert result.error == "transcript at 900 tokens of 1000"
    assert result.extra["token_budget_estimate"] == 900
    assert len(client.calls) == 2, "the third request is never sent"


def test_token_budget_shrinks_the_output_cap():
    config = AgentConfig(max_tokens=600, max_transcript_tokens=1000,
                         min_turn_tokens=50, max_tool_output_chars=100)
    counts = iter([100, 600, 800])

    script = [response(calls=[tool_call(f"c{i}", f"print({i})")],
                       finish="tool_calls") for i in range(1, 3)]
    script.append(response(content="done", finish="stop"))
    client, result = run(agent_module, config, script, echo,
                         count_tokens=lambda messages: next(counts))
    assert [c["max_tokens"] for c in client.calls] == [600, 400, 200]
    assert result.stop_reason == "completed"


def test_the_unread_tool_results_of_the_last_round_are_dropped():
    """A run that stops on the budget returns no tool result nobody read.

    The results of the last round arrive after the turn that asked for them
    and no later turn is ever conditioned on them. Training scores assistant
    tokens only, so they would add length to the sequence and nothing else.
    """
    config = AgentConfig(max_tokens=200, max_transcript_tokens=1000,
                         min_turn_tokens=100, max_tool_output_chars=100,
                         max_tool_rounds=22)
    counts = iter([100, 400, 950])
    script = [response(calls=[tool_call(f"c{i}a", f"print({i})"),
                              tool_call(f"c{i}b", f"print(-{i})")],
                       finish="tool_calls") for i in range(1, 4)]
    client, result = run(agent_module, config, script, echo,
                         count_tokens=lambda messages: next(counts))

    assert result.stop_reason == "token_budget"
    assert len(client.calls) == 2, "the third request is never sent"
    # Two rounds ran, each of two calls: system, user, and then an assistant
    # message and two tool messages per round. The two tool messages of the
    # second round are the ones no turn read.
    assert [m["role"] for m in result.messages] == [
        "system", "user", "assistant", "tool", "tool", "assistant"]
    assert result.messages[-1]["tool_calls"]
    assert result.extra["unread_tool_results"] == 2
    assert result.tool_rounds == 2
    assert len(result.iterations) == 2
    assert len(result.iterations[-1]["tool_calls"]) == 2
    assert [c["args"]["code"] for c in result.iterations[-1]["tool_calls"]] == \
        ["print(2)", "print(-2)"]


def test_the_tool_results_stay_when_the_budget_is_off():
    """The evaluation protocol returns the transcript it always returned."""
    config = AgentConfig(max_tokens=8192, max_tool_rounds=22, dup_stop=2)
    script = [response(calls=[tool_call(f"c{i}", "print(1)")],
                       finish="tool_calls") for i in range(1, 4)]
    client, result = run(agent_module, config, script, echo)

    assert result.stop_reason == "duplicate_loop"
    assert [m["role"] for m in result.messages] == [
        "system", "user", "assistant", "tool", "assistant", "tool"]
    assert result.messages[-1]["content"] == "ran: print(1)"
    assert "unread_tool_results" not in result.extra
    assert result.extra == {"dup_max_count": 2}


class GreedyClient:
    """A model that spends its whole output allowance and calls the tool."""

    def __init__(self):
        self.calls: list[dict] = []

    def chat(self, messages, tools=None, temperature=0.0, top_p=1.0,
             max_tokens=None, **extra):
        self.calls.append({"max_tokens": max_tokens})
        arguments = json.dumps({"code": "print(1)"})
        return response(content="x" * max(0, max_tokens - len(arguments)),
                        calls=[tool_call(f"c{len(self.calls)}", "print(1)")],
                        finish="tool_calls")


def dense_count(messages) -> int:
    """One token per character, which is denser than any real tokenizer."""
    total = 0
    for message in messages:
        total += len(message.get("content") or "")
        for call in message.get("tool_calls") or []:
            total += len(call["function"]["arguments"])
    return total


def test_the_finished_transcript_stays_inside_the_budget():
    """The returned transcript is bounded, and this is the bound.

    Every request is capped at what is left inside the budget, so the
    transcript is inside the budget at the end of every model turn. The tool
    results that land after the last turn are the only thing that could carry
    it past the budget, and they are dropped, so the trainer sees at most the
    budget plus one assistant turn's envelope.
    """
    config = AgentConfig(max_tokens=300, max_transcript_tokens=4000,
                         min_turn_tokens=100, max_tool_output_chars=200,
                         max_tool_rounds=22)
    client = GreedyClient()
    saved = agent_module.Sandbox
    agent_module.Sandbox = make_sandbox(lambda code, index: StubSnippet("y" * 200))
    try:
        result = agent_module.run_task(
            task=a_task(), working_ifc=paths.PROJECT_ROOT / "w.ifc",
            client=client, agent_config=config,
            log_file=paths.PROJECT_ROOT / "sandbox.log",
            count_tokens=dense_count)
    finally:
        agent_module.Sandbox = saved
    assert result.stop_reason == "token_budget"
    assert result.messages[-1]["role"] == "assistant"
    assert result.extra["unread_tool_results"] == 1
    assert dense_count(result.messages) <= config.max_transcript_tokens


def test_a_budget_without_a_counter_is_refused():
    """The budget's bound is only as good as the count it stops on.

    Without a counter the loop would have to guess the transcript length, and
    the guess is empty before the first response arrives: the opening messages
    would never be charged, the first request would be capped at the whole
    budget, and a single long turn would return a transcript several times the
    budget. The run is refused instead, before the sandbox is started.
    """
    config = AgentConfig(max_tokens=8192, max_transcript_tokens=1000,
                         min_turn_tokens=256)
    script = [response(content="x" * 40000, finish="stop")]
    try:
        run(agent_module, config, script, echo)
    except ValueError as exc:
        assert "count_tokens" in str(exc), exc
    else:
        raise AssertionError("a budget with no counter must be refused")


def test_token_budget_off_by_default():
    config = AgentConfig(max_tokens=8192)
    script = [response(content="done", finish="stop")]

    def never(messages):
        raise AssertionError("the counter must not be called when the budget is off")

    client, result = run(agent_module, config, script, echo, count_tokens=never)
    assert client.calls[0]["max_tokens"] == 8192
    assert result.extra == {}


# --------------------------------------------------------------------------
# 3. the repeat stop


def loop_script(codes):
    return [response(calls=[tool_call(f"c{i}", code)], finish="tool_calls")
            for i, code in enumerate(codes)] + [response(content="done")]


def test_duplicate_loop_stops_on_the_third_repeat():
    config = AgentConfig(dup_stop=3)
    client, result = run(agent_module, config,
                         loop_script(["print(1)"] * 4), echo)
    assert result.stop_reason == "duplicate_loop"
    assert result.error_type == "DuplicateLoop"
    assert result.error == "the same tool call and output repeated 3 times"
    assert result.extra["dup_max_count"] == 3
    assert result.tool_rounds == 3
    assert len(client.calls) == 3


def test_duplicate_loop_needs_the_same_output_too():
    config = AgentConfig(dup_stop=3)
    codes = ["print(1)", "print(1)", "print(2)", "print(3)"]
    _, result = run(agent_module, config, loop_script(codes), echo)
    assert result.stop_reason == "completed"
    assert result.extra["dup_max_count"] == 2


def test_duplicate_loop_ignores_the_output_when_the_code_repeats_differently():
    """Same code, different answers: the model is making progress, not looping."""
    config = AgentConfig(dup_stop=2)
    counter = {"n": 0}

    def changing(code, call_index):
        counter["n"] += 1
        return StubSnippet(f"answer {counter['n']}")

    _, result = run(agent_module, config, loop_script(["print(1)"] * 3), changing)
    assert result.stop_reason == "completed"
    assert result.extra["dup_max_count"] == 1


def test_duplicate_loop_off_by_default():
    config = AgentConfig()
    _, result = run(agent_module, config, loop_script(["print(1)"] * 5), echo)
    assert result.stop_reason == "completed"
    assert result.extra == {}


def test_duplicate_loop_ignores_malformed_calls():
    config = AgentConfig(dup_stop=2)
    bad = {"id": "x", "type": "function",
           "function": {"name": "other_tool", "arguments": "{}"}}
    script = [response(calls=[dict(bad, id=f"x{i}")], finish="tool_calls")
              for i in range(4)] + [response(content="done")]
    _, result = run(agent_module, config, script, echo)
    assert result.stop_reason == "completed"
    assert result.extra["dup_max_count"] == 0


# --------------------------------------------------------------------------
# 4. log-probabilities


def test_client_payload_carries_logprobs_only_when_asked():
    client = ChatClient(base_url="http://server.invalid/v1", model="m")
    sent: list[dict] = []

    def fake_post(path, payload):
        sent.append(copy.deepcopy(payload))
        return {"choices": [{"message": {"content": "hi"},
                             "finish_reason": "stop",
                             "logprobs": {"content": [
                                 {"token": "h", "logprob": -0.5},
                                 {"token": "i", "logprob": -1.25}]}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2}}

    client._post = fake_post
    plain = client.chat([{"role": "user", "content": "x"}], tools=[TOOL_SCHEMA])
    assert "logprobs" not in sent[-1]
    assert plain.token_logprobs == []

    asked = client.chat([{"role": "user", "content": "x"}], tools=[TOOL_SCHEMA],
                        logprobs=True)
    assert sent[-1]["logprobs"] is True
    assert asked.token_logprobs == [-0.5, -1.25]
    assert asked.tokens == ["h", "i"]
    assert asked.token_ids == []


def test_run_task_keeps_per_turn_logprobs():
    config = AgentConfig()
    script = [response(calls=[tool_call("c1", "print(1)")], finish="tool_calls",
                       logprobs=[-0.1, -0.2]),
              response(content="done", finish="stop", logprobs=[-0.3])]
    client, result = run(agent_module, config, copy.deepcopy(script), echo,
                         request_logprobs=True)
    assert all(call["extra"] == {"logprobs": True} for call in client.calls)
    assert result.extra["turn_logprobs"] == [[-0.1, -0.2], [-0.3]]
    assert result.iterations[0]["logprobs"] == [-0.1, -0.2]

    client, result = run(agent_module, config, copy.deepcopy(script), echo)
    assert all(call["extra"] == {} for call in client.calls)
    assert "turn_logprobs" not in result.extra
    assert "logprobs" not in result.iterations[0]


# --------------------------------------------------------------------------
# 5. the rollout's instruments


def iterations_with(codes):
    return [{"tool_calls": [{"name": TOOL_NAME, "args": {"code": code}}]}
            for code in codes]


def test_indicators_on_an_update_task():
    task = {"task_id": "t", "operation": "update",
            "target": {"entity_type": "IfcProduct",
                       "guids": [GUID_A, GUID_B, GUID_C]}}
    codes = [f"e = ifc.by_guid('{GUID_A}')",
             f"f = ifc.by_guid('{GUID_B}')\ng = ifc.by_guid('{'z' * 22}')"]
    written, distinct = code_indicators(task, iterations_with(codes))
    assert abs(written - 2 / 3) < 1e-9
    assert distinct == 3


def test_indicators_use_the_instruction_for_a_create_task():
    """A create task's target ids are the reference script's, so the host is used."""
    task = {"task_id": "t", "operation": "create",
            "instruction": f"Add a wall on the storey with GlobalId '{GUID_C}'.",
            "target": {"guids": [GUID_A, GUID_B]}}
    assert gold_resolution_keys(task) == [GUID_C]
    written, distinct = code_indicators(
        task, iterations_with([f"s = ifc.by_guid('{GUID_C}')"]))
    assert written == 1.0 and distinct == 1


def test_indicators_are_none_without_keys():
    task = {"task_id": "t", "operation": "create", "instruction": "Add a wall.",
            "target": {"guids": [GUID_A]}}
    written, distinct = code_indicators(task, iterations_with(["print(1)"]))
    assert written is None and distinct == 0


def test_indicators_ignore_malformed_calls_and_long_tokens():
    task = {"task_id": "t", "operation": "delete", "target": {"guids": [GUID_A]}}
    records = [{"tool_calls": [{"name": TOOL_NAME, "args": {"raw": GUID_A}},
                               {"name": TOOL_NAME,
                                "args": {"code": "x = 'a' * 23"}}]}]
    written, distinct = code_indicators(task, records)
    assert written == 0.0
    assert distinct == 0
    assert assistant_code(records) == "x = 'a' * 23"
    assert code_indicators(task, [{"tool_calls": [
        {"name": TOOL_NAME, "args": {"code": "y" * 23}}]}])[1] == 0


def test_rollout_stats_carry_the_instruments():
    from stage_c.rollout import Rollout

    rollout = Rollout(index=1, messages=[], stop_reason="completed",
                      tool_rounds=2, commits=1, tool_calls=2, raised_calls=0,
                      well_formed_calls=2, gold_keys_written=0.5,
                      distinct_guids=3)
    rollout.transcript_tokens = 4096
    stats = rollout.stats()
    assert stats["gold_keys_written"] == 0.5
    assert stats["distinct_guids"] == 3
    assert stats["transcript_tokens"] == 4096
    assert Rollout(index=1, messages=[], stop_reason="x", tool_rounds=0,
                   commits=0, tool_calls=0, raised_calls=0,
                   well_formed_calls=0).stats()["transcript_tokens"] is None


# --------------------------------------------------------------------------
# 6. the counter agrees with the encoder


def synthetic_transcripts() -> list[list[dict]]:
    """Three-round transcripts in the shape the server and sandbox produce."""
    out = []
    for seed in (1, 2):
        messages = [{"role": "system", "content": "You are a BIM assistant."},
                    {"role": "user",
                     "content": f"Rename the wall with GlobalId '{GUID_A}'.\n\n"
                                f"IFC model path: /models/task_r{seed}/model.ifc"}]
        for turn in range(3):
            messages.append({
                "role": "assistant", "content": "",
                "tool_calls": [{"id": f"call_{turn}", "type": "function",
                                "function": {"name": TOOL_NAME,
                                             "arguments": json.dumps(
                                                 {"code": f"print(ifc.by_guid('{GUID_A}'))\n"
                                                          f"# step {turn} of {seed}"})}}]})
            messages.append({"role": "tool", "tool_call_id": f"call_{turn}",
                             "name": TOOL_NAME,
                             "content": f"#{turn + 1}=IfcWall('{GUID_A}')"})
        messages.append({"role": "assistant", "content": "The wall is renamed."})
        out.append(messages)
    return out


def real_transcripts(limit: int = 3) -> list[list[dict]]:
    root = paths.PROJECT_ROOT / "runs_local" / "stage_c_val500"
    files = sorted(root.glob("*/transcripts/*.json")) if root.is_dir() else []
    out = []
    for path in files:
        record = json.loads(path.read_text(encoding="utf-8"))
        messages = record.get("messages") or []
        if sum(1 for m in messages if m.get("role") == "assistant") >= 2:
            out.append(messages)
        if len(out) >= limit:
            break
    return out


def test_counter_agrees_with_the_encoder():
    from transformers import AutoTokenizer

    from stage_a.chat_format import ASSISTANT_HEADER, canonical_template
    from stage_b.assemble import encode_side
    from stage_b.pairs import canonical_prompt, normalise

    tokenizer = AutoTokenizer.from_pretrained(str(paths.BASE_MODEL_DIR))
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    tools = [TOOL_SCHEMA]
    count = make_count_tokens(tokenizer, tools)
    template = canonical_template()
    header = len(tokenizer(ASSISTANT_HEADER,
                           add_special_tokens=False)["input_ids"])

    transcripts = real_transcripts()
    source = "recorded" if transcripts else "synthetic"
    transcripts = transcripts or synthetic_transcripts()
    print(f"     counter checked on {len(transcripts)} {source} transcripts")
    assert len(transcripts) >= 2
    for messages in transcripts:
        first = next(i for i, m in enumerate(messages)
                     if m.get("role") == "assistant")
        last = max(i for i, m in enumerate(messages)
                   if m.get("role") == "assistant")
        side = encode_side(tokenizer, canonical_prompt(messages[:first]),
                           normalise(messages[first:]), tools)
        assert "error" not in side, side
        encoded = len(side["input_ids"])

        # On a finished transcript the two differ by the generation prompt and
        # by nothing else. The exact relation is what the transcript budget
        # rests on, because an undercount is what would let a trajectory run
        # past the sequence length the trainer can take.
        assert count(counting_messages(messages)) - encoded == header, (
            f"counter {count(counting_messages(messages))}, encoder {encoded}")

        counted = count(counting_messages(messages[:last]))
        # What the counter cannot know is the turn the model has not written
        # yet, so it must fall short by that turn and by no more.
        rendered = tokenizer.apply_chat_template(
            normalise(messages), tools=tools, tokenize=False,
            chat_template=template)
        before = tokenizer.apply_chat_template(
            normalise(messages[:last]), tools=tools, tokenize=False,
            chat_template=template)
        tail = len(tokenizer(rendered[len(before):],
                             add_special_tokens=False)["input_ids"])
        assert 0 <= encoded - counted <= tail + 8, (
            f"counter {counted}, encoder {encoded}, last turn {tail}")


def test_encode_group_takes_a_transcript_that_ends_on_a_tool_call():
    """The shape the budget stop now returns must encode, and must add up.

    Dropping the unread results leaves the transcript ending on an assistant
    turn that asked for a tool call nobody answered. The encoder has to take
    that, the gradient mask has to reach the end of it, and its length has to
    be what the budget counted before the request plus the tokens the turn
    generated, or the budget would not bound what the trainer encodes.
    """
    from transformers import AutoTokenizer

    from stage_a.chat_format import ASSISTANT_HEADER, canonical_template
    from stage_b.pairs import normalise
    from stage_c.rollout import Rollout, encode_group

    tokenizer = AutoTokenizer.from_pretrained(str(paths.BASE_MODEL_DIR))
    tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
    tools = [TOOL_SCHEMA]
    count = make_count_tokens(tokenizer, tools)
    template = canonical_template()

    # The closing answer and the last tool result go, which is what the agent
    # loop returns when the budget stops it after a tool round.
    messages = synthetic_transcripts()[0][:-2]
    assert messages[-1]["role"] == "assistant" and messages[-1]["tool_calls"]

    task = {"task_id": "task"}
    rollout = Rollout(index=1, messages=messages, stop_reason="token_budget",
                      tool_rounds=3, commits=0, tool_calls=3, raised_calls=0,
                      well_formed_calls=3, reward=0.5)
    encoded = encode_group(tokenizer, task, [rollout], tools, 12288)
    entry = encoded["rollouts"][0]
    assert "error" not in entry, entry

    mask = entry["completion_mask"]
    rendered = tokenizer.apply_chat_template(
        normalise(messages), tools=tools, tokenize=False, chat_template=template)
    before = tokenizer.apply_chat_template(
        normalise(messages[:-1]), tools=tools, tokenize=False,
        chat_template=template)
    tail = len(tokenizer(rendered[len(before):],
                         add_special_tokens=False)["input_ids"])
    header = len(tokenizer(ASSISTANT_HEADER,
                           add_special_tokens=False)["input_ids"])
    # The final turn is masked from the end of its header to its closing
    # marker, so all but the header and that one marker carry gradient.
    assert sum(mask[-tail:]) >= tail - header - 2, (sum(mask[-tail:]), tail)
    assert max(i for i, m in enumerate(mask) if m) >= len(mask) - 3

    counted = count(counting_messages(messages[:-1], "task", 1))
    length = len(encoded["prompt_ids"]) + len(entry["completion_ids"])
    envelope = length - counted - (tail - header)
    assert 0 <= envelope <= 8, (length, counted, tail, header, envelope)
    print(f"     encoded {length} = counted {counted} + generated "
          f"{tail - header} + envelope {envelope}")


def test_rollout_counter_refuses_an_impossible_count():
    from stage_c.rollout import CounterError, _rollout_counter

    messages = [{"role": "system", "content": "s" * 4000},
                {"role": "user", "content": "u" * 4000}]
    counted = _rollout_counter(lambda prepared: 2, "TASK", 1)
    try:
        counted(messages)
    except CounterError as exc:
        assert "no tokenizer produces" in str(exc)
    else:
        raise AssertionError("a two-token answer for 8000 characters passed")

    mapping = _rollout_counter(lambda prepared: {"input_ids": [0] * 2000,
                                                 "attention_mask": []},
                               "TASK", 1)
    assert mapping(messages) == 2000


class ShortTokenizer:
    """A tokenizer whose answer is the number of fields, not of tokens."""

    def __init__(self, per_character: float = 0.0):
        self.per_character = per_character

    def apply_chat_template(self, messages, tools=None,
                            add_generation_prompt=True, tokenize=True,
                            chat_template=None):
        chars = sum(len(m.get("content") or "") for m in messages)
        return {"input_ids": [0] * max(2, int(chars * self.per_character)),
                "attention_mask": []}


def test_the_counter_is_answered_once_before_any_rollout():
    """A counter that does not measure tokens fails where it is built.

    Every rollout of every group shares one counter, and a rollout swallows its
    own exceptions and scores the trajectory as an unreadable file. A counter
    checked only inside the loop would therefore score a whole batch the same
    and take a no-op step, so it is answered once here instead.
    """
    from stage_c.rollout import CounterError

    try:
        make_count_tokens(ShortTokenizer(), [])
    except CounterError as exc:
        assert "no tokenizer produces" in str(exc)
    else:
        raise AssertionError("a two-token answer for the probe passed")
    count = make_count_tokens(ShortTokenizer(per_character=0.3), [])
    assert count([{"role": "user", "content": "x" * 100}]) == 30


def test_a_broken_counter_is_not_scored_as_a_dead_rollout():
    """It ends the group, rather than becoming eight unreadable files."""
    from stage_c.rollout import CounterError, rollout_group

    holder = Path(tempfile.mkdtemp(prefix="rollout_v3_"))
    task = {"task_id": "T-1", "operation": "update", "category": "spatial",
            "instruction": "Rename the wall.", "input_ifc": "in.ifc",
            "ground_truth_ifc": "gold.ifc", "target": {}}
    config = AgentConfig(max_transcript_tokens=1000, max_tool_output_chars=100)
    saved = agent_module.Sandbox
    agent_module.Sandbox = make_sandbox(echo)
    try:
        rollout_group(task, 2, ScriptedClient(default_episode()), config,
                      holder, paths.PROJECT_ROOT, holder, disk_floor_gb=0.0,
                      count_tokens=lambda prepared: 2)
    except CounterError:
        pass
    else:
        raise AssertionError("the broken counter was scored as a dead rollout")
    finally:
        agent_module.Sandbox = saved
        shutil.rmtree(holder, ignore_errors=True)


def test_counting_messages_collapses_the_rollout_directory():
    messages = [{"role": "system", "content": "s"},
                {"role": "user", "content": "path /work/TASK_r3/model.ifc"},
                {"role": "assistant", "content": "",
                 "tool_calls": [{"id": "c", "type": "function",
                                 "function": {"name": TOOL_NAME,
                                              "arguments": '{"code": "print(1)"}'}}]}]
    prepared = counting_messages(messages, "TASK", 3)
    assert prepared[1]["content"] == "path /work/TASK/model.ifc"
    assert prepared[2]["tool_calls"][0]["function"]["arguments"] == {"code": "print(1)"}


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
