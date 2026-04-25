#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import state_updater


class KeeperGenericFilterTests(unittest.TestCase):
    def test_table_fragment_is_not_character_name(self):
        self.assertFalse(state_updater._looks_like_character_name('角那桌一', set()))
        self.assertFalse(state_updater._looks_like_character_name('斜对角那桌', set()))

    def test_prose_fragments_are_not_state_signals(self):
        self.assertEqual(state_updater._state_like_signal('他压低了声，却压不住语气里的兴奋：“你听没听说'), '')
        self.assertEqual(state_updater._state_like_signal('她把壶放下，拿布擦了擦手'), '')
        self.assertEqual(state_updater._state_like_signal('年长挑夫笑着打断'), '')

    def test_meaningful_signals_survive(self):
        self.assertEqual(state_updater._state_like_signal('东市昨夜又封了半条街'), '东市昨夜又封了半条街')
        self.assertEqual(state_updater._state_like_signal('陌生人反复追问遗失文件'), '陌生人反复追问遗失文件')

    def test_action_anchored_appellations_are_characters(self):
        text = '老汉低声提醒她城里不太平，学徒递给她一包药，官差拦住路人盘问。'
        names = state_updater.extract_generic_character_names(text, {}, {}, [], limit=6)

        self.assertIn('老汉', names)
        self.assertIn('学徒', names)
        self.assertIn('官差', names)

    def test_function_fragments_are_not_character_names(self):
        for name in ['也没', '谁知', '真正', '反倒', '不爱', '至少', '随口', '忙嘿嘿一', '嘴里含糊']:
            self.assertFalse(state_updater._looks_like_character_name(name, set()))

    def test_stale_main_event_can_be_replaced(self):
        self.assertTrue(state_updater._should_replace_stale_main_event(
            '掌柜含糊其辞',
            '官差在城门盘问过路行人',
            current_onstage=['官差'],
        ))


if __name__ == '__main__':
    unittest.main()
