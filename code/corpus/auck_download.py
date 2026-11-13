"""Download the Open IFC Model Repository (U. Auckland) listing, politely and sequentially."""
import hashlib, json, os, re, subprocess, time, unicodedata

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "data", "corpus_build")

S = WORK + os.sep
OUT = os.path.join(ROOT, "data", "corpus", "auckland")
os.makedirs(OUT, exist_ok=True)
heads = json.load(open(S + "auck_head.json"))


def safe(name):
    n = unicodedata.normalize("NFKC", name)
    n = re.sub(r"[^A-Za-z0-9._ -]", "_", n)
    return re.sub(r"\s+", " ", n).strip()


recs = []
for i, m in enumerate(heads):
    if m["http"] != "200":
        recs.append(dict(m, local=None, sha256=None, status="http_" + str(m["http"])))
        print(i, "SKIP", m["http"], m["modelFile"][:60], flush=True)
        continue
    fn = "%03d_%s" % (m["id"], safe(m["modelFile"]))
    dest = os.path.join(OUT, fn)
    if os.path.exists(dest) and os.path.getsize(dest) == m["bytes"]:
        status = "cached"
    else:
        r = subprocess.run(["curl", "-sSL", "--max-time", "900", "--retry", "2",
                            "-o", dest, "-w", "%{http_code}", m["url"]],
                           capture_output=True, text=True)
        status = "http_" + r.stdout.strip()
        time.sleep(1.0)
    got = os.path.getsize(dest) if os.path.exists(dest) else 0
    h = hashlib.sha256()
    with open(dest, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    recs.append(dict(m, local=fn, sha256=h.hexdigest(), got_bytes=got,
                     status=status, size_match=(got == m["bytes"])))
    print(i, status, got, "match" if got == m["bytes"] else "SIZE-MISMATCH", fn[:70], flush=True)

json.dump(recs, open(S + "auck_downloaded.json", "w"), indent=1)
print("done", sum(1 for r in recs if r.get("local")))
