"""One step of the migrator-v2 pipeline per process (so memory returns to the OS between steps).

  steps.py migrate   SRC TARGET DST OUT.json   migrate_v2.migrate(SRC, TARGET, DST); report to OUT.json
  steps.py validate  PATH OUT.json             ifcopenshell.validate (express_rules=False), every issue key counted
  steps.py signature PATH OUT.pkl              product table, representation digests and model_signature of PATH
Every step writes its own seconds and peak RSS."""
import os, sys, json, time, resource, pickle, hashlib, gc
os.environ["OMP_NUM_THREADS"] = "1"
HERE = "runs_local/corpus_v10/migrator_v2"
sys.path[:0] = ["scripts/corpus/migrator_v2", "code", "code/harness"]
import numpy as np
import ifcopenshell, ifcopenshell.util.placement

FAMILY_CLASSES = ("IfcWall", "IfcSlab", "IfcSpace", "IfcDoor", "IfcWindow", "IfcColumn")
# Attributes whose values v2 restores from the source (rename / nested_aggregate / wrap_select rules). A representation
# digest with these masked tells a restored source value apart from any other difference.
MASKED = {("IfcCurveStyleFontAndScaling", "CurveStyleFont"), ("IfcFillAreaStyle", "ModelOrDraughting"),
          ("IfcMaterialRelationship", "MaterialExpression"), ("IfcStructuralCurveConnection", "AxisDirection"),
          ("IfcImageTexture", "URLReference"), ("IfcBSplineSurface", "ControlPointsList"),
          ("IfcDirectrixCurveSweptAreaSolid", "StartParam"), ("IfcDirectrixCurveSweptAreaSolid", "EndParam")}


def peak_gb():
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6, 3)


def write_json(path, obj):
    tmp = path + ".tmp"; json.dump(obj, open(tmp, "w"), indent=1); os.replace(tmp, path)


def cmd_migrate(src, target, dst, out):
    from migrate_v2 import migrate
    t = time.time(); rep = migrate(src, target, dst)
    rep["wall_seconds"] = round(time.time() - t, 1); rep["peak_rss_gb"] = peak_gb()
    write_json(out, rep)


def cmd_validate(path, out):
    from vkeys import validate_keys
    t = time.time(); rec = {"path": path, "bytes": os.path.getsize(path)}
    try:
        f = ifcopenshell.open(path); rec["schema"] = f.schema_identifier
        kinds, samples = validate_keys(f, samples=1)
        rec["n_issues"] = sum(kinds.values()); rec["kinds"] = dict(kinds.most_common())
        rec["samples"] = {k: v[0][:700] for k, v in samples.items()}
        del f
    except Exception as ex:
        rec["error"] = repr(ex)[:300]
    rec["seconds"] = round(time.time() - t, 1); rec["peak_rss_gb"] = peak_gb()
    write_json(out, rec)


class RepDigest:
    """Digest of an entity graph reached through direct attributes, raw and with MASKED attributes blanked."""

    def __init__(self, f):
        self.f = f; self.raw = {}; self.msk = {}; self.mask_idx = {}

    def _mask_for(self, e):
        cls = e.is_a()
        m = self.mask_idx.get(cls)
        if m is None:
            decl = ifcopenshell.ifcopenshell_wrapper.schema_by_name(self.f.schema_identifier).declaration_by_name(cls)
            names = [a.name() for a in decl.all_attributes()]
            m = set()
            for base, att in MASKED:
                if e.is_a(base) and att in names:
                    m.add(names.index(att))
            self.mask_idx[cls] = m
        return m

    def _enc(self, v, table):
        if v is None:
            return "N"
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:
                return f"{v.is_a()}({self._enc(v.wrappedValue, table)})"
            return table[v.id()]
        if isinstance(v, (list, tuple)):
            return "[" + ",".join(self._enc(x, table) for x in v) + "]"
        if isinstance(v, float):
            return repr(round(v, 9))
        return repr(v)

    def _children(self, v, out):
        if isinstance(v, ifcopenshell.entity_instance):
            if v.id() == 0:
                self._children(v.wrappedValue, out)
            else:
                out.append(v)
        elif isinstance(v, (list, tuple)):
            for x in v:
                self._children(x, out)

    def digest(self, root):
        stack = [(root, False)]
        while stack:
            e, expanded = stack.pop()
            i = e.id()
            if i in self.raw:
                continue
            vals = [e[k] for k in range(len(e))]
            if not expanded:
                kids = []
                for v in vals:
                    self._children(v, kids)
                pending = [k for k in kids if k.id() not in self.raw]
                if pending:
                    stack.append((e, True))
                    stack.extend((k, False) for k in pending)
                    continue
            mask = self._mask_for(e)
            r = e.is_a() + "(" + ";".join(self._enc(v, self.raw) for v in vals) + ")"
            m = e.is_a() + "(" + ";".join("*" if k in mask else self._enc(v, self.msk) for k, v in enumerate(vals)) + ")"
            self.raw[i] = hashlib.blake2b(r.encode(), digest_size=12).hexdigest()
            self.msk[i] = hashlib.blake2b(m.encode(), digest_size=12).hexdigest()
        return self.raw[root.id()], self.msk[root.id()]


def cmd_signature(path, out):
    from modifc_gen.scene import _storey_ancestor
    from modifc_gen.verify import model_signature
    t = time.time()
    f = ifcopenshell.open(path)
    products = {}; fam_guids = []; rep = {}
    rd = RepDigest(f)
    for p in f.by_type("IfcProduct"):
        g = p.GlobalId; k = g; n = 1
        while k in products:
            n += 1; k = f"{g}#{n}"
        m = None
        if p.ObjectPlacement is not None:
            try:
                m = tuple(np.round(np.array(ifcopenshell.util.placement.get_local_placement(p.ObjectPlacement),
                                            dtype=float), 9).ravel().tolist())
            except Exception:
                m = "error"
        cont = getattr(p, "ContainedInStructure", None) or ()
        container = cont[0].RelatingStructure if cont else None
        dec = getattr(p, "Decomposes", None) or ()
        parent = dec[0].RelatingObject if dec else None
        storey = _storey_ancestor(container) if container is not None else (_storey_ancestor(parent) if parent is not None else None)
        host = None
        for fv in getattr(p, "FillsVoids", None) or ():
            op = fv.RelatingOpeningElement
            for ve in (getattr(op, "VoidsElements", None) or ()):
                host = ve.RelatingBuildingElement.GlobalId
        voidhost = None
        for ve in getattr(p, "VoidsElements", None) or ():
            voidhost = ve.RelatingBuildingElement.GlobalId
        products[k] = (p.is_a(), p.Name, m, container.GlobalId if container is not None else None,
                       storey.GlobalId if storey is not None else None, parent.GlobalId if parent is not None else None,
                       host, voidhost)
        if any(p.is_a(c) for c in FAMILY_CLASSES):
            fam_guids.append(g)
            r = p.Representation
            rep[k] = rd.digest(r) if r is not None else (None, None)
    del rd, f; gc.collect()
    t1 = time.time()
    ms = model_signature(path, fam_guids)
    sig = {"path": path, "products": products, "rep": rep, "ms_entities": ms["entities"], "ms_counts": ms["counts"],
           "ms_guids": ms["guids"], "seconds_products": round(t1 - t, 1), "seconds": round(time.time() - t, 1),
           "peak_rss_gb": peak_gb()}
    tmp = out + ".tmp"; pickle.dump(sig, open(tmp, "wb")); os.replace(tmp, out)


if __name__ == "__main__":
    cmd = sys.argv[1]
    {"migrate": cmd_migrate, "validate": cmd_validate, "signature": cmd_signature}[cmd](*sys.argv[2:])
