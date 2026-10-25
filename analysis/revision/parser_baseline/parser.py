"""Template-inversion parser: instruction text in, program or question out.

This is the entry point of the rule-based baseline.  It reads one benchmark
instruction (the text only, nothing else from the task record) and returns

  * a question naming the missing value, when the instruction leaves out an
    element, a storey or a dimension the edit needs (the reply carries no edit);
  * otherwise a Python program for the harness sandbox that resolves the named
    references with the helper library and performs the edit, ending with
    commit().

The grammar (grammar.py) inverts the benchmark generator's sentence templates,
reference phrases, identifier spellings, synonyms and unit dialects; the
program writer (codegen.py) maps each parsed intent to helper calls, using the
prelude in prelude_src.py.  No language model and no learned component is used.

Usage:
  python parser.py "Move the wall 'W-12' 0.5 m east."
"""

from __future__ import annotations

import json
import sys

import codegen
import grammar


def parse(instruction: str) -> dict:
    """The parsed intent of one instruction (see grammar.parse)."""
    return grammar.parse(instruction)


def respond(instruction: str) -> dict:
    """Parse one instruction and return the reply, and the program if any."""
    intent = grammar.parse(instruction)
    if not intent.get("recognised"):
        return {"intent": intent, "program": None,
                "reply": "I could not read this instruction, so I made no change."}
    if intent.get("clarify"):
        return {"intent": intent, "program": None,
                "reply": codegen.question(intent)}
    return {"intent": intent, "program": codegen.program(intent),
            "body": codegen.body(intent),
            "reply": "The edit is done and the model is saved."}


if __name__ == "__main__":
    out = respond(" ".join(sys.argv[1:]))
    print(json.dumps({"intent": {k: out["intent"].get(k) for k in
                                 ("op", "clarify", "parse")},
                      "reply": out["reply"]}, indent=1, default=str))
    if out.get("body"):
        print("---- program body (after the prelude) ----")
        print(out["body"])
