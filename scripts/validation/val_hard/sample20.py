"""Print 20 random candidates for reading by hand: instruction, gold script body,
and what changed between the source model and the rebuilt gold model for the
elements the task names (target, created, removed), plus the anchor the
instruction refers to."""
import gzip, json, os, random, re, sys, tempfile
from pathlib import Path

ROOT = Path(".")
VH = ROOT / "runs_local/stage_b_v10/val_hard"
os.sched_setaffinity(0, set(range(8, 16)))


def describe(f, g):
    import ifcopenshell.util.placement as P
    import ifcopenshell.util.element as E
    try:
        e = f.by_guid(g)
    except Exception:
        return None
    d = {"class": e.is_a(), "name": getattr(e, "Name", None)}
    try:
        m = P.get_local_placement(e.ObjectPlacement)
        d["xyz"] = [round(float(x), 3) for x in m[:3, 3]]
        d["xdir"] = [round(float(x), 3) for x in m[:3, 0]]
    except Exception:
        pass
    try:
        c = E.get_container(e)
        d["storey"] = getattr(c, "Name", None) if c else None
    except Exception:
        pass
    try:
        mat = E.get_material(e)
        d["material"] = getattr(mat, "Name", None) or (mat.is_a() if mat else None)
    except Exception:
        pass
    try:
        t = E.get_type(e)
        d["type"] = getattr(t, "Name", None) if t else None
    except Exception:
        pass
    for attr in ("OverallHeight", "OverallWidth", "PredefinedType"):
        if hasattr(e, attr):
            d[attr] = getattr(e, attr)
    if e.is_a("IfcElement"):
        try:
            fills = [r.RelatingOpeningElement for r in (e.FillsVoids or [])]
            if fills:
                host = [v.RelatingBuildingElement for v in (fills[0].VoidsElements or [])]
                d["host"] = host[0].GlobalId if host else None
            d["n_openings"] = len(e.HasOpenings or [])
        except Exception:
            pass
    return d


def main():
    import ifcopenshell
    from modifc_gen import materialize
    recs = [json.loads(l) for l in open(VH / "candidates_v10.jsonl")]
    rng = random.Random(int(sys.argv[1]) if len(sys.argv) > 1 else 20260930)
    sample = rng.sample(recs, 20)
    out_dir = VH / "work/sample20"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, t in enumerate(sample, 1):
        print("=" * 100)
        print(f"[{i}] {t['task_id']}  {t['ifc_version']} {t['origin']}  {t['operation']}/{t['category']}  "
              f"{t['edit_kind']}  tier={t['tier']}  building={t['building_id']}  src={t['input_ifc']}")
        print("INSTRUCTION:", t["instruction"])
        if t.get("expected_reply") or t.get("clarification"):
            print("CLARIFICATION:", t.get("clarification"), "| EXPECTED REPLY:", t.get("expected_reply"))
        print("ANCHOR:", json.dumps(t.get("anchor"))[:400])
        print("EDIT_PARAMS:", json.dumps({k: v for k, v in (t.get("edit_params") or {}).items()
                                          if k not in ("families", "wording")})[:600])
        body = t["gold_script"].split("def apply_edit(model):", 1)[-1]
        body = body.split("\ndef main", 1)[0].split("\nif __name__", 1)[0]
        print("GOLD SCRIPT apply_edit:" + body[:2500])
        gz = VH / "models" / f"{t['task_id']}.ifc.gz"
        gold = out_dir / f"{t['task_id']}.ifc"
        if gz.exists():
            with gzip.open(gz, "rb") as a, open(gold, "wb") as b:
                b.write(a.read())
        else:
            r = materialize.rebuild(t, ROOT, gold, True)
            print("rebuild:", r.ok, r.check, r.reason)
        src = ifcopenshell.open(str(ROOT / t["input_ifc"]))
        gm = ifcopenshell.open(str(gold))
        eg = t.get("edit_guids") or {}
        print("SCORES:", t["verification"]["self_score"], "null_edit:", t["verification"]["null_edit_score"])
        for role in ("target", "created", "removed"):
            for g in (eg.get(role) or [])[:6]:
                print(f"  {role} {g}\n    source: {describe(src, g)}\n    gold:   {describe(gm, g)}")
        params = (t.get("anchor") or {}).get("params") or {}
        for k, v in params.items():
            if isinstance(v, str) and len(v) == 22:
                print(f"  anchor param {k}={v}: source {describe(src, v)}")
        print(f"  products source {len(src.by_type('IfcProduct'))} gold {len(gm.by_type('IfcProduct'))}")
        del src, gm
        os.remove(gold)


if __name__ == "__main__":
    main()
