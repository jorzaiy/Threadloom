#!/usr/bin/env python3
"""Helpers for bridging markdown workspace state into Threadloom JSON state."""

from __future__ import annotations

import re
from typing import Any, Iterable

try:
    from .continuity_hints import match_continuity_hint
    from .character_assets import load_system_npcs
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_modifier_fragment, looks_like_bad_entity_fragment
    from .card_hints import get_known_npc_role
except ImportError:
    from continuity_hints import match_continuity_hint
    from character_assets import load_system_npcs
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, protagonist_names, looks_like_modifier_fragment, looks_like_bad_entity_fragment
    from card_hints import get_known_npc_role


STRUCTURED_NAME_RE = re.compile(r'[\u4e00-\u9fff]{2,4}(?:·[\u4e00-\u9fff]{2,5})?')
CONTINUITY_INFO_PHRASE_RE = re.compile(r'^[一二三四五六七八九十百千两几半多整\d]+(?:处|条|座|份|项|路|线|页|封|张|本|箱|匣|车|门|库|仓|道)?[\u4e00-\u9fff]{0,8}$')
NON_PERSON_SUFFIXES = ('场', '区', '室', '楼', '廊', '门', '路', '馆', '堂', '院', '厅', '阁', '府', '宫', '殿', '街', '巷', '亭', '轩', '井', '墙', '山')
NON_PERSON_TOKENS = {
    '轻功', '自保', '一声', '规则', '结论', '现象', '世界', '逻辑', '认知', '交互', '概念', '目标', '问题', '决定',
    '对话', '关系', '后续', '物理', '错误', '能力', '剧情', '局势', '线索', '风险', '客厅',
}
ABSTRACT_CONTINUITY_TOKENS = {
    '物理接触', '肢体接触', '身体接触', '接触', '互动', '机制', '系统', '面板', '提示', '规则', '判定', '反馈',
    '设定', '限制', '条件', '代价', '状态', '异常', '效果', '能力', '技能', '天赋', '特性', '权限', '接口',
    '流程', '步骤', '进度', '事件', '剧情', '关系', '概念', '逻辑', '认知', '现象', '目标', '问题', '风险',
    '线索', '情报', '消息', '痕迹', '记忆', '意识', '情绪', '欲望', '冲动', '杀意', '敌意', '压力',
}
ABSTRACT_CONTINUITY_PARTS = (
    '接触', '互动', '机制', '系统', '规则', '判定', '反馈', '设定', '限制', '条件', '状态', '效果', '能力',
    '技能', '天赋', '特性', '流程', '步骤', '进度', '事件', '剧情', '关系', '概念', '逻辑', '认知', '现象',
    '目标', '问题', '风险', '线索', '情报', '记忆', '意识', '情绪', '欲望', '冲动', '杀意', '敌意',
)
ABSTRACT_CONTINUITY_PREFIXES = ('物理', '精神', '心理', '自动', '被动', '主动', '外部', '内部', '当前', '后续', '持续')
ABSTRACT_CONTINUITY_SUFFIXES = ('机制', '系统', '规则', '判定', '反馈', '设定', '限制', '条件', '状态', '效果', '能力', '技能', '关系', '概念', '逻辑', '现象', '问题', '风险', '线索', '情报')
ENTITY_DESCRIPTOR_SUFFIXES = (
    '身影', '背影', '影子', '影', '之人', '那人', '此人', '来人',
    '男人', '女人', '女子', '青年', '少年', '老者', '壮汉',
    '皂衣人', '黑衣人', '灰衣人', '白衣人', '毡笠人', '人',
)
GENERIC_SHADOW_LABELS = {'暗影', '黑影', '影子', '人影'}
PERSON_EVIDENCE_SUFFIXES = ENTITY_DESCRIPTOR_SUFFIXES + (
    '老汉', '老妇', '老人', '先生', '小姐', '姑娘', '掌柜', '老板', '东家', '伙计', '学徒', '官差', '衙役',
    '捕快', '巡捕', '守卫', '侍卫', '士兵', '弟子', '师父', '师兄', '师姐', '师弟', '师妹', '长老', '管事',
)
PERSON_ACTION_VERBS = (
    '说', '问', '答', '笑', '喊', '叫', '道', '提醒', '解释', '反驳', '点头', '摇头', '看', '望', '盯', '瞥',
    '走', '站', '坐', '递', '接', '拿', '放', '拦', '扶', '推', '拉', '领', '带', '跟', '追', '退', '拱手', '皱眉',
)
PERSON_ROLE_HINTS = (
    '人物', '人', '者', '男', '女', '青年', '少年', '老者', '老人', '老汉', '老妇', '姑娘', '先生', '小姐',
    '掌柜', '老板', '东家', '伙计', '学徒', '官差', '衙役', '捕快', '巡捕', '守卫', '侍卫', '士兵', '弟子',
    '师父', '师兄', '师姐', '师弟', '师妹', '长老', '管事', 'NPC', 'npc',
)


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


def infer_runtime_role_label(name: str, *, main_event: str = '', active_threads: list[dict] | None = None, onstage: bool = False, relevant: bool = False) -> str:
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
    text_parts = [str(main_event or '')]
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


def _choose_role_label(name: str, explicit_role: str = '', previous_role: str = '', *, main_event: str = '', active_threads: list[dict] | None = None, onstage: bool = False, relevant: bool = False) -> str:
    explicit = str(explicit_role or '').strip()
    if explicit and explicit != '待确认':
        return explicit
    previous = str(previous_role or '').strip()
    if previous and previous != '待确认':
        return previous
    return infer_runtime_role_label(name, main_event=main_event, active_threads=active_threads, onstage=onstage, relevant=relevant)


def dedupe_names(items: Iterable[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    for item in items:
        name = sanitize_runtime_name(item)
        if not name or is_protagonist_name(name) or looks_like_bad_entity_fragment(name) or name in out:
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


def _looks_like_person_label(name: str) -> bool:
    text = sanitize_runtime_name(name)
    if not text or is_protagonist_name(text) or looks_like_bad_entity_fragment(text):
        return False
    if len(text) > 16:
        return False
    if any(ch in text for ch in '，。！？：；、“”‘’【】[]（）()'):
        return False
    if text.endswith(NON_PERSON_SUFFIXES):
        return False
    if '的' in text:
        return False
    if '·' in text and 3 <= len(text) <= 16:
        return True
    if any(text.endswith(suffix) for suffix in PERSON_EVIDENCE_SUFFIXES):
        return True
    return False


def _person_action_evidence(name: str, text: str) -> bool:
    label = sanitize_runtime_name(name)
    if not label or not text or label not in text:
        return False
    verb_pattern = '|'.join(re.escape(verb) for verb in PERSON_ACTION_VERBS)
    patterns = [
        rf'{re.escape(label)}[^。！？\n]{{0,8}}(?:{verb_pattern})',
        rf'(?:对|向|和|与|跟|把|将|被|让){re.escape(label)}',
        rf'{re.escape(label)}[^。！？\n]{{0,12}}(?:低声|沉声|扬声|拱手|皱眉|点头|摇头)',
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _role_has_person_evidence(role_label: str) -> bool:
    role = str(role_label or '').strip()
    if not role or role == '待确认':
        return False
    return any(hint in role for hint in PERSON_ROLE_HINTS)


def _actor_name_pool(*states: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for state in states:
        actors = state.get('actors', {}) if isinstance(state, dict) else {}
        if not isinstance(actors, dict):
            continue
        for actor_id, actor in actors.items():
            if not isinstance(actor, dict) or str(actor_id) == 'protagonist' or actor.get('kind') == 'protagonist':
                continue
            for raw in [actor.get('name', '')] + list(actor.get('aliases', []) or []):
                name = sanitize_runtime_name(raw)
                if name and not is_protagonist_name(name):
                    names.add(name)
    return names


def _important_name_pool(items: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for raw in [item.get('primary_label', '')] + list(item.get('aliases', []) or []):
            name = sanitize_runtime_name(raw)
            if name and not is_protagonist_name(name):
                names.add(name)
    return names


def _continuity_hint_name_pool(items: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        for raw in [item.get('primary_label', '')] + list(item.get('aliases', []) or []):
            name = sanitize_runtime_name(raw)
            if name and not is_protagonist_name(name):
                names.add(name)
    return names


def _person_evidence_text(current: dict[str, Any], prev: dict[str, Any]) -> str:
    blocks: list[str] = []
    for state in (current, prev):
        if not isinstance(state, dict):
            continue
        blocks.extend(str(state.get(field, '') or '') for field in ('main_event', 'immediate_goal'))
        for item in state.get('active_threads', []) or []:
            if isinstance(item, dict):
                blocks.extend(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
    recent = _recent_assistant_text(prev, limit=4) if isinstance(prev, dict) else ''
    if recent:
        blocks.append(recent)
    return '\n'.join(block for block in blocks if block)


def _has_positive_person_evidence(name: str, item: dict[str, Any] | None, current: dict[str, Any], prev: dict[str, Any]) -> bool:
    label = sanitize_runtime_name(name)
    if not label or is_protagonist_name(label) or looks_like_bad_entity_fragment(label):
        return False
    if label in _actor_name_pool(current, prev):
        return True
    important_names = _important_name_pool(current.get('important_npcs', prev.get('important_npcs', []))) | _important_name_pool(prev.get('important_npcs', []))
    if label in important_names:
        return True
    hint_names = _continuity_hint_name_pool(current.get('continuity_hints', prev.get('continuity_hints', []))) | _continuity_hint_name_pool(prev.get('continuity_hints', []))
    if label in hint_names:
        return True
    if item and _looks_like_person_label(label) and _role_has_person_evidence(str(item.get('role_label', '') or '')):
        return True
    if _looks_like_person_label(label) and _person_action_evidence(label, _person_evidence_text(current, prev)):
        return True
    return False


def _filter_person_names_with_evidence(names: Iterable[str], current: dict[str, Any], prev: dict[str, Any], *, limit: int = 6) -> list[str]:
    out: list[str] = []
    for raw in names or []:
        name = sanitize_runtime_name(raw)
        if not name or name in out:
            continue
        if not _has_positive_person_evidence(name, None, current, prev):
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _filter_scene_entities_with_person_evidence(entities: list[dict[str, Any]], current: dict[str, Any], prev: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in entities or []:
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if not _has_positive_person_evidence(primary, item, current, prev):
            continue
        next_item = dict(item)
        aliases = []
        for alias in item.get('aliases', []) or []:
            alias_text = sanitize_runtime_name(alias)
            if alias_text and (alias_text == primary or _has_positive_person_evidence(alias_text, item, current, prev)):
                aliases.append(alias_text)
        next_item['primary_label'] = primary
        next_item['aliases'] = dedupe_names(aliases + [primary])
        out.append(next_item)
    return out


def entity_descriptor_signature(name: str) -> str:
    text = sanitize_runtime_name(name)
    if not text:
        return ''
    for suffix in ENTITY_DESCRIPTOR_SUFFIXES:
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[:-len(suffix)].strip()
    return text


def _descriptor_signature(name: str) -> str:
    return entity_descriptor_signature(name)


def _labels_compatible(left: str, right: str) -> bool:
    return entity_labels_compatible(left, right)


def entity_labels_compatible(left: str, right: str) -> bool:
    left_text = sanitize_runtime_name(left)
    right_text = sanitize_runtime_name(right)
    if not left_text or not right_text:
        return False
    if left_text == right_text:
        return True
    if left_text in GENERIC_SHADOW_LABELS or right_text in GENERIC_SHADOW_LABELS:
        return False
    left_sig = _descriptor_signature(left_text)
    right_sig = _descriptor_signature(right_text)
    return bool(left_sig and right_sig and left_sig == right_sig)


def normalize_carryover_signals(items) -> list[dict]:
    out = []
    seen = set()
    for item in items or []:
        if isinstance(item, str):
            signal_type = 'mixed'
            text = str(item or '').strip()
        elif isinstance(item, dict):
            signal_type = str(item.get('type', '') or 'mixed').strip() or 'mixed'
            text = str(item.get('text', '') or '').strip()
        else:
            continue
        if not text:
            continue
        key = (signal_type, text)
        if key in seen:
            continue
        seen.add(key)
        out.append({'type': signal_type, 'text': text})
        if len(out) >= 6:
            break
    return out


def derive_risks_clues_from_signals(items: list[dict]) -> tuple[list[str], list[str]]:
    risks = []
    clues = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        signal_type = str(item.get('type', '') or 'mixed').strip() or 'mixed'
        text = str(item.get('text', '') or '').strip()
        if not text:
            continue
        if signal_type in {'risk', 'mixed'} and text not in risks:
            risks.append(text)
        if signal_type in {'clue', 'mixed'} and text not in clues:
            clues.append(text)
    return risks[:4], clues[:4]


def normalize_keeper_object_label(text: str) -> str:
    value = str(text or '').strip()
    if not value:
        return ''
    return value.split('（', 1)[0].split('(', 1)[0].strip()


def _preferred_primary_label(labels: list[str], onstage_names: set[str], relevant_names: set[str]) -> str:
    normalized = [sanitize_runtime_name(label) for label in labels if sanitize_runtime_name(label)]
    if not normalized:
        return ''
    for label in normalized:
        if label in onstage_names:
            return label
    for label in normalized:
        if label in relevant_names:
            return label
    concrete = [label for label in normalized if not _is_degraded_entity_label(label)]
    if concrete:
        concrete.sort(key=lambda item: (item in GENERIC_SHADOW_LABELS, -len(_descriptor_signature(item)), -len(item), item))
        return concrete[0]
    normalized.sort(key=lambda item: (-len(item), item))
    return normalized[0]


def _filter_entity_aliases(primary: str, aliases: list[str], protected_names: set[str]) -> list[str]:
    out: list[str] = []
    for alias in aliases or []:
        text = sanitize_runtime_name(alias)
        if not text or text == primary:
            continue
        if text in protected_names and not _labels_compatible(primary, text):
            continue
        if text not in out:
            out.append(text)
    return out


def _normalize_merged_scene_entities(entities: list[dict], onstage_names: list[str], relevant_names: list[str]) -> list[dict]:
    if not entities:
        return []
    onstage_set = {sanitize_runtime_name(name) for name in onstage_names if sanitize_runtime_name(name)}
    relevant_set = {sanitize_runtime_name(name) for name in relevant_names if sanitize_runtime_name(name)}
    protected_names = onstage_set | relevant_set
    grouped: dict[str, list[dict]] = {}
    for item in entities:
        if not isinstance(item, dict):
            continue
        entity_id = str(item.get('entity_id', '') or '').strip()
        grouped.setdefault(entity_id, []).append(item)

    max_id = max((_entity_numeric_id(entity_id) for entity_id in grouped.keys()), default=0)
    normalized: list[dict] = []
    for entity_id, group in grouped.items():
        if len(group) == 1:
            item = dict(group[0])
            primary = sanitize_runtime_name(item.get('primary_label', ''))
            aliases = dedupe_names((item.get('aliases') or []) + [primary])
            item['aliases'] = _filter_entity_aliases(primary, aliases, protected_names)
            item['primary_label'] = primary
            item['onstage'] = primary in onstage_set
            normalized.append(item)
            continue

        clusters: list[list[dict]] = []
        for item in group:
            primary = sanitize_runtime_name(item.get('primary_label', ''))
            if not primary:
                continue
            matched_cluster = None
            for cluster in clusters:
                cluster_labels = [
                    sanitize_runtime_name(existing.get('primary_label', ''))
                    for existing in cluster
                    if sanitize_runtime_name(existing.get('primary_label', ''))
                ]
                if any(_labels_compatible(primary, other) for other in cluster_labels):
                    matched_cluster = cluster
                    break
            if matched_cluster is None:
                clusters.append([item])
            else:
                matched_cluster.append(item)

        for idx, cluster in enumerate(clusters):
            labels = [
                sanitize_runtime_name(item.get('primary_label', ''))
                for item in cluster
                if sanitize_runtime_name(item.get('primary_label', ''))
            ]
            primary = _preferred_primary_label(labels, onstage_set, relevant_set)
            aliases = dedupe_names(
                [
                    alias
                    for item in cluster
                    for alias in ((item.get('aliases') or []) + [item.get('primary_label', '')])
                ]
            )
            merged_item = dict(cluster[0])
            merged_item['primary_label'] = primary
            merged_item['aliases'] = _filter_entity_aliases(primary, aliases, protected_names)
            merged_item['onstage'] = primary in onstage_set
            if idx == 0 and entity_id:
                merged_item['entity_id'] = entity_id
            else:
                max_id += 1
                merged_item['entity_id'] = f'scene_npc_{max_id:02d}'
            normalized.append(merged_item)

    merged_again: list[dict] = []
    consumed: set[int] = set()
    for idx, item in enumerate(normalized):
        if idx in consumed:
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if not primary:
            continue
        cluster = [item]
        for other_idx in range(idx + 1, len(normalized)):
            if other_idx in consumed:
                continue
            other = normalized[other_idx]
            other_primary = sanitize_runtime_name(other.get('primary_label', ''))
            if not other_primary:
                continue
            if not _labels_compatible(primary, other_primary):
                continue
            consumed.add(other_idx)
            cluster.append(other)

        labels = [
            sanitize_runtime_name(entry.get('primary_label', ''))
            for entry in cluster
            if sanitize_runtime_name(entry.get('primary_label', ''))
        ]
        merged_item = dict(cluster[0])
        merged_item['primary_label'] = _preferred_primary_label(labels, onstage_set, relevant_set)
        aliases = dedupe_names(
            [
                alias
                for entry in cluster
                for alias in ((entry.get('aliases') or []) + [entry.get('primary_label', '')])
            ]
        )
        merged_item['aliases'] = _filter_entity_aliases(merged_item['primary_label'], aliases, protected_names)
        merged_item['onstage'] = merged_item['primary_label'] in onstage_set
        merged_again.append(merged_item)

    return merged_again


def _normalize_important_npcs(items: list[dict], protected_names: set[str], onstage_names: set[str], relevant_names: set[str]) -> list[dict]:
    normalized: list[dict] = []
    consumed: set[int] = set()
    for idx, item in enumerate(items or []):
        if idx in consumed or not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if not primary:
            continue
        cluster = [item]
        for other_idx in range(idx + 1, len(items or [])):
            if other_idx in consumed:
                continue
            other = items[other_idx]
            if not isinstance(other, dict):
                continue
            other_primary = sanitize_runtime_name(other.get('primary_label', ''))
            if not other_primary or not _labels_compatible(primary, other_primary):
                continue
            consumed.add(other_idx)
            cluster.append(other)

        labels = [
            sanitize_runtime_name(entry.get('primary_label', ''))
            for entry in cluster
            if sanitize_runtime_name(entry.get('primary_label', ''))
        ]
        merged = dict(cluster[0])
        merged['primary_label'] = _preferred_primary_label(labels, onstage_names, relevant_names)
        aliases = dedupe_names(
            [
                alias
                for entry in cluster
                for alias in ((entry.get('aliases') or []) + [entry.get('primary_label', '')])
            ]
        )
        merged['aliases'] = _filter_entity_aliases(merged['primary_label'], aliases, protected_names)
        merged['importance_score'] = max(int(entry.get('importance_score', 0) or 0) for entry in cluster)
        merged['present_now'] = merged['primary_label'] in onstage_names or merged['primary_label'] in relevant_names
        normalized.append(merged)

    return normalized


def _is_degraded_entity_label(name: str) -> bool:
    text = str(name or '').strip()
    if not text:
        return True
    if text in GENERIC_SHADOW_LABELS:
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
    if prev_primary and primary and prev_primary != primary and primary in prev_primary:
        return prev_primary
    return primary


def _meaningful_text(value) -> str:
    text = str(value or '').strip()
    return '' if not text or text == '待确认' else text


def _merge_scene_entity_details(prev: dict | None, item: dict, *, entity_id: str, primary: str, aliases: list[str], role_label: str, onstage: bool) -> dict:
    """Keep stable entity identity and only let new extraction fill useful details."""
    merged = dict(prev or {})
    for key, value in (item or {}).items():
        if key in {'entity_id', 'primary_label', 'aliases', 'role_label', 'onstage', 'possible_link'}:
            continue
        if key not in merged or merged.get(key) in (None, '', [], {}, '待确认'):
            merged[key] = value
    merged['entity_id'] = entity_id
    merged['primary_label'] = primary
    merged['aliases'] = aliases
    merged['role_label'] = role_label
    merged['onstage'] = onstage
    candidate_link = _meaningful_text((item or {}).get('possible_link'))
    prev_link = (prev or {}).get('possible_link') if prev else None
    merged['possible_link'] = candidate_link or prev_link
    return merged


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
        r'((?:高个|矮个|靠后|前头|后侧|左侧|右侧|靠门|靠窗)[\u4e00-\u9fff]{1,5}(?:人|者|男人|女人|青年|少年|女子|老者))',
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
    return []


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


def _looks_like_abstract_continuity_name(name: str) -> bool:
    candidate = sanitize_runtime_name(name)
    if not candidate:
        return False
    if candidate in ABSTRACT_CONTINUITY_TOKENS:
        return True
    if candidate.endswith(ABSTRACT_CONTINUITY_SUFFIXES):
        return True
    if any(candidate.startswith(prefix) and any(part in candidate[len(prefix):] for part in ABSTRACT_CONTINUITY_PARTS) for prefix in ABSTRACT_CONTINUITY_PREFIXES):
        return True
    if sum(1 for part in ABSTRACT_CONTINUITY_PARTS if part in candidate) >= 2:
        return True
    return False


def _looks_like_continuity_name(name: str, text: str) -> bool:
    candidate = sanitize_runtime_name(name)
    if not candidate or is_protagonist_name(candidate):
        return False
    if looks_like_modifier_fragment(candidate):
        return False
    if len(candidate) < 2 or len(candidate) > 8:
        return False
    if CONTINUITY_INFO_PHRASE_RE.match(candidate):
        return False
    if any(ch.isdigit() for ch in candidate):
        return False
    if candidate in NON_PERSON_TOKENS:
        return False
    if _looks_like_abstract_continuity_name(candidate):
        return False
    if candidate.startswith(('我', '你', '他', '她', '先', '再', '又', '仍', '还', '继续', '低声', '忽然', '终于')):
        return False
    if candidate.endswith(NON_PERSON_SUFFIXES):
        return False
    if candidate.endswith(('上', '下', '里', '中', '前', '后', '旁', '外')):
        return False
    if '的' in candidate:
        return False
    if any(token in candidate for token in ('账本', '账册', '木匣', '匣子', '线索', '情报')):
        return False
    patterns = [
        rf'{re.escape(candidate)}(?:说|问|笑|道|看|想|将|把|对|向|已|正|仍|又|判定|认为|解释|反驳)',
        rf'(?:对|向|和|与){re.escape(candidate)}',
    ]
    return any(re.search(pattern, text) for pattern in patterns)


def _stable_name_pool(prev: dict) -> list[str]:
    names: list[str] = []
    for item in (prev.get('scene_entities', []) or []):
        if not isinstance(item, dict):
            continue
        primary = sanitize_runtime_name(item.get('primary_label', ''))
        if primary and primary not in names:
            names.append(primary)
        for alias in (item.get('aliases', []) or []):
            alias_text = sanitize_runtime_name(alias)
            if alias_text and alias_text not in names:
                names.append(alias_text)
    for field in ('onstage_npcs', 'relevant_npcs'):
        for name in (prev.get(field, []) or []):
            text = sanitize_runtime_name(name)
            if text and text not in names:
                names.append(text)
    for item in (prev.get('important_npcs', []) or []):
        if not isinstance(item, dict):
            continue
        text = sanitize_runtime_name(item.get('primary_label', ''))
        if text and text not in names:
            names.append(text)
    return names[:16]


def _extract_recovery_candidates(text: str, prev: dict, *, limit: int = 12) -> list[str]:
    candidates: list[str] = []
    for name in _stable_name_pool(prev):
        if name and name in text and name not in candidates:
            candidates.append(name)
        if len(candidates) >= limit:
            return candidates
    for match in STRUCTURED_NAME_RE.finditer(text):
        candidate = sanitize_runtime_name(match.group(0))
        if not candidate or candidate in candidates:
            continue
        if len(candidate) < 2 or len(candidate) > 8:
            continue
        candidates.append(candidate)
        if len(candidates) >= limit:
            break
    return candidates


def _judge_recovery_candidates(candidates: list[str], text: str, prev: dict) -> list[str] | None:
    return None


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
    heuristic_recovered: list[str] = []
    for match in STRUCTURED_NAME_RE.finditer(text):
        name = sanitize_runtime_name(match.group(0))
        if not _looks_like_continuity_name(name, text):
            continue
        if name not in heuristic_recovered:
            heuristic_recovered.append(name)
        if len(heuristic_recovered) >= 3:
            break
    judged = _judge_recovery_candidates(_extract_recovery_candidates(text, prev), text, prev)
    if judged is not None:
        return dedupe_names(judged, limit=3)
    recovered = heuristic_recovered
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
    if '的' in text and (len(text) > 4 or text in {'的包', '的手', '的眼', '的门'}):
        return True
    return False


def _object_signature(label: str) -> str:
    text = str(label or '').strip()
    if not text:
        return ''
    return re.sub(r'^(?:一[个把只张本份封]|这[个把只张本份封]|那[个把只张本份封])', '', text).strip()


def _object_labels_compatible(left: str, right: str) -> bool:
    left_sig = _object_signature(left)
    right_sig = _object_signature(right)
    if not left_sig or not right_sig:
        return False
    if left_sig == right_sig:
        return True
    return len(left_sig) >= 2 and len(right_sig) >= 2 and (left_sig in right_sig or right_sig in left_sig)


def _prefer_stable_object_label(candidate: str, previous: str) -> str:
    current = str(candidate or '').strip()
    prev_label = str(previous or '').strip()
    if prev_label and (_looks_like_bad_object_label(current) or len(current) < len(prev_label)):
        return prev_label
    return current or prev_label


def _prefer_stable_object_kind(candidate: str, previous: str) -> str:
    current = _meaningful_text(candidate) or 'item'
    prev_kind = _meaningful_text(previous)
    if prev_kind and prev_kind != 'item' and current == 'item':
        return prev_kind
    return current


def _merge_tracked_objects(prev_objects: list[dict], candidate_objects: list[dict]) -> list[dict]:
    prev_items = [item for item in (prev_objects or []) if isinstance(item, dict)]
    candidate_items = [item for item in (candidate_objects or []) if isinstance(item, dict)]
    max_id = 0
    for item in prev_items + candidate_items:
        object_id = str(item.get('object_id', '') or '')
        try:
            max_id = max(max_id, int(object_id.rsplit('_', 1)[1]))
        except Exception:
            continue

    merged: list[dict] = []
    used_prev: set[int] = set()
    for candidate in candidate_items:
        label = str(candidate.get('label', '') or '').strip()
        object_id = str(candidate.get('object_id', '') or '').strip()
        if not label or _looks_like_bad_object_label(label):
            continue
        matched_idx = None
        for idx, prev in enumerate(prev_items):
            if idx in used_prev:
                continue
            prev_id = str(prev.get('object_id', '') or '').strip()
            prev_label = str(prev.get('label', '') or '').strip()
            if (object_id and prev_id and object_id == prev_id) or _object_labels_compatible(label, prev_label):
                matched_idx = idx
                break
        prev = prev_items[matched_idx] if matched_idx is not None else None
        if matched_idx is not None:
            used_prev.add(matched_idx)
        if prev:
            candidate_lifecycle = str(candidate.get('lifecycle_status', '') or '').strip()
            prev_lifecycle = str(prev.get('lifecycle_status', '') or '').strip()
            if not candidate_lifecycle and prev_lifecycle in {'consumed', 'destroyed', 'lost', 'archived'}:
                continue
            stable_id = str(prev.get('object_id', '') or '').strip() or object_id
            stable_label = _prefer_stable_object_label(label, str(prev.get('label', '') or ''))
            merged_item = dict(prev)
            merged_item['object_id'] = stable_id
            merged_item['label'] = stable_label
            merged_item['kind'] = _prefer_stable_object_kind(candidate.get('kind'), prev.get('kind'))
            merged_item['story_relevant'] = bool(candidate.get('story_relevant', prev.get('story_relevant', True)))
            lifecycle_status = str(candidate.get('lifecycle_status', prev.get('lifecycle_status', 'active')) or 'active').strip() or 'active'
            if lifecycle_status in {'consumed', 'destroyed', 'lost', 'archived'}:
                merged_item['lifecycle_status'] = lifecycle_status
                merged_item['lifecycle_reason'] = str(candidate.get('lifecycle_reason', candidate.get('reason', prev.get('lifecycle_reason', ''))) or '').strip()
            merged.append(merged_item)
            continue
        if not object_id:
            max_id += 1
            object_id = f'obj_{max_id:02d}'
        lifecycle_status = str(candidate.get('lifecycle_status', 'active') or 'active').strip() or 'active'
        if lifecycle_status not in {'active', 'consumed', 'destroyed', 'lost', 'archived'}:
            lifecycle_status = 'active'
        next_item = {
            **candidate,
            'object_id': object_id,
            'label': label,
            'kind': _meaningful_text(candidate.get('kind')) or 'item',
            'story_relevant': bool(candidate.get('story_relevant', True)),
        }
        if lifecycle_status != 'active':
            next_item['lifecycle_status'] = lifecycle_status
            next_item['lifecycle_reason'] = str(candidate.get('lifecycle_reason', candidate.get('reason', '')) or '').strip()
        merged.append(next_item)

    for idx, prev in enumerate(prev_items):
        if idx in used_prev:
            continue
        label = str(prev.get('label', '') or '').strip()
        object_id = str(prev.get('object_id', '') or '').strip()
        if any(str(item.get('object_id', '') or '').strip() == object_id for item in merged):
            continue
        if not label or not object_id or _looks_like_bad_object_label(label):
            continue
        merged.append(dict(prev))
    return merged


def _entity_lookup_by_name(entities: list[dict]) -> dict[str, dict]:
    lookup: dict[str, dict] = {}
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        primary = sanitize_runtime_name(entity.get('primary_label', ''))
        if not primary:
            continue
        lookup[primary] = entity
        for alias in entity.get('aliases', []) or []:
            alias_text = sanitize_runtime_name(alias)
            if alias_text and alias_text not in lookup:
                lookup[alias_text] = entity
    return lookup


def _apply_object_entity_bindings(state: dict) -> dict:
    entities = [dict(item) for item in (state.get('scene_entities', []) or []) if isinstance(item, dict)]
    objects = [dict(item) for item in (state.get('tracked_objects', []) or []) if isinstance(item, dict)]
    possession = [dict(item) for item in (state.get('possession_state', []) or []) if isinstance(item, dict)]
    visibility_by_id = {
        str(item.get('object_id', '') or '').strip(): item
        for item in (state.get('object_visibility', []) or [])
        if isinstance(item, dict) and str(item.get('object_id', '') or '').strip()
    }
    entity_lookup = _entity_lookup_by_name(entities)
    entity_by_primary = {
        sanitize_runtime_name(item.get('primary_label', '')): item
        for item in entities
        if sanitize_runtime_name(item.get('primary_label', ''))
    }
    object_by_id = {
        str(item.get('object_id', '') or '').strip(): item
        for item in objects
        if str(item.get('object_id', '') or '').strip()
    }
    owned_by_entity: dict[str, list[dict]] = {}
    normalized_possession: list[dict] = []

    for item in possession:
        object_id = str(item.get('object_id', '') or '').strip()
        holder = sanitize_runtime_name(item.get('holder', ''))
        if not object_id or not holder or object_id not in object_by_id:
            continue
        entity = entity_lookup.get(holder)
        if entity:
            holder = sanitize_runtime_name(entity.get('primary_label', '')) or holder
        next_item = dict(item)
        next_item['holder'] = holder
        normalized_possession.append(next_item)

        obj = object_by_id[object_id]
        obj['owner'] = holder
        obj['owner_type'] = 'npc' if entity else ('protagonist' if is_protagonist_name(holder) else 'unknown')
        if entity:
            entity_id = str(entity.get('entity_id', '') or '').strip()
            if entity_id:
                obj['bound_entity_id'] = entity_id
            obj['bound_entity_label'] = holder
        status = str(item.get('status', '') or '').strip()
        if status:
            obj['possession_status'] = status
        if entity:
            owned_by_entity.setdefault(holder, []).append({
                'object_id': object_id,
                'label': str(obj.get('label', '') or '').strip(),
                'status': status or 'carried',
                'visibility': str((visibility_by_id.get(object_id) or {}).get('visibility', '') or '').strip(),
            })

    for primary, entity in entity_by_primary.items():
        owned = owned_by_entity.get(primary, [])
        if owned:
            seen_ids = set()
            clean_owned = []
            for owned_item in owned:
                object_id = owned_item.get('object_id')
                if not object_id or object_id in seen_ids:
                    continue
                seen_ids.add(object_id)
                clean_owned.append(owned_item)
            entity['owned_objects'] = clean_owned[:6]
        elif 'owned_objects' in entity:
            entity['owned_objects'] = []

    state['tracked_objects'] = list(object_by_id.values())
    state['possession_state'] = normalized_possession
    state['scene_entities'] = entities
    return state


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
    name_overlap = 2.0 if prev_names & item_names else 0.0
    signature_overlap = 0.0
    prev_signatures = {_descriptor_signature(name) for name in prev_names if _descriptor_signature(name)}
    item_signatures = {_descriptor_signature(name) for name in item_names if _descriptor_signature(name)}
    if prev_signatures & item_signatures:
        signature_overlap = 1.2
    role_prev = str((prev or {}).get('role_label', '') or '').strip()
    role_item = str((item or {}).get('role_label', '') or '').strip()
    role_score = 0.0
    if (name_overlap > 0 or signature_overlap > 0) and role_prev and role_item and role_prev == role_item and role_prev != '待确认' and role_item != '待确认':
        role_score = 0.4
    link_prev = str((prev or {}).get('possible_link', '') or '').strip()
    link_item = str((item or {}).get('possible_link', '') or '').strip()
    link_score = 0.4 if link_prev and link_item and link_prev == link_item else 0.0
    return name_overlap + signature_overlap + role_score + link_score


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
    return best if best_score >= 1.0 else None


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
        if looks_like_modifier_fragment(primary):
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
        role_label = _choose_role_label(
            primary,
            item.get('role_label', ''),
            prev.get('role_label', '') if prev else '',
            onstage=primary in onstage_names,
            relevant=primary not in onstage_names,
        ).strip() or '待确认'
        merged.append(_merge_scene_entity_details(
            prev,
            item,
            entity_id=entity_id,
            primary=primary,
            aliases=aliases,
            role_label=role_label,
            onstage=primary in onstage_names,
        ))

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
    return _normalize_merged_scene_entities(
        merged,
        onstage_names,
        [
            sanitize_runtime_name(item.get('primary_label', ''))
            for item in (important_npcs or [])
            if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
        ],
    )


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


def _coerce_knowledge_scope_delta(value) -> dict:
    if not isinstance(value, dict):
        return {}
    result: dict = {}
    protagonist = value.get('protagonist', {})
    if isinstance(protagonist, str):
        protagonist = {'learned': [protagonist]}
    if isinstance(protagonist, dict):
        learned = protagonist.get('learned', [])
        if isinstance(learned, str):
            learned = [learned]
        cleaned = []
        if isinstance(learned, list):
            for item in learned:
                text = str(item or '').strip()
                if text and text not in cleaned:
                    cleaned.append(text)
        if cleaned:
            result['protagonist'] = {'learned': cleaned[:10]}
    npc_local_raw = value.get('npc_local', {})
    npc_local: dict = {}
    if isinstance(npc_local_raw, dict):
        for name, data in npc_local_raw.items():
            holder = sanitize_runtime_name(name)
            if not holder:
                continue
            if isinstance(data, str):
                data = {'learned': [data]}
            if not isinstance(data, dict):
                continue
            learned = data.get('learned', [])
            if isinstance(learned, str):
                learned = [learned]
            cleaned = []
            if isinstance(learned, list):
                for item in learned:
                    text = str(item or '').strip()
                    if text and text not in cleaned:
                        cleaned.append(text)
            if cleaned:
                npc_local[holder] = {'learned': cleaned[:10]}
    if npc_local:
        result['npc_local'] = npc_local
    return result


def normalize_state_dict(state: dict, prev_state: dict | None = None, session_id: str | None = None) -> dict:
    prev = prev_state or {}
    current = dict(state or {})
    prev_actors = prev.get('actors', {}) if isinstance(prev.get('actors', {}), dict) else {}
    current_actors = current.get('actors', {}) if isinstance(current.get('actors', {}), dict) else {}
    current['actors'] = {**current_actors, **prev_actors}
    for key in ('actor_context_index',):
        value = current.get(key, prev.get(key, {}))
        if not isinstance(value, dict):
            value = prev.get(key, {}) if isinstance(prev.get(key, {}), dict) else {}
        current[key] = value
    for key in ('knowledge_records',):
        value = current.get(key, prev.get(key, []))
        if not isinstance(value, list):
            value = prev.get(key, []) if isinstance(prev.get(key, []), list) else []
        current[key] = value

    def _derive_names_from_scene_entities(items: list[dict], *, onstage_only: bool = False) -> list[str]:
        out: list[str] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            if onstage_only and not bool(item.get('onstage')):
                continue
            name = sanitize_runtime_name(item.get('primary_label', ''))
            if not name or is_protagonist_name(name) or name in out or looks_like_bad_entity_fragment(name):
                continue
            out.append(name)
            if len(out) >= 6:
                break
        return out

    def _looks_like_fragmentary_core_value(value: str, field: str) -> bool:
        text = str(value or '').strip()
        if not text:
            return True
        actor_names = set(current.get('onstage_npcs', []) or []) | set(current.get('relevant_npcs', []) or [])
        actor_names |= {str(item.get('primary_label', '') or '').strip() for item in (current.get('scene_entities', []) or []) if isinstance(item, dict)}
        actor_names = {name for name in actor_names if name}
        if len(text) < 4:
            return True
        if field != 'main_event' and field != 'immediate_goal' and len(text) > 42:
            return True
        if '→' in text:
            return True
        if text.count('：') + text.count(':') >= 1 and len(text) <= 20:
            return True
        if text.startswith(('说：', '问：', '答：', '看着', '盯着', '靠着', '贴着', '撇撇嘴', '皱着眉', '抿着嘴', '仰着头', '缩在')):
            return True
        if text.startswith(('我', '你', '她', '他')) and len(text) <= 18:
            return True
        if text.endswith(('了', '着', '呢', '呀', '吧', '吗')) and len(text) <= 18:
            return True
        if field == 'immediate_goal' and len(text) <= 4:
            return True
        if field not in {'main_event', 'immediate_goal'} and actor_names and not any(name in text for name in actor_names) and '，' in text:
            return True
        return False

    for key in ['time', 'location', 'main_event', 'immediate_goal']:
        value = current.get(key)
        if not isinstance(value, str) or not value.strip():
            current[key] = prev.get(key, '待确认')
        else:
            current[key] = value.strip()

    for key in ['main_event', 'immediate_goal']:
        if _looks_like_fragmentary_core_value(current.get(key, ''), key):
            previous_value = str(prev.get(key, '') or '').strip()
            if previous_value and not _looks_like_fragmentary_core_value(previous_value, key):
                current[key] = previous_value
                continue
            active_main = next((str(item.get('label', '') or '').strip() for item in (current.get('active_threads', []) or []) if isinstance(item, dict) and str(item.get('kind', '') or '') == 'main'), '')
            if active_main and not _looks_like_fragmentary_core_value(active_main, key):
                current[key] = active_main
            elif key == 'immediate_goal':
                current[key] = '待确认'

    if isinstance(current.get('scene_entities', []), list):
        current['scene_entities'] = _filter_scene_entities_with_person_evidence(current.get('scene_entities', []), current, prev)

    entity_onstage_names = _derive_names_from_scene_entities(current.get('scene_entities', []), onstage_only=True)
    if entity_onstage_names:
        current['onstage_npcs'] = entity_onstage_names
    else:
        current['onstage_npcs'] = dedupe_names(current.get('onstage_npcs', prev.get('onstage_npcs', [])), limit=6)
    current['onstage_npcs'] = _filter_person_names_with_evidence(current['onstage_npcs'], current, prev, limit=6)
    current['relevant_npcs'] = dedupe_names(
        [name for name in current.get('relevant_npcs', prev.get('relevant_npcs', [])) if name not in current['onstage_npcs']],
        limit=6,
    )
    current['relevant_npcs'] = _filter_person_names_with_evidence(current['relevant_npcs'], current, prev, limit=6)

    current['carryover_signals'] = normalize_carryover_signals(current.get('carryover_signals', prev.get('carryover_signals', [])))
    if current['carryover_signals']:
        derived_risks, derived_clues = derive_risks_clues_from_signals(current['carryover_signals'])
        current['immediate_risks'] = normalize_text_list(derived_risks, limit=4)
        current['carryover_clues'] = normalize_text_list(derived_clues, limit=4)
    else:
        current['immediate_risks'] = normalize_text_list(current.get('immediate_risks', prev.get('immediate_risks', [])), limit=4)
        current['carryover_clues'] = normalize_text_list(current.get('carryover_clues', prev.get('carryover_clues', [])), limit=4)
    tracked_objects = current.get('tracked_objects', prev.get('tracked_objects', []))
    if not isinstance(tracked_objects, list):
        tracked_objects = prev.get('tracked_objects', []) if isinstance(prev.get('tracked_objects', []), list) else []
    prev_tracked_objects = prev.get('tracked_objects', []) if isinstance(prev.get('tracked_objects', []), list) else []
    tracked_objects = _merge_tracked_objects(prev_tracked_objects, tracked_objects)
    normalized_objects = []
    seen_object_ids: set[str] = set()
    retired_candidates = {
        str(item.get('object_id', '') or '').strip()
        for item in tracked_objects
        if isinstance(item, dict) and str(item.get('lifecycle_status', '') or '').strip() in {'consumed', 'destroyed', 'lost', 'archived'}
    }
    for idx, item in enumerate(tracked_objects):
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or f'obj_{idx + 1:02d}').strip()
        label = str(item.get('label', '') or '').strip()
        lifecycle_status = str(item.get('lifecycle_status', 'active') or 'active').strip() or 'active'
        if object_id in retired_candidates and lifecycle_status not in {'consumed', 'destroyed', 'lost', 'archived'}:
            continue
        if label == object_id:
            continue
        if _looks_like_bad_object_label(label):
            continue
        if not object_id or not label or object_id in seen_object_ids:
            continue
        seen_object_ids.add(object_id)
        normalized_item = {
            'object_id': object_id,
            'label': label,
            'kind': str(item.get('kind', '') or 'item').strip() or 'item',
            'story_relevant': bool(item.get('story_relevant', True)),
        }
        if lifecycle_status in {'consumed', 'destroyed', 'lost', 'archived'}:
            normalized_item['lifecycle_status'] = lifecycle_status
            normalized_item['lifecycle_reason'] = str(item.get('lifecycle_reason', '') or '').strip()
        normalized_objects.append(normalized_item)
    object_index = {item['object_id']: item for item in normalized_objects}
    graveyard_objects = [dict(item) for item in current.get('graveyard_objects', prev.get('graveyard_objects', [])) if isinstance(item, dict)]
    graveyard_by_id = {
        str(item.get('object_id', '') or '').strip(): item
        for item in graveyard_objects
        if str(item.get('object_id', '') or '').strip()
    }
    retired_object_ids: set[str] = set()
    for item in list(object_index.values()):
        lifecycle_status = str(item.get('lifecycle_status', 'active') or 'active').strip() or 'active'
        if lifecycle_status not in {'consumed', 'destroyed', 'lost', 'archived'}:
            continue
        object_id = item['object_id']
        retired_object_ids.add(object_id)
        graveyard_by_id[object_id] = {
            **graveyard_by_id.get(object_id, {}),
            'object_id': object_id,
            'label': item.get('label', ''),
            'kind': item.get('kind', 'item'),
            'lifecycle_status': lifecycle_status,
            'lifecycle_reason': str(item.get('lifecycle_reason', '') or '').strip(),
        }
        object_index.pop(object_id, None)

    possession_state = current.get('possession_state', prev.get('possession_state', []))
    if not isinstance(possession_state, list):
        possession_state = prev.get('possession_state', []) if isinstance(prev.get('possession_state', []), list) else []
    normalized_possession = []
    seen_possession: set[str] = set()
    early_holder_lookup = _entity_lookup_by_name(
        (current.get('scene_entities', []) if isinstance(current.get('scene_entities', []), list) else [])
        + (prev.get('scene_entities', []) if isinstance(prev.get('scene_entities', []), list) else [])
    )
    actor_name_lookup: dict[str, str] = {}
    actor_source = current.get('actors', prev.get('actors', {}))
    if isinstance(actor_source, dict):
        for actor_id, actor in actor_source.items():
            if not isinstance(actor, dict):
                continue
            for raw_name in [actor.get('name', '')] + list(actor.get('aliases', []) or []):
                actor_name = sanitize_runtime_name(raw_name)
                if actor_name:
                    actor_name_lookup[actor_name] = str(actor_id)
    valid_holders = set(current['onstage_npcs']) | set(current['relevant_npcs']) | protagonist_names() | set(early_holder_lookup.keys()) | set(actor_name_lookup.keys())
    possession_by_object: dict[str, dict] = {}
    for item in possession_state:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or '').strip()
        holder = sanitize_runtime_name(item.get('holder', ''))
        holder_entity = early_holder_lookup.get(holder)
        if holder_entity:
            holder = sanitize_runtime_name(holder_entity.get('primary_label', '')) or holder
        if not object_id or not holder:
            continue
        if valid_holders and holder not in valid_holders:
            continue
        if object_id not in object_index or object_id in retired_object_ids:
            continue
        normalized_item = {
            'object_id': object_id,
            'holder': holder,
            'status': str(item.get('status', '') or 'carried').strip() or 'carried',
            'location': str(item.get('location', '') or '').strip(),
            'updated_by_turn': str(item.get('updated_by_turn', '') or '').strip(),
        }
        holder_actor_id = str(item.get('holder_actor_id', '') or '').strip() or actor_name_lookup.get(holder, '')
        if holder_actor_id:
            normalized_item['holder_actor_id'] = holder_actor_id
        possession_by_object[object_id] = normalized_item
    for object_id, item in possession_by_object.items():
        if object_id in seen_possession:
            continue
        seen_possession.add(object_id)
        normalized_possession.append(item)
    current['possession_state'] = normalized_possession

    object_visibility = current.get('object_visibility', prev.get('object_visibility', []))
    if not isinstance(object_visibility, list):
        object_visibility = prev.get('object_visibility', []) if isinstance(prev.get('object_visibility', []), list) else []
    normalized_visibility = []
    seen_visibility: set[str] = set()
    visibility_by_object: dict[str, dict] = {}
    for item in object_visibility:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get('object_id', '') or '').strip()
        if not object_id:
            continue
        if object_id not in object_index or object_id in retired_object_ids:
            continue
        visibility = str(item.get('visibility', '') or 'private').strip() or 'private'
        if visibility not in {'private', 'public'}:
            visibility = 'private'
        visibility_item = {
            'object_id': object_id,
            'visibility': visibility,
            'known_to': [sanitize_runtime_name(name) for name in (item.get('known_to', []) or []) if sanitize_runtime_name(name)][:6],
            'note': str(item.get('note', '') or '').strip(),
        }
        known_to_actor_ids = []
        for actor_id in item.get('known_to_actor_ids', []) or []:
            actor_id_text = str(actor_id or '').strip()
            if actor_id_text and actor_id_text not in known_to_actor_ids:
                known_to_actor_ids.append(actor_id_text)
        for name in visibility_item['known_to']:
            actor_id = actor_name_lookup.get(name, '')
            if actor_id and actor_id not in known_to_actor_ids:
                known_to_actor_ids.append(actor_id)
        if known_to_actor_ids:
            visibility_item['known_to_actor_ids'] = known_to_actor_ids[:6]
        visibility_by_object[object_id] = visibility_item
    for object_id, item in visibility_by_object.items():
        if object_id in seen_visibility:
            continue
        seen_visibility.add(object_id)
        normalized_visibility.append(item)
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
    current['graveyard_objects'] = list(graveyard_by_id.values())[-40:]

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
    current['scene_entities'] = _filter_scene_entities_with_person_evidence(current.get('scene_entities', []), current, prev)
    entity_onstage_names = _derive_names_from_scene_entities(current.get('scene_entities', []), onstage_only=True)
    if entity_onstage_names:
        current['onstage_npcs'] = _filter_person_names_with_evidence(entity_onstage_names, current, prev, limit=6)
    else:
        current['onstage_npcs'] = _filter_person_names_with_evidence(current.get('onstage_npcs', []), current, prev, limit=6)
    arbiter_signals = current.get('arbiter_signals', {})
    if not isinstance(arbiter_signals, dict):
        arbiter_signals = {}
    current['arbiter_signals'] = arbiter_signals
    state_keeper_diagnostics = current.get('state_keeper_diagnostics', prev.get('state_keeper_diagnostics', {}))
    if not isinstance(state_keeper_diagnostics, dict):
        state_keeper_diagnostics = prev.get('state_keeper_diagnostics', {}) if isinstance(prev.get('state_keeper_diagnostics', {}), dict) else {}
    current['state_keeper_diagnostics'] = state_keeper_diagnostics
    active_threads = current.get('active_threads', prev.get('active_threads', []))
    if not isinstance(active_threads, list):
        active_threads = prev.get('active_threads', []) if isinstance(prev.get('active_threads', []), list) else []
    current['active_threads'] = active_threads
    current['relevant_npcs'] = dedupe_names(
        [name for name in current.get('relevant_npcs', []) if name not in current['onstage_npcs']],
        limit=6,
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
            active_threads=current.get('active_threads', []),
            onstage=primary in set(current.get('onstage_npcs', []) or []),
            relevant=primary in set(current.get('relevant_npcs', []) or []),
        )
    important_npcs = current.get('important_npcs', prev.get('important_npcs', []))
    if not isinstance(important_npcs, list):
        important_npcs = prev.get('important_npcs', []) if isinstance(prev.get('important_npcs', []), list) else []
    protected_entity_names = {
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (current.get('scene_entities', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    }
    current['important_npcs'] = _normalize_important_npcs(
        important_npcs,
        protected_entity_names,
        set(current.get('onstage_npcs', []) or []),
        set(current.get('relevant_npcs', []) or []),
    )
    recovered_relevant = _recover_relevant_from_continuity(current, prev)
    if recovered_relevant:
        current['relevant_npcs'] = _filter_person_names_with_evidence(dedupe_names(current.get('relevant_npcs', []) + recovered_relevant, limit=6), current, prev, limit=6)
    recovered_names = _recover_names_from_structure(current, prev)
    if recovered_names:
        current['relevant_npcs'] = _filter_person_names_with_evidence(dedupe_names(current.get('relevant_npcs', []) + recovered_names, limit=6), current, prev, limit=6)
        if not current.get('scene_entities'):
            current['scene_entities'] = fallback_scene_entities(recovered_names)
            current['scene_entities'] = _filter_scene_entities_with_person_evidence(current.get('scene_entities', []), current, prev)
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
    current['state_keeper_bootstrapped'] = bool(current.get('state_keeper_bootstrapped', prev.get('state_keeper_bootstrapped', False)))

    if session_id:
        current['session_id'] = session_id
    elif prev.get('session_id'):
        current['session_id'] = prev['session_id']

    # knowledge_scope is a per-turn delta; long-term knowledge lives in knowledge_records.
    current['knowledge_scope'] = _coerce_knowledge_scope_delta(current.get('knowledge_scope', {}))

    current = _apply_object_entity_bindings(current)

    return current


def fallback_scene_entities(names: Iterable[str]) -> list[dict]:
    out: list[dict] = []
    clean_names = dedupe_names(names)
    for idx, name in enumerate(clean_names, start=1):
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
        'scene_entities': entities,
        'onstage_npcs': onstage,
        'relevant_npcs': relevant,
        'immediate_goal': immediate_goal or '待确认',
        'immediate_risks': extract_list_entries(text, 'Immediate Risks'),
        'carryover_clues': extract_list_entries(text, 'Carryover Clues'),
    }
