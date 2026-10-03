"""ModIFC-Gen: an inverse generator of verified IFC editing tasks.

A task is generated answer-first.  A source model is sampled from the corpus, a
parameterised edit is drawn from the operation library, the edit is written out
as a gold Python script, and the script is executed to produce the gold model.
The instruction is rendered from the same edit parameters, so instruction, gold
model and gold script agree by construction.
"""

from .version import GENERATOR_VERSION

__all__ = ["GENERATOR_VERSION"]
