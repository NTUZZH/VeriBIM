"""Independent re-read of the re-source outputs, and the numbers REPORT.txt quotes.

Reads the inputs, the outputs, the journals and the check files; recomputes every
count from the records themselves; writes gen/resource/dropped.jsonl (both files)
and gen/resource/report_numbers.json.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

RS = Path("runs_local/corpus_v10/gen/resource")
RUNS = {"train_ifc4x3": ("inputs/train_ifc4x3_in.jsonl", "train_ifc4x3_v2.jsonl"),
        "train_ifc4": ("inputs/train_ifc4_in.jsonl", "train_ifc4_v2.jsonl")}
ORIGINAL = {"train_ifc4x3": "runs_local/corpus_v10/gen/train_ifc4x3/tasks.jsonl",
            "train_ifc4": "runs_local/corpus_v10/gen/train_ifc4/tasks.jsonl"}
ALLOWED = {"input_ifc", "source_model.relpath", "source_model.sha256",
           "verification.gold_sha256", "verification.gold_bytes",
           "verification.reexecution_match", "verification.null_edit_score",
           "verification.self_score.geometry", "verification.self_score.semantics",
           "verification.self_score.topology", "verification.self_score.final",
           "difficulty.scene_n_products", "difficulty.scene_n_relations",
           "verification.resourced", "verification.resourced_old"}


def diff_paths(old, new, prefix=""):
    if isinstance(old, dict) and isinstance(new, dict):
        out = []
        for key in list(old) + [k for k in new if k not in old]:
            path = f"{prefix}.{key}" if prefix else str(key)
            if key not in old or key not in new:
                out.append(path)
            else:
                out.extend(diff_paths(old[key], new[key], path))
        return out
    return [prefix] if (old != new or type(old) is not type(new)) else []


def main():
    numbers = {}
    dropped_all = []
    for run, (inp, out) in RUNS.items():
        a = [json.loads(l) for l in open(RS / inp)]
        b = [json.loads(l) for l in open(RS / out)]
        orig = [json.loads(l) for l in open(ORIGINAL[run])]
        dropped = [json.loads(l) for l in open(RS / f"work_{run}/dropped.jsonl")]
        drop_ids = {d["task_id"] for d in dropped}
        for d in dropped:
            dropped_all.append({"file": run, **d})
        # order: output = input minus dropped, same order
        assert [r["task_id"] for r in a if r["task_id"] not in drop_ids] == \
            [r["task_id"] for r in b], run
        # the original generator file has the same ids in the same order
        assert [r["task_id"] for r in orig] == [r["task_id"] for r in a], run
        by_in = {r["task_id"]: r for r in a}
        c = Counter()
        extra_paths = Counter()
        for r in b:
            old = by_in[r["task_id"]]
            ver = r["verification"]
            if ver.get("resourced"):
                c["resourced"] += 1
                changed = set(diff_paths(old, r))
                bad = changed - ALLOWED
                if bad:
                    extra_paths.update(bad)
                ro = ver["resourced_old"]
                c["source_bytes_identical_v1_v2" if ro["source_sha256"] == r["source_model"]["sha256"]
                  else "source_bytes_changed_v1_v2"] += 1
                c["gold_sha_unchanged" if ro["gold_sha256"] == ver["gold_sha256"]
                  else "gold_sha_changed"] += 1
                if ro["gold_sha256"] != ver["gold_sha256"] and \
                        ro["source_sha256"] == r["source_model"]["sha256"]:
                    c["gold_sha_changed_on_identical_source"] += 1
                for key in ro:
                    if key not in ("input_ifc", "source_sha256", "gold_sha256", "gold_bytes"):
                        c[f"also_changed:{key}"] += 1
                if ver.get("repair"):
                    c["resourced_and_filling_repaired"] += 1
            else:
                assert r == old, r["task_id"]
                c["native_unchanged_in_this_pass"] += 1
                if ver.get("repair"):
                    c["native_filling_repaired"] += 1
            if ver.get("repair_rerendered"):
                c["script_rerendered"] += 1
            if ver.get("repair"):
                c["filling_repaired_total"] += 1
        c["input"] = len(a)
        c["output"] = len(b)
        c["dropped"] = len(dropped)
        c.update({f"dropped:{d['reason']}": 1 for d in dropped} and Counter(
            f"dropped:{d['reason']}" for d in dropped))
        c["migrated_in_input"] = sum(1 for r in a if "/corpus_v10/migrated/" in r["input_ifc"]
                                     or "/corpus_v10/heldout_4x3/" in r["input_ifc"])
        c["heldout_4x3_sources"] = sum(1 for r in a if "/heldout_4x3/" in r["input_ifc"])
        # original -> input: only the filling repair and the re-render
        rep = Counter()
        for o, i in zip(orig, a):
            paths = set(diff_paths(o, i))
            rep[tuple(sorted(paths))] += 1
        numbers[run] = {"counts": dict(sorted(c.items())),
                        "fields_changed_beyond_allowed": dict(extra_paths),
                        "original_to_input_changes": {"|".join(k) or "(none)": v
                                                      for k, v in rep.items()}}
        journal = [json.loads(l) for l in open(RS / f"work_{run}/journal.jsonl")]
        numbers[run]["journal"] = {
            "entries": len(journal), "unique": len({j["task_id"] for j in journal}),
            "ok": sum(1 for j in journal if j["ok"]),
            "failed": dict(Counter(j["stage"] for j in journal if not j["ok"])),
            "reexecution_match": dict(Counter(j.get("reexecution_match") for j in journal)),
            "filling_type_unset": sum(1 for j in journal if j.get("filling_type_unset")),
            "task_seconds": round(sum(j.get("seconds", 0) for j in journal), 1)}
    (RS / "dropped.jsonl").write_text("".join(json.dumps(d, ensure_ascii=False) + "\n"
                                              for d in dropped_all))
    # peak memory per worker process (chunk logs) and per launch (time -v)
    peaks = {}
    for run in RUNS:
        text = (RS / f"logs/resource_{run}.log").read_text()
        values = [float(x) for x in re.findall(r", ([0-9.]+) GB \|", text)]
        idx = [float(x) for x in re.findall(r"s ([0-9.]+) GB$", text, re.M)]
        peaks[run] = {"max_chunk_worker_gb": max(values or [0]),
                      "max_index_worker_gb": max(idx or [0])}
        tfile = RS / f"logs/resource_{run}.time"
        if tfile.exists():
            t = tfile.read_text()
            peaks[run]["time_v_max_rss_kb"] = re.findall(r"Maximum resident set size \(kbytes\): (\d+)", t)
            peaks[run]["time_v_elapsed"] = re.findall(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\): (\S+)", t)
    numbers["peaks"] = peaks
    numbers["n_dropped_total"] = len(dropped_all)
    (RS / "report_numbers.json").write_text(json.dumps(numbers, indent=1))
    print(json.dumps(numbers, indent=1))


if __name__ == "__main__":
    main()
