#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import keeper_archive
import keeper_record_retriever
from mid_context_agent import build_mid_window_digest


def _history(pair_count: int) -> list[dict]:
    items = []
    for idx in range(1, pair_count + 1):
        items.append({'role': 'user', 'content': f'第{idx}轮观察茶摊线索'})
        items.append({'role': 'assistant', 'content': f'第{idx}轮茶摊调查持续推进，掌柜和药铺线索被反复提及'})
    return items


def _history_with_partial() -> list[dict]:
    items = _history(12)
    items.append({'role': 'user', 'content': '触发半截回复的动作'})
    items.append({'role': 'assistant', 'content': '半截回复', 'completion_status': 'partial'})
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

    def test_keeper_archive_ignores_partial_assistant_pairs(self):
        with patch.object(keeper_archive, 'load_history', return_value=_history_with_partial()), \
                patch.object(keeper_archive, 'load_state', return_value={'location': '茶摊'}), \
                patch.object(keeper_archive, 'ensure_npc_registry', return_value={'entities': []}), \
                patch.object(keeper_archive, 'ensure_object_registry', return_value=None), \
                patch.object(keeper_archive, 'ensure_clue_registry', return_value=None):
            archive = keeper_archive.build_keeper_record_archive(
                'test-session',
                window_size=10,
                overlap_recent_pairs=1,
                use_llm=False,
            )

        self.assertEqual(archive['source_pair_count'], 12)
        self.assertNotIn('半截回复', str(archive['records']))

    def test_retrieve_keeper_records_can_disable_archive_writes(self):
        stale_archive = {
            'version': 1,
            'window_size': 10,
            'source_pair_count': 30,
            'records': [
                {
                    'window': {'end_pair_index': 30},
                    'location_anchor': '茶摊',
                    'stable_entities': [{'name': '掌柜'}],
                    'tracked_objects': [],
                    'ongoing_events': ['掌柜继续追查茶摊线索'],
                    'open_loops': [],
                    'history_digest': [],
                },
                {
                    'window': {'end_pair_index': 10},
                    'location_anchor': '茶摊',
                    'stable_entities': [{'name': '掌柜'}],
                    'tracked_objects': [],
                    'ongoing_events': ['掌柜追查茶摊线索'],
                    'open_loops': [],
                    'history_digest': [],
                },
            ],
        }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value=stale_archive), \
                patch.object(keeper_record_retriever, 'save_keeper_record_archive') as save_archive, \
                patch.object(keeper_record_retriever, 'build_keeper_record_archive') as build_archive:
            result = keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊', 'onstage_npcs': ['掌柜'], 'main_event': '掌柜追查茶摊线索'},
                current_pair_count=12,
                recent_window_pairs=1,
                allow_archive_write=False,
            )

        save_archive.assert_not_called()
        build_archive.assert_not_called()
        self.assertEqual([record['window']['end_pair_index'] for record in result['records']], [10])

    def test_retrieve_keeper_records_keeps_default_archive_write_behavior(self):
        stale_archive = {
            'version': 1,
            'window_size': 10,
            'source_pair_count': 30,
            'records': [{'window': {'end_pair_index': 30}, 'location_anchor': '茶摊'}],
        }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value=stale_archive), \
                patch.object(keeper_record_retriever, 'save_keeper_record_archive') as save_archive, \
                patch.object(keeper_record_retriever, 'build_keeper_record_archive') as build_archive:
            keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊'},
                current_pair_count=12,
                recent_window_pairs=1,
            )

        save_archive.assert_called_once()
        build_archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
