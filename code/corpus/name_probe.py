"""Independent provenance probe: overlap of Revit family names between corpus and BIM-Edit.

Element counts and bounding boxes change a lot when a scene is derived from a source
model by extracting part of it, so the descriptor score is a weak detector of exactly
that case. Library and family names survive extraction. Revit exports type names as
"<localized family>:<type>"; the part after the colon is language-invariant, which
matters because the BIM-Edit scenes were exported from an English Revit UI and some
corpus models from a German one.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
W = os.path.join(ROOT, "data", "corpus_build")

GENERIC = {"Standard", "Typ1", "Default", "", "Standard-Fall"}


def suffixes(names):
    return {n.split(":", 1)[1].strip() for n in names
            if ":" in n and n.split(":", 1)[1].strip()}


def main():
    d = json.load(open(os.path.join(ROOT, "data", "corpus_descriptors.json")))
    man = json.load(open(os.path.join(ROOT, "data", "corpus_manifest.json")))
    contam = {r["relpath"] for r in man["files"] if r["contamination"]["n_shared_guids"]}
    N = {}
    for line in open(os.path.join(W, "names.jsonl")):
        r = json.loads(line)
        N[r["relpath"]] = r

    be = sorted(d["bimedit"])
    be_suf = {b: suffixes(N[b]["type_names"]) for b in be}
    be_all = set().union(*be_suf.values()) if be_suf else set()
    be_proj = {N[b]["project_name"] for b in be if N[b]["project_name"]}

    def probe(keys):
        rows = []
        for k in keys:
            s = suffixes(N[k]["type_names"])
            if not s:
                continue
            best = max(((len(s & be_suf[b]) / len(s | be_suf[b]) if (s | be_suf[b]) else 0.0,
                         len(s & be_suf[b]), b) for b in be), default=(0.0, 0, None))
            shared_all = sorted(s & be_all)
            rows.append(dict(
                relpath=k, n_family_names=len(s),
                best_jaccard=round(best[0], 4), best_shared=best[1], best_match=best[2],
                shared_with_any_scene=len(shared_all),
                distinctive_shared=[x for x in shared_all if x not in GENERIC][:30],
                project_name=N[k]["project_name"],
                project_name_matches_bimedit=bool(N[k]["project_name"] in be_proj
                                                  and N[k]["project_name"])))
        rows.sort(key=lambda r: -r["shared_with_any_scene"])
        return rows

    elig = [k for k, v in sorted(d["corpus"].items()) if v.get("training_eligible")]
    res = dict(
        note=__doc__.strip(),
        bimedit_project_names=sorted(be_proj),
        generic_names_ignored=sorted(GENERIC - {""}),
        training_eligible=probe(elig),
        positive_control=probe(sorted(contam)),
    )
    res["summary"] = dict(
        eligible_max_shared_family_names=max(
            (r["shared_with_any_scene"] for r in res["training_eligible"]), default=0),
        eligible_max_jaccard=max((r["best_jaccard"] for r in res["training_eligible"]), default=0),
        control_max_shared_family_names=max(
            (r["shared_with_any_scene"] for r in res["positive_control"]), default=0),
        control_max_jaccard=max((r["best_jaccard"] for r in res["positive_control"]), default=0),
    )
    json.dump(res, open(os.path.join(W, "name_probe.json"), "w"), indent=1)
    print(json.dumps(res["summary"], indent=1))
    print("\ntop eligible by shared family names:")
    for r in res["training_eligible"][:5]:
        print("  %2d shared / %4d names  %s  %s" % (r["shared_with_any_scene"], r["n_family_names"],
                                                    r["relpath"][13:60], r["distinctive_shared"][:6]))
    print("\ntop control by shared family names:")
    for r in res["positive_control"][:3]:
        print("  %2d shared / %4d names  %s" % (r["shared_with_any_scene"], r["n_family_names"],
                                                r["relpath"][13:60]))
        print("      %s" % r["distinctive_shared"][:8])


if __name__ == "__main__":
    main()
