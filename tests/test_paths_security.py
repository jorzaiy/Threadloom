#!/usr/bin/env python3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'backend'))

import paths


class PathsSecurityTests(unittest.TestCase):
    def test_character_override_slugifies_path_separators(self):
        token = paths.set_active_character_override('../outside/card')
        try:
            self.assertEqual(paths.active_character_id(), 'outside-card')
            root = paths.character_root()
            root.relative_to(paths.user_root())
            self.assertNotIn('/', paths.active_character_id())
        finally:
            paths.reset_active_character_override(token)


if __name__ == '__main__':
    unittest.main()
