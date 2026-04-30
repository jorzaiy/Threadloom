#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import time
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from paths import normalize_session_id, reset_active_character_override, resolve_session_dir, set_active_character_override
from arbiter_runtime import run_arbiter
from arbiter_state import merge_arbiter_state
from context_builder import build_runtime_context
from continuity_hints import normalized_hint_entries
from continuity_resolver import resolve_important_npc_continuity
from important_npc_tracker import update_important_npcs
from persona_updater import update_persona
from state_fragment import build_state_fragment, merge_state_skeleton
from state_keeper import call_skeleton_keeper, call_state_keeper, skeleton_keeper_enabled
from runtime_store import (
    build_state_snapshot,
    invalidate_history_cache,
    load_canon,
    load_context,
    load_history,
    load_state,
    save_canon,
    save_context,
    save_history,
    save_meta,
    save_session_persona_layers,
    save_state,
    save_summary,
    seed_default_state,
    session_paths,
)
from state_updater import update_state
from summary_updater import update_summary
from thread_tracker import apply_thread_tracker


ROOT = Path(__file__).resolve().parents[2]
REBUILD_KEEPER_MIN_INTERVAL_SECONDS = 24.0


def _safe_empty_dir(path: Path) -> bool:
    if not path.exists():
        return True
    for item in path.iterdir():
        if item.is_dir():
            if any(item.iterdir()):
                return False
        else:
            return False
    return True


def _load_json_file(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return {}


def _is_rebuild_artifact(path: Path, *, source_session: str | None = None) -> bool:
    context = _load_json_file(path / 'context.json')
    if not isinstance(context, dict):
        return False
    if context.get('rebuild_mode') == 'history-only':
        return True
    if source_session and context.get('rebuild_source_session') == source_session:
        return True
    return False


def _remove_target_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def _assistant_pairs(items: list[dict]) -> list[tuple[int, dict, dict]]:
    pairs: list[tuple[int, dict, dict]] = []
    current_user: tuple[int, dict] | None = None
    for idx, item in enumerate(items):
        role = item.get('role')
        if role == 'user':
            current_user = (idx, item)
        elif role == 'assistant' and current_user is not None:
            user_idx, user_item = current_user
            if item.get('completion_status', 'complete') != 'complete':
                current_user = None
                continue
            pairs.append((user_idx, user_item, item))
            current_user = None
    return pairs


def _reset_runtime_layers(session_id: str) -> None:
    paths = session_paths(session_id)
    save_state(session_id, seed_default_state(session_id))
    save_summary(session_id, '# Summary\n\n## 当前状态锚点\n- 暂无\n\n## 活跃线程\n- 暂无\n\n## 当前裁定信号\n- 暂无\n\n## 最近变化\n- 暂无\n\n## 未决问题\n- 暂无\n')
    save_meta(session_id, {'last_turn_id': 0, 'processed_client_turn_ids': {}})
    save_session_persona_layers(session_id, {'scene': {}, 'archive': {}, 'longterm': {}})
    trace_dir = paths['trace_dir']
    if trace_dir.exists():
        shutil.rmtree(trace_dir)


def _prepare_target_session(source_session: str, target_session: str, *, force_recreate: bool = False) -> list[dict]:
    source_session = normalize_session_id(source_session)
    target_session = normalize_session_id(target_session)
    source_paths = session_paths(source_session)
    raw_target_dir = resolve_session_dir(target_session, create=False)
    if raw_target_dir.exists():
        if force_recreate or _safe_empty_dir(raw_target_dir) or _is_rebuild_artifact(raw_target_dir, source_session=source_session):
            _remove_target_dir(raw_target_dir)
        else:
            raise RuntimeError(f'target session already exists and is not empty: {target_session}')
    target_paths = session_paths(target_session)

    history = load_history(source_session)
    save_history(target_session, history)
    save_canon(target_session, load_canon(source_session))
    save_context(target_session, {
        **load_context(source_session),
        'rebuild_source_session': source_session,
        'rebuild_mode': 'history-only',
    })
    return history


def _llm_keeper_rebuild_step(session_id: str, user_text: str, assistant_text: str) -> tuple[dict, dict]:
    def _retry_delay_from_error(err: Exception) -> float:
        text = str(err or '')
        match = re.search(r'Please try again in ([0-9]+(?:\.[0-9]+)?)s', text)
        if match:
            try:
                return max(0.0, float(match.group(1))) + 0.2
            except Exception:
                return 1.0
        if '429' in text or 'Too Many Requests' in text:
            return 10.5
        if 'timed out' in text or 'The read operation timed out' in text:
            return 6.0
        return 0.0

    def _call_with_retry(fn, *args, retries: int = 2, **kwargs):
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except Exception as err:
                delay = _retry_delay_from_error(err)
                if attempt >= retries or delay <= 0:
                    raise
                time.sleep(delay)
                attempt += 1

    heuristic_seed = update_state(session_id)
    prev_state = heuristic_seed or load_state(session_id) or seed_default_state(session_id)
    context = build_runtime_context(session_id)
    scene = context.get('scene_facts', {}) if isinstance(context.get('scene_facts', {}), dict) else {}
    arbiter = run_arbiter(user_text, scene)
    state_fragment = build_state_fragment(prev_state, scene, user_text=user_text, arbiter=arbiter)

    skeleton_info: dict = {
        'enabled': bool(skeleton_keeper_enabled()),
        'used': False,
        'skipped': True,
        'reason': 'disabled_for_rebuild_rate_limit',
        'error': None,
    }

    keeper_trace = None
    fallback_reason = None
    try:
        state, keeper_trace = _call_with_retry(
            call_state_keeper,
            session_id,
            assistant_text,
            state_fragment=state_fragment,
            user_text=user_text,
            return_trace=True,
        )
    except Exception as err:
        fallback_reason = str(err)
        state = update_state(session_id)
        diagnostics = state.get('state_keeper_diagnostics', {}) if isinstance(state.get('state_keeper_diagnostics', {}), dict) else {}
        diagnostics.update({
            'provider_requested': 'llm',
            'provider_used': 'heuristic-fallback',
            'fallback_used': True,
            'fallback_reason': fallback_reason,
        })
        state['state_keeper_diagnostics'] = diagnostics

    state = merge_arbiter_state(state, arbiter)
    state = apply_thread_tracker(
        state,
        user_text=user_text,
        narrator_reply=assistant_text,
        arbiter=arbiter,
    )
    state['continuity_hints'] = normalized_hint_entries(session_id)
    state = update_important_npcs(state, load_history(session_id), context.get('continuity_candidates', []), allow_archive_write=False)
    state = resolve_important_npc_continuity(state)
    save_state(session_id, state)
    persona_counts = update_persona(session_id, context.get('continuity_candidates', []))
    summary_text = update_summary(session_id)
    debug = {
        'mode': 'llm-keeper',
        'arbiter_needed': bool(arbiter.get('arbiter_needed')),
        'arbiter_results': arbiter.get('results', []),
        'skeleton_keeper': skeleton_info,
        'state_keeper_diagnostics': state.get('state_keeper_diagnostics', {}),
        'fallback_reason': fallback_reason,
        'keeper_trace_excerpt': {
            'raw_reply': (keeper_trace or {}).get('raw_reply', '')[:800] if isinstance(keeper_trace, dict) else '',
            'payload': (keeper_trace or {}).get('payload', {}) if isinstance(keeper_trace, dict) else {},
        },
    }
    return state, {
        'persona_counts': persona_counts,
        'summary_chars': len(summary_text),
        'debug': debug,
    }


def rebuild_session_from_history(source_session: str, *, target_session: str | None = None, max_pairs: int | None = None, start_pair: int = 1, warmup_pairs: int = 6, force_recreate: bool = False, use_llm_keeper: bool = False, keeper_stride: int = 1) -> dict:
    source_session = normalize_session_id(source_session)
    if target_session:
        target_session = normalize_session_id(target_session)
    session_id = target_session or source_session
    using_target_copy = bool(target_session and target_session != source_session)
    try:
        if using_target_copy:
            full_history = _prepare_target_session(source_session, target_session, force_recreate=force_recreate)
        else:
            full_history = load_history(session_id)
    except Exception:
        if using_target_copy:
            raw_target_dir = resolve_session_dir(session_id, create=False)
            if _safe_empty_dir(raw_target_dir):
                shutil.rmtree(raw_target_dir, ignore_errors=True)
        raise
    pairs = _assistant_pairs(full_history)
    start_index = max(0, int(start_pair or 1) - 1)
    warmup_count = max(0, int(warmup_pairs or 0))
    warmup_start = max(0, start_index - warmup_count)
    pairs = pairs[warmup_start:]
    if max_pairs is not None:
        total_needed = (start_index - warmup_start) + max_pairs
        pairs = pairs[:total_needed]

    try:
        _reset_runtime_layers(session_id)
        rebuilt_history: list[dict] = []
        reports: list[dict] = []

        measured_start = start_index - warmup_start
        for pair_index, (_user_idx, user_item, assistant_item) in enumerate(pairs, start=1):
            rebuilt_history.append(dict(user_item))
            rebuilt_history.append(dict(assistant_item))
            save_history(session_id, rebuilt_history)
            invalidate_history_cache(session_id)

            user_text = str(user_item.get('content', '') or '')
            assistant_text = str(assistant_item.get('content', '') or '')

            if use_llm_keeper and ((pair_index - 1) % max(1, keeper_stride) == 0):
                state, step_info = _llm_keeper_rebuild_step(session_id, user_text, assistant_text)
                persona_counts = step_info['persona_counts']
                summary_text = 'x' * int(step_info['summary_chars'])
                debug = step_info['debug']
                time.sleep(REBUILD_KEEPER_MIN_INTERVAL_SECONDS)
            else:
                state = update_state(session_id)
                state = apply_thread_tracker(
                    state,
                    user_text=user_text,
                    narrator_reply=assistant_text,
                    arbiter=None,
                )
                state['continuity_hints'] = normalized_hint_entries(session_id)
                state = update_important_npcs(state, rebuilt_history, [], allow_archive_write=False)
                state = resolve_important_npc_continuity(state)
                save_state(session_id, state)
                persona_counts = update_persona(session_id, [])
                summary_text = update_summary(session_id)
                debug = {
                    'mode': 'heuristic',
                    'llm_keeper_skipped': bool(use_llm_keeper),
                }

            if pair_index > measured_start:
                reports.append({
                    'pair_index': start_index + (pair_index - measured_start),
                    'user_preview': user_text[:120],
                    'assistant_preview': assistant_text[:120],
                    'state_snapshot': build_state_snapshot(load_state(session_id)),
                    'persona_counts': persona_counts,
                    'summary_chars': len(summary_text),
                    'debug': debug,
                })

        final_state = load_state(session_id)
        report = {
            'session_id': session_id,
            'source_session': source_session,
            'mode': 'llm-keeper' if use_llm_keeper else 'heuristic',
            'keeper_stride': max(1, keeper_stride),
            'start_pair': max(1, int(start_pair or 1)),
            'warmup_pairs': max(0, measured_start),
            'pair_count': len(reports),
            'history_message_count': len(rebuilt_history),
            'final_state_snapshot': build_state_snapshot(final_state),
            'turn_reports': reports[-8:],
        }
        report_path = session_paths(session_id)['session_dir'] / 'rebuild-report.json'
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        return report
    except Exception:
        if using_target_copy:
            raw_target_dir = resolve_session_dir(session_id, create=False)
            if _safe_empty_dir(raw_target_dir):
                shutil.rmtree(raw_target_dir, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description='Rebuild state/summary/persona/threads from an existing session history')
    parser.add_argument('--session', required=True, help='Existing source session id')
    parser.add_argument('--target-session', help='Optional target session id for safe rebuild testing')
    parser.add_argument('--character-id', help='Target character id / directory name override')
    parser.add_argument('--start-pair', type=int, default=1, help='Start rebuilding from this user/assistant pair index (1-based)')
    parser.add_argument('--warmup-pairs', type=int, default=6, help='Replay this many earlier pairs before start-pair to build continuity context')
    parser.add_argument('--max-pairs', type=int, help='Optional max number of complete user/assistant pairs to rebuild')
    parser.add_argument('--force-recreate', action='store_true', help='Allow deleting an existing rebuild target session before regenerating it')
    parser.add_argument('--use-llm-keeper', action='store_true', help='Use the real LLM keeper chain instead of heuristic update_state()')
    parser.add_argument('--keeper-model', help='Temporary state_keeper model override used only for this rebuild run')
    parser.add_argument('--keeper-max-tokens', type=int, help='Temporary state_keeper max_output_tokens override used only for this rebuild run')
    parser.add_argument('--keeper-summary-chars', type=int, help='Temporary state_keeper summary excerpt size override used only for this rebuild run')
    parser.add_argument('--keeper-stride', type=int, default=1, help='Only call LLM keeper every N pairs during rebuild; other pairs use heuristics')
    args = parser.parse_args()
    character_override_token = set_active_character_override(args.character_id)
    old_override = os.environ.get('THREADLOOM_OVERRIDE_STATE_KEEPER_MODEL')
    old_max_tokens_override = os.environ.get('THREADLOOM_OVERRIDE_STATE_KEEPER_MAX_TOKENS')
    old_summary_chars_override = os.environ.get('THREADLOOM_OVERRIDE_STATE_KEEPER_SUMMARY_CHARS')
    old_stream_override = os.environ.get('THREADLOOM_OVERRIDE_STATE_KEEPER_STREAM')
    if args.keeper_model:
        os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_MODEL'] = args.keeper_model
    if args.keeper_max_tokens:
        os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_MAX_TOKENS'] = str(args.keeper_max_tokens)
        os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_STREAM'] = 'false'
    if args.keeper_summary_chars:
        os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_SUMMARY_CHARS'] = str(args.keeper_summary_chars)
    try:
        report = rebuild_session_from_history(
            normalize_session_id(args.session),
            target_session=normalize_session_id(args.target_session) if args.target_session else None,
            max_pairs=args.max_pairs,
            start_pair=args.start_pair,
            warmup_pairs=args.warmup_pairs,
            force_recreate=args.force_recreate,
            use_llm_keeper=args.use_llm_keeper,
            keeper_stride=args.keeper_stride,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    finally:
        if args.keeper_model:
            if old_override is None:
                os.environ.pop('THREADLOOM_OVERRIDE_STATE_KEEPER_MODEL', None)
            else:
                os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_MODEL'] = old_override
        if args.keeper_max_tokens:
            if old_max_tokens_override is None:
                os.environ.pop('THREADLOOM_OVERRIDE_STATE_KEEPER_MAX_TOKENS', None)
            else:
                os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_MAX_TOKENS'] = old_max_tokens_override
        if args.keeper_summary_chars:
            if old_summary_chars_override is None:
                os.environ.pop('THREADLOOM_OVERRIDE_STATE_KEEPER_SUMMARY_CHARS', None)
            else:
                os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_SUMMARY_CHARS'] = old_summary_chars_override
        if args.keeper_max_tokens:
            if old_stream_override is None:
                os.environ.pop('THREADLOOM_OVERRIDE_STATE_KEEPER_STREAM', None)
            else:
                os.environ['THREADLOOM_OVERRIDE_STATE_KEEPER_STREAM'] = old_stream_override
        reset_active_character_override(character_override_token)


if __name__ == '__main__':
    raise SystemExit(main())
