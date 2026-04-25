#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy

try:
    from .name_sanitizer import is_protagonist_name
except ImportError:
    from name_sanitizer import is_protagonist_name


def _contains_any(text: str, names: list[str]) -> bool:
    return any(name and name in text for name in names)


def resolve_important_npc_continuity(state: dict) -> dict:
    current = deepcopy(state or {})
    onstage = list(current.get('onstage_npcs', []) or [])
    relevant = list(current.get('relevant_npcs', []) or [])
    important = [item for item in (current.get('important_npcs', []) or []) if isinstance(item, dict) and item.get('locked')]

    text_pool = ' '.join([
        str(current.get('location', '') or ''),
        str(current.get('main_event', '') or ''),
        ' '.join(current.get('immediate_risks', []) or []),
        ' '.join(current.get('carryover_clues', []) or []),
        ' '.join(
            ' '.join(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
            for item in (current.get('active_threads', []) or []) if isinstance(item, dict)
        ),
    ])

    for item in important:
        label = str(item.get('primary_label', '') or '').strip()
        if not label or is_protagonist_name(label) or label in onstage or label in relevant:
            continue
        aliases = [str(alias).strip() for alias in (item.get('aliases') or []) if str(alias).strip() and not is_protagonist_name(alias)]
        names = [label] + aliases

        if int(item.get('inactive_turns', 0) or 0) > 3:
            continue

        evidence = 0
        if _contains_any(text_pool, names):
            evidence += 2
        role_label = str(item.get('role_label', '') or '').strip()
        if role_label and role_label in text_pool:
            evidence += 1
        last_location = str(item.get('last_location', '') or '').strip()
        if last_location and last_location == str(current.get('location', '') or '').strip():
            evidence += 1
        last_main_event = str(item.get('last_main_event', '') or '').strip()
        if last_main_event and last_main_event == str(current.get('main_event', '') or '').strip():
            evidence += 1
        if item.get('retained'):
            evidence += 1

        if evidence >= 2 and len(relevant) < 6:
            relevant.append(label)

    current['relevant_npcs'] = relevant[:6]
    return current
