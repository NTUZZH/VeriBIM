"""Hand check of analysis 3: world boxes of a clashing pair in a ground-truth model,
read independently of clashlib.py."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as C
import hand_check_abs as H

if __name__ == "__main__":
    tasks = C.load_tasks()
    dest = C.TMP / "hand"; dest.mkdir(exist_ok=True)
    for spec in sys.argv[1:]:
        tid, *guids = spec.split("|")
        gold = C.unpack_gold(tasks[tid], dest)
        print(tid, tasks[tid]["instruction"][:160])
        for g in guids:
            H.describe(gold, guid=g)
        gold.unlink()
