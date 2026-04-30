#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

from backend import paths
from backend.paths import read_json_file, slugify


class PathHelperTests(unittest.TestCase):
    def test_slugify_preserves_existing_character_id_rules(self):
        self.assertEqual(slugify('  维克托 奥古斯特/测试:01  ', 'character'), '维克托-奥古斯特-测试-01')
        self.assertEqual(slugify('abc#$%·中文', 'character'), 'abc·中文')
        self.assertEqual(slugify('  !!!  ', 'character'), 'character')
        self.assertEqual(slugify('', 'character'), 'character')

    def test_read_json_file_matches_existing_utf8_reader(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'data.json'
            path.write_text(json.dumps({'name': '维克托'}, ensure_ascii=False), encoding='utf-8')

            self.assertEqual(read_json_file(path), {'name': '维克托'})

    def test_resolve_layered_source_skips_shared_fallback_under_character_override(self):
        # P2.6 regression: a per-request character override must isolate read
        # paths from the legacy SHARED_ROOT fallback so concurrent imports do
        # not surface a different card's lorebook.
        with tempfile.TemporaryDirectory() as temp_dir:
            original_runtime_root = paths.RUNTIME_DATA_ROOT
            original_shared_root = paths.SHARED_ROOT
            temp_root = Path(temp_dir)
            try:
                paths.RUNTIME_DATA_ROOT = temp_root / 'runtime-data'
                paths.SHARED_ROOT = temp_root / 'shared'
                shared_lorebook = paths.SHARED_ROOT / 'character' / 'lorebook.json'
                shared_lorebook.parent.mkdir(parents=True, exist_ok=True)
                shared_lorebook.write_text(json.dumps({'entries': ['leak']}), encoding='utf-8')

                token = paths.set_active_character_override('isolated-card')
                try:
                    resolved = paths.resolve_layered_source('character/lorebook.json')
                    self.assertNotEqual(resolved.resolve(strict=False), shared_lorebook.resolve(strict=False))
                    self.assertTrue(paths.is_character_override_active())
                finally:
                    paths.reset_active_character_override(token)

                # Without override the legacy fallback still works for back-compat.
                self.assertFalse(paths.is_character_override_active())
                resolved_default = paths.resolve_layered_source('character/lorebook.json')
                self.assertEqual(resolved_default.resolve(strict=False), shared_lorebook.resolve(strict=False))
            finally:
                paths.RUNTIME_DATA_ROOT = original_runtime_root
                paths.SHARED_ROOT = original_shared_root


if __name__ == '__main__':
    unittest.main()
