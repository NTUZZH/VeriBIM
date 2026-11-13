"""Edit sets: what a model changed relative to the original input model.

Both the reference edit set and the predicted edit set are diffs against the
original input model M0, never a diff of the prediction against the ground
truth.  Which entities land in a set depends on the operation:

* ``create``  -- entities present in the edited model and absent from M0;
* ``update``  -- the task's target entities in the edited model, together with
  entities the edit added, so that a target rebuilt under a new identifier is
  still represented;
* ``delete``  -- entities present in M0 and absent from the edited model.

Every set is restricted to the task's target entity type.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

DIFF_MODES = {"create": "added", "update": "guids+added", "delete": "removed"}


def guids_of_type(model, entity_type: str) -> dict[str, Any]:
    """GUID -> entity for every entity of ``entity_type`` (subtypes included)."""
    out: dict[str, Any] = {}
    if not entity_type:
        return out
    try:
        entities = model.by_type(entity_type)
    except Exception:
        return out
    for e in entities:
        guid = getattr(e, "GlobalId", None)
        if guid:
            out[guid] = e
    return out


def by_guid(model, guid: str):
    try:
        return model.by_guid(guid)
    except Exception:
        return None


@dataclass
class EditSet:
    """Entities that one model changed relative to the input model."""

    entities: list[Any] = field(default_factory=list)
    guids: list[str] = field(default_factory=list)
    mode: str = ""

    def __len__(self) -> int:
        return len(self.entities)


def build_edit_set(model_0, model_x, operation: str, entity_type: str,
                   target_guids: Sequence[str]) -> EditSet:
    mode = DIFF_MODES.get(operation, "added")
    base = guids_of_type(model_0, entity_type)
    other = guids_of_type(model_x, entity_type)
    entities: list[Any] = []
    guids: list[str] = []

    if mode == "added":
        for guid, entity in other.items():
            if guid not in base:
                entities.append(entity)
                guids.append(guid)
    elif mode == "removed":
        if target_guids:
            for guid in target_guids:
                if guid in base and guid not in other:
                    entities.append(base[guid])
                    guids.append(guid)
        else:
            for guid, entity in base.items():
                if guid not in other:
                    entities.append(entity)
                    guids.append(guid)
    else:  # guids+added
        seen: set[str] = set()
        for guid in target_guids:
            entity = other.get(guid)
            if entity is not None:
                entities.append(entity)
                guids.append(guid)
                seen.add(guid)
        for guid, entity in other.items():
            if guid not in base and guid not in seen:
                entities.append(entity)
                guids.append(guid)
    return EditSet(entities=entities, guids=guids, mode=mode)


def removed_guids(model_0, model_x, entity_type: str) -> list[str]:
    base = guids_of_type(model_0, entity_type)
    other = guids_of_type(model_x, entity_type)
    return [g for g in base if g not in other]


def reference_entities(model_0, model_gt, operation: str, entity_type: str,
                       target_guids: Sequence[str]) -> tuple[list[Any], str]:
    """The reference entities a prediction is scored against, and their source.

    ``spec``  -- the task pins the target GUIDs and they resolve;
    ``diff``  -- the task pins nothing, so the reference comes from the diff;
    ``empty`` -- the pinned GUIDs do not resolve, so there is no reference.
    """
    if target_guids:
        found: list[Any] = []
        for guid in target_guids:
            if operation == "delete":
                # The entity a deletion refers to lives in the input model; if
                # the ground truth still carries it, that copy will do.
                entity = by_guid(model_0, guid) or by_guid(model_gt, guid)
            else:
                entity = by_guid(model_gt, guid)
            if entity is not None:
                found.append(entity)
        if found:
            return found, "spec"
        return [], "empty"

    edit = build_edit_set(model_0, model_gt, operation, entity_type, target_guids)
    if edit.entities:
        return list(edit.entities), "diff"
    return [], "empty"
