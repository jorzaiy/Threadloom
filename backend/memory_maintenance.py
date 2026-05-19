#!/usr/bin/env python3
from __future__ import annotations

import copy
from typing import Any

try:
    from .keeper_archive import build_keeper_record_archive, load_keeper_record_archive, save_keeper_record_archive, validate_keeper_archive
    from .runtime_store import load_event_summaries, load_state, load_summary_chunks, save_event_summaries, save_state, save_summary_chunks
    from .summary_chunks import update_summary_chunks
except ImportError:
    from keeper_archive import build_keeper_record_archive, load_keeper_record_archive, save_keeper_record_archive, validate_keeper_archive
    from runtime_store import load_event_summaries, load_state, load_summary_chunks, save_event_summaries, save_state, save_summary_chunks
    from summary_chunks import update_summary_chunks


def _clean_text(value: Any) -> str:
    return str(value or '').strip()


def _dedupe(items: list[str]) -> list[str]:
    out: list[str] = []
    for item in items:
        text = _clean_text(item)
        if text and text not in out:
            out.append(text)
    return out


def actor_alias_map(state: dict) -> dict[str, str]:
    """Return exact alias/name -> canonical actor name map from actor registry.

    This is intentionally conservative: only aliases already recorded on an
    actor are migrated. It does not infer two actors are the same by prose.
    """
    canonical_names: set[str] = set()
    alias_candidates: dict[str, set[str]] = {}
    actors = state.get('actors', {}) if isinstance(state.get('actors', {}), dict) else {}
    for actor in actors.values():
        if not isinstance(actor, dict) or actor.get('kind') == 'protagonist':
            continue
        canonical = _clean_text(actor.get('name'))
        if not canonical:
            continue
        canonical_names.add(canonical)
        for alias in actor.get('aliases', []) if isinstance(actor.get('aliases', []), list) else []:
            text = _clean_text(alias)
            if text:
                alias_candidates.setdefault(text, set()).add(canonical)
    mapping: dict[str, str] = {name: name for name in canonical_names}
    for alias, targets in alias_candidates.items():
        if alias in canonical_names or len(targets) != 1:
            continue
        mapping[alias] = next(iter(targets))
    return mapping


def _canon_name(value: Any, mapping: dict[str, str]) -> str:
    text = _clean_text(value)
    return mapping.get(text, text)


def _actor_id_for_name(state: dict, name: str) -> str:
    target = _clean_text(name)
    actors = state.get('actors', {}) if isinstance(state.get('actors', {}), dict) else {}
    for actor_id, actor in actors.items():
        if not isinstance(actor, dict):
            continue
        if _clean_text(actor.get('name')) == target:
            return str(actor_id)
    return ''


def canonicalize_state_memory(state: dict) -> tuple[dict, list[dict]]:
    current = copy.deepcopy(state) if isinstance(state, dict) else {}
    changes: list[dict] = []
    mapping = actor_alias_map(current)
    if not mapping:
        return current, changes

    def canon_list(values: Any) -> list[str]:
        if not isinstance(values, list):
            return []
        return _dedupe([_canon_name(item, mapping) for item in values])

    for field in ('onstage_npcs', 'relevant_npcs'):
        before = current.get(field, []) if isinstance(current.get(field, []), list) else []
        after = canon_list(before)
        if after != before:
            current[field] = after
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': field, 'before': before, 'after': after})

    for entity in current.get('scene_entities', []) if isinstance(current.get('scene_entities', []), list) else []:
        if not isinstance(entity, dict):
            continue
        old_label = _clean_text(entity.get('primary_label'))
        new_label = _canon_name(old_label, mapping)
        if new_label and new_label != old_label:
            aliases = entity.get('aliases', []) if isinstance(entity.get('aliases', []), list) else []
            entity['aliases'] = _dedupe([old_label] + [_canon_name(item, mapping) for item in aliases])
            entity['primary_label'] = new_label
            entity['role_label'] = new_label if _clean_text(entity.get('role_label')) == old_label else entity.get('role_label', '')
            actor_id = _actor_id_for_name(current, new_label)
            if actor_id:
                entity['possible_link'] = actor_id
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'scene_entities.primary_label', 'before': old_label, 'after': new_label})
        elif new_label:
            actor_id = _actor_id_for_name(current, new_label)
            if actor_id and not entity.get('possible_link'):
                entity['possible_link'] = actor_id
                changes.append({'artifact': 'state', 'action': 'bind_actor', 'field': 'scene_entities.possible_link', 'label': new_label, 'actor_id': actor_id})

    for thread in current.get('active_threads', []) if isinstance(current.get('active_threads', []), list) else []:
        if not isinstance(thread, dict):
            continue
        before = thread.get('actors', []) if isinstance(thread.get('actors', []), list) else []
        after = canon_list(before)
        if after != before:
            thread['actors'] = after
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'active_threads.actors', 'before': before, 'after': after})

    for item in current.get('important_npcs', []) if isinstance(current.get('important_npcs', []), list) else []:
        if not isinstance(item, dict):
            continue
        old = _clean_text(item.get('primary_label'))
        new = _canon_name(old, mapping)
        if new and new != old:
            item['primary_label'] = new
            item['key'] = f'important:{new}'
            aliases = item.get('aliases', []) if isinstance(item.get('aliases', []), list) else []
            item['aliases'] = _dedupe([old] + [_canon_name(alias, mapping) for alias in aliases])
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'important_npcs.primary_label', 'before': old, 'after': new})

    for item in current.get('possession_state', []) if isinstance(current.get('possession_state', []), list) else []:
        if not isinstance(item, dict):
            continue
        old = _clean_text(item.get('holder'))
        new = _canon_name(old, mapping)
        if new and new != old:
            item['holder'] = new
            actor_id = _actor_id_for_name(current, new)
            if actor_id:
                item['holder_actor_id'] = actor_id
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'possession_state.holder', 'before': old, 'after': new})

    for item in current.get('object_visibility', []) if isinstance(current.get('object_visibility', []), list) else []:
        if not isinstance(item, dict):
            continue
        before = item.get('known_to', []) if isinstance(item.get('known_to', []), list) else []
        after = canon_list(before)
        if after != before:
            item['known_to'] = after
            item['known_to_actor_ids'] = _dedupe([_actor_id_for_name(current, name) for name in after if _actor_id_for_name(current, name)])
            changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'object_visibility.known_to', 'before': before, 'after': after})

    scope = current.get('knowledge_scope', {}) if isinstance(current.get('knowledge_scope', {}), dict) else {}
    npc_local = scope.get('npc_local', {}) if isinstance(scope.get('npc_local', {}), dict) else {}
    merged: dict[str, dict] = {}
    scope_changed = False
    for raw_name, payload in npc_local.items():
        name = _canon_name(raw_name, mapping)
        if name != raw_name:
            scope_changed = True
        existing = merged.setdefault(name, {'learned': []})
        learned = payload.get('learned', []) if isinstance(payload, dict) and isinstance(payload.get('learned', []), list) else []
        existing['learned'] = _dedupe(existing.get('learned', []) + [_clean_text(item) for item in learned])
    if scope_changed:
        scope['npc_local'] = merged
        current['knowledge_scope'] = scope
        changes.append({'artifact': 'state', 'action': 'canonicalize', 'field': 'knowledge_scope.npc_local'})

    return current, changes


STALE_WAITING_TERMS = ('仍在门外等待', '还在门外等待', '门外等待', '在走廊等待', '等在门外')


def resolve_stale_state_threads(state: dict) -> tuple[dict, list[dict]]:
    current = copy.deepcopy(state) if isinstance(state, dict) else {}
    changes: list[dict] = []
    onstage = set(current.get('onstage_npcs', []) if isinstance(current.get('onstage_npcs', []), list) else [])
    if not onstage:
        return current, changes

    def stale_waiting(text: str) -> str:
        value = _clean_text(text)
        if not value or not any(term in value for term in STALE_WAITING_TERMS):
            return ''
        for name in onstage:
            if name and name in value:
                return name
        return ''

    for field in ('immediate_risks', 'carryover_clues'):
        before = current.get(field, []) if isinstance(current.get(field, []), list) else []
        after = [item for item in before if not stale_waiting(str(item or ''))]
        if after != before:
            current[field] = after
            changes.append({'artifact': 'state', 'action': 'prune_stale_signal', 'field': field, 'before_count': len(before), 'after_count': len(after)})

    signals = current.get('carryover_signals', []) if isinstance(current.get('carryover_signals', []), list) else []
    kept_signals = []
    for signal in signals:
        text = signal.get('text', '') if isinstance(signal, dict) else str(signal or '')
        if not stale_waiting(text):
            kept_signals.append(signal)
    if kept_signals != signals:
        current['carryover_signals'] = kept_signals
        changes.append({'artifact': 'state', 'action': 'prune_stale_signal', 'field': 'carryover_signals', 'before_count': len(signals), 'after_count': len(kept_signals)})

    threads = current.get('active_threads', []) if isinstance(current.get('active_threads', []), list) else []
    kept_threads = []
    threads_changed = False
    for thread in threads:
        if not isinstance(thread, dict):
            threads_changed = True
            continue
        label_text = _clean_text(thread.get('label'))
        obstacle_text = _clean_text(thread.get('obstacle'))
        thread_text = ' '.join(_clean_text(thread.get(field)) for field in ('label', 'goal', 'obstacle', 'latest_change'))
        if stale_waiting(label_text) or (_clean_text(thread.get('kind')) == 'risk' and stale_waiting(thread_text)):
            done = dict(thread)
            done['status'] = 'resolved'
            done['resolved_reason'] = 'actor_now_onstage'
            current.setdefault('resolved_events', [])
            if isinstance(current['resolved_events'], list):
                current['resolved_events'].append(done)
            changes.append({'artifact': 'state', 'action': 'resolve_stale_thread', 'thread_id': thread.get('thread_id'), 'label': thread.get('label')})
            threads_changed = True
            continue
        if stale_waiting(obstacle_text):
            thread = dict(thread)
            thread['obstacle'] = ''
            changes.append({'artifact': 'state', 'action': 'clear_stale_thread_obstacle', 'thread_id': thread.get('thread_id'), 'before': obstacle_text})
            threads_changed = True
        kept_threads.append(thread)
    if threads_changed:
        current['active_threads'] = kept_threads
    return current, changes


def canonicalize_event_summaries(payload: dict, mapping: dict[str, str]) -> tuple[dict, list[dict]]:
    data = copy.deepcopy(payload) if isinstance(payload, dict) else {'version': 1, 'items': []}
    changes: list[dict] = []
    for item in data.get('items', []) if isinstance(data.get('items', []), list) else []:
        if not isinstance(item, dict):
            continue
        before = item.get('actors', []) if isinstance(item.get('actors', []), list) else []
        after = _dedupe([_canon_name(actor, mapping) for actor in before])
        if after != before:
            item['actors'] = after
            changes.append({'artifact': 'event_summaries', 'action': 'canonicalize', 'event_id': item.get('event_id'), 'before': before, 'after': after})
    return data, changes


def canonicalize_summary_chunks(payload: dict, mapping: dict[str, str]) -> tuple[dict, list[dict]]:
    data = copy.deepcopy(payload) if isinstance(payload, dict) else {'version': 1, 'chunks': []}
    changes: list[dict] = []
    for chunk in data.get('chunks', []) if isinstance(data.get('chunks', []), list) else []:
        if not isinstance(chunk, dict):
            continue
        for field in ('actors_mentioned', 'keywords'):
            before = chunk.get(field, []) if isinstance(chunk.get(field, []), list) else []
            after = _dedupe([_canon_name(value, mapping) for value in before])
            if after != before:
                chunk[field] = after
                changes.append({'artifact': 'summary_chunks', 'action': 'canonicalize', 'chunk_id': chunk.get('chunk_id'), 'field': field})
    return data, changes


def canonicalize_keeper_archive(payload: dict, mapping: dict[str, str]) -> tuple[dict, list[dict]]:
    data = copy.deepcopy(payload) if isinstance(payload, dict) else {'version': 1, 'records': []}
    changes: list[dict] = []
    for record in data.get('records', []) if isinstance(data.get('records', []), list) else []:
        if not isinstance(record, dict):
            continue
        for entity in record.get('stable_entities', []) if isinstance(record.get('stable_entities', []), list) else []:
            if not isinstance(entity, dict):
                continue
            old = _clean_text(entity.get('name'))
            new = _canon_name(old, mapping)
            if new and new != old:
                entity['name'] = new
                changes.append({'artifact': 'keeper_archive', 'action': 'canonicalize', 'field': 'stable_entities.name', 'before': old, 'after': new})
    registry = data.get('npc_registry', {}) if isinstance(data.get('npc_registry', {}), dict) else {}
    for entity in registry.get('entities', []) if isinstance(registry.get('entities', []), list) else []:
        if not isinstance(entity, dict):
            continue
        for field in ('primary_label', 'name'):
            old = _clean_text(entity.get(field))
            new = _canon_name(old, mapping)
            if new and new != old:
                entity[field] = new
                changes.append({'artifact': 'keeper_archive', 'action': 'canonicalize', 'field': f'npc_registry.{field}', 'before': old, 'after': new})
    return data, changes


def repair_memory(session_id: str, *, dry_run: bool = True, rebuild_derived: bool = False, allow_archive_write: bool = True) -> dict:
    report = {'session_id': session_id, 'dry_run': dry_run, 'changes': [], 'warnings': [], 'counts': {}}
    state = load_state(session_id)
    state, state_changes = canonicalize_state_memory(state)
    state, stale_changes = resolve_stale_state_threads(state)
    report['changes'].extend(state_changes + stale_changes)
    mapping = actor_alias_map(state)
    if not dry_run and (state_changes or stale_changes):
        save_state(session_id, state)

    events, event_changes = canonicalize_event_summaries(load_event_summaries(session_id), mapping)
    report['changes'].extend(event_changes)
    if not dry_run and event_changes:
        save_event_summaries(session_id, events)

    if rebuild_derived and not dry_run:
        save_summary_chunks(session_id, {'version': 1, 'chunks': []})
        chunks = update_summary_chunks(session_id, use_llm=False)
        report['changes'].append({'artifact': 'summary_chunks', 'action': 'rebuild_missing', 'created': bool(chunks.get('created'))})
    else:
        chunks, chunk_changes = canonicalize_summary_chunks(load_summary_chunks(session_id), mapping)
        report['changes'].extend(chunk_changes)
        if not dry_run and chunk_changes:
            save_summary_chunks(session_id, chunks)

    archive = load_keeper_record_archive(session_id, skip_bootstrap=True, use_llm=False, allow_archive_write=False)
    if rebuild_derived and not dry_run:
        archive = build_keeper_record_archive(session_id, skip_bootstrap=True, use_llm=False)
        report['changes'].append({'artifact': 'keeper_archive', 'action': 'rebuild'})
    archive, archive_changes = canonicalize_keeper_archive(archive, mapping)
    archive, validation = validate_keeper_archive(archive)
    report['changes'].extend(archive_changes + validation.get('changes', []))
    report['warnings'].extend(validation.get('warnings', []))
    if not dry_run and allow_archive_write and (archive_changes or validation.get('changed') or rebuild_derived):
        save_keeper_record_archive(session_id, archive)

    report['counts'] = {
        'changes': len(report['changes']),
        'warnings': len(report['warnings']),
    }
    return report
