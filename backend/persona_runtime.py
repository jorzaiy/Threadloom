#!/usr/bin/env python3
from __future__ import annotations

import time

try:
    from .card_hints import get_persona_archetypes
except ImportError:
    from card_hints import get_persona_archetypes


def merge_identity(previous: dict | None, role_label: str = '待确认', *, faction: str | None = None, base_region: str | None = None) -> dict:
    previous = previous or {}
    prev_identity = previous.get('identity', {}) if isinstance(previous, dict) else {}
    return {
        'role_label': role_label or prev_identity.get('role_label', '待确认'),
        'faction': faction or prev_identity.get('faction', '待确认'),
        'base_region': base_region or prev_identity.get('base_region', '待确认'),
    }


def _trait_block(
    *,
    mbti: str,
    mbti_conf: float,
    archetype: str,
    archetype_conf: float,
    decision_style: tuple[str, float],
    social_strategy: tuple[str, float],
    conflict_style: tuple[str, float],
    speech_rhythm: tuple[str, float],
    stress_response: tuple[str, float],
) -> dict:
    return {
        'mbti': {'value': mbti, 'confidence': mbti_conf},
        'archetype': {'value': archetype, 'confidence': archetype_conf},
        'runtime_hooks': {
            'decision_style': {'value': decision_style[0], 'confidence': decision_style[1]},
            'social_strategy': {'value': social_strategy[0], 'confidence': social_strategy[1]},
            'conflict_style': {'value': conflict_style[0], 'confidence': conflict_style[1]},
            'speech_rhythm': {'value': speech_rhythm[0], 'confidence': speech_rhythm[1]},
            'stress_response': {'value': stress_response[0], 'confidence': stress_response[1]},
        },
    }


def _match_archetype(name: str, role_label: str) -> dict | None:
    """Match name/role against card-defined persona archetypes."""
    archetypes = get_persona_archetypes()
    combined = f'{name} {role_label}'
    for entry in archetypes:
        tokens = entry.get('match_tokens', [])
        if not isinstance(tokens, list):
            continue
        if any(token in combined for token in tokens):
            return entry
    return None


def infer_persona_traits(name: str, role_label: str = '待确认') -> dict:
    name = (name or '').strip()
    role_label = (role_label or '').strip()

    match = _match_archetype(name, role_label)
    if match:
        def _hook(key: str) -> tuple[str, float]:
            value = match.get(key, '待确认')
            if isinstance(value, list) and len(value) >= 2:
                return (str(value[0]), float(value[1]))
            return (str(value), 0.35)

        return _trait_block(
            mbti=str(match.get('mbti', 'unknown')),
            mbti_conf=float(match.get('mbti_conf', 0.35)),
            archetype=str(match.get('archetype', '待确认')),
            archetype_conf=float(match.get('archetype_conf', 0.35)),
            decision_style=_hook('decision_style'),
            social_strategy=_hook('social_strategy'),
            conflict_style=_hook('conflict_style'),
            speech_rhythm=_hook('speech_rhythm'),
            stress_response=_hook('stress_response'),
        )

    combined = f'{name} {role_label}'.strip()
    if any(token in combined for token in ('掌柜', '店家')):
        return _trait_block(
            mbti='ISTJ',
            mbti_conf=0.28,
            archetype='守序经营者',
            archetype_conf=0.3,
            decision_style=('先保局面和规矩，再决定站队', 0.28),
            social_strategy=('表面周旋，暗中留余地', 0.27),
            conflict_style=('尽量不正面对撞，但会保护自己的地盘', 0.27),
            speech_rhythm=('话少、稳、留三分余地', 0.3),
            stress_response=('先压住场面，再找退路', 0.26),
        )
    if any(token in combined for token in ('小二', '跑堂')):
        return _trait_block(
            mbti='ISFJ',
            mbti_conf=0.24,
            archetype='谨慎服役者',
            archetype_conf=0.28,
            decision_style=('先看强势者脸色，再求自保', 0.25),
            social_strategy=('顺着局势说话，尽量少惹事', 0.25),
            conflict_style=('能躲就躲，避免卷进正面冲突', 0.24),
            speech_rhythm=('快、小声、带点试探', 0.27),
            stress_response=('慌但会立刻找最安全的站位', 0.25),
        )
    if any(token in combined for token in ('皂衣人', '镇北司', '官差', '官面')):
        return _trait_block(
            mbti='ESTJ',
            mbti_conf=0.32,
            archetype='执行者',
            archetype_conf=0.36,
            decision_style=('先执行命令，再根据阻碍调整动作', 0.32),
            social_strategy=('压迫式推进，但仍会顾忌规矩与观感成本', 0.31),
            conflict_style=('正面施压，必要时快速升级', 0.33),
            speech_rhythm=('短句，直接，命令式', 0.35),
            stress_response=('更强硬，但会优先维护目标与职责一致性', 0.3),
        )

    return _trait_block(
        mbti='unknown',
        mbti_conf=0.0,
        archetype='待确认',
        archetype_conf=0.0,
        decision_style=('待确认', 0.0),
        social_strategy=('待确认', 0.0),
        conflict_style=('待确认', 0.0),
        speech_rhythm=('待确认', 0.0),
        stress_response=('待确认', 0.0),
    )


def build_persona_seed(
    display_name: str,
    role_label: str = '待确认',
    *,
    layer: str = 'scene',
    previous: dict | None = None,
    appearance_turns: int | None = None,
    dormant_turns: int = 0,
    onstage: bool = False,
    relevant: bool = False,
    identity_overrides: dict | None = None,
    scene_signature: str | None = None,
    reason_suffix: str | None = None,
) -> dict:
    previous = previous or {}
    traits = infer_persona_traits(display_name, role_label)
    prev_importance = previous.get('importance', {})
    prev_identity = previous.get('identity', {})
    prev_turns = int(prev_importance.get('appearance_turns', 0) or 0)
    turns = max(appearance_turns if appearance_turns is not None else prev_turns, 1)

    if layer == 'longterm':
        level = 'high'
        score = max(5, turns + 2)
        tier = 'medium'
    elif layer == 'scene':
        level = 'medium'
        score = max(3, turns + 1)
        tier = 'low'
    else:
        level = 'low'
        score = max(2, turns)
        tier = 'low'

    reasons = []
    if onstage:
        reasons.append('当前在场，下一轮直接可能继续互动。')
    elif relevant:
        reasons.append('当前虽未在场，但仍直接影响后续局势。')
    else:
        reasons.append('当前已离场，先保留人格骨架以备后续回流。')
    if turns >= 3:
        reasons.append(f'已累计 {turns} 轮被持续识别，适合保留稳定人格钩子。')
    if dormant_turns >= 1 and not onstage:
        reasons.append(f'已连续 {dormant_turns} 轮未在场，当前进入后台保留。')
    if reason_suffix:
        reasons.append(reason_suffix)

    now_ms = int(time.time() * 1000)
    identity = merge_identity(previous, role_label)
    if identity_overrides:
        for key, value in identity_overrides.items():
            if value:
                identity[key] = value
    return {
        'npc_id': display_name,
        'display_name': display_name,
        'seed_layer': layer,
        'seed_confidence_tier': tier,
        'name_unlock_status': 'unlocked',
        'identity': identity,
        'importance': {
            'level': level,
            'observation_window_turns': 12,
            'appearance_turns': turns,
            'score': score,
            'reason': reasons,
            'dormant_turns': dormant_turns,
        },
        'persona_seed': traits,
        'uncertainties': previous.get('uncertainties', [
            '当前 seed 为运行时骨架，不应把单轮情绪直接固化为长期人格。',
            '若后续多个回合表现稳定变化，应重评而不是沿用旧钩子。',
        ]),
        'source_window': {
            'history_range': 'session-local',
            'last_evaluated_at': now_ms,
            'scene_signature': scene_signature or previous.get('source_window', {}).get('scene_signature', ''),
        },
    }
