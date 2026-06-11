"""Regression: per-NPC `last_main_event` must not be clobbered with the current
scene's global main_event for NPCs who are not on-stage this turn (e23032).

Symptom that motivated this: every important_npc in a long session shared an
identical `last_main_event` (the current frame), even NPCs inactive for 100+
turns in other towns. The clobber happened because the write was ungated while
the adjacent `last_location` write was correctly gated on on-stage presence.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend.state_bridge import normalize_state_dict  # noqa: E402
from backend.important_npc_tracker import update_important_npcs  # noqa: E402


def _important(label, *, last_event, last_loc, present, aliases=None):
    return {
        'key': f'important:{label}',
        'primary_label': label,
        'aliases': aliases or [],
        'role_label': '同行旅人',
        'anchor_type': 'continuous',
        'importance_score': 8,
        'locked': True,
        'retained': not present,
        'present_now': present,
        'inactive_turns': 0 if present else 5,
        'last_location': last_loc,
        'last_main_event': last_event,
    }


class ImportantNpcLastEventTests(unittest.TestCase):
    def test_normalize_state_dict_preserves_absent_npc_anchor(self):
        """state_bridge: an off-stage important NPC keeps its own last_main_event
        even when this turn's (accepted, different) main_event is something else."""
        old_event = '张麻子在北门盘问路引。'
        new_event = '三根触手从门缝探出拦路，随后主动缩回。'
        npcs = [_important('张麻子', last_event=old_event, last_loc='北门', present=False)]
        prev = {'time': '深夜', 'location': '北门', 'main_event': old_event, 'important_npcs': npcs}
        current = {
            'time': '深夜',
            'location': '东巷',
            'main_event': new_event,
            'immediate_goal': '观察门缝动静。',
            'onstage_npcs': [],
            'scene_entities': [],
            'important_npcs': [dict(n) for n in npcs],
        }

        out = normalize_state_dict(current, prev_state=prev)
        # Guard: the turn's main_event must actually be accepted, or the test below
        # would pass for the wrong reason (continuity guard reverting to prev).
        self.assertEqual(out.get('main_event'), new_event)

        by_label = {n['primary_label']: n for n in out.get('important_npcs', [])}
        self.assertIn('张麻子', by_label)
        self.assertEqual(by_label['张麻子']['last_main_event'], old_event)
        self.assertNotEqual(by_label['张麻子']['last_main_event'], new_event)
        self.assertEqual(by_label['张麻子']['last_location'], '北门')

    def test_update_important_npcs_carried_branch_keeps_anchor(self):
        """tracker: an NPC absent from the scene this turn is carried forward with
        its prior anchor, not the current main_event."""
        old_event = '张麻子在北门盘问路引。'
        state = {
            'session_id': '',
            'location': '东巷',
            'main_event': '触手从门缝探出拦路。',
            'scene_entities': [],          # 张麻子 absent this turn -> carried branch
            'onstage_npcs': [],
            'relevant_npcs': [],
            'active_threads': [],
            'continuity_hints': [],
            'important_npcs': [
                _important('张麻子', last_event=old_event, last_loc='北门',
                           present=False, aliases=['张叔', '老张']),
            ],
        }

        out = update_important_npcs(state, history=[], allow_archive_write=False)
        by_label = {n['primary_label']: n for n in out.get('important_npcs', [])}

        self.assertIn('张麻子', by_label)
        self.assertEqual(by_label['张麻子']['last_main_event'], old_event)
        self.assertEqual(by_label['张麻子']['last_location'], '北门')
        self.assertFalse(by_label['张麻子']['present_now'])

    def test_update_important_npcs_onstage_advances_anchor(self):
        """tracker: an on-stage NPC's anchor IS advanced to the current frame
        (guards against over-correcting the fix)."""
        new_event = '触手从门缝探出拦路。'
        state = {
            'session_id': '',
            'location': '东巷',
            'main_event': new_event,
            'scene_entities': [
                {'entity_id': 'scene_npc_01', 'primary_label': '张麻子',
                 'aliases': ['张叔', '老张'], 'role_label': '当前互动核心人物', 'onstage': True},
            ],
            'onstage_npcs': ['张麻子'],
            'relevant_npcs': [],
            'active_threads': [],
            'continuity_hints': [],
            'important_npcs': [
                _important('张麻子', last_event='张麻子在北门盘问路引。', last_loc='北门',
                           present=True, aliases=['张叔', '老张']),
            ],
        }

        out = update_important_npcs(state, history=[], allow_archive_write=False)
        by_label = {n['primary_label']: n for n in out.get('important_npcs', [])}

        self.assertIn('张麻子', by_label)
        self.assertTrue(by_label['张麻子']['present_now'])
        self.assertEqual(by_label['张麻子']['last_main_event'], new_event)
        self.assertEqual(by_label['张麻子']['last_location'], '东巷')


if __name__ == '__main__':
    unittest.main()
