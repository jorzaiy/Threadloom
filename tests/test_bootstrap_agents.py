"""Unit tests for the bootstrap-agent cluster (npc/object/clue).

These agents were previously untested. Each follows the same shape: heuristic
candidate extraction -> LLM classify/dedupe -> merge into a session registry.
The deterministic parts (normalize, merge, heuristic extraction, label/҂type
validation, name canonicalization) are pure and tested directly here; the
``ensure_*_registry`` orchestrators are covered with the LLM call mocked and the
session registry redirected to a temp dir.
"""
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))

import npc_bootstrap_agent as npc  # noqa: E402
import object_bootstrap_agent as obj  # noqa: E402
import clue_bootstrap_agent as clue  # noqa: E402


def _pairs(n):
    items = []
    for i in range(n):
        items.append({'role': 'user', 'content': f'u{i}'})
        items.append({'role': 'assistant', 'content': f'a{i}'})
    return items


# ── shared helpers (identical across the three agents) ───────────────────────

class SharedHelperTests(unittest.TestCase):
    def test_strip_code_fences_json(self):
        self.assertEqual(npc._strip_code_fences('```json\n{"a": 1}\n```'), '{"a": 1}')

    def test_strip_code_fences_plain(self):
        self.assertEqual(npc._strip_code_fences('```\nhello\n```'), 'hello')

    def test_strip_code_fences_noop(self):
        self.assertEqual(npc._strip_code_fences('  bare text '), 'bare text')

    def test_turn_pairs_pairs_user_then_assistant(self):
        items = [
            {'role': 'user', 'content': 'q1'},
            {'role': 'assistant', 'content': 'a1'},
            {'role': 'user', 'content': 'q2'},
            {'role': 'assistant', 'content': 'a2'},
        ]
        pairs = npc._turn_pairs(items)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[0][0]['content'], 'q1')
        self.assertEqual(pairs[0][1]['content'], 'a1')

    def test_turn_pairs_ignores_trailing_unpaired_user_and_junk(self):
        items = [
            'not-a-dict',
            {'role': 'assistant', 'content': 'orphan'},  # no preceding user
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': 'a'},
            {'role': 'user', 'content': 'dangling'},
        ]
        pairs = npc._turn_pairs(items)
        self.assertEqual(len(pairs), 1)


# ── npc_bootstrap_agent ──────────────────────────────────────────────────────

class NpcNormalizeTests(unittest.TestCase):
    def test_canonical_inserted_into_aliases_and_defaults_filled(self):
        out = npc._normalize_entities([{'canonical_name': '老王', 'aliases': ['王掌柜']}])
        self.assertEqual(len(out), 1)
        e = out[0]
        self.assertEqual(e['canonical_name'], '老王')
        self.assertEqual(e['aliases'][0], '老王')  # canonical prepended
        self.assertIn('王掌柜', e['aliases'])
        self.assertEqual(e['role_label'], '待确认')
        self.assertEqual(e['faction'], '待确认')
        self.assertEqual(e['stability'], 'low')

    def test_duplicate_canonical_dropped(self):
        out = npc._normalize_entities([
            {'canonical_name': '老王'},
            {'canonical_name': '老王'},
        ])
        self.assertEqual(len(out), 1)

    def test_non_dict_and_empty_canonical_dropped(self):
        out = npc._normalize_entities(['x', {}, {'canonical_name': '   '}])
        self.assertEqual(out, [])


class NpcMergeTests(unittest.TestCase):
    def test_merge_by_canonical_upgrades_fields(self):
        existing = [{'canonical_name': '老王', 'aliases': ['老王'], 'role_label': '待确认', 'faction': '待确认', 'stability': 'low'}]
        incoming = [{'canonical_name': '老王', 'aliases': ['王掌柜'], 'role_label': '掌柜', 'faction': '盐帮', 'stability': 'high'}]
        merged = npc._merge_registry_entities(existing, incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['role_label'], '掌柜')
        self.assertEqual(merged[0]['faction'], '盐帮')
        self.assertEqual(merged[0]['stability'], 'high')
        self.assertIn('王掌柜', merged[0]['aliases'])

    def test_merge_by_alias_overlap_collapses_to_one(self):
        existing = [{'canonical_name': '老王', 'aliases': ['老王', '王掌柜']}]
        incoming = [{'canonical_name': '王掌柜', 'aliases': ['王掌柜']}]
        merged = npc._merge_registry_entities(existing, incoming)
        self.assertEqual(len(merged), 1)  # '王掌柜' folded into '老王'

    def test_unrelated_entity_is_added(self):
        existing = [{'canonical_name': '老王', 'aliases': ['老王']}]
        incoming = [{'canonical_name': '李四', 'aliases': ['李四']}]
        merged = npc._merge_registry_entities(existing, incoming)
        self.assertEqual({m['canonical_name'] for m in merged}, {'老王', '李四'})


class NpcCanonicalizeTests(unittest.TestCase):
    def test_alias_resolves_to_canonical(self):
        registry = {'entities': [{'canonical_name': '老王', 'aliases': ['老王', '王掌柜']}]}
        self.assertEqual(npc.canonicalize_name('王掌柜', registry), '老王')

    def test_unknown_name_returns_itself(self):
        registry = {'entities': [{'canonical_name': '老王', 'aliases': ['老王']}]}
        self.assertEqual(npc.canonicalize_name('陌生人', registry), '陌生人')


class EnsureNpcRegistryTests(unittest.TestCase):
    def test_force_parses_llm_entities_and_advances_processed_pairs(self):
        reply = json.dumps({'entities': [
            {'canonical_name': '老王', 'aliases': ['王掌柜'], 'role_label': '掌柜', 'stability': 'high'},
        ]})
        with TemporaryDirectory() as d:
            with mock.patch.object(npc, 'session_paths', lambda sid: {'memory_dir': Path(d)}), \
                 mock.patch.object(npc, 'call_role_llm', return_value=(reply, {})):
                reg = npc.ensure_npc_registry('s1', _pairs(4), force=True)
        self.assertIn('老王', [e['canonical_name'] for e in reg['entities']])
        self.assertEqual(reg['processed_pairs'], 4)

    def test_skips_and_does_not_call_llm_when_too_few_pending(self):
        with TemporaryDirectory() as d:
            with mock.patch.object(npc, 'session_paths', lambda sid: {'memory_dir': Path(d)}), \
                 mock.patch.object(npc, 'call_role_llm') as m:
                reg = npc.ensure_npc_registry('s1', _pairs(2), force=False)
                m.assert_not_called()
        self.assertEqual(reg['entities'], [])

    def test_falls_back_to_heuristic_on_bad_llm_reply(self):
        # Malformed JSON -> exception path -> heuristic (which keeps the prior
        # entity list). Should not raise, and processed_pairs still advances.
        with TemporaryDirectory() as d:
            with mock.patch.object(npc, 'session_paths', lambda sid: {'memory_dir': Path(d)}), \
                 mock.patch.object(npc, 'call_role_llm', return_value=('not json', {})):
                reg = npc.ensure_npc_registry('s1', _pairs(4), force=True)
        self.assertEqual(reg['processed_pairs'], 4)
        self.assertEqual(reg['entities'], [])


# ── object_bootstrap_agent ───────────────────────────────────────────────────

class ObjectLabelValidationTests(unittest.TestCase):
    def test_known_object_labels_are_valid(self):
        for label in ('长剑', '令牌', '钥匙'):
            self.assertTrue(obj._is_valid_object_label(label), label)

    def test_non_object_nouns_rejected(self):
        for label in ('桌子', '小二', '门口'):
            self.assertFalse(obj._is_valid_object_label(label), label)

    def test_labels_with_function_words_rejected(self):
        self.assertFalse(obj._is_valid_object_label('拿来'))   # 来 is a junk char
        self.assertFalse(obj._is_valid_object_label('他的'))   # 的 is a junk char

    def test_length_bounds(self):
        self.assertFalse(obj._is_valid_object_label('刀'))            # too short
        self.assertFalse(obj._is_valid_object_label('一二三四五六七八九'))  # too long

    def test_directional_suffix_rejected(self):
        self.assertFalse(obj._is_valid_object_label('床旁边'))  # ends with 旁边


class ObjectHeuristicExtractTests(unittest.TestCase):
    def test_extracts_known_weapon_noun(self):
        window = [({'content': 'u'}, {'content': '他从腰间拔出一把长剑，寒光凛凛。'})]
        labels = [c['label'] for c in obj._heuristic_extract_objects(window)]
        self.assertIn('长剑', labels)

    def test_does_not_extract_furniture(self):
        window = [({'content': 'u'}, {'content': '他放下桌子，转身离开。'})]
        labels = [c['label'] for c in obj._heuristic_extract_objects(window)]
        self.assertNotIn('桌子', labels)


class ObjectNormalizeMergeTests(unittest.TestCase):
    def test_normalize_fills_defaults_and_dedupes(self):
        out = obj._normalize_objects([
            {'label': '长剑', 'holder': '老王', 'state': '手持'},
            {'label': '令牌'},          # holder/state default
            {'label': '长剑'},          # dup
        ])
        by_label = {o['label']: o for o in out}
        self.assertEqual(by_label['长剑']['holder'], '老王')
        self.assertEqual(by_label['长剑']['state'], '手持')
        self.assertEqual(by_label['令牌']['holder'], '未知')
        self.assertEqual(by_label['令牌']['state'], '收纳')
        self.assertEqual(len(out), 2)

    def test_merge_upgrades_holder_and_state(self):
        existing = [{'label': '长剑', 'holder': '未知', 'state': '收纳'}]
        incoming = [{'label': '长剑', 'holder': '老王', 'state': '手持'}]
        merged = obj._merge_objects(existing, incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['holder'], '老王')
        self.assertEqual(merged[0]['state'], '手持')


# ── clue_bootstrap_agent ─────────────────────────────────────────────────────

class ClueNormalizeTests(unittest.TestCase):
    def test_valid_type_and_confidence_preserved(self):
        out = clue._normalize_clues([
            {'summary': '盐帮暗中囤粮', 'type': 'hidden', 'confidence': 'high'},
        ])
        self.assertEqual(out[0]['type'], 'hidden')
        self.assertEqual(out[0]['confidence'], 'high')

    def test_invalid_type_and_confidence_defaulted(self):
        out = clue._normalize_clues([
            {'summary': '某条线索', 'type': 'nonsense', 'confidence': 'wat'},
        ])
        self.assertEqual(out[0]['type'], 'rumor')
        self.assertEqual(out[0]['confidence'], 'low')

    def test_dedupe_by_summary_prefix(self):
        # Dedup key is summary[:15]; these share an identical 15-char prefix
        # and only diverge afterwards, so the second is dropped.
        out = clue._normalize_clues([
            {'summary': '盐帮在城西暗中囤积粮草秘密调运准备起事'},
            {'summary': '盐帮在城西暗中囤积粮草秘密调运另有图谋'},
        ])
        self.assertEqual(len(out), 1)


class ClueHeuristicTests(unittest.TestCase):
    def test_rumor_sentence_becomes_candidate(self):
        window = [({'content': 'u'}, {'content': '听说官府正在暗中调查盐帮的私盐生意。'})]
        candidates = clue._heuristic_extract_clues(window)
        self.assertTrue(candidates)
        self.assertTrue(any('听说' in c['source_sentence'] for c in candidates))

    def test_plain_chatter_is_not_a_candidate(self):
        window = [({'content': 'u'}, {'content': '今天天气不错，我们去喝茶吧。'})]
        self.assertEqual(clue._heuristic_extract_clues(window), [])


class ClueMergeTests(unittest.TestCase):
    def test_existing_clue_confidence_upgraded(self):
        existing = [{'summary': '盐帮暗中囤粮', 'type': 'hidden', 'confidence': 'low'}]
        incoming = [{'summary': '盐帮暗中囤粮', 'type': 'hidden', 'confidence': 'high'}]
        merged = clue._merge_clues(existing, incoming)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['confidence'], 'high')

    def test_caps_at_twenty(self):
        existing = [{'summary': f'线索{i:02d}号内容描述', 'type': 'rumor', 'confidence': 'low'} for i in range(25)]
        merged = clue._merge_clues(existing, [])
        self.assertEqual(len(merged), 20)


if __name__ == '__main__':
    unittest.main()
