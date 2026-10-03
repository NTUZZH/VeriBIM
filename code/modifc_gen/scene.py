"""A read-only view of one source model, with the indexes the generator needs.

Building the indexes costs one pass over the model and is done once per source
model, however many tasks that model goes on to host.  Everything a scene
reports in a length unit reports it in metres, whatever unit the file is
written in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

import numpy as np

import ifcopenshell
import ifcopenshell.util.placement
import ifcopenshell.util.unit

from . import geomindex, goldlib

# The six element families the operation library covers, and the IFC class each
# one is read from.  Subtypes come with the class, so ``IfcWall`` also collects
# ``IfcWallStandardCase``.
FAMILY_CLASS = {
    "wall": "IfcWall",
    "slab": "IfcSlab",
    "space": "IfcSpace",
    "door": "IfcDoor",
    "window": "IfcWindow",
    "column": "IfcColumn",
}

FAMILIES = tuple(FAMILY_CLASS)

# Short codes used in task identifiers.
FAMILY_CODE = {"wall": "WAL", "slab": "SLB", "space": "SPC",
               "door": "DOR", "window": "WIN", "column": "COL"}

# The relation classes the topology axis of ModIFC-Score reads.
TOPOLOGY_RELATIONS = (
    "IfcRelContainedInSpatialStructure",
    "IfcRelAggregates",
    "IfcRelSpaceBoundary",
    "IfcRelVoidsElement",
    "IfcRelFillsElement",
    "IfcRelConnectsElements",
)

# Plain names for the world axes, used by the spatial instruction templates.
AXIS_WORDS = {
    (0, 1): ("east", "+X"), (0, -1): ("west", "-X"),
    (1, 1): ("north", "+Y"), (1, -1): ("south", "-Y"),
    (2, 1): ("up", "+Z"), (2, -1): ("down", "-Z"),
}


@dataclass
class Extent:
    """A box in the coordinate system it was measured in, in metres."""

    lo: np.ndarray
    hi: np.ndarray

    @property
    def size(self) -> np.ndarray:
        return self.hi - self.lo

    def contains(self, point: np.ndarray, margin: float = 0.0) -> bool:
        return bool(np.all(point >= self.lo - margin) and
                    np.all(point <= self.hi + margin))


class Scene:
    """One parsed source model plus the indexes the generator reads."""

    def __init__(self, path: str, relpath: str = "", sha256: str = ""):
        self.path = str(path)
        self.relpath = relpath or str(path)
        self.sha256 = sha256
        self.model = ifcopenshell.open(self.path)
        self.schema = self.model.schema
        self.unit_scale = goldlib.unit_scale(self.model)

        self._by_family: dict[str, list[Any]] = {}
        for family, ifc_class in FAMILY_CLASS.items():
            try:
                self._by_family[family] = list(self.model.by_type(ifc_class))
            except Exception:
                self._by_family[family] = []

        self.storeys = sorted(self.model.by_type("IfcBuildingStorey"),
                              key=lambda s: (s.Elevation if s.Elevation is not None
                                             else 0.0, s.GlobalId))
        self.n_products = len(self.model.by_type("IfcProduct"))
        self.n_relations = sum(len(self.model.by_type(r))
                               for r in TOPOLOGY_RELATIONS)

        self._point: dict[str, np.ndarray] = {}
        self._matrix: dict[str, np.ndarray] = {}
        self._storey_of: dict[str, Any] = {}
        self._host_of: dict[str, str] = {}
        self._hosted: dict[str, list[str]] = {}
        self._bounded_spaces: dict[str, list[str]] = {}
        self._space_elements: dict[str, list[str]] = {}
        self._connected: dict[str, list[str]] = {}
        self._index_relations()
        self._name_counts: dict[str, dict[str, int]] = {}
        self._long_name_counts: dict[str, int] = {}
        self._index_names()

    # ------------------------------------------------------------- geometry

    def matrix(self, product) -> Optional[np.ndarray]:
        """World placement of a product, translation in metres."""
        guid = product.GlobalId
        if guid in self._matrix:
            return self._matrix[guid]
        placement = getattr(product, "ObjectPlacement", None)
        matrix = None
        if placement is not None:
            try:
                matrix = np.array(
                    ifcopenshell.util.placement.get_local_placement(placement),
                    dtype=float)
                matrix[:3, 3] *= self.unit_scale
            except Exception:
                matrix = None
        self._matrix[guid] = matrix
        return matrix

    def point(self, product) -> Optional[np.ndarray]:
        """World position of a product's placement origin, in metres.

        The generator locates elements by their placement origin rather than by
        a meshed centroid: it is exact, it costs nothing to compute, and it is
        the same quantity the spatial anchors are checked against.
        """
        guid = product.GlobalId
        if guid in self._point:
            return self._point[guid]
        matrix = self.matrix(product)
        self._point[guid] = None if matrix is None else matrix[:3, 3].copy()
        return self._point[guid]

    def local_extent(self, product) -> Optional[Extent]:
        """Box of a product's single extruded body in its own axes, in metres.

        ``None`` when the product has no body the generator can read: a mapped
        or faceted representation carries no profile to measure.
        """
        solid = goldlib.sole_extrusion(self.model, product)
        if solid is None:
            return None
        profile = solid.SweptArea
        points = _profile_points(profile)
        if points is None:
            return None
        points = points * self.unit_scale
        depth = float(solid.Depth) * self.unit_scale
        position = np.identity(4)
        if solid.Position is not None:
            position = np.array(ifcopenshell.util.placement.get_axis2placement(
                solid.Position), dtype=float)
            position[:3, 3] *= self.unit_scale
        lo = np.array([points[:, 0].min(), points[:, 1].min(), 0.0])
        hi = np.array([points[:, 0].max(), points[:, 1].max(), depth])
        lo = position[:3, :3] @ lo + position[:3, 3]
        hi = position[:3, :3] @ hi + position[:3, 3]
        return Extent(np.minimum(lo, hi), np.maximum(lo, hi))

    def has_body(self, product) -> bool:
        """True when the product carries geometry the score can compare.

        An element without a representation has no surface, so a task that
        edited it could not be scored on the geometry axis at all.
        """
        shape = getattr(product, "Representation", None)
        return bool(shape and (shape.Representations or ()))

    def body_donor(self) -> Optional[str]:
        """An element whose body names the context created geometry goes in."""
        for family in FAMILIES:
            for element in self.elements(family):
                if goldlib.body_representation(element) is not None:
                    return element.GlobalId
        return None

    def extrusion_axis(self, product) -> Optional[np.ndarray]:
        solid = goldlib.sole_extrusion(self.model, product)
        if solid is None:
            return None
        try:
            return goldlib.extrusion_world_direction(product, solid)
        except Exception:
            return None

    # ------------------------------------------------------------ relations

    def _index_relations(self) -> None:
        for relation in self.model.by_type("IfcRelContainedInSpatialStructure"):
            structure = relation.RelatingStructure
            storey = _storey_ancestor(structure)
            if storey is None:
                continue
            for element in relation.RelatedElements or ():
                self._storey_of[element.GlobalId] = storey.GlobalId
        for relation in self.model.by_type("IfcRelAggregates"):
            parent = relation.RelatingObject
            storey = _storey_ancestor(parent)
            if storey is None:
                continue
            for child in relation.RelatedObjects or ():
                self._storey_of.setdefault(child.GlobalId, storey.GlobalId)
        for relation in self.model.by_type("IfcRelVoidsElement"):
            opening = relation.RelatedOpeningElement
            host = relation.RelatingBuildingElement
            if opening is None or host is None:
                continue
            for fills in getattr(opening, "HasFillings", ()) or ():
                filling = fills.RelatedBuildingElement
                if filling is None:
                    continue
                self._host_of[filling.GlobalId] = host.GlobalId
                self._hosted.setdefault(host.GlobalId, []).append(filling.GlobalId)
        for relation in self.model.by_type("IfcRelSpaceBoundary"):
            space = relation.RelatingSpace
            element = relation.RelatedBuildingElement
            if space is None or element is None:
                continue
            self._bounded_spaces.setdefault(element.GlobalId, []).append(space.GlobalId)
            self._space_elements.setdefault(space.GlobalId, []).append(element.GlobalId)
        for relation in self.model.by_type("IfcRelConnectsElements"):
            a, b = relation.RelatingElement, relation.RelatedElement
            if a is None or b is None:
                continue
            self._connected.setdefault(a.GlobalId, []).append(b.GlobalId)
            self._connected.setdefault(b.GlobalId, []).append(a.GlobalId)
        for mapping in (self._hosted, self._bounded_spaces, self._space_elements,
                        self._connected):
            for key, values in mapping.items():
                mapping[key] = sorted(dict.fromkeys(values))

    def elements(self, family: str) -> list[Any]:
        if family == "storey":
            return self.storeys
        return self._by_family.get(family, [])

    def storey_guid_of(self, product) -> Optional[str]:
        """Identifier of the storey a product sits on.

        Identifiers rather than entities: IfcOpenShell hands out a fresh wrapper
        object on every lookup, so two references to one storey are not the same
        Python object and must not be compared as if they were.
        """
        return self._storey_of.get(product.GlobalId)

    def storey_of(self, product):
        guid = self._storey_of.get(product.GlobalId)
        return None if guid is None else self.by_guid(guid)

    def on_storey(self, family: str, storey_guid: str) -> list[Any]:
        """The family's elements on one storey, grouped once per family.

        Every draw asks this question many times, and a model with four
        thousand slabs would otherwise be walked once per question, so the
        grouping is built on the first question and kept.
        """
        cache = getattr(self, "_by_storey", None)
        if cache is None:
            cache = {}
            setattr(self, "_by_storey", cache)
        grouped = cache.get(family)
        if grouped is None:
            grouped = {}
            for element in self.elements(family):
                grouped.setdefault(self._storey_of.get(element.GlobalId),
                                   []).append(element)
            cache[family] = grouped
        return grouped.get(storey_guid, [])

    def host_of(self, product) -> Optional[str]:
        return self._host_of.get(product.GlobalId)

    def hosted_by(self, product) -> list[str]:
        return self._hosted.get(product.GlobalId, [])

    def bounded_spaces(self, product) -> list[str]:
        return self._bounded_spaces.get(product.GlobalId, [])

    def space_elements(self, space) -> list[str]:
        return self._space_elements.get(space.GlobalId, [])

    def connected(self, product) -> list[str]:
        return self._connected.get(product.GlobalId, [])

    def by_guid(self, guid: str):
        try:
            return self.model.by_guid(guid)
        except Exception:
            return None

    # ------------------------------------------------------------ labelling

    def storey_label(self, storey) -> Optional[str]:
        """A phrase that identifies one storey and no other.

        A storey name is used when it is the only storey carrying it; otherwise
        the storey's elevation is used, again only when it is unique.
        """
        name = (storey.Name or "").strip()
        if name and sum(1 for s in self.storeys
                        if (s.Name or "").strip() == name) == 1:
            return f"storey '{name}'"
        elevation = storey.Elevation
        if elevation is None:
            return None
        metres = float(elevation) * self.unit_scale
        same = [s for s in self.storeys if s.Elevation is not None
                and abs(float(s.Elevation) * self.unit_scale - metres) < 1e-6]
        if len(same) == 1:
            return f"the storey at elevation {metres:.2f} m"
        return None

    def _index_names(self) -> None:
        """Count how often each name occurs, so uniqueness is a lookup.

        Names are asked for once per candidate element and a model can hold
        thousands, so counting up front turns a quadratic scan into a table.
        """
        for family in tuple(FAMILY_CLASS) + ("storey",):
            counts: dict[str, int] = {}
            for element in self.elements(family):
                name = (element.Name or "").strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
            self._name_counts[family] = counts
        for space in self.elements("space"):
            long_name = (getattr(space, "LongName", None) or "").strip()
            if long_name:
                self._long_name_counts[long_name] = (
                    self._long_name_counts.get(long_name, 0) + 1)

    def unique_name(self, product) -> Optional[str]:
        """The product's name, when no other element of its family shares it."""
        name = (product.Name or "").strip()
        if not name:
            return None
        family = self.family_of(product)
        if family is None:
            return None
        return name if self._name_counts.get(family, {}).get(name, 0) == 1 else None

    def unique_long_name(self, space) -> Optional[str]:
        long_name = (getattr(space, "LongName", None) or "").strip()
        if not long_name:
            return None
        return long_name if self._long_name_counts.get(long_name, 0) == 1 else None

    def space_phrase(self, space) -> Optional[str]:
        label = self.unique_long_name(space) or self.unique_name(space)
        return f"space '{label}'" if label else None

    def family_of(self, product) -> Optional[str]:
        """Which family a product belongs to, ``storey`` included.

        Storeys are not editable targets, but instructions name them, so they
        need a family label for the anchor machinery.
        """
        for family, ifc_class in FAMILY_CLASS.items():
            if product.is_a(ifc_class):
                return family
        if product.is_a("IfcBuildingStorey"):
            return "storey"
        return None

    # --------------------------------------------------------------- extent

    def storey_extent(self, storey) -> Optional[Extent]:
        """Box over the placement origins of everything the storey holds."""
        points = []
        for family in FAMILIES:
            for element in self.on_storey(family, storey.GlobalId):
                point = self.point(element)
                if point is not None:
                    points.append(point)
        if len(points) < 4:
            return None
        stacked = np.vstack(points)
        return Extent(stacked.min(axis=0), stacked.max(axis=0))

    def storey_local_extent(self, storey) -> Optional[Extent]:
        """The storey's own extent expressed in the storey's coordinates."""
        extent = self.storey_extent(storey)
        matrix = self.matrix(storey)
        if extent is None or matrix is None:
            return None
        inverse = np.linalg.inv(matrix)
        corners = np.array([[x, y, z]
                            for x in (extent.lo[0], extent.hi[0])
                            for y in (extent.lo[1], extent.hi[1])
                            for z in (extent.lo[2], extent.hi[2])])
        local = (inverse[:3, :3] @ corners.T).T + inverse[:3, 3]
        return Extent(local.min(axis=0), local.max(axis=0))

    # ------------------------------------------------- geometric footprint

    def geometry_index(self) -> dict:
        """World bounding box, class and storey of every element with a body."""
        index = getattr(self, "_geometry_index", None)
        if index is None:
            index = geomindex.build(self.path, self.model)
            setattr(self, "_geometry_index", index)
        return index

    def mesh(self, product):
        """The scorer's own triangle mesh of a product, cached per scene."""
        from modifc_score.geometry import mesh_for
        from modifc_score.model_cache import MeshCache, model_key

        cache = getattr(self, "_mesh_cache", None)
        if cache is None:
            cache = MeshCache(capacity_vertices=1_000_000)
            setattr(self, "_mesh_cache", cache)
        key = getattr(self, "_mesh_key", None)
        if key is None:
            key = model_key(self.path)
            setattr(self, "_mesh_key", key)
        try:
            mesh = mesh_for(product, key, cache, 0.001, False)
        except Exception:
            return None
        if mesh is None or len(mesh.verts) == 0:
            return None
        return mesh

    def box_in_frame(self, product, matrix) -> Optional[Extent]:
        """Box of a product's meshed body in the frame ``matrix`` describes."""
        mesh = self.mesh(product)
        if mesh is None or matrix is None:
            return None
        inverse = np.linalg.inv(matrix)
        local = (inverse[:3, :3] @ mesh.verts.T).T + inverse[:3, 3]
        return Extent(local.min(axis=0), local.max(axis=0))

    def centre(self, product) -> Optional[np.ndarray]:
        """World centre of a product's body, falling back to its origin.

        A relative reference reads as a person reads it, from where the element
        stands rather than from where its placement happens to be written: a
        wall's origin sits at one end of it, so the origin would make "nearest"
        mean something the reader cannot see.
        """
        box = self.world_box(product)
        if box is not None:
            return (box.lo + box.hi) / 2.0
        return self.point(product)

    def storey_neighbour(self, storey, direction: int):
        """The storey immediately above (+1) or below (-1) this one.

        ``None`` when the model has no such storey, or when two storeys share
        an elevation and the phrase would not name one of them.
        """
        here = storey.Elevation
        if here is None:
            return None
        here = float(here) * self.unit_scale
        others = [(float(s.Elevation) * self.unit_scale, s) for s in self.storeys
                  if s.Elevation is not None and s.GlobalId != storey.GlobalId]
        side = [(e, s) for e, s in others
                if (e > here + 0.5 if direction > 0 else e < here - 0.5)]
        if not side:
            return None
        best = min(side, key=lambda pair: abs(pair[0] - here))
        close = [s for e, s in side if abs(e - best[0]) < 1e-6]
        return best[1] if len(close) == 1 else None

    def own_frame_box(self, product) -> Optional[Extent]:
        """Box of a product's meshed body in the product's own axes, in metres."""
        return self.box_in_frame(product, self.matrix(product))

    def world_box(self, product) -> Optional[Extent]:
        """Axis-aligned world box of a product, read from the geometry index."""
        index = self.geometry_index()
        position = index["lookup"].get(product.GlobalId)
        if position is None:
            return None
        return Extent(index["lo"][position].copy(), index["hi"][position].copy())

    def storey_footprint(self, storey) -> Optional[Extent]:
        """Box over the geometry of everything the storey holds, in world axes.

        A storey too few of whose elements carry a body has no footprint the
        placement rules can trust, and they stand down rather than guess.
        """
        cached = getattr(self, "_footprints", None)
        if cached is None:
            cached = {}
            setattr(self, "_footprints", cached)
        guid = storey.GlobalId
        if guid in cached:
            return cached[guid]
        index = self.geometry_index()
        same = index["storey"] == guid
        footprint = None
        if int(same.sum()) >= geomindex.MIN_STOREY_ELEMENTS:
            footprint = Extent(index["lo"][same].min(axis=0),
                               index["hi"][same].max(axis=0))
        cached[guid] = footprint
        return footprint

    def storey_local_footprint(self, storey) -> Optional[Extent]:
        """The storey's geometric footprint expressed in the storey's axes."""
        footprint = self.storey_footprint(storey)
        matrix = self.matrix(storey)
        if footprint is None or matrix is None:
            return None
        inverse = np.linalg.inv(matrix)
        corners = np.array([[x, y, z]
                            for x in (footprint.lo[0], footprint.hi[0])
                            for y in (footprint.lo[1], footprint.hi[1])
                            for z in (footprint.lo[2], footprint.hi[2])])
        local = (inverse[:3, :3] @ corners.T).T + inverse[:3, 3]
        return Extent(local.min(axis=0), local.max(axis=0))

    def occupied_share(self, points: np.ndarray, storey_guid: str,
                       skip: Iterable[str] = ()) -> float:
        """Largest share of ``points`` any one neighbour's box already holds.

        The points sample the body a draw wants to place, and a neighbour is
        another solid element of the same storey.  The share is measured
        against the neighbour's bounding box, which is an upper bound on the
        share of its solid, so a draw this test lets through cannot collide.

        An element the model files under no storey counts as a neighbour of
        every storey.  Between a sixth and a quarter of the bodies in this
        corpus are recorded that way, furniture and building-element proxies
        above all, and they are matter whatever the file says about where they
        belong: reading only the named storey let a re-hosted door land a fifth
        of its volume inside a proxy in the 0.7.0 pilot.
        """
        if points.size == 0 or not storey_guid:
            return 0.0
        index = self.geometry_index()
        if index["guid"].size == 0:
            return 0.0
        lo = points.min(axis=0)
        hi = points.max(axis=0)
        here = (index["storey"] == storey_guid) | (index["storey"] == "")
        near = here & index["solid"] \
            & np.all(index["lo"] <= hi + 1e-6, axis=1) \
            & np.all(index["hi"] >= lo - 1e-6, axis=1)
        skip = set(skip)
        worst = 0.0
        for position in np.where(near)[0]:
            if str(index["guid"][position]) in skip:
                continue
            inside = np.all(points >= index["lo"][position] - 1e-6, axis=1) & \
                np.all(points <= index["hi"][position] + 1e-6, axis=1)
            share = float(inside.mean())
            if share > worst:
                worst = share
        return worst

    def scene_extent(self) -> Optional[Extent]:
        points = [self.point(e) for family in FAMILIES
                  for e in self.elements(family)]
        points = [p for p in points if p is not None]
        if len(points) < 4:
            return None
        stacked = np.vstack(points)
        return Extent(stacked.min(axis=0), stacked.max(axis=0))

    def scene_diagonal(self) -> float:
        extent = self.scene_extent()
        if extent is None:
            return 0.0
        return float(np.linalg.norm(extent.size))


def _profile_points(profile) -> Optional[np.ndarray]:
    """Corner points of a profile in profile coordinates, in model units.

    Only the two profile kinds the generator can measure are read: a rectangle
    and a closed polyline.  Anything else returns ``None`` and the element is
    skipped rather than guessed at.
    """
    if profile.is_a("IfcRectangleProfileDef"):
        half = np.array([float(profile.XDim) / 2.0, float(profile.YDim) / 2.0])
        points = np.array([[-half[0], -half[1]], [half[0], half[1]]])
    elif profile.is_a("IfcArbitraryClosedProfileDef"):
        curve = profile.OuterCurve
        if not curve.is_a("IfcPolyline"):
            return None
        points = np.array([p.Coordinates[:2] for p in curve.Points], dtype=float)
    else:
        return None
    position = getattr(profile, "Position", None)
    if position is not None:
        origin = np.array(position.Location.Coordinates, dtype=float)
        if position.RefDirection is not None:
            ref = np.array(position.RefDirection.DirectionRatios, dtype=float)
            norm = float(np.linalg.norm(ref)) or 1.0
            ref = ref / norm
            rotation = np.array([[ref[0], -ref[1]], [ref[1], ref[0]]])
        else:
            rotation = np.identity(2)
        points = (rotation @ points.T).T + origin
    return points


def _storey_ancestor(structure):
    """The building storey a spatial structure belongs to, if any."""
    seen = 0
    while structure is not None and seen < 8:
        if structure.is_a("IfcBuildingStorey"):
            return structure
        parents = getattr(structure, "Decomposes", ()) or ()
        structure = parents[0].RelatingObject if parents else None
        seen += 1
    return None
