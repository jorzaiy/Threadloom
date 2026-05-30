"""Unit tests for the pure helpers extracted out of handle_message.

handle_message itself has no direct unit coverage (test_regenerate_turn mocks it
wholesale). These cover the small, side-effect-free units pulled out of it so
their behavior is pinned independently of the 800-line orchestrator.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import handler_message as hm  # noqa: E402


class RecentHistoryPairsTests(unittest.TestCase):
    def _history(self, n):
        out = []
        for i in range(n):
            out += [{'role': 'user', 'content': f'q{i}'}, {'role': 'assistant', 'content': f'a{i}'}]
        return out

    def test_pairs_user_then_assistant(self):
        self.assertEqual(
            hm._recent_history_pairs(self._history(2), limit=3),
            [('q0', 'a0'), ('q1', 'a1')],
        )

    def test_limit_keeps_only_the_last_pairs(self):
        self.assertEqual(
            hm._recent_history_pairs(self._history(5), limit=2),
            [('q3', 'a3'), ('q4', 'a4')],
        )

    def test_trailing_unpaired_user_is_ignored(self):
        history = [
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': 'a'},
            {'role': 'user', 'content': 'dangling'},
        ]
        self.assertEqual(hm._recent_history_pairs(history), [('q', 'a')])

    def test_empty_history(self):
        self.assertEqual(hm._recent_history_pairs([]), [])


class ApplyPendingNpcBiosTests(unittest.TestCase):
    def test_applies_bio_to_existing_actor_and_drops_marker(self):
        state = {'_pending_npc_bios': [{'actor_id': 'a1', 'bio': '冷静的剑客'}], 'actors': {'a1': {'name': '老王'}}}
        hm._apply_pending_npc_bios(state, 7)
        self.assertNotIn('_pending_npc_bios', state)
        self.assertEqual(state['actors']['a1']['bio'], '冷静的剑客')
        self.assertEqual(state['actors']['a1']['bio_updated_turn'], 7)

    def test_unknown_actor_is_skipped(self):
        state = {'_pending_npc_bios': [{'actor_id': 'ghost', 'bio': 'x'}], 'actors': {'a1': {}}}
        hm._apply_pending_npc_bios(state, 1)
        self.assertNotIn('bio', state['actors']['a1'])

    def test_empty_bio_is_skipped(self):
        state = {'_pending_npc_bios': [{'actor_id': 'a1', 'bio': ''}], 'actors': {'a1': {}}}
        hm._apply_pending_npc_bios(state, 1)
        self.assertNotIn('bio', state['actors']['a1'])

    def test_missing_marker_is_noop(self):
        state = {'actors': {'a1': {}}}
        hm._apply_pending_npc_bios(state, 1)
        self.assertEqual(state['actors'], {'a1': {}})


if __name__ == '__main__':
    unittest.main()
