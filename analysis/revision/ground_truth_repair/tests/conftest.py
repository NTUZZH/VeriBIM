"""Puts the helper library under test first on the import path.

GT_FIX_LIB=new (default) tests the repaired copy in gt_fix/patched_code;
GT_FIX_LIB=old tests the shipped library in code/, to show the tests catch
the two defects.
"""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
LIB = os.environ.get("GT_FIX_LIB", "new")
CODE = HERE.parent / "patched_code" if LIB == "new" else ROOT / "code"
for entry in (str(CODE / "harness"), str(CODE)):
    if entry in sys.path:
        sys.path.remove(entry)
    sys.path.insert(0, entry)


def pytest_report_header(config):
    return f"helper library under test: {CODE}"
