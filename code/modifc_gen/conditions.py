"""Layer 6 of the requirement taxonomy: the conditions one model carries.

A source model is not a neutral container.  It is written in a schema version,
in a length unit, with storeys that may be turned against the world axes and a
site that may sit far from the origin, with element bodies that may be a swept
profile, a faceted solid or geometry borrowed from a type object, and with
element names in whatever language the office that drew it works in.  Every one
of those changes what an instruction can say and what a gold script has to do.

This module reads those conditions off a model, decides which of them a task
carries, and names each one with the tag the taxonomy gives it.  The tags are
measurements rather than draws: a run cannot ask for more millimetre models
than the corpus holds, so a condition is reported and stratified on rather than
mixed.  ``runs_local/gen_v07/corpus_conditions.md`` is the same measurement over
the whole pool.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

import numpy as np

# --------------------------------------------------------------------- units

#: Metres per model unit, and the tag a task drawn from such a model carries.
#: Only the units this corpus holds are named.  A model written in metres
#: carries no tag, because a length in the instruction and a length in the file
#: are then the same number and nothing has to be converted.
UNIT_TAGS = {
    "mm": "model.units.mm",
    "cm": "model.units.mm",
    "ft": "model.units.imperial",
    "in": "model.units.imperial",
}

#: How a length is spelled in each unit, for the wording layer.  The first
#: entry of each list is the plain form and the rest are the spellings a person
#: writing the same requirement would use instead.
UNIT_WORDS = {
    "m": ("m", "metres", "meters"),
    "mm": ("mm", "millimetres", "millimeters"),
    "cm": ("cm", "centimetres", "centimeters"),
}


def unit_word(scale: float) -> str:
    """The name of the length unit a scale of metres per unit stands for."""
    return {1.0: "m", 0.001: "mm", 0.01: "cm", 0.3048: "ft",
            0.0254: "in"}.get(round(float(scale), 6), "other")


def unit_tag(scale: float) -> Optional[str]:
    return UNIT_TAGS.get(unit_word(scale))


# -------------------------------------------------------------------- schema

#: The schema versions that need a tag.  IFC4 is the version the generator was
#: written against, so a task drawn from an IFC4 model carries no tag and the
#: two versions that differ from it do.
SCHEMA_TAGS = {"IFC2X3": "model.schema.ifc2x3", "IFC4X3": "model.schema.ifc4x3"}


def schema_tag(schema: str) -> Optional[str]:
    """The tag for a schema version, or None for the one taken as the norm."""
    name = (schema or "").upper()
    if name.startswith("IFC4X3"):
        return SCHEMA_TAGS["IFC4X3"]
    return SCHEMA_TAGS.get(name)


def schema_family(schema: str) -> str:
    """``ifc2x3``, ``ifc4`` or ``ifc4x3``, whichever the model is written in."""
    name = (schema or "").upper()
    if name.startswith("IFC2X3"):
        return "ifc2x3"
    if name.startswith("IFC4X3"):
        return "ifc4x3"
    return "ifc4"


# ----------------------------------------------------------------- placement

#: Degrees a storey's own axes may stand from the world axes and still count as
#: aligned.  Below this a turn is an exporter's rounding rather than a plan
#: that was drawn on a skewed grid.
ROTATION_TOLERANCE = 0.01

#: Metres a site's placement may sit from the world origin before a coordinate
#: read in the world frame stops being a coordinate read on the building.
SITE_OFFSET_TOLERANCE = 1.0


def rotation_degrees(matrix) -> float:
    """How far a placement's own axes are turned about the vertical, in degrees."""
    if matrix is None:
        return 0.0
    rotation = np.array(matrix, dtype=float)[:3, :3]
    angle = np.degrees(np.arctan2(rotation[1, 0], rotation[0, 0]))
    return float(abs(((angle + 180.0) % 360.0) - 180.0))


def is_upright_turn(matrix) -> bool:
    """True when a placement's axes are a turn about the vertical and nothing else.

    A storey drawn on a skewed grid still describes a building whose walls stand
    upright, and a world coordinate can be converted into its system exactly.  A
    placement that is mirrored, tilted or scaled cannot, so it is refused rather
    than approximated.
    """
    if matrix is None:
        return False
    rotation = np.array(matrix, dtype=float)[:3, :3]
    if abs(float(rotation[2, 2]) - 1.0) > 1e-6:
        return False
    if max(abs(float(rotation[0, 2])), abs(float(rotation[1, 2])),
           abs(float(rotation[2, 0])), abs(float(rotation[2, 1]))) > 1e-6:
        return False
    plan = rotation[:2, :2]
    if abs(float(np.linalg.det(plan)) - 1.0) > 1e-6:
        return False
    return bool(np.abs(plan @ plan.T - np.identity(2)).max() < 1e-6)


def storey_rotation(scene, storey) -> float:
    """The turn of one storey's own axes against the world axes, in degrees."""
    return rotation_degrees(scene.matrix(storey))


def is_rotated(scene, storey) -> bool:
    return storey_rotation(scene, storey) > ROTATION_TOLERANCE


def site_offset(scene) -> Optional[np.ndarray]:
    """The site's placement origin in world metres, or None when it has none."""
    if hasattr(scene, "_site_offset"):
        return getattr(scene, "_site_offset")
    import ifcopenshell.util.placement

    offset = None
    for site in scene.model.by_type("IfcSite"):
        placement = getattr(site, "ObjectPlacement", None)
        if placement is None:
            continue
        try:
            matrix = np.array(
                ifcopenshell.util.placement.get_local_placement(placement),
                dtype=float)
        except Exception:
            continue
        offset = matrix[:3, 3] * scene.unit_scale
        break
    setattr(scene, "_site_offset", offset)
    return offset


def has_site_offset(scene) -> bool:
    """True when the model's site stands far enough from the world origin.

    A world coordinate then reads on a survey grid rather than on the building,
    which is what the tag warns a reader of.
    """
    offset = site_offset(scene)
    if offset is None:
        return False
    return bool(float(np.linalg.norm(np.asarray(offset)[:2])) > SITE_OFFSET_TOLERANCE)


# ------------------------------------------------------------ representation

#: What kind of body an element carries.  The names are the taxonomy's.
REPRESENTATION_TAGS = {
    "brep": "model.representation.brep",
    "tessellated": "model.representation.brep",
    "mapped_item": "model.representation.mapped_item",
}


def item_kind(item) -> str:
    """Which body kind one representation item belongs to."""
    if item is None:
        return "none"
    if item.is_a("IfcMappedItem"):
        return "mapped_item"
    if item.is_a("IfcExtrudedAreaSolid"):
        return "extrusion"
    if item.is_a("IfcManifoldSolidBrep") or item.is_a("IfcShell") \
            or item.is_a("IfcFaceBasedSurfaceModel") \
            or item.is_a("IfcShellBasedSurfaceModel"):
        return "brep"
    if item.is_a("IfcTessellatedItem"):
        return "tessellated"
    if item.is_a("IfcBooleanResult"):
        return "boolean"
    if item.is_a("IfcSweptAreaSolid") or item.is_a("IfcSweptDiskSolid") \
            or item.is_a("IfcSurfaceCurveSweptAreaSolid"):
        return "swept"
    if item.is_a("IfcCsgSolid") or item.is_a("IfcCsgPrimitive3D"):
        return "csg"
    if item.is_a("IfcGeometricSet") or item.is_a("IfcCurve"):
        return "curve"
    return "other"


#: Which kind wins when a body holds items of more than one kind.  Geometry
#: borrowed from a type object is named first because an edit that rewrites a
#: body has to know it would rewrite every element sharing that type.
KIND_ORDER = ("mapped_item", "brep", "tessellated", "extrusion", "boolean",
              "swept", "csg", "curve", "other")


def body_representation(product):
    shape = getattr(product, "Representation", None)
    if not shape:
        return None
    representations = list(shape.Representations or ())
    for representation in representations:
        if (representation.RepresentationIdentifier or "").lower() == "body":
            return representation
    return representations[0] if representations else None


def representation_kind(product) -> str:
    """The kind of body one element carries, or ``none`` when it carries none."""
    representation = body_representation(product)
    if representation is None:
        return "none"
    items = list(representation.Items or ())
    if not items:
        return "none"
    kinds = {item_kind(item) for item in items}
    for preferred in KIND_ORDER:
        if preferred in kinds:
            return preferred
    return "other"


def representation_tag(product) -> Optional[str]:
    return REPRESENTATION_TAGS.get(representation_kind(product))


#: Which edit an element of each body kind can carry, and why not where it
#: cannot.  A resize rewrites the profile or the depth of a swept solid, so it
#: is undefinable on a body that holds no profile; a mirror flips that same
#: profile about its own centre.  Geometry borrowed from a type object is
#: shared with every other element of that type, so rewriting it would edit
#: elements the instruction never named.
UNDEFINABLE = {
    "brep": {
        "resize_extrusion": "a faceted body has no extrusion depth to set",
        "resize_profile": "a faceted body has no swept profile to resize",
        "mirror": "a faceted body has no profile that can be flipped",
    },
    "tessellated": {
        "resize_extrusion": "a tessellated body has no extrusion depth to set",
        "resize_profile": "a tessellated body has no swept profile to resize",
        "mirror": "a tessellated body has no profile that can be flipped",
    },
    "mapped_item": {
        "resize_extrusion": "the body belongs to the type object and is shared "
                            "with every element of that type",
        "resize_profile": "the body belongs to the type object and is shared "
                          "with every element of that type",
        "mirror": "the body belongs to the type object, so flipping its profile "
                  "would flip every element of that type",
    },
    "boolean": {
        "resize_extrusion": "a boolean result has no single extrusion to set",
        "resize_profile": "a boolean result has no single profile to resize",
        "mirror": "a boolean result has no single profile that can be flipped",
    },
}


def undefinable_reason(product, edit_kind: str) -> Optional[str]:
    """Why one edit cannot be written on this element's body, or None."""
    return UNDEFINABLE.get(representation_kind(product), {}).get(edit_kind)


# --------------------------------------------------------------------- names

#: Stems that mark a name as written in a language other than English wherever
#: they appear inside a word.  An exporter writes a compound noun as one word,
#: so "Innenwand-2" and "Bodenplatte" are only caught by looking inside them.
#: Each entry is long enough not to sit inside an ordinary English word.
NON_ENGLISH_STEMS = (
    # German
    "wand", "geschoss", "fenster", "mauerwerk", "stahlbeton", "brüstung",
    "stütze", "decke", "boden", "dach", "keller", "treppe", "bauteil",
    "wohnung", "aussen", "außen", "innen", "grundmauer", "putz",
    # Dutch
    "vloer", "kolom", "verdieping", "gevel", "woning", "begane grond",
    # French
    "dalle", "poteau", "fenêtre", "plancher", "cloison", "rez-de-chauss",
    "menuiserie", "escalier", "bureaux", "exterieure", "extérieure",
    # Spanish and Portuguese
    "hormig", "zapata", "cubierta", "pared", "puerta", "ventana", "parede",
    "janela", "coluna", "concreto", "madeira", "básico", "basico", "muro",
    "revestimiento", "forjado", "ciment",
    # Nordic
    "vägg", "bjälklag", "yttervegg", "innervegg", "plasstøpt", "søyle",
    "himling", "etasje",
    # Italian
    "muratura", "solaio", "pilastro",
)

#: Words that mark a name only when they stand on their own.  Each is short
#: enough, or close enough to an English word, that looking inside a word would
#: call an English name foreign.
NON_ENGLISH_WORDS = (
    "mur", "murs", "raum", "flur", "tür", "tur", "raam", "deur", "porte",
    "porta", "piso", "pilar", "laje", "losa", "etage", "étage", "vindu",
    "dør", "dekke", "kamer", "binnen", "buiten",
)

#: Every character that is not a plain ASCII one.  A name holding one is
#: written in a language whose alphabet is not the English one, whether that is
#: an accented Latin letter or a Chinese character.
_NON_ASCII = re.compile(r"[^\x00-\x7f]")

#: Names that hold one of the stems above and are ordinary English all the
#: same, so the stem test alone would call an English name foreign.
_ENGLISH_EXCEPTIONS = ("wander", "murphy", "murray", "porter", "portal",
                       "abandon", "boundary")


def is_non_english(name: str) -> bool:
    """Whether one element name is written in a language other than English.

    Three marks decide it and all three are mechanical: a character outside the
    ASCII range, one of the stems above standing anywhere inside a word, or one
    of the words above standing on its own.
    """
    text = (name or "").strip()
    if not text:
        return False
    if _NON_ASCII.search(text):
        return True
    lowered = text.lower()
    if any(word in lowered for word in _ENGLISH_EXCEPTIONS):
        return False
    if any(stem in lowered for stem in NON_ENGLISH_STEMS):
        return True
    words = re.split(r"[^a-z]+", lowered)
    return any(word in NON_ENGLISH_WORDS for word in words if word)


def anchor_names(anchor) -> list[str]:
    """The element names one anchor's phrase quotes."""
    out: list[str] = []
    params = getattr(anchor, "params", None) or {}
    for key, value in params.items():
        if isinstance(value, str) and (key == "name" or key.endswith("_name")
                                       or key in ("space", "space_name",
                                                  "host_name", "label")):
            out.append(value)
    phrase = getattr(anchor, "phrase", "") or ""
    out.extend(re.findall(r"'([^']*)'", phrase))
    return [name for name in out if name]


# ------------------------------------------------------------------ the tags


def model_tags(scene, plan, anchor=None, storey=None,
               expected=()) -> list[str]:
    """Every layer 6 condition one task carries, named after the taxonomy.

    The conditions are read off the model and off the element the task edits,
    not declared by the planner, so the benchmark can report per condition and
    the audit can recompute the tags from the record alone.
    """
    tags: list[str] = []
    tag = unit_tag(scene.unit_scale)
    if tag:
        tags.append(tag)
    tag = schema_tag(scene.schema)
    if tag:
        tags.append(tag)

    # Which storey the task touches.  An element the edit creates is not in the
    # source model yet, so its storey cannot be read from a containment
    # relationship: it is read from the parameters the create call carries, and
    # from the elements the instruction names, which stand on it.  Reading only
    # the containment left 195 create tasks on turned storeys untagged in the
    # first 0.7.0 pilot.
    storeys = []
    if storey is not None:
        storeys.append(storey)
    named = list(plan.target_guids) + list(plan.touched_guids)
    for key in ("storey_guid", "storey_to_guid", "host_guid", "host_to_guid",
                "source_guid", "replaced_guid"):
        value = plan.params.get(key)
        if isinstance(value, str):
            named.append(value)
    named.extend(str(g) for g in expected or () if isinstance(g, str))
    if anchor is not None:
        value = (getattr(anchor, "params", None) or {}).get("guid")
        if isinstance(value, str):
            named.append(value)
    for guid in dict.fromkeys(named):
        element = scene.by_guid(guid)
        if element is None:
            continue
        if element.is_a("IfcBuildingStorey"):
            storeys.append(element)
            continue
        found = scene.storey_of(element)
        if found is not None:
            storeys.append(found)
    if any(is_rotated(scene, s) for s in storeys):
        tags.append("model.placement.rotated_storey")
    if has_site_offset(scene):
        tags.append("model.placement.site_offset")

    for guid in tuple(plan.target_guids) + tuple(plan.params.get("source_guids")
                                                 or ()):
        element = scene.by_guid(guid)
        if element is None:
            continue
        tag = representation_tag(element)
        if tag:
            tags.append(tag)

    names: list[str] = []
    if anchor is not None:
        names.extend(anchor_names(anchor))
    for key in ("plane_wall", "host_to", "type_name", "material"):
        value = plan.params.get(key)
        if isinstance(value, str):
            names.append(value)
    placement = plan.params.get("placement") or {}
    for key in ("a_name", "b_name", "space_label"):
        value = placement.get(key)
        if isinstance(value, str):
            names.append(value)
    if any(is_non_english(name) for name in names):
        tags.append("model.names.non_english")

    return sorted(dict.fromkeys(tags))
