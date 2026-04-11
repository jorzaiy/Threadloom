#!/usr/bin/env python3
"""Card-level semantic hints loader.

Loads entity classification tokens and NPC role mappings from
character-data.json['hints'] instead of hardcoded constants.
Falls back to empty/conservative defaults when no hints are present,
so the system works with any card.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    from .paths import resolve_layered_source
    from .model_config import load_runtime_config
except ImportError:
    from paths import resolve_layered_source
    from model_config import load_runtime_config


def _load_character_data() -> dict:
    cfg = load_runtime_config()
    sources = cfg.get('sources', {})
    char_path_str = sources.get('character_core', 'character/character-data.json')
    try:
        char_path = resolve_layered_source(char_path_str)
        if char_path.exists():
            return json.loads(char_path.read_text(encoding='utf-8'))
    except Exception:
        pass
    return {}


@lru_cache(maxsize=1)
def load_card_hints() -> dict:
    """Load hints from character-data.json['hints'].

    Returns a dict with keys like:
        environment_tokens: tuple[str, ...]
        transient_group_tokens: tuple[str, ...]
        non_character_object_tokens: tuple[str, ...]
        generic_target_tokens: tuple[str, ...]
        service_role_tokens: tuple[str, ...]
        known_npc_roles: dict[str, str]   # name -> role_label
        npc_canonical_mappings: dict[str, str]  # surface form -> canonical name
        time_era_prefix: str
    All fields fall back to empty if not declared.
    """
    char = _load_character_data()
    raw = char.get('hints', {})
    if not isinstance(raw, dict):
        raw = {}

    def _tuple_field(key: str) -> tuple[str, ...]:
        value = raw.get(key, [])
        if isinstance(value, (list, tuple)):
            return tuple(str(item).strip() for item in value if str(item).strip())
        return ()

    def _dict_field(key: str) -> dict[str, str]:
        value = raw.get(key, {})
        if isinstance(value, dict):
            return {str(k).strip(): str(v).strip() for k, v in value.items() if str(k).strip()}
        return {}

    persona_archetypes = raw.get('persona_archetypes', [])
    if not isinstance(persona_archetypes, list):
        persona_archetypes = []

    return {
        'environment_tokens': _tuple_field('environment_tokens'),
        'transient_group_tokens': _tuple_field('transient_group_tokens'),
        'non_character_object_tokens': _tuple_field('non_character_object_tokens'),
        'generic_target_tokens': _tuple_field('generic_target_tokens'),
        'service_role_tokens': _tuple_field('service_role_tokens'),
        'known_npc_roles': _dict_field('known_npc_roles'),
        'npc_canonical_mappings': _dict_field('npc_canonical_mappings'),
        'time_era_prefix': str(raw.get('time_era_prefix', '') or '').strip(),
        'persona_archetypes': persona_archetypes,
    }


def invalidate_card_hints_cache() -> None:
    """Clear the cached hints. Call when character card changes."""
    load_card_hints.cache_clear()


def get_environment_tokens() -> tuple[str, ...]:
    return load_card_hints()['environment_tokens']


def get_transient_group_tokens() -> tuple[str, ...]:
    return load_card_hints()['transient_group_tokens']


def get_non_character_object_tokens() -> tuple[str, ...]:
    return load_card_hints()['non_character_object_tokens']


def get_generic_target_tokens() -> tuple[str, ...]:
    return load_card_hints()['generic_target_tokens']


def get_service_role_tokens() -> tuple[str, ...]:
    return load_card_hints()['service_role_tokens']


def get_known_npc_role(name: str) -> str:
    """Look up a known NPC role_label from card hints. Returns '' if not found."""
    return load_card_hints()['known_npc_roles'].get(name, '')


def get_canonical_name(surface: str) -> str:
    """Look up a canonical NPC name from card hints. Returns '' if no mapping."""
    return load_card_hints()['npc_canonical_mappings'].get(surface, '')


def get_time_era_prefix() -> str:
    return load_card_hints()['time_era_prefix']


def get_persona_archetypes() -> list[dict]:
    """Return persona archetype definitions from card hints.
    Each entry has 'match_tokens' (list[str]) and trait fields."""
    return load_card_hints()['persona_archetypes']
