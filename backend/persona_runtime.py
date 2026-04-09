#!/usr/bin/env python3
from __future__ import annotations

import time


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


def infer_persona_traits(name: str, role_label: str = '待确认') -> dict:
    name = (name or '').strip()
    role_label = (role_label or '').strip()
    combined = f'{name} {role_label}'

    if '掌柜' in combined or '老板' in combined:
        return _trait_block(
            mbti='ISTJ',
            mbti_conf=0.38,
            archetype='秩序维护者',
            archetype_conf=0.44,
            decision_style=('先止损，再判断，再决定是否担责', 0.43),
            social_strategy=('先摆规矩，见对方识趣才给余地', 0.46),
            conflict_style=('先压场、再切割，最后才公开翻脸', 0.42),
            speech_rhythm=('短句，少形容，不说满', 0.48),
            stress_response=('更硬，更快，更少解释', 0.41),
        )
    if '伙计' in combined or '小二' in combined or '跑堂' in combined:
        return _trait_block(
            mbti='ESFJ',
            mbti_conf=0.34,
            archetype='热心帮手',
            archetype_conf=0.4,
            decision_style=('先看眼前活计和人情，再决定帮到哪一步', 0.39),
            social_strategy=('比掌柜更容易搭话，也更容易被使唤', 0.41),
            conflict_style=('不主动顶硬局，真急了会立刻去叫人', 0.38),
            speech_rhythm=('短到中句，偏口语', 0.43),
            stress_response=('先慌，再赶紧补位', 0.37),
        )
    if '船夫' in combined or '艄公' in combined or '掌舵' in combined or '老汉' in combined:
        return _trait_block(
            mbti='ISTP',
            mbti_conf=0.35,
            archetype='老练看路人',
            archetype_conf=0.39,
            decision_style=('先看水势、风向和当下实际情况', 0.4),
            social_strategy=('能少说就少说，必要时点一句要紧的', 0.39),
            conflict_style=('优先稳工具和位置，不为闲气起冲突', 0.38),
            speech_rhythm=('短句，平，带行路经验', 0.42),
            stress_response=('更专注手上活，不轻易乱动', 0.37),
        )
    if '师兄' in combined or '同行' in combined or '伤者' in combined:
        return _trait_block(
            mbti='ISTJ',
            mbti_conf=0.41,
            archetype='克制同行者',
            archetype_conf=0.46,
            decision_style=('先忍耐，再判断，再在必要时出手或表态', 0.42),
            social_strategy=('先保持距离，确认可信后才松口', 0.4),
            conflict_style=('受伤或受压时更偏防守与克制', 0.39),
            speech_rhythm=('短句，克制，少废话', 0.45),
            stress_response=('更沉默，更硬撑，必要时突然变得很直接', 0.4),
        )
    if '皂衣人' in combined or '追索者' in combined or '官面执行者' in combined:
        return _trait_block(
            mbti='ESTJ',
            mbti_conf=0.39,
            archetype='执行者',
            archetype_conf=0.44,
            decision_style=('先执行命令，再根据阻碍调整动作', 0.4),
            social_strategy=('压迫式推进，不以安抚为优先', 0.39),
            conflict_style=('正面施压，必要时快速升级', 0.41),
            speech_rhythm=('短句，直接，命令式', 0.44),
            stress_response=('更强硬，更少废话', 0.39),
        )
    if '少年' in combined:
        return _trait_block(
            mbti='ISFP',
            mbti_conf=0.31,
            archetype='被卷入者',
            archetype_conf=0.36,
            decision_style=('先保命，再看谁能救自己', 0.36),
            social_strategy=('本能依附眼前更强的一方', 0.35),
            conflict_style=('多逃、多躲，少正面硬顶', 0.34),
            speech_rhythm=('短句，急，容易露慌', 0.38),
            stress_response=('更惊、更乱、更依赖别人判断', 0.35),
        )
    if '公子' in combined or '苏' in combined or '黑衣' in combined or '短褐' in combined:
        return _trait_block(
            mbti='INTJ',
            mbti_conf=0.34,
            archetype='试探者',
            archetype_conf=0.39,
            decision_style=('先观察，再试探，再决定是否亮底牌', 0.38),
            social_strategy=('先测边界，再决定靠近还是抽离', 0.38),
            conflict_style=('偏好控制节奏，不急着一次摊牌', 0.36),
            speech_rhythm=('短到中句，留白较多', 0.4),
            stress_response=('更冷，更收，更不轻易表态', 0.37),
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
