"""Cost of each hosted arm from the per-task token counts and the providers' list prices (USD per million tokens,
recorded 2026-09-29). Input tokens are charged at the uncached rate, so the figures are an
upper bound where a provider caches prompt prefixes.
    python hosted_cost.py [results_dir]
"""
import glob, json, os, sys
PRICE = {  # model id: (input, output) USD per million tokens
    "gpt-5.6-luna": (0.20, 1.20), "gpt-5.6-sol": (4.0, 20.0), "gpt-5.5": (1.25, 10.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-sonnet-5": (2.0, 10.0),
    "gemini-3.8-flash": (0.75, 3.75), "deepseek-v4-pro": (1.32, 3.96), "deepseek-flash": (0.30, 1.20),
}
root = sys.argv[1] if len(sys.argv) > 1 else "results/benchmark"
rows = []
for p in sorted(glob.glob(os.path.join(root, "hosted108_*_all", "per_task_*.jsonl"))):
    arm = os.path.basename(os.path.dirname(p)).replace("hosted108_", "").replace("_all", "")
    model = os.path.basename(p)[len("per_task_"):-len(".jsonl")]
    recs = [json.loads(l) for l in open(p) if l.strip()]
    tin = sum(int(r.get("input_tokens") or 0) for r in recs); tout = sum(int(r.get("output_tokens") or 0) for r in recs)
    cread = sum(int(r.get("cache_read_tokens") or 0) for r in recs); cwrite = sum(int(r.get("cache_creation_tokens") or 0) for r in recs)
    done = sum(1 for r in recs if all(((r.get("score") or {}).get(k) or 0) >= 0.9 for k in ("geometry", "semantics", "topology")))
    err = sum(1 for r in recs if r.get("stop_reason") == "inference_error")
    pi, po = PRICE.get(model, (float("nan"),) * 2)
    # cache reads at 0.1x and cache writes at 1.25x the base input price (Anthropic); input_tokens already includes both
    cost = (tin - cread - cwrite) / 1e6 * pi + cread / 1e6 * pi * 0.1 + cwrite / 1e6 * pi * 1.25 + tout / 1e6 * po
    rows.append((arm, model, len(recs), done, err, tin, cread, tout, cost, cost / max(1, len(recs))))
print(f"{'arm':22} {'model':20} {'n':>4} {'done':>4} {'err':>3} {'in_tok':>10} {'cached':>9} {'out_tok':>9} {'USD':>7} {'USD/task':>8}")
for r in rows:
    print(f"{r[0]:22} {r[1]:20} {r[2]:4d} {r[3]:4d} {r[4]:3d} {r[5]:10d} {r[6]:9d} {r[7]:9d} {r[8]:7.2f} {r[9]:8.3f}")
