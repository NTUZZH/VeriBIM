"""The reward: the verifier's score, normalised by the task's own no-op floor.

Two properties are wanted and they are in tension. The reward has to be
comparable across tasks, because a batch mixes them and GRPO's advantage is
computed within a group; and it has to stay the verifier's own quantity, because
the paper's claim is that a deterministic verifier can be the training signal
without shaping. Normalising by the null-edit score of the same task buys the
first without touching the second: it is an affine map per task, using a number
the generator already measured and stored.

    r = (final - null) / (1 - null),  clipped to [-0.2, 1]

Doing nothing scores the null-edit level, so it earns r = 0 rather than the
partial credit an unnormalised score would hand it. Making the model worse than
untouched earns a negative reward, floored at the same -0.2 as an unreadable
file so that no failure mode is worth more than any other.

There is exactly one shaped term: a final file the scorer cannot read gets
-0.2. It is here because "the model wrote something the tool chain cannot open"
is not a point on the quality scale, it is off the scale, and leaving it at 0
would make corrupting the file as good as leaving it alone.
"""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

#: Spec §3. Named so a reader can see they are constants of the design.
REWARD_FLOOR = -0.2
REWARD_CEILING = 1.0
UNREADABLE_FILE_REWARD = -0.2

#: The held-out verifier is the same scorer with a different point-sampling
#: seed and a coarser budget (guidance §3.5: "different point-sampling
#: seed/density"). It is never used for training, only to measure whether the
#: policy is learning the verifier's sampling noise instead of the task.
HELDOUT_SEED = 8675309
HELDOUT_TOTAL_SAMPLES = 8192
HELDOUT_MIN_PER_OBJECT = 128

#: Which operations lose the reward when the trajectory never called commit().
#: "off" is what every run up to grpo_v3 did, and it is the default.
COMMIT_REQUIRED_CHOICES = ("off", "create", "all")

#: The checker's completion verdict (every axis >= COMPLETION_AXIS)
#: adds this much to the normalised score, so that a near miss no longer pays
#: almost the full reward. Zero keeps the reward of every run up to grpo_v4.
#: It reaches the scoring subprocess through the environment, which the
#: trainer sets from --completion-bonus and records in its configuration.
COMPLETION_AXIS = 0.9
COMPLETION_BONUS = float(os.environ.get("VERIBIM_COMPLETION_BONUS", "0") or 0)


def training_config(task):
    """The scorer the reward is computed with.

    ``task`` is the task record, and the record is what decides the reading: a
    material association, a type assignment and an under-specified instruction
    each need a setting the published reading does not carry, and
    ``scorer_config_for`` turns exactly those on for the families that carry
    them. Every other task resolves to the same configuration the operation
    alone resolved to, so the reward of a task outside those families is the
    number it always was. An operation string is still accepted, because the
    reward check in ``stage_c.cli`` reports the configuration per operation and
    has no record to hand.
    """
    from stage_a.scoring import scorer_config, scorer_config_for

    if isinstance(task, str):
        return scorer_config(task)
    return scorer_config_for(task)


def heldout_config(task):
    """A verifier that agrees on the task and disagrees on the sampling noise."""
    return dataclasses.replace(
        training_config(task),
        sampling_seed=HELDOUT_SEED,
        pooled_max_total_samples=HELDOUT_TOTAL_SAMPLES,
        pooled_min_samples_per_object=HELDOUT_MIN_PER_OBJECT,
    )


def null_edit_score(task: dict) -> float:
    """What the task pays for doing nothing, as the generator measured it."""
    value = (task.get("verification") or {}).get("null_edit_score")
    if value is None:
        raise KeyError(
            f"{task.get('task_id')} carries no null_edit_score; the reward is "
            "normalised by it and must not fall back to an assumed value")
    return float(value)


def normalise(final: float, null: float) -> float:
    """Map a raw score onto the task's own scale, then clip."""
    denominator = 1.0 - null
    if denominator <= 1e-9:
        # A task nothing can improve on would divide by zero. None exist in the
        # canonical set (the largest null-edit score is 0.843), so this is a
        # guard rather than a path: such a task carries no signal either way.
        return 0.0
    value = (final - null) / denominator
    return max(REWARD_FLOOR, min(REWARD_CEILING, value))


@dataclass
class Reward:
    value: float
    final: Optional[float] = None
    null: Optional[float] = None
    readable: bool = True
    error: Optional[str] = None
    completed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {"reward": round(self.value, 6),
                "final": None if self.final is None else round(self.final, 6),
                "null": None if self.null is None else round(self.null, 6),
                "readable": self.readable, "error": self.error,
                "completed": self.completed}


def score_trajectory(task: dict, predicted: Path, project_root: Path,
                     gold_path: Path, heldout: bool = False,
                     reply: str = "") -> Reward:
    """The reward for one finished trajectory.

    ``predicted`` is whatever the trajectory left on disk, committed or not; a
    trajectory that never committed is scored on the unchanged file and lands at
    the no-op floor by construction, which is r = 0.

    ``reply`` is the last thing the policy said. Only an under-specified task
    reads it, and only under the reading its family asks for: the answer there
    is to change nothing and ask for the missing value, so the file alone
    cannot separate a correct answer from a trajectory that did nothing.
    """
    from stage_a.scoring import score_prediction

    null = null_edit_score(task)
    config = heldout_config(task) if heldout else training_config(task)
    predicted = Path(predicted)
    if not (predicted.is_file() and predicted.stat().st_size > 0):
        return Reward(UNREADABLE_FILE_REWARD, null=null, readable=False,
                      error="no file on disk")
    score = score_prediction(task, predicted, project_root, gold_path=gold_path,
                             config=config, reply=reply)
    if score.error and "parse" in str(score.error).lower():
        return Reward(UNREADABLE_FILE_REWARD, null=null, readable=False,
                      error=str(score.error)[:160])
    if score.error:
        return Reward(UNREADABLE_FILE_REWARD, null=null, readable=False,
                      error=str(score.error)[:160])
    value = normalise(float(score.final), null)
    axes = [getattr(score, name, None) for name in ("geometry", "semantics", "topology")]
    completed = all(a is not None and float(a) >= COMPLETION_AXIS for a in axes)
    if COMPLETION_BONUS and completed:
        value += COMPLETION_BONUS
    return Reward(value, final=float(score.final), null=null, completed=completed)
