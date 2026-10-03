"""How often does a snapshot open its turn with deliberation it was not trained on?

The training targets carry an empty think block: the chat template opens an
assistant turn with `<think>\\n`, which is exactly the generation prompt, and the
target closes it immediately. So a rollout whose first turn keeps deliberating is
doing something the supervised data never showed it.

This probe asks only that question, and asks it cheaply: one request per task per
adapter, capped at a few dozen tokens, no tool execution and no sandbox. The
completion either closes the block straight away or it does not.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import paths

paths.ensure_harness_on_path()

from modifc_harness.client import ChatClient  # noqa: E402
from modifc_harness.prompts import SYSTEM_PROMPT, TOOL_SCHEMA, build_user_message  # noqa: E402

CLOSE = re.compile(r"^\s*</think>")


def classify(text: str) -> str:
    """``empty`` when the turn closes the block before saying anything."""
    if CLOSE.match(text or ""):
        return "empty_think"
    return "deliberating"


def probe(adapter: str, records, base_url: str, max_tokens: int,
          concurrency: int) -> dict:
    client = ChatClient(base_url=base_url, model=adapter, request_timeout=600.0,
                        max_attempts=2, retry_delay=10.0)

    def one(record):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(
                record.get("instruction") or record["prompt"], "/work/model.ifc")},
        ]
        try:
            response = client.chat(messages, tools=[TOOL_SCHEMA], temperature=0.0,
                                   top_p=1.0, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001
            return {"task_id": record["task_id"], "verdict": "error",
                    "detail": str(exc)[:120]}
        text = response.content or ""
        return {"task_id": record["task_id"], "operation": record["operation"],
                "verdict": classify(text), "head": text[:80]}

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        rows = list(pool.map(one, records))
    counts = Counter(r["verdict"] for r in rows)
    by_op = {}
    for operation in sorted({r.get("operation") for r in rows if r.get("operation")}):
        group = [r for r in rows if r.get("operation") == operation]
        by_op[operation] = {
            "n": len(group),
            "deliberating": sum(1 for r in group if r["verdict"] == "deliberating"),
        }
    return {"adapter": adapter, "n": len(rows), "counts": dict(counts),
            "deliberating_share": round(counts["deliberating"] / len(rows), 4)
            if rows else None, "by_operation": by_op, "rows": rows}


def main(argv=None) -> int:
    from .gate_eval import load_subset

    ap = argparse.ArgumentParser(prog="stage-a-think-probe")
    ap.add_argument("--adapters", nargs="+", required=True)
    ap.add_argument("--subset", default=str(paths.STAGE_A_DATA / "v1/val_subset_100.json"))
    ap.add_argument("--tasks-file",
                    default=str(paths.PROJECT_ROOT / "data/veribim_tasks_v1/tasks.jsonl"))
    ap.add_argument("--base-url", default="http://127.0.0.1:8000/v1")
    ap.add_argument("--max-tokens", type=int, default=48)
    ap.add_argument("--concurrency", type=int, default=16)
    ap.add_argument("--out", default=str(paths.PROJECT_ROOT
                                         / "runs_local/stage_a_val_v1/think_probe.json"))
    args = ap.parse_args(argv)

    records = load_subset(Path(args.subset), Path(args.tasks_file))
    out = []
    for adapter in args.adapters:
        result = probe(adapter, records, args.base_url, args.max_tokens,
                       args.concurrency)
        out.append(result)
        print(json.dumps({k: result[k] for k in
                          ("adapter", "n", "counts", "deliberating_share")},
                         indent=2), flush=True)
    Path(args.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
