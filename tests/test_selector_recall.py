#!/usr/bin/env python3
import unittest

from backend.selector import build_selector_decision


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


if __name__ == '__main__':
    unittest.main()
