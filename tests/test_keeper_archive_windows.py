#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import keeper_archive
from mid_context_agent import build_mid_window_digest


def _history(pair_count: int) -> list[dict]:
    items = []
    for idx in range(1, pair_count + 1):
        items.append({'role': 'user', 'content': f'第{idx}轮观察茶摊线索'})
        items.append({'role': 'assistant', 'content': f'第{idx}轮茶摊调查持续推进，掌柜和药铺线索被反复提及'})
    return items


class KeeperArchiveWindowTests(unittest.TestCase):
    def test_mid_digest_can_digest_explicit_archive_window_without_dropping_tail(self):
        digest = build_mid_window_digest(
            history=_history(10),
            hard_anchors={'location': '茶摊'},
            max_pairs=10,
            use_llm=False,
            exclude_recent_pairs=0,
        )

        self.assertEqual(digest['window']['pair_count'], 10)
        self.assertEqual(digest['window']['from_turn'], 'turn-0001')
        self.assertEqual(digest['window']['to_turn'], 'turn-0010')
        self.assertIn('第10轮', digest['history_digest'][-1]['user'])

    def test_keeper_archive_window_metadata_matches_digest_scope(self):
        with patch.object(keeper_archive, 'load_history', return_value=_history(13)), \
                patch.object(keeper_archive, 'load_state', return_value={'location': '茶摊'}), \
                patch.object(keeper_archive, 'ensure_npc_registry', return_value={'entities': []}), \
                patch.object(keeper_archive, 'ensure_object_registry', return_value=None), \
                patch.object(keeper_archive, 'ensure_clue_registry', return_value=None):
            archive = keeper_archive.build_keeper_record_archive(
                'test-session',
                window_size=10,
                overlap_recent_pairs=3,
                use_llm=False,
            )

        self.assertEqual(archive['source_pair_count'], 13)
        self.assertEqual(len(archive['records']), 1)
        record = archive['records'][0]
        self.assertEqual(record['window']['pair_count'], 10)
        self.assertEqual(record['window']['from_turn'], 'turn-0001')
        self.assertEqual(record['window']['to_turn'], 'turn-0010')
        self.assertEqual(record['window']['end_pair_index'], 10)
        self.assertIn('第10轮', record['history_digest'][-1]['user'])


if __name__ == '__main__':
    unittest.main()
