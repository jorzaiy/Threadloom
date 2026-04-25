#!/usr/bin/env python3
from __future__ import annotations

import json
import re

try:
    from .llm_manager import call_role_llm, get_role_runtime
    from .local_model_client import parse_json_response
except ImportError:
    from llm_manager import call_role_llm, get_role_runtime
    from local_model_client import parse_json_response


OBSERVATION_MARKERS = ('看', '观察', '打量', '盯', '听', '细听', '查看', '确认', '留神', '扫了一眼')
STEALTH_MARKERS = ('不出声', '屏住', '放轻', '压低', '悄悄', '藏', '躲', '贴着', '潜行', '绕开', '避开')
CONFRONTATION_MARKERS = ('冲出去', '闯', '拦', '堵', '追上', '抢先', '扑上去', '拔刀', '动手', '出手', '迎上去')
IDENTITY_MARKERS = ('认出', '认得', '识破', '看穿', '真名', '身份', '名字', '来路', '来历', '伪装', '化名', '面具', '到底是谁')
INFO_MARKERS = ('告诉', '说出', '传开', '消息', '让他们知道', '提起', '口信', '传闻', '透露', '交代', '情报')
PATH_MARKERS = ('出口', '门口', '岸边', '窄湾', '前头', '前面', '路口', '拐角', '通道', '桥', '巷口', '舱口')
THREAT_MARKERS = ('有人', '守', '等', '埋伏', '拦', '追兵', '搜查', '盘问', '巡逻', '盯梢', '可疑', '影子', '观察者')

SCENE_PURSUIT_MARKERS = ('追索', '搜捕', '搜查', '追兵', '盘问', '巡逻', '封锁', '检查', '警戒', '通缉', '追踪')
SCENE_STEALTH_MARKERS = ('潜行', '藏匿', '藏身', '不出声', '隐蔽', '观察者', '可疑', '试探', '避开', '暴露')
SCENE_CONTACT_MARKERS = ('出口风险', '观察', '试探', '埋伏', '接触风险', '窄路', '狭路', '岸边', '路口', '通道', '桥', '前方')
SCENE_IDENTITY_MARKERS = ('身份', '真名', '名字', '面具', '伪装', '化名', '来历', '秘密', '隐情', '认知', '误认')
SCENE_INFO_MARKERS = ('消息', '传闻', '口信', '情报', '证物', '线索', '消息源', '风声', '传开', '泄露', '听说')
ROLE_AUTHORITY_MARKERS = ('守卫', '巡逻', '哨', '官', '兵', '捕', '侍卫', '护卫', '看守', '追兵', '猎人', '执法', '岗哨')


def contains_any(text: str, keywords: list[str] | tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def clean_text(value: str) -> str:
    return re.sub(r'\s+', ' ', value or '').strip()


def build_scene_signal_text(scene_facts: dict) -> str:
    parts: list[str] = []
    for key in ('location', 'main_event'):
        value = scene_facts.get(key, '')
        if isinstance(value, str) and value.strip():
            parts.append(value)
    for key in ('immediate_risks', 'carryover_clues'):
        for item in scene_facts.get(key, []) or []:
            if isinstance(item, str) and item.strip():
                parts.append(item)
    for entity in scene_facts.get('scene_entities', []) or []:
        if not isinstance(entity, dict):
            continue
        for field in ('primary_label', 'role_label', 'possible_link'):
            value = entity.get(field)
            if isinstance(value, str) and value.strip():
                parts.append(value)
        for alias in entity.get('aliases', []) or []:
            if isinstance(alias, str) and alias.strip():
                parts.append(alias)
    return ' '.join(parts)


def scene_entity_metrics(scene_facts: dict) -> dict:
    entities = [item for item in (scene_facts.get('scene_entities', []) or []) if isinstance(item, dict)]
    alias_rich_entities = 0
    authority_like_entities = 0
    for entity in entities:
        aliases = [alias for alias in (entity.get('aliases') or []) if isinstance(alias, str) and alias.strip()]
        if len(set(aliases)) >= 2:
            alias_rich_entities += 1
        role_label = str(entity.get('role_label', '') or '')
        primary_label = str(entity.get('primary_label', '') or '')
        entity_text = f'{primary_label} {role_label}'
        if contains_any(entity_text, ROLE_AUTHORITY_MARKERS):
            authority_like_entities += 1
    return {
        'entity_count': len(entities),
        'alias_rich_entities': alias_rich_entities,
        'authority_like_entities': authority_like_entities,
    }


def _heuristic_analysis(user_text: str, scene_facts: dict) -> dict:
    text = clean_text(user_text)
    risk_text = build_scene_signal_text(scene_facts)
    entity_metrics = scene_entity_metrics(scene_facts)

    intent_flags = {
        'observation': contains_any(text, OBSERVATION_MARKERS),
        'stealth': contains_any(text, STEALTH_MARKERS),
        'confrontation': contains_any(text, CONFRONTATION_MARKERS),
        'identity_probe': contains_any(text, IDENTITY_MARKERS),
        'info_spread': contains_any(text, INFO_MARKERS),
        'path_probe': contains_any(text, PATH_MARKERS),
        'contact_or_threat': contains_any(text, THREAT_MARKERS),
    }

    scene_flags = {
        'search_pressure': contains_any(risk_text, SCENE_PURSUIT_MARKERS) or entity_metrics['authority_like_entities'] > 0,
        'stealth_context': contains_any(risk_text, SCENE_STEALTH_MARKERS),
        'contact_risk': contains_any(risk_text, SCENE_CONTACT_MARKERS),
        'identity_sensitivity': contains_any(risk_text, SCENE_IDENTITY_MARKERS) or entity_metrics['alias_rich_entities'] > 0,
        'info_sensitivity': contains_any(risk_text, SCENE_INFO_MARKERS),
    }

    trigger_scores = {
        'stealth': int(intent_flags['stealth']) + int(intent_flags['observation']) + int(scene_flags['stealth_context']) + int(scene_flags['search_pressure'] or scene_flags['contact_risk']),
        'identity': int(intent_flags['identity_probe']) + int(intent_flags['observation']) + int(scene_flags['identity_sensitivity']),
        'info': int(intent_flags['info_spread']) + int(scene_flags['info_sensitivity']),
        'pursuit': int(intent_flags['confrontation']) + int(intent_flags['contact_or_threat']) + int(scene_flags['search_pressure']),
        'intercept': int(intent_flags['path_probe']) + int(intent_flags['contact_or_threat']) + int(scene_flags['contact_risk']),
    }

    return {
        'text': text,
        'entity_metrics': entity_metrics,
        'intent_flags': intent_flags,
        'scene_flags': scene_flags,
        'trigger_scores': trigger_scores,
        'provider': 'heuristic',
        'model_usage': None,
    }


TURN_ANALYZER_SYSTEM = """你是一个 RP runtime 的 turn analyzer。

你的任务不是写剧情，而是把“用户输入 + 当前场景信号”压成结构化分析结果。

只输出 JSON，不要输出解释。输出格式：
{
  "text": "清洗后的用户输入",
  "entity_metrics": {
    "entity_count": 0,
    "alias_rich_entities": 0,
    "authority_like_entities": 0
  },
  "intent_flags": {
    "observation": false,
    "stealth": false,
    "confrontation": false,
    "identity_probe": false,
    "info_spread": false,
    "path_probe": false,
    "contact_or_threat": false
  },
  "scene_flags": {
    "search_pressure": false,
    "stealth_context": false,
    "contact_risk": false,
    "identity_sensitivity": false,
    "info_sensitivity": false
  },
  "trigger_scores": {
    "stealth": 0,
    "identity": 0,
    "info": 0,
    "pursuit": 0,
    "intercept": 0
  }
}

要求：
- 用泛用 RP 运行态视角判断，不依赖某张角色卡的专属名词。
- 分数应反映“是否值得把这轮送进 arbiter”。
- 不要输出未定义字段。
- 不确定时也必须保留字段，并显式给出 `false` 或 `0`，不要省略键。
"""


def _coerce_bool_map(payload: dict, key: str, fields: tuple[str, ...]) -> dict:
    source = payload.get(key, {}) if isinstance(payload.get(key, {}), dict) else {}
    return {field: bool(source.get(field, False)) for field in fields}


def _coerce_int_map(payload: dict, key: str, fields: tuple[str, ...]) -> dict:
    source = payload.get(key, {}) if isinstance(payload.get(key, {}), dict) else {}
    out = {}
    for field in fields:
        value = source.get(field, 0)
        try:
            out[field] = int(value)
        except Exception:
            out[field] = 0
    return out


def _coerce_entity_metrics(payload: dict, scene_facts: dict) -> dict:
    source = payload.get('entity_metrics', {}) if isinstance(payload.get('entity_metrics', {}), dict) else {}
    fallback = scene_entity_metrics(scene_facts)
    out = {}
    for field in ('entity_count', 'alias_rich_entities', 'authority_like_entities'):
        value = source.get(field, fallback[field])
        try:
            out[field] = int(value)
        except Exception:
            out[field] = fallback[field]
    return out


def _normalize_analysis_payload(payload: dict, user_text: str, scene_facts: dict, *, provider: str, usage: dict | None) -> dict:
    text = clean_text(payload.get('text') if isinstance(payload.get('text'), str) else user_text)
    return {
        'text': text,
        'entity_metrics': _coerce_entity_metrics(payload, scene_facts),
        'intent_flags': _coerce_bool_map(payload, 'intent_flags', ('observation', 'stealth', 'confrontation', 'identity_probe', 'info_spread', 'path_probe', 'contact_or_threat')),
        'scene_flags': _coerce_bool_map(payload, 'scene_flags', ('search_pressure', 'stealth_context', 'contact_risk', 'identity_sensitivity', 'info_sensitivity')),
        'trigger_scores': _coerce_int_map(payload, 'trigger_scores', ('stealth', 'identity', 'info', 'pursuit', 'intercept')),
        'provider': provider,
        'model_usage': usage,
    }


def validate_analysis_payload(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise ValueError('turn-analysis payload must be an object')

    if 'intent_flags' not in payload or not isinstance(payload.get('intent_flags'), dict):
        raise ValueError('turn-analysis payload missing intent_flags object')
    if 'scene_flags' not in payload or not isinstance(payload.get('scene_flags'), dict):
        raise ValueError('turn-analysis payload missing scene_flags object')
    if 'trigger_scores' not in payload or not isinstance(payload.get('trigger_scores'), dict):
        raise ValueError('turn-analysis payload missing trigger_scores object')

    required_intent = ('observation', 'stealth', 'confrontation', 'identity_probe', 'info_spread', 'path_probe', 'contact_or_threat')
    required_scene = ('search_pressure', 'stealth_context', 'contact_risk', 'identity_sensitivity', 'info_sensitivity')
    required_scores = ('stealth', 'identity', 'info', 'pursuit', 'intercept')

    for field in required_intent:
        if field not in payload['intent_flags']:
            raise ValueError(f'turn-analysis payload missing intent flag: {field}')
    for field in required_scene:
        if field not in payload['scene_flags']:
            raise ValueError(f'turn-analysis payload missing scene flag: {field}')
    for field in required_scores:
        if field not in payload['trigger_scores']:
            raise ValueError(f'turn-analysis payload missing trigger score: {field}')

    if 'entity_metrics' in payload and not isinstance(payload.get('entity_metrics'), dict):
        raise ValueError('turn-analysis entity_metrics must be an object')


def _llm_analysis(user_text: str, scene_facts: dict) -> dict:
    heuristic = _heuristic_analysis(user_text, scene_facts)
    user_prompt = json.dumps({
        'user_input': clean_text(user_text),
        'scene_facts': {
            'time': scene_facts.get('time', '待确认'),
            'location': scene_facts.get('location', '待确认'),
            'main_event': scene_facts.get('main_event', '待确认'),
            'immediate_risks': scene_facts.get('immediate_risks', []),
            'carryover_clues': scene_facts.get('carryover_clues', []),
            'scene_entities': scene_facts.get('scene_entities', []),
        },
        'heuristic_hint': {
            'entity_metrics': heuristic['entity_metrics'],
            'intent_flags': heuristic['intent_flags'],
            'scene_flags': heuristic['scene_flags'],
            'trigger_scores': heuristic['trigger_scores'],
        },
    }, ensure_ascii=False, indent=2)
    reply, usage = call_role_llm('turn_analyzer', TURN_ANALYZER_SYSTEM, user_prompt)
    payload = parse_json_response(reply)
    validate_analysis_payload(payload)
    return _normalize_analysis_payload(payload, user_text, scene_facts, provider='llm', usage=usage)


def _with_diagnostics(result: dict, *, provider_requested: str, fallback_used: bool, fallback_reason: str | None = None) -> dict:
    output = dict(result)
    output['diagnostics'] = {
        'provider_requested': provider_requested,
        'provider_used': output.get('provider', provider_requested),
        'fallback_used': fallback_used,
        'fallback_reason': fallback_reason,
    }
    return output


def analyze_turn(user_text: str, scene_facts: dict) -> dict:
    runtime = get_role_runtime('turn_analyzer')
    provider = runtime['provider']
    if provider == 'heuristic':
        return _with_diagnostics(_heuristic_analysis(user_text, scene_facts), provider_requested='heuristic', fallback_used=False)
    if provider == 'llm':
        try:
            return _with_diagnostics(_llm_analysis(user_text, scene_facts), provider_requested='llm', fallback_used=False)
        except Exception as err:
            return _with_diagnostics(
                _heuristic_analysis(user_text, scene_facts),
                provider_requested='llm',
                fallback_used=True,
                fallback_reason=str(err),
            )
    return _with_diagnostics(
        _heuristic_analysis(user_text, scene_facts),
        provider_requested=provider,
        fallback_used=True,
        fallback_reason=f'unknown provider: {provider}',
    )
