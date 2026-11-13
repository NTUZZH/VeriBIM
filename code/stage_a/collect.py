"""Rejection-sampled trajectories from the pinned base model.

The gold-synthesized backbone teaches one idiom. This source teaches the model
its own: several trajectories are sampled per task at temperature, the file each
one leaves on disk is scored, and the ones that reach the same floor as the gold
backbone are kept. Near-identical solutions are dropped and at most two survive
per task, so one easy task cannot flood the set with the same answer.

Sampling itself is a GPU job and runs through the harness probe path, so the
protocol, the budget, the sandbox and the output rendering are the evaluation
harness's, unchanged. Everything after sampling is CPU work on the run directory
the sampler wrote, which is why the two halves are separate entry points: the
filter can be re-run, re-tuned and re-reported without touching the card.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import re
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from . import paths
from .goldmodels import open_cache, resolve_gold
from .scoring import Score, accepted, score_prediction
from .trajectory import trajectory_record

THINK_CLOSE = "</think>"
COMMENT = re.compile(r"#.*$", re.MULTILINE)
TOKEN = re.compile(r"[A-Za-z_][A-Za-z_0-9]*|\d+\.?\d*|[^\sA-Za-z_0-9]")


# ------------------------------------------------------------------ sampling

def sample_run(model_tag: str, task_ids: Sequence[str], tasks_file: Path,
               results_dir: Path, k: int = 8, temperature: float = 0.8,
               top_p: float = 0.95, max_model_len: int = 65536,
               headroom_mib: int = 3072, max_tool_rounds: int = 22,
               port: int = 8000, notes: str = "") -> dict:
    """Sample k trajectories per task from a served base model.

    This is the GPU half. It reuses the harness's own probe path, which starts
    the server, sizes the memory pool against the card as it is at launch,
    supervises it, runs the tasks and shuts down again.
    """
    paths.ensure_harness_on_path()
    from modifc_harness.bakeoff import run_model
    from modifc_harness.config import AgentConfig
    from modifc_harness.models import MODELS

    spec = MODELS[model_tag]
    return run_model(
        spec=spec,
        task_ids=list(task_ids),
        results_dir=Path(results_dir),
        tasks_file=Path(tasks_file),
        scenes_dir=paths.PROJECT_ROOT,
        port=port,
        headroom_mib=headroom_mib,
        max_model_len=max_model_len,
        max_restarts=3,
        agent=AgentConfig(max_tool_rounds=max_tool_rounds, temperature=temperature,
                          top_p=top_p),
        resume=True,
        notes=notes or f"Stage A rejection sampling, k={k} at T={temperature}",
        run_tag=f"stage_a_sample_{spec.tag}",
        task_source="corpus",
        num_samples=k,
    )


# ------------------------------------------------------------- normalisation

def strip_reasoning(content: str) -> str:
    """The visible part of an assistant turn.

    The pinned base is served without a reasoning parser, so a turn arrives as
    its deliberation, a closing ``</think>``, then the answer. Training targets
    carry the answer only, which is the same convention the gold-synthesized
    backbone follows, so one mixed set does not teach two different turn shapes.
    """
    if THINK_CLOSE in content:
        content = content.split(THINK_CLOSE)[-1]
    return content.lstrip("\n")


def normalise_messages(messages: Sequence[dict], keep_reasoning: bool = False
                       ) -> tuple[list[dict], list[bool], list[str]]:
    """Harness transcript to training messages, with the loss flags and the code."""
    out: list[dict] = []
    loss_on: list[bool] = []
    snippets: list[str] = []
    for message in messages:
        role = message.get("role")
        if role in ("system", "user"):
            out.append({"role": role, "content": message.get("content") or ""})
            loss_on.append(False)
        elif role == "tool":
            out.append({
                "role": "tool",
                "tool_call_id": message.get("tool_call_id", ""),
                "name": message.get("name", ""),
                "content": message.get("content") or "",
            })
            loss_on.append(False)
        elif role == "assistant":
            content = message.get("content") or ""
            if not keep_reasoning:
                content = strip_reasoning(content)
            entry: dict = {"role": "assistant", "content": content}
            calls = []
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                arguments = function.get("arguments")
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {"code": arguments}
                if not isinstance(arguments, dict):
                    arguments = {"code": str(arguments)}
                code = arguments.get("code")
                if not isinstance(code, str):
                    return [], [], []
                snippets.append(code)
                calls.append({
                    "id": call.get("id", f"call_{len(calls) + 1}"),
                    "type": "function",
                    "function": {"name": function.get("name", "execute_ifc_code"),
                                 "arguments": {"code": code}},
                })
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
            loss_on.append(True)
        else:
            return [], [], []
    return out, loss_on, snippets


def code_signature(snippets: Sequence[str]) -> tuple[str, frozenset]:
    """A key for exact duplicates, and a token set for near-duplicates."""
    joined = "\n".join(snippets)
    stripped = COMMENT.sub("", joined)
    words = TOKEN.findall(stripped)
    exact = " ".join(words)
    shingles = frozenset(zip(words, words[1:], words[2:]))
    return exact, shingles


def jaccard(first: frozenset, second: frozenset) -> float:
    if not first and not second:
        return 1.0
    union = len(first | second)
    return len(first & second) / union if union else 0.0


# ---------------------------------------------------------------- harvesting

@dataclass
class Candidate:
    task_id: str
    sample: int
    messages: list[dict]
    loss_on: list[bool]
    snippets: list[str]
    score: Score
    tool_rounds: int
    commits: int
    stop_reason: str


def _load_tasks(tasks_file: Path) -> dict[str, dict]:
    tasks: dict[str, dict] = {}
    with Path(tasks_file).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                record = json.loads(line)
                tasks[record["task_id"]] = record
    return tasks


_CTX: dict[str, Any] = {}


def _init(project_root: str, run_root: str, floor: float, require_axes: bool,
          keep_reasoning: bool, gold_cache_root: str = "",
          cores: Sequence[int] = ()) -> None:
    for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
        os.environ[name] = "1"
    if cores and hasattr(os, "sched_setaffinity"):
        try:
            os.sched_setaffinity(0, set(cores))
        except OSError:
            pass
    from modifc_score.model_cache import MESHES, MODELS

    MODELS.capacity = max(1, int(os.environ.get("VERIBIM_MODEL_CACHE", "3")))
    MESHES.capacity_vertices = int(os.environ.get("VERIBIM_MESH_VERTICES",
                                                  str(800_000)))
    cache = None
    if gold_cache_root:
        cache = open_cache(Path(gold_cache_root) / f"w{os.getpid()}")
    _CTX.update(project_root=Path(project_root), run_root=Path(run_root),
                floor=floor, require_axes=require_axes,
                keep_reasoning=keep_reasoning, gold_cache=cache)


def _score_sample(payload: tuple[dict, dict]) -> dict:
    task, result = payload
    run_root: Path = _CTX["run_root"]
    edited = run_root / str(result.get("edited_ifc", ""))
    info = result.get("runtime_info") or {}
    out = {
        "task_id": task["task_id"],
        "sample": int(result.get("sample", 1)),
        "stop_reason": info.get("stop_reason", ""),
        "tool_rounds": int(info.get("tool_rounds", 0)),
        "commits": int(info.get("commits", 0)),
        "reason": "",
        "score": None,
        "messages": None,
        "loss_on": None,
        "snippets": None,
    }
    if result.get("artifact_dropped"):
        out["reason"] = "no commit"
        return out
    if not edited.is_file() or edited.stat().st_size == 0:
        out["reason"] = "no edited file"
        return out
    if out["commits"] < 1:
        out["reason"] = "no commit"
        return out
    messages, loss_on, snippets = normalise_messages(
        result.get("messages") or [], keep_reasoning=_CTX["keep_reasoning"])
    if not messages:
        out["reason"] = "unparsable transcript"
        return out
    if messages[-1].get("role") != "assistant" or messages[-1].get("tool_calls"):
        out["reason"] = "trajectory did not end on an answer"
        return out
    gold = resolve_gold(task, _CTX.get("gold_cache"), _CTX["project_root"])
    if gold is None:
        out["reason"] = "gold model could not be rebuilt from its script"
        return out
    score = score_prediction(task, edited, _CTX["project_root"], gold_path=gold)
    from modifc_score.model_cache import MESHES

    MESHES.clear()
    out["score"] = score.as_dict()
    if not accepted(score, floor=_CTX["floor"], require_axes=_CTX["require_axes"]):
        out["reason"] = score.error or "score below floor"
        return out
    out["messages"] = messages
    out["loss_on"] = loss_on
    out["snippets"] = snippets
    return out


def harvest_run(run_dir: Path, tasks_file: Path, out_dir: Path, project_root: Path,
                floor: float = 0.98, require_axes: bool = True,
                cap_per_task: int = 2, workers: int = 6,
                keep_reasoning: bool = False,
                near_duplicate_threshold: float = 0.9,
                gold_cache_root: str = "", cores: Sequence[int] = ()) -> dict:
    """Score, filter, de-duplicate and cap the samples in one run directory."""
    run_dir = Path(run_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    caches = sorted(run_dir.glob("cache_*.json"))
    if not caches:
        raise FileNotFoundError(f"no cache_*.json in {run_dir}")
    cache = json.loads(caches[0].read_text(encoding="utf-8"))
    tasks = _load_tasks(tasks_file)

    payloads: list[tuple[dict, dict]] = []
    for task_id, record in sorted(cache.items()):
        task = tasks.get(task_id)
        if task is None:
            continue
        for result in record.get("results") or []:
            payloads.append((task, result))

    started = time.monotonic()
    context = mp.get_context("spawn")
    scored: list[dict] = []
    with context.Pool(processes=max(1, workers), initializer=_init,
                      initargs=(str(project_root), str(run_dir), floor,
                                require_axes, keep_reasoning, gold_cache_root,
                                tuple(cores))) as pool:
        for result in pool.imap_unordered(_score_sample, payloads, chunksize=1):
            scored.append(result)

    passed: dict[str, list[dict]] = {}
    reasons: Counter = Counter()
    for result in scored:
        if result["messages"] is None:
            reasons[result["reason"][:60] or "unknown"] += 1
            continue
        passed.setdefault(result["task_id"], []).append(result)

    kept_records: list[dict] = []
    dropped_duplicates = 0
    capped = 0
    for task_id, group in sorted(passed.items()):
        group.sort(key=lambda r: (-r["score"]["final"], r["tool_rounds"], r["sample"]))
        chosen: list[dict] = []
        signatures: list[tuple[str, frozenset]] = []
        for candidate in group:
            exact, shingles = code_signature(candidate["snippets"])
            if any(exact == seen_exact or
                   jaccard(shingles, seen_shingles) >= near_duplicate_threshold
                   for seen_exact, seen_shingles in signatures):
                dropped_duplicates += 1
                continue
            if len(chosen) >= cap_per_task:
                capped += 1
                continue
            chosen.append(candidate)
            signatures.append((exact, shingles))
        for candidate in chosen:
            task = tasks[task_id]
            kept_records.append(trajectory_record(
                task=task,
                messages=candidate["messages"],
                loss_on=candidate["loss_on"],
                source="self",
                score=Score(**{k: v for k, v in candidate["score"].items()
                               if k in Score.__dataclass_fields__}),
                extra={
                    "sample": candidate["sample"],
                    "stop_reason": candidate["stop_reason"],
                    "commits": candidate["commits"],
                    "target": task.get("target") or {},
                    "run_dir": str(run_dir),
                    "generator": "stage-a-reject/0.1.0",
                },
            ))

    out_file = out_dir / "trajectories_self.jsonl"
    with out_file.open("w", encoding="utf-8") as fh:
        for record in kept_records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    (out_dir / "scored_samples.jsonl").write_text(
        "\n".join(json.dumps({k: v for k, v in r.items()
                              if k not in ("messages", "loss_on", "snippets")})
                  for r in scored) + "\n", encoding="utf-8")

    report = {
        "run_dir": str(run_dir),
        "samples_scored": len(scored),
        "samples_passing": sum(len(v) for v in passed.values()),
        "tasks_with_a_pass": len(passed),
        "tasks_sampled": len(cache),
        "dropped_near_duplicates": dropped_duplicates,
        "dropped_over_cap": capped,
        "kept": len(kept_records),
        "cap_per_task": cap_per_task,
        "score_floor": floor,
        "require_all_axes": require_axes,
        "near_duplicate_threshold": near_duplicate_threshold,
        "rejection_reasons": dict(reasons),
        "trajectories": str(out_file),
        "duration_seconds": round(time.monotonic() - started, 1),
    }
    (out_dir / "funnel_self.json").write_text(json.dumps(report, indent=2),
                                              encoding="utf-8")
    return report
