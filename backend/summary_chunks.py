#!/usr/bin/env python3
from __future__ import annotations

import json
import re

try:
    from .llm_manager import call_role_llm
    from .local_model_client import parse_json_response
    from .runtime_store import is_complete_assistant_item, load_history, load_summary_chunks, save_summary_chunks
except ImportError:
    from llm_manager import call_role_llm
    from local_model_client import parse_json_response
    from runtime_store import is_complete_assistant_item, load_history, load_summary_chunks, save_summary_chunks


SUMMARY_CHUNK_SIZE = 12


SUMMARY_CHUNK_SYSTEM = """你是 RP 历史分段整理器。

只输出 JSON，不要解释。

你要把固定 12 轮对话整理成 dense summary chunk。要求尽量保留事件细节，不要写成高度抽象的一句话。

输出格式：
{
  "dense_summary": ["按时间顺序，每轮或每个连续动作一条，保留地点、人物、物品、台词要点、发现、误会、未解问题"],
  "key_events": ["这一段最关键的事件事实"],
  "unresolved": ["这一段结束后仍未解决的问题"],
  "locations": ["出现过的地点"],
  "actors_mentioned": ["出现过的人物称呼"],
  "objects_mentioned": ["出现过的物品"],
  "keywords": ["用于后续检索的短关键词"]
}

规则：
1. 只总结输入窗口，不要续写。
2. dense_summary 尽量细，8-18 条，每条 50-140 中文字。
3. key_events 3-10 条。
4. unresolved 0-10 条。
5. 不维护 NPC 性格设定；人物设定由 actor registry 管。
6. 不维护物品主账本或谁知道什么；这些由 keeper 管。
7. 保留台词里的关键信息，但不要整段抄 prose。
"""


def _turn_pairs(history: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history or []:
        role = item.get('role')
        content = str(item.get('content', '') or '')
        if role == 'user':
            current_user = content
        elif role == 'assistant' and current_user is not None and is_complete_assistant_item(item):
            pairs.append((current_user, content))
            current_user = None
    return pairs


def _compact(value: str, limit: int = 260) -> str:
    text = re.sub(r'\s+', ' ', str(value or '')).strip()
    return text[:limit]


def _dedupe_limited(values: list[str], limit: int) -> list[str]:
    out: list[str] = []
    for value in values:
        text = _compact(value, 40)
        if text and text not in out:
            out.append(text)
        if len(out) >= limit:
            break
    return out


def _extract_chunk_metadata(text: str) -> dict[str, list[str]]:
    value = str(text or '')
    locations: list[str] = []
    for header in re.findall(r'【([^】]{2,40})】', value):
        parts = [part.strip() for part in re.split(r'[，,、/｜|]', header) if part.strip()]
        if len(parts) >= 2:
            locations.append(parts[-1])
    return {
        'actors_mentioned': [],
        'locations': locations,
        'objects_mentioned': [],
    }


def _fallback_chunk(*, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]], provider: str = 'heuristic') -> dict:
    dense = []
    for idx, (user_text, assistant_text) in enumerate(pairs, start=turn_start):
        dense.append(f'第{idx}轮：用户动作：{_compact(user_text, 90)}；世界反馈：{_compact(assistant_text, 180)}')
    text = '\n'.join(' '.join(pair) for pair in pairs)
    keywords = []
    for token in re.findall(r'[\u4e00-\u9fff]{2,8}', text):
        if token not in keywords:
            keywords.append(token)
        if len(keywords) >= 36:
            break
    extracted = _extract_chunk_metadata(text)
    return {
        'chunk_id': chunk_id,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'dense_summary': dense[:18],
        'key_events': dense[:6],
        'unresolved': [],
        'locations': extracted['locations'],
        'actors_mentioned': extracted['actors_mentioned'],
        'objects_mentioned': extracted['objects_mentioned'],
        'keywords': keywords,
        'provider': provider,
    }


def _normalize_chunk(payload: dict, *, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]], provider: str) -> dict:
    fallback = _fallback_chunk(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider=provider)
    if not isinstance(payload, dict):
        return fallback
    out = dict(fallback)
    for field, limit in (
        ('dense_summary', 18),
        ('key_events', 10),
        ('unresolved', 10),
        ('locations', 12),
        ('actors_mentioned', 18),
        ('objects_mentioned', 18),
        ('keywords', 30),
    ):
        values = payload.get(field, [])
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, list):
            continue
        cleaned = []
        for item in values:
            text = _compact(str(item or ''), 180 if field in {'dense_summary', 'key_events', 'unresolved'} else 40)
            if text and text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        if cleaned:
            out[field] = cleaned
    extracted = _extract_chunk_metadata('\n'.join(' '.join(pair) for pair in pairs))
    for field in ('locations', 'actors_mentioned', 'objects_mentioned'):
        if not out.get(field):
            out[field] = extracted[field]
    out['provider'] = provider
    return out


def _build_chunk_with_llm(*, chunk_id: str, turn_start: int, turn_end: int, pairs: list[tuple[str, str]]) -> dict:
    prompt = json.dumps({
        'chunk_id': chunk_id,
        'turn_start': turn_start,
        'turn_end': turn_end,
        'turn_pairs': [
            {'turn': turn_start + idx, 'user': user, 'assistant': assistant}
            for idx, (user, assistant) in enumerate(pairs)
        ],
    }, ensure_ascii=False, indent=2)
    try:
        reply, _usage = call_role_llm('state_keeper_candidate', SUMMARY_CHUNK_SYSTEM, prompt)
        payload = parse_json_response(reply)
        return _normalize_chunk(payload, chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider='llm')
    except Exception:
        return _fallback_chunk(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=pairs, provider='heuristic')


def update_summary_chunks(session_id: str, *, chunk_size: int = SUMMARY_CHUNK_SIZE) -> dict:
    history = load_history(session_id)
    pairs = _turn_pairs(history)
    store = load_summary_chunks(session_id)
    chunks = [item for item in store.get('chunks', []) if isinstance(item, dict)]
    existing_ids = {str(item.get('chunk_id', '') or '') for item in chunks}
    complete_chunks = len(pairs) // chunk_size
    changed = False
    for idx in range(complete_chunks):
        turn_start = idx * chunk_size + 1
        turn_end = (idx + 1) * chunk_size
        chunk_id = f'chunk_{idx + 1:04d}'
        if chunk_id in existing_ids:
            continue
        chunk_pairs = pairs[turn_start - 1:turn_end]
        chunk = _build_chunk_with_llm(chunk_id=chunk_id, turn_start=turn_start, turn_end=turn_end, pairs=chunk_pairs)
        chunks.append(chunk)
        existing_ids.add(chunk_id)
        changed = True
    if changed:
        save_summary_chunks(session_id, {'version': 1, 'chunks': chunks})
    return {'version': 1, 'chunks': chunks, 'created': changed}
