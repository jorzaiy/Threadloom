#!/usr/bin/env python3
from __future__ import annotations

try:
    from .turn_analyzer import analyze_turn, contains_any
except ImportError:
    from turn_analyzer import analyze_turn, contains_any


RULES_SUMMARY = [
    '没有信息来源，不得精准知晓',
    '没有移动依据，不得无解释抢先堵截',
    '没有公开传播路径，旧信息不得自动外溢到新 NPC',
    '合理但不确定的事，才能进入进一步裁定或掷骰',
]


def build_candidate_events(user_text: str, scene_facts: dict) -> list[dict]:
    analysis = analyze_turn(user_text, scene_facts)
    text = analysis['text']
    if not text:
        return []

    intent = analysis['intent_flags']
    scene = analysis['scene_flags']
    scores = analysis['trigger_scores']
    events: list[dict] = []

    world_time = scene_facts.get('time', '未明')
    location = scene_facts.get('location', '待确认')
    scene_core = scene_facts.get('scene_core', '待确认')
    onstage = scene_facts.get('onstage_npcs', []) or []
    risks = scene_facts.get('immediate_risks', []) or []
    clues = scene_facts.get('carryover_clues', []) or []

    def event(event_id: str, event_type: str, priority: str, claim: str, state_slice: dict) -> dict:
        return {
            'event_id': event_id,
            'event_type': event_type,
            'priority': priority,
            'actors': {
                'initiator': ['用户主角'],
                'target': onstage or ['当前场景'],
            },
            'event_claim': claim,
            'state_slice': state_slice,
            'rules_summary': RULES_SUMMARY,
        }

    if scores['stealth'] >= 3 and (intent['stealth'] or intent['observation']):
        events.append(event(
            'event-stealth-001',
            'stealth_exposure_risk',
            'medium',
            '当前动作带有压低存在感、降低动静或潜行观察特征，存在暴露风险。',
            {
                'world_time': world_time,
                'location': location,
                'scene_core': scene_core,
                'known_risks': risks,
                'carryover_clues': clues,
                'stealth_context': '用户试图降低声响、存在感或被观察概率。',
            },
        ))

    if scores['identity'] >= 3 and (intent['identity_probe'] or contains_any(text, ('谁', '来路', '身份', '名字', '来历', '真名'))):
        events.append(event(
            'event-identity-001',
            'identity_or_knowledge_leak',
            'high',
            '当前动作可能触发身份识别、知情范围扩大或认知边界突破。',
            {
                'world_time': world_time,
                'location': location,
                'scene_core': scene_core,
                'known_risks': risks,
                'knowledge_boundary': '需要检查是否存在合理知情来源。',
            },
        ))

    if scores['info'] >= 2 and intent['info_spread']:
        events.append(event(
            'event-info-001',
            'knowledge_propagation',
            'medium',
            '当前动作可能触发信息扩散、怀疑升级或局部知情外溢。',
            {
                'world_time': world_time,
                'location': location,
                'scene_core': scene_core,
                'knowledge_boundary': '需区分独知、小范围共享与公开事实。',
                'known_risks': risks,
            },
        ))

    if scores['pursuit'] >= 3 and (intent['confrontation'] or contains_any(text, ('上前', '追', '拦', '截', '逼近'))):
        events.append(event(
            'event-pursuit-001',
            'pursuit_or_search_pressure',
            'high',
            '当前动作可能立即推动追索、对峙或搜索压力升级。',
            {
                'world_time': world_time,
                'location': location,
                'scene_core': scene_core,
                'known_risks': risks,
                'terrain': location,
            },
        ))

    if scores['intercept'] >= 3 and intent['path_probe'] and (intent['contact_or_threat'] or intent['observation'] or scene['contact_risk']):
        events.append(event(
            'event-intercept-001',
            'intercept_attempt',
            'high',
            '当前动作正在确认出口、岸边或狭窄路径是否存在观察、停留或拦截风险。',
            {
                'world_time': world_time,
                'location': location,
                'scene_core': scene_core,
                'known_risks': risks,
                'known_clues': clues,
                'terrain': location,
            },
        ))

    return events


def result_for_event(item: dict) -> dict:
    event_type = item.get('event_type', 'unknown')
    event_id = item.get('event_id', 'unknown-event')

    if event_type == 'intercept_attempt':
        return {
            'event_id': event_id,
            'allowed': True,
            'result': 'uncertain_contact_risk',
            'reason': [
                '当前只足以支持存在观察、试探或等待风险。',
                '若无额外信息来源，不应直接写成对方已精准堵截成功。',
            ],
            'permitted_outcomes': [
                '出口、岸边或窄路附近存在试探、停留或观察风险。',
                '对方可能起疑，但尚未锁定全部信息。',
            ],
            'forbidden_outcomes': [
                '对方无依据地提前知道主角全部动向。',
                '对方无成本、无路径解释地精准堵在前方。',
            ],
            'state_updates': {
                'search_pressure': 'elevated',
                'contact_risk': 'uncertain',
            },
            'dice_needed': False,
        }

    if event_type == 'pursuit_or_search_pressure':
        return {
            'event_id': event_id,
            'allowed': True,
            'result': 'search_pressure_increase_without_precise_lock',
            'reason': [
                '场景允许搜索、盘查或对峙压力上升。',
                '但没有新线索时，不应直接跳成敌方已精准掌握主角位置。',
            ],
            'permitted_outcomes': [
                '风险提升。',
                '搜索范围收紧。',
                '局势朝更高压方向移动。',
            ],
            'forbidden_outcomes': [
                '追索方无依据瞬间锁定主角精确位置。',
                '没有过程就直接形成闭合包围。',
            ],
            'state_updates': {
                'search_pressure': 'high',
                'target_exact_position_known': False,
            },
            'dice_needed': False,
        }

    if event_type == 'identity_or_knowledge_leak':
        return {
            'event_id': event_id,
            'allowed': True,
            'result': 'knowledge_source_check_required',
            'reason': [
                '身份识别和真名解锁必须依赖信息来源。',
                '没有来源时，只能写成怀疑、试探或误判。',
            ],
            'permitted_outcomes': [
                '出现怀疑。',
                '出现试探。',
                '在来源充足时触发身份或真名解锁。',
            ],
            'forbidden_outcomes': [
                '新角色无来源直接看穿私密身份。',
                '角色无依据直接掌握全部隐情。',
            ],
            'state_updates': {
                'knowledge_boundary_review': 'required',
            },
            'dice_needed': False,
        }

    if event_type == 'knowledge_propagation':
        return {
            'event_id': event_id,
            'allowed': True,
            'result': 'propagation_requires_channel_check',
            'reason': [
                '信息扩散必须经过传播路径。',
                '可写传闻、小范围共享或怀疑升级，但不能直接全场皆知。',
            ],
            'permitted_outcomes': [
                '形成传闻。',
                '小范围共享。',
                '局部怀疑升级。',
            ],
            'forbidden_outcomes': [
                '私密信息自动变成公开事实。',
                '新登场人物自动掌握旧私密内容。',
            ],
            'state_updates': {
                'knowledge_boundary_review': 'required',
                'public_fact_auto_expand': False,
            },
            'dice_needed': False,
        }

    if event_type == 'stealth_exposure_risk':
        return {
            'event_id': event_id,
            'allowed': True,
            'result': 'stealth_risk_needs_resolution',
            'reason': [
                '当前动作允许存在暴露风险。',
                '但在没有触发细节前，不能直接写成已经彻底暴露。',
            ],
            'permitted_outcomes': [
                '动静增大带来风险。',
                '观察者起疑。',
                '后续可继续进入更细的裁定。',
            ],
            'forbidden_outcomes': [
                '没有过程就直接暴露全部行踪。',
            ],
            'state_updates': {
                'stealth_risk': 'elevated',
            },
            'dice_needed': True,
        }

    return {
        'event_id': event_id,
        'allowed': True,
        'result': 'manual_review_required',
        'reason': ['当前事件类型没有专门裁定模板，需要后续进一步扩展。'],
        'permitted_outcomes': [],
        'forbidden_outcomes': [],
        'state_updates': {},
        'dice_needed': False,
    }


def run_arbiter(user_text: str, scene_facts: dict) -> dict:
    analysis = analyze_turn(user_text, scene_facts)
    events = build_candidate_events(user_text, scene_facts)
    results = [result_for_event(item) for item in events]
    return {
        'arbiter_needed': bool(events),
        'analysis': analysis,
        'candidate_events': events,
        'results': results,
    }
