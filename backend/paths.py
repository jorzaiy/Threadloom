#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent


def detect_shared_root() -> Path:
    if (APP_ROOT / 'character').exists() and (APP_ROOT / 'memory').exists():
        return APP_ROOT
    return WORKSPACE_ROOT


SHARED_ROOT = detect_shared_root()


def shared_path(*parts: str) -> Path:
    return SHARED_ROOT.joinpath(*parts)
