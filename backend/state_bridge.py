#!/usr/bin/env python3
"""Helpers for bridging markdown workspace state into Threadloom JSON state."""

from __future__ import annotations

import re
from typing import Iterable

try:
    from .continuity_hints import match_continuity_hint
    from .character_assets import load_system_npcs
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names
    from .card_hints import get_known_npc_role
except ImportError:
    from continuity_hints import match_continuity_hint
    from character_assets import load_system_npcs
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names
    from card_hints import get_known_npc_role


STRUCTURED_NAME_RE = re.compile(r'[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?')
NON_PERSON_SUFFIXES = ('场', '区', '室', '楼', '廊', '门', '路', '馆', '堂', '院', '厅', '阁', '府', '宫', '殿', '街', '巷', '亭', '轩', '井', '墙', '山')
NON_PERSON_TOKENS = {
    '轻功', '自保', '一声', '规则', '结论', '现象', '世界', '逻辑', '认知', '交互', '概念', '目标', '问题', '决定',
    '对话', '关系', '后续', '物理', '错误', '能力', '剧情', '局势', '线索', '风险', '客厅',
}


def _thread_key_from_label(kind: str, label: str) -> str:
    text = ' '.join(str(label or '').split()).strip()
    text = re.sub(r'[，。、“”‘’！？：:；,.!?()（）\[\]{}<>/\\-]+', '', text)
    text = text[:48] or 'unknown'
    return f'{kind}:{text}'


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
    card_role = get_known_npc_role(name)
    if card_role:
        return card_role
    system_npcs = load_system_npcs()
    for item in (system_npcs.get('items', []) or []):
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('name', ''))
        aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or [])]
        if name == primary or name in aliases:
            text = str(item.get('role_label', '') or '').strip()
            if text:
                return text
    return '待确认'


def infer_runtime_role_label(name: str, *, main_event: str = '', scene_core: str = '', active_threads: list[dict] | None = None, onstage: bool = False, relevant: bool = False) -> str:
    explicit = infer_role_label(name)
    if explicit and explicit != '待确认':
        return explicit
    thread_actors = set()
    for item in active_threads or []:
        if not isinstance(item, dict):
            continue
        for actor in item.get('actors', []) or []:
            actor_name = sanitize_runtime_name(actor)
            if actor_name:
                thread_actors.add(actor_name)
    text_parts = [str(main_event or ''), str(scene_core or '')]
    for item in active_threads or []:
        if not isinstance(item, dict):
            continue
        text_parts.extend(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
    text = ' '.join(part for part in text_parts if part)
    if name and (name in text or name in thread_actors):
        if name.endswith(('伯', '叔', '婶', '姨', '翁', '婆', '爷')):
            return '长辈协助者'
        if onstage:
            return '当前互动核心人物'
        if relevant:
            return '相关场景人物'
        return '当前场景人物'
    return '待确认'


def _choose_role_label(name: str, explicit_role: str = '', previous_role: str = '', *, main_event: str = '', scene_core: str = '', active_threads: list[dict] | None = None, onstage: bool = False, relevant: bool = False) -> str:
    explicit = str(explicit_role or '').strip()
    if explicit and explicit != '待确认':
        return explicit
    previous = str(previous_role or '').strip()
    if previous and previous != '待确认':
        return previous
    return infer_runtime_role_label(name, main_event=main_event, scene_core=scene_core, active_threads=active_threads, onstage=onstage, relevant=relevant)


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


def _is_degraded_entity_label(name: str) -> bool:
    text = str(name or '').strip()
    if not text:
        return True
    generic_patterns = (
        r'^皂衣人\d+$',
        r'^黑衣人\d+$',
        r'^蒙面人\d+$',
        r'^衙役\d+$',
        r'^官兵\d+$',
        r'^士兵\d+$',
        r'^路人\d+$',
        r'^守卫\d+$',
        r'^壮汉\d+$',
        r'^高个(?:男人|人)$',
        r'^矮个(?:男人|人)$',
        r'^年轻(?:男人|女子|人)$',
        r'^中年(?:男人|女子|人)$',
        r'^深衣青年$',
        r'^青年$',
    )
    return any(re.match(pattern, text) for pattern in generic_patterns)


def _canonical_entity_label(name: str) -> str:
    text = str(name or '').strip()
    if not text:
        return ''
    return text


def _prefer_stable_primary_label(item: dict, prev: dict | None) -> str:
    primary = str((item or {}).get('primary_label', '') or '').strip()
    prev_primary = str((prev or {}).get('primary_label', '') or '').strip()
    if prev_primary and (_is_degraded_entity_label(primary) or primary == '待确认') and not _is_degraded_entity_label(prev_primary):
        return prev_primary
    return primary


def _extract_descriptive_entity_names_from_history(prev_state: dict) -> list[str]:
    history_items = prev_state.get('_recent_history_items', []) if isinstance(prev_state.get('_recent_history_items', []), list) else []
    text = '\n'.join(
        str(item.get('content', '') or '')
        for item in history_items[-4:]
        if isinstance(item, dict) and item.get('role') == 'assistant'
    )
    if not text:
        return []
    patterns = [
        r'(高个皂衣人)',
        r'(靠后的皂衣人)',
        r'(前头一名皂衣人)',
        r'(后侧那名皂衣人)',
        r'(高个男人)',
        r'(深衣青年)',
    ]
    names: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, text):
            label = sanitize_runtime_name(match)
            if not label:
                continue
            if label not in names:
                names.append(label)
    return names


def _extract_descriptive_pairs_from_history(prev_state: dict) -> list[tuple[str, str]]:
    history_items = prev_state.get('_recent_history_items', []) if isinstance(prev_state.get('_recent_history_items', []), list) else []
    text = '\n'.join(
        str(item.get('content', '') or '')
        for item in history_items[-4:]
        if isinstance(item, dict) and item.get('role') == 'assistant'
    )
    if not text:
        return []
    pairs: list[tuple[str, str]] = []
    mapping_patterns = [
        (r'高个皂衣人', r'皂衣人1'),
        (r'靠后的皂衣人', r'皂衣人2'),
        (r'后侧那名皂衣人', r'皂衣人2'),
        (r'前头一名皂衣人', r'皂衣人1'),
    ]
    for concrete, degraded in mapping_patterns:
        if re.search(concrete, text):
            pairs.append((degraded, concrete))
    if re.search(r'深衣青年', text):
        pairs.append(('深衣青年', '深衣青年'))
    return pairs


def _promote_named_groups(candidate_pool: list[dict], prev_state: dict) -> list[dict]:
    descriptive_names = _extract_descriptive_entity_names_from_history(prev_state)
    if not descriptive_names:
        return candidate_pool
    promoted: list[dict] = []
    fallback_slots = [name for name in descriptive_names if name]
    slot_idx = 0
    for item in candidate_pool:
        if not isinstance(item, dict):
            promoted.append(item)
            continue
        current = dict(item)
        primary = sanitize_runtime_name(current.get('primary_label', ''))
        if _is_degraded_entity_label(primary) and slot_idx < len(fallback_slots):
            better = fallback_slots[slot_idx]
            slot_idx += 1
            current['primary_label'] = better
            aliases = current.get('aliases', []) if isinstance(current.get('aliases', []), list) else []
            current['aliases'] = dedupe_names(aliases + [better])
        promoted.append(current)
    return promoted


def _repair_existing_degraded_entities(entities: list[dict], prev_state: dict) -> list[dict]:
    pairs = _extract_descriptive_pairs_from_history(prev_state)
    if not pairs:
        return entities
    repaired: list[dict] = []
    for item in entities:
        if not isinstance(item, dict):
            repaired.append(item)
            continue
        current = dict(item)
        primary = sanitize_runtime_name(current.get('primary_label', ''))
        replacement = next((concrete for degraded, concrete in pairs if primary == degraded), '')
        if replacement:
            current['primary_label'] = replacement
            aliases = current.get('aliases', []) if isinstance(current.get('aliases', []), list) else []
            current['aliases'] = dedupe_names(aliases + [replacement])
        repaired.append(current)
    return repaired


def _recent_assistant_text(prev_state: dict, limit: int = 4) -> str:
    history_items = prev_state.get('_recent_history_items', []) if isinstance(prev_state.get('_recent_history_items', []), list) else []
    texts = [
        str(item.get('content', '') or '')
        for item in history_items[-limit:]
        if isinstance(item, dict) and item.get('role') == 'assistant'
    ]
    return '\n'.join(texts)


def _looks_like_continuity_name(name: str, text: str) -> bool:
    candidate = sanitize_runtime_name(name)
    if not candidate or is_protagonist_name(candidate):
        return False
    if len(candidate) < 2 or len(candidate) > 8:
        return False
    if any(ch.isdigit() for ch in candidate):
        return False
    if candidate in NON_PERSON_TOKENS:
        return False
    if candidate.endswith(NON_PERSON_SUFFIXES):
        return False
    if candidate.endswith(('上', '下', '里', '中', '前', '后', '旁', '外')):
        return False
    if '的' in candidate:
        return False
    patterns = [
        rf'{re.escape(candidate)}(?:说|问|笑|道|看|想|将|把|对|向|已|正|仍|又|判定|认为|解释|反驳)',
        rf'(?:对|向|和|与){re.escape(candidate)}',
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _recover_names_from_structure(current: dict, prev: dict) -> list[str]:
    if current.get('onstage_npcs') or current.get('scene_entities'):
        return []
    active_threads = current.get('active_threads', [])
    if not isinstance(active_threads, list):
        active_threads = []
    carryover_clues = current.get('carryover_clues', [])
    if not isinstance(carryover_clues, list):
        carryover_clues = []
    blocks = []
    blocks.extend(str(item or '') for item in carryover_clues)
    for item in active_threads:
        if not isinstance(item, dict):
            continue
        blocks.extend(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle'))
    text = '\n'.join(block for block in blocks if block)
    recovered: list[str] = []
    for match in STRUCTURED_NAME_RE.finditer(text):
        name = sanitize_runtime_name(match.group(0))
        if not _looks_like_continuity_name(name, text):
            continue
        if name not in recovered:
            recovered.append(name)
        if len(recovered) >= 3:
            break
    return recovered


def _recover_relevant_from_continuity(current: dict, prev: dict) -> list[str]:
    if current.get('onstage_npcs') or current.get('relevant_npcs'):
        return current.get('relevant_npcs', [])
    important_npcs = current.get('important_npcs', prev.get('important_npcs', []))
    if not isinstance(important_npcs, list):
        important_npcs = []
    if not important_npcs:
        return current.get('relevant_npcs', [])
    active_threads = current.get('active_threads', [])
    if not isinstance(active_threads, list):
        active_threads = []
    carryover_clues = current.get('carryover_clues', [])
    if not isinstance(carryover_clues, list):
        carryover_clues = []
    thread_text = ' '.join(
        ' '.join(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
        for item in active_threads
        if isinstance(item, dict)
    )
    clue_text = ' '.join(str(item or '') for item in carryover_clues)
    recent_assistant_text = _recent_assistant_text(prev)
    haystack = ' '.join([thread_text, clue_text, recent_assistant_text])
    recovered: list[str] = []
    for item in important_npcs:
        if not isinstance(item, dict):
            continue
        label = sanitize_runtime_name(item.get('primary_label', ''))
        if not label or is_protagonist_name(label):
            continue
        aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias)]
        if any(name and name in haystack for name in [label] + aliases):
            recovered.append(label)
        if len(recovered) >= 3:
            break
    return dedupe_names(recovered, limit=6)


def _should_decay_tracked_object(item: dict, possession_ids: set[str], visibility_ids: set[str], recent_text: str) -> bool:
    if not isinstance(item, dict):
        return False
    object_id = str(item.get('object_id', '') or '').strip()
    label = str(item.get('label', '') or '').strip()
    kind = str(item.get('kind', '') or 'item').strip() or 'item'
    if not object_id or not label:
        return True
    if object_id in possession_ids or object_id in visibility_ids:
        return False
    if kind in {'document', 'key_item', 'weapon', 'container', 'tool'}:
        return False
    if recent_text and label in recent_text:
        return False
    return True


def _promote_degraded_candidates(candidate_pool: list[dict], prev_entities: list[dict], prev_state: dict) -> list[dict]:
    descriptive_names = _extract_descriptive_entity_names_from_history(prev_state)
    if not descriptive_names:
        return candidate_pool
    promoted: list[dict] = []
    replacement_idx = 0
    for item in candidate_pool:
        if not isinstance(item, dict):
            promoted.append(item)
            continue
        current = dict(item)
        primary = sanitize_runtime_name(current.get('primary_label', ''))
        if _is_degraded_entity_label(primary) and replacement_idx < len(descriptive_names):
            better = descriptive_names[replacement_idx]
            replacement_idx += 1
            current['primary_label'] = better
            aliases = current.get('aliases', []) if isinstance(current.get('aliases', []), list) else []
            current['aliases'] = sorted({alias for alias in aliases + [better] if sanitize_runtime_name(alias)})
        promoted.append(current)
    return promoted


def _entity_match_score(prev: dict, item: dict) -> float:
    prev_names = _entity_name_set(prev)
    item_names = _entity_name_set(item)
    name_overlap = 1.0 if prev_names & item_names else 0.0
    role_prev = str((prev or {}).get('role_label', '') or '').strip()
    role_item = str((item or {}).get('role_label', '') or '').strip()
    role_score = 0.0
    if role_prev and role_item and role_prev == role_item and role_prev != '待确认' and role_item != '待确认':
        role_score = 0.7
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
        primary = _prefer_stable_primary_label(item, prev)
        if not primary:
            continue
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
            'role_label': _choose_role_label(
                primary,
                item.get('role_label', ''),
                prev.get('role_label', '') if prev else '',
                onstage=primary in onstage_names,
                relevant=primary not in onstage_names,
            ).strip() or '待确认',
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
            'role_label': _choose_role_label(primary, '', prev.get('role_label', ''), relevant=True).strip() or '待确认',
            'onstage': False,
            'possible_link': prev.get('possible_link'),
        })

    if not merged and onstage_names:
        return fallback_scene_entities(onstage_names)
    return merged


def _merge_knowledge_scope(prev_scope: dict, new_scope: dict) -> dict:
    """增量合并知情边界：new_scope 的 learned 条目追加到 prev_scope 上，去重并限制数量。"""
    prev_scope = prev_scope if isinstance(prev_scope, dict) else {}
    new_scope = new_scope if isinstance(new_scope, dict) else {}
    result: dict = {}

    # 合并 protagonist
    prev_p = prev_scope.get('protagonist', {}) or {}
    new_p = new_scope.get('protagonist', {}) or {}
    prev_learned = list(prev_p.get('learned', []) or []) if isinstance(prev_p.get('learned'), list) else []
    new_learned = list(new_p.get('learned', []) or []) if isinstance(new_p.get('learned'), list) else []
    merged = []
    seen: set[str] = set()
    for item in prev_learned + new_learned:
        text = str(item).strip()
        if text and text not in seen:
            seen.add(text)
            merged.append(text)
    if merged:
        result['protagonist'] = {'learned': merged[-30:]}  # 保留最近 30 条

    # 合并 npc_local
    prev_npc = prev_scope.get('npc_local', {}) or {}
    new_npc = new_scope.get('npc_local', {}) or {}
    all_npc_names = set(list(prev_npc.keys()) + list(new_npc.keys()))
    npc_local: dict = {}
    for name in all_npc_names:
        prev_items = list((prev_npc.get(name, {}) or {}).get('learned', []) or [])
        new_items = list((new_npc.get(name, {}) or {}).get('learned', []) or [])
        merged_npc = []
        seen_npc: set[str] = set()
        for item in prev_items + new_items:
            text = str(item).strip()
            if text and text not in seen_npc:
                seen_npc.add(text)
                merged_npc.append(text)
        if merged_npc:
            npc_local[name] = {'learned': merged_npc[-15:]}  # 每 NPC 保留最近 15 条
    if npc_local:
        result['npc_local'] = npc_local

    return result


def normalize_state_dict(state: dict, prev_state: dict | None = None, session_id: str | None = None) -> dict:
    prev = prev_state or {}
    current = dict(state or {})

    def _looks_like_bad_object_label(label: str) -> bool:
        text = str(label or '').strip()
        if not text:
            return True
        if len(text) > 14:
            return True
        if any(token in text for token in ('——', '……', '，', '。', '？', '?', '！', '!', '：', ':', '"', '“', '”', '‘', '’')):
            return True
        if any(token in text for token in ('准确地说', '停了一瞬', '似乎', '像是', '仿佛', '大概', '忽然', '随后')):
            return True
        if any(token in text for token in ('了一', '了个', '一下', '起来', '过去', '下来', '进去', '出来')):
            return True
        if '的' in text and len(text) > 4:
            return True
        return False

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
    tracked_objects = current.get('tracked_objects', prev.get('tracked_objects', []))
    if not isinstance(tracked_objects, list):
        tracked_objects = prev.get('tracked_objects', []) if isinstance(prev.get('tracked_objects', []), list) else []
    normalized_objects = []
    seen_object_ids: set[str] = set()
    for idx, item in enumerate(tracked_objects):
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or f'obj_{idx + 1:02d}').strip()
        label = str(item.get('label', '') or '').strip()
        if label == object_id:
            continue
        if _looks_like_bad_object_label(label):
            continue
        if not object_id or not label or object_id in seen_object_ids:
            continue
        seen_object_ids.add(object_id)
        normalized_objects.append({
            'object_id': object_id,
            'label': label,
            'kind': str(item.get('kind', '') or 'item').strip() or 'item',
            'story_relevant': bool(item.get('story_relevant', True)),
        })
    object_index = {item['object_id']: item for item in normalized_objects}

    possession_state = current.get('possession_state', prev.get('possession_state', []))
    if not isinstance(possession_state, list):
        possession_state = prev.get('possession_state', []) if isinstance(prev.get('possession_state', []), list) else []
    normalized_possession = []
    seen_possession: set[str] = set()
    valid_holders = set(current['onstage_npcs']) | set(current['relevant_npcs']) | protagonist_names()
    for item in possession_state:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or '').strip()
        holder = sanitize_runtime_name(item.get('holder', ''))
        if not object_id or not holder or object_id in seen_possession:
            continue
        if valid_holders and holder not in valid_holders:
            continue
        if object_id not in object_index:
            continue
        seen_possession.add(object_id)
        normalized_possession.append({
            'object_id': object_id,
            'holder': holder,
            'status': str(item.get('status', '') or 'carried').strip() or 'carried',
            'location': str(item.get('location', '') or '').strip(),
            'updated_by_turn': str(item.get('updated_by_turn', '') or '').strip(),
        })
    current['possession_state'] = normalized_possession

    object_visibility = current.get('object_visibility', prev.get('object_visibility', []))
    if not isinstance(object_visibility, list):
        object_visibility = prev.get('object_visibility', []) if isinstance(prev.get('object_visibility', []), list) else []
    normalized_visibility = []
    seen_visibility: set[str] = set()
    for item in object_visibility:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or '').strip()
        if not object_id or object_id in seen_visibility:
            continue
        if object_id not in object_index:
            continue
        seen_visibility.add(object_id)
        normalized_visibility.append({
            'object_id': object_id,
            'visibility': str(item.get('visibility', '') or 'private').strip() or 'private',
            'known_to': [sanitize_runtime_name(name) for name in (item.get('known_to', []) or []) if sanitize_runtime_name(name)][:6],
            'note': str(item.get('note', '') or '').strip(),
        })
    current['object_visibility'] = normalized_visibility
    object_ids_with_state = {item['object_id'] for item in normalized_possession} | {item['object_id'] for item in normalized_visibility}
    filtered_objects = []
    recent_assistant_text = _recent_assistant_text(prev)
    for item in object_index.values():
        kind = str(item.get('kind', '') or 'item').strip() or 'item'
        if _should_decay_tracked_object(item, {entry['object_id'] for entry in normalized_possession}, {entry['object_id'] for entry in normalized_visibility}, recent_assistant_text):
            continue
        if item['object_id'] in object_ids_with_state:
            filtered_objects.append(item)
            continue
        if kind in {'document', 'key_item', 'weapon', 'container', 'tool'}:
            filtered_objects.append(item)
            continue
    current['tracked_objects'] = filtered_objects

    candidate_entities = current.get('scene_entities', [])
    if isinstance(candidate_entities, list):
        current['scene_entities'] = _promote_named_groups(
            _promote_degraded_candidates(candidate_entities, prev.get('scene_entities', []), prev),
            prev,
        )

    current['scene_entities'] = merge_scene_entities(
        prev.get('scene_entities', []),
        current.get('scene_entities', []),
        current['onstage_npcs'],
        current.get('important_npcs', prev.get('important_npcs', [])),
        current.get('continuity_hints', prev.get('continuity_hints', [])),
    )
    current['scene_entities'] = _repair_existing_degraded_entities(current.get('scene_entities', []), prev)
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
    actor_names = []
    for item in current.get('active_threads', []) or []:
        if not isinstance(item, dict):
            continue
        for actor in item.get('actors', []) or []:
            actor_name = sanitize_runtime_name(actor)
            if actor_name and not is_protagonist_name(actor_name) and actor_name not in actor_names:
                actor_names.append(actor_name)
    for actor_name in actor_names:
        if actor_name not in current['onstage_npcs'] and actor_name not in current['relevant_npcs']:
            current['relevant_npcs'].append(actor_name)
    current['relevant_npcs'] = dedupe_names(
        [name for name in current.get('relevant_npcs', []) if name not in current['onstage_npcs']],
        limit=6,
    )
    if actor_names:
        current['scene_entities'] = merge_scene_entities(
            current.get('scene_entities', []),
            fallback_scene_entities(current['onstage_npcs'] + current['relevant_npcs']),
            current['onstage_npcs'],
            current.get('important_npcs', prev.get('important_npcs', [])),
            current.get('continuity_hints', prev.get('continuity_hints', [])),
        )
    for item in current.get('scene_entities', []) or []:
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if not primary:
            continue
        item['role_label'] = _choose_role_label(
            primary,
            item.get('role_label', ''),
            '',
            main_event=current.get('main_event', ''),
            scene_core=current.get('scene_core', ''),
            active_threads=current.get('active_threads', []),
            onstage=primary in set(current.get('onstage_npcs', []) or []),
            relevant=primary in set(current.get('relevant_npcs', []) or []),
        )
    current_main_event = str(current.get('main_event', '') or '').strip()
    if current_main_event:
        for item in current['active_threads']:
            if not isinstance(item, dict):
                continue
            if str(item.get('kind', '') or '') != 'main':
                continue
            item['label'] = current_main_event
            item['key'] = _thread_key_from_label('main', current_main_event)
            break
    important_npcs = current.get('important_npcs', prev.get('important_npcs', []))
    if not isinstance(important_npcs, list):
        important_npcs = prev.get('important_npcs', []) if isinstance(prev.get('important_npcs', []), list) else []
    current['important_npcs'] = important_npcs
    recovered_relevant = _recover_relevant_from_continuity(current, prev)
    if recovered_relevant:
        current['relevant_npcs'] = dedupe_names(current.get('relevant_npcs', []) + recovered_relevant, limit=6)
    recovered_names = _recover_names_from_structure(current, prev)
    if recovered_names:
        current['relevant_npcs'] = dedupe_names(current.get('relevant_npcs', []) + recovered_names, limit=6)
        if not current.get('scene_entities'):
            current['scene_entities'] = fallback_scene_entities(recovered_names)
    current_main_event = str(current.get('main_event', '') or '').strip()
    current_location = str(current.get('location', '') or '').strip()
    present_names = set(current.get('onstage_npcs', []) or []) | set(current.get('relevant_npcs', []) or [])
    for item in current.get('important_npcs', []) or []:
        if not isinstance(item, dict):
            continue
        label = sanitize_runtime_name(item.get('primary_label', ''))
        if current_main_event:
            item['last_main_event'] = current_main_event
        if current_location and label and label in present_names:
            item['last_location'] = current_location
        if label:
            item['present_now'] = label in present_names
            item['role_label'] = _choose_role_label(
                label,
                item.get('role_label', ''),
                '',
                main_event=current_main_event,
                scene_core=current.get('scene_core', ''),
                active_threads=current.get('active_threads', []),
                onstage=label in set(current.get('onstage_npcs', []) or []),
                relevant=label in set(current.get('relevant_npcs', []) or []),
            )
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

    # knowledge_scope 合并：增量追加到 prev 上
    current['knowledge_scope'] = _merge_knowledge_scope(
        prev.get('knowledge_scope', {}),
        current.get('knowledge_scope', {}),
    )

    return current


def fallback_scene_entities(names: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    for idx, name in enumerate(names, start=1):
        out.append({
            'entity_id': f'scene_npc_{idx:02d}',
            'primary_label': name,
            'aliases': [name],
            'role_label': infer_runtime_role_label(name, onstage=True),
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
