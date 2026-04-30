#!/usr/bin/env python3
import unittest
from typing import Any
from unittest.mock import patch

from backend.state_fragment import extract_reply_skeleton, merge_reply_skeleton, merge_state_skeleton
from backend import state_keeper
from backend.state_bridge import normalize_state_dict
from backend.thread_tracker import apply_thread_tracker
from backend.actor_registry import update_actor_registry
from backend.arbiter_state import merge_arbiter_state
from backend.state_keeper import _call_state_keeper_llm, _merge_keeper_fill, _parse_fill_payload
from backend.state_bridge import derive_risks_clues_from_signals, entity_descriptor_signature, entity_labels_compatible, normalize_carryover_signals, normalize_keeper_object_label
from backend.handler_message import _keeper_fallback_bootstrapped


class StateFragmentTest(unittest.TestCase):
    def test_shared_normalization_helpers_preserve_current_contract(self):
        self.assertEqual(entity_descriptor_signature('灰衣人'), '灰衣')
        self.assertTrue(entity_labels_compatible('灰衣人', '灰衣'))
        self.assertFalse(entity_labels_compatible('暗影', '暗'))
        self.assertEqual(normalize_keeper_object_label('纸封（坊署证物）'), '纸封')

        signals = normalize_carryover_signals([
            {'type': 'risk', 'text': '巡捕仍在盘查'},
            {'type': 'risk', 'text': '巡捕仍在盘查'},
            {'type': 'clue', 'text': '纸封未拆'},
            '掌柜仍在隐瞒账册',
        ])
        self.assertEqual(signals, [
            {'type': 'risk', 'text': '巡捕仍在盘查'},
            {'type': 'clue', 'text': '纸封未拆'},
            {'type': 'mixed', 'text': '掌柜仍在隐瞒账册'},
        ])
        self.assertEqual(derive_risks_clues_from_signals(signals), (
            ['巡捕仍在盘查', '掌柜仍在隐瞒账册'],
            ['纸封未拆', '掌柜仍在隐瞒账册'],
        ))

    def test_state_keeper_returns_state_but_does_not_own_persistence(self):
        self.assertFalse(hasattr(state_keeper, 'save_state'))


    def test_normalize_state_does_not_inherit_stale_arbiter_signals(self):
        prev: dict[str, Any] = {
            'time': '夜里',
            'location': '巷口',
            'main_event': '旧潜行风险仍未裁定。',
            'arbiter_signals': {
                'events': [{'event_id': 'event-stealth-001', 'result': 'stealth_risk_needs_resolution', 'dice_needed': True}],
                'flags': {'stealth_risk': 'elevated'},
            },
        }
        current = {'time': '后半夜', 'location': '空屋', 'main_event': '主角睡下。'}

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual(normalized['arbiter_signals'], {})

    def test_merge_arbiter_state_clears_signals_when_not_needed(self):
        state = {
            'immediate_risks': ['当前潜行或压低动静的动作存在暴露风险。', '年轻男子伤势仍需看护。'],
            'carryover_clues': ['潜行是否已经惊动观察者，仍需在后续回合继续确认。', '纸封是围杀关键物证。'],
            'arbiter_signals': {
                'events': [{'event_id': 'event-stealth-001', 'result': 'stealth_risk_needs_resolution', 'dice_needed': True}],
                'flags': {'stealth_risk': 'elevated'},
            },
        }

        merged = merge_arbiter_state(state, {'arbiter_needed': False, 'results': []})

        self.assertEqual(merged['arbiter_signals'], {'events': [], 'flags': {}})
        self.assertEqual(merged['immediate_risks'], ['年轻男子伤势仍需看护。'])
        self.assertEqual(merged['carryover_clues'], ['纸封是围杀关键物证。'])

    def test_extract_reply_skeleton_uses_scene_header_and_first_sentence(self):
        reply = '【清早，医馆门前】\n\n陆小环拎着医箱跨过门槛，扬声招呼东家。\n\n屋里药气未散。'

        skeleton = extract_reply_skeleton(reply)

        self.assertEqual(skeleton['time'], '清早')
        self.assertEqual(skeleton['location'], '医馆门前')
        self.assertEqual(skeleton['main_event'], '陆小环拎着医箱跨过门槛，扬声招呼东家。')

    def test_merge_reply_skeleton_advances_stale_fragment_without_llm(self):
        fragment = {
            'time': '后半夜',
            'location': '坊署偏东空屋',
            'main_event': '陆小环在偏东空屋内沐浴驱寒。',
            'immediate_goal': '起身擦干。',
        }
        reply = '【清早，医馆门前】\n\n陆小环拎着医箱跨过门槛，声音先一步进了屋。'

        merged = merge_reply_skeleton(fragment, reply)

        self.assertEqual(merged['time'], '清早')
        self.assertEqual(merged['location'], '医馆门前')
        self.assertEqual(merged['main_event'], '陆小环拎着医箱跨过门槛，声音先一步进了屋。')

    def test_state_keeper_llm_retries_once_on_empty_output(self):
        usage = {'model': 'test-model', 'finish_reason': 'stop'}
        with patch('backend.state_keeper.call_role_llm', side_effect=[('', dict(usage)), ('{"carryover_signals": []}', dict(usage))]) as mocked:
            reply, final_usage, attempts = _call_state_keeper_llm('prompt')

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(attempts, 2)
        self.assertEqual(reply, '{"carryover_signals": []}')
        self.assertEqual(final_usage['retry_count'], 1)

    def test_state_keeper_llm_retries_once_on_unparsable_output(self):
        usage = {'model': 'test-model', 'finish_reason': 'stop'}
        with patch('backend.state_keeper.call_role_llm', side_effect=[('not json', dict(usage)), ('{"carryover_signals": []}', dict(usage))]) as mocked:
            reply, final_usage, attempts = _call_state_keeper_llm('prompt')

        self.assertEqual(mocked.call_count, 2)
        self.assertEqual(attempts, 2)
        self.assertEqual(reply, '{"carryover_signals": []}')
        self.assertEqual(final_usage['retry_count'], 1)

    def test_keeper_fallback_with_usable_fragment_exits_bootstrap_mode(self):
        fragment_state = {
            'time': '近午',
            'location': '医馆前堂',
            'main_event': '坊署跑腿来医馆对昨夜伤者账目。',
            'immediate_goal': '把账对清。',
            'onstage_npcs': ['莫大夫', '跑腿汉子'],
        }

        self.assertTrue(_keeper_fallback_bootstrapped(fragment_state, None))

    def test_keeper_fallback_with_pending_fragment_stays_unbootstrapped(self):
        fragment_state = {
            'time': '待确认',
            'location': '待确认',
            'main_event': '',
            'immediate_goal': '',
            'onstage_npcs': [],
        }

        self.assertFalse(_keeper_fallback_bootstrapped(fragment_state, None))

    def test_parse_fill_payload_salvages_object_and_knowledge_from_bad_json(self):
        text = '''{
          "tracked_objects": [
            {"object_id":"obj_06","label":"纸封","kind":"evidence","story_relevant":true}
          ],
          "possession_state": [
            {"object_id":"obj_06","holder":"巡捕","status":"evidence","location":"神都坊署"}
          ],
          "object_visibility": [
            {"object_id":"obj_06","visibility":"private","known_to":["巡捕","文吏"]}
          ],
          "knowledge_scope": {
            "protagonist": {"learned": ["纸封内容未公开"]}
          },
          "broken": [
        '''

        payload = _parse_fill_payload(text)

        self.assertEqual(payload['tracked_objects'][0]['label'], '纸封')
        self.assertEqual(payload['possession_state'][0]['holder'], '巡捕')
        self.assertEqual(payload['object_visibility'][0]['visibility'], 'private')
        self.assertEqual(payload['knowledge_scope']['protagonist']['learned'], ['纸封内容未公开'])

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
        prev: dict[str, Any] = {
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

    def test_actor_registry_parse_failure_preserves_usage_and_raw_reply_diagnostics(self):
        usage = {'model': 'test-model', 'input_tokens': 10, 'output_tokens': 0}

        with patch('backend.actor_registry.call_role_llm', return_value=('', usage)):
            updated = update_actor_registry({}, narrator_reply='雨声淹没了长街。', turn_number=3, use_llm=True)

        diagnostics = updated['actor_registry_diagnostics']
        self.assertTrue(diagnostics['fallback_used'])
        self.assertEqual(diagnostics['model_usage'], usage)
        self.assertTrue(diagnostics['raw_reply_empty'])
        self.assertEqual(diagnostics['raw_reply_excerpt'], '')
        self.assertIn('Failed to parse JSON', diagnostics['error'])

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

    def test_normalize_state_rejects_scene_title_fragment_as_npc(self):
        main_event = '**2026年4月28日 清晨，训练场跑道。** 维克托独自在跑道上调整呼吸。'
        state = {
            'time': '2026年4月28日 清晨',
            'location': '训练场跑道',
            'main_event': main_event,
            'onstage_npcs': ['训练场跑'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '训练场跑',
                    'aliases': ['训练场跑'],
                    'role_label': '当前互动核心人物',
                    'onstage': True,
                },
            ],
        }

        normalized = normalize_state_dict(state, prev_state={})
        threaded = apply_thread_tracker(normalized, narrator_reply=main_event)

        self.assertEqual(normalized['onstage_npcs'], [])
        self.assertEqual(normalized['scene_entities'], [])
        self.assertNotIn('训练场跑', threaded['active_threads'][0]['actors'])

    def test_normalize_state_keeps_action_anchored_people_as_npcs(self):
        state = {
            'time': '清晨',
            'location': '村口',
            'main_event': '老汉低声提醒她城里不太平，学徒递给她一包药。',
            'onstage_npcs': ['老汉', '学徒'],
            'scene_entities': [],
        }

        normalized = normalize_state_dict(state, prev_state={})

        self.assertEqual(normalized['onstage_npcs'], ['老汉', '学徒'])
        self.assertEqual([item['primary_label'] for item in normalized['scene_entities']], ['老汉', '学徒'])

    def test_normalize_state_accepts_main_event_without_npc_name(self):
        prev: dict[str, Any] = {
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

    def test_normalize_state_preserves_actor_registry_from_previous_state(self):
        prev: dict[str, Any] = {
            'time': '雨夜',
            'location': '神都东坊外巷',
            'main_event': '受伤男子被皂衣人围捕。',
            'actors': {
                'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '陆小环'},
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '提灯皂衣首领',
                    'aliases': ['提灯汉子'],
                    'personality': '沉稳果断',
                    'appearance': '皂衣提灯',
                    'identity': '自称官差，身份可疑',
                    'created_turn': 4,
                },
                'npc_002': {
                    'actor_id': 'npc_002',
                    'kind': 'npc',
                    'name': '年轻男子',
                    'aliases': ['墙边那年轻男子'],
                    'personality': '坚韧隐忍',
                    'appearance': '深色衣袍，肩侧有伤',
                    'identity': '',
                    'created_turn': 4,
                },
            },
            'actor_context_index': {
                'active_actor_ids': ['protagonist', 'npc_001', 'npc_002'],
                'archived_actor_ids': [],
                'last_mentioned_turn': {'protagonist': 4, 'npc_001': 4, 'npc_002': 4},
            },
            'knowledge_records': [{'holder_actor_id': 'npc_002', 'text': '皂衣人身份可疑', 'source_turn': 4}],
        }
        candidate = {
            'time': '雨夜',
            'location': '神都东坊外巷',
            'main_event': '陆小环扬声喊人，皂衣人急欲收尾。',
            'onstage_npcs': [],
            'scene_entities': [],
            'relevant_npcs': [],
            'actors': {
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '错误覆盖'},
            },
        }

        normalized = normalize_state_dict(candidate, prev_state=prev)

        self.assertEqual(normalized['actors']['npc_001']['name'], '提灯皂衣首领')
        self.assertEqual(normalized['actors']['npc_002']['name'], '年轻男子')
        self.assertEqual(normalized['actor_context_index']['active_actor_ids'], ['protagonist', 'npc_001', 'npc_002'])
        self.assertEqual(normalized['knowledge_records'], [{'holder_actor_id': 'npc_002', 'text': '皂衣人身份可疑', 'source_turn': 4}])

    def test_keeper_fill_empty_lists_do_not_clear_existing_records(self):
        baseline = {
            'immediate_risks': ['门外有人盯梢'],
            'carryover_clues': ['铜牌来自旧案'],
            'tracked_objects': [{'object_id': 'obj_01', 'label': '铜牌', 'kind': 'key_item'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '顾青衣', 'status': 'held'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['顾青衣']}],
        }
        payload = {
            'immediate_risks': [],
            'carryover_clues': [],
            'tracked_objects': [],
            'possession_state': [],
            'object_visibility': [],
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertEqual(merged['immediate_risks'], baseline['immediate_risks'])
        self.assertEqual(merged['carryover_clues'], baseline['carryover_clues'])
        self.assertEqual(merged['tracked_objects'], baseline['tracked_objects'])
        self.assertEqual(merged['possession_state'], baseline['possession_state'])
        self.assertEqual(merged['object_visibility'], baseline['object_visibility'])

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

    def test_knowledge_scope_is_per_turn_delta(self):
        prev = {
            'knowledge_scope': {'protagonist': {'learned': ['旧情报']}},
            'knowledge_records': [{'holder_actor_id': 'protagonist', 'text': '旧情报', 'source_turn': 1}],
        }

        normalized = normalize_state_dict({}, prev_state=prev)

        self.assertEqual(normalized['knowledge_scope'], {})
        self.assertEqual(normalized['knowledge_records'], prev['knowledge_records'])

    def test_actor_registry_dedupes_similar_knowledge_records(self):
        state = {
            'knowledge_records': [{'holder_actor_id': 'protagonist', 'text': '主角知道村长是卧底', 'source_turn': 1}],
            'knowledge_scope': {'protagonist': {'learned': ['主角了解到村长的卧底身份']}},
        }

        updated = update_actor_registry(state, narrator_reply='村长的身份再次被提起。', turn_number=2, use_llm=False)

        self.assertEqual(updated['knowledge_records'], [{'holder_actor_id': 'protagonist', 'text': '主角知道村长是卧底', 'source_turn': 1}])

    def test_possession_new_valid_holder_overrides_old_holder(self):
        prev: dict[str, Any] = {
            'actors': {
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '顾青衣', 'aliases': []},
                'npc_002': {'actor_id': 'npc_002', 'kind': 'npc', 'name': '林越', 'aliases': []},
            },
            'tracked_objects': [{'object_id': 'obj_01', 'label': '铜牌', 'kind': 'key_item'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '顾青衣', 'status': 'held'}],
        }
        state = {
            **prev,
            'onstage_npcs': ['林越'],
            'possession_state': prev['possession_state'] + [{'object_id': 'obj_01', 'holder': '林越', 'status': 'held'}],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['possession_state'][0]['holder'], '林越')
        self.assertEqual(normalized['possession_state'][0]['holder_actor_id'], 'npc_002')

    def test_possession_invalid_holder_does_not_override_old_holder(self):
        prev: dict[str, Any] = {
            'actors': {'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '顾青衣', 'aliases': []}},
            'tracked_objects': [{'object_id': 'obj_01', 'label': '铜牌', 'kind': 'key_item'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '顾青衣', 'status': 'held'}],
        }
        state = {
            **prev,
            'possession_state': prev['possession_state'] + [{'object_id': 'obj_01', 'holder': '幻觉人物', 'status': 'held'}],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['possession_state'][0]['holder'], '顾青衣')

    def test_destroyed_object_moves_to_graveyard(self):
        prev = {
            'tracked_objects': [{'object_id': 'obj_01', 'label': '纸条', 'kind': 'document'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '主角', 'status': 'held'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['主角']}],
        }
        state = {
            **prev,
            'tracked_objects': prev['tracked_objects'] + [{'object_id': 'obj_01', 'label': '纸条', 'kind': 'document', 'lifecycle_status': 'destroyed', 'lifecycle_reason': '被烧毁'}],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['tracked_objects'], [])
        self.assertEqual(normalized['possession_state'], [])
        self.assertEqual(normalized['object_visibility'], [])
        self.assertEqual(normalized['graveyard_objects'][0]['lifecycle_status'], 'destroyed')

    def test_keeper_fill_payload_overrides_baseline_object_by_id(self):
        # P1.1 regression: previously baseline + payload were concatenated, the
        # baseline copy of obj_01 won the dedupe in normalize_state_dict, and
        # the keeper's fresh data for the same object_id was discarded.
        baseline = {
            'tracked_objects': [
                {'object_id': 'obj_01', 'label': '铜牌', 'kind': 'item', 'story_relevant': True},
                {'object_id': 'obj_02', 'label': '账册', 'kind': 'document', 'story_relevant': True},
            ],
            'possession_state': [
                {'object_id': 'obj_01', 'holder': '顾青衣', 'status': 'held', 'location': '', 'updated_by_turn': ''},
            ],
            'object_visibility': [
                {'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['顾青衣'], 'note': ''},
            ],
        }
        payload = {
            'tracked_objects': [
                {'object_id': 'obj_01', 'label': '铜牌', 'kind': 'key_item', 'story_relevant': True},
            ],
            'possession_state': [
                {'object_id': 'obj_01', 'holder': '林越', 'status': 'held', 'location': '', 'updated_by_turn': ''},
            ],
            'object_visibility': [
                {'object_id': 'obj_01', 'visibility': 'public', 'known_to': ['林越', '顾青衣'], 'note': '亮在桌面'},
            ],
        }

        merged = _merge_keeper_fill(baseline, payload)

        ids = [item['object_id'] for item in merged['tracked_objects']]
        self.assertEqual(sorted(ids), ['obj_01', 'obj_02'])
        obj_01 = next(item for item in merged['tracked_objects'] if item['object_id'] == 'obj_01')
        self.assertEqual(obj_01['kind'], 'key_item')
        self.assertEqual(merged['possession_state'][0]['holder'], '林越')
        self.assertEqual(merged['object_visibility'][0]['visibility'], 'public')
        self.assertEqual(merged['object_visibility'][0]['note'], '亮在桌面')

    def test_keeper_fill_merges_knowledge_scope_with_baseline(self):
        # P1.2 regression: keeper output replaced the baseline scope outright,
        # so an opening turn's scope that hadn't been folded into knowledge_records
        # yet was lost when the next runtime turn produced its own delta.
        baseline = {
            'knowledge_scope': {
                'protagonist': {'learned': ['开局学到的旧线索']},
                'npc_local': {'顾青衣': {'learned': ['顾青衣注意到主角佩刀']}},
            },
        }
        payload = {
            'knowledge_scope': {
                'protagonist': {'learned': ['本轮新看到伤疤']},
                'npc_local': {'林越': {'learned': ['林越听见了脚步声']}},
            },
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertEqual(
            merged['knowledge_scope']['protagonist']['learned'],
            ['开局学到的旧线索', '本轮新看到伤疤'],
        )
        self.assertEqual(merged['knowledge_scope']['npc_local']['顾青衣']['learned'], ['顾青衣注意到主角佩刀'])
        self.assertEqual(merged['knowledge_scope']['npc_local']['林越']['learned'], ['林越听见了脚步声'])

    def test_keeper_fill_signals_extend_baseline_risks_and_clues(self):
        # P1.3 regression: when the keeper output one new signal, deriving risks
        # and clues replaced baseline values entirely, dropping ongoing carryovers.
        baseline = {
            'immediate_risks': ['门外巡捕仍在盘查', '同伴受伤未恢复'],
            'carryover_clues': ['纸封未拆', '账册中夹有暗号'],
        }
        payload = {
            'carryover_signals': [
                {'type': 'risk', 'text': '陌生人逼近巷口'},
            ],
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertIn('陌生人逼近巷口', merged['immediate_risks'])
        self.assertIn('门外巡捕仍在盘查', merged['immediate_risks'])
        self.assertIn('同伴受伤未恢复', merged['immediate_risks'])
        # Clues from baseline must persist when not contradicted by signals.
        self.assertIn('纸封未拆', merged['carryover_clues'])
        self.assertIn('账册中夹有暗号', merged['carryover_clues'])

    def test_extract_reply_skeleton_skips_main_event_without_terminal_punctuation(self):
        # P3.8 regression: previously the first paragraph was sliced to 100 chars
        # whenever no sentence-ending punctuation was found, leaking half-sentences
        # into main_event.
        reply = '【清早，医馆门前】\n\n陆小环拎着医箱跨过门槛声音像风穿过院落很久没有停下'

        skeleton = extract_reply_skeleton(reply)

        self.assertEqual(skeleton.get('time'), '清早')
        self.assertEqual(skeleton.get('location'), '医馆门前')
        self.assertNotIn('main_event', skeleton)

    def test_update_important_npcs_threads_allow_archive_write_to_archive_loader(self):
        # Tools (replay / rebuild) call update_important_npcs with
        # allow_archive_write=False so a stale or missing archive cache cannot
        # silently be rebuilt and persisted during read-only debugging.
        from backend import important_npc_tracker

        captured: dict[str, Any] = {}

        def fake_loader(session_id, *, allow_archive_write=True, **kwargs):
            captured['session_id'] = session_id
            captured['allow_archive_write'] = allow_archive_write
            return {'npc_registry': {'entities': []}}

        with patch.object(important_npc_tracker, 'load_keeper_record_archive', side_effect=fake_loader):
            from backend.important_npc_tracker import update_important_npcs

            state = {'session_id': 'session-isolated', 'important_npcs': []}
            update_important_npcs(state, [], None, allow_archive_write=False)

        self.assertEqual(captured.get('session_id'), 'session-isolated')
        self.assertFalse(captured.get('allow_archive_write'))


if __name__ == '__main__':
    unittest.main()
