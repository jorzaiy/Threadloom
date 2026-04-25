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


if __name__ == '__main__':
    unittest.main()
