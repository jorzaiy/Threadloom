#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy

try:
    from .name_sanitizer import sanitize_runtime_name, is_protagonist_name, looks_like_modifier_fragment
    from .card_hints import get_service_role_tokens
    from .keeper_archive import load_keeper_record_archive
except ImportError:
    from name_sanitizer import sanitize_runtime_name, is_protagonist_name, looks_like_modifier_fragment
    from card_hints import get_service_role_tokens
    from keeper_archive import load_keeper_record_archive
THREAD_KIND_WEIGHT = {
    'main': 2,
    'risk': 1,
    'clue': 1,
    'arbiter': 1,
}


def _turn_pairs(history: list[dict]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    current_user = None
    for item in history:
        role = item.get('role')
        content = item.get('content', '') or ''
        if role == 'user':
            current_user = content
        elif role == 'assistant':
            pairs.append((current_user or '', content))
            current_user = None
    return pairs


def _count_mentions(history: list[dict], names: list[str]) -> tuple[int, int]:
    user_mentions = 0
    any_mentions = 0
    for user_text, assistant_text in _turn_pairs(history):
        matched = any(name and (name in user_text or name in assistant_text) for name in names)
        if matched:
            any_mentions += 1
        if any(name and name in user_text for name in names):
            user_mentions += 1
    return user_mentions, any_mentions


def _is_service_role(role_label: str) -> bool:
    text = role_label or ''
    tokens = get_service_role_tokens()
    if not tokens:
        return False
    return any(token in text for token in tokens)


def _important_key(label: str) -> str:
    return f'important:{(label or "unknown").strip()}'


def _is_generic_anchor(label: str, aliases: list[str], role_label: str) -> bool:
    if not label:
        return True
    if len(set(aliases)) >= 2:
        return False
    if role_label and not _is_service_role(role_label) and role_label not in {'待确认', '当前互动核心人物', '相关场景人物'}:
        return False
    return True


def _service_lock_allowed(*, label: str, role_label: str, reference_candidate: bool, user_mentions: int, total_mentions: int, thread_weight: int, retained_entity: bool, latest_change: str) -> bool:
    if reference_candidate:
        return True
    if not _is_service_role(role_label):
        return True

    if user_mentions >= 2 and thread_weight >= 2:
        return True
    if total_mentions >= 5 and thread_weight >= 2 and retained_entity:
        return True
    return False


def update_important_npcs(state: dict, history: list[dict], reference_candidates: list[dict] | None = None, *, allow_archive_write: bool = True) -> dict:
    current = deepcopy(state or {})
    session_id = str(current.get('session_id', '') or '').strip()
    current_location = str(current.get('location', '') or '').strip()
    current_main_event = str(current.get('main_event', '') or '').strip()
    previous = current.get('important_npcs', []) if isinstance(current.get('important_npcs', []), list) else []
    prev_by_key = {item.get('key'): item for item in previous if isinstance(item, dict) and item.get('key')}
    candidate_sources = {
        str(item.get('name', '')).strip(): str(item.get('source', '')).strip()
        for item in (reference_candidates or [])
        if str(item.get('name', '')).strip()
    }
    protected_names = {
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (current.get('scene_entities', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    }
    hint_names = {
        sanitize_runtime_name(item.get('primary_label', ''))
        for item in (current.get('continuity_hints', []) or [])
        if isinstance(item, dict) and sanitize_runtime_name(item.get('primary_label', ''))
    }
    thread_actor_names = set()
    thread_weight_by_actor: dict[str, int] = {}
    for item in current.get('active_threads', []) or []:
        if not isinstance(item, dict):
            continue
        thread_weight = THREAD_KIND_WEIGHT.get(str(item.get('kind', '') or ''), 0)
        for actor in item.get('actors', []) or []:
            actor_name = sanitize_runtime_name(actor)
            if actor_name:
                thread_actor_names.add(actor_name)
                thread_weight_by_actor[actor_name] = thread_weight_by_actor.get(actor_name, 0) + thread_weight

    next_items: list[dict] = []
    seen: set[str] = set()
    for entity in current.get('scene_entities', []) or []:
        if not isinstance(entity, dict):
            continue
        label = sanitize_runtime_name(entity.get('primary_label', ''))
        if not label or is_protagonist_name(label):
            continue
        if looks_like_modifier_fragment(label):
            continue
        aliases = [sanitize_runtime_name(alias) for alias in (entity.get('aliases') or []) if sanitize_runtime_name(alias) and not is_protagonist_name(alias)]
        names = [label] + aliases
        role_label = str(entity.get('role_label', '') or '').strip()
        latest_change = ' '.join(str(item.get('latest_change', '') or '') for item in (current.get('active_threads', []) or []) if isinstance(item, dict))
        user_mentions, total_mentions = _count_mentions(history, names)
        candidate_source = candidate_sources.get(label, '')
        worldbook_candidate = candidate_source in {'lorebook_npc', 'featured_cast'}
        reference_candidate = bool(candidate_source)
        retained_entity = not bool(entity.get('onstage'))
        previously_locked = _important_key(label) in prev_by_key
        importance_score = 0
        if entity.get('onstage'):
            importance_score += 2
        if label in (current.get('relevant_npcs', []) or []):
            importance_score += 1
        importance_score += min(thread_weight_by_actor.get(label, 0), 2)
        if user_mentions >= 2:
            importance_score += 2
        if total_mentions >= 4:
            importance_score += 1
        if reference_candidate:
            importance_score += 2
        if label in hint_names:
            importance_score += 3
        if len(set(aliases)) >= 2:
            importance_score += 1
        if retained_entity:
            importance_score += 1
        if previously_locked:
            importance_score += 2
        if _is_service_role(role_label) and not reference_candidate:
            if user_mentions == 0:
                importance_score -= 2
            if total_mentions < 3:
                importance_score -= 1
            if thread_weight_by_actor.get(label, 0) <= 1:
                importance_score -= 1

        service_lock_ok = _service_lock_allowed(
            label=label,
            role_label=role_label,
            reference_candidate=reference_candidate,
            user_mentions=user_mentions,
            total_mentions=total_mentions,
            thread_weight=thread_weight_by_actor.get(label, 0),
            retained_entity=retained_entity,
            latest_change=latest_change,
        )
        if _is_service_role(role_label) and not service_lock_ok and not previously_locked:
            continue
        generic_anchor = _is_generic_anchor(label, aliases, role_label)
        threshold = 5 if generic_anchor else 3
        if importance_score < threshold and not previously_locked:
            continue
        if generic_anchor and user_mentions == 0 and thread_weight_by_actor.get(label, 0) <= 1 and not reference_candidate and not entity.get('onstage'):
            continue

        key = _important_key(label)
        prev = prev_by_key.get(key, {})
        if key in seen:
            continue
        seen.add(key)
        previously_locked = bool(prev.get('locked'))
        present_now = bool(entity.get('onstage')) or label in (current.get('relevant_npcs', []) or [])
        inactive_turns = 0 if present_now else int(prev.get('inactive_turns', 0) or 0) + 1
        should_lock = service_lock_ok or not _is_service_role(role_label) or reference_candidate
        next_items.append({
            'key': key,
            'primary_label': label,
            'aliases': sorted({
                alias for alias in aliases + [sanitize_runtime_name(alias) for alias in prev.get('aliases', [])]
                if alias and not is_protagonist_name(alias) and (alias == label or alias not in protected_names)
            }),
            'role_label': role_label or prev.get('role_label', '待确认'),
            'anchor_type': 'continuous',
            'worldbook_candidate': worldbook_candidate,
            'reference_source': candidate_source or prev.get('reference_source', ''),
            'importance_score': max(int(prev.get('importance_score', 0) or 0), importance_score),
            'locked': should_lock,
            'retained': retained_entity,
            'present_now': present_now,
            'inactive_turns': inactive_turns,
            'last_location': current_location if present_now or not prev.get('last_location') else prev.get('last_location'),
            'last_main_event': current_main_event or prev.get('last_main_event'),
            'newly_locked': not previously_locked,
        })

    if not next_items and session_id:
        try:
            archive = load_keeper_record_archive(session_id, allow_archive_write=allow_archive_write)
        except Exception:
            archive = {}
        registry_items = archive.get('npc_registry', {}).get('entities', []) if isinstance(archive.get('npc_registry', {}), dict) else []
        for item in registry_items[:4]:
            if not isinstance(item, dict):
                continue
            label = sanitize_runtime_name(item.get('canonical_name', ''))
            if not label or is_protagonist_name(label):
                continue
            key = _important_key(label)
            if key in seen:
                continue
            seen.add(key)
            aliases = [sanitize_runtime_name(alias) for alias in (item.get('aliases', []) or []) if sanitize_runtime_name(alias) and not is_protagonist_name(alias)]
            next_items.append({
                'key': key,
                'primary_label': label,
                'aliases': aliases,
                'role_label': str(item.get('role_label', '') or '待确认').strip() or '待确认',
                'anchor_type': 'continuous',
                'worldbook_candidate': False,
                'reference_source': 'keeper_registry',
                'importance_score': 3,
                'locked': False,
                'retained': True,
                'present_now': False,
                'inactive_turns': 0,
                'last_location': current_location,
                'last_main_event': current_main_event,
                'newly_locked': False,
            })

    for key, prev in prev_by_key.items():
        if key in seen:
            continue
        label = sanitize_runtime_name(prev.get('primary_label', ''))
        if not label or is_protagonist_name(label):
            continue
        if looks_like_modifier_fragment(label):
            continue
        carried = deepcopy(prev)
        prev_role = str(carried.get('role_label', '') or '').strip()
        prev_aliases = [sanitize_runtime_name(alias) for alias in (carried.get('aliases') or []) if sanitize_runtime_name(alias)]
        generic_anchor = _is_generic_anchor(label, prev_aliases, prev_role)
        if generic_anchor and int(prev.get('inactive_turns', 0) or 0) >= 1:
            continue
        carried['aliases'] = [alias for alias in (carried.get('aliases') or []) if sanitize_runtime_name(alias) and not is_protagonist_name(alias)]
        carried['retained'] = True
        carried['present_now'] = False
        carried['inactive_turns'] = int(prev.get('inactive_turns', 0) or 0) + 1
        if current_main_event:
            carried['last_main_event'] = current_main_event
        carried['newly_locked'] = False
        next_items.append(carried)
        seen.add(key)

    current['important_npcs'] = next_items
    return current
