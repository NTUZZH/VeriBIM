"""Write one user note per benchmark task with the three retrieved training trajectories as worked examples.

Two variants:
  notes/<task_id>.md        the documented library note (analysis/revision/informed/note_informed.md)
                            with its three generic worked examples replaced by the three retrieved ones;
                            every character before "### Example 1" is kept as it is.
  notes_short/<task_id>.md  the short library note (runs_local/bench_v4/geom_prompt_note_frontier.md), then the
                            same heading and the same three retrieved examples.

The examples are formatted by the same rules as analysis/revision/informed/build_informed_note.py
(user turn, assistant text, each tool call as a python block, each tool result as a text block cut to its
first 1,500 characters). The script first rebuilds note_informed.md from its own three examples with this
formatter and stops unless the result is byte-identical, so the two arms differ only in which examples they
show.

The prompt length of the first request (system message, tool schema and user turn rendered with the served
chat template) is measured with the Qwen3.5-9B tokenizer. A prompt above BUDGET tokens has the middle of its
longest tool results replaced by "[... output shortened ...]" until it fits; the count is reported.

Reads results/retrieval.json and runs_local/stage_a_v10/sft_train.jsonl.gz; writes notes/, notes_short/,
results/retrieval_table.csv and results/notes_report.json. Runs in the l2train environment (tokenizer).
"""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "../../.."))
INFORMED = os.path.join(ROOT, "analysis/revision/informed")
SHORT_NOTE = os.path.join(ROOT, "runs_local/bench_v4/geom_prompt_note_frontier.md")
MODEL_DIR = os.environ.get("QWEN_DIR", os.path.expanduser("~/models/Qwen3.5-9B"))  # the weights the server loads
RESULTS = os.path.join(ROOT, "runs_local/bench_v4/results")
SERVED = "Qwen3.5-9B"
BUDGET = 20000
HEADING = "## Three worked examples (reference dialogues on other buildings)"
SHORT_MARK = "[... output shortened ...]"
TOOL_CAP = 1500


def load_prompts_module():
    spec = importlib.util.spec_from_file_location(
        "veribim_prompts", os.path.join(ROOT, "code/harness/modifc_harness/prompts.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def clean(s: str) -> str:
    # The working-copy path is replaced as in the documented note. The rest of the line is taken too,
    # because some model file names contain spaces.
    return re.sub(r"IFC model path: [^\n]+", "IFC model path: <path to the working copy>", s or "")


def tool_text(c: str, limit: int | None) -> str:
    """The tool result as the documented note shows it (first 1,500 characters), or, when the prompt
    is over budget, its head and tail around a marker."""
    c = c.rstrip()
    if limit is None:
        return c[:TOOL_CAP]
    c = c[:TOOL_CAP]
    if len(c) <= limit:
        return c
    head = (limit * 2) // 3
    tail = limit - head
    return c[:head].rstrip() + "\n" + SHORT_MARK + "\n" + c[-tail:].lstrip()


def example_parts(i: int, messages: list[dict], limits: dict | None = None) -> list[str]:
    """Same layout as build_informed_note.py. ``limits`` maps a message index to a shortened length."""
    limits = limits or {}
    parts = [f"### Example {i}"]
    for j, m in enumerate(messages[1:], start=1):
        role = m["role"]
        c = clean(m.get("content"))
        if role == "user":
            parts.append("User:\n" + c)
        elif role == "assistant":
            if c.strip():
                parts.append("Assistant: " + c.strip())
            for t in m.get("tool_calls") or []:
                args = t["function"]["arguments"]
                code = args["code"] if isinstance(args, dict) else json.loads(args)["code"]
                parts.append("Assistant tool call execute_ifc_code:\n```python\n" + code.rstrip() + "\n```")
        elif role == "tool":
            parts.append("Tool result:\n```\n" + tool_text(c, limits.get(j)) + "\n```")
    parts.append("")
    return parts


def main() -> int:
    from transformers import AutoTokenizer

    prompts = load_prompts_module()
    tok = AutoTokenizer.from_pretrained(MODEL_DIR)
    template = open(os.path.join(MODEL_DIR, "chat_template.jinja"), encoding="utf-8").read()

    def n_tokens(user: str) -> int:
        msgs = [{"role": "system", "content": prompts.SYSTEM_PROMPT}, {"role": "user", "content": user}]
        ids = tok.apply_chat_template(msgs, tools=[prompts.TOOL_SCHEMA], chat_template=template,
                                      add_generation_prompt=True, tokenize=True)
        if isinstance(ids, dict) or hasattr(ids, "keys"):
            ids = ids["input_ids"]
        return len(ids)

    def user_turn(instruction: str, path: str, note: str) -> str:
        # prompts.build_user_message with the note read from a file: instruction, path, stripped note
        note = note.strip()
        message = f"{instruction}\n\nIFC model path: {path}"
        return f"{message}\n\n{note}" if note else message

    # 1. the formatter reproduces the documented note exactly
    informed = open(os.path.join(INFORMED, "note_informed.md"), encoding="utf-8").read()
    prefix = informed[: informed.index("### Example 1")]
    assert prefix.rstrip("\n").endswith(HEADING)
    pick = json.load(open(os.path.join(INFORMED, "example_trajectories.json")))
    parts = []
    for i, k in enumerate(["create_filling_opposite", "translate", "underspecified"], 1):
        parts += example_parts(i, pick[k]["messages"])
    rebuilt = prefix + "\n".join(parts)
    assert rebuilt == informed, "formatter does not reproduce note_informed.md"
    short_base = open(SHORT_NOTE, encoding="utf-8").read().rstrip()
    short_prefix = short_base + "\n\n" + HEADING + "\n\n"

    # 2. the retrieved trajectories
    retrieval = json.load(open(os.path.join(HERE, "results", "retrieval.json")))
    want = {p["row"] for o in retrieval for p in o["retrieved"]}
    msgs_by_row = {}
    for n, line in enumerate(gzip.open(os.path.join(ROOT, "runs_local/stage_a_v10/sft_train.jsonl.gz"), "rt", encoding="utf-8")):
        if n in want:
            r = json.loads(line)
            msgs_by_row[n] = (r["task_id"], r["messages"])
    assert set(msgs_by_row) == want
    tasks = {}
    for line in open(os.path.join(ROOT, "runs_local/bench_v4/tasks.v4c.jsonl"), encoding="utf-8"):
        t = json.loads(line)
        tasks[t["task_id"]] = t

    # calibration: the documented arm's first request for one task, against the server's own count
    cal_id = "CHN-CWD-DIR-B45m4-003"
    tr = json.load(open(os.path.join(RESULTS, "local108_informed_all", SERVED, "transcripts", f"{cal_id}.json")))
    cal_user = tr["messages"][1]["content"]
    cal_ours = n_tokens(cal_user)
    cal_server = int(tr["iterations"][0]["input_tokens"])
    print("calibration", cal_id, "tokenizer", cal_ours, "server", cal_server, flush=True)

    os.makedirs(os.path.join(HERE, "notes"), exist_ok=True)
    os.makedirs(os.path.join(HERE, "notes_short"), exist_ok=True)
    table, shortened = [], []
    leaks = 0
    for o in retrieval:
        tid = o["task_id"]
        t = tasks[tid]
        instruction = t.get("instruction") or t["prompt"]
        stem = os.path.splitext(os.path.basename(t["input_ifc"]))[0]
        for p in o["retrieved"]:
            assert msgs_by_row[p["row"]][0] == p["task_id"]
        row = {"task_id": tid}
        for variant, prefix_text, run in (("notes", prefix, "local108_retrieval_all"),
                                          ("notes_short", short_prefix, "local108_retrievalshort_all")):
            limits = {p["row"]: {} for p in o["retrieved"]}
            path = os.path.join(RESULTS, run, SERVED, "edited", tid, f"{stem}.ifc")
            while True:
                ex = []
                for i, p in enumerate(o["retrieved"], 1):
                    ex += example_parts(i, msgs_by_row[p["row"]][1], limits[p["row"]])
                note = prefix_text + "\n".join(ex)
                n = n_tokens(user_turn(instruction, path, note))
                if n <= BUDGET:
                    break
                # shorten the longest tool result still above 300 characters
                best = None
                for p in o["retrieved"]:
                    for j, m in enumerate(msgs_by_row[p["row"]][1][1:], start=1):
                        if m["role"] != "tool":
                            continue
                        cur = limits[p["row"]].get(j, min(TOOL_CAP, len((m.get("content") or "").rstrip())))
                        if cur > 300 and (best is None or cur > best[0]):
                            best = (cur, p["row"], j)
                assert best is not None, f"{tid}: cannot shorten below budget"
                limits[best[1]][best[2]] = int(best[0] * 0.6)
            n_short = sum(len(v) for v in limits.values())
            if n_short:
                shortened.append({"task_id": tid, "variant": variant, "tool_results_shortened": n_short})
            if "/home/" in note or "runs_local/" in note or "data/corpus" in note:
                leaks += 1
                raise AssertionError(f"{tid} {variant}: a local path is left in the note")
            with open(os.path.join(HERE, variant, f"{tid}.md"), "w", encoding="utf-8") as fh:
                fh.write(note)
            row[f"prompt_tokens_{variant}"] = n
            row[f"note_sha256_{variant}"] = hashlib.sha256(note.encode()).hexdigest()[:16]
        for i, p in enumerate(o["retrieved"], 1):
            row[f"train_task_{i}"] = p["task_id"]
            row[f"train_cell_{i}"] = p["cell"]
            row[f"train_edit_kind_{i}"] = p["edit_kind"]
            row[f"similarity_{i}"] = p["similarity"]
        row["cell"] = o["cell"]
        row["edit_kind"] = o["edit_kind"]
        row["clarification"] = o["clarification"]
        row["verbatim_rows_excluded"] = len(o["excluded_verbatim_rows"])
        table.append(row)

    cols = ["task_id", "cell", "edit_kind", "clarification"]
    for i in (1, 2, 3):
        cols += [f"train_task_{i}", f"train_cell_{i}", f"train_edit_kind_{i}", f"similarity_{i}"]
    cols += ["verbatim_rows_excluded", "prompt_tokens_notes", "prompt_tokens_notes_short",
             "note_sha256_notes", "note_sha256_notes_short"]
    with open(os.path.join(HERE, "results", "retrieval_table.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in table:
            w.writerow(r)
    doc_tokens = [r["prompt_tokens_notes"] for r in table]
    short_tokens = [r["prompt_tokens_notes_short"] for r in table]
    rep = {
        "budget_tokens": BUDGET,
        "calibration": {"task_id": cal_id, "tokenizer_count": cal_ours, "server_count": cal_server},
        "documented_note_rebuilt_byte_identical": True,
        "notes": {"min": min(doc_tokens), "median": sorted(doc_tokens)[len(doc_tokens) // 2], "max": max(doc_tokens)},
        "notes_short": {"min": min(short_tokens), "median": sorted(short_tokens)[len(short_tokens) // 2],
                        "max": max(short_tokens)},
        "prompts_shortened": shortened,
        "tool_results_cut_at_1500_chars": sum(
            1 for o in retrieval for p in o["retrieved"] for m in msgs_by_row[p["row"]][1]
            if m["role"] == "tool" and len(clean(m.get("content")).rstrip()) > TOOL_CAP),
        "tool_results_total": sum(1 for o in retrieval for p in o["retrieved"] for m in msgs_by_row[p["row"]][1]
                                  if m["role"] == "tool"),
    }
    json.dump(rep, open(os.path.join(HERE, "results", "notes_report.json"), "w"), indent=1)
    print(json.dumps(rep, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
