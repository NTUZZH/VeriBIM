"""Grouping source files into the buildings they were exported from.

A split has to be made by building, not by file: the corpus holds the same
building several times over, exported by different tools, at different dates,
or split by discipline.  Putting one export of a building in the training set
and another in the validation set would leak.

Three signals decide whether two files are the same building, in order of
strength.  The first is a shared set of GlobalIds: a re-export of the same
project keeps most of its identifiers, and unrelated files share at most a
handful of deterministic exporter identifiers, so the two cases are orders of
magnitude apart.  The second is a shared project name together with a shared
set of storey names.  The third is a shared filename stem after the corpus's
numbering and date prefixes are stripped.
"""

from __future__ import annotations

import gzip
import json
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Optional

# A file pair whose identifier sets overlap by at least this much is the same
# building.  Coincidental exporter identifiers give overlaps below 0.01.
GUID_JACCARD = 0.10

# Project names an exporter writes when the author left the field alone.
GENERIC_PROJECT_NAMES = {
    "", "project", "project number", "project  number", "default project",
    "projet", "undefined", "none", "0001", "123456789", "100001", "3458",
    "unnamed", "no name", "ifc project", "projectnumber", "n/a", "na",
    "numero du projet", "numéro du projet", "project name",
}

# Filename decorations the corpus adds: an Auckland index and a date stamp.
_PREFIX = re.compile(r"^\d{3}_(\d{6}|\d{8})?")
_TRAILING_DATE = re.compile(r"[-_ ]?\d{6,8}$")


def _fold(text: Optional[str]) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text.strip().lower())


def stem_key(relpath: str) -> str:
    """The filename with the corpus's own decorations removed."""
    stem = Path(relpath).stem
    stem = _PREFIX.sub("", stem)
    stem = _TRAILING_DATE.sub("", stem)
    stem = re.sub(r"[^a-z0-9]+", " ", _fold(stem)).strip()
    return stem


# Files that hold the same building but share no identifiers, because each was
# exported from a different authoring tool or covers a different discipline.
# Each entry is a group of filename fragments and the evidence that joined them.
MANUAL_MERGES: list[tuple[str, tuple[str, ...]]] = [
    ("FZK-Haus, the KIT demonstration house, exported by four tools",
     ("088_231110AC11-FZK-Haus-IFC", "100_301110FZK-Haus-EliteCAD",
      "103_301110Nem-FZK-Haus-2x3", "210_20201030AC20-FZK-Haus")),
    ("Institute building 'Variante 2', ArchiCAD and Allplan exports",
     ("089_231110AC11-Institute-Var-2-IFC",
      "094_261110Allplan-2008-Institute-Var-2-IFC")),
    ("Trapelo Road: architectural design intent and structural model",
     ("160_20160125Trapelo - Existing-RST_2010_Trapelo",
      "161_20160125Trapelo - Existing-Trapelo_Design_Intent",
      "163_20160125RST_2010_Trapelo", "164_20160125Trapelo_Design_Intent")),
    ("WestRiverSide Hospital: architectural and structural models",
     ("167_20160125WestRiverSide Hospital", "175_20160125WestRiverSide Hospital",
      "184_20190104WestRiverSide Hospital", "186_20190104WestRiverSide Hospital")),
    ("Duplex Apartment: architecture and its four discipline models",
     ("Duplex_A_20110907", "Duplex_Electrical_20121207", "Duplex_MEP_20110907",
      "Duplex_M_20111024_ROOMS_AND_SPACES", "Duplex_Plumbing_20121113")),
    ("Medical-Dental Clinic: architecture and its discipline models",
     ("Clinic_Architectural", "Clinic_Electrical", "Clinic_HVAC",
      "Clinic_Plumbing", "Clinic_Structural")),
    ("AISC connection sculpture, boundary-representation and parametric export",
     ("140_171210AISC_Sculpture_brep", "141_171210AISC_Sculpture_param")),
    ("Revit Structure analysis model, two exports",
     ("142_171210analysis_brep", "143_171210analysis_param")),
    ("Bentley Structural design model, two exports",
     ("144_171210Bentley1_brep", "145_171210Bentley1_param")),
    ("Peninsula Players Theatre, two exports",
     ("150_171210PlayersTheater_param", "150_171210PlayersTheater_brep")),
    ("buildingSMART certification sample scene, one scene split by discipline "
     "and issued in two schemas",
     ("PCERT-Sample-Scene",)),
]


def _manual_group_of(relpath: str) -> Optional[int]:
    for index, (_reason, fragments) in enumerate(MANUAL_MERGES):
        if any(fragment in relpath for fragment in fragments):
            return index
    return None


class _Union:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def load_guid_set(root: Path, sha256: str) -> set[str]:
    path = root / "data" / "corpus_guids" / f"{sha256}.txt.gz"
    if not path.exists():
        return set()
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return {line.strip() for line in handle if line.strip()}


def load_names(root: Path) -> dict[str, dict[str, Any]]:
    path = root / "data" / "corpus_build" / "names.jsonl"
    out: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            out[record["relpath"]] = record
    return out


def group(root: Path, files: list[dict[str, Any]],
          guid_jaccard: float = GUID_JACCARD) -> dict[str, dict[str, Any]]:
    """Assign every file a building id, with the evidence that put it there.

    ``files`` are manifest records; each needs ``relpath`` and ``sha256``.
    """
    root = Path(root)
    names = load_names(root)
    relpaths = [f["relpath"] for f in files]
    union = _Union(relpaths)
    evidence: dict[tuple[str, str], str] = {}

    guids = {f["relpath"]: load_guid_set(root, f["sha256"]) for f in files}
    for i, a in enumerate(relpaths):
        for b in relpaths[i + 1:]:
            ga, gb = guids[a], guids[b]
            if not ga or not gb:
                continue
            shared = len(ga & gb)
            if not shared:
                continue
            score = shared / len(ga | gb)
            if score >= guid_jaccard:
                union.union(a, b)
                evidence[(a, b)] = f"guid_jaccard={score:.3f}"

    for i, a in enumerate(relpaths):
        na = names.get(a, {})
        pa = _fold(na.get("project_name"))
        sa = {_fold(s) for s in (na.get("storey_names") or [])}
        for b in relpaths[i + 1:]:
            if union.find(a) == union.find(b):
                continue
            nb = names.get(b, {})
            pb = _fold(nb.get("project_name"))
            sb = {_fold(s) for s in (nb.get("storey_names") or [])}
            if pa and pa == pb and pa not in GENERIC_PROJECT_NAMES:
                if sa and sb and len(sa & sb) / len(sa | sb) >= 0.5:
                    union.union(a, b)
                    evidence[(a, b)] = f"project_name+storeys={pa!r}"
                    continue
            ka, kb = stem_key(a), stem_key(b)
            if ka and ka == kb:
                union.union(a, b)
                evidence[(a, b)] = f"stem={ka!r}"

    manual: dict[int, list[str]] = {}
    for relpath in relpaths:
        index = _manual_group_of(relpath)
        if index is not None:
            manual.setdefault(index, []).append(relpath)
    for index, group_files in manual.items():
        first = group_files[0]
        for other in group_files[1:]:
            union.union(first, other)
            evidence[(first, other)] = f"manual:{MANUAL_MERGES[index][0]}"

    members: dict[str, list[str]] = {}
    for relpath in relpaths:
        members.setdefault(union.find(relpath), []).append(relpath)

    out: dict[str, dict[str, Any]] = {}
    for index, (_root_path, group_files) in enumerate(
            sorted(members.items(), key=lambda kv: sorted(kv[1])[0]), start=1):
        building_id = f"BLD{index:03d}"
        label = _label(sorted(group_files), names)
        for relpath in group_files:
            out[relpath] = {"building_id": building_id, "label": label,
                            "n_files": len(group_files)}
    return out


def _label(group_files: list[str], names: dict[str, dict[str, Any]]) -> str:
    """A readable name for a building, preferring its project name."""
    for relpath in group_files:
        project = (names.get(relpath, {}) or {}).get("project_name") or ""
        if project and _fold(project) not in GENERIC_PROJECT_NAMES:
            return project.strip()
    return stem_key(group_files[0]) or Path(group_files[0]).stem
