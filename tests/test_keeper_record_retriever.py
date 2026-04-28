#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent / 'backend'))

import keeper_record_retriever


class KeeperRecordRetrieverTests(unittest.TestCase):
    def test_archive_refresh_defaults_to_safe_mode(self):
        calls = []

        def fake_build_keeper_record_archive(session_id, **kwargs):
            calls.append(kwargs)
            return {
                'version': 1,
                'window_size': 10,
                'source_pair_count': 16,
                'records': [],
            }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value={
            'version': 1,
            'window_size': 10,
            'source_pair_count': 10,
            'records': [],
        }), patch.object(keeper_record_retriever, 'build_keeper_record_archive', fake_build_keeper_record_archive), patch.object(keeper_record_retriever, 'save_keeper_record_archive', lambda session_id, archive: None):
            keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊', 'main_event': '主角回想茶摊传闻'},
                current_pair_count=16,
                recent_window_pairs=4,
            )

        self.assertEqual(calls, [{'skip_bootstrap': True, 'use_llm': False}])

    def test_archive_refresh_can_opt_into_llm_bootstrap(self):
        calls = []

        def fake_build_keeper_record_archive(session_id, **kwargs):
            calls.append(kwargs)
            return {
                'version': 1,
                'window_size': 10,
                'source_pair_count': 16,
                'records': [],
            }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value={
            'version': 1,
            'window_size': 10,
            'source_pair_count': 10,
            'records': [],
        }), patch.object(keeper_record_retriever, 'build_keeper_record_archive', fake_build_keeper_record_archive), patch.object(keeper_record_retriever, 'save_keeper_record_archive', lambda session_id, archive: None):
            keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊', 'main_event': '主角回想茶摊传闻'},
                current_pair_count=16,
                recent_window_pairs=4,
                refresh_skip_bootstrap=False,
                refresh_use_llm=True,
            )

        self.assertEqual(calls, [{'skip_bootstrap': False, 'use_llm': True}])

    def test_archive_initial_load_defaults_to_safe_mode(self):
        calls = []

        def fake_load_keeper_record_archive(session_id, **kwargs):
            calls.append(kwargs)
            return {
                'version': 1,
                'window_size': 10,
                'source_pair_count': 0,
                'records': [],
            }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', fake_load_keeper_record_archive):
            keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊', 'main_event': '主角回想茶摊传闻'},
                current_pair_count=0,
                recent_window_pairs=4,
            )

        self.assertEqual(calls, [{'skip_bootstrap': True, 'use_llm': False}])

    def test_prunes_future_records_after_rollback(self):
        saved = []
        archive = {
            'version': 1,
            'window_size': 10,
            'source_pair_count': 20,
            'records': [
                {'window': {'end_pair_index': 8}, 'location_anchor': '茶摊'},
                {'window': {'end_pair_index': 18}, 'location_anchor': '城门'},
            ],
        }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value=archive), patch.object(keeper_record_retriever, 'save_keeper_record_archive', lambda session_id, archive: saved.append(archive)):
            result = keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '茶摊', 'main_event': '主角回到茶摊'},
                current_pair_count=10,
                recent_window_pairs=2,
            )

        self.assertEqual(saved[0]['source_pair_count'], 10)
        self.assertEqual([item['window']['end_pair_index'] for item in saved[0]['records']], [8])
        self.assertEqual([item['window']['end_pair_index'] for item in result['records']], [8])

    def test_refresh_preserves_manual_cleanup_records(self):
        saved = []
        previous = {
            'version': 1,
            'window_size': 10,
            'source_pair_count': 10,
            'records': [
                {
                    'provider': 'manual-cleanup',
                    'window': {'end_pair_index': 10},
                    'location_anchor': '坊署偏厅',
                    'ongoing_events': ['人工整理的纸封与口供摘要'],
                    'stable_entities': [{'name': '文吏'}],
                },
            ],
        }
        refreshed = {
            'version': 1,
            'window_size': 10,
            'source_pair_count': 16,
            'records': [
                {
                    'window': {'end_pair_index': 10},
                    'location_anchor': '错误弱摘要地点',
                    'ongoing_events': ['围绕什么的局势仍在持续演化'],
                    'stable_entities': [{'name': '文吏'}],
                },
            ],
        }

        with patch.object(keeper_record_retriever, 'load_keeper_record_archive', return_value=previous), patch.object(keeper_record_retriever, 'build_keeper_record_archive', return_value=refreshed), patch.object(keeper_record_retriever, 'save_keeper_record_archive', lambda session_id, archive: saved.append(archive)):
            keeper_record_retriever.retrieve_keeper_records(
                'test-session',
                {'location': '坊署偏厅', 'main_event': '陆小环录口供', 'onstage_npcs': ['文吏']},
                current_pair_count=16,
                recent_window_pairs=4,
            )

        self.assertTrue(saved[-1]['manual_cleanup_preserved'])
        self.assertEqual(saved[-1]['records'][0]['provider'], 'manual-cleanup')
        self.assertEqual(saved[-1]['records'][0]['ongoing_events'], ['人工整理的纸封与口供摘要'])


if __name__ == '__main__':
    unittest.main()
