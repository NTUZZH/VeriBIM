"""Render a trajectory for a human to read.

Inspection packs and reports need the whole conversation, not a summary, and
they need it in the form the model will see: the turn boundaries, the code, and
the tool output as it came back from the sandbox.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional, Sequence


def render_trajectory(record: dict, max_output_chars: int = 1200,
                      include_system: bool = False) -> str:
    """One trajectory as Markdown."""
    lines: list[str] = []
    score = record.get("score") or {}
    lines.append(f"**{record['task_id']}** ({record['operation']} / "
                 f"{record['category']}, edit kind `{record.get('edit_kind', '')}`, "
                 f"source `{record.get('source', '')}`) "
                 f"final score {score.get('final')}, "
                 f"{record.get('tool_rounds')} tool rounds, "
                 f"{record.get('commits', 0)} commit")
    lines.append("")
    for index, message in enumerate(record["messages"]):
        role = message.get("role")
        if role == "system":
            if not include_system:
                continue
            lines.append("### system")
            lines.append("")
            lines.append("```")
            lines.append(message["content"])
            lines.append("```")
        elif role == "user":
            lines.append("### user")
            lines.append("")
            lines.append("```")
            lines.append(message["content"])
            lines.append("```")
        elif role == "assistant":
            lines.append(f"### assistant (turn {index}, loss on)")
            lines.append("")
            if message.get("content"):
                lines.append(message["content"])
                lines.append("")
            for call in message.get("tool_calls") or []:
                arguments = call["function"]["arguments"]
                code = arguments.get("code") if isinstance(arguments, dict) else arguments
                lines.append(f"`{call['function']['name']}`:")
                lines.append("")
                lines.append("```python")
                lines.append(str(code).rstrip())
                lines.append("```")
                lines.append("")
        elif role == "tool":
            content = message.get("content") or ""
            clipped = content
            if len(content) > max_output_chars:
                clipped = (content[: max_output_chars // 2] +
                           f"\n... [{len(content) - max_output_chars} characters omitted] ...\n" +
                           content[-max_output_chars // 2:])
            lines.append("### tool result (masked)")
            lines.append("")
            lines.append("```")
            lines.append(clipped.rstrip())
            lines.append("```")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def load(path: Path) -> list[dict]:
    records = []
    with Path(path).open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def pick(records: Sequence[dict], operation: str, category: str,
         edit_kind: str = "") -> Optional[dict]:
    for record in records:
        if record["operation"] != operation or record["category"] != category:
            continue
        if edit_kind and record.get("edit_kind") != edit_kind:
            continue
        return record
    return None


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="stage-a-render")
    parser.add_argument("--trajectories", required=True)
    parser.add_argument("--task-ids", nargs="*", default=[])
    parser.add_argument("--select", nargs="*", default=[],
                        help="operation/category[/edit_kind] triples")
    parser.add_argument("--max-output-chars", type=int, default=1200)
    parser.add_argument("--include-system", action="store_true")
    args = parser.parse_args(argv)

    records = load(Path(args.trajectories))
    chosen: list[dict] = []
    for task_id in args.task_ids:
        chosen.extend(r for r in records if r["task_id"] == task_id)
    for spec in args.select:
        parts = spec.split("/")
        record = pick(records, parts[0], parts[1],
                      parts[2] if len(parts) > 2 else "")
        if record is not None:
            chosen.append(record)
    for record in chosen:
        print(render_trajectory(record, args.max_output_chars, args.include_system))
        print("\n---\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
