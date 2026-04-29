#!/usr/bin/env python3
import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == '__main__':
    unittest.main()
