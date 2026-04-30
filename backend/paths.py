#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = APP_ROOT.parent
RUNTIME_DATA_ROOT = APP_ROOT / 'runtime-data'
DEFAULT_USER_ID = 'default-user'
DEFAULT_USER_LABEL = 'default_user'
ACTIVE_CHARACTER_CONFIG_NAME = 'active-character.json'
USER_ID_RE = re.compile(r'^[0-9A-Za-z_-]{1,64}$')
SESSION_ID_RE = re.compile(r'^[0-9A-Za-z_\-\u4e00-\u9fff]+$')
TURN_ID_RE = re.compile(r'^[0-9A-Za-z_-]+$')
MAX_SESSION_ID_LENGTH = 120
MAX_TURN_ID_LENGTH = 120
_ACTIVE_CHARACTER_ID_OVERRIDE: ContextVar[str | None] = ContextVar('threadloom_active_character_id_override', default=None)
_ACTIVE_USER_ID: ContextVar[str] = ContextVar('threadloom_active_user_id', default=DEFAULT_USER_ID)
_MULTI_USER_REQUEST: ContextVar[bool] = ContextVar('threadloom_multi_user_request', default=False)


def detect_shared_root() -> Path:
    if (APP_ROOT / 'character').exists() and (APP_ROOT / 'memory').exists():
        return APP_ROOT
    return WORKSPACE_ROOT


SHARED_ROOT = detect_shared_root()


def shared_path(*parts: str) -> Path:
    return SHARED_ROOT.joinpath(*parts)


def slugify(text: str, fallback: str) -> str:
    value = str(text or '').strip()
    if not value:
        return fallback
    value = re.sub(r'[\\/:\s]+', '-', value)
    value = re.sub(r'[^0-9A-Za-z_\-\u4e00-\u9fff·]+', '', value)
    value = value.strip('-')
    return value or fallback


def _slug(text: str, fallback: str) -> str:
    return slugify(text, fallback)


def read_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


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


def normalize_user_id(user_id: str) -> str:
    value = str(user_id or '').strip()
    if not value:
        raise ValueError('user_id is required')
    if value in {'_system', '_template'}:
        raise ValueError('user_id is reserved')
    if not USER_ID_RE.fullmatch(value):
        raise ValueError('user_id contains invalid characters')
    return value


def active_user_id() -> str:
    return _ACTIVE_USER_ID.get()


def set_active_user_id(user_id: str) -> Token[str]:
    return _ACTIVE_USER_ID.set(normalize_user_id(user_id))


def reset_active_user_id(token: Token[str]) -> None:
    _ACTIVE_USER_ID.reset(token)


def is_multi_user_request_context() -> bool:
    return _MULTI_USER_REQUEST.get()


def set_multi_user_request_context(enabled: bool) -> Token[bool]:
    return _MULTI_USER_REQUEST.set(bool(enabled))


def reset_multi_user_request_context(token: Token[bool]) -> None:
    _MULTI_USER_REQUEST.reset(token)


@contextmanager
def active_user_context(user_id: str) -> Generator[None, None, None]:
    token = set_active_user_id(user_id)
    try:
        yield
    finally:
        reset_active_user_id(token)


def _resolve_user_id(user_id: str | None = None) -> str:
    return normalize_user_id(user_id or active_user_id())


def confine_to_root(root: Path, candidate: Path, *, label: str = 'path') -> Path:
    root_resolved = root.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(root_resolved)
    except ValueError as err:
        raise ValueError(f'{label} escapes managed root') from err
    return candidate_resolved


def user_runtime_root(user_id: str | None = None) -> Path:
    return RUNTIME_DATA_ROOT / _resolve_user_id(user_id)


def confine_to_user_root(candidate: Path, user_id: str | None = None, *, label: str = 'path') -> Path:
    return confine_to_root(user_runtime_root(user_id), candidate, label=label)


def is_path_within_user_root(candidate: Path, user_id: str | None = None) -> bool:
    try:
        confine_to_user_root(candidate, user_id)
    except ValueError:
        return False
    return True


DEFAULT_CHARACTER_ID = '碎影江湖'
TEMPLATE_ROOT = RUNTIME_DATA_ROOT / '_template'


def ensure_user_root(user_id: str | None = None) -> Path:
    """确保用户目录结构存在。新用户自动获得默认角色卡。"""
    import shutil
    uid = _resolve_user_id(user_id)
    root = user_runtime_root(uid)
    if root.exists():
        return root
    # 创建基本目录结构
    (root / 'config').mkdir(parents=True, exist_ok=True)
    (root / 'profile').mkdir(parents=True, exist_ok=True)
    (root / 'presets').mkdir(parents=True, exist_ok=True)
    (root / 'characters').mkdir(parents=True, exist_ok=True)
    # 复制默认角色卡。多用户新账号只能从 _template 初始化，不能回退复制
    # default-user 的私有角色卡数据。
    template_card = TEMPLATE_ROOT / 'characters' / DEFAULT_CHARACTER_ID
    if not template_card.exists() and uid == DEFAULT_USER_ID:
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


def set_active_character_override(character_id: str | None) -> Token[str | None]:
    value = str(character_id or '').strip()
    return _ACTIVE_CHARACTER_ID_OVERRIDE.set(value or None)


def reset_active_character_override(token: Token[str | None]) -> None:
    _ACTIVE_CHARACTER_ID_OVERRIDE.reset(token)


def clear_active_character_override() -> None:
    _ACTIVE_CHARACTER_ID_OVERRIDE.set(None)


def is_character_override_active() -> bool:
    """True when a per-request character override is set in this context.

    Read paths use this to skip the legacy SHARED_ROOT fallback so an explicit
    override (e.g. card import / cross-character inspection) cannot accidentally
    serve content from another card's shared directory.
    """
    return bool(_ACTIVE_CHARACTER_ID_OVERRIDE.get())


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return read_json_file(path)
    except Exception:
        return {}


def active_character_id() -> str:
    override = _ACTIVE_CHARACTER_ID_OVERRIDE.get()
    if override:
        return override
    active_path = user_config_root() / ACTIVE_CHARACTER_CONFIG_NAME
    active_data = _read_json(active_path)
    configured = str(active_data.get('character_id', '') or '').strip()
    if configured:
        return _slug(configured, 'character')
    if is_multi_user_request_context():
        return DEFAULT_CHARACTER_ID
    character_path = SHARED_ROOT / 'character' / 'character-data.json'
    data = _read_json(character_path)
    name = str(data.get('name', '') or '').strip()
    if name:
        return _slug(name, 'character')
    return _slug(character_path.parent.name or character_path.stem, 'character')


def user_root(user_id: str | None = None) -> Path:
    return user_runtime_root(user_id)


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
    if is_multi_user_request_context():
        return roots
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


def find_character_session_dir(session_id: str, *, exclude_active: bool = False) -> Path | None:
    safe_session_id = normalize_session_id(session_id)
    active_character = active_character_id()
    current_resolved = current_session_dir(safe_session_id).resolve(strict=False) if exclude_active else None
    root = user_root() / 'characters'
    if not root.exists():
        return None
    for character_dir in sorted(root.iterdir(), key=lambda item: item.name):
        if not character_dir.is_dir():
            continue
        if exclude_active and character_dir.name == active_character:
            continue
        candidate = _session_dir_for_root(character_dir / 'sessions', safe_session_id)
        if current_resolved is not None and candidate.resolve(strict=False) == current_resolved:
            continue
        if candidate.exists():
            return candidate
    return None


def current_session_owner_context(session_id: str) -> dict:
    safe_session_id = normalize_session_id(session_id)
    session_dir = current_session_dir(safe_session_id)
    return {
        'user_id': active_user_id(),
        'character_id': active_character_id(),
        'session_id': safe_session_id,
        'session_root': str(current_sessions_root().resolve(strict=False)),
        'session_dir': str(session_dir.resolve(strict=False)),
    }


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
    if not is_multi_user_request_context() and legacy.exists():
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
    if not is_multi_user_request_context() and legacy.exists() and legacy != current:
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


def resolve_legacy_source(path_str: str) -> Path:
    return SHARED_ROOT / path_str


def layered_source_map() -> dict[str, Path]:
    return {
        'user.player_profile_base_json': user_profile_root() / 'player-profile.base.json',
        'user.player_profile_json': user_profile_root() / 'player-profile.json',
        'user.player_profile_md': user_profile_root() / 'player-profile.md',
        'user.presets_dir': user_presets_root(),
        'character.character_data': character_source_root() / 'character-data.json',
        'character.player_profile_override_json': character_source_root() / 'player-profile.override.json',
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
        'player-profile.base.json': resolve_source_key('user.player_profile_base_json'),
        'player-profile.json': resolve_source_key('user.player_profile_json'),
        'player-profile.md': resolve_source_key('user.player_profile_md'),
        'character/player-profile.override.json': resolve_source_key('character.player_profile_override_json'),
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
    if mapped and (is_multi_user_request_context() or is_character_override_active()):
        return mapped

    direct = resolve_legacy_source(text)
    if direct.exists():
        return direct
    return direct
