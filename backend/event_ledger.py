#!/usr/bin/env python3
from __future__ import annotations

import json
import re

from model_client import call_model
from local_model_client import parse_json_response
from model_config import resolve_provider_model


def _split_sentences(text: str) -> list[str]:
    raw = str(text or '').replace('\r', '\n')
    parts = re.split(r'[\n。！？!?]+', raw)
    out = []
    for part in parts:
        cleaned = part.strip(' ，、；："“”')
        cleaned = re.sub(r'^\[(?:用户|叙事)\]\s*', '', cleaned)
        if cleaned:
            out.append(cleaned)
    return out


def _normalize(text: str) -> str:
    return ' '.join(str(text or '').split()).strip()


def _recent_turn_pairs(history_items: list[dict], limit_pairs: int = 3) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history_items or []:
        if not isinstance(item, dict):
            continue
        role = item.get('role')
        content = str(item.get('content', '') or '')
        if role == 'user':
            current_user = content
        elif role == 'assistant' and current_user is not None:
            pairs.append((current_user, content))
            current_user = None
    return pairs[-limit_pairs:]


def _window_text(recent_pairs: list[tuple[str, str]]) -> str:
    parts = []
    for user_text, assistant_text in recent_pairs:
        if user_text.strip():
            parts.append(f'[用户] {user_text.strip()}')
        if assistant_text.strip():
            parts.append(f'[叙事] {assistant_text.strip()}')
    return '\n'.join(parts)


def _assistant_window_text(recent_pairs: list[tuple[str, str]]) -> str:
    parts = []
    for _user_text, assistant_text in recent_pairs:
        if assistant_text.strip():
            parts.append(assistant_text.strip())
    return '\n'.join(parts)


def _fragment_score(text: str) -> int:
    value = _normalize(text)
    score = 0
    if len(value) < 10:
        score += 2
    if len(value) <= 24 and any(p in value for p in ('：', ':', '，')):
        score += 2
    if value[:1] in {'我', '你', '他', '她'}:
        score += 2
    if value.endswith(('了', '着', '呢', '呀', '吧', '吗')):
        score += 1
    if '→' in value:
        score += 3
    return score


def _progress_score(text: str) -> int:
    value = _normalize(text)
    score = 0
    event_tokens = (
        '逼', '压', '撞', '刺', '斩', '劈', '割', '追', '拦', '封', '退', '进', '收', '抢', '拿',
        '搜', '问', '喝', '命', '令', '暴露', '察觉', '发现', '掉', '滑', '扑', '逃', '翻', '钉',
        '困', '断', '开口', '逼问', '收口', '变势', '分神', '突传', '响', '亮出', '下令',
    )
    consequence_tokens = ('于是', '顿时', '立刻', '下一瞬', '就在这时', '紧接着', '这一下', '这时', '随即')
    atmosphere_tokens = (
        '雨下得', '风灯', '檐角', '青石', '灯影', '雨幕', '夜雨', '冷雨', '潮气', '光晕',
        '墙面', '积水', '水珠', '天光', '昏黄', '铁锈气', '腥气',
    )
    score += sum(1 for token in event_tokens if token in value)
    score += 2 * sum(1 for token in consequence_tokens if token in value)
    if any(token in value for token in ('“', '”', '：', ':')) and any(token in value for token in ('交', '找', '拿', '带', '搜', '问', '命', '令', '册', '活口')):
        score += 2
    if any(token in value for token in atmosphere_tokens) and score == 0:
        score -= 2
    return score


def _compress_signal_text(text: str, limit: int = 28) -> str:
    value = _normalize(text)
    value = re.sub(r'^\[(?:用户|叙事)\]\s*', '', value)
    value = re.sub(r'^(?:于是|顿时|立刻|下一瞬|就在这时|紧接着|这一下|这时|随即)', '', value).strip(' ，、；：')
    if '“' in value and '”' in value:
        quoted = re.findall(r'“([^”]+)”', value)
        if quoted:
            lead = value.split('“', 1)[0].strip(' ，、；：')
            value = (lead + '：' + quoted[0]).strip(' ：') if lead else quoted[0]
    for brk in ('，', '；', ',', '——', '……'):
        idx = value.find(brk, max(6, limit // 2))
        if 0 < idx < limit:
            value = value[:idx].strip()
            break
    if len(value) > limit:
        value = value[:limit].rstrip('，、；：')
    return value


def _compress_event_summary_text(text: str, limit: int = 72) -> str:
    value = _normalize(text)
    value = re.sub(r'^(?:就在这时|紧接着|下一瞬|这一下|于是|随即)', '', value).strip(' ，、；：')
    for marker in ('——', '；', '，', ',', '……'):
        idx = value.find(marker, max(10, limit // 2))
        if 0 < idx < limit:
            value = value[:idx].strip()
            break
    if len(value) > limit:
        value = value[:limit].rstrip('，、；：')
    return value


def _scene_score(text: str, onstage_names: list[str]) -> int:
    value = _normalize(text)
    score = 0
    hits = sum(1 for name in onstage_names if name and name in value)
    if hits >= 2:
        score += 3
    elif hits == 1:
        score += 1
    if len(value) >= 14:
        score += 1
    clause_marks = sum(value.count(mark) for mark in ('，', '；', '、'))
    if clause_marks >= 1:
        score += 2
    return score


def core_value_quality(text: str, onstage_names: list[str]) -> int:
    value = _normalize(text)
    if not value:
        return -99
    return _scene_score(value, onstage_names) - _fragment_score(value)


def _looks_like_scene_shift(prev_state: dict, location: str, onstage_names: list[str]) -> tuple[bool, int]:
    score = 0
    prev_location = str(prev_state.get('location', '') or '').strip()
    prev_onstage = [str(name or '').strip() for name in (prev_state.get('onstage_npcs', []) or []) if str(name or '').strip()]
    location_changed = bool(location and prev_location and location != prev_location)
    onstage_rebuilt = False
    if location and prev_location and location != prev_location:
        score += 2
    overlap = len(set(prev_onstage) & set(onstage_names))
    if prev_onstage and onstage_names and overlap <= max(0, min(len(prev_onstage), len(onstage_names)) - 2):
        score += 2
        onstage_rebuilt = True
    if location_changed and onstage_rebuilt:
        score += 1
    if location_changed and not prev_onstage and onstage_names:
        score += 1
    changed = False
    if location_changed and onstage_rebuilt:
        changed = True
    elif location_changed and not prev_onstage and len(onstage_names) >= 2:
        changed = True
    return changed, score


def build_event_ledger(*, user_text: str, narrator_reply: str, prev_state: dict, onstage_names: list[str], location: str, recent_pairs: list[tuple[str, str]] | None = None, current_state: dict | None = None) -> dict:
    window_pairs = recent_pairs or [(user_text, narrator_reply)]
    assistant_window = _assistant_window_text(window_pairs)
    sentences = _split_sentences(assistant_window)
    main_event_candidates = []
    risk_candidates = []
    clue_candidates = []
    discarded_fragments = []

    for idx, text in enumerate(sentences):
        fragment_score = _fragment_score(text)
        scene_score = _scene_score(text, onstage_names)
        progress_score = _progress_score(text)
        item = {
            'text': text,
            'fragment_score': fragment_score,
            'scene_score': scene_score,
            'progress_score': progress_score,
            'idx': idx,
        }
        if progress_score >= 2 and scene_score >= 2 and fragment_score <= 2:
            main_event_candidates.append(item)
        else:
            discarded_fragments.append(item)
        if progress_score >= 2 and any(token in text for token in ('危险', '威胁', '暴露', '围', '死', '杀', '伤', '断', '追', '封', '拿下', '灭口')):
            signal = _compress_signal_text(text)
            if signal and signal not in risk_candidates:
                risk_candidates.append(signal)
        if progress_score >= 2 and any(token in text for token in ('册', '信', '图', '口供', '印信', '搜', '问', '谁', '主子', '来历', '东西')):
            signal = _compress_signal_text(text)
            if signal and signal not in clue_candidates:
                clue_candidates.append(signal)

    ranked_candidates = sorted(
        main_event_candidates,
        key=lambda item: (-(item.get('progress_score', 0) + item.get('scene_score', 0)), item.get('fragment_score', 0), item.get('idx', 0)),
    )
    summary_candidates = sorted(ranked_candidates[:2], key=lambda item: item.get('idx', 0))

    state_snapshot = current_state or {}
    state_signals = [
        str(item.get('text', '') or '').strip()
        for item in (state_snapshot.get('carryover_signals', []) or [])
        if isinstance(item, dict) and str(item.get('text', '') or '').strip()
    ]
    object_labels = [
        str(item.get('label', '') or '').strip()
        for item in (state_snapshot.get('tracked_objects', []) or [])
        if isinstance(item, dict) and str(item.get('label', '') or '').strip()
    ]
    changed, score = _looks_like_scene_shift(prev_state, location, onstage_names)
    summary_parts = []
    if main_event_candidates:
        summary_parts.extend(
            _compress_event_summary_text(item.get('text', ''), limit=72)
            for item in summary_candidates
            if isinstance(item, dict) and item.get('text')
        )
    if state_signals:
        for text in state_signals[:2]:
            compressed = _compress_signal_text(text, limit=40)
            if compressed and compressed not in summary_parts:
                summary_parts.append(compressed)
    if object_labels:
        object_hint = '关键物件：' + ' / '.join(object_labels[:2])
        if object_hint not in summary_parts:
            summary_parts.append(object_hint)
    return {
        'ledger_version': 1,
        'provider': 'heuristic',
        'summary_text': _normalize('；'.join(part for part in summary_parts if part))[:150],
        'scene_shift': {
            'changed': changed,
            'score': score,
        },
        'main_event_candidates': ranked_candidates[:3],
        'risk_candidates': risk_candidates[:2],
        'clue_candidates': (clue_candidates[:2] or [_compress_signal_text(text, limit=28) for text in state_signals[:2] if _compress_signal_text(text, limit=28)]),
        'discarded_fragments': discarded_fragments[:6],
    }


EVENT_LEDGER_SYSTEM = """你是事件账本整理器。\n\n你的职责不是挑要点，也不是改写成高度抽象的摘要，而是把最近 1~3 轮里真实发生的关键经过如实整理成一条事件总结。\n\n要求：\n1. summary_text 必须像“阶段总结”，不是单句对白，也不是一句局部动作。\n2. summary_text 应尽量覆盖最近 1~3 轮里真正推进局势的经过，长度控制在 80~150 个中文字符。\n3. main_event_candidate 必须比 summary_text 更短，是一条可作为 state 主锚点的局势句。\n4. risk_candidates / clue_candidates 只保留真正会影响后续的 0~2 条。\n5. scene_shift.changed 只有在地点、在场人物群或互动模式明显切段时才为 true。\n6. 不要输出解释，只输出 JSON。"""


def _ledger_prompt(*, user_text: str, narrator_reply: str, prev_state: dict, onstage_names: list[str], location: str, recent_pairs: list[tuple[str, str]] | None = None, current_state: dict | None = None) -> str:
    baseline = {
        'prev_location': prev_state.get('location', '待确认'),
        'prev_main_event': prev_state.get('main_event', '待确认'),
        'prev_onstage_npcs': prev_state.get('onstage_npcs', []),
        'current_location_candidate': location or '待确认',
        'current_onstage_npcs': onstage_names,
    }
    current_snapshot = {
        'time': (current_state or {}).get('time', '待确认'),
        'location': (current_state or {}).get('location', location or '待确认'),
        'main_event': (current_state or {}).get('main_event', '待确认'),
        'onstage_npcs': (current_state or {}).get('onstage_npcs', onstage_names),
        'carryover_signals': (current_state or {}).get('carryover_signals', []),
        'tracked_objects': (current_state or {}).get('tracked_objects', []),
    }
    return json.dumps({
        'baseline': baseline,
        'recent_turn_pairs': [
            {'user': user, 'assistant': assistant}
            for user, assistant in (recent_pairs or [(user_text, narrator_reply)])
        ],
        'current_turn': {
            'user_text': user_text,
            'narrator_reply': narrator_reply,
        },
        'current_state_snapshot': current_snapshot,
    }, ensure_ascii=False, indent=2)


def _coerce_ledger_payload(payload: dict) -> dict:
    scene_shift = payload.get('scene_shift', {}) if isinstance(payload.get('scene_shift', {}), dict) else {}
    return {
        'ledger_version': 2,
        'provider': 'llm',
        'summary_text': str(payload.get('summary_text', '') or '').strip(),
        'scene_shift': {
            'changed': bool(scene_shift.get('changed')),
            'score': int(scene_shift.get('score', 0) or 0),
        },
        'main_event_candidates': [{'text': str(payload.get('main_event_candidate', '') or '').strip(), 'fragment_score': 0, 'scene_score': 5}] if str(payload.get('main_event_candidate', '') or '').strip() else [],
        'risk_candidates': [str(x).strip() for x in (payload.get('risk_candidates', []) or []) if str(x).strip()][:2],
        'clue_candidates': [str(x).strip() for x in (payload.get('clue_candidates', []) or []) if str(x).strip()][:2],
        'discarded_fragments': [],
    }


def build_event_ledger_with_llm(*, user_text: str, narrator_reply: str, prev_state: dict, onstage_names: list[str], location: str, recent_pairs: list[tuple[str, str]] | None = None, current_state: dict | None = None) -> dict:
    fallback = build_event_ledger(
        user_text=user_text,
        narrator_reply=narrator_reply,
        prev_state=prev_state,
        onstage_names=onstage_names,
        location=location,
        recent_pairs=recent_pairs,
        current_state=current_state,
    )
    try:
        cfg = resolve_provider_model('state_keeper_candidate')
        reply, _usage = call_model(
            cfg,
            EVENT_LEDGER_SYSTEM,
            _ledger_prompt(
                user_text=user_text,
                narrator_reply=narrator_reply,
                prev_state=prev_state,
                onstage_names=onstage_names,
                location=location,
                recent_pairs=recent_pairs,
                current_state=current_state,
            ),
        )
        payload = parse_json_response(reply)
        result = _coerce_ledger_payload(payload)
        result['fallback_heuristic'] = fallback
        return result
    except Exception:
        return fallback


def build_event_summary_item(*, turn_id: str, ledger: dict, onstage_names: list[str], tracked_objects: list[dict] | None = None, carryover_clues: list[str] | None = None) -> dict:
    summary = _normalize(str(ledger.get('summary_text', '') or ''))
    if not summary:
        main_text = next((item.get('text', '') for item in (ledger.get('main_event_candidates', []) or []) if isinstance(item, dict) and item.get('text')), '')
        summary = _normalize(main_text)
    summary = summary[:150]

    normalized_clues = []
    for item in (ledger.get('clue_candidates', []) or [])[:2]:
        if isinstance(item, dict):
            text = str(item.get('text', '') or '').strip()
        else:
            text = str(item).strip()
        if text and text not in normalized_clues:
            normalized_clues.append(text)
    if not normalized_clues:
        normalized_clues = [str(item).strip() for item in (carryover_clues or [])[:2] if str(item).strip()]

    return {
        'event_id': f'evt_{turn_id[-4:]}',
        'turn_id': turn_id,
        'summary': summary,
        'actors': [name for name in onstage_names[:3] if name],
        'objects': [str(item.get('label', '') or '').strip() for item in (tracked_objects or [])[:2] if isinstance(item, dict) and str(item.get('label', '') or '').strip()],
        'clues': normalized_clues,
        'scene_shift': bool(ledger.get('scene_shift', {}).get('changed')),
        'provider': ledger.get('provider', 'heuristic'),
    }
