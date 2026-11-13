"""Summaries for REPORT.txt from migrate_v2.jsonl, validate_v2.jsonl, equivalence_v2.jsonl and the source validations
(runs_local/corpus_v10/validate_schema.jsonl when complete, else migrator_v2's own). Writes requirement_v2.jsonl (one
line per output: issue keys added by the migration, carried source issues) and prints the tables."""
import json, collections, os, glob, re
ROOT = "."; C10 = f"{ROOT}/runs_local/corpus_v10"; HERE = f"{C10}/migrator_v2"
UT = os.path.join(os.path.dirname(__import__("ifcopenshell").__file__), "util")
import ifcopenshell.ifcopenshell_wrapper as W

C2X3_4 = json.load(open(f"{UT}/class_2x3_to_4.json")); C2X3_4["IfcRelOccupiesSpaces"] = "IfcRelAssignsToActor"
C4_4X3 = {"IfcWindowStyle": "IfcWindowType", "IfcDoorStyle": "IfcDoorType", "IfcWallStandardCase": "IfcWall"}
ATTR_REN = {("IfcCurveStyleFontAndScaling", "CurveFont"): "CurveStyleFont", ("IfcStructuralCurveConnection", "Axis"): "AxisDirection"}
SC = {s: W.schema_by_name(s) for s in ("IFC4", "IFC4X3_ADD2")}


def exists(schema, cls):
    try:
        SC[schema].declaration_by_name(cls); return True
    except Exception:
        return False


def map_key(key, src_schema, target):
    m = re.match(r"^([^.]*)\.([^:]*):(.*)$", key, re.S)
    if not m:
        return key
    cls, att, msg = m.groups()
    if cls.startswith("Ifc"):
        if src_schema == "IFC2X3" and not exists("IFC4", cls):
            cls = C2X3_4.get(cls, cls)
        if target == "IFC4X3":
            cls = C4_4X3.get(cls, cls)
            if (cls, att) in ATTR_REN and target == "IFC4X3":
                att = ATTR_REN[(cls, att)]
    return f"{cls}.{att}:{msg}"


def load_jsonl(p):
    return [json.loads(l) for l in open(p)] if os.path.exists(p) else []


src_val = {}
for r in load_jsonl(f"{C10}/validate_schema.jsonl"):
    if "n_issues" in r and sum(r["kinds"].values()) == r["n_issues"]:
        src_val[r["relpath"]] = r
for r in load_jsonl(f"{HERE}/validate_v2.jsonl"):
    if r["role"] == "source" and r["relpath"] not in src_val:
        src_val[r["relpath"]] = r
jobs = {j["key"]: j for j in json.load(open(f"{HERE}/jobs.json"))}
outs = [r for r in load_jsonl(f"{HERE}/validate_v2.jsonl") if r["role"] == "output"]
migs = {r["new"]: r for r in load_jsonl(f"{HERE}/migrate_v2.jsonl")}
eqs = {r["new"]: r for r in load_jsonl(f"{HERE}/equivalence_v2.jsonl")}
old_val = {r["relpath"]: r for r in load_jsonl(f"{C10}/validate_schema.jsonl") if "n_issues" in r}

req = []
for o in outs:
    j = jobs[o["key"]]; s = src_val.get(o["source"])
    rec = {"relpath": o["relpath"], "key": o["key"], "target": o["target"], "source": o["source"],
           "source_schema": j["schema"], "n_issues": o.get("n_issues"), "source_n_issues": None if s is None else s["n_issues"]}
    if o.get("error") or s is None:
        rec["status"] = "unknown"; rec["reason"] = o.get("error") or "source not validated"
        req.append(rec); continue
    mapped = collections.Counter()
    for k, v in s["kinds"].items():
        mapped[map_key(k, j["schema"], o["target"])] += v
    added = {k: v - mapped.get(k, 0) for k, v in o["kinds"].items() if v > mapped.get(k, 0)}
    carried = {k: v for k, v in o["kinds"].items() if k not in added}
    rec["added"] = added; rec["carried"] = carried
    rec["removed_vs_source"] = {k: v - o["kinds"].get(k, 0) for k, v in mapped.items() if v > o["kinds"].get(k, 0)}
    ov = old_val.get(o["old_relpath"])
    rec["old_file_n_issues"] = None if ov is None else ov["n_issues"]
    rec["status"] = "failing" if added else ("carried_only" if o["n_issues"] else "clean")
    if added:
        rec["samples"] = {k: o["samples"].get(k, "")[:500] for k in added}
    req.append(rec)
with open(f"{HERE}/requirement_v2.jsonl", "w") as fh:
    for r in req:
        fh.write(json.dumps(r) + "\n")

print("== per version: files clean / carrying only source issues / still failing")
for t in ("IFC4", "IFC4X3"):
    c = collections.Counter(r["status"] for r in req if r["target"] == t)
    print(f"{t}: {sum(c.values())} files: clean {c['clean']}, carrying only source issues {c['carried_only']}, "
          f"failing {c['failing']}, unknown {c['unknown']}")
print("\n== files carrying source issues (issue key: count in output / count in source)")
for r in sorted(req, key=lambda r: r["relpath"]):
    if r["status"] == "carried_only":
        s = src_val[r["source"]]; j = jobs[r["key"]]
        mp = collections.Counter()
        for k, v in s["kinds"].items():
            mp[map_key(k, j["schema"], r["target"])] += v
        print(f"  {os.path.basename(r['relpath'])}: " + "; ".join(f"{k} {v}/{mp[k]}" for k, v in r["carried"].items()))
print("\n== still failing")
for r in req:
    if r["status"] in ("failing", "unknown"):
        print(" ", os.path.basename(r["relpath"]), r["status"], r.get("added") or r.get("reason"))
        for k, v in (r.get("samples") or {}).items():
            print("     sample:", v.replace("\n", " | ")[:400])

print("\n== rules: changes / files (over all migration steps)")
rc = collections.Counter(); rf = collections.Counter(); per_t = collections.defaultdict(collections.Counter)
for m in migs.values():
    for k, v in m["rules"].items():
        rc[k] += v; rf[k] += 1; per_t[k][m["target"]] += v
for k in sorted(rc):
    print(f"  {k}: {rc[k]} changes in {rf[k]} files  ({dict(per_t[k])})")
cn = collections.Counter(); cf = collections.Counter(); un = collections.Counter(); uf = collections.Counter()
for m in migs.values():
    for k, v in m["carried_nulls"].items():
        cn[k] += v; cf[k] += 1
    for k, v in m["unhandled_nulls"].items():
        un[k] += v; uf[k] += 1
print("  carried source nulls (left as in source):", {k: f"{cn[k]} in {cf[k]} files" for k in cn})
print("  unhandled mandatory nulls:", {k: f"{un[k]} in {uf[k]} files" for k in un})
er = collections.Counter(); ef = collections.Counter(); dr = collections.Counter(); df = collections.Counter()
for m in migs.values():
    for k, v in m["errors"].items():
        er[(m["target"], k.split(":")[0])] += v; ef[(m["target"], k.split(":")[0])] += 1
    for k, v in m["dropped_attributes"].items():
        dr[(m["target"], k)] += v; df[(m["target"], k)] += 1
print("  entities not migrated (class absent from target, as in v1):", {f"{t}:{c}": f"{er[(t, c)]} in {ef[(t, c)]} files" for t, c in er})
print("  attribute values dropped (optional, no target equivalent, as in v1):", {f"{t}:{c}": f"{dr[(t, c)]} in {df[(t, c)]} files" for t, c in dr})

print("\n== equivalence with the old migrated files")
ok = sum(1 for e in eqs.values() if e["ok"]); print(f"  {ok}/{len(eqs)} outputs pass")
tot = collections.Counter(); files_restored = []
for e in eqs.values():
    tot["products_old"] += e["n_products_old"]; tot["products_new"] += e["n_products_new"]
    tot["missing"] += e["missing_products"]
    for k, v in e["added_products"].items():
        tot[f"added_{k}"] += v
    for k, v in e["field_differences"].items():
        tot[f"field_{k}"] += v
    for k, v in e["representation"].items():
        tot[f"rep_{k}"] += v
    for k, v in e["model_signature_entities"].items():
        tot[f"ms_{k}"] += v
    tot["roots_added"] += e["roots_added"]; tot["roots_missing"] += e["roots_missing"]
    if e["representation"].get("differs_only_in_restored_source_values"):
        files_restored.append((os.path.basename(e["new"]), e["representation"]["differs_only_in_restored_source_values"]))
for k, v in sorted(tot.items()):
    print(f"  {k}: {v}")
print("  files with representations restored to source values:", files_restored)
for e in eqs.values():
    if not e["ok"]:
        print("  FAIL", os.path.basename(e["new"]), json.dumps({k: e[k] for k in ("missing_products", "added_products",
              "field_differences", "field_examples", "representation", "representation_examples", "model_signature_entities",
              "model_signature_differ_examples", "roots_missing")})[:1500])

print("\n== resources")
peaks = []; secs = collections.Counter()
for p in glob.glob(f"{HERE}/work/*/*.json"):
    if os.path.basename(p).startswith(("migrate_", "validate_")):
        r = json.load(open(p)); peaks.append((r.get("peak_rss_gb", 0), p))
        secs[os.path.basename(p).split("_")[0]] += r.get("wall_seconds", r.get("seconds", 0)) or 0
import pickle
for p in glob.glob(f"{HERE}/work/*/sig*.pkl"):
    r = pickle.load(open(p, "rb")); peaks.append((r["peak_rss_gb"], p)); secs["signature"] += r["seconds"]
peaks.sort(reverse=True)
print("  largest single-step peak RSS:", [(round(a, 2), b.replace(HERE + '/work/', '')) for a, b in peaks[:3]])
print("  step CPU-side seconds by kind:", dict(secs))
for p in sorted(glob.glob(f"{HERE}/run_stats_*.json")):
    print("  run:", open(p).read().strip())
