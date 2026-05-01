#!/usr/bin/env python3
import copy
import time
from typing import Any

try:
    from .arbiter_runtime import run_arbiter
    from .arbiter_state import merge_arbiter_state
    from .continuity_resolver import resolve_important_npc_continuity
    from .continuity_hints import normalized_hint_entries
    from .important_npc_tracker import update_important_npcs
    from .thread_tracker import apply_thread_tracker
    from .runtime_store import append_event_summary, append_history, build_state_snapshot, load_canon, load_continuity_hints, load_event_summaries, load_history, load_meta, load_session_persona_layers, load_state, load_summary, save_meta, save_state, save_turn_trace, seed_default_state, web_runtime_settings
    from .actor_registry import update_actor_registry
    from .summary_updater import update_summary
    from .summary_chunks import update_summary_chunks
    from .context_builder import build_runtime_context
    from .bootstrap_session import bootstrap_session
    from .opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from .model_config import resolve_provider_model, load_runtime_config
    from .model_client import call_model
    from .model_client import looks_incomplete_reply
    from .narrator_input import build_narrator_input, prompt_block_stats
    from .paths import normalize_session_id
    from .state_fragment import build_state_fragment, build_state_from_fragment, merge_reply_skeleton
    from .state_keeper import StateKeeperCallError, call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from .persona_updater import update_persona
    from .state_fragment import merge_state_skeleton
    from .event_ledger import build_event_summary_item
except ImportError:
    from arbiter_runtime import run_arbiter
    from arbiter_state import merge_arbiter_state
    from continuity_resolver import resolve_important_npc_continuity
    from continuity_hints import normalized_hint_entries
    from important_npc_tracker import update_important_npcs
    from thread_tracker import apply_thread_tracker
    from runtime_store import append_event_summary, append_history, build_state_snapshot, load_canon, load_continuity_hints, load_event_summaries, load_history, load_meta, load_session_persona_layers, load_state, load_summary, save_meta, save_state, save_turn_trace, seed_default_state, web_runtime_settings
    from actor_registry import update_actor_registry
    from summary_updater import update_summary
    from summary_chunks import update_summary_chunks
    from context_builder import build_runtime_context
    from bootstrap_session import bootstrap_session
    from opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from model_config import resolve_provider_model, load_runtime_config
    from model_client import call_model
    from model_client import looks_incomplete_reply
    from narrator_input import build_narrator_input, prompt_block_stats
    from paths import normalize_session_id
    from state_fragment import build_state_fragment, build_state_from_fragment, merge_reply_skeleton
    from state_keeper import StateKeeperCallError, call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from persona_updater import update_persona
    from state_fragment import merge_state_skeleton
    from event_ledger import build_event_summary_item


TRACE_PROMPT_LIMIT = 4000
OBJECT_TRANSFER_TERMS = (
    '递给', '交给', '塞给', '接过', '拿走', '夺过', '收走', '放下', '放回', '搁下', '摆回',
    '收起', '亮出', '摸出', '掏出', '握住', '拿起', '取出', '归还', '还给', '落到', '交回',
)


def _trim_trace_text(text: str, limit: int = TRACE_PROMPT_LIMIT) -> str:
    value = str(text or '')
    if len(value) <= limit:
        return value
    return value[:limit] + '\n...[truncated]'


def _state_keeper_failure_diagnostics(err: Exception, state_error: str) -> dict:
    usage = err.usage if isinstance(err, StateKeeperCallError) and isinstance(err.usage, dict) else None
    raw_reply = err.raw_reply if isinstance(err, StateKeeperCallError) else ''
    diagnostics = {
        'provider_requested': 'llm',
        'provider_used': 'fragment-baseline',
        'model_usage': copy.deepcopy(usage),
        'fallback_used': True,
        'fallback_reason': state_error,
    }
    if isinstance(raw_reply, str):
        diagnostics['raw_reply_empty'] = not raw_reply.strip()
        diagnostics['raw_reply_excerpt'] = _trim_trace_text(raw_reply, 600)
    return diagnostics


def _model_label(model_cfg: dict) -> str:
    return f"{model_cfg.get('provider_name', 'unknown')}:{model_cfg.get('model', {}).get('id', 'unknown')}"


def _secondary_narrator_model_cfg(primary_cfg: dict, keeper_cfg: dict) -> dict:
    secondary = copy.deepcopy(primary_cfg)
    secondary['provider_name'] = keeper_cfg.get('provider_name', secondary.get('provider_name'))
    secondary['provider'] = copy.deepcopy(keeper_cfg.get('provider', secondary.get('provider', {})))
    secondary['model'] = copy.deepcopy(keeper_cfg.get('model', secondary.get('model', {})))
    secondary['is_secondary_narrator'] = True
    secondary.pop('response_format', None)
    return secondary


def _call_narrator_with_retries(system_prompt: str, user_prompt: str, *, max_attempts: int = 3) -> tuple[str, dict, dict]:
    primary_cfg = resolve_provider_model('narrator')
    keeper_cfg = resolve_provider_model('state_keeper')
    model_plan = [
        ('primary', primary_cfg),
        ('secondary', _secondary_narrator_model_cfg(primary_cfg, keeper_cfg)),
    ]
    attempts = []
    last_error = None
    attempt_count = 0
    for role, model_cfg in model_plan:
        while attempt_count < max_attempts:
            attempt_count += 1
            attempt = {
                'role': role,
                'attempt': attempt_count,
                'model': _model_label(model_cfg),
            }
            try:
                reply, usage = call_model(model_cfg, system_prompt, user_prompt)
            except Exception as err:
                last_error = str(err)
                attempt['ok'] = False
                attempt['error'] = last_error
                attempts.append(attempt)
                continue
            finish_reason = usage.get('finish_reason') if isinstance(usage, dict) else None
            if not str(reply or '').strip():
                last_error = 'empty narrator reply'
                attempt['ok'] = False
                attempt['error'] = last_error
                attempt['finish_reason'] = finish_reason
                attempts.append(attempt)
                continue
            if finish_reason in ('length', 'error') or looks_incomplete_reply(reply):
                last_error = 'incomplete narrator reply'
                attempt['ok'] = False
                attempt['error'] = last_error
                attempt['finish_reason'] = finish_reason or 'incomplete'
                attempt['reply_excerpt'] = _trim_trace_text(reply, 500)
                attempts.append(attempt)
                continue
            attempt['ok'] = True
            attempt['finish_reason'] = finish_reason
            attempts.append(attempt)
            usage = dict(usage or {})
            usage['model_role'] = role
            usage['model'] = usage.get('model') or _model_label(model_cfg)
            trace = {
                'attempts': attempts,
                'provider_used': role,
                'model_used': _model_label(model_cfg),
                'fallback_to_secondary': role == 'secondary',
                'all_failed': False,
            }
            return reply, usage, trace
        if attempt_count >= max_attempts:
            break
    trace = {
        'attempts': attempts,
        'provider_used': 'none',
        'model_used': None,
        'fallback_to_secondary': True,
        'all_failed': True,
        'last_error': last_error or 'narrator failed after retries',
    }
    usage = {
        'model': _model_label(primary_cfg),
        'input_tokens': 0,
        'output_tokens': 0,
        'finish_reason': 'error',
    }
    return '', usage, trace


def _keeper_fallback_bootstrapped(fragment_state: dict, skeleton_keeper_diagnostics: dict | None = None) -> bool:
    """Treat fragment/skeleton state as enough to leave bootstrap retry mode.

    A full keeper parse failure should not force every later turn back into full
    bootstrap mode; that also skips skeleton keeper and amplifies missing writes.
    """
    if isinstance(skeleton_keeper_diagnostics, dict) and not skeleton_keeper_diagnostics.get('fallback_used'):
        if skeleton_keeper_diagnostics.get('provider_used') in {'llm', 'skipped'}:
            return True
    if not isinstance(fragment_state, dict):
        return False
    usable_core = 0
    for field in ('time', 'location', 'main_event', 'immediate_goal'):
        value = str(fragment_state.get(field, '') or '').strip()
        if value and not value.startswith('待确认'):
            usable_core += 1
    if fragment_state.get('onstage_npcs'):
        usable_core += 1
    return usable_core >= 2


def _trace_context_excerpt(context: dict) -> dict:
    if not isinstance(context, dict):
        return {}
    scene = context.get('scene_facts', {}) if isinstance(context.get('scene_facts', {}), dict) else {}
    preset = context.get('active_preset', {}) if isinstance(context.get('active_preset', {}), dict) else {}
    return {
        'active_preset': preset.get('name'),
        'scene_facts': copy.deepcopy(scene),
        'context_audit': copy.deepcopy(context.get('context_audit', {})) if isinstance(context.get('context_audit', {}), dict) else {},
        'summary_text_present': bool(context.get('summary_text', '')),
        'persona_names': [item.get('name') for item in (context.get('persona', []) or []) if isinstance(item, dict)],
        'lorebook_npc_candidates': [
            {
                'name': item.get('name'),
                'title': item.get('title'),
                'summary': item.get('summary'),
                'priority': item.get('priority'),
                'source': item.get('source'),
            }
            for item in (context.get('lorebook_npc_candidates', []) or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'system_npc_candidates': [
            {
                'name': item.get('name'),
                'title': item.get('title'),
                'summary': item.get('summary'),
                'priority': item.get('priority'),
                'source': item.get('source'),
            }
            for item in (context.get('system_npc_candidates', []) or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'continuity_candidates': [
            {
                'name': item.get('name'),
                'title': item.get('title'),
                'summary': item.get('summary'),
                'priority': item.get('priority'),
                'source': item.get('source'),
            }
            for item in (context.get('continuity_candidates', []) or [])
            if isinstance(item, dict) and item.get('name')
        ],
        'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
        'recent_history_count': len(context.get('recent_history', []) or []),
    }


def _safe_count(value) -> int:
    return len(value) if isinstance(value, list) else 0


def _compact_selector_audit(selector: dict) -> dict:
    if not isinstance(selector, dict):
        return {}
    return {
        'selector_version': selector.get('selector_version'),
        'inject_lorebook_text': bool(selector.get('inject_lorebook_text')),
        'inject_npc_candidates': bool(selector.get('inject_npc_candidates')),
        'inject_summary': bool(selector.get('inject_summary')),
        'event_hit_count': _safe_count(selector.get('event_hits')),
        'summary_chunk_hit_count': _safe_count(selector.get('summary_chunk_hits')),
        'npc_profile_target_count': _safe_count(selector.get('npc_profile_targets')),
        'npc_roster_count': _safe_count(selector.get('npc_roster')),
        'event_hit_ids': [str(item.get('event_id', '') or '') for item in (selector.get('event_hits') or []) if isinstance(item, dict) and item.get('event_id')][:8],
        'summary_chunk_ids': [str(item.get('chunk_id', '') or '') for item in (selector.get('summary_chunk_hits') or []) if isinstance(item, dict) and item.get('chunk_id')][:8],
    }


def _compact_lorebook_audit(lorebook_injection: dict) -> dict:
    if not isinstance(lorebook_injection, dict):
        return {}
    items = lorebook_injection.get('items', []) if isinstance(lorebook_injection.get('items', []), list) else []
    return {
        'item_count': len(items),
        'total_chars': lorebook_injection.get('total_chars', 0),
        'mode': lorebook_injection.get('mode'),
        'item_ids': [str(item.get('id', item.get('title', '')) or '') for item in items if isinstance(item, dict)][:8],
        'foundation_count': _safe_count((lorebook_injection.get('foundation') or {}).get('items') if isinstance(lorebook_injection.get('foundation'), dict) else []),
    }


def _build_turn_audit(context: dict, *, turn_id: str, prompt_stats: list[dict], force_full_keeper: bool = False, force_full_keeper_reason: str = '', state_keeper_diagnostics: dict | None = None) -> dict:
    selector = context.get('context_audit', {}) if isinstance(context, dict) else {}
    lorebook_injection = context.get('lorebook_injection', {}) if isinstance(context, dict) else {}
    return {
        'version': 1,
        'turn_id': turn_id,
        'selector': _compact_selector_audit(selector),
        'lorebook_injection': _compact_lorebook_audit(lorebook_injection),
        'narrator_injection': {
            'prompt_block_stats': copy.deepcopy(prompt_stats),
            'lorebook_text_injected': bool((context or {}).get('lorebook_text', '')),
            'system_npc_candidate_count': _safe_count((context or {}).get('system_npc_candidates')),
            'lorebook_npc_candidate_count': _safe_count((context or {}).get('lorebook_npc_candidates')),
            'npc_profile_count': _safe_count((context or {}).get('npc_profiles')),
            'selected_summary_chunk_count': _safe_count((context or {}).get('selected_summary_chunks')),
            'event_summary_count': _safe_count((context or {}).get('event_summaries')),
        },
        'keeper': {
            'force_full_keeper': bool(force_full_keeper),
            'force_full_keeper_reason': force_full_keeper_reason,
            'provider_used': (state_keeper_diagnostics or {}).get('provider_used') if isinstance(state_keeper_diagnostics, dict) else None,
        },
    }


def _is_object_heavy_turn(user_text: str, reply: str, state: dict, state_fragment: dict | None = None) -> bool:
    combined = f'{user_text}\n{reply}'
    if state_fragment:
        combined += '\n' + str(state_fragment.get('main_event', '') or '')
        combined += '\n' + ' '.join(str(item.get('text', '') if isinstance(item, dict) else item) for item in (state_fragment.get('carryover_signals', []) or []))
    if not any(term in combined for term in OBJECT_TRANSFER_TERMS):
        return False
    labels = [str(item.get('label', '') or '').strip() for item in (state.get('tracked_objects', []) or []) if isinstance(item, dict) and str(item.get('label', '') or '').strip()]
    if labels and any(label in combined for label in labels):
        return True
    return False


def _store_turn_audit(meta: dict, audit: dict) -> None:
    if not isinstance(audit, dict) or not audit:
        return
    meta['last_turn_audit'] = audit
    audits = meta.get('turn_audits', [])
    if not isinstance(audits, list):
        audits = []
    audits.append(audit)
    meta['turn_audits'] = audits[-20:]


def _build_turn_trace_base(session_id: str, turn_id: str, *, ts: int, client_turn_id: str, text: str, request_meta: dict, prev_state: dict, meta: dict) -> dict:
    return {
        'trace_version': 1,
        'session_id': session_id,
        'turn_id': turn_id,
        'ts': ts,
        'client_turn_id': client_turn_id,
        'request': {
            'text': text,
            'meta': copy.deepcopy(request_meta),
        },
        'pre_turn': {
            'last_turn_id': meta.get('last_turn_id', 0),
            'state': copy.deepcopy(prev_state),
            'state_snapshot': build_state_snapshot(prev_state),
            'summary_text': load_summary(session_id),
            'canon_text': load_canon(session_id),
            'history_items': load_history(session_id),
            'persona_layers': load_session_persona_layers(session_id),
            'continuity_hints': load_continuity_hints(session_id),
            'history_count': len(load_history(session_id)),
        },
    }


def _save_turn_trace_safe(session_id: str, turn_id: str, trace: dict) -> None:
    try:
        save_turn_trace(session_id, turn_id, trace)
    except Exception:
        pass


def update_stub_state(state: dict, text: str, context: dict) -> dict:
    next_state = dict(state or {})
    if not next_state:
        next_state = seed_default_state('unknown')

    scene = context.get('scene_facts', {})
    next_state['time'] = scene.get('time') or next_state.get('time') or '待确认'
    next_state['location'] = scene.get('location') or next_state.get('location') or '待确认'
    next_state['main_event'] = scene.get('main_event') or '处理当前用户输入并等待 runtime 主链接管。'
    next_state['scene_entities'] = scene.get('scene_entities', [])
    next_state['onstage_npcs'] = scene.get('onstage_npcs', [])
    next_state['relevant_npcs'] = scene.get('relevant_npcs', [])
    next_state['immediate_goal'] = (scene.get('immediate_goal') or ['先跑通最小消息链路。'])[0]
    next_state['immediate_risks'] = scene.get('immediate_risks', ['尚未接入真正 narrator/arbiter/state 更新逻辑。'])
    next_state['carryover_clues'] = scene.get('carryover_clues', [])

    next_state['last_user_input'] = text
    return next_state


def validate_message_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    raw_session_id = str(payload.get('session_id', '') or '').strip()
    text = str(payload.get('text', '') or '').strip()
    client_turn_id = str(payload.get('client_turn_id', '') or '').strip()
    meta = payload.get('meta', {}) or {}

    if not raw_session_id:
        return False, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}}
    try:
        session_id = normalize_session_id(raw_session_id)
    except ValueError as err:
        return False, {'error': {'code': 'INVALID_INPUT', 'message': str(err)}}
    if not text:
        return False, {'error': {'code': 'INVALID_INPUT', 'message': 'text is required'}}

    return True, {
        'session_id': session_id,
        'text': text,
        'client_turn_id': client_turn_id,
        'meta': meta,
    }


def handle_message(payload: dict[str, Any]) -> dict[str, Any]:
    ok, parsed = validate_message_payload(payload)
    if not ok:
        return parsed

    session_id = parsed['session_id']
    text = parsed['text']
    client_turn_id = parsed['client_turn_id']
    request_meta = parsed['meta']
    debug_enabled = bool(request_meta.get('debug'))
    bootstrap_session(session_id)
    meta = load_meta(session_id)

    if client_turn_id and client_turn_id in meta['processed_client_turn_ids']:
        return meta['processed_client_turn_ids'][client_turn_id]

    turn_id = f"turn-{meta['last_turn_id'] + 1:04d}"
    ts = int(time.time() * 1000)
    prev_state = load_state(session_id)
    turn_trace = _build_turn_trace_base(
        session_id,
        turn_id,
        ts=ts,
        client_turn_id=client_turn_id,
        text=text,
        request_meta=request_meta,
        prev_state=prev_state if isinstance(prev_state, dict) else {},
        meta=meta,
    )

    def finalize_response(response: dict[str, Any], *, trace: dict | None = None) -> dict[str, Any]:
        active_trace = trace if isinstance(trace, dict) else turn_trace
        active_trace['response'] = copy.deepcopy(response)
        _save_turn_trace_safe(session_id, turn_id, active_trace)
        return response

    def append_turn_history(*, assistant_item: dict | None = None) -> None:
        append_history(session_id, {'ts': ts, 'role': 'user', 'content': text})
        if assistant_item is not None:
            append_history(session_id, assistant_item)

    def finalize_opening_choice(choice: str) -> dict[str, Any]:
        state = initialize_opening_choice_state(session_id, choice)
        opening_prompt = build_opening_choice_reply(choice)
        context = build_runtime_context(session_id, user_text=opening_prompt)
        scene = context.get('scene_facts', {})
        arbiter = run_arbiter(opening_prompt, scene)
        arbiter_result = arbiter.get('results', []) if arbiter.get('arbiter_needed') else None
        state_fragment = build_state_fragment(state, scene, user_text=opening_prompt, arbiter=arbiter)
        context = dict(context)
        context['state_fragment'] = state_fragment
        system_prompt, user_prompt = build_narrator_input(context, opening_prompt, arbiter_result=arbiter_result)
        reply, usage, narrator_retry_trace = _call_narrator_with_retries(system_prompt, user_prompt)
        model_error = narrator_retry_trace.get('last_error') if narrator_retry_trace.get('all_failed') else None
        if narrator_retry_trace.get('all_failed'):
            response = {
                'session_id': session_id,
                'turn_id': turn_id,
                'reply': '',
                'usage': usage,
                'narrator_retry': narrator_retry_trace,
                'state_snapshot': build_state_snapshot(state),
                'web': web_runtime_settings(),
                'error': {'code': 'NARRATOR_UNAVAILABLE', 'message': '正文生成不完整，已重试 3 次，未提交本轮'},
            }
            trace = copy.deepcopy(turn_trace)
            trace['mode'] = 'opening-choice-narrator-failed'
            trace['opening'] = {
                'choice': choice,
                'opening_prompt': opening_prompt,
            }
            trace['runtime'] = {
                'context': _trace_context_excerpt(context),
                'arbiter': copy.deepcopy(arbiter),
                'state_fragment_initial': copy.deepcopy(state_fragment),
                'narrator': {
                    'system_prompt': _trim_trace_text(system_prompt),
                    'user_prompt': _trim_trace_text(user_prompt),
                    'prompt_block_stats': copy.deepcopy(prompt_block_stats(system_prompt)),
                    'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                    'reply': '',
                    'usage': copy.deepcopy(usage),
                    'model_error': model_error,
                    'retry_trace': copy.deepcopy(narrator_retry_trace),
                },
            }
            trace['post_turn'] = {
                'state': copy.deepcopy(state),
                'state_snapshot': build_state_snapshot(state),
                'not_committed': True,
            }
            return finalize_response(response, trace=trace)
        state['opening_started'] = True
        state['state_keeper_bootstrapped'] = False
        # First authoritative turn commit after keeper/arbiter/thread/NPC
        # merges. A later actor-registry pass may enrich the same turn state.
        save_state(session_id, state)

        state_error = None
        state_keeper_trace = {}
        state_keeper_diagnostics = None
        skeleton_keeper_trace = None
        skeleton_keeper_diagnostics = None
        try:
            skeleton_fragment, skeleton_usage, skeleton_keeper_trace = call_skeleton_keeper(
                state,
                state_fragment,
                reply,
                return_trace=True,
            )
        except Exception as err:
            skeleton_keeper_diagnostics = {
                'provider_requested': 'llm',
                'provider_used': 'disabled-or-failed',
                'model_usage': None,
                'fallback_used': True,
                'fallback_reason': str(err),
            }
        else:
            state_fragment = merge_state_skeleton(state_fragment, skeleton_fragment)
            skeleton_keeper_diagnostics = {
                'provider_requested': 'llm',
                'provider_used': 'llm',
                'model_usage': skeleton_usage,
                'fallback_used': False,
                'fallback_reason': None,
                'skeleton_fragment': skeleton_fragment,
            }

        try:
            state, state_keeper_trace = call_state_keeper(
                session_id,
                reply,
                state_fragment=state_fragment,
                user_text=opening_prompt,
                return_trace=True,
            )
            state_keeper_diagnostics = state.get('state_keeper_diagnostics', {})
            state_keeper_diagnostics['bootstrap_turn'] = True
            state['state_keeper_bootstrapped'] = True
        except Exception as err:
            state_error = str(err)
            fragment_state = build_state_from_fragment(state, state_fragment, session_id)
            fragment_state['state_keeper_diagnostics'] = _state_keeper_failure_diagnostics(err, state_error)
            fragment_state['state_keeper_diagnostics']['bootstrap_turn'] = True
            fragment_state['state_keeper_bootstrapped'] = _keeper_fallback_bootstrapped(fragment_state, skeleton_keeper_diagnostics)
            state = fragment_state
            state_keeper_diagnostics = fragment_state.get('state_keeper_diagnostics', {})
            state['state_keeper_diagnostics'] = state_keeper_diagnostics

        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply})
        state = merge_arbiter_state(state, arbiter)
        state = apply_thread_tracker(state, user_text=opening_prompt, narrator_reply=reply, arbiter=arbiter)
        state['continuity_hints'] = normalized_hint_entries(session_id)
        state = update_important_npcs(state, load_history(session_id), context.get('continuity_candidates', []))
        state = resolve_important_npc_continuity(state)
        save_state(session_id, state)

        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': usage,
            'narrator_retry': narrator_retry_trace,
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'opening-choice',
                'arbiter_used': bool(arbiter.get('arbiter_needed')),
                'arbiter_event_count': len(arbiter.get('results', [])),
                'active_persona': [],
                'loaded_preset': context.get('active_preset', {}).get('name', 'unknown'),
                'loaded_onstage': state.get('onstage_npcs', []),
                'model_error': model_error,
                'narrator_retry': copy.deepcopy(narrator_retry_trace),
                'state_keeper_diagnostics': copy.deepcopy(state_keeper_diagnostics) if isinstance(state_keeper_diagnostics, dict) else {},
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        trace = copy.deepcopy(turn_trace)
        trace['mode'] = 'opening-choice'
        trace['opening'] = {
            'choice': choice,
            'opening_prompt': opening_prompt,
        }
        trace['runtime'] = {
            'context': _trace_context_excerpt(context),
            'arbiter': copy.deepcopy(arbiter),
            'state_fragment_initial': copy.deepcopy(state_fragment),
            'narrator': {
                'system_prompt': _trim_trace_text(system_prompt),
                'user_prompt': _trim_trace_text(user_prompt),
                'prompt_block_stats': copy.deepcopy(prompt_block_stats(system_prompt)),
                'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                'reply': reply,
                'usage': copy.deepcopy(usage),
                'model_error': model_error,
                'retry_trace': copy.deepcopy(narrator_retry_trace),
            },
            'skeleton_keeper': {
                'diagnostics': copy.deepcopy(skeleton_keeper_diagnostics),
                'trace': copy.deepcopy(skeleton_keeper_trace),
            },
            'state_keeper': {
                'diagnostics': copy.deepcopy(state_keeper_diagnostics),
                'trace': copy.deepcopy(state_keeper_trace),
                'state_error': state_error,
            },
        }
        trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
        }
        return finalize_response(response, trace=trace)

    state = load_state(session_id)
    if state.get('opening_mode') == 'menu' and not state.get('opening_resolved'):
        choice = resolve_opening_choice(text)
        if choice is not None:
            return finalize_opening_choice(choice)

        reply = build_opening_reply(text) if is_opening_command(text) else '当前还在选择开局。请直接报数字、开局标题，或输入“随机开局”。'
        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply})
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': {'model': 'opening-menu-guard', 'input_tokens': 0, 'output_tokens': 0},
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'opening-menu',
                'arbiter_used': False,
                'arbiter_event_count': 0,
                'active_persona': [],
                'loaded_preset': 'world-sim-balanced',
                'loaded_onstage': [],
                'model_error': None,
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        trace = copy.deepcopy(turn_trace)
        trace['mode'] = 'opening-menu'
        trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
        }
        return finalize_response(response, trace=trace)

    if meta['last_turn_id'] == 0:
        choice = resolve_opening_choice(text)
        if choice is not None:
            return finalize_opening_choice(choice)

    if state.get('opening_resolved') and state.get('opening_started') and is_opening_command(text):
        reply = '当前开局已经开始。若要重新选择开局，请点击“开始新游戏”。'
        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply})
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': {'model': 'opening-guard', 'input_tokens': 0, 'output_tokens': 0},
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'opening-guard',
                'arbiter_used': False,
                'arbiter_event_count': 0,
                'active_persona': [],
                'loaded_preset': 'world-sim-balanced',
                'loaded_onstage': [],
                'model_error': None,
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        trace = copy.deepcopy(turn_trace)
        trace['mode'] = 'opening-guard'
        trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
        }
        return finalize_response(response, trace=trace)

    if meta['last_turn_id'] == 0 and is_opening_command(text):
        state = initialize_opening_state(session_id)
        reply = build_opening_reply(text)
        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply})
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': {'model': 'opening', 'input_tokens': 0, 'output_tokens': 0},
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'opening',
                'arbiter_used': False,
                'arbiter_event_count': 0,
                'active_persona': [],
                'loaded_preset': 'world-sim-balanced',
                'loaded_onstage': [],
                'model_error': None,
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        trace = copy.deepcopy(turn_trace)
        trace['mode'] = 'opening'
        trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
        }
        return finalize_response(response, trace=trace)

    context = build_runtime_context(session_id, user_text=text)
    if not state:
        state = seed_default_state(session_id)
    scene = context.get('scene_facts', {})
    turn_trace['mode'] = 'runtime'
    turn_trace['runtime'] = {
        'context': _trace_context_excerpt(context),
    }
    arbiter = run_arbiter(text, scene)
    arbiter_result = arbiter.get('results', []) if arbiter.get('arbiter_needed') else None
    state_fragment = build_state_fragment(state, scene, user_text=text, arbiter=arbiter)
    turn_trace['runtime']['arbiter'] = copy.deepcopy(arbiter)
    turn_trace['runtime']['state_fragment_initial'] = copy.deepcopy(state_fragment)
    skeleton_keeper_diagnostics = None
    skeleton_keeper_trace = None
    state_keeper_trace = None
    context = dict(context)
    context['state_fragment'] = state_fragment
    system_prompt, user_prompt = build_narrator_input(context, text, arbiter_result=arbiter_result)
    prompt_stats = prompt_block_stats(system_prompt)
    turn_trace['runtime']['narrator'] = {
        'system_prompt': _trim_trace_text(system_prompt),
        'user_prompt': _trim_trace_text(user_prompt),
        'prompt_block_stats': copy.deepcopy(prompt_stats),
        'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
    }
    reply, usage, narrator_retry_trace = _call_narrator_with_retries(system_prompt, user_prompt)
    model_error = narrator_retry_trace.get('last_error') if narrator_retry_trace.get('all_failed') else None
    fallback_used = bool(narrator_retry_trace.get('all_failed'))
    turn_trace['runtime']['narrator']['reply'] = reply
    turn_trace['runtime']['narrator']['usage'] = copy.deepcopy(usage)
    turn_trace['runtime']['narrator']['model_error'] = model_error
    turn_trace['runtime']['narrator']['retry_trace'] = copy.deepcopy(narrator_retry_trace)
    finish_reason = usage.get('finish_reason')
    completion_status = 'partial' if fallback_used or finish_reason in ('length', 'error') else 'complete'
    if completion_status == 'complete' and looks_incomplete_reply(reply):
        completion_status = 'partial'
        finish_reason = finish_reason or 'incomplete'
        usage['finish_reason'] = finish_reason
    turn_trace['runtime']['completion'] = {
        'completion_status': completion_status,
        'finish_reason': finish_reason,
    }

    if fallback_used and not reply.strip():
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': '',
            'usage': usage,
            'narrator_retry': narrator_retry_trace,
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
            'error': {'code': 'NARRATOR_UNAVAILABLE', 'message': '正文生成不完整，已重试 3 次，未提交本轮'},
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'runtime-narrator-failed',
                'arbiter_used': bool(arbiter.get('arbiter_needed')),
                'arbiter_event_count': len(arbiter.get('results', [])),
                'arbiter_analysis': arbiter.get('analysis', {}),
                'loaded_preset': context.get('active_preset', {}).get('name', 'unknown'),
                'loaded_onstage': scene.get('onstage_npcs', []),
                'model_error': model_error,
                'completion_status': completion_status,
                'finish_reason': finish_reason,
                'narrator_retry': copy.deepcopy(narrator_retry_trace),
                'prompt_block_stats': copy.deepcopy(prompt_stats),
            }
        turn_trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
            'not_committed': True,
        }
        return finalize_response(response)

    current_turn_num = meta['last_turn_id'] + 1
    is_first_turn = current_turn_num == 1
    needs_keeper_bootstrap = bool(state.get('opening_resolved')) and bool(state.get('opening_started')) and not bool(state.get('state_keeper_bootstrapped'))
    skeleton_every = 1
    if completion_status == 'complete':
        state_fragment = merge_reply_skeleton(state_fragment, reply)
        context = dict(context)
        context['state_fragment'] = state_fragment
        turn_trace['runtime']['state_fragment_reply_skeleton'] = copy.deepcopy(state_fragment)
    should_run_skeleton = completion_status == 'complete' and skeleton_keeper_enabled() and (not is_first_turn) and (not needs_keeper_bootstrap)
    if should_run_skeleton:
        try:
            skeleton_fragment, skeleton_usage, skeleton_keeper_trace = call_skeleton_keeper(state, state_fragment, reply, return_trace=True)
        except Exception as err:
            skeleton_keeper_diagnostics = {
                'provider_requested': 'llm',
                'provider_used': 'disabled-or-failed',
                'model_usage': None,
                'fallback_used': True,
                'fallback_reason': str(err),
            }
        else:
            state_fragment = merge_state_skeleton(state_fragment, skeleton_fragment)
            context = dict(context)
            context['state_fragment'] = state_fragment
            skeleton_keeper_diagnostics = {
                'provider_requested': 'llm',
                'provider_used': 'llm',
                'model_usage': skeleton_usage,
                'fallback_used': False,
                'fallback_reason': None,
                'skeleton_fragment': skeleton_fragment,
                'skeleton_every_turns': skeleton_every,
            }
    elif completion_status == 'complete' and skeleton_keeper_enabled():
        skeleton_keeper_diagnostics = {
            'provider_requested': 'llm',
            'provider_used': 'skipped',
            'model_usage': None,
            'fallback_used': False,
            'fallback_reason': None,
            'skipped_reason': 'full state_keeper bootstrap turn' if (is_first_turn or needs_keeper_bootstrap) else f'non-skeleton turn ({current_turn_num}/{skeleton_every})',
            'skeleton_every_turns': skeleton_every,
        }
    turn_trace['runtime']['skeleton_keeper'] = {
        'diagnostics': copy.deepcopy(skeleton_keeper_diagnostics),
        'trace': copy.deepcopy(skeleton_keeper_trace),
    }
    turn_trace['runtime']['state_fragment_final'] = copy.deepcopy(state_fragment)

    if completion_status == 'partial':
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': '',
            'usage': usage,
            'narrator_retry': narrator_retry_trace,
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
            'error': {'code': 'NARRATOR_INCOMPLETE', 'message': '正文生成不完整，已重试 3 次，未提交本轮'},
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'runtime-partial',
                'arbiter_used': bool(arbiter.get('arbiter_needed')),
                'arbiter_event_count': len(arbiter.get('results', [])),
                'arbiter_analysis': arbiter.get('analysis', {}),
                'loaded_preset': context.get('active_preset', {}).get('name', 'unknown'),
                'loaded_onstage': scene.get('onstage_npcs', []),
                'model_error': model_error,
                'completion_status': completion_status,
                'finish_reason': finish_reason,
                'narrator_retry': copy.deepcopy(narrator_retry_trace),
                'current_character': context.get('character_core', {}).get('name', ''),
                'current_user': context.get('player_profile_json', {}).get('name', '') or context.get('player_profile_json', {}).get('courtesyName', '') or 'user',
                'prompt_block_stats': copy.deepcopy(prompt_stats),
                'selector': copy.deepcopy(context.get('context_audit', {})) if isinstance(context.get('context_audit', {}), dict) else {},
                'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                'lorebook_text_injected': bool(context.get('lorebook_text', '')),
                'system_npc_candidate_count': len(context.get('system_npc_candidates', []) or []),
                'lorebook_npc_candidate_count': len(context.get('lorebook_npc_candidates', []) or []),
                'npc_profile_count': len(context.get('npc_profiles', []) or []),
                'event_summary_count': len(load_event_summaries(session_id).get('items', [])),
            }
        turn_trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
            'not_committed': True,
        }
        return finalize_response(response, trace=turn_trace)

    state_error = None
    state_keeper_diagnostics = None
    state_keeper_trace = {}
    cfg = load_runtime_config()
    consolidate_every = cfg.get('memory', {}).get('consolidate_every_turns', 3)
    is_consolidation_turn = consolidate_every > 0 and current_turn_num % consolidate_every == 0
    force_full_keeper_for_objects = _is_object_heavy_turn(text, reply, state, state_fragment)

    if is_first_turn or needs_keeper_bootstrap or is_consolidation_turn or force_full_keeper_for_objects:
        try:
            state, state_keeper_trace = call_state_keeper(
                session_id,
                reply,
                state_fragment=state_fragment,
                user_text=text,
                return_trace=True,
            )
            state_keeper_diagnostics = state.get('state_keeper_diagnostics', {})
            if force_full_keeper_for_objects:
                state_keeper_diagnostics['forced_full_keeper_reason'] = 'object_heavy_turn'
            if is_first_turn or needs_keeper_bootstrap:
                state_keeper_diagnostics['bootstrap_turn'] = True
            state['state_keeper_bootstrapped'] = True
        except Exception as err:
            state_error = str(err)
            fragment_state = build_state_from_fragment(state, state_fragment, session_id)
            fragment_state['state_keeper_diagnostics'] = _state_keeper_failure_diagnostics(err, state_error)
            if force_full_keeper_for_objects:
                fragment_state['state_keeper_diagnostics']['forced_full_keeper_reason'] = 'object_heavy_turn'
            fragment_state['state_keeper_bootstrapped'] = _keeper_fallback_bootstrapped(fragment_state, skeleton_keeper_diagnostics)
            state = fragment_state
            state_keeper_diagnostics = fragment_state['state_keeper_diagnostics']
    else:
        state_keeper_trace = {}
        fragment_state = build_state_from_fragment(state, state_fragment, session_id)
        provider_used = 'skeleton+fragment' if skeleton_keeper_diagnostics and not skeleton_keeper_diagnostics.get('fallback_used') else 'fragment-baseline'
        fragment_state['state_keeper_diagnostics'] = {
            'provider_requested': 'skeleton-only',
            'provider_used': provider_used,
            'model_usage': None,
            'fallback_used': False,
            'skipped_reason': f'non-consolidation turn ({current_turn_num}/{consolidate_every}), skeleton keeper provides core fields',
        }
        state = fragment_state
        state_keeper_diagnostics = fragment_state.get('state_keeper_diagnostics', {})
        state['state_keeper_diagnostics'] = state_keeper_diagnostics
        if 'state_keeper_bootstrapped' not in state:
            state['state_keeper_bootstrapped'] = bool(state.get('opening_started'))
    turn_trace['runtime']['state_keeper'] = {
        'diagnostics': copy.deepcopy(state_keeper_diagnostics),
        'trace': copy.deepcopy(state_keeper_trace),
        'state_error': state_error,
    }
    turn_trace['runtime']['state_after_keeper'] = copy.deepcopy(state)
    append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply, 'completion_status': completion_status})
    state = merge_arbiter_state(state, arbiter)
    state = apply_thread_tracker(state, user_text=text, narrator_reply=reply, arbiter=arbiter)
    state['continuity_hints'] = normalized_hint_entries(session_id)
    state = update_important_npcs(state, load_history(session_id), context.get('continuity_candidates', []))
    state = resolve_important_npc_continuity(state)
    recent_pairs = []
    history_after_append = load_history(session_id)
    current_user = None
    for item in history_after_append:
        if item.get('role') == 'user':
            current_user = item
        elif item.get('role') == 'assistant' and current_user is not None:
            recent_pairs.append((str(current_user.get('content', '') or ''), str(item.get('content', '') or '')))
            current_user = None
    recent_pairs = recent_pairs[-3:]

    state = update_actor_registry(
        state,
        narrator_reply=reply,
        turn_number=current_turn_num,
        user_text=text,
        recent_pairs=recent_pairs,
        player_name=context.get('player_profile_json', {}).get('name', '') or context.get('player_profile_json', {}).get('courtesyName', ''),
    )
    # Single authoritative turn commit after keeper, arbiter, thread/npc trackers,
    # and actor registry have all merged their bindings. update_actor_registry
    # contains its own LLM-failure fallback so it does not raise out, which lets
    # us collapse the prior intermediate save into this final write.
    save_state(session_id, state)
    summary_chunk_result = update_summary_chunks(session_id)
    event_summary_item = build_event_summary_item(
        turn_id=turn_id,
        ledger={'summary_text': state.get('main_event', ''), 'provider': 'state_keeper'},
        onstage_names=state.get('onstage_npcs', []),
        tracked_objects=state.get('tracked_objects', []),
        carryover_clues=state.get('carryover_clues', []),
    )
    if event_summary_item.get('summary'):
        append_event_summary(session_id, event_summary_item)
    summary_text = update_summary(session_id)
    persona_counts = update_persona(session_id, context.get('continuity_candidates', []))
    turn_audit = _build_turn_audit(
        context,
        turn_id=turn_id,
        prompt_stats=prompt_stats,
        force_full_keeper=force_full_keeper_for_objects,
        force_full_keeper_reason='object_heavy_turn' if force_full_keeper_for_objects else '',
        state_keeper_diagnostics=state_keeper_diagnostics if isinstance(state_keeper_diagnostics, dict) else {},
    )

    response = {
        'session_id': session_id,
        'turn_id': turn_id,
        'reply': reply,
        'usage': usage,
        'state_snapshot': build_state_snapshot(state),
        'meta': {'turn_audit': turn_audit},
        'web': web_runtime_settings(),
    }
    if debug_enabled:
        retained_threads = [
            {
                'thread_id': item.get('thread_id'),
                'label': item.get('label'),
                'status': item.get('status'),
                'cooldown_turns': item.get('cooldown_turns', 0),
            }
            for item in state.get('active_threads', []) if isinstance(item, dict) and item.get('status') == 'watch'
        ]
        retained_entities = [
            {
                'entity_id': item.get('entity_id'),
                'primary_label': item.get('primary_label'),
                'role_label': item.get('role_label'),
            }
            for item in state.get('scene_entities', []) if isinstance(item, dict) and not item.get('onstage')
        ]
        response['debug'] = {
            'scene_mode': 'runtime-loaded',
            'arbiter_used': bool(arbiter.get('arbiter_needed')),
            'arbiter_event_count': len(arbiter.get('results', [])),
            'arbiter_analysis': arbiter.get('analysis', {}),
            'active_persona': [item['name'] for item in context.get('persona', [])],
            'loaded_preset': context.get('active_preset', {}).get('name', 'unknown'),
                'loaded_onstage': scene.get('onstage_npcs', []),
                'current_character': context.get('character_core', {}).get('name', ''),
                'current_user': context.get('player_profile_json', {}).get('name', '') or context.get('player_profile_json', {}).get('courtesyName', '') or 'user',
                'state_fragment': state_fragment,
                'skeleton_keeper_diagnostics': skeleton_keeper_diagnostics,
                'model_error': model_error,
                'state_error': state_error,
                'state_keeper_diagnostics': state_keeper_diagnostics,
                'persona_counts': persona_counts,
                'arbiter_results': arbiter.get('results', []),
                'retained_threads': retained_threads,
                'retained_entities': retained_entities,
                'prompt_block_stats': copy.deepcopy(prompt_stats),
                'selector': copy.deepcopy(context.get('context_audit', {})) if isinstance(context.get('context_audit', {}), dict) else {},
                'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                'lorebook_text_injected': bool(context.get('lorebook_text', '')),
                'system_npc_candidate_count': len(context.get('system_npc_candidates', []) or []),
                'lorebook_npc_candidate_count': len(context.get('lorebook_npc_candidates', []) or []),
                'npc_profile_count': len(context.get('npc_profiles', []) or []),
            }

    meta['last_turn_id'] += 1
    _store_turn_audit(meta, turn_audit)
    if client_turn_id:
        meta['processed_client_turn_ids'][client_turn_id] = response
    save_meta(session_id, meta)
    turn_trace['post_turn'] = {
        'state': copy.deepcopy(state),
        'state_snapshot': build_state_snapshot(state),
        'summary_updated': True,
        'summary_text': summary_text,
        'summary_chunks': copy.deepcopy(summary_chunk_result),
        'persona_counts': copy.deepcopy(persona_counts),
        'event_summary_item': copy.deepcopy(event_summary_item),
    }
    return finalize_response(response)
