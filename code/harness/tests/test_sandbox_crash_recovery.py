"""A worker crash is recovered inside the trajectory, the same for every model.

The IFC library is compiled code, and a snippet that touches an entity after
removing it ends the worker with SIGSEGV. The agent loop then starts a fresh
worker on the file as the last ``commit()`` left it, or on a fresh copy of the
input model when that file is incomplete, tells the model, and continues. The
third crash ends the trajectory as ``sandbox_crash``. These tests drive
``run_task`` with a scripted client and snippets that kill the worker.

    OMP_NUM_THREADS=1 PYTHONNOUSERSITE=1 taskset -c 8-9 \\
        python -m pytest -q code/harness/tests/test_sandbox_crash_recovery.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1]
if str(HARNESS) not in sys.path:
    sys.path.insert(0, str(HARNESS))

from modifc_harness.agent import (CRASH_MESSAGE_INPUT,  # noqa: E402
                                  CRASH_MESSAGE_LAST_COMMIT,
                                  CRASH_SKIPPED_MESSAGE, MAX_SANDBOX_CRASHES,
                                  run_task)
from modifc_harness.client import ChatResponse  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.sandbox import has_step_trailer  # noqa: E402
from modifc_harness.tasks import Task  # noqa: E402

GUARD_DIR = Path("runs_local/sandbox_guard")
FIXTURE = GUARD_DIR / "fixtures" / "room_0.ifc"
DECOY = GUARD_DIR / "decoy" / "outside.ifc"
PYTHON = sys.executable

SEGV = "import os\nos.kill(os.getpid(), 11)\n"
EXIT0 = "import os\nos._exit(0)\n"
ADD_COMMITTED = ("ifc.create_entity('IfcWall', GlobalId=guid.new(), Name='Committed wall')\n"
                 "commit()\nprint('committed')\n")
ADD_UNCOMMITTED = "ifc.create_entity('IfcWall', GlobalId=guid.new(), Name='Uncommitted wall')\n"
COUNT = ("names = sorted(w.Name or '' for w in ifc.by_type('IfcWall'))\n"
         "print(len(names), names.count('Committed wall'), names.count('Uncommitted wall'))\n")
# A crash inside commit() leaves the working file cut short; the snippet
# reproduces that by cutting the file itself and then dying.
TRUNCATE_THEN_SEGV = ("import os\n"
                      "p = [os.path.join(WORKDIR, a) for a in os.listdir(WORKDIR) if a.endswith('.ifc')][0]\n"
                      "data = open(p, 'rb').read()\n"
                      "open(p, 'wb').write(data[: len(data) // 2])\n" + SEGV)
GARBAGE_THEN_SEGV = ("import os\n"
                     "p = [os.path.join(WORKDIR, a) for a in os.listdir(WORKDIR) if a.endswith('.ifc')][0]\n"
                     "open(p, 'wb').write(b'not a STEP file\\nEND-ISO-10303-21;\\n')\n" + SEGV)
READ_DECOY = (f"try:\n    open({str(DECOY)!r}).read()\n    print('read')\n"
              "except PermissionError as e:\n    print(e)\n")


def _call(i: int, code: str) -> dict:
    return {"id": f"c{i}", "type": "function",
            "function": {"name": "execute_ifc_code", "arguments": json.dumps({"code": code})}}


class ScriptedClient:
    """Sends one scripted turn per request; a turn is a list of snippets."""

    def __init__(self, turns: list[list[str]]):
        self.turns = turns
        self.requests: list[list[dict]] = []

    def chat(self, messages, tools=None, **kw):
        self.requests.append([dict(m) for m in messages])
        n = len(self.requests)
        if n <= len(self.turns):
            calls = [_call(10 * n + j, code) for j, code in enumerate(self.turns[n - 1])]
            return ChatResponse(content="", finish_reason="tool_calls", tool_calls=calls)
        return ChatResponse(content="done", finish_reason="stop")


def _run(tmp_path: Path, turns: list[list[str]], **config):
    workdir = tmp_path / "edited" / "T-001"
    working = workdir / "room_0_0.ifc"
    prefix = f"WORKDIR = {str(workdir)!r}\n"
    client = ScriptedClient([[prefix + code for code in turn] for turn in turns])
    task = Task("WAL-DEL-DIR-A-001", "delete", "direct", "Delete a wall.", FIXTURE,
                FIXTURE, {}, [])
    result = run_task(task, working, client, AgentConfig(**config),
                      log_file=tmp_path / "logs" / "T-001.log", python_executable=PYTHON)
    return result, client, working


def _outputs(result) -> list[str]:
    return [c["output"] for r in result.iterations for c in r["tool_calls"]]


@pytest.fixture(autouse=True)
def _guard_off(monkeypatch):
    for var in ("VERIBIM_SANDBOX_GUARD", "VERIBIM_SANDBOX_LANDLOCK", "VERIBIM_NO_GEOM"):
        monkeypatch.delenv(var, raising=False)


def _baseline_walls(tmp_path: Path) -> int:
    result, _, _ = _run(tmp_path / "baseline", [[COUNT]])
    return int(_outputs(result)[0].split()[0])


@pytest.mark.parametrize("killer", [SEGV, EXIT0], ids=["sigsegv", "os_exit"])
def test_crash_is_reported_and_trajectory_continues(tmp_path, killer):
    result, client, working = _run(tmp_path, [[killer], ["print(len(ifc.by_type('IfcWall')))"]])
    assert result.stop_reason == "completed"
    assert result.sandbox_crashes == 1
    assert result.tool_rounds == 2 and result.tool_calls == 2 and len(client.requests) == 3
    out = _outputs(result)
    assert out[0] == CRASH_MESSAGE_LAST_COMMIT
    assert out[1].strip().isdigit()  # the fresh worker runs code
    # The model read the message as the tool reply to its call.
    tool_msgs = [m for m in client.requests[1] if m["role"] == "tool"]
    assert tool_msgs[-1]["content"] == CRASH_MESSAGE_LAST_COMMIT
    assert tool_msgs[-1]["tool_call_id"] == "c10"
    crash = result.iterations[0]["tool_calls"][0]["sandbox_crash"]
    assert result.iterations[0]["sandbox_crashes"] == 1
    assert crash["restarted_from"] == "last_commit"
    assert crash["returncode"] == (-11 if killer == SEGV else 0)
    assert crash["working_file_changed"] is False
    assert result.iterations[0]["tool_calls"][0]["ok"] is False
    assert "sandbox_crashes" not in result.iterations[1]
    log = (tmp_path / "logs" / "T-001.log").read_text()
    assert "=== sandbox restart 1 (last commit) ===" in log


def test_restart_sees_last_committed_state(tmp_path):
    base = _baseline_walls(tmp_path)
    result, _, working = _run(tmp_path, [[ADD_COMMITTED], [ADD_UNCOMMITTED + SEGV], [COUNT]])
    assert result.stop_reason == "completed" and result.sandbox_crashes == 1
    out = _outputs(result)
    assert out[1] == CRASH_MESSAGE_LAST_COMMIT
    assert out[2].split() == [str(base + 1), "1", "0"]
    assert result.commits == 1
    assert has_step_trailer(working)


def test_commit_inside_crashed_snippet_is_kept(tmp_path):
    base = _baseline_walls(tmp_path)
    result, _, _ = _run(tmp_path, [[ADD_COMMITTED + SEGV], [COUNT]])
    crash = result.iterations[0]["tool_calls"][0]["sandbox_crash"]
    assert crash["working_file_changed"] is True
    assert crash["restarted_from"] == "last_commit"
    assert _outputs(result)[1].split() == [str(base + 1), "1", "0"]


@pytest.mark.parametrize("breaker", [TRUNCATE_THEN_SEGV, GARBAGE_THEN_SEGV],
                         ids=["truncated", "unreadable"])
def test_incomplete_edited_file_falls_back_to_input(tmp_path, breaker):
    base = _baseline_walls(tmp_path)
    result, _, working = _run(tmp_path, [[ADD_COMMITTED], [breaker], [COUNT]])
    assert result.stop_reason == "completed" and result.sandbox_crashes == 1
    out = _outputs(result)
    assert out[1] == CRASH_MESSAGE_INPUT
    crash = result.iterations[1]["tool_calls"][0]["sandbox_crash"]
    assert crash["restarted_from"] == "input"
    assert "fallback_reason" in crash
    assert out[2].split() == [str(base), "0", "0"]
    assert working.read_bytes() == FIXTURE.read_bytes()


def test_third_crash_ends_trajectory(tmp_path):
    result, client, _ = _run(tmp_path, [[SEGV], [SEGV], [SEGV], ["print('never')"]])
    assert result.stop_reason == "sandbox_crash"
    assert result.sandbox_crashes == MAX_SANDBOX_CRASHES == 3
    assert result.tool_rounds == 3 and len(client.requests) == 3
    out = _outputs(result)
    assert out[:2] == [CRASH_MESSAGE_LAST_COMMIT] * 2
    assert out[2].startswith("sandbox_crash: ")
    assert result.error == "sandbox worker closed its result pipe"
    assert result.iterations[2]["tool_calls"][0]["sandbox_crash"]["returncode"] == -11


def test_later_calls_of_a_crashed_turn_are_answered_not_run(tmp_path):
    result, client, _ = _run(tmp_path, [[SEGV, ADD_COMMITTED], [COUNT]])
    assert result.stop_reason == "completed" and result.commits == 0
    first = result.iterations[0]
    assert [c["output"] for c in first["tool_calls"]] == [CRASH_MESSAGE_LAST_COMMIT]
    assert [c["output"] for c in first["skipped_calls"]] == [CRASH_SKIPPED_MESSAGE]
    replies = [m for m in client.requests[1] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in replies] == ["c10", "c11"]
    assert result.tool_calls == 2  # the skipped call was not executed


def test_timeout_still_ends_trajectory(tmp_path):
    result, _, _ = _run(tmp_path, [["import time\ntime.sleep(30)"], [COUNT]], tool_timeout=2.0)
    assert result.stop_reason == "tool_timeout"
    assert result.sandbox_crashes == 0 and result.tool_rounds == 1


@pytest.mark.parametrize("landlock", [False, True], ids=["audit", "audit+landlock"])
def test_guard_applies_to_restarted_worker(tmp_path, monkeypatch, landlock):
    monkeypatch.setenv("VERIBIM_SANDBOX_GUARD", "1")
    if landlock:
        monkeypatch.setenv("VERIBIM_SANDBOX_LANDLOCK", "1")
    monkeypatch.setenv("FAKE_API_KEY", "secret-value")
    leak = "import os\nprint(os.environ.get('FAKE_API_KEY'))\n"
    result, _, _ = _run(tmp_path, [[READ_DECOY], [leak], [SEGV], [READ_DECOY], [leak], [COUNT]])
    assert result.stop_reason == "completed" and result.sandbox_crashes == 1
    calls = [c for r in result.iterations for c in r["tool_calls"]]
    before, after = calls[0], calls[3]
    assert "sandbox: access outside the working directory is not permitted" in before["output"]
    assert after["output"] == before["output"]
    # The snippet index counts the snippets of one worker, so the restarted
    # worker's first snippet is 0 again.
    assert before["blocked"] == after["blocked"] == [
        {"event": "open", "arg": str(DECOY), "snippet": 0}]
    assert result.sandbox_blocked == 2
    assert calls[1]["output"].strip() == calls[4]["output"].strip() == "None"
    assert calls[5]["output"].strip().split()[0].isdigit()
