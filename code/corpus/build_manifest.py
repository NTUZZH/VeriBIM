"""Assemble data/corpus_manifest.json + data/corpus_descriptors.json.

Applies: deduplication, the ModIFC exclusion policy, and
contamination check #1 (GlobalId overlap against the 151 BIM-Edit scene files).
"""
import gzip
import json
import os
import re
import sys
import urllib.parse
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
S = os.path.join(ROOT, "data", "corpus_build") + os.sep
GUIDDIR = os.path.join(ROOT, "data/corpus_guids")

COLLECTIONS = {
    "auckland": dict(
        name="Open IFC Model Repository, University of Auckland",
        home="https://openifcmodel.cs.auckland.ac.nz/",
        license_basis=("Open academic repository, publicly downloadable without registration; "
                       "NO explicit licence or terms-of-use text published on the site or in the "
                       "repository papers. re3data record r3d100012443 lists open access / CC BY 3.0 "
                       "(registry metadata, unverified against the primary site). Used here for local "
                       "research only; source files never redistributed."),
        license_review_required=True),
    "schependomlaan": dict(
        name="Schependomlaan dataset (openBIMstandards archive)",
        home="https://github.com/openBIMstandards/Archive-DataSetSchependomlaan",
        license_basis=("CC BY 4.0 per LICENSE.MD ('(C) original owners'); README-old states all data "
                       "owners gave permission for scientific and academic use."),
        license_review_required=False),
    "buildingsmart_official": dict(
        name="buildingSMART Certification-datasets (formerly Sample-Test-Files)",
        home="https://github.com/buildingSMART/Certification-datasets",
        license_basis="CC BY 4.0, buildingSMART International Ltd., per repository LICENSE file.",
        license_review_required=False),
    "buildingsmart_community": dict(
        name="buildingsmart-community Community-Sample-Test-Files",
        home="https://github.com/buildingsmart-community/Community-Sample-Test-Files",
        license_basis=("CC BY 4.0 per repository LICENSE and contribution policy; README notes the "
                       "files are community contributions, not official buildingSMART examples."),
        license_review_required=False),
}

REPO_URL = {
    "schependomlaan": ("openBIMstandards/Archive-DataSetSchependomlaan",
                       "data/corpus/schependomlaan_repo"),
    "buildingsmart_official": ("buildingSMART/Certification-datasets",
                               "data/corpus/bs_official_repo"),
    "buildingsmart_community": ("buildingsmart-community/Community-Sample-Test-Files",
                                "data/corpus/bs_community_repo"),
}
COMMITS = json.load(open(S + "commits.json"))

AUTHORITY = ["buildingsmart_official", "buildingsmart_community", "schependomlaan", "auckland"]

WEEKLY_RE = re.compile(r"/As Planned models/", re.I)

# Pre-registered structural-similarity disposition. The threshold was fixed from the
# distribution of the structural-similarity scores BEFORE any exclusion was
# applied. The scores
# below are pinned to that analysis and are deliberately NOT recomputed here: a
# pre-registration that moves with the corpus it prunes is not a pre-registration.
STRUCTURAL_THRESHOLD = 0.80
STRUCTURAL_EXCLUSIONS = {
    "data/corpus/auckland/230_20211122Wellness center Sama.ifc": 0.862,
}


def load_jsonl(p):
    return [json.loads(l) for l in open(p) if l.strip()]


def guids_of(sha):
    p = os.path.join(GUIDDIR, sha + ".txt.gz")
    if not os.path.exists(p):
        return set()
    with gzip.open(p, "rt") as fh:
        t = fh.read()
    return set(t.split("\n")) - {""}


def gh_url(coll, relpath):
    owner_repo, local_root = REPO_URL[coll]
    inner = os.path.relpath(relpath, local_root)
    return "https://github.com/%s/blob/%s/%s" % (
        owner_repo, COMMITS[coll], urllib.parse.quote(inner))


def main():
    scans = []
    for f in sys.argv[1:]:
        scans += load_jsonl(f)
    descs = []
    for f in sys.argv[1:]:
        dp = f + ".desc.jsonl"
        if os.path.exists(dp):
            descs += load_jsonl(dp)

    auck = {r["local"]: r for r in json.load(open(S + "auck_downloaded.json")) if r.get("local")}

    bimedit = [r for r in scans if r["source_collection"] == "bimedit_reference"]
    corpus = [r for r in scans if r["source_collection"] != "bimedit_reference"]

    # ---- BIM-Edit reference sets -------------------------------------------
    be_guids = set()
    be_by_guid = defaultdict(list)
    be_sha = {}
    for r in bimedit:
        if not r["parse_ok"]:
            continue
        g = guids_of(r["sha256"])
        be_guids |= g
        for x in g:
            be_by_guid[x].append(r["relpath"])
        be_sha.setdefault(r["sha256"], r["relpath"])

    # ---- Schependomlaan GUID union (E3 building fingerprint) ---------------
    sch_guids = set()
    for r in corpus:
        if r["source_collection"] == "schependomlaan" and r["parse_ok"]:
            sch_guids |= guids_of(r["sha256"])

    # ---- build records ------------------------------------------------------
    recs = []
    for r in corpus:
        coll = r["source_collection"]
        rec = dict(
            relpath=r["relpath"],
            source_collection=coll,
            sha256=r["sha256"],
            bytes=r["bytes"],
            ifc_schema=r.get("ifc_schema") or r.get("ifc_schema_header"),
            ifc_schema_header=r.get("ifc_schema_header"),
            parse_ok=r["parse_ok"],
            parse_error=r.get("error"),
            n_products=r.get("n_products"),
            n_guids=r.get("n_guids"),
            guid_set_sha256=r.get("guid_set_sha256"),
            storey_count=r.get("storey_count"),
            license_basis=COLLECTIONS[coll]["license_basis"],
            license_review_required=COLLECTIONS[coll]["license_review_required"],
            e3_reserved=False,
            e3_building=False,
            duplicate_of=None,
            training_eligible=False,
            exclusion_reason=None,
        )
        if coll == "auckland":
            a = auck.get(os.path.basename(r["relpath"]))
            rec["source_url"] = a["url"] if a else None
            rec["source_page"] = COLLECTIONS[coll]["home"]
            rec["source_record"] = ({k: a.get(k) for k in
                                     ("id", "name", "org", "createdby", "desc")} if a else None)
        else:
            rec["source_url"] = gh_url(coll, r["relpath"])
            rec["source_page"] = COLLECTIONS[coll]["home"]
            rec["source_record"] = dict(commit=COMMITS[coll])
        if coll == "schependomlaan":
            rec["e3_building"] = True
            rec["e3_reserved"] = bool(WEEKLY_RE.search("/" + r["relpath"]))
        recs.append(rec)

    by_rel = {r["relpath"]: r for r in recs}

    # ---- deduplication ------------------------------------------------------
    def rank(rec):
        return (AUTHORITY.index(rec["source_collection"]), rec["relpath"])

    def mark_dups(keyfn, label):
        groups = defaultdict(list)
        for rec in recs:
            k = keyfn(rec)
            if k:
                groups[k].append(rec)
        n = 0
        for k, g in groups.items():
            if len(g) < 2:
                continue
            g = sorted(g, key=rank)
            canon = g[0]
            for d in g[1:]:
                if d["duplicate_of"] is None:
                    d["duplicate_of"] = canon["relpath"]
                    d["duplicate_kind"] = label
                    n += 1
        return n

    n_byte_dups = mark_dups(lambda r: ("sha", r["sha256"]), "byte_identical_sha256")
    n_guid_dups = mark_dups(
        lambda r: ("guid", r["guid_set_sha256"]) if (r["parse_ok"] and r.get("n_guids")) else None,
        "identical_globalid_set")

    # ---- contamination check #1 --------------------------------------------
    contaminated = []
    for rec in recs:
        rec["contamination"] = dict(n_shared_guids=0, n_bimedit_files=0,
                                    example_shared_guids=[], example_bimedit_files=[],
                                    byte_identical_to_bimedit=None)
        if rec["sha256"] in be_sha:
            rec["contamination"]["byte_identical_to_bimedit"] = be_sha[rec["sha256"]]
        if not rec["parse_ok"]:
            continue
        g = guids_of(rec["sha256"])
        inter = g & be_guids
        if inter:
            files = set()
            for x in list(inter)[:5000]:
                files.update(be_by_guid[x])
            rec["contamination"].update(
                n_shared_guids=len(inter), n_bimedit_files=len(files),
                example_shared_guids=sorted(inter)[:10],
                example_bimedit_files=sorted(files)[:10])
            contaminated.append(rec)
        # E3 building fingerprint by GUID overlap with Schependomlaan
        if rec["source_collection"] != "schependomlaan" and sch_guids:
            si = g & sch_guids
            if si and rec["n_guids"] and len(si) >= max(50, 0.05 * rec["n_guids"]):
                rec["e3_building"] = True
                rec["e3_building_evidence"] = "shares %d GlobalIds with Schependomlaan" % len(si)

    # ---- shared-GlobalId diagnosis (second pass; see diagnose_contamination.py) ----
    dg = S + "contam_diag.json"
    diag = json.load(open(dg)) if os.path.exists(dg) else None
    if diag:
        for rec in recs:
            d = diag["per_file"].get(rec["relpath"])
            if d:
                rec["contamination"]["diagnosis"] = d

    # ---- eligibility --------------------------------------------------------
    for rec in recs:
        c = rec["contamination"]
        if not rec["parse_ok"]:
            rec["exclusion_reason"] = "parse_failed: %s" % (rec["parse_error"] or "unknown")
        elif c["byte_identical_to_bimedit"]:
            rec["exclusion_reason"] = ("byte-identical to BIM-Edit scene %s"
                                       % c["byte_identical_to_bimedit"])
        elif c["n_shared_guids"]:
            rec["exclusion_reason"] = ("contamination: shares %d GlobalIds with %d BIM-Edit scene "
                                       "file(s)" % (c["n_shared_guids"], c["n_bimedit_files"]))
        elif rec["duplicate_of"]:
            rec["exclusion_reason"] = "duplicate (%s) of %s" % (rec["duplicate_kind"],
                                                                rec["duplicate_of"])
        elif rec["e3_reserved"]:
            rec["exclusion_reason"] = ("Schependomlaan as-planned snapshot reserved for the E3 case "
                                       "study")
        elif rec["e3_building"]:
            rec["exclusion_reason"] = ("Schependomlaan building on the exclusion list (E3 case "
                                       "study)")
        elif not rec["n_products"]:
            rec["exclusion_reason"] = "no IfcProduct in file (not a usable building model)"
        elif rec["relpath"] in STRUCTURAL_EXCLUSIONS:
            rec["structural_similarity_max_vs_bimedit"] = STRUCTURAL_EXCLUSIONS[rec["relpath"]]
            rec["exclusion_reason"] = (
                "structural-similarity %.3f >= pre-registered %.2f threshold; "
                "coincidental match, dropped belt-and-braces"
                % (STRUCTURAL_EXCLUSIONS[rec["relpath"]], STRUCTURAL_THRESHOLD))
        else:
            rec["training_eligible"] = True

    # ---- measured structural similarity, attached for the record --------------
    simax = os.path.join(S, "similarity_axes.json")
    simat = os.path.join(S, "similarity_matrix.npy")
    if os.path.exists(simax) and os.path.exists(simat):
        import numpy as np
        ax = json.load(open(simax))
        mx = np.load(simat).max(axis=1)
        for i, rel in enumerate(ax["corpus"]):
            if rel in by_rel:
                by_rel[rel].setdefault("structural_similarity_max_vs_bimedit",
                                       round(float(mx[i]), 4))

    # ---- descriptors --------------------------------------------------------
    dmap = {}
    for d in descs:
        dmap.setdefault(d["sha256"], d)
    descriptors = dict(
        generated_from="code/corpus/scan_ifc.py + build_manifest.py",
        note=("placement_bbox is the axis-aligned bounding box of the absolute placement origins of "
              "all IfcProducts (cheap spatial-layout summary; not a tessellated geometry bbox)."),
        corpus={}, bimedit={})
    for rec in recs:
        d = dmap.get(rec["sha256"])
        if d:
            descriptors["corpus"][rec["relpath"]] = dict(
                d, training_eligible=rec["training_eligible"],
                source_collection=rec["source_collection"])
    be_recs = []
    for r in bimedit:
        rr = dict(relpath=r["relpath"], sha256=r["sha256"], bytes=r["bytes"],
                  ifc_schema=r.get("ifc_schema") or r.get("ifc_schema_header"),
                  parse_ok=r["parse_ok"], parse_error=r.get("error"),
                  n_products=r.get("n_products"), n_guids=r.get("n_guids"),
                  guid_set_sha256=r.get("guid_set_sha256"))
        be_recs.append(rr)
        d = dmap.get(r["sha256"])
        if d:
            descriptors["bimedit"][r["relpath"]] = d

    # ---- summary ------------------------------------------------------------
    elig = [r for r in recs if r["training_eligible"]]
    per_coll = {}
    for c in COLLECTIONS:
        g = [r for r in recs if r["source_collection"] == c]
        per_coll[c] = dict(
            files=len(g), parse_ok=sum(r["parse_ok"] for r in g),
            duplicates=sum(bool(r["duplicate_of"]) for r in g),
            training_eligible=sum(r["training_eligible"] for r in g),
            bytes=sum(r["bytes"] for r in g),
            **{k: COLLECTIONS[c][k] for k in ("name", "home", "license_basis",
                                              "license_review_required")})

    def size_bucket(n):
        for lim, lab in [(1e5, "<100 KB"), (1e6, "100 KB-1 MB"), (1e7, "1-10 MB"),
                         (1e8, "10-100 MB")]:
            if n < lim:
                return lab
        return ">=100 MB"

    def prod_bucket(n):
        n = n or 0
        for lim, lab in [(1, "0"), (50, "1-49"), (500, "50-499"), (5000, "500-4999")]:
            if n < lim:
                return lab
        return ">=5000"

    summary = dict(
        generated="2026-08-23",
        policy=("Local research use only. Source IFC files are never redistributed; the public "
                "repository ships this manifest plus regeneration instructions."),
        collections=per_coll,
        total_files=len(recs),
        total_bytes=sum(r["bytes"] for r in recs),
        parse_ok=sum(r["parse_ok"] for r in recs),
        parse_failed=sum(not r["parse_ok"] for r in recs),
        duplicates_byte_identical=n_byte_dups,
        duplicates_identical_guid_set=n_guid_dups,
        training_eligible=len(elig),
        training_eligible_target=120,
        target_met=len(elig) >= 120,
        training_eligible_excluding_unclear_licence=sum(
            1 for r in elig if not r["license_review_required"]),
        training_eligible_with_ge_50_products=sum(1 for r in elig if (r["n_products"] or 0) >= 50),
        training_eligible_if_exporter_guid_collisions_kept=len(elig) + sum(
            1 for r in recs if (not r["training_eligible"]) and r["contamination"]["n_shared_guids"]
            and (r["exclusion_reason"] or "").startswith("contamination")),
        e3_reserved=sum(r["e3_reserved"] for r in recs),
        e3_building=sum(r["e3_building"] for r in recs),
        exclusion_reasons=dict(Counter(
            (r["exclusion_reason"] or "").split(":")[0].split(" (")[0]
            for r in recs if not r["training_eligible"])),
        schema_distribution=dict(Counter(r["ifc_schema"] or "unknown" for r in recs)),
        schema_distribution_training_eligible=dict(Counter(r["ifc_schema"] or "unknown"
                                                           for r in elig)),
        size_distribution=dict(Counter(size_bucket(r["bytes"]) for r in recs)),
        size_distribution_training_eligible=dict(Counter(size_bucket(r["bytes"]) for r in elig)),
        product_count_distribution_training_eligible=dict(Counter(prod_bucket(r["n_products"])
                                                                  for r in elig)),
        contamination_protocol=dict(
            probes=[
                dict(name="GlobalId overlap", scope="all corpus files x 151 BIM-Edit scenes",
                     rule="any shared GlobalId drops the corpus building",
                     result="14 files dropped; 26 ids shared, all exporter-generated type, "
                            "relationship or default-storey objects; zero placed physical "
                            "elements shared",
                     report="corpus report, 2026-08-23"),
                dict(name="Provenance (Revit family names and project number)",
                     scope="188 training-eligible + the 14 dropped files x 151 scenes",
                     rule="overlap of language-invariant Revit family names, plus IfcProject name",
                     result="clean across the eligible set (best 5 shared names, all Autodesk "
                            "stock placeholders); VALIDATED by the DigitalHub positive control, "
                            "which shares 25 project-specific German family names and the "
                            "IfcProject number 2018_01 with the BIM-Edit complex scenes and was "
                            "already removed by the GlobalId probe",
                     report="structural-similarity analysis, 2026-08-24"),
                dict(name="Structural similarity", scope="188 x 151 = 28,388 pairs",
                     rule="S_struct = 0.6*cosine(element-type histogram) + 0.4*mean of storey, "
                          "footprint-area, aspect and product-count ratios; pre-registered "
                          "threshold %.2f" % STRUCTURAL_THRESHOLD,
                     result="1 building above threshold (0.862), dropped; the match is "
                            "coincidental on inspection, so the drop is belt-and-braces",
                     report="structural-similarity analysis, 2026-08-24"),
            ],
            note=("The provenance probe is the load-bearing one: the positive control shows the "
                  "structural score gives the single genuinely related model only 0.704, below 14 "
                  "coincidental eligible buildings, because BIM-Edit derived its scenes by "
                  "extracting part of a source project and extraction changes exactly the counts "
                  "and bounding boxes that score measures."),
            structural_threshold=STRUCTURAL_THRESHOLD,
            structural_exclusions=STRUCTURAL_EXCLUSIONS,
        ),
        contamination_check=dict(
            shared_globalid_diagnosis=(
                dict(distinct_shared_globalids=diag["distinct_shared_globalids"],
                     shared_guid_class_histogram=diag["shared_guid_class_histogram"],
                     n_shared_physical_element_guids=diag["n_shared_physical_element_guids"],
                     files_with_shared_physical_elements=diag["files_with_shared_physical_elements"],
                     interpretation=(
                         "Every shared GlobalId is an IfcXxxType definition, a relationship object "
                         "(IfcRelAggregates / IfcRelContainedInSpatialStructure) or a default "
                         "IfcBuildingStorey. No placed physical element (IfcElement instance) is "
                         "shared between any corpus file and any BIM-Edit scene. Revit derives IFC "
                         "GlobalIds from internal element ids, so type and relationship objects "
                         "collide across unrelated projects exported from the same template; the "
                         "same 26 ids recur in up to 86 of the 151 BIM-Edit scenes, including "
                         "purely synthetic ones. The 14 affected corpus files are nonetheless "
                         "dropped from training eligibility, applying the exclusion rule literally "
                         "and conservatively."))
                if diag else None),
            bimedit_scene_files=len(bimedit),
            bimedit_parse_ok=sum(r["parse_ok"] for r in bimedit),
            bimedit_distinct_globalids=len(be_guids),
            corpus_files_sharing_globalids=len(contaminated),
            corpus_files_byte_identical_to_bimedit=sum(
                1 for r in recs if r["contamination"]["byte_identical_to_bimedit"]),
            manifest_diff_clean=not any(
                r["sha256"] in be_sha for r in recs),
            verdict=("CLEAN: no corpus file shares a GlobalId with any BIM-Edit scene file"
                     if not contaminated else
                     "NO SHARED BUILDING CONTENT, but not a literal zero-overlap result: %d corpus "
                     "file(s) share %d distinct GlobalIds with BIM-Edit scenes, every one of them a "
                     "type definition, a relationship object or a default storey emitted with a "
                     "deterministic Revit id; zero placed physical elements are shared, and no "
                     "corpus file is byte-identical to a BIM-Edit scene. The %d files are dropped "
                     "from training eligibility anyway, applying the exclusion rule literally."
                     % (len(contaminated),
                        (diag or {}).get("distinct_shared_globalids", -1), len(contaminated))),
        ),
    )

    manifest = dict(summary=summary, files=recs, bimedit_reference=be_recs,
                    not_acquired=json.load(open(S + "not_acquired.json")))
    json.dump(manifest, open(os.path.join(ROOT, "data/corpus_manifest.json"), "w"), indent=1)
    json.dump(descriptors, open(os.path.join(ROOT, "data/corpus_descriptors.json"), "w"), indent=1)
    print(json.dumps(summary, indent=1)[:6000])


if __name__ == "__main__":
    main()
