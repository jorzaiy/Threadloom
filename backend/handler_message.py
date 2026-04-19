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
    from .runtime_store import append_history, build_state_snapshot, load_canon, load_continuity_hints, load_history, load_meta, load_session_persona_layers, load_state, load_summary, save_meta, save_state, save_turn_trace, seed_default_state, web_runtime_settings
    from .context_builder import build_runtime_context
    from .bootstrap_session import bootstrap_session
    from .opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from .model_config import resolve_provider_model, load_runtime_config
    from .model_client import call_model
    from .model_client import looks_incomplete_reply
    from .narrator_input import build_narrator_input, prompt_block_stats
    from .paths import normalize_session_id
    from .state_fragment import build_state_fragment, build_state_from_fragment
    from .state_keeper import call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from .state_updater import update_state
    from .persona_updater import update_persona
    from .state_fragment import merge_state_skeleton
except ImportError:
    from arbiter_runtime import run_arbiter
    from arbiter_state import merge_arbiter_state
    from continuity_resolver import resolve_important_npc_continuity
    from continuity_hints import normalized_hint_entries
    from important_npc_tracker import update_important_npcs
    from thread_tracker import apply_thread_tracker
    from runtime_store import append_history, build_state_snapshot, load_canon, load_continuity_hints, load_history, load_meta, load_session_persona_layers, load_state, load_summary, save_meta, save_state, save_turn_trace, seed_default_state, web_runtime_settings
    from context_builder import build_runtime_context
    from bootstrap_session import bootstrap_session
    from opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from model_config import resolve_provider_model, load_runtime_config
    from model_client import call_model
    from model_client import looks_incomplete_reply
    from narrator_input import build_narrator_input, prompt_block_stats
    from paths import normalize_session_id
    from state_fragment import build_state_fragment, build_state_from_fragment
    from state_keeper import call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from state_updater import update_state
    from persona_updater import update_persona
    from state_fragment import merge_state_skeleton


TRACE_PROMPT_LIMIT = 4000
def _trim_trace_text(text: str, limit: int = TRACE_PROMPT_LIMIT) -> str:
    value = str(text or '')
    if len(value) <= limit:
        return value
    return value[:limit] + '\n...[truncated]'


def _trace_context_excerpt(context: dict) -> dict:
    if not isinstance(context, dict):
        return {}
    scene = context.get('scene_facts', {}) if isinstance(context.get('scene_facts', {}), dict) else {}
    preset = context.get('active_preset', {}) if isinstance(context.get('active_preset', {}), dict) else {}
    return {
        'active_preset': preset.get('name'),
        'scene_facts': copy.deepcopy(scene),
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
    next_state['scene_core'] = scene.get('scene_core') or '当前仍为 stub handler，只保证消息收发、状态快照和写回结构稳定。'
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
        context = build_runtime_context(session_id)
        system_prompt, user_prompt = build_narrator_input(context, opening_prompt, arbiter_result=None)
        model_cfg = resolve_provider_model('narrator')
        try:
            reply, usage = call_model(model_cfg, system_prompt, user_prompt)
        except Exception:
            reply = opening_prompt
            usage = {
                'model': f"{model_cfg.get('provider_name', 'unknown')}:{model_cfg.get('model', {}).get('id', 'unknown')}",
                'input_tokens': 0,
                'output_tokens': 0,
            }
        state['opening_started'] = True
        save_state(session_id, state)
        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply})
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': usage,
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
        }
        if debug_enabled:
            response['debug'] = {
                'scene_mode': 'opening-choice',
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
        trace['mode'] = 'opening-choice'
        trace['opening'] = {
            'choice': choice,
            'opening_prompt': opening_prompt,
        }
        trace['runtime'] = {
            'context': _trace_context_excerpt(context),
            'narrator': {
                'system_prompt': _trim_trace_text(system_prompt),
                'user_prompt': _trim_trace_text(user_prompt),
                'reply': reply,
                'usage': copy.deepcopy(usage),
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

    context = build_runtime_context(session_id)
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
    model_cfg = resolve_provider_model('narrator')
    model_error = None
    try:
        reply, usage = call_model(model_cfg, system_prompt, user_prompt)
    except Exception as err:
        model_error = str(err)
        reply = f"[fallback] 当前主事件：{scene.get('main_event', '待确认')} | 收到输入：{text}"
        usage = {
            'model': f"{model_cfg.get('provider_name', 'unknown')}:{model_cfg.get('model', {}).get('id', 'unknown')}",
            'input_tokens': 0,
            'output_tokens': 0,
            'finish_reason': 'error',
        }
    if not reply.strip():
        reply = f"[fallback] 当前主事件：{scene.get('main_event', '待确认')} | 收到输入：{text}"
    turn_trace['runtime']['narrator']['reply'] = reply
    turn_trace['runtime']['narrator']['usage'] = copy.deepcopy(usage)
    turn_trace['runtime']['narrator']['model_error'] = model_error
    finish_reason = usage.get('finish_reason')
    completion_status = 'partial' if finish_reason == 'length' else 'complete'
    if completion_status == 'complete' and looks_incomplete_reply(reply):
        completion_status = 'partial'
        finish_reason = finish_reason or 'incomplete'
        usage['finish_reason'] = finish_reason
    turn_trace['runtime']['completion'] = {
        'completion_status': completion_status,
        'finish_reason': finish_reason,
    }

    if completion_status == 'complete' and skeleton_keeper_enabled():
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
            }
    turn_trace['runtime']['skeleton_keeper'] = {
        'diagnostics': copy.deepcopy(skeleton_keeper_diagnostics),
        'trace': copy.deepcopy(skeleton_keeper_trace),
    }
    turn_trace['runtime']['state_fragment_final'] = copy.deepcopy(state_fragment)

    if completion_status == 'partial':
        append_turn_history(assistant_item={'ts': ts + 1, 'role': 'assistant', 'content': reply, 'completion_status': completion_status})
        response = {
            'session_id': session_id,
            'turn_id': turn_id,
            'reply': reply,
            'usage': usage,
            'state_snapshot': build_state_snapshot(state),
            'web': web_runtime_settings(),
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
                'prompt_block_stats': copy.deepcopy(prompt_stats),
                'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                'system_npc_candidate_count': len(context.get('system_npc_candidates', []) or []),
                'lorebook_npc_candidate_count': len(context.get('lorebook_npc_candidates', []) or []),
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        turn_trace['post_turn'] = {
            'state': copy.deepcopy(state),
            'state_snapshot': build_state_snapshot(state),
        }
        return finalize_response(response)

    state_error = None
    state_keeper_diagnostics = None
    state_keeper_trace = {}
    current_turn_num = meta['last_turn_id'] + 1
    cfg = load_runtime_config()
    consolidate_every = cfg.get('memory', {}).get('consolidate_every_turns', 12)
    is_consolidation_turn = consolidate_every > 0 and current_turn_num % consolidate_every == 0

    if is_consolidation_turn:
        try:
            state, state_keeper_trace = call_state_keeper(
                session_id,
                reply,
                state_fragment=state_fragment,
                user_text=text,
                return_trace=True,
            )
            state_keeper_diagnostics = state.get('state_keeper_diagnostics', {})
        except Exception as err:
            state_error = str(err)
            fragment_state = build_state_from_fragment(state, state_fragment, session_id)
            fragment_state['state_keeper_diagnostics'] = {
                'provider_requested': 'llm',
                'provider_used': 'fragment-baseline',
                'model_usage': None,
                'fallback_used': True,
                'fallback_reason': state_error,
            }
            save_state(session_id, fragment_state)
            try:
                state = update_state(session_id)
            except Exception as fallback_err:
                turn_trace['runtime']['state_keeper'] = {
                    'diagnostics': {
                        'provider_requested': 'llm',
                        'provider_used': 'fragment-baseline',
                        'model_usage': None,
                        'fallback_used': True,
                        'fallback_reason': state_error,
                    },
                    'trace': copy.deepcopy(state_keeper_trace),
                    'state_error': state_error,
                    'fallback_update_error': str(fallback_err),
                }
                turn_trace['post_turn'] = {
                    'state': copy.deepcopy(fragment_state),
                    'state_snapshot': build_state_snapshot(fragment_state),
                }
                turn_trace['failure'] = {
                    'type': type(fallback_err).__name__,
                    'message': str(fallback_err),
                    'stage': 'state_updater_fallback',
                }
                _save_turn_trace_safe(session_id, turn_id, turn_trace)
                raise
            state_keeper_diagnostics = {
                'provider_requested': 'llm',
                'provider_used': 'fragment+heuristic-fallback',
                'model_usage': None,
                'fallback_used': True,
            'fallback_reason': state_error,
        }
        state['state_keeper_diagnostics'] = state_keeper_diagnostics
    else:
        state_keeper_trace = {}
        fragment_state = build_state_from_fragment(state, state_fragment, session_id)
        fragment_state['state_keeper_diagnostics'] = {
            'provider_requested': 'fragment-only',
            'provider_used': 'fragment-baseline',
            'model_usage': None,
            'fallback_used': False,
            'skipped_reason': f'non-consolidation turn ({current_turn_num}/{consolidate_every})',
        }
        save_state(session_id, fragment_state)
        try:
            state = update_state(session_id)
        except Exception:
            state = fragment_state
        state_keeper_diagnostics = fragment_state.get('state_keeper_diagnostics', {})
        state['state_keeper_diagnostics'] = state_keeper_diagnostics
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
    save_state(session_id, state)
    persona_counts = update_persona(session_id, context.get('continuity_candidates', []))

    response = {
        'session_id': session_id,
        'turn_id': turn_id,
        'reply': reply,
        'usage': usage,
        'state_snapshot': build_state_snapshot(state),
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
                'lorebook_injection': copy.deepcopy(context.get('lorebook_injection', {})) if isinstance(context.get('lorebook_injection', {}), dict) else {},
                'system_npc_candidate_count': len(context.get('system_npc_candidates', []) or []),
                'lorebook_npc_candidate_count': len(context.get('lorebook_npc_candidates', []) or []),
            }

    meta['last_turn_id'] += 1
    if client_turn_id:
        meta['processed_client_turn_ids'][client_turn_id] = response
    save_meta(session_id, meta)
    turn_trace['post_turn'] = {
        'state': copy.deepcopy(state),
        'state_snapshot': build_state_snapshot(state),
        'summary_updated': False,
        'persona_counts': copy.deepcopy(persona_counts),
    }
    return finalize_response(response)
