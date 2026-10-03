"""Migrator v2: IFC2X3 -> IFC4 -> IFC4X3 migration that adds no schema violation beyond those the
source file already carries.

Base: ifcopenshell 0.8.5 `ifcopenshell.util.schema.Migrator`, plus the subclass logic of
scripts/corpus/probe_migrate.py (three IFC4 -> IFC4X3 class renames, the IfcRelOccupiesSpaces mapping and the
tolerant attribute step), copied here with the fixes below. Every rule counts its changes in `Migrator.rules`.

Rules (key in the report's "rules" dict):
  rename:<Class>.<Attr>          attribute renamed between the two schemas that ifcopenshell's mapping lacks
                                 (IFC4 CurveFont -> IFC4X3 CurveStyleFont, Axis -> AxisDirection, ModelorDraughting ->
                                 ModelOrDraughting, Expression -> MaterialExpression; IFC2X3 UrlReference ->
                                 URLReference, NumberOfRiser -> NumberOfRisers). The value is carried unchanged.
  nested_aggregate:<Class>.<Attr> list of lists of entities (IfcBSplineSurface.ControlPointsList) migrated element by
                                 element; the stock Migrator copied the inner lists without migrating them and wrote
                                 empty lists.
  wrap_select:<Class>.<Attr>     a bare IfcParameterValue whose attribute became a SELECT (IFC4 StartParam/EndParam ->
                                 IFC4X3 IfcCurveMeasureSelect) is wrapped as IfcParameterValue; the stock step dropped
                                 these values, so the sweep ran over the whole directrix. Other bare values that no
                                 longer fit (IFC2X3 stiffness measures, IfcRelAssigns.RelatedObjectsType) stay dropped.
  enum_default:<Class>.<Attr>=V  mandatory enumeration with no source value: IfcDoorType.PredefinedType = DOOR,
                                 IfcWindowType.PredefinedType = WINDOW, IfcWindowType.PartitioningType = the old
                                 IfcWindowStyle.OperationType when that literal exists in IfcWindowTypePartitioningEnum,
                                 else NOTDEFINED; any other mandatory enumeration = NOTDEFINED.
  enum_notdefined_invalid:<Class>.<Attr>  tolerant step of probe_migrate.py: a source literal that does not exist in the
                                 target enumeration becomes NOTDEFINED (unchanged behaviour, now counted).
  structural_axis:<Class>        IfcStructuralCurveMember / IfcStructuralCurveConnection Axis (IFC4) with no source
                                 value: unit vector perpendicular to the member's own edge (IfcTopologyRepresentation
                                 IfcEdge start -> end), in the member's ObjectPlacement axes: world +Z projected
                                 perpendicular to the edge, or world +X projected when the edge is vertical (horizontal
                                 component of the unit edge < 1e-3). A horizontal member gets (0,0,1), a vertical one
                                 (1,0,0).
  structural_axis_fallback:<Class>  the edge is not computable (no IfcEdge with two IfcVertexPoint): (0,0,1) in the
                                 placement axes; counted and reported.
  virtual_boundary_element       IfcRelSpaceBoundary without RelatedBuildingElement (optional in IFC2X3, mandatory in
                                 IFC4): one IfcVirtualElement per boundary, no placement, no representation, as the IFC4
                                 documentation prescribes for virtual boundaries.
  virtual_boundary_containment   one IfcRelContainedInSpatialStructure per storey holding those virtual elements; the
                                 storey is the IfcBuildingStorey the space decomposes (the nearest non-space spatial
                                 ancestor when the space has no storey ancestor).
  port_nests:IfcRelConnectsPortToElement  IFC2X3 port-to-element relation whose element is not an
                                 IfcDistributionElement (IFC4 narrowed RelatedElement to IfcDistributionElement): migrated
                                 as IfcRelNests(RelatingObject = element, RelatedObjects = [port]), same GlobalId, Name,
                                 Description, the IFC4 way of attaching a port to an element.
  surface_feature_adheres        IFC4X3 requires every IfcSurfaceFeature to adhere to exactly one element
                                 (IfcRelAdheresToElement, new in IFC4X3). The host is the element whose ObjectPlacement
                                 is the feature's PlacementRelTo (the authoring tool placed the feature on it); one
                                 IfcRelAdheresToElement per host. Features without such a unique host are left and
                                 reported.
A mandatory attribute that is null in the source while the source schema also declares it mandatory is a source issue:
it is left null and counted in "carried_nulls". A mandatory null that no rule covers is counted in "unhandled_nulls".
New GlobalIds are deterministic (uuid5 of the source boundary / storey / host GlobalId and step id).
"""
import collections, gc, os, time, uuid
import numpy as np
import ifcopenshell, ifcopenshell.guid, ifcopenshell.util.placement
import ifcopenshell.ifcopenshell_wrapper as W
from ifcopenshell.util.schema import Migrator as _Migrator

CLASS_4_TO_4X3 = {"IfcWindowStyle": "IfcWindowType", "IfcDoorStyle": "IfcDoorType",
                  "IfcWallStandardCase": "IfcWall"}
# IFC2X3 entities absent from IFC4 that ifcopenshell's class_2x3_to_4.json does not map (seen on Svaleveien).
CLASS_2X3_TO_4_EXTRA = {"IfcRelOccupiesSpaces": "IfcRelAssignsToActor"}
# (source schema, target schema, target class, target attribute) -> source attribute
RENAMES = {
    ("IFC4", "IFC4X3", "IfcCurveStyleFontAndScaling", "CurveStyleFont"): "CurveFont",
    ("IFC4", "IFC4X3", "IfcStructuralCurveConnection", "AxisDirection"): "Axis",
    ("IFC4", "IFC4X3", "IfcFillAreaStyle", "ModelOrDraughting"): "ModelorDraughting",
    ("IFC4", "IFC4X3", "IfcMaterialRelationship", "MaterialExpression"): "Expression",
    ("IFC2X3", "IFC4", "IfcImageTexture", "URLReference"): "UrlReference",
    ("IFC2X3", "IFC4", "IfcStairFlight", "NumberOfRisers"): "NumberOfRiser",
}
ENUM_CLASS_DEFAULT = {("IfcDoorType", "PredefinedType"): "DOOR", ("IfcWindowType", "PredefinedType"): "WINDOW"}
# Source value types wrapped when the target attribute became a SELECT. Only IfcParameterValue (sweep/trim parameters,
# IFC4 REAL -> IFC4X3 IfcCurveMeasureSelect), where the wrapped value means exactly what the bare one meant. IFC2X3
# IfcBoundaryNodeCondition stiffness values (-1 = rigid in IFC2X3, IfcBoolean TRUE in IFC4) stay dropped as in v1.
WRAP_TYPES = ("IfcParameterValue",)
AXIS_CLASSES = ("IfcStructuralCurveMember", "IfcStructuralCurveConnection")
VERTICAL_TOL = 1e-3          # horizontal component of the unit edge below which a member counts as vertical
_NS = uuid.UUID("5d0c3a52-8f3e-4c1e-9a55-6d2b1f0e7a10")


def det_guid(key):
    return ifcopenshell.guid.compress(uuid.uuid5(_NS, key).hex)


def _unwrap(t):
    while isinstance(t, (W.named_type, W.type_declaration)):
        t = t.declared_type()
    return t


class Migrator(_Migrator):
    """ifcopenshell's Migrator plus the IFC4 -> IFC4X3 class renames it lacks, the tolerant attribute step of
    probe_migrate.py, and the v2 rules listed in the module docstring."""

    def __init__(self):
        super().__init__()
        self.dropped = collections.Counter()
        self.rules = collections.Counter()
        self.carried = collections.Counter()
        self.unhandled = collections.Counter()
        self.pending_boundaries = []      # (new boundary id, old boundary id)
        self._ainfo = {}
        self._tinfo = {}

    # ---------------------------------------------------------------- helpers
    def _attr_info(self, schema_name, cls, name):
        """(optional, unwrapped type) of attribute `name` of `cls` in schema `schema_name`; None if absent."""
        k = (schema_name, cls, name)
        if k not in self._ainfo:
            sc = W.schema_by_name(schema_name)
            decl = sc.declaration_by_name(cls)
            info = None
            for a in decl.all_attributes():
                if a.name() == name:
                    info = (a.optional(), _unwrap(a.type_of_attribute()), a.type_of_attribute())
                    break
            self._ainfo[k] = info
        return self._ainfo[k]

    def _src_equivalent(self, element, new_element, name, new_file):
        """Name of the source attribute that feeds target attribute `name`, or None."""
        if hasattr(element, name):
            return name
        old_s = element.wrapped_data.file.schema
        ren = RENAMES.get((old_s, new_file.schema, new_element.is_a(), name))
        if ren and hasattr(element, ren):
            return ren
        key = ("IFC4", "IFC2X3") if new_file.schema == "IFC4" else ("IFC4X3", "IFC4")
        eq = self.attributes_mapping.get(key, {}).get(new_element.is_a(), {}).get(name)
        if eq and hasattr(element, eq):
            return eq
        return None

    def _migrate_value(self, value, new_file):
        if isinstance(value, ifcopenshell.entity_instance):
            return self.migrate(value, new_file)
        if isinstance(value, (list, tuple)):
            return [self._migrate_value(v, new_file) for v in value]
        return value

    @staticmethod
    def _has_entity(value):
        if isinstance(value, ifcopenshell.entity_instance):
            return True
        if isinstance(value, (list, tuple)):
            return any(Migrator._has_entity(v) for v in value)
        return False

    # ---------------------------------------------------------------- classes
    def migrate(self, element, new_file):
        if (element.id() and new_file.schema == "IFC4" and element.id() not in self.migrated_ids
                and element.is_a("IfcRelConnectsPortToElement") and element.wrapped_data.file.schema == "IFC2X3"):
            nest = self._port_to_nests(element, new_file)
            if nest is not None:
                return nest
        return super().migrate(element, new_file)

    def _port_to_nests(self, element, new_file):
        rel_el, port = element.RelatedElement, element.RelatingPort
        if rel_el is None or port is None:
            return None
        new_el = self.migrate(rel_el, new_file)
        if new_el.is_a("IfcDistributionElement"):
            return None
        if any(r.is_a("IfcRelNests") for r in element.wrapped_data.file.get_inverse(port)):
            self.unhandled["IfcRelConnectsPortToElement.RelatedElement:port_already_nested"] += 1
            return None
        new_port = self.migrate(port, new_file)
        oh = self.migrate(element.OwnerHistory, new_file) if element.OwnerHistory is not None else None
        nest = new_file.create_entity("IfcRelNests", GlobalId=element.GlobalId, OwnerHistory=oh, Name=element.Name,
                                      Description=element.Description, RelatingObject=new_el, RelatedObjects=[new_port])
        self.migrated_ids[element.id()] = nest.id()
        self.rules["port_nests:IfcRelConnectsPortToElement"] += 1
        return nest

    def migrate_class(self, element, new_file):
        ifc_class = element.is_a()
        if new_file.schema == "IFC4X3" and ifc_class in CLASS_4_TO_4X3:
            return new_file.create_entity(CLASS_4_TO_4X3[ifc_class])
        if new_file.schema == "IFC4" and ifc_class in CLASS_2X3_TO_4_EXTRA:
            return new_file.create_entity(CLASS_2X3_TO_4_EXTRA[ifc_class])
        return super().migrate_class(element, new_file)

    # ------------------------------------------------------------- attributes
    def _target_info(self, attribute, cls, name):
        """(optional, nested entity aggregate?) of a target attribute, cached per class and name."""
        k = (cls, name)
        v = self._tinfo.get(k)
        if v is None:
            t = _unwrap(attribute.type_of_attribute()); depth = 0
            while isinstance(t, W.aggregation_type):
                t = _unwrap(t.type_of_element()); depth += 1
            nested = depth >= 2 and isinstance(t, (W.entity, W.select_type))
            v = self._tinfo[k] = (attribute.optional(), nested)
        return v

    def migrate_attribute(self, attribute, element, new_file, new_element, new_element_schema):
        name = attribute.name(); cls = new_element.is_a()
        old_s = element.wrapped_data.file.schema
        optional, nested = self._target_info(attribute, cls, name)
        if self._special_attribute(attribute, element, new_file, new_element, name, cls, old_s, nested):
            pass
        else:
            try:
                super().migrate_attribute(attribute, element, new_file, new_element, new_element_schema)
            except Exception as ex:
                if not self._wrap_select(attribute, element, new_file, new_element, name, cls, old_s):
                    self.dropped[f"{cls}.{name}:{type(ex).__name__}"] += 1
                    if not optional:
                        if name in ("PredefinedType", "PartitioningType", "OperationType"):
                            setattr(new_element, name, "NOTDEFINED")
                            self.rules[f"enum_notdefined_invalid:{cls}.{name}"] += 1
                        else:
                            raise
        if not optional:
            try:
                cur = getattr(new_element, name)
            except Exception:
                cur = None
            if cur is None:
                self._mandatory_null(attribute, element, new_file, new_element, name, cls, old_s)

    def _special_attribute(self, attribute, element, new_file, new_element, name, cls, old_s, nested):
        ren = RENAMES.get((old_s, new_file.schema, cls, name))
        if ren and not hasattr(element, name) and hasattr(element, ren):
            value = getattr(element, ren)
            if value is not None:
                setattr(new_element, name, self._migrate_value(value, new_file))
                self.rules[f"rename:{cls}.{name}"] += 1
            return True
        if nested and hasattr(element, name):
            value = getattr(element, name)
            if value and self._has_entity(value):
                setattr(new_element, name, self._migrate_value(value, new_file))
                self.rules[f"nested_aggregate:{cls}.{name}"] += 1
                return True
        return False

    def _wrap_select(self, attribute, element, new_file, new_element, name, cls, old_s):
        t = _unwrap(attribute.type_of_attribute())
        if not isinstance(t, W.select_type):
            return False
        src = self._src_equivalent(element, new_element, name, new_file)
        if src is None:
            return False
        value = getattr(element, src)
        if value is None or isinstance(value, (ifcopenshell.entity_instance, list, tuple)):
            return False
        info = self._attr_info(old_s, element.is_a(), src)
        if info is None:
            return False
        decl = info[2]
        while isinstance(decl, W.named_type):
            decl = decl.declared_type()
        tname = decl.name() if hasattr(decl, "name") else None
        from ifcopenshell.validate import get_select_members
        members = get_select_members(W.schema_by_name(new_file.schema_identifier), t)
        if tname not in WRAP_TYPES or tname not in members:
            return False
        try:
            setattr(new_element, name, new_file.create_entity(tname, value))
        except Exception:
            return False
        self.rules[f"wrap_select:{cls}.{name}"] += 1
        return True

    def _mandatory_null(self, attribute, element, new_file, new_element, name, cls, old_s):
        src = self._src_equivalent(element, new_element, name, new_file)
        if src is not None and getattr(element, src) is None:
            info = self._attr_info(old_s, element.is_a(), src)
            if info is not None and not info[0]:
                self.carried[f"{cls}.{name}"] += 1
                return
        t = _unwrap(attribute.type_of_attribute())
        if isinstance(t, W.enumeration_type):
            items = set(t.enumeration_items())
            value = ENUM_CLASS_DEFAULT.get((cls, name))
            if cls == "IfcWindowType" and name == "PartitioningType":
                op = getattr(element, "OperationType", None) if element.is_a("IfcWindowStyle") else None
                value = op if op in items else "NOTDEFINED"
            if value is None and "NOTDEFINED" in items:
                value = "NOTDEFINED"
            if value is not None and value in items:
                setattr(new_element, name, value)
                self.rules[f"enum_default:{cls}.{name}={value}"] += 1
                return
        if name in ("Axis", "AxisDirection") and any(new_element.is_a(c) for c in AXIS_CLASSES):
            axis, ok = self._structural_axis(element)
            setattr(new_element, name, new_file.create_entity("IfcDirection", DirectionRatios=axis))
            base = "IfcStructuralCurveMember" if new_element.is_a("IfcStructuralCurveMember") else "IfcStructuralCurveConnection"
            self.rules[f"structural_axis{'' if ok else '_fallback'}:{base}"] += 1
            return
        if cls.startswith("IfcRelSpaceBoundary") and name == "RelatedBuildingElement":
            self.pending_boundaries.append((new_element.id(), element.id()))
            return
        self.unhandled[f"{cls}.{name}"] += 1

    @staticmethod
    def _structural_axis(element):
        """Axis for a structural curve item, in its ObjectPlacement axes, and whether the edge was computable."""
        try:
            R = np.array(ifcopenshell.util.placement.get_local_placement(element.ObjectPlacement), dtype=float)[:3, :3] \
                if element.ObjectPlacement is not None else np.identity(3)
        except Exception:
            R = np.identity(3)
        d = None
        rep = element.Representation
        for r in (rep.Representations if rep is not None else ()) or ():
            for it in r.Items or ():
                e = it
                if e.is_a("IfcOrientedEdge"):
                    e = e.EdgeElement
                if e.is_a("IfcEdge"):
                    try:
                        a = np.array(e.EdgeStart.VertexGeometry.Coordinates, dtype=float)
                        b = np.array(e.EdgeEnd.VertexGeometry.Coordinates, dtype=float)
                        a = np.pad(a, (0, 3 - len(a))); b = np.pad(b, (0, 3 - len(b)))
                        if np.linalg.norm(b - a) > 0:
                            d = (b - a) / np.linalg.norm(b - a)
                            break
                    except Exception:
                        pass
            if d is not None:
                break
        if d is None:
            return (0.0, 0.0, 1.0), False
        dw = R @ d; dw /= np.linalg.norm(dw)
        ref = np.array([1.0, 0.0, 0.0]) if np.hypot(dw[0], dw[1]) < VERTICAL_TOL else np.array([0.0, 0.0, 1.0])
        zw = ref - np.dot(ref, dw) * dw; zw /= np.linalg.norm(zw)
        zl = R.T @ zw; zl /= np.linalg.norm(zl)
        zl = [0.0 if abs(x) < 1e-12 else float(round(x, 12)) for x in zl]
        return tuple(zl), True

    # ------------------------------------------------------------- post-pass
    def postprocess(self, old_file, new_file):
        self._virtual_boundaries(old_file, new_file)
        if new_file.schema == "IFC4X3":
            self._surface_feature_hosts(new_file)

    @staticmethod
    def _storey_of_space(space):
        node, first_non_space = space, None
        for _ in range(32):
            parents = [r.RelatingObject for r in (getattr(node, "Decomposes", ()) or ()) if r.is_a("IfcRelAggregates")]
            if not parents:
                break
            node = parents[0]
            if node.is_a("IfcBuildingStorey"):
                return node, True
            if first_non_space is None and node.is_a("IfcSpatialElement") and not node.is_a("IfcSpace"):
                first_non_space = node
        return (first_non_space or space), False

    def _virtual_boundaries(self, old_file, new_file):
        by_storey = collections.OrderedDict()
        for new_id, old_id in self.pending_boundaries:
            b = new_file.by_id(new_id)
            if b.RelatedBuildingElement is not None:
                continue
            if b.PhysicalOrVirtualBoundary != "VIRTUAL":
                self.unhandled[f"{b.is_a()}.RelatedBuildingElement:{b.PhysicalOrVirtualBoundary}"] += 1
                continue
            space = b.RelatingSpace
            if space is None:
                self.unhandled[f"{b.is_a()}.RelatedBuildingElement:no_space"] += 1
                continue
            old_guid = old_file.by_id(old_id).GlobalId
            ve = new_file.create_entity("IfcVirtualElement", GlobalId=det_guid(f"virtual/{old_guid}/{old_id}"),
                                        OwnerHistory=b.OwnerHistory)
            b.RelatedBuildingElement = ve
            self.rules["virtual_boundary_element"] += 1
            storey, is_storey = self._storey_of_space(space)
            if not is_storey:
                self.rules["virtual_boundary_container_not_storey"] += 1
            by_storey.setdefault(storey.id(), (storey, []))[1].append(ve)
        for sid, (storey, elements) in by_storey.items():
            new_file.create_entity("IfcRelContainedInSpatialStructure",
                                   GlobalId=det_guid(f"virtual-containment/{storey.GlobalId}/{sid}"),
                                   OwnerHistory=storey.OwnerHistory, RelatedElements=elements, RelatingStructure=storey)
            self.rules["virtual_boundary_containment"] += 1

    def _surface_feature_hosts(self, new_file):
        by_host = collections.OrderedDict()
        for sf in new_file.by_type("IfcSurfaceFeature"):
            if sf.AdheresToElement:
                continue
            host = None
            pl = sf.ObjectPlacement
            rel_to = getattr(pl, "PlacementRelTo", None) if pl is not None else None
            if rel_to is not None:
                cands = [p for p in new_file.get_inverse(rel_to) if p.is_a("IfcElement") and not p.is_a("IfcFeatureElement")
                         and p.ObjectPlacement == rel_to]
                if len(cands) == 1:
                    host = cands[0]
            if host is None:
                self.unhandled["IfcSurfaceFeature.AdheresToElement:no_unique_placement_host"] += 1
                continue
            by_host.setdefault(host.id(), (host, []))[1].append(sf)
        for hid, (host, feats) in by_host.items():
            new_file.create_entity("IfcRelAdheresToElement", GlobalId=det_guid(f"adheres/{host.GlobalId}/{hid}"),
                                   OwnerHistory=feats[0].OwnerHistory, RelatingElement=host, RelatedSurfaceFeatures=feats)
            self.rules["surface_feature_adheres"] += len(feats)


FAMILY_COUNT_CLASSES = ("IfcWall", "IfcWallStandardCase", "IfcSlab", "IfcSpace", "IfcDoor", "IfcWindow", "IfcColumn",
                        "IfcBuildingStorey", "IfcProduct")


def migrate(src, target, dst):
    """Migrate `src` to schema `target` ("IFC4" or "IFC4X3") into `dst`. Returns probe_migrate.migrate_one's report dict
    plus "rules" (changes per rule), "carried_nulls" and "unhandled_nulls"."""
    t = time.perf_counter()
    import ifcopenshell.util.schema as _us
    _us.print = lambda *a, **k: None      # the stock Migrator prints one line per unmapped attribute
    old = ifcopenshell.open(src)
    new = ifcopenshell.file(schema=target)
    mig = Migrator()
    mig.preprocess(old, new)
    n = 0; errs = collections.Counter()
    for e in old:
        try:
            mig.migrate(e, new); n += 1
        except Exception as ex:
            errs[f"{e.is_a()}:{type(ex).__name__}:{str(ex)[:60]}"] += 1
    mig.postprocess(old, new)
    new.write(str(dst))
    rep = {"src": src, "target": target, "dst": str(dst)}
    del old, new
    rules, carried, unhandled, dropped = mig.rules, mig.carried, mig.unhandled, mig.dropped
    del mig; gc.collect()
    chk = ifcopenshell.open(str(dst))
    fam = {c: len(chk.by_type(c)) for c in FAMILY_COUNT_CLASSES}
    rep.update({"seconds": round(time.perf_counter() - t, 1), "migrated": n, "errors": dict(errs.most_common(10)),
                "dropped_attributes": dict(dropped.most_common(12)), "n_errors": sum(errs.values()),
                "schema_out": chk.schema, "counts": fam, "bytes": os.path.getsize(dst),
                "rules": dict(sorted(rules.items())), "carried_nulls": dict(sorted(carried.items())),
                "unhandled_nulls": dict(sorted(unhandled.items()))})
    del chk
    return rep
