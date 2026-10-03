"""Command line entry points for the Stage A pipeline.

Four subcommands, in the order they run. The first two open IFC models and
belong in the ``l2`` environment; the last two load the tokenizer and the
training stack and belong in ``l2train``.

``synthesize``  gold-backed trajectories from a task file
``harvest``     rejection-sampled trajectories out of a sampling run directory
``assemble``    the chat-format training set, its mix and its truncation rate
``train``       the SFT run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import paths
from .sample import breadth_first_order, chunked_building_order, parse_cores


def cmd_synthesize(args: argparse.Namespace) -> int:
    # The emit mode is read when the synthesizer module loads, so it is set
    # before the pipeline pulls that module in.
    import os

    os.environ["VERIBIM_STAGE_A_GEOM"] = "0" if args.no_geom_lib else "1"
    from .pipeline import load_tasks, stratified_sample, synthesize_set

    tasks = load_tasks(Path(args.tasks_file))
    if args.split:
        tasks = [t for t in tasks if t.get("split", args.split) == args.split]
    if args.operations:
        wanted_ops = set(args.operations)
        tasks = [t for t in tasks if t["operation"] in wanted_ops]
    if args.task_ids:
        wanted = set(args.task_ids)
        tasks = [t for t in tasks if t["task_id"] in wanted]
    elif args.limit:
        tasks = stratified_sample(tasks, args.limit)
    if args.order == "chunked":
        tasks = chunked_building_order(tasks, chunk=args.chunk)
    elif args.order == "breadth":
        # The task file is written shard by shard, so its natural order is one
        # building and one edit kind at a time: the first 1,625 trajectories of
        # this run were 1,620 compositional wall-and-door creations. A pass that
        # completes covers everything either way, but a pass that is interrupted
        # should leave a usable set rather than a skewed one, so the queue is
        # walked breadth first over building, edit kind and category.
        tasks = breadth_first_order(tasks)
    print(f"synthesizing {len(tasks)} trajectories with {args.workers} workers",
          flush=True)
    funnel = synthesize_set(
        tasks=tasks,
        out_dir=Path(args.out_dir),
        scratch=Path(args.scratch),
        project_root=paths.PROJECT_ROOT,
        workers=args.workers,
        floor=args.floor,
        require_axes=not args.final_score_only,
        threads_per_worker=args.threads_per_worker,
        resume=not args.no_resume,
        gold_cache_root=args.gold_cache or str(Path(args.scratch) / "_gold"),
        cores=parse_cores(args.cores) if args.cores else (),
        recycle_after=args.recycle_after,
        report_every=args.report_every,
        chunk_size=args.chunk,
        large_permits=args.large_permits,
        name_index_root=("" if args.no_name_index
                         else (args.name_index
                               or str(Path(args.out_dir) / "name_index"))),
    )
    print(json.dumps(funnel, indent=2))
    return 0


def cmd_harvest(args: argparse.Namespace) -> int:
    from .collect import harvest_run

    report = harvest_run(
        run_dir=Path(args.run_dir),
        tasks_file=Path(args.tasks_file),
        out_dir=Path(args.out_dir),
        project_root=paths.PROJECT_ROOT,
        floor=args.floor,
        require_axes=not args.final_score_only,
        cap_per_task=args.cap_per_task,
        workers=args.workers,
        gold_cache_root=args.gold_cache,
        cores=parse_cores(args.cores) if args.cores else (),
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_assemble(args: argparse.Namespace) -> int:
    from .assemble import assemble

    report = assemble(
        sources=[Path(p) for p in args.trajectories],
        out_dir=Path(args.out_dir),
        model_dir=Path(args.model_dir),
        max_seq=args.max_seq,
        val_fraction=args.val_fraction,
        seed=args.seed,
        emit_token_ids=args.emit_token_ids,
        require_observed=not args.allow_unobserved,
        out_name=args.out_name,
    )
    print(json.dumps(report, indent=2))
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    from .train_sft import main as train_main

    return train_main(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="stage-a")
    sub = parser.add_subparsers(dest="command", required=True)

    p_syn = sub.add_parser("synthesize", help="gold-backed trajectories")
    p_syn.add_argument("--tasks-file", default=str(paths.default_tasks_file()))
    p_syn.add_argument("--task-ids", nargs="*", default=[])
    p_syn.add_argument("--limit", type=int, default=0,
                       help="stratified sample of this many tasks")
    p_syn.add_argument("--out-dir", default=str(paths.STAGE_A_DATA / "dev"))
    p_syn.add_argument("--scratch", default=str(paths.STAGE_A_DATA / "_work"),
                       help="where a trajectory's working copy of the model lives;"
                            " the path is shown to the model, as the harness shows it")
    p_syn.add_argument("--workers", type=int, default=6)
    p_syn.add_argument("--threads-per-worker", type=int, default=1)
    p_syn.add_argument("--floor", type=float, default=0.98)
    p_syn.add_argument("--no-geom-lib", action="store_true",
                       help="write a create edit as a hand-written helper block"
                            " instead of calls into the sandbox's geom library")
    p_syn.add_argument("--final-score-only", action="store_true",
                       help="hold only the final score to the floor, not every axis")
    p_syn.add_argument("--split", default="",
                       help="restrict to one split of the task file")
    p_syn.add_argument("--operations", nargs="*", default=[])
    p_syn.add_argument("--no-resume", action="store_true")
    p_syn.add_argument("--cores", default="",
                       help="pin the workers, e.g. 0-9")
    p_syn.add_argument("--gold-cache", default="",
                       help="directory the rebuilt gold models are cached in")
    p_syn.add_argument("--order", choices=("chunked", "breadth", "file"),
                       default="chunked",
                       help="chunked: round robin over buildings a chunk at a"
                            " time, which keeps an interrupted run balanced"
                            " without losing source-model locality")
    p_syn.add_argument("--chunk", type=int, default=64,
                       help="tasks taken from one building per visit")
    p_syn.add_argument("--large-permits", type=int, default=3,
                       help="workers allowed inside a large building at once")
    p_syn.add_argument("--report-every", type=int, default=200,
                       help="rewrite the funnel and flush the outcomes after"
                            " this many attempts; a short run wants a small"
                            " number, or its counts sit in the buffer")
    p_syn.add_argument("--name-index", default="",
                       help="directory the per-model name indexes live in;"
                            " defaults to name_index under the output directory."
                            " It is what lets a trajectory find an element by"
                            " the name the instruction quotes rather than"
                            " writing its identifier as a literal")
    p_syn.add_argument("--no-name-index", action="store_true",
                       help="plan without name lookups, as before the lookups"
                            " existed; the observed-identifier check then"
                            " refuses most spatial and topological tasks")
    p_syn.add_argument("--recycle-after", type=int, default=50,
                       help="replace a worker after this many tasks, so the"
                            " memory a large building took is given back")
    p_syn.set_defaults(func=cmd_synthesize)

    p_har = sub.add_parser("harvest", help="filter a sampling run into trajectories")
    p_har.add_argument("--run-dir", required=True)
    p_har.add_argument("--tasks-file", default=str(paths.default_tasks_file()))
    p_har.add_argument("--out-dir", default=str(paths.STAGE_A_DATA / "dev"))
    p_har.add_argument("--floor", type=float, default=0.98)
    p_har.add_argument("--final-score-only", action="store_true")
    p_har.add_argument("--cap-per-task", type=int, default=2)
    p_har.add_argument("--workers", type=int, default=6)
    p_har.add_argument("--cores", default="", help="pin the workers, e.g. 0-9")
    p_har.add_argument("--gold-cache", default="",
                       help="directory the rebuilt gold models are cached in")
    p_har.set_defaults(func=cmd_harvest)

    p_asm = sub.add_parser("assemble", help="build the training set")
    p_asm.add_argument("--trajectories", nargs="+", required=True)
    p_asm.add_argument("--out-dir", default=str(paths.STAGE_A_DATA / "dev"))
    p_asm.add_argument("--model-dir", default=str(paths.BASE_MODEL_DIR))
    p_asm.add_argument("--max-seq", type=int, default=8192)
    p_asm.add_argument("--val-fraction", type=float, default=0.0)
    p_asm.add_argument("--seed", type=int, default=20260824)
    p_asm.add_argument("--emit-token-ids", action="store_true")
    p_asm.add_argument("--out-name", default="sft_train",
                       help="stem of the written file, so a replay set and a"
                            " training set can be assembled into one directory")
    p_asm.add_argument("--allow-unobserved", action="store_true",
                       help="keep trajectories that use an identifier no"
                            " earlier round printed and the instruction does"
                            " not carry; on by default such a trajectory is"
                            " dropped and counted in the report")
    p_asm.set_defaults(func=cmd_assemble)

    p_tr = sub.add_parser("train", help="run the SFT job")
    from .train_args import add_train_arguments

    add_train_arguments(p_tr)
    p_tr.set_defaults(func=cmd_train)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
