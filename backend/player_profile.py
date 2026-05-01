#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
from pathlib import Path

try:
    from .paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root
except ImportError:
    from paths import character_source_root, is_character_override_active, is_multi_user_request_context, shared_path, user_profile_root


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
    return _read_json(base_player_profile_path())


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
    return _read_json(character_player_profile_override_path())


def load_effective_player_profile() -> dict:
    base = load_base_player_profile()
    override = load_character_player_profile_override()
    if not override:
        return base
    if not base:
        return override
    return _merge_value(base, override)


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
        ('origin', '出身'),
        ('status', '身份'),
    ):
        value = str(profile.get(key, '') or '').strip()
        if value:
            basics.append(f'- {label}：{value}')
    if basics:
        lines.extend(['## 核心身份', *basics, ''])

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

    while lines and not lines[-1].strip():
        lines.pop()
    return '\n'.join(lines) + '\n'
