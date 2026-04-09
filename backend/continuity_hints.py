#!/usr/bin/env python3
from __future__ import annotations

try:
    from .runtime_store import load_continuity_hints
except ImportError:
    from runtime_store import load_continuity_hints


def normalized_hint_entries(session_id: str) -> list[dict]:
    items = load_continuity_hints(session_id)
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        primary_label = str(item.get('primary_label', '') or '').strip()
        if not primary_label:
            continue
        aliases = [str(alias).strip() for alias in (item.get('aliases') or []) if str(alias).strip()]
        out.append({
            'primary_label': primary_label,
            'aliases': sorted(set(aliases + [primary_label])),
            'role_label': str(item.get('role_label', '') or '').strip(),
            'continuity_mode': str(item.get('continuity_mode', 'important') or 'important').strip(),
            'notes': str(item.get('notes', '') or '').strip(),
        })
    return out


def match_continuity_hint(name: str, aliases: list[str], hints: list[dict]) -> dict | None:
    names = {str(name or '').strip()} | {str(alias or '').strip() for alias in (aliases or [])}
    names = {item for item in names if item}
    for hint in hints:
        hint_names = set(hint.get('aliases', []) or [])
        if names & hint_names:
            return hint
    return None
