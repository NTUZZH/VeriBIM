"""Re-resolve the 35 opposite anchors of the 6,000-task Stage B pool under the corrected rule (fixed modules)."""
import json, os, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'install_v2'))
from fixcommon import read_jsonl, reresolve, setup_code
code = setup_code('fixed')
recs = read_jsonl(HERE + '/pool_opposite_records.jsonl')
rows = reresolve(recs, code)
json.dump(rows, open(HERE + '/pool_opposite_reresolve.json', 'w'), indent=1)
print(len(rows), collections.Counter(r['class'] for r in rows), 'library agrees', sum(r['generator_library_agree'] for r in rows))
