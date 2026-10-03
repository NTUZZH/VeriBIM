"""The verifier, as Stage A calls it.

Two readings are fixed here and used by every filter in the stage.  A deletion
is scored by whether the target is gone.  A material association and a
type assignment are scored under the settings that make them visible, which the
published reading does not carry, because neither leaves a trace it can see;
``scorer_config_for`` turns those on for the families that need them and leaves
every other task exactly as the published runs read it. The alternative reading, which
the published runs used, compares a deleted entity with a counterpart that no
longer exists and therefore scores a perfect deletion zero on semantics; a
training filter built on it would reject every correct delete. Evaluation
against BIM-Edit keeps the published reading, which is the reward/eval
separation the method section describes.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Sequence

#: Every axis and the final score of a kept trajectory must reach this.
SCORE_FLOOR = 0.98


def scorer_config(operation: str):
    from modifc_score.config import DEFAULT_CONFIG

    if operation == "delete":
        return dataclasses.replace(DEFAULT_CONFIG, delete_semantics="removal")
    return DEFAULT_CONFIG


#: What each 0.6.0 family needs the scorer to read before its edit is visible.
#: A material association and a type assignment leave no trace the published
#: reading can see, so a filter built on it would accept an empty answer for
#: them.  Every other family is graded under the shipped settings, and
#: evaluation against BIM-Edit is graded under them too.
FAMILY_SCORER_SETTINGS: dict[str, dict] = {
    "op.update.material": {
        "properties_include_material": True,
        "topology_relations_extra": ("IfcRelAssociatesMaterial",)},
    "op.update.type_object": {
        "properties_include_type": True,
        "topology_relations_extra": ("IfcRelDefinesByType",)},
    # An instruction that leaves out a value the edit needs is answered by
    # changing nothing and asking for it, which the shipped reading would score
    # as a perfect answer for any system that changed nothing at all.
    "wording.underspecified": {"underspecified_mode": True},
}


#: The axis each family's edit moves once its reading is switched on, and one
#: sentence saying what the reading does.  A trajectory is filtered on every
#: axis, and this names the axis that would fall if the edit were wrong, which
#: is what the per-family funnel reports.
FAMILY_READING: dict[str, tuple[str, str]] = {
    "op.update.material": (
        "semantics",
        "the associated material's name is compared as one more property, and"
        " the association is an edge of the relation graph"),
    "op.update.type_object": (
        "semantics",
        "the assigned type object's name is compared as one more property, and"
        " the assignment is an edge of the relation graph"),
    "op.update.pset": (
        "topology",
        "a property-set change already counts as a modified node under the"
        " shipped settings, so the published reading is kept"),
    "op.delete": (
        "semantics",
        "a deletion scores by whether the target is gone, because comparing it"
        " with a counterpart that no longer exists scores a correct delete zero"),
    "wording.underspecified": (
        "reply",
        "the file has to come back unchanged and the reply has to ask for the"
        " value the instruction left out"),
}

#: The reading every other family is graded under, which is the one the
#: published BIM-Edit runs used.
PUBLISHED_READING = "the published BIM-Edit settings, on all three axes"


def reading_for(record: dict) -> dict:
    """What one task is graded under, written down for the record it produces."""
    families = [f for f in (record.get("families") or ()) if f in FAMILY_READING]
    if "wording.underspecified" in families:
        # The reading short-circuits every other one: the file and the reply
        # decide the task, and nothing is compared against the gold model.
        families = ["wording.underspecified"]
    elif record.get("operation") == "delete" and "op.delete" not in families:
        families.append("op.delete")
    fields = {name: value for name, value in
              dataclasses.asdict(scorer_config_for(record)).items()
              if getattr(DEFAULT_FIELDS, name, None) != value}
    return {
        "families": families,
        "axes": sorted({FAMILY_READING[f][0] for f in families}) or ["geometry",
                                                                     "semantics",
                                                                     "topology"],
        "settings": fields,
        "note": "; ".join(FAMILY_READING[f][1] for f in families)
                or PUBLISHED_READING,
    }


class _DefaultFields:
    """The shipped configuration's own values, for diffing a task's reading."""

    def __getattr__(self, name):
        from modifc_score.config import DEFAULT_CONFIG

        return getattr(DEFAULT_CONFIG, name, None)


DEFAULT_FIELDS = _DefaultFields()


def is_underspecified(record: dict) -> bool:
    """Whether the instruction leaves out a value the edit would need.

    Such a task has a no-op gold model and an expected question, and it is
    answered by changing nothing and asking rather than by editing.
    """
    return bool(record.get("clarification")) and bool(record.get("expected_reply"))


def scorer_config_for(record: dict):
    """The settings one task is graded under, from the families it carries.

    The two settings above are additive, so a task that carries both families
    is read with both, and a task that carries neither is read exactly as the
    published runs read it.
    """
    settings: dict = {}
    relations: tuple = ()
    for family in record.get("families") or ():
        extra = FAMILY_SCORER_SETTINGS.get(family)
        if not extra:
            continue
        for name, value in extra.items():
            if name == "topology_relations_extra":
                relations = tuple(dict.fromkeys(relations + tuple(value)))
            else:
                settings[name] = value
    config = scorer_config(record.get("operation", ""))
    if not settings and not relations:
        return config
    if relations:
        settings["topology_relations_extra"] = tuple(
            dict.fromkeys(tuple(config.topology_relations_extra) + relations))
    return dataclasses.replace(config, **settings)


@dataclass
class Score:
    final: float = 0.0
    geometry: float = 0.0
    semantics: float = 0.0
    topology: float = 0.0
    n_reference: int = 0
    n_matched: int = 0
    gt_source: str = ""
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "final": round(self.final, 6),
            "geometry": round(self.geometry, 6),
            "semantics": round(self.semantics, 6),
            "topology": round(self.topology, 6),
            "n_reference": self.n_reference,
            "n_matched": self.n_matched,
            "gt_source": self.gt_source,
            "error": self.error,
        }

    @property
    def min_axis(self) -> float:
        return min(self.geometry, self.semantics, self.topology)


def score_prediction(record: dict, predicted: Path, project_root: Path,
                     models=None, meshes=None,
                     gold_path: Path | str | None = None,
                     config=None, reply: str = "") -> Score:
    """Score one edited file against the task it answers.

    ``config`` overrides the scorer settings, which the held-out verifier
    variant needs; it defaults to the reading this stage trains on.

    ``gold_path`` overrides the record's own reference. The v1 task set keeps
    the gold script rather than the gold model, so at scale the
    reference is rebuilt on demand into a bounded cache and its location is not
    the one the record names.
    """
    from modifc_score.model_cache import MESHES, MODELS
    from modifc_score.scorer import score_task
    from modifc_score.tasks import Task

    target = record.get("target") or {}
    task = Task(
        task_id=record["task_id"],
        operation=record["operation"],
        category=record["category"],
        input_ifc=str(project_root / record["input_ifc"]),
        ground_truth_ifc=str(gold_path) if gold_path is not None
                         else str(project_root / record["ground_truth_ifc"]),
        prompt=record.get("prompt", ""),
        entity_type=target.get("entity_type", record.get("element_type", "")),
        guids=tuple(target.get("guids") or ()),
        tags=(),
        clarification=record.get("clarification") or None,
    )
    try:
        result = score_task(
            task,
            task.input_ifc,
            task.ground_truth_ifc,
            str(predicted),
            config if config is not None else scorer_config(record["operation"]),
            models or MODELS,
            meshes or MESHES,
            geometry_mode="per_pair",
            reply=reply,
        )
    except Exception as exc:  # noqa: BLE001 - a failed score is a rejected trajectory
        return Score(error=f"{type(exc).__name__}: {exc}"[:300])
    return Score(
        final=float(result.final_score),
        geometry=float(result.geometry),
        semantics=float(result.semantics),
        topology=float(result.topology),
        n_reference=int(result.n_reference),
        n_matched=int(result.n_matched),
        gt_source=str(result.gt_source),
        error=result.error,
    )


def accepted(score: Score, floor: float = SCORE_FLOOR,
             require_axes: bool = True) -> bool:
    """The filter both trajectory sources pass through.

    ``require_axes`` also holds every individual axis to the floor, which is the
    convention the generator's own acceptance funnel uses. The spec states the
    filter on the final score, so the stricter reading is a setting rather than
    a fact of the pipeline, and the funnel reports both counts.
    """
    if score.error is not None or score.final < floor:
        return False
    return score.min_axis >= floor if require_axes else True
