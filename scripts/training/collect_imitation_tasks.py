"""Collect the task records behind the imitation stage's reference trajectories.

    python collect_imitation_tasks.py <output dir>        (run from the project root)

Reads (paths relative to the project root):
  runs_local/stage_b_v10/tasks_stage_b_v10.jsonl    the training task file (51,956 tasks)
  runs_local/stage_a_v10/sft_train.jsonl.gz          the rows the imitation stage trained on (task id and source per row)
  runs_local/wave_v2/wave_all_accepted.jsonl         the accepted tasks of the second task wave
  runs_local/stage_a_v8_dev/tasks_v8_all.jsonl       tasks regenerated for the v8 imitation set
  runs_local/stage_a_v8_dev/tasks_to_add_v8b.jsonl   tasks added to the v8 imitation set

Writes into <output dir>:
  imitation_task_ids.json             every task id with a reference trajectory in the imitation rows, sorted
  tasks_imitation_earlier.jsonl       the records of those tasks that the training task file does not hold,
                                      copied unchanged from the earlier task files, in the order of those files
  imitation_tasks_report.json         counts per source file and the checks below

Checks: every imitation task id is found in exactly one place (the training task file or one earlier file, in the
order listed above, first match wins), and no earlier record repeats a task id.
"""
import collections
import gzip
import json
import os
import sys

TRAIN = "runs_local/stage_b_v10/tasks_stage_b_v10.jsonl"
ROWS = "runs_local/stage_a_v10/sft_train.jsonl.gz"
EARLIER = ["runs_local/wave_v2/wave_all_accepted.jsonl",
           "runs_local/stage_a_v8_dev/tasks_v8_all.jsonl",
           "runs_local/stage_a_v8_dev/tasks_to_add_v8b.jsonl"]


def task_id(line):
    i = line.find('"task_id": "')
    return line[i + 12:line.index('"', i + 12)]


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    train_ids = {task_id(l) for l in open(TRAIN, encoding="utf-8")}
    rows_by_source, ids = collections.Counter(), set()
    with gzip.open(ROWS, "rt", encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            rows_by_source[r["source"]] += 1
            ids.add(r["task_id"])
    outside = ids - train_ids
    found, per_file = {}, collections.Counter()
    with open(os.path.join(out, "tasks_imitation_earlier.jsonl"), "w", encoding="utf-8") as dst:
        for path in EARLIER:
            for line in open(path, encoding="utf-8"):
                t = task_id(line)
                if t in outside and t not in found:
                    found[t] = path
                    per_file[path] += 1
                    dst.write(line if line.endswith("\n") else line + "\n")
    missing = sorted(outside - set(found))
    assert not missing, f"{len(missing)} imitation tasks found in no task file, e.g. {missing[:5]}"
    json.dump(sorted(ids), open(os.path.join(out, "imitation_task_ids.json"), "w"), indent=0)
    report = {"imitation_rows": sum(rows_by_source.values()), "imitation_rows_by_source": dict(rows_by_source),
              "imitation_tasks": len(ids), "training_task_file_tasks": len(train_ids),
              "imitation_tasks_in_training_task_file": len(ids & train_ids),
              "imitation_tasks_outside_training_task_file": len(outside),
              "outside_tasks_by_source_file": dict(per_file)}
    json.dump(report, open(os.path.join(out, "imitation_tasks_report.json"), "w"), indent=1)
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
