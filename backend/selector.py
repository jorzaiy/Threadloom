#!/usr/bin/env python3
from __future__ import annotations

import json
import re

try:
    from .name_sanitizer import looks_like_bad_entity_fragment
except ImportError:
    from name_sanitizer import looks_like_bad_entity_fragment


GENERIC_TOPIC_TOKENS = {
    '当前', '继续', '已经', '没有', '还有', '一个', '一些', '自己', '觉得', '开始',
    '位置', '地方', '时候', '周围', '后面', '前面', '然后', '只是', '不是', '可能',
    '主角', '用户', '玩家', '叙事', '正文', '世界', '反馈', '动作', '事情',
}

WEAK_RECALL_TOKENS = {
    '陆小环的', '的呼吸', '的呼吸声', '脚步落在', '一下一下', '刻意压低',
}
WEAK_RECALL_SUFFIXES = ('的', '地')
WEAK_RECALL_PARTS = ('呼吸', '脚步', '声音', '目光', '视线')
WEAK_MUNDANE_RECALL_HINTS = ('吃', '喝', '拿', '放', '买', '卖', '穿', '用', '休息', '打坐', '恢复', '整理', '等待', '走', '去')

PRESSURE_TOKENS = {
    '风险', '危险', '威胁', '暴露', '怀疑', '审查', '盘问', '追踪', '追捕', '封锁', '惩罚', '倒计时',
    '监视', '监控', '警告', '失控', '逼近', '逃跑', '退学', '查过', '异常',
}
WEAKNESS_TOKENS = {
    '弱点', '弱势', '虚弱', '缺氧', '呼吸困难', '身体限制', '身体不适', '伪装破绽', '旧伤',
    '疼痛', '受伤', '肿胀', '发紫', '青紫', '手抖', '发抖', '体力不支', '撑不住', '暴露', '可疑',
}
ABSTRACT_NPC_TOKENS = {
    '时间', '空间', '规则', '概念', '逻辑', '关系', '事件', '问题', '目标', '答案', '线索', '风险',
    '情报', '记忆', '意识', '状态', '流程', '步骤', '进度', '盲区', '栏目', '标题', '课题', '题目',
}

PROFILE_DETAIL_TRIGGERS = {
    'appearance': ('外貌', '样子', '穿着', '打量', '看起来', '伪装', '认出', '受伤', '伤口'),
    'abilities': ('能力', '擅长', '施展', '使用', '尝试', '战斗', '修炼', '训练', '检查', '破解'),
    'personality': ('性格', '反应', '害怕', '喜欢', '讨厌', '犹豫', '决定', '内心', '想法'),
    'preferences': ('喜欢', '偏好', '讨厌', '舒服', '不舒服', '想要'),
    'background': ('背景', '身世', '过去', '以前', '小时候', '家', '家人', '出身', '来历', '故乡', '回忆'),
    'psychology': ('心理', '内心', '动机', '目标', '害怕', '创伤', '回忆', '为什么', '选择'),
    'worldAdaptation': ('世界', '适配', '身份', '设定', '规则'),
    'privateBoundaries': ('秘密', '私密', '真实身份', '伪装', '弱点', '暴露', '识破', '隐瞒', '旧伤'),
}

BACKGROUND_EVENT_RECALL_TRIGGERS = (
    '来历', '背景', '过去', '以前', '出身', '家里', '故乡', '回忆', '为什么', '怎么回事', '原因', '什么关系', '听说'
)
SERVICE_ROLE_SUFFIXES = ('老板', '掌柜', '店主', '老板娘', '掌柜的')


def _valid_npc_name(name: str) -> bool:
    text = str(name or '').strip()
    if not text or looks_like_bad_entity_fragment(text) or text in ABSTRACT_NPC_TOKENS:
        return False
    if any(text.endswith(suffix) for suffix in ('栏', '栏位', '栏目', '盲区', '概念', '规则', '逻辑', '问题', '答案', '题目', '课题')):
        return False
    return True


def joined_recent_text(recent_history: list[dict], limit: int = 6) -> str:
    parts = []
    for item in recent_history[-limit:]:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get('content', '') or ''))
    return '\n'.join(parts)


def _topic_tokens(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r'[\u4e00-\u9fff]{2,8}|[A-Za-z][A-Za-z0-9_-]{1,20}', str(text or '')):
        if token in GENERIC_TOPIC_TOKENS:
            continue
        tokens.add(token)
    return tokens


def _pressure_tokens(text: str) -> set[str]:
    value = str(text or '')
    return {token for token in PRESSURE_TOKENS if token in value}


def _sensitive_tokens(text: str) -> set[str]:
    value = str(text or '')
    return {token for token in (PRESSURE_TOKENS | WEAKNESS_TOKENS) if token in value}


def _strong_keywords(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items or []:
        token = str(item or '').strip()
        if not token or token in WEAK_RECALL_TOKENS or token in GENERIC_TOPIC_TOKENS:
            continue
        if len(token) < 3:
            continue
        if token.endswith(WEAK_RECALL_SUFFIXES):
            continue
        if len(token) <= 5 and any(part in token for part in WEAK_RECALL_PARTS):
            continue
        out.append(token)
    return out


def _background_event_recall_requested(user_text: str, current_text: str) -> bool:
    value = f'{user_text}\n{current_text}'
    return any(trigger in value for trigger in BACKGROUND_EVENT_RECALL_TRIGGERS)


def _long_range_query_anchors(state_json: dict, user_text: str, current_text: str) -> set[str]:
    anchors: set[str] = set()
    for field in ('onstage_npcs', 'relevant_npcs'):
        for item in state_json.get(field, []) or []:
            text = str(item or '').strip()
            if _valid_npc_name(text):
                anchors.add(text)
    for token in _topic_tokens(f'{user_text}\n{current_text}'):
        if len(token) >= 2 and token not in GENERIC_TOPIC_TOKENS:
            anchors.add(token)
        for suffix in SERVICE_ROLE_SUFFIXES:
            idx = token.find(suffix)
            if idx > 0:
                prefix = token[:idx]
                for size in range(1, min(4, len(prefix)) + 1):
                    base = prefix[-size:]
                    alias = f'{base}{suffix}'
                    anchors.add(base)
                    anchors.add(alias)
                    if suffix in {'老板', '老板娘'}:
                        anchors.add(f'{base}掌柜')
                    if suffix in {'掌柜', '掌柜的'}:
                        anchors.add(f'{base}老板')
    for match in re.findall(r'[\u4e00-\u9fff]{1,6}(?:老板娘|掌柜的|老板|掌柜|店主)', f'{user_text}\n{current_text}'):
        anchors.add(match)
        for suffix in SERVICE_ROLE_SUFFIXES:
            if match.endswith(suffix) and len(match) > len(suffix):
                base = match[:-len(suffix)]
                anchors.add(base)
                if suffix in {'老板', '老板娘'}:
                    anchors.add(f'{base}掌柜')
                if suffix in {'掌柜', '掌柜的'}:
                    anchors.add(f'{base}老板')
    if '井' in str(user_text or '') or '井' in str(current_text or ''):
        anchors.add('井')
    return {anchor for anchor in anchors if len(anchor) >= 1 and anchor not in GENERIC_TOPIC_TOKENS}


def _long_range_event_candidates(event_summaries: list[dict], recent_events: list[dict], *, state_json: dict, user_text: str, current_text: str, limit: int = 24) -> list[dict]:
    if not _background_event_recall_requested(user_text, current_text):
        return []
    recent_ids = {str(item.get('event_id') or item.get('turn_id') or '').strip() for item in recent_events if isinstance(item, dict)}
    anchors = _long_range_query_anchors(state_json, user_text, current_text)
    explicit_anchors = _long_range_query_anchors({}, user_text, '')
    if not anchors:
        return []
    current_actor_names = {
        str(name or '').strip()
        for field in ('onstage_npcs', 'relevant_npcs')
        for name in (state_json.get(field, []) or [])
        if str(name or '').strip()
    }
    scored: list[tuple[float, int, dict]] = []
    for idx, item in enumerate(event_summaries or []):
        if not isinstance(item, dict):
            continue
        event_id = str(item.get('event_id') or item.get('turn_id') or '').strip()
        if event_id in recent_ids:
            continue
        event_text = _event_text(item)
        anchor_hits = [anchor for anchor in anchors if anchor and anchor in event_text]
        explicit_anchor_hits = [anchor for anchor in explicit_anchors if anchor and anchor in event_text]
        actor_hits = [str(actor or '').strip() for actor in (item.get('actors', []) or []) if str(actor or '').strip() in current_actor_names]
        if not explicit_anchor_hits and len(anchor_hits) < 2:
            continue
        score = len(set(anchor_hits)) * 1.25 + len(set(explicit_anchor_hits)) * 2.0 + len(set(actor_hits)) * 0.75
        if any(trigger in event_text for trigger in BACKGROUND_EVENT_RECALL_TRIGGERS):
            score += 1.0
        if score < 2.5:
            continue
        scored.append((score, _turn_index(item, idx + 1), item))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [item for _score, _turn, item in scored[:limit]]


def _looks_like_weak_mundane_query(text: str) -> bool:
    value = str(text or '').strip()
    if not value:
        return False
    tokens = _topic_tokens(value)
    if len(tokens) > 2:
        return False
    return any(hint in value for hint in WEAK_MUNDANE_RECALL_HINTS)


def _knowledge_record_overlap(chunk_text: str, knowledge_texts: list[str]) -> list[str]:
    hits: list[str] = []
    normalized_chunk = re.sub(r'[，。！？、；：,.!?;:\s"“”‘’（）()【】\[\]]+', '', str(chunk_text or ''))
    for text in knowledge_texts:
        value = str(text or '').strip()
        if len(value) < 8:
            continue
        normalized_value = re.sub(r'[，。！？、；：,.!?;:\s"“”‘’（）()【】\[\]]+', '', value)
        if normalized_value[:8] in normalized_chunk:
            hits.append(value)
            continue
        for idx in range(0, max(0, len(normalized_value) - 5)):
            if normalized_value[idx:idx + 6] in normalized_chunk:
                hits.append(value)
                break
    return hits


def _event_lookup(event_summaries: list[dict]) -> dict[str, dict]:
    event_by_id: dict[str, dict] = {}
    for item in event_summaries or []:
        if not isinstance(item, dict):
            continue
        for key in ('event_id', 'turn_id'):
            value = str(item.get(key, '') or '').strip()
            if value:
                event_by_id[value] = item
    return event_by_id


def _event_hit_text(event_hits: list[dict], event_summaries: list[dict]) -> str:
    event_by_id = _event_lookup(event_summaries)
    parts = []
    for hit in event_hits or []:
        event = event_by_id.get(str(hit.get('event_id', '') or ''))
        if not isinstance(event, dict):
            continue
        parts.append(_event_text(event))
    return '\n'.join(parts)


def _event_hit_ids(event_hits: list[dict]) -> set[str]:
    return {str(hit.get('event_id', '') or '').strip() for hit in event_hits or [] if str(hit.get('event_id', '') or '').strip()}


def _event_hit_topics(event_hits: list[dict], event_summaries: list[dict]) -> set[str]:
    event_by_id = _event_lookup(event_summaries)
    tokens: set[str] = set()
    for event_id in _event_hit_ids(event_hits):
        item = event_by_id.get(event_id)
        if isinstance(item, dict):
            tokens |= _topic_tokens(_event_text(item))
    return tokens


def _event_text(item: dict) -> str:
    pieces = []
    for field in ('event_id', 'title', 'label', 'summary', 'result', 'claim', 'location', 'main_event'):
        pieces.append(str(item.get(field, '') or ''))
    for field in ('actors', 'keywords', 'open_loops', 'unresolved', 'signals'):
        value = item.get(field, [])
        if isinstance(value, list):
            pieces.extend(str(x or '') for x in value)
    return ' '.join(pieces)


def _turn_index(item: dict, fallback: int = 0) -> int:
    for field in ('turn_id', 'event_id'):
        text = str(item.get(field, '') or '')
        match = re.search(r'(\d+)$', text)
        if match:
            try:
                return int(match.group(1))
            except Exception:
                return fallback
    return fallback


def _repeated_token_counts(items: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        tokens = _topic_tokens(' '.join(str(x or '') for x in (item.get('clues', []) or [])))
        tokens |= _topic_tokens(' '.join(str(x or '') for x in (item.get('signals', []) or [])))
        for token in tokens:
            counts[token] = counts.get(token, 0) + 1
    return counts


def event_summary_hits(event_summaries: list[dict], *, state_json: dict, recent_history: list[dict], user_text: str = '') -> list[dict]:
    recent_text = joined_recent_text(recent_history)
    current_text = '\n'.join([
        str(user_text or ''),
        str(state_json.get('location', '') or ''),
        str(state_json.get('main_event', '') or ''),
    ])
    carryover_text = '\n'.join([
        ' '.join(str(x or '') for x in (state_json.get('immediate_risks', []) or [])),
        ' '.join(str(x.get('text', '') or '') for x in (state_json.get('carryover_signals', []) or []) if isinstance(x, dict)),
    ])
    query_text = '\n'.join([
        recent_text,
        current_text,
        ' '.join(str(x or '') for x in (state_json.get('onstage_npcs', []) or [])),
        ' '.join(str(x or '') for x in (state_json.get('relevant_npcs', []) or [])),
        carryover_text,
    ])
    actor_context_text = '\n'.join([
        recent_text,
        current_text,
        ' '.join(str(x or '') for x in (state_json.get('onstage_npcs', []) or [])),
        ' '.join(str(x or '') for x in (state_json.get('relevant_npcs', []) or [])),
    ])
    query_tokens = _topic_tokens(query_text)
    current_tokens = _topic_tokens(current_text)
    recent_tokens = _topic_tokens(recent_text)
    location_tokens = _topic_tokens(str(state_json.get('location', '') or ''))
    carryover_tokens = _topic_tokens(carryover_text)
    weak_mundane_query = _looks_like_weak_mundane_query(user_text)
    recent_events = [item for item in event_summaries[-20:] if isinstance(item, dict)]
    long_range_events = _long_range_event_candidates(event_summaries, recent_events, state_json=state_json, user_text=user_text, current_text=current_text)
    long_range_ids = {str(item.get('event_id') or item.get('turn_id') or '').strip() for item in long_range_events if isinstance(item, dict)}
    long_range_explicit_anchors = _long_range_query_anchors({}, user_text, '')
    candidate_events = recent_events + long_range_events
    repeated_counts = _repeated_token_counts(recent_events)
    latest_turn = max((_turn_index(item, idx + 1) for idx, item in enumerate(candidate_events)), default=0)
    hits = []
    seen_clues: set[str] = set()
    for idx, item in enumerate(candidate_events):
        if not isinstance(item, dict):
            continue
        event_tokens = _topic_tokens(_event_text(item))
        shared = sorted(query_tokens & event_tokens)
        current_shared = sorted(current_tokens & event_tokens)
        recent_shared = sorted(recent_tokens & event_tokens)
        location_shared = sorted(location_tokens & event_tokens)
        carryover_shared = sorted(carryover_tokens & event_tokens)
        clue_key = '\n'.join(sorted(str(clue or '').strip() for clue in (item.get('clues', []) or []) if str(clue or '').strip()))
        actor_bonus = 0
        for name in (item.get('actors', []) or []):
            if str(name or '').strip() and str(name).strip() in actor_context_text:
                actor_bonus += 1
        event_text = _event_text(item)
        if weak_mundane_query and actor_bonus == 0 and not current_shared and not location_shared and not carryover_shared:
            continue
        event_sensitive = _sensitive_tokens(event_text)
        user_sensitive = _sensitive_tokens(user_text)
        explicit_user_overlap = bool(_topic_tokens(str(user_text or '')) & event_tokens)
        if event_sensitive and not user_sensitive and not current_shared and not location_shared and not carryover_shared and not explicit_user_overlap:
            continue
        if carryover_shared and not current_shared and not recent_shared and not location_shared and actor_bonus == 0:
            continue
        if clue_key and clue_key in seen_clues and carryover_shared and not current_shared and not location_shared:
            continue
        turn_idx = _turn_index(item, idx + 1)
        distance = max(0, latest_turn - turn_idx) if latest_turn else 0
        recency_bonus = max(0.0, 2.0 - min(distance, 8) * 0.25)
        repeated_penalty = sum(1 for token in shared if repeated_counts.get(token, 0) >= 4) * 0.5
        score = (len(shared) * 0.75) + (len(current_shared) * 2.0) + len(location_shared) + actor_bonus + recency_bonus - repeated_penalty
        event_id = str(item.get('event_id') or item.get('turn_id') or '').strip()
        if event_id in long_range_ids:
            explicit_anchor_hits = [anchor for anchor in long_range_explicit_anchors if anchor and anchor in event_text]
            score += 2.0 + len(set(explicit_anchor_hits)) * 2.0
        if score <= 0:
            continue
        if clue_key:
            seen_clues.add(clue_key)
        hits.append({
            'event_id': item.get('event_id') or item.get('turn_id'),
            'score': score,
            'reason': 'long_range_background' if event_id in long_range_ids else 'topic_overlap',
            'keyword_hits': (current_shared + [token for token in shared if token not in current_shared])[:8],
            'turn_index': turn_idx,
        })
    hits.sort(key=lambda x: (-x['score'], -int(x.get('turn_index', 0) or 0)))
    return hits[:4]


def candidate_name_hits(candidates: list[dict], text: str, limit: int = 3) -> int:
    haystack = str(text or '')
    hits = 0
    for item in candidates[:limit * 2]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '') or '').strip()
        if name and name in haystack:
            hits += 1
            if hits >= limit:
                break
    return hits


def important_npc_names(items: list[dict], limit: int = 4) -> list[str]:
    names = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('primary_label', '') or '').strip()
        if _valid_npc_name(name) and name not in names:
            names.append(name)
    return names


def should_inject_lorebook_text(state_json: dict, recent_history: list[dict], keeper_records: dict, lorebook_entries: list[dict], active_threads: list[dict], user_text: str = '') -> bool:
    if not lorebook_entries:
        return False
    trigger_text = str(user_text or '')
    if not trigger_text.strip():
        return False
    for entry in lorebook_entries[:6]:
        title = str(entry.get('title', '') or '').strip()
        if title and title in trigger_text:
            return True
        for keyword in entry.get('keywords', []) or []:
            token = str(keyword or '').strip()
            if token and token in trigger_text:
                return True
    return False


def should_inject_npc_candidates(onstage: list[str], relevant: list[str], active_threads: list[dict], recent_history: list[dict], important_npcs: list[dict], candidates: list[dict]) -> bool:
    recent_text = joined_recent_text(recent_history)
    hits = candidate_name_hits(candidates, recent_text)
    if any(name and name in recent_text for name in relevant[:3]):
        return True
    if hits >= 1:
        return True
    return False


def profile_targets(onstage: list[str], relevant: list[str], active_threads: list[dict], recent_history: list[dict], important_npcs: list[dict], limit: int = 3, event_hits: list[dict] | None = None, event_summaries: list[dict] | None = None) -> list[str]:
    targets = []
    recent_text = joined_recent_text(recent_history)
    selected_event_text = _event_hit_text(event_hits or [], event_summaries or [])
    for name in onstage:
        if _valid_npc_name(name) and name not in targets:
            targets.append(name)
    for name in relevant:
        if len(targets) >= limit:
            break
        if _valid_npc_name(name) and name in recent_text and name not in targets:
            targets.append(name)
    for name in important_npc_names(important_npcs):
        if len(targets) >= limit:
            break
        if _valid_npc_name(name) and (name in recent_text or name in selected_event_text) and name not in targets:
            targets.append(name)
    return targets[:limit]


def build_npc_roster(*, onstage: list[str], relevant: list[str], active_threads: list[dict], important_npcs: list[dict], event_hits: list[dict], event_summaries: list[dict], limit: int = 5) -> list[dict]:
    event_by_id = _event_lookup(event_summaries)
    scored = {}
    def touch(name: str, score: int, role: str = '', status: str = ''):
        if not _valid_npc_name(name):
            return
        item = scored.setdefault(name, {'name': name, 'score': 0, 'role': '', 'status': ''})
        item['score'] += score
        if role and not item['role']:
            item['role'] = role
        if status and not item['status']:
            item['status'] = status

    important_by_name = {str(item.get('primary_label', '') or '').strip(): item for item in important_npcs if isinstance(item, dict)}
    for name in onstage:
        touch(str(name).strip(), 4)
    for name in relevant[:3]:
        touch(str(name).strip(), 3, status='当前相关人物')
    for hit in event_hits:
        event = event_by_id.get(str(hit.get('event_id', '') or ''))
        if not isinstance(event, dict):
            continue
        for actor in event.get('actors', []) or []:
            touch(str(actor).strip(), 2)
    for name, item in important_by_name.items():
        role = str(item.get('role_label', '') or '').strip()
        touch(name, 1, role=role, status='当前重要人物')
    # fallback: if no signals, still keep a few obvious current actors from onstage/important
    if not scored:
        for name in onstage[:3]:
            touch(str(name).strip(), 3, status='当前在场人物')
        for name, item in list(important_by_name.items())[:2]:
            role = str(item.get('role_label', '') or '').strip()
            touch(name, 1, role=role, status='当前重要人物')
        latest_event = next((item for item in reversed(event_summaries) if isinstance(item, dict) and (item.get('actors') or [])), None)
        if isinstance(latest_event, dict):
            for name in latest_event.get('actors', [])[:3]:
                touch(str(name).strip(), 2, status='近期事件相关人物')
    result = []
    for item in sorted(scored.values(), key=lambda x: (-x['score'], x['name']))[:limit]:
        if not item['role']:
            item['role'] = '当前相关人物'
        if not item['status']:
            item['status'] = '与当前局势存在直接关联'
        result.append({'name': item['name'], 'role': item['role'], 'status': item['status']})
    return result


def summary_chunk_hits(summary_chunks: list[dict], *, recent_history: list[dict], user_text: str = '', tracked_objects: list[dict] | None = None, knowledge_records: list[dict] | None = None, event_hits: list[dict] | None = None, event_summaries: list[dict] | None = None) -> list[dict]:
    recent_text = joined_recent_text(recent_history)
    query_text = '\n'.join([recent_text, str(user_text or '')])
    object_labels = []
    for item in (tracked_objects or []):
        if not isinstance(item, dict):
            continue
        label = str(item.get('label', '') or '').strip()
        if label:
            object_labels.append(label)
        for alias in (item.get('aliases', []) or []):
            a = str(alias or '').strip()
            if a and a not in object_labels:
                object_labels.append(a)
    knowledge_texts = [str(item.get('text', '') or '').strip() for item in (knowledge_records or []) if isinstance(item, dict) and str(item.get('text', '') or '').strip()]
    weak_mundane_query = _looks_like_weak_mundane_query(user_text)
    selected_event_topics = _event_hit_topics(event_hits or [], event_summaries or [])
    hits = []
    for item in summary_chunks[-12:]:
        if not isinstance(item, dict):
            continue
        score = 0
        reason = []
        actors = [str(x).strip() for x in (item.get('actors_mentioned', []) or []) if _valid_npc_name(str(x).strip())]
        actor_overlap = any(name and name in query_text for name in actors)
        if actor_overlap:
            score += 2
            reason.append('actor_overlap')
        event_objects = [str(x).strip() for x in (item.get('objects_mentioned', []) or []) if str(x).strip()]
        object_overlap = any(obj in event_objects for obj in object_labels)
        if object_overlap:
            score += 2
            reason.append('object_overlap')
        chunk_text = ' '.join(str(x or '') for field in ('dense_summary', 'key_events', 'unresolved', 'keywords', 'locations') for x in (item.get(field, []) or []))
        chunk_topics = _topic_tokens(chunk_text)
        knowledge_hits = _knowledge_record_overlap(chunk_text, knowledge_texts)
        clue_overlap = bool(knowledge_hits)
        if clue_overlap:
            score += 2
            reason.append('knowledge_overlap')
        keyword_hits = _strong_keywords([str(keyword).strip() for keyword in (item.get('keywords', []) or []) if str(keyword).strip() and str(keyword).strip() in query_text])
        keyword_overlap = bool(keyword_hits)
        if keyword_overlap:
            score += 2
            reason.append('keyword_overlap')
        if not keyword_overlap and not actor_overlap and not object_overlap and not clue_overlap:
            shared_topics = chunk_topics & _topic_tokens(query_text)
            if weak_mundane_query:
                shared_topics = set()
            if len(shared_topics) >= 2:
                score += min(3, len(shared_topics))
                reason.append('topic_overlap')
        chunk_pressure = _pressure_tokens(chunk_text)
        chunk_sensitive = _sensitive_tokens(chunk_text)
        user_sensitive = _sensitive_tokens(user_text)
        explicit_user_overlap = bool(_topic_tokens(str(user_text or '')) & _topic_tokens(chunk_text))
        if chunk_sensitive and not user_sensitive and not object_overlap and not clue_overlap and not explicit_user_overlap:
            continue
        if chunk_pressure and not user_sensitive and not object_overlap and not clue_overlap:
            score -= 1.5
            reason.append('pressure_downgrade')
        has_direct_anchor = bool(keyword_overlap or object_overlap or actor_overlap)
        if clue_overlap:
            has_direct_anchor = has_direct_anchor or any(hit and hit in query_text for hit in knowledge_hits)
        if clue_overlap and not has_direct_anchor and not keyword_overlap and not object_overlap:
            score -= 1
            reason.append('archival_knowledge_only')
        if selected_event_topics and not object_overlap and not clue_overlap and not explicit_user_overlap and (chunk_topics & selected_event_topics):
            continue
        if selected_event_topics and not object_overlap and not keyword_overlap and (chunk_topics & selected_event_topics):
            score -= 2
            reason.append('event_hit_covers_topic')
        reason_text = '+'.join(reason)
        if score >= 3 and has_direct_anchor:
            hits.append({'chunk_id': item.get('chunk_id'), 'turn_start': item.get('turn_start'), 'turn_end': item.get('turn_end'), 'score': score, 'reason': reason_text, 'keyword_hits': keyword_hits[:8]})
        elif score >= 3 and 'topic_overlap' in reason:
            hits.append({'chunk_id': item.get('chunk_id'), 'turn_start': item.get('turn_start'), 'turn_end': item.get('turn_end'), 'score': score, 'reason': reason_text})
    hits.sort(key=lambda x: -x['score'])
    return hits[:2]


def player_profile_detail_hits(profile_sections: list[dict], *, state_json: dict, recent_history: list[dict], user_text: str = '') -> list[dict]:
    if not isinstance(profile_sections, list) or not profile_sections:
        return []
    recent_text = joined_recent_text(recent_history)
    current_text = '\n'.join([
        str(user_text or ''),
        str(state_json.get('location', '') or ''),
        str(state_json.get('main_event', '') or ''),
        str(state_json.get('immediate_goal', '') or ''),
    ])
    query_text = '\n'.join([current_text, recent_text])
    query_tokens = _topic_tokens(query_text)
    user_tokens = _topic_tokens(str(user_text or ''))
    weak_mundane_query = _looks_like_weak_mundane_query(user_text)
    hits = []
    for section in profile_sections:
        if not isinstance(section, dict):
            continue
        section_id = str(section.get('section_id', '') or '').strip()
        section_text = str(section.get('text', '') or '')
        if not section_id or not section_text.strip():
            continue
        section_tokens = _topic_tokens(section_text)
        shared = sorted(query_tokens & section_tokens)
        user_shared = sorted(user_tokens & section_tokens)
        trigger_hits = [token for token in PROFILE_DETAIL_TRIGGERS.get(section_id, ()) if token in str(user_text or '') or token in str(state_json.get('main_event', '') or '')]
        sensitivity = str(section.get('sensitivity', '') or 'narrator_only')
        score = len(user_shared) * 3 + len(shared) + len(trigger_hits) * 2
        if weak_mundane_query and not user_shared and not trigger_hits:
            continue
        if sensitivity == 'private' and not user_shared and not trigger_hits:
            continue
        if score >= 2 and (user_shared or trigger_hits or (len(shared) >= 2 and not weak_mundane_query)):
            hits.append({
                'section_id': section_id,
                'score': score,
                'reason': '+'.join(filter(None, [
                    'user_overlap' if user_shared else '',
                    'trigger' if trigger_hits else '',
                    'topic_overlap' if shared and not user_shared else '',
                ])),
                'keyword_hits': (user_shared + [token for token in shared if token not in user_shared] + trigger_hits)[:8],
                'sensitivity': sensitivity,
            })
    hits.sort(key=lambda x: (-x['score'], x['section_id']))
    return hits[:3]


def build_selector_decision(*, state_json: dict, recent_history: list[dict], keeper_records: dict, active_threads: list[dict], important_npcs: list[dict], onstage: list[str], relevant: list[str], lorebook_entries: list[dict], system_npc_candidates: list[dict], lorebook_npc_candidates: list[dict], event_summaries: list[dict], summary_text: str, summary_chunks: list[dict] | None = None, player_profile_sections: list[dict] | None = None, user_text: str = '') -> dict:
    inject_lorebook = should_inject_lorebook_text(state_json, recent_history, keeper_records, lorebook_entries, active_threads, user_text=user_text)
    all_candidates = list(system_npc_candidates) + list(lorebook_npc_candidates)
    inject_candidates = should_inject_npc_candidates(onstage, relevant, active_threads, recent_history, important_npcs, all_candidates)
    event_hits = event_summary_hits(event_summaries, state_json=state_json, recent_history=recent_history, user_text=user_text)
    chunk_hits = summary_chunk_hits(
        summary_chunks or [],
        recent_history=recent_history,
        user_text=user_text,
        tracked_objects=state_json.get('tracked_objects', []),
        knowledge_records=state_json.get('knowledge_records', []),
        event_hits=event_hits,
        event_summaries=event_summaries,
    )
    targets = profile_targets(onstage, relevant, active_threads, recent_history, important_npcs, limit=3, event_hits=event_hits, event_summaries=event_summaries)
    inject_summary = bool(chunk_hits) and any(hit.get('score', 0) >= 2 for hit in chunk_hits)
    npc_roster = build_npc_roster(
        onstage=onstage,
        relevant=relevant,
        active_threads=active_threads,
        important_npcs=important_npcs,
        event_hits=event_hits,
        event_summaries=event_summaries,
        limit=5,
    )
    profile_detail_hits = player_profile_detail_hits(player_profile_sections or [], state_json=state_json, recent_history=recent_history, user_text=user_text)
    return {
        'selector_version': 2,
        'inject_lorebook_text': inject_lorebook,
        'inject_npc_candidates': inject_candidates,
        'npc_profile_targets': targets,
        'event_hits': event_hits,
        'summary_chunk_hits': chunk_hits,
        'inject_summary': inject_summary,
        'npc_roster': npc_roster,
        'player_profile_detail_hits': profile_detail_hits,
        'inject_player_profile_detail': bool(profile_detail_hits),
    }
