import sys, os, json
os.environ["OMP_NUM_THREADS"]="1"
sys.path.insert(0, "scripts/corpus/migrator_v2")
import ifcopenshell
from vkeys import validate_keys
f = ifcopenshell.open(sys.argv[1]); n = int(sys.argv[2]) if len(sys.argv) > 2 else 2
filt = sys.argv[3] if len(sys.argv) > 3 else ""
k, s = validate_keys(f, samples=n)
print(f.schema_identifier, dict(k.most_common()))
for key, v in s.items():
    if filt and filt not in key: continue
    print("=====", key, k[key])
    for m in v: print(m); print("--")
