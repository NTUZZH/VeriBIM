"""Scoring a task whose instruction leaves out a value the edit needs.

Such a task has two right answers in one: the model comes back with nothing
changed, and the reply asks for the value that was missing.  Neither half is
worth anything alone.  A system that edits a guessed element and asks a polite
question has still edited the wrong element, and a system that asks nothing has
guessed silently.

Both halves are checked deterministically.  "Nothing changed" is read entity by
entity between the input model and the prediction, which is how the batch scope
check reads it, so it survives a round trip through a writer that renumbers or
reformats the file.  "Asked for the missing value" is a question mark plus one
of the words the task's own record lists for the value that is missing.

What this cannot do is judge whether the question is a good one.  A reply that
asks "which storey?" when the storey was given and the dimension was not passes
the word test if "storey" happens to be one of the dimension's words, and a
reply in another language fails it.  The check is a floor on the behaviour and
not a measure of it, which is why it is a flag and not the default.
"""

from __future__ import annotations

import re
from typing import Any, Optional, Sequence

#: Products whose difference between two models counts as an edit.  The set is
#: the one the topology axis reads, so "unchanged" here means what it means
#: there.
NODE_CLASS = "IfcProduct"


def entity_signature(entity) -> Any:
    from .topology import full_signature

    return full_signature(entity)


def model_unchanged(model_0, model_pred, limit: int = 4) -> tuple[bool, dict]:
    """Whether the prediction holds the same model the input did.

    The identifiers have to be the same set and every entity under a shared
    identifier has to carry the same content.  Comparing content rather than
    bytes is what makes the check survive a file the system opened and saved.
    """
    before = {p.GlobalId for p in model_0.by_type(NODE_CLASS)}
    after = {p.GlobalId for p in model_pred.by_type(NODE_CLASS)}
    added = sorted(after - before)
    removed = sorted(before - after)
    if added or removed:
        return False, {"added": added[:limit], "removed": removed[:limit],
                       "n_added": len(added), "n_removed": len(removed)}
    changed: list[str] = []
    for guid in sorted(before):
        try:
            if entity_signature(model_0.by_guid(guid)) != \
                    entity_signature(model_pred.by_guid(guid)):
                changed.append(guid)
        except Exception:
            continue
        if len(changed) >= limit:
            break
    if changed:
        return False, {"changed": changed[:limit], "n_changed": len(changed)}
    return True, {}


#: The words that mark a reply as a question.  A question mark is required, so
#: this is a second reading rather than the only one.
QUESTION_OPENERS = ("which", "what", "where", "how", "could you tell",
                    "can you tell", "please tell", "please confirm",
                    "please specify")


def reply_asks(reply: str, keywords: Sequence[str]) -> tuple[bool, dict]:
    """Whether the reply asks one question about the value that is missing.

    Two marks are required and both are mechanical: a question mark, and one of
    the words the record lists for the missing value standing as its own word.
    """
    text = (reply or "").strip()
    if not text:
        return False, {"reason": "no_reply"}
    if "?" not in text:
        return False, {"reason": "no_question_mark"}
    lowered = text.lower()
    words = set(re.split(r"[^a-z0-9]+", lowered))
    named = [word for word in keywords if word.lower() in words]
    if not named:
        return False, {"reason": "missing_value_not_named",
                       "keywords": list(keywords)}
    opener = any(text_opener in lowered for text_opener in QUESTION_OPENERS)
    return True, {"named": named, "opened_as_a_question": opener}


def score(model_0, model_pred, clarification: dict,
          reply: str) -> tuple[float, dict]:
    """One under-specified task's score: one when both halves hold, else zero."""
    unchanged, unchanged_detail = model_unchanged(model_0, model_pred)
    asked, asked_detail = reply_asks(reply,
                                     clarification.get("keywords") or ())
    detail = {"slot": clarification.get("slot"),
              "file_unchanged": unchanged,
              "reply_asks": asked,
              "file_detail": unchanged_detail,
              "reply_detail": asked_detail}
    return (1.0 if unchanged and asked else 0.0), detail
