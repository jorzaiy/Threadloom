#!/usr/bin/env python3
from __future__ import annotations

import json


def joined_recent_text(recent_history: list[dict], limit: int = 6) -> str:
    parts = []
    for item in recent_history[-limit:]:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get('content', '') or ''))
    return '\n'.join(parts)


def candidate_name_hits(candidates: list[dict], text: str, limit: int = 3) -> int:
    haystack = str(text or '')
    hits = 0
    for item in candidates[:limit * 2]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('name', '') or '').strip()
        if name and name in haystack:
            hits += 1
            if hits >= limit:
                break
    return hits


def important_npc_names(items: list[dict], limit: int = 4) -> list[str]:
    names = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        name = str(item.get('primary_label', '') or '').strip()
        if name and name not in names:
            names.append(name)
    return names


def should_inject_lorebook_text(state_json: dict, recent_history: list[dict], keeper_records: dict, lorebook_entries: list[dict], active_threads: list[dict]) -> bool:
    if not lorebook_entries:
        return False
    location = str(state_json.get('location', '') or '').strip()
    main_event = str(state_json.get('main_event', '') or '').strip()
    recent_text = joined_recent_text(recent_history)
    anchor_text = ' '.join([
        main_event,
        location,
        json.dumps(keeper_records or {}, ensure_ascii=False),
        recent_text,
    ])
    explanation_pressure = 0
    if location and location not in {'待确认', '住处内', '门前', '巷口', '屋内'}:
        explanation_pressure += 1
    if keeper_records:
        explanation_pressure += 1
    for entry in lorebook_entries[:3]:
        title = str(entry.get('title', '') or '').strip()
        runtime_scope = str(entry.get('runtimeScope', '') or '').strip()
        entry_type = str(entry.get('entryType', '') or '').strip()
        if title and title in anchor_text:
            explanation_pressure += 1
        if runtime_scope == 'foundation' and any(token in anchor_text for token in (title,)):
            explanation_pressure += 1
        if entry_type in {'faction', 'world'} and title and location and title in location:
            explanation_pressure += 1
    return explanation_pressure >= 2


def should_inject_npc_candidates(onstage: list[str], relevant: list[str], active_threads: list[dict], recent_history: list[dict], important_npcs: list[dict], candidates: list[dict]) -> bool:
    recent_text = joined_recent_text(recent_history)
    hits = candidate_name_hits(candidates, recent_text)
    if any(name and name in recent_text for name in relevant[:3]):
        return True
    if hits >= 1:
        return True
    return False


def profile_targets(onstage: list[str], relevant: list[str], active_threads: list[dict], recent_history: list[dict], important_npcs: list[dict], limit: int = 3) -> list[str]:
    targets = []
    recent_text = joined_recent_text(recent_history)
    for name in onstage:
        if name and name not in targets:
            targets.append(name)
    for name in relevant:
        if len(targets) >= limit:
            break
        if name and name in recent_text and name not in targets:
            targets.append(name)
    for name in important_npc_names(important_npcs):
        if len(targets) >= limit:
            break
        if name and name in recent_text and name not in targets:
            targets.append(name)
    return targets[:limit]


def build_npc_roster(*, onstage: list[str], relevant: list[str], active_threads: list[dict], important_npcs: list[dict], event_hits: list[dict], event_summaries: list[dict], limit: int = 5) -> list[dict]:
    event_by_id = {str(item.get('event_id', '') or ''): item for item in event_summaries if isinstance(item, dict)}
    scored = {}
    def touch(name: str, score: int, role: str = '', status: str = ''):
        if not name:
            return
        item = scored.setdefault(name, {'name': name, 'score': 0, 'role': '', 'status': ''})
        item['score'] += score
        if role and not item['role']:
            item['role'] = role
        if status and not item['status']:
            item['status'] = status

    important_by_name = {str(item.get('primary_label', '') or '').strip(): item for item in important_npcs if isinstance(item, dict)}
    for name in onstage:
        touch(str(name).strip(), 4)
    for name in relevant[:3]:
        touch(str(name).strip(), 3, status='当前相关人物')
    for hit in event_hits:
        event = event_by_id.get(str(hit.get('event_id', '') or ''))
        if not isinstance(event, dict):
            continue
        for actor in event.get('actors', []) or []:
            touch(str(actor).strip(), 2)
    for name, item in important_by_name.items():
        role = str(item.get('role_label', '') or '').strip()
        touch(name, 1, role=role, status='当前重要人物')
    # fallback: if no signals, still keep a few obvious current actors from onstage/important
    if not scored:
        for name in onstage[:3]:
            touch(str(name).strip(), 3, status='当前在场人物')
        for name, item in list(important_by_name.items())[:2]:
            role = str(item.get('role_label', '') or '').strip()
            touch(name, 1, role=role, status='当前重要人物')
        latest_event = next((item for item in reversed(event_summaries) if isinstance(item, dict) and (item.get('actors') or [])), None)
        if isinstance(latest_event, dict):
            for name in latest_event.get('actors', [])[:3]:
                touch(str(name).strip(), 2, status='近期事件相关人物')
    result = []
    for item in sorted(scored.values(), key=lambda x: (-x['score'], x['name']))[:limit]:
        if not item['role']:
            item['role'] = '当前相关人物'
        if not item['status']:
            item['status'] = '与当前局势存在直接关联'
        result.append({'name': item['name'], 'role': item['role'], 'status': item['status']})
    return result


def event_summary_hits(event_summaries: list[dict], *, recent_history: list[dict], active_threads: list[dict], important_npcs: list[dict], tracked_objects: list[dict], carryover_clues: list[str]) -> list[dict]:
    recent_text = joined_recent_text(recent_history)
    object_labels = [str(item.get('label', '') or '').strip() for item in (tracked_objects or []) if isinstance(item, dict) and str(item.get('label', '') or '').strip()]
    clue_labels = [str(item).strip() for item in (carryover_clues or []) if str(item).strip()]
    hits = []
    for item in event_summaries[-12:]:
        if not isinstance(item, dict):
            continue
        score = 0
        reason = []
        actors = [str(x).strip() for x in (item.get('actors', []) or []) if str(x).strip()]
        actor_overlap = any(name and name in recent_text for name in actors)
        if actor_overlap:
            score += 2
            reason.append('actor_overlap')
        event_objects = [str(x).strip() for x in (item.get('objects', []) or []) if str(x).strip()]
        object_overlap = any(obj in event_objects for obj in object_labels)
        if object_overlap:
            score += 2
            reason.append('object_overlap')
        event_clues = [str(x).strip() for x in (item.get('clues', []) or []) if str(x).strip()]
        clue_overlap = any(clue and any(clue[:6] and clue[:6] in ec for ec in event_clues) for clue in clue_labels if len(clue) >= 6)
        if clue_overlap:
            score += 2
            reason.append('clue_overlap')
        summary = str(item.get('summary', '') or '').strip()
        summary_overlap = bool(summary and summary[:8] in recent_text)
        if summary_overlap:
            score += 1
            reason.append('summary_overlap')
        # actor/object overlap 只能算弱相关；若没有 clue 或 summary 的辅助命中，不足以触发旧事件回流
        if score > 0 and (clue_overlap or summary_overlap or (actor_overlap and clue_overlap) or (object_overlap and clue_overlap)):
            hits.append({'event_id': item.get('event_id'), 'turn_id': item.get('turn_id'), 'score': score, 'reason': '+'.join(reason)})
    hits.sort(key=lambda x: -x['score'])
    return hits[:3]


def build_selector_decision(*, state_json: dict, recent_history: list[dict], keeper_records: dict, active_threads: list[dict], important_npcs: list[dict], onstage: list[str], relevant: list[str], lorebook_entries: list[dict], system_npc_candidates: list[dict], lorebook_npc_candidates: list[dict], event_summaries: list[dict], summary_text: str) -> dict:
    inject_lorebook = should_inject_lorebook_text(state_json, recent_history, keeper_records, lorebook_entries, active_threads)
    all_candidates = list(system_npc_candidates) + list(lorebook_npc_candidates)
    inject_candidates = should_inject_npc_candidates(onstage, relevant, active_threads, recent_history, important_npcs, all_candidates)
    targets = profile_targets(onstage, relevant, active_threads, recent_history, important_npcs, limit=3)
    event_hits = event_summary_hits(
        event_summaries,
        recent_history=recent_history,
        active_threads=active_threads,
        important_npcs=important_npcs,
        tracked_objects=state_json.get('tracked_objects', []),
        carryover_clues=state_json.get('carryover_clues', []),
    )
    inject_summary = bool(event_hits) and any(hit.get('score', 0) >= 3 for hit in event_hits) and bool(str(summary_text or '').strip())
    npc_roster = build_npc_roster(
        onstage=onstage,
        relevant=relevant,
        active_threads=active_threads,
        important_npcs=important_npcs,
        event_hits=event_hits,
        event_summaries=event_summaries,
        limit=5,
    )
    return {
        'selector_version': 2,
        'inject_lorebook_text': inject_lorebook,
        'inject_npc_candidates': inject_candidates,
        'npc_profile_targets': targets,
        'event_hits': event_hits,
        'inject_summary': inject_summary,
        'npc_roster': npc_roster,
    }
