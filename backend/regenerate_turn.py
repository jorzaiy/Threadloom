#!/usr/bin/env python3
from __future__ import annotations

import json
import logging
from pathlib import Path

try:
    from .atomic_io import atomic_write_text
    from .fact_log import FactLog
    from .handler_message import handle_message
    from .runtime_store import load_event_summaries, load_history, load_meta, load_session_persona_layers, load_state, load_summary, load_summary_chunks, load_turn_trace, save_event_summaries, save_history, save_meta, save_session_persona_layers, save_state, save_summary, save_summary_chunks, session_paths
    from .summary_updater import update_summary
except ImportError:
    from atomic_io import atomic_write_text
    from fact_log import FactLog
    from handler_message import handle_message
    from runtime_store import load_event_summaries, load_history, load_meta, load_session_persona_layers, load_state, load_summary, load_summary_chunks, load_turn_trace, save_event_summaries, save_history, save_meta, save_session_persona_layers, save_state, save_summary, save_summary_chunks, session_paths
    from summary_updater import update_summary

logger = logging.getLogger(__name__)


def _latest_turn_id(meta: dict) -> str | None:
    last_turn_id = int(meta.get('last_turn_id', 0) or 0)
    if last_turn_id <= 0:
        return None
    return f'turn-{last_turn_id:04d}'


def _drop_processed_turn(meta: dict, target_turn_id: str | None) -> None:
    processed = dict(meta.get('processed_client_turn_ids', {}))
    if processed and target_turn_id:
        processed = {
            key: value for key, value in processed.items()
            if not isinstance(value, dict) or value.get('turn_id') != target_turn_id
        }
    meta['processed_client_turn_ids'] = processed


def _drop_turn_audits(meta: dict, target_turn_id: str | None) -> None:
    if not target_turn_id:
        return
    audits = meta.get('turn_audits', [])
    if isinstance(audits, list):
        meta['turn_audits'] = [
            item for item in audits
            if not isinstance(item, dict) or item.get('turn_id') != target_turn_id
        ]
    last_audit = meta.get('last_turn_audit')
    if isinstance(last_audit, dict) and last_audit.get('turn_id') == target_turn_id:
        remaining = meta.get('turn_audits', [])
        if isinstance(remaining, list) and remaining:
            meta['last_turn_audit'] = remaining[-1]
        else:
            meta.pop('last_turn_audit', None)


def _turn_number(turn_id: str | None) -> int:
    try:
        return int(str(turn_id or '').rsplit('-', 1)[-1])
    except (TypeError, ValueError):
        return 0


def _int_value(value: object) -> int:
    try:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            return int(value or 0)
    except (TypeError, ValueError):
        return 0
    return 0


def _record_end_pair_index(record: dict) -> int:
    try:
        return int((record.get('window', {}) or {}).get('end_pair_index', 0) or 0)
    except (TypeError, ValueError):
        return 0


def _prune_summary_chunks(session_id: str, *, max_pair_index: int) -> None:
    payload = load_summary_chunks(session_id)
    chunks = payload.get('chunks', []) if isinstance(payload.get('chunks', []), list) else []
    kept = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        try:
            turn_end = int(chunk.get('turn_end', 0) or 0)
        except (TypeError, ValueError):
            turn_end = 0
        if turn_end <= max_pair_index:
            kept.append(chunk)
    next_payload: dict = dict(payload) if isinstance(payload, dict) else {'version': 1}
    next_payload['chunks'] = kept
    save_summary_chunks(session_id, next_payload)


def _prune_keeper_archive(session_id: str, *, max_pair_index: int, history_message_count: int) -> None:
    keeper_archive = session_paths(session_id)['keeper_archive']
    if not keeper_archive.exists():
        return
    try:
        archive = json.loads(keeper_archive.read_text(encoding='utf-8'))
    except Exception:
        return
    if not isinstance(archive, dict):
        return
    records = archive.get('records', []) if isinstance(archive.get('records', []), list) else []
    kept = [record for record in records if isinstance(record, dict) and _record_end_pair_index(record) <= max_pair_index]
    next_archive = dict(archive)
    next_archive['records'] = kept
    next_archive['source_pair_count'] = min(_int_value(next_archive.get('source_pair_count', 0)), max_pair_index)
    next_archive['history_message_count'] = history_message_count
    atomic_write_text(keeper_archive, json.dumps(next_archive, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _truncate_fact_log_before_turn(session_id: str, target_turn_id: str | None) -> None:
    """Drop facts at/after the rolled-back turn so re-commit does not double-count.

    truncate_after(N) keeps turn <= N. Regenerating turn-0005 means drop turn >= 5,
    i.e. truncate_after(4). Fully guarded — missing fact-log is a no-op.
    """
    turn = _turn_number(target_turn_id)
    if turn <= 0:
        return
    try:
        paths = session_paths(session_id)
        memory_dir = paths.get('memory_dir')
        if not memory_dir:
            return
        memory_dir = Path(memory_dir)
        log = FactLog.load(memory_dir)
        if not log.facts:
            return
        log.truncate_after(turn - 1)
        log.save(memory_dir)
    except Exception as err:
        logger.warning('FACTLOG_TRUNCATE_FAILED session=%s turn=%s err=%s', session_id, target_turn_id, err)


def _factlog_snapshot(session_id: str) -> dict:
    """Capture facts.jsonl + entities.json for regenerate failure restore."""
    try:
        paths = session_paths(session_id)
        memory_dir = paths.get('memory_dir')
        if not memory_dir:
            return {'facts_existed': False, 'entities_existed': False, 'facts_text': '', 'entities_text': ''}
        memory_dir = Path(memory_dir)
        facts_path = memory_dir / 'facts.jsonl'
        entities_path = memory_dir / 'entities.json'
        return {
            'facts_existed': facts_path.exists(),
            'entities_existed': entities_path.exists(),
            'facts_text': facts_path.read_text(encoding='utf-8') if facts_path.exists() else '',
            'entities_text': entities_path.read_text(encoding='utf-8') if entities_path.exists() else '',
        }
    except Exception as err:
        logger.warning('FACTLOG_SNAPSHOT_FAILED session=%s err=%s', session_id, err)
        return {'facts_existed': False, 'entities_existed': False, 'facts_text': '', 'entities_text': ''}


def _factlog_restore(session_id: str, snapshot: dict | None) -> None:
    if not isinstance(snapshot, dict):
        return
    try:
        paths = session_paths(session_id)
        memory_dir = paths.get('memory_dir')
        if not memory_dir:
            return
        memory_dir = Path(memory_dir)
        memory_dir.mkdir(parents=True, exist_ok=True)
        facts_path = memory_dir / 'facts.jsonl'
        entities_path = memory_dir / 'entities.json'
        if snapshot.get('facts_existed'):
            atomic_write_text(facts_path, str(snapshot.get('facts_text', '') or ''), encoding='utf-8')
        elif facts_path.exists():
            facts_path.unlink()
        if snapshot.get('entities_existed'):
            atomic_write_text(entities_path, str(snapshot.get('entities_text', '') or ''), encoding='utf-8')
        elif entities_path.exists():
            entities_path.unlink()
    except Exception as err:
        logger.warning('FACTLOG_RESTORE_FAILED session=%s err=%s', session_id, err)


def _rollback_derived_artifacts(session_id: str, target_turn_id: str, turn_trace: dict, *, reset_derived_caches: bool = True, history_message_count: int = 0) -> None:
    pre_turn = turn_trace.get('pre_turn', {}) if isinstance(turn_trace.get('pre_turn', {}), dict) else {}
    prev_state = pre_turn.get('state') if isinstance(pre_turn.get('state'), dict) else None
    if prev_state is None:
        raise ValueError('turn trace does not contain pre-turn state')

    save_state(session_id, prev_state)
    persona_layers = pre_turn.get('persona_layers')
    if isinstance(persona_layers, dict):
        save_session_persona_layers(session_id, persona_layers)

    event_payload = load_event_summaries(session_id)
    items = [
        item for item in event_payload.get('items', [])
        if not isinstance(item, dict) or str(item.get('turn_id', '') or '') != target_turn_id
    ]
    event_payload['items'] = items
    save_event_summaries(session_id, event_payload)

    # Keep fact-log aligned with state/history rollback (hard gate for WRITE_IMPORTANT).
    _truncate_fact_log_before_turn(session_id, target_turn_id)

    if reset_derived_caches:
        save_summary_chunks(session_id, {'version': 1, 'chunks': []})
        keeper_archive = session_paths(session_id)['keeper_archive']
        if keeper_archive.exists():
            keeper_archive.unlink()
    else:
        max_pair_index = max(0, _turn_number(target_turn_id) - 1)
        _prune_summary_chunks(session_id, max_pair_index=max_pair_index)
        _prune_keeper_archive(session_id, max_pair_index=max_pair_index, history_message_count=history_message_count)


def _snapshot_artifacts(session_id: str, history: list, meta: dict) -> dict:
    paths = session_paths(session_id)
    keeper_archive = paths['keeper_archive']
    snap = {
        'history': list(history),
        'meta': dict(meta),
        'state': load_state(session_id),
        'persona_layers': load_session_persona_layers(session_id),
        'event_summaries': load_event_summaries(session_id),
        'summary_chunks': load_summary_chunks(session_id),
        'summary': load_summary(session_id),
        'keeper_archive_exists': keeper_archive.exists(),
        'keeper_archive_text': keeper_archive.read_text(encoding='utf-8') if keeper_archive.exists() else '',
    }
    snap.update(_factlog_snapshot(session_id))
    return snap


def _restore_artifacts(session_id: str, snapshot: dict) -> None:
    save_history(session_id, snapshot.get('history', []))
    save_meta(session_id, snapshot.get('meta', {}))
    state = snapshot.get('state')
    if isinstance(state, dict):
        save_state(session_id, state)
    persona_layers = snapshot.get('persona_layers')
    if isinstance(persona_layers, dict):
        save_session_persona_layers(session_id, persona_layers)
    event_summaries = snapshot.get('event_summaries')
    if isinstance(event_summaries, dict):
        save_event_summaries(session_id, event_summaries)
    summary_chunks = snapshot.get('summary_chunks')
    if isinstance(summary_chunks, dict):
        save_summary_chunks(session_id, summary_chunks)
    save_summary(session_id, str(snapshot.get('summary', '') or ''))
    keeper_archive = session_paths(session_id)['keeper_archive']
    if snapshot.get('keeper_archive_exists'):
        atomic_write_text(keeper_archive, str(snapshot.get('keeper_archive_text', '') or ''), encoding='utf-8')
    elif keeper_archive.exists():
        keeper_archive.unlink()
    _factlog_restore(session_id, snapshot)


def regenerate_last_partial(session_id: str, *, allow_complete: bool = False) -> dict:
    history = load_history(session_id)
    meta = load_meta(session_id)
    if len(history) < 2:
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'no partial turn to regenerate'}}

    assistant = history[-1]
    user = history[-2]
    if user.get('role') != 'user' or assistant.get('role') != 'assistant':
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'latest turn is not a user/assistant pair'}}
    completion_status = assistant.get('completion_status', 'complete')
    if completion_status != 'partial' and not allow_complete:
        return {'error': {'code': 'NO_PARTIAL_TURN', 'message': 'latest assistant reply is not partial'}}

    restore_snapshot = _snapshot_artifacts(session_id, history, meta) if completion_status != 'partial' else None
    target_turn_id = _latest_turn_id(meta)
    if completion_status != 'partial':
        if not target_turn_id:
            return {'error': {'code': 'NO_REGENERATABLE_TURN', 'message': 'no committed turn to regenerate'}}
        turn_trace = load_turn_trace(session_id, target_turn_id)
        if not turn_trace:
            return {'error': {'code': 'TURN_TRACE_MISSING', 'message': 'latest turn trace is required to regenerate a complete turn'}}
        try:
            _rollback_derived_artifacts(session_id, target_turn_id, turn_trace)
        except ValueError as err:
            return {'error': {'code': 'TURN_TRACE_MISSING', 'message': str(err)}}

    trimmed_history = history[:-2]
    save_history(session_id, trimmed_history)
    if completion_status != 'partial':
        update_summary(session_id)

    if meta.get('last_turn_id', 0) > 0:
        meta['last_turn_id'] = int(meta.get('last_turn_id', 0)) - 1
    _drop_processed_turn(meta, target_turn_id)
    _drop_turn_audits(meta, target_turn_id)
    save_meta(session_id, meta)

    try:
        result = handle_message({
            'session_id': session_id,
            'text': str(user.get('content', '') or ''),
            'client_turn_id': f'regenerate-{assistant.get("ts", "latest")}',
            'meta': {
                'source': 'regenerate',
                'debug': True,
            },
        })
    except Exception:
        if restore_snapshot is not None:
            _restore_artifacts(session_id, restore_snapshot)
        raise
    if 'error' in result and restore_snapshot is not None:
        _restore_artifacts(session_id, restore_snapshot)
        return result
    if 'error' not in result:
        regenerated_history = load_history(session_id)
        if len(regenerated_history) >= 2 and regenerated_history[-2].get('role') == 'user':
            regenerated_history[-2] = dict(user)
            save_history(session_id, regenerated_history)
    return result


def delete_latest_turn(session_id: str) -> dict:
    history = load_history(session_id)
    meta = load_meta(session_id)
    if len(history) < 2:
        return {'error': {'code': 'NO_DELETABLE_TURN', 'message': 'no latest turn to delete'}}

    assistant = history[-1]
    user = history[-2]
    if user.get('role') != 'user' or assistant.get('role') != 'assistant':
        return {'error': {'code': 'NO_DELETABLE_TURN', 'message': 'latest turn is not a user/assistant pair'}}

    completion_status = assistant.get('completion_status', 'complete')
    target_turn_id = _latest_turn_id(meta)
    restore_snapshot = _snapshot_artifacts(session_id, history, meta)
    try:
        if completion_status != 'partial':
            if not target_turn_id:
                return {'error': {'code': 'NO_DELETABLE_TURN', 'message': 'no committed turn to delete'}}
            turn_trace = load_turn_trace(session_id, target_turn_id)
            if not turn_trace:
                return {'error': {'code': 'TURN_TRACE_MISSING', 'message': 'latest turn trace is required to delete a complete turn'}}
            _rollback_derived_artifacts(session_id, target_turn_id, turn_trace, reset_derived_caches=False, history_message_count=len(history) - 2)

        trimmed_history = history[:-2]
        save_history(session_id, trimmed_history)
        if completion_status != 'partial':
            update_summary(session_id)

        if completion_status != 'partial' and int(meta.get('last_turn_id', 0) or 0) > 0:
            meta['last_turn_id'] = int(meta.get('last_turn_id', 0) or 0) - 1
        _drop_processed_turn(meta, target_turn_id if completion_status != 'partial' else None)
        _drop_turn_audits(meta, target_turn_id if completion_status != 'partial' else None)
        save_meta(session_id, meta)
    except ValueError as err:
        _restore_artifacts(session_id, restore_snapshot)
        return {'error': {'code': 'TURN_TRACE_MISSING', 'message': str(err)}}
    except Exception:
        _restore_artifacts(session_id, restore_snapshot)
        raise

    return {
        'ok': True,
        'session_id': session_id,
        'deleted_turn_id': target_turn_id if completion_status != 'partial' else None,
        'deleted_user_text': str(user.get('content', '') or ''),
    }
