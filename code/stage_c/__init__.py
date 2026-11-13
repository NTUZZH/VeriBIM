"""Stage C: GRPO against the verifier.

The thesis of the stage is that the deterministic verifier is the training
signal, so the reward module is deliberately thin: the score the benchmark would
give, normalised by what doing nothing already earns on that task, and one
shaped penalty for a file that cannot be read back. Everything else is the
verifier's own scale.
"""

from .version import STAGE_C_VERSION

__all__ = ["STAGE_C_VERSION"]
