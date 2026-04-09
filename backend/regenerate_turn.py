#!/usr/bin/env python3
from __future__ import annotations

try:
    from .handler_message import handle_message
    from .runtime_store import load_history, load_meta, save_history, save_meta
except ImportError:
    from handler_message import handle_message
    from runtime_store import load_history, load_meta, save_history, save_meta


def regenerate_last_partial(session_id: str) -> dict:
    history = load_history(session_id)
    meta = load_meta(session_id)
    if len(history) < 2:
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'no partial turn to regenerate'}}

    assistant = history[-1]
    user = history[-2]
    if user.get('role') != 'user' or assistant.get('role') != 'assistant':
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'latest turn is not a user/assistant pair'}}
    if assistant.get('completion_status') != 'partial':
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'latest assistant reply is not partial'}}

    trimmed_history = history[:-2]
    save_history(session_id, trimmed_history)

    target_turn_id = f'turn-{int(meta.get("last_turn_id", 0)):04d}' if int(meta.get('last_turn_id', 0) or 0) > 0 else None
    if meta.get('last_turn_id', 0) > 0:
        meta['last_turn_id'] = int(meta.get('last_turn_id', 0)) - 1
    processed = dict(meta.get('processed_client_turn_ids', {}))
    if processed and target_turn_id:
        processed = {
            key: value for key, value in processed.items()
            if not isinstance(value, dict) or value.get('turn_id') != target_turn_id
        }
    meta['processed_client_turn_ids'] = processed
    save_meta(session_id, meta)

    return handle_message({
        'session_id': session_id,
        'text': str(user.get('content', '') or ''),
        'client_turn_id': f'regenerate-{assistant.get("ts", "latest")}',
        'meta': {
            'source': 'regenerate',
            'debug': True,
        },
    })
