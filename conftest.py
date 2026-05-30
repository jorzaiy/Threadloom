"""Pytest bootstrap shared by the whole suite.

Ensures both the repo root and ``backend/`` are importable before any test
module is collected, so collection no longer depends on which test file
happens to insert ``sys.path`` first. This is what makes a single-file run
(``pytest tests/test_foo.py``) behave the same as a full run, and removes the
order-dependent ``ModuleNotFoundError`` that used to surface when a test
imported ``backend.*`` before the repo root was on ``sys.path``.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _candidate in (_ROOT, _ROOT / 'backend'):
    _entry = str(_candidate)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)
