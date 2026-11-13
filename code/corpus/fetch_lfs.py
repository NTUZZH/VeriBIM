"""Fetch git-lfs objects for a cloned repo via media.githubusercontent.com."""
import json, os, subprocess, sys, time, urllib.parse, hashlib

ptrs = json.load(open(sys.argv[1]))
root = sys.argv[2]          # local clone dir, e.g. bs_community_repo
owner_repo = sys.argv[3]    # e.g. buildingsmart-community/Community-Sample-Test-Files
branch = sys.argv[4]
only_ext = sys.argv[5].lower() if len(sys.argv) > 5 else ".ifc"
skip_sub = sys.argv[6] if len(sys.argv) > 6 else None

ok = fail = skipped = 0
for i, p in enumerate(ptrs):
    path = p["path"]
    if not path.lower().endswith(only_ext):
        continue
    if skip_sub and skip_sub in path:
        skipped += 1
        continue
    rel = os.path.relpath(path, root)
    url = ("https://media.githubusercontent.com/media/%s/%s/%s"
           % (owner_repo, branch, urllib.parse.quote(rel)))
    r = subprocess.run(["curl", "-sSL", "--max-time", "600", "-o", path, "-w", "%{http_code}", url],
                       capture_output=True, text=True)
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    good = h.hexdigest() == p["oid"] and os.path.getsize(path) == p["size"]
    ok += good
    fail += (not good)
    print(i, r.stdout.strip(), "OK" if good else "MISMATCH", os.path.getsize(path), rel, flush=True)
    time.sleep(0.3)
print("done ok=%d fail=%d skipped=%d" % (ok, fail, skipped))
