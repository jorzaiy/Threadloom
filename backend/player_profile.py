#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import threading
from pathlib import Path

try:
    from .atomic_io import atomic_write_bytes, atomic_write_json
    from .paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root
except ImportError:
    from atomic_io import atomic_write_bytes, atomic_write_json
    from paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root


PLAYER_PROFILE_LOCK = threading.RLock()

UNIFIED_PROFILE_SCHEMA_VERSION = 1
UNIFIED_PROFILE_TOP_KEYS = (
    'schemaVersion',
    'identity',
    'appearance',
    'abilities',
    'personality',
    'preferences',
    'background',
    'psychology',
    'worldAdaptation',
    'privateBoundaries',
)
UNIFIED_PROFILE_IDENTITY_KEYS = ('name', 'courtesyName', 'gender', 'age', 'origin', 'status')
UNIFIED_PROFILE_ARRAY_KEYS = (
    'appearance',
    'abilities',
    'personality',
    'preferences',
    'background',
    'psychology',
    'worldAdaptation',
    'privateBoundaries',
)


def _paths_module():
    for name in ('paths', 'backend.paths'):
        module = sys.modules.get(name)
        if module is None:
            continue
        if module.is_multi_user_request_context() or module.active_user_id() != module.DEFAULT_USER_ID:
            return module
    return sys.modules.get('paths') or sys.modules.get('backend.paths')


def _user_profile_root() -> Path:
    module = _paths_module()
    return module.user_profile_root() if module is not None else user_profile_root()


def _character_source_root() -> Path:
    module = _paths_module()
    return module.character_source_root() if module is not None else character_source_root()


def _shared_path(*parts: str) -> Path:
    module = _paths_module()
    return module.shared_path(*parts) if module is not None else shared_path(*parts)


def empty_unified_player_profile() -> dict:
    return {
        'schemaVersion': UNIFIED_PROFILE_SCHEMA_VERSION,
        'identity': {key: '' for key in UNIFIED_PROFILE_IDENTITY_KEYS},
        **{key: [] for key in UNIFIED_PROFILE_ARRAY_KEYS},
    }


def _clean_string(value) -> str:
    return ' '.join(str(value or '').split()).strip()


def _clean_text_items(value, *, limit: int = 24) -> list[str]:
    if not isinstance(value, list):
        raise ValueError('profile array fields must stay arrays')
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError('profile array items must be strings')
        text = _clean_string(item)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def validate_unified_player_profile(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError('profile must be an object')
    unknown = [key for key in payload if key not in UNIFIED_PROFILE_TOP_KEYS]
    if unknown:
        raise ValueError(f'unknown profile field: {unknown[0]}')
    identity = payload.get('identity', {})
    if not isinstance(identity, dict):
        raise ValueError('identity must be an object')
    unknown_identity = [key for key in identity if key not in UNIFIED_PROFILE_IDENTITY_KEYS]
    if unknown_identity:
        raise ValueError(f'unknown identity field: {unknown_identity[0]}')
    normalized = empty_unified_player_profile()
    for key in UNIFIED_PROFILE_IDENTITY_KEYS:
        value = identity.get(key, '')
        if value is None:
            value = ''
        if not isinstance(value, str | int | float) or isinstance(value, bool):
            raise ValueError(f'identity.{key} must be a string')
        normalized['identity'][key] = _clean_string(value)
    for key in UNIFIED_PROFILE_ARRAY_KEYS:
        normalized[key] = _clean_text_items(payload.get(key, []))
    return normalized


def is_unified_player_profile(payload: dict) -> bool:
    return isinstance(payload, dict) and isinstance(payload.get('identity'), dict)


def legacy_profile_to_unified(profile: dict) -> dict:
    normalized = normalize_player_profile(profile)
    unified = empty_unified_player_profile()
    identity = unified['identity']
    for source_key, target_key in (
        ('name', 'name'),
        ('courtesyName', 'courtesyName'),
        ('gender', 'gender'),
        ('age', 'age'),
        ('origin', 'origin'),
        ('status', 'status'),
    ):
        identity[target_key] = _clean_string(normalized.get(source_key, ''))

    appearance = normalized.get('appearance', {}) if isinstance(normalized.get('appearance', {}), dict) else {}
    appearance_items = []
    for key in ('hair', 'skin', 'eyes', 'bearing'):
        text = _compact_text(appearance.get(key))
        if text:
            appearance_items.append(text)
    character = _character_layer(normalized)
    character_appearance = character.get('appearance', {}) if isinstance(character.get('appearance', {}), dict) else {}
    for key in ('hair', 'skin', 'eyes', 'bearing', 'attire', 'aura'):
        text = _compact_text(character_appearance.get(key))
        if text:
            appearance_items.append(text)
    unified['appearance'] = _clean_text_items(appearance_items)

    abilities = []
    abilities.extend(_profile_list_items(normalized.get('skills', [])))
    cultivation = character.get('cultivation_info', {}) if isinstance(character.get('cultivation_info', {}), dict) else {}
    for key, label in (('realm', '境界'), ('status', '身份'), ('cultivation_path', '修炼路径'), ('spirit_root', '灵根')):
        text = _compact_text(cultivation.get(key))
        if text:
            abilities.append(f'{label}：{text}')
    abilities.extend(_profile_list_items(character.get('skills', [])))
    unified['abilities'] = _clean_text_items(abilities)

    personality = []
    personality.extend(_profile_list_items(normalized.get('personality', []), label_keys=('trait', 'name', 'title')))
    personality.extend(_profile_list_items(character.get('personality', []), label_keys=('trait', 'name', 'title')))
    unified['personality'] = _clean_text_items(personality)

    for source_key, target_key in (('interests', 'preferences'), ('weaknesses', 'privateBoundaries')):
        items = normalized.get(source_key, []) if isinstance(normalized.get(source_key, []), list) else []
        unified[target_key] = _clean_text_items([_compact_text(item) for item in items])

    background = normalized.get('background', {}) if isinstance(normalized.get('background', {}), dict) else {}
    background_items = [_compact_text(item) for item in background.values()]
    character_background = character.get('background', {})
    if isinstance(character_background, dict):
        background_items.extend(_compact_text(item) for item in character_background.values())
    elif isinstance(character_background, list):
        background_items.extend(_compact_text(item) for item in character_background)
    unified['background'] = _clean_text_items(background_items)

    psychology = normalized.get('psychology', {}) if isinstance(normalized.get('psychology', {}), dict) else {}
    psychology_items = [_compact_text(item) for item in psychology.values()]
    character_psychology = character.get('psychology', {}) if isinstance(character.get('psychology', {}), dict) else {}
    psychology_items.extend(_compact_text(item) for item in character_psychology.values())
    unified['psychology'] = _clean_text_items(psychology_items)

    adaptation = normalized.get('worldAdaptation', {}) if isinstance(normalized.get('worldAdaptation', {}), dict) else {}
    unified['worldAdaptation'] = _clean_text_items(adaptation.get('notes', []) if isinstance(adaptation.get('notes', []), list) else [])
    return validate_unified_player_profile(unified)


def render_unified_player_profile_markdown(profile: dict) -> str:
    profile = validate_unified_player_profile(profile)
    lines = ['# 玩家档案', '']
    identity = profile['identity']
    identity_lines = []
    for key, label in (('name', '名字'), ('courtesyName', '常用称呼'), ('gender', '性别'), ('age', '年龄'), ('origin', '出身'), ('status', '身份')):
        value = identity.get(key, '')
        if value:
            identity_lines.append(f'- {label}：{value}')
    if identity_lines:
        lines.extend(['## 核心身份', *identity_lines, ''])
    for key, title in (
        ('appearance', '外貌锚点'),
        ('abilities', '稳定能力'),
        ('personality', '性格锚点'),
        ('preferences', '偏好'),
        ('background', '背景'),
        ('psychology', '心理与剧情'),
        ('worldAdaptation', '世界适配说明'),
        ('privateBoundaries', '私密边界'),
    ):
        items = profile.get(key, [])
        if items:
            lines.extend([f'## {title}', *[f'- {item}' for item in items], ''])
    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines) + '\n' if lines else ''


def merge_unified_player_profiles(base: dict, override: dict) -> dict:
    merged = validate_unified_player_profile(base) if base else empty_unified_player_profile()
    override = validate_unified_player_profile(override) if override else empty_unified_player_profile()
    for key in UNIFIED_PROFILE_IDENTITY_KEYS:
        value = override['identity'].get(key, '')
        if value:
            merged['identity'][key] = value
    for key in UNIFIED_PROFILE_ARRAY_KEYS:
        items = override.get(key, [])
        if items:
            merged[key] = list(items)
    return validate_unified_player_profile(merged)


def _is_multi_user_request_context() -> bool:
    module = _paths_module()
    return module.is_multi_user_request_context() if module is not None else is_multi_user_request_context()


def _is_character_override_active() -> bool:
    module = _paths_module()
    return module.is_character_override_active() if module is not None else is_character_override_active()


PROFILE_FIELD_ALIASES = {
    'name': (
        'name',
        'character.name',
        'character.basic_info.name',
        'basic.name',
        'profile.name',
        'player.name',
        '名字',
        '姓名',
        '角色.name',
        '角色.名字',
    ),
    'courtesyName': (
        'courtesyName',
        'courtesy_name',
        'nickname',
        'nickName',
        'alias',
        'character.courtesyName',
        'character.courtesy_name',
        'character.basic_info.courtesyName',
        'character.basic_info.courtesy_name',
        'character.basic_info.nickname',
        'character.nickname',
        'basic.courtesyName',
        'basic.nickname',
        'profile.courtesyName',
        'profile.nickname',
        '常用称呼',
        '称呼',
        '昵称',
        '角色.courtesyName',
        '角色.常用称呼',
        '角色.昵称',
    ),
    'gender': ('gender', 'character.gender', 'character.basic_info.gender', 'basic.gender', 'profile.gender', '性别', '角色.gender', '角色.性别'),
    'age': ('age', 'character.age', 'character.basic_info.age', 'basic.age', 'profile.age', '年龄', '角色.age', '角色.年龄'),
    'birthday': (
        'birthday',
        'birthDay',
        'birth_date',
        'birthDate',
        'character.birthday',
        'character.birthDay',
        'character.basic_info.birthday',
        'character.basic_info.birthDay',
        'basic.birthday',
        'profile.birthday',
        '生辰',
        '生日',
        '角色.birthday',
        '角色.生辰',
        '角色.生日',
    ),
    'height': ('height', 'character.height', 'character.appearance.body.height', 'basic.height', 'profile.height', '身高', '身量', '角色.height', '角色.身高', '角色.身量'),
    'origin': ('origin', 'hometown', 'birthplace', 'character.origin', 'character.basic_info.origin', 'basic.origin', 'profile.origin', '出身', '籍贯', '来历', '角色.origin', '角色.出身'),
    'status': ('status', 'identity', 'role', 'character.status', 'character.identity', 'character.basic_info.status', 'character.basic_info.identity', 'character.cultivation_info.status', 'basic.status', 'profile.status', '身份', '定位', '角色.status', '角色.身份'),
}

PROFILE_LABELS = {
    'mathematics': '数学',
    'hacking': '黑客技术',
    'judo': '柔道',
    'shooting': '射击',
    'speed': '速度',
    'agility': '敏捷',
    'strength': '力量',
    'endurance': '耐力',
    'level': '水平',
    'start_age': '开始年龄',
    'specialties': '擅长',
    'experience': '经验',
    'skill': '能力',
    'additional': '补充',
    'height': '身高',
    'figure': '体型',
    'chest': '胸部',
    'skin': '皮肤',
}


def _character_layer(profile: dict) -> dict:
    character = profile.get('character', {}) if isinstance(profile, dict) else {}
    return character if isinstance(character, dict) else {}


def _compact_text(value) -> str:
    if value is None:
        return ''
    if isinstance(value, list):
        return '；'.join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _compact_text(item)
            if text:
                label = PROFILE_LABELS.get(str(key), '')
                parts.append(f'{label}={text}' if label else text)
        return '；'.join(parts)
    return str(value).strip()


def _append_bullets(lines: list[str], title: str, items: list[str], *, limit: int = 6) -> None:
    clean = []
    for item in items:
        text = str(item or '').strip()
        if text and text not in clean:
            clean.append(text)
    if not clean:
        return
    lines.extend([f'## {title}', *[f'- {item}' for item in clean[:limit]], ''])


def _profile_list_items(value, *, label_keys: tuple[str, ...] = ('name', 'trait', 'title'), detail_keys: tuple[str, ...] = ('detail', 'description', 'level')) -> list[str]:
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value:
        if isinstance(item, dict):
            label = next((str(item.get(key, '') or '').strip() for key in label_keys if str(item.get(key, '') or '').strip()), '')
            details = []
            for key in detail_keys:
                text = _compact_text(item.get(key))
                if text and text != label:
                    details.append(text)
            if label and details:
                items.append(f'{label}：{"；".join(details)}')
            elif label:
                items.append(label)
            else:
                text = _compact_text(item)
                if text:
                    items.append(text)
        else:
            text = _compact_text(item)
            if text:
                items.append(text)
    return items


def _nested_character_runtime_sections(profile: dict) -> list[str]:
    character = _character_layer(profile)
    if not character:
        return []
    lines: list[str] = []

    appearance = character.get('appearance', {}) if isinstance(character.get('appearance', {}), dict) else {}
    body = appearance.get('body', {}) if isinstance(appearance.get('body', {}), dict) else {}
    clothing = appearance.get('clothing', {}) if isinstance(appearance.get('clothing', {}), dict) else {}
    appearance_items = []
    hair = _compact_text(appearance.get('hair'))
    eyes = _compact_text(appearance.get('eyes'))
    face = _compact_text(appearance.get('face'))
    body_text = _compact_text({
        'height': body.get('height'),
        'figure': body.get('figure'),
        'chest': body.get('chest'),
        'skin': body.get('skin'),
    })
    clothing_text = _compact_text(clothing)
    for item in (hair, eyes, face, body_text, clothing_text):
        if item:
            appearance_items.append(item)
    _append_bullets(lines, '角色卡外貌锚点', appearance_items, limit=5)

    abilities = character.get('abilities', {}) if isinstance(character.get('abilities', {}), dict) else {}
    ability_items = []
    for group_key in ('talents', 'combat'):
        group = abilities.get(group_key, {}) if isinstance(abilities.get(group_key, {}), dict) else {}
        for name, detail in group.items():
            text = _compact_text(detail)
            if text:
                ability_items.append(f'{PROFILE_LABELS.get(str(name), str(name))}：{text}')
    physical_stats = abilities.get('physical_stats', {}) if isinstance(abilities.get('physical_stats', {}), dict) else {}
    physical_text = _compact_text(physical_stats)
    if physical_text:
        ability_items.append(f'身体素质：{physical_text}')
    cultivation = character.get('cultivation_info', {}) if isinstance(character.get('cultivation_info', {}), dict) else {}
    cultivation_items = []
    for key, label in (('realm', '境界'), ('status', '身份'), ('cultivation_path', '修炼路径'), ('spirit_root', '灵根')):
        text = _compact_text(cultivation.get(key))
        if text:
            cultivation_items.append(f'{label}：{text}')
    ability_items.extend(cultivation_items)
    ability_items.extend(_profile_list_items(character.get('skills', [])))
    _append_bullets(lines, '角色卡稳定能力', ability_items, limit=8)

    nested_traits = _profile_list_items(character.get('personality', []), label_keys=('trait', 'name', 'title'))
    _append_bullets(lines, '角色卡性格锚点', nested_traits, limit=6)

    weakness_items = [_compact_text(item) for item in character.get('weaknesses', [])] if isinstance(character.get('weaknesses', []), list) else []
    _append_bullets(lines, '角色卡身体短板', weakness_items, limit=6)

    disguise = character.get('disguise', {}) if isinstance(character.get('disguise', {}), dict) else {}
    disguise_items = []
    if disguise.get('level'):
        disguise_items.append(f"伪装水平：{_compact_text(disguise.get('level'))}")
    for key in ('techniques', 'weaknesses'):
        value = disguise.get(key, [])
        if isinstance(value, list):
            disguise_items.extend(_compact_text(item) for item in value)
        else:
            text = _compact_text(value)
            if text:
                disguise_items.append(text)
    _append_bullets(lines, '角色卡伪装约束', disguise_items, limit=8)

    personality = character.get('personality', {}) if isinstance(character.get('personality', {}), dict) else {}
    trait_items = []
    for key in ('traits', 'hidden_traits'):
        value = personality.get(key, [])
        if isinstance(value, list):
            trait_items.extend(_compact_text(item) for item in value)
    _append_bullets(lines, '角色卡性格锚点', trait_items, limit=6)

    background_items = [_compact_text(item) for item in character.get('background', [])] if isinstance(character.get('background', []), list) else []
    _append_bullets(lines, '角色卡背景线索', background_items, limit=6)

    goal_items = [_compact_text(item) for item in character.get('goals', [])] if isinstance(character.get('goals', []), list) else []
    _append_bullets(lines, '角色卡剧情目标', goal_items, limit=5)
    return lines


def _value_at_path(data: dict, dotted_path: str):
    current = data
    for part in dotted_path.split('.'):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _is_profile_scalar(value) -> bool:
    return isinstance(value, str | int | float) and not isinstance(value, bool)


def normalize_player_profile(profile: dict) -> dict:
    if not isinstance(profile, dict) or not profile:
        return {}

    normalized = copy.deepcopy(profile)
    for canonical_key, aliases in PROFILE_FIELD_ALIASES.items():
        if _is_profile_scalar(normalized.get(canonical_key)) and str(normalized.get(canonical_key)).strip():
            continue
        for alias in aliases:
            value = _value_at_path(profile, alias)
            if _is_profile_scalar(value) and str(value).strip():
                normalized[canonical_key] = value
                break

    if not str(normalized.get('courtesyName', '') or '').strip() and str(normalized.get('name', '') or '').strip():
        normalized['courtesyName'] = normalized['name']
    return normalized


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _merge_value(base, override):
    if isinstance(base, dict) and isinstance(override, dict):
        merged = copy.deepcopy(base)
        for key, value in override.items():
            merged[key] = _merge_value(merged.get(key), value)
        return merged
    if isinstance(base, list) and isinstance(override, list):
        return copy.deepcopy(override)
    return copy.deepcopy(override)


def base_player_profile_path() -> Path:
    layered = _user_profile_root() / 'player-profile.base.json'
    if layered.exists():
        return layered
    legacy = _user_profile_root() / 'player-profile.json'
    if legacy.exists():
        return legacy
    if _is_multi_user_request_context() or _is_character_override_active():
        return layered
    shared_base = _shared_path('player-profile.base.json')
    if shared_base.exists():
        return shared_base
    return _shared_path('player-profile.json')


def character_player_profile_override_path() -> Path:
    return _character_source_root() / 'player-profile.override.json'


def base_player_profile_source_path() -> Path:
    return _user_profile_root() / 'player-profile.source.md'


def character_player_profile_override_source_path() -> Path:
    return _character_source_root() / 'player-profile.override.source.md'


def read_profile_source(path: Path) -> str:
    try:
        return path.read_text(encoding='utf-8') if path.exists() else ''
    except Exception:
        return ''


def load_base_player_profile() -> dict:
    raw = _read_json(base_player_profile_path())
    if is_unified_player_profile(raw):
        try:
            return validate_unified_player_profile(raw)
        except ValueError:
            return empty_unified_player_profile()
    return normalize_player_profile(raw)


def save_base_player_profile(payload: dict) -> Path:
    payload = validate_unified_player_profile(payload)
    path = _user_profile_root() / 'player-profile.base.json'
    with PLAYER_PROFILE_LOCK:
        atomic_write_json(path, payload)
    return path


def save_base_player_profile_source(text: str) -> Path:
    path = base_player_profile_source_path()
    with PLAYER_PROFILE_LOCK:
        atomic_write_bytes(path, str(text or '').encode('utf-8'))
    return path


def user_avatar_dir() -> Path:
    return _user_profile_root() / 'assets'


def resolve_user_avatar_path() -> Path | None:
    root = user_avatar_dir()
    if not root.exists():
        return None
    for name in ('avatar.png', 'avatar.jpg', 'avatar.jpeg', 'avatar.webp'):
        candidate = root / name
        if candidate.exists():
            return candidate
    return None


def save_user_avatar(filename: str, content: bytes) -> Path:
    suffix = Path(filename or '').suffix.lower()
    if suffix not in {'.png', '.jpg', '.jpeg', '.webp'}:
        raise ValueError('avatar file must be png, jpg, jpeg, or webp')
    with PLAYER_PROFILE_LOCK:
        root = user_avatar_dir()
        root.mkdir(parents=True, exist_ok=True)
        for existing in root.glob('avatar.*'):
            try:
                existing.unlink()
            except Exception:
                pass
        target = root / f'avatar{suffix}'
        atomic_write_bytes(target, content)
    return target


def delete_user_avatar() -> bool:
    with PLAYER_PROFILE_LOCK:
        path = resolve_user_avatar_path()
        if not path:
            return False
        try:
            path.unlink()
            return True
        except Exception:
            return False


def load_character_player_profile_override() -> dict:
    raw = _read_json(character_player_profile_override_path())
    if is_unified_player_profile(raw):
        try:
            return validate_unified_player_profile(raw)
        except ValueError:
            return empty_unified_player_profile()
    return normalize_player_profile(raw)


def load_effective_player_profile() -> dict:
    base = load_base_player_profile()
    override = load_character_player_profile_override()
    if not override:
        return base
    if not base:
        return override
    if is_unified_player_profile(base) or is_unified_player_profile(override):
        return merge_unified_player_profiles(
            base if is_unified_player_profile(base) else legacy_profile_to_unified(base),
            override if is_unified_player_profile(override) else legacy_profile_to_unified(override),
        )
    merged = _merge_value(base, override)
    if isinstance(merged, dict) and is_unified_player_profile(merged):
        return validate_unified_player_profile(merged)
    return normalize_player_profile(merged if isinstance(merged, dict) else {})


def save_character_player_profile_override(payload: dict) -> Path:
    payload = validate_unified_player_profile(payload)
    path = character_player_profile_override_path()
    with PLAYER_PROFILE_LOCK:
        atomic_write_json(path, payload)
    return path


def save_character_player_profile_override_source(text: str) -> Path:
    path = character_player_profile_override_source_path()
    with PLAYER_PROFILE_LOCK:
        atomic_write_bytes(path, str(text or '').encode('utf-8'))
    return path


def build_player_profile_override_draft(character_core: dict, *, base_profile: dict | None = None) -> dict:
    title = str((character_core.get('name') if isinstance(character_core, dict) else '') or '').strip()
    draft = empty_unified_player_profile()
    draft['worldAdaptation'] = [
        f'已为《{title or "当前角色卡"}》生成一份初始主角特化草稿。',
        '若当前题材与基础档案差异较大，建议手动补充身份、出身与世界适配说明。',
    ]
    return draft


PROFILE_NORMALIZE_SYSTEM = '''你是 Threadloom 的玩家档案整理器。你的任务是把用户给出的自然语言设定整理为固定 JSON schema。
硬性要求：
- 只输出 JSON object，不要 Markdown，不要解释。
- 不得编造用户没有提供的事实；不确定就留空字符串或空数组。
- 保持用户原意，不要改写成另一种人设。
- 顶层字段只能是：schemaVersion, identity, appearance, abilities, personality, preferences, background, psychology, worldAdaptation, privateBoundaries。
- identity 只能包含：name, courtesyName, gender, age, origin, status，值必须是字符串。
- 其他字段都必须是字符串数组；数组项要短、清楚、可直接给叙事模型使用。
'''


def normalize_profile_text_with_keeper_llm(source_text: str, *, existing_profile: dict | None = None) -> tuple[dict, dict]:
    try:
        from .local_model_client import parse_json_response
        from .model_client import call_model
        from .model_config import resolve_provider_model
    except ImportError:
        from local_model_client import parse_json_response
        from model_client import call_model
        from model_config import resolve_provider_model

    text = str(source_text or '').strip()
    existing = validate_unified_player_profile(existing_profile) if isinstance(existing_profile, dict) and existing_profile else empty_unified_player_profile()
    if not text:
        return existing, {'provider_used': 'empty', 'model_usage': None}
    model_cfg = resolve_provider_model('state_keeper')
    model_cfg = dict(model_cfg)
    model_cfg['stream'] = False
    model_cfg['response_format'] = {'type': 'json_object'}
    model_cfg['max_output_tokens'] = max(int(model_cfg.get('max_output_tokens', 0) or 0), 1400)
    schema = empty_unified_player_profile()
    user_prompt = json.dumps({
        'schema': schema,
        'existing_profile': existing,
        'source_text': text,
    }, ensure_ascii=False, indent=2)
    reply, usage = call_model(model_cfg, PROFILE_NORMALIZE_SYSTEM, user_prompt)
    payload = parse_json_response(reply)
    profile = validate_unified_player_profile(payload)
    return profile, {'provider_used': 'llm', 'model_usage': usage}


def render_player_profile_markdown(profile: dict) -> str:
    if not isinstance(profile, dict) or not profile:
        return ''
    if is_unified_player_profile(profile):
        return render_unified_player_profile_markdown(profile)
    lines = ['# 玩家档案', '']

    basics = []
    field_labels = [
        ('name', '名字'),
        ('courtesyName', '常用称呼'),
        ('gender', '性别'),
        ('age', '年龄'),
        ('birthday', '生辰'),
        ('height', '身量'),
        ('origin', '出身'),
        ('status', '身份'),
    ]
    for key, label in field_labels:
        value = profile.get(key)
        text = str(value).strip() if value is not None else ''
        if text:
            basics.append(f'- {label}：{text}')
    if basics:
        lines.extend(['## 基本信息', *basics, ''])

    appearance = profile.get('appearance', {}) if isinstance(profile.get('appearance', {}), dict) else {}
    appearance_parts = [str(appearance.get(key, '') or '').strip() for key in ('hair', 'skin', 'eyes', 'bearing') if str(appearance.get(key, '') or '').strip()]
    if appearance_parts:
        lines.extend(['## 外貌', '，'.join(appearance_parts), ''])

    skills = profile.get('skills', []) if isinstance(profile.get('skills', []), list) else []
    if skills:
        lines.append('## 所长')
        for item in skills:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', '') or '').strip()
            detail = str(item.get('detail', '') or '').strip()
            if name or detail:
                lines.append(f"- {name or '未命名'}：{detail or '待确认'}")
        lines.append('')

    personality = profile.get('personality', []) if isinstance(profile.get('personality', []), list) else []
    if personality:
        lines.append('## 性情')
        for item in personality:
            if not isinstance(item, dict):
                continue
            trait = str(item.get('trait', '') or '').strip()
            detail = str(item.get('detail', '') or '').strip()
            if trait or detail:
                lines.append(f"- {trait or '特征'}：{detail or '待确认'}")
        lines.append('')

    interests = [str(item).strip() for item in (profile.get('interests', []) or []) if str(item).strip()]
    if interests:
        lines.extend(['## 喜好', *[f'- {item}' for item in interests], ''])

    style = profile.get('style', {}) if isinstance(profile.get('style', {}), dict) else {}
    style_lines = []
    if str(style.get('dailyWear', '') or '').strip():
        style_lines.append(f"- 日常：{str(style.get('dailyWear')).strip()}")
    if str(style.get('formalWear', '') or '').strip():
        style_lines.append(f"- 正式场合：{str(style.get('formalWear')).strip()}")
    if style_lines:
        lines.extend(['## 穿着风格', *style_lines, ''])

    background = profile.get('background', {}) if isinstance(profile.get('background', {}), dict) else {}
    background_lines = []
    for key, label in (('family', '家庭'), ('upbringing', '成长'), ('education', '所学')):
        value = str(background.get(key, '') or '').strip()
        if value:
            background_lines.append(f'- {label}：{value}')
    if background_lines:
        lines.extend(['## 背景', *background_lines, ''])

    psychology = profile.get('psychology', {}) if isinstance(profile.get('psychology', {}), dict) else {}
    psychology_lines = []
    for key, label in (('core', '心理底色'), ('motivation', '驱动力'), ('storyUse', '剧情适配')):
        value = str(psychology.get(key, '') or '').strip()
        if value:
            psychology_lines.append(f'- {label}：{value}')
    if psychology_lines:
        lines.extend(['## 心理与剧情', *psychology_lines, ''])

    adaptation = profile.get('worldAdaptation', {}) if isinstance(profile.get('worldAdaptation', {}), dict) else {}
    notes = [str(item).strip() for item in (adaptation.get('notes', []) or []) if str(item).strip()]
    if notes:
        lines.extend(['## 世界适配说明', *[f'- {item}' for item in notes], ''])

    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines) + '\n'


def render_runtime_player_profile_markdown(profile: dict) -> str:
    if not isinstance(profile, dict) or not profile:
        return ''
    if is_unified_player_profile(profile):
        return render_unified_player_profile_markdown(profile)
    lines = ['# 玩家档案', '']

    basics = []
    for key, label in (
        ('name', '名字'),
        ('courtesyName', '常用称呼'),
        ('age', '年龄'),
        ('gender', '性别'),
        ('height', '身高'),
        ('origin', '出身'),
        ('status', '身份'),
    ):
        value = str(profile.get(key, '') or '').strip()
        if value:
            basics.append(f'- {label}：{value}')
    if basics:
        lines.extend(['## 核心身份', *basics, ''])

    nested_character = _character_layer(profile)
    nested_basic = nested_character.get('basic_info', {}) if isinstance(nested_character.get('basic_info', {}), dict) else {}
    nested_basics = []
    for key, label in (('race', '种族'),):
        value = str(nested_basic.get(key, '') or '').strip()
        if value and not str(profile.get(key, '') or '').strip():
            nested_basics.append(f'- {label}：{value}')
    if nested_basics:
        lines.extend(['## 核心身份补充', *nested_basics, ''])

    nested_has_skills = isinstance(nested_character.get('skills', []), list) and bool(nested_character.get('skills', []))
    skills = [] if nested_has_skills else (profile.get('skills', []) if isinstance(profile.get('skills', []), list) else [])
    skill_lines = []
    for item in skills[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '') or '').strip()
        detail = str(item.get('detail', '') or '').strip()
        if name:
            skill_lines.append(f"- {name}：{detail[:70] + '...' if len(detail) > 70 else detail}")
    if skill_lines:
        lines.extend(['## 稳定能力', *skill_lines, ''])

    nested_has_personality = isinstance(nested_character.get('personality', []), list) and bool(nested_character.get('personality', []))
    personality = [] if nested_has_personality else (profile.get('personality', []) if isinstance(profile.get('personality', []), list) else [])
    trait_lines = []
    for item in personality[:4]:
        if not isinstance(item, dict):
            continue
        trait = str(item.get('trait', '') or '').strip()
        detail = str(item.get('detail', '') or '').strip()
        if trait:
            trait_lines.append(f"- {trait}：{detail[:70] + '...' if len(detail) > 70 else detail}")
    if trait_lines:
        lines.extend(['## 性格锚点', *trait_lines, ''])

    psychology = profile.get('psychology', {}) if isinstance(profile.get('psychology', {}), dict) else {}
    story_use = str(psychology.get('storyUse', '') or '').strip()
    if story_use:
        lines.extend(['## 剧情适配', f'- {story_use}', ''])

    adaptation = profile.get('worldAdaptation', {}) if isinstance(profile.get('worldAdaptation', {}), dict) else {}
    notes = [str(item).strip() for item in (adaptation.get('notes', []) or []) if str(item).strip()][:3]
    if notes:
        lines.extend(['## 世界适配说明', *[f'- {item}' for item in notes], ''])

    lines.extend(_nested_character_runtime_sections(profile))

    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines) + '\n'
