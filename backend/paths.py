#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent
RUNTIME_DATA_ROOT = APP_ROOT / 'runtime-data'
DEFAULT_USER_ID = 'default-user'


def detect_shared_root() -> Path:
    if (APP_ROOT / 'character').exists() and (APP_ROOT / 'memory').exists():
        return APP_ROOT
    return WORKSPACE_ROOT


SHARED_ROOT = detect_shared_root()


def shared_path(*parts: str) -> Path:
    return SHARED_ROOT.joinpath(*parts)


def _slug(text: str, fallback: str) -> str:
    value = str(text or '').strip()
    if not value:
        return fallback
    value = re.sub(r'[\\/:\s]+', '-', value)
    value = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff]+', '', value)
    value = value.strip('-')
    return value or fallback


def active_user_id() -> str:
    return DEFAULT_USER_ID


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def active_character_id() -> str:
    character_path = SHARED_ROOT / 'character' / 'character-data.json'
    data = _read_json(character_path)
    name = str(data.get('name', '') or '').strip()
    if name:
        return _slug(name, 'character')
    return _slug(character_path.parent.name or character_path.stem, 'character')


def user_root(user_id: str | None = None) -> Path:
    return RUNTIME_DATA_ROOT / (user_id or active_user_id())


def user_profile_root(user_id: str | None = None) -> Path:
    return user_root(user_id) / 'profile'


def user_presets_root(user_id: str | None = None) -> Path:
    return user_root(user_id) / 'presets'


def character_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return user_root(user_id) / 'characters' / (character_id or active_character_id())


def character_source_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return character_root(character_id, user_id) / 'source'


def character_memory_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return character_source_root(character_id, user_id) / 'memory'


def character_npcs_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return character_memory_root(character_id, user_id) / 'npcs'


def character_runtime_persona_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return character_source_root(character_id, user_id) / 'runtime' / 'persona-seeds'


def character_sessions_root(character_id: str | None = None, user_id: str | None = None) -> Path:
    return character_root(character_id, user_id) / 'sessions'


def legacy_sessions_root() -> Path:
    return APP_ROOT / 'sessions'


def current_sessions_root() -> Path:
    return character_sessions_root()


def resolve_session_dir(session_id: str, *, create: bool = False) -> Path:
    current = current_sessions_root() / session_id
    legacy = legacy_sessions_root() / session_id
    if current.exists():
        return current
    if legacy.exists():
        return legacy
    if create:
        current.mkdir(parents=True, exist_ok=True)
    return current


def iter_session_dirs() -> list[Path]:
    roots = []
    current = current_sessions_root()
    legacy = legacy_sessions_root()
    if current.exists():
        roots.append(current)
    if legacy.exists() and legacy != current:
        roots.append(legacy)

    seen_names: set[str] = set()
    out: list[Path] = []
    for root in roots:
        for path in root.iterdir():
            if not path.is_dir():
                continue
            if path.name in seen_names:
                continue
            seen_names.add(path.name)
            out.append(path)
    return out


def session_archive_target(session_dir: Path, session_id: str) -> Path:
    stamp = __import__('time').strftime('%Y%m%d-%H%M%S')
    return session_dir.parent / f'archive-{stamp}-{session_id}'


def resolve_legacy_source(path_str: str) -> Path:
    return SHARED_ROOT / path_str


def layered_source_map() -> dict[str, Path]:
    return {
        'user.user_md': user_profile_root() / 'USER.md',
        'user.player_profile_json': user_profile_root() / 'player-profile.json',
        'user.player_profile_md': user_profile_root() / 'player-profile.md',
        'user.presets_dir': user_presets_root(),
        'character.character_data': character_source_root() / 'character-data.json',
        'character.lorebook': character_source_root() / 'lorebook.json',
        'character.canon': character_source_root() / 'canon.md',
        'character.state': character_source_root() / 'state.md',
        'character.summary': character_source_root() / 'summary.md',
        'character.npc_profiles_dir': character_npcs_root(),
        'character.persona_seeds_dir': character_runtime_persona_root(),
        'session.sessions_root': current_sessions_root(),
        'session.legacy_sessions_root': legacy_sessions_root(),
    }


def resolve_source_key(source_key: str) -> Path:
    mapping = layered_source_map()
    return mapping.get(source_key, SHARED_ROOT)


def resolve_layered_source(path_str: str) -> Path:
    text = str(path_str or '').strip()
    if not text:
        return SHARED_ROOT
    direct = resolve_legacy_source(text)
    if direct.exists():
        return direct

    mappings = {
        'USER.md': resolve_source_key('user.user_md'),
        'player-profile.json': resolve_source_key('user.player_profile_json'),
        'player-profile.md': resolve_source_key('user.player_profile_md'),
        'character/character-data.json': resolve_source_key('character.character_data'),
        'character/lorebook.json': resolve_source_key('character.lorebook'),
        'memory/canon.md': resolve_source_key('character.canon'),
        'memory/state.md': resolve_source_key('character.state'),
        'memory/summary.md': resolve_source_key('character.summary'),
        'memory/npcs': resolve_source_key('character.npc_profiles_dir'),
        'runtime/persona-seeds': resolve_source_key('character.persona_seeds_dir'),
        'character/presets': resolve_source_key('user.presets_dir'),
    }
    mapped = mappings.get(text)
    if mapped and mapped.exists():
        return mapped
    return direct
