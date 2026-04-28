#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy
import re

try:
    from .arbiter_state import merge_arbiter_state
    from .state_bridge import normalize_text_list
    from .state_bridge import normalize_state_dict
except ImportError:
    from arbiter_state import merge_arbiter_state
    from state_bridge import normalize_text_list
    from state_bridge import normalize_state_dict


def _dedupe_names(items, limit: int = 6) -> list[str]:
    out: list[str] = []
    for item in items or []:
        name = str(item or '').strip()
        if not name or name in out:
            continue
        out.append(name)
        if len(out) >= limit:
            break
    return out


def _goal(scene_facts: dict, prev_state: dict) -> str:
    raw = scene_facts.get('immediate_goal')
    if isinstance(raw, list) and raw:
        return str(raw[0] or '').strip() or str(prev_state.get('immediate_goal', '待确认') or '待确认')
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return str(prev_state.get('immediate_goal', '待确认') or '待确认')


def _turn_mode(analysis: dict) -> str:
    intent = analysis.get('intent_flags', {}) if isinstance(analysis.get('intent_flags', {}), dict) else {}
    if intent.get('confrontation'):
        return 'confrontation'
    if intent.get('stealth'):
        return 'stealth'
    if intent.get('observation'):
        return 'observation'
    if intent.get('path_probe'):
        return 'probe'
    if intent.get('info_spread'):
        return 'information'
    return 'general'


def _stability_hints(turn_mode: str, fragment: dict) -> list[str]:
    hints: list[str] = []
    if turn_mode in {'observation', 'stealth', 'probe', 'general'}:
        hints.append('若本轮只是观察、试探或短回应，时间、地点与主事件默认延续，不要主动改回待确认。')
        if fragment.get('onstage_npcs'):
            hints.append('若正文没有明确改变人物存在关系或场景接触关系，不要主动清空当前在场人物。')
    if turn_mode == 'confrontation':
        hints.append('若本轮存在明显对峙或冲突，优先维持当前主事件与风险线，不要无依据切换到新场景。')
    if fragment.get('scene_entities'):
        hints.append('优先沿用当前 scene_entities 与 entity_id，对同一人物不要重新发明新实体。')
    return hints[:4]


def build_state_fragment(prev_state: dict, scene_facts: dict, user_text: str = '', arbiter: dict | None = None) -> dict:
    prev = deepcopy(prev_state or {})
    scene = deepcopy(scene_facts or {})
    analysis = arbiter.get('analysis', {}) if isinstance(arbiter, dict) else {}

    base = {
        'time': str(scene.get('time', '') or prev.get('time', '待确认') or '待确认').strip(),
        'location': str(scene.get('location', '') or prev.get('location', '待确认') or '待确认').strip(),
        'main_event': str(scene.get('main_event', '') or prev.get('main_event', '待确认') or '待确认').strip(),
        'onstage_npcs': _dedupe_names(scene.get('onstage_npcs', []) or prev.get('onstage_npcs', []), limit=6),
        'relevant_npcs': _dedupe_names(scene.get('relevant_npcs', []) or prev.get('relevant_npcs', []), limit=6),
        'immediate_goal': _goal(scene, prev),
        'immediate_risks': normalize_text_list(scene.get('immediate_risks', []) or prev.get('immediate_risks', []), limit=6),
        'carryover_clues': normalize_text_list(scene.get('carryover_clues', []) or prev.get('carryover_clues', []), limit=6),
        'scene_entities': deepcopy(scene.get('scene_entities', []) or prev.get('scene_entities', [])),
        'tracked_objects': deepcopy(scene.get('tracked_objects', []) or prev.get('tracked_objects', [])),
        'possession_state': deepcopy(scene.get('possession_state', []) or prev.get('possession_state', [])),
        'object_visibility': deepcopy(scene.get('object_visibility', []) or prev.get('object_visibility', [])),
    }

    merged = merge_arbiter_state(base, arbiter) if arbiter else base
    fragment = {
        'time': merged.get('time', '待确认'),
        'location': merged.get('location', '待确认'),
        'main_event': merged.get('main_event', '待确认'),
        'onstage_npcs': merged.get('onstage_npcs', []),
        'relevant_npcs': merged.get('relevant_npcs', []),
        'immediate_goal': merged.get('immediate_goal', '待确认'),
        'immediate_risks': merged.get('immediate_risks', []),
        'carryover_clues': merged.get('carryover_clues', []),
        'scene_entities': merged.get('scene_entities', []),
        'tracked_objects': merged.get('tracked_objects', []),
        'possession_state': merged.get('possession_state', []),
        'object_visibility': merged.get('object_visibility', []),
        'turn_mode': _turn_mode(analysis),
        'arbiter_events': [
            {
                'event_id': str(item.get('event_id', 'unknown-event') or 'unknown-event'),
                'result': str(item.get('result', 'unknown') or 'unknown'),
                'dice_needed': bool(item.get('dice_needed')),
            }
            for item in (arbiter.get('results', []) or [])
            if isinstance(item, dict)
        ],
    }
    fragment['stability_hints'] = _stability_hints(fragment['turn_mode'], fragment)
    return fragment


def build_state_from_fragment(prev_state: dict, state_fragment: dict, session_id: str) -> dict:
    prev = deepcopy(prev_state or {})
    fragment = deepcopy(state_fragment or {})
    next_state = dict(prev)

    for field in ('time', 'location', 'main_event', 'immediate_goal'):
        value = str(fragment.get(field, '') or '').strip()
        if value and value != '待确认':
            next_state[field] = value

    for field in ('onstage_npcs', 'relevant_npcs', 'immediate_risks', 'carryover_clues', 'scene_entities', 'tracked_objects', 'possession_state', 'object_visibility'):
        value = fragment.get(field)
        if isinstance(value, list) and value:
            next_state[field] = deepcopy(value)

    return normalize_state_dict(next_state, prev_state=prev, session_id=session_id)


def extract_reply_skeleton(narrator_reply: str) -> dict:
    """Extract a minimal scene skeleton directly from narrator prose.

    This is a deterministic fallback for turns where the LLM skeleton/full keeper
    fails. It intentionally only trusts the explicit scene header and first
    narrative sentence, so it cannot invent state beyond the current reply.
    """
    text = str(narrator_reply or '').strip()
    if not text:
        return {}

    skeleton: dict = {}
    header_match = re.search(r'【([^】\n]{2,80})】', text)
    body = text
    if header_match:
        header = header_match.group(1).strip()
        body = (text[:header_match.start()] + text[header_match.end():]).strip()
        parts = [part.strip() for part in re.split(r'[，,、]', header) if part.strip()]
        if len(parts) >= 2:
            skeleton['time'] = parts[0]
            skeleton['location'] = parts[-1]
        elif parts:
            token = parts[0]
            if any(marker in token for marker in ('晨', '早', '午', '暮', '夜', '更', '黄昏', '黎明', '天明')):
                skeleton['time'] = token
            else:
                skeleton['location'] = token

    paragraphs = [line.strip() for line in body.splitlines() if line.strip()]
    first = ''
    for paragraph in paragraphs:
        if paragraph.startswith(('[fallback]', '#')):
            continue
        first = paragraph
        break
    if first:
        sentence_match = re.match(r'(.{8,120}?[。！？!?])', first)
        main_event = sentence_match.group(1).strip() if sentence_match else first[:100].strip()
        if main_event:
            skeleton['main_event'] = main_event
    return skeleton


def merge_reply_skeleton(state_fragment: dict, narrator_reply: str) -> dict:
    skeleton = extract_reply_skeleton(narrator_reply)
    return merge_state_skeleton(state_fragment, skeleton) if skeleton else deepcopy(state_fragment or {})


def merge_state_skeleton(state_fragment: dict, skeleton_fragment: dict) -> dict:
    fragment = deepcopy(state_fragment or {})
    skeleton = deepcopy(skeleton_fragment or {})

    for field in ('time', 'location', 'main_event', 'immediate_goal'):
        value = str(skeleton.get(field, '') or '').strip()
        if value and value != '待确认':
            fragment[field] = value

    onstage = _dedupe_names(skeleton.get('onstage_npcs', []), limit=6)
    if onstage:
        fragment['onstage_npcs'] = onstage
        scene_entities = fragment.get('scene_entities')
        if isinstance(scene_entities, list):
            onstage_names = set(onstage)
            for entity in scene_entities:
                if not isinstance(entity, dict):
                    continue
                primary = str(entity.get('primary_label', '') or '').strip()
                entity['onstage'] = bool(primary and primary in onstage_names)

    return fragment
