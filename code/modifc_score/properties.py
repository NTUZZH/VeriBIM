"""Property extraction and comparison for the semantic score."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import ifcopenshell.util.element as element_util

from .config import CANDIDATE_ATTRIBUTES


def associated_material(entity) -> Any:
    """The name of the material an entity is associated with, or ``None``.

    A layered material is read as the tuple of its layers' names, so a wall
    built of three named layers is told apart from one built of two.
    """
    import ifcopenshell.util.element as util

    try:
        material = util.get_material(entity)
    except Exception:
        return None
    if material is None:
        return None
    if material.is_a("IfcMaterial"):
        return material.Name
    layers = getattr(material, "ForLayerSet", None) or material
    names = []
    for layer in getattr(layers, "MaterialLayers", None) or ():
        inner = getattr(layer, "Material", None)
        names.append(getattr(inner, "Name", None))
    if names:
        return tuple(names)
    return getattr(material, "Name", None)


def assigned_type(entity) -> Any:
    """The name of the type object an entity is assigned to, or ``None``."""
    import ifcopenshell.util.element as util

    try:
        type_object = util.get_type(entity)
    except Exception:
        return None
    if type_object is None:
        return None
    return getattr(type_object, "Name", None)


def entity_properties(entity, ignore: Iterable[str] = (),
                      include_material: bool = False,
                      include_type: bool = False) -> dict[str, Any]:
    """Flatten an entity's property sets and its own attributes into one map.

    Keys are ``"<PropertySet>.<Property>"`` for property-set values and the bare
    attribute name for direct attributes.  Values that are ``None`` are dropped,
    and names on the ignore list never appear.
    """
    ignore = set(ignore)
    out: dict[str, Any] = {}
    try:
        psets = element_util.get_psets(entity)
    except Exception:
        psets = {}
    for pset_name, props in psets.items():
        if not isinstance(props, dict):
            continue
        for prop_name, value in props.items():
            if prop_name == "id":
                continue
            if prop_name in ignore or value is None:
                continue
            out[f"{pset_name}.{prop_name}"] = value
    for attr in CANDIDATE_ATTRIBUTES:
        if attr in ignore:
            continue
        try:
            value = getattr(entity, attr, None)
        except Exception:
            value = None
        if value is None:
            continue
        out[attr] = value
    if include_material:
        value = associated_material(entity)
        if value is not None:
            out["Material"] = value
    if include_type:
        value = assigned_type(entity)
        if value is not None:
            out["TypeObject"] = value
    return out


def values_match(expected: Any, actual: Any, tolerance: float) -> bool:
    if actual is None:
        return expected is None
    if isinstance(expected, bool) or isinstance(actual, bool):
        return bool(expected) == bool(actual)
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        if expected == actual:
            return True
        denom = max(abs(float(expected)), abs(float(actual)))
        if denom == 0.0:
            return True
        return abs(float(expected) - float(actual)) / denom <= tolerance
    if isinstance(expected, (list, tuple)) and isinstance(actual, (list, tuple)):
        if len(expected) != len(actual):
            return False
        return all(values_match(e, a, tolerance) for e, a in zip(expected, actual))
    return expected == actual


def property_score(reference, candidate, tolerance: float,
                   ignore: Sequence[str], include_material: bool = False,
                   include_type: bool = False) -> dict[str, Any]:
    """Fraction of the reference entity's properties the candidate reproduces."""
    if candidate is None:
        return {"score": 0.0, "n_keys": 0, "skipped": "no_match"}
    expected = entity_properties(reference, ignore, include_material,
                                 include_type)
    actual = entity_properties(candidate, ignore, include_material,
                               include_type)
    if not expected:
        return {"score": 1.0, "n_keys": 0, "passed": [], "failed": []}
    passed: list[str] = []
    failed: list[dict[str, Any]] = []
    for key, value in expected.items():
        got = actual.get(key)
        if values_match(value, got, tolerance):
            passed.append(key)
        else:
            failed.append({"key": key, "expected": value, "actual": got})
    return {
        "score": len(passed) / len(expected),
        "n_keys": len(expected),
        "passed": passed,
        "failed": failed,
    }
