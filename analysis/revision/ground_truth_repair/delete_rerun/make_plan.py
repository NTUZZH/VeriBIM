"""Build the v4e deletion re-run plan (2026-10-16).

Input: gt_fix/rerun_list_delete_v2.csv (rows whose transcript ran delete_element, delete_filling or
delete_filling_with_opening without a traceback, on the 49 deletion tasks whose ground truth was repaired;
the contended latency arm and smoke runs already excluded when the list was built).
Rows with geom_call_ran_clean = 0 are left out (their code never called the library helper).

Writes, all under gt_fix/delete_rerun/ (and the arms table in gt_fix/):
  subset_<run>_<model>.json   task ids of each job (sorted)
  plan.json                   one entry per (run, model): server group, adapter, environment, launcher, checks
  ../rerun_delete_arms.md     the arms table
Nothing is launched.
    python make_plan.py
"""
import ast, csv, hashlib, json, os, sys
from collections import defaultdict
from pathlib import Path

P = Path(".")
B = P / "runs_local/bench_v4"
RES = B / "results"
G = P / "analysis/revision/ground_truth_repair"
D = G / "delete_rerun"
R15 = P / "analysis/revision"

NOTE_FRONTIER = B / "geom_prompt_note_frontier.md"
NOTE_INFORMED = P / "analysis/revision/informed/note_informed.md"
NOTE_LIBFIX = R15 / "commercial_reruns/note_lib_override.md"
NOTES_RETR = R15 / "retrieval_fewshot/notes"
NOTES_RETR_SHORT = R15 / "retrieval_fewshot/notes_short"
MANIFEST = {NOTES_RETR: (R15 / "retrieval_fewshot/results/manifest_notes.sha256", "5beafea91dcdfc49"),
            NOTES_RETR_SHORT: (R15 / "retrieval_fewshot/results/manifest_notes_short.sha256", "5ca788b0a9c7e710")}
# md5 each original run logged (eval_rerun.log, eval_informed4.log, eval_informed216.log, gt_fix/report.md)
NOTE_MD5 = {NOTE_FRONTIER: "a2ff593dbf8d64de84ac79bf51cbc6a2",
            NOTE_INFORMED: "7dad463cc8e7e6245995ee0876653d2a",
            NOTE_LIBFIX: "07b07129cdbe6838567c494036cf0644"}

ADAPTER = {  # served name -> path (gt_fix/report.md "Adapters of the re-runs"; FINAL_ARTIFACT for grpo_v10b_c10)
    "sft_v10": P / "checkpoints/stage_a/sft_v10/adapter",
    "dpo_v10_c3": P / "checkpoints/stage_b/dpo_v10/checkpoint-3",
    "dpo_v10_c6": P / "checkpoints/stage_b/dpo_v10/checkpoint-6",
    "dpo_v9_c10": P / "checkpoints/stage_b/dpo_v9/checkpoint-10",
    "grpo_v10_c50": P / "checkpoints/stage_c/grpo_v10/snapshots/step_50",
    "grpo_v10b_c10": P / "checkpoints/stage_c/grpo_v10b/snapshots/step_10",
    "sft_small": P / "checkpoints/stage_a/sft_small/adapter",
    "dpo_small_c12": P / "checkpoints/stage_b/dpo_small/checkpoint-12",
    "grpo_small_c10": P / "checkpoints/stage_c/grpo_small/snapshots/step_10",
    "sft_extA": P / "checkpoints/stage_a/sft_extA/adapter",
}
HOSTED = {  # model -> (provider key name, base url, request style, reasoning effort)
    "claude-sonnet-5-5": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "anthropic_native", ""),
    "claude-opus-5-5": ("ANTHROPIC_API_KEY", "https://api.anthropic.com/v1", "anthropic_native", ""),
    "gpt-5.6-luna": ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt5", "none"),
    "gemini-3.8-flash": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai", "", ""),
    "deepseek-v4-pro": ("DEEPSEEK_API_KEY", "https://api.deepseek.com/v1", "", ""),
}
SERVER = {
    "9b_canonical": "Qwen3.5-9B base + runtime LoRA, canonical template code/stage_a/chat_template_veribim.jinja, max-model-len 32768 (code/stage_c/scripts_serve.sh)",
    "9b_owntemplate": "Qwen3.5-9B base alone, model's own chat_template.jinja, max-model-len 65536 (flags of analysis/revision/base_documented/serve_base.sh)",
    "gemma": "Gemma 4 31B AWQ (flags of analysis/revision/gemma31b/serve_gemma.sh), max-model-len 65536",
    "hosted": "provider API",
    "composite": "none (rows taken from the source arms' re-runs)",
}
EXCLUDE_ROWS = {  # (run, model, task): reason, applied on top of the v2 criterion
}


def md5(p):
    return hashlib.md5(open(p, "rb").read()).hexdigest()


def spec(run, model):
    """Arm environment and launcher as the original read set them. Evidence in rerun_delete_arms.md."""
    s = dict(run=run, model=model, adapter=model, adapter_path="", note="", no_geom=False, style="", effort="",
             base_url="http://127.0.0.1:8000/v1", key="", conc=16, sw=2, entry="stage_a.run_gate", solo=False,
             orig_guard=True, sampling="none", template_kwargs="none", sources=[])
    if run == "full_all":
        s.update(group="9b_canonical", adapter_path=str(ADAPTER[model]), arm="lib",
                 launcher="runs_local/bench_v4/eval_bench_v4.sh (PART=all, no LOCAL_NOTE), called by bench_v4/chain_after_post_v10.sh, "
                          "final_queue.sh or small_v10/reads_small.sh (small models)",
                 orig_guard=model not in ("dpo_v10_c3", "dpo_v9_c10", "sft_v10"))
    elif run == "local108_lib_all":
        s.update(group="9b_canonical", adapter_path=str(ADAPTER[model]), arm="lib",
                 launcher="runs_local/bench_v4/run_local_subset108.sh <name> <adapter> lib")
    elif run == "local324_lib_all":
        s.update(group="9b_canonical", adapter_path=str(ADAPTER[model]), arm="lib",
                 launcher="runs_local/bench_v4/run_local_subset324.sh <name> <adapter> lib"
                          + (" (from extA/morning_1004.sh)" if model == "sft_extA" else ""))
    elif run == "local108_libnote_all":
        s.update(group="9b_canonical", adapter_path="", arm="libnote", note=str(NOTE_FRONTIER),
                 launcher="runs_local/bench_v4/run_local_subset108.sh Qwen3.5-9B '' libnote (2026-10-02, Stage C server)")
    elif run == "local108_lib_solo":
        s.update(group="9b_canonical", adapter_path=str(ADAPTER[model]), arm="lib, one task at a time", conc=1, solo=True,
                 launcher={"grpo_v10_c50": "runs_local/stage_c_v10/solo_rerun_clean.sh (concurrency 1, exclusive cores 16-19)",
                           "grpo_v10b_c10": "runs_local/stage_c_v10/final_latency_flip.sh step 1 (concurrency 1, cores 12-15)"}[model])
    elif run == "local108_informed_all" and model == "Qwen3.5-9B":
        s.update(group="9b_owntemplate", arm="informed", note=str(NOTE_INFORMED),
                 launcher="analysis/revision/base_documented/after_server.sh -> run_local108_informed.sh Qwen3.5-9B '' informed (server serve_base.sh)")
    elif run in ("local108_retrieval_all", "local108_retrievalshort_all"):
        short = run == "local108_retrievalshort_all"
        s.update(group="9b_owntemplate", arm="retrievalshort" if short else "retrieval",
                 note=str(NOTES_RETR_SHORT if short else NOTES_RETR),
                 entry=str(R15 / "retrieval_fewshot/run_gate_pertask.py"),
                 launcher="analysis/revision/retrieval_fewshot/run_both.sh -> launch_retrieval.sh ARM=%s (server serve_base.sh)"
                          % ("retrievalshort" if short else "retrieval"))
    elif run == "local108_informed_all" and model == "gemma-4-31b-it-awq":
        s.update(group="gemma", arm="informed", note=str(NOTE_INFORMED), conc=4,
                 launcher="analysis/revision/gemma31b/restart_gemma.sh -> run_gemma108.sh gemma-4-31b-it-awq '' informed (CONC 4, SW 1), server serve_gemma.sh")
    elif run.startswith("hosted"):
        key, url, style, effort = HOSTED[model]
        s.update(group="hosted", key=key, base_url=url, style=style, effort=effort, conc=4, adapter=model)
        if run == "hosted108_informed_all":
            s.update(arm="informed", note=str(NOTE_INFORMED), orig_guard=model != "claude-sonnet-5-5",
                     launcher="analysis/revision/informed/eval_informed.sh SUBSET=hosted ARM=informed HOSTED=anthropic"
                     if model == "claude-sonnet-5-5" else
                     "analysis/revision/documented/eval_informed4.sh SUBSET=hosted ARM=informed HOSTED=%s%s"
                     % (key.split("_")[0].lower(), " VERIBIM_REASONING_EFFORT=none (reasoning off; its endpoint refuses function tools otherwise)" if effort else ""))
        elif run in ("hosted108_informed_rep2_all", "hosted108_informed_rep3_all"):
            s.update(arm="informed", note=str(NOTE_INFORMED),
                     launcher="analysis/revision/commercial_reruns/run_all.sh -> eval_rerun.sh SUBSET=hosted ARM=informed RUNTAG=%s HOSTED=anthropic CONC=4 SW=2"
                     % run.split("_")[2])
        elif run == "hosted108_lib_all":
            crash = model == "deepseek-v4-pro"
            s.update(arm="lib", note=str(NOTE_FRONTIER), orig_guard=crash,
                     launcher=("runs_local/bench_v4/reread_crashed.sh hosted108 lib deepseek deepseek-v4-pro (the listed row comes from "
                               "results/hosted108_lib_all_crashreread; the arm itself from run_hosted_arms.sh)") if crash else
                     "runs_local/bench_v4/run_hosted_arms.sh -> eval_bench_v4.sh SUBSET=hosted ARM=lib HOSTED=%s CONC=4 SW=2"
                     % key.split("_")[0].lower())
        elif run == "hosted108_asknote_all":
            s.update(arm="asknote", note=str(NOTE_LIBFIX),
                     launcher="analysis/revision/commercial_reruns/run_all.sh -> eval_rerun.sh SUBSET=hosted ARM=asknote HOSTED=%s CONC=4 SW=2%s"
                     % (key.split("_")[0].lower(), " VERIBIM_REASONING_EFFORT=none" if effort else ""))
        elif run == "hosted216_lib_all":
            s.update(arm="lib", note=str(NOTE_FRONTIER),
                     launcher="runs_local/bench_v4/run_hosted_extension.sh lib anthropic claude-sonnet-5-5 (CONC 4, SW 2)")
        elif run == "hosted324rest_informed_all":
            s.update(arm="informed", note=str(NOTE_INFORMED),
                     launcher="analysis/revision/equivalence/eval_informed216.sh SUBSET=rest216 ARM=informed HOSTED=anthropic")
        elif run == "hosted324_lib_all":
            s.update(group="composite", arm="lib (composite)", note=str(NOTE_FRONTIER),
                     launcher="assembled by runs_local/bench_v4/run_hosted_extension.sh / reassemble_324.sh from hosted108_lib_all + hosted216_lib_all")
        else:
            raise SystemExit(f"no spec for {run}/{model}")
    else:
        raise SystemExit(f"no spec for {run}/{model}")
    return s


def main():
    rows = list(csv.DictReader(open(G / "rerun_list_delete_v2.csv")))
    gold_bytes, ids_v4d = {}, set()
    for l in open(B / "tasks.v4d.jsonl"):
        r = json.loads(l)
        v = r["verification"]
        v = ast.literal_eval(v) if isinstance(v, str) else v
        gold_bytes[r["task_id"]] = int(v.get("gold_bytes") or 0)
        ids_v4d.add(r["task_id"])
    jobs, left_out = defaultdict(list), []
    for r in rows:
        if r["geom_call_ran_clean"] != "1":
            left_out.append(dict(run=r["run"], model=r["model"], task=r["task"],
                                 reason="the only clean call named delete_element was ifcopenshell.util.element.delete_element, "
                                        "not the library helper (geom.*); no library deletion ran"))
            continue
        jobs[(r["run"], r["model"])].append(r["task"])
    plan = []
    for (run, model), tasks in sorted(jobs.items()):
        tasks = sorted(tasks)
        assert all(t in ids_v4d for t in tasks)
        s = spec(run, model)
        s["tasks"] = tasks
        s["n"] = len(tasks)
        s["est_edited_bytes"] = sum(gold_bytes[t] for t in tasks)
        # the arm's original summary, whose resolved_agent_config the re-run must reproduce
        cand = [RES / run / f"summary_{model}.json.pre_v4d", RES / run / f"summary_{model}.json"]
        s["orig_summary"] = next((str(c) for c in cand if c.is_file()), "")
        if s["note"]:
            n = Path(s["note"])
            if n.is_dir():
                man, pref = MANIFEST[n]
                s["note_check"] = f"manifest:{man}:{pref}"
            else:
                assert md5(n) == NOTE_MD5[n], (n, md5(n))
                s["note_check"] = f"md5:{NOTE_MD5[n]}"
        else:
            s["note_check"] = "-"
        if s["adapter_path"]:
            assert (Path(s["adapter_path"]) / "adapter_model.safetensors").is_file(), s["adapter_path"]
        if s["group"] == "composite":
            # which source arm holds each listed row (the composite's rows point at the source arms' files)
            src = {}
            for l in open(RES / run / f"per_task_{model}.jsonl"):
                x = json.loads(l)
                if x["task_id"] in tasks:
                    src[x["task_id"]] = x["edited_ifc"].split("/results/")[1].split("/")[0]
            s["sources"] = sorted({(v, t) for t, v in src.items()})
            s["sources"] = [{"run": v, "task": t} for v, t in s["sources"]]
            s["subset"] = ""
        else:
            sub = D / f"subset_{run}_{model}.json"
            sub.write_text(json.dumps(tasks, indent=1) + "\n")
            s["subset"] = str(sub)
            s["subset_md5"] = md5(sub)
        plan.append(s)
    # every composite row must be a re-run row of its source arm
    have = {(s["run"], s["model"]): set(s["tasks"]) for s in plan}
    for s in plan:
        for src in s["sources"]:
            assert src["task"] in have.get((src["run"], s["model"]), set()), (s["run"], src)
    (D / "plan.json").write_text(json.dumps({"built_from": str(G / "rerun_list_delete_v2.csv"),
                                             "tasks_file": str(B / "tasks.v4d.jsonl"),
                                             "tasks_file_md5": md5(B / "tasks.v4d.jsonl"),
                                             # the repaired libraries (identical to gt_fix/patched_code/); every job asserts them
                                             "geom_lib": str(P / "code/harness/modifc_harness/veribim_geom.py"),
                                             "geom_lib_md5": md5(G / "patched_code/harness/modifc_harness/veribim_geom.py"),
                                             "goldlib": str(P / "code/modifc_gen/goldlib.py"),
                                             "goldlib_md5": md5(G / "patched_code/modifc_gen/goldlib.py"),
                                             "left_out": left_out, "jobs": plan}, indent=1) + "\n")
    write_table(plan, left_out)
    print(f"{len(plan)} jobs, {sum(s['n'] for s in plan)} rows "
          f"({sum(s['n'] for s in plan if s['group'] != 'composite')} to run), {len(left_out)} row(s) left out")


def write_table(plan, left_out):
    L = []
    L.append("# Deletion re-run (v4e): arms, servers and environments\n")
    L.append("Built by `delete_rerun/make_plan.py` from `rerun_list_delete_v2.csv` (deletion helper ran without a traceback). "
             "Every job below is run on `runs_local/bench_v4/tasks.v4d.jsonl` with the original protocol "
             "(22 rounds, 420 s, 8192 tokens, temperature 0, top_p 1, family reading), sandbox guard and Landlock on, "
             "VERIBIM_LOCAL_TEMPERATURE/TOP_P/TOP_K/PRESENCE_PENALTY/SEED, VERIBIM_CHAT_TEMPLATE_KWARGS and "
             "VERIBIM_ANTHROPIC_THINKING unset (no original read in scope set them), VERIBIM_NO_GEOM unset (every arm in scope has the library). "
             "Note md5 values were checked against the current files (unchanged since the runs).\n")
    L.append("Servers: " + "; ".join(f"**{k}** = {v}" for k, v in SERVER.items()) + ".\n")
    L.append("| Arm (run) | Model | Rows | Server | Adapter (served name = path) | Note file (check) | Request style / effort / base URL | Conc / SW | Original guard | Subset file | Original launcher |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for s in plan:
        ad = "-" if s["group"] in ("hosted", "composite", "gemma") else (
            f"{s['adapter']} = {s['adapter_path'].replace('', '')}" if s["adapter_path"] else "none (base, served as Qwen3.5-9B)")
        note = s["note"].replace("./", "") if s["note"] else "none"
        chk = s["note_check"].replace("./", "")
        if chk.startswith("md5:"):
            chk = chk[:12] + "…"
        st = (f"{s['style'] or 'unset'} / {s['effort'] or 'unset'} / {s['base_url']}") if s["group"] in ("hosted", "composite") else "unset / unset / 127.0.0.1:8000"
        cs = "-" if s["group"] == "composite" else f"{s['conc']} / {s['sw']}"
        sub = "-" if not s["subset"] else os.path.basename(s["subset"])
        if s["group"] == "composite":
            srcs = ", ".join(sorted({x["run"] for x in s["sources"]}))
            sub = f"none (rows from {srcs})"
        L.append(f"| {s['run']} | {s['model']} | {s['n']} | {s['group']} | {ad} | {note} ({chk}) | {st} | {cs} | "
                 f"{'yes' if s['orig_guard'] else 'no'} | {sub} | {s['launcher']} |")
    L.append("")
    L.append("Left out of the scripts:\n")
    L.append("* `local108_lib_solo_cpu_contended_20261002/grpo_v10_c50` (3 rows under either criterion): excluded as a contended timing read that stays as recorded. Its rows' edited_ifc paths point into `local108_lib_solo/grpo_v10_c50/` (the folder it was renamed from), so the helper search read local108_lib_solo's transcripts for it.")
    for x in left_out:
        L.append(f"* `{x['run']}/{x['model']}` task {x['task']}: {x['reason']}. This arm then has no row left to re-run.")
    L.append("* Arms with rows in the in_code list but none in v2 (every deletion call failed): local108_alone_all/sft_v10 (3), local324_alone_all/sft_v10 (8), hosted108_lib_all/gpt-5.6-luna (1). The alone arms have VERIBIM_NO_GEOM=1, so `geom` was never importable.")
    L.append("* Arms in this analysis's scope with no listed row at all: hosted108_alone_all, hosted216_alone_all, hosted324_alone_all, local108_alone_sampled_all, local108_alone_thinking_all, local108_alone_all/Qwen3.5-9B.")
    L.append("")
    L.append("Evidence for the environments:\n")
    L.append("* Server template and context per arm: vLLM `non-default args` lines in phase2/logs/stage_c_serve.log (09-29 start), runs_local/stage_c_v10/logs/stage_c_serve_*.log (10-01, 10-02), small_v10/logs/serve_*.log, extA/logs/serve_*.log (all chat_template_veribim.jinja, 32768), analysis/revision/base_documented/serve.log and retrieval_fewshot/serve.log (model chat_template.jinja, 65536), gemma31b/serve.log. The two Qwen templates differ in one line (`<think>\\n` vs `<think>\\n\\n` in the generation prompt), so the base-model arms run on the server they had.")
    L.append("* Request style: Claude rows carry cache_read_tokens (native Messages transport) in every Claude arm; GPT effort none from run_all.sh (asknote) and the documented-arm launcher (informed); Gemini and DeepSeek unset in every launcher.")
    L.append("* Guard: rows carry `sandbox_blocked` only when VERIBIM_SANDBOX_GUARD=1. The originals without it are marked 'no' above; the re-runs set it for every arm (run rules), which changes only what a tool call may read outside its working copy.")
    L.append("* resolved_agent_config of every original summary equals the standard protocol; each job asserts the re-run's equals the arm's (`orig_summary` in plan.json).")
    (G / "rerun_delete_arms.md").write_text("\n".join(L) + "\n")


if __name__ == "__main__":
    main()
