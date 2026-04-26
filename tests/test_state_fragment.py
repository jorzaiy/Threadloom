#!/usr/bin/env python3
import unittest

from backend.state_fragment import merge_state_skeleton
from backend.state_bridge import normalize_state_dict
from backend.actor_registry import update_actor_registry


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

    def test_actor_registry_keeps_base_fields_immutable(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '顾青衣',
                    'aliases': ['青衣女子'],
                    'personality': '冷静',
                    'appearance': '青衣佩剑',
                    'identity': '江湖女子',
                    'created_turn': 2,
                },
            },
            'scene_entities': [
                {'primary_label': '顾青衣', 'aliases': ['顾姑娘'], 'role_label': '新身份', 'temperament': '热络', 'onstage': True},
            ],
        }

        updated = update_actor_registry(state, narrator_reply='顾青衣站在门边，没有说话。', turn_number=5, use_llm=False)

        actor = updated['actors']['npc_001']
        self.assertEqual(actor['aliases'], ['青衣女子'])
        self.assertEqual(actor['personality'], '冷静')
        self.assertEqual(actor['appearance'], '青衣佩剑')
        self.assertEqual(actor['identity'], '江湖女子')

    def test_actor_registry_archives_and_recalls_after_twelve_quiet_turns(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '顾青衣',
                    'aliases': ['青衣女子'],
                    'personality': '冷静',
                    'appearance': '青衣佩剑',
                    'identity': '江湖女子',
                    'created_turn': 1,
                },
            },
            'actor_context_index': {
                'last_mentioned_turn': {'npc_001': 1},
            },
        }

        archived = update_actor_registry(state, narrator_reply='雨声淹没了长街。', turn_number=13, use_llm=False)
        self.assertIn('npc_001', archived['actor_context_index']['archived_actor_ids'])

        recalled = update_actor_registry(archived, user_text='顾青衣现在在哪？', narrator_reply='门外传来脚步声。', turn_number=14, use_llm=False)
        self.assertIn('npc_001', recalled['actor_context_index']['active_actor_ids'])
        self.assertNotIn('npc_001', recalled['actor_context_index']['archived_actor_ids'])

    def test_actor_registry_fallback_does_not_create_from_scene_entities(self):
        state = {
            'scene_entities': [
                {'primary_label': '旧污染称呼', 'aliases': [], 'role_label': '当前互动核心人物', 'onstage': True},
            ],
        }

        updated = update_actor_registry(state, narrator_reply='雨声淹没了长街。', turn_number=3, use_llm=False)

        self.assertEqual([actor_id for actor_id in updated['actors'] if actor_id != 'protagonist'], [])

    def test_normalize_state_keeps_archived_actor_possession_holder(self):
        state = {
            'onstage_npcs': [],
            'relevant_npcs': [],
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '顾青衣',
                    'aliases': ['青衣女子'],
                    'personality': '冷静',
                    'appearance': '青衣佩剑',
                    'identity': '江湖女子',
                    'created_turn': 1,
                },
            },
            'tracked_objects': [{'object_id': 'obj_01', 'label': '铜牌', 'kind': 'key_item', 'story_relevant': True}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '青衣女子', 'status': 'held'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': '公开可见', 'known_to': ['青衣女子']}],
        }

        normalized = normalize_state_dict(state, prev_state={})

        self.assertEqual(normalized['possession_state'][0]['holder'], '青衣女子')
        self.assertEqual(normalized['possession_state'][0]['holder_actor_id'], 'npc_001')
        self.assertEqual(normalized['object_visibility'][0]['visibility'], 'private')
        self.assertEqual(normalized['object_visibility'][0]['known_to_actor_ids'], ['npc_001'])

    def test_normalize_state_does_not_backfill_relevant_from_threads(self):
        state = {
            'time': '夜里',
            'location': '来福客栈',
            'main_event': '主角独自整理铜牌。',
            'onstage_npcs': [],
            'relevant_npcs': [],
            'active_threads': [
                {
                    'thread_id': 'thread_001',
                    'kind': 'main',
                    'label': '旧人物追索铜牌',
                    'actors': ['旧人物'],
                },
            ],
        }

        normalized = normalize_state_dict(state, prev_state={})

        self.assertEqual(normalized['relevant_npcs'], [])
        self.assertEqual(normalized['scene_entities'], [])
        self.assertEqual(normalized['main_event'], '主角独自整理铜牌。')

    def test_normalize_state_accepts_main_event_without_npc_name(self):
        prev = {
            'main_event': '陆小环在茶棚试探老汉。',
            'onstage_npcs': ['瘦长中年人', '花白老妇'],
            'scene_entities': [
                {'primary_label': '瘦长中年人', 'onstage': True},
                {'primary_label': '花白老妇', 'onstage': True},
            ],
        }
        state = {
            **prev,
            'main_event': '陆小环转入药铺试探昨夜伤客线索，门外有人驻足窃听。',
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['main_event'], '陆小环转入药铺试探昨夜伤客线索，门外有人驻足窃听。')

    def test_actor_registry_binds_items_and_knowledge_to_actor_ids(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '顾青衣',
                    'aliases': ['青衣女子'],
                    'personality': '冷静',
                    'appearance': '青衣佩剑',
                    'identity': '江湖女子',
                    'created_turn': 1,
                },
            },
            'possession_state': [{'object_id': 'obj_01', 'holder': '青衣女子', 'status': 'held'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['青衣女子', '主角']}],
            'knowledge_scope': {
                'protagonist': {'learned': ['铜牌上有残纹']},
                'npc_local': {'青衣女子': {'learned': ['铜牌来自旧案']}}
            },
        }

        updated = update_actor_registry(state, narrator_reply='顾青衣收起铜牌。', turn_number=2, use_llm=False)

        self.assertEqual(updated['possession_state'][0]['holder_actor_id'], 'npc_001')
        self.assertEqual(updated['object_visibility'][0]['known_to_actor_ids'], ['npc_001', 'protagonist'])
        self.assertIn({'holder_actor_id': 'npc_001', 'text': '铜牌来自旧案', 'source_turn': 2}, updated['knowledge_records'])
        self.assertIn({'holder_actor_id': 'protagonist', 'text': '铜牌上有残纹', 'source_turn': 2}, updated['knowledge_records'])


if __name__ == '__main__':
    unittest.main()
