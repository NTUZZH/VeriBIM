"""Preference pairs, from whole trajectories and from single repaired turns.

Two constructions, both from the same on-policy rollouts and both labeled by the
verifier rather than by a heuristic about what good code looks like.

*Trajectory pairs* put a solved attempt against a failed one on the same task.
They carry the broad signal: this whole way of going about it scored, that one
did not.

*Turn pairs* put a clean version of one turn against the raising version of the
same turn, sharing a token-identical prefix. They carry the narrow signal, aimed
at the exact site of a failure, which is what the two named error classes need.

The rejection criteria are the ones the spec pre-registered. Nothing here moves
a margin; a margin moves only by amending the spec.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from .sample import unobserved_guids_per_turn

#: Pre-registered thresholds (spec §2). Named so a reader can see they are
#: constants of the design rather than tuned numbers.
CHOSEN_FLOOR = 0.90
REJECT_MARGIN = 0.30
MAX_PAIRS_PER_TASK = 2
TURN_PAIR_CAP = 2000

#: The user turn carries the working copy's path, which differs per sample
#: (`.../sample_3/model.ifc`). DPO needs one prompt shared by both sides of a
#: pair, so the path is normalised to a per-task canonical form. This is safe
#: because the path is a protocol artifact the model never dereferences: it
#: edits the pre-bound `ifc` object, and no accepted trajectory in Stage A or
#: Stage B opens the file by name. Logged as a deviation.
SAMPLE_SEGMENT = re.compile(r"/sample_\d+/")

NOT_FOUND = re.compile(r"Instance with GlobalId '([^']*)' not found")
BAD_SCHEMA = re.compile(r"Entity with name '([^']+)' not found in schema '([^']+)'")


def error_class(line: str) -> str:
    """Which named class a traceback's last line belongs to."""
    if NOT_FOUND.search(line):
        return "fabricated_globalid"
    if BAD_SCHEMA.search(line):
        return "wrong_schema_class"
    if "has no attribute" in line:
        return "invented_attribute"
    if "No module named" in line:
        return "invented_module"
    if line.startswith("NameError"):
        return "undefined_name"
    return "other"


#: The classes construction (b) targets. Originally two, named in the spec from
#: the gate-eval decomposition; extended to every raising class the model
#: actually produces on-policy, because the target is "classes that block the
#: code-run gate, weighted by what the model does" rather than a fixed list.
#: `other` and `invented_module` are excluded: the first is not a class, the
#: second is 0.02% of failures.
NAMED_CLASSES = ("fabricated_globalid", "invented_attribute",
                 "undefined_name", "wrong_schema_class")


def observed_class_shares(rollouts, classes=NAMED_CLASSES) -> dict[str, float]:
    """Each class's share of raising calls, over every call in the sample.

    Measured at the call level, not from the job list: a job list holds at most
    one entry per rollout per class, which flattens the difference between a
    class that fails once and one that fails on every turn.
    """
    counts = Counter()
    for task in rollouts:
        for sample in task["samples"]:
            for call in sample["calls"]:
                if call["raised"]:
                    counts[error_class(call["error_line"])] += 1
    total = sum(counts[c] for c in classes)
    if not total:
        return {c: 0.0 for c in classes}
    return {c: counts[c] / total for c in classes}


def schema_valid(sample: dict, allow_no_calls: bool = False) -> bool:
    """Whether every tool call the rollout made was well formed.

    A rollout that made no call at all is invalid by default, because a task
    that asks for an edit is not answered without one. ``allow_no_calls``
    lifts that for a task whose correct answer is to change nothing and ask,
    where zero calls, or inspection calls alone, is the shape of a right answer.
    """
    if not sample["calls"]:
        return bool(allow_no_calls)
    return all(c["well_formed"] for c in sample["calls"])


#: The tag the v2 task set puts on an instruction that leaves out a value the
#: edit would need.
UNDERSPECIFIED_FAMILY = "wording.underspecified"


def task_is_underspecified(task: dict) -> bool:
    """Whether one rollout line describes a task answered by asking.

    Read from the line rather than from the task file, so pair construction
    needs nothing but the rollouts. A v1 line carries neither the families nor
    the clarification and is therefore never under-specified, which is what
    keeps v1 pair counts reproducible.
    """
    if UNDERSPECIFIED_FAMILY in (task.get("families") or ()):
        return True
    return bool(task.get("clarification")) and bool(task.get("expected_reply"))


def chosen_candidates(samples: Sequence[dict], info: dict, floor: float,
                      underspecified: bool) -> list[dict]:
    """The rollouts on one task that may be the chosen side.

    An ordinary task is answered by editing and committing, so the chosen side
    has to score, be schema-valid and have committed. An under-specified task is
    answered by leaving the file alone and asking for the missing value, so the
    chosen side has to score and must NOT have committed; a commit there is the
    failure the pair is meant to teach against.
    """
    if underspecified:
        return [s for s in samples
                if info[id(s)]["final"] >= floor
                and not info[id(s)]["committed"]
                and schema_valid(s, allow_no_calls=True)]
    return [s for s in samples
            if info[id(s)]["final"] >= floor
            and info[id(s)]["committed"] and info[id(s)]["schema_valid"]]


def raised_turns(sample: dict) -> list[dict]:
    return [c for c in sample["calls"] if c["raised"]]


def fabricated_turns(sample: dict) -> list[dict]:
    """Turns using an identifier no earlier tool output printed."""
    return [e for e in unobserved_guids_per_turn(sample["messages"])
            if e["unobserved"]]


def classify_sample(sample: dict) -> dict:
    """Everything the pair rules need to know about one rollout."""
    raised = raised_turns(sample)
    fabricated = fabricated_turns(sample)
    classes = Counter(error_class(c["error_line"]) for c in raised)
    return {
        "final": sample["final"],
        "committed": sample["commits"] > 0,
        "schema_valid": schema_valid(sample),
        "raised": bool(raised),
        "fabricated": bool(fabricated),
        "error_classes": dict(classes),
        "named_class": next((c for c in NAMED_CLASSES if classes.get(c)), ""),
        "first_raising_turn": raised[0]["turn"] if raised else None,
    }


def normalise(messages: Sequence[dict]) -> list[dict]:
    """Sampled transcripts into the shape the chat template renders.

    The server returns a tool call's arguments as a JSON string; the template
    iterates them as a mapping. Stage A's synthesized data already carried
    mappings, so this only bites on sampled rollouts, and it bites as a template
    error rather than a wrong number, which is the good way for it to fail.
    """
    out: list[dict] = []
    for message in messages:
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            out.append(dict(message))
            continue
        calls = []
        for call in message["tool_calls"]:
            function = dict(call.get("function") or {})
            arguments = function.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    arguments = {"code": arguments}
            if not isinstance(arguments, dict):
                arguments = {"code": str(arguments)}
            function["arguments"] = {"code": str(arguments.get("code", ""))}
            calls.append({**call, "function": function})
        out.append({**message, "tool_calls": calls})
    return out


def canonical_prompt(messages: Sequence[dict]) -> list[dict]:
    """The prefix with the per-sample working path collapsed to one form."""
    out = []
    for message in messages:
        content = message.get("content") or ""
        if message.get("role") == "user":
            content = SAMPLE_SEGMENT.sub("/", content)
        out.append({**message, "content": content})
    return out


def split_prompt(messages: Sequence[dict]) -> tuple[list[dict], list[dict]]:
    """The shared prefix (system + user) and the model's continuation."""
    first = next((i for i, m in enumerate(messages)
                  if m.get("role") == "assistant"), len(messages))
    return canonical_prompt(messages[:first]), normalise(messages[first:])


def trajectory_pairs(rollouts: Iterable[dict],
                     chosen_floor: float = CHOSEN_FLOOR,
                     margin: float = REJECT_MARGIN,
                     cap: int = MAX_PAIRS_PER_TASK) -> tuple[list[dict], dict]:
    """Construction (a): a solved attempt against a failed one, same task."""
    pairs: list[dict] = []
    stats = Counter()
    for task in rollouts:
        stats["tasks"] += 1
        underspecified = task_is_underspecified(task)
        if underspecified:
            stats["tasks_underspecified"] += 1
        samples = [s for s in task["samples"] if s.get("final") is not None]
        info = {id(s): classify_sample(s) for s in samples}
        eligible = chosen_candidates(samples, info, chosen_floor, underspecified)
        if not eligible:
            stats["tasks_without_a_chosen"] += 1
            continue
        chosen = max(eligible, key=lambda s: info[id(s)]["final"])
        candidates: list[tuple[dict, str]] = []
        for sample in samples:
            if sample is chosen:
                continue
            meta = info[id(sample)]
            if meta["final"] <= info[id(chosen)]["final"] - margin:
                candidates.append((sample, "margin"))
            elif meta["raised"]:
                candidates.append((sample, "raised"))
            elif meta["fabricated"]:
                candidates.append((sample, "fabricated_guid"))
        if not candidates:
            stats["tasks_without_a_rejected"] += 1
            continue
        # The spec asks for the named classes to be preferred where there is a
        # choice, so order by whether the rejection exhibits one.
        candidates.sort(key=lambda pair: (
            0 if info[id(pair[0])]["named_class"] else 1,
            info[id(pair[0])]["final"]))
        stats["tasks_with_pairs"] += 1
        prompt, chosen_completion = split_prompt(chosen["messages"])
        for sample, reason in candidates[:cap]:
            rejected_prompt, rejected_completion = split_prompt(sample["messages"])
            if [m.get("content") for m in rejected_prompt] != \
                    [m.get("content") for m in prompt]:
                stats["dropped_prompt_mismatch"] += 1
                continue
            meta = info[id(sample)]
            # A rejection caught by the unobserved-identifier check belongs to
            # the fabricated-GlobalId class even though nothing raised: the
            # check exists precisely to catch the cases the sandbox does not.
            named = meta["named_class"] or (
                "fabricated_globalid" if reason == "fabricated_guid" else "")
            pairs.append({
                "construction": "trajectory",
                "task_id": task["task_id"],
                "operation": task["operation"],
                "category": task["category"],
                "edit_kind": task.get("edit_kind", ""),
                "building_id": task.get("building_id", ""),
                "schema": task.get("schema", ""),
                "families": list(task.get("families") or ()),
                "underspecified": underspecified,
                "prompt_messages": prompt,
                "chosen_messages": chosen_completion,
                "rejected_messages": rejected_completion,
                "chosen_final": info[id(chosen)]["final"],
                "rejected_final": meta["final"],
                "reason": reason,
                "error_classes": meta["error_classes"],
                "named_class": named,
            })
            stats[f"reason_{reason}"] += 1
            if named:
                stats[f"class_{named}"] += 1
            if underspecified:
                stats["underspecified_pairs"] += 1
    return pairs, dict(stats)


def branch_jobs(rollouts: Iterable[dict],
                classes: Sequence[str] = NAMED_CLASSES) -> list[dict]:
    """Construction (b), first half: where a turn should be resampled.

    One job per rollout turn that raised with a named-class error. The prefix is
    the exact message list up to that turn, so the resampled continuation shares
    a token-identical context with the turn it replaces.
    """
    jobs: list[dict] = []
    for task in rollouts:
        for sample in task["samples"]:
            # One job per rollout PER CLASS, not per rollout. Taking only the
            # first named-class failure lets the common class mask the rare one:
            # fabricated identifiers precede a wrong-schema class in almost
            # every rollout, which left the second named target with ten jobs
            # out of eleven thousand.
            claimed: set[str] = set()
            assistant_index = -1
            for position, message in enumerate(sample["messages"]):
                if message.get("role") != "assistant":
                    continue
                assistant_index += 1
                call = next((c for c in sample["calls"]
                             if c["turn"] == assistant_index), None)
                if call is None or not call["raised"]:
                    continue
                cls = error_class(call["error_line"])
                if cls not in classes or cls in claimed:
                    continue
                claimed.add(cls)
                jobs.append({
                    "task_id": task["task_id"],
                    "operation": task["operation"],
                    "category": task["category"],
                    "edit_kind": task.get("edit_kind", ""),
                    "building_id": task.get("building_id", ""),
                    "schema": task.get("schema", ""),
                    "families": list(task.get("families") or ()),
                    "underspecified": task_is_underspecified(task),
                    "sample": sample["sample"],
                    "turn": assistant_index,
                    "error_class": cls,
                    "error_line": call["error_line"],
                    "prefix_messages": list(sample["messages"][:position]),
                    "rejected_turn": message,
                    "input_ifc": task["input_ifc"],
                    "ground_truth_ifc": task["ground_truth_ifc"],
                    "target": task.get("target") or {},
                    "instruction": task.get("instruction", ""),
                })
                if len(claimed) == len(classes):
                    break
    return jobs


def select_branch_jobs(jobs: Sequence[dict], cap: int = TURN_PAIR_CAP,
                       seed: int = 20260826,
                       weights: dict[str, float] | None = None,
                       already: set[tuple] | None = None) -> tuple[list[dict], dict]:
    """Spread the cap over the named classes in proportion to what fails.

    Supply exceeds the cap by an order of magnitude, so the selection decides
    what the turn pairs teach. The cap is allocated to each named class in
    proportion to its share of the observed raising turns, because the classes
    that block the gate should dominate the gradient exactly as much as they
    dominate the failures. Inside a class the walk is uniform over
    operation x building, so no one building supplies a class on its own.

    A class that cannot fill its quota gives the remainder back to its own
    strata first; only what a class genuinely cannot supply is offered to the
    others. At most one pair per (task, turn) and two per task.
    """
    import random

    rng = random.Random(seed)
    by_class: dict[str, list[dict]] = {}
    for job in jobs:
        by_class.setdefault(job["error_class"], []).append(job)
    total = sum(len(v) for v in by_class.values())
    if not total:
        return [], {"observed": {}, "quota": {}, "realized": {}}

    observed = {c: len(v) for c, v in by_class.items()}
    if weights:
        # Proportional to what the model actually does, measured over every
        # raising call, not to how many jobs the list happens to hold.
        quota = {c: int(round(cap * weights.get(c, 0.0))) for c in observed}
    else:
        quota = {c: int(cap * n / total) for c, n in observed.items()}
    # integer remainder to the largest class, so the cap is spent
    if quota:
        spare = cap - sum(quota.values())
        if spare:
            quota[max(quota, key=lambda c: observed[c])] += spare

    picked: list[dict] = []
    per_task = Counter()
    seen_turns: set[tuple] = set(already or ())
    realized = Counter()

    def draw(pool: Sequence[dict], want: int) -> list[dict]:
        """Round robin over operation x building inside one class."""
        cells: dict[tuple, list[dict]] = {}
        for job in pool:
            cells.setdefault((job["operation"], job["building_id"]), []).append(job)
        keys = sorted(cells)
        rng.shuffle(keys)
        for bucket in cells.values():
            rng.shuffle(bucket)
            # A failure at turn 0 has no prior tool output to carry an identifier
            # forward from, so resampling it reproduces the fabrication: measured
            # 0 repairs in 64 production jobs and 0 of 6 in a controlled probe,
            # against 2 of 2 at turn >= 1. Later turns are drawn first; turn 0
            # still fills a class that would otherwise run short.
            bucket.sort(key=lambda job: job["turn"] == 0)
        out: list[dict] = []
        depth = 0
        while len(out) < want:
            progressed = False
            for key in keys:
                bucket = cells[key]
                if depth >= len(bucket):
                    continue
                job = bucket[depth]
                progressed = True
                key_tt = (job["task_id"], job["turn"])
                if key_tt in seen_turns or per_task[job["task_id"]] >= 2:
                    continue
                seen_turns.add(key_tt)
                per_task[job["task_id"]] += 1
                out.append(job)
                if len(out) >= want:
                    break
            if not progressed:
                break
            depth += 1
        return out

    for cls in sorted(quota, key=lambda c: -observed[c]):
        taken = draw(by_class[cls], quota[cls])
        picked.extend(taken)
        realized[cls] = len(taken)

    # Anything a class could not supply is offered to the classes that still
    # have jobs left, largest first.
    shortfall = cap - len(picked)
    if shortfall > 0:
        for cls in sorted(observed, key=lambda c: -observed[c]):
            if shortfall <= 0:
                break
            remaining = [j for j in by_class[cls]
                         if (j["task_id"], j["turn"]) not in seen_turns]
            extra = draw(remaining, shortfall)
            picked.extend(extra)
            realized[cls] += len(extra)
            shortfall -= len(extra)

    allocation = {
        "cap": cap,
        "weights": weights or "proportional to the job list",
        "carried_over": len(already or ()),
        "observed_raising_turns": observed,
        "quota_by_class": quota,
        "realized_by_class": dict(realized),
        "selected": len(picked),
        "by_operation": dict(Counter(j["operation"] for j in picked)),
        "by_turn": dict(Counter(min(j["turn"], 5) for j in picked)),
        "turn_zero_selected": sum(1 for j in picked if j["turn"] == 0),
        "buildings": len({j["building_id"] for j in picked}),
        "tasks": len({j["task_id"] for j in picked}),
    }
    return picked, allocation
