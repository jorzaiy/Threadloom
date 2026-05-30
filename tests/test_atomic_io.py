"""Unit tests for the atomic write primitives (backend/atomic_io.py).

These are durability-critical: the whole runtime relies on writes being
all-or-nothing so a crash mid-write can never leave a torn JSON file. The repo
root atomic_io.py is only a re-export shim; the real implementation lives in
backend/atomic_io.py, which is what we exercise here.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

from backend.atomic_io import atomic_write_bytes, atomic_write_json, atomic_write_text  # noqa: E402


class AtomicWriteTextTests(unittest.TestCase):
    def test_round_trip(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.txt'
            atomic_write_text(p, 'héllo\n世界')
            self.assertEqual(p.read_text(encoding='utf-8'), 'héllo\n世界')

    def test_creates_parent_dirs(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'a' / 'b' / 'c.txt'
            atomic_write_text(p, 'x')
            self.assertEqual(p.read_text(), 'x')

    def test_overwrites_existing(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.txt'
            atomic_write_text(p, 'old')
            atomic_write_text(p, 'new')
            self.assertEqual(p.read_text(), 'new')

    def test_no_tmp_file_left_after_success(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.txt'
            atomic_write_text(p, 'x')
            self.assertEqual([q.name for q in Path(d).glob('*.tmp')], [])

    def test_failure_preserves_original_and_cleans_tmp(self):
        # If the final os.replace fails, the original file must be untouched and
        # the temp file must not be left behind. This is the core atomicity
        # guarantee: a failed write never corrupts existing data.
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.txt'
            atomic_write_text(p, 'original')
            with mock.patch('backend.atomic_io.os.replace', side_effect=OSError('boom')):
                with self.assertRaises(OSError):
                    atomic_write_text(p, 'should-not-land')
            self.assertEqual(p.read_text(), 'original')
            self.assertEqual([q.name for q in Path(d).glob('*.tmp')], [])

    def test_mode_sets_permissions(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'secret.txt'
            atomic_write_text(p, 'x', mode=0o600)
            self.assertEqual(p.stat().st_mode & 0o777, 0o600)


class AtomicWriteBytesTests(unittest.TestCase):
    def test_round_trip_binary(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.bin'
            payload = bytes(range(256))
            atomic_write_bytes(p, payload)
            self.assertEqual(p.read_bytes(), payload)

    def test_failure_cleans_tmp_and_leaves_no_target(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.bin'
            with mock.patch('backend.atomic_io.os.replace', side_effect=OSError('boom')):
                with self.assertRaises(OSError):
                    atomic_write_bytes(p, b'data')
            self.assertFalse(p.exists())
            self.assertEqual([q.name for q in Path(d).glob('*.tmp')], [])


class AtomicWriteJsonTests(unittest.TestCase):
    def test_round_trip_with_trailing_newline(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.json'
            data = {'b': 2, 'a': [1, 2, 3]}
            atomic_write_json(p, data)
            raw = p.read_text(encoding='utf-8')
            self.assertTrue(raw.endswith('\n'))
            self.assertEqual(json.loads(raw), data)

    def test_preserves_unicode(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.json'
            atomic_write_json(p, {'name': '世界'})
            raw = p.read_text(encoding='utf-8')
            self.assertIn('世界', raw)  # ensure_ascii=False
            self.assertEqual(json.loads(raw), {'name': '世界'})

    def test_indent_applied(self):
        with TemporaryDirectory() as d:
            p = Path(d) / 'f.json'
            atomic_write_json(p, {'a': 1}, indent=2)
            self.assertIn('\n  "a"', p.read_text())


if __name__ == '__main__':
    unittest.main()
