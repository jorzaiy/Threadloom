#!/usr/bin/env python3
import unittest

from backend.state_fragment import merge_state_skeleton
from backend.state_bridge import normalize_state_dict
from backend.event_status import apply_event_status_transitions


class StateFragmentTest(unittest.TestCase):
    def test_merge_state_skeleton_updates_scene_entity_onstage_flags(self):
        fragment = {
            'onstage_npcs': ['旧人物'],
            'scene_entities': [
                {'primary_label': '旧人物', 'onstage': True},
                {'primary_label': '新人物', 'onstage': False},
            ],
        }

        merged = merge_state_skeleton(fragment, {'onstage_npcs': ['新人物']})

        self.assertEqual(merged['onstage_npcs'], ['新人物'])
        self.assertEqual(
            merged['scene_entities'],
            [
                {'primary_label': '旧人物', 'onstage': False},
                {'primary_label': '新人物', 'onstage': True},
            ],
        )

    def test_normalize_state_keeps_stable_entities_and_objects_when_candidate_is_weaker(self):
        prev = {
            'time': '夜里',
            'location': '来福客栈',
            'main_event': '客栈老板递出账册。',
            'onstage_npcs': ['来福客栈老板'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '来福客栈老板',
                    'aliases': ['客栈老板'],
                    'role_label': '来福客栈老板',
                    'onstage': True,
                    'temperament': '谨慎精明',
                },
            ],
            'tracked_objects': [
                {
                    'object_id': 'obj_01',
                    'label': '来福客栈账册',
                    'kind': 'document',
                    'story_relevant': True,
                },
            ],
        }
        candidate = {
            **prev,
            'onstage_npcs': ['客栈老板', '九芝堂老板'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_99',
                    'primary_label': '客栈老板',
                    'aliases': [],
                    'role_label': '待确认',
                    'onstage': True,
                    'temperament': '热络',
                },
                {
                    'primary_label': '九芝堂老板',
                    'aliases': [],
                    'role_label': '药铺掌柜',
                    'onstage': True,
                },
            ],
            'tracked_objects': [
                {
                    'object_id': 'obj_99',
                    'label': '账册',
                    'kind': 'item',
                    'story_relevant': True,
                },
                {
                    'object_id': 'obj_02',
                    'label': '的包',
                    'kind': 'item',
                    'story_relevant': True,
                },
            ],
        }

        normalized = normalize_state_dict(candidate, prev_state=prev)

        entities = {item['primary_label']: item for item in normalized['scene_entities']}
        self.assertIn('来福客栈老板', entities)
        self.assertIn('九芝堂老板', entities)
        self.assertEqual(entities['来福客栈老板']['entity_id'], 'scene_npc_01')
        self.assertEqual(entities['来福客栈老板']['role_label'], '来福客栈老板')
        self.assertEqual(entities['来福客栈老板']['temperament'], '谨慎精明')

        objects = {item['label']: item for item in normalized['tracked_objects']}
        self.assertIn('来福客栈账册', objects)
        self.assertNotIn('账册', objects)
        self.assertNotIn('的包', objects)
        self.assertEqual(objects['来福客栈账册']['object_id'], 'obj_01')

    def test_normalize_state_binds_owned_objects_to_npc_both_ways(self):
        state = {
            'time': '夜里',
            'location': '来福客栈',
            'main_event': '老板亮出账册。',
            'onstage_npcs': ['来福客栈老板'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '来福客栈老板',
                    'aliases': ['客栈老板'],
                    'role_label': '客栈掌柜',
                    'onstage': True,
                },
            ],
            'tracked_objects': [
                {
                    'object_id': 'obj_01',
                    'label': '来福客栈账册',
                    'kind': 'document',
                    'story_relevant': True,
                },
            ],
            'possession_state': [
                {
                    'object_id': 'obj_01',
                    'holder': '客栈老板',
                    'status': 'held',
                    'location': '',
                    'updated_by_turn': 'turn-0003',
                },
            ],
            'object_visibility': [
                {
                    'object_id': 'obj_01',
                    'visibility': 'public',
                    'known_to': ['来福客栈老板'],
                    'note': '柜台上亮出',
                },
            ],
        }

        normalized = normalize_state_dict(state, prev_state={})

        obj = normalized['tracked_objects'][0]
        self.assertEqual(obj['owner'], '来福客栈老板')
        self.assertEqual(obj['owner_type'], 'npc')
        self.assertEqual(obj['bound_entity_id'], 'scene_npc_01')
        self.assertEqual(obj['bound_entity_label'], '来福客栈老板')
        self.assertEqual(obj['possession_status'], 'held')

        self.assertEqual(normalized['possession_state'][0]['holder'], '来福客栈老板')
        entity = normalized['scene_entities'][0]
        self.assertEqual(
            entity['owned_objects'],
            [
                {
                    'object_id': 'obj_01',
                    'label': '来福客栈账册',
                    'status': 'held',
                    'visibility': 'public',
                },
            ],
        )

    def test_event_status_transition_relabels_dynamic_descriptor(self):
        state = {
            'time': '亥时初',
            'location': '乌衣巷口',
            'main_event': "陆小环一句'巡夜的差人'搅散皂衣人包围，被围男子借机脱困转向巷口。",
            'onstage_npcs': ['被围男子', '皂衣人'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '被围男子',
                    'aliases': [],
                    'role_label': '当前互动核心人物',
                    'onstage': True,
                },
                {
                    'entity_id': 'scene_npc_02',
                    'primary_label': '皂衣人',
                    'aliases': [],
                    'role_label': '当前互动核心人物',
                    'onstage': True,
                },
            ],
            'active_threads': [
                {
                    'key': 'main:被围男子皂衣人包围',
                    'label': '被围男子 / 皂衣人包围被搅散',
                    'kind': 'main',
                    'goal': '趁乱决定下一步行动',
                    'obstacle': '待确认',
                    'actors': ['被围男子', '皂衣人'],
                },
            ],
        }

        normalized = apply_event_status_transitions(state, {
            'status_transitions': [
                {
                    'entity_ref': '被围男子',
                    'primary_label': '脱困男子',
                    'onstage': True,
                    'status_note': '脱困男子已脱出原本包围，不再被困在巷心。',
                },
            ],
        })

        self.assertIn('脱困男子', normalized['onstage_npcs'])
        self.assertNotIn('被围男子', normalized['onstage_npcs'])
        entity = normalized['scene_entities'][0]
        self.assertEqual(entity['primary_label'], '脱困男子')
        self.assertIn('被围男子', entity['aliases'])
        self.assertIn('脱困男子', normalized['main_event'])
        self.assertNotIn('被围男子', normalized['main_event'])
        self.assertEqual(normalized['active_threads'][0]['actors'][0], '脱困男子')


if __name__ == '__main__':
    unittest.main()
