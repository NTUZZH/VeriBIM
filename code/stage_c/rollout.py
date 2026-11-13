"""Rollouts for GRPO: the eval protocol, run in groups, scored by the verifier.

A GRPO step needs a group of trajectories on one task and a reward for each. The
trajectories are produced the way the benchmark produces them — multi-turn,
one `execute_ifc_code` tool, a sandbox worker per trajectory, the canonical
template on the server — because a policy trained on a different interaction
shape than it is evaluated on is trained on the wrong thing.

Only assistant-authored tokens carry gradient. The mask is rebuilt from the
finished transcript rather than tracked during generation, so it cannot drift
from what the template actually rendered.

Disk discipline: every trajectory's working copy is removed in a
`finally`, and a group is not started when free space is under the floor.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from stage_a import paths
from stage_b.branch import free_gb, wait_for_disk

paths.ensure_harness_on_path()

from modifc_harness.agent import run_task  # noqa: E402
from modifc_harness.config import AgentConfig  # noqa: E402
from modifc_harness.tasks import Task, normalise_path  # noqa: E402

from .reward import COMMIT_REQUIRED_CHOICES, UNREADABLE_FILE_REWARD  # noqa: E402,F401

DISK_FLOOR_GB = 30.0

#: An IFC GlobalId is 22 characters from a 64-character alphabet. The lookaround
#: keeps the match to a whole token, so a longer identifier is not read as the
#: GlobalId hiding inside its first 22 characters.
GUID_TOKEN = re.compile(r"(?<![0-9A-Za-z_$])[0-9A-Za-z_$]{22}(?![0-9A-Za-z_$])")

#: Runs of whitespace inside one line, collapsed before two code strings are
#: compared. Two snippets that differ only in spacing around an operator are
#: the same attempt, and the sandbox answers them the same way.
INLINE_WHITESPACE = re.compile(r"[^\S\n]+")

#: The design values of the repeat-failure deduction. They are
#: named here so the run's record can quote them; the flags default to off and
#: the trainer passes whatever the run asked for.
REPEAT_PENALTY = 0.05
REPEAT_PENALTY_CAP = 0.25

def normalised_code(code: str) -> str:
    """One code string in the form two attempts are compared in.

    Blank lines and trailing spaces go, and a run of spaces or tabs inside a
    line becomes one space. Indentation is kept and counted, because Python
    reads it: a re-indented snippet is a different program, and a policy that
    changed the indentation after an IndentationError has changed its approach
    rather than resent the same attempt.
    """
    lines: list[str] = []
    for line in code.splitlines():
        body = line.strip()
        if not body:
            continue
        indent = len(line) - len(line.lstrip())
        lines.append(f"{indent}|{INLINE_WHITESPACE.sub(' ', body)}")
    return "\n".join(lines)


def raised(call: dict) -> bool:
    """Whether one tool call came back as a traceback.

    The same test ``raised_calls`` counts with, so the two numbers describe the
    same set of calls.
    """
    return str(call.get("output") or "").startswith("Traceback")


def repeat_failures(iterations: Sequence[dict]) -> tuple[int, int]:
    """How often the policy resent a snippet that had already raised.

    The trajectory is walked in order, and a call is counted when its code,
    with whitespace collapsed, matches the code of an earlier call in the same
    trajectory that came back as a traceback. What the repeat itself returns
    does not matter: the failure mode this measures is the policy sending the
    snippet again instead of changing approach, which is what ran 130 of the
    324 benchmark tasks to the round budget without a commit. A repeat
    of a call that succeeded is not counted, because resending working code is
    not that failure mode.

    Returns the number of repeats and how many distinct snippets they came
    from, so a trajectory stuck on one snippet is separable in the log from one
    cycling through several.
    """
    seen_raising: set[str] = set()
    repeats = 0
    codes: set[str] = set()
    for record in iterations:
        for call in record.get("tool_calls") or []:
            code = (call.get("args") or {}).get("code")
            if not isinstance(code, str):
                continue
            key = normalised_code(code)
            if not key:
                continue
            if key in seen_raising:
                repeats += 1
                codes.add(key)
            if raised(call):
                seen_raising.add(key)
    return repeats, len(codes)


@dataclass
class Rollout:
    index: int
    messages: list[dict]
    stop_reason: str
    tool_rounds: int
    commits: int
    tool_calls: int
    raised_calls: int
    well_formed_calls: int
    reward: float = 0.0
    final: Optional[float] = None
    null: Optional[float] = None
    readable: bool = True
    error: Optional[str] = None
    #: The verifier's reward before any per-error deduction; equal to
    #: ``reward`` when the deduction is off.
    reward_raw: Optional[float] = None
    #: How many tool calls resent a snippet that had already raised, and how
    #: many distinct snippets those repeats came from. Logged always; deducted
    #: from only when the run asks for the deduction.
    repeat_failures: int = 0
    repeated_codes: int = 0
    #: True when the reward was set to zero because the trajectory never
    #: committed and the run required a commit for this operation.
    commit_gated: bool = False
    #: The last thing the policy said, which an under-specified task is read
    #: against and every other task ignores.
    reply: str = ""
    #: Instruments, logged and never rewarded. See ``code_indicators``.
    gold_keys_written: Optional[float] = None
    distinct_guids: int = 0
    #: Encoded length of the trajectory, filled in after encoding.
    transcript_tokens: Optional[int] = None
    #: One list of per-token log-probabilities per model turn, present only for
    #: the rollouts that asked the server for them.
    turn_logprobs: Optional[list[list[float]]] = None

    def _hold_raw(self) -> None:
        """Keep the verifier's own value before the first deduction touches it."""
        if self.reward_raw is None:
            self.reward_raw = self.reward

    def apply_error_penalty(self, per_call: float, cap: float) -> None:
        """Deduct ``per_call`` per tool call that raised, at most ``cap``."""
        self._hold_raw()
        self.reward = self.reward - min(cap, per_call * self.raised_calls)

    def apply_repeat_penalty(self, per_repeat: float, cap: float) -> None:
        """Deduct ``per_repeat`` per resent failing snippet, at most ``cap``.

        It rides on top of the per-error deduction rather than replacing it,
        because the two name different things: one call raising is a mistake,
        and the same call raising again is the policy not reading the answer.
        """
        self._hold_raw()
        self.reward = self.reward - min(cap, per_repeat * self.repeat_failures)

    def apply_commit_gate(self, operation: str, scope: str) -> None:
        """Zero the reward when the trajectory never wrote the file.

        A create that never commits leaves the input untouched, which the
        verifier already scores at or near the no-op floor. Making it exactly
        zero states the rule instead of relying on the file, and it is logged,
        so a run can be read for how often the gate fired. ``scope`` is "off",
        "create", or "all".

        A trajectory whose file could not be read is left alone. It never
        committed either, so the gate would otherwise lift a crashed rollout
        from the unreadable-file floor of -0.2 up to zero and pay it more than
        the verifier did. That floor is a verdict of its own and it stands.

        Applied last, after both deductions, because it replaces the value
        rather than reducing it: an uncommitted trajectory is worth zero
        whatever else it did.
        """
        if scope == "off" or self.commits > 0 or not self.readable:
            return
        if scope == "create" and operation != "create":
            return
        self._hold_raw()
        self.reward = 0.0
        self.commit_gated = True

    def stats(self) -> dict[str, Any]:
        return {"index": self.index, "stop_reason": self.stop_reason,
                "tool_rounds": self.tool_rounds, "commits": self.commits,
                "tool_calls": self.tool_calls, "raised_calls": self.raised_calls,
                "well_formed_calls": self.well_formed_calls,
                "repeat_failures": self.repeat_failures,
                "repeated_codes": self.repeated_codes,
                "commit_gated": self.commit_gated,
                "reward": round(self.reward, 6),
                "reward_raw": None if self.reward_raw is None else round(self.reward_raw, 6),
                "final": self.final,
                "readable": self.readable, "error": self.error,
                "gold_keys_written": (None if self.gold_keys_written is None
                                      else round(self.gold_keys_written, 4)),
                "distinct_guids": self.distinct_guids,
                "transcript_tokens": self.transcript_tokens}


def assistant_code(iterations: Sequence[dict]) -> str:
    """Every code string the model sent, joined in the order it sent them."""
    pieces: list[str] = []
    for record in iterations:
        for call in record.get("tool_calls") or []:
            code = (call.get("args") or {}).get("code")
            if isinstance(code, str):
                pieces.append(code)
    return "\n".join(pieces)


def gold_resolution_keys(task: dict) -> list[str]:
    """The identifiers a correct solution has to name.

    For an update or a delete these are the task's target GlobalIds: the
    elements already in the model that the edit has to reach. For a create they
    are not, because a create task's target GlobalIds are the ones the reference
    script invented for the elements it added, and no solution can guess them.
    What a create task's solution must name is the host the new element hangs
    from, which the instruction states, so the instruction's own GlobalIds are
    used instead. A task naming none has no keys.
    """
    target = task.get("target") or {}
    if task.get("operation") == "create":
        text = task.get("instruction") or task.get("prompt") or ""
        return sorted(set(GUID_TOKEN.findall(text)))
    return sorted({g for g in (target.get("guids") or []) if isinstance(g, str)})


def code_indicators(task: dict, iterations: Sequence[dict]) -> tuple[Optional[float], int]:
    """Two numbers describing what the model's code named, for the log only.

    The first is the share of the task's gold resolution keys that appear
    verbatim somewhere in the code the model sent; it is ``None`` when the task
    has no keys. The second is how many distinct GlobalId-shaped tokens the code
    mentions, which separates a trajectory that looked the model up from one
    that invented an identifier and reused it.

    Neither enters the reward. They are read alongside it to see whether a run
    that scores better is also resolving more of what the task points at.
    """
    code = assistant_code(iterations)
    distinct = len(set(GUID_TOKEN.findall(code)))
    keys = gold_resolution_keys(task)
    if not keys:
        return None, distinct
    return sum(1 for key in keys if key in code) / len(keys), distinct


def counting_messages(messages: Sequence[dict], task_id: str = "",
                      index: Optional[int] = None) -> list[dict]:
    """A live transcript in the shape ``encode_group`` will render it.

    The transcript budget is only worth having if it counts what the encoder
    will count. Two things stand between the two. The server returns a tool
    call's arguments as a JSON string and the chat template iterates them as a
    mapping, so an unconverted transcript does not render at all. And the user
    turn carries this rollout's own working directory, which the encoder
    collapses so the group shares one prompt.
    """
    from stage_b.pairs import canonical_prompt, normalise

    first = next((i for i, m in enumerate(messages)
                  if m.get("role") == "assistant"), len(messages))
    prefix = list(messages[:first])
    if task_id and index is not None:
        marker = f"{task_id}_r{index}"
        prefix = [{**m, "content": (m.get("content") or "").replace(marker, task_id)}
                  if m.get("role") == "user" else m for m in prefix]
    return canonical_prompt(prefix) + normalise(messages[first:])


#: The loosest character-per-token ratio this content can produce. Real
#: transcripts sit near three characters per token; forty is only asked to be
#: far enough away that a wrong answer cannot pass for a right one.
MAX_CHARS_PER_TOKEN = 40


class CounterError(RuntimeError):
    """The token counter answered something no tokenizer would.

    It has its own type because a rollout swallows every other exception and
    scores the trajectory as an unreadable file. A counter is shared by the
    whole batch, so swallowing this one would score every rollout of every
    group the same, which reads as a batch of flat groups and takes a no-op
    step: the run would keep going and measure nothing. This type is re-raised
    instead, and the step fails where it can be seen.
    """


def _rollout_counter(count_tokens: Optional[Callable], task_id: str, index: int):
    """The trainer's token counter, fed the messages the encoder would see.

    The answer is checked against the length of the text it was given, because
    the one way this can go wrong is silent. `apply_chat_template` returns a
    mapping of fields rather than a list of ids under transformers 5, so a
    counter that measures it with `len` reports the number of fields, every
    reserve then looks enormous, and the transcript budget never binds.
    """
    if count_tokens is None:
        return None

    def counted(messages: list[dict]) -> int:
        prepared = counting_messages(messages, task_id, index)
        return check_count(count_tokens(prepared), prepared)

    return counted


def check_count(value, prepared: Sequence[dict]) -> int:
    """One counter answer, held against the text it was given."""
    if not isinstance(value, int):
        try:
            value = len(value["input_ids"])
        except Exception as exc:  # noqa: BLE001
            raise CounterError("the token counter must return a token count, "
                               f"got {type(value).__name__}") from exc
    chars = sum(len(m.get("content") or "") for m in prepared)
    if value * MAX_CHARS_PER_TOKEN < chars:
        raise CounterError(
            f"the token counter reported {value} tokens for {chars} "
            "characters, which no tokenizer produces")
    return value


def make_count_tokens(tokenizer, tools: Sequence[dict]) -> Callable[[list[dict]], int]:
    """A token counter for the next request's prompt, rendered as it is served.

    The template is the canonical one rather than whatever the tokenizer
    happens to carry, for the same reason the encoder pins it: they must agree,
    or the budget is measured against a different rendering than the one the
    trainer encodes.
    """
    from stage_a.chat_format import canonical_template

    template = canonical_template()

    def count(messages: list[dict]) -> int:
        encoded = tokenizer.apply_chat_template(
            list(messages), tools=list(tools), add_generation_prompt=True,
            tokenize=True, chat_template=template)
        ids = encoded["input_ids"] if hasattr(encoded, "keys") else encoded
        return len(ids)

    # Answered once here, on a probe long enough that a wrong answer cannot
    # look plausible, so a counter that does not measure what it is asked to
    # measure stops the run before the first rollout rather than during it.
    probe = [{"role": "system", "content": "count these characters."},
             {"role": "user", "content": "x " * 2000}]
    check_count(count(probe), probe)
    return count


def as_task(record: dict, project_root: Path) -> Task:
    return Task(
        task_id=record["task_id"], operation=record["operation"],
        category=record["category"],
        prompt=record.get("instruction") or record["prompt"],
        input_ifc=project_root / normalise_path(record["input_ifc"]),
        ground_truth_ifc=project_root / normalise_path(record["ground_truth_ifc"]),
        target=record.get("target") or {},
        tags=[f"edit_kind:{record.get('edit_kind')}"])


def score_group(jobs: list[dict], gold_cache_dir: Path, heldout: bool,
                timeout: float = 3600.0) -> list[dict]:
    """Rewards for a finished group, computed in the environment that can.

    The scorer and IfcOpenShell live in `l2`; the trainer lives in `l2train`.
    The two exchange two JSON files and nothing else.
    """
    import subprocess
    import tempfile

    if not jobs:
        return []
    holder = Path(tempfile.mkdtemp(prefix="scorejob_", dir=str(gold_cache_dir.parent)))
    try:
        job_file, out_file = holder / "jobs.json", holder / "rewards.json"
        job_file.write_text(json.dumps(jobs), encoding="utf-8")
        command = [str(paths.L2_PYTHON), "-m", "stage_c.score_cli",
                   "--jobs", str(job_file), "--out", str(out_file),
                   "--gold-cache", str(gold_cache_dir)]
        if heldout:
            command.append("--heldout")
        env = dict(os.environ, PYTHONPATH=str(paths.PROJECT_ROOT / "code"))
        process = subprocess.run(command, capture_output=True, text=True,
                                 timeout=timeout, env=env, check=False)
        if process.returncode != 0 or not out_file.exists():
            raise RuntimeError(
                "the scorer subprocess failed: "
                f"{(process.stderr or process.stdout or '')[-400:]}")
        return json.loads(out_file.read_text(encoding="utf-8"))
    finally:
        shutil.rmtree(holder, ignore_errors=True)


def rollout_group(task: dict, k: int, client, agent: AgentConfig,
                  work_root: Path, project_root: Path, gold_cache_dir: Path,
                  heldout: bool = False,
                  disk_floor_gb: float = DISK_FLOOR_GB,
                  count_tokens: Optional[Callable[[list[dict]], int]] = None,
                  request_logprobs: bool = False) -> list[Rollout]:
    """k trajectories on one task, scored as a group, working copies removed.

    Each trajectory's final file is lifted out of its sandbox before the sandbox
    is deleted, because the group is scored in one subprocess after all k have
    finished rather than one at a time inside the loop.

    ``count_tokens`` measures the next request's prompt for the transcript
    budget, and is used only when ``agent`` sets one. ``request_logprobs`` keeps
    the server's per-token log-probabilities on each rollout, which the one-shot
    check against the trainer's own log-probabilities needs.
    """
    if not wait_for_disk(work_root, disk_floor_gb):
        raise RuntimeError(
            f"free disk stayed below {disk_floor_gb:.0f} GB; refusing to roll out")
    harness_task = as_task(task, project_root)
    finals = paths.require_absolute(work_root / f"_final_{task['task_id']}", "finals")
    shutil.rmtree(finals, ignore_errors=True)
    finals.mkdir(parents=True, exist_ok=True)

    def one(index: int) -> tuple[Rollout, Optional[Path]]:
        work = paths.require_absolute(
            work_root / f"{task['task_id']}_r{index}", "rollout work dir")
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True, exist_ok=True)
        working = work / f"{harness_task.input_ifc.stem}.ifc"
        kept: Optional[Path] = None
        try:
            result = run_task(task=harness_task, working_ifc=working, client=client,
                              agent_config=agent, log_file=work / "sandbox.log",
                              # The sandbox runs IfcOpenShell, which this
                              # interpreter does not have. Without this every
                              # tool call would fail on import.
                              python_executable=str(paths.L2_PYTHON),
                              count_tokens=_rollout_counter(
                                  count_tokens, task["task_id"], index),
                              request_logprobs=request_logprobs)
            calls = [c for r in result.iterations for c in r["tool_calls"]]
            written, distinct = code_indicators(task, result.iterations)
            repeats, repeated = repeat_failures(result.iterations)
            rollout = Rollout(
                index=index, messages=result.messages,
                stop_reason=result.stop_reason, tool_rounds=result.tool_rounds,
                commits=result.commits, tool_calls=len(calls),
                raised_calls=sum(1 for c in calls if raised(c)),
                well_formed_calls=sum(1 for c in calls if c.get("ok")),
                repeat_failures=repeats, repeated_codes=repeated,
                reply=result.model_output or "",
                gold_keys_written=written, distinct_guids=distinct,
                turn_logprobs=(result.extra.get("turn_logprobs")
                               if request_logprobs else None))
            if working.is_file() and working.stat().st_size > 0:
                kept = finals / f"r{index}.ifc"
                shutil.copy2(working, kept)
            return rollout, kept
        except CounterError:
            # Not one dead rollout: the counter belongs to the whole batch, so
            # scoring this one as an unreadable file would hide a fault that
            # every rollout of every group shares.
            raise
        except Exception as exc:  # noqa: BLE001 - one dead rollout is not a dead step
            return Rollout(index=index, messages=[], stop_reason="driver_error",
                           tool_rounds=0, commits=0, tool_calls=0, raised_calls=0,
                           well_formed_calls=0, reward=UNREADABLE_FILE_REWARD,
                           readable=False,
                           error=f"{type(exc).__name__}: {exc}"[:160]), None
        finally:
            # Unconditional: a rollout that crashed still copied a model.
            shutil.rmtree(work, ignore_errors=True)

    try:
        with ThreadPoolExecutor(max_workers=k) as pool:
            produced = list(pool.map(one, range(1, k + 1)))
        rollouts = [item[0] for item in produced]
        jobs = [{"task": task, "index": rollout.index, "predicted": str(kept),
                 "reply": rollout.reply}
                for rollout, kept in produced if kept is not None]
        by_index = {row["index"]: row for row in
                    score_group(jobs, Path(gold_cache_dir), heldout)}
        for rollout in rollouts:
            row = by_index.get(rollout.index)
            if row is None:
                # No file survived the trajectory, so there is nothing to score.
                if rollout.error is None:
                    rollout.reward = UNREADABLE_FILE_REWARD
                    rollout.readable = False
                    rollout.error = "no file on disk"
                continue
            rollout.reward = float(row["reward"])
            rollout.final = row.get("final")
            rollout.null = row.get("null")
            rollout.readable = bool(row.get("readable", True))
            rollout.error = row.get("error")
        return rollouts
    finally:
        shutil.rmtree(finals, ignore_errors=True)


def encode_group(tokenizer, task: dict, rollouts: Sequence[Rollout],
                 tools: Sequence[dict], max_seq: int) -> dict:
    """Prompt ids shared by the group, and per-rollout completion ids and mask.

    The mask marks assistant-authored tokens only. Tool results sit inside the
    completion and must be attended to but must not carry gradient: they are the
    sandbox's words, and rewarding them would train the policy on the
    environment's output.
    """
    from stage_b.assemble import encode_side
    from stage_b.pairs import canonical_prompt, normalise

    encoded: list[dict] = []
    prompt_ids: Optional[list[int]] = None
    for rollout in rollouts:
        first = next((i for i, m in enumerate(rollout.messages)
                      if m.get("role") == "assistant"), len(rollout.messages))
        # Stage C work dirs are {task_id}_r{index}; collapse that per-rollout
        # segment so the group shares one prompt (Stage B's canonical_prompt
        # only knows its own /sample_N/ layout).
        marker = f"{task['task_id']}_r{rollout.index}"
        prefix = [{**m, "content": (m.get("content") or "").replace(marker, task["task_id"])}
                  if m.get("role") == "user" else m
                  for m in rollout.messages[:first]]
        prompt_messages = canonical_prompt(prefix)
        completion = normalise(rollout.messages[first:])
        side = encode_side(tokenizer, prompt_messages, completion, tools)
        if "error" in side:
            encoded.append({"error": side["error"], "index": rollout.index})
            continue
        ids, mask, plen = side["input_ids"], side["completion_mask"], side["prompt_len"]
        if len(ids) > max_seq:
            # The length travels with the error. Without it the only trace of a
            # trajectory that outgrew the sequence length is the fact that its
            # group was dropped, and the number needed to retune the transcript
            # budget is exactly the one that was thrown away.
            encoded.append({"error": "over max_seq", "index": rollout.index,
                            "tokens": len(ids)})
            continue
        if prompt_ids is None:
            prompt_ids = ids[:plen]
        elif ids[:plen] != prompt_ids:
            encoded.append({"error": "prompt differs within the group",
                            "index": rollout.index, "tokens": len(ids)})
            continue
        encoded.append({"index": rollout.index, "completion_ids": ids[plen:],
                        "completion_mask": mask[plen:],
                        "reward": rollout.reward,
                        "n_assistant": sum(mask[plen:])})
    return {"prompt_ids": prompt_ids or [], "rollouts": encoded}
