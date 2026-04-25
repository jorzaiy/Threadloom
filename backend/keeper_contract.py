#!/usr/bin/env python3
from __future__ import annotations


SCENE_CORE_FIELDS = ('time', 'location', 'main_event', 'immediate_goal')
ACTOR_FIELDS = ('onstage_npcs', 'relevant_npcs', 'scene_entities')
SIGNAL_FIELDS = ('carryover_signals', 'immediate_risks', 'carryover_clues')
OBJECT_FIELDS = ('tracked_objects', 'possession_state', 'object_visibility')
KNOWLEDGE_FIELDS = ('knowledge_scope',)
EVENT_DIGEST_FIELDS = ('stable_entities', 'ongoing_events', 'tracked_objects', 'open_loops', 'history_digest')

KEEPER_STATE_FIELDS = (
    *SCENE_CORE_FIELDS,
    *ACTOR_FIELDS,
    *SIGNAL_FIELDS,
    *OBJECT_FIELDS,
    *KNOWLEDGE_FIELDS,
)

ENTITY_TYPES = {'named_character', 'descriptive_character', 'collective_group', 'object', 'location_or_faction', 'abstract_signal'}
SIGNAL_TYPES = {'risk', 'clue', 'mixed'}
OBJECT_VISIBILITY = {'private', 'public'}


def keeper_contract_summary() -> dict:
    return {
        'scene_core': list(SCENE_CORE_FIELDS),
        'actors': list(ACTOR_FIELDS),
        'signals': list(SIGNAL_FIELDS),
        'objects': list(OBJECT_FIELDS),
        'knowledge_delta': list(KNOWLEDGE_FIELDS),
        'event_digest': list(EVENT_DIGEST_FIELDS),
        'entity_types': sorted(ENTITY_TYPES),
        'signal_types': sorted(SIGNAL_TYPES),
        'object_visibility': sorted(OBJECT_VISIBILITY),
    }


def unknown_keeper_state_fields(payload: dict) -> list[str]:
    if not isinstance(payload, dict):
        return []
    allowed = set(KEEPER_STATE_FIELDS)
    return sorted(str(key) for key in payload.keys() if str(key) not in allowed)
