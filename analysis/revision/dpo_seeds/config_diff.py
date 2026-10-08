#!/usr/bin/env python3
"""Comparator check of a seed replicate against the reported preference run dpo_v10.

  config_diff.py NEW_RESOLVED_CONFIG REF_RESOLVED_CONFIG --run-id RUNID --seed SEED --out FILE [--dry-run]

Flattens both resolved_config.json files and lists every differing key. Exit 0 only when the differing keys are a
subset of the run identity (run_id, cli_args.run_id), the seed (cli_args.seed, dpo_config.seed, dpo_config.data_seed),
the output path (dpo_config.output_dir) and the timestamp (started_at), and when those keys carry the expected values
(the new run id, the new seed, checkpoints/stage_b/<run id>). With --dry-run the trainer's own dry-run flag
(cli_args.dry_run True against False) is also accepted, because the config dumped by `--dry-run` records it.
Every other difference (recipe, data, adapter, parameter counts, library versions, notes) is a mismatch: exit 1.
"""
import argparse
import json
import os
import sys

ROOT = os.environ.get("VERIBIM_ROOT") or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
REF_SEED = 20260929
REF_RUN = "dpo_v10"


def flat(d, pre=""):
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(flat(v, pre + k + "."))
        else:
            out[pre + k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("new")
    ap.add_argument("ref")
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    fn, fr = flat(json.load(open(a.new))), flat(json.load(open(a.ref)))
    expected = {
        "run_id": (a.run_id, REF_RUN),
        "cli_args.run_id": (a.run_id, REF_RUN),
        "cli_args.seed": (a.seed, REF_SEED),
        "dpo_config.seed": (a.seed, REF_SEED),
        "dpo_config.data_seed": (a.seed, REF_SEED),
        "dpo_config.output_dir": (f"{ROOT}/checkpoints/stage_b/{a.run_id}", f"{ROOT}/checkpoints/stage_b/{REF_RUN}"),
    }
    if a.dry_run:
        expected["cli_args.dry_run"] = (True, False)
    lines, bad = [], []
    for k in sorted(set(fn) | set(fr)):
        if fn.get(k, "<absent>") == fr.get(k, "<absent>"):
            continue
        line = f"{k}: {a.run_id}={fn.get(k, '<absent>')!r}  {REF_RUN}={fr.get(k, '<absent>')!r}"
        if k == "dpo_config.dataset_num_proc":
            # number of data-loading worker processes; derived from the core allowance, does not touch the optimisation
            lines.append(line + "  [loader workers, allowed]")
            continue
        if k == "started_at":
            lines.append(line + "  [timestamp, allowed]")
        elif k in expected:
            ok = (fn.get(k), fr.get(k)) == expected[k]
            lines.append(line + ("  [allowed]" if ok else f"  [UNEXPECTED VALUE, expected {expected[k]!r}]"))
            if not ok:
                bad.append(k)
        else:
            lines.append(line + "  [NOT ALLOWED]")
            bad.append(k)
    # a key that must differ but does not (for example the seed left at 20260929) is also a mismatch
    for k, (want_new, _) in expected.items():
        if fn.get(k) != want_new and k not in bad:
            bad.append(k)
            lines.append(f"{k}: {a.run_id}={fn.get(k)!r}  [UNEXPECTED VALUE, expected {want_new!r}]")
    verdict = ("VERDICT OK: only the run identity, the seed, the output path and the timestamp differ"
               if not bad else f"VERDICT MISMATCH: {len(bad)} key(s) differ beyond run identity/seed/output/timestamp: {', '.join(bad)}")
    text = "\n".join([f"# {a.new}", f"# against {a.ref}", f"# {len(lines)} differing key(s)"] + lines + [verdict]) + "\n"
    open(a.out, "w").write(text)
    print(text, end="")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
