"""Write the program that performs one parsed instruction.

The program is the helper prelude (prelude_src.py, with a verbatim copy of the
generator's edit runtime goldlib.py in front of it) followed by a few lines
that resolve the references the instruction names and call one edit function.
It ends with ``commit()``.  An instruction that leaves out a value the edit
needs gets no program at all, only a question.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent
GOLDLIB_SOURCE = (HERE.parents[2] / "code" / "modifc_gen" / "goldlib.py").read_text(encoding="utf-8")
PRELUDE = (HERE / "prelude_src.py").read_text(encoding="utf-8")

CLASS_OF = {"wall": "IfcWall", "slab": "IfcSlab", "space": "IfcSpace",
            "door": "IfcDoor", "window": "IfcWindow", "column": "IfcColumn"}


def question(intent: dict) -> str:
    """The question an under-specified instruction is answered with."""
    slot = intent["clarify"]
    fam = intent.get("fam") or "element"
    if slot == "element":
        return f"Which {fam} do you mean?"
    if slot == "storey":
        return f"Which storey should the new {fam} go on?"
    op = intent["op"]
    dim = (intent.get("parse") or {}).get("dim")
    if op == "clarify_resize" and dim:
        return f"What should the new {dim} be?"
    if op == "clarify_move":
        return "What distance should it be moved?"
    if op == "clarify_rotate":
        return "By how many degrees should it be rotated?"
    if op == "clarify_rename":
        return "What should the new name be?"
    return "What value should I use?"


def body(intent: dict) -> str:
    """The task-specific lines, after the prelude."""
    op = intent["op"]
    v = intent["parse"]
    t = v.get("t")
    L = []
    a = L.append
    if op in ("translate", "copy_element", "array_elements",
              "move_wall_with_fillings", "move_space_with_bounding_walls"):
        a(f"offset = world_offset({v['mv']['dir']!r}, {v['mv']['dist']!r})")
    if op == "translate":
        a(f"T = R({t!r})")
        a("do_translate(T, offset)")
    elif op == "resize":
        a(f"T = R({t!r})")
        a(f"do_resize(T, {v['dim']!r}, {v['new']!r})")
    elif op == "resize_batch":
        a(f"for T in RS({t!r}):")
        a(f"    do_resize(T, {v['dim']!r}, {v['new']!r})")
    elif op == "rename":
        a(f"T = R({t!r})")
        a(f"gl.set_attribute(ifc, T.GlobalId, 'Name', {v['new']!r})")
    elif op == "retype":
        a(f"for T in RS({t!r}):")
        a(f"    gl.set_attribute(ifc, T.GlobalId, 'PredefinedType', {v['new']!r})")
    elif op == "rotate":
        a(f"T = R({t!r})")
        a(f"do_rotate(T, {v['deg']!r}, {v['pivot']!r})")
    elif op == "mirror_wall":
        a(f"T = R({t!r})")
        a(f"point, normal = wall_plane(by_name('wall', {v['wall']!r}))")
        a("do_mirror(T, point, normal)")
    elif op == "mirror_plane":
        across = 0 if v["axis"] == "x" else 1
        point = [0.0, 0.0]
        point[across] = v["v"]
        normal = [0.0, 0.0]
        normal[across] = 1.0
        a(f"T = R({t!r})")
        a(f"do_mirror(T, {point!r}, {normal!r})")
    elif op == "set_pset":
        a(f"for T in RS({t!r}):")
        a(f"    do_pset(T, {v['pset']!r}, {v['prop']!r}, {v['val']['v']!r})")
    elif op == "assign_material":
        a(f"for T in RS({t!r}):")
        a(f"    do_material(T, {v['mat']!r})")
    elif op == "assign_type":
        a(f"T = R({t!r})")
        a(f"do_type(T, {v['type']!r})")
    elif op in ("move_to_storey", "move_to_storey_keep"):
        a(f"T = R({t!r})")
        a(f"do_restorey(T, S({v['st']!r}), {op == 'move_to_storey'!r})")
    elif op == "rehost_filling":
        a(f"T = R({t!r})")
        a(f"geom.move_filling(T, R({v['wall']!r}), {v['along']!r})")
    elif op == "delete":
        a(f"for T in RS({t!r}):")
        a("    do_delete(T)")
    elif op == "copy_element":
        a(f"T = R({t!r})")
        a(f"geom.copy_element(T, offset[0], offset[1], 0.0, {v['name']!r})")
    elif op == "array_elements":
        a(f"T = R({t!r})")
        a(f"geom.array_elements(T, {int(v['n'])!r}, offset[0], offset[1], 0.0, "
          f"{v['names']!r})")
    elif op == "replace_filling":
        a(f"T = R({t!r})")
        a(f"geom.replace_filling(T, {CLASS_OF[v['fam']]!r}, {v['name']!r}, "
          f"{v['w']!r}, {v['h']!r}, {v['sill']!r})")
    elif op == "create_filling":
        a(f"wall = R({t!r})")
        a(f"along = filling_along(wall, {v['fw']!r}, {v['w']!r})")
        a(f"new = geom.add_filling(wall, {CLASS_OF[v['fam']]!r}, {v['name']!r}, "
          f"{v['w']!r}, {v['h']!r}, along, {v['sill']!r})")
        a(f"add_relations(new, {v.get('relation')!r})")
    elif op == "create_box":
        L.extend(_create_box(v))
    elif op == "create_wall_with_door":
        x, y, _z = v["p"]
        a(f"storey = S({v['where']!r})")
        a(f"wall = geom.add_box_element(storey, 'IfcWall', {v['name']!r}, "
          f"{x!r}, {y!r}, 0.0, {v['l']!r}, {v['w']!r}, {v['h']!r})")
        a(f"geom.add_filling(wall, 'IfcDoor', {v['dname']!r}, {v['dw']!r}, "
          f"{v['dh']!r}, {v['along']!r}, 0.0)")
    elif op == "delete_wall_with_fillings":
        a(f"wall = R({t!r})")
        a("fillings = geom.hosted_in(wall, 'IfcDoor') + "
          "geom.hosted_in(wall, 'IfcWindow')")
        a(f"if len(fillings) != {int(v['count'])}:")
        a(f"    print('stated {int(v['count'])} hosted, found', len(fillings))")
        a("for f in fillings:")
        a("    do_delete(f)")
        a("gl.delete_element(ifc, wall.GlobalId)")
    elif op == "move_wall_with_fillings":
        a(f"wall = R({t!r})")
        a("hosted = [h for h in geom.hosted_in(wall) if not moves_with(h, wall)]")
        a("openings = stranded_openings(wall)")
        a("gl.translate(ifc, wall.GlobalId, *offset)")
        a("for h in hosted:")
        a("    gl.translate(ifc, h.GlobalId, *offset)")
        a("for o in openings:")
        a("    gl.translate(ifc, o.GlobalId, *offset)")
    elif op == "move_space_with_bounding_walls":
        a(f"space = R({t!r})")
        a("walls = eligible_bounding_walls(space)")
        a(f"if len(walls) != {int(v['n'])}:")
        a(f"    print('stated {int(v['n'])} walls, found', len(walls))")
        a("gl.translate(ifc, space.GlobalId, *offset)")
        a("for w in walls:")
        a("    gl.translate(ifc, w.GlobalId, *offset)")
    else:
        raise ValueError(f"no program for {op}")
    a("commit()")
    return "\n".join(L) + "\n"


def _create_box(v: dict) -> list[str]:
    fam = v["fam"]
    cls = CLASS_OF[fam]
    pt = v.get("pt")
    L = [f"storey = S({v['where']!r})"]
    a = L.append
    if "der" in v:
        d = v["der"]
        kind = d["pos"]
        if kind == "fits_gap":
            a(f"lo, size = fits_gap_box(R({d['a']!r}), R({d['b']!r}))")
        elif kind == "on_top_of":
            a(f"lo, top = geom.spot_on_top_of(R({d['a']!r}))")
            a(f"lo = [float(lo[0]), float(lo[1]), float(lo[2])]")
            a(f"size = [float(top[0]), float(top[1]), {d['h']!r}]")
        elif kind == "adjacent_to_space":
            a(f"size = [{d['l']!r}, {d['w']!r}, {d['h']!r}]")
            a(f"lo = against_wall_box(R({d['space']!r}), R({d['a']!r}), size)")
        else:
            raise ValueError("the instruction gives no position: " + kind)
        a(f"new = geom.add_box_element(storey, {cls!r}, {v['name']!r}, lo[0], "
          f"lo[1], lo[2], size[0], size[1], size[2], predefined_type={pt!r}, "
          f"frame='world')")
    elif "p1" in v:
        a(f"lo, size = span_box({v['p1']!r}, {v['p2']!r}, {v['t']!r}, "
          f"{v['tdir']!r})")
        a(f"size[2] = {v['h']!r}")
        a(f"new = geom.add_box_element(storey, {cls!r}, {v['name']!r}, lo[0], "
          f"lo[1], lo[2], size[0], size[1], size[2], predefined_type={pt!r}, "
          f"frame='world')")
    else:
        size = v["size"]
        bp = v["bp"]
        dims = (size["l"], size["w"], size["h"])
        if bp["pos"] == "offset":
            sx = 1.0 if bp["xw"] == "east" else -1.0
            sy = 1.0 if bp["yw"] == "north" else -1.0
            a(f"o = geom.origin_in_frame(R({bp['ref']!r}), storey)")
            a(f"x = float(o[0]) + {sx * bp['dx']!r}")
            a(f"y = float(o[1]) + {sy * bp['dy']!r}")
            a(f"new = geom.add_box_element(storey, {cls!r}, {v['name']!r}, x, y, "
              f"0.0, {dims[0]!r}, {dims[1]!r}, {dims[2]!r}, "
              f"predefined_type={pt!r}, frame='storey')")
        else:
            x, y, z = bp["p"]
            frame = "storey" if bp["pos"] == "storey" else "world"
            a(f"new = geom.add_box_element(storey, {cls!r}, {v['name']!r}, {x!r}, "
              f"{y!r}, {z!r}, {dims[0]!r}, {dims[1]!r}, {dims[2]!r}, "
              f"predefined_type={pt!r}, frame={frame!r})")
    a(f"add_relations(new, {v.get('relation')!r})")
    return L


def program(intent: dict) -> str:
    """The whole program for one recognised, fully specified instruction."""
    return ("GOLDLIB_SOURCE = " + repr(GOLDLIB_SOURCE) + "\n" + PRELUDE
            + "\n# ---- the edit this instruction asks for\n" + body(intent))
