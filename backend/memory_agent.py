#!/usr/bin/env python3
from __future__ import annotations

import re


def _tokenize(text: str) -> set[str]:
    raw = str(text or '').lower()
    tokens = set(re.findall(r'[\u4e00-\u9fff]{2,8}|[a-z0-9_]{3,24}', raw))
    return {token for token in tokens if token and token not in {'当前', '继续', '发生', '一个', '什么', '他们'}}


def _history_pairs(items: list[dict]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    current_user = None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, item))
            current_user = None
    return pairs


def _shorten(text: str, limit: int = 180) -> str:
    value = ' '.join(str(text or '').split()).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + '...'


def _query_terms(user_text: str, scene_facts: dict, summary_text: str) -> set[str]:
    parts: list[str] = [user_text, summary_text]
    if isinstance(scene_facts, dict):
        for key in ('location', 'main_event'):
            parts.append(str(scene_facts.get(key, '') or ''))
        parts.extend(scene_facts.get('onstage_npcs', []) or [])
        parts.extend(scene_facts.get('relevant_npcs', []) or [])
        for item in scene_facts.get('active_threads', []) or []:
            if not isinstance(item, dict):
                continue
            parts.append(str(item.get('label', '') or ''))
            parts.append(str(item.get('goal', '') or ''))
        for item in scene_facts.get('tracked_objects', []) or []:
            if not isinstance(item, dict):
                continue
            parts.append(str(item.get('label', '') or ''))
    return _tokenize('\n'.join(parts))


def _score_pair(user_item: dict, assistant_item: dict, query_terms: set[str],
                *, pair_index: int = 0, total_pairs: int = 1,
                important_npcs: list[str] | None = None) -> int:
    combined = '\n'.join([
        str(user_item.get('content', '') or ''),
        str(assistant_item.get('content', '') or ''),
    ])
    tokens = _tokenize(combined)
    if not tokens:
        return 0
    overlap = len(tokens & query_terms)
    if overlap == 0:
        return 0
    score = overlap
    # 长内容加分
    if len(combined) > 120:
        score += 1
    # 承诺/回忆词加分
    if any(token in combined for token in ('答应', '约', '记得', '之前', '还说', '上次', '又', '继续')):
        score += 2
    # NPC 关系权重：提到重要 NPC 额外加分
    if important_npcs:
        npc_hits = sum(1 for npc in important_npcs if npc in combined)
        score += min(npc_hits * 2, 4)
    # 时间衰减：越早的对话分数越低
    if total_pairs > 1:
        recency = pair_index / total_pairs  # 0.0=最早, 1.0=最近
        decay = 0.4 + 0.6 * recency  # 最早的保留 40% 分数
        score = max(1, int(score * decay))
    # 重复提及惩罚：与 query 完全重叠说明是当前轮信息而非独特记忆
    if query_terms and len(tokens) > 0:
        overlap_ratio = len(tokens & query_terms) / len(tokens)
        if overlap_ratio > 0.8:
            score = max(1, score - 2)
    return score


def build_memory_bundle(
    *,
    user_text: str,
    scene_facts: dict,
    summary_text: str,
    full_history: list[dict],
    recent_history: list[dict],
    important_npcs: list[str] | None = None,
    max_items: int = 4,
) -> dict:
    query_terms = _query_terms(user_text, scene_facts or {}, summary_text or '')
    recent_ts = {
        int(item.get('ts', 0) or 0)
        for item in (recent_history or [])
        if isinstance(item, dict)
    }

    all_pairs = _history_pairs(full_history or [])
    total_pairs = len(all_pairs)
    memories: list[tuple[int, dict]] = []
    for pair_index, (user_item, assistant_item) in enumerate(all_pairs):
        user_ts = int(user_item.get('ts', 0) or 0)
        assistant_ts = int(assistant_item.get('ts', 0) or 0)
        if user_ts in recent_ts or assistant_ts in recent_ts:
            continue
        score = _score_pair(user_item, assistant_item, query_terms,
                            pair_index=pair_index, total_pairs=total_pairs,
                            important_npcs=important_npcs)
        if score <= 0:
            continue
        memories.append((score, {
            'kind': 'history',
            'summary': _shorten(
                f"用户：{user_item.get('content', '')} / 世界：{assistant_item.get('content', '')}",
                limit=220,
            ),
            'source': {
                'user_ts': user_ts,
                'assistant_ts': assistant_ts,
            },
            'relevance': min(0.99, 0.45 + score * 0.08),
        }))

    memories.sort(key=lambda item: item[0], reverse=True)
    items = [payload for _score, payload in memories[:max_items]]
    return {
        'query_terms': sorted(query_terms)[:16],
        'memories': items,
    }
