#!/usr/bin/env python3
from __future__ import annotations

import re
from copy import deepcopy

try:
    from .name_sanitizer import sanitize_runtime_name
except ImportError:
    from name_sanitizer import sanitize_runtime_name


THREAD_RETENTION_TURNS = 2


def _short(text: str, limit: int = 72) -> str:
    one = ' '.join((text or '').split()).strip()
    return one[: limit - 3] + '...' if len(one) > limit else one


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
            if len(str(item.get('label', '') or '')) > len(str(existing.get('label', '') or '')):
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


def build_active_threads(state: dict, *, user_text: str = '', narrator_reply: str = '', arbiter: dict | None = None, limit: int = 5) -> list[dict]:
    current = dict(state or {})
    prev_threads = _coerce_threads(current.get('active_threads', []))
    prev_by_key = {str(item.get('key')): item for item in prev_threads if str(item.get('key', '')).strip()}
    used_ids: set[str] = set()
    actors = _actors_from_state(current)
    latest_change = _short(narrator_reply or user_text or current.get('scene_core', ''))
    candidates: list[dict] = []

    def add_candidate(key: str, *, label: str, kind: str, priority: str, goal: str, obstacle: str, latest: str):
        if not label.strip():
            return
        candidates.append({
            'key': key,
            'label': _short(label, 80),
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

    add_candidate(
        f'main:{_norm_key(main_event or immediate_goal or "当前主线程")}',
        label=main_event or '当前主线程',
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
        if cooldown_turns >= THREAD_RETENTION_TURNS:
            continue
        carried = deepcopy(prev)
        carried['status'] = 'watch'
        carried['cooldown_turns'] = cooldown_turns + 1
        carried['latest_change'] = _short(prev.get('latest_change', latest_change), 80)
        deduped.append(carried)
        used_ids.add(prev_id)

    return _dedupe_similar_threads(deduped, limit=limit)


def apply_thread_tracker(state: dict, *, user_text: str = '', narrator_reply: str = '', arbiter: dict | None = None) -> dict:
    next_state = deepcopy(state or {})
    next_state['active_threads'] = build_active_threads(next_state, user_text=user_text, narrator_reply=narrator_reply, arbiter=arbiter)
    return next_state
