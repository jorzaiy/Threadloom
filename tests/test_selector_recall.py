#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.selector import build_selector_decision, event_summary_hits


class SelectorRecallTests(unittest.TestCase):
    def test_selector_hits_event_summaries_by_current_actor_and_topic(self):
        decision = build_selector_decision(
            state_json={
                'location': '青岚训练基地训练场器械区',
                'main_event': '教官甲宣布前往战术教室参加观察与记忆测试',
                'onstage_npcs': ['教官甲'],
                'relevant_npcs': [],
                'immediate_risks': ['观察与记忆测试'],
            },
            recent_history=[{'role': 'user', 'content': '继续观察同学训练'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '教官甲', 'role_label': '教官'}],
            onstage=['教官甲'],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_training_001',
                'summary': '教官甲在训练场组织障碍组合，并预告观察与记忆测试。',
                'actors': ['教官甲'],
                'keywords': ['训练场', '观察与记忆测试'],
            }],
            summary_text='',
            summary_chunks=[],
            user_text='靠着树继续看训练',
        )

        self.assertEqual(decision['event_hits'][0]['event_id'], 'evt_training_001')
        self.assertGreaterEqual(decision['event_hits'][0]['score'], 2)

    def test_event_recall_prefers_current_scene_over_stale_same_actor_events(self):
        events = [
            {
                'event_id': 'evt_0002',
                'turn_id': 'turn-0002',
                'summary': '教官甲在器械区组织引体向上，学员刻意拉开与教官的距离。',
                'actors': ['教官甲'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0003',
                'turn_id': 'turn-0003',
                'summary': '主角完成十二个引体向上，教官甲判定勉强达标。',
                'actors': ['教官甲'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0011',
                'turn_id': 'turn-0011',
                'summary': '主角在障碍场观察两米高矮墙，寻找墙顶和墙根鞋印作为借力点。',
                'actors': ['教官甲'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
            {
                'event_id': 'evt_0012',
                'turn_id': 'turn-0012',
                'summary': '主角计算矮墙助跑起跳点，教官甲宣布剩余两分钟时限。',
                'actors': ['教官甲'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
        ]

        hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地主训练场障碍场矮墙西侧泥地',
                'main_event': '主角准备挑战矮墙并计算助跑距离',
                'onstage_npcs': ['教官甲'],
                'immediate_risks': ['学员刻意拉开与教官的距离'],
                'carryover_signals': [{'type': 'clue', 'text': '学员刻意拉开与教官的距离'}],
            },
            recent_history=[{'role': 'user', 'content': '看着矮墙计算借力的位置和距离'}],
            user_text='准备试着翻过矮墙',
        )

        self.assertEqual([hit['event_id'] for hit in hits[:2]], ['evt_0012', 'evt_0011'])

    def test_event_recall_tie_breaks_to_newer_turn(self):
        events = [
            {'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '教官甲宣布训练规则。', 'actors': ['教官甲']},
            {'event_id': 'evt_0002', 'turn_id': 'turn-0002', 'summary': '教官甲宣布训练规则。', 'actors': ['教官甲']},
        ]

        hits = event_summary_hits(
            events,
            state_json={'main_event': '教官甲宣布训练规则', 'onstage_npcs': ['教官甲']},
            recent_history=[],
            user_text='继续听训练规则',
        )

        self.assertEqual(hits[0]['event_id'], 'evt_0002')

    def test_event_recall_skips_carryover_only_stale_clue_hits_after_scene_shift(self):
        events = [
            {
                'event_id': 'evt_0004',
                'turn_id': 'turn-0004',
                'summary': '教官甲在训练场记录体检日单独跟进。',
                'actors': ['教官甲'],
                'clues': ["教官甲记录'体检日，单独跟进'。"],
            },
            {
                'event_id': 'evt_0014',
                'turn_id': 'turn-0014',
                'summary': '安全组人员在图书馆指出系统记录与主角说法不符。',
                'actors': ['拿平板的人', '管理员'],
                'clues': [],
            },
        ]

        hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地图书馆公共终端区',
                'main_event': '安全组人员要求主角前往训练部安全组谈话',
                'onstage_npcs': ['拿平板的人', '管理员'],
                'relevant_npcs': [],
                'carryover_signals': [{'type': 'clue', 'text': "教官甲记录'体检日，单独跟进'"}],
            },
            recent_history=[{'role': 'user', 'content': '我在查资料'}],
            user_text='跟着安全组人员走',
        )

        self.assertEqual([hit['event_id'] for hit in hits], ['evt_0014'])

    def test_event_recall_skips_sensitive_actor_only_hits_on_quiet_turn(self):
        events = [{
            'event_id': 'evt_0008',
            'turn_id': 'turn-0008',
            'summary': '教官甲注意到主角旧伤导致呼吸困难，后续存在暴露风险。',
            'actors': ['教官甲'],
            'clues': ['旧伤导致呼吸困难，存在暴露风险'],
        }]

        quiet_hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地食堂',
                'main_event': '主角坐在角落吃午饭',
                'onstage_npcs': ['教官甲'],
            },
            recent_history=[{'role': 'assistant', 'content': '教官甲之前巡视过训练场。'}],
            user_text='低头吃完米饭和菜',
        )
        direct_hits = event_summary_hits(
            events,
            state_json={
                'location': '青岚训练基地宿舍',
                'main_event': '主角发现旧伤牵扯得呼吸困难',
                'onstage_npcs': [],
            },
            recent_history=[],
            user_text='旧伤牵扯得呼吸困难',
        )

        self.assertEqual(quiet_hits, [])
        self.assertEqual(direct_hits[0]['event_id'], 'evt_0008')

    def test_selector_targets_locked_important_npc_from_selected_event(self):
        decision = build_selector_decision(
            state_json={
                'location': '青岚训练基地训练楼靶场',
                'main_event': '主角查看射击成绩',
                'onstage_npcs': [],
                'relevant_npcs': [],
            },
            recent_history=[{'role': 'assistant', 'content': '电子屏显示成绩逐轮提升。'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '教官甲', 'role_label': '教官', 'locked': True}],
            onstage=[],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_0025',
                'turn_id': 'turn-0025',
                'summary': '主角查看成绩时，教官甲折返回来称赞其成绩并提醒下午理论课。',
                'actors': ['教官甲'],
                'keywords': ['射击成绩', '理论课'],
            }],
            summary_text='',
            summary_chunks=[],
            user_text='看自己的射击成绩',
        )

        self.assertIn('教官甲', decision['npc_profile_targets'])
        self.assertEqual(decision['event_hits'][0]['event_id'], 'evt_0025')


if __name__ == '__main__':
    unittest.main()
