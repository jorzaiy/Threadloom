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


def build_keeper_record_archive(session_id: str, *, window_size: int = 10, overlap_recent_pairs: int = 3) -> dict:
    history = load_history(session_id)
    state = load_state(session_id)
    registry = ensure_npc_registry(session_id, history)
    ensure_object_registry(session_id, history)
    ensure_clue_registry(session_id, history)

    pairs = []
    current_user = None
    for item in history:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, item))
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
            },
            max_pairs=window_size,
        )
        if not digest:
            continue
        digest['window']['from_turn'] = f"turn-{start + 1:04d}"
        digest['window']['to_turn'] = f"turn-{start + len(window_pairs):04d}"
        digest['window']['end_pair_index'] = start + len(window_pairs)
        if len(digest.get('stable_entities', []) or []) < 2:
            continue
        if not (digest.get('ongoing_events') or digest.get('open_loops')):
            continue
        records.append(digest)

    return {
        'version': 1,
        'window_size': window_size,
        'recent_window_pairs': overlap_recent_pairs,
        'source_pair_count': len(pairs),
        'history_message_count': len(history),
        'records': records,
        'npc_registry': registry,
    }


def save_keeper_record_archive(session_id: str, archive: dict) -> None:
    path = session_paths(session_id)['keeper_archive']
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from .runtime_store import _atomic_write_json
    except ImportError:
        from runtime_store import _atomic_write_json
    _atomic_write_json(path, archive)


def load_keeper_record_archive(session_id: str) -> dict:
    path = session_paths(session_id)['keeper_archive']
    if not path.exists():
        archive = build_keeper_record_archive(session_id)
        save_keeper_record_archive(session_id, archive)
        return archive
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        archive = build_keeper_record_archive(session_id)
        save_keeper_record_archive(session_id, archive)
        return archive
