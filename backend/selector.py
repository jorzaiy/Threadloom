#!/usr/bin/env python3
from __future__ import annotations

import json
import re


GENERIC_TOPIC_TOKENS = {
    '当前', '继续', '已经', '没有', '还有', '一个', '一些', '自己', '觉得', '开始',
    '位置', '地方', '时候', '周围', '后面', '前面', '然后', '只是', '不是', '可能',
}


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
    query_text = '\n'.join([
        recent_text,
        current_text,
        ' '.join(str(x or '') for x in (state_json.get('onstage_npcs', []) or [])),
        ' '.join(str(x or '') for x in (state_json.get('relevant_npcs', []) or [])),
        ' '.join(str(x or '') for x in (state_json.get('immediate_risks', []) or [])),
        ' '.join(str(x.get('text', '') or '') for x in (state_json.get('carryover_signals', []) or []) if isinstance(x, dict)),
    ])
    query_tokens = _topic_tokens(query_text)
    current_tokens = _topic_tokens(current_text)
    location_tokens = _topic_tokens(str(state_json.get('location', '') or ''))
    recent_events = [item for item in event_summaries[-20:] if isinstance(item, dict)]
    repeated_counts = _repeated_token_counts(recent_events)
    latest_turn = max((_turn_index(item, idx + 1) for idx, item in enumerate(recent_events)), default=0)
    hits = []
    for idx, item in enumerate(recent_events):
        if not isinstance(item, dict):
            continue
        event_tokens = _topic_tokens(_event_text(item))
        shared = sorted(query_tokens & event_tokens)
        current_shared = sorted(current_tokens & event_tokens)
        location_shared = sorted(location_tokens & event_tokens)
        actor_bonus = 0
        for name in (item.get('actors', []) or []):
            if str(name or '').strip() and str(name).strip() in query_text:
                actor_bonus += 1
        turn_idx = _turn_index(item, idx + 1)
        distance = max(0, latest_turn - turn_idx) if latest_turn else 0
        recency_bonus = max(0.0, 2.0 - min(distance, 8) * 0.25)
        repeated_penalty = sum(1 for token in shared if repeated_counts.get(token, 0) >= 4) * 0.5
        score = (len(shared) * 0.75) + (len(current_shared) * 2.0) + len(location_shared) + actor_bonus + recency_bonus - repeated_penalty
        if score <= 0:
            continue
        hits.append({
            'event_id': item.get('event_id'),
            'score': score,
            'reason': 'topic_overlap',
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
        if name and name not in names:
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


def profile_targets(onstage: list[str], relevant: list[str], active_threads: list[dict], recent_history: list[dict], important_npcs: list[dict], limit: int = 3) -> list[str]:
    targets = []
    recent_text = joined_recent_text(recent_history)
    for name in onstage:
        if name and name not in targets:
            targets.append(name)
    for name in relevant:
        if len(targets) >= limit:
            break
        if name and name in recent_text and name not in targets:
            targets.append(name)
    for name in important_npc_names(important_npcs):
        if len(targets) >= limit:
            break
        if name and name in recent_text and name not in targets:
            targets.append(name)
    return targets[:limit]


def build_npc_roster(*, onstage: list[str], relevant: list[str], active_threads: list[dict], important_npcs: list[dict], event_hits: list[dict], event_summaries: list[dict], limit: int = 5) -> list[dict]:
    event_by_id = {str(item.get('event_id', '') or ''): item for item in event_summaries if isinstance(item, dict)}
    scored = {}
    def touch(name: str, score: int, role: str = '', status: str = ''):
        if not name:
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


def summary_chunk_hits(summary_chunks: list[dict], *, recent_history: list[dict], user_text: str = '', tracked_objects: list[dict] | None = None, knowledge_records: list[dict] | None = None) -> list[dict]:
    recent_text = joined_recent_text(recent_history)
    query_text = '\n'.join([recent_text, str(user_text or '')])
    object_labels = [str(item.get('label', '') or '').strip() for item in (tracked_objects or []) if isinstance(item, dict) and str(item.get('label', '') or '').strip()]
    knowledge_texts = [str(item.get('text', '') or '').strip() for item in (knowledge_records or []) if isinstance(item, dict) and str(item.get('text', '') or '').strip()]
    hits = []
    for item in summary_chunks[-12:]:
        if not isinstance(item, dict):
            continue
        score = 0
        reason = []
        actors = [str(x).strip() for x in (item.get('actors_mentioned', []) or []) if str(x).strip()]
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
        clue_overlap = any(text and text[:8] in chunk_text for text in knowledge_texts if len(text) >= 8)
        if clue_overlap:
            score += 2
            reason.append('knowledge_overlap')
        keyword_hits = [str(keyword).strip() for keyword in (item.get('keywords', []) or []) if str(keyword).strip() and str(keyword).strip() in query_text]
        keyword_overlap = bool(keyword_hits)
        if keyword_overlap:
            score += 2
            reason.append('keyword_overlap')
        if not keyword_overlap and not actor_overlap and not object_overlap and not clue_overlap:
            shared_topics = _topic_tokens(chunk_text) & _topic_tokens(query_text)
            if len(shared_topics) >= 2:
                score += min(3, len(shared_topics))
                reason.append('topic_overlap')
        if score >= 2 and (clue_overlap or keyword_overlap or object_overlap or actor_overlap):
            hits.append({'chunk_id': item.get('chunk_id'), 'turn_start': item.get('turn_start'), 'turn_end': item.get('turn_end'), 'score': score, 'reason': '+'.join(reason), 'keyword_hits': keyword_hits[:8]})
        elif score >= 2 and 'topic_overlap' in reason:
            hits.append({'chunk_id': item.get('chunk_id'), 'turn_start': item.get('turn_start'), 'turn_end': item.get('turn_end'), 'score': score, 'reason': '+'.join(reason)})
    hits.sort(key=lambda x: -x['score'])
    return hits[:3]


def build_selector_decision(*, state_json: dict, recent_history: list[dict], keeper_records: dict, active_threads: list[dict], important_npcs: list[dict], onstage: list[str], relevant: list[str], lorebook_entries: list[dict], system_npc_candidates: list[dict], lorebook_npc_candidates: list[dict], event_summaries: list[dict], summary_text: str, summary_chunks: list[dict] | None = None, user_text: str = '') -> dict:
    inject_lorebook = should_inject_lorebook_text(state_json, recent_history, keeper_records, lorebook_entries, active_threads, user_text=user_text)
    all_candidates = list(system_npc_candidates) + list(lorebook_npc_candidates)
    inject_candidates = should_inject_npc_candidates(onstage, relevant, active_threads, recent_history, important_npcs, all_candidates)
    targets = profile_targets(onstage, relevant, active_threads, recent_history, important_npcs, limit=3)
    chunk_hits = summary_chunk_hits(
        summary_chunks or [],
        recent_history=recent_history,
        user_text=user_text,
        tracked_objects=state_json.get('tracked_objects', []),
        knowledge_records=state_json.get('knowledge_records', []),
    )
    event_hits = event_summary_hits(event_summaries, state_json=state_json, recent_history=recent_history, user_text=user_text)
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
    return {
        'selector_version': 2,
        'inject_lorebook_text': inject_lorebook,
        'inject_npc_candidates': inject_candidates,
        'npc_profile_targets': targets,
        'event_hits': event_hits,
        'summary_chunk_hits': chunk_hits,
        'inject_summary': inject_summary,
        'npc_roster': npc_roster,
    }
