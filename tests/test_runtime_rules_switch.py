"""Narrator runtime-rules switch: grok-family narrators get runtime-rules-grok.md,
others keep the default; missing variant falls back."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'backend'))

from backend import context_builder as cb  # noqa: E402


class _Exists:
    def __init__(self, ok): self.ok = ok
    def exists(self): return self.ok


class RuntimeRulesSwitchTests(unittest.TestCase):
    def test_grok_narrator_gets_grok_variant(self):
        orig = cb.resolve_source
        cb.resolve_source = lambda p: _Exists(True)
        try:
            out = cb._runtime_rules_path_for_narrator(
                {'models': {'narrator': {'model': 'grok-4.3'}}}, 'prompts/runtime-rules.md')
        finally:
            cb.resolve_source = orig
        self.assertEqual(out, 'prompts/runtime-rules-grok.md')

    def test_grok_but_variant_missing_falls_back(self):
        orig = cb.resolve_source
        cb.resolve_source = lambda p: _Exists(False)
        try:
            out = cb._runtime_rules_path_for_narrator(
                {'models': {'narrator': {'model': 'grok-4.3'}}}, 'prompts/runtime-rules.md')
        finally:
            cb.resolve_source = orig
        self.assertEqual(out, 'prompts/runtime-rules.md')

    def test_non_grok_uses_default(self):
        out = cb._runtime_rules_path_for_narrator(
            {'models': {'narrator': {'model': 'mimo-v2.5-pro'}}}, 'prompts/runtime-rules.md')
        self.assertEqual(out, 'prompts/runtime-rules.md')

    def test_missing_cfg_uses_default(self):
        self.assertEqual(
            cb._runtime_rules_path_for_narrator({}, 'prompts/runtime-rules.md'),
            'prompts/runtime-rules.md')


if __name__ == '__main__':
    unittest.main()
