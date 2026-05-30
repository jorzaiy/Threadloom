"""Tests for event-recall recent-window exclusion (e23032 backlog #3).

The event index (event_summary_hits -> 【命中事件索引】) is meant to surface
OUT-of-window history. Recency bias made it re-surface events already in the
recent window (full prose + per-turn outline), wasting prompt budget (e23032
turn-227: 3 of 4 hits were turns 224/225/226, already in the 6-turn full window).
recent_window_turns excludes events whose turn is inside the recent window.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from selector import event_summary_hits  # noqa: E402


def _events(lo, hi):
    return [
        {
            'event_id': f'evt_{t:04d}', 'turn_id': f'turn-{t:04d}',
            'summary': '青铜古镜在断桥被人发现并取走', 'actors': ['陆小环'], 'clues': [],
        }
        for t in range(lo, hi + 1)
    ]


STATE = {'location': '断桥', 'main_event': '追查青铜古镜下落', 'onstage_npcs': ['陆小环'], 'relevant_npcs': []}
QUERY = '青铜古镜现在在哪'


class EventRecallWindowExclusionTests(unittest.TestCase):
    def test_baseline_without_window_surfaces_in_window_events(self):
        # No exclusion: recency bias pulls in recent (in-window) turns.
        hits = event_summary_hits(_events(10, 30), state_json=STATE, recent_history=[], user_text=QUERY)
        self.assertTrue(hits)
        self.assertTrue(any(h['turn_index'] > 18 for h in hits))

    def test_window_excludes_in_window_events(self):
        # latest_turn=30, window=12 -> floor=18 -> turns 19..30 excluded; the
        # out-of-window events (<=18) are still recalled.
        hits = event_summary_hits(_events(10, 30), state_json=STATE, recent_history=[], user_text=QUERY, recent_window_turns=12)
        self.assertTrue(hits)
        self.assertTrue(all(h['turn_index'] <= 18 for h in hits), [h['turn_index'] for h in hits])

    def test_all_in_window_yields_no_recall(self):
        # Every event is inside the window -> nothing left to recall.
        hits = event_summary_hits(_events(25, 30), state_json=STATE, recent_history=[], user_text=QUERY, recent_window_turns=12)
        self.assertEqual(hits, [])

    def test_zero_window_is_no_op(self):
        # Default (0) preserves the old behavior — nothing excluded.
        hits = event_summary_hits(_events(10, 30), state_json=STATE, recent_history=[], user_text=QUERY, recent_window_turns=0)
        self.assertTrue(any(h['turn_index'] > 18 for h in hits))


if __name__ == '__main__':
    unittest.main()
