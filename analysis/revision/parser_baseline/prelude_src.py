# Helper code that every program the parser writes starts with.
#
# It is executed inside the editing sandbox, where the namespace already holds
# ``ifc`` (the open working model), ``geom`` (the helper library
# modifc_harness.veribim_geom) and ``commit``.  The program the parser writes
# places a verbatim copy of code/modifc_gen/goldlib.py in GOLDLIB_SOURCE before
# this text; the sandbox cannot import that module, so the copy is executed as
# a module of its own.  Every length is in metres.

import types as _types

import numpy as np
import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.element

gl = _types.ModuleType("goldlib_copy")
exec(compile(GOLDLIB_SOURCE, "goldlib_copy", "exec"), gl.__dict__)

CLASS_OF = {"wall": "IfcWall", "slab": "IfcSlab", "space": "IfcSpace",
            "door": "IfcDoor", "window": "IfcWindow", "column": "IfcColumn",
            "storey": "IfcBuildingStorey"}
PLURAL_WORD = {"wall": "walls", "slab": "slabs", "space": "spaces",
               "door": "doors", "window": "windows", "column": "columns"}
TYPE_CLASSES = {"wall": ("IfcWallType",), "slab": ("IfcSlabType",),
                "column": ("IfcColumnType",), "space": ("IfcSpaceType",),
                "door": ("IfcDoorType", "IfcDoorStyle"),
                "window": ("IfcWindowType", "IfcWindowStyle")}
PROPERTY_OF_WORD = {"fire rating": ("FireRating", "IfcLabel"),
                    "external flag": ("IsExternal", "IfcBoolean"),
                    "load-bearing flag": ("LoadBearing", "IfcBoolean"),
                    "thermal transmittance": ("ThermalTransmittance",
                                              "IfcThermalTransmittanceMeasure")}
WORLD_DIR = {"east": (0, 1.0), "west": (0, -1.0), "north": (1, 1.0),
             "south": (1, -1.0), "up": (2, 1.0), "down": (2, -1.0)}


class ParserLookupError(LookupError):
    pass


def _by_type(cls):
    try:
        return list(ifc.by_type(cls))
    except Exception:
        return []


def family_of(product):
    for fam, cls in CLASS_OF.items():
        if product.is_a(cls):
            return fam
    return None


def _one(items, what):
    items = list({e.GlobalId: e for e in items}.values())
    if len(items) != 1:
        raise ParserLookupError("%s: %d candidates %s" % (
            what, len(items), [e.GlobalId for e in items[:5]]))
    return items[0]


def _name_variants(name, fam):
    """The name as written, and the name with a class word turned back.

    The wording layer that writes a class name in place of a plain family
    word can land inside a quoted name ("... IfcColumn elements:532869" for
    "... columns:532869"); turning the class word back gives the name the
    model carries.
    """
    out = [name]
    for f, cls in CLASS_OF.items():
        if f == "storey":
            continue
        for wrong, right in ((cls + " elements", PLURAL_WORD[f]), (cls, f)):
            if wrong in name:
                fixed = name.replace(wrong, right, 1)
                if fixed not in out:
                    out.append(fixed)
    return out


def by_name(fam, name):
    """The element of a family whose name is ``name`` and nobody else's."""
    pool = _by_type(CLASS_OF[fam])
    for variant in _name_variants(name, fam):
        hits = [e for e in pool if (e.Name or "").strip() == variant]
        if len(hits) == 1:
            return hits[0]
        if fam == "space":
            hits = [e for e in pool
                    if (getattr(e, "LongName", None) or "").strip() == variant]
            if len(hits) == 1:
                return hits[0]
    raise ParserLookupError("no unique %s named %r" % (fam, name))


def by_space_label(name):
    """A space named the way a space phrase names it: long name, then name."""
    pool = _by_type("IfcSpace")
    for variant in _name_variants(name, "space"):
        hits = [e for e in pool
                if (getattr(e, "LongName", None) or "").strip() == variant]
        if len(hits) == 1:
            return hits[0]
        hits = [e for e in pool if (e.Name or "").strip() == variant]
        if len(hits) == 1:
            return hits[0]
    raise ParserLookupError("no unique space labelled %r" % (name,))


def storey_of(product):
    found = geom.storey_of(product)
    if found is None:
        for rel in getattr(product, "Decomposes", ()) or ():
            parent = rel.RelatingObject
            if parent is not None and parent.is_a("IfcBuildingStorey"):
                return parent
    if found is None:
        raise ParserLookupError("%s is on no storey" % product.GlobalId)
    return found


def S(ref):
    """The storey a storey phrase names."""
    kind = ref["k"]
    if kind == "storey_name":
        pool = _by_type("IfcBuildingStorey")
        return _one([s for s in pool if (s.Name or "").strip() == ref["name"]],
                    "storey %r" % ref["name"])
    if kind == "storey_elev":
        scale = geom.unit_scale(ifc)
        pool = [s for s in _by_type("IfcBuildingStorey")
                if s.Elevation is not None
                and abs(float(s.Elevation) * scale - ref["e"]) < 0.006]
        return _one(pool, "storey at elevation %s" % ref["e"])
    if kind == "guid":
        return ifc.by_guid(ref["g"])
    if kind == "storey_of":
        return storey_of(R(ref["el"]))
    raise ValueError("not a storey phrase: %r" % (ref,))


def bounded_spaces(element):
    out = []
    for rel in _by_type("IfcRelSpaceBoundary"):
        if rel.RelatedBuildingElement is not None and rel.RelatingSpace is not None \
                and rel.RelatedBuildingElement.GlobalId == element.GlobalId:
            out.append(rel.RelatingSpace)
    return list({e.GlobalId: e for e in out}.values())


def space_elements(space, cls=""):
    return geom.bounding_elements(space, cls)


def connected(element):
    out = []
    for rel in _by_type("IfcRelConnectsElements"):
        a, b = rel.RelatingElement, rel.RelatedElement
        if a is None or b is None:
            continue
        if a.GlobalId == element.GlobalId:
            out.append(b)
        elif b.GlobalId == element.GlobalId:
            out.append(a)
    return list({e.GlobalId: e for e in out}.values())


def host_of(filling):
    return geom.host_wall_of(filling)


def _phrase_label(space):
    """Whether a space carries a label a phrase could name it by."""
    pool = _by_type("IfcSpace")
    long_name = (getattr(space, "LongName", None) or "").strip()
    if long_name and sum(1 for s in pool if (getattr(s, "LongName", None)
                                              or "").strip() == long_name) == 1:
        return True
    name = (space.Name or "").strip()
    return bool(name) and sum(1 for s in pool
                              if (s.Name or "").strip() == name) == 1


def is_external(element):
    for rel in getattr(element, "IsDefinedBy", ()) or ():
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pset = rel.RelatingPropertyDefinition
        for prop in (getattr(pset, "HasProperties", ()) or ()) if pset else ():
            if prop.is_a("IfcPropertySingleValue") and prop.Name == "IsExternal":
                value = getattr(prop.NominalValue, "wrappedValue", None)
                if value is not None:
                    return bool(value)
    return False


def R(ref):
    """The one element a reference phrase names."""
    kind = ref["k"]
    fam = ref.get("fam")
    cls = CLASS_OF.get(fam or "", "")
    if kind == "guid":
        return ifc.by_guid(ref["g"])
    if kind == "name":
        return by_name(fam, ref["name"])
    if kind == "spacelabel":
        return by_space_label(ref["name"])
    if kind == "offset":
        return geom.find_offset(R(ref["ref"]), cls, S(ref["st"]), ref["dir"],
                                ref["d"])
    if kind == "extreme":
        return geom.find_extreme(cls, S(ref["st"]), ref["dir"])
    if kind == "in_storey":
        return _one(geom.on_storey(S(ref["st"]), cls), "only %s" % fam)
    if kind == "hosted":
        return _one(geom.hosted_in(R(ref["host"]), cls), "%s hosted" % fam)
    if kind == "bounding":
        a, b = (R(r) for r in ref["pair"])
        ids_a = {e.GlobalId for e in space_elements(a, cls)}
        hits = [e for e in space_elements(b, cls) if e.GlobalId in ids_a]
        return _one(hits, "%s bounding both" % fam)
    if kind == "space_of":
        els = [R(r) for r in (ref["pair"] if "pair" in ref else [ref["el"]])]
        hits = None
        for el in els:
            here = {s.GlobalId: s for s in bounded_spaces(el)}
            hits = here if hits is None else {g: s for g, s in hits.items()
                                              if g in here}
        return _one(list(hits.values()), "space bounded by")
    if kind == "connects":
        hits = [e for e in connected(R(ref["other"])) if e.is_a(cls)]
        return _one(hits, "%s connected" % fam)
    if kind == "nearest":
        return geom.find_nearest(R(ref["ref"]), cls, S(ref["st"]))
    if kind == "between":
        a, b = (R(r) for r in ref["pair"])
        return geom.find_between(a, b, cls, S(ref["st"]))
    if kind == "above_below":
        return geom.find_above_below(R(ref["ref"]), cls, ref["dir"],
                                     S(ref["st"]))
    if kind == "opposite":
        return geom.find_opposite(R(ref["ref"]), cls, R(ref["space"]))
    if kind == "egocentric":
        return geom.find_beside_door(R(ref["door"]), R(ref["space"]),
                                     ref["side"], cls)
    if kind == "ordinal":
        return geom.find_ordinal(R(ref["host"]), cls, ref["dir"], ref["ord"])
    if kind == "space_without":
        missing = CLASS_OF[ref["missing"]]
        hits = []
        for space in geom.on_storey(S(ref["st"]), "IfcSpace"):
            if not _phrase_label(space):
                continue
            around = space_elements(space)
            if not around:
                continue
            if not any(e.is_a(missing) for e in around):
                hits.append(space)
        return _one(hits, "space with no %s" % ref["missing"])
    if kind == "wall_without_filling":
        hits = [w for w in geom.on_storey(S(ref["st"]), cls)
                if not geom.hosted_in(w, "IfcDoor")
                and not geom.hosted_in(w, "IfcWindow")]
        return _one(hits, "wall hosting nothing")
    if kind == "bounding_wall_without":
        missing = CLASS_OF[ref["missing"]]
        hits = [w for w in space_elements(R(ref["space"]), cls)
                if not geom.hosted_in(w, missing)]
        return _one(hits, "bounding wall hosting no %s" % ref["missing"])
    if kind == "host_of":
        return geom.find_host(R(ref["el"]))
    if kind in ("joins", "joins_out"):
        first = R(ref["pair"][0] if kind == "joins" else ref["a"])
        second = R(ref["pair"][1]) if kind == "joins" else None
        hits = []
        for element in _by_type(cls):
            host = host_of(element)
            if host is None:
                continue
            around = {s.GlobalId for s in bounded_spaces(host)}
            if first.GlobalId not in around:
                continue
            if second is None:
                if len(around) == 1 or is_external(host):
                    hits.append(element)
            elif second.GlobalId in around:
                hits.append(element)
        return _one(hits, "%s joining rooms" % fam)
    if kind == "bounds":
        return _one(space_elements(R(ref["space"]), cls), "%s bounding" % fam)
    if kind == "under":
        return geom.find_under(S(ref["st"]), cls)
    if kind == "without_relation":
        hits = []
        for element in geom.on_storey(S(ref["st"]), cls):
            related = (connected(element) if ref["rel"] == "connection"
                       else bounded_spaces(element))
            if not related:
                hits.append(element)
        return _one(hits, "%s with no %s" % (fam, ref["rel"]))
    raise ValueError("unknown reference kind %r" % kind)


def RS(ref):
    """Every element a set phrase names."""
    if ref.get("k") != "set":
        return [R(ref)]
    fam = ref["fam"]
    cls = CLASS_OF[fam]
    scope = ref["scope"]
    if scope == "ids":
        members = [ifc.by_guid(g) for g in ref["gs"]]
    elif scope == "storey":
        members = geom.on_storey(S(ref["st"]), cls)
    elif scope == "host":
        members = geom.hosted_in(R(ref["host"]), cls)
    else:
        members = space_elements(R(ref["space"]), cls)
    cond = ref.get("cond")
    if cond:
        kept = []
        for m in members:
            value = geom.measure(m, cond["measure"])
            if value is None:
                raise ParserLookupError("cannot measure %s" % m.GlobalId)
            if float(value) > float(cond["threshold"]):
                kept.append(m)
        members = kept
    if not members:
        raise ParserLookupError("the set is empty")
    return list({m.GlobalId: m for m in members}.values())


# ------------------------------------------------------------------ edits


def new_guid():
    return ifcopenshell.guid.new()


def moves_with(child, parent):
    parent_placement = getattr(parent, "ObjectPlacement", None)
    if parent_placement is None:
        return False
    if child.GlobalId == parent.GlobalId:
        return True
    placement = getattr(child, "ObjectPlacement", None)
    depth = 0
    while placement is not None and depth < 16:
        if placement.id() == parent_placement.id():
            return True
        placement = getattr(placement, "PlacementRelTo", None)
        depth += 1
    return False


def world_offset(direction, distance):
    axis, sign = WORLD_DIR[direction]
    offset = [0.0, 0.0, 0.0]
    offset[axis] = round(sign * float(distance), 2)
    return offset


def do_translate(product, offset):
    movers = [product]
    if product.is_a("IfcDoor") or product.is_a("IfcWindow"):
        opening = geom.opening_of(product)
        if opening is not None:
            if moves_with(product, opening):
                movers = [opening]
            elif not moves_with(opening, product):
                movers = [product, opening]
    for mover in movers:
        gl.translate(ifc, mover.GlobalId, *offset)


def do_resize(product, dim, new):
    fam = family_of(product)
    g = product.GlobalId
    if dim == "overall height":
        gl.set_length_attribute(ifc, g, "OverallHeight", new)
    elif dim == "overall width":
        gl.set_length_attribute(ifc, g, "OverallWidth", new)
    elif dim == "height" or (dim == "thickness" and fam == "slab"):
        gl.set_extrusion_depth(ifc, g, new)
    elif dim == "length":
        gl.set_profile_dimension(ifc, g, "XDim", new)
    else:
        gl.set_profile_dimension(ifc, g, "YDim", new)


def do_rotate(product, degrees, pivot):
    if pivot == "origin":
        matrix = geom.frame_of(product)
        px, py = float(matrix[0, 3]), float(matrix[1, 3])
    else:
        lo, hi = geom.world_box(product)
        px, py = float(lo[0] + hi[0]) / 2.0, float(lo[1] + hi[1]) / 2.0
    gl.rotate(ifc, product.GlobalId, float(degrees), round(px, 2), round(py, 2))


def wall_plane(wall):
    """The vertical plane along a wall's own axis: point, normal, across."""
    matrix = geom.frame_of(wall)
    direction = np.array(matrix[:3, 0], dtype=float)
    direction = direction / (float(np.linalg.norm(direction)) or 1.0)
    axis = None
    for candidate in (0, 1):
        if abs(float(direction[candidate])) > 0.999:
            axis = candidate
    if axis is None:
        raise ParserLookupError("the wall does not run along a world axis")
    across = 1 - axis
    lo, hi = geom.world_box(wall)
    point = [0.0, 0.0]
    point[across] = round(float(lo[across] + hi[across]) / 2.0, 2)
    normal = [0.0, 0.0]
    normal[across] = 1.0
    return point, normal


def do_mirror(product, point, normal):
    gl.mirror(ifc, product.GlobalId, point[0], point[1], normal[0], normal[1])


def do_pset(product, pset, word, value):
    prop, value_type = PROPERTY_OF_WORD[word]
    gl.set_property_value(ifc, product.GlobalId, pset, prop, value, value_type,
                          new_guid(), new_guid())


def do_material(product, name):
    gl.assign_material(ifc, product.GlobalId, name, new_guid())


def do_type(product, name):
    fam = family_of(product)
    pool = []
    for cls in TYPE_CLASSES.get(fam, ()):
        pool.extend(_by_type(cls))
    hits = [t for t in pool if (t.Name or "").strip() == name]
    chosen = _one(hits, "type object %r" % name)
    gl.assign_type(ifc, product.GlobalId, chosen.GlobalId, new_guid())


def do_restorey(product, storey, keep_world):
    gl.move_to_storey(ifc, product.GlobalId, storey.GlobalId, new_guid(),
                      bool(keep_world))


def do_delete(product):
    if (product.is_a("IfcDoor") or product.is_a("IfcWindow")) \
            and geom.opening_of(product) is not None:
        gl.delete_filling_with_opening(ifc, product.GlobalId)
    else:
        gl.delete_element(ifc, product.GlobalId)


def add_relations(created, relation):
    if not relation:
        return
    partners = [R(p) for p in relation["partners"]]
    kind = relation["rel"]
    for other in partners:
        if kind == "bounds":
            geom.add_space_boundary(other, created)
        elif kind == "bounded_by":
            geom.add_space_boundary(created, other)
        elif kind == "boundary_class":
            if created.is_a("IfcSpace"):
                geom.add_space_boundary(created, other)
            else:
                geom.add_space_boundary(other, created)
        else:
            geom.connect_elements(created, other)


def filling_along(wall, where, width):
    if where["where"] == "along":
        return float(where["v"])
    if where["where"] == "centre":
        box = geom.wall_box(wall)
        return float(box["start"]) + float(where["v"]) - float(width) / 2.0
    reference = R(where["ref"])
    centre = np.asarray(geom.centre(reference), dtype=float)
    frame = geom.frame_of(wall)
    inverse = np.linalg.inv(frame)
    local = inverse[:3, :3] @ centre + inverse[:3, 3]
    return round(float(local[0]) - float(width) / 2.0, 2)


def fits_gap_box(a, b):
    """The box closing the gap between two walls in line, in world metres."""
    box_a = geom.world_box(a)
    box_b = geom.world_box(b)
    for axis in (0, 1):
        other = 1 - axis
        low = max(float(box_a[0][other]), float(box_b[0][other]))
        high = min(float(box_a[1][other]), float(box_b[1][other]))
        if high - low < 0.05:
            continue
        if float(box_a[1][axis]) <= float(box_b[0][axis]):
            start, end = float(box_a[1][axis]), float(box_b[0][axis])
        elif float(box_b[1][axis]) <= float(box_a[0][axis]):
            start, end = float(box_b[1][axis]), float(box_a[0][axis])
        else:
            continue
        base = max(float(box_a[0][2]), float(box_b[0][2]))
        top = min(float(box_a[1][2]), float(box_b[1][2]))
        lo = [0.0, 0.0, base]
        size = [0.0, 0.0, top - base]
        lo[axis], size[axis] = start, end - start
        lo[other], size[other] = low, high - low
        return lo, size
    raise ParserLookupError("the two walls leave no gap in line")


def against_wall_box(space, wall, size):
    """The box standing inside a room against one of its walls, world metres."""
    room_lo, room_hi = geom.world_box(space)
    lo_w, hi_w = geom.world_box(wall)
    lo_w, hi_w = np.asarray(lo_w, float), np.asarray(hi_w, float)
    centre = (np.asarray(room_lo, float) + np.asarray(room_hi, float)) / 2.0
    wsize = hi_w - lo_w
    across = int(np.argmin(wsize[:2]))
    along = 1 - across
    inward = 1.0 if float(centre[across]) > float(hi_w[across]) - \
        float(wsize[across]) / 2.0 else -1.0
    face = float(hi_w[across]) if inward > 0 else float(lo_w[across])
    lo = [0.0, 0.0, float(room_lo[2])]
    lo[across] = face if inward > 0 else face - float(size[across])
    lo[along] = round(0.5 * (float(lo_w[along]) + float(hi_w[along]))
                      - float(size[along]) / 2.0, 2)
    return lo


def span_box(p1, p2, thickness, direction):
    run = 0 if abs(p2[0] - p1[0]) >= abs(p2[1] - p1[1]) else 1
    across = {"+x": (0, 1.0), "-x": (0, -1.0), "+y": (1, 1.0),
              "-y": (1, -1.0)}[direction]
    lo = [min(p1[0], p2[0]), min(p1[1], p2[1]), p1[2]]
    size = [0.0, 0.0, 0.0]
    size[run] = abs(p2[run] - p1[run])
    size[across[0]] = thickness
    if across[1] < 0:
        lo[across[0]] -= thickness
    return lo, size


def eligible_bounding_walls(space):
    walls = []
    for element in space_elements(space):
        if not element.is_a("IfcWall"):
            continue
        if moves_with(element, space) or moves_with(space, element):
            continue
        if any(moves_with(element, other) or moves_with(other, element)
               for other in walls):
            continue
        shape = getattr(element, "Representation", None)
        if not (shape and (shape.Representations or ())):
            continue
        walls.append(element)
    return walls


def stranded_openings(wall):
    out = []
    for rel in getattr(wall, "HasOpenings", ()) or ():
        opening = rel.RelatedOpeningElement
        if opening is not None and not moves_with(opening, wall):
            out.append(opening)
    return out
