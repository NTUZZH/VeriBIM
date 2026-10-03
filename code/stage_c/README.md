# Stage C: GRPO against the verifier

The policy rolls out the evaluation protocol, the verifier scores the file each
trajectory leaves, and the score becomes the reward. This file documents the
reward's composition and the flags that change it.

## The reward

    r = (final - null_edit) / (1 - null_edit),  clipped to [-0.2, 1]

`final` is the verifier's score for the file on disk and `null_edit` is what
the same task pays for doing nothing, measured by the generator and stored on
the record. Doing nothing earns exactly zero, and a file the scorer
cannot read earns -0.2. Deletions are read under `delete_semantics="removal"`.
The reward's weights are the training reading and the evaluation reading is the
published one; the two are deliberately different and the separation is a
claim of the paper, so nothing below may be turned on for an evaluation run.

Each task is scored under the settings its own families need, through
`stage_a.scoring.scorer_config_for`. A material association and a type
assignment leave no trace the published reading can see, and an under-specified
instruction is answered by changing nothing and asking for the missing value,
which the published reading would score as a perfect answer for any system that
changed nothing at all. Every task outside those three families resolves to the
same configuration the operation alone resolved to, so its reward is unchanged.
An under-specified task is also read against the policy's last message, which
travels from the rollout to the scorer as the job's `reply` field.

## The flags

All three deductions are off by default, and every one of them is recorded in
`resolved_config.json` under `reward`, in the `shaping` sentence and as its own
key, alongside the `cli_args` copy of the flag.

| Flag | Default | What it does |
| --- | --- | --- |
| `--error-penalty` | `0.0` | Deducts this much per tool call that came back as a traceback. The launch value was `0.02`. |
| `--error-penalty-cap` | `0.10` | The most one trajectory can lose to the per-error deduction. |
| `--repeat-penalty` | `0.0` | Deducts this much each time a tool call resends code that already raised earlier in the same trajectory. The designed value is `0.05`. |
| `--repeat-penalty-cap` | `0.25` | The most one trajectory can lose to the repeat deduction. |
| `--commit-required` | `off` | `create` scores a create trajectory that never called `commit()` at zero; `all` does the same for every operation; `off` leaves the verdict to the file. |

The three compose in that order: the per-error deduction, then the repeat
deduction, then the commit gate, which replaces the value rather than reducing
it. The verifier's own number survives on every rollout as `reward_raw`, and the
group skip rule reads that number and not the shaped one, so a group the
verifier scored flat at or below the no-op level stays skipped.

### Why the repeat deduction

On the external benchmark the trained policy resent the same failing snippet
three or more times in 130 of 324 tasks and ran to the round budget without
committing, scoring 0.26 on those tasks against 0.435 on the rest. The
trainer used a repeat stop and the evaluation harness does not, so the policy
never had to learn to recover from a repeated failure at evaluation length. The
deduction puts that cost inside the reward, where the evaluation protocol stays
untouched.

Two calls are the same attempt when their code matches after blank lines and
trailing spaces are removed and runs of spaces or tabs inside a line are
collapsed to one. Indentation is kept and compared, because Python reads it: a
policy that re-indented after an IndentationError changed its approach. A repeat
counts whatever the repeat itself returns, and a repeat of a call that succeeded
is never counted. Every rollout logs `repeat_failures` and `repeated_codes` to
`rollouts.jsonl` whether or not the deduction is on, and each group record
carries their sums.

### Why the commit gate

An uncommitted create leaves the input untouched, which the verifier already
scores at the no-op floor. The gate states the rule instead of relying on the
file, and it is logged as `commit_gated` per rollout and counted per group. A
trajectory whose file could not be read is left alone: it never committed
either, and zeroing it would lift a crashed rollout off the -0.2 floor and rank
it above one that made the model worse.

## Tests

    PYTHONPATH=code l2/bin/python      -m stage_c.tests.test_reward_v4
    PYTHONPATH=code l2train/bin/python -m stage_c.tests.test_train_grpo_v4
    PYTHONPATH=code l2train/bin/python -m stage_c.tests.test_rollout_v3
    PYTHONPATH=code l2train/bin/python -m stage_c.tests.test_train_grpo_v3

`test_reward_v4` needs the scorer's environment (`l2`) and the two trainer
suites need torch (`l2train`). Its first test holds the reward of twelve
synthetic trajectories, with every flag off, against the numbers the
implementation produced before the flags existed.
