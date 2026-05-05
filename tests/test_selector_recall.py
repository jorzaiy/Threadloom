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
                'location': '鹰巢特工学院训练场器械区',
                'main_event': '维克托宣布前往战术教室参加观察与记忆测试',
                'onstage_npcs': ['维克托'],
                'relevant_npcs': [],
                'immediate_risks': ['观察与记忆测试'],
            },
            recent_history=[{'role': 'user', 'content': '继续观察同学训练'}],
            keeper_records={'records': []},
            active_threads=[],
            important_npcs=[{'primary_label': '维克托', 'role_label': '教官'}],
            onstage=['维克托'],
            relevant=[],
            lorebook_entries=[],
            system_npc_candidates=[],
            lorebook_npc_candidates=[],
            event_summaries=[{
                'event_id': 'evt_training_001',
                'summary': '维克托在训练场组织障碍组合，并预告观察与记忆测试。',
                'actors': ['维克托'],
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
                'summary': '维克托在器械区组织引体向上，学员刻意拉开与教官的距离。',
                'actors': ['维克托·奥古斯特'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0003',
                'turn_id': 'turn-0003',
                'summary': '陆小环完成十二个引体向上，维克托判定勉强达标。',
                'actors': ['维克托·奥古斯特'],
                'clues': ['学员刻意拉开与教官的距离'],
            },
            {
                'event_id': 'evt_0011',
                'turn_id': 'turn-0011',
                'summary': '陆小环在障碍场观察两米高矮墙，寻找墙顶和墙根鞋印作为借力点。',
                'actors': ['维克托·奥古斯特'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
            {
                'event_id': 'evt_0012',
                'turn_id': 'turn-0012',
                'summary': '陆小环计算矮墙助跑起跳点，维克托宣布剩余两分钟时限。',
                'actors': ['维克托·奥古斯特'],
                'clues': ['左边双杠握把间距比其他宽两寸'],
            },
        ]

        hits = event_summary_hits(
            events,
            state_json={
                'location': '鹰巢特工学院主训练场障碍场矮墙西侧泥地',
                'main_event': '陆小环准备挑战矮墙并计算助跑距离',
                'onstage_npcs': ['维克托·奥古斯特'],
                'immediate_risks': ['学员刻意拉开与教官的距离'],
                'carryover_signals': [{'type': 'clue', 'text': '学员刻意拉开与教官的距离'}],
            },
            recent_history=[{'role': 'user', 'content': '看着矮墙计算借力的位置和距离'}],
            user_text='准备试着翻过矮墙',
        )

        self.assertEqual([hit['event_id'] for hit in hits[:2]], ['evt_0012', 'evt_0011'])

    def test_event_recall_tie_breaks_to_newer_turn(self):
        events = [
            {'event_id': 'evt_0001', 'turn_id': 'turn-0001', 'summary': '维克托宣布训练规则。', 'actors': ['维克托']},
            {'event_id': 'evt_0002', 'turn_id': 'turn-0002', 'summary': '维克托宣布训练规则。', 'actors': ['维克托']},
        ]

        hits = event_summary_hits(
            events,
            state_json={'main_event': '维克托宣布训练规则', 'onstage_npcs': ['维克托']},
            recent_history=[],
            user_text='继续听训练规则',
        )

        self.assertEqual(hits[0]['event_id'], 'evt_0002')


if __name__ == '__main__':
    unittest.main()
