#!/usr/bin/env python3
from __future__ import annotations

try:
    from .keeper_archive import load_keeper_record_archive
except ImportError:
    from keeper_archive import load_keeper_record_archive


def _current_query(scene_facts: dict) -> dict:
    scene = scene_facts if isinstance(scene_facts, dict) else {}
    return {
        'location': str(scene.get('location', '') or '').strip(),
        'entities': {
            str(name or '').strip()
            for name in (scene.get('onstage_npcs', []) or []) + (scene.get('relevant_npcs', []) or [])
            if str(name or '').strip()
        },
        'objects': {
            str(item.get('label', '') or '').strip()
            for item in (scene.get('tracked_objects', []) or [])
            if isinstance(item, dict) and str(item.get('label', '') or '').strip()
        },
    }


def _score_record(record: dict, query: dict, *, max_pair_index: int = 0) -> int:
    score = 0
    if str(record.get('location_anchor', '') or '').strip() == query.get('location'):
        score += 2
    score += 3 * len({item.get('name') for item in (record.get('stable_entities', []) or []) if isinstance(item, dict)} & set(query.get('entities', set())))
    score += 2 * len({item.get('label') for item in (record.get('tracked_objects', []) or []) if isinstance(item, dict)} & set(query.get('objects', set())))
    # 时间衰减：距离当前越远的记录分数越低
    if max_pair_index > 0:
        end_pair = int((record.get('window', {}) or {}).get('end_pair_index', 0) or 0)
        recency = end_pair / max_pair_index if max_pair_index else 0.5
        decay = 0.5 + 0.5 * recency  # 最早的记录保留 50% 分数
        score = max(1, int(score * decay)) if score > 0 else 0
    return score


def retrieve_keeper_records(
    session_id: str,
    scene_facts: dict,
    *,
    recent_window_pairs: int = 10,
    limit: int = 4,
) -> dict:
    archive = load_keeper_record_archive(session_id)
    records = archive.get('records', []) if isinstance(archive.get('records', []), list) else []
    max_pair_index = max((int((item.get('window', {}) or {}).get('end_pair_index', 0) or 0) for item in records), default=0)
    cutoff = max(0, max_pair_index - recent_window_pairs)
    query = _current_query(scene_facts)
    scored = []
    for record in records:
        if not isinstance(record, dict):
            continue
        end_pair_index = int((record.get('window', {}) or {}).get('end_pair_index', 0) or 0)
        if end_pair_index > cutoff:
            continue
        score = _score_record(record, query, max_pair_index=max_pair_index)
        if score <= 0:
            continue
        scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    return {'records': [record for _score, record in scored[:limit]]}
