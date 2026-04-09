#!/usr/bin/env python3
import time
from typing import Any

try:
    from .arbiter_runtime import run_arbiter
    from .arbiter_state import merge_arbiter_state
    from .continuity_resolver import resolve_important_npc_continuity
    from .continuity_hints import normalized_hint_entries
    from .important_npc_tracker import update_important_npcs
    from .thread_tracker import apply_thread_tracker
    from .runtime_store import append_history, build_state_snapshot, load_history, load_meta, load_state, save_meta, save_state, seed_default_state, web_runtime_settings
    from .context_builder import build_runtime_context
    from .bootstrap_session import bootstrap_session
    from .opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from .model_config import resolve_provider_model
    from .model_client import call_model
    from .narrator_input import build_narrator_input
    from .state_fragment import build_state_fragment, build_state_from_fragment
    from .state_keeper import call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from .summary_updater import update_summary
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
    from runtime_store import append_history, build_state_snapshot, load_history, load_meta, load_state, save_meta, save_state, seed_default_state, web_runtime_settings
    from context_builder import build_runtime_context
    from bootstrap_session import bootstrap_session
    from opening import build_opening_choice_reply, build_opening_reply, initialize_opening_choice_state, initialize_opening_state, is_opening_command, resolve_opening_choice
    from model_config import resolve_provider_model
    from model_client import call_model
    from narrator_input import build_narrator_input
    from state_fragment import build_state_fragment, build_state_from_fragment
    from state_keeper import call_state_keeper, call_skeleton_keeper, skeleton_keeper_enabled
    from summary_updater import update_summary
    from state_updater import update_state
    from persona_updater import update_persona
    from state_fragment import merge_state_skeleton


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
    session_id = str(payload.get('session_id', '') or '').strip()
    text = str(payload.get('text', '') or '').strip()
    client_turn_id = str(payload.get('client_turn_id', '') or '').strip()
    meta = payload.get('meta', {}) or {}

    if not session_id:
        return False, {'error': {'code': 'INVALID_INPUT', 'message': 'session_id is required'}}
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
        append_history(session_id, {'ts': ts + 1, 'role': 'assistant', 'content': reply})
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
        return response

    append_history(session_id, {'ts': ts, 'role': 'user', 'content': text})

    state = load_state(session_id)
    if state.get('opening_mode') == 'menu' and not state.get('opening_resolved'):
        choice = resolve_opening_choice(text)
        if choice is not None:
            return finalize_opening_choice(choice)

        reply = build_opening_reply(text) if is_opening_command(text) else '当前还在选择开局。请直接报数字、开局标题，或输入“随机开局”。'
        append_history(session_id, {'ts': ts + 1, 'role': 'assistant', 'content': reply})
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
        return response

    if meta['last_turn_id'] == 0:
        choice = resolve_opening_choice(text)
        if choice is not None:
            return finalize_opening_choice(choice)

    if state.get('opening_resolved') and state.get('opening_started') and is_opening_command(text):
        reply = '当前开局已经开始。若要重新选择开局，请点击“开始新游戏”。'
        append_history(session_id, {'ts': ts + 1, 'role': 'assistant', 'content': reply})
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
        return response

    if meta['last_turn_id'] == 0 and is_opening_command(text):
        state = initialize_opening_state(session_id)
        reply = build_opening_reply(text)
        append_history(session_id, {'ts': ts + 1, 'role': 'assistant', 'content': reply})
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
        return response

    context = build_runtime_context(session_id)
    if not state:
        state = seed_default_state(session_id)
    scene = context.get('scene_facts', {})
    arbiter = run_arbiter(text, scene)
    arbiter_result = arbiter.get('results', []) if arbiter.get('arbiter_needed') else None
    state_fragment = build_state_fragment(state, scene, user_text=text, arbiter=arbiter)
    skeleton_keeper_diagnostics = None
    context = dict(context)
    context['state_fragment'] = state_fragment
    system_prompt, user_prompt = build_narrator_input(context, text, arbiter_result=arbiter_result)
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
    finish_reason = usage.get('finish_reason')
    completion_status = 'partial' if finish_reason == 'length' else 'complete'
    append_history(session_id, {'ts': ts + 1, 'role': 'assistant', 'content': reply, 'completion_status': completion_status})

    if completion_status == 'complete' and skeleton_keeper_enabled():
        try:
            skeleton_fragment, skeleton_usage = call_skeleton_keeper(state, state_fragment, reply)
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

    if completion_status == 'partial':
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
            }
        meta['last_turn_id'] += 1
        if client_turn_id:
            meta['processed_client_turn_ids'][client_turn_id] = response
        save_meta(session_id, meta)
        return response

    state_error = None
    state_keeper_diagnostics = None
    try:
        state = call_state_keeper(session_id, reply, state_fragment=state_fragment)
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
        state = update_state(session_id)
        state_keeper_diagnostics = {
            'provider_requested': 'llm',
            'provider_used': 'fragment+heuristic-fallback',
            'model_usage': None,
            'fallback_used': True,
            'fallback_reason': state_error,
        }
        state['state_keeper_diagnostics'] = state_keeper_diagnostics
    state = merge_arbiter_state(state, arbiter)
    state = apply_thread_tracker(state, user_text=text, narrator_reply=reply, arbiter=arbiter)
    state['continuity_hints'] = normalized_hint_entries(session_id)
    state = update_important_npcs(state, load_history(session_id), context.get('lorebook_npc_candidates', []))
    state = resolve_important_npc_continuity(state)
    save_state(session_id, state)
    persona_counts = update_persona(session_id, context.get('lorebook_npc_candidates', []))
    update_summary(session_id)

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
        }

    meta['last_turn_id'] += 1
    if client_turn_id:
        meta['processed_client_turn_ids'][client_turn_id] = response
    save_meta(session_id, meta)
    return response
