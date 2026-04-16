#!/usr/bin/env python3
from __future__ import annotations

import re
from copy import deepcopy

try:
    from .name_sanitizer import sanitize_runtime_name
except ImportError:
    from name_sanitizer import sanitize_runtime_name


THREAD_RETENTION_CONFIG = {
    'main':    {'retention': 4, 'cooldown_escalation': 0},
    'risk':    {'retention': 3, 'cooldown_escalation': 0},
    'clue':    {'retention': 2, 'cooldown_escalation': 0},
    'arbiter': {'retention': 1, 'cooldown_escalation': 0},
}
THREAD_RETENTION_DEFAULT = {'retention': 2, 'cooldown_escalation': 0}


def _short(text: str, limit: int = 72) -> str:
    one = ' '.join((text or '').split()).strip()
    return one[: limit - 3] + '...' if len(one) > limit else one


def _clean_label(text: str) -> str:
    value = ' '.join(str(text or '').split()).strip()
    value = re.sub(r'^场景已转到', '', value)
    value = re.sub(r'^场面已切到', '', value)
    value = re.sub(r'，?互动重点随之转入新地点。?$', '', value)
    value = re.sub(r'里的局势正围绕“([^”]+)”推进。?$', r'\1', value)
    value = re.sub(r'成为当前场面重心，局势正接着“([^”]+)”往下走。?$', r'\1', value)
    value = value.strip('。；;，, ')
    return value


def _make_thread_key(kind: str, label: str) -> str:
    cleaned = _clean_label(label)
    if kind == 'main' and cleaned:
        return f'main:{_norm_key(cleaned)}'
    return f'{kind}:{_norm_key(cleaned or label)}'


def _is_generic_label(value: str) -> bool:
    text = _clean_label(value)
    if not text:
        return True
    if text.startswith('当前局势正围绕'):
        return True
    if text.startswith('人界·') or text.startswith('修仙历') or text.startswith('当前局面'):
        return True
    if '说：' in text or '问：' in text or '…' in text:
        return True
    return False


def _compress_secondary_label(text: str, kind: str) -> str:
    value = _clean_label(text)
    if kind == 'risk':
        if any(token in value for token in ('表态', '走向', '态度')):
            return '表态风险'
        if any(token in value for token in ('转场', '环境', '规则')):
            return '转场风险'
        if any(token in value for token in ('审查', '盘问', '怀疑', '暴露')):
            return '暴露风险'
        if any(token in value for token in ('受伤', '超时', '连坐')):
            return '失败风险'
        if any(token in value for token in ('规则', '摸清', '不确定')):
            return '规则风险'
    if kind == 'clue':
        if any(token in value for token in ('目标', '决定', '后续推进')):
            return '延续线索'
        if any(token in value for token in ('表态', '细节', '回流')):
            return '细节线索'
        if any(token in value for token in ('记录板', '画圈', '标记')):
            return '记录板标记'
        if any(token in value for token in ('怀疑', '假身份', '林诺')):
            return '身份疑点'
        if any(token in value for token in ('高崎', '掩护', '垫脚', '协作')):
            return '协作线索'
    return value


def _norm_key(text: str) -> str:
    cleaned = re.sub(r'\s+', '', text or '')
    cleaned = re.sub(r'[，。、“”‘’！？：:；,.!?()（）\[\]{}<>/\\-]+', '', cleaned)
    return cleaned[:48] or 'unknown'


def _tokenize(text: str) -> set[str]:
    raw = re.split(r'[\s，。、“”‘’！？：:；,.!?()（）\[\]{}<>/\\-]+', text or '')
    return {item for item in raw if len(item) >= 2}


def _similarity(a: str, b: str) -> float:
    ta = _tokenize(a)
    tb = _tokenize(b)
    if not ta or not tb:
        return 0.0
    overlap = len(ta & tb)
    base = max(len(ta), len(tb))
    return overlap / base if base else 0.0


def _thread_signature(item: dict) -> str:
    return ' '.join([
        str(item.get('label', '') or ''),
        str(item.get('goal', '') or ''),
        str(item.get('obstacle', '') or ''),
        ' '.join(item.get('actors', []) or []),
    ]).strip()


def _find_thread_match(candidate: dict, prev_threads: list[dict]) -> dict | None:
    candidate_kind = str(candidate.get('kind', ''))
    candidate_actors = set(candidate.get('actors', []) or [])
    candidate_sig = _thread_signature(candidate)
    best = None
    best_score = 0.0
    for item in prev_threads:
        if not isinstance(item, dict):
            continue
        if str(item.get('kind', '')) != candidate_kind:
            continue
        prev_actors = set(item.get('actors', []) or [])
        actor_bonus = 0.35 if candidate_actors and prev_actors and (candidate_actors & prev_actors) else 0.0
        label_score = _similarity(str(candidate.get('label', '')), str(item.get('label', '')))
        sig_score = _similarity(candidate_sig, _thread_signature(item))
        score = max(label_score, sig_score) + actor_bonus
        if score > best_score:
            best = item
            best_score = score
    return best if best_score >= 0.55 else None


def _find_main_thread_match(candidate: dict, prev_threads: list[dict], state: dict) -> dict | None:
    current_location = str(state.get('location', '') or '').strip()
    current_goal = str(state.get('immediate_goal', '') or '').strip()
    best = None
    best_score = 0.0
    for item in prev_threads:
        if not isinstance(item, dict):
            continue
        if str(item.get('kind', '')) != 'main':
            continue
        score = 0.0
        prev_goal = str(item.get('goal', '') or '').strip()
        prev_label = str(item.get('label', '') or '').strip()
        if current_goal and prev_goal and _similarity(current_goal, prev_goal) >= 0.4:
            score += 0.5
        if current_location and contains_same_location_hint(current_location, prev_label + ' ' + prev_goal):
            score += 0.4
        score += _similarity(_thread_signature(candidate), _thread_signature(item))
        if score > best_score:
            best = item
            best_score = score
    return best if best_score >= 0.6 else None


def contains_same_location_hint(current_location: str, previous_text: str) -> bool:
    current_tokens = _tokenize(current_location)
    previous_tokens = _tokenize(previous_text)
    return bool(current_tokens and previous_tokens and (current_tokens & previous_tokens))


def _coerce_threads(items) -> list[dict]:
    if not isinstance(items, list):
        return []
    out = []
    for item in items:
        if not isinstance(item, dict):
            continue
        out.append(item)
    return out


def _next_thread_id(prev_threads: list[dict], used_ids: set[str]) -> str:
    max_idx = 0
    for item in prev_threads:
        thread_id = str(item.get('thread_id', ''))
        match = re.search(r'(\d+)$', thread_id)
        if match:
            max_idx = max(max_idx, int(match.group(1)))
    while True:
        max_idx += 1
        candidate = f'thread_{max_idx:02d}'
        if candidate not in used_ids:
            return candidate


def _actors_from_state(state: dict) -> list[str]:
    actors = []
    for name in (state.get('onstage_npcs', []) or []) + (state.get('relevant_npcs', []) or []):
        cleaned = sanitize_runtime_name(name)
        if cleaned and cleaned not in actors:
            actors.append(cleaned)
    return actors[:4]


def _dedupe_similar_threads(items: list[dict], limit: int = 5) -> list[dict]:
    deduped: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = str(item.get('kind', '') or '').strip()
        if kind not in {'risk', 'clue'}:
            deduped.append(item)
            continue
        matched = False
        for existing in deduped:
            if not isinstance(existing, dict):
                continue
            if str(existing.get('kind', '') or '').strip() != kind:
                continue
            label_score = _similarity(str(item.get('label', '') or ''), str(existing.get('label', '') or ''))
            obstacle_score = _similarity(str(item.get('obstacle', '') or ''), str(existing.get('obstacle', '') or ''))
            goal_score = _similarity(str(item.get('goal', '') or ''), str(existing.get('goal', '') or ''))
            combo_score = _similarity(
                f"{item.get('label', '')} {item.get('obstacle', '')}",
                f"{existing.get('label', '')} {existing.get('obstacle', '')}",
            )
            score = max(label_score, obstacle_score, goal_score, combo_score)
            if score < 0.72:
                continue
            existing_label = str(existing.get('label', '') or '')
            item_label = str(item.get('label', '') or '')
            if _is_generic_label(existing_label) and not _is_generic_label(item_label):
                existing['label'] = item.get('label')
            elif len(item_label) > len(existing_label):
                existing['label'] = item.get('label')
            if len(str(item.get('obstacle', '') or '')) > len(str(existing.get('obstacle', '') or '')):
                existing['obstacle'] = item.get('obstacle')
            if len(str(item.get('goal', '') or '')) > len(str(existing.get('goal', '') or '')):
                existing['goal'] = item.get('goal')
            existing['latest_change'] = item.get('latest_change', existing.get('latest_change'))
            existing['stability_turns'] = max(int(existing.get('stability_turns', 1) or 1), int(item.get('stability_turns', 1) or 1))
            matched = True
            break
        if not matched:
            deduped.append(item)
        if len(deduped) >= limit:
            break
    return deduped[:limit]


def build_active_threads(state: dict, *, user_text: str = '', narrator_reply: str = '', arbiter: dict | None = None, limit: int = 5) -> tuple[list[dict], list[dict]]:
    """返回 (active_threads, newly_resolved_threads)"""
    current = dict(state or {})
    prev_threads = _coerce_threads(current.get('active_threads', []))
    prev_by_key = {str(item.get('key')): item for item in prev_threads if str(item.get('key', '')).strip()}
    used_ids: set[str] = set()
    newly_resolved: list[dict] = []
    actors = _actors_from_state(current)
    latest_change = _short(narrator_reply or user_text or current.get('scene_core', ''))
    candidates: list[dict] = []

    def add_candidate(key: str, *, label: str, kind: str, priority: str, goal: str, obstacle: str, latest: str):
        if not label.strip():
            return
        normalized_label = _clean_label(label) or label
        if kind in {'risk', 'clue'}:
            normalized_label = _compress_secondary_label(normalized_label, kind)
        normalized_key = _make_thread_key(kind, normalized_label)
        candidates.append({
            'key': normalized_key,
            'label': _short(normalized_label, 80),
            'kind': kind,
            'priority': priority,
            'status': 'active',
            'goal': _short(goal or '待确认', 80),
            'obstacle': _short(obstacle or '待确认', 80),
            'latest_change': _short(latest or latest_change or '待确认', 80),
            'actors': actors,
            'stability_turns': 1,
            'cooldown_turns': 0,
        })

    main_event = str(current.get('main_event', '') or '').strip()
    immediate_goal = str(current.get('immediate_goal', '') or '').strip()
    immediate_risks = [str(item).strip() for item in (current.get('immediate_risks', []) or []) if str(item).strip()]
    carryover_clues = [str(item).strip() for item in (current.get('carryover_clues', []) or []) if str(item).strip()]
    arbiter_signals = current.get('arbiter_signals', {}) if isinstance(current.get('arbiter_signals', {}), dict) else {}
    arbiter_events = arbiter_signals.get('events', []) if isinstance(arbiter_signals.get('events', []), list) else []

    def _better_main_label() -> str:
        if main_event and not _is_generic_label(main_event):
            return main_event
        if active_threads := current.get('active_threads', []):
            for item in active_threads:
                if not isinstance(item, dict):
                    continue
                label = str(item.get('label', '') or '').strip()
                if label and not _is_generic_label(label):
                    return label
        if immediate_goal and not immediate_goal.startswith('先处理“'):
            return immediate_goal
        text = str(current.get('location', '') or '').strip()
        if text and immediate_risks:
            return f'{text}中的局势仍在朝更高压方向推进'
        if text:
            return f'{text}中的局势仍在持续演化'
        return '当前局势仍在持续演化'

    add_candidate(
        f'main:{_norm_key(_better_main_label() or immediate_goal or "当前主线程")}',
        label=_better_main_label(),
        kind='main',
        priority='primary',
        goal=immediate_goal or '维持当前主推进并准备下一步选择',
        obstacle=immediate_risks[0] if immediate_risks else '待确认',
        latest=latest_change,
    )

    for risk in immediate_risks[:2]:
        add_candidate(
            f'risk:{_norm_key(risk)}',
            label=risk,
            kind='risk',
            priority='secondary',
            goal='避免该风险在下一轮直接失控或越界落地',
            obstacle=risk,
            latest=latest_change,
        )

    for clue in carryover_clues[:2]:
        add_candidate(
            f'clue:{_norm_key(clue)}',
            label=clue,
            kind='clue',
            priority='secondary',
            goal='澄清该线索的含义、来源或后续影响',
            obstacle='当前仍缺少足够上下文或验证',
            latest=latest_change,
        )

    for item in arbiter_events[:2]:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get('event_id', 'unknown-event'))
        result = str(item.get('result', 'unknown'))
        add_candidate(
            f'arbiter:{_norm_key(event_id)}',
            label=event_id,
            kind='arbiter',
            priority='secondary',
            goal='按当前裁定边界继续推进，不越过 forbidden outcomes',
            obstacle=result,
            latest=f'裁定结果：{result}',
        )

    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for item in candidates:
        key = item['key']
        if key in seen_keys:
            continue
        seen_keys.add(key)
        prev = prev_by_key.get(key)
        if prev is None and item.get('kind') == 'main':
            prev = _find_main_thread_match(item, prev_threads, current)
        if prev is None:
            prev = _find_thread_match(item, prev_threads)
        if prev:
            thread_id = str(prev.get('thread_id', '') or '')
            if item.get('kind') != 'main':
                item['key'] = str(prev.get('key', key) or key)
            item['stability_turns'] = int(prev.get('stability_turns', 1) or 1) + 1
            item['cooldown_turns'] = 0
        else:
            thread_id = _next_thread_id(prev_threads, used_ids)
        used_ids.add(thread_id)
        merged = deepcopy(prev) if prev else {}
        merged.update(item)
        merged['thread_id'] = thread_id
        deduped.append(merged)
        if len(deduped) >= limit:
            break

    for prev in prev_threads:
        if len(deduped) >= limit:
            break
        if not isinstance(prev, dict):
            continue
        prev_id = str(prev.get('thread_id', '') or '')
        if prev_id in used_ids:
            continue
        cooldown_turns = int(prev.get('cooldown_turns', 0) or 0)
        prev_kind = str(prev.get('kind', '') or '')
        retention_config = THREAD_RETENTION_CONFIG.get(prev_kind, THREAD_RETENTION_DEFAULT)
        max_cooldown = retention_config['retention']
        if cooldown_turns >= max_cooldown:
            # 线程冷却期结束 → 标记为 resolved 以便归档
            resolved = deepcopy(prev)
            resolved['status'] = 'resolved'
            resolved['resolved_reason'] = 'cooldown_expired'
            newly_resolved.append(resolved)
            continue
        carried = deepcopy(prev)
        if cooldown_turns >= max(1, max_cooldown - 1):
            carried['status'] = 'cooling_down'
        else:
            carried['status'] = 'watch'
        carried['cooldown_turns'] = cooldown_turns + 1
        carried['latest_change'] = _short(prev.get('latest_change', latest_change), 80)
        deduped.append(carried)
        used_ids.add(prev_id)

    return _dedupe_similar_threads(deduped, limit=limit), newly_resolved


def apply_thread_tracker(state: dict, *, user_text: str = '', narrator_reply: str = '', arbiter: dict | None = None) -> dict:
    next_state = deepcopy(state or {})
    active, resolved = build_active_threads(next_state, user_text=user_text, narrator_reply=narrator_reply, arbiter=arbiter)
    next_state['active_threads'] = active

    # 将冷却期结束的线程归档到 resolved_events
    existing_resolved = next_state.get('resolved_events', []) or []
    if not isinstance(existing_resolved, list):
        existing_resolved = []
    for thread in resolved:
        existing_resolved.append({
            'label': thread.get('label', ''),
            'kind': thread.get('kind', ''),
            'status': 'resolved',
            'resolved_reason': thread.get('resolved_reason', 'cooldown_expired'),
            'goal': thread.get('goal', ''),
            'actors': thread.get('actors', []),
            'stability_turns': thread.get('stability_turns', 0),
        })
    # 只保留最近 20 条已解决事件
    next_state['resolved_events'] = existing_resolved[-20:]
    current_main_event = _clean_label(str(next_state.get('main_event', '') or ''))
    if current_main_event and not _is_generic_label(current_main_event):
        for item in next_state['active_threads']:
            if not isinstance(item, dict):
                continue
            if str(item.get('kind', '') or '') != 'main':
                continue
            item['label'] = current_main_event
            item['key'] = _make_thread_key('main', current_main_event)
            break
    return next_state
