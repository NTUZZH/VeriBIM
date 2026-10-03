"""Mid-training validation: run the eval protocol against the model being trained.

The gate Stage A is judged by is a score on held-out tasks, not a training loss,
so the run has to be able to answer "is it getting better at the task" while it
is still going. The hook does that by running the harness's own agent loop
against the model in memory: same system prompt, same tool, same sandbox worker,
same budget rule. Only the transport differs, because there is no server to talk
to while the trainer holds the card.

Two environments are involved and both are used from here. The sandbox worker is
started with the ``l2`` interpreter, which is the one that carries IfcOpenShell;
scoring is a subprocess in the same environment. Neither ever runs inside the
training process.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional, Sequence

from . import paths

paths.ensure_harness_on_path()

from modifc_harness.agent import run_task  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.tasks import Task  # noqa: E402

TOOL_CALL = re.compile(
    r"<tool_call>\s*<function=(?P<name>[^>]+)>(?P<body>.*?)</function>\s*</tool_call>",
    re.DOTALL,
)
PARAMETER = re.compile(r"<parameter=(?P<key>[^>]+)>\n?(?P<value>.*?)\n?</parameter>",
                       re.DOTALL)
THINK_CLOSE = "</think>"


@dataclass
class LocalResponse:
    """The shape ``modifc_harness.agent`` expects back from a chat client."""

    content: str
    reasoning_content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw_message: dict = field(default_factory=dict)


def parse_completion(text: str) -> tuple[str, str, list[dict]]:
    """Split a raw completion into deliberation, visible content and tool calls."""
    reasoning = ""
    if THINK_CLOSE in text:
        reasoning, text = text.split(THINK_CLOSE, 1)
        text = text.lstrip("\n")
    calls: list[dict] = []
    for index, match in enumerate(TOOL_CALL.finditer(text), start=1):
        arguments = {key: value for key, value in
                     ((m.group("key"), m.group("value")) for m in
                      PARAMETER.finditer(match.group("body")))}
        calls.append({
            "id": f"call_{index}",
            "type": "function",
            "function": {"name": match.group("name").strip(), "arguments": arguments},
        })
    content = TOOL_CALL.sub("", text).strip()
    return reasoning.strip(), content, calls


class LocalChatClient:
    """A chat client backed by the model in this process rather than a server."""

    def __init__(self, model, tokenizer, tools: Sequence[dict],
                 max_new_tokens: int = 1024, temperature: float = 0.0) -> None:
        self.model = model
        self.tokenizer = getattr(tokenizer, "tokenizer", tokenizer)
        self.tools = list(tools)
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    def chat(self, messages: list[dict], tools=None, temperature: float = 0.0,
             top_p: float = 1.0, max_tokens: int | None = None) -> LocalResponse:
        import torch

        text = self.tokenizer.apply_chat_template(
            messages, tools=self.tools, tokenize=False, add_generation_prompt=True)
        encoded = self.tokenizer(text, return_tensors="pt", add_special_tokens=False)
        encoded = {k: v.to(self.model.device) for k, v in encoded.items()}
        prompt_tokens = int(encoded["input_ids"].shape[-1])
        with torch.inference_mode():
            generated = self.model.generate(
                **encoded,
                max_new_tokens=max_tokens or self.max_new_tokens,
                do_sample=self.temperature > 0,
                temperature=self.temperature if self.temperature > 0 else None,
                top_p=top_p,
                pad_token_id=self.tokenizer.pad_token_id or self.tokenizer.eos_token_id,
                use_cache=True,
            )
        new_tokens = generated[0][prompt_tokens:]
        completion = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        finish = "length" if len(new_tokens) >= (max_tokens or self.max_new_tokens) else "stop"
        reasoning, content, calls = parse_completion(completion)
        return LocalResponse(
            content=content,
            reasoning_content=reasoning,
            tool_calls=calls,
            finish_reason="tool_calls" if calls else finish,
            prompt_tokens=prompt_tokens,
            completion_tokens=int(len(new_tokens)),
        )


def pick_tasks(tasks_file: Path, n: int, ids_file: str = "") -> list[dict]:
    """The fixed validation subset.

    Fixed matters more than large: the number is compared with itself across
    steps, so the tasks must not change between two measurements.
    """
    records = []
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    if ids_file:
        wanted = json.loads(Path(ids_file).read_text(encoding="utf-8"))
        order = {task_id: i for i, task_id in enumerate(wanted)}
        return sorted([r for r in records if r["task_id"] in order],
                      key=lambda r: order[r["task_id"]])
    cells: dict[tuple[str, str], list[dict]] = {}
    for record in records:
        cells.setdefault((record["operation"], record["category"]), []).append(record)
    for bucket in cells.values():
        bucket.sort(key=lambda r: r["task_id"])
    picked: list[dict] = []
    index = 0
    keys = sorted(cells)
    while len(picked) < n:
        progressed = False
        for key in keys:
            if index < len(cells[key]):
                picked.append(cells[key][index])
                progressed = True
                if len(picked) >= n:
                    break
        if not progressed:
            break
        index += 1
    return picked


def _valid_python(code: str) -> bool:
    try:
        compile(code, "<tool_call>", "exec")
    except SyntaxError:
        return False
    except Exception:
        return False
    return True


#: The frozen protocol. These are the defaults because a
#: measurement taken under anything else is not the gate: the first attempt ran
#: at 8 rounds and 1,024 output tokens, which truncated a third of its turns
#: mid-answer and exhausted the budget on a quarter of its tasks, and the
#: numbers looked like a bad model rather than a bad harness.
PROTOCOL_MAX_ROUNDS = 22
PROTOCOL_MAX_NEW_TOKENS = 8192


def run_validation(model, tokenizer, tasks: Sequence[dict], tools: Sequence[dict],
                   work_root: Path, max_rounds: int = PROTOCOL_MAX_ROUNDS,
                   max_new_tokens: int = PROTOCOL_MAX_NEW_TOKENS,
                   score_python: Path | None = None) -> dict:
    """Roll out the validation tasks and score whatever each one leaves on disk."""
    work_root = Path(work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    client = LocalChatClient(model, tokenizer, tools, max_new_tokens=max_new_tokens)
    agent = AgentConfig(max_tool_rounds=max_rounds, max_tokens=max_new_tokens,
                        temperature=0.0, top_p=1.0)

    jobs: list[dict] = []
    rows: list[dict] = []
    started = time.monotonic()
    for record in tasks:
        task = Task(
            task_id=record["task_id"],
            operation=record["operation"],
            category=record["category"],
            prompt=record.get("instruction") or record["prompt"],
            input_ifc=paths.PROJECT_ROOT / record["input_ifc"],
            ground_truth_ifc=paths.PROJECT_ROOT / record["ground_truth_ifc"],
            target=record.get("target") or {},
            tags=[],
        )
        work = work_root / record["task_id"]
        work.mkdir(parents=True, exist_ok=True)
        working = work / f"{Path(record['input_ifc']).stem}.ifc"
        result = run_task(task=task, working_ifc=working, client=client,
                          agent_config=agent, log_file=work / "sandbox.log",
                          python_executable=str(paths.L2_PYTHON))
        calls = [call for round_ in result.iterations for call in round_["tool_calls"]]
        well_formed = [c for c in calls if c.get("ok")]
        compiles = [c for c in well_formed if _valid_python(c["args"].get("code", ""))]
        ran = [c for c in well_formed
               if not str(c.get("output", "")).startswith("Traceback")]
        rows.append({
            "task_id": record["task_id"],
            "operation": record["operation"],
            "category": record["category"],
            "stop_reason": result.stop_reason,
            "tool_calls": len(calls),
            "well_formed_calls": len(well_formed),
            "compiling_calls": len(compiles),
            "running_calls": len(ran),
            "commits": result.commits,
            "edited": str(working),
        })
        jobs.append({"task": record, "predicted": str(working)})

    scores = _score(jobs, work_root, score_python)
    by_id = {row["task_id"]: row for row in scores}
    for row in rows:
        entry = by_id.get(row["task_id"]) or {}
        row["score"] = (entry.get("score") or {}).get("final")
        row["score_error"] = entry.get("error")

    total_calls = sum(r["tool_calls"] for r in rows) or 1
    finals = [r["score"] for r in rows if r["score"] is not None]
    conformant = (max_rounds >= PROTOCOL_MAX_ROUNDS
                  and max_new_tokens >= PROTOCOL_MAX_NEW_TOKENS)
    if not conformant:
        print(f"WARNING: rounds={max_rounds} tokens={max_new_tokens} are below the "
              f"frozen protocol ({PROTOCOL_MAX_ROUNDS}/{PROTOCOL_MAX_NEW_TOKENS}); "
              "this is not a gate measurement", flush=True)
    summary = {
        "protocol_conformant": conformant,
        "max_tool_rounds": max_rounds,
        "max_new_tokens": max_new_tokens,
        "n_tasks": len(rows),
        "mean_final_score": round(sum(finals) / len(finals), 6) if finals else None,
        "schema_validity": round(sum(r["well_formed_calls"] for r in rows) / total_calls, 4),
        "code_valid": round(sum(r["compiling_calls"] for r in rows) / total_calls, 4),
        "code_run": round(sum(r["running_calls"] for r in rows) / total_calls, 4),
        "commit_rate": round(sum(1 for r in rows if r["commits"] > 0) / (len(rows) or 1), 4),
        "mean_tool_calls": round(total_calls / (len(rows) or 1), 3),
        "duration_seconds": round(time.monotonic() - started, 1),
        "by_operation": {},
    }
    for operation in sorted({r["operation"] for r in rows}):
        values = [r["score"] for r in rows
                  if r["operation"] == operation and r["score"] is not None]
        summary["by_operation"][operation] = (
            round(sum(values) / len(values), 6) if values else None)
    return {"summary": summary, "tasks": rows}


def _score(jobs: list[dict], work_root: Path, score_python: Path | None) -> list[dict]:
    """Score the edited files in the environment that can open them."""
    python = Path(score_python or paths.L2_PYTHON)
    jobs_file = work_root / "score_jobs.json"
    out_file = work_root / "score_out.json"
    jobs_file.write_text(json.dumps(jobs), encoding="utf-8")
    command = [str(python), "-m", "stage_a.score_cli",
               "--jobs", str(jobs_file), "--out", str(out_file)]
    env = {"PYTHONPATH": str(paths.CODE_ROOT), "OMP_NUM_THREADS": "4",
           "MKL_NUM_THREADS": "4", "PATH": "/usr/bin:/bin"}
    process = subprocess.run(command, capture_output=True, text=True,
                             env=env, cwd=str(paths.PROJECT_ROOT))
    if process.returncode != 0 or not out_file.exists():
        return [{"task_id": job["task"]["task_id"], "score": None,
                 "error": (process.stderr or "scoring failed")[-300:]} for job in jobs]
    return json.loads(out_file.read_text(encoding="utf-8"))
