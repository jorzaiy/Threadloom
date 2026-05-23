#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.state_fragment import build_state_from_fragment, extract_reply_skeleton, merge_reply_skeleton, merge_state_skeleton
from backend import state_keeper
from backend.state_bridge import normalize_state_dict
from backend.thread_tracker import apply_thread_tracker
from backend.actor_registry import update_actor_registry
from backend.arbiter_state import merge_arbiter_state
from backend.state_keeper import _call_state_keeper_llm, _fill_user_prompt, _merge_keeper_fill, _parse_fill_payload, _restore_current_turn_onstage_marker
from backend.state_bridge import derive_risks_clues_from_signals, entity_descriptor_signature, entity_labels_compatible, normalize_carryover_signals, normalize_keeper_object_label
from backend.handler_message import _add_lightweight_knowledge_delta, _build_turn_audit, _is_object_heavy_turn, _keeper_fallback_bootstrapped, _redact_trace_prompt, _store_turn_audit
from backend.summary_chunks import _fallback_chunk, _normalize_chunk
from backend.memory_maintenance import actor_alias_map, canonicalize_event_summaries, canonicalize_state_memory, resolve_stale_state_threads
from backend.name_sanitizer import looks_like_non_person_alias_fragment, looks_like_low_quality_signal_fragment
from backend.runtime_store import build_state_snapshot
from backend.event_ledger import build_event_ledger, build_event_summary_item, extract_time_location_anchor


class StateFragmentTest(unittest.TestCase):
    def test_turn_trace_redacts_player_profile_detail_block(self):
        prompt = '【玩家档案】\n- 名字：测试主角\n\n【命中玩家档案细节】\n### 背景细节 / visibility=narrator_only\n- 私密旧伤\n\n### 私密边界细节 / visibility=private\n- 真实身份\n\n【最近上下文】\n正文'

        redacted = _redact_trace_prompt(prompt)

        self.assertIn('【玩家档案】', redacted)
        self.assertIn('【命中玩家档案细节】', redacted)
        self.assertNotIn('私密旧伤', redacted)
        self.assertNotIn('真实身份', redacted)
        self.assertNotIn('### 私密边界细节', redacted)
        self.assertIn('【最近上下文】', redacted)

    def test_shared_normalization_helpers_preserve_current_contract(self):
        self.assertEqual(entity_descriptor_signature('灰衣人'), '灰衣')
        self.assertTrue(entity_labels_compatible('灰衣人', '灰衣'))
        self.assertTrue(entity_labels_compatible('背纹灵貂', '灵貂'))
        self.assertTrue(entity_labels_compatible('药铺年轻男人', '年轻男人'))
        self.assertFalse(entity_labels_compatible('茶馆掌柜', '药铺掌柜'))
        self.assertFalse(entity_labels_compatible('掌柜', '茶馆掌柜'))
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

    def test_generic_non_person_filters_do_not_depend_on_card_terms(self):
        self.assertTrue(looks_like_non_person_alias_fragment('下午三点'))
        self.assertTrue(looks_like_non_person_alias_fragment('第三组'))
        self.assertTrue(looks_like_non_person_alias_fragment('两人一组'))
        self.assertTrue(looks_like_non_person_alias_fragment('训练基地'))
        self.assertFalse(looks_like_non_person_alias_fragment('秦野'))
        self.assertTrue(looks_like_low_quality_signal_fragment('惹了涂'))

    def test_signal_normalization_demotes_weak_observation_risk_to_clue(self):
        signals = normalize_carryover_signals([
            {'type': 'risk', 'text': '某人握拳又松开'},
            {'type': 'risk', 'text': '追捕者即将发现主角'},
        ])

        self.assertEqual(signals[0], {'type': 'clue', 'text': '某人握拳又松开'})
        self.assertEqual(signals[1], {'type': 'risk', 'text': '追捕者即将发现主角'})

    def test_state_keeper_returns_state_but_does_not_own_persistence(self):
        self.assertFalse(hasattr(state_keeper, 'save_state'))

    def test_keeper_fill_merges_scene_objective_without_replacing_immediate_goal(self):
        baseline = {
            'time': '中午',
            'location': '训练场',
            'main_event': '主角和对手围绕补给箱僵持。',
            'immediate_goal': '决定是否接受交换条件。',
        }
        payload = {
            'scene_objective': {
                'label': '第二轮训练',
                'objective': '测试学员在资源争夺和规则模糊下的判断能力',
                'status': 'active',
                'completion_hint': '取得补给、被承认完成或训练叫停时结束',
            }
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertEqual(merged['immediate_goal'], '决定是否接受交换条件。')
        self.assertEqual(merged['scene_objective']['label'], '第二轮训练')
        self.assertEqual(merged['scene_objective']['objective'], '测试学员在资源争夺和规则模糊下的判断能力')
        self.assertEqual(merged['scene_objective']['status'], 'active')

    def test_keeper_fill_accepts_npc_relationship_delta(self):
        baseline = {
            'time': '中午',
            'location': '训练场',
            'main_event': '主角和严教官完成一轮协作。',
            'immediate_goal': '等待严教官点评。',
        }

        merged = _merge_keeper_fill(baseline, {
            'npc_relationships': [
                {'npc': '严教官', 'label': '相知', 'evidence': '共同完成训练复盘'},
                {'npc': '主角', 'label': '好友'},
            ]
        })

        self.assertEqual(merged['npc_relationships'], [
            {'npc': '严教官', 'label': '相知', 'evidence': '共同完成训练复盘'},
            {'npc': '主角', 'label': '好友'},
        ])

    def test_actor_registry_applies_relationship_delta_to_existing_npc(self):
        state = {
            'actors': {
                'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '主角', 'aliases': ['你', '主角']},
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '严教官', 'aliases': [], 'identity': '教官'},
            },
            'npc_relationships': [
                {'npc': '严教官', 'label': '队友', 'evidence': '并肩完成夜巡'},
                {'npc': '不存在的人', 'label': '好友'},
            ],
        }

        updated = update_actor_registry(state, narrator_reply='严教官点头认可。', turn_number=7, use_llm=False)

        relationship = updated['actors']['npc_001']['relationship_to_protagonist']
        self.assertEqual(relationship['label'], '队友')
        self.assertEqual(relationship['evidence'], '并肩完成夜巡')
        self.assertEqual(relationship['updated_turn'], 7)
        self.assertNotIn('npc_relationships', updated)
        self.assertNotIn('relationship_to_protagonist', updated['actors']['protagonist'])

    def test_actor_registry_drops_ambiguous_service_aliases(self):
        state = {
            'actors': {
                'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '主角', 'aliases': ['你', '主角']},
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '茶馆掌柜', 'aliases': ['掌柜'], 'identity': '茶馆经营者'},
                'npc_002': {'actor_id': 'npc_002', 'kind': 'npc', 'name': '药铺掌柜', 'aliases': ['掌柜'], 'identity': '药铺经营者'},
            },
        }

        updated = update_actor_registry(state, narrator_reply='茶馆掌柜收起铜板。', turn_number=3, use_llm=False)

        self.assertEqual(updated['actors']['npc_001']['aliases'], [])
        self.assertEqual(updated['actors']['npc_002']['aliases'], [])

    def test_memory_maintenance_merges_actor_alias_split_npcs(self):
        state = {
            'actors': {
                'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '主角', 'aliases': ['你', '主角']},
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '年轻男人', 'aliases': ['药铺年轻男人', '青灰色短褐年轻男人']},
            },
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '年轻男人', 'aliases': ['年轻男人'], 'onstage': True},
                {'entity_id': 'scene_npc_02', 'primary_label': '药铺年轻男人', 'aliases': ['药铺年轻男人', '掌柜'], 'onstage': False},
            ],
            'important_npcs': [
                {'key': 'important:年轻男人', 'primary_label': '年轻男人', 'aliases': ['年轻男人'], 'importance_score': 4},
                {'key': 'important:药铺年轻男人', 'primary_label': '药铺年轻男人', 'aliases': ['青灰色短褐年轻男人'], 'importance_score': 8},
            ],
            'active_threads': [
                {'thread_id': 'thread_1', 'actors': ['药铺年轻男人']},
            ],
        }

        updated, changes = canonicalize_state_memory(state)

        self.assertTrue(changes)
        self.assertEqual([item['primary_label'] for item in updated['scene_entities']], ['年轻男人'])
        self.assertEqual(updated['scene_entities'][0]['aliases'], ['药铺年轻男人', '青灰色短褐年轻男人'])
        self.assertEqual([item['primary_label'] for item in updated['important_npcs']], ['年轻男人'])
        self.assertEqual(updated['important_npcs'][0]['key'], 'important:年轻男人')
        self.assertEqual(updated['important_npcs'][0]['importance_score'], 8)
        self.assertEqual(updated['active_threads'][0]['actors'], ['年轻男人'])

    def test_memory_maintenance_ignores_stale_ambiguous_service_actor_alias(self):
        state = {
            'actors': {
                'protagonist': {'actor_id': 'protagonist', 'kind': 'protagonist', 'name': '主角', 'aliases': ['你', '主角']},
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '茶馆掌柜', 'aliases': ['掌柜']},
            },
            'onstage_npcs': ['掌柜'],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '掌柜', 'aliases': ['掌柜'], 'onstage': True},
            ],
            'important_npcs': [],
            'active_threads': [
                {'thread_id': 'thread_1', 'actors': ['掌柜']},
            ],
        }

        mapping = actor_alias_map(state)
        updated, changes = canonicalize_state_memory(state)

        self.assertNotIn('掌柜', mapping)
        self.assertEqual(updated['onstage_npcs'], ['掌柜'])
        self.assertEqual(updated['scene_entities'][0]['primary_label'], '掌柜')
        self.assertEqual(updated['active_threads'][0]['actors'], ['掌柜'])
        self.assertFalse(any(change.get('before') == '掌柜' and change.get('after') == '茶馆掌柜' for change in changes))

    def test_normalize_state_preserves_scene_objective_across_turns(self):
        prev = {
            'time': '上午',
            'location': '训练场',
            'main_event': '旧事件',
            'immediate_goal': '旧目标',
            'scene_objective': {
                'label': '体能测试',
                'objective': '测试学员基础体能',
                'status': 'active',
            },
        }
        current = {
            'time': '上午',
            'location': '训练场',
            'main_event': '主角继续跑步。',
            'immediate_goal': '调整呼吸继续跑。',
        }

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual(normalized['scene_objective']['label'], '体能测试')
        self.assertEqual(normalized['scene_objective']['objective'], '测试学员基础体能')
        self.assertEqual(normalized['scene_objective']['status'], 'active')

    def test_state_snapshot_exposes_scene_objective_for_ui(self):
        snapshot = build_state_snapshot({
            'time': '中午',
            'location': '训练场',
            'main_event': '主角继续谈判。',
            'graveyard_objects': [{'object_id': 'obj_01', 'label': '旧木牌', 'lifecycle_status': 'destroyed'}],
            'scene_objective': {
                'label': '第二轮训练',
                'objective': '测试资源争夺和规则判断',
                'status': 'active',
            },
        })

        self.assertEqual(snapshot['scene_objective']['label'], '第二轮训练')
        self.assertEqual(snapshot['scene_objective']['objective'], '测试资源争夺和规则判断')
        self.assertEqual(snapshot['scene_objective']['status'], 'active')
        self.assertEqual(snapshot['graveyard_objects'][0]['object_id'], 'obj_01')

    def test_keeper_fill_prompt_requires_missing_scene_objective(self):
        prompt = _fill_user_prompt(
            {
                'time': '清晨',
                'location': '训练场跑道',
                'main_event': '学员正在进行体能测试。',
                'immediate_goal': '观察学员完成最后一圈。',
            },
            '一个学员在最后一圈体力见底，仍试图跑完全程。',
        )

        self.assertIn('缺少 active scene_objective', prompt)
        self.assertIn('必须输出 scene_objective', prompt)

    def test_current_turn_skeleton_onstage_survives_normalization(self):
        fragment = merge_state_skeleton(
            {
                'time': '清晨',
                'location': '训练场',
                'main_event': '矮个子学员在长跑最后阶段体力见底。',
                'immediate_goal': '观察他是否能完成最后一圈。',
            },
            {'onstage_npcs': ['严教官']},
        )
        actors = {'npc_001': {'kind': 'npc', 'name': '严教官', 'aliases': []}}

        normalized = normalize_state_dict({**fragment, 'actors': actors}, prev_state={'actors': actors})

        self.assertEqual(normalized['onstage_npcs'], ['严教官'])
        self.assertNotIn('_current_turn_onstage_npcs', normalized)

    def test_current_turn_skeleton_onstage_survives_before_actor_registration(self):
        fragment = merge_state_skeleton(
            {
                'time': '清晨',
                'location': '训练场跑道',
                'main_event': '主角以计算过的节奏冲过终点线，并受到教官注意。',
                'immediate_goal': '前往起点线集合。',
            },
            {
                'main_event': '主角以计算过的节奏冲过终点线，并受到严教官注意。',
                'onstage_npcs': ['严教官'],
            },
        )

        normalized = normalize_state_dict(fragment, prev_state={})

        self.assertEqual(normalized['onstage_npcs'], ['严教官'])
        self.assertNotIn('_current_turn_onstage_npcs', normalized)

    def test_current_scene_onstage_refresh_drops_stale_generic_entity(self):
        prev = {
            'time': '下午',
            'location': '旧客栈',
            'main_event': '主角和中年人谈完旧事。',
            'immediate_goal': '离开客栈。',
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '中年人',
                    'aliases': ['中年人'],
                    'role_label': '当前互动核心人物',
                    'onstage': False,
                }
            ],
        }
        current = {
            'time': '下午',
            'location': '青州城北门内茶肆',
            'main_event': '瘦长脸、黑皮和半大孩子在茶肆旁压低声音说起城门盘查。',
            'immediate_goal': '判断是否继续听他们谈话。',
            'onstage_npcs': ['瘦长脸', '黑皮', '半大孩子'],
            '_current_turn_onstage_npcs': ['瘦长脸', '黑皮', '半大孩子'],
        }

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual(normalized['onstage_npcs'], ['瘦长脸', '黑皮', '半大孩子'])
        self.assertEqual([item['primary_label'] for item in normalized['scene_entities']], ['瘦长脸', '黑皮', '半大孩子'])

    def test_build_state_from_fragment_preserves_current_turn_onstage_marker(self):
        fragment = merge_state_skeleton(
            {
                'time': '下午',
                'location': '青州城北门内茶肆',
                'main_event': '茶肆旁几人压低声音说起城门盘查。',
                'immediate_goal': '判断是否继续听他们谈话。',
            },
            {'onstage_npcs': ['黑皮', '半大孩子']},
        )

        normalized = build_state_from_fragment({}, fragment, 'session-test')

        self.assertEqual(normalized['onstage_npcs'], ['黑皮', '半大孩子'])
        self.assertEqual([item['primary_label'] for item in normalized['scene_entities']], ['黑皮', '半大孩子'])
        self.assertNotIn('_current_turn_onstage_npcs', normalized)

    def test_object_aliases_merge_duplicate_ids_and_possession(self):
        prev = {
            'time': '下午',
            'location': '客栈',
            'main_event': '主角整理物品。',
            'immediate_goal': '继续赶路。',
            'tracked_objects': [
                {'object_id': 'wind_talisman_01', 'label': '御风符', 'kind': 'key_item', 'story_relevant': True},
                {'object_id': 'bronze_calc_rods', 'label': '青铜算筹', 'kind': 'tool', 'story_relevant': True},
            ],
            'possession_state': [
                {'object_id': 'wind_talisman_01', 'holder': '主角', 'status': 'on_desk', 'location': '桌上'},
                {'object_id': 'bronze_calc_rods', 'holder': '主角', 'status': 'placed_on_ground', 'location': '地上'},
            ],
        }
        current = {
            'time': '下午',
            'location': '客栈',
            'main_event': '主角把御风符和青铜算筹收进储物袋。',
            'immediate_goal': '离开客栈。',
            'tracked_objects': [
                {'object_id': 'wind_charm', 'label': '御风符', 'kind': 'key_item', 'aliases': ['风符']},
                {'object_id': 'calculation_sticks', 'label': '青铜算筹', 'kind': 'tool', 'aliases': ['算筹']},
            ],
            'possession_state': [
                {'object_id': 'wind_charm', 'holder': '主角', 'status': 'in_storage_bag', 'location': '储物袋'},
                {'object_id': 'calculation_sticks', 'holder': '主角', 'status': 'in_storage_bag', 'location': '储物袋'},
            ],
        }

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual([item['object_id'] for item in normalized['tracked_objects']], ['wind_talisman_01', 'bronze_calc_rods'])
        self.assertEqual([item['object_id'] for item in normalized['possession_state']], ['wind_talisman_01', 'bronze_calc_rods'])
        self.assertTrue(all(item['status'] == 'in_storage_bag' for item in normalized['possession_state']))

    def test_keeper_baseline_restores_current_turn_skeleton_marker(self):
        baseline = normalize_state_dict(
            {
                'time': '清晨',
                'location': '训练场跑道',
                'main_event': '主角按自己的节奏继续跑步。',
                'immediate_goal': '维持节奏跑完本圈。',
                'onstage_npcs': ['严教官', '记分员老周'],
                '_current_turn_onstage_npcs': ['严教官', '记分员老周'],
            },
            prev_state={},
        )
        self.assertNotIn('_current_turn_onstage_npcs', baseline)

        restored = _restore_current_turn_onstage_marker(
            baseline,
            {'_current_turn_onstage_npcs': ['严教官', '记分员老周']},
        )
        normalized = normalize_state_dict(restored, prev_state={})

        self.assertEqual(normalized['onstage_npcs'], ['严教官', '记分员老周'])
        self.assertNotIn('_current_turn_onstage_npcs', normalized)

    def test_header_only_reply_sentence_does_not_replace_main_event(self):
        reply = '**2003年9月1日，清晨，训练场跑道终点。**\n\n矮个子学员踉跄着越过终点线。'

        skeleton = extract_reply_skeleton(reply)
        normalized = normalize_state_dict(
            {
                'time': '清晨',
                'location': '训练场跑道终点',
                'main_event': '**2003年9月1日，清晨，训练场跑道终点。',
                'immediate_goal': '记录学员完成情况。',
            },
            prev_state={
                'main_event': '矮个子学员在长跑最后阶段体力见底。',
                'immediate_goal': '观察他是否能完成最后一圈。',
            },
        )

        self.assertNotIn('main_event', skeleton)
        self.assertEqual(normalized['main_event'], '矮个子学员在长跑最后阶段体力见底。')

    def test_non_gregorian_header_only_event_does_not_replace_main_event(self):
        normalized = normalize_state_dict(
            {
                'time': '午后',
                'location': '山门前',
                'main_event': '**景和三年冬月初七，午后，山门前。**',
                'immediate_goal': '等待守门人回应。',
            },
            prev_state={
                'main_event': '主角在山门前向守门人递上拜帖。',
                'immediate_goal': '等待守门人回应。',
            },
        )

        self.assertEqual(normalized['main_event'], '主角在山门前向守门人递上拜帖。')

    def test_header_only_event_with_station_house_does_not_replace_main_event(self):
        normalized = normalize_state_dict(
            {
                'time': '上午',
                'location': '北岭驿站堂屋',
                'main_event': '景和三年四月初四，上午，北岭驿站堂屋。',
                'immediate_goal': '等待驿卒回应。',
            },
            prev_state={
                'main_event': '主角在驿站向驿卒询问渡口车马。',
                'immediate_goal': '等待驿卒回应。',
            },
        )

        self.assertEqual(normalized['main_event'], '主角在驿站向驿卒询问渡口车马。')

    def test_plain_xianxia_scene_header_does_not_replace_main_event(self):
        reply = '九幽历三千七百二十一年·孟秋初四 清晨，人界·苍梧岭北坡灌木丛。\n\n短剑插下去，剑尖没入泛暗光的泥面。'

        skeleton = extract_reply_skeleton(reply)
        normalized = normalize_state_dict(
            {
                'time': '清晨',
                'location': '苍梧岭北坡灌木丛',
                'main_event': '九幽历三千七百二十一年·孟秋初四 清晨，人界·苍梧岭北坡灌木丛。',
                'immediate_goal': '探查泥土暗光与壳的关联。',
            },
            prev_state={
                'main_event': '主角用短剑试探发光泥地。',
                'immediate_goal': '探查泥土暗光与壳的关联。',
            },
        )

        self.assertEqual(skeleton['time'], '清晨')
        self.assertEqual(skeleton['location'], '人界·苍梧岭北坡灌木丛')
        self.assertEqual(skeleton['main_event'], '短剑插下去，剑尖没入泛暗光的泥面。')
        self.assertEqual(normalized['main_event'], '主角用短剑试探发光泥地。')

    def test_plain_xianxia_action_at_location_is_not_header_only(self):
        event = '九幽历三千七百二十一年·孟秋初四 清晨，人界·苍梧岭北坡灌木丛中传来脚步声。'

        normalized = normalize_state_dict(
            {
                'time': '清晨',
                'location': '苍梧岭北坡灌木丛',
                'main_event': event,
                'immediate_goal': '判断脚步声来源。',
            },
            prev_state={
                'main_event': '主角用短剑试探发光泥地。',
                'immediate_goal': '探查泥土暗光与壳的关联。',
            },
        )

        self.assertEqual(normalized['main_event'], event)

    def test_main_event_time_sentence_falls_back_to_previous_event(self):
        normalized = normalize_state_dict(
            {
                'time': '辰时',
                'location': '青石镇，西侧民居废弃空地',
                'main_event': '九幽历三千七百二十二年，四月十七，辰时。',
                'immediate_goal': '继续牵引泥壳。',
            },
            prev_state={
                'main_event': '陆小环以灵力线慢慢牵引井中泥壳。',
                'immediate_goal': '继续观察根须反应。',
            },
        )

        self.assertEqual(normalized['main_event'], '陆小环以灵力线慢慢牵引井中泥壳。')

    def test_main_event_strips_time_sentence_and_label(self):
        normalized = normalize_state_dict(
            {
                'time': '辰时',
                'location': '青石镇，西侧民居废弃空地',
                'main_event': '九幽历三千七百二十二年，四月十七，辰时。主要事件：陆小环继续牵引泥壳。',
                'immediate_goal': '继续牵引泥壳。',
            },
            prev_state={
                'main_event': '陆小环观察井中根须。',
                'immediate_goal': '继续观察根须反应。',
            },
        )

        self.assertEqual(normalized['main_event'], '陆小环继续牵引泥壳。')

    def test_main_event_strips_leading_label(self):
        normalized = normalize_state_dict(
            {
                'time': '辰时',
                'location': '青石镇，西侧民居废弃空地',
                'main_event': '主要事件：陆小环继续牵引泥壳。',
                'immediate_goal': '继续牵引泥壳。',
            },
            prev_state={
                'main_event': '陆小环观察井中根须。',
                'immediate_goal': '继续观察根须反应。',
            },
        )

        self.assertEqual(normalized['main_event'], '陆小环继续牵引泥壳。')

    def test_location_only_main_event_falls_back_to_previous_event(self):
        normalized = normalize_state_dict(
            {
                'time': '辰时',
                'location': '人界，青石镇，客栈二楼房间',
                'main_event': '人界，青石镇，客栈二楼房间。',
                'immediate_goal': '继续观察年轻男人反应。',
            },
            prev_state={
                'main_event': '陆小环使用泥壳追赶并吸收年轻男人经脉内散乱的残余灵力。',
                'immediate_goal': '用泥壳吸收残余灵力。',
            },
        )

        self.assertEqual(normalized['main_event'], '陆小环使用泥壳追赶并吸收年轻男人经脉内散乱的残余灵力。')

    def test_location_action_main_event_is_preserved(self):
        event = '客栈二楼房间传来敲门声。'

        normalized = normalize_state_dict(
            {
                'time': '辰时',
                'location': '人界，青石镇，客栈二楼房间',
                'main_event': event,
                'immediate_goal': '判断门外是谁。',
            },
            prev_state={
                'main_event': '陆小环使用泥壳追赶并吸收年轻男人经脉内散乱的残余灵力。',
                'immediate_goal': '用泥壳吸收残余灵力。',
            },
        )

        self.assertEqual(normalized['main_event'], event)

    def test_keeper_fill_rejects_location_only_main_event(self):
        merged = _merge_keeper_fill(
            {
                'time': '九幽历三千七百二十二年，四月十七，辰时',
                'location': '人界，青石镇，客栈二楼房间',
                'main_event': '陆小环使用泥壳追赶并吸收年轻男人经脉内散乱的残余灵力。',
                'immediate_goal': '用泥壳吸收残余灵力。',
            },
            {
                'main_event': '人界，青石镇，客栈二楼房间。',
                'immediate_goal': '继续询问药铺老板来历。',
            },
        )

        self.assertEqual(merged['main_event'], '陆小环使用泥壳追赶并吸收年轻男人经脉内散乱的残余灵力。')
        self.assertEqual(merged['immediate_goal'], '继续询问药铺老板来历。')

    def test_location_subject_event_is_not_header_only(self):
        event = '景和三年四月初四，上午，驿站起火。'

        normalized = normalize_state_dict(
            {
                'time': '上午',
                'location': '北岭驿站',
                'main_event': event,
                'immediate_goal': '判断驿站火势。',
            },
            prev_state={
                'main_event': '主角在驿站向驿卒询问渡口车马。',
                'immediate_goal': '等待驿卒回应。',
            },
        )
        item = build_event_summary_item(
            turn_id='turn-0014',
            ledger={
                'provider': 'llm',
                'summary_text': event,
                'main_event_candidates': [{'text': event}],
                'scene_shift': {'changed': False},
            },
            onstage_names=[],
        )

        self.assertEqual(normalized['main_event'], event)
        self.assertEqual(item['summary'], event)

    def test_action_clause_ending_with_location_suffix_is_not_header_only(self):
        event = '景和三年四月初四，上午，驿卒站在院中。'

        normalized = normalize_state_dict(
            {
                'time': '上午',
                'location': '北岭驿站院中',
                'main_event': event,
                'immediate_goal': '观察驿卒反应。',
            },
            prev_state={
                'main_event': '主角在驿站向驿卒询问渡口车马。',
                'immediate_goal': '等待驿卒回应。',
            },
        )
        item = build_event_summary_item(
            turn_id='turn-0015',
            ledger={
                'provider': 'llm',
                'summary_text': event,
                'main_event_candidates': [{'text': event}],
                'scene_shift': {'changed': False},
            },
            onstage_names=['驿卒'],
        )

        self.assertEqual(normalized['main_event'], event)
        self.assertEqual(item['summary'], event)

    def test_event_ledger_rejects_micro_action_fragment_as_main_event(self):
        ledger = build_event_ledger(
            user_text='问他药铺掌柜是什么来历',
            narrator_reply='年轻男人的嘴巴张了一下，喉结动了一下，手指攥紧又松开，背脊绷得更直。年轻男人开口回答陆小环询问药铺掌柜的来历。',
            prev_state={'location': '客栈二楼房间', 'onstage_npcs': ['年轻男人']},
            onstage_names=['年轻男人'],
            location='客栈二楼房间',
        )

        candidate_texts = [item['text'] for item in ledger['main_event_candidates']]
        self.assertNotIn('年轻男人的嘴巴张了一下，喉结动了一下，手指攥紧又松开，背脊绷得更直', candidate_texts)
        self.assertIn('年轻男人开口回答陆小环询问药铺掌柜的来历', candidate_texts)

    def test_event_summary_item_rejects_header_only_summary(self):
        item = build_event_summary_item(
            turn_id='turn-0012',
            ledger={
                'provider': 'llm',
                'summary_text': '景和三年四月初四，上午，北岭驿站堂屋。',
                'main_event_candidates': [{'text': '景和三年四月初四，上午，北岭驿站堂屋。'}],
                'scene_shift': {'changed': False},
            },
            onstage_names=[],
        )

        self.assertEqual(item['summary'], '')

    def test_event_summary_item_records_time_and_location_anchor(self):
        time_anchor, location_anchor = extract_time_location_anchor(
            '景和三年四月初四，上午，北岭驿站堂屋。\n主角向驿卒询问渡口车马。',
        )
        item = build_event_summary_item(
            turn_id='turn-0013',
            ledger={
                'provider': 'llm',
                'summary_text': '主角向驿卒询问渡口车马。',
                'scene_shift': {'changed': False},
            },
            onstage_names=[],
            time_anchor=time_anchor,
            location_anchor=location_anchor,
        )

        self.assertEqual(item['time_anchor'], '景和三年四月初四，上午')
        self.assertEqual(item['location_anchor'], '北岭驿站堂屋')

    def test_partial_keeper_fill_cannot_overwrite_core_scene_fields(self):
        baseline = {
            'time': '午后',
            'location': '茶棚',
            'main_event': '主角在茶棚向老汉打听渡口消息。',
            'onstage_npcs': ['老汉'],
            'immediate_goal': '判断是否继续追问渡口消息。',
        }
        payload = {
            'time': '待确认',
            'location': '某处',
            'main_event': '闲聊。',
            'immediate_goal': '继续。',
            'carryover_signals': [{'type': 'clue', 'text': '渡口有人换班'}],
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertEqual(merged['time'], '午后')
        self.assertEqual(merged['location'], '茶棚')
        self.assertEqual(merged['main_event'], '主角在茶棚向老汉打听渡口消息。')
        self.assertEqual(merged['immediate_goal'], '判断是否继续追问渡口消息。')
        self.assertEqual(merged['carryover_signals'], [{'type': 'clue', 'text': '渡口有人换班'}])

    def test_saved_half_consumed_mundane_object_remains_active(self):
        state = {
            'time': '午后',
            'location': '茶棚外',
            'main_event': '主角吃了半块饼后把剩下的油纸包收进怀里。',
            'tracked_objects': [{'object_id': 'obj_01', 'label': '油纸包饼', 'kind': 'item', 'story_relevant': True}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '主角', 'status': 'saved', 'location': '怀里'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['主角']}],
        }

        normalized = normalize_state_dict(state, prev_state={})

        self.assertEqual(normalized['tracked_objects'][0]['label'], '油纸包饼')
        self.assertEqual(normalized['possession_state'][0]['status'], 'saved')
        self.assertEqual(normalized['object_visibility'][0]['visibility'], 'private')

    def test_tracked_object_aliases_survive_normalization_and_object_heavy_detection(self):
        state = {
            'time': '午后',
            'location': '茶棚外',
            'main_event': '主角把小青收回怀里。',
            'tracked_objects': [
                {
                    'object_id': 'obj_01',
                    'label': '青玉小剑',
                    'aliases': ['小青', '青剑'],
                    'kind': 'weapon',
                    'story_relevant': True,
                },
            ],
            'possession_state': [{'object_id': 'obj_01', 'holder': '主角', 'status': 'carried', 'location': '怀里'}],
        }

        normalized = normalize_state_dict(state, prev_state={})

        self.assertEqual(normalized['tracked_objects'][0]['aliases'], ['小青', '青剑'])
        self.assertTrue(_is_object_heavy_turn('把小青收起', '主角把小青放进怀里。', normalized))

    def test_consumed_mundane_object_moves_to_graveyard_not_active(self):
        prev = {
            'tracked_objects': [{'object_id': 'obj_01', 'label': '油纸包饼', 'kind': 'item', 'story_relevant': True}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '主角', 'status': 'saved'}],
            'object_visibility': [{'object_id': 'obj_01', 'visibility': 'private', 'known_to': ['主角']}],
        }
        state = {
            **prev,
            'main_event': '主角把剩下的饼吃完，将油纸揉成一团丢进火盆。',
            'tracked_objects': [{'object_id': 'obj_01', 'label': '油纸包饼', 'kind': 'item', 'story_relevant': True, 'lifecycle_status': 'consumed'}],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['tracked_objects'], [])
        self.assertEqual(normalized['possession_state'], [])
        self.assertEqual(normalized['object_visibility'], [])
        self.assertEqual(normalized['graveyard_objects'][0]['object_id'], 'obj_01')
        self.assertEqual(normalized['graveyard_objects'][0]['lifecycle_status'], 'consumed')

    def test_possessed_object_cannot_be_marked_lost_by_same_turn(self):
        prev = {
            'tracked_objects': [{'object_id': 'mud_shell_01', 'label': '泥壳', 'kind': 'item', 'story_relevant': True}],
            'possession_state': [{'object_id': 'mud_shell_01', 'holder': '陆小环', 'status': '手持展示后收回袖中'}],
        }
        state = {
            **prev,
            'main_event': '灵貂衔着泥壳目送陆小环离去，泥壳仍在它嘴里。',
            'tracked_objects': [{'object_id': 'mud_shell_01', 'label': '泥壳', 'kind': 'item', 'story_relevant': True, 'lifecycle_status': 'lost'}],
            'possession_state': [{'object_id': 'mud_shell_01', 'holder': '陆小环', 'status': '包好收在袖中'}],
            'object_visibility': [{'object_id': 'mud_shell_01', 'visibility': 'private', 'known_to': ['陆小环']}],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertEqual(normalized['tracked_objects'][0]['object_id'], 'mud_shell_01')
        self.assertNotIn('lifecycle_status', normalized['tracked_objects'][0])
        self.assertEqual(normalized['possession_state'][0]['object_id'], 'mud_shell_01')
        self.assertEqual(normalized.get('graveyard_objects', []), [])

    def test_memory_maintenance_canonicalizes_actor_alias_layers(self):
        state = {
            'actors': {
                'npc_005': {
                    'actor_id': 'npc_005',
                    'kind': 'npc',
                    'name': '秦野',
                    'aliases': ['剃寸头的高个子学员'],
                },
            },
            'onstage_npcs': ['剃寸头的高个子学员'],
            'relevant_npcs': ['剃寸头的高个子学员'],
            'scene_entities': [{'primary_label': '剃寸头的高个子学员', 'aliases': ['剃寸头的高个子学员'], 'onstage': True}],
            'active_threads': [{'thread_id': 'thread_01', 'actors': ['剃寸头的高个子学员']}],
            'possession_state': [{'object_id': 'folder', 'holder': '剃寸头的高个子学员'}],
            'object_visibility': [{'object_id': 'folder', 'known_to': ['剃寸头的高个子学员']}],
            'knowledge_scope': {'npc_local': {'剃寸头的高个子学员': {'learned': ['陆小环昨晚十一点半睡']}, '秦野': {'learned': ['自己的笔记本已被封存']}}},
        }

        repaired, changes = canonicalize_state_memory(state)

        self.assertTrue(changes)
        self.assertEqual(repaired['onstage_npcs'], ['秦野'])
        self.assertEqual(repaired['relevant_npcs'], ['秦野'])
        self.assertEqual(repaired['scene_entities'][0]['primary_label'], '秦野')
        self.assertEqual(repaired['scene_entities'][0]['possible_link'], 'npc_005')
        self.assertEqual(repaired['active_threads'][0]['actors'], ['秦野'])
        self.assertEqual(repaired['possession_state'][0]['holder_actor_id'], 'npc_005')
        self.assertEqual(repaired['object_visibility'][0]['known_to_actor_ids'], ['npc_005'])
        self.assertEqual(repaired['knowledge_scope']['npc_local']['秦野']['learned'], ['陆小环昨晚十一点半睡', '自己的笔记本已被封存'])

    def test_memory_maintenance_resolves_waiting_risk_when_actor_onstage(self):
        state = {
            'onstage_npcs': ['秦野'],
            'immediate_risks': ['秦野仍在门外等待。', '技术部镜像仍未完成。'],
            'carryover_signals': [{'type': 'risk', 'text': '秦野仍在门外等待'}, {'type': 'risk', 'text': '技术部镜像仍未完成'}],
            'active_threads': [
                {'thread_id': 'thread_01', 'label': '秦野仍在门外等待', 'goal': '避免失控', 'obstacle': '秦野仍在门外等待'},
                {'thread_id': 'thread_02', 'label': '技术部镜像仍未完成', 'goal': '等待镜像', 'obstacle': '镜像耗时'},
            ],
        }

        repaired, changes = resolve_stale_state_threads(state)

        self.assertTrue(any(item['action'] == 'resolve_stale_thread' for item in changes))
        self.assertEqual(repaired['immediate_risks'], ['技术部镜像仍未完成。'])
        self.assertEqual(repaired['carryover_signals'], [{'type': 'risk', 'text': '技术部镜像仍未完成'}])
        self.assertEqual([item['thread_id'] for item in repaired['active_threads']], ['thread_02'])
        self.assertEqual(repaired['resolved_events'][0]['resolved_reason'], 'actor_now_onstage')

    def test_memory_maintenance_persists_stale_thread_obstacle_clear_without_removal(self):
        state = {
            'onstage_npcs': ['秦野'],
            'active_threads': [
                {'thread_id': 'thread_01', 'kind': 'main', 'label': '追查笔记本', 'goal': '读取芯片', 'obstacle': '秦野仍在门外等待'},
            ],
        }

        repaired, changes = resolve_stale_state_threads(state)

        self.assertTrue(any(item['action'] == 'clear_stale_thread_obstacle' for item in changes))
        self.assertEqual(repaired['active_threads'][0]['obstacle'], '')

    def test_memory_maintenance_skips_conflicting_actor_aliases(self):
        state = {
            'actors': {
                'npc_001': {'kind': 'npc', 'name': '秦野', 'aliases': ['学员']},
                'npc_002': {'kind': 'npc', 'name': '赵明', 'aliases': ['学员', '秦野']},
            },
        }

        mapping = actor_alias_map(state)

        self.assertNotIn('学员', mapping)
        self.assertEqual(mapping['秦野'], '秦野')
        self.assertEqual(mapping['赵明'], '赵明')

    def test_memory_maintenance_canonicalizes_event_summary_actors(self):
        payload = {'version': 1, 'items': [{'event_id': 'evt_0001', 'actors': ['剃寸头的高个子学员', '维克托·奥古斯特']}]} 

        repaired, changes = canonicalize_event_summaries(payload, {'剃寸头的高个子学员': '秦野', '秦野': '秦野'})

        self.assertTrue(changes)
        self.assertEqual(repaired['items'][0]['actors'], ['秦野', '维克托·奥古斯特'])

    def test_actor_registry_binds_revealed_name_to_local_descriptive_actor(self):
        state = {
            'actors': {
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '严教官', 'aliases': [], 'identity': '教官'},
                'npc_002': {'actor_id': 'npc_002', 'kind': 'npc', 'name': '矮壮的学员', 'aliases': [], 'appearance': '矮壮', 'identity': '学员'},
            },
        }
        narrator_reply = '矮壮的学员把课本翻开，扉页贴着“李明 / 青年部一班”。严教官在远处继续训话。严教官又点了一次名。'

        updated = update_actor_registry(state, narrator_reply=narrator_reply, turn_number=3, use_llm=False)

        self.assertEqual(updated['actors']['npc_002']['name'], '李明')
        self.assertIn('矮壮的学员', updated['actors']['npc_002']['aliases'])
        self.assertNotIn('李明', updated['actors']['npc_001']['aliases'])

    def test_actor_registry_promotes_keeper_revealed_name_to_descriptive_actor(self):
        state = {
            'actors': {
                'npc_qingshi_young_man': {
                    'actor_id': 'npc_qingshi_young_man',
                    'kind': 'npc',
                    'name': '年轻男人',
                    'aliases': ['青灰色短褐年轻男人'],
                    'identity': '青石镇沈家人',
                    'created_turn': 53,
                },
            },
            'onstage_npcs': ['年轻男人', '灵貂'],
            'scene_entities': [{
                'entity_id': 'scene_npc_01',
                'primary_label': '沈青',
                'aliases': ['年轻男人', '那男子', '青灰色短褐年轻男人', '沈青'],
                'role_label': '青石镇沈家人',
                'onstage': True,
            }],
            'important_npcs': [{
                'key': 'important:年轻男人',
                'primary_label': '年轻男人',
                'aliases': ['青灰色短褐年轻男人'],
                'role_label': '当前互动核心人物',
            }],
            'knowledge_scope': {
                'protagonist': {
                    'learned': ['年轻男人真名沈青，父亲姓沈，青石镇沈家人'],
                },
            },
        }

        updated = update_actor_registry(state, narrator_reply='沈青垂眼承认真名。', turn_number=91, use_llm=False)

        actor = updated['actors']['npc_qingshi_young_man']
        self.assertEqual(actor['name'], '沈青')
        self.assertIn('年轻男人', actor['aliases'])
        self.assertIn('青灰色短褐年轻男人', actor['aliases'])
        self.assertIn('沈青', updated['onstage_npcs'])
        self.assertNotIn('年轻男人', updated['onstage_npcs'])
        self.assertEqual(updated['important_npcs'][0]['primary_label'], '沈青')
        self.assertEqual(updated['important_npcs'][0]['key'], 'important:沈青')
        self.assertTrue(updated['actor_registry_diagnostics']['alias_updates'][0]['promoted_to_name'])

    def test_actor_registry_promotes_name_from_split_npc_local_holder(self):
        state = {
            'actors': {
                'npc_qingshi_young_man': {
                    'actor_id': 'npc_qingshi_young_man',
                    'kind': 'npc',
                    'name': '年轻男人',
                    'aliases': ['青灰色短褐年轻男人'],
                    'identity': '三天前下井触碰井底石片后被灌入凉湿灵力的青石镇年轻男子',
                    'created_turn': 55,
                },
                'npc_lingdiao': {'actor_id': 'npc_lingdiao', 'kind': 'npc', 'name': '灵貂', 'aliases': []},
            },
            'important_npcs': [{
                'key': 'important:年轻男人',
                'primary_label': '年轻男人',
                'aliases': ['那男子', '青灰色短褐年轻男人'],
                'role_label': '触碰井底石片后被灌入凉湿灵力的求助者',
            }],
            'active_threads': [{'thread_id': 'thread_1', 'actors': ['年轻男人']}],
            'object_visibility': [{'object_id': 'mud_shell_01', 'known_to': ['陆小环', '灵貂', '沈青']}],
            'knowledge_scope': {
                'npc_local': {
                    '年轻男人': {'learned': ['陆小环认为黑狗血无用且不惧闹鬼']},
                    '沈青': {'learned': ['陆小环似乎记得陈掌柜大后天出门的事']},
                },
            },
            'resolved_events': [{
                'label': '沈青主动告知真名，并确认陆小环为散修身份',
                'kind': 'main',
                'status': 'resolved',
            }],
            'actor_context_index': {
                'active_actor_ids': ['protagonist', 'npc_lingdiao', 'npc_qingshi_young_man'],
                'last_mentioned_turn': {'npc_qingshi_young_man': 91},
            },
        }

        updated = update_actor_registry(state, narrator_reply='沈青站在原地。', turn_number=93, use_llm=False)

        actor = updated['actors']['npc_qingshi_young_man']
        self.assertEqual(actor['name'], '沈青')
        self.assertIn('年轻男人', actor['aliases'])
        self.assertEqual(updated['important_npcs'][0]['primary_label'], '沈青')
        self.assertEqual(updated['active_threads'][0]['actors'], ['沈青'])
        self.assertIn('沈青', updated['knowledge_scope']['npc_local'])
        self.assertNotIn('年轻男人', updated['knowledge_scope']['npc_local'])
        self.assertEqual(updated['object_visibility'][0]['known_to_actor_ids'], ['protagonist', 'npc_lingdiao', 'npc_qingshi_young_man'])
        self.assertTrue(updated['actor_registry_diagnostics']['alias_updates'][0]['promoted_to_name'])

    def test_actor_registry_persists_protagonist_public_private_identity_boundary(self):
        profile = {
            'name': '测试主角',
            'gender': '女性（伪装成男性）',
            'character': {
                'appearance': {
                    'body': {
                        'figure': '身形偏瘦',
                        'chest': '用束带压平轮廓',
                    },
                    'clothing': {'style': '宽松制服'},
                },
                'disguise': {
                    'level': '稳定',
                    'techniques': ['压低声线'],
                    'weaknesses': ['喉结不明显'],
                },
            },
        }
        with patch('backend.actor_registry.load_effective_player_profile', return_value=profile):
            updated = update_actor_registry({}, narrator_reply='训练场风声很低。', turn_number=1, player_name='测试主角', use_llm=False)

        protagonist = updated['actors']['protagonist']
        self.assertEqual(protagonist['identity'], '场内公开呈现为男性')
        self.assertEqual(protagonist['public_identity'], '场内公开呈现为男性')
        self.assertIn('性别=女性（伪装成男性）', protagonist['private_identity'])
        self.assertIn('NPC 只有在知情记录明确写出其已获知时', protagonist['knowledge_boundary'])
        self.assertIn('身形偏瘦', protagonist['appearance'])

    def test_actor_registry_rejects_abstract_topic_candidate(self):
        state = {}
        with patch('backend.actor_registry._extract_actor_candidates_with_llm', return_value=([
            {'name': '时间', 'aliases': ['时间栏', '时间盲区'], 'personality': '', 'appearance': '瘦高', 'identity': '学员'},
        ], {}, None)):
            updated = update_actor_registry(state, narrator_reply='老师讲解时间栏。', turn_number=1, use_llm=True)

        self.assertNotIn('npc_001', updated['actors'])

    def test_actor_context_counts_partial_canonical_actor_mentions(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': [],
                    'identity': '教官',
                    'created_turn': 1,
                },
            },
            'actor_context_index': {
                'active_actor_ids': ['protagonist', 'npc_001'],
                'archived_actor_ids': [],
                'last_mentioned_turn': {'npc_001': 14},
            },
        }

        updated = update_actor_registry(
            state,
            narrator_reply='维克托合上记录板，转身提醒下午两点去D栋301。',
            turn_number=18,
            use_llm=False,
        )

        self.assertEqual(updated['actor_context_index']['last_mentioned_turn']['npc_001'], 18)
        self.assertIn('npc_001', updated['actor_context_index']['active_actor_ids'])


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

    def test_normalize_state_does_not_keep_absent_actor_onstage_from_registry_only(self):
        prev = {
            'actors': {
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '维克托', 'aliases': ['教官']},
            },
        }
        current = {
            'time': '上午',
            'location': '庭院树下',
            'main_event': '主角在树下坐着看书。',
            'immediate_goal': '继续休息看书。',
            'scene_entities': [{'entity_id': 'scene_npc_01', 'primary_label': '维克托', 'aliases': ['教官'], 'role_label': '教官', 'onstage': True}],
            'onstage_npcs': ['维克托'],
        }

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual(normalized['onstage_npcs'], [])
        self.assertEqual(normalized['scene_entities'], [])

    def test_normalize_state_rejects_abstract_scene_entity_as_person(self):
        normalized = normalize_state_dict({
            'time': '上午',
            'location': '教室',
            'main_event': '老师讲解时间栏和时间盲区。',
            'scene_entities': [{'entity_id': 'scene_npc_01', 'primary_label': '时间', 'aliases': ['时间栏'], 'role_label': '学员', 'onstage': True}],
            'onstage_npcs': ['时间'],
        })

        self.assertEqual(normalized['onstage_npcs'], [])
        self.assertEqual(normalized['scene_entities'], [])

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

    def test_arbiter_stealth_signal_is_clue_not_immediate_risk(self):
        merged = merge_arbiter_state({}, {
            'arbiter_needed': True,
            'results': [{'event_id': 'event-stealth-001', 'result': 'stealth_risk_needs_resolution', 'dice_needed': True}],
        })

        self.assertEqual(merged['immediate_risks'], [])
        self.assertEqual(merged['carryover_clues'], ['压低动静或隐蔽行动是否引起注意，仍需在后续回合继续确认。'])

    def test_turn_analyzer_does_not_escalate_quiet_reading_as_stealth(self):
        from backend.turn_analyzer import _heuristic_analysis

        analysis = _heuristic_analysis(
            '找了个隐蔽的阴凉位置坐下看书',
            {'location': '庭院绿化带', 'main_event': '主角在树下休息'},
        )

        self.assertLess(analysis['trigger_scores']['stealth'], 3)

    def test_extract_reply_skeleton_uses_scene_header_and_first_sentence(self):
        reply = '【清早，医馆门前】\n\n陆小环拎着医箱跨过门槛，扬声招呼东家。\n\n屋里药气未散。'

        skeleton = extract_reply_skeleton(reply)

        self.assertEqual(skeleton['time'], '清早')
        self.assertEqual(skeleton['location'], '医馆门前')
        self.assertEqual(skeleton['main_event'], '陆小环拎着医箱跨过门槛，扬声招呼东家。')

    def test_extract_reply_skeleton_coarsens_precise_header_time(self):
        reply = '【2026年9月14日 上午九点三十二分，鹰巢教室】\n\n陆小环把资料塞进背包，准备下午两点去E栋。'

        skeleton = extract_reply_skeleton(reply)

        self.assertEqual(skeleton['time'], '上午')
        self.assertEqual(skeleton['location'], '鹰巢教室')

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

    def test_normalize_state_coarsens_current_time_but_preserves_deadline_goal(self):
        state = {
            'time': '2026年9月14日 上午九点三十二分',
            'location': '鹰巢教室',
            'main_event': '维克托命令陆小环等待镜像完成。',
            'immediate_goal': '准备下午两点前往E栋地下一层。',
            'onstage_npcs': [],
        }

        normalized = normalize_state_dict(state)

        self.assertEqual(normalized['time'], '上午')
        self.assertEqual(normalized['immediate_goal'], '准备下午两点前往E栋地下一层。')

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

    def test_actor_registry_treats_card_name_parts_with_titles_as_existing_actor(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': [],
                    'created_turn': 1,
                },
            },
        }
        usage = {'model': 'test-model'}

        with patch('backend.actor_registry.get_character_primary_name', return_value='维克托·奥古斯特'):
            with patch('backend.actor_registry.call_role_llm', return_value=('{"new_actors":[{"name":"奥古斯特教官","aliases":[]}] }', usage)):
                updated = update_actor_registry(state, narrator_reply='奥古斯特教官合上记录板。', turn_number=9, use_llm=True)

        self.assertEqual([actor_id for actor_id in updated['actors'] if actor_id != 'protagonist'], ['npc_001'])
        self.assertEqual(updated['actor_registry_diagnostics']['created_actor_ids'], [])

    def test_actor_registry_adds_revealed_name_alias_to_existing_generic_actor(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '剃寸头的高个子学员',
                    'aliases': [],
                    'appearance': '剃寸头，高个子，膝盖有擦伤',
                    'identity': '新生学员',
                    'created_turn': 3,
                },
            },
            'actor_context_index': {'last_mentioned_turn': {'npc_001': 3}},
            'knowledge_scope': {
                'npc_local': {
                    '秦野': {'learned': ['秦野注意到陆小环刚才超了自己']},
                },
            },
        }
        reply = '寸头高个子的脚步拖得很沉。走出三四步之后他停了一下，没回头。"姓秦。"他说，"秦野。"然后继续往前挪。'

        updated = update_actor_registry(state, narrator_reply=reply, turn_number=8, use_llm=False)

        actor = updated['actors']['npc_001']
        self.assertEqual(actor['name'], '秦野')
        self.assertIn('剃寸头的高个子学员', actor['aliases'])
        self.assertEqual(updated['actor_context_index']['last_mentioned_turn']['npc_001'], 8)
        self.assertEqual(updated['actor_registry_diagnostics']['alias_updates'][0]['alias'], '秦野')
        self.assertTrue(any(item['holder_actor_id'] == 'npc_001' and '陆小环' in item['text'] for item in updated['knowledge_records']))

    def test_actor_registry_adds_stuttered_revealed_name_alias(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '迟到新生',
                    'aliases': [],
                    'appearance': '瘦高，胸口起伏大，额头冒汗',
                    'identity': '新生学员',
                    'created_turn': 9,
                },
            },
        }
        reply = '维克托看向迟到那个新生。"你叫什么。"那个瘦高的新生站起来。"赵——赵明。"'

        updated = update_actor_registry(state, narrator_reply=reply, turn_number=10, use_llm=False)

        self.assertEqual(updated['actors']['npc_001']['name'], '赵明')
        self.assertIn('迟到新生', updated['actors']['npc_001']['aliases'])
        self.assertEqual(updated['actor_context_index']['last_mentioned_turn']['npc_001'], 10)

    def test_actor_registry_rejects_quoted_comparison_as_revealed_name(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '助教',
                    'aliases': [],
                    'identity': '助教',
                    'created_turn': 9,
                },
            },
        }
        reply = '教官看向远处的学员。“注意她的呼吸节奏。”他说，“和之前比。”助教愣了一下，把视线移过去。'

        updated = update_actor_registry(state, narrator_reply=reply, turn_number=15, use_llm=False)

        self.assertEqual(updated['actors']['npc_001']['name'], '助教')
        self.assertEqual(updated['actors']['npc_001']['aliases'], [])
        self.assertEqual(updated['actor_registry_diagnostics']['alias_updates'], [])

    def test_actor_registry_rejects_phrase_fragments_as_aliases(self):
        state = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '剃寸头的高个子学员',
                    'aliases': ['不能', '抱着电脑', '在跑代码', '本机日志', '终端编号'],
                    'appearance': '剃寸头，高个子',
                    'identity': '新生学员',
                    'created_turn': 3,
                },
            },
        }
        reply = '剃寸头的高个子学员说：“不能。”随后又提到“本机日志”和“终端编号”。'

        updated = update_actor_registry(state, narrator_reply=reply, turn_number=21, use_llm=False)

        self.assertEqual(updated['actors']['npc_001']['aliases'], [])
        self.assertEqual(updated['actor_registry_diagnostics']['alias_updates'], [])

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

    def test_normalize_state_retains_current_related_non_onstage_npc(self):
        prev: dict[str, Any] = {
            'scene_entities': [
                {'primary_label': '测试掌柜', 'aliases': ['掌柜'], 'role_label': '客栈掌柜', 'onstage': False},
            ],
            'important_npcs': [{'primary_label': '测试掌柜', 'aliases': ['掌柜'], 'role_label': '客栈掌柜', 'locked': True}],
        }
        state = {
            'time': '午后',
            'location': '前厅',
            'main_event': '主角整理账册时，测试掌柜仍在门外等待结果。',
            'onstage_npcs': [],
            'relevant_npcs': [],
            'scene_entities': [],
        }

        normalized = normalize_state_dict(state, prev_state=prev)

        self.assertIn('测试掌柜', normalized['relevant_npcs'])

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

    def test_actor_registry_frames_npc_protagonist_knowledge(self):
        state = {
            'actors': {
                'protagonist': {
                    'actor_id': 'protagonist',
                    'kind': 'protagonist',
                    'name': '陆小环',
                    'aliases': ['你', '主角'],
                },
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': ['教官'],
                },
            },
            'knowledge_scope': {
                'npc_local': {
                    '教官': {
                        'learned': [
                            '陆小环听觉范围比正常宽',
                        ]
                    }
                }
            },
        }

        updated = update_actor_registry(state, narrator_reply='维克托看向陆小环。', turn_number=3, use_llm=False)

        records = [item for item in updated['knowledge_records'] if item['holder_actor_id'] == 'npc_001']
        self.assertIn({'holder_actor_id': 'npc_001', 'text': '维克托·奥古斯特注意到陆小环听觉范围比正常宽', 'source_turn': 3}, records)
        self.assertFalse(any(item['text'] == '陆小环听觉范围比正常宽' for item in records))

    def test_actor_registry_preserves_existing_npc_knowledge_frame(self):
        state = {
            'actors': {
                'protagonist': {
                    'actor_id': 'protagonist',
                    'kind': 'protagonist',
                    'name': '陆小环',
                    'aliases': ['你', '主角'],
                },
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': ['教官'],
                },
            },
            'knowledge_scope': {
                'npc_local': {'教官': {'learned': ['维克托注意到陆小环保持稳定步频']}}
            },
        }

        updated = update_actor_registry(state, narrator_reply='维克托看向陆小环。', turn_number=3, use_llm=False)

        self.assertIn(
            {'holder_actor_id': 'npc_001', 'text': '维克托注意到陆小环保持稳定步频', 'source_turn': 3},
            updated['knowledge_records'],
        )

    def test_knowledge_scope_is_per_turn_delta(self):
        prev = {
            'knowledge_scope': {'protagonist': {'learned': ['旧情报']}},
            'knowledge_records': [{'holder_actor_id': 'protagonist', 'text': '旧情报', 'source_turn': 1}],
        }

        normalized = normalize_state_dict({}, prev_state=prev)

        self.assertEqual(normalized['knowledge_scope'], {})
        self.assertEqual(normalized['knowledge_records'], prev['knowledge_records'])

    def test_persona_observed_context_keeps_npc_specific_sentences(self):
        from backend.persona_updater import _observed_context

        history = [
            {'role': 'user', 'content': '继续等'},
            {'role': 'assistant', 'content': '陆小环贴着墙站着，鞋底蹭过水泥地。秦野在门外低声问技术部什么时候放人。'},
        ]

        observed = _observed_context(history, '秦野', ['终端编号'])

        self.assertIn('秦野', observed['recent_behavior'])
        self.assertNotIn('陆小环贴着墙站着', observed['recent_behavior'])
        self.assertNotIn('终端编号', observed['recent_behavior'])

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

    def test_scene_entities_canonicalize_actor_aliases(self):
        state: dict[str, Any] = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': ['维克托', '教官'],
                },
            },
            'onstage_npcs': ['维克托'],
            'scene_entities': [
                {
                    'entity_id': 'scene_npc_01',
                    'primary_label': '维克托',
                    'aliases': ['维克托'],
                    'role_label': '当前互动核心人物',
                    'onstage': True,
                    'possible_link': None,
                }
            ],
        }

        normalized = normalize_state_dict(state)

        self.assertEqual(normalized['onstage_npcs'], ['维克托·奥古斯特'])
        self.assertEqual(normalized['scene_entities'][0]['primary_label'], '维克托·奥古斯特')
        self.assertIn('维克托', normalized['scene_entities'][0]['aliases'])
        self.assertEqual(normalized['scene_entities'][0]['possible_link'], 'npc_001')

    def test_scene_entities_do_not_import_dirty_actor_aliases(self):
        state: dict[str, Any] = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '秦野',
                    'aliases': ['剃寸头的高个子学员', '不能', '本机日志', '终端编号'],
                },
            },
            'onstage_npcs': ['剃寸头的高个子学员'],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '剃寸头的高个子学员', 'aliases': ['不能'], 'role_label': '新生学员', 'onstage': True}
            ],
        }

        normalized = normalize_state_dict(state)

        entity = normalized['scene_entities'][0]
        self.assertEqual(entity['primary_label'], '秦野')
        self.assertIn('剃寸头的高个子学员', entity['aliases'])
        self.assertNotIn('不能', entity['aliases'])
        self.assertNotIn('本机日志', entity['aliases'])
        self.assertNotIn('终端编号', entity['aliases'])

    def test_scene_entities_canonicalize_card_name_part_with_title(self):
        state: dict[str, Any] = {
            'actors': {
                'npc_001': {
                    'actor_id': 'npc_001',
                    'kind': 'npc',
                    'name': '维克托·奥古斯特',
                    'aliases': [],
                },
            },
            'onstage_npcs': ['奥古斯特教官'],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '奥古斯特教官', 'aliases': [], 'role_label': '教官', 'onstage': True}
            ],
        }

        with patch('backend.state_bridge.get_character_primary_name', return_value='维克托·奥古斯特'):
            normalized = normalize_state_dict(state)

        self.assertEqual(normalized['onstage_npcs'], ['维克托·奥古斯特'])
        self.assertEqual(normalized['scene_entities'][0]['primary_label'], '维克托·奥古斯特')
        self.assertIn('奥古斯特教官', normalized['scene_entities'][0]['aliases'])

    def test_important_npc_present_now_ignores_merely_relevant_names(self):
        from backend.important_npc_tracker import update_important_npcs

        state = {
            'time': '中午',
            'location': '图书馆公共终端区',
            'main_event': '安全组人员要求陆小环前往训练部谈话。',
            'relevant_npcs': ['维克托'],
            'important_npcs': [
                {
                    'key': 'important:维克托',
                    'primary_label': '维克托',
                    'aliases': [],
                    'role_label': '特工学院教官',
                    'locked': True,
                    'importance_score': 6,
                    'present_now': True,
                    'inactive_turns': 0,
                    'last_location': '训练场',
                }
            ],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '维克托', 'aliases': [], 'role_label': '特工学院教官', 'onstage': False},
            ],
        }

        updated = update_important_npcs(state, history=[])

        victor = updated['important_npcs'][0]
        self.assertFalse(victor['present_now'])
        self.assertEqual(victor['last_location'], '训练场')

    def test_possession_holder_alias_canonicalizes_to_actor_name(self):
        state: dict[str, Any] = {
            'actors': {
                'npc_001': {'actor_id': 'npc_001', 'kind': 'npc', 'name': '维克托·奥古斯特', 'aliases': ['维克托']},
            },
            'onstage_npcs': ['维克托'],
            'scene_entities': [{'entity_id': 'scene_npc_01', 'primary_label': '维克托', 'aliases': ['维克托'], 'onstage': True}],
            'tracked_objects': [{'object_id': 'obj_01', 'label': '手枪', 'kind': 'weapon'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '维克托', 'status': 'holding'}],
        }

        normalized = normalize_state_dict(state)

        self.assertEqual(normalized['possession_state'][0]['holder'], '维克托·奥古斯特')
        self.assertEqual(normalized['possession_state'][0]['holder_actor_id'], 'npc_001')

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

    def test_keeper_fill_payload_overrides_baseline_possession_location(self):
        baseline = {
            'possession_state': [
                {'object_id': 'obj_01', 'holder': '主角', 'status': '浸在溪水中', 'location': '溪水中/掌心'},
            ],
        }
        payload = {
            'possession_state': [
                {'object_id': 'obj_01', 'holder': '主角', 'status': '重新包好带着', 'location': '怀里'},
            ],
        }

        merged = _merge_keeper_fill(baseline, payload)

        self.assertEqual(merged['possession_state'], payload['possession_state'])

    def test_normalize_state_clears_stale_scene_location_for_carried_object(self):
        prev: dict[str, Any] = {
            'tracked_objects': [{'object_id': 'big_spirit', 'label': '大灵物', 'kind': 'item', 'story_relevant': True}],
            'possession_state': [
                {
                    'object_id': 'big_spirit',
                    'holder': '主角',
                    'status': '双手捧着浸在溪水中，吸水后恢复拳头大小',
                    'location': '溪水中/掌心',
                },
            ],
        }
        current = {
            **prev,
            'time': '上午',
            'location': '驿站门口',
            'main_event': '主角将大灵物重新用布包好，带着鼓囊布包走到驿站门口。',
            'immediate_goal': '向驿卒询问路线。',
        }

        normalized = normalize_state_dict(current, prev_state=prev)

        self.assertEqual(normalized['possession_state'][0]['status'], 'carried')
        self.assertEqual(normalized['possession_state'][0]['location'], '')

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

    def test_thread_dedupe_recomputes_key_when_label_changes(self):
        state = {
            'main_event': '陆小环体力耗尽后手抖。',
            'immediate_goal': '继续训练。',
            'carryover_signals': [
                {'type': 'risk', 'text': '维克托左腿旧伤在雨后僵硬'},
                {'type': 'risk', 'text': '陆小环体力耗尽手抖未被察觉'},
            ],
            'active_threads': [
                {
                    'key': 'risk:维克托左腿旧伤在雨后僵硬',
                    'label': '维克托左腿旧伤在雨后僵硬',
                    'kind': 'risk',
                    'priority': 'secondary',
                    'status': 'active',
                    'goal': '避免该风险在下一轮直接失控或越界落地',
                    'obstacle': '维克托左腿旧伤在雨后僵硬',
                    'thread_id': 'thread_02',
                },
            ],
        }

        threaded = apply_thread_tracker(state, narrator_reply='陆小环体力耗尽，双手仍在发抖。')

        risk_threads = [item for item in threaded['active_threads'] if item.get('kind') == 'risk']
        for item in risk_threads:
            self.assertIn(item['label'].rstrip('。'), item['key'])

    def test_keeper_fill_resolved_signals_drop_stale_risk(self):
        baseline = {
            'carryover_signals': [{'type': 'risk', 'text': '维克托要求陆小环伸出双手检查'}],
            'immediate_risks': ['维克托要求陆小环伸出双手检查'],
            'carryover_clues': ['左边双杠握把间距比其他宽两寸'],
        }
        payload = {'resolved_signals': ['伸出双手检查已经完成']}

        merged = _merge_keeper_fill(baseline, payload)
        normalized = normalize_state_dict(merged, prev_state=baseline)
        threaded = apply_thread_tracker(normalized, narrator_reply='维克托检查完双手，替陆小环缠好胶布。')

        self.assertNotIn('维克托要求陆小环伸出双手检查。', normalized['immediate_risks'])
        self.assertFalse(any('伸出双手检查' in item.get('label', '') for item in threaded['active_threads']))

    def test_normalize_state_canonicalizes_and_prunes_thread_actors(self):
        state = {
            'main_event': '赵明被点名后低头挪到窗口旁。',
            'immediate_goal': '继续观察赵明的反应。',
            'onstage_npcs': ['赵明'],
            'relevant_npcs': ['金发男生', '迟到新生'],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '赵明', 'aliases': ['迟到新生'], 'role_label': '新生', 'onstage': True},
            ],
            'actors': {
                'npc_002': {'kind': 'npc', 'name': '金发男生', 'aliases': []},
                'npc_007': {'kind': 'npc', 'name': '赵明', 'aliases': ['迟到新生']},
            },
            'active_threads': [
                {
                    'thread_id': 'thread_01',
                    'key': 'main:迟到新生被点名',
                    'label': '迟到新生被点名',
                    'kind': 'main',
                    'goal': '看清赵明是否会继续拖慢分组',
                    'obstacle': '赵明仍紧张',
                    'latest_change': '赵明被点名',
                    'actors': ['金发男生', '迟到新生'],
                },
            ],
        }

        normalized = normalize_state_dict(state)

        self.assertEqual(normalized['active_threads'][0]['actors'], ['赵明'])

    def test_normalize_state_converges_relevant_npcs_to_current_mentions(self):
        state = {
            'main_event': '赵明被点名后站到窗口旁。',
            'immediate_goal': '完成当前分组。',
            'onstage_npcs': ['赵明'],
            'relevant_npcs': ['助教', '战术基础助教', '高年级学员', '秦野'],
            'immediate_risks': ['秦野留下的第三波小代码仍可能影响后续排序。'],
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '赵明', 'aliases': ['迟到新生'], 'role_label': '新生', 'onstage': True},
                {'entity_id': 'scene_npc_02', 'primary_label': '秦野', 'aliases': ['剃寸头的高个子学员'], 'role_label': '学员', 'onstage': False},
            ],
            'actors': {
                'npc_003': {'kind': 'npc', 'name': '助教', 'aliases': []},
                'npc_004': {'kind': 'npc', 'name': '战术基础助教', 'aliases': []},
                'npc_005': {'kind': 'npc', 'name': '秦野', 'aliases': ['剃寸头的高个子学员']},
                'npc_006': {'kind': 'npc', 'name': '高年级学员', 'aliases': []},
                'npc_007': {'kind': 'npc', 'name': '赵明', 'aliases': ['迟到新生']},
            },
            'active_threads': [
                {
                    'thread_id': 'thread_02',
                    'label': '秦野留下的小代码风险',
                    'kind': 'risk',
                    'goal': '避免秦野留下的小代码误导排序',
                    'obstacle': '第三波小代码仍未确认',
                    'latest_change': '风险仍挂起',
                    'actors': ['秦野', '助教'],
                },
            ],
        }

        normalized = normalize_state_dict(state)

        self.assertEqual(normalized['relevant_npcs'], ['秦野'])
        self.assertEqual(normalized['active_threads'][0]['actors'], ['秦野'])

    def test_keeper_prompts_keep_core_fields_scene_focused(self):
        from backend.narrator_input import build_narrator_input

        self.assertIn('接下来1-2轮内可能直接约束行动', state_keeper.STATE_KEEPER_FILL_SYSTEM)
        self.assertIn('预约、背景悬念', state_keeper.STATE_KEEPER_FILL_SYSTEM)
        self.assertIn('默认写 clue，不要写成 risk', state_keeper.STATE_KEEPER_FILL_SYSTEM)
        self.assertIn('优先写主角当前正在参与的互动', state_keeper.SKELETON_KEEPER_SYSTEM)
        self.assertIn('粗时段', state_keeper.SKELETON_KEEPER_SYSTEM)
        self.assertIn('旁观者、监督者、提及者', state_keeper.SKELETON_KEEPER_SYSTEM)
        self.assertIn('必须站在主角视角', state_keeper.SKELETON_KEEPER_SYSTEM)
        self.assertIn('不要写 NPC 的目标', state_keeper.SKELETON_KEEPER_SYSTEM)
        system_prompt, _user_prompt = build_narrator_input({'scene_facts': {}, 'active_preset': {}}, '继续')
        self.assertIn('当前时间”默认只写粗时段', system_prompt)
        self.assertIn('精确钟点只用于剧情内已经明确存在的预约', system_prompt)

    def test_lightweight_knowledge_delta_records_visible_object_possession(self):
        state = {
            'tracked_objects': [{'object_id': 'obj_01', 'label': '运动胶布', 'kind': 'item'}],
            'possession_state': [{'object_id': 'obj_01', 'holder': '维克托·奥古斯特', 'status': '塞回战术裤侧袋'}],
        }

        updated = _add_lightweight_knowledge_delta(state, '维克托·奥古斯特把运动胶布塞回战术裤侧袋。')

        self.assertEqual(
            updated['knowledge_scope']['protagonist']['learned'],
            ['运动胶布由维克托·奥古斯特持有，状态为塞回战术裤侧袋'],
        )

    def test_state_keeper_environment_filter_is_not_card_name_specific(self):
        from backend.state_keeper import _looks_like_environment_entity

        self.assertFalse(_looks_like_environment_entity('陆姑娘', '当前场景人物'))
        self.assertTrue(_looks_like_environment_entity('轻功', '技能'))

    def test_object_heavy_turn_detects_known_object_transfer(self):
        state = {'tracked_objects': [{'object_id': 'obj_01', 'label': '铜牌', 'kind': 'token'}]}

        self.assertTrue(_is_object_heavy_turn('继续看着', '林越放回铜牌，退回门边。', state))
        self.assertFalse(_is_object_heavy_turn('继续看着', '林越看向库房，退回门边。', state))
        self.assertFalse(_is_object_heavy_turn('继续看着', '林越放回银簪，退回门边。', state))

    def test_turn_audit_is_compact_and_stored_in_meta(self):
        context = {
            'context_audit': {
                'selector_version': 2,
                'inject_lorebook_text': True,
                'event_hits': [{'event_id': 'evt_0001', 'summary': '很长的正文不应进入审计'}],
                'summary_chunk_hits': [{'chunk_id': 'chunk_0001', 'dense_summary': ['正文']}],
                'npc_profile_targets': ['韩骁', '资料管理员'],
                'npc_profile_load': {
                    'reason': 'target_profile_missing',
                    'missing': ['韩骁', '资料管理员'],
                    'loaded': [],
                    'available_profile_names': ['维克托'],
                },
            },
            'lorebook_injection': {'items': [{'id': 'entry_1', 'content': '不应进入审计'}], 'total_chars': 20, 'source_hit_chars': 15, 'index_hit_chars': 9, 'foundation_chars': 30, 'effective_total_chars': 45, 'mode': 'selected'},
            'lorebook_text': '全文不应进入审计',
            'system_npc_candidates': [{'name': '甲'}],
            'selected_summary_chunks': [{'chunk_id': 'chunk_0001'}],
            'event_summaries': [{'event_id': 'evt_0001'}],
        }

        audit = _build_turn_audit(context, turn_id='turn-0001', prompt_stats=[{'label': 'A', 'chars': 3}], force_full_keeper=True, force_full_keeper_reason='object_heavy_turn', state_keeper_diagnostics={'provider_used': 'llm'})
        meta: dict[str, Any] = {}
        _store_turn_audit(meta, audit)

        self.assertEqual(meta['last_turn_audit']['selector']['event_hit_ids'], ['evt_0001'])
        self.assertEqual(meta['last_turn_audit']['selector']['npc_profile_load_reason'], 'target_profile_missing')
        self.assertEqual(meta['last_turn_audit']['selector']['npc_profile_missing_names'], ['韩骁', '资料管理员'])
        self.assertEqual(meta['turn_audits'][0]['keeper']['provider_used'], 'llm')
        self.assertEqual(meta['last_turn_audit']['lorebook_injection']['effective_total_chars'], 45)
        self.assertEqual(meta['last_turn_audit']['lorebook_injection']['source_hit_chars'], 15)
        self.assertNotIn('content', str(meta['last_turn_audit']['lorebook_injection']))

    def test_summary_chunk_keeps_metadata_generic_and_payload_driven(self):
        pairs = [
            ('继续观察', '【傍晚，旧渡口库房】\n顾青衣看着林越把铜牌放回木匣。'),
        ]

        fallback = _fallback_chunk(chunk_id='chunk_0001', turn_start=1, turn_end=1, pairs=pairs)
        normalized = _normalize_chunk({
            'dense_summary': ['林越在旧渡口库房放回铜牌。'],
            'actors_mentioned': ['林越'],
            'objects_mentioned': ['铜牌'],
            'locations': ['旧渡口库房'],
        }, chunk_id='chunk_0001', turn_start=1, turn_end=1, pairs=pairs, provider='llm')

        self.assertEqual(fallback['actors_mentioned'], [])
        self.assertEqual(fallback['objects_mentioned'], [])
        self.assertEqual(fallback['locations'], ['旧渡口库房'])
        self.assertEqual(fallback['time_start'], '傍晚')
        self.assertEqual(fallback['time_end'], '傍晚')
        self.assertEqual(normalized['actors_mentioned'], ['林越'])
        self.assertEqual(normalized['objects_mentioned'], ['铜牌'])
        self.assertEqual(normalized['time_start'], '傍晚')
        self.assertEqual(normalized['time_end'], '傍晚')
        self.assertNotIn('护具（护胸、', normalized['keywords'])
        self.assertNotIn('维克托在', normalized['keywords'])

    def test_summary_chunk_repairs_protagonist_name_drift(self):
        pairs = [
            ('继续观察', '陆小环把铜牌收回袖中，沿着旧渡口往前走。'),
        ]

        with patch('backend.summary_chunks.protagonist_names', return_value={'陆小环'}):
            normalized = _normalize_chunk({
                'dense_summary': ['陆小盘把铜牌收回袖中。'],
                'key_events': ['陆小盘保管铜牌。'],
                'actors_mentioned': ['陆小盘'],
                'keywords': ['陆小盘', '铜牌'],
            }, chunk_id='chunk_0001', turn_start=1, turn_end=1, pairs=pairs, provider='llm')

        self.assertEqual(normalized['dense_summary'], ['陆小环把铜牌收回袖中。'])
        self.assertEqual(normalized['key_events'], ['陆小环保管铜牌。'])
        self.assertEqual(normalized['actors_mentioned'], ['陆小环'])
        self.assertIn('陆小环', normalized['keywords'])
        self.assertNotIn('陆小盘', normalized['keywords'])

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
