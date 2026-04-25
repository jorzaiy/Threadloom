#!/usr/bin/env python3
from __future__ import annotations

from copy import deepcopy


def _dedupe_text(items: list[str], limit: int | None = None) -> list[str]:
    out: list[str] = []
    for item in items or []:
        text = str(item or '').strip()
        if not text or text in out:
            continue
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def _replace_exact_label(text: str, old: str, new: str) -> str:
    if not old or not new or old == new:
        return str(text or '')
    return str(text or '').replace(old, new)


def _entity_matches_ref(entity: dict, entity_ref: str) -> bool:
    if not isinstance(entity, dict):
        return False
    ref = str(entity_ref or '').strip()
    if not ref:
        return False
    names = {str(entity.get('primary_label', '') or '').strip()}
    names.update(str(alias or '').strip() for alias in (entity.get('aliases', []) or []) if str(alias or '').strip())
    return ref in names


def apply_event_status_transitions(state: dict, ledger: dict) -> dict:
    """Merge event-ledger status transitions back into runtime state."""
    next_state = deepcopy(state or {})
    transitions = ledger.get('status_transitions', []) if isinstance(ledger, dict) else []
    if not isinstance(transitions, list):
        return next_state
    entities = next_state.get('scene_entities', []) if isinstance(next_state.get('scene_entities', []), list) else []

    for transition in transitions:
        if not isinstance(transition, dict):
            continue
        entity_ref = str(transition.get('entity_ref', '') or '').strip()
        primary_label = str(transition.get('primary_label', '') or '').strip()
        status_note = str(transition.get('status_note', '') or '').strip()
        if not entity_ref:
            continue

        matched_entity = next((item for item in entities if _entity_matches_ref(item, entity_ref)), None)
        old_label = str((matched_entity or {}).get('primary_label', '') or entity_ref).strip()
        if matched_entity and primary_label and primary_label != old_label:
            aliases = [str(alias or '').strip() for alias in (matched_entity.get('aliases', []) or []) if str(alias or '').strip()]
            for alias in (old_label, entity_ref):
                if alias and alias != primary_label and alias not in aliases:
                    aliases.append(alias)
            matched_entity['primary_label'] = primary_label
            matched_entity['aliases'] = aliases[:6]
        if matched_entity and 'onstage' in transition:
            matched_entity['onstage'] = bool(transition.get('onstage'))
        if matched_entity and status_note:
            matched_entity['status_note'] = status_note

        if primary_label and primary_label != old_label:
            for field in ('onstage_npcs', 'relevant_npcs'):
                values = next_state.get(field, []) if isinstance(next_state.get(field, []), list) else []
                next_state[field] = _dedupe_text([primary_label if str(item or '').strip() in {old_label, entity_ref} else str(item or '').strip() for item in values], limit=6)
            for field in ('main_event', 'immediate_goal'):
                next_state[field] = _replace_exact_label(next_state.get(field, ''), old_label, primary_label)
                next_state[field] = _replace_exact_label(next_state.get(field, ''), entity_ref, primary_label)
            for field in ('immediate_risks', 'carryover_clues'):
                values = next_state.get(field, []) if isinstance(next_state.get(field, []), list) else []
                next_state[field] = _dedupe_text([
                    _replace_exact_label(_replace_exact_label(str(item or ''), old_label, primary_label), entity_ref, primary_label)
                    for item in values
                ], limit=6)
            for item in next_state.get('active_threads', []) or []:
                if not isinstance(item, dict):
                    continue
                for field in ('label', 'goal', 'obstacle', 'latest_change'):
                    item[field] = _replace_exact_label(_replace_exact_label(item.get(field, ''), old_label, primary_label), entity_ref, primary_label)
                actors = item.get('actors', []) if isinstance(item.get('actors', []), list) else []
                item['actors'] = _dedupe_text([primary_label if str(actor or '').strip() in {old_label, entity_ref} else str(actor or '').strip() for actor in actors], limit=4)
        if status_note:
            clues = next_state.get('carryover_clues', []) if isinstance(next_state.get('carryover_clues', []), list) else []
            next_state['carryover_clues'] = _dedupe_text(clues + [status_note], limit=6)

    if entities:
        next_state['scene_entities'] = entities
        onstage_from_entities = [str(item.get('primary_label', '') or '').strip() for item in entities if isinstance(item, dict) and item.get('onstage') and str(item.get('primary_label', '') or '').strip()]
        if onstage_from_entities:
            next_state['onstage_npcs'] = _dedupe_text(onstage_from_entities, limit=6)
            relevant = next_state.get('relevant_npcs', []) if isinstance(next_state.get('relevant_npcs', []), list) else []
            next_state['relevant_npcs'] = _dedupe_text([name for name in relevant if name not in next_state['onstage_npcs']], limit=6)
    return next_state
