#!/usr/bin/env python3
from __future__ import annotations

import json
import re

try:
    from .llm_manager import call_role_llm
except ImportError:
    from llm_manager import call_role_llm


MID_CONTEXT_SYSTEM = """你是 RP 中程场景摘要器。

你只处理第 4 到 13 轮之间的中程窗口，不处理最近 3 轮，也不处理很久以前的记忆。

目标：
- 从中程窗口里提取“跨多轮仍然持续影响当前判断”的内容
- 不要复读单轮小动作
- 不要复述完整原文
- 不要把现有 state 摘要字段原样抄回来

只输出 JSON 对象，字段只允许：
- stable_entities: [{name, status}]
- ongoing_events: [str]
- tracked_objects: [{label, kind}]
- open_loops: [str]
- history_digest: [{user, assistant}]

规则：
1. 只保留跨两轮以上仍在持续的内容。
2. 不要把短暂动作、气氛描写、一次性小细节当成 ongoing event。
3. 不要把抽象词、地点词、势力词误当成 stable entity。
4. tracked_objects 只保留中程窗口里持续被提及、且仍然 relevant 的物件。
5. history_digest 只保留 2 到 3 对最能代表中程演化的 user/assistant 对，不要原文长抄。
6. `ongoing_events` 与 `open_loops` 必须写成结构化摘要句，不要复述某一轮 assistant prose。
7. 若某条内容仍然像“原文片段”或长叙事句，应继续压缩到更抽象的状态描述。
"""


def _turn_pairs(items: list[dict]) -> list[tuple[dict, dict]]:
    pairs: list[tuple[dict, dict]] = []
    current_user = None
    for item in items or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        if role == 'user':
            current_user = item
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, item))
            current_user = None
    return pairs


def _short(text: str, limit: int = 120) -> str:
    value = ' '.join(str(text or '').split()).strip()
    if len(value) <= limit:
        return value
    return value[: limit - 3] + '...'


def _dedupe(items, limit: int = 6) -> list[str]:
    out: list[str] = []
    for item in items or []:
        text = str(item or '').strip()
        if not text or text in out:
            continue
        out.append(text)
        if len(out) >= limit:
            break
    return out


def _heuristic_digest(mid_pairs: list[tuple[dict, dict]], hard_anchors: dict, from_turn: str, to_turn: str) -> dict:
    hard = hard_anchors if isinstance(hard_anchors, dict) else {}
    combined = '\n'.join(
        ' '.join([
            str(user_item.get('content', '') or ''),
            str(assistant_item.get('content', '') or ''),
        ])
        for user_item, assistant_item in mid_pairs
    )

    # 通用实体提取：从锚点中查找在中程窗口出现的人物
    entities = []
    for name in _dedupe(list(hard.get('onstage_npcs', []) or []) + list(hard.get('relevant_npcs', []) or []), limit=8):
        if name and name in combined:
            entities.append({'name': name, 'status': '跨中程窗口持续出现'})

    # 通用事件提取：评分式
    events = _score_events(mid_pairs)

    # 通用未决点提取：检测疑问/悬念模式
    loops = _score_open_loops(mid_pairs)

    return {
        'window': {
            'pair_count': len(mid_pairs),
            'from_turn': from_turn,
            'to_turn': to_turn,
        },
        'time_anchor': str(hard.get('time', '') or '').strip(),
        'location_anchor': str(hard.get('location', '') or '').strip(),
        'stable_entities': entities[:5],
        'ongoing_events': _dedupe(events, limit=4),
        'tracked_objects': [
            {
                'label': str(item.get('label', '') or '').strip(),
                'kind': str(item.get('kind', '') or 'item').strip() or 'item',
            }
            for item in (hard.get('tracked_objects', []) or [])[:3]
            if isinstance(item, dict) and item.get('label') and str(item.get('label', '') or '').strip() not in {'包', '铜板'}
        ],
        'open_loops': _dedupe(loops, limit=4),
        'history_digest': [
            {
                'user': _short(user_item.get('content', ''), limit=80),
                'assistant': _short(assistant_item.get('content', ''), limit=120),
            }
            for user_item, assistant_item in mid_pairs[-3:]
        ],
    }


def _score_events(mid_pairs: list[tuple[dict, dict]]) -> list[str]:
    """通用评分式事件提取：扫描跨多轮持续出现的动态。"""
    turn_phrases: list[set[str]] = []
    for user_item, assistant_item in mid_pairs:
        text = ' '.join([
            str(user_item.get('content', '') or ''),
            str(assistant_item.get('content', '') or ''),
        ])
        phrases = set(re.findall(r'[\u4e00-\u9fff]{2,6}', text))
        turn_phrases.append(phrases)

    if not turn_phrases:
        return []
    phrase_counts: dict[str, int] = {}
    for phrases in turn_phrases:
        for phrase in phrases:
            phrase_counts[phrase] = phrase_counts.get(phrase, 0) + 1

    threshold = max(2, len(turn_phrases) * 0.4)
    persistent = sorted(
        [(count, phrase) for phrase, count in phrase_counts.items() if count >= threshold],
        key=lambda x: x[0], reverse=True
    )

    events = []
    action_tokens = {'搜查', '盘问', '追踪', '调查', '审查', '逃离', '守卫', '战斗',
                     '谈判', '试探', '隐瞒', '欺骗', '威胁', '观察', '等待', '受伤',
                     '对峙', '商议', '密谈', '交易', '潜入', '暴露', '争吵', '合作'}
    for _count, phrase in persistent[:10]:
        if phrase in action_tokens or any(t in phrase for t in action_tokens):
            events.append(f'与"{phrase}"相关的局势仍在持续')
        if len(events) >= 4:
            break

    if not events and persistent:
        top = [p for _, p in persistent[:3]]
        events.append(f'围绕{"、".join(top)}的局势仍在持续演化')

    return events


def _score_open_loops(mid_pairs: list[tuple[dict, dict]]) -> list[str]:
    """通用评分式未决点提取：检测悬念和未解决问题。"""
    loops = []
    suspense_patterns = [
        (r'(谁|什么|为什么|怎么|哪里|何时).*[？?]', '存在未解的疑问'),
        (r'(身份|来历|目的|真相|秘密|阴谋)', '相关问题仍未完全揭示'),
        (r'(暗示|似乎|可能|或许|好像)', '存在暗示但尚未证实的信息'),
        (r'(承诺|约定|答应|保证)', '存在尚未兑现的承诺'),
    ]
    all_text = '\n'.join(
        str(assistant_item.get('content', '') or '')
        for _, assistant_item in mid_pairs
    )
    for pattern, description in suspense_patterns:
        matches = re.findall(pattern, all_text)
        if len(matches) >= 2:
            keyword = matches[0] if isinstance(matches[0], str) else matches[0]
            loops.append(f'与"{keyword}"{description}')
    return loops



def _build_user_prompt(mid_pairs: list[tuple[dict, dict]], hard_anchors: dict, from_turn: str, to_turn: str) -> str:
    history_rows = [
        {
            'user': str(user_item.get('content', '') or ''),
            'assistant': str(assistant_item.get('content', '') or ''),
        }
        for user_item, assistant_item in mid_pairs
    ]
    payload = {
        'window': {
            'from_turn': from_turn,
            'to_turn': to_turn,
            'pair_count': len(mid_pairs),
        },
        'hard_anchors': hard_anchors,
        'history_pairs': history_rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _normalize_digest(payload: dict, from_turn: str, to_turn: str, pair_count: int) -> dict:
    if not isinstance(payload, dict):
        return {}

    def _norm_entities(items) -> list[dict]:
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            name = str(item.get('name', '') or '').strip()
            if not name:
                continue
            out.append({
                'name': name,
                'status': str(item.get('status', '') or '持续出现').strip() or '持续出现',
            })
        return out[:5]

    def _looks_like_prose(text: str) -> bool:
        value = str(text or '').strip()
        if not value:
            return False
        if len(value) > 80:
            return True
        prose_markers = ('她', '他', '忽然', '随后', '立刻', '这时', '雨', '灯', '门', '窗')
        return any(token in value for token in prose_markers)

    def _norm_strings(items, limit: int) -> list[str]:
        cleaned = []
        for item in items if isinstance(items, list) else []:
            text = str(item or '').strip()
            if not text:
                continue
            if _looks_like_prose(text):
                continue
            if text not in cleaned:
                cleaned.append(text)
            if len(cleaned) >= limit:
                break
        return cleaned

    def _norm_objects(items) -> list[dict]:
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            label = str(item.get('label', '') or '').strip()
            if not label:
                continue
            out.append({
                'label': label,
                'kind': str(item.get('kind', '') or 'item').strip() or 'item',
            })
        return out[:4]

    def _norm_history(items) -> list[dict]:
        out = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            user = _short(item.get('user', ''), limit=80)
            assistant = _short(item.get('assistant', ''), limit=100)
            if not user and not assistant:
                continue
            out.append({'user': user, 'assistant': assistant})
        return out[:3]

    return {
        'window': {
            'pair_count': pair_count,
            'from_turn': from_turn,
            'to_turn': to_turn,
        },
        'time_anchor': str(payload.get('time_anchor', '') or '').strip(),
        'location_anchor': str(payload.get('location_anchor', '') or '').strip(),
        'stable_entities': _norm_entities(payload.get('stable_entities', [])),
        'ongoing_events': _norm_strings(payload.get('ongoing_events', []), limit=4),
        'tracked_objects': _norm_objects(payload.get('tracked_objects', [])),
        'open_loops': _norm_strings(payload.get('open_loops', []), limit=5),
        'history_digest': _norm_history(payload.get('history_digest', [])),
    }


def build_mid_window_digest(
    *,
    history: list[dict],
    hard_anchors: dict,
    max_pairs: int = 10,
) -> dict:
    pairs = _turn_pairs(history)
    if len(pairs) <= 3:
        return {}

    mid_pairs = pairs[-13:-3][-max_pairs:]
    if not mid_pairs:
        return {}

    from_turn = f"turn-{max(1, len(pairs) - len(mid_pairs) - 2):04d}"
    to_turn = f"turn-{max(1, len(pairs) - 3):04d}"

    user_prompt = _build_user_prompt(mid_pairs, hard_anchors, from_turn, to_turn)
    try:
        reply, _usage = call_role_llm('state_keeper_candidate', MID_CONTEXT_SYSTEM, user_prompt)
        payload = json.loads(reply)
        normalized = _normalize_digest(payload, from_turn, to_turn, len(mid_pairs))
        if not normalized.get('stable_entities') and not normalized.get('ongoing_events') and not normalized.get('open_loops'):
            raise ValueError('mid digest is too weak')
        return normalized
    except Exception:
        return _heuristic_digest(mid_pairs, hard_anchors, from_turn, to_turn)
