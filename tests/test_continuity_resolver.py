"""Unit tests for backend/continuity_resolver.py.

resolve_important_npc_continuity decides whether a locked important NPC that is
not currently onstage should be re-surfaced into relevant_npcs, using a small
evidence score (name/role/location/event match + retained flag). It must never
mutate its input and must cap relevant_npcs at 6.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from backend.continuity_resolver import resolve_important_npc_continuity  # noqa: E402


def _important(label, **kw):
    item = {'primary_label': label, 'locked': True}
    item.update(kw)
    return item


class ContinuityResolverTests(unittest.TestCase):
    def test_no_important_npcs_leaves_relevant_unchanged(self):
        out = resolve_important_npc_continuity({'relevant_npcs': ['A'], 'important_npcs': []})
        self.assertEqual(out['relevant_npcs'], ['A'])

    def test_name_in_main_event_promotes_to_relevant(self):
        # name match in the text pool is worth +2 -> enough on its own.
        out = resolve_important_npc_continuity({
            'main_event': '老王在城门口拦住了去路',
            'important_npcs': [_important('老王')],
        })
        self.assertIn('老王', out['relevant_npcs'])

    def test_single_weak_signal_is_not_enough(self):
        # last_location match alone is +1 (< 2) -> not promoted.
        out = resolve_important_npc_continuity({
            'location': '茶馆',
            'important_npcs': [_important('老王', last_location='茶馆')],
        })
        self.assertNotIn('老王', out['relevant_npcs'])

    def test_two_weak_signals_promote(self):
        # last_location (+1) + retained (+1) = 2 -> promoted.
        out = resolve_important_npc_continuity({
            'location': '茶馆',
            'important_npcs': [_important('老王', last_location='茶馆', retained=True)],
        })
        self.assertIn('老王', out['relevant_npcs'])

    def test_unlocked_important_is_ignored(self):
        out = resolve_important_npc_continuity({
            'main_event': '老王来了',
            'important_npcs': [{'primary_label': '老王', 'locked': False}],
        })
        self.assertNotIn('老王', out['relevant_npcs'])

    def test_inactive_too_long_is_skipped(self):
        out = resolve_important_npc_continuity({
            'main_event': '老王来了',
            'important_npcs': [_important('老王', inactive_turns=4)],
        })
        self.assertNotIn('老王', out['relevant_npcs'])

    def test_already_relevant_not_duplicated(self):
        out = resolve_important_npc_continuity({
            'main_event': '老王来了',
            'relevant_npcs': ['老王'],
            'important_npcs': [_important('老王')],
        })
        self.assertEqual(out['relevant_npcs'].count('老王'), 1)

    def test_relevant_capped_at_six(self):
        out = resolve_important_npc_continuity({
            'relevant_npcs': ['R1', 'R2', 'R3', 'R4', 'R5', 'R6'],
            'main_event': '甲 乙 丙 出现',
            'important_npcs': [_important('甲'), _important('乙'), _important('丙')],
        })
        self.assertEqual(len(out['relevant_npcs']), 6)

    def test_input_is_not_mutated(self):
        state = {'main_event': '老王来了', 'important_npcs': [_important('老王')]}
        out = resolve_important_npc_continuity(state)
        self.assertIn('老王', out['relevant_npcs'])
        # The original dict must be untouched (function works on a deepcopy).
        self.assertNotIn('relevant_npcs', state)


if __name__ == '__main__':
    unittest.main()
