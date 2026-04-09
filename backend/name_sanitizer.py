#!/usr/bin/env python3
from __future__ import annotations

import ast
import json
from functools import lru_cache

try:
    from .paths import shared_path
except ImportError:
    from paths import shared_path


PLAYER_PROFILE = shared_path('player-profile.json')


@lru_cache(maxsize=1)
def protagonist_names() -> set[str]:
    names: set[str] = set()
    if not PLAYER_PROFILE.exists():
        return names
    try:
        data = json.loads(PLAYER_PROFILE.read_text(encoding='utf-8'))
    except Exception:
        return names
    for key in ('name', 'courtesyName'):
        value = str(data.get(key, '') or '').strip()
        if value:
            names.add(value)
    return names


def sanitize_runtime_name(item) -> str:
    text = str(item or '').strip()
    if not text:
        return ''
    if text[0] == '{' and text[-1] == '}':
        try:
            parsed = ast.literal_eval(text)
            if isinstance(parsed, dict):
                return ''
        except Exception:
            return ''
    return text


def is_protagonist_name(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    return text in protagonist_names()
