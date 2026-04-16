#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent
RUNTIME_DATA_ROOT = APP_ROOT / 'runtime-data'
DEFAULT_USER_ID = 'default-user'
DEFAULT_USER_LABEL = 'default_user'
ACTIVE_CHARACTER_CONFIG_NAME = 'active-character.json'
SESSION_ID_RE = re.compile(r'^[0-9A-Za-z_\-\u4e00-\u9fff]+$')
TURN_ID_RE = re.compile(r'^[0-9A-Za-z_-]+$')
MAX_SESSION_ID_LENGTH = 120
MAX_TURN_ID_LENGTH = 120
_ACTIVE_CHARACTER_ID_OVERRIDE: str | None = None


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


def normalize_session_id(session_id: str) -> str:
    value = str(session_id or '').strip()
    if not value:
        raise ValueError('session_id is required')
    if len(value) > MAX_SESSION_ID_LENGTH:
        raise ValueError('session_id is too long')
    if not SESSION_ID_RE.fullmatch(value):
        raise ValueError('session_id contains invalid characters')
    return value


def normalize_turn_id(turn_id: str) -> str:
    value = str(turn_id or '').strip()
    if not value:
        raise ValueError('turn_id is required')
    if len(value) > MAX_TURN_ID_LENGTH:
        raise ValueError('turn_id is too long')
    if not TURN_ID_RE.fullmatch(value):
        raise ValueError('turn_id contains invalid characters')
    return value


def active_user_id() -> str:
    return DEFAULT_USER_ID


DEFAULT_CHARACTER_ID = '碎影江湖'
TEMPLATE_ROOT = RUNTIME_DATA_ROOT / '_template'


def ensure_user_root(user_id: str | None = None) -> Path:
    """确保用户目录结构存在。新用户自动获得默认角色卡。"""
    import shutil
    uid = user_id or active_user_id()
    root = RUNTIME_DATA_ROOT / uid
    if root.exists():
        return root
    # 创建基本目录结构
    (root / 'config').mkdir(parents=True, exist_ok=True)
    (root / 'profile').mkdir(parents=True, exist_ok=True)
    (root / 'presets').mkdir(parents=True, exist_ok=True)
    (root / 'characters').mkdir(parents=True, exist_ok=True)
    # 复制默认角色卡
    template_card = TEMPLATE_ROOT / 'characters' / DEFAULT_CHARACTER_ID
    if not template_card.exists():
        # 回退到 default-user 的碎影江湖
        template_card = RUNTIME_DATA_ROOT / DEFAULT_USER_ID / 'characters' / DEFAULT_CHARACTER_ID
    if template_card.exists():
        target = root / 'characters' / DEFAULT_CHARACTER_ID
        shutil.copytree(str(template_card), str(target), dirs_exist_ok=True)
    # 设置默认角色
    config_file = root / 'config' / ACTIVE_CHARACTER_CONFIG_NAME
    config_file.write_text(json.dumps({'character_id': DEFAULT_CHARACTER_ID}, ensure_ascii=False), encoding='utf-8')
    return root


def active_user_label() -> str:
    if active_user_id() == DEFAULT_USER_ID:
        return DEFAULT_USER_LABEL
    return active_user_id()


def set_active_character_override(character_id: str | None) -> None:
    global _ACTIVE_CHARACTER_ID_OVERRIDE
    value = str(character_id or '').strip()
    _ACTIVE_CHARACTER_ID_OVERRIDE = value or None


def clear_active_character_override() -> None:
    set_active_character_override(None)


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def active_character_id() -> str:
    if _ACTIVE_CHARACTER_ID_OVERRIDE:
        return _ACTIVE_CHARACTER_ID_OVERRIDE
    active_path = user_config_root() / ACTIVE_CHARACTER_CONFIG_NAME
    active_data = _read_json(active_path)
    configured = str(active_data.get('character_id', '') or '').strip()
    if configured:
        return _slug(configured, 'character')
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


def user_config_root(user_id: str | None = None) -> Path:
    return user_root(user_id) / 'config'


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


def session_roots() -> list[Path]:
    roots = [current_sessions_root()]
    legacy = legacy_sessions_root()
    if legacy not in roots:
        roots.append(legacy)
    return roots


def _session_dir_for_root(root: Path, session_id: str) -> Path:
    safe_session_id = normalize_session_id(session_id)
    root_resolved = root.resolve()
    candidate = (root_resolved / safe_session_id).resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as err:
        raise ValueError('session_id escapes managed session roots') from err
    return candidate


def current_session_dir(session_id: str) -> Path:
    return _session_dir_for_root(current_sessions_root(), session_id)


def legacy_session_dir(session_id: str) -> Path:
    return _session_dir_for_root(legacy_sessions_root(), session_id)


def managed_session_id_from_path(path: Path) -> str | None:
    resolved = path.resolve(strict=False)
    for root in session_roots():
        root_resolved = root.resolve(strict=False)
        try:
            rel = resolved.relative_to(root_resolved)
        except ValueError:
            continue
        if len(rel.parts) != 1:
            continue
        try:
            return normalize_session_id(rel.parts[0])
        except ValueError:
            return None
    return None


def is_managed_session_dir(path: Path) -> bool:
    return managed_session_id_from_path(path) is not None


def resolve_session_dir(session_id: str, *, create: bool = False) -> Path:
    safe_session_id = normalize_session_id(session_id)
    current = current_session_dir(safe_session_id)
    legacy = legacy_session_dir(safe_session_id)
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
    safe_session_id = normalize_session_id(session_id)
    return session_dir.parent / f'archive-{stamp}-{safe_session_id}'


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

    direct = resolve_legacy_source(text)
    if direct.exists():
        return direct
    return direct
