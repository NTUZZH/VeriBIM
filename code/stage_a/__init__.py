"""Stage A: supervised fine-tuning data and training for VeriBIM.

The package turns generated editing tasks into full harness trajectories, filters
them with the verifier, assembles them into a chat-format training set with loss
on assistant tokens only, and trains the LoRA adapter.

Four pieces, in the order data flows through them:

``synthesize``  gold-backed trajectories: inspection rounds derived from a task's
                anchor metadata, the edit as one tool call, a commit round and a
                closing message. Every round is really executed in the harness
                sandbox and the finished file is scored before the trajectory is
                kept.
``collect``     rejection-sampled trajectories: k samples per task from the
                pinned base, kept when the finished file scores above the same
                floor, de-duplicated and capped per task.
``assemble``    the training set: chat-format records with a per-message loss
                flag, mix accounting and a truncation measurement at the
                training sequence length.
``train_sft``   the trainer.

Environments: everything that opens an IFC model runs in ``l2``; the assembler
and the trainer run in ``l2train``. ``paths`` names both interpreters so a step
can start the other environment's subprocess when it needs one.
"""

from .version import STAGE_A_VERSION

__all__ = ["STAGE_A_VERSION"]
