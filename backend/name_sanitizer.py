#!/usr/bin/env python3
from __future__ import annotations

import ast
import re

try:
    from .paths import active_character_id, active_user_id
    from .player_profile import load_effective_player_profile
except ImportError:
    from paths import active_character_id, active_user_id
    from player_profile import load_effective_player_profile


# Per (user, character) cache: switching character cards (via ContextVar
# override or persisted active card) must not surface another card's
# protagonist names. lru_cache(maxsize=1) was process-global and leaked
# across requests when overrides differed.
_protagonist_names_cache: dict[tuple[str, str], frozenset[str]] = {}


def _protagonist_cache_key() -> tuple[str, str]:
    try:
        return (active_user_id(), active_character_id())
    except Exception:
        return ('', '')


def protagonist_names() -> set[str]:
    key = _protagonist_cache_key()
    cached = _protagonist_names_cache.get(key)
    if cached is not None:
        return set(cached)
    names: set[str] = set()
    data = load_effective_player_profile()
    for field in ('name', 'courtesyName'):
        value = str(data.get(field, '') or '').strip()
        if value:
            names.add(value)
    _protagonist_names_cache[key] = frozenset(names)
    return names


def invalidate_protagonist_names_cache() -> None:
    """Clear cached protagonist names. Call when active character/user changes."""
    _protagonist_names_cache.clear()


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


GENERIC_MODIFIER_FRAGMENTS = {
    '淡淡', '轻轻', '缓缓', '静静', '冷冷', '慢慢', '低低', '轻声', '低声', '笑嘻嘻', '笑吟吟', '笑盈盈',
    '闷闷', '怔怔', '直直', '定定', '微微', '幽幽', '怯怯', '怔住', '顿住'
}


def looks_like_modifier_fragment(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    if text in GENERIC_MODIFIER_FRAGMENTS:
        return True
    if len(text) <= 4 and len(set(text)) <= 2 and text[:1] == text[1:2]:
        return True
    if len(text) <= 4 and text.endswith(('地', '着')):
        return True
    return False


VAGUE_ENTITY_FRAGMENTS = {
    '旁边几个', '附近几个', '周围几个', '门口几个', '门外几个',
    '这几个', '那几个', '几个', '一些', '一群', '一帮',
}

PROSE_ENTITY_PREFIXES = (
    '说是', '据说', '听说', '本以为', '谁知', '这里', '那里', '刚才', '昨夜', '今晨',
)


def looks_like_bad_entity_fragment(item) -> bool:
    """Reject short prose/quantifier fragments that are not stable entity names."""
    text = sanitize_runtime_name(item)
    if not text:
        return True
    if looks_like_modifier_fragment(text):
        return True
    if text in VAGUE_ENTITY_FRAGMENTS:
        return True
    if text.startswith(PROSE_ENTITY_PREFIXES):
        return True
    if re.match(r'^(?:旁边|附近|周围|门口|门外)?(?:几个|几名|一些|一群|一帮|一伙)$', text):
        return True
    return False


def is_protagonist_name(item) -> bool:
    text = sanitize_runtime_name(item)
    if not text:
        return False
    return text in protagonist_names()
