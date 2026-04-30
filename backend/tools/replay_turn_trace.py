#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from paths import normalize_session_id, normalize_turn_id, resolve_session_dir
from continuity_hints import normalized_hint_entries
from continuity_resolver import resolve_important_npc_continuity
from important_npc_tracker import update_important_npcs
from persona_updater import update_persona
from runtime_store import (
    append_history,
    build_state_snapshot,
    load_history,
    load_turn_trace,
    save_canon,
    save_continuity_hints,
    save_context,
    save_history,
    save_meta,
    save_session_persona_layers,
    save_state,
    save_summary,
    session_paths,
)
from state_fragment import build_state_from_fragment
from state_updater import update_state
from summary_updater import update_summary
from thread_tracker import apply_thread_tracker
from arbiter_state import merge_arbiter_state


ROOT = Path(__file__).resolve().parents[2]


def _copy_optional_file(src: Path, dst: Path) -> None:
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def _bootstrap_replay_session(source_session: str, target_session: str, trace: dict) -> None:
    source_session = normalize_session_id(source_session)
    target_session = normalize_session_id(target_session)
    source_paths = session_paths(source_session)
    raw_target_dir = resolve_session_dir(target_session, create=False)
    if raw_target_dir.exists() and any(raw_target_dir.iterdir()):
        raise RuntimeError(f'target session already exists and is not empty: {target_session}')
    target_paths = session_paths(target_session)
    target_paths['session_dir'].mkdir(parents=True, exist_ok=True)

    context = {
        'replay_bootstrap': 'trace-turn',
        'source_session': source_session,
        'source_turn_id': trace.get('turn_id'),
    }
    source_context_path = source_paths['context']
    if source_context_path.exists():
        try:
            source_context = json.loads(source_context_path.read_text(encoding='utf-8'))
        except Exception:
            source_context = {}
        if isinstance(source_context, dict):
            context.update(source_context)
    save_context(target_session, context)

    _copy_optional_file(source_paths['canon'], target_paths['canon'])
    _copy_optional_file(source_paths['summary'], target_paths['summary'])
    _copy_optional_file(source_paths['continuity_hints'], target_paths['continuity_hints'])


def _restore_pre_turn(trace: dict, target_session: str) -> None:
    request = trace.get('request', {}) if isinstance(trace.get('request', {}), dict) else {}
    pre_turn = trace.get('pre_turn', {}) if isinstance(trace.get('pre_turn', {}), dict) else {}

    pre_state = pre_turn.get('state', {})
    if not isinstance(pre_state, dict):
        raise RuntimeError('trace pre_turn.state is missing or invalid')
    save_state(target_session, pre_state)

    pre_summary = pre_turn.get('summary_text')
    if isinstance(pre_summary, str):
        save_summary(target_session, pre_summary)

    pre_canon = pre_turn.get('canon_text')
    if isinstance(pre_canon, str):
        save_canon(target_session, pre_canon)

    if isinstance(pre_turn.get('history_items'), list):
        save_history(target_session, pre_turn['history_items'])
    else:
        save_history(target_session, [])

    continuity_hints = pre_turn.get('continuity_hints')
    if isinstance(continuity_hints, list):
        save_continuity_hints(target_session, continuity_hints)

    persona_layers = pre_turn.get('persona_layers')
    if persona_layers is not None:
        save_session_persona_layers(target_session, persona_layers)

    turn_index = int(pre_turn.get('last_turn_id', 0) or 0)
    client_turn_id = str(trace.get('client_turn_id', '') or '').strip()
    save_meta(target_session, {
        'last_turn_id': turn_index,
        'processed_client_turn_ids': {},
    })

    user_text = str(request.get('text', '') or '').strip()
    if user_text:
        ts = int(trace.get('ts', 0) or 0)
        append_history(target_session, {'ts': ts, 'role': 'user', 'content': user_text})


def replay_turn_trace(source_session: str, turn_id: str, target_session: str) -> dict:
    source_session = normalize_session_id(source_session)
    turn_id = normalize_turn_id(turn_id)
    target_session = normalize_session_id(target_session)
    trace = load_turn_trace(source_session, turn_id)
    if not trace:
        raise RuntimeError(f'trace not found: session={source_session} turn={turn_id}')
    if trace.get('mode') != 'runtime':
        raise RuntimeError(f'trace mode {trace.get("mode")} is not supported for exact runtime replay')

    _bootstrap_replay_session(source_session, target_session, trace)
    _restore_pre_turn(trace, target_session)

    request = trace.get('request', {}) if isinstance(trace.get('request', {}), dict) else {}
    runtime = trace.get('runtime', {}) if isinstance(trace.get('runtime', {}), dict) else {}
    post_turn = trace.get('post_turn', {}) if isinstance(trace.get('post_turn', {}), dict) else {}
    text = str(request.get('text', '') or '').strip()
    ts = int(trace.get('ts', 0) or 0)
    reply = str((runtime.get('narrator', {}) or {}).get('reply', '') or '').replace('\n...[truncated]', '').rstrip()
    completion = runtime.get('completion', {}) if isinstance(runtime.get('completion', {}), dict) else {}
    completion_status = str(completion.get('completion_status', 'complete') or 'complete')
    if not reply:
        raise RuntimeError('trace narrator reply is missing')

    append_history(target_session, {
        'ts': ts + 1,
        'role': 'assistant',
        'content': reply,
        'completion_status': completion_status,
    })

    pre_state = trace.get('pre_turn', {}).get('state', {})
    if not isinstance(pre_state, dict):
        pre_state = {}
    arbiter = runtime.get('arbiter', {}) if isinstance(runtime.get('arbiter', {}), dict) else {}
    state_fragment = runtime.get('state_fragment_final', runtime.get('state_fragment_initial', {}))
    if not isinstance(state_fragment, dict):
        state_fragment = {}

    state_after_keeper = runtime.get('state_after_keeper')
    needs_post_processing = True
    if isinstance(state_after_keeper, dict) and state_after_keeper:
        state = dict(state_after_keeper)
        state = merge_arbiter_state(state, arbiter)
    else:
        state_error = ((runtime.get('state_keeper') or {}).get('state_error')) if isinstance(runtime.get('state_keeper', {}), dict) else None
        if state_error:
            fragment_state = build_state_from_fragment(pre_state, state_fragment, target_session)
            diagnostics = ((runtime.get('state_keeper') or {}).get('diagnostics')) if isinstance(runtime.get('state_keeper', {}), dict) else {}
            fragment_state['state_keeper_diagnostics'] = diagnostics if isinstance(diagnostics, dict) else {
                'provider_requested': 'llm',
                'provider_used': 'fragment-baseline',
                'model_usage': None,
                'fallback_used': True,
                'fallback_reason': state_error,
            }
            save_state(target_session, fragment_state)
            state = update_state(target_session)
            state['state_keeper_diagnostics'] = diagnostics if isinstance(diagnostics, dict) else state.get('state_keeper_diagnostics', {})
            state = merge_arbiter_state(state, arbiter)
        else:
            final_post_state = post_turn.get('state', {})
            if not isinstance(final_post_state, dict):
                raise RuntimeError('trace runtime.state_after_keeper and post_turn.state are both missing')
            state = dict(final_post_state)
            needs_post_processing = False

    runtime_context = runtime.get('context', {}) if isinstance(runtime.get('context', {}), dict) else {}
    continuity_candidates = runtime_context.get('continuity_candidates', [])
    if not isinstance(continuity_candidates, list) or not continuity_candidates:
        continuity_candidates = []
        seen_names: set[str] = set()
        for key in ('system_npc_candidates', 'lorebook_npc_candidates'):
            for item in (runtime_context.get(key, []) or []):
                if not isinstance(item, dict):
                    continue
                name = str(item.get('name', '') or '').strip()
                if not name or name in seen_names:
                    continue
                seen_names.add(name)
                continuity_candidates.append(item)

    if needs_post_processing:
        state = apply_thread_tracker(state, user_text=text, narrator_reply=reply, arbiter=arbiter)
        state['continuity_hints'] = normalized_hint_entries(target_session)
        state = update_important_npcs(state, load_history(target_session), continuity_candidates, allow_archive_write=False)
        state = resolve_important_npc_continuity(state)
        save_state(target_session, state)
        persona_counts = update_persona(target_session, continuity_candidates)
        summary_text = update_summary(target_session)
    else:
        save_state(target_session, state)
        persona_counts = {'scene': 0, 'archive': 0, 'longterm': 0}
        summary_text = ''

    final_snapshot = build_state_snapshot(state)
    report = {
        'source_session': source_session,
        'source_turn_id': turn_id,
        'target_session': target_session,
        'request_text': text,
        'reply_preview': reply[:200],
        'completion_status': completion_status,
        'state_snapshot': final_snapshot,
        'persona_counts': persona_counts,
        'summary_chars': len(summary_text),
        'expected_state_snapshot': post_turn.get('state_snapshot'),
    }
    report_path = session_paths(target_session)['session_dir'] / 'replay-turn-report.json'
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description='Replay a single saved turn trace into a fresh replay session')
    parser.add_argument('--source-session', required=True, help='Session id that contains turn-trace/<turn>.json')
    parser.add_argument('--turn-id', required=True, help='Turn id such as turn-0007')
    parser.add_argument('--target-session', help='Optional replay target session id')
    args = parser.parse_args()

    source_session = normalize_session_id(args.source_session)
    turn_id = normalize_turn_id(args.turn_id)
    target_session = normalize_session_id(args.target_session or f'replay-{source_session}-{turn_id}')
    report = replay_turn_trace(source_session, turn_id, target_session)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
