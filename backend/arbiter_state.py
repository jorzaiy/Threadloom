#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy

try:
    from .state_bridge import normalize_text_list
except ImportError:
    from state_bridge import normalize_text_list


def merge_arbiter_state(state: dict, arbiter: dict | None) -> dict:
    if not arbiter or not arbiter.get('arbiter_needed'):
        return dict(state or {})

    next_state = deepcopy(state or {})
    results = arbiter.get('results', []) or []
    signals = {
        'events': [],
        'flags': {},
    }

    immediate_risks = list(next_state.get('immediate_risks', []) or [])
    carryover_clues = list(next_state.get('carryover_clues', []) or [])

    for item in results:
        event_id = item.get('event_id', 'unknown-event')
        result = item.get('result', 'unknown')
        state_updates = item.get('state_updates', {}) or {}
        signals['events'].append({
            'event_id': event_id,
            'result': result,
            'dice_needed': bool(item.get('dice_needed')),
        })
        for key, value in state_updates.items():
            signals['flags'][key] = value

        if result == 'stealth_risk_needs_resolution':
            immediate_risks.append('当前潜行或压低动静的动作存在暴露风险。')
            carryover_clues.append('潜行是否已经惊动观察者，仍需在后续回合继续确认。')
        elif result == 'knowledge_source_check_required':
            carryover_clues.append('身份识别与知情扩散必须继续检查信息来源。')
        elif result == 'propagation_requires_channel_check':
            carryover_clues.append('本轮涉及的信息扩散仍需区分私密、小范围共享与公开流通。')
        elif result == 'uncertain_contact_risk':
            immediate_risks.append('前方或附近存在观察、试探或接触风险，但尚未坐实为精准堵截。')
            carryover_clues.append('可疑观察者的知情范围与停留目的仍未确定。')
        elif result == 'search_pressure_increase_without_precise_lock':
            immediate_risks.append('外部追索或搜索压力正在上升，但尚未形成精确锁定。')

    next_state['arbiter_signals'] = signals
    next_state['immediate_risks'] = normalize_text_list(immediate_risks, limit=6)
    next_state['carryover_clues'] = normalize_text_list(carryover_clues, limit=6)
    return next_state
