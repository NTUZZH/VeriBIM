"""The gold model of a task, rebuilt on demand.

The v1 task set stores the gold script and not the gold model: fifty thousand
materialised models would need most of a terabyte, so the canonical artifact is
the script and the model is rebuilt when something needs it. Both the
synthesizer and the harvester need it, because it is the reference the verifier
scores against, so both go through the generator's own bounded cache rather than
each keeping their own copy of the logic.

A cache lives in one worker process and bounds a directory, not the process. A
rebuild that would breach the bound evicts the least recently used entry first,
so a long run's disk use is flat rather than growing with the task count.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

from . import paths

paths.ensure_code_on_path()

#: Per-worker bounds. A worker needs one gold model resident at a time, so the
#: rest of the allowance is headroom that lets a retry hit the cache instead of
#: rebuilding; at six workers this bounds the whole run at about 12 GB.
DEFAULT_MAX_BYTES = 1024 ** 3
DEFAULT_MAX_FILES = 4


def open_cache(cache_dir: Path, root: Path | None = None,
               max_bytes: int = DEFAULT_MAX_BYTES,
               max_files: int = DEFAULT_MAX_FILES, check: bool = True):
    """A gold-model cache rooted at the project directory."""
    from modifc_gen.materialize import GoldCache

    return GoldCache(root=root or paths.PROJECT_ROOT, cache_dir=cache_dir,
                     max_bytes=max_bytes, max_files=max_files, check=check)


def resolve_gold(record: dict, cache=None,
                 project_root: Path | None = None) -> Optional[Path]:
    """Where this task's gold model is, materialising it if it is not on disk.

    A record whose gold model is already written (the smoke set, and the v1
    validation split) is used as it stands; anything else is rebuilt from the
    gold script and checked against the checksum the record carries.
    """
    project_root = project_root or paths.PROJECT_ROOT
    named = project_root / record["ground_truth_ifc"]
    if named.is_file() and named.stat().st_size > 0:
        return named
    if cache is None:
        return None
    return cache.path_for(record)
