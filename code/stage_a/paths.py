"""Where things live, and which interpreter opens them.

Two conda environments are involved. ``l2`` carries IfcOpenShell and the scorer,
so anything that opens an IFC model runs there. ``l2train`` carries the training
stack. Both are named here rather than in each module, and both can be pointed
elsewhere with an environment variable so the package holds no machine-specific
path as a hard requirement.
"""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("VERIBIM_ROOT", Path(__file__).resolve().parents[2]))
CODE_ROOT = PROJECT_ROOT / "code"
HARNESS_ROOT = CODE_ROOT / "harness"

CONDA_ROOT = Path(os.environ.get("CONDA_ROOT", Path.home() / "miniconda3"))
L2_PYTHON = Path(os.environ.get("VERIBIM_L2_PYTHON", CONDA_ROOT / "envs/l2/bin/python"))
L2TRAIN_PYTHON = Path(
    os.environ.get("VERIBIM_L2TRAIN_PYTHON", CONDA_ROOT / "envs/l2train/bin/python")
)

BASE_MODEL_DIR = Path(
    os.environ.get("VERIBIM_BASE_MODEL", PROJECT_ROOT / "models" / "Qwen3.5-9B")
)

SMOKE_TASKS = PROJECT_ROOT / "data/modifc_tasks_smoke/tasks.jsonl"
V1_TASKS = PROJECT_ROOT / "data/veribim_tasks_v1/tasks.jsonl"

STAGE_A_DATA = PROJECT_ROOT / "data/stage_a"
CHECKPOINT_ROOT = PROJECT_ROOT / "checkpoints/stage_a"


def default_tasks_file() -> Path:
    """The v1 set once it exists, the smoke set until then."""
    return V1_TASKS if V1_TASKS.exists() else SMOKE_TASKS


def ensure_harness_on_path() -> None:
    """Make ``modifc_harness`` importable from whichever environment is running."""
    import sys

    root = str(HARNESS_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def ensure_code_on_path() -> None:
    """Make ``modifc_score`` and ``modifc_gen`` importable."""
    import sys

    root = str(CODE_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def require_absolute(path, what: str = "path"):
    """Return ``path`` resolved, refusing a relative one.

    The sandbox worker runs with its own working directory, so a relative path
    handed to it resolves somewhere else and every trajectory dies at startup
    with `FileNotFoundError`. That failure has now happened twice, in the Stage A
    repair pass and in the first Stage B smoke, and both times it looked like a
    hundred-percent model failure rather than a caller mistake. Anything that
    becomes a sandbox working path goes through here.
    """
    from pathlib import Path as _Path

    resolved = _Path(path).expanduser()
    if not resolved.is_absolute():
        resolved = resolved.resolve()
    if not resolved.is_absolute():
        raise ValueError(f"{what} must be absolute, got {path!r}")
    return resolved
