#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path

try:
    from .paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root
except ImportError:
    from paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root


PROFILE_FIELD_ALIASES = {
    'name': (
        'name',
        'character.name',
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
        'basic.birthday',
        'profile.birthday',
        '生辰',
        '生日',
        '角色.birthday',
        '角色.生辰',
        '角色.生日',
    ),
    'height': ('height', 'character.height', 'character.appearance.body.height', 'basic.height', 'profile.height', '身高', '身量', '角色.height', '角色.身高', '角色.身量'),
    'origin': ('origin', 'hometown', 'birthplace', 'character.origin', 'basic.origin', 'profile.origin', '出身', '籍贯', '来历', '角色.origin', '角色.出身'),
    'status': ('status', 'identity', 'role', 'character.status', 'basic.status', 'profile.status', '身份', '定位', '角色.status', '角色.身份'),
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
    _append_bullets(lines, '角色卡稳定能力', ability_items, limit=6)

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
    layered = user_profile_root() / 'player-profile.base.json'
    if layered.exists():
        return layered
    legacy = user_profile_root() / 'player-profile.json'
    if legacy.exists():
        return legacy
    if is_multi_user_request_context() or is_character_override_active():
        return layered
    shared_base = shared_path('player-profile.base.json')
    if shared_base.exists():
        return shared_base
    return shared_path('player-profile.json')


def character_player_profile_override_path() -> Path:
    return character_source_root() / 'player-profile.override.json'


def load_base_player_profile() -> dict:
    return normalize_player_profile(_read_json(base_player_profile_path()))


def save_base_player_profile(payload: dict) -> Path:
    path = user_profile_root() / 'player-profile.base.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def user_avatar_dir() -> Path:
    return user_profile_root() / 'assets'


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
    root = user_avatar_dir()
    root.mkdir(parents=True, exist_ok=True)
    for existing in root.glob('avatar.*'):
        try:
            existing.unlink()
        except Exception:
            pass
    target = root / f'avatar{suffix}'
    target.write_bytes(content)
    return target


def delete_user_avatar() -> bool:
    path = resolve_user_avatar_path()
    if not path:
        return False
    try:
        path.unlink()
        return True
    except Exception:
        return False


def load_character_player_profile_override() -> dict:
    return normalize_player_profile(_read_json(character_player_profile_override_path()))


def load_effective_player_profile() -> dict:
    base = load_base_player_profile()
    override = load_character_player_profile_override()
    if not override:
        return base
    if not base:
        return override
    merged = _merge_value(base, override)
    return normalize_player_profile(merged if isinstance(merged, dict) else {})


def save_character_player_profile_override(payload: dict) -> Path:
    path = character_player_profile_override_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def build_player_profile_override_draft(character_core: dict, *, base_profile: dict | None = None) -> dict:
    title = str((character_core.get('name') if isinstance(character_core, dict) else '') or '').strip()
    draft: dict = {}

    draft.update({
        'worldAdaptation': {
            'notes': [
                f'已为《{title or "当前角色卡"}》生成一份初始主角特化草稿。',
                '若当前题材与基础档案差异较大，建议手动补充身份、出身与世界适配说明。',
            ]
        }
    })

    return draft


def render_player_profile_markdown(profile: dict) -> str:
    if not isinstance(profile, dict) or not profile:
        return ''
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

    skills = profile.get('skills', []) if isinstance(profile.get('skills', []), list) else []
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

    personality = profile.get('personality', []) if isinstance(profile.get('personality', []), list) else []
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
