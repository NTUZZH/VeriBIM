"""HEAD-probe every model in the Open IFC Model Repository listing."""
import json, subprocess, time, urllib.parse

import os

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WORK = os.path.join(ROOT, "data", "corpus_build")

S = WORK + os.sep
d=json.load(open(S+"auck_models.json"))
base="https://openifcmodel.cs.auckland.ac.nz/api/download/"
out=[]
for i,m in enumerate(d):
    mf=m.get("modelFile")
    if not mf: continue
    url=base+urllib.parse.quote(mf)
    r=subprocess.run(["curl","-sSI","--max-time","30","-L",url],capture_output=True,text=True)
    code=""; length=""
    for line in r.stdout.splitlines():
        ls=line.lower()
        if ls.startswith("http/"): code=line.split()[1]
        if ls.startswith("content-length:"): length=line.split(":",1)[1].strip()
    out.append(dict(id=m["id"],name=m["name"],modelFile=mf,url=url,http=code,bytes=int(length) if length.isdigit() else None,viewable=m.get("viewable"),org=m.get("organisation"),desc=m.get("description"),createdby=m.get("createdby")))
    print(i,m["id"],code,length,mf[:60],flush=True)
    time.sleep(0.6)
json.dump(out,open(S+"auck_head.json","w"),indent=1)
