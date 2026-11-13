"""Stage B: preference data and DPO training for VeriBIM.

Stage A taught the protocol; the gate showed what it did not teach. Under the
canonical template `sft590` completes 94 of 100 validation tasks and commits on
94, but 29.5% of its tool calls still raise, and two causes account for 85% of
that: identifiers it invented rather than read, and IFC classes from the wrong
schema version. Stage B aims the gradient at those two.

The pieces, in the order data flows through them:

``pool``      the sampling subset: seeded, stratified, weighted toward the
              operations Stage A scores lowest
``sample``    on-policy rollouts of sft590 behind its own template, every
              trajectory scored and kept
``pairs``     preference pairs, from whole trajectories and from single repaired
              turns at the exact site of a failure
``train_dpo`` the trainer, with the DPO logprob restricted to assistant tokens
"""

from .version import STAGE_B_VERSION

__all__ = ["STAGE_B_VERSION"]
