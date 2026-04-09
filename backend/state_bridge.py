#!/usr/bin/env python3
"""Helpers for bridging markdown workspace state into Threadloom JSON state."""

from __future__ import annotations

from typing import Iterable

try:
    from .continuity_hints import match_continuity_hint
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name
except ImportError:
    from continuity_hints import match_continuity_hint
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name


def extract_section_lines(text: str, section: str) -> list[str]:
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if line.startswith('## '):
            in_section = line.strip() == f'## {section}'
            if in_section:
                continue
            if out:
                break
        elif in_section:
            out.append(line)
    return out


def extract_prefixed_value(text: str, prefix: str, fallback: str = '待确认') -> str:
    for line in text.splitlines():
        if line.startswith(prefix):
            value = line.split('：', 1)[1].strip()
            return value.rstrip('。') or fallback
    return fallback


def extract_named_entries(text: str, section: str) -> list[str]:
    names: list[str] = []
    ignored = ('暂无', '参考模板', '单个活跃 NPC', '当前暂无', '最近玩家动作')
    for line in extract_section_lines(text, section):
        if not (line.startswith('- ') and '：' in line):
            continue
        name = line[2:].split('：', 1)[0].strip()
        if not name or any(name.startswith(prefix) for prefix in ignored):
            continue
        if name not in names:
            names.append(name)
    return names


def extract_list_entries(text: str, section: str) -> list[str]:
    items: list[str] = []
    for line in extract_section_lines(text, section):
        if not line.startswith('- '):
            continue
        value = line[2:].strip()
        if not value or value.startswith('暂无'):
            continue
        if value not in items:
            items.append(value.rstrip('。') + ('。' if not value.endswith('。') else ''))
    return items


def extract_scene_entities(text: str) -> list[dict]:
    lines = extract_section_lines(text, 'Scene Entities')
    entities: list[dict] = []
    current: dict | None = None
    for line in lines:
        if line.startswith('- entity_id:'):
            if current:
                entities.append(current)
            current = {
                'entity_id': line.split(':', 1)[1].strip(),
                'primary_label': '',
                'aliases': [],
                'role_label': '待确认',
                'onstage': False,
                'possible_link': None,
            }
            continue
        if current is None:
            continue
        stripped = line.strip()
        if stripped.startswith('- 当前主称呼：'):
            current['primary_label'] = stripped.split('：', 1)[1].strip()
        elif stripped.startswith('- 其他称呼：'):
            raw = stripped.split('：', 1)[1].strip()
            aliases = [item.strip() for item in raw.split('/') if item.strip()]
            current['aliases'] = aliases
        elif stripped.startswith('- 身份标签：'):
            current['role_label'] = stripped.split('：', 1)[1].strip()
        elif stripped.startswith('- 是否当前在场：'):
            current['onstage'] = stripped.split('：', 1)[1].strip().startswith('是')
        elif stripped.startswith('- 可能关联：'):
            current['possible_link'] = stripped.split('：', 1)[1].strip()
    if current:
        entities.append(current)
    return entities


def infer_role_label(name: str) -> str:
    if name == '师兄':
        return '同行伤者 / 师兄'
    if name == '褐袍人':
        return '褐袍同行者'
    if name == '掌柜':
        return '掌柜'
    if name == '伙计':
        return '伙计'
    if name == '老汉':
        return '掌舵老汉'
    if name == '船夫':
        return '船夫'
    if name == '皂衣人':
        return '镇北司皂衣人'
    if name == '高个皂衣人':
        return '镇北司高个皂衣人'
    if name == '少年':
        return '抱包少年'
    if name == '姓苏的':
        return '待确认公子 / 苏姓青年'
    return '待确认'


def dedupe_names(items: Iterable[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    for item in items:
        name = sanitize_runtime_name(item)
        if not name or is_protagonist_name(name) or name in out:
            continue
        out.append(name)
        if limit is not None and len(out) >= limit:
            break
    return out


def normalize_text_list(items: Iterable[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    for item in items:
        value = (item or '').strip()
        if not value or value == '待确认' or value in out:
            continue
        if not value.endswith('。') and not value.endswith('！') and not value.endswith('？'):
            value = value + '。'
        out.append(value)
        if limit is not None and len(out) >= limit:
            break
    return out


def _entity_numeric_id(entity_id: str) -> int:
    try:
        return int(entity_id.rsplit('_', 1)[1])
    except Exception:
        return 0


def _entity_name_set(entity: dict) -> set[str]:
    names = set()
    primary = str((entity or {}).get('primary_label', '') or '').strip()
    if primary:
        names.add(primary)
    for alias in (entity or {}).get('aliases', []) or []:
        alias_text = str(alias or '').strip()
        if alias_text:
            names.add(alias_text)
    return names


def _entity_match_score(prev: dict, item: dict) -> float:
    prev_names = _entity_name_set(prev)
    item_names = _entity_name_set(item)
    name_overlap = 1.0 if prev_names & item_names else 0.0
    role_prev = str((prev or {}).get('role_label', '') or '').strip()
    role_item = str((item or {}).get('role_label', '') or '').strip()
    role_score = 0.7 if role_prev and role_item and role_prev == role_item else 0.0
    link_prev = str((prev or {}).get('possible_link', '') or '').strip()
    link_item = str((item or {}).get('possible_link', '') or '').strip()
    link_score = 0.2 if link_prev and link_item and link_prev == link_item else 0.0
    return name_overlap + role_score + link_score


def _find_matching_prev_entity(prev_entities: list[dict], item: dict, used_ids: set[str]) -> dict | None:
    best = None
    best_score = 0.0
    for prev in prev_entities or []:
        prev_id = str((prev or {}).get('entity_id', '') or '')
        if prev_id and prev_id in used_ids:
            continue
        score = _entity_match_score(prev, item)
        if score > best_score:
            best = prev
            best_score = score
    return best if best_score >= 0.7 else None


def _find_important_entity(item: dict, important_npcs: list[dict], prev_entities: list[dict], used_ids: set[str]) -> dict | None:
    primary = str((item or {}).get('primary_label', '') or '').strip()
    aliases = _entity_name_set(item)
    important_keys = {
        str(entry.get('primary_label', '') or '').strip()
        for entry in important_npcs or []
        if isinstance(entry, dict) and entry.get('locked')
    }
    if not (primary in important_keys or aliases & important_keys):
        return None
    return _find_matching_prev_entity(prev_entities, item, used_ids)


def _apply_continuity_hint(item: dict, continuity_hints: list[dict]) -> dict:
    hint = match_continuity_hint(item.get('primary_label', ''), item.get('aliases', []), continuity_hints)
    if not hint:
        return item
    updated = dict(item)
    updated['primary_label'] = hint.get('primary_label', updated.get('primary_label', ''))
    updated['aliases'] = sorted(set((updated.get('aliases') or []) + (hint.get('aliases') or []) + [updated['primary_label']]))
    if hint.get('role_label'):
        updated['role_label'] = hint['role_label']
    return updated


def merge_scene_entities(prev_entities: list[dict], candidate_entities: list[dict], onstage_names: list[str], important_npcs: list[dict] | None = None, continuity_hints: list[dict] | None = None) -> list[dict]:
    prev_by_name: dict[str, dict] = {}
    for entity in prev_entities or []:
        primary = (entity.get('primary_label') or '').strip()
        if primary and primary not in prev_by_name:
            prev_by_name[primary] = entity

    max_id = max((_entity_numeric_id((entity or {}).get('entity_id', '')) for entity in prev_entities or []), default=0)
    merged: list[dict] = []
    used_prev_ids: set[str] = set()
    candidate_pool = candidate_entities or fallback_scene_entities(onstage_names)

    for item in candidate_pool:
        item = _apply_continuity_hint(item, continuity_hints or [])
        primary = (item.get('primary_label') or '').strip()
        if not primary:
            continue
        prev = prev_by_name.get(primary)
        if prev is None:
            prev = _find_important_entity(item, important_npcs or [], prev_entities, used_prev_ids)
        if prev is None:
            prev = _find_matching_prev_entity(prev_entities, item, used_prev_ids)
        aliases = dedupe_names((item.get('aliases') or []) + (prev.get('aliases') or [] if prev else []) + [primary])
        if prev:
            entity_id = prev.get('entity_id', '') or f'scene_npc_{max_id + 1:02d}'
            if entity_id:
                used_prev_ids.add(entity_id)
        else:
            max_id += 1
            entity_id = f'scene_npc_{max_id:02d}'
        merged.append({
            'entity_id': entity_id,
            'primary_label': primary,
            'aliases': aliases,
            'role_label': (item.get('role_label') or (prev.get('role_label') if prev else '') or infer_role_label(primary) or '待确认').strip(),
            'onstage': primary in onstage_names,
            'possible_link': item.get('possible_link') if item.get('possible_link') is not None else (prev.get('possible_link') if prev else None),
        })

    for prev in prev_entities or []:
        prev_id = str((prev or {}).get('entity_id', '') or '')
        if prev_id and prev_id in used_prev_ids:
            continue
        primary = str((prev or {}).get('primary_label', '') or '').strip()
        if not primary:
            continue
        merged.append({
            'entity_id': prev.get('entity_id', ''),
            'primary_label': primary,
            'aliases': dedupe_names((prev.get('aliases') or []) + [primary]),
            'role_label': str(prev.get('role_label', '') or infer_role_label(primary) or '待确认').strip(),
            'onstage': False,
            'possible_link': prev.get('possible_link'),
        })

    if not merged and onstage_names:
        return fallback_scene_entities(onstage_names)
    return merged


def normalize_state_dict(state: dict, prev_state: dict | None = None, session_id: str | None = None) -> dict:
    prev = prev_state or {}
    current = dict(state or {})

    for key in ['time', 'location', 'main_event', 'scene_core', 'immediate_goal']:
        value = current.get(key)
        if not isinstance(value, str) or not value.strip():
            current[key] = prev.get(key, '待确认')
        else:
            current[key] = value.strip()

    current['onstage_npcs'] = dedupe_names(current.get('onstage_npcs', prev.get('onstage_npcs', [])), limit=6)
    current['relevant_npcs'] = dedupe_names(
        [name for name in current.get('relevant_npcs', prev.get('relevant_npcs', [])) if name not in current['onstage_npcs']],
        limit=6,
    )
    current['immediate_risks'] = normalize_text_list(current.get('immediate_risks', prev.get('immediate_risks', [])), limit=4)
    current['carryover_clues'] = normalize_text_list(current.get('carryover_clues', prev.get('carryover_clues', [])), limit=4)
    current['scene_entities'] = merge_scene_entities(
        prev.get('scene_entities', []),
        current.get('scene_entities', []),
        current['onstage_npcs'],
        current.get('important_npcs', prev.get('important_npcs', [])),
        current.get('continuity_hints', prev.get('continuity_hints', [])),
    )
    arbiter_signals = current.get('arbiter_signals', prev.get('arbiter_signals', {}))
    if not isinstance(arbiter_signals, dict):
        arbiter_signals = prev.get('arbiter_signals', {}) if isinstance(prev.get('arbiter_signals', {}), dict) else {}
    current['arbiter_signals'] = arbiter_signals
    state_keeper_diagnostics = current.get('state_keeper_diagnostics', prev.get('state_keeper_diagnostics', {}))
    if not isinstance(state_keeper_diagnostics, dict):
        state_keeper_diagnostics = prev.get('state_keeper_diagnostics', {}) if isinstance(prev.get('state_keeper_diagnostics', {}), dict) else {}
    current['state_keeper_diagnostics'] = state_keeper_diagnostics
    active_threads = current.get('active_threads', prev.get('active_threads', []))
    if not isinstance(active_threads, list):
        active_threads = prev.get('active_threads', []) if isinstance(prev.get('active_threads', []), list) else []
    current['active_threads'] = active_threads
    important_npcs = current.get('important_npcs', prev.get('important_npcs', []))
    if not isinstance(important_npcs, list):
        important_npcs = prev.get('important_npcs', []) if isinstance(prev.get('important_npcs', []), list) else []
    current['important_npcs'] = important_npcs
    continuity_hints = current.get('continuity_hints', prev.get('continuity_hints', []))
    if not isinstance(continuity_hints, list):
        continuity_hints = prev.get('continuity_hints', []) if isinstance(prev.get('continuity_hints', []), list) else []
    current['continuity_hints'] = continuity_hints
    current['opening_mode'] = str(current.get('opening_mode', prev.get('opening_mode', '')) or prev.get('opening_mode', '') or '')
    current['opening_choice'] = current.get('opening_choice', prev.get('opening_choice'))
    current['opening_resolved'] = bool(current.get('opening_resolved', prev.get('opening_resolved', False)))
    current['opening_started'] = bool(current.get('opening_started', prev.get('opening_started', False)))

    if session_id:
        current['session_id'] = session_id
    elif prev.get('session_id'):
        current['session_id'] = prev['session_id']
    return current


def fallback_scene_entities(names: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    for idx, name in enumerate(names, start=1):
        out.append({
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': name,
            'aliases': [name],
            'role_label': infer_role_label(name),
            'onstage': True,
            'possible_link': None,
        })
    return out


def parse_root_state_markdown(text: str, session_id: str) -> dict:
    onstage = extract_named_entries(text, 'Onstage NPCs')
    relevant = extract_named_entries(text, 'Relevant NPCs')

    entities = extract_scene_entities(text)
    if not entities and onstage:
        entities = fallback_scene_entities(onstage)

    immediate_goal = extract_prefixed_value(text, '- Immediate Goal', '')
    if immediate_goal == '待确认':
        immediate_goal = extract_prefixed_value(text, '- 当前直接目标：', '')
    if not immediate_goal:
        section_items = extract_list_entries(text, 'Immediate Goal')
        immediate_goal = section_items[0] if section_items else '待确认'

    return {
        'session_id': session_id,
        'time': extract_prefixed_value(text, '- 当前时间：'),
        'location': extract_prefixed_value(text, '- 当前地点：'),
        'main_event': extract_prefixed_value(text, '- 当前主事件：'),
        'scene_core': extract_prefixed_value(text, '- 当前局势核心：'),
        'scene_entities': entities,
        'onstage_npcs': onstage,
        'relevant_npcs': relevant,
        'immediate_goal': immediate_goal or '待确认',
        'immediate_risks': extract_list_entries(text, 'Immediate Risks'),
        'carryover_clues': extract_list_entries(text, 'Carryover Clues'),
    }
