#!/usr/bin/env python3
from __future__ import annotations

import re

try:
    from .keeper_archive import build_keeper_record_archive, load_keeper_record_archive, save_keeper_record_archive
except ImportError:
    from keeper_archive import build_keeper_record_archive, load_keeper_record_archive, save_keeper_record_archive


LOCATION_HINT_SUFFIXES = (
    '院', '屋', '堂', '阁', '楼', '廊', '巷', '街', '坡', '关', '门', '墙',
    '栈', '店', '棚', '厩', '道', '路', '桥', '亭', '台', '寺', '观', '寨',
)
GENERIC_TOPIC_TOKENS = {
    '当前', '局势', '继续', '仍在', '附近', '周围', '有关', '存在', '相关', '人物',
    '地方', '事情', '问题', '感觉', '一个', '一些', '已经', '准备', '判断', '变化',
    '突然', '后院', '堂屋',
}


def _normalize_text(text: str) -> str:
    return ' '.join(str(text or '').split()).strip()


def _pair_count_from_archive(archive: dict, records: list[dict]) -> int:
    if isinstance(archive, dict):
        raw = archive.get('source_pair_count')
        try:
            value = int(raw or 0)
        except (TypeError, ValueError):
            value = 0
        if value > 0:
            return value
    return max((int((item.get('window', {}) or {}).get('end_pair_index', 0) or 0) for item in records), default=0)


def _archive_needs_refresh(archive: dict, records: list[dict], *, current_pair_count: int, recent_window_pairs: int) -> bool:
    if current_pair_count <= 0:
        return False
    window_size = 10
    if isinstance(archive, dict):
        try:
            window_size = int(archive.get('window_size', 10) or 10)
        except (TypeError, ValueError):
            window_size = 10
    min_pairs_for_archive = max(2, window_size + max(1, recent_window_pairs // 4))
    archived_pair_count = _pair_count_from_archive(archive, records)
    if current_pair_count < min_pairs_for_archive:
        return False
    if not records and archived_pair_count < current_pair_count:
        return True
    refresh_stride = max(4, window_size // 2)
    return archived_pair_count + refresh_stride <= current_pair_count


def _meaningful_location_tokens(text: str) -> set[str]:
    value = _normalize_text(text)
    if not value:
        return set()
    tokens: set[str] = set()
    for part in re.split(r'[\s/|·,，。、“”‘’！？:：;；()\[\]{}<>]+', value):
        token = part.strip()
        if not token:
            continue
        if len(token) >= 2 and token.endswith(LOCATION_HINT_SUFFIXES):
            tokens.add(token[-4:] if len(token) > 4 else token)
    for token in re.findall(r'[\u4e00-\u9fff]{2,4}', value):
        if token.endswith(LOCATION_HINT_SUFFIXES):
            tokens.add(token)
    return tokens


def _topic_tokens(text: str) -> set[str]:
    value = _normalize_text(text)
    if not value:
        return set()
    tokens = {
        token for token in re.findall(r'[\u4e00-\u9fff]{2,6}|[A-Za-z][A-Za-z0-9_-]{1,15}', value)
        if token not in GENERIC_TOPIC_TOKENS
    }
    return tokens


def _record_topic_tokens(record: dict) -> set[str]:
    pieces = []
    for field in ('location_anchor',):
        pieces.append(str(record.get(field, '') or ''))
    for item in (record.get('ongoing_events', []) or []):
        pieces.append(str(item or ''))
    for item in (record.get('open_loops', []) or []):
        pieces.append(str(item or ''))
    for item in (record.get('history_digest', []) or []):
        if not isinstance(item, dict):
            continue
        pieces.append(str(item.get('user', '') or ''))
        pieces.append(str(item.get('assistant', '') or ''))
    return _topic_tokens(' '.join(pieces))


def _current_query(scene_facts: dict) -> dict:
    scene = scene_facts if isinstance(scene_facts, dict) else {}
    topic_parts = [
        str(scene.get('location', '') or ''),
        str(scene.get('main_event', '') or ''),
        str(scene.get('scene_core', '') or ''),
        ' '.join(str(item or '') for item in (scene.get('immediate_risks', []) or [])),
        ' '.join(str(item or '') for item in (scene.get('carryover_clues', []) or [])),
    ]
    for item in (scene.get('active_threads', []) or []):
        if not isinstance(item, dict):
            continue
        topic_parts.extend(str(item.get(field, '') or '') for field in ('label', 'goal', 'obstacle', 'latest_change'))
    return {
        'location': _normalize_text(scene.get('location', '')),
        'location_tokens': _meaningful_location_tokens(scene.get('location', '')),
        'entities': {
            _normalize_text(name)
            for name in (scene.get('onstage_npcs', []) or []) + (scene.get('relevant_npcs', []) or [])
            if _normalize_text(name)
        },
        'objects': {
            _normalize_text(item.get('label', ''))
            for item in (scene.get('tracked_objects', []) or [])
            if isinstance(item, dict) and _normalize_text(item.get('label', ''))
        },
        'topics': _topic_tokens(' '.join(topic_parts)),
    }


def _score_record(record: dict, query: dict, *, current_pair_count: int = 0) -> int:
    location_score = 0
    record_location = _normalize_text(record.get('location_anchor', ''))
    if record_location and record_location == query.get('location'):
        location_score = 3
    elif record_location:
        record_location_tokens = _meaningful_location_tokens(record_location)
        shared_location_tokens = record_location_tokens & set(query.get('location_tokens', set()))
        if len(shared_location_tokens) >= 2:
            location_score = 2
        elif shared_location_tokens:
            location_score = 1

    entity_score = 3 * len({
        _normalize_text(item.get('name', ''))
        for item in (record.get('stable_entities', []) or [])
        if isinstance(item, dict) and _normalize_text(item.get('name', ''))
    } & set(query.get('entities', set())))

    object_score = 2 * len({
        _normalize_text(item.get('label', ''))
        for item in (record.get('tracked_objects', []) or [])
        if isinstance(item, dict) and _normalize_text(item.get('label', ''))
    } & set(query.get('objects', set())))

    base_score = location_score + entity_score + object_score
    if base_score <= 0:
        return 0

    topic_bonus = 0
    shared_topics = _record_topic_tokens(record) & set(query.get('topics', set()))
    if len(shared_topics) >= 3:
        topic_bonus = 2
    elif len(shared_topics) >= 1:
        topic_bonus = 1

    score = base_score + topic_bonus
    if current_pair_count > 0:
        end_pair = int((record.get('window', {}) or {}).get('end_pair_index', 0) or 0)
        distance = max(0, current_pair_count - end_pair)
        if distance >= 24:
            score -= 2
        elif distance >= 12:
            score -= 1
    return max(score, 0)


def retrieve_keeper_records(
    session_id: str,
    scene_facts: dict,
    *,
    current_pair_count: int = 0,
    recent_window_pairs: int = 10,
    limit: int = 4,
) -> dict:
    archive = load_keeper_record_archive(session_id)
    records = archive.get('records', []) if isinstance(archive.get('records', []), list) else []
    if _archive_needs_refresh(archive, records, current_pair_count=current_pair_count, recent_window_pairs=recent_window_pairs):
        archive = build_keeper_record_archive(session_id)
        save_keeper_record_archive(session_id, archive)
        records = archive.get('records', []) if isinstance(archive.get('records', []), list) else []

    pair_count = max(0, int(current_pair_count or 0))
    cutoff = max(0, pair_count - max(1, recent_window_pairs))
    query = _current_query(scene_facts)
    scored = []
    for record in records:
        if not isinstance(record, dict):
            continue
        end_pair_index = int((record.get('window', {}) or {}).get('end_pair_index', 0) or 0)
        if end_pair_index <= 0:
            continue
        if end_pair_index > cutoff:
            continue
        score = _score_record(record, query, current_pair_count=pair_count)
        if score <= 0:
            continue
        scored.append((score, record))
    scored.sort(key=lambda item: item[0], reverse=True)
    return {'records': [record for _score, record in scored[:limit]]}
