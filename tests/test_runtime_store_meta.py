"""Unit tests for runtime_store.save_meta idempotency-cache pruning.

The idempotency cache (meta.processed_client_turn_ids) is capped so meta.json
stays small. The prune must keep the MOST RECENT entries by insertion order
(= turn order), not the lexically-smallest keys: client_turn_ids are
client-supplied and need not sort chronologically.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import runtime_store as rs  # noqa: E402


class SaveMetaPruneTests(unittest.TestCase):
    def _save_and_reload(self, meta):
        with TemporaryDirectory() as d:
            meta_path = Path(d) / 'meta.json'
            with mock.patch.object(rs, 'session_paths', lambda _sid: {'meta': meta_path}):
                rs.save_meta('s', meta)
                return json.loads(meta_path.read_text(encoding='utf-8'))

    def test_cache_capped_to_max(self):
        cap = rs.MAX_IDEMPOTENCY_CACHE
        cache = {f'ct-{i:03d}': {'reply': str(i)} for i in range(cap + 6)}
        out = self._save_and_reload({'last_turn_id': 99, 'processed_client_turn_ids': cache})
        self.assertEqual(len(out['processed_client_turn_ids']), cap)
        self.assertEqual(out['last_turn_id'], 99)

    def test_keeps_most_recent_by_insertion_not_lexical(self):
        cap = rs.MAX_IDEMPOTENCY_CACHE
        # 'aaa-last' is inserted LAST but is lexically smallest; the old
        # sorted-key prune would have wrongly dropped it.
        keys = [f'zzz-{i:03d}' for i in range(cap)] + ['aaa-last']
        cache = {k: {'i': i} for i, k in enumerate(keys)}
        kept = self._save_and_reload({'last_turn_id': 1, 'processed_client_turn_ids': cache})['processed_client_turn_ids']
        self.assertEqual(len(kept), cap)
        self.assertIn('aaa-last', kept)        # newest kept despite lexically smallest
        self.assertNotIn('zzz-000', kept)      # oldest insertion dropped

    def test_under_cap_is_left_intact(self):
        cache = {'ct-1': {'reply': 'a'}, 'ct-2': {'reply': 'b'}}
        kept = self._save_and_reload({'last_turn_id': 2, 'processed_client_turn_ids': dict(cache)})['processed_client_turn_ids']
        self.assertEqual(kept, cache)


if __name__ == '__main__':
    unittest.main()
