#!/usr/bin/env python3
from __future__ import annotations

import json
try:
    from .mid_context_agent import build_mid_window_digest
    from .npc_bootstrap_agent import ensure_npc_registry
    from .object_bootstrap_agent import ensure_object_registry
    from .clue_bootstrap_agent import ensure_clue_registry
    from .runtime_store import load_history, load_state, session_paths
except ImportError:
    from mid_context_agent import build_mid_window_digest
    from npc_bootstrap_agent import ensure_npc_registry
    from object_bootstrap_agent import ensure_object_registry
    from clue_bootstrap_agent import ensure_clue_registry
    from runtime_store import load_history, load_state, session_paths


def build_keeper_record_archive(session_id: str, *, window_size: int = 10, overlap_recent_pairs: int = 3, skip_bootstrap: bool = False, use_llm: bool = True) -> dict:
    import logging
    _logger = logging.getLogger(__name__)
    history = load_history(session_id)
    state = load_state(session_id)
    
    # 可选：跳过可能阻塞的 bootstrap agents
    if not skip_bootstrap:
        try:
            registry = ensure_npc_registry(session_id, history)
        except Exception as e:
            _logger.warning('NPC bootstrap 异常，使用空 registry: %s', e)
            registry = {'entities': []}
        try:
            ensure_object_registry(session_id, history)
        except Exception as e:
            _logger.warning('物品 bootstrap 异常: %s', e)
        try:
            ensure_clue_registry(session_id, history)
        except Exception as e:
            _logger.warning('情报 bootstrap 异常: %s', e)
    else:
        _logger.info('跳过 bootstrap agents（skip_bootstrap=True）')
        registry = {'entities': []}

    pairs = []
    current_user = None
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None and item.get('completion_status', 'complete') == 'complete':
            pairs.append((current_user, item))
            current_user = None
        elif role == 'assistant' and current_user is not None:
            current_user = None

    records = []
    for start in range(0, max(0, len(pairs) - overlap_recent_pairs), window_size):
        window_pairs = pairs[start:start + window_size]
        if len(window_pairs) < 2:
            continue
        flat_history = []
        for user_item, assistant_item in window_pairs:
            flat_history.append(user_item)
            flat_history.append(assistant_item)
        digest = build_mid_window_digest(
            history=flat_history,
            hard_anchors={
                'time': state.get('time', ''),
                'location': state.get('location', ''),
                'onstage_npcs': state.get('onstage_npcs', []),
                'relevant_npcs': state.get('relevant_npcs', []),
                'tracked_objects': state.get('tracked_objects', []),
                'npc_registry': registry,
            },
            max_pairs=window_size,
            use_llm=use_llm,
            exclude_recent_pairs=0,
        )
        if not digest:
            continue
        digest['window']['from_turn'] = f"turn-{start + 1:04d}"
        digest['window']['to_turn'] = f"turn-{start + len(window_pairs):04d}"
        digest['window']['end_pair_index'] = start + len(window_pairs)
        # 放宽过滤条件：只需要有实体或有事件/线索即可
        has_entities = len(digest.get('stable_entities', []) or []) >= 1
        has_content = (digest.get('ongoing_events') or digest.get('open_loops') or 
                      digest.get('tracked_objects') or digest.get('history_digest'))
        if not (has_entities or has_content):
            continue
        records.append(digest)

    archive = {
        'version': 1,
        'window_size': window_size,
        'recent_window_pairs': overlap_recent_pairs,
        'source_pair_count': len(pairs),
        'history_message_count': len(history),
        'records': records,
        'npc_registry': registry,
    }
    validated, _validation = validate_keeper_archive(archive)
    return validated


def save_keeper_record_archive(session_id: str, archive: dict) -> None:
    path = session_paths(session_id)['keeper_archive']
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .runtime_store import _atomic_write_json
    except ImportError:
        from runtime_store import _atomic_write_json
    _atomic_write_json(path, archive)


BAD_DIGEST_FRAGMENTS = {
    '了一下', '的声音', '的目光', '的钢笔', '的脚步', '下一个',
}
SHORT_BAD_DIGEST_FRAGMENTS = {'不能', '没有', '可能', '似乎', '好像'}


def _normalize_text(text: str) -> str:
    return ' '.join(str(text or '').split()).strip()


def _valid_record_sentence(text: str) -> bool:
    value = _normalize_text(text)
    if not value or len(value) < 6:
        return False
    if any(fragment in value for fragment in BAD_DIGEST_FRAGMENTS):
        return False
    if value in SHORT_BAD_DIGEST_FRAGMENTS or (len(value) <= 8 and any(fragment in value for fragment in SHORT_BAD_DIGEST_FRAGMENTS)):
        return False
    if '围绕' in value and '局势仍在持续演化' in value:
        if not any(token in value for token in ('搜查', '盘问', '追踪', '调查', '审查', '等待', '封存', '约定', '身份', '来历', '真相', '测评', '终端')):
            return False
    if value.isascii():
        return False
    return True


def _valid_window(window: dict, source_pair_count: int) -> bool:
    if not isinstance(window, dict):
        return False
    try:
        end_pair_index = int(window.get('end_pair_index', 0) or 0)
        pair_count = int(window.get('pair_count', 1) or 1)
    except (TypeError, ValueError):
        return False
    if pair_count <= 0 or end_pair_index <= 0:
        return False
    if source_pair_count > 0 and end_pair_index > source_pair_count:
        return False
    return True


def validate_keeper_archive(archive: dict) -> tuple[dict, dict]:
    """Drop malformed or fragment-like keeper archive records.

    Keeper archives are derived caches; validation is deterministic and safe to
    run after load/build before recall. Manual-cleanup records are protected.
    """
    if not isinstance(archive, dict):
        return {'version': 1, 'records': []}, {'changed': True, 'changes': [{'artifact': 'keeper_archive', 'action': 'reset_invalid'}], 'warnings': []}
    records = archive.get('records', []) if isinstance(archive.get('records', []), list) else []
    try:
        source_pair_count = int(archive.get('source_pair_count', 0) or 0)
    except (TypeError, ValueError):
        source_pair_count = 0
    kept = []
    changes = []
    warnings = []
    for record in records:
        if not isinstance(record, dict):
            changes.append({'artifact': 'keeper_archive', 'action': 'drop_invalid_record', 'reason': 'not_object'})
            continue
        if record.get('provider') == 'manual-cleanup':
            kept.append(record)
            continue
        if not _valid_window(record.get('window', {}), source_pair_count):
            changes.append({'artifact': 'keeper_archive', 'action': 'drop_invalid_record', 'reason': 'bad_window'})
            continue
        stable_entities = record.get('stable_entities', []) if isinstance(record.get('stable_entities', []), list) else []
        ongoing = [item for item in record.get('ongoing_events', []) if _valid_record_sentence(item)] if isinstance(record.get('ongoing_events', []), list) else []
        loops = [item for item in record.get('open_loops', []) if _valid_record_sentence(item)] if isinstance(record.get('open_loops', []), list) else []
        history_digest = record.get('history_digest', []) if isinstance(record.get('history_digest', []), list) else []
        tracked_objects = record.get('tracked_objects', []) if isinstance(record.get('tracked_objects', []), list) else []
        next_record = dict(record)
        if ongoing != record.get('ongoing_events', []):
            next_record['ongoing_events'] = ongoing
            changes.append({'artifact': 'keeper_archive', 'action': 'sanitize_record', 'field': 'ongoing_events'})
        if loops != record.get('open_loops', []):
            next_record['open_loops'] = loops
            changes.append({'artifact': 'keeper_archive', 'action': 'sanitize_record', 'field': 'open_loops'})
        has_named_entity = any(isinstance(item, dict) and _normalize_text(item.get('name', '')) for item in stable_entities)
        has_content = bool(ongoing or loops or tracked_objects or history_digest)
        if not has_named_entity and not has_content:
            changes.append({'artifact': 'keeper_archive', 'action': 'drop_invalid_record', 'reason': 'empty_content'})
            continue
        kept.append(next_record)
    changed = len(kept) != len(records) or bool(changes)
    next_archive = dict(archive)
    next_archive['records'] = kept
    if changed:
        warnings.append(f'keeper archive validation changed {len(changes)} record fields/items')
    return next_archive, {'changed': changed, 'changes': changes, 'warnings': warnings}


def load_keeper_record_archive(
    session_id: str,
    *,
    skip_bootstrap: bool = False,
    use_llm: bool = True,
    allow_archive_write: bool = True,
) -> dict:
    """Load the derived keeper archive.

    The archive is a cache, so default reads may rebuild/save missing or corrupt
    cache files. Pass allow_archive_write=False for inspection paths that must
    not touch disk.
    """
    path = session_paths(session_id)['keeper_archive']
    if not path.exists():
        archive = build_keeper_record_archive(session_id, skip_bootstrap=skip_bootstrap, use_llm=use_llm)
        if allow_archive_write:
            save_keeper_record_archive(session_id, archive)
        return archive
    try:
        archive = json.loads(path.read_text(encoding='utf-8'))
        archive, validation = validate_keeper_archive(archive)
        if validation.get('changed') and allow_archive_write:
            save_keeper_record_archive(session_id, archive)
        return archive
    except Exception:
        archive = build_keeper_record_archive(session_id, skip_bootstrap=skip_bootstrap, use_llm=use_llm)
        if allow_archive_write:
            save_keeper_record_archive(session_id, archive)
        return archive
